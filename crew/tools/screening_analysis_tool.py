"""Tool to analyze case details and search results and produce a screening analysis."""
import json
import logging
from typing import Type

from crewai.tools import BaseTool
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field
logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
logger = logging.getLogger(__name__)


class ScreeningAnalysisInput(BaseModel):
    case_details: str = Field(description="JSON string of case details from get_case_details")
    search_results: str = Field(description="Web search results about the person from search_person")


class ScreeningAnalysisTool(BaseTool):
    """Analyze case details and web search results to produce a KYC screening analysis result."""

    name: str = "produce_screening_analysis"
    description: str = (
        "Takes the output of get_case_details and search_person, analyzes them, "
        "and produces a screening analysis result as JSON with analysis_result and analysis_summary."
    )
    args_schema: Type[ScreeningAnalysisInput] = ScreeningAnalysisInput

    def _run(self, case_details: str, search_results: str) -> str:
        """Analyze case and search results, produce screening analysis JSON."""
        logger.info("produce_screening_analysis input: case_details len=%s, search_results len=%s",
                    len(case_details) if case_details else 0, len(search_results) if search_results else 0)
        if not case_details:
            return json.dumps({"error": "case_details is required"})
        if not search_results:
            return json.dumps({"error": "search_results is required"})

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
        
        # Use LLM for analysis of search results
        analysis_result, analysis_summary, search_results_summary = self._analyze_with_llm(search_results_text)

        out = json.dumps({
            "case_id": case_id,
            "name": name,
            "analysis_result": analysis_result,
            "analysis_summary": analysis_summary,
            "search_results_summary": search_results_summary,
        }, indent=2)
        logger.info("produce_screening_analysis output: analysis_result=%s", analysis_result)
        return out

    def _analyze_with_llm(self, search_results: str):
        """Use LLM to analyze search results and determine screening outcome (OK, NOK, AMBIGUOUS)."""
        # Ensure string for slicing (agent may pass dict)
        text = search_results if isinstance(search_results, str) else str(search_results)
        text_truncated = text[:12000] if len(text) > 12000 else text
        logger.info("_analyze_with_llm: input length=%s (truncated to %s)", len(text), len(text_truncated))
        llm = ChatOpenAI(
            model="gpt-4o-mini",
            temperature=0,
        )
        prompt = f"""You are a KYC (Know Your Customer) compliance analyst.
Analyze the following web search results about a person for adverse media, sanctions, PEP (Politically Exposed Person), fraud, criminal activity, or other compliance risks.

Search results:
{text_truncated}

Respond with a JSON object containing exactly these keys:
1. "analysis_result": one of "OK" (no adverse findings), "NOK" (clear adverse findings), or "AMBIGUOUS" (unclear or investigatory content requiring manual review)
2. "analysis_summary": a 5-10 sentence summary explaining your reasoning
3. "search_results_summary": a 5-10 sentence summary of the key information found in the web search results (main sources, topics, and any notable findings)

Example:
{{"analysis_result": "OK", "analysis_summary": "No adverse findings in search results.", "search_results_summary": "Search returned news articles and public records. No sanctions or adverse media identified. Subject appears in business and professional contexts only."}}
{{"analysis_result": "NOK", "analysis_summary": "Adverse findings: convicted of fraud in 2018.", "search_results_summary": "Multiple sources report conviction for financial fraud. Subject was charged in 2018 and sentenced to..."}}

Your response (JSON only, no markdown):"""

        try:
            response = llm.invoke(prompt)
            logger.info("LLM response: %s", response)
            content = response.content.strip()
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
