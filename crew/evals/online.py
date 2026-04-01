"""Online (real-time) deterministic evaluations for KYC agent outputs.

All functions return score dicts: {"name": str, "value": 0|1 or float, "comment": str}
Scores are submitted to Langfuse via submit_scores().
All scoring is wrapped in try/except — failures log warnings but never break the pipeline.
"""

import json
import logging
import os
from typing import Any

import boto3

logger = logging.getLogger(__name__)


# --- Schema Validation Scores ---

def score_identity_schema(task_output: dict) -> dict:
    """Validate identity verification agent output schema."""
    valid = True
    issues = []

    comparison_result = task_output.get("comparison_result", "")
    if comparison_result not in ("MATCH", "PARTIAL_MATCH", "MISMATCH"):
        valid = False
        issues.append(f"comparison_result '{comparison_result}' not in valid set")

    discrepancies = task_output.get("discrepancies")
    if not isinstance(discrepancies, list):
        valid = False
        issues.append("discrepancies is not a list")

    for field in ("comparison_summary", "documents_summary"):
        val = task_output.get(field, "")
        if not val or not isinstance(val, str) or len(val.strip()) == 0:
            valid = False
            issues.append(f"{field} is empty or missing")

    if not task_output.get("case_id"):
        valid = False
        issues.append("case_id missing")

    return {
        "name": "identity_schema_valid",
        "value": 1 if valid else 0,
        "comment": "Valid" if valid else "; ".join(issues),
    }


def score_income_schema(task_output: dict) -> dict:
    """Validate income verification agent output schema."""
    valid = True
    issues = []

    verification_result = task_output.get("verification_result", "")
    if verification_result not in ("VERIFIED", "INSUFFICIENT", "SUSPICIOUS", "UNREADABLE"):
        valid = False
        issues.append(f"verification_result '{verification_result}' not in valid set")

    income_source = task_output.get("income_source", "")
    valid_sources = ("employment", "self_employment", "business_ownership", "investments", "pension", "social_benefits", "unknown")
    if income_source not in valid_sources:
        valid = False
        issues.append(f"income_source '{income_source}' not in valid set")

    risk_indicators = task_output.get("risk_indicators")
    if not isinstance(risk_indicators, list):
        valid = False
        issues.append("risk_indicators is not a list")

    income_details = task_output.get("income_details")
    if income_details and isinstance(income_details, dict):
        for key in ("employer_or_source", "monthly_income_eur"):
            if key not in income_details:
                valid = False
                issues.append(f"income_details missing '{key}'")

    additional_docs = task_output.get("additional_documents_needed")
    if additional_docs is not None and not isinstance(additional_docs, list):
        valid = False
        issues.append("additional_documents_needed is not a list")

    if not task_output.get("case_id"):
        valid = False
        issues.append("case_id missing")

    return {
        "name": "income_schema_valid",
        "value": 1 if valid else 0,
        "comment": "Valid" if valid else "; ".join(issues),
    }


def score_screening_schema(task_output: dict) -> dict:
    """Validate risk list screening agent output schema."""
    valid = True
    issues = []

    result = task_output.get("result", "")
    if result not in ("CLEAR", "HIT", "ERROR"):
        valid = False
        issues.append(f"result '{result}' not in valid set")

    pep_status = task_output.get("pepStatus", "")
    if pep_status not in ("NOT_PEP", "PEP", "UNKNOWN"):
        valid = False
        issues.append(f"pepStatus '{pep_status}' not in valid set")

    sanctions_status = task_output.get("sanctionsStatus", "")
    if sanctions_status not in ("NOT_SANCTIONED", "SANCTIONED", "UNKNOWN"):
        valid = False
        issues.append(f"sanctionsStatus '{sanctions_status}' not in valid set")

    datasets_matched = task_output.get("datasetsMatched")
    if not isinstance(datasets_matched, list):
        valid = False
        issues.append("datasetsMatched is not a list")

    if not task_output.get("case_id"):
        valid = False
        issues.append("case_id missing")

    return {
        "name": "screening_schema_valid",
        "value": 1 if valid else 0,
        "comment": "Valid" if valid else "; ".join(issues),
    }


def score_adverse_media_schema(task_output: dict) -> dict:
    """Validate adverse media agent output schema."""
    valid = True
    issues = []

    result = task_output.get("result", "")
    if result not in ("OK", "NOK", "PENDING_REVIEW"):
        valid = False
        issues.append(f"result '{result}' not in valid set")

    summary = task_output.get("summary", "")
    if not summary or not isinstance(summary, str) or len(summary.strip()) == 0:
        valid = False
        issues.append("summary is empty or missing")

    if not task_output.get("case_id"):
        valid = False
        issues.append("case_id missing")

    return {
        "name": "adverse_media_schema_valid",
        "value": 1 if valid else 0,
        "comment": "Valid" if valid else "; ".join(issues),
    }


