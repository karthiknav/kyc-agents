"""Tool to fetch the processing stages for a KYC case from DynamoDB."""
import json
import logging
import os
from typing import Type

import boto3
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class GetCaseStagesInput(BaseModel):
    case_id: str = Field(description="The case ID to fetch stage results for")


class GetCasestagesTool(BaseTool):
    """Read the stages map (documentProcessing, screening, orchestrator) for a KYC case."""

    name: str = "get_case_stages"
    description: str = (
        "Reads the 'stages' attribute from DynamoDB for a KYC case. "
        "Returns the full stages map including documentProcessing, screening, and orchestrator sub-stages. "
        "Use this to check whether sub-agents have already completed and written their results."
    )
    args_schema: Type[GetCaseStagesInput] = GetCaseStagesInput

    def _run(self, case_id: str) -> str:
        logger.info("get_case_stages input: case_id=%s", case_id)
        if not case_id:
            return "Error: case_id is required."

        table_name = os.environ.get("KYC_CASES_TABLE", "kyc-cases")
        try:
            dynamodb = boto3.resource("dynamodb")
            table = dynamodb.Table(table_name)
            response = table.get_item(Key={"CaseId": case_id})

            item = response.get("Item")
            if not item:
                return f"Error: No case found for caseId {case_id}."

            stages = item.get("stages") or {}
            result = {
                "case_id": case_id,
                "case_status": item.get("status", "UNKNOWN"),
                "stages": stages,
                "has_document_processing": "documentProcessing" in stages,
                "has_screening": "screening" in stages,
                "has_orchestrator": "orchestrator" in stages,
            }
            out = json.dumps(result, default=str)
            logger.info(
                "get_case_stages output: case_id=%s, has_doc=%s, has_screening=%s, has_orchestrator=%s",
                case_id,
                result["has_document_processing"],
                result["has_screening"],
                result["has_orchestrator"],
            )
            return out

        except Exception as e:
            logger.exception("DynamoDB get_case_stages failed")
            return f"Error fetching case stages: {str(e)}"
