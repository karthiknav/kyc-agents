# KYC Agents — Codebase Guide

## Overview

This repo contains a **multi-agent KYC (Know Your Customer) automation system** built with [CrewAI](https://docs.crewai.com/) running on **AWS Bedrock**. It automates compliance screening for customer onboarding: document verification, PEP/sanctions watchlist checks, and adverse media screening — culminating in an APPROVE or ESCALATE decision.

The main agent implementation lives in [`crew/`](crew/).

---

## Architecture

### Entry Point

[`crew/kyc_app.py`](crew/kyc_app.py) is an **AWS AgentCore Lambda handler**. It:
- Receives an invocation payload with a `caseId` (and optional `analystComments`)
- Spawns a background thread to run the crew (non-blocking response — handler returns `{"status": "started"}` immediately)
- Refreshes the LLM model ID from SSM Parameter Store every 5 minutes (allows model changes without redeployment)
- Optionally enables Langfuse observability tracing

### Two Crews

There are **two separate CrewAI crew classes** in [`crew/crew.py`](crew/crew.py):

| Crew | Class | Trigger | Model |
|------|-------|---------|-------|
| **KYCCrew** | Main 4-agent screening pipeline | `payload.caseId` (no `analystComments`) | `bedrock/openai.gpt-oss-120b-1:0` (SSM-overridable) |
| **OverrideValidationCrew** | Single-agent analyst override review | `payload.analystComments` present | `bedrock/us.anthropic.claude-sonnet-4-6` (hardcoded) |

### KYC Screening Pipeline

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

### Retry Behaviour

On **any** failure (transient error or guardrail exhaustion), the handler restarts the **entire crew from task 1** — there is no incremental recovery. Controlled by `KYC_CREW_MAX_RETRIES` (default 7). The OverrideValidationCrew has no retry; it runs once.

### Override Validation Flow

When `analystComments` is present in the payload, `OverrideValidationCrew` runs instead:
- Agent: `override_validation_agent` — configs in `crew/config/override_agents.yaml`
- Task: `override_validation_task` — configs in `crew/config/override_tasks.yaml`
- Tools: `get_case_details`, `get_case_stage_details`, `analyze_override`
- Callback: [`crew/update_override_result.py`](crew/update_override_result.py)
- No guardrails, no retry

---

## Agents & Tasks

Defined in [`crew/config/kyc_agents.yaml`](crew/config/kyc_agents.yaml) and [`crew/config/kyc_tasks.yaml`](crew/config/kyc_tasks.yaml), wired together in [`crew/crew.py`](crew/crew.py).

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

#### Active tools (wired into a crew)

| Tool name | File | Used by | Description |
|-----------|------|---------|-------------|
| `get_case_details` | `dynamodb_tool.py` + `get_case_details_tool.py` | KYCCrew, OverrideValidationCrew | Fetch case identity from DynamoDB by caseId |
| `get_case_files` | `get_case_files_tool.py` | KYCCrew (doc agent) | List S3 document references for the case |
| `extract_document_text` | `textract_tool.py` | KYCCrew (doc agent) | OCR via AWS Textract (sync for images, async polling for PDFs) |
| `verify_identity_document` | `verify_identity_tool.py` | KYCCrew (doc agent) | Dutch BRP government registry lookup |
| `compare_identity_documents` | `compare_identity_tool.py` | KYCCrew (doc agent) | LLM-driven 3-way comparison (DB vs OCR vs govt) |
| `risk_list_screening` | `risk_list_screening_tool.py` | KYCCrew (screening agent) | OpenSanctions-compatible PEP/sanctions API |
| `search_internet` | `search_tools.py` | KYCCrew (media agent) | DuckDuckGo web search (configurable via `SEARCH_MAX_RESULTS`) |
| `produce_adverse_media_analysis` | `adverse_media_analysis_tool.py` | KYCCrew (media agent) | LLM analysis of search results for adverse content |
| `escalate_to_human` | `escalate_human_tool.py` | KYCCrew (orchestrator) | Updates DynamoDB status + sends SQS notification |
| `get_case_stages` | `get_case_stages_tool.py` | KYCCrew (orchestrator) | Read all processing stages from case |
| `get_case_stage_details` | `get_case_stage_details_tool.py` | OverrideValidationCrew | Fetch a specific stage's data |
| `analyze_override` | `analyze_override_tool.py` | OverrideValidationCrew | Validate analyst override decision |
| `score_case_risk` | `risk_scoring_tool.py` | KYCCrew (orchestrator, optional) | ML risk tier prediction via SageMaker endpoint |

#### Unused/legacy tools (present but not wired into any crew)
`pep_screening_tool.py`, `aggregate_results_tool.py`, `fanout_tool.py`, `screening_analysis_tool.py`, `search_person_tool.py`

#### Tool implementation pattern

Every tool follows the same structure:

```python
from crewai.tools import BaseTool
from pydantic import BaseModel, Field
from typing import Type

class MyToolInput(BaseModel):
    case_id: str = Field(description="...")

class MyTool(BaseTool):
    name: str = "tool_name"
    description: str = "..."
    args_schema: Type[MyToolInput] = MyToolInput

    def _run(self, case_id: str) -> str:
        return json.dumps({...})   # always return JSON string
```

Tools that need guardrail verification also store a nonce UUID in thread-local storage (see Guardrail Nonce Pattern below).

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

Six patch files apply fixes at startup in [`crew/crew.py`](crew/crew.py):

| File | Problem Fixed |
|------|---------------|
| [`bedrock_stop_sequences_patch.py`](crew/bedrock_stop_sequences_patch.py) | Bedrock rejects `stopSequences` param — strips it from all converse requests |
| [`bedrock_tool_args_patch.py`](crew/bedrock_tool_args_patch.py) | CrewAI parses tool args from OpenAI-style `function.arguments`, but Bedrock uses `input` — patches `parse_tool_call_args` |
| [`bedrock_assistant_prefill_patch.py`](crew/bedrock_assistant_prefill_patch.py) | Fixes assistant message prefill behaviour for Bedrock converse API |
| [`crewai_tool_observation_patch.py`](crew/crewai_tool_observation_patch.py) | CrewAI appends full tool list every 3rd call, ballooning context — disables `_should_remember_format()` (re-enable with `KYC_CREWAI_TOOL_FORMAT_REMINDERS=1`) |
| [`crewai_guardrail_scratchpad_patch.py`](crew/crewai_guardrail_scratchpad_patch.py) | Fixes guardrail scratchpad handling so retry context is correctly passed back to the agent |
| [`langfuse_crewai_patches.py`](crew/langfuse_crewai_patches.py) | OpenInference misses `CrewStructuredTool.invoke()` — wraps it with Langfuse observations via `wrapt` |

Applied in `crew.py` at module load:
```python
apply_bedrock_tool_args_patch()
apply_slim_tool_observations_patch()
apply_guardrail_scratchpad_patch()
apply_bedrock_assistant_prefill_patch()
```
`langfuse_crewai_patches` is applied only when `LANGFUSE_ENABLED=1`.

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
KYC_CREW_MAX_RETRIES=      # Full-crew restart limit (default: 7)

# ML Risk Scorer (Stage 1 — SageMaker)
RISK_SCORER_ENDPOINT_NAME= # SageMaker endpoint name for risk scoring (e.g. kyc-risk-scorer)
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
- **Full-crew restart on failure** — no incremental recovery; if any task fails after `guardrail_max_retries` the entire pipeline restarts from task 1 (up to `KYC_CREW_MAX_RETRIES` times). This is intentional: earlier stage outputs are in DynamoDB, but CrewAI's in-memory context is lost, so resuming mid-pipeline is unreliable.

### Guardrail Nonce Pattern (Anti-Hallucination)

Each task where a specific tool **must** run uses a UUID nonce stored in **thread-local storage** to prove the tool executed (vs the LLM just describing it in text):

```python
# Inside the tool:
scoring_id = str(uuid.uuid4())
_tool_state.nonce = scoring_id   # set before the real work

# Inside the task guardrail in crew.py:
def _guardrail(output):
    # Reject if the LLM output IS a tool-call JSON instead of a real answer
    if isinstance(parsed, dict) and "tool" in parsed and "tool_input" in parsed:
        return (False, "REJECTED: You described a tool call instead of executing it.")
    # Reject if the nonce was never set (tool never ran)
    if not get_last_nonce():
        return (False, "REJECTED: the required tool was never called.")
    return (True, output.raw)
```

`guardrail_max_retries=3` per task. After 3 failures the task raises, triggering a full-crew restart. Tools that use this pattern: `compare_identity_documents`, `risk_list_screening`, `produce_adverse_media_analysis`.

### `parse_task_output()` — Robust JSON Extraction

[`crew/utils.py`](crew/utils.py) exports `parse_task_output(raw)` used by every callback. The LLM sometimes wraps its JSON answer in markdown fences or adds prose. Three fallback strategies:

1. Direct `json.loads(text)` — fast path
2. Strip ` ```json … ``` ` fences then parse
3. Regex-extract the first `{…}` block then parse
4. Return `None` and log error if all fail

Callbacks that get `None` fall back to the tool's cached thread-local result (e.g. `compare_identity_tool.get_last_result()`).

### DynamoDB Nested Update Pattern

Callbacks use a 3-step `if_not_exists` approach to safely write into the nested `stages` map without overwriting sibling keys:

```python
# 1. Ensure stages map exists
table.update_item(UpdateExpression="SET #stages = if_not_exists(#stages, :empty)", ...)
# 2. Ensure sub-map exists (e.g. stages.screening)
table.update_item(UpdateExpression="SET #stages.#screening = if_not_exists(...)", ...)
# 3. Write the actual data
table.update_item(UpdateExpression="SET #stages.#screening.#risk = :data", ...)
```

---

## ML Risk Scoring Module (`sagemaker/`)

Added in Stage 1 of the MLOps plan. Trains an XGBoost model on 8 signals from the KYC pipeline and deploys it as a SageMaker endpoint.

### Directory layout

```
sagemaker/
├── pipeline.py          # Create/run SageMaker Pipeline (4 steps)
├── deploy.py            # Deploy approved model version to endpoint
└── scripts/
    ├── preprocess.py    # SKLearnProcessor: encode features, 80/20 split
    ├── train.py         # XGBoost custom script (multi:softprob, 3 classes)
    └── evaluate.py      # Compute AUC/accuracy/per-class F1; write evaluation.json
```

### Pipeline steps

```
PreprocessRiskData → TrainRiskScorer → EvaluateRiskScorer → CheckModelQuality
                                                                 ├─ AUC ≥ 0.85 → RegisterRiskScorer (PendingManualApproval)
                                                                 └─ AUC < 0.85 → FailStep
```

### Feature set (8 features, label = `final_risk_label`)

| Feature | Type | Source in KYC case |
|---------|------|--------------------|
| `pep_match_score` | float 0–100 | approximated from `pepStatus` |
| `sanctions_hit` | 0/1 | `sanctionsStatus` == SANCTIONED |
| `doc_authenticity_score` | float 0–100 | approximated from `documentProcessing.result` |
| `adverse_media_hits` | int | approximated from `adverseMedia.result` |
| `adverse_media_severity` | int 0–4 | approximated from `adverseMedia.result` |
| `pep_match_type` | ordinal 0–2 | none=0, fuzzy=1, exact=2 |
| `doc_status` | ordinal 0–2 | failed=0, unreadable=1, verified=2 |
| `country_risk_tier` | int 1–5 | nationality lookup in `risk_scoring_tool.py` |

**Label**: `final_risk_label` → low=0, medium=1, high=2 (rejected maps to high=2)

### Running the pipeline

```bash
python sagemaker/pipeline.py \
  --role  arn:aws:iam::123456789012:role/SageMakerExecutionRole \
  --bucket kyc-mlops \
  --region eu-west-1 \
  --run

# After manual approval in Model Registry:
python sagemaker/deploy.py \
  --role  arn:aws:iam::123456789012:role/SageMakerExecutionRole \
  --bucket kyc-mlops \
  --smoke-test
```

### Input CSV format expected by pipeline

```
customer_id, pep_match_score, pep_match_type, sanctions_hit, doc_status,
doc_authenticity_score, adverse_media_hits, adverse_media_severity,
country_risk_tier, final_risk_label
[optional: event_time, confirmed_by, confirmed_at]
```

The preprocess script handles both string (low/medium/high) and numeric representations of ordinal columns.
