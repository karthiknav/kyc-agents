# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

KYC (Know Your Customer) agentic AI system built on **CrewAI** + **AWS Bedrock AgentCore**. A multi-agent crew processes KYC cases through identity verification, income/source-of-funds verification, risk/sanctions screening, adverse media checks, and a final orchestrator decision applying Dutch Wwft (Anti-Money Laundering Act) business rules. The system runs as a long-lived AgentCore runtime that receives case payloads via SQS.

## Architecture

**Agent crew** (`crew/`): Five sequential CrewAI agents defined in `crew.py`, configured via YAML in `crew/config/`:
1. **Identity Verification Agent** — fetches case from DynamoDB, extracts text via Textract, verifies identity documents against Dutch BRP government registry, compares identity fields across DB/OCR/government data
2. **Income Verification Agent** — extracts income documents via Textract, cross-references with UWV Polisadministratie (employment registry) and KVK (business registry), applies Wwft source-of-funds rules via LLM analysis. Can request additional documents if income proof is insufficient
3. **Risk List Screening Agent** — runs PEP/sanctions API checks (OpenSanctions format)
4. **Adverse Media Agent** — web search (DuckDuckGo) + LLM analysis for adverse media
5. **Orchestrator Agent** — applies Wwft business rules, computes risk classification (LOW/MEDIUM/HIGH) and risk score (0-100), makes final APPROVE / ADDITIONAL_DOCUMENTS_REQUIRED / ESCALATE decision

**Entry point** (`crew/kyc_app.py`): BedrockAgentCoreApp that receives `{caseId}` payloads, refreshes the LLM model ID from SSM Parameter Store (`/kyc-agent/model-id`), and kicks off the crew in a background thread. Langfuse/OpenTelemetry tracing is optional (`LANGFUSE_ENABLED=1`).

**Backend API** (`backend/`): FastAPI app serving the frontend. Handles KYC submission (S3 upload + DynamoDB + SQS), case listing, status updates, additional document uploads, and analyst-triggered re-processing. Deployed as Lambda via Mangum or run locally with uvicorn.

**Frontend** (`frontend/`): Vite + React + TypeScript UI for uploading KYC documents and viewing case status/decisions. Polls `GET /submission/{userId}` every 5 seconds. Supports additional document upload when requested by the system.

**Mock service** (`mock-service/`): Express/TypeScript service simulating 4 external APIs via JSON definitions in `mocks/`:
- BRP Personen (identity verification) — Dutch civil registry
- PEP/Sanctions Match (OpenSanctions format) — PEP and sanctions screening
- UWV Polisadministratie (employment/income) — Dutch employment insurance registry
- KVK Basisprofiel (business registration) — Dutch Chamber of Commerce

Uses better-sqlite3 for persistence, faker.js for response generation. Deployed to Elastic Beanstalk.

**Lambda processor** (`lambda/kyc-processor.py`): SQS-triggered Lambda that invokes the AgentCore runtime.

**Bedrock patches**: The crew applies monkey-patches at import time to fix CrewAI/Bedrock integration issues:
- `bedrock_tool_args_patch.py` — fixes tool-call argument parsing (input vs arguments)
- `bedrock_stop_sequences_patch.py` — fixes stop sequence handling
- `crewai_tool_observation_patch.py` — slims down tool observation context (disable with `KYC_CREWAI_TOOL_FORMAT_REMINDERS=1`)

## DynamoDB Case Schema (stages)

```
stages:
  identityVerification:   result (MATCH/PARTIAL_MATCH/MISMATCH), summary, discrepancies, governmentVerificationSummary
  incomeVerification:     result (VERIFIED/INSUFFICIENT/SUSPICIOUS/UNREADABLE), incomeSource, monthlyIncomeEur, riskIndicators, additionalDocumentsNeeded
  screening:
    riskListScreening:    result (CLEAR/HIT/ERROR), pepStatus, sanctionsStatus
    adverseMedia:         result (OK/NOK/PENDING_REVIEW), searchQueries, summary
  orchestrator:           status, decision, reason, risk_classification (LOW/MEDIUM/HIGH), risk_score (0-100), additional_documents_needed
```

Case-level status values: `INITIATED`, `PROCESSING`, `APPROVED`, `PENDING_HUMAN_REVIEW`, `ADDITIONAL_DOCUMENTS_REQUESTED`, `REJECTED`

## Common Commands

### Agent (CrewAI) — `crew/`
```bash
cd crew
uv venv --python 3.13 && source .venv/bin/activate
uv pip install -r requirements.txt
python -m crew.kyc_app          # run AgentCore runtime locally
```

### Backend API — `backend/`
```bash
cd backend
uv venv --python 3.13 && source .venv/bin/activate
uv pip install -r requirements.txt
python -m uvicorn main:app --reload --port 8000
```

### Frontend — `frontend/`
```bash
cd frontend
npm install
npm run dev                      # default calls http://localhost:8000
VITE_API_BASE_URL=https://... npm run dev   # point to deployed API
npm run build                    # production build
npm run lint                     # ESLint
```

