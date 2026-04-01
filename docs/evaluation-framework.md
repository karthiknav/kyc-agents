# KYC Evaluation Framework -- Design Decisions & Reference

## Quick Look

| Eval Type | Framework | Metric Name | What It Measures | Cost per Eval | Frequency |
|-----------|-----------|-------------|------------------|---------------|-----------|
| Online | Custom Python | `identity_schema_valid` | Identity agent output has correct fields and enum values | $0 | Every trace |
| Online | Custom Python | `income_schema_valid` | Income agent output has correct fields and enum values | $0 | Every trace |
| Online | Custom Python | `screening_schema_valid` | Screening agent output has correct fields and enum values | $0 | Every trace |
| Online | Custom Python | `adverse_media_schema_valid` | Adverse media agent output has correct fields and enum values | $0 | Every trace |
| Online | Custom Python | `orchestrator_schema_valid` | Orchestrator agent output has correct fields and enum values | $0 | Every trace |
| Online | Custom Python | `risk_score_in_range` | Risk score falls within the correct range for its classification | $0 | Every trace (orchestrator) |
| Online | Custom Python | `risk_breakdown_sums` | Breakdown TOTAL line matches the computed risk score | $0 | Every trace (orchestrator) |
| Online | Custom Python | `decision_rule_correct` | Orchestrator action matches Wwft rules given the 4 stage results | $0 | Every trace (orchestrator) |
| Offline | DeepEval | `TaskCompletionMetric` | Agent completed its assigned task and produced valid output | ~$0.02 (LLM judge) | On-demand / CI |
| Offline | DeepEval (custom) | `KYCComplianceMetric` | Orchestrator decision follows Dutch Wwft rules | ~$0.02 (LLM judge) | On-demand / CI |
| Offline | DeepEval (custom) | `RiskDetectionMetric` | Income agent identified all applicable Wwft risk indicators | ~$0.02 (LLM judge) | On-demand / CI |
| Offline | RAGAS | `AgentGoalAccuracy` | Agent achieved its stated objective (binary) | ~$0.02 (LLM judge) | On-demand / CI |

---

## Part 1: Why We Need Evals

LLM agents are non-deterministic. The same input -- the same KYC case with the same documents and the same government data -- can produce different outputs on different runs. The identity agent might classify a discrepancy as MISMATCH one time and PARTIAL_MATCH the next. The orchestrator might approve a case it should escalate. The income agent might miss a risk indicator it caught yesterday.

In most software systems, occasional variation is tolerable. In a KYC/compliance context, it is not. The Dutch Anti-Money Laundering Act (Wwft) imposes specific obligations on financial institutions. Approving a sanctioned individual is not a quality issue -- it is a legal violation that carries regulatory fines and potential criminal liability. Missing a Politically Exposed Person (PEP) means failing to perform legally required Enhanced Due Diligence. Overlooking suspicious income patterns means failing the institution's gatekeeper role.

This creates two distinct evaluation needs:

**Real-time monitoring (online evals):** Is the system behaving correctly right now, on every single case? If the identity agent starts producing malformed output, or the orchestrator starts approving cases it should escalate, we need to know immediately -- not days later when someone reviews a dashboard. These checks must be fast, cheap, and run on every trace.

**Pre-deployment quality gates (offline evals):** Before promoting a new model version or agent configuration, is the new version at least as good as the current one? This requires running a standardized set of test cases and measuring quality with metrics that understand KYC-specific correctness. These checks can be slower and more expensive because they run on a fixed dataset, not on every production trace.

The distinction between online and offline evals is fundamental to the architecture. Online evals are deterministic Python checks -- they verify structural correctness and rule compliance with zero LLM cost. Offline evals use LLM-as-judge to assess nuanced quality -- whether reasoning is complete, whether all risk indicators were identified, whether the agent achieved its goal. Combining both tiers gives us confidence that the system is correct (online) and high-quality (offline).

---

## Part 2: Evaluation Architecture

### Two-Tier Design

The evaluation system is split into two tiers that complement each other:

**Tier 1 -- Online evals:** Deterministic Python checks embedded in agent callbacks. These run on every production trace, cost nothing (no LLM calls), and submit boolean scores to Langfuse in real time. They catch structural failures (malformed output, wrong enum values), arithmetic bugs (risk score does not match classification), and rule violations (orchestrator approved a sanctioned person). The implementation lives in `crew/evals/online.py` and is called from each agent's callback function after the DynamoDB write completes. All scoring is wrapped in try/except -- failures log warnings but never break the pipeline.

**Tier 2 -- Offline evals:** Golden datasets evaluated with LLM-as-judge via DeepEval and RAGAS. These run on demand or in a CI/CD pipeline, use a configurable Bedrock model as the judge, and assess nuanced quality that deterministic checks cannot capture. The implementation lives in `crew/evals/offline.py`, `crew/evals/custom_metrics.py`, and `crew/evals/bedrock_judge.py`.

**Both tiers submit scores to Langfuse** using `langfuse.create_score()`. This means traces in Langfuse carry both real-time structural scores and (when offline evals are run against historical traces) quality scores. A single dashboard shows everything.

### What Gets Evaluated at Each Layer

**Agent outputs (5 agents):**
- Identity verification agent -- comparison_result, discrepancies, summaries
- Income verification agent -- verification_result, income_source, risk_indicators, income_details
- Risk list screening agent -- result, pepStatus, sanctionsStatus, datasetsMatched
- Adverse media agent -- result, summary
- Orchestrator agent -- action, reason, recommendation_summary, risk_score, risk_classification

**Tool call patterns:**
- Offline evals assess whether agents called the right tools (TaskCompletionMetric evaluates this as part of task completion)

**Risk scoring consistency:**
- Online: score-to-classification range check, breakdown sum verification
- Offline: risk classification correctness assessed by KYCComplianceMetric

**Decision-rule compliance:**
- Online: deterministic Wwft rule check against DynamoDB stage results
- Offline: LLM judge assesses reasoning completeness via KYCComplianceMetric