def score_orchestrator_schema(task_output: dict) -> dict:
    """Validate orchestrator agent output schema."""
    valid = True
    issues = []

    action = task_output.get("action", "")
    if action not in ("APPROVED", "ESCALATED", "ADDITIONAL_DOCUMENTS_REQUIRED"):
        valid = False
        issues.append(f"action '{action}' not in valid set")

    if not task_output.get("case_id"):
        valid = False
        issues.append("case_id missing")

    reason = task_output.get("reason")
    if not isinstance(reason, list):
        valid = False
        issues.append("reason is not a list")

    recommendation = task_output.get("recommendation_summary", "")
    if not recommendation or len(str(recommendation).strip()) == 0:
        valid = False
        issues.append("recommendation_summary is empty")

    return {
        "name": "orchestrator_schema_valid",
        "value": 1 if valid else 0,
        "comment": "Valid" if valid else "; ".join(issues),
    }


# --- Risk Score Consistency ---

def score_risk_consistency(risk_score: int, risk_classification: str, breakdown: list) -> list[dict]:
    """Validate risk score is consistent with classification and breakdown sums correctly."""
    scores = []

    # Check score is in correct range for classification
    in_range = False
    if risk_classification == "LOW" and 0 <= risk_score <= 30:
        in_range = True
    elif risk_classification == "MEDIUM" and 31 <= risk_score <= 60:
        in_range = True
    elif risk_classification == "HIGH" and 61 <= risk_score <= 100:
        in_range = True

    scores.append({
        "name": "risk_score_in_range",
        "value": 1 if in_range else 0,
        "comment": f"score={risk_score}, classification={risk_classification}, in_range={in_range}",
    })

    # Check breakdown sums to total
    if breakdown and isinstance(breakdown, list):
        # Parse the TOTAL line from breakdown (format: "TOTAL: {score}/100 = {classification}")
        total_line = [line for line in breakdown if isinstance(line, str) and "TOTAL:" in line]
        breakdown_matches = True
        if total_line:
            try:
                # Extract the number after "TOTAL: "
                total_str = total_line[0].split("TOTAL:")[1].split("/")[0].strip()
                breakdown_total = int(total_str)
                if breakdown_total != risk_score:
                    breakdown_matches = False
            except (ValueError, IndexError):
                breakdown_matches = False

        scores.append({
            "name": "risk_breakdown_sums",
            "value": 1 if breakdown_matches else 0,
            "comment": f"Breakdown total matches score={risk_score}: {breakdown_matches}",
        })

    return scores


# --- Decision-Rule Alignment ---

