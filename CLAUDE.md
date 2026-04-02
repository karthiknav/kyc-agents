# KYC Agents — Codebase Guide

## Overview

This repo contains a **multi-agent KYC (Know Your Customer) automation system** built with [CrewAI](https://docs.crewai.com/) running on **AWS Bedrock**. It automates compliance screening for customer onboarding: document verification, PEP/sanctions watchlist checks, and adverse media screening — culminating in an APPROVE or ESCALATE decision.

The main agent implementation lives in [`crew/`](crew/).

---

## Architecture

### Entry Point

[`crew/kyc_app.py`](crew/kyc_app.py) is an **AWS AgentCore Lambda handler**. It:
- Receives an invocation payload with a `caseId`
- Spawns a background thread to run the crew (non-blocking response)
- Refreshes the LLM model ID from SSM Parameter Store every 5 minutes (allows model changes without redeployment)
- Optionally enables Langfuse observability tracing

### Agent Pipeline

The crew executes **four agents sequentially**:

```
Lambda (kyc_app.py)
        ↓
[1] Document Processing Agent
        ↓ callback → DynamoDB + S3
[2] Risk List Screening Agent
        ↓ callback → DynamoDB + S3
[3] Adverse Media Agent
        ↓ callback → DynamoDB + S3
[4] Orchestrator Agent
        ↓ callback → DynamoDB (final case status)
```

Each task has a **callback that persists results immediately** — so if a later stage fails, earlier results are preserved.

---

## Agents & Tasks

Defined in [`crew/config/agents.yaml`](crew/config/agents.yaml) and [`crew/config/tasks.yaml`](crew/config/tasks.yaml), wired together in [`crew/crew.py`](crew/crew.py).

### 1. Document Processing Agent
- **Task**: Fetch identity data from DynamoDB, run OCR on uploaded documents via Textract, verify against the Dutch BRP government registry, then LLM-compare all three sources.
- **Output**: `comparison_result` — `MATCH` | `PARTIAL_MATCH` | `MISMATCH`, plus discrepancies list
- **Callback**: [`crew/update_document_result.py`](crew/update_document_result.py) — writes DynamoDB `stages.documentProcessing`, uploads markdown report to S3

### 2. Risk List Screening Agent
- **Task**: Query an OpenSanctions-compatible PEP/sanctions API with the person's name, DOB, nationality.
- **Output**: `result` — `CLEAR` | `HIT` | `ERROR`, plus `pepStatus` and `sanctionsStatus`
- **Callback**: [`crew/update_case.py`](crew/update_case.py) `update_risk_list_screening_result()` — writes DynamoDB `stages.screening.riskListScreening`, uploads raw JSON to S3

### 3. Adverse Media Agent
- **Task**: DuckDuckGo web search for negative news/fraud/crime, then LLM analysis of results.
- **Output**: `result` — `OK` | `NOK` | `PENDING_REVIEW`, plus summary and search queries used
- **Callback**: [`crew/update_case.py`](crew/update_case.py) `update_adverse_media_result()` — writes DynamoDB `stages.screening.adverseMedia`, uploads JSON + markdown report to S3

### 4. Orchestrator Agent
- **Task**: Synthesize all three results and make a final decision. Has access to full context from all prior tasks.
- **Output**: `action` — `APPROVED` | `ESCALATED`, plus `reason[]` and `recommendation_summary`
- **Callback**: [`crew/update_orchestrator_result.py`](crew/update_orchestrator_result.py) — writes final `status` field to DynamoDB case

---

## Business Logic — Decision Rules

The orchestrator uses a **conservative, escalation-biased** policy:

| Document | Risk List | Adverse Media | Decision |
|----------|-----------|---------------|----------|
| MATCH | CLEAR | OK | **APPROVED** |
| anything else | anything | anything | **ESCALATED** |

When escalated:
1. Case status → `PENDING_HUMAN_REVIEW`
2. SQS notification sent to human review queue (`KYC_HUMAN_REVIEW_QUEUE_URL`)
3. Compliance officer reviews S3 reports and decides manually

---

## Tools

All tools live in [`crew/tools/`](crew/tools/).

| Tool | File | Description |
|------|------|-------------|
| `get_case_details` | `dynamodb_tool.py` | Fetch case identity from DynamoDB by caseId |
| `get_case_files` | `get_case_files_tool.py` | List S3 document references for the case |
| `extract_document_text` | `textract_tool.py` | OCR via AWS Textract (sync for images, async polling for PDFs) |
| `verify_identity_document` | `verify_identity_tool.py` | Dutch BRP government registry lookup |
| `compare_identity_documents` | `compare_identity_tool.py` | LLM-driven 3-way comparison (DB vs OCR vs govt) |
| `risk_list_screening` | `risk_list_screening_tool.py` | OpenSanctions-compatible PEP/sanctions API |
| `search_internet` | `search_tools.py` | DuckDuckGo web search (configurable via `SEARCH_MAX_RESULTS`) |
| `produce_adverse_media_analysis` | `adverse_media_analysis_tool.py` | LLM analysis of search results for adverse content |
| `escalate_to_human` | `escalate_human_tool.py` | Updates DynamoDB status + sends SQS notification |
| `get_case_stages` | `get_case_stages_tool.py` | Read processing stages from case |

**Unused/legacy tools** (present but not wired into current crew): `pep_screening`, `aggregate_results_tool`, `fanout_tool`

---

## External Integrations

### AWS Services
| Service | Usage |
|---------|-------|
| **DynamoDB** (`KYC_CASES_TABLE`) | Stores all case data with nested `stages` map |
| **S3** (`KYC_RESULTS_BUCKET`) | Stores markdown + JSON reports under `cases/{caseId}/` |
| **Textract** | OCR on uploaded identity documents |
| **SSM Parameter Store** (`/kyc-agent/model-id`) | LLM model ID, refreshed every 5 min |
| **SQS** (`KYC_HUMAN_REVIEW_QUEUE_URL`) | Escalation notifications to human review queue |
| **Bedrock** | Hosts the Claude LLM used by all agents |

### External APIs
| API | Env Var | Purpose |
|-----|---------|---------|
| Dutch BRP | `BRP_API_URL` | Government identity registry verification |
| PEP/Sanctions | `PEP_API_URL` | OpenSanctions-compatible watchlist screening |
| DuckDuckGo | (library) | Adverse media web search |

### Observability
- **Langfuse** — optional tracing of all agent/tool calls
- Enable with `LANGFUSE_ENABLED=1`
- Config: `LANGFUSE_BASE_URL`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`

---

## Monkey-Patches (CrewAI + Bedrock Integration Fixes)

Four patch files apply fixes at startup in [`crew/crew.py`](crew/crew.py):

| File | Problem Fixed |
|------|---------------|
| [`bedrock_stop_sequences_patch.py`](crew/bedrock_stop_sequences_patch.py) | Bedrock rejects `stopSequences` param — strips it from all converse requests |
| [`bedrock_tool_args_patch.py`](crew/bedrock_tool_args_patch.py) | CrewAI parses tool args from OpenAI-style `function.arguments`, but Bedrock uses `input` — patches `parse_tool_call_args` |
| [`crewai_tool_observation_patch.py`](crew/crewai_tool_observation_patch.py) | CrewAI appends full tool list every 3rd call, ballooning context — disables `_should_remember_format()` (re-enable with `KYC_CREWAI_TOOL_FORMAT_REMINDERS=1`) |
| [`langfuse_crewai_patches.py`](crew/langfuse_crewai_patches.py) | OpenInference misses `CrewStructuredTool.invoke()` — wraps it with Langfuse observations via `wrapt` |

All patches include idempotency guards to prevent double-patching.

---

## Environment Variables

```bash
# AWS
KYC_CASES_TABLE=           # DynamoDB table name
KYC_RESULTS_BUCKET=        # S3 bucket for reports
AWS_REGION=                # AWS region (default: us-east-1)

# LLM
MODEL=                     # Bedrock model ID (fallback if SSM unavailable)
MODEL_SSM_REFRESH_SECONDS= # SSM refresh interval (default: 300)

# External APIs
BRP_API_URL=               # Dutch BRP government identity API
PEP_API_URL=               # PEP/sanctions screening API
MOCK_SERVICE_URL=          # Base URL for mock services (dev/test)

# Queues
KYC_HUMAN_REVIEW_QUEUE_URL= # SQS queue for human escalation notifications
KYC_QUEUE_URL=              # SQS queue for parallel subagent fanout (unused)

# Observability
LANGFUSE_ENABLED=          # Set to 1 or "true" to enable
LANGFUSE_BASE_URL=
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
CREWAI_TRACING_ENABLED=    # Set to "true" for CrewAI internal tracing

# Tuning
SEARCH_MAX_RESULTS=        # Max DuckDuckGo results (default: 5)
KYC_CREWAI_TOOL_FORMAT_REMINDERS= # Set to 1 to re-enable tool list injection
```

---

## DynamoDB Schema (case document)

```
CaseId (PK)
identity: { firstName, lastName, dateOfBirth, nationality, ... }
files: [{ s3Bucket, s3Key, documentType }]
status: PENDING | APPROVED | PENDING_HUMAN_REVIEW
stages:
  documentProcessing:
    result: MATCH | PARTIAL_MATCH | MISMATCH
    summary: str
    discrepancies: [str]
    governmentVerificationSummary: str
    reportS3: { bucket, key }
    updatedAt: ISO8601
  screening:
    riskListScreening:
      result: CLEAR | HIT | ERROR
      pepStatus: str
      sanctionsStatus: str
      datasetsMatched: [str]
      updatedAt: ISO8601
    adverseMedia:
      result: OK | NOK | PENDING_REVIEW
      summary: str
      searchQueries: [str]
      updatedAt: ISO8601
  orchestrator:
    status: APPROVED | ESCALATED
    decision: str
    reason: [str]
    recommendation_summary: str
    decidedAt: ISO8601
```

---

## S3 Report Layout

```
cases/{caseId}/
  document-processing-report.md   ← human-readable identity comparison
  risk-list-report.json            ← raw PEP/sanctions API response
  adverse-media-report.json        ← structured adverse media result
  adverse-media-report.md          ← human-readable adverse media summary
```

---

## Key Design Decisions

- **Sequential pipeline**: Tasks run in order so each agent can leverage prior context. Infrastructure for parallel subagents exists (`fanout_tool`) but is not used.
- **Immediate persistence via callbacks**: Each task writes to DynamoDB/S3 before the next task starts — partial results survive orchestrator failures.
- **LLM at zero temperature** for comparisons and analysis tools — deterministic, auditable outputs.
- **Patch-over-fork** for upstream fixes — keeps CrewAI upgradeable without maintaining a fork.
- **SSM-backed model ID** — allows switching between Claude model versions without redeployment.
