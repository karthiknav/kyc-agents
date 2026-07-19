"""Tool to request a narrow, targeted human clarification for a genuinely ambiguous risk-list hit."""
import json
import logging
import os
from datetime import datetime, timezone
from typing import Type

import boto3
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class RequestClarificationInput(BaseModel):
    case_id: str = Field(description="The KYC case ID needing clarification")
    question: str = Field(
        description="A single, specific, answerable question naming the exact missing or "
        "unresolvable piece of information (e.g. which field is missing or unrecognized) — "
        "not a generic 'please review this case' request."
    )
    matched_entity_json: str = Field(
        description="JSON string of the matched watchlist entity summary (from risk_list_screening's "
        "matchedEntitySummary) that the question is about."
    )
    discrepancy_fields_json: str = Field(
        default="[]",
        description="JSON array of field names that could not be compared (e.g. [\"nationality\"]).",
    )


class RequestClarificationTool(BaseTool):
    """Request a narrow human clarification for a risk-list hit instead of a full case escalation."""

    name: str = "request_clarification"
    description: str = (
        "Requests a single targeted clarification from a human reviewer for a risk-list hit whose "
        "corroborating fields (DOB, nationality) could not be resolved from available data. "
        "Sets the case to PENDING_QUICK_CONFIRM (distinct from full PENDING_HUMAN_REVIEW) and notifies "
        "the human review queue with the specific question. Use this only when a field is genuinely "
        "incomparable (missing or unrecognized) — not merely because two comparable fields disagree."
    )
    args_schema: Type[RequestClarificationInput] = RequestClarificationInput

    def _run(self, case_id: str, question: str, matched_entity_json: str, discrepancy_fields_json: str = "[]") -> str:
        logger.info("request_clarification: case_id=%s, question=%s", case_id, question)
        if not case_id:
            return json.dumps({"error": "case_id is required"})
        if not question:
            return json.dumps({"error": "question is required"})

        try:
            matched_entity = json.loads(matched_entity_json) if matched_entity_json else {}
        except json.JSONDecodeError:
            matched_entity = {"raw": matched_entity_json}

        try:
            discrepancy_fields = json.loads(discrepancy_fields_json) if discrepancy_fields_json else []
            if not isinstance(discrepancy_fields, list):
                discrepancy_fields = [str(discrepancy_fields)]
        except json.JSONDecodeError:
            discrepancy_fields = []

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        table_name = os.environ.get("KYC_CASES_TABLE", "kyc-cases")

        # Idempotency guard: skip if case already moved past a state where a fresh question makes sense.
        try:
            dynamodb = boto3.resource("dynamodb")
            table = dynamodb.Table(table_name)
            response = table.get_item(Key={"CaseId": case_id})
            item = response.get("Item") or {}
            current_status = item.get("status", "")
            if current_status in ("PENDING_HUMAN_REVIEW", "APPROVED", "PENDING_QUICK_CONFIRM"):
                logger.warning(
                    "request_clarification: case already in status=%s for case_id=%s — skipping",
                    current_status, case_id,
                )
                return json.dumps({
                    "case_id": case_id,
                    "status": current_status,
                    "message": f"Case already in status {current_status}. No action taken.",
                })
        except Exception:
            logger.exception("request_clarification: pre-flight check failed for case_id=%s", case_id)
            # Don't block on a pre-flight check failure; proceed

        clarification_request = {
            "question": question,
            "matchedEntity": matched_entity,
            "discrepancyFields": discrepancy_fields,
            "requestedAt": now,
        }

        errors = []
        try:
            dynamodb = boto3.resource("dynamodb")
            table = dynamodb.Table(table_name)

            table.update_item(
                Key={"CaseId": case_id},
                UpdateExpression="SET #status = :status",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={":status": "PENDING_QUICK_CONFIRM"},
            )

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
                ExpressionAttributeNames={
                    "#stages": "stages", "#screening": "screening", "#risk": "riskListScreening",
                },
                ExpressionAttributeValues={":empty_map": {}},
            )
            table.update_item(
                Key={"CaseId": case_id},
                UpdateExpression="SET #stages.#screening.#risk.#cr = :cr",
                ExpressionAttributeNames={
                    "#stages": "stages",
                    "#screening": "screening",
                    "#risk": "riskListScreening",
                    "#cr": "clarificationRequest",
                },
                ExpressionAttributeValues={":cr": clarification_request},
            )
            logger.info("request_clarification: DynamoDB updated PENDING_QUICK_CONFIRM for case_id=%s", case_id)
        except Exception as e:
            logger.exception("request_clarification: DynamoDB update failed for case_id=%s", case_id)
            errors.append(f"DynamoDB: {str(e)}")

        human_review_queue_url = os.environ.get("KYC_HUMAN_REVIEW_QUEUE_URL", "")
        if human_review_queue_url:
            try:
                sqs = boto3.client("sqs")
                notification = {
                    "caseId": case_id,
                    "type": "QUICK_CONFIRM_REQUIRED",
                    "requestedAt": now,
                    "question": question,
                    "matchedEntity": matched_entity,
                }
                sqs.send_message(
                    QueueUrl=human_review_queue_url,
                    MessageBody=json.dumps(notification, default=str),
                )
                logger.info("request_clarification: quick-confirm notification sent for case_id=%s", case_id)
            except Exception as e:
                logger.exception(
                    "request_clarification: SQS notification failed for case_id=%s", case_id
                )
                errors.append(f"SQS: {str(e)}")
        else:
            logger.warning(
                "request_clarification: KYC_HUMAN_REVIEW_QUEUE_URL not set — skipping notification"
            )

        return json.dumps({
            "case_id": case_id,
            "status": "PENDING_QUICK_CONFIRM",
            "question": question,
            "requested_at": now,
            "errors": errors,
        })
