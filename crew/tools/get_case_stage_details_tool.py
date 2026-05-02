"""Tool to fetch a structured summary of all KYC processing stage results from DynamoDB."""
import json
import logging
import os
from typing import Type

import boto3
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class GetCaseStageDetailsInput(BaseModel):
    case_id: str = Field(description="The case ID to fetch stage details for")


class GetCaseStageDetailsTool(BaseTool):
    """Fetch a structured summary of all KYC stage results for a case."""

    name: str = "get_case_stage_details"
    description: str = (
        "Reads the stages map from DynamoDB for a KYC case and returns a structured summary "
        "of each stage's result and summary text: documentProcessing, riskListScreening, and adverseMedia. "
        "Use this before analysing an override request so you have the full picture of what caused the escalation."
    )
    args_schema: Type[GetCaseStageDetailsInput] = GetCaseStageDetailsInput

    def _run(self, case_id: str) -> str:
        logger.info("get_case_stage_details: case_id=%s", case_id)
        if not case_id:
            return json.dumps({"error": "case_id is required"})

        table_name = os.environ.get("KYC_CASES_TABLE", "kyc-cases")
        try:
            dynamodb = boto3.resource("dynamodb")
            table = dynamodb.Table(table_name)
            response = table.get_item(Key={"CaseId": case_id})

            item = response.get("Item")
            if not item:
                return json.dumps({"error": f"No case found for caseId {case_id}"})

            stages = item.get("stages") or {}
            doc = stages.get("documentProcessing") or {}
            screening = stages.get("screening") or {}
            risk = screening.get("riskListScreening") or {}
            media = screening.get("adverseMedia") or {}

            result = {
                "case_id": case_id,
                "case_status": item.get("status", "UNKNOWN"),
                "documentProcessing": {
                    "result": doc.get("result"),
                    "summary": doc.get("summary"),
                    "discrepancies": doc.get("discrepancies", []),
                    "governmentVerificationSummary": doc.get("governmentVerificationSummary"),
                },
                "riskListScreening": {
                    "result": risk.get("result"),
                    "pepStatus": risk.get("pepStatus"),
                    "sanctionsStatus": risk.get("sanctionsStatus"),
                    "datasetsMatched": risk.get("datasetsMatched", []),
                    "summary": risk.get("summary"),
                },
                "adverseMedia": {
                    "result": media.get("result"),
                    "summary": media.get("summary"),
                    "searchQueries": media.get("searchQueries", []),
                },
            }

            logger.info(
                "get_case_stage_details: doc=%s, risk=%s, media=%s",
                result["documentProcessing"]["result"],
                result["riskListScreening"]["result"],
                result["adverseMedia"]["result"],
            )
            return json.dumps(result, default=str, indent=2)

        except Exception as e:
            logger.exception("get_case_stage_details failed")
            return json.dumps({"error": f"Failed to fetch case stage details: {str(e)}"})
