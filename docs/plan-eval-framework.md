# Plan: KYC Evaluation Framework — Online + Offline Evals with Langfuse, DeepEval & RAGAS

## Context

The KYC agent system has Langfuse observability (traces, spans, tool observations, LLM calls) but **no custom evaluations**. We need two evaluation tiers:

1. **Online evals** — real-time deterministic scoring on every production trace (zero LLM cost)
2. **Offline evals** — golden dataset-based evaluation using DeepEval + RAGAS + LLM-as-judge for quality gates before promoting agents

### Instrumentation status (verified)
All Bedrock Converse calls in tools ARE instrumented — `BedrockInstrumentor` patches botocore at class level before tools are imported. Import order in `kyc_app.py` is correct. No fix needed.

### Design decisions (confirmed)
- **Judge model**: Configurable via `EVAL_JUDGE_MODEL` env var (default same as agent model)
- **CI/CD**: Skip for now — build eval framework first, CI/CD integration later (may be GitLab)
- **Langfuse availability**: Assume always up (self-hosted EKS)
- **Frameworks**: Prefer DeepEval (primary) + RAGAS (supplementary) over fully custom evals

---

## Framework Selection

| Framework | Role | Why |
|-----------|------|-----|
| **DeepEval** | Primary offline eval | 6 agent-specific metrics (ToolCorrectness, ArgumentCorrectness, TaskCompletion, PlanQuality, PlanAdherence, StepEfficiency), custom metrics via G-Eval/BaseMetric, native Bedrock support |
| **RAGAS** | Supplementary offline eval | ToolCallAccuracy, ToolCallF1, AgentGoalAccuracy — softer F1-based scoring complements DeepEval's strict matching |
| **Langfuse** | Score storage + dashboards | All scores from both frameworks submitted via `langfuse.create_score()`. Datasets for golden test cases. Experiment tracking |
| **Custom (Python)** | Online evals | Deterministic checks (schema validation, risk score consistency, decision-rule alignment) — zero cost, runs in callbacks |

### What we DON'T use (RAG-only, not relevant)
- DeepEval: AnswerRelevancy, Faithfulness, ContextualRecall
- RAGAS: AnswerRelevancy, Faithfulness, ContextPrecision, ContextRecall

---

## ONLINE EVALS (Real-time, every production trace, $0 cost)

All online evals are **deterministic Python checks** running inside existing callback functions. No LLM calls. Scores submitted to Langfuse via `langfuse.create_score()`.

### Eval 1: Schema Compliance (per agent)

Validate each agent's JSON output has required fields with correct types/enums.

| Score Name | Agent | Checks | Type |
|------------|-------|--------|------|
| `identity_schema_valid` | Identity | comparison_result in {MATCH, PARTIAL_MATCH, MISMATCH}, discrepancies is list, summaries non-empty | BOOLEAN |
| `income_schema_valid` | Income | verification_result in {VERIFIED, INSUFFICIENT, SUSPICIOUS, UNREADABLE}, income_details has required keys, risk_indicators is list | BOOLEAN |
| `screening_schema_valid` | Screening | result in {CLEAR, HIT, ERROR}, pepStatus/sanctionsStatus are valid enums | BOOLEAN |
| `adverse_media_schema_valid` | Adverse Media | result in {OK, NOK, PENDING_REVIEW}, summary non-empty | BOOLEAN |
| `orchestrator_schema_valid` | Orchestrator | action in {APPROVED, ESCALATED, ADDITIONAL_DOCUMENTS_REQUIRED}, risk_classification in {LOW, MEDIUM, HIGH}, risk_score int 0-100 | BOOLEAN |

### Eval 2: Risk Score Consistency

| Score Name | Checks | Type |
|------------|--------|------|
| `risk_score_in_range` | Score within classification range (0-30=LOW, 31-60=MEDIUM, 61-100=HIGH) | BOOLEAN |
| `risk_breakdown_sums` | Sum of breakdown factor points equals total score | BOOLEAN |

### Eval 3: Decision-Rule Alignment

| Score Name | Checks | Type |
|------------|--------|------|
| `decision_rule_correct` | Orchestrator action matches expected outcome given the 4 stage results per Wwft rules | BOOLEAN |

