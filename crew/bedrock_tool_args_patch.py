"""
Monkey-patches for CrewAI + AWS Bedrock native provider (Converse API).

1) Tool-call arguments: Bedrock sends tool_use["input"] (dict). CrewAI may read
   func_info["arguments"] first; the default "{}" is truthy and blocks "input".
   We coerce dict input and parse JSON strings when needed.

2) Empty assistant messages: Bedrock sometimes returns output.message.content=[] —
   especially on the *recursive* Converse call right after a toolResult (nested
   _handle_converse). An earlier retry patch only ran at TLS depth 1, so those
   empty replies never got a nudge. We retry with a user nudge at any depth.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_BEDROCK_HANDLE_CONVERS_ORIGINAL = None

_EMPTY_RESPONSE_APOLOGY = (
    "I apologize, but I received an empty response. Please try again."
)

_NUDGE_MESSAGE = (
    "Your last model turn had no output (empty content from Bedrock). "
    "Continue now: Thought + Action + Action Input (JSON only), or Thought + Final Answer "
    "with the required JSON. Do not reply with empty content."
)

_NUDGE_MESSAGE_SHORT = (
    "Empty assistant message again. Reply immediately with your next Thought/Action or Final Answer."
)


def _coerce_tool_args_from_dict(tool_call: dict) -> dict:
    """Prefer Bedrock Converse ``input`` dict; fall back to OpenAI-style ``function.arguments``."""
    inp = tool_call.get("input")
    if isinstance(inp, dict):
        return inp

    func_info = tool_call.get("function") or {}
    raw = func_info.get("arguments")
    if raw is None or raw == "":
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        s = raw.strip()
        if not s or s == "{}":
            return {}
        try:
            parsed = json.loads(s)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _parse_native_tool_call_bedrock_fixed(self, tool_call: Any):
    """Patched _parse_native_tool_call that correctly reads Bedrock's 'input' field."""
    from crewai.utilities.string_utils import sanitize_tool_name

    if hasattr(tool_call, "function"):
        call_id = getattr(tool_call, "id", f"call_{id(tool_call)}")
        func_name = sanitize_tool_name(tool_call.function.name)
        return call_id, func_name, tool_call.function.arguments
    if hasattr(tool_call, "function_call") and tool_call.function_call:
        call_id = f"call_{id(tool_call)}"
        func_name = sanitize_tool_name(tool_call.function_call.name)
        func_args = (
            dict(tool_call.function_call.args)
            if tool_call.function_call.args
            else {}
        )
        return call_id, func_name, func_args
    if hasattr(tool_call, "name") and hasattr(tool_call, "input"):
        call_id = getattr(tool_call, "id", f"call_{id(tool_call)}")
        func_name = sanitize_tool_name(tool_call.name)
        return call_id, func_name, tool_call.input
    if isinstance(tool_call, dict):
        call_id = (
            tool_call.get("id")
            or tool_call.get("toolUseId")
            or f"call_{id(tool_call)}"
        )
        func_info = tool_call.get("function") or {}
        func_name = sanitize_tool_name(
            func_info.get("name", "") or tool_call.get("name", "")
        )
        func_args = _coerce_tool_args_from_dict(tool_call)
        return call_id, func_name, func_args
    return None


def apply_bedrock_tool_args_patch() -> None:
    """Apply monkey-patch so Bedrock tool calls receive correct arguments."""
    from crewai.agents import crew_agent_executor

    crew_agent_executor.CrewAgentExecutor._parse_native_tool_call = (
        _parse_native_tool_call_bedrock_fixed
    )


def _handle_converse_with_empty_retry(
    self,
    messages,
    body,
    available_functions=None,
    from_task=None,
    from_agent=None,
):
    """
    Wrap BedrockCompletion._handle_converse.

    When Converse returns no content blocks, CrewAI returns the apology string.
    That happens often on the *inner* call after toolResult (recursion), where a
    depth==1-only retry never runs. We nudge and retry at any call depth.
    """
    global _BEDROCK_HANDLE_CONVERS_ORIGINAL
    assert _BEDROCK_HANDLE_CONVERS_ORIGINAL is not None

    try:
        max_nudges = int(os.getenv("KYC_BEDROCK_EMPTY_RESPONSE_MAX_RETRIES", "4"))
    except ValueError:
        max_nudges = 4
    max_nudges = max(1, min(max_nudges, 8))

    # Pass the same list through on the first call — CrewAI appends tool turns in place
    # and recurses; copying here would break that chain.
    result = _BEDROCK_HANDLE_CONVERS_ORIGINAL(
        self,
        messages,
        body,
        available_functions,
        from_task,
        from_agent,
    )
    if result != _EMPTY_RESPONSE_APOLOGY:
        return result

    logger.warning(
        "Bedrock returned empty message.content (after tool or mid-turn). "
        "Sending up to %s continuation nudge(s). You may also see "
        "WARNING:root:No content in Bedrock response from CrewAI.",
        max_nudges,
    )

    msgs = list(messages)
    for attempt in range(1, max_nudges + 1):
        nudge = _NUDGE_MESSAGE if attempt == 1 else _NUDGE_MESSAGE_SHORT
        logger.warning("Empty Bedrock response: continuation nudge %s/%s", attempt, max_nudges)
        msgs.append({"role": "user", "content": [{"text": nudge}]})
        result = _BEDROCK_HANDLE_CONVERS_ORIGINAL(
            self,
            msgs,
            body,
            available_functions,
            from_task,
            from_agent,
        )
        if result != _EMPTY_RESPONSE_APOLOGY:
            return result

    return result


def apply_bedrock_empty_response_retry_patch() -> None:
    """Patch Bedrock Converse to nudge/retry when the model returns empty content."""
    global _BEDROCK_HANDLE_CONVERS_ORIGINAL
    from crewai.llms.providers.bedrock.completion import BedrockCompletion

    if getattr(BedrockCompletion._handle_converse, "__name__", "") == "_handle_converse_with_empty_retry":
        return
    _BEDROCK_HANDLE_CONVERS_ORIGINAL = BedrockCompletion._handle_converse
    BedrockCompletion._handle_converse = _handle_converse_with_empty_retry
