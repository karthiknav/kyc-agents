import json
import os
import logging
import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

AGENTCORE_QUALIFIER = "DEFAULT"


def _invoke_agent_fire_and_forget(agentcore_client, agent_arn: str, payload: dict) -> None:
    """Invoke Bedrock AgentCore runtime and drain the response (fire-and-forget)."""
    boto3_response = agentcore_client.invoke_agent_runtime(
        agentRuntimeArn=agent_arn,
        qualifier=AGENTCORE_QUALIFIER,
        payload=json.dumps(payload),
    )
    if "text/event-stream" in boto3_response.get("contentType", ""):
        for _ in boto3_response["response"].iter_lines(chunk_size=1):
            pass
    else:
        for _ in boto3_response.get("response", []):
            pass


def handler(event, context):
    agent_arn = os.environ.get("KYC_AGENT_ARN")
    region = os.environ.get("AWS_REGION", "us-east-1")

    if not agent_arn:
        raise ValueError("KYC_AGENT_ARN environment variable is required")

    agentcore_client = boto3.client("bedrock-agentcore", region_name=region)

    for record in event.get("Records", []):
        try:
            body = json.loads(record.get("body", "{}"))
            case_id = body.get("caseId", "")
            logger.info("Invoking KYC agent for caseId=%s", case_id)
            _invoke_agent_fire_and_forget(agentcore_client, agent_arn, {"caseId": case_id})
        except Exception as e:
            logger.exception("Error processing record: %s", e)
            raise

    return {"statusCode": 200}