**End-to-end case outcomes:**
- Offline: orchestrator_e2e dataset tests the full decision pipeline with all combinations of stage results

---

## Part 3: Online Evals -- What, Why, How

All online eval functions are defined in `crew/evals/online.py`. The main entry point is `run_online_evals()`, which dispatches to the appropriate scoring functions based on the `stage` parameter and submits all scores to Langfuse via `submit_scores()`.

### 3.1 Schema Compliance (5 scores)

Each of the 5 agents produces a structured JSON output. Schema compliance checks verify that the output contains the required fields with valid values. If an agent produces malformed output, the downstream callback may fail silently, and subsequent agents receive garbage input.

#### identity_schema_valid

- **What it checks:**
  - `comparison_result` is one of: `MATCH`, `PARTIAL_MATCH`, `MISMATCH`
  - `discrepancies` is a list
  - `comparison_summary` is a non-empty string
  - `documents_summary` is a non-empty string
  - `case_id` is present
- **Why this matters:** If comparison_result contains a typo or unexpected value (e.g., "MATCHH" or "Match"), the orchestrator cannot correctly determine the identity verification outcome. The downstream decision logic depends on exact enum values.
- **How it works:** Pure Python `isinstance()` and `in` checks. No LLM involved.
- **Score type:** BOOLEAN (0 or 1)
- **Example:** Identity agent outputs `comparison_result="MATCHH"` (typo) -- score=0, comment="comparison_result 'MATCHH' not in valid set"

#### income_schema_valid

- **What it checks:**
  - `verification_result` is one of: `VERIFIED`, `INSUFFICIENT`, `SUSPICIOUS`, `UNREADABLE`
  - `income_source` is one of: `employment`, `self_employment`, `business_ownership`, `investments`, `pension`, `social_benefits`, `unknown`
  - `risk_indicators` is a list
  - `income_details` (if present) contains `employer_or_source` and `monthly_income_eur`
  - `additional_documents_needed` (if present) is a list
  - `case_id` is present
- **Why this matters:** The income verification result drives the orchestrator's decision about whether to request additional documents or escalate. An invalid `verification_result` value means the orchestrator cannot apply its decision rules.
- **How it works:** Python type and membership checks.
- **Score type:** BOOLEAN (0 or 1)

#### screening_schema_valid

- **What it checks:**
  - `result` is one of: `CLEAR`, `HIT`, `ERROR`
  - `pepStatus` is one of: `NOT_PEP`, `PEP`, `UNKNOWN`
  - `sanctionsStatus` is one of: `NOT_SANCTIONED`, `SANCTIONED`, `UNKNOWN`
  - `datasetsMatched` is a list
  - `case_id` is present
- **Why this matters:** Sanctions screening is the most legally critical check. If `sanctionsStatus` contains an unexpected value, the orchestrator may fail to escalate a sanctioned individual -- a direct Wwft violation.
- **How it works:** Python type and membership checks.
- **Score type:** BOOLEAN (0 or 1)

#### adverse_media_schema_valid

- **What it checks:**
  - `result` is one of: `OK`, `NOK`, `PENDING_REVIEW`
  - `summary` is a non-empty string
  - `case_id` is present
- **Why this matters:** An empty or missing summary means compliance officers have no context for review. An invalid result value means the orchestrator cannot factor adverse media into its decision.
- **How it works:** Python type and membership checks.
- **Score type:** BOOLEAN (0 or 1)

#### orchestrator_schema_valid

- **What it checks:**
  - `action` is one of: `APPROVED`, `ESCALATED`, `ADDITIONAL_DOCUMENTS_REQUIRED`
  - `case_id` is present
  - `reason` is a list
  - `recommendation_summary` is a non-empty string
- **Why this matters:** The orchestrator's action is the final KYC decision. If it contains an invalid value, the case cannot be routed to the correct workflow (approval queue, escalation queue, or document request queue).
- **How it works:** Python type and membership checks.
- **Score type:** BOOLEAN (0 or 1)

### 3.2 Risk Score Consistency (2 scores)

#### risk_score_in_range

- **What it checks:** The numeric risk score falls within the correct range for the stated risk classification:
  - LOW: 0--30
  - MEDIUM: 31--60
  - HIGH: 61--100
- **Why this matters:** A risk score of 75 classified as LOW is a bug that could cause a high-risk case to be treated as low-risk. This is a direct compliance failure.
- **How it works:** Integer range comparison. No LLM needed.
- **Score type:** BOOLEAN (0 or 1)

#### risk_breakdown_sums

- **What it checks:** The TOTAL line in the risk breakdown (format: `"TOTAL: {score}/100 = {classification}"`) matches the actual risk_score value.
- **Why this matters:** The risk breakdown is shown to compliance officers. If the breakdown says "TOTAL: 45/100" but the risk_score field says 65, the officer sees contradictory information and cannot trust the system.
- **How it works:** String parsing of the TOTAL line, integer comparison. No LLM needed.
- **Score type:** BOOLEAN (0 or 1)
- **Why not LLM-based:** This is pure arithmetic -- verifying that a sum equals a stated total. Using an LLM judge for this would be wasteful (approximately $0.01 per check) and less reliable than a simple integer comparison.

### 3.3 Decision-Rule Alignment (1 score)

#### decision_rule_correct

- **What it checks:** The orchestrator's `action` matches the expected outcome given the 4 stage results stored in DynamoDB. The complete rule table:

| Condition | Expected Action | Rationale |
|-----------|----------------|-----------|
| Sanctions HIT (sanctionsStatus = SANCTIONED) | ESCALATED | EU sanctions law -- no discretion allowed |
| Identity MISMATCH | ESCALATED | Potential identity fraud |
| Income SUSPICIOUS | ESCALATED | Potential money laundering indicators |
| Adverse media NOK | ESCALATED | Confirmed adverse findings |
| Income INSUFFICIENT + requires_additional_documents | ADDITIONAL_DOCUMENTS_REQUIRED | Incomplete verification, more evidence needed |
| Income UNREADABLE | ADDITIONAL_DOCUMENTS_REQUIRED | Document could not be processed |
| All pass (MATCH + VERIFIED + CLEAR + OK, no risk indicators) | APPROVED | All checks satisfied |
| PEP HIT (no sanctions) | ESCALATED | Enhanced Due Diligence required under Wwft Art. 8 |
| All pass but PEP HIT | APPROVED or ESCALATED (both acceptable) | PEP escalation is always acceptable even when score is LOW |