Rules checked:
- All MATCH + VERIFIED(no flags) + CLEAR + OK → must be APPROVED
- Any sanctions HIT → must be ESCALATED
- Income INSUFFICIENT + requires_additional_documents → must be ADDITIONAL_DOCUMENTS_REQUIRED
- Any MISMATCH or SUSPICIOUS → must be ESCALATED

### Eval 4: Latency & Efficiency

| Score Name | What | Type |
|------------|------|------|
| `total_pipeline_duration_s` | Time from crew kickoff to orchestrator callback | NUMERIC |
| `identity_agent_iterations` | LLM reasoning loops used (from max_iter budget) | NUMERIC |
| `income_agent_iterations` | LLM reasoning loops used | NUMERIC |

### Implementation

**New file**: `crew/evals/__init__.py`
**New file**: `crew/evals/online.py`

```python
# crew/evals/online.py
def score_identity_schema(task_output: dict) -> dict  # returns {name, value, comment}
def score_income_schema(task_output: dict) -> dict
def score_screening_schema(task_output: dict) -> dict
def score_adverse_media_schema(task_output: dict) -> dict
def score_orchestrator_schema(task_output: dict) -> dict
def score_risk_consistency(risk_score, risk_classification, breakdown) -> list[dict]
def score_decision_rules(case_id, action) -> dict  # reads stages from DynamoDB
def submit_scores(scores: list[dict], trace_id: str) -> None  # wraps langfuse.create_score()
```

**Modify callbacks** to call scoring after DynamoDB write:
- `crew/update_document_result.py` → call `score_identity_schema()`
- `crew/update_income_result.py` → call `score_income_schema()`
- `crew/update_case.py` → call `score_screening_schema()`, `score_adverse_media_schema()`
- `crew/update_orchestrator_result.py` → call `score_orchestrator_schema()`, `score_risk_consistency()`, `score_decision_rules()`

All scoring is wrapped in try/except — failures log warnings but never break the pipeline.

---

## OFFLINE EVALS (Golden datasets, DeepEval + RAGAS + LLM-as-judge)

### Golden Datasets (stored in Langfuse)

4 datasets, each with test items containing input + expected output:

**Dataset 1: `kyc-identity-verification`** (6 items)

| Item | Input Summary | Expected comparison_result | Expected discrepancies |
|------|--------------|---------------------------|----------------------|
| Jan de Vries (clean) | DB=BRP=OCR all match | MATCH | [] |
| Maria Bakker (name mismatch) | DB="Jansen", BRP="Bakker" | MISMATCH | ["name differs"] |
| DOB format swap | DOB: 1985-03-15 vs 1985-15-03 | PARTIAL_MATCH | ["DOB format"] |
| Missing nationality in OCR | OCR extraction incomplete | PARTIAL_MATCH | ["nationality missing"] |
| Expired document | Document past datumEindeGeldigheid | PARTIAL_MATCH | ["document expired"] |
| All sources empty | Minimal/no OCR text | MISMATCH | ["insufficient data"] |

**Dataset 2: `kyc-income-verification`** (8 items)

| Item | Input Summary | Expected verification_result | Expected risk_indicators |
|------|--------------|------------------------------|-------------------------|
| Clean employment (EUR 4K/month) | Salary slip + UWV confirms | VERIFIED | [] |
| No UWV records | Income doc present, UWV=NIET_GEVONDEN | INSUFFICIENT | [] |
| High income temp contract (EUR 250K) | UWV: tijdelijk, no KVK/tax reg | SUSPICIOUS | [income threshold, no KVK, no tax] |
| Self-employed with KVK | Business doc + KVK registered since 2015 | VERIFIED | ["Multiple income sources"] |
| Unreadable document | Garbled OCR text | UNREADABLE | [] |
| Cash deposits > EUR 15K | Bank statement with large cash | SUSPICIOUS or VERIFIED with flag | ["Cash deposits exceed Wwft threshold"] |
| Outdated salary slip (> 3 months) | Old document | INSUFFICIENT | ["Document not recent"] |
| Name mismatch on income doc | Different name on salary slip vs DB | SUSPICIOUS | ["Name mismatch"] |

