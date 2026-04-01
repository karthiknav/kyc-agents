"""Tool to analyze income documents for KYC verification using an LLM."""
import json
import logging
import os
from typing import Type

import boto3
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_MAX_INCOME_TEXT_CHARS = 10000


class AnalyzeIncomeInput(BaseModel):
    case_details: str = Field(description="JSON string of case details from get_case_details")
    extracted_income_text: str = Field(
        description="Extracted text from the income document (via OCR/Textract)"
    )
    document_type_hint: str = Field(
        default="unknown",
        description="Hint about the document type, e.g. 'bank_statement', 'salary_slip', 'employment_contract'. Defaults to 'unknown'."
    )
    income_registry_data: str = Field(
        default="",
        description="JSON string of income registry data from UWV or KVK verification. Optional — defaults to empty string if not provided."
    )


class AnalyzeIncomeDocumentTool(BaseTool):
    """Analyze income documents against Dutch Wwft requirements using an LLM."""

    name: str = "analyze_income_document"
    description: str = (
        "Takes case details (from get_case_details), extracted income document text "
        "(from extract_document_text), a document type hint, and optional income registry data "
        "(from verify_income_uwv or verify_business_kvk). Analyzes the income document per Dutch "
        "Wwft (Anti-Money Laundering Act) requirements. Returns JSON with verification_result "
        "(VERIFIED/INSUFFICIENT/SUSPICIOUS/UNREADABLE), income_details, risk_indicators, and summary."
    )
    args_schema: Type[AnalyzeIncomeInput] = AnalyzeIncomeInput

    def _run(self, case_details: str, extracted_income_text: str, document_type_hint: str = "unknown", income_registry_data: str = "") -> str:
        """Analyze an income document against the case record and registry data."""
        logger.info(
            "analyze_income_document input: case_details len=%s, extracted_income_text len=%s, document_type_hint=%s, registry_data len=%s",
            len(case_details) if case_details else 0,
            len(extracted_income_text) if extracted_income_text else 0,
            document_type_hint,
            len(income_registry_data) if income_registry_data else 0,
        )
        if not case_details:
            return json.dumps({"error": "case_details is required"})
        if not extracted_income_text:
            return json.dumps({"error": "extracted_income_text is required"})

        try:
            case = json.loads(case_details) if isinstance(case_details, str) else case_details
        except json.JSONDecodeError:
            return json.dumps({"error": "Invalid case_details JSON"})

        case_id = "Unknown"
        name = "Unknown"
        identity_from_db = {}
        if isinstance(case, dict):
            case_id = case.get("caseId") or case.get("case_id") or "Unknown"
            identity = case.get("identity") or {}
            if isinstance(identity, dict):
                name = identity.get("fullName", "Unknown")
                identity_from_db = identity

        # Summarize long documents before analysis
        income_text = extracted_income_text
        if len(income_text) > _MAX_INCOME_TEXT_CHARS:
            logger.info("Income text exceeds %s chars (%s), summarizing first", _MAX_INCOME_TEXT_CHARS, len(income_text))
            income_text = self._summarize_long_document(income_text)

        analysis = self._analyze_with_llm(identity_from_db, income_text, document_type_hint, income_registry_data)

        result = {
            "case_id": case_id,
            "name": name,
            **analysis,
        }
        logger.info("analyze_income_document output: verification_result=%s", analysis.get("verification_result"))
        return json.dumps(result, indent=2)

    def _summarize_long_document(self, full_text: str) -> str:
        """Use LLM to summarize a long income document, preserving all financially relevant data."""
        region = os.getenv("AWS_REGION_NAME") or os.getenv("AWS_REGION") or "us-east-1"
        model_id = (os.getenv("MODEL") or "us.anthropic.claude-3-5-sonnet-20241022-v2:0").strip()
        model_id = model_id.replace("bedrock/", "")

        prompt = f"""You are a financial document specialist. The following document text is very long. Extract and preserve ALL financially relevant data in a structured JSON summary.

Document text:
{full_text}

Extract the following into a JSON object:
- "account_holder_name": name of the account holder or employee
- "employer_or_company_names": list of all employer or company names mentioned
- "monetary_amounts": list of objects with "amount", "currency", "context" (e.g. "salary", "deposit", "transfer")
- "dates_and_periods": list of all relevant dates and periods
- "iban_numbers": list of all IBAN numbers found
- "contract_terms": any contract terms found (type, duration, etc.)
- "transaction_patterns": summary of transaction patterns if applicable
- "red_flags": any suspicious items found (large cash deposits, unusual patterns, etc.)
- "other_relevant_info": any other financially relevant information

Preserve ALL financial information regardless of where it appears in the document. Do not omit any monetary amounts.

Your response (JSON only, no markdown):"""

        try:
            logger.info("Bedrock invoke (summarize): tool=%s modelId=%s region=%s", self.name, model_id, region)
            client = boto3.client("bedrock-runtime", region_name=region)
            response = client.converse(
                modelId=model_id,
                messages=[{"role": "user", "content": [{"text": prompt}]}],
                inferenceConfig={"maxTokens": 4096, "temperature": 0.0},
            )
            content_parts = []
            for block in response.get("output", {}).get("message", {}).get("content", []):
                if "text" in block:
                    content_parts.append(block["text"])
            content = "".join(content_parts).strip()
            logger.info("LLM summarize response length: %s", len(content))
            if content.startswith("```"):
                lines = content.split("\n")
                content = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
            return content
        except Exception as e:
            logger.exception("LLM document summarization failed: %s", e)
            # Fall back to truncation
            return full_text[:_MAX_INCOME_TEXT_CHARS]

    def _analyze_with_llm(self, identity_from_db: dict, income_text: str, document_type_hint: str, registry_data: str) -> dict:
        """Use LLM to analyze income document against Dutch Wwft requirements."""
        identity_json = json.dumps(identity_from_db, indent=2)

        region = os.getenv("AWS_REGION_NAME") or os.getenv("AWS_REGION") or "us-east-1"
        model_id = (os.getenv("MODEL") or "us.anthropic.claude-3-5-sonnet-20241022-v2:0").strip()
        model_id = model_id.replace("bedrock/", "")

        prompt = f"""You are a KYC (Know Your Customer) income verification specialist applying Dutch Wwft (Anti-Money Laundering Act) rules.

Analyze the following income document to verify source of funds.

Applicant identity from database:
{identity_json}

Income document text (extracted via OCR):
{income_text}

Document type hint: {document_type_hint}

Income registry data (from UWV/government, if available):
{registry_data or "No registry data available."}

Perform the following checks:

1. DOCUMENT TYPE IDENTIFICATION: Identify whether this is a bank statement (bankafschrift), employment contract (arbeidsovereenkomst), salary slip (loonstrook), tax return (belastingaangifte), business registration (KvK-uittreksel), or other document.

2. KEY DATA EXTRACTION: Extract account holder/employer name, all monetary amounts, dates/periods, IBAN, contract type if applicable.

3. NAME CONSISTENCY: Does the name on the document match the applicant's identity? Account for Dutch naming conventions (voorvoegsel like "van", "de", "van den").

4. INCOME PLAUSIBILITY: Is the income reasonable for the claimed occupation and age?
   - Flag if monthly net income exceeds EUR 10,000 for standard employment
   - Flag if income is inconsistent with the occupation type
   - Compare with registry data if available

5. DOCUMENT RECENCY: Is the document within acceptable timeframe?
   - Bank statements: within 3 months
   - Salary slips: within 3 months
   - Employment contracts: must be currently valid
   - Tax returns: most recent fiscal year

6. COMPLETENESS: Does the document contain enough information to verify source of funds?

7. RED FLAGS (check for ALL of these):
   - Large cash deposits (> EUR 15,000 — Wwft reporting threshold)
   - Transfers from high-risk jurisdictions
   - Income from multiple unknown sources
   - Gaps in employment history
   - Discrepancies between document and registry data

8. CROSS-REFERENCE: If registry data is available, compare income figures, employer details, and contract type.

Respond with a JSON object containing exactly these keys:
- "document_type_detected": one of "bank_statement", "employment_contract", "salary_slip", "tax_return", "business_registration", "unknown"
- "income_source": one of "employment", "self_employment", "business_ownership", "investments", "pension", "social_benefits", "unknown"
- "income_details": object with "employer_or_source" (string), "monthly_income_eur" (number), "annual_income_eur" (number), "currency" (string), "income_frequency" (string)
- "name_on_document": the name found on the income document (string)
- "name_match": whether name matches applicant identity (boolean)
- "document_date": date on the document or most recent date (string or null)
- "document_period": period covered by the document (string or null)
- "verification_result": one of "VERIFIED" (income confirmed, no issues), "INSUFFICIENT" (not enough info to verify), "SUSPICIOUS" (red flags found), "UNREADABLE" (document quality too poor to analyze)
- "risk_indicators": list of specific risk flags found (array of strings, empty if none)
- "missing_information": list of information that could not be determined (array of strings, empty if none)
- "plausibility_assessment": 1-3 sentence assessment of income plausibility (string)
- "summary": 3-8 sentence overall summary of the verification (string)
- "requires_additional_documents": whether more documents are needed (boolean)
- "additional_documents_needed": array of objects with "document_type" and "reason" keys (empty array if none needed)

Your response (JSON only, no markdown):"""

        try:
            logger.info("Bedrock invoke: tool=%s modelId=%s region=%s", self.name, model_id, region)
            client = boto3.client("bedrock-runtime", region_name=region)
            response = client.converse(
                modelId=model_id,
                messages=[{"role": "user", "content": [{"text": prompt}]}],
                inferenceConfig={"maxTokens": 2048, "temperature": 0.0},
            )
            content_parts = []
            for block in response.get("output", {}).get("message", {}).get("content", []):
                if "text" in block:
                    content_parts.append(block["text"])
            content = "".join(content_parts).strip()
            logger.info("LLM analyze_income response length: %s", len(content))
            if content.startswith("```"):
                lines = content.split("\n")
                content = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
            parsed = json.loads(content)
            logger.info("LLM income analysis result: verification_result=%s", parsed.get("verification_result"))

            # Validate verification_result
            verification_result = str(parsed.get("verification_result", "INSUFFICIENT")).upper()
            if verification_result not in ("VERIFIED", "INSUFFICIENT", "SUSPICIOUS", "UNREADABLE"):
                verification_result = "INSUFFICIENT"
            parsed["verification_result"] = verification_result

            # Validate list fields
            if not isinstance(parsed.get("risk_indicators"), list):
                parsed["risk_indicators"] = []
            if not isinstance(parsed.get("missing_information"), list):
                parsed["missing_information"] = []
            if not isinstance(parsed.get("additional_documents_needed"), list):
                parsed["additional_documents_needed"] = []

            return parsed
        except Exception as e:
            logger.exception("LLM income analysis failed: %s", e)
            return {
                "document_type_detected": "unknown",
                "income_source": "unknown",
                "income_details": None,
                "name_on_document": None,
                "name_match": None,
                "document_date": None,
                "document_period": None,
                "verification_result": "INSUFFICIENT",
                "risk_indicators": [f"Analysis failed: {str(e)}"],
                "missing_information": ["All fields — automated analysis failed"],
                "plausibility_assessment": f"Automated income analysis failed: {str(e)}. Manual review required.",
                "summary": f"Automated income analysis failed: {str(e)}. Manual review required.",
                "requires_additional_documents": True,
                "additional_documents_needed": [{"document_type": "any", "reason": "Automated analysis failed, manual review needed"}],
            }