- **Why this matters:** The orchestrator is an LLM making the final KYC decision. It receives a system prompt with these rules, but LLMs can drift -- they may occasionally ignore instructions, especially under ambiguous inputs. This eval verifies that every single production decision follows the rules.
- **Why deterministic (not LLM judge):** The rules are explicit and binary. There is no judgment call -- sanctions HIT must be ESCALATED, period. An LLM judge would add cost, latency, and its own potential for error on checks that have objectively correct answers.
- **How it reads stage results:** The function calls `boto3.resource("dynamodb").Table(table_name).get_item(Key={"CaseId": case_id})` to retrieve the case record. It extracts `identityVerification`, `incomeVerification`, `screening.riskListScreening`, and `screening.adverseMedia` from the `stages` field. If the DynamoDB read fails, the score returns 0 with a comment explaining the failure.

---

## Part 4: Offline Evals -- Framework Selection

### 4.1 Why DeepEval (Primary)

DeepEval was selected as the primary offline evaluation framework for several reasons:

- **Agent-specific metrics:** DeepEval provides 6 metrics designed for tool-using agents (ToolCorrectness, ArgumentCorrectness, TaskCompletion, PlanQuality, PlanAdherence, StepEfficiency), not just RAG pipelines. Our KYC agents are tool-using agents, not retrieval-augmented generators.
- **Custom metrics via BaseMetric subclassing:** We needed two domain-specific metrics (KYCComplianceMetric and RiskDetectionMetric) that encode Dutch Wwft rules. DeepEval's `BaseMetric` class provides a clean interface for this -- implement `measure()`, `is_successful()`, and `__name__`, and the metric integrates with the rest of the framework.
- **Native AWS Bedrock support:** DeepEval's `DeepEvalBaseLLM` base class allows wrapping any LLM provider. Our `BedrockJudgeLLM` class extends this to use the Bedrock Converse API, keeping all evaluation data within AWS infrastructure.
- **Pytest integration for CI/CD:** DeepEval test cases can run as pytest tests, which integrates naturally with CI/CD pipelines.
- **Active development and documentation:** The framework is well-maintained and has clear documentation for custom metric development.

### 4.2 Why RAGAS (Supplementary)

RAGAS supplements DeepEval with metrics that take a different approach:

- **AgentGoalAccuracy** provides a binary goal completion assessment. It infers the agent's goal from the full conversation and judges whether the goal was achieved. This complements DeepEval's TaskCompletionMetric, which is more focused on output format compliance.
- **ToolCallAccuracy and ToolCallF1** provide F1-based scoring for tool calls. Where DeepEval's ToolCorrectnessMetric uses exact sequence matching (all-or-nothing), RAGAS gives partial credit for getting most tool calls right.
- RAGAS was originally RAG-focused but has added agent evaluation metrics. It supplements DeepEval -- it does not replace it.

In the current implementation (`crew/evals/offline.py`), RAGAS is used for `AgentGoalAccuracy` across all 4 datasets. If RAGAS is not installed, the offline runner logs a warning and skips RAGAS metrics without failing.

### 4.3 Why Langfuse (Score Storage)

Langfuse serves as the unified score storage and dashboard layer:

- **Already deployed:** Langfuse is self-hosted on EKS and already in use for tracing (spans, tool observations, LLM calls). Adding evaluation scores to the same system avoids introducing new infrastructure.
- **Unified dashboard:** Traces and evaluation scores appear in one place. A compliance officer or developer can look at a single trace and see both what the agent did (trace) and how well it did it (scores).
- **Dataset management:** Langfuse supports dataset creation and management, which can be used for golden test cases via the `seed_datasets.py` CLI.
- **Experiment tracking:** When running offline evals, results are grouped into experiments (named with a timestamp, e.g., `kyc-offline-eval-20260401T120000`), making it easy to compare model versions over time.
- **Both frameworks submit scores:** Online evals use `langfuse.create_score()` directly. Offline evals submit via `submit_to_langfuse()` in the offline runner.

### 4.4 What We Rejected and Why

| Framework/Metric | What It Does | Why Rejected |
|-----------------|-------------|--------------|
| DeepEval AnswerRelevancyMetric | Scores if answer is relevant to question | RAG-specific -- our agents do not answer questions, they execute tool-based workflows that produce structured JSON outputs |
| DeepEval FaithfulnessMetric | Checks if answer is grounded in context | RAG-specific -- requires `retrieval_context` which our agents do not use; there is no retrieval step in the pipeline |
| DeepEval ContextualRecallMetric | Checks if relevant info was retrieved | RAG-specific -- no retrieval step exists in our pipeline |
| DeepEval ContextualPrecisionMetric | Checks if retrieved context is relevant | RAG-specific -- same reason as above |
| DeepEval HallucinationMetric | Detects hallucinated content | Our agents output structured JSON with specific field values (e.g., `comparison_result: "MATCH"`). Hallucination in this context manifests as wrong enum values or fabricated field content, which schema validation catches deterministically and more reliably |
| DeepEval BiasMetric | Detects biased responses | Not applicable -- our agents do not generate free-text responses to users; they produce structured compliance data based on document analysis and registry lookups |
| DeepEval ToxicityMetric | Detects toxic content | Not applicable -- agents produce structured compliance data (JSON with enum fields), not user-facing text |
| RAGAS AnswerRelevancy | Same as DeepEval's variant | RAG-specific -- no question-answering pattern in our agents |
| RAGAS Faithfulness | Same as DeepEval's variant | RAG-specific -- no retrieval_context available |
| RAGAS ContextPrecision/Recall | Context quality metrics | RAG-specific -- no retrieval pipeline exists |
| RAGAS TopicAdherence | Checks if agent stays on topic | Marginally useful, but our agents are task-specific with explicit tool lists defined in YAML. Off-topic behavior would manifest as wrong tool calls, which ToolCorrectness catches more precisely |
| RAGAS PlanQualityMetric | Evaluates agent planning quality | Useful in theory, but our CrewAI agents have fixed tool sequences defined in their YAML configuration. Planning quality is mostly predetermined by the agent definition, not emergent |
| Bedrock built-in GoalSuccessRate | Generic goal success assessment | Too generic -- does not understand Wwft rules or KYC-specific success criteria. A decision could be "successful" in generic terms but violate sanctions law |
| Bedrock built-in Correctness | Generic correctness assessment | Same problem -- no domain knowledge of what "correct" means in a Dutch KYC context |
| Custom LLM-as-judge for online evals | Use LLM to score every trace in real-time | Rejected for online use: too slow ($0.01--$0.10 per evaluation call), adds latency to every case processing, and all online checks are deterministic (schema validation, arithmetic, rule matching) -- no judgment is needed |
| Separate eval database (not Langfuse) | Store evaluation scores in a dedicated database | Rejected because Langfuse is already deployed and operational. Adding another system increases operational complexity. Unified tracing and evaluation in one dashboard is simpler to maintain and reason about |

