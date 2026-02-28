import json
import logging
import os
from datetime import datetime, timezone

import boto3

logger = logging.getLogger(__name__)


def update_screening_result(task_output):
    """Update the screening stage in the case document according to the schema."""
    logger.info("update_screening_result input: task_output=%s", task_output)
    # task_output may be TaskOutput object or dict or JSON string from agent
    if hasattr(task_output, "raw"):
        task_output = task_output.raw
    if isinstance(task_output, str):
        try:
            task_output = json.loads(task_output)
        except json.JSONDecodeError:
            logger.error("update_screening_result: task_output is not valid JSON")
            return
    case_id = task_output.get("case_id")
    analysis_result = task_output.get("analysis_result")
    analysis_summary = task_output.get("analysis_summary")
    if not case_id or not analysis_result or not analysis_summary:
        logger.info("Results incomplete: case_id=%s, analysis_result=%s, analysis_summary=%s", case_id, analysis_result, analysis_summary)
        return

    # Map analysis_result (screening ok | screening not ok | ambiguous) to schema status (OK | NOT_OK | AMBIGUOUS)
    result_map = {
        "screening ok": "OK",
        "screening not ok": "NOK",
        "ambiguous": "AMBIGUOUS",
        "ok": "OK",
        "nok": "NOK",
        "OK": "OK",
        "NOK": "NOK",
        "AMBIGUOUS": "AMBIGUOUS",
    }
    status = result_map.get(analysis_result.lower(), "AMBIGUOUS")
    # finalDecision: LOGICALLY DERIVED from screening result
    final_decision_map = {
        "OK": "OK",
        "NOK": "NOT_OK",
        "AMBIGUOUS": "PENDING_REVIEW",
    }
    final_decision = final_decision_map.get(status, "PENDING_REVIEW")

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Build the screening stage object per schema
    screening_stage = {
        "status": status,
        "updatedAt": now,
        "summary": analysis_summary,
    }

    table_name = os.environ.get("KYC_CASES_TABLE", "kyc-cases")
    try:
        dynamodb = boto3.resource("dynamodb")
        table = dynamodb.Table(table_name)
        # Step 1: ensure #stages map exists (create empty if not)
        table.update_item(
            Key={"CaseId": case_id},
            UpdateExpression="SET #stages = if_not_exists(#stages, :empty_map)",
            ExpressionAttributeNames={"#stages": "stages"},
            ExpressionAttributeValues={":empty_map": {}},
        )
        # Step 2: set #stages.screening with status, summary, updatedAt
        table.update_item(
            Key={"CaseId": case_id},
            UpdateExpression="SET #stages.#screening = :screening",
            ExpressionAttributeNames={
                "#stages": "stages",
                "#screening": "screening",
            },
            ExpressionAttributeValues={":screening": screening_stage},
        )
        logger.info("update_screening_result success: case_id=%s, status=%s, final_decision=%s", case_id, status, final_decision)
    except Exception as e:
        logger.exception("update_screening_result error: %s", e)
