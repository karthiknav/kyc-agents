"""
Patch: prevent assistant message prefill errors on Bedrock Converse API.

Root cause: CrewAI's ReAct loop (_invoke_loop_react) appends each model
response — including the Observation from tool results — as an `assistant`
message, then loops back and calls the LLM again with messages ending on
`assistant`. Claude on Bedrock rejects this with:
  ValidationException: "This model does not support assistant message prefill.
  The conversation must end with a user message."

CrewAI's BedrockCompletion._format_messages_for_converse already handles this
case for Cohere/Command/Coral models (lines 1836-1861 in completion.py) by
appending a continuation user message, but not for Claude.

Fix: wrap _format_messages_for_converse so that ANY trailing assistant message
gets a continuation user message appended, regardless of model family.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_PATCHED_ATTR = "_assistant_prefill_patch_applied"


def apply_bedrock_assistant_prefill_patch() -> None:
    try:
        from crewai.llms.providers.bedrock.completion import BedrockCompletion
    except ImportError as e:
        logger.warning("bedrock_assistant_prefill_patch: could not import BedrockCompletion (%s)", e)
        return

    if getattr(BedrockCompletion, _PATCHED_ATTR, False):
        return

    original = BedrockCompletion._format_messages_for_converse

    def _format_messages_with_prefill_guard(self, messages):
        converse_messages, system_message = original(self, messages)

        if converse_messages and converse_messages[-1].get("role") == "assistant":
            logger.info(
                "bedrock_assistant_prefill_patch: appending continuation user message "
                "(model=%s, last message was assistant)",
                getattr(self, "model", "unknown"),
            )
            converse_messages.append(
                {
                    "role": "user",
                    "content": [{"text": "Please continue and provide your final answer."}],
                }
            )

        return converse_messages, system_message

    BedrockCompletion._format_messages_for_converse = _format_messages_with_prefill_guard
    setattr(BedrockCompletion, _PATCHED_ATTR, True)
    logger.info("bedrock_assistant_prefill_patch applied")
