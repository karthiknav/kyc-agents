# KYC Agents — Architecture

## System Overview

A multi-agent KYC (Know Your Customer) automation system built with **CrewAI** on **AWS Bedrock**, hosted as an **AWS AgentCore** Lambda. It screens customers through document verification, PEP/sanctions checks, and adverse media analysis — producing a final APPROVE or ESCALATE decision. All agent/tool activity is optionally traced in **Langfuse** via OpenTelemetry/OpenInference instrumentation.

---

## High-Level Flow

```
Client / Caller
      │
      ▼
┌─────────────────────────────────────────────┐
│         AWS AgentCore Lambda                │
│            kyc_app.py                       │
│                                             │
│  1. Validate payload (caseId)               │
│  2. Refresh MODEL from SSM (TTL 5 min)      │
│  3. Spawn background thread                 │
│  4. Return { status: "started" }            │
└──────────────────────┬──────────────────────┘
                       │ background thread
                       ▼
             ┌─────────────────┐
             │  Langfuse Span  │  (if LANGFUSE_ENABLED=1)
             │ "crewai-index-  │
             │    trace"       │
             └────────┬────────┘
                      │
                      ▼
          KYCCrew.crew().kickoff()
          (CrewAI sequential process)
```

---

## Agent Pipeline (Sequential)

```
┌──────────────────────────────────────────────────────────────────┐
│  Task 1: Document Processing                                     │
│  Agent: document_processing_agent                                │
│                                                                  │
│  Tools: get_case_details → get_case_files → extract_document_   │
│         text (Textract) → verify_identity_document (BRP) →      │
│         compare_identity_documents (LLM 3-way compare)          │
│                                                                  │
│  Guardrail: run_id nonce proves full pipeline ran                │
│  Callback → DynamoDB stages.documentProcessing + S3 report.md   │
│  Output: MATCH | PARTIAL_MATCH | MISMATCH                        │
└────────────────────────────┬─────────────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│  Task 2: Risk List Screening                                     │
│  Agent: risk_list_screening_agent                                │
│                                                                  │
│  Tools: get_case_details → risk_list_screening (OpenSanctions)   │
│                                                                  │
│  Callback → DynamoDB stages.screening.riskListScreening + S3    │
│  Output: CLEAR | HIT | ERROR + pepStatus + sanctionsStatus       │
└────────────────────────────┬─────────────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│  Task 3: Adverse Media Screening                                 │
│  Agent: adverse_media_agent                                      │
│                                                                  │
│  Tools: get_case_details → search_internet (DuckDuckGo) →       │
│         produce_adverse_media_analysis (LLM)                     │
│                                                                  │
│  Callback → DynamoDB stages.screening.adverseMedia + S3 reports │
│  Output: OK | NOK | PENDING_REVIEW + summary                     │
└────────────────────────────┬─────────────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│  Task 4: Orchestration (context: outputs of Tasks 1+2+3)         │
│  Agent: orchestrator_agent                                       │
│                                                                  │
│  Tools: get_case_details, escalate_to_human                      │
│                                                                  │
│  Decision rule:                                                  │
│    MATCH + CLEAR + OK  →  APPROVED                               │
│    anything else       →  ESCALATED → SQS → human review        │
│                                                                  │
│  Callback → DynamoDB case.status (final)                         │
└──────────────────────────────────────────────────────────────────┘
```

---

## AWS Infrastructure

```
                        ┌──────────────────────┐
                        │   SSM Parameter Store │
                        │  /kyc-agent/model-id  │
                        │  (refreshed every 5m) │
                        └──────────┬───────────┘
                                   │ MODEL env var
                    ┌──────────────▼─────────────────┐
                    │       AWS Bedrock               │
                    │  Claude / configured model      │
                    │  (all 4 agent LLM calls)        │
                    └────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│                       AgentCore Lambda                           │
│                         kyc_app.py                               │
└──────┬──────────────┬─────────────────┬──────────────────────────┘
       │              │                 │
       ▼              ▼                 ▼
  DynamoDB          S3 Bucket      SQS Queue
  KYC_CASES_TABLE   KYC_RESULTS_   KYC_HUMAN_REVIEW_
  (case data,       BUCKET         QUEUE_URL
   stages,          (markdown +    (escalation
   status)          JSON reports)   notifications)
       │
       ▼
  AWS Textract
  (OCR: images sync,
   PDFs async polling)
```

---

## External Integrations

| Service | Env Var | Used By |
|---------|---------|---------|
| Dutch BRP Registry | `BRP_API_URL` | Document Processing Agent |
| OpenSanctions PEP/Sanctions API | `PEP_API_URL` | Risk List Screening Agent |
| DuckDuckGo Search | (library) | Adverse Media Agent |

---

