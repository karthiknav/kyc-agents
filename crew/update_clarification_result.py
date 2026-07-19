import logging
import os
from datetime import datetime, timezone

import boto3

from crew.utils import parse_task_output

logger = logging.getLogger(__name__)


def update_clarification_result(task_output):
    """Persist the clarification resolution verdict to riskListScreening. Does not touch case status."""
    logger.info("update_clarification_result input: task_output=%s", task_output)
    task_output = parse_task_output(task_output)
    if task_output is None:
        logger.error("update_clarification_result: task_output is not valid JSON, skipping DB update")
        return

    case_id = task_output.get("case_id")
    verdict = task_output.get("verdict", "")
    reasoning = task_output.get("reasoning", "")

    if not case_id:
        logger.error("update_clarification_result: no case_id in output")
        return

    if verdict not in ("FALSE_POSITIVE", "CONFIRMED_MATCH"):
        logger.error("update_clarification_result: unexpected verdict=%s for case_id=%s", verdict, case_id)
        return

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    new_risk_result = "CLEAR" if verdict == "FALSE_POSITIVE" else "HIT"

    clarification_resolution = {
        "verdict": verdict,
        "reasoning": reasoning,
        "resolvedAt": now,
    }

    table_name = os.environ.get("KYC_CASES_TABLE", "kyc-cases")
    try:
        dynamodb = boto3.resource("dynamodb")
        table = dynamodb.Table(table_name)

        table.update_item(
            Key={"CaseId": case_id},
            UpdateExpression="SET #stages = if_not_exists(#stages, :empty_map)",
            ExpressionAttributeNames={"#stages": "stages"},
            ExpressionAttributeValues={":empty_map": {}},
        )
        table.update_item(
            Key={"CaseId": case_id},
            UpdateExpression="SET #stages.#screening = if_not_exists(#stages.#screening, :empty_map)",
            ExpressionAttributeNames={"#stages": "stages", "#screening": "screening"},
            ExpressionAttributeValues={":empty_map": {}},
        )
        table.update_item(
            Key={"CaseId": case_id},
            UpdateExpression="SET #stages.#screening.#risk = if_not_exists(#stages.#screening.#risk, :empty_map)",
            ExpressionAttributeNames={"#stages": "stages", "#screening": "screening", "#risk": "riskListScreening"},
            ExpressionAttributeValues={":empty_map": {}},
        )
        table.update_item(
            Key={"CaseId": case_id},
            UpdateExpression=(
                "SET #stages.#screening.#risk.#result = :result, "
                "#stages.#screening.#risk.#cres = :cres"
            ),
            ExpressionAttributeNames={
                "#stages": "stages",
                "#screening": "screening",
                "#risk": "riskListScreening",
                "#result": "result",
                "#cres": "clarificationResolution",
            },
            ExpressionAttributeValues={
                ":result": new_risk_result,
                ":cres": clarification_resolution,
            },
        )
        logger.info(
            "update_clarification_result success: case_id=%s, verdict=%s, riskListScreening.result=%s",
            case_id, verdict, new_risk_result,
        )
    except Exception as e:
        logger.exception("update_clarification_result DynamoDB error: %s", e)
