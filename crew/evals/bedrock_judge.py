"""Bedrock Converse LLM wrapper for DeepEval evaluation judge.

Allows DeepEval metrics to use Bedrock models (Claude, etc.) as the judge LLM,
keeping all evaluation data within AWS infrastructure.

Usage:
    from crew.evals.bedrock_judge import BedrockJudgeLLM
    judge = BedrockJudgeLLM()  # uses EVAL_JUDGE_MODEL or MODEL env var
"""

import json
import logging
import os
from typing import Any, Optional

import boto3
from deepeval.models import DeepEvalBaseLLM

logger = logging.getLogger(__name__)


class BedrockJudgeLLM(DeepEvalBaseLLM):
    """DeepEval-compatible LLM using AWS Bedrock Converse API."""

    def __init__(self, model: str | None = None, region: str | None = None):
        self._model_id = (
            model
            or os.getenv("EVAL_JUDGE_MODEL")
            or os.getenv("MODEL", "us.anthropic.claude-3-5-sonnet-20241022-v2:0")
        ).strip().replace("bedrock/", "")
        self._region = region or os.getenv("AWS_REGION_NAME") or os.getenv("AWS_REGION") or "us-east-1"
        self._client = None

    def _get_client(self):
        if self._client is None:
            self._client = boto3.client("bedrock-runtime", region_name=self._region)
        return self._client

    def load_model(self) -> str:
        return self._model_id

    def generate(self, prompt: str, schema: Optional[Any] = None) -> str:
        """Generate a response from Bedrock. DeepEval calls this for evaluation."""
        logger.debug("BedrockJudgeLLM.generate: model=%s, prompt_len=%d", self._model_id, len(prompt))

        messages = [{"role": "user", "content": [{"text": prompt}]}]

        inference_config = {"maxTokens": 4096, "temperature": 0.0}

        try:
            response = self._get_client().converse(
                modelId=self._model_id,
                messages=messages,
                inferenceConfig=inference_config,
            )

            content_parts = []
            for block in response.get("output", {}).get("message", {}).get("content", []):
                if "text" in block:
                    content_parts.append(block["text"])
            content = "".join(content_parts).strip()

            # Strip markdown code blocks if present
            if content.startswith("```"):
                lines = content.split("\n")
                content = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

            return content
        except Exception as e:
            logger.exception("BedrockJudgeLLM.generate failed: %s", e)
            raise

    async def a_generate(self, prompt: str, schema: Optional[Any] = None) -> str:
        """Async generate — falls back to sync for Bedrock."""
        return self.generate(prompt, schema)

    def get_model_name(self) -> str:
        return f"bedrock/{self._model_id}"
