from __future__ import annotations

import logging
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


def _wrap_bedrock_converse(client: Any) -> None:
    """Wrap a bedrock-runtime client's converse() to strip stop fields right before send."""
    if not hasattr(client, "converse"):
        return

    # Avoid double-wrapping the same client instance
    if getattr(client, "__stopseq_converse_wrapped__", False):
        return

    original_converse = client.converse

    def converse(*args, **kwargs):
        # kwargs contains modelId, messages, inferenceConfig, etc.
        if "stopSequences" in str(kwargs):
            logger.warning("⚠️ stopSequences detected BEFORE removal (will be stripped)")
        _deep_remove_stop_fields(kwargs)
        logger.info("✅ stopSequences stripped from Bedrock converse() request")
        return original_converse(*args, **kwargs)

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

    # Idempotency guard
    if getattr(boto3, "__bedrock_stopseq_patch_applied__", False):
        logger.info("✅ Bedrock stopSequences patch already applied (global)")
        return

    logger.info("✅ Applying Bedrock stopSequences patch (boto3.client + Session.client)")

    # -----------------------------
    # 1) Patch boto3.client(...)
    # -----------------------------
    original_boto3_client = boto3.client

    def patched_boto3_client(service_name: str, *args, **kwargs):
        c = original_boto3_client(service_name, *args, **kwargs)
        if service_name == "bedrock-runtime":
            logger.info("✅ Intercepted boto3.client('bedrock-runtime')")
            _wrap_bedrock_converse(c)
        return c

    boto3.client = patched_boto3_client

    # ----------------------------------------
    # 2) Patch boto3.session.Session.client(...)
    # ----------------------------------------
    original_session_client = boto3.session.Session.client

    def patched_session_client(self, service_name: str, *args, **kwargs):
        c = original_session_client(self, service_name, *args, **kwargs)
        if service_name == "bedrock-runtime":
            logger.info("✅ Intercepted Session().client('bedrock-runtime')")
            _wrap_bedrock_converse(c)
        return c

    boto3.session.Session.client = patched_session_client

    # ---------------------------------------------------
    # 3) Optional backstop: patch CrewAI BedrockCompletion
    # ---------------------------------------------------
    try:
        from crewai.llms.providers.bedrock.completion import BedrockCompletion  # type: ignore

        if not getattr(BedrockCompletion, "__stopseq_handle_converse_patched__", False):
            original_handle_converse = BedrockCompletion._handle_converse

            def patched_handle_converse(self, formatted_messages, body, available_functions, from_task, from_agent):
                # 'body' is the dict that gets splatted into client.converse(**body)
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
        # Not fatal; patching boto3/Session is usually enough
        logger.info("ℹ️ CrewAI BedrockCompletion patch skipped (%s)", e)

    boto3.__bedrock_stopseq_patch_applied__ = True