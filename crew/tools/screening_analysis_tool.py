"""Tool to analyze case details and search results and produce a screening analysis."""
import json
import logging
import os
from typing import Optional, Type

import boto3
from crewai.tools import BaseTool
from pydantic import BaseModel, Field
logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
logger = logging.getLogger(__name__)


class ScreeningAnalysisInput(BaseModel):
    case_details: str = Field(description="JSON string of case details from get_case_details")
    search_results: str = Field(description="Web search results about the person from search_internet")
    pep_results: str = Field(
        default="",
        description="Optional JSON string from pep_screening (severity HIGH/MEDIUM and pep_summary). Include when PEP was run before web search.",
    )


class ScreeningAnalysisTool(BaseTool):
    """Analyze case details and web search results to produce a KYC screening analysis result."""

    name: str = "produce_screening_analysis"
    description: str = (
        "Takes the output of get_case_details, pep_screening (optional), and search_internet. "
        "Analyzes them and produces a screening analysis result as JSON with analysis_result, "
        "analysis_summary, severity (from PEP: HIGH/MEDIUM or none), and pep_summary."
    )
    args_schema: Type[ScreeningAnalysisInput] = ScreeningAnalysisInput

    def _run(self, case_details: str, search_results: str, pep_results: str = "") -> str:
        """Analyze case, optional PEP results, and search results; produce screening analysis JSON."""
        logger.info("produce_screening_analysis input: case_details len=%s, search_results len=%s, pep_results len=%s",
                    len(case_details) if case_details else 0,
                    len(search_results) if search_results else 0,
                    len(pep_results) if pep_results else 0)
        if not case_details:
            return json.dumps({"error": "case_details is required"})
        if not search_results:
            return json.dumps({"error": "search_results is required"})

        severity = None
        pep_summary = ""
        if pep_results and pep_results.strip():
            try:
                pep = json.loads(pep_results) if isinstance(pep_results, str) else pep_results
                severity = pep.get("severity")
                pep_summary = pep.get("pep_summary") or ""
            except json.JSONDecodeError:
                pass

        try:
            case = json.loads(case_details) if isinstance(case_details, str) else case_details
        except json.JSONDecodeError:
            return json.dumps({"error": "Invalid case_details JSON"})

        # search_results may be raw string or JSON with case_id + search_results, or a dict (from agent)
        search_results_text = search_results
        case_id_from_search = None
        if isinstance(search_results, dict):
            search_results_text = search_results.get("search_results", "")
            if not isinstance(search_results_text, str):
                search_results_text = json.dumps(search_results_text) if search_results_text else ""
            case_id_from_search = search_results.get("case_id")
        elif isinstance(search_results, str) and search_results.strip().startswith("{"):
            try:
                search_parsed = json.loads(search_results)
                if isinstance(search_parsed, dict):
                    search_results_text = search_parsed.get("search_results", search_results)
                    case_id_from_search = search_parsed.get("case_id")
            except json.JSONDecodeError:
                pass
        # Ensure we always have a string for the LLM (slicing a dict would raise)
        if not isinstance(search_results_text, str):
            search_results_text = str(search_results_text) if search_results_text else ""

        name = "Unknown"
        case_id = "Unknown"
        if isinstance(case, dict):
            case_id = case.get("caseId") or case.get("case_id") or "Unknown"
            if case_id_from_search:
                case_id = case_id_from_search
            identity = case.get("identity") or {}
            name = identity.get("fullName", "Unknown") if isinstance(identity, dict) else "Unknown"
        
        # Use LLM for analysis (include PEP severity/summary when provided)
        analysis_result, analysis_summary, search_results_summary = self._analyze_with_llm(
            search_results_text, person_name=name, pep_severity=severity, pep_summary=pep_summary
        )

        out_obj = {
            "case_id": case_id,
            "name": name,
            "analysis_result": analysis_result,
            "analysis_summary": analysis_summary,
            "search_results_summary": search_results_summary,
        }
        if severity is not None:
            out_obj["severity"] = severity
        if pep_summary:
            out_obj["pep_summary"] = pep_summary
        out = json.dumps(out_obj, indent=2)
        logger.info("produce_screening_analysis output: analysis_result=%s", analysis_result)
        return out

    def _analyze_with_llm(
        self,
        search_results: str,
        person_name: str = "Unknown",
        pep_severity: Optional[str] = None,
        pep_summary: str = "",
    ):
        """Use Bedrock LLM to analyze search results and optional PEP outcome; determine screening (OK, NOK, AMBIGUOUS)."""
        # Ensure string for slicing (agent may pass dict)
        text = search_results if isinstance(search_results, str) else str(search_results)
        text_truncated = text[:12000] if len(text) > 12000 else text
        logger.info(
            "_analyze_with_llm: person_name=%s, pep_severity=%s, input length=%s (truncated to %s)",
            person_name, pep_severity, len(text), len(text_truncated),
        )

        pep_block = ""
        if pep_severity or pep_summary:
            pep_block = f"""
**PEP/Sanctions API result (run before web search):**
- Severity: {pep_severity or 'none'}
- Summary: {pep_summary or 'N/A'}
If severity is HIGH (sanctions match), the screening outcome must reflect that. If severity is MEDIUM (PEP only), consider it in your analysis alongside web search.
"""

        # Bedrock model: use inference profile ID (no "bedrock/" prefix for boto3)
        prompt = f"""You are a KYC (Know Your Customer) compliance analyst.

**Person being screened (from case details):** "{person_name}"
{pep_block}
Your task: Determine whether the PEP/sanctions result (if any) and the web search results below contain adverse media, sanctions, PEP (Politically Exposed Person), fraud, criminal activity, or other compliance risks **that actually refer to this specific person** ("{person_name}").

**Matching rules:**
- **Match the results to the name above.** Only treat content as adverse if it clearly refers to or implicates **"{person_name}"** (the person being screened). Same or similar names can refer to different people — only flag as adverse when the context (e.g. role, location, dates) indicates it is the same individual.
- If results mention adverse topics but are about **other people** (different person with same/similar name, or unrelated individuals/entities), return **OK** — the findings are not about the person being screened.
- If results are generic, about unrelated topics, or mention the name only in passing without clearly identifying "{person_name}" in an adverse context, return **OK**.
- Return **NOK** only when there is clear evidence that **"{person_name}"** (this specific person) is linked to adverse activity.
- When in doubt whether the content refers to "{person_name}" or to someone else, prefer **AMBIGUOUS**; do not assume that any search hit is about this person.

Search results:
{text_truncated}

Respond with a JSON object containing exactly these keys:
1. "analysis_result": one of "OK" (no adverse findings for "{person_name}", or results not about this person), "NOK" (clear adverse findings that refer to "{person_name}"), or "AMBIGUOUS" (unclear whether content refers to "{person_name}" — manual review needed)
2. "analysis_summary": a 5-10 sentence summary explaining your reasoning, including whether the results actually match and refer to "{person_name}" (the person being screened)
3. "search_results_summary": a 5-10 sentence summary of the key information in the search results (main sources, topics, and whether they relate to "{person_name}")

Examples:
{{"analysis_result": "OK", "analysis_summary": "Search results mention adverse events but do not reference or implicate the person being screened. Articles refer to other individuals or unrelated entities.", "search_results_summary": "Search returned news and public records. Content does not identify the subject as involved in adverse activity."}}
{{"analysis_result": "OK", "analysis_summary": "No adverse findings. Results are generic or about different people with similar names.", "search_results_summary": "Results include general news; no clear link to the screened person."}}
{{"analysis_result": "NOK", "analysis_summary": "Adverse findings: multiple sources confirm this person was convicted of fraud in 2018.", "search_results_summary": "Multiple sources report conviction for financial fraud for the subject. Court records and news cite the same individual."}}

Your response (JSON only, no markdown):"""

        try:
            region = os.getenv("AWS_REGION_NAME") or os.getenv("AWS_REGION") or "us-east-1"
            model_id = (os.getenv("MODEL") or "us.anthropic.claude-3-5-sonnet-20241022-v2:0").strip()
            model_id = model_id.replace("bedrock/", "")
            logger.info("Bedrock invoke: tool=%s modelId=%s region=%s", self.name, model_id, region)

            client = boto3.client("bedrock-runtime", region_name=region)
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
            logger.info("LLM response length: %s", len(content))
            # Remove markdown code block if present
            if content.startswith("```"):
                lines = content.split("\n")
                content = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
            result = json.loads(content)
            logger.info("LLM screening analysis result: %s", result)
            analysis_result = str(result.get("analysis_result", "AMBIGUOUS")).upper()
            if analysis_result not in ("OK", "NOK", "AMBIGUOUS"):
                analysis_result = "AMBIGUOUS"
            analysis_summary = str(result.get("analysis_summary", "")) or "Analysis completed."
            search_results_summary = str(result.get("search_results_summary", "")) or "No search results summary available."
        except Exception as e:
            logger.exception("LLM screening analysis failed: %s", e)
            analysis_result = "AMBIGUOUS"
            analysis_summary = f"Analysis failed: {str(e)}. Manual review required."
            search_results_summary = ""

        return analysis_result, analysis_summary, search_results_summary
