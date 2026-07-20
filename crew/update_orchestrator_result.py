import logging
import os
from datetime import datetime, timezone

import boto3

from crew.utils import parse_task_output

logger = logging.getLogger(__name__)


def update_orchestrator_result(task_output):
    """Persist the orchestrator's final decision to DynamoDB."""
    logger.info("update_orchestrator_result input: task_output=%s", task_output)
    task_output = parse_task_output(task_output)
    if task_output is None:
        logger.error("update_orchestrator_result: task_output is not valid JSON, skipping DB update")
        return

    case_id = task_output.get("case_id")
    action = task_output.get("action", "")
    decision = task_output.get("decision", "")
    reason = task_output.get("reason", [])
    recommendation_summary = task_output.get("recommendation_summary", "")
    risk_tier = task_output.get("risk_tier", "")
    risk_confidence = task_output.get("confidence")
    scoring_id = task_output.get("scoring_id", "")

    if not case_id:
        logger.error("update_orchestrator_result: no case_id in output")
        return

    # Only persist a final case status for terminal actions
    if action not in ("APPROVED", "ESCALATED"):
        logger.info(
            "update_orchestrator_result: non-terminal action=%s for case_id=%s — skipping status update",
            action, case_id,
        )
        return

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    case_status = "APPROVED" if action == "APPROVED" else "PENDING_HUMAN_REVIEW"

    orchestrator_stage = {
        "status": action,
        "decision": decision,
        "reason": reason if isinstance(reason, list) else [str(reason)],
        "recommendation_summary": recommendation_summary,
        "decidedAt": now,
        "mlRiskTier": risk_tier,
        "mlRiskConfidence": risk_confidence,
        "mlScoringId": scoring_id,
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
