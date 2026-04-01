import json
import logging
import os
from datetime import datetime, timezone

import boto3

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Deterministic risk scoring
#
# Replaces the LLM-guessed score with a weighted, auditable calculation.
# Each factor contributes points based on the stage result. The sum
# determines the risk_score (0-100) and risk_classification (LOW/MEDIUM/HIGH).
#
#   Factor              Weight   LOW (0 pts)          MEDIUM              HIGH (max pts)
#   ─────────────────── ──────── ──────────────────── ─────────────────── ────────────────
#   Identity result       30     MATCH: 0             PARTIAL_MATCH: 15   MISMATCH: 30
#   Income result         25     VERIFIED (0 flags):0 VERIFIED (flags):12 INSUF/SUSP/UNREAD: 25
#   PEP / Sanctions       30     CLEAR: 0             PEP only: 15        SANCTIONS: 30
#   Adverse media         15     OK: 0                PENDING_REVIEW: 8   NOK: 15
#
#   Classification:  0-30 = LOW,  31-60 = MEDIUM,  61-100 = HIGH
# ---------------------------------------------------------------------------

_IDENTITY_SCORES = {"MATCH": 0, "PARTIAL_MATCH": 15, "MISMATCH": 30}
_INCOME_SCORES = {"VERIFIED": 0, "INSUFFICIENT": 25, "SUSPICIOUS": 25, "UNREADABLE": 25}
_INCOME_VERIFIED_WITH_FLAGS = 12  # VERIFIED but has risk_indicators
_PEP_SANCTIONS_SCORES = {"CLEAR": 0, "PEP_ONLY": 15, "SANCTIONED": 30}
_ADVERSE_MEDIA_SCORES = {"OK": 0, "PENDING_REVIEW": 8, "NOK": 15}


def _compute_risk_score(case_id: str) -> tuple[int, str, list[str]]:
    """Read prior stage results from DynamoDB and compute a deterministic risk score.

    Returns (risk_score, risk_classification, score_breakdown).
    """
    table_name = os.environ.get("KYC_CASES_TABLE", "kyc-cases")
    breakdown = []
    try:
        dynamodb = boto3.resource("dynamodb")
        table = dynamodb.Table(table_name)
        response = table.get_item(Key={"CaseId": case_id})
        item = response.get("Item", {})
        stages = item.get("stages", {})
    except Exception as e:
        logger.exception("_compute_risk_score: failed to read stages for case_id=%s", case_id)
        return 50, "MEDIUM", [f"Could not read stages from DynamoDB: {e}"]

    score = 0

    # --- Identity (weight: 30) ---
    identity = stages.get("identityVerification", {})
    identity_result = (identity.get("result") or "").upper()
    identity_pts = _IDENTITY_SCORES.get(identity_result, 15)  # default MEDIUM if unknown
    score += identity_pts
    breakdown.append(f"Identity ({identity_result}): +{identity_pts}/30")

    # --- Income (weight: 25) ---
    income = stages.get("incomeVerification", {})
    income_result = (income.get("result") or "").upper()
    income_risk_indicators = income.get("riskIndicators") or []
    if income_result == "VERIFIED" and income_risk_indicators:
        income_pts = _INCOME_VERIFIED_WITH_FLAGS
    else:
        income_pts = _INCOME_SCORES.get(income_result, 12)  # default MEDIUM if unknown
    score += income_pts
    indicator_note = f" ({len(income_risk_indicators)} flags)" if income_risk_indicators else ""
    breakdown.append(f"Income ({income_result}{indicator_note}): +{income_pts}/25")

    # --- PEP / Sanctions (weight: 30) ---
    screening = stages.get("screening", {})
    risk_list = screening.get("riskListScreening", {})
    risk_result = (risk_list.get("result") or "").upper()
    sanctions_status = (risk_list.get("sanctionsStatus") or "").upper()
    pep_status = (risk_list.get("pepStatus") or "").upper()

    if risk_result == "HIT" and sanctions_status in ("SANCTIONED",):
        pep_sanctions_pts = _PEP_SANCTIONS_SCORES["SANCTIONED"]
    elif risk_result == "HIT" and pep_status in ("PEP",):
        pep_sanctions_pts = _PEP_SANCTIONS_SCORES["PEP_ONLY"]
    elif risk_result == "CLEAR":
        pep_sanctions_pts = _PEP_SANCTIONS_SCORES["CLEAR"]
    else:
        pep_sanctions_pts = 15  # default MEDIUM if unknown
    score += pep_sanctions_pts
    breakdown.append(f"PEP/Sanctions ({risk_result}, pep={pep_status}, sanctions={sanctions_status}): +{pep_sanctions_pts}/30")

    # --- Adverse Media (weight: 15) ---
    adverse = screening.get("adverseMedia", {})
    adverse_result = (adverse.get("result") or "").upper()
    adverse_pts = _ADVERSE_MEDIA_SCORES.get(adverse_result, 8)  # default MEDIUM if unknown
    score += adverse_pts
    breakdown.append(f"Adverse Media ({adverse_result}): +{adverse_pts}/15")

    # --- Clamp and classify ---
    score = max(0, min(100, score))
    if score <= 30:
        classification = "LOW"
    elif score <= 60:
        classification = "MEDIUM"
    else:
        classification = "HIGH"

    breakdown.append(f"TOTAL: {score}/100 = {classification}")
    logger.info("_compute_risk_score case_id=%s: score=%s, classification=%s, breakdown=%s",
                case_id, score, classification, breakdown)
    return score, classification, breakdown


