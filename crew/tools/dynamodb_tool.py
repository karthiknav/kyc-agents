"""Tool to fetch case details from DynamoDB."""
import logging
import os
from typing import Type
import json
import boto3
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class GetCaseDetailsInput(BaseModel):
    case_id: str = Field(description="The case ID to fetch from DynamoDB")


class GetCaseDetailsTool(BaseTool):
    """Fetch case details from DynamoDB by caseId. Returns the full case including identity.fullName."""

    name: str = "get_case_details"
    description: str = (
        "Fetches case details from DynamoDB by caseId. "
        "Returns the full case document including identity.fullName, files, documentVerification, personScreening, etc. "
        "Use this first to get the person's name and case context."
    )
    args_schema: Type[GetCaseDetailsInput] = GetCaseDetailsInput

    def _run(self, case_id: str) -> str:
        """Fetch case from DynamoDB by caseId."""
        logger.info("get_case_details input: case_id=%s", case_id)
        if not case_id:
            return "Error: case_id is required."

        table_name = os.environ.get("KYC_CASES_TABLE", "kyc-cases")
        logger.info("get_case_details table_name: %s", table_name)
        try:
            dynamodb = boto3.resource("dynamodb")
            table = dynamodb.Table(table_name)
            response = table.get_item(Key={"CaseId": case_id})

            item = response.get("Item")
            if not item:
                return f"Error: No case found for caseId {case_id}."

            # Identity may be stored as a map; ensure fullName is extracted
            identity = item.get("identity") or {}
            full_name = identity.get("fullName", "Unknown") if isinstance(identity, dict) else "Unknown"

            # Build a readable summary including case_id and name from identity.fullName
            case_id_val = item.get("caseId")
            result = {
                "case_id": case_id_val,
                "caseId": case_id_val,
                "identity": {
                    "fullName": full_name,
                    "dateOfBirth": identity.get("dateOfBirth") if isinstance(identity, dict) else None,
                    "nationality": identity.get("nationality") if isinstance(identity, dict) else None,
                },
                "status": item.get("status")
            }
            out = json.dumps(result, indent=2, default=str)
            logger.info("get_case_details output: returned case for case_id=%s", case_id)
            return out

        except Exception as e:
            logger.exception("DynamoDB get_case_details failed")
            return f"Error fetching case: {str(e)}"
