import logging
import os
from datetime import datetime, timezone

import boto3

from crew.utils import parse_task_output

logger = logging.getLogger(__name__)


def update_override_result(task_output):
    """Persist the override validation verdict to DynamoDB."""
    logger.info("update_override_result input: task_output=%s", task_output)
    task_output = parse_task_output(task_output)
    if task_output is None:
        logger.error("update_override_result: task_output is not valid JSON, skipping DB update")
        return

    case_id = task_output.get("case_id")
    verdict = task_output.get("override_verdict", "")
    reasoning = task_output.get("reasoning", "")
    risk_flags_evaluated = task_output.get("risk_flags_evaluated", [])
    analyst_comments = task_output.get("analyst_comments", "")

    if not case_id:
        logger.error("update_override_result: no case_id in output")
        return

    if verdict not in ("APPROVED", "REJECTED"):
        logger.error("update_override_result: unexpected verdict=%s for case_id=%s", verdict, case_id)
        return

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    override_stage = {
        "verdict": verdict,
        "reasoning": reasoning,
        "riskFlagsEvaluated": risk_flags_evaluated if isinstance(risk_flags_evaluated, list) else [],
        "analystComments": analyst_comments,
        "reviewedAt": now,
    }

    # APPROVED → case moves to APPROVED; REJECTED → back to PENDING_HUMAN_REVIEW
    new_case_status = "APPROVED" if verdict == "APPROVED" else "PENDING_HUMAN_REVIEW"

    table_name = os.environ.get("KYC_CASES_TABLE", "kyc-cases")
    try:
        dynamodb = boto3.resource("dynamodb")
        table = dynamodb.Table(table_name)

        table.update_item(
            Key={"CaseId": case_id},
            UpdateExpression="SET #status = :status",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":status": new_case_status},
        )

        table.update_item(
            Key={"CaseId": case_id},
            UpdateExpression="SET #stages = if_not_exists(#stages, :empty_map)",
            ExpressionAttributeNames={"#stages": "stages"},
            ExpressionAttributeValues={":empty_map": {}},
        )
        table.update_item(
            Key={"CaseId": case_id},
            UpdateExpression="SET #stages.#override = :override",
            ExpressionAttributeNames={
                "#stages": "stages",
                "#override": "overrideReview",
            },
            ExpressionAttributeValues={":override": override_stage},
        )
        logger.info(
            "update_override_result success: case_id=%s, verdict=%s, new_status=%s",
            case_id, verdict, new_case_status,
        )
    except Exception as e:
        logger.exception("update_override_result DynamoDB error: %s", e)