**Dataset 3: `kyc-adverse-media`** (5 items)

| Item | Input Summary | Expected result |
|------|--------------|-----------------|
| No relevant results | Common name, unrelated hits | OK |
| Clear fraud conviction | THIS person + fraud article | NOK |
| Same name, different person | News about another "Jan de Vries" | OK |
| Ambiguous partial match | Could be this person or another | PENDING_REVIEW |
| No search results at all | Empty results array | OK |

**Dataset 4: `kyc-orchestrator-e2e`** (8 items)

| Item | Input (4 stage results) | Expected action | Expected risk_classification |
|------|------------------------|-----------------|------------------------------|
| All pass | MATCH + VERIFIED + CLEAR + OK | APPROVED | LOW |
| Identity mismatch | MISMATCH + VERIFIED + CLEAR + OK | ESCALATED | MEDIUM/HIGH |
| Sanctions hit | MATCH + VERIFIED + HIT(sanctions) + OK | ESCALATED | HIGH |
| PEP only | MATCH + VERIFIED + HIT(pep) + OK | ESCALATED | LOW (but PEP requires EDD) |
| Income insufficient | MATCH + INSUFFICIENT + CLEAR + OK | ADDITIONAL_DOCUMENTS_REQUIRED | MEDIUM |
| Income suspicious | MATCH + SUSPICIOUS + CLEAR + OK | ESCALATED | MEDIUM |
| Multiple failures | MISMATCH + SUSPICIOUS + HIT + NOK | ESCALATED | HIGH |
| Adverse media pending | MATCH + VERIFIED + CLEAR + PENDING_REVIEW | ESCALATED | LOW/MEDIUM |

### DeepEval Metrics Used

| Metric | Applied To | What It Evaluates |
|--------|-----------|-------------------|
| `ToolCorrectnessMetric` | All agents | Did agent call the right tools in the right order? |
| `ArgumentCorrectnessMetric` | All agents | Were tool parameters correct (case_id, BSN, document type)? |
| `TaskCompletionMetric` | All agents | Did agent produce the expected output format and decision? |
| `StepEfficiencyMetric` | All agents | Were there unnecessary/redundant tool calls? |
| **Custom: `KYCComplianceMetric`** | Orchestrator | Did decision follow Wwft rules given inputs? (G-Eval based) |
| **Custom: `RiskDetectionMetric`** | Income agent | Were all applicable risk indicators identified? (G-Eval based) |

### RAGAS Metrics Used

| Metric | Applied To | What It Evaluates |
|--------|-----------|-------------------|
| `ToolCallAccuracy` | All agents | Exact match of tool call sequence vs expected |
| `ToolCallF1` | All agents | Softer F1-score of tool calls (precision + recall) |
| `AgentGoalAccuracy` | Per agent | Binary: did agent achieve its stated goal? |

### Custom Metrics (DeepEval G-Eval)

**KYCComplianceMetric** — evaluates orchestrator's Wwft rule adherence:
```
Criteria: Given the 4 stage results (identity, income, screening, media),
evaluate whether the orchestrator's decision correctly applies Dutch Wwft rules:
- Sanctions HIT must always ESCALATE
- PEP must always ESCALATE (EDD required)
- All MATCH+VERIFIED+CLEAR+OK must APPROVE
- Income INSUFFICIENT must request additional documents
Score 0-1 based on rule adherence completeness.
```

**RiskDetectionMetric** — evaluates income agent's red flag detection:
```
Criteria: Given the income document text and UWV/KVK registry data,
evaluate whether the agent identified ALL applicable risk indicators:
- Income > EUR 10K/month flagged?
- Missing KVK/tax registration flagged?
- Document recency checked?
- Name consistency verified?
- Cash deposit thresholds checked?
Score 0-1 based on completeness of risk detection.
```

### LLM Judge Configuration

```python
# Uses Bedrock by default, configurable via EVAL_JUDGE_MODEL
judge_model = os.getenv("EVAL_JUDGE_MODEL", os.getenv("MODEL", "us.anthropic.claude-3-5-sonnet-20241022-v2:0"))
```

