"""Tool to fetch document file references from DynamoDB for a KYC case."""
import json
import logging
import os
from typing import Type

import boto3
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class GetCaseFilesInput(BaseModel):
    case_id: str = Field(description="The case ID to fetch uploaded document files for")


class GetCaseFilesTool(BaseTool):
    """Fetch the uploaded document file references for a KYC case from DynamoDB."""

    name: str = "get_case_files"
    description: str = (
        "Fetches the list of uploaded identity document file references (S3 bucket/key pairs) "
        "for a KYC case from DynamoDB. Returns the raw 'files' attribute as JSON. "
        "Use this after get_case_details to get the documents that need to be processed."
    )
    args_schema: Type[GetCaseFilesInput] = GetCaseFilesInput

    def _run(self, case_id: str) -> str:
        """Fetch the files attribute for a case from DynamoDB."""
        logger.info("get_case_files input: case_id=%s", case_id)
        if not case_id:
            return "Error: case_id is required."

        table_name = os.environ.get("KYC_CASES_TABLE", "kyc-cases")
        logger.info("get_case_files table_name: %s", table_name)
        try:
            dynamodb = boto3.resource("dynamodb")
            table = dynamodb.Table(table_name)
            response = table.get_item(Key={"CaseId": case_id})

            item = response.get("Item")
            if not item:
                return f"Error: No case found for caseId {case_id}."

            files = item.get("files")
            if files is None:
                logger.info("get_case_files: no files attribute for case_id=%s", case_id)
                return json.dumps({"case_id": case_id, "files": []})

            out = json.dumps({"case_id": case_id, "files": files}, default=str)
            logger.info("get_case_files output: returned files for case_id=%s", case_id)
            return out

        except Exception as e:
            logger.exception("DynamoDB get_case_files failed")
            return f"Error fetching case files: {str(e)}"
