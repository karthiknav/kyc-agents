"""Shared utility helpers for the KYC crew."""
import json
import logging
import re

logger = logging.getLogger(__name__)


def parse_task_output(raw) -> dict | None:
    """Parse a CrewAI task output (TaskOutput, str, or dict) to a dict.

    Handles the common case where an LLM wraps JSON in markdown code fences
    (```json ... ```) or adds explanatory text before/after the JSON object.
    Returns None and logs an error if no JSON object can be extracted.
    """
    if hasattr(raw, "raw"):
        raw = raw.raw
    if isinstance(raw, dict):
        return raw

    if not isinstance(raw, str):
        logger.error("parse_task_output: unexpected type %s", type(raw))
        return None

    text = raw.strip()

    # Direct parse — fast path for clean JSON output.
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Strip markdown code fences: ```json\n{...}\n``` or ```\n{...}\n```
    fenced = re.sub(r"^```(?:json)?\s*\n?", "", text)
    fenced = re.sub(r"\n?```\s*$", "", fenced).strip()
    try:
        return json.loads(fenced)
    except json.JSONDecodeError:
        pass

    # Last resort: find the first {...} block in the text.
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    logger.error("parse_task_output: could not extract JSON from output: %.200s", text)
    return None
