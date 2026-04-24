from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def _deep_remove_stop_fields(x: Any) -> None:
    """Recursively remove stopSequences / stop / stop_sequences from nested dict/list."""
    if isinstance(x, dict):
        x.pop("stopSequences", None)
        x.pop("stop", None)
        x.pop("stop_sequences", None)
        for v in x.values():
            _deep_remove_stop_fields(v)
    elif isinstance(x, list):
        for i in x:
            _deep_remove_stop_fields(i)


_REASONING_TAG_RE = re.compile(r"<reasoning>.*?</reasoning>", re.DOTALL)


def _clean_response_text(text: str) -> str:
    """Remove <reasoning> tags and truncate at self-generated Observation:.

    Some models on Bedrock don't support stopSequences. Without a stop, the model
    generates the full ReAct cycle in one shot — including writing 'Observation:'
    itself (with no content), which causes CrewAI to see an empty tool result and
    never actually call the tool.

    This strips <reasoning>...</reasoning> blocks and truncates at the first
    'Observation:' so CrewAI receives only the action JSON and can inject the
    real tool result.
    """
    text = _REASONING_TAG_RE.sub("", text)
    # Truncate at the first self-generated Observation: marker
    obs_idx = text.find("\nObservation:")
    if obs_idx != -1:
        logger.info("✅ Truncated model output at self-generated Observation: (index %d)", obs_idx)
        text = text[:obs_idx]
    return text.rstrip()


def _clean_converse_response(response: Any) -> None:
    """Post-process a Bedrock converse() response to strip self-generated stop markers."""
    try:
        content = response.get("output", {}).get("message", {}).get("content", [])
        for block in content:
            if isinstance(block, dict) and "text" in block:
                original = block["text"]
                cleaned = _clean_response_text(original)
                if cleaned != original:
                    block["text"] = cleaned
                    logger.info("✅ Cleaned Bedrock response text block")
    except Exception:
        pass  # never break the response


def _wrap_bedrock_converse(client: Any) -> None:
    """Wrap a bedrock-runtime client's converse() to strip stop fields and clean responses."""
    if not hasattr(client, "converse"):
        return

    if getattr(client, "__stopseq_converse_wrapped__", False):
        return

    original_converse = client.converse

    def converse(*args, **kwargs):
        if "stopSequences" in str(kwargs):
            logger.warning("⚠️ stopSequences detected BEFORE removal (will be stripped)")
        _deep_remove_stop_fields(kwargs)
        logger.info("✅ stopSequences stripped from Bedrock converse() request")
        response = original_converse(*args, **kwargs)
        _clean_converse_response(response)
        return response

    client.converse = converse
    client.__stopseq_converse_wrapped__ = True
    logger.info("✅ Wrapped bedrock-runtime client.converse()")


def apply_bedrock_stop_sequences_patch() -> None:
    """
    Patch BOTH boto3.client and boto3.session.Session.client to ensure we intercept
    all ways CrewAI constructs the bedrock-runtime client.
    Also adds a final optional patch to CrewAI BedrockCompletion._handle_converse.
    """
    import boto3
    import boto3.session

    if getattr(boto3, "__bedrock_stopseq_patch_applied__", False):
        logger.info("✅ Bedrock stopSequences patch already applied (global)")
        return

    logger.info("✅ Applying Bedrock stopSequences patch (boto3.client + Session.client)")

    original_boto3_client = boto3.client

    def patched_boto3_client(service_name: str, *args, **kwargs):
        c = original_boto3_client(service_name, *args, **kwargs)
        if service_name == "bedrock-runtime":
            logger.info("✅ Intercepted boto3.client('bedrock-runtime')")
            _wrap_bedrock_converse(c)
        return c

    boto3.client = patched_boto3_client

    original_session_client = boto3.session.Session.client

    def patched_session_client(self, service_name: str, *args, **kwargs):
        c = original_session_client(self, service_name, *args, **kwargs)
        if service_name == "bedrock-runtime":
            logger.info("✅ Intercepted Session().client('bedrock-runtime')")
            _wrap_bedrock_converse(c)
        return c

    boto3.session.Session.client = patched_session_client

    try:
        from crewai.llms.providers.bedrock.completion import BedrockCompletion  # type: ignore

        if not getattr(BedrockCompletion, "__stopseq_handle_converse_patched__", False):
            original_handle_converse = BedrockCompletion._handle_converse

            def patched_handle_converse(self, formatted_messages, body, available_functions, from_task, from_agent):
                try:
                    if isinstance(body, dict):
                        if "stopSequences" in str(body):
                            logger.warning("⚠️ stopSequences detected in CrewAI body BEFORE removal (will be stripped)")
                        _deep_remove_stop_fields(body)
                except Exception:
                    pass
                return original_handle_converse(self, formatted_messages, body, available_functions, from_task, from_agent)

            BedrockCompletion._handle_converse = patched_handle_converse
            BedrockCompletion.__stopseq_handle_converse_patched__ = True
            logger.info("✅ Patched CrewAI BedrockCompletion._handle_converse (backstop)")
    except Exception as e:
        logger.info("ℹ️ CrewAI BedrockCompletion patch skipped (%s)", e)

    boto3.__bedrock_stopseq_patch_applied__ = True