---

## Part 5: Offline Eval Metrics -- Detailed Breakdown

### 5.1 DeepEval: TaskCompletionMetric

- **What:** An LLM judge assesses whether the agent completed its assigned task. It analyzes the input, the tools available, and the actual output to determine if the agent fulfilled its objective.
- **How it maps to KYC:** Did the identity agent produce a valid identity comparison? Did the income agent verify source of funds and flag risk indicators? Did the adverse media agent reach a conclusion about media findings? Did the orchestrator make a final KYC decision with reasoning?
- **Judge prompt:** DeepEval infers the task from the input and analyzes the tool usage and response format. The judge assesses whether the output constitutes a complete response to the task.
- **Score:** 0.0--1.0 continuous
- **Applied to:** All 4 datasets (identity_verification, income_verification, adverse_media, orchestrator_e2e)
- **Threshold:** 0.85
- **Implementation:** Used directly from DeepEval with the configurable judge model passed in: `TaskCompletionMetric(threshold=threshold, model=judge_model)`

### 5.2 DeepEval: Custom KYCComplianceMetric

- **What:** An LLM judge evaluates whether the orchestrator's decision correctly applies Dutch Wwft rules given the 4 stage results.
- **How it maps to KYC:** Sanctions HIT must result in ESCALATED. PEP must trigger Enhanced Due Diligence (ESCALATED). All checks passing must result in APPROVED. Income INSUFFICIENT must request additional documents. Identity MISMATCH or SUSPICIOUS income must result in ESCALATED.
- **Judge prompt:** The judge receives the full Wwft rule set as part of its prompt, including:
  1. Sanctions HIT must always ESCALATE (EU law, no discretion)
  2. PEP must always ESCALATE (Wwft Art. 8 EDD requirement)
  3. All MATCH + VERIFIED + CLEAR + OK must APPROVE
  4. Income INSUFFICIENT with additional documents needed must result in ADDITIONAL_DOCUMENTS_REQUIRED
  5. Identity MISMATCH or SUSPICIOUS income must ESCALATE
  6. Risk classification must be consistent with score ranges
- **Scoring rubric:**
  - 1.0: Decision is correct AND all Wwft rules properly applied AND reasoning is complete
  - 0.75: Decision is correct but reasoning misses some factors
  - 0.5: Decision is correct but risk classification is wrong
  - 0.25: Decision is wrong but shows partial understanding
  - 0.0: Decision violates Wwft rules (e.g., approved a sanctions hit)
- **Fallback:** If the LLM judge is unavailable or its response cannot be parsed, the metric falls back to a deterministic check: exact match on expected action. If `expected_action == actual_action`, score is 1.0; otherwise 0.0.
- **Score:** 0.0--1.0 continuous
- **Applied to:** orchestrator_e2e dataset only (added conditionally when `"orchestrator"` appears in the dataset name)
- **Threshold:** 0.80
- **Why custom:** No off-the-shelf metric understands Dutch Wwft compliance rules. Generic "correctness" metrics do not know that approving a sanctioned person is illegal, or that PEP status requires Enhanced Due Diligence. The domain rules must be explicitly encoded in the judge prompt.

### 5.3 DeepEval: Custom RiskDetectionMetric

- **What:** An LLM judge evaluates whether the income agent identified all applicable risk indicators from the Wwft perspective.
- **How it maps to KYC:** Did the agent catch that monthly income exceeds EUR 10,000? Did it flag the missing KVK registration? Did it notice cash deposits above EUR 15,000? Did it detect the name mismatch between the salary slip and the applicant?
- **Judge prompt:** The judge receives 8 specific Wwft risk indicators to check:
  1. Income exceeding EUR 10,000/month from standard employment
  2. Missing Dutch KVK registration for employer
  3. Missing Dutch loonheffingennummer (wage tax number)
  4. Document older than 3 months (salary slip/bank statement)
  5. Cash deposits exceeding EUR 15,000 (Wwft Art. 16)
  6. Name on document does not match applicant
  7. Temporary contract with unusually high salary
  8. Transfers from high-risk jurisdictions
- **Scoring rubric:**
  - 1.0: All applicable indicators identified, no false positives
  - 0.75: Most indicators found, 1 minor miss
  - 0.5: Some indicators found, missed important ones
  - 0.25: Few indicators found
  - 0.0: Failed to identify obvious risk indicators
