"""Tool to compare extracted document identity fields against the DB record using an LLM."""
import json
import logging
import os
from typing import Type

import boto3
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_MAX_EXTRACTED_DOCS_CHARS = 12000


class CompareIdentityInput(BaseModel):
    case_details: str = Field(description="JSON string of case details from get_case_details")
    extracted_documents: str = Field(
        description="JSON array of Textract extraction results from extract_document_text (one entry per document)"
    )
    government_verification_results: str = Field(
        default="[]",
        description="JSON array of BRP government verification results from verify_identity_document (one entry per document). Optional — defaults to empty array if not provided."
    )


class CompareIdentityDocumentsTool(BaseTool):
    """Compare extracted document identity fields against the DynamoDB case record using an LLM."""

    name: str = "compare_identity_documents"
    description: str = (
        "Takes case details (from get_case_details), a JSON array of Textract extraction results "
        "(from extract_document_text), and optionally a JSON array of BRP government verification results "
        "(from verify_identity_document). Compares identity fields across all three sources: database record, "
        "OCR-extracted text, and government registry. Returns JSON with comparison_result (MATCH/PARTIAL_MATCH/MISMATCH), "
        "discrepancies, comparison_summary, documents_summary, and government_verification_summary."
    )
    args_schema: Type[CompareIdentityInput] = CompareIdentityInput

    def _run(self, case_details: str, extracted_documents: str, government_verification_results: str = "[]") -> str:
        """Compare identity documents against the DB record and government verification data."""
        logger.info(
            "compare_identity_documents input: case_details len=%s, extracted_documents len=%s, govt_verification len=%s",
            len(case_details) if case_details else 0,
            len(extracted_documents) if extracted_documents else 0,
            len(government_verification_results) if government_verification_results else 0,
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

        try:
            govt_results = json.loads(government_verification_results) if isinstance(government_verification_results, str) else government_verification_results
        except json.JSONDecodeError:
            govt_results = []

        case_id = "Unknown"
        name = "Unknown"
        identity_from_db = {}
        if isinstance(case, dict):
            case_id = case.get("caseId") or case.get("case_id") or "Unknown"
            identity = case.get("identity") or {}
            if isinstance(identity, dict):
                name = identity.get("fullName", "Unknown")
                identity_from_db = identity

        comparison_result, discrepancies, comparison_summary, documents_summary, government_verification_summary = self._compare_with_llm(
            identity_from_db, docs, govt_results
        )

        result = {
            "case_id": case_id,
            "name": name,
            "comparison_result": comparison_result,
            "discrepancies": discrepancies,
            "comparison_summary": comparison_summary,
            "documents_summary": documents_summary,
            "government_verification_summary": government_verification_summary,
        }
        logger.info("compare_identity_documents output: comparison_result=%s", comparison_result)
        return json.dumps(result, indent=2)

    def _compare_with_llm(self, identity_from_db: dict, extracted_docs: list, govt_results: list = None):
        """Use LLM to compare extracted document text against the DB identity record and government verification data."""
        docs_text = json.dumps(extracted_docs, indent=2) if not isinstance(extracted_docs, str) else extracted_docs
        docs_truncated = docs_text[:_MAX_EXTRACTED_DOCS_CHARS] if len(docs_text) > _MAX_EXTRACTED_DOCS_CHARS else docs_text

        db_identity_text = json.dumps(identity_from_db, indent=2)

        govt_text = ""
        if govt_results:
            govt_text = json.dumps(govt_results, indent=2)
            govt_truncated = govt_text[:_MAX_EXTRACTED_DOCS_CHARS] if len(govt_text) > _MAX_EXTRACTED_DOCS_CHARS else govt_text
        else:
            govt_truncated = "No government verification data available."

        logger.info(
            "_compare_with_llm: db_identity len=%s, docs len=%s (truncated to %s), govt len=%s",
            len(db_identity_text), len(docs_text), len(docs_truncated),
            len(govt_text) if govt_text else 0,
        )
        # Bedrock model: use inference profile ID (no "bedrock/" prefix for boto3)
        model_id = os.getenv("MODEL", "us.anthropic.claude-3-5-sonnet-20241022-v2:0")
        prompt = f"""You are a KYC (Know Your Customer) document verification specialist.
Compare identity fields across THREE sources:
1. The database record (what the applicant submitted)
2. The OCR-extracted text from uploaded identity documents
3. The government BRP (Basisregistratie Personen) verification response (official registry data)

Source 1 — Database identity record:
{db_identity_text}

Source 2 — Extracted document text (one entry per document):
{docs_truncated}

Source 3 — Government BRP verification results:
{govt_truncated}

Analyze whether the identity information is consistent across all three sources.
Check fields such as full name, date of birth, nationality, document numbers, and any other identity-relevant fields present.
Pay special attention to whether the government registry confirms the document belongs to the same person in the database record.

Respond with a JSON object containing exactly these keys:
1. "comparison_result": one of "MATCH" (all fields match across all sources), "PARTIAL_MATCH" (most fields match but some discrepancies), or "MISMATCH" (significant differences found between sources)
2. "discrepancies": a list of strings, each describing a specific field discrepancy in the format "field X differs: source1=A, source2=B". Empty list if MATCH.
3. "comparison_summary": a 5-10 sentence explanation of the comparison outcome and reasoning
4. "documents_summary": a brief summary of each document processed (type, key fields found, quality of extraction)
5. "government_verification_summary": a summary of the government verification results — whether the document is confirmed as authentic, whether the registered person matches, and any notable findings

Example:
{{"comparison_result": "MATCH", "discrepancies": [], "comparison_summary": "All identity fields match across database, documents, and government registry.", "documents_summary": "Passport: clear extraction, all fields present.", "government_verification_summary": "BRP confirms document NL123456789 is registered to Jan de Vries, matching both DB and OCR data."}}
{{"comparison_result": "MISMATCH", "discrepancies": ["name differs: DB=Maria Jansen, BRP=Maria Bakker"], "comparison_summary": "Government registry shows document registered to different person.", "documents_summary": "Passport processed.", "government_verification_summary": "BRP shows passport NL987654321 registered to Maria Bakker, not Maria Jansen as in DB record. Document may be fraudulent or misattributed."}}

Your response (JSON only, no markdown):"""

        try:
            client = boto3.client("bedrock-runtime", region_name=os.getenv("AWS_REGION_NAME", "us-east-1"))
            response = client.converse(
                modelId=model_id,
                messages=[{"role": "user", "content": [{"text": prompt}]}],
                inferenceConfig={"maxTokens": 2048, "temperature": 0.0},
            )
            # Converse API returns output.message.content[].text
            content_parts = []
            for block in response.get("output", {}).get("message", {}).get("content", []):
                if "text" in block:
                    content_parts.append(block["text"])
            content = "".join(content_parts).strip()
            logger.info("LLM compare_identity response length: %s", len(content))
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
            government_verification_summary = str(parsed.get("government_verification_summary", "")) or "No government verification data available."
        except Exception as e:
            logger.exception("LLM identity comparison failed: %s", e)
            comparison_result = "PARTIAL_MATCH"
            discrepancies = [f"Comparison failed: {str(e)}"]
            comparison_summary = f"Automated comparison failed: {str(e)}. Manual review required."
            documents_summary = ""
            government_verification_summary = "Government verification comparison could not be completed."

        return comparison_result, discrepancies, comparison_summary, documents_summary, government_verification_summary
