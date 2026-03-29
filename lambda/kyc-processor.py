import json
import os
import logging
import secrets
import uuid
from datetime import datetime

import boto3
from botocore.config import Config

logger = logging.getLogger()
logger.setLevel(logging.INFO)

AGENTCORE_QUALIFIER = "DEFAULT"
PROCESSING_STATUS = "PROCESSING"


def _drain_agentcore_response(boto3_response: dict, *, max_bytes: int) -> tuple[str, bool]:
    """Drain up to max_bytes from the AgentCore invoke response.

    Returns (decoded_text, truncated).
    """
    response = boto3_response.get("response")
    if not response:
        return "", False

    if max_bytes <= 0:
        return "", True

    content_type = str(boto3_response.get("contentType") or "")

    collected = 0
    truncated = False
    chunks: list[bytes] = []

    try:
        if "text/event-stream" in content_type:
            # SSE: capture line-by-line (still streaming bytes).
            for line in response.iter_lines(chunk_size=1024):
                if not line:
                    continue
                line_bytes = line.encode("utf-8", errors="replace") if isinstance(line, str) else line
                addition = line_bytes + b"\n"
                remaining = max_bytes - collected
                if remaining <= 0:
                    truncated = True
                    break
                if len(addition) > remaining:
                    chunks.append(addition[:remaining])
                    collected += remaining
                    truncated = True
                    break
                chunks.append(addition)
                collected += len(addition)
        else:
            # Non-SSE: drain chunks.
            for chunk in response.iter_chunks(chunk_size=8192):
                if not chunk:
                    continue
                remaining = max_bytes - collected
                if remaining <= 0:
                    truncated = True
                    break
                if len(chunk) > remaining:
                    chunks.append(chunk[:remaining])
                    collected += remaining
                    truncated = True
                    break
                chunks.append(chunk)
                collected += len(chunk)
    except Exception as e:
        logger.warning("Error draining AgentCore response body: %s", e)

    data = b"".join(chunks)
    return data.decode("utf-8", errors="replace"), truncated

# Important: botocore retries can re-send timed-out requests, which may create
# duplicate AgentCore invocations. Keep attempts to 1.
AGENTCORE_CLIENT_CONFIG = Config(
    connect_timeout=60,
    read_timeout=120,
    retries={"total_max_attempts": 1, "max_attempts": 0, "mode": "standard"},
)


def _uuid34() -> str:
    """Return a 34-character unique id (hex)."""
    # uuid4().hex -> 32 chars, token_hex(1) -> 2 chars
    return uuid.uuid4().hex + secrets.token_hex(1)


def _invoke_agent_fire_and_forget(
    agentcore_client,
    agent_arn: str,
    payload: dict,
    *,
    runtime_session_id: str | None = None,
) -> str:
    """Invoke Bedrock AgentCore runtime without waiting for any response."""
    case_id = payload.get("caseId", "unknown")
    case_id = case_id.strip() if isinstance(case_id, str) else str(case_id)
    runtime_session_id = runtime_session_id or f"kyc-case-{case_id}-{_uuid34()}"

    logger.info(
        "Invoking AgentCore runtime: caseId=%s runtimeSessionId=%s qualifier=%s",
        case_id,
        runtime_session_id,
        AGENTCORE_QUALIFIER,
    )

    # Invoke AgentCore (this still waits for headers, <150ms)
    boto3_response = agentcore_client.invoke_agent_runtime(
        agentRuntimeArn=agent_arn,
        runtimeSessionId=runtime_session_id,
        qualifier=AGENTCORE_QUALIFIER,
        payload=json.dumps(payload),
    )

    # Drain and log the response body (this WILL wait for tokens).
    try:
        response = boto3_response.get("response")
        content_type = str(boto3_response.get("contentType") or "")

        if response:
            max_bytes = int(os.environ.get("AGENTCORE_MAX_RESPONSE_BYTES", "20000"))
            text, truncated = _drain_agentcore_response(boto3_response, max_bytes=max_bytes)
            # If it's JSON, log a compact representation.
            try:
                text = json.dumps(json.loads(text), ensure_ascii=False)
            except Exception:
                pass
            logger.info(
                "AgentCore response body (contentType=%s truncated=%s maxBytes=%s): %s",
                content_type,
                truncated,
                max_bytes,
                text,
            )
    except Exception as e:
        logger.warning("Error closing AgentCore streaming response: %s", e)
    finally:
        try:
            response = boto3_response.get("response")
            if response:
                response.close()
        except Exception:
            pass

    return runtime_session_id


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
        logger.info(
            "Current case status read from DynamoDB: caseId=%s status=%s item_found=%s",
            case_id,
            current_status,
            bool(item),
        )
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

    agentcore_client = boto3.client(
        "bedrock-agentcore",
        region_name=region,
        config=AGENTCORE_CLIENT_CONFIG,
    )
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
                logger.info("Skipping agent invocation for caseId=%s as it is duplicate", case_id)
                continue

            message_id = record.get("messageId")
            stable_session_id = (
                f"kyc-case-{case_id}-{message_id}" if isinstance(message_id, str) and message_id else None
            )
            _invoke_agent_fire_and_forget(
                agentcore_client,
                agent_arn,
                {"caseId": case_id},
                runtime_session_id=stable_session_id,
            )
        except Exception as e:
            try:
                _, case_id = _parse_body(record)
            except Exception:
                case_id = "?"
            logger.exception("Error processing SQS record (caseId=%s): %s", case_id, e)
            failed += 1

    return {"statusCode": 200, "failed": failed}