### Mock Service — `mock-service/`
```bash
cd mock-service
npm install
npm run dev                      # tsx watch mode (port 9000)
npm run build && npm start       # compiled JS
```

### Test agent invocation (against deployed AgentCore)
```bash
python test_agent_invocation.py  # invokes via bedrock-agentcore boto3 client
```

### Publish test case to DynamoDB + SQS
```bash
cd utils && python kyc_publisher.py
```

### Deploy
```bash
cd scripts && chmod +x *.sh
./deploy-base.sh                 # VPC, storage, IAM
./deploy_mock_service.sh         # Elastic Beanstalk mock APIs
./deploy.sh                      # agent runtime, lambdas, API, UI
LANGFUSE_ENABLED=1 ./deploy.sh   # with Langfuse/OTEL
```

## Evaluation Framework

### Online evals (automatic, every trace)
Deterministic scoring runs in each callback — schema validation, risk score consistency, decision-rule alignment. Scores submitted to Langfuse. Zero LLM cost. See `crew/evals/online.py`.

### Offline evals (golden datasets)
```bash
# Seed golden datasets into Langfuse
python -m crew.evals.seed_datasets --all

# Run offline evaluation with DeepEval + RAGAS
python -m crew.evals.offline --dataset all --threshold 0.85

# Run specific dataset
python -m crew.evals.offline --dataset kyc-identity-verification

# List available datasets
python -m crew.evals.offline --list-datasets
```

Frameworks: DeepEval (ToolCorrectness, TaskCompletion, custom KYCCompliance/RiskDetection) + RAGAS (ToolCallAccuracy, AgentGoalAccuracy). Judge model configurable via `EVAL_JUDGE_MODEL` env var.

## Key Environment Variables

- `MODEL` — Bedrock model ID (auto-refreshed from SSM param `/kyc-agent/model-id`); prefix `bedrock/` is added if missing
- `OPENAI_API_KEY` — used by screening analysis LLM
- `TAVILY_API_KEY` — required for adverse media web search
- `KYC_CASES_TABLE` — DynamoDB table name (default `kyc-cases` in crew, `KycCases` in backend)
- `KYC_RESULTS_BUCKET` — S3 bucket for reports
- `KYC_DOCUMENTS_BUCKET` — S3 bucket for uploaded documents
- `MOCK_SERVICE_URL` — base URL for the mock service (default `http://localhost:9000`)
- `LANGFUSE_ENABLED` — set to `1` to enable Langfuse tracing
- `KYC_BEDROCK_EMPTY_RESPONSE_RETRY` — set to `0` to disable empty-response retry (on by default)
- `MODEL_SSM_REFRESH_SECONDS` — TTL for SSM model ID refresh (default 300)
- `EVAL_JUDGE_MODEL` — Bedrock model ID for offline eval LLM-as-judge (default same as `MODEL`)

## Component Boundaries

Each component (`crew/`, `backend/`, `lambda/`, `utils/`) has its own `requirements.txt` and should use a **separate virtual environment** to avoid dependency conflicts. Python 3.10+ required; 3.13 recommended. Use `uv` for venv/package management.

## Agent Tool Pattern

All crew tools are in `crew/tools/` and follow the CrewAI `BaseTool` pattern with Pydantic input schemas. LLM-based tools (compare_identity, analyze_income, adverse_media_analysis) call Bedrock Converse API directly via boto3. API-calling tools (verify_identity, verify_income_uwv, verify_business_kvk, risk_list_screening) call the mock service.

Task callbacks write results back to DynamoDB/S3:
- `update_document_result.py` — writes `stages.identityVerification`
- `update_income_result.py` — writes `stages.incomeVerification`
- `update_case.py` — writes `stages.screening.riskListScreening` and `stages.screening.adverseMedia`
- `update_orchestrator_result.py` — writes `stages.orchestrator` + top-level `status`

## Model Resolution

The LLM model is resolved at **runtime** (not import time) via `_resolve_bedrock_model_from_env()` in `crew.py`. This is intentional — AgentCore runtimes are long-lived and the model can change between invocations via SSM.

## Business Rules Reference

See `docs/kyc-business-rules-and-references.md` for comprehensive documentation of Dutch Wwft requirements, mock API schema sources (with links to real Dutch government APIs), risk classification logic, income document types, and additional document request triggers.

## Test Personas (seeded in mock service)

| Person | BSN | Scenario |
|--------|-----|----------|
| Jan de Vries | 123456789 | Clean approval — all checks pass, LOW risk |
| Maria Bakker | 987654321 | Document mismatch + no income records — triggers additional docs |
| Ahmed Al-Rashid | 555666777 | Sanctions hit + suspicious income (EUR 250K temp) — HIGH risk |
| Willem van den Berg | 111222333 | PEP (former minister) + dual income (govt + consulting BV) — MEDIUM risk |