def update_orchestrator_result(task_output):
    """Persist the orchestrator's final decision to DynamoDB."""
    logger.info("update_orchestrator_result input: task_output=%s", task_output)
    if hasattr(task_output, "raw"):
        task_output = task_output.raw
    if isinstance(task_output, str):
        try:
            task_output = json.loads(task_output)
        except json.JSONDecodeError:
            logger.error("update_orchestrator_result: task_output is not valid JSON")
            return

    case_id = task_output.get("case_id")
    action = task_output.get("action", "")
    decision = task_output.get("decision", "")
    reason = task_output.get("reason", [])
    recommendation_summary = task_output.get("recommendation_summary", "")

    if not case_id:
        logger.error("update_orchestrator_result: no case_id in output")
        return

    # Compute deterministic risk score from prior stage results in DynamoDB
    risk_score, risk_classification, score_breakdown = _compute_risk_score(case_id)
    additional_documents_needed = task_output.get("additional_documents_needed", [])

    # Only persist a final case status for terminal actions
    if action not in ("APPROVED", "ESCALATED", "ADDITIONAL_DOCUMENTS_REQUIRED"):
        logger.info(
            "update_orchestrator_result: non-terminal action=%s for case_id=%s — skipping status update",
            action, case_id,
        )
        return

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Map action to case-level status
    if action == "APPROVED":
        case_status = "APPROVED"
    elif action == "ADDITIONAL_DOCUMENTS_REQUIRED":
        case_status = "ADDITIONAL_DOCUMENTS_REQUESTED"
    else:
        case_status = "PENDING_HUMAN_REVIEW"

    orchestrator_stage = {
        "status": action,
        "decision": decision,
        "reason": reason if isinstance(reason, list) else [str(reason)],
        "recommendation_summary": recommendation_summary,
        "risk_classification": risk_classification,
        "risk_score": risk_score,
        "risk_score_breakdown": score_breakdown,
        "additional_documents_needed": additional_documents_needed if isinstance(additional_documents_needed, list) else [],
        "decidedAt": now,
    }

    table_name = os.environ.get("KYC_CASES_TABLE", "kyc-cases")
    try:
        dynamodb = boto3.resource("dynamodb")
        table = dynamodb.Table(table_name)

        # Update top-level case status
        table.update_item(
            Key={"CaseId": case_id},
            UpdateExpression="SET #status = :status",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":status": case_status},
        )

        # Ensure stages map exists, then write orchestrator sub-stage
        table.update_item(
            Key={"CaseId": case_id},
            UpdateExpression="SET #stages = if_not_exists(#stages, :empty_map)",
            ExpressionAttributeNames={"#stages": "stages"},
            ExpressionAttributeValues={":empty_map": {}},
        )
        table.update_item(
            Key={"CaseId": case_id},
            UpdateExpression="SET #stages.#orchestrator = :orchestrator",
            ExpressionAttributeNames={
                "#stages": "stages",
                "#orchestrator": "orchestrator",
            },
            ExpressionAttributeValues={":orchestrator": orchestrator_stage},
        )
        logger.info(
            "update_orchestrator_result success: case_id=%s, case_status=%s, action=%s",
            case_id, case_status, action,
        )
    except Exception as e:
        logger.exception("update_orchestrator_result DynamoDB error: %s", e)
        return

    # Online evals: schema + risk consistency + decision-rule alignment
    try:
        from crew.evals.online import run_online_evals
        run_online_evals(
            stage="orchestrator",
            task_output=task_output,
            case_id=case_id,
            risk_score=risk_score,
            risk_classification=risk_classification,
            risk_breakdown=score_breakdown,
            action=action,
        )
    except Exception:
        logger.debug("Online eval scoring skipped (orchestrator)", exc_info=True)
