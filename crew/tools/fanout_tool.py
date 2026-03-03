"""Tool to fan out KYC sub-agent invocations via SQS."""
import json
import logging
import os
from datetime import datetime, timezone
from typing import Type

import boto3
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class FanoutSubagentsInput(BaseModel):
    case_id: str = Field(description="The KYC case ID to fan out to sub-agents")


class FanoutSubagentsTool(BaseTool):
    """Publish SQS messages to trigger document processing and sanctions screening in parallel."""

    name: str = "fanout_subagents"
    description: str = (
        "Publishes two SQS messages to trigger the document_processor and sanctions sub-agents "
        "in parallel for the given case. Also marks stages.orchestrator.status = AWAITING_SUBAGENTS "
        "in DynamoDB so subsequent invocations know fanout has already occurred. "
        "Only call this once per case — check get_case_stages first."
    )
    args_schema: Type[FanoutSubagentsInput] = FanoutSubagentsInput

    def _run(self, case_id: str) -> str:
        logger.info("fanout_subagents input: case_id=%s", case_id)
        if not case_id:
            return json.dumps({"error": "case_id is required"})

        queue_url = os.environ.get("KYC_QUEUE_URL", "")
        if not queue_url:
            return json.dumps({"error": "KYC_QUEUE_URL env var not set — cannot fanout"})

        # Double-fanout guard: check if orchestrator stage already exists in DynamoDB
        table_name = os.environ.get("KYC_CASES_TABLE", "kyc-cases")
        try:
            dynamodb = boto3.resource("dynamodb")
            table = dynamodb.Table(table_name)
            response = table.get_item(Key={"CaseId": case_id})
            item = response.get("Item") or {}
            stages = item.get("stages") or {}
            orchestrator_stage = stages.get("orchestrator") or {}
            existing_status = orchestrator_stage.get("status", "")
            if existing_status in ("AWAITING_SUBAGENTS", "ESCALATED", "APPROVED"):
                logger.warning(
                    "fanout_subagents: fanout already performed (status=%s) for case_id=%s — skipping",
                    existing_status, case_id,
                )
                return json.dumps({
                    "case_id": case_id,
                    "status": existing_status,
                    "message": f"Fanout already performed (status={existing_status}). Not re-triggering sub-agents.",
                })
        except Exception as e:
            logger.exception("fanout_subagents: pre-flight DynamoDB check failed for case_id=%s", case_id)
            return json.dumps({"error": f"Pre-flight check failed: {str(e)}"})

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        published = []
        errors = []

        try:
            sqs = boto3.client("sqs")
            for target in ("document_processor", "sanctions"):
                msg = {"caseId": case_id, "targetAgent": target}
                sqs.send_message(QueueUrl=queue_url, MessageBody=json.dumps(msg))
                logger.info("fanout_subagents: sent SQS targetAgent=%s for case_id=%s", target, case_id)
                published.append(target)
        except Exception as e:
            logger.exception("fanout_subagents: SQS publish failed for case_id=%s", case_id)
            errors.append(str(e))

        # Mark orchestrator stage as AWAITING_SUBAGENTS in DynamoDB
        table_name = os.environ.get("KYC_CASES_TABLE", "kyc-cases")
        orchestrator_stage = {
            "status": "AWAITING_SUBAGENTS",
            "fanoutAt": now,
            "publishedTo": published,
        }
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
                UpdateExpression="SET #stages.#orchestrator = :orchestrator",
                ExpressionAttributeNames={
                    "#stages": "stages",
                    "#orchestrator": "orchestrator",
                },
                ExpressionAttributeValues={":orchestrator": orchestrator_stage},
            )
            logger.info("fanout_subagents: marked AWAITING_SUBAGENTS for case_id=%s", case_id)
        except Exception as e:
            logger.exception("fanout_subagents: DynamoDB update failed for case_id=%s", case_id)
            errors.append(str(e))

        return json.dumps({
            "case_id": case_id,
            "published_to": published,
            "fanout_at": now,
            "errors": errors,
            "status": "AWAITING_SUBAGENTS" if published else "FAILED",
        })
