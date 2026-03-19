import json
import os
import logging
import secrets
import uuid
import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

AGENTCORE_QUALIFIER = "DEFAULT"


def _uuid34() -> str:
    """Return a 34-character unique id (hex)."""
    # uuid4().hex -> 32 chars, token_hex(1) -> 2 chars
    return uuid.uuid4().hex + secrets.token_hex(1)


def _invoke_agent_fire_and_forget(agentcore_client, agent_arn: str, payload: dict) -> None:
    """Invoke Bedrock AgentCore runtime and drain the response (fire-and-forget)."""
    case_id = payload.get("caseId", "unknown")
    case_id = case_id.strip() if isinstance(case_id, str) else str(case_id)
    runtime_session_id = f"kyc-case-{case_id}-{_uuid34()}"
    boto3_response = agentcore_client.invoke_agent_runtime(
        agentRuntimeArn=agent_arn,
        runtimeSessionId=runtime_session_id,
        qualifier=AGENTCORE_QUALIFIER,
        payload=json.dumps(payload),
    )
    if "text/event-stream" in boto3_response.get("contentType", ""):
        for _ in boto3_response["response"].iter_lines(chunk_size=1):
            pass
    else:
        for _ in boto3_response.get("response", []):
            pass


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


def handler(event, context):
    agent_arn = os.environ.get("KYC_AGENT_ARN")
    region = os.environ.get("AWS_REGION", "us-east-1")

    if not agent_arn:
        raise ValueError("KYC_AGENT_ARN environment variable is required")

    agentcore_client = boto3.client("bedrock-agentcore", region_name=region)

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
