"""Tool that fetches identity, searches the web, and produces an adverse media verdict in one step."""
import json
import logging
import os
import threading
import uuid
from typing import Type

import boto3
from crewai.tools import BaseTool
from ddgs import DDGS
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_adverse_state = threading.local()


def get_last_adverse_id() -> str | None:
    return getattr(_adverse_state, "analysis_id", None)


def get_last_adverse_result() -> dict | None:
    return getattr(_adverse_state, "last_result", None)


def reset_adverse_state() -> None:
    _adverse_state.analysis_id = None
    _adverse_state.last_result = None


def _fetch_full_name(case_id: str) -> str:
    """Fetch identity.fullName from DynamoDB for the given case."""
    table_name = os.environ.get("KYC_CASES_TABLE", "kyc-agent-storage-kyc-cases")
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(table_name)
    response = table.get_item(Key={"CaseId": case_id})
    item = response.get("Item")
    if not item:
        raise ValueError(f"No case found for caseId {case_id}")
    identity = item.get("identity") or {}
    full_name = (identity.get("fullName") or "").strip() if isinstance(identity, dict) else ""
    if not full_name:
        raise ValueError(f"identity.fullName is missing for caseId {case_id}")
    return full_name


def _search(query: str) -> list:
    """Run a DuckDuckGo search and return results as a list."""
    max_results = int(os.getenv("SEARCH_MAX_RESULTS", "5"))
    ddg = DDGS()
    return list(ddg.text(query, max_results=max_results))


class AdverseMediaAnalysisInput(BaseModel):
    case_id: str = Field(description="The KYC case ID to screen for adverse media.")


class AdverseMediaAnalysisTool(BaseTool):
    """Fetch identity, search the web for adverse media, and return a structured verdict."""

    name: str = "produce_adverse_media_analysis"
    description: str = (
        "Fetches identity data from DynamoDB, performs a DuckDuckGo web search for adverse media "
        "(fraud, crime, money laundering, arrest, investigation), then analyses the results with an LLM. "
        "Pass only the case_id — the tool handles fetch, search, and analysis internally. "
        "Returns result (OK/NOK/PENDING_REVIEW), summary, searchQueries, and analysis_id."
    )
    args_schema: Type[AdverseMediaAnalysisInput] = AdverseMediaAnalysisInput

    def _run(self, case_id: str) -> str:
        if not case_id or not case_id.strip():
            return json.dumps({"error": "case_id is required"})

        # Issue nonce early so even an error return carries a valid analysis_id for the guardrail.
        analysis_id = str(uuid.uuid4())
        _adverse_state.analysis_id = analysis_id

        # Step 1: fetch identity from DynamoDB
        try:
            full_name = _fetch_full_name(case_id)
        except Exception as e:
            logger.exception("produce_adverse_media_analysis: DynamoDB fetch failed")
            out = {
                "analysis_id": analysis_id,
                "result": "PENDING_REVIEW",
                "summary": f"Could not fetch identity for {case_id}: {e}. Manual review required.",
                "searchQueries": [],
            }
            _adverse_state.last_result = out
            return json.dumps(out, indent=2)

        # Step 2: web search
        search_query = f"{full_name} fraud crime money laundering arrest investigation adverse media"
        try:
            hits = _search(search_query)
        except Exception as e:
            logger.exception("produce_adverse_media_analysis: DuckDuckGo search failed")
            hits = []

        # Step 3: LLM analysis
        payload = {"searchQueries": [search_query], "searchResults": [{"query": search_query, "result": hits}]}
        payload_text = json.dumps(payload, indent=2)
        payload_text_truncated = payload_text[:12000] if len(payload_text) > 12000 else payload_text

        prompt = f"""You are a KYC (Know Your Customer) compliance analyst specializing in adverse media screening.

**Person being screened:** "{full_name}"

You are given web search queries and their raw results. Determine if there are adverse media findings (fraud, crime, corruption, money laundering, arrest, investigation, sanctions/PEP news) that clearly refer to this specific person.

**Matching rules:**
- Only flag as adverse if the results clearly refer to "{full_name}" (same individual), not just a similar name.
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
            logger.info("produce_adverse_media_analysis: modelId=%s region=%s caseId=%s", model_id, region, case_id)

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
            logger.exception("produce_adverse_media_analysis: LLM analysis failed")
            result = "PENDING_REVIEW"
            summary = f"Adverse media analysis failed: {e}. Manual review required."

        out = {
            "analysis_id": analysis_id,
            "case_id": case_id,
            "name": full_name,
            "result": result,
            "summary": summary,
            "searchQueries": [search_query],
            "rawResponse": {"searchQueries": [search_query], "searchResults": hits},
        }
        _adverse_state.last_result = out
        return json.dumps(out, indent=2)
