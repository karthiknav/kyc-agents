"""
Monkey-patch for CrewAI + Bedrock: ensure tool arguments are taken from Bedrock's 'input' field.

Why:
Some CrewAI versions parse tool args from tool_call["function"]["arguments"] and accidentally
default that to a truthy string like " {}", which prevents falling back to tool_call["input"].
Bedrock Converse tool calls commonly return:
  {"name": "...", "input": {...}, "toolUseId": "..."}
so input must be used.

This patch targets the current CrewAI path:
  crewai.utilities.agent_utils.parse_tool_call_args
(which is imported and used by CrewAgentExecutor). [1](https://github.com/arunahk/CrewAI/blob/main/lib/crewai/src/crewai/agents/crew_agent_executor.py)[2](https://github.com/crewAIInc/crewAI/blob/main/lib/crewai/src/crewai/utilities/agent_utils.py)
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def _maybe_json_loads(v: Any) -> Any:
    """Parse JSON string into dict if applicable; otherwise return as-is."""
    if isinstance(v, str):
        s = v.strip()
        if (s.startswith("{") and s.endswith("}")) or (s.startswith("[") and s.endswith("]")):
            try:
                return json.loads(s)
            except Exception:
                return v
    return v


def _bedrock_args_from_tool_call(tool_call: Any) -> Dict[str, Any]:
    """
    Extract args dict from various tool_call shapes, prioritizing Bedrock 'input'.
    """
    # Bedrock dict shape: {"name": "...", "input": {...}, "toolUseId": "..."}
    if isinstance(tool_call, dict):
        if isinstance(tool_call.get("input"), dict):
            return tool_call["input"]

        # OpenAI-like dict shape: {"function": {"arguments": "..."}}
        func = tool_call.get("function")
        if isinstance(func, dict):
            args = func.get("arguments")
            args = _maybe_json_loads(args)
            if isinstance(args, dict):
                return args

        return {}

    # Bedrock object shape: tool_call.input
    if hasattr(tool_call, "input"):
        inp = getattr(tool_call, "input", None)
        if isinstance(inp, dict):
            return inp

    # OpenAI object shape: tool_call.function.arguments
    if hasattr(tool_call, "function") and getattr(tool_call, "function") is not None:
        fn = tool_call.function
        args = getattr(fn, "arguments", None)
        args = _maybe_json_loads(args)
        if isinstance(args, dict):
            return args

    return {}


def apply_bedrock_tool_args_patch() -> None:
    """
    Patch crewai.utilities.agent_utils.parse_tool_call_args so Bedrock tool calls
    pass real arguments (from tool_call['input']) instead of {}.
    """
    from crewai.utilities import agent_utils

    if getattr(agent_utils, "__bedrock_tool_args_patch_applied__", False):
        logger.info("✅ Bedrock tool args patch already applied")
        return

    if not hasattr(agent_utils, "parse_tool_call_args"):
        logger.warning("❌ parse_tool_call_args not found in crewai.utilities.agent_utils; patch not applied")
        return

    original = agent_utils.parse_tool_call_args

    def patched_parse_tool_call_args(tool_call: Any, *args, **kwargs):
        # First, try original CrewAI behavior
        try:
            out = original(tool_call, *args, **kwargs)
        except TypeError:
            # Some versions may have different signature; call with tool_call only
            out = original(tool_call)

        # If CrewAI returned empty (common bug case), fall back to Bedrock input
        if not out or (isinstance(out, dict) and len(out) == 0):
            fallback = _bedrock_args_from_tool_call(tool_call)
            if fallback:
                logger.info("✅ Tool args recovered from Bedrock tool_call['input']")
                return fallback

        # Also handle the "truthy string {}" scenario
        if isinstance(out, str):
            parsed = _maybe_json_loads(out)
            if isinstance(parsed, dict) and parsed:
                return parsed
            if out.strip() in ("{}", "{ }", "[]"):
                fallback = _bedrock_args_from_tool_call(tool_call)
                if fallback:
                    logger.info("✅ Tool args recovered from Bedrock tool_call['input'] (string default case)")
                    return fallback

        return out

    # Apply patch
    agent_utils.__bedrock_tool_args_patch_original__ = original
    agent_utils.parse_tool_call_args = patched_parse_tool_call_args
    agent_utils.__bedrock_tool_args_patch_applied__ = True

    logger.info("✅ Patched crewai.utilities.agent_utils.parse_tool_call_args")

    # If CrewAgentExecutor already imported parse_tool_call_args directly, patch that reference too.
    try:
        from crewai.agents import crew_agent_executor as cae
        if hasattr(cae, "parse_tool_call_args"):
            cae.parse_tool_call_args = patched_parse_tool_call_args
            logger.info("✅ Patched crewai.agents.crew_agent_executor.parse_tool_call_args reference")
    except Exception:
        # Not fatal; module may not be loaded yet.
        pass