def score_decision_rules(case_id: str, action: str) -> dict:
    """Verify orchestrator action aligns with Wwft business rules given stage results.

    Reads stage results from DynamoDB to determine expected action.
    """
    table_name = os.environ.get("KYC_CASES_TABLE", "kyc-cases")
    try:
        dynamodb = boto3.resource("dynamodb")
        table = dynamodb.Table(table_name)
        response = table.get_item(Key={"CaseId": case_id})
        item = response.get("Item", {})
        stages = item.get("stages", {})
    except Exception as e:
        logger.warning("score_decision_rules: failed to read DynamoDB for case_id=%s: %s", case_id, e)
        return {"name": "decision_rule_correct", "value": 0, "comment": f"DynamoDB read failed: {e}"}

    # Extract stage results
    identity = stages.get("identityVerification", {})
    identity_result = (identity.get("result") or "").upper()

    income = stages.get("incomeVerification", {})
    income_result = (income.get("result") or "").upper()
    income_requires_docs = income.get("requiresAdditionalDocuments", False)
    income_risk_indicators = income.get("riskIndicators") or []

    screening = stages.get("screening", {})
    risk_list = screening.get("riskListScreening", {})
    risk_result = (risk_list.get("result") or "").upper()
    sanctions_status = (risk_list.get("sanctionsStatus") or "").upper()

    adverse = screening.get("adverseMedia", {})
    adverse_result = (adverse.get("result") or "").upper()

    # Determine expected action per Wwft rules
    expected = None
    reason = ""

    # Rule: sanctions HIT -> must ESCALATE
    if risk_result == "HIT" and sanctions_status == "SANCTIONED":
        expected = "ESCALATED"
        reason = "Sanctions HIT requires ESCALATED"
    # Rule: MISMATCH -> must ESCALATE
    elif identity_result == "MISMATCH":
        expected = "ESCALATED"
        reason = "Identity MISMATCH requires ESCALATED"
    # Rule: SUSPICIOUS income -> must ESCALATE
    elif income_result == "SUSPICIOUS":
        expected = "ESCALATED"
        reason = "Suspicious income requires ESCALATED"
    # Rule: adverse media NOK -> must ESCALATE
    elif adverse_result == "NOK":
        expected = "ESCALATED"
        reason = "Adverse media NOK requires ESCALATED"
    # Rule: income INSUFFICIENT + requires docs -> ADDITIONAL_DOCUMENTS_REQUIRED
    elif income_result == "INSUFFICIENT" and income_requires_docs:
        expected = "ADDITIONAL_DOCUMENTS_REQUIRED"
        reason = "Income INSUFFICIENT + requires_additional_documents"
    # Rule: income UNREADABLE -> ADDITIONAL_DOCUMENTS_REQUIRED
    elif income_result == "UNREADABLE":
        expected = "ADDITIONAL_DOCUMENTS_REQUIRED"
        reason = "Income UNREADABLE requires additional documents"
    # Rule: all pass -> APPROVED (but PEP may override to ESCALATED, which is also acceptable)
    elif (identity_result == "MATCH" and income_result == "VERIFIED"
          and not income_risk_indicators and risk_result == "CLEAR" and adverse_result == "OK"):
        expected = "APPROVED"
        reason = "All checks pass"
    # Rule: PEP hit (no sanctions) can be ESCALATED (EDD) — acceptable
    elif risk_result == "HIT":
        # PEP without sanctions — ESCALATED is acceptable for EDD
        expected = "ESCALATED"
        reason = "PEP HIT requires ESCALATED for EDD"
    else:
        # Default: ESCALATED is the safe fallback
        expected = "ESCALATED"
        reason = "Default conservative: ESCALATED"

    # Check if action matches expected
    correct = (action == expected)
    # Special case: PEP-only cases — APPROVED is also acceptable if score is LOW
    # But most banks escalate PEP, so we accept both
    if expected == "APPROVED" and action == "ESCALATED" and risk_result == "HIT":
        correct = True  # PEP escalation is always acceptable

    return {
        "name": "decision_rule_correct",
        "value": 1 if correct else 0,
        "comment": f"expected={expected} ({reason}), got={action}, correct={correct}",
    }


# --- Langfuse Score Submission ---

def submit_scores(scores: list[dict], trace_id: str | None = None) -> None:
    """Submit scores to Langfuse. Silently skips if Langfuse is not available."""
    try:
        from langfuse import get_client
        lf = get_client()
    except Exception:
        logger.debug("submit_scores: Langfuse not available, skipping score submission")
        return

    for score in scores:
        try:
            kwargs = {
                "name": score["name"],
                "value": score["value"],
            }
            if trace_id:
                kwargs["trace_id"] = trace_id
            if "comment" in score:
                kwargs["comment"] = score["comment"][:200]  # Langfuse metadata limit

            lf.create_score(**kwargs)
        except Exception as e:
            logger.warning("submit_scores: failed to submit score %s: %s", score.get("name"), e)


def run_online_evals(stage: str, task_output: dict, case_id: str | None = None,
                     risk_score: int | None = None, risk_classification: str | None = None,
                     risk_breakdown: list | None = None, action: str | None = None,
                     trace_id: str | None = None) -> None:
    """Run all applicable online evals for a given stage and submit scores to Langfuse.

    This is the main entry point called from each callback.
    """
    try:
        scores = []

        if stage == "identity":
            scores.append(score_identity_schema(task_output))
        elif stage == "income":
            scores.append(score_income_schema(task_output))
        elif stage == "screening":
            scores.append(score_screening_schema(task_output))
        elif stage == "adverse_media":
            scores.append(score_adverse_media_schema(task_output))
        elif stage == "orchestrator":
            scores.append(score_orchestrator_schema(task_output))
            if risk_score is not None and risk_classification:
                scores.extend(score_risk_consistency(risk_score, risk_classification, risk_breakdown or []))
            if case_id and action:
                scores.append(score_decision_rules(case_id, action))

        if scores:
            submit_scores(scores, trace_id=trace_id)
            logger.info("Online evals for stage=%s: %s", stage,
                       {s["name"]: s["value"] for s in scores})
    except Exception as e:
        logger.warning("run_online_evals failed for stage=%s: %s (non-fatal)", stage, e)
