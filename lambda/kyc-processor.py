import json
import os
import logging
import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

AGENTCORE_QUALIFIER = "DEFAULT"


def _invoke_agent_fire_and_forget(agentcore_client, agent_arn: str, payload: dict) -> None:
    """Invoke Bedrock Agent Core runtime and drain the response (fire-and-forget)."""
    boto3_response = agentcore_client.invoke_agent_runtime(
        agentRuntimeArn=agent_arn,
        qualifier=AGENTCORE_QUALIFIER,
        payload=json.dumps(payload),
    )
    # Drain the response so the connection closes and Lambda can exit; we don't use the output.
    if "text/event-stream" in boto3_response.get("contentType", ""):
        for _ in boto3_response["response"].iter_lines(chunk_size=1):
            pass
    else:
        for _ in boto3_response.get("response", []):
            pass


def handler(event, context):
    agent_arn = os.environ.get("AGENT_ARN")
    table_name = os.environ.get("KYC_CASES_TABLE")
    region = os.environ.get("AWS_REGION", "us-east-1")
    if not agent_arn:
        raise ValueError("AGENT_ARN environment variable is required")

    agentcore_client = boto3.client("bedrock-agentcore", region_name=region)
    logger.info("AGENT_ARN=%s KYC_CASES_TABLE=%s", agent_arn, table_name)

    for record in event.get("Records", []):
        try:
            body = json.loads(record.get("body", "{}"))
            case_id = body.get("caseId")
            logger.info("Invoking agent for caseId=%s (fire-and-forget)", case_id)
            payload = {"prompt": case_id or ""}
            _invoke_agent_fire_and_forget(agentcore_client, agent_arn, payload)
        except Exception as e:
            logger.exception("Error processing record: %s", e)
            raise
    return {"statusCode": 200}
