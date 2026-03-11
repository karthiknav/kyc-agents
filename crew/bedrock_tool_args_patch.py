"""
Monkey-patch for CrewAI + Bedrock: extract tool arguments from Bedrock's 'input' field.

CrewAI bug: crew_agent_executor.py uses
  func_args = func_info.get("arguments", "{}") or tool_call.get("input", {})
The default "{}" is truthy, so the 'or' never uses tool_call.get("input", {}).
Bedrock sends arguments in tool_call["input"], so tools receive empty {}.

Fix: use func_info.get("arguments") or tool_call.get("input") or {}
"""

from typing import Any


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
        func_info = tool_call.get("function", {})
        func_name = sanitize_tool_name(
            func_info.get("name", "") or tool_call.get("name", "")
        )
        # Fixed: no default "{}" so Bedrock's tool_call["input"] is used when arguments is missing
        func_args = func_info.get("arguments") or tool_call.get("input") or {}
        return call_id, func_name, func_args
    return None


def apply_bedrock_tool_args_patch() -> None:
    """Apply monkey-patch so Bedrock tool calls receive correct arguments."""
    from crewai.agents import crew_agent_executor

    crew_agent_executor.CrewAgentExecutor._parse_native_tool_call = (
        _parse_native_tool_call_bedrock_fixed
    )
