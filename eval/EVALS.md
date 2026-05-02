# KYC Evaluation Coverage

This document summarises every evaluation in the KYC eval suite — what it measures, how it scores, and where it lives.

---

## Evaluation categories

| Category | When it runs | Where scores appear |
|---|---|---|
| **Online — Langfuse managed** | Continuously on live production traces | Langfuse trace scores (auto) |
| **Experiment** | On-demand via `run_eval.py`, against seeded fixtures | Langfuse dataset experiment runs |
| **Offline** | On-demand via `offline_run.py`, against existing traces | Langfuse trace/observation scores |

---

## Online Evals (Langfuse-managed, production traces)

Configured directly in Langfuse and run automatically against live production traces. No code changes needed to add or adjust these.

| Eval Name | Scoring Method | What it measures |
|---|---|---|
| `toxicity` | LLM-as-judge | Detects harmful, offensive, or inappropriate content in any agent output |
| `relevance` | LLM-as-judge | Whether the agent's response addresses the task it was given |
| `agent_quality` | LLM-as-judge | Overall reasoning quality, coherence, and usefulness of agent outputs |
| `adverse_media_hallucination` | LLM-as-judge | Whether the adverse media agent invents or exaggerates findings not supported by the search results |

All four are **LLM-as-judge** — no deterministic ground truth is available for these qualities.

---

## Experiment Evals (`eval/experiments/run_eval.py`)

Run against four golden fixtures (`all_clear`, `document_mismatch`, `sanction`, `pep`). The full 4-agent crew executes against real mock services; scores are posted to the `kyc-pipeline-accuracy` Langfuse dataset experiment.

| Eval Name | Score Key | Scoring Method | Ground Truth | What it measures |
|---|---|---|---|---|
| Decision Accuracy | `decision-accuracy` | Deterministic (exact match) | `golden_dataset.json` → `expected_action` | Final orchestrator action matches expected `APPROVED` / `ESCALATED` |
| Doc Result Accuracy | `doc-result-accuracy` | Deterministic (exact match) | `golden_dataset.json` → `expected_doc_result` | Document processing stage output matches expected `MATCH` / `MISMATCH` / `PARTIAL_MATCH` |
| Risk Result Accuracy | `risk-result-accuracy` | Deterministic (exact match) | `golden_dataset.json` → `expected_risk_result` | Risk list screening output matches expected `CLEAR` / `HIT` / `ERROR` |
| Decision Justification | `decision-justification` | **LLM-as-judge** (GEval via DeepEval + Bedrock) | Upstream agent results as context | Whether the orchestrator's `action` and `reason[]` logically follow from what the three upstream agents reported |

### Decision Justification judge criteria

The GEval judge receives the full upstream context (document, risk, adverse media results) as INPUT and the orchestrator's raw JSON output as ACTUAL OUTPUT. It scores:
- **High (≥ 0.7)**: correct decision AND `reason[]` explicitly names every failing check with its result value
- **Low (< 0.7)**: wrong decision, or `reason[]` is vague/empty, or decision contradicts upstream findings

---

## Offline Evals (`eval/offline/offline_run.py`)

Post-hoc analysis on existing Langfuse traces — no crew re-execution. Both evaluations run together against the last N traces.

| Eval Name | Score Key | Scoring Method | What it measures |
|---|---|---|---|
| Tool Coverage | `tool-coverage` | Deterministic (fraction) | Fraction of expected tools actually called per agent span; `escalate_to_human` excluded from denominator (conditional) |
| Orchestrator Decision Quality | `orchestrator-decision-quality` | **LLM-as-judge** (Bedrock Claude) | Decision correctness + completeness of `reason[]` relative to the agent's actual reasoning in the trace |

### Tool Coverage — expected tools per agent

| Agent | Expected Tools |
|---|---|
| Document Processing Agent | `get_case_details`, `get_case_files`, `extract_document_text`, `verify_identity_document`, `compare_identity_documents` |
| Risk List Screening Agent | `get_case_details`, `risk_list_screening` |
| Adverse Media Screening Agent | `get_case_details`, `search_internet`, `produce_adverse_media_analysis` |
| KYC Decision Orchestrator | `escalate_to_human` *(optional — only on ESCALATED cases)* |

Scores are attached to each agent's GENERATION observation in the trace. A score of `1.0` means all required tools were called.

### Orchestrator Decision Quality judge criteria

The judge receives the orchestrator's raw LLM reasoning (Thought + Observation from the trace) as input and the structured final JSON decision as output. It scores on two dimensions:

1. **Decision correctness**: `APPROVED` only valid when doc=`MATCH` AND risk=`CLEAR` AND adverse=`OK`; `ESCALATED` valid otherwise
2. **Reason completeness**: `reason[]` should name the person, the specific finding, and the result — not just the check name

| Band | Score | Meaning |
|---|---|---|
| HIGH | 0.8–1.0 | Correct decision AND `reason[]` captures specific findings from trace input |
| MEDIUM | 0.5–0.7 | Correct decision BUT `reason[]` is vague relative to what the trace shows |
| LOW | 0.0–0.4 | Wrong decision, `reason[]` contradicts input, or output is not valid JSON |

---

## Summary: scoring method at a glance

| Eval | Deterministic | LLM-as-judge |
|---|---|---|
| `toxicity` | | ✓ |
| `relevance` | | ✓ |
| `agent_quality` | | ✓ |
| `adverse_media_hallucination` | | ✓ |
| `decision-accuracy` | ✓ | |
| `doc-result-accuracy` | ✓ | |
| `risk-result-accuracy` | ✓ | |
| `decision-justification` | | ✓ |
| `tool-coverage` | ✓ | |
| `orchestrator-decision-quality` | | ✓ |
