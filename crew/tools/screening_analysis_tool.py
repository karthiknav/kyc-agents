"""Tool to analyze case details and search results and produce a screening analysis."""
import json
import logging
from typing import Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

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

        # search_results may be raw string or JSON with case_id + search_results
        search_results_text = search_results
        case_id_from_search = None
        if isinstance(search_results, str) and search_results.strip().startswith("{"):
            try:
                search_parsed = json.loads(search_results)
                if isinstance(search_parsed, dict):
                    search_results_text = search_parsed.get("search_results", search_results)
                    case_id_from_search = search_parsed.get("case_id")
            except json.JSONDecodeError:
                pass

        name = "Unknown"
        case_id = "Unknown"
        if isinstance(case, dict):
            case_id = case.get("caseId") or case.get("case_id") or "Unknown"
            if case_id_from_search:
                case_id = case_id_from_search
            identity = case.get("identity") or {}
            name = identity.get("fullName", "Unknown") if isinstance(identity, dict) else "Unknown"

        # Use LLM for analysis - we'll use a simple structured prompt via CrewAI
        # Since this tool runs inside an agent, the agent can also do analysis.
        # This tool provides a structured format; the actual analysis logic
        # can be enhanced. For now we produce a template the agent can refine,
        # or we invoke the model. CrewAI tools don't have direct LLM access by default.
        # We'll do a heuristic + structured output. For production, hook to an LLM.
        analysis_result = self._analyze(search_results_text)
        analysis_summary = self._summarize(search_results_text, analysis_result)

        out = json.dumps({
            "case_id": case_id,
            "name": name,
            "analysis_result": analysis_result,
            "analysis_summary": analysis_summary,
        }, indent=2)
        logger.info("produce_screening_analysis output: analysis_result=%s", analysis_result)
        return out

    def _analyze(self, search_results: str) -> str:
        """Determine screening outcome from search results."""
        lower = search_results.lower()
        negative_keywords = ["sanction", "convicted", "fraud", "arrest", "scam", "money laundering"]
        ambiguous_keywords = ["investigation", "alleged", "accused", "controversy", "lawsuit"]

        if any(k in lower for k in negative_keywords):
            return "NOT"
        if any(k in lower for k in ambiguous_keywords):
            return "AMBIGUOUS"
        return "OK"

    def _summarize(self, search_results: str, result: str) -> str:
        """Produce a short summary."""
        if result == "NOK":
            return "Adverse findings or negative indicators found in search results."
        if result == "AMBIGUOUS":
            return "Some ambiguous or investigatory content found; manual review recommended."
        return "No adverse findings in search results."
