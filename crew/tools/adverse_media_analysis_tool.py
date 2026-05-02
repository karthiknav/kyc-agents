"""Tool to analyze adverse media results and produce a structured outcome."""
import json
import logging
import os
from typing import Type

import boto3
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class AdverseMediaAnalysisInput(BaseModel):
    person_name: str = Field(description="Full name of the person being screened")
    search_query: str = Field(
        description="The exact query string you passed to search_internet."
    )
    search_results_json: str = Field(
        description="The raw return value from search_internet (a JSON array string). Pass it unchanged."
    )


class AdverseMediaAnalysisTool(BaseTool):
    """Analyze aggregated web search results for adverse media risks."""

    name: str = "produce_adverse_media_analysis"
    description: str = (
        "Analyze web search results for adverse media. Pass person_name, search_query (same string as search_internet), "
        "and search_results_json (the raw JSON array string from search_internet, unchanged). "
        "Returns result (OK/NOK/PENDING_REVIEW) and summary."
    )
    args_schema: Type[AdverseMediaAnalysisInput] = AdverseMediaAnalysisInput

    def _run(self, person_name: str, search_query: str, search_results_json: str) -> str:
        if not person_name:
            return json.dumps({"error": "person_name is required"})
        if not search_query:
            return json.dumps({"error": "search_query is required"})
        if not search_results_json:
            return json.dumps({"error": "search_results_json is required"})

        try:
            hits = json.loads(search_results_json)
        except json.JSONDecodeError:
            return json.dumps({"error": "search_results_json is not valid JSON"})
        if not isinstance(hits, list):
            return json.dumps({"error": "search_results_json must be a JSON array"})

        payload = {
            "searchQueries": [search_query],
            "searchResults": [{"query": search_query, "result": hits}],
        }

        queries = payload["searchQueries"]
        wrapped_results = payload["searchResults"]

        # Keep prompt input bounded
        payload_text = json.dumps(
            {"searchQueries": queries, "searchResults": wrapped_results}, indent=2
        )
        payload_text_truncated = payload_text[:12000] if len(payload_text) > 12000 else payload_text

        prompt = f"""You are a KYC (Know Your Customer) compliance analyst specializing in adverse media screening.

**Person being screened:** "{person_name}"

You are given web search queries and their raw results. Determine if there are adverse media findings (fraud, crime, corruption, money laundering, arrest, investigation, sanctions/PEP news) that clearly refer to this specific person.

**Matching rules:**
- Only flag as adverse if the results clearly refer to "{person_name}" (same individual), not just a similar name.
- If results are about other individuals with similar names or are generic/unrelated, return OK.
- If it is unclear whether results refer to this person, return PENDING_REVIEW.

Return JSON with exactly:
1. "result": "OK", "NOK", or "PENDING_REVIEW"
2. "summary": 3-8 sentences explaining your conclusion and the key evidence from search results.

Search payload:
{payload_text_truncated}

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
                inferenceConfig={"maxTokens": 1024, "temperature": 0.0},
            )
            content_parts = []
            for block in response.get("output", {}).get("message", {}).get("content", []):
                if "text" in block:
                    content_parts.append(block["text"])
            content = "".join(content_parts).strip()
            if content.startswith("```"):
                lines = content.split("\n")
                content = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
            parsed = json.loads(content)
            result = str(parsed.get("result", "PENDING_REVIEW")).upper()
            if result not in ("OK", "NOK", "PENDING_REVIEW"):
                result = "PENDING_REVIEW"
            summary = str(parsed.get("summary", "")) or "Adverse media analysis completed."
        except Exception as e:
            logger.exception("Adverse media analysis failed: %s", e)
            result = "PENDING_REVIEW"
            summary = f"Adverse media analysis failed: {str(e)}. Manual review required."

        return json.dumps({"result": result, "summary": summary}, indent=2)