- **Fallback:** If the LLM judge is unavailable, the metric falls back to a deterministic set overlap: it compares expected_indicators with actual_indicators (case-insensitive string matching) and computes the ratio of found indicators to expected indicators.
- **Score:** 0.0--1.0 continuous
- **Applied to:** income_verification dataset only (added conditionally when `"income"` appears in the dataset name)
- **Threshold:** 0.80
- **Why custom:** No off-the-shelf metric knows about Wwft-specific risk indicators. A generic "completeness" metric would not know that cash deposits above EUR 15,000 trigger a specific legal reporting obligation, or that a missing KVK number for a Dutch employer is a red flag.

### 5.4 RAGAS: AgentGoalAccuracy

- **What:** A binary assessment of whether the agent achieved its objective. RAGAS infers the goal from the input and evaluates whether the output satisfies that goal.
- **How it maps to KYC:** For each dataset item, did the agent reach the expected verdict? Did the identity agent correctly classify the comparison? Did the orchestrator make the right decision?
- **Score:** Binary (0 or 1)
- **Applied to:** All 4 datasets
- **Why RAGAS over DeepEval for this:** RAGAS infers the goal from the full conversation context, providing a different perspective than DeepEval's TaskCompletionMetric, which is more focused on output format and tool usage. Having both gives a more complete picture of agent quality.
- **Implementation:** The offline runner constructs a HuggingFace Dataset from the golden dataset items and passes it to `ragas.evaluate()` with `AgentGoalAccuracy()` as the metric. If RAGAS is not installed, the metric is skipped with a warning.

---

## Part 6: Golden Datasets -- Design and Scenarios

### 6.1 Design Principles

- Each dataset covers the full range of possible outcomes for its agent. Every valid enum value for the agent's primary output field appears at least once.
- Scenarios map to the 4 test personas (Jan de Vries, Maria Bakker, Ahmed Al-Rashid, Willem van den Berg) plus edge cases with additional test identities.
- Expected outputs are deterministic reference answers -- specific enum values, not ranges. This enables exact-match scoring as a baseline.
- Items include both happy paths (everything works correctly) AND failure modes (mismatches, suspicious patterns, missing data, unreadable documents).
- Datasets are stored as JSON files in `crew/evals/datasets/` and can be seeded into Langfuse via the `seed_datasets.py` CLI.

### 6.2 Dataset: kyc-identity-verification (6 items)

**File:** `crew/evals/datasets/identity_verification.json`

#### Item 1: Clean match (Jan de Vries)

- **Scenario:** Jan de Vries, born 1985-03-15, passport NL123456789. All three sources (case database, OCR extraction from passport, BRP government verification) agree on name, date of birth, nationality, and document number.
- **What is being tested:** The happy path. When all data sources are consistent, the agent should confidently return MATCH with no discrepancies.
- **Why this scenario matters:** This is the baseline. If the agent cannot correctly identify a clean match, nothing else will work. Most real KYC cases are clean matches -- the agent must handle the common case reliably.
- **Expected output:** `comparison_result: "MATCH"`, `discrepancies: []`

#### Item 2: Name mismatch (Maria Bakker)

- **Scenario:** Case database says "Maria Jansen", but the passport OCR and BRP government verification both say "Maria Bakker". Date of birth and document number match.
- **What is being tested:** Detection of identity fraud or data entry errors. The agent must recognize that the name in the case database differs from the verified government record.
- **Why this scenario matters:** This is the most critical identity test. A name mismatch between the customer's stated identity and government records could indicate identity fraud -- someone using another person's documents. Failing to catch this means a potentially fraudulent account gets approved.
- **Expected output:** `comparison_result: "MISMATCH"`, `discrepancies: ["name differs: DB=Maria Jansen, BRP=Maria Bakker"]`

#### Item 3: DOB format swap

- **Scenario:** Pieter Smit, same date of birth in case database and OCR (1985-03-15 and 15-03-1985 respectively), but BRP has it as 1985-15-03 -- an ambiguous format that could be DD-MM or MM-DD.
- **What is being tested:** Tolerance for date format variations. European and American date formats can be confused (15-03 vs 03-15). The agent should recognize the ambiguity rather than declaring a definitive match or mismatch.
- **Why this scenario matters:** Date format confusion is a common real-world issue, especially with international documents. It is not fraud, but it needs human review to confirm.
- **Expected output:** `comparison_result: "PARTIAL_MATCH"`, `discrepancies: ["date of birth format inconsistency between sources"]`

#### Item 4: Missing nationality in OCR

- **Scenario:** Anna Visser, all core fields match between sources, but the OCR extraction from the passport did not capture the nationality field.
- **What is being tested:** Handling of incomplete extraction. Textract (the OCR tool) does not always extract every field. The agent should recognize that while available data matches, a field is missing.
- **Why this scenario matters:** OCR failures are a regular occurrence in production. The agent must not treat missing data as matching data.
- **Expected output:** `comparison_result: "PARTIAL_MATCH"`, `discrepancies: ["nationality not found in OCR extraction"]`

#### Item 5: Expired document

- **Scenario:** Kees de Jong, all fields match between sources, but the passport expired on 2024-01-01 (the `datumEindeGeldigheid` field in the BRP response shows this, and the OCR text says "Geldig tot: 01-01-2024").
- **What is being tested:** Document validity detection. An expired identity document may not be legally acceptable for KYC purposes.
- **Why this scenario matters:** Accepting an expired document could be a compliance violation. The agent must check document validity dates.
- **Expected output:** `comparison_result: "PARTIAL_MATCH"`, `discrepancies: ["document has expired (datumEindeGeldigheid: 2024-01-01)"]`

#### Item 6: Empty sources

- **Scenario:** "Unknown Person" with passport NL000000000. The OCR extraction returns an empty string. The government verification returns an empty array.
- **What is being tested:** Graceful handling of complete data failure. No usable data from any source.
- **Why this scenario matters:** Edge case that can occur when documents are illegible or government systems are down. The agent must not crash or produce an optimistic result from no data.
- **Expected output:** `comparison_result: "MISMATCH"`, `discrepancies: ["insufficient data from document extraction and government verification"]`

### 6.3 Dataset: kyc-income-verification (8 items)

**File:** `crew/evals/datasets/income_verification.json`

#### Item 1: Clean employment (Jan de Vries)

