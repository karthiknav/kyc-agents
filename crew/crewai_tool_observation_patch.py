"""
CrewAI appends the full tools list to every N-th tool observation (ToolUsage).

Default: _remember_format_after_usages == 3, so the 3rd tool (often extract_document_text)
gets a massive \"You ONLY have access...\" block after the real output. That blows up
context, triggers empty Bedrock responses, and looks like the LLM \"ignored\" the tool.

This patch disables those periodic reminders. Set KYC_CREWAI_TOOL_FORMAT_REMINDERS=1
to keep CrewAI's default behavior (useful for debugging).
"""

import os


def _should_remember_format_disabled(self) -> bool:
    return False


def apply_slim_tool_observations_patch() -> None:
    """Stop appending full tool definitions to tool results (ReAct path)."""
    if os.getenv("KYC_CREWAI_TOOL_FORMAT_REMINDERS", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        return

    from crewai.tools.tool_usage import ToolUsage

    ToolUsage._should_remember_format = _should_remember_format_disabled  # type: ignore[method-assign]
