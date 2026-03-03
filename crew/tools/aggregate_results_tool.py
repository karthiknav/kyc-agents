"""Tool to aggregate sub-agent results and produce the final KYC decision."""
import json
import logging
from typing import Type

from crewai.tools import BaseTool
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_MAX_INPUT_CHARS = 12000


class AggregateKYCResultsInput(BaseModel):
    case_id: str = Field(description="The KYC case ID")
    document_processing_result: str = Field(
        description="JSON string of the documentProcessing stage result from get_case_stages"
    )
    screening_result: str = Field(
        description="JSON string of the screening stage result from get_case_stages"
    )


class AggregateKYCResultsTool(BaseTool):
    """Aggregate document processing and sanctions screening results to produce the final KYC decision."""

    name: str = "aggregate_kyc_results"
    description: str = (
        "Takes the documentProcessing and screening stage results and uses an LLM to produce "
        "a final KYC decision: APPROVE or ESCALATE. "
        "APPROVE only when document comparison is MATCH and screening is OK. "
        "ESCALATE for any PARTIAL_MATCH, MISMATCH, NOK, or AMBIGUOUS result. "
        "Returns JSON with decision, reason, and recommendation_summary."
    )
    args_schema: Type[AggregateKYCResultsInput] = AggregateKYCResultsInput

    def _run(
        self,
        case_id: str,
        document_processing_result: str,
        screening_result: str,
    ) -> str:
        logger.info(
            "aggregate_kyc_results input: case_id=%s, doc_result len=%s, screening len=%s",
            case_id,
            len(document_processing_result) if document_processing_result else 0,
            len(screening_result) if screening_result else 0,
        )
        if not case_id:
            return json.dumps({"error": "case_id is required"})
        if not document_processing_result:
            return json.dumps({"error": "document_processing_result is required — sub-agent may not have completed yet"})
        if not screening_result:
            return json.dumps({"error": "screening_result is required — sub-agent may not have completed yet"})

        # Guard: both results must be non-trivial JSON (not error strings)
        for label, raw in [("document_processing_result", document_processing_result), ("screening_result", screening_result)]:
            try:
                parsed = json.loads(raw) if isinstance(raw, str) else raw
                if isinstance(parsed, dict) and "error" in parsed:
                    logger.warning("aggregate_kyc_results: %s contains an error: %s", label, parsed["error"])
                    # Treat any error result as ESCALATE immediately — conservative
                    return json.dumps({
                        "case_id": case_id,
                        "decision": "ESCALATE",
                        "reason": [f"{label} returned an error: {parsed['error']}"],
                        "recommendation_summary": f"Cannot make an automated decision because {label} failed. Manual review required.",
                    })
            except json.JSONDecodeError:
                pass  # raw string result — still send to LLM

        # Parse inputs for LLM; fall back to raw string if not JSON
        try:
            doc_parsed = json.loads(document_processing_result) if isinstance(document_processing_result, str) else document_processing_result
            doc_text = json.dumps(doc_parsed, indent=2)
        except json.JSONDecodeError:
            doc_text = document_processing_result

        try:
            screening_parsed = json.loads(screening_result) if isinstance(screening_result, str) else screening_result
            screening_text = json.dumps(screening_parsed, indent=2)
        except json.JSONDecodeError:
            screening_text = screening_result

        combined = f"Document Processing:\n{doc_text}\n\nSanctions Screening:\n{screening_text}"
        if len(combined) > _MAX_INPUT_CHARS:
            combined = combined[:_MAX_INPUT_CHARS]

        decision, reason, recommendation_summary = self._decide_with_llm(combined)

        result = {
            "case_id": case_id,
            "decision": decision,
            "reason": reason,
            "recommendation_summary": recommendation_summary,
        }
        logger.info("aggregate_kyc_results output: case_id=%s, decision=%s", case_id, decision)
        return json.dumps(result, indent=2)

    def _decide_with_llm(self, combined_results: str):
        """Use LLM to evaluate both sub-agent results and make the final KYC decision."""
        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

        prompt = f"""You are a senior KYC compliance officer making the final approval decision.

You have received the results from two KYC verification sub-agents:

{combined_results}

Based on these results, make the final KYC decision.

Decision rules (apply strictly):
- APPROVE: document comparison result is "MATCH" AND screening result is "OK"
- ESCALATE: any of the following → document result is "PARTIAL_MATCH" or "MISMATCH", OR screening result is "NOK" or "AMBIGUOUS"
- When in doubt, always ESCALATE (conservative approach protects against compliance risk)

Respond with a JSON object containing exactly these keys:
1. "decision": "APPROVE" or "ESCALATE"
2. "reason": list of strings — each reason explaining a specific factor that influenced the decision
3. "recommendation_summary": a 5-10 sentence explanation of the overall assessment and what action should follow

Example:
{{"decision": "ESCALATE", "reason": ["Document comparison returned PARTIAL_MATCH with date of birth discrepancy", "Sanctions screening returned AMBIGUOUS — possible PEP match"], "recommendation_summary": "The applicant's documents show minor discrepancies and the sanctions check is inconclusive. A compliance officer should manually review the uploaded documents and clarify the date of birth mismatch before approving."}}

Your response (JSON only, no markdown):"""

        try:
            response = llm.invoke(prompt)
            content = response.content.strip()
            if content.startswith("```"):
                lines = content.split("\n")
                content = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
            parsed = json.loads(content)
            logger.info("LLM aggregate decision: %s", parsed)

            decision = str(parsed.get("decision", "ESCALATE")).upper()
            if decision not in ("APPROVE", "ESCALATE"):
                decision = "ESCALATE"
            reason = parsed.get("reason", [])
            if not isinstance(reason, list):
                reason = [str(reason)]
            recommendation_summary = str(parsed.get("recommendation_summary", "")) or "Review required."
        except Exception as e:
            logger.exception("LLM aggregate decision failed: %s", e)
            decision = "ESCALATE"
            reason = [f"Automated aggregation failed: {str(e)}"]
            recommendation_summary = f"Aggregation failed: {str(e)}. Manual review required."

        return decision, reason, recommendation_summary
