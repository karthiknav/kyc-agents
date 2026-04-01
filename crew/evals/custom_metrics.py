"""Custom DeepEval metrics for KYC agent evaluation.

KYCComplianceMetric — evaluates orchestrator Wwft rule adherence
RiskDetectionMetric — evaluates income agent risk indicator completeness
"""

import logging
from typing import Optional

from deepeval.metrics import BaseMetric
from deepeval.test_case import LLMTestCase

logger = logging.getLogger(__name__)


class KYCComplianceMetric(BaseMetric):
    """Evaluate whether the orchestrator correctly applied Dutch Wwft rules.

    Uses LLM-as-judge to assess if the decision (APPROVED/ESCALATED/ADDITIONAL_DOCUMENTS_REQUIRED)
    is correct given the 4 stage results.
    """

    def __init__(self, model=None, threshold: float = 0.8):
        self.threshold = threshold
        self.model = model
        self.score = 0.0
        self.reason = ""
        self.success = False

    def measure(self, test_case: LLMTestCase) -> float:
        prompt = f"""You are a Dutch KYC compliance auditor evaluating an AI agent's decision.

The agent received these verification results:
{test_case.input}

The agent produced this decision:
{test_case.actual_output}

The expected correct decision was:
{test_case.expected_output}

Evaluate the agent's decision against Dutch Wwft (Anti-Money Laundering Act) rules:
1. Sanctions HIT must ALWAYS result in ESCALATED (no discretion — EU law)
2. PEP match must ALWAYS result in ESCALATED (Enhanced Due Diligence required under Wwft Art. 8)
3. All checks passing (MATCH + VERIFIED + CLEAR + OK) should result in APPROVED
4. Income INSUFFICIENT with additional documents needed should result in ADDITIONAL_DOCUMENTS_REQUIRED
5. Identity MISMATCH or SUSPICIOUS income should result in ESCALATED
6. Risk classification must be consistent: LOW (0-30), MEDIUM (31-60), HIGH (61-100)

Score from 0.0 to 1.0:
- 1.0: Decision is correct AND all Wwft rules properly applied AND reasoning is complete
- 0.75: Decision is correct but reasoning misses some factors
- 0.5: Decision is correct but risk classification is wrong
- 0.25: Decision is wrong but shows partial understanding
- 0.0: Decision violates Wwft rules (e.g., approved a sanctions hit)

Respond with ONLY a JSON object: {{"score": <float>, "reason": "<explanation>"}}"""

        try:
            if self.model:
                response = self.model.generate(prompt)
            else:
                # Fallback: deterministic check if no LLM available
                return self._deterministic_check(test_case)

            import json
            parsed = json.loads(response)
            self.score = float(parsed.get("score", 0.0))
            self.reason = parsed.get("reason", "")
        except Exception as e:
            logger.warning("KYCComplianceMetric LLM judge failed, falling back to deterministic: %s", e)
            return self._deterministic_check(test_case)

        self.success = self.score >= self.threshold
        return self.score

    def _deterministic_check(self, test_case: LLMTestCase) -> float:
        """Fallback deterministic compliance check."""
        try:
            import json
            expected = json.loads(test_case.expected_output) if isinstance(test_case.expected_output, str) else test_case.expected_output
            actual = json.loads(test_case.actual_output) if isinstance(test_case.actual_output, str) else test_case.actual_output

            expected_action = expected.get("action", "")
            actual_action = actual.get("action", "")

            if expected_action == actual_action:
                self.score = 1.0
                self.reason = "Action matches expected"
            else:
                self.score = 0.0
                self.reason = f"Expected {expected_action}, got {actual_action}"
        except Exception as e:
            self.score = 0.0
            self.reason = f"Parse error: {e}"

        self.success = self.score >= self.threshold
        return self.score

    async def a_measure(self, test_case: LLMTestCase) -> float:
        return self.measure(test_case)

    def is_successful(self) -> bool:
        return self.success

    @property
    def __name__(self):
        return "KYC Compliance (Wwft)"


class RiskDetectionMetric(BaseMetric):
    """Evaluate whether the income agent identified all applicable risk indicators.

    Uses LLM-as-judge to assess completeness of red flag detection per Wwft rules.
    """

    def __init__(self, model=None, threshold: float = 0.8):
        self.threshold = threshold
        self.model = model
        self.score = 0.0
        self.reason = ""
        self.success = False

    def measure(self, test_case: LLMTestCase) -> float:
        prompt = f"""You are a Dutch KYC risk assessment auditor evaluating an AI agent's risk detection.

The agent analyzed this income verification input:
{test_case.input}

The agent identified these risk indicators:
{test_case.actual_output}

The expected risk indicators were:
{test_case.expected_output}

Evaluate completeness of risk detection per Dutch Wwft rules:
1. Income > EUR 10,000/month from standard employment — should be flagged
2. Missing Dutch KVK registration for employer — should be flagged
3. Missing Dutch loonheffingennummer (wage tax number) — should be flagged
4. Document older than 3 months (salary slip/bank statement) — should be flagged
5. Cash deposits > EUR 15,000 — should be flagged (Wwft Art. 16)
6. Name on document doesn't match applicant — should be flagged
7. Temporary contract with unusually high salary — should be flagged
8. Transfers from high-risk jurisdictions — should be flagged

Score from 0.0 to 1.0:
- 1.0: All applicable indicators identified, no false positives
- 0.75: Most indicators found, 1 minor miss
- 0.5: Some indicators found, missed important ones
- 0.25: Few indicators found
- 0.0: Failed to identify obvious risk indicators

Respond with ONLY a JSON object: {{"score": <float>, "reason": "<explanation>"}}"""

        try:
            if self.model:
                response = self.model.generate(prompt)
            else:
                return self._deterministic_check(test_case)

            import json
            parsed = json.loads(response)
            self.score = float(parsed.get("score", 0.0))
            self.reason = parsed.get("reason", "")
        except Exception as e:
            logger.warning("RiskDetectionMetric LLM judge failed, falling back to deterministic: %s", e)
            return self._deterministic_check(test_case)

        self.success = self.score >= self.threshold
        return self.score

    def _deterministic_check(self, test_case: LLMTestCase) -> float:
        """Fallback deterministic risk indicator check."""
        try:
            import json
            expected = json.loads(test_case.expected_output) if isinstance(test_case.expected_output, str) else test_case.expected_output
            actual = json.loads(test_case.actual_output) if isinstance(test_case.actual_output, str) else test_case.actual_output

            expected_indicators = set(str(i).lower() for i in expected.get("risk_indicators", []))
            actual_indicators = set(str(i).lower() for i in actual.get("risk_indicators", []))

            if not expected_indicators:
                # No indicators expected — check none were falsely added
                self.score = 1.0 if not actual_indicators else 0.5
            else:
                # Check overlap
                found = len(expected_indicators & actual_indicators)
                self.score = found / len(expected_indicators) if expected_indicators else 0.0

            self.reason = f"Found {len(actual_indicators)} of {len(expected_indicators)} expected indicators"
        except Exception as e:
            self.score = 0.0
            self.reason = f"Parse error: {e}"

        self.success = self.score >= self.threshold
        return self.score

    async def a_measure(self, test_case: LLMTestCase) -> float:
        return self.measure(test_case)

    def is_successful(self) -> bool:
        return self.success

    @property
    def __name__(self):
        return "Risk Detection (Wwft)"