- **Scenario:** Jan de Vries, salary slip showing EUR 4,000/month from Tech Solutions BV (vast/permanent contract), UWV registry confirms the employment with matching employer name, KVK number 12345678, and annual salary of EUR 48,000.
- **What is being tested:** Happy path for standard employment. All data is consistent and within normal parameters.
- **Why this scenario matters:** Baseline case. Most applicants have straightforward employment that should verify cleanly.
- **Expected output:** `verification_result: "VERIFIED"`, `income_source: "employment"`, `risk_indicators: []`

#### Item 2: No UWV records (Maria Bakker)

- **Scenario:** Maria Bakker, salary slip shows EUR 3,500/month from "Onbekend BV", but UWV registry returns `status: "NIET_GEVONDEN"` (not found) with empty employment records.
- **What is being tested:** The "request more documents" path. The salary slip exists but cannot be verified against government records.
- **Why this scenario matters:** When UWV has no record of the employment, it could mean the employer is not registered, the employment is informal, or there is a data delay. Additional documents are needed to verify.
- **Expected output:** `verification_result: "INSUFFICIENT"`, `requires_additional_documents: true`

#### Item 3: Suspicious high income (Ahmed Al-Rashid)

- **Scenario:** Ahmed Al-Rashid, employment contract showing EUR 20,833/month (EUR 250,000/year) as a "Consultant" on a temporary 1-year contract with "International Trading GmbH". UWV shows the employer has no Dutch KVK registration and no Dutch loonheffingennummer (wage tax number).
- **What is being tested:** Multi-flag detection. This scenario has three distinct risk indicators that must all be identified.
- **Why this scenario matters:** This is a textbook suspicious income pattern: unusually high salary for a temporary contract, employer not registered in Dutch business registries, and no Dutch tax withholding setup. Each flag alone warrants attention; together they strongly suggest money laundering risk.
- **Expected output:** `verification_result: "SUSPICIOUS"`, `risk_indicators: ["Monthly income EUR 20,833 exceeds EUR 10,000 threshold", "Employer has no Dutch KVK registration", "Employer has no Dutch loonheffingennummer"]`

#### Item 4: Self-employed with KVK (Willem van den Berg)

- **Scenario:** Willem van den Berg, tax return showing EUR 95,000 from government employment plus EUR 65,000 from a private business (KVK number 87654321). UWV confirms the government employment.
- **What is being tested:** Non-standard income source. Multiple income streams, including self-employment.
- **Why this scenario matters:** Self-employed income verified via KVK is legitimate, but the multiple income sources should be noted as a risk indicator (not necessarily negative, but requires documentation).
- **Expected output:** `verification_result: "VERIFIED"`, `income_source: "employment"`, `risk_indicators: ["Multiple income sources: government employment + private business"]`

#### Item 5: Unreadable document

- **Scenario:** "Test Person", garbled OCR text ("xk39f... [[garbled]] ...#@$ unable to parse"), empty income registry data.
- **What is being tested:** Graceful degradation when the document cannot be processed.
- **Why this scenario matters:** OCR failures happen in production (poor image quality, unusual document formats). The agent must recognize unreadable input and request a new document rather than guessing.
- **Expected output:** `verification_result: "UNREADABLE"`

#### Item 6: Cash deposits exceeding EUR 15K (Frank Dekker)

- **Scenario:** Frank Dekker, bank statement showing two cash deposits of EUR 18,000 and EUR 22,000 in a single month, alongside a regular salary of EUR 3,500 from ABC Corp.
- **What is being tested:** Detection of the Wwft Art. 16 cash transaction reporting threshold. Cash deposits above EUR 15,000 must be flagged.
- **Why this scenario matters:** Large cash deposits are a primary money laundering indicator under Dutch law. The Wwft requires financial institutions to report unusual transactions, and cash deposits above EUR 15,000 are explicitly listed.
- **Expected output:** `verification_result: "SUSPICIOUS"`, `risk_indicators: ["Cash deposits exceed EUR 15,000 Wwft reporting threshold"]`

#### Item 7: Outdated salary slip (Eva Mulder)

- **Scenario:** Eva Mulder, salary slip from September 2025 (more than 3 months old at the time of evaluation). UWV confirms employment at Retail BV.
- **What is being tested:** Document recency check. Old documents may not reflect current employment status.
- **Why this scenario matters:** A salary slip from months ago could be from a job the applicant no longer holds. KYC verification requires recent documentation.
- **Expected output:** `verification_result: "INSUFFICIENT"`, `risk_indicators: ["Document older than 3 months"]`

#### Item 8: Name mismatch on income doc (Sophie van Dijk)

- **Scenario:** Sophie van Dijk (applicant name), but the salary slip says "Sophie Hendriks" as the employee. UWV confirms employment at Design Studio BV.
- **What is being tested:** Cross-reference between the applicant's identity and the name on the income document.
- **Why this scenario matters:** If the name on the salary slip does not match the applicant, it could mean the document belongs to someone else -- a common fraud pattern.
- **Expected output:** `verification_result: "SUSPICIOUS"`, `risk_indicators: ["Name on document (Sophie Hendriks) does not match applicant (Sophie van Dijk)"]`

### 6.4 Dataset: kyc-adverse-media (5 items)

**File:** `crew/evals/datasets/adverse_media.json`

#### Item 1: No relevant results (Jan de Vries)

- **Scenario:** Search for "Jan de Vries" returns two results: one about a chess tournament winner and one about a family bakery. Neither is related to financial crime.
- **What is being tested:** False positive avoidance. Common Dutch names return many search results; the agent must distinguish irrelevant hits from genuine adverse findings.
- **Why this scenario matters:** Jan de Vries is one of the most common Dutch names. If the agent flags every common-name result as adverse, it would generate massive false positive volumes that overwhelm compliance teams.
- **Expected output:** `result: "OK"`

#### Item 2: Clear fraud conviction (Hans Mueller)

