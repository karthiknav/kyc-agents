"""CrewAI + Langfuse: capture tool runs that bypass BaseTool.run.

OpenInference instruments ``BaseTool.run``, but CrewAI executes tools via
``CrewStructuredTool.invoke`` calling ``self._run`` directly (see
``crewai.tools.base_tool.BaseTool.to_structured_tool``). This patch adds Langfuse
``tool`` observations around that path.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Mapping, Tuple

logger = logging.getLogger(__name__)
_patched = False


def patch_crewai_structured_tool_for_langfuse() -> None:
    global _patched
    if _patched:
        return

    from langfuse import get_client
    from wrapt import wrap_function_wrapper

    def _invoke_wrapper(
        wrapped: Callable[..., Any],
        instance: Any,
        args: Tuple[Any, ...],
        kwargs: Mapping[str, Any],
    ) -> Any:
        lf = get_client()
        tool_name = getattr(instance, "name", None) or instance.__class__.__name__
        input_payload = args[0] if len(args) > 0 else kwargs.get("input")
        with lf.start_as_current_observation(
            as_type="tool",
            name=str(tool_name),
            input=input_payload,
        ) as obs:
            try:
                out = wrapped(*args, **kwargs)
            except Exception:
                obs.update(level="ERROR")
                raise
            obs.update(output=out)
            return out

    wrap_function_wrapper(
        module="crewai.tools.structured_tool",
        name="CrewStructuredTool.invoke",
        wrapper=_invoke_wrapper,
    )
    _patched = True
    logger.info("Langfuse: patched CrewStructuredTool.invoke for tool observations")
