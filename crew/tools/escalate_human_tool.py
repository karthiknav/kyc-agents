"""Tool to escalate a KYC case for human review."""
import json
import logging
import os
from datetime import datetime, timezone
from typing import Type

import boto3
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class EscalateToHumanInput(BaseModel):
    case_id: str = Field(description="The KYC case ID to escalate")
    reason: str = Field(description="Comma-separated reasons why the case is being escalated")
    escalation_summary: str = Field(description="Human-readable summary of the escalation for the reviewer")
    additional_documents_needed: str = Field(
        default="",
        description='Optional JSON array of additional documents needed from the customer. Each item should be an object with "document_type" and "reason" keys. Empty string if not applicable.'
    )


class EscalateToHumanTool(BaseTool):
    """Escalate a KYC case to human review by updating DynamoDB and notifying the human review queue."""

    name: str = "escalate_to_human"
    description: str = (
        "Escalates a KYC case for human review. "
        "Updates the case status to PENDING_HUMAN_REVIEW in DynamoDB and publishes "
        "a notification to the human review SQS queue (KYC_HUMAN_REVIEW_QUEUE_URL). "
        "Call this when the aggregate_kyc_results decision is ESCALATE."
    )
    args_schema: Type[EscalateToHumanInput] = EscalateToHumanInput

    def _run(self, case_id: str, reason: str, escalation_summary: str, additional_documents_needed: str = "") -> str:
        logger.info(
            "escalate_to_human input: case_id=%s, reason=%s", case_id, reason
        )
        if not case_id:
            return json.dumps({"error": "case_id is required"})
        if not reason:
            return json.dumps({"error": "reason is required"})

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        errors = []

        # Idempotency guard: skip if case is already escalated or approved
        table_name = os.environ.get("KYC_CASES_TABLE", "kyc-cases")
        try:
            dynamodb = boto3.resource("dynamodb")
            table = dynamodb.Table(table_name)
            response = table.get_item(Key={"CaseId": case_id})
            item = response.get("Item") or {}
            current_status = item.get("status", "")
            if current_status in ("PENDING_HUMAN_REVIEW", "APPROVED"):
                logger.warning(
                    "escalate_to_human: case already in terminal status=%s for case_id=%s — skipping",
                    current_status, case_id,
                )
                return json.dumps({
                    "case_id": case_id,
                    "status": current_status,
                    "message": f"Case already in terminal status {current_status}. No action taken.",
                })
        except Exception as e:
            logger.exception("escalate_to_human: pre-flight check failed for case_id=%s", case_id)
            # Don't block escalation on a pre-flight check failure; proceed

        # Update DynamoDB: case status → PENDING_HUMAN_REVIEW, orchestrator stage → ESCALATED
        table_name = os.environ.get("KYC_CASES_TABLE", "kyc-cases")
        # Parse additional documents needed if provided
        parsed_additional_docs = []
        if additional_documents_needed:
            try:
                parsed_additional_docs = json.loads(additional_documents_needed) if isinstance(additional_documents_needed, str) else additional_documents_needed
                if not isinstance(parsed_additional_docs, list):
                    parsed_additional_docs = []
            except (json.JSONDecodeError, TypeError):
                parsed_additional_docs = []

        escalation_status = "ADDITIONAL_DOCUMENTS_REQUIRED" if parsed_additional_docs else "ESCALATED"
        orchestrator_stage_update = {
            "status": escalation_status,
            "escalatedAt": now,
            "reason": reason,
            "escalation_summary": escalation_summary,
            "additional_documents_needed": parsed_additional_docs,
        }
        try:
            dynamodb = boto3.resource("dynamodb")
            table = dynamodb.Table(table_name)

            # Update top-level case status
            case_level_status = "ADDITIONAL_DOCUMENTS_REQUESTED" if parsed_additional_docs else "PENDING_HUMAN_REVIEW"
            table.update_item(
                Key={"CaseId": case_id},
                UpdateExpression="SET #status = :status",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={":status": case_level_status},
            )

            # Ensure stages map exists then update orchestrator sub-stage
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
                ExpressionAttributeValues={":orchestrator": orchestrator_stage_update},
            )
            logger.info(
                "escalate_to_human: DynamoDB updated PENDING_HUMAN_REVIEW for case_id=%s", case_id
            )
        except Exception as e:
            logger.exception("escalate_to_human: DynamoDB update failed for case_id=%s", case_id)
            errors.append(f"DynamoDB: {str(e)}")

        # Notify human review queue
        human_review_queue_url = os.environ.get("KYC_HUMAN_REVIEW_QUEUE_URL", "")
        if human_review_queue_url:
            try:
                sqs = boto3.client("sqs")
                notification = {
                    "caseId": case_id,
                    "type": "ADDITIONAL_DOCUMENTS_REQUIRED" if parsed_additional_docs else "HUMAN_REVIEW_REQUIRED",
                    "escalatedAt": now,
                    "reason": reason,
                    "escalation_summary": escalation_summary,
                    "additional_documents_needed": parsed_additional_docs,
                }
                sqs.send_message(
                    QueueUrl=human_review_queue_url,
                    MessageBody=json.dumps(notification),
                )
                logger.info(
                    "escalate_to_human: human review notification sent for case_id=%s", case_id
                )
            except Exception as e:
                logger.exception(
                    "escalate_to_human: SQS human review notification failed for case_id=%s", case_id
                )
                errors.append(f"SQS: {str(e)}")
        else:
            logger.warning(
                "escalate_to_human: KYC_HUMAN_REVIEW_QUEUE_URL not set — skipping notification"
            )

        return json.dumps({
            "case_id": case_id,
            "status": "ESCALATED",
            "escalated_at": now,
            "reason": reason,
            "errors": errors,
        })
