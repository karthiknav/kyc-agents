import json
import os
import logging
import secrets
import uuid
from datetime import datetime

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

AGENTCORE_QUALIFIER = "DEFAULT"
PROCESSING_STATUS = "PROCESSING"


def _uuid34() -> str:
    """Return a 34-character unique id (hex)."""
    # uuid4().hex -> 32 chars, token_hex(1) -> 2 chars
    return uuid.uuid4().hex + secrets.token_hex(1)


def _invoke_agent_fire_and_forget(agentcore_client, agent_arn: str, payload: dict) -> None:
    """Invoke Bedrock AgentCore runtime without waiting for any response."""
    case_id = payload.get("caseId", "unknown")
    case_id = case_id.strip() if isinstance(case_id, str) else str(case_id)
    runtime_session_id = f"kyc-case-{case_id}-{_uuid34()}"

    # Invoke AgentCore (this still waits for headers, <150ms)
    boto3_response = agentcore_client.invoke_agent_runtime(
        agentRuntimeArn=agent_arn,
        runtimeSessionId=runtime_session_id,
        qualifier=AGENTCORE_QUALIFIER,
        payload=json.dumps(payload),
    )

    # TRUE fire-and-forget: immediately close the streaming response
    try:
        stream = boto3_response.get("response")
        if stream:
            stream.close()   # closes the socket, does NOT wait for tokens
    except Exception as e:
        logger.warning("Error closing AgentCore streaming response: %s", e)

    # Do NOT iterate, do NOT wait, do NOT drain


def _parse_body(record) -> tuple[dict, str]:
    """
    Parse SQS message body. Supports:
    - Direct JSON from backend: {"caseId": "CASE-XXX", ...}
    - SNS-wrapped: {"Type": "Notification", "Message": "{\"caseId\":\"CASE-XXX\",...}"}
    Returns (body_dict, case_id).
    """
    raw = record.get("body", "{}")
    try:
        body = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Invalid JSON in SQS body: %s", raw[:200] if raw else "(empty)")
        return {}, ""

    # SNS subscription: payload is in Message as a string
    if body.get("Type") == "Notification" and isinstance(body.get("Message"), str):
        try:
            body = json.loads(body["Message"])
        except json.JSONDecodeError:
            logger.warning("SNS Message field is not valid JSON: %s", body.get("Message", "")[:200])
            return body, ""

    case_id = (
        body.get("caseId")
        or body.get("case_id")
        or body.get("CaseId")
        or ""
    )
    if isinstance(case_id, str):
        case_id = case_id.strip()
    else:
        case_id = str(case_id) if case_id is not None else ""

    return body, case_id


def _utc_now_iso() -> str:
    # Match backend timestamp convention
    return datetime.utcnow().isoformat() + "Z"


def _get_cases_table(region: str):
    table_name = os.environ.get("KYC_CASES_TABLE")
    if not table_name:
        return None
    dynamodb = boto3.resource("dynamodb", region_name=region)
    return dynamodb.Table(table_name)


def _mark_case_processing_or_skip(table, case_id: str) -> bool:
    """Return True if we should process this case, False to skip.

    Reads current case status from DynamoDB and attempts to set it to PROCESSING.
    If the case is already PROCESSING (or another concurrent invoker set it first),
    skip this SQS event.
    """
    if table is None:
        logger.warning("KYC_CASES_TABLE not set; proceeding without PROCESSING gate")
        return True

    try:
        response = table.get_item(Key={"CaseId": case_id})
        item = response.get("Item") or {}
        current_status = item.get("status")
        if isinstance(current_status, str) and current_status.strip().upper() == PROCESSING_STATUS:
            logger.info("Skipping caseId=%s because status is already %s", case_id, PROCESSING_STATUS)
            return False
    except Exception as e:
        logger.warning("Failed reading case from DynamoDB (caseId=%s); proceeding: %s", case_id, e)
        return True

    try:
        table.update_item(
            Key={"CaseId": case_id},
            UpdateExpression="SET #s = :processing, statusUpdatedAt = :t",
            ConditionExpression="attribute_not_exists(#s) OR #s <> :processing",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":processing": PROCESSING_STATUS, ":t": _utc_now_iso()},
        )
        logger.info("Marked caseId=%s status=%s", case_id, PROCESSING_STATUS)
        return True
    except Exception as e:
        # If another invocation updated it to PROCESSING after our read, DynamoDB will reject.
        if getattr(e, "response", {}).get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            logger.info("Skipping caseId=%s because status became %s", case_id, PROCESSING_STATUS)
            return False
        logger.warning("Failed updating case status to %s (caseId=%s); proceeding: %s", PROCESSING_STATUS, case_id, e)
        return True


def handler(event, context):
    agent_arn = os.environ.get("KYC_AGENT_ARN")
    region = os.environ.get("AWS_REGION", "us-east-1")

    if not agent_arn:
        raise ValueError("KYC_AGENT_ARN environment variable is required")

    agentcore_client = boto3.client("bedrock-agentcore", region_name=region)
    cases_table = _get_cases_table(region)

    failed = 0
    for record in event.get("Records", []):
        # Log record detail so we can see what came from the event (SQS)
        logger.info(
            "SQS record from event: messageId=%s eventSourceArn=%s body_preview=%s",
            record.get("messageId"),
            record.get("eventSourceARN", "")[:120] if record.get("eventSourceARN") else None,
            (record.get("body") or "")[:300],
        )
        try:
            body, case_id = _parse_body(record)
            if not case_id:
                logger.warning(
                    "SQS message missing caseId (skipping agent invocation). MessageId=%s body_keys=%s",
                    record.get("messageId", "?"),
                    list(body.keys()) if body else "empty",
                )
                failed += 1
                continue
            if not _mark_case_processing_or_skip(cases_table, case_id):
                continue

            logger.info("Invoking KYC agent for caseId=%s", case_id)
            _invoke_agent_fire_and_forget(agentcore_client, agent_arn, {"caseId": case_id})
        except Exception as e:
            try:
                _, case_id = _parse_body(record)
            except Exception:
                case_id = "?"
            logger.exception("Error processing SQS record (caseId=%s): %s", case_id, e)
            failed += 1

    return {"statusCode": 200, "failed": failed}
