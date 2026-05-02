"""Tool to analyse an analyst's override justification against persisted KYC stage results."""
import json
import logging
import os
from typing import Type

import boto3
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class AnalyzeOverrideInput(BaseModel):
    stage_details_json: str = Field(
        description="JSON string returned by get_case_stage_details"
    )
    identity_json: str = Field(
        description="JSON string returned by get_case_details, used to evaluate PEP/sanctions false-positive claims against the subject's actual DOB and nationality"
    )
    analyst_comments: str = Field(
        description="The analyst's written justification for overriding the escalation"
    )
    analyst_decision: str = Field(
        description="The analyst's requested outcome: APPROVED or REJECTED"
    )


class AnalyzeOverrideTool(BaseTool):
    """Analyse an analyst's override justification against persisted KYC risk flags."""

    name: str = "analyze_override"
    description: str = (
        "Takes the output of get_case_stage_details, the output of get_case_details (subject identity), "
        "the analyst's written justification, and their requested decision (APPROVED/REJECTED). "
        "Uses an LLM to evaluate whether the justification credibly addresses each risk flag, "
        "cross-referencing the subject's DOB and nationality when evaluating PEP/sanctions claims. "
        "Returns a structured verdict: override_verdict (APPROVED/REJECTED), reasoning, and risk_flags_evaluated."
    )
    args_schema: Type[AnalyzeOverrideInput] = AnalyzeOverrideInput

    def _run(self, stage_details_json: str, identity_json: str, analyst_comments: str, analyst_decision: str) -> str:
        logger.info(
            "analyze_override: analyst_decision=%s, comments_len=%s",
            analyst_decision,
            len(analyst_comments) if analyst_comments else 0,
        )

        if not stage_details_json:
            return json.dumps({"error": "stage_details_json is required"})
        if not identity_json:
            return json.dumps({"error": "identity_json is required"})
        if not analyst_comments:
            return json.dumps({"error": "analyst_comments is required"})
        if not analyst_decision:
            return json.dumps({"error": "analyst_decision is required"})

        try:
            stages = json.loads(stage_details_json) if isinstance(stage_details_json, str) else stage_details_json
        except json.JSONDecodeError:
            return json.dumps({"error": "stage_details_json is not valid JSON"})

        try:
            identity = json.loads(identity_json) if isinstance(identity_json, str) else identity_json
        except json.JSONDecodeError:
            identity = {}

        case_id = stages.get("case_id", "unknown")
        verdict, reasoning, flags = self._analyze_with_llm(stages, identity, analyst_comments, analyst_decision)

        result = {
            "case_id": case_id,
            "override_verdict": verdict,
            "reasoning": reasoning,
            "risk_flags_evaluated": flags,
            "analyst_comments": analyst_comments,
            "analyst_decision": analyst_decision,
        }
        logger.info("analyze_override result: case_id=%s verdict=%s flags=%s", case_id, verdict, flags)
        return json.dumps(result, indent=2)

    def _analyze_with_llm(self, stages: dict, identity: dict, analyst_comments: str, analyst_decision: str):
        doc = stages.get("documentProcessing") or {}
        risk = stages.get("riskListScreening") or {}
        media = stages.get("adverseMedia") or {}

        stages_text = json.dumps(
            {
                "documentProcessing": doc,
                "riskListScreening": risk,
                "adverseMedia": media,
            },
            indent=2,
        )
        identity_text = json.dumps(identity.get("identity") or identity, indent=2)

        prompt = f"""You are a senior KYC compliance reviewer evaluating an analyst's request to override an AI-escalated case.

## Subject Identity
{identity_text}

## KYC Stage Results
{stages_text}

## Analyst's Override Request
Decision requested: {analyst_decision}
Justification: "{analyst_comments}"

## Your Task
1. Identify every risk flag present in the stage results (e.g. document MISMATCH/PARTIAL_MATCH, PEP/sanctions HIT, adverse media NOK/PENDING_REVIEW).
2. For each flag, assess whether the analyst's justification specifically and credibly addresses it,
   using the subject's identity (DOB, nationality, fullName) as ground truth where relevant:
   - A PEP/sanctions HIT requires a concrete false-positive explanation cross-referenced against the
     subject's actual DOB and nationality above. If the analyst claims a DOB or nationality mismatch,
     verify it is consistent with the identity data. Generic statements ("I think it's fine") are NEVER sufficient.
   - An adverse media NOK requires a clear explanation of why the negative coverage does not apply to this subject.
   - A document MISMATCH requires an explanation of each discrepancy listed in documentProcessing.discrepancies.
3. If all flags are credibly addressed AND the analyst requested APPROVED → verdict is APPROVED.
   If any flag is not credibly addressed OR the analyst requested REJECTED → verdict is REJECTED.

Respond with JSON only (no markdown):
{{
  "override_verdict": "APPROVED" or "REJECTED",
  "reasoning": "detailed explanation referencing each risk flag and whether the justification addressed it",
  "risk_flags_evaluated": ["list", "of", "risk flags found"]
}}"""

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
            verdict = str(parsed.get("override_verdict", "REJECTED")).upper()
            if verdict not in ("APPROVED", "REJECTED"):
                verdict = "REJECTED"
            reasoning = str(parsed.get("reasoning", "")) or "No reasoning provided."
            flags = parsed.get("risk_flags_evaluated", [])
            if not isinstance(flags, list):
                flags = [str(flags)]
            return verdict, reasoning, flags

        except Exception as e:
            logger.exception("analyze_override LLM call failed: %s", e)
            return (
                "REJECTED",
                f"Override analysis failed: {str(e)}. Defaulting to REJECTED — manual review required.",
                [],
            )