- **Scenario:** Search for "Hans Mueller" returns two results: a court conviction for a EUR 2M fraud scheme involving money laundering, and a police arrest in connection with an international money laundering investigation. Both specifically name Hans Mueller of Den Haag.
- **What is being tested:** True positive detection. Clear, unambiguous adverse media about the specific person.
- **Why this scenario matters:** This is the core purpose of adverse media screening -- catching individuals with documented criminal financial activity. Missing this would be a direct compliance failure.
- **Expected output:** `result: "NOK"`

#### Item 3: Same name, different person (Jan de Vries)

- **Scenario:** Search for "Jan de Vries" returns results about a 72-year-old professor emeritus at Leiden University and a 65-year-old art historian appointed to a museum board. These are clearly different individuals.
- **What is being tested:** Disambiguation. The agent must recognize that search results about other people with the same name are not relevant.
- **Why this scenario matters:** Without disambiguation, common names would always trigger false positives. The agent must use contextual clues (age, profession, location) to determine relevance.
- **Expected output:** `result: "OK"`

#### Item 4: Ambiguous partial match (Peter van der Berg)

- **Scenario:** Search for "Peter van der Berg" returns one result about a "van der Berg" under investigation for tax evasion (first name not specified) and another about "Peter van der Berg" opening a restaurant. The tax evasion article could be about this person or someone else.
- **What is being tested:** Appropriate uncertainty. When results are ambiguous, the agent should flag for human review rather than making a definitive judgment.
- **Why this scenario matters:** In real-world screening, many results are ambiguous. The agent must not over-confidently dismiss potentially relevant findings, nor must it flag clearly irrelevant ones. PENDING_REVIEW is the correct response when the agent cannot determine relevance.
- **Expected output:** `result: "PENDING_REVIEW"`

#### Item 5: Empty results

- **Scenario:** Search for "Extremely Unique Name XYZ123" returns no results at all.
- **What is being tested:** Handling of no data. No search results means no adverse media was found.
- **Why this scenario matters:** Edge case ensuring the agent does not manufacture concerns from absence of data.
- **Expected output:** `result: "OK"`

### 6.5 Dataset: kyc-orchestrator-e2e (8 items)

**File:** `crew/evals/datasets/orchestrator_e2e.json`

#### Item 1: All pass

- **Scenario:** Identity MATCH, income VERIFIED (no risk indicators), risk list CLEAR (NOT_PEP, NOT_SANCTIONED), adverse media OK.
- **What is being tested:** The happy path. All checks passed, case should be approved.
- **Expected output:** `action: "APPROVED"`, `risk_classification: "LOW"`

#### Item 2: Identity mismatch

- **Scenario:** Identity MISMATCH, income VERIFIED, risk list CLEAR, adverse media OK.
- **What is being tested:** Escalation on identity failure. Even though everything else passes, identity mismatch requires human review.
- **Expected output:** `action: "ESCALATED"`, `risk_classification: "MEDIUM"`

#### Item 3: Sanctions hit

- **Scenario:** Identity MATCH, income VERIFIED, risk list HIT with SANCTIONED status (NOT_PEP), adverse media OK.
- **What is being tested:** Mandatory escalation for sanctions. This is the most critical test case in the entire dataset. Approving a sanctioned person is illegal under EU sanctions regulations.
- **Expected output:** `action: "ESCALATED"`, `risk_classification: "HIGH"`

#### Item 4: PEP only

- **Scenario:** Identity MATCH, income VERIFIED (with "Multiple income sources" indicator), risk list HIT with PEP status (NOT_SANCTIONED), adverse media OK.
- **What is being tested:** PEP requires Enhanced Due Diligence (escalation) even when the overall risk score is low. PEP status alone triggers Wwft Art. 8 obligations.
- **Expected output:** `action: "ESCALATED"`, `risk_classification: "LOW"`

#### Item 5: Income insufficient

- **Scenario:** Identity MATCH, income INSUFFICIENT with `income_requires_additional_documents: true`, risk list CLEAR, adverse media OK.
- **What is being tested:** The additional documents path. Income could not be verified, but there is no suspicion of fraud -- just missing evidence.
- **Expected output:** `action: "ADDITIONAL_DOCUMENTS_REQUIRED"`, `risk_classification: "MEDIUM"`

#### Item 6: Income suspicious

- **Scenario:** Identity MATCH, income SUSPICIOUS with risk indicators ["Income exceeds threshold", "No KVK registration"], risk list CLEAR, adverse media OK.
- **What is being tested:** Escalation on suspicious income. Risk indicators suggest potential money laundering.
- **Expected output:** `action: "ESCALATED"`, `risk_classification: "MEDIUM"`

#### Item 7: Multiple failures

- **Scenario:** Identity MISMATCH, income SUSPICIOUS (with "Income exceeds threshold" indicator), risk list HIT with SANCTIONED status, adverse media NOK.
- **What is being tested:** Worst case. Every single check failed. The agent must escalate with HIGH risk.
- **Expected output:** `action: "ESCALATED"`, `risk_classification: "HIGH"`

#### Item 8: Adverse media pending

- **Scenario:** Identity MATCH, income VERIFIED (no risk indicators), risk list CLEAR, adverse media PENDING_REVIEW.
- **What is being tested:** Escalation on uncertain adverse media. When adverse media screening is inconclusive, the case must be escalated for human review.
- **Expected output:** `action: "ESCALATED"`, `risk_classification: "LOW"`

### 6.6 Dataset Statistics

| Dataset | Items | Positive (pass) | Negative (fail) | Edge Cases | Coverage |
|---------|-------|-----------------|-----------------|------------|----------|
| Identity | 6 | 1 (MATCH) | 2 (MISMATCH) | 3 (PARTIAL_MATCH) | All 3 comparison_result values |
| Income | 8 | 2 (VERIFIED) | 3 (SUSPICIOUS) | 3 (INSUFFICIENT/UNREADABLE) | All 4 verification_result values + 6 risk indicator types |
| Adverse Media | 5 | 3 (OK) | 1 (NOK) | 1 (PENDING_REVIEW) | All 3 result values |
| Orchestrator | 8 | 1 (APPROVED) | 5 (ESCALATED) | 2 (ADDITIONAL_DOCS/pending) | All 3 action values + sanctions/PEP distinction |
| **Total** | **27** | **7** | **11** | **9** | |

