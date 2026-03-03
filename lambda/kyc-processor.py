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
    sanctions_agent_arn = os.environ.get("SANCTIONS_AGENT_ARN")
    doc_processor_agent_arn = os.environ.get("DOC_PROCESSOR_AGENT_ARN", "")
    orchestrator_agent_arn = os.environ.get("ORCHESTRATOR_AGENT_ARN", "")
    table_name = os.environ.get("KYC_CASES_TABLE")
    region = os.environ.get("AWS_REGION", "us-east-1")

    if not sanctions_agent_arn:
        raise ValueError("SANCTIONS_AGENT_ARN environment variable is required")

    agent_arn_map = {
        "sanctions": sanctions_agent_arn,
        "document_processor": doc_processor_agent_arn,
        "orchestrator": orchestrator_agent_arn,
    }

    agentcore_client = boto3.client("bedrock-agentcore", region_name=region)
    logger.info(
        "SANCTIONS_AGENT_ARN=%s DOC_PROCESSOR_AGENT_ARN=%s ORCHESTRATOR_AGENT_ARN=%s KYC_CASES_TABLE=%s",
        sanctions_agent_arn, doc_processor_agent_arn, orchestrator_agent_arn, table_name,
    )

    for record in event.get("Records", []):
        try:
            body = json.loads(record.get("body", "{}"))
            case_id = body.get("caseId")
            target_agent = body.get("targetAgent", "sanctions")

            agent_arn = agent_arn_map.get(target_agent)
            if not agent_arn:
                logger.warning(
                    "Unknown or unconfigured targetAgent=%s for caseId=%s — skipping record",
                    target_agent, case_id,
                )
                continue

            logger.info(
                "Invoking agent targetAgent=%s for caseId=%s (fire-and-forget)",
                target_agent, case_id,
            )
            payload = {"caseId": case_id or ""}
            _invoke_agent_fire_and_forget(agentcore_client, agent_arn, payload)
        except Exception as e:
            logger.exception("Error processing record: %s", e)
            raise
    return {"statusCode": 200}