DeepEval's `DeepEvalBaseLLM` subclass wrapping Bedrock Converse API (same pattern as existing tools).

---

## Implementation Phases

### Phase 1: Online evals infrastructure

**New files:**
- `crew/evals/__init__.py`
- `crew/evals/online.py` — all deterministic scoring functions + Langfuse submission

**Modified files:**
- `crew/update_document_result.py` — add `score_identity_schema()` call
- `crew/update_income_result.py` — add `score_income_schema()` call
- `crew/update_case.py` — add screening + adverse media schema scoring
- `crew/update_orchestrator_result.py` — add orchestrator schema + risk consistency + decision-rule scoring

### Phase 2: Golden datasets + seeding

**New files:**
- `crew/evals/datasets/identity_verification.json`
- `crew/evals/datasets/income_verification.json`
- `crew/evals/datasets/adverse_media.json`
- `crew/evals/datasets/orchestrator_e2e.json`
- `crew/evals/seed_datasets.py` — CLI to create/populate Langfuse datasets from JSON files

**Command**: `python -m crew.evals.seed_datasets --all`

### Phase 3: DeepEval + RAGAS evaluators

**New files:**
- `crew/evals/bedrock_judge.py` — `DeepEvalBaseLLM` subclass for Bedrock Converse
- `crew/evals/custom_metrics.py` — KYCComplianceMetric, RiskDetectionMetric (G-Eval based)
- `crew/evals/offline.py` — orchestrates DeepEval + RAGAS metrics, maps golden datasets to test cases, runs evaluation, submits scores to Langfuse

**Command**: `python -m crew.evals.offline --dataset all --threshold 0.85`

### Phase 4: Documentation

**Modified files:**
- `docs/kyc-business-rules-and-references.md` — add eval section
- `CLAUDE.md` — add eval commands
- `crew/requirements.txt` — add `deepeval`, `ragas`

---

## File Summary

### New files (10)
| File | Purpose |
|------|---------|
| `crew/evals/__init__.py` | Package init |
| `crew/evals/online.py` | Deterministic online scoring functions + Langfuse submission |
| `crew/evals/offline.py` | Offline eval runner (DeepEval + RAGAS + Langfuse experiments) |
| `crew/evals/bedrock_judge.py` | DeepEval-compatible Bedrock LLM wrapper |
| `crew/evals/custom_metrics.py` | KYCComplianceMetric + RiskDetectionMetric (G-Eval) |
| `crew/evals/seed_datasets.py` | CLI to create/populate Langfuse golden datasets |
| `crew/evals/datasets/identity_verification.json` | Golden test cases |
| `crew/evals/datasets/income_verification.json` | Golden test cases |
| `crew/evals/datasets/adverse_media.json` | Golden test cases |
| `crew/evals/datasets/orchestrator_e2e.json` | Golden test cases |

### Modified files (6)
| File | Change |
|------|--------|
| `crew/update_document_result.py` | Add online eval scoring call |
| `crew/update_income_result.py` | Add online eval scoring call |
| `crew/update_case.py` | Add online eval scoring calls |
| `crew/update_orchestrator_result.py` | Add online eval scoring calls |
| `crew/requirements.txt` | Add `deepeval`, `ragas` |
| `CLAUDE.md` | Add eval commands |

---

## Verification

1. **Online evals**: Deploy with `LANGFUSE_ENABLED=1`, run test case, check Langfuse trace shows boolean/numeric scores attached to observations
2. **Golden datasets**: Run `python -m crew.evals.seed_datasets --all`, verify 4 datasets in Langfuse UI with correct item counts
3. **Offline evals**: Run `python -m crew.evals.offline --dataset kyc-identity-verification --threshold 0.85`, verify:
   - DeepEval ToolCorrectness/TaskCompletion scores appear
   - RAGAS ToolCallAccuracy/AgentGoalAccuracy scores appear
   - Custom KYCCompliance/RiskDetection scores appear
   - All linked to Langfuse experiment
4. **Thresholds**: Verify known-good test cases (Jan de Vries) score > 0.85 on all metrics