---

## Part 7: LLM Judge Configuration

### Judge Model Selection

The judge model is resolved in the following order:

1. Explicit `model` parameter passed to `BedrockJudgeLLM(model=...)`
2. `EVAL_JUDGE_MODEL` environment variable
3. `MODEL` environment variable (same model used by the agents)
4. Default fallback: `us.anthropic.claude-3-5-sonnet-20241022-v2:0`

The model ID string is stripped of any `bedrock/` prefix (for compatibility with LiteLLM-style identifiers). The AWS region is resolved from `AWS_REGION_NAME`, `AWS_REGION`, or defaults to `us-east-1`.

The implementation is in `crew/evals/bedrock_judge.py`. `BedrockJudgeLLM` extends DeepEval's `DeepEvalBaseLLM` base class and wraps the boto3 Bedrock Converse API. It provides both synchronous `generate()` and async `a_generate()` methods (the async method falls back to synchronous, since the Bedrock SDK does not natively support async).

### Why Configurable

Using the same model for both agents and the judge is the simplest setup, but it introduces a potential blind-spot bias -- the same model that made the decision is now judging whether the decision was correct. It may be systematically blind to its own failure modes.

Using a different (typically stronger) model as the judge provides more objective evaluation, but increases cost and requires access to an additional model.

Teams choose per environment:

- **Dev:** Same model (fast iteration, minimal cost, acceptable bias risk)
- **Staging:** Stronger model (catch regressions before production, worth the additional cost)
- **Prod:** N/A -- offline evals run pre-deployment, not in production. Online evals are deterministic and do not use a judge model.

### Judge Prompt Design

All custom metrics (KYCComplianceMetric and RiskDetectionMetric) use structured prompts with:

- **Explicit scoring rubric:** Five levels (1.0, 0.75, 0.5, 0.25, 0.0) with concrete definitions for each level. This reduces scoring ambiguity -- the judge knows exactly what each score means.
- **Domain context:** Wwft rules are spelled out in the prompt for KYCComplianceMetric. The 8 specific risk indicators are listed for RiskDetectionMetric. The judge does not need prior knowledge of Dutch compliance law.
- **JSON-only response format:** The prompt ends with "Respond with ONLY a JSON object: `{\"score\": <float>, \"reason\": \"<explanation>\"}`". This makes parsing reliable.
- **Fallback to deterministic check:** If the LLM response cannot be parsed as JSON, or if no judge model is available, both custom metrics fall back to deterministic checks (exact action match for compliance, set overlap for risk indicators). This ensures evaluation always produces a score, even if the judge fails.
- **Temperature 0.0:** The Bedrock Converse API is called with `temperature: 0.0` to maximize judge consistency across runs. Evaluation should be as deterministic as possible.

---

## Part 8: How to Run Evals

### Online evals (automatic)

Online evals run automatically when `LANGFUSE_ENABLED=1` is set in the environment. No manual action is needed. Every time an agent callback executes, `run_online_evals()` is called with the appropriate stage name and task output. Scores appear in Langfuse attached to the trace.

To verify online evals are working: run a test case through the system, then check the Langfuse UI for boolean scores on the trace (e.g., `identity_schema_valid`, `risk_score_in_range`, `decision_rule_correct`).

If Langfuse is not available, `submit_scores()` silently skips submission and logs a debug message. Online eval failures never break the pipeline -- all scoring is wrapped in try/except.

### Offline evals

```bash
# Step 1: Seed golden datasets into Langfuse
python -m crew.evals.seed_datasets --all

# Step 2: Run evaluation against all datasets
python -m crew.evals.offline --dataset all --threshold 0.85

# Step 3: Run evaluation against a specific dataset
python -m crew.evals.offline --dataset kyc-identity-verification

# Step 4: List available datasets and their item counts
python -m crew.evals.offline --list-datasets

# Step 5: Skip specific frameworks if needed
python -m crew.evals.offline --dataset all --skip-ragas
python -m crew.evals.offline --dataset all --skip-deepeval

# Step 6: Output results to file
python -m crew.evals.offline --dataset all --output eval_results.json
```

Results are submitted to Langfuse as an experiment (named `kyc-offline-eval-{timestamp}`) and also printed to stdout as JSON. Check the Langfuse experiments view to compare results across runs.

### Interpreting Results

**Online eval scores (investigate immediately if 0):**

- **Schema validation = 0:** Agent produced malformed output. Check the comment field for which fields failed. Common causes: model drift producing unexpected enum values, prompt changes that altered output format.
- **Risk consistency = 0:** Bug in the scoring formula. The risk score does not match the classification range, or the breakdown does not sum correctly. This is almost always a code bug, not an LLM issue.
- **Decision-rule = 0:** The orchestrator violated Wwft rules. This is the most serious online eval failure. Check the comment field for what was expected vs. what was produced. Common causes: LLM ignoring instructions under ambiguous inputs, prompt regression, model version change.

**Offline eval scores (investigate if below threshold):**

- **TaskCompletion < 0.85:** Agent is struggling with the task format. It may not be producing complete outputs, or it may be missing required fields. Review the specific test cases that scored low.
- **KYCCompliance < 0.80:** Orchestrator is not following Wwft rules reliably. Check which specific rules are being violated. This may indicate the system prompt needs strengthening or the model needs more examples.
- **RiskDetection < 0.80:** Income agent is missing risk indicators. Check which indicators are being missed. The judge prompt lists 8 specific indicators -- the agent may need more explicit instructions for the ones it misses.
- **AgentGoalAccuracy = 0:** Agent completely failed to achieve its objective for a test case. Review the specific failing case to understand what went wrong.

---

## Document Version History

| Date | Change |
|------|--------|
| 2026-04-01 | Initial version -- evaluation framework design and implementation |