## Langfuse Observability

Enabled via `LANGFUSE_ENABLED=1`. Uses **OpenTelemetry** as the transport layer with **OpenInference** instrumentation adapters.

```
┌─────────────────────────────────────────────────────────────────┐
│                    Langfuse Trace                                │
│                                                                  │
│  Span: "crewai-index-trace"  (kyc_app.py)                       │
│    │                                                             │
│    ├── CrewAI spans  (openinference-instrumentation-crewai)      │
│    │     ├── Agent runs (task 1–4)                               │
│    │     └── Tool calls via patched CrewStructuredTool.invoke    │
│    │           (langfuse_crewai_patches.py)                      │
│    │                                                             │
│    ├── Bedrock LLM spans (openinference-instrumentation-bedrock) │
│    │     └── Converse API calls for each agent step              │
│    │                                                             │
│    └── Textract spans  (opentelemetry-instrumentation-botocore)  │
│          └── start_document_text_detection calls                 │
│                                                                  │
│  Suppressed: raw HTTP spans (requests, urllib3, httpx)           │
└─────────────────────────────────────────────────────────────────┘
                        │
                        ▼
              Langfuse Server
           (LANGFUSE_BASE_URL)
```

### Instrumentation Stack

| Layer | Library | What it captures |
|-------|---------|-----------------|
| CrewAI agents & tasks | `openinference-instrumentation-crewai` | Agent reasoning, task lifecycle |
| Tool invocations | `langfuse_crewai_patches.py` (wrapt patch) | `CrewStructuredTool.invoke` — missed by OpenInference |
| Bedrock LLM calls | `openinference-instrumentation-bedrock` | Converse API, token counts |
| Textract calls | `opentelemetry-instrumentation-botocore` | Async document detection spans |
| HTTP noise | uninstrumented | Suppressed to keep traces clean |

### Why the wrapt patch?

OpenInference instruments `BaseTool.run`, but CrewAI bypasses it — tools are executed via `CrewStructuredTool.invoke → _run` directly. The patch in [crew/langfuse_crewai_patches.py](crew/langfuse_crewai_patches.py) wraps `CrewStructuredTool.invoke` with a Langfuse `tool` observation so every tool call appears in the trace.

---

## Monkey-Patches (Bedrock + CrewAI Compatibility)

Applied at startup in [crew/crew.py](crew/crew.py) before any agent is constructed:

| Patch File | Problem Solved |
|-----------|---------------|
| [bedrock_stop_sequences_patch.py](crew/bedrock_stop_sequences_patch.py) | Bedrock Converse rejects `stopSequences` — strips it from all requests |
| [bedrock_tool_args_patch.py](crew/bedrock_tool_args_patch.py) | CrewAI reads `function.arguments` (OpenAI style); Bedrock uses `input` — patches `parse_tool_call_args` |
| [crewai_tool_observation_patch.py](crew/crewai_tool_observation_patch.py) | CrewAI re-appends full tool list every 3rd call, ballooning context — disables `_should_remember_format()` |
| [langfuse_crewai_patches.py](crew/langfuse_crewai_patches.py) | Missing Langfuse coverage for tool calls (see above) |

All patches are idempotent (guarded by a `_patched` flag).

---

## Decision Logic

```
Document Result   Risk List Result   Adverse Media   →  Final Decision
─────────────────────────────────────────────────────────────────────
MATCH             CLEAR              OK              →  APPROVED
                                                        (DynamoDB status=APPROVED)

anything else     anything           anything        →  ESCALATED
                                                        (DynamoDB status=PENDING_HUMAN_REVIEW)
                                                        (SQS → human review queue)
```

---

## Data Persistence Per Stage

Each task callback writes immediately so partial results survive later failures:

```
Task 1 callback → DynamoDB stages.documentProcessing
                  S3 cases/{caseId}/document-processing-report.md

Task 2 callback → DynamoDB stages.screening.riskListScreening
                  S3 cases/{caseId}/risk-list-report.json

Task 3 callback → DynamoDB stages.screening.adverseMedia
                  S3 cases/{caseId}/adverse-media-report.json
                  S3 cases/{caseId}/adverse-media-report.md

Task 4 callback → DynamoDB case.status  (APPROVED | PENDING_HUMAN_REVIEW)
```

---

## Model Refresh Strategy

```
Cold start
    └── ensure_model_env_from_ssm(force=True)
            └── SSM /kyc-agent/model-id → os.environ['MODEL']

Each invocation
    └── ensure_model_env_from_ssm(max_age_seconds=300)
            └── skip if MODEL set and < 5 min old
            └── else refresh from SSM

KYCCrew.get_llm()
    └── reads os.environ['MODEL'] at runtime (not import time)
    └── allows model change without Lambda redeployment
```
