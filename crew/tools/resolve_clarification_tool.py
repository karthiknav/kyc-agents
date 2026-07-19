"""Tool to resolve a pending risk-list clarification question using a human analyst's free-text answer."""
import json
import logging
import os
import threading
import uuid
from typing import Type

import boto3
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_resolution_state = threading.local()


def get_last_resolution_id() -> str | None:
    return getattr(_resolution_state, "resolution_id", None)


def reset_resolution_state() -> None:
    _resolution_state.resolution_id = None


class ResolveClarificationInput(BaseModel):
    case_id: str = Field(description="The KYC case ID with a pending clarification request")
    analyst_answer: str = Field(description="The human reviewer's free-text answer to the pending question")


def _fetch_clarification_request(case_id: str) -> dict:
    table_name = os.environ.get("KYC_CASES_TABLE", "kyc-cases")
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(table_name)
    response = table.get_item(Key={"CaseId": case_id})
    item = response.get("Item")
    if not item:
        raise ValueError(f"No case found for caseId {case_id}")
    stages = item.get("stages") or {}
    screening = stages.get("screening") or {}
    risk = screening.get("riskListScreening") or {}
    clarification_request = risk.get("clarificationRequest")
    if not clarification_request:
        raise ValueError(f"No pending clarificationRequest found for caseId {case_id}")
    return clarification_request


class ResolveClarificationTool(BaseTool):
    """Resolve a pending risk-list clarification question against a human reviewer's answer."""

    name: str = "resolve_clarification"
    description: str = (
        "Fetches the pending clarificationRequest for a case and evaluates the human reviewer's "
        "free-text answer against it. Returns a verdict: FALSE_POSITIVE (the watchlist hit does not "
        "refer to this customer) or CONFIRMED_MATCH (it does), with reasoning."
    )
    args_schema: Type[ResolveClarificationInput] = ResolveClarificationInput

    def _run(self, case_id: str, analyst_answer: str) -> str:
        if not case_id or not case_id.strip():
            return json.dumps({"error": "case_id is required"})
        if not analyst_answer or not analyst_answer.strip():
            return json.dumps({"error": "analyst_answer is required"})

        try:
            clarification_request = _fetch_clarification_request(case_id)
        except Exception as e:
            logger.exception("resolve_clarification: failed to fetch clarification request")
            return json.dumps({"error": f"Failed to fetch clarification request: {e}"})

        resolution_id = str(uuid.uuid4())
        _resolution_state.resolution_id = resolution_id

        question = clarification_request.get("question", "")
        matched_entity = clarification_request.get("matchedEntity", {})

        prompt = f"""You are a KYC compliance reviewer resolving a pending watchlist-match clarification.

**Question that was asked:** "{question}"

**Matched watchlist entity:**
{json.dumps(matched_entity, indent=2, default=str)}

**Human reviewer's answer:** "{analyst_answer}"

Decide whether the watchlist entity refers to the same individual as the customer, based strictly on
what the reviewer's answer states (they may have access to information the system doesn't, such as
another document or an internal record — trust their stated conclusion, don't second-guess it).

Return JSON with exactly:
1. "verdict": "FALSE_POSITIVE" (not the same individual) or "CONFIRMED_MATCH" (same individual, or the
   reviewer's answer is unclear/inconclusive — default to CONFIRMED_MATCH when in doubt, since a watchlist
   hit is never auto-cleared without an unambiguous false-positive statement).
2. "reasoning": 2-4 sentences explaining the verdict based on the reviewer's answer.

Your response (JSON only, no markdown):"""

        try:
            region = os.getenv("AWS_REGION_NAME") or os.getenv("AWS_REGION") or "us-east-1"
            model_id = (os.getenv("MODEL") or "us.anthropic.claude-3-5-sonnet-20241022-v2:0").strip()
            model_id = model_id.replace("bedrock/", "")
            logger.info("resolve_clarification: modelId=%s region=%s caseId=%s", model_id, region, case_id)

            client = boto3.client("bedrock-runtime", region_name=region)
            response = client.converse(
                modelId=model_id,
                messages=[{"role": "user", "content": [{"text": prompt}]}],
                inferenceConfig={"maxTokens": 512, "temperature": 0.0},
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
            verdict = str(parsed.get("verdict", "CONFIRMED_MATCH")).upper()
            if verdict not in ("FALSE_POSITIVE", "CONFIRMED_MATCH"):
                verdict = "CONFIRMED_MATCH"
            reasoning = str(parsed.get("reasoning", "")) or "No reasoning provided."
        except Exception as e:
            logger.exception("resolve_clarification: LLM analysis failed")
            verdict = "CONFIRMED_MATCH"
            reasoning = f"Clarification analysis failed: {e}. Defaulting to CONFIRMED_MATCH — manual review required."

        out = {
            "resolution_id": resolution_id,
            "case_id": case_id,
            "verdict": verdict,
            "reasoning": reasoning,
            "question": question,
            "analyst_answer": analyst_answer,
        }
        logger.info("resolve_clarification result: case_id=%s verdict=%s", case_id, verdict)
        return json.dumps(out, indent=2, default=str)
