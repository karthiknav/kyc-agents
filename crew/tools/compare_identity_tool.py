"""Tool to compare extracted document identity fields against the DB record using an LLM."""
import json
import logging
from typing import Type

from crewai.tools import BaseTool
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_MAX_EXTRACTED_DOCS_CHARS = 12000


class CompareIdentityInput(BaseModel):
    case_details: str = Field(description="JSON string of case details from get_case_details")
    extracted_documents: str = Field(
        description="JSON array of Textract extraction results from extract_document_text (one entry per document)"
    )


class CompareIdentityDocumentsTool(BaseTool):
    """Compare extracted document identity fields against the DynamoDB case record using an LLM."""

    name: str = "compare_identity_documents"
    description: str = (
        "Takes case details (from get_case_details) and a JSON array of Textract extraction results "
        "(from extract_document_text), then uses an LLM to compare identity fields across all documents "
        "and against the database record. Returns JSON with comparison_result (MATCH/PARTIAL_MATCH/MISMATCH), "
        "discrepancies, comparison_summary, and documents_summary."
    )
    args_schema: Type[CompareIdentityInput] = CompareIdentityInput

    def _run(self, case_details: str, extracted_documents: str) -> str:
        """Compare identity documents against the DB record."""
        logger.info(
            "compare_identity_documents input: case_details len=%s, extracted_documents len=%s",
            len(case_details) if case_details else 0,
            len(extracted_documents) if extracted_documents else 0,
        )
        if not case_details:
            return json.dumps({"error": "case_details is required"})
        if not extracted_documents:
            return json.dumps({"error": "extracted_documents is required"})

        try:
            case = json.loads(case_details) if isinstance(case_details, str) else case_details
        except json.JSONDecodeError:
            return json.dumps({"error": "Invalid case_details JSON"})

        try:
            docs = json.loads(extracted_documents) if isinstance(extracted_documents, str) else extracted_documents
        except json.JSONDecodeError:
            return json.dumps({"error": "Invalid extracted_documents JSON"})

        case_id = "Unknown"
        name = "Unknown"
        identity_from_db = {}
        if isinstance(case, dict):
            case_id = case.get("caseId") or case.get("case_id") or "Unknown"
            identity = case.get("identity") or {}
            if isinstance(identity, dict):
                name = identity.get("fullName", "Unknown")
                identity_from_db = identity

        comparison_result, discrepancies, comparison_summary, documents_summary = self._compare_with_llm(
            identity_from_db, docs
        )

        result = {
            "case_id": case_id,
            "name": name,
            "comparison_result": comparison_result,
            "discrepancies": discrepancies,
            "comparison_summary": comparison_summary,
            "documents_summary": documents_summary,
        }
        logger.info("compare_identity_documents output: comparison_result=%s", comparison_result)
        return json.dumps(result, indent=2)

    def _compare_with_llm(self, identity_from_db: dict, extracted_docs: list):
        """Use LLM to compare extracted document text against the DB identity record."""
        docs_text = json.dumps(extracted_docs, indent=2) if not isinstance(extracted_docs, str) else extracted_docs
        docs_truncated = docs_text[:_MAX_EXTRACTED_DOCS_CHARS] if len(docs_text) > _MAX_EXTRACTED_DOCS_CHARS else docs_text

        db_identity_text = json.dumps(identity_from_db, indent=2)

        logger.info(
            "_compare_with_llm: db_identity len=%s, docs len=%s (truncated to %s)",
            len(db_identity_text), len(docs_text), len(docs_truncated),
        )

        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

        prompt = f"""You are a KYC (Know Your Customer) document verification specialist.
Compare the identity fields from the database record against the text extracted from the uploaded identity documents.

Database identity record:
{db_identity_text}

Extracted document text (one entry per document):
{docs_truncated}

Analyze whether the identity information in the documents matches the database record.
Check fields such as full name, date of birth, nationality, document numbers, and any other identity-relevant fields present.

Respond with a JSON object containing exactly these keys:
1. "comparison_result": one of "MATCH" (all fields match), "PARTIAL_MATCH" (most fields match but some discrepancies), or "MISMATCH" (significant differences found)
2. "discrepancies": a list of strings, each describing a specific field discrepancy in the format "field X differs: DB=A, doc=B". Empty list if MATCH.
3. "comparison_summary": a 5-10 sentence explanation of the comparison outcome and reasoning
4. "documents_summary": a brief summary of each document processed (type, key fields found, quality of extraction)

Example:
{{"comparison_result": "MATCH", "discrepancies": [], "comparison_summary": "All identity fields match.", "documents_summary": "Passport: clear extraction, all fields present."}}
{{"comparison_result": "PARTIAL_MATCH", "discrepancies": ["dateOfBirth differs: DB=1990-01-15, doc=15/01/1990"], "comparison_summary": "Name matches but date format differs.", "documents_summary": "Passport processed, 2 pages."}}

Your response (JSON only, no markdown):"""

        try:
            response = llm.invoke(prompt)
            logger.info("LLM compare_identity response: %s", response)
            content = response.content.strip()
            if content.startswith("```"):
                lines = content.split("\n")
                content = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
            parsed = json.loads(content)
            logger.info("LLM comparison result: %s", parsed)

            comparison_result = str(parsed.get("comparison_result", "PARTIAL_MATCH")).upper()
            if comparison_result not in ("MATCH", "PARTIAL_MATCH", "MISMATCH"):
                comparison_result = "PARTIAL_MATCH"
            discrepancies = parsed.get("discrepancies", [])
            if not isinstance(discrepancies, list):
                discrepancies = [str(discrepancies)]
            comparison_summary = str(parsed.get("comparison_summary", "")) or "Comparison completed."
            documents_summary = str(parsed.get("documents_summary", "")) or "No documents summary available."
        except Exception as e:
            logger.exception("LLM identity comparison failed: %s", e)
            comparison_result = "PARTIAL_MATCH"
            discrepancies = [f"Comparison failed: {str(e)}"]
            comparison_summary = f"Automated comparison failed: {str(e)}. Manual review required."
            documents_summary = ""

        return comparison_result, discrepancies, comparison_summary, documents_summary
