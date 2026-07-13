#!/usr/bin/env python3
"""Update an existing Bedrock AgentCore runtime with Langfuse + OTEL env from SSM.

Reads /langfuse/* parameters, merges into current runtime environmentVariables,
and calls UpdateAgentRuntime (same effect as toolkit launch(env_vars=...) for an
existing CFN-managed runtime).
"""

from __future__ import annotations

import argparse
import base64
import os
import sys
from typing import Any, Dict, Optional

import boto3
from botocore.exceptions import ClientError

from bedrock_agentcore_starter_toolkit.services.runtime import BedrockAgentCoreClient


def _runtime_id_from_arn(agent_runtime_arn: str) -> str:
    marker = ":runtime/"
    if marker in agent_runtime_arn:
        return agent_runtime_arn.split(marker, 1)[1]
    if agent_runtime_arn.startswith("runtime/"):
        return agent_runtime_arn[len("runtime/") :]
    raise ValueError(
        f"Expected agent runtime ARN containing ':runtime/', got: {agent_runtime_arn!r}"
    )


def _get_ssm_parameter(ssm, name: str, *, decrypt: bool) -> str:
    resp = ssm.get_parameter(Name=name, WithDecryption=decrypt)
    return resp["Parameter"]["Value"].strip()


def _normalize_host(host: str) -> str:
    h = host.strip().rstrip("/")
    if not h.startswith(("http://", "https://")):
        h = f"https://{h}"
    return h.rstrip("/")


def _optional_update_fields(cur: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key in (
        "lifecycleConfiguration",
        "protocolConfiguration",
        "authorizerConfiguration",
        "requestHeaderConfiguration",
        "description",
        "metadataConfiguration",
    ):
        if cur.get(key) is not None:
            out[key] = cur[key]
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent-runtime-arn", required=True, help="Bedrock AgentCore runtime ARN")
    parser.add_argument("--region", default=None, help="AWS region (default: session / env)")
    parser.add_argument(
        "--tracing-environment",
        default=None,
        help="LANGFUSE_TRACING_ENVIRONMENT value (default: LANGFUSE_TRACING_ENVIRONMENT env, then ENVIRONMENT, then 'agentcore')",
    )
    parser.add_argument(
        "--max-wait-endpoint",
        type=int,
        default=900,
        help="Seconds to wait for DEFAULT endpoint after update (default: 900)",
    )
    args = parser.parse_args()

    session = boto3.session.Session()
    region = args.region or session.region_name or os.getenv("AWS_DEFAULT_REGION") or os.getenv("AWS_REGION")
    if not region:
        print("error: could not determine AWS region", file=sys.stderr)
        return 1

    runtime_id = _runtime_id_from_arn(args.agent_runtime_arn)
    tracing_env = (
        args.tracing_environment
        or os.getenv("LANGFUSE_TRACING_ENVIRONMENT")
        or os.getenv("ENVIRONMENT")
        or "agentcore"
    )

    ssm_prefix = os.getenv("LANGFUSE_SSM_PREFIX", "/langfuse")
    paths = {
        "LANGFUSE_PROJECT_NAME": f"{ssm_prefix}/project_name",
        "LANGFUSE_SECRET_KEY": f"{ssm_prefix}/secret_key",
        "LANGFUSE_PUBLIC_KEY": f"{ssm_prefix}/public_key",
        "LANGFUSE_HOST": f"{ssm_prefix}/host",
    }

    ssm = session.client("ssm", region_name=region)
    try:
        langfuse_project_name = _get_ssm_parameter(ssm, paths["LANGFUSE_PROJECT_NAME"], decrypt=False)
        langfuse_secret_key = _get_ssm_parameter(ssm, paths["LANGFUSE_SECRET_KEY"], decrypt=True)
        langfuse_public_key = _get_ssm_parameter(ssm, paths["LANGFUSE_PUBLIC_KEY"], decrypt=True)
        langfuse_host_raw = _get_ssm_parameter(ssm, paths["LANGFUSE_HOST"], decrypt=False)
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code == "ParameterNotFound":
            print(
                f"warning: Langfuse SSM parameters not found under '{ssm_prefix}' — skipping Langfuse configuration",
                file=sys.stderr,
            )
            return 0
        print(f"error: SSM read failed ({code}): {e}", file=sys.stderr)
        return 1

    host = _normalize_host(langfuse_host_raw)
    otel_endpoint = f"{host}/api/public/otel"
    token = base64.b64encode(f"{langfuse_public_key}:{langfuse_secret_key}".encode()).decode()
    otel_auth_header = f"Authorization=Basic {token}, x-langfuse-ingestion-version=4"

    bedrock_model_id = os.getenv("BEDROCK_MODEL_ID") or os.getenv("MODEL")
    system_prompt = os.getenv("SYSTEM_PROMPT")

    extra: Dict[str, str] = {
        "LANGFUSE_ENABLED": "1",
        "LANGFUSE_PROJECT_NAME": langfuse_project_name,
        "LANGFUSE_SECRET_KEY": langfuse_secret_key,
        "LANGFUSE_PUBLIC_KEY": langfuse_public_key,
        "LANGFUSE_HOST": host,
        "LANGFUSE_BASE_URL": host,
        "LANGFUSE_TRACING_ENVIRONMENT": tracing_env,
        "OTEL_EXPORTER_OTLP_ENDPOINT": otel_endpoint,
        "OTEL_EXPORTER_OTLP_HEADERS": otel_auth_header,
        "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
        "DISABLE_ADOT_OBSERVABILITY": "true",
    }
    if bedrock_model_id:
        extra["BEDROCK_MODEL_ID"] = bedrock_model_id
    if system_prompt is not None:
        if len(system_prompt) > 5000:
            print(
                "error: SYSTEM_PROMPT exceeds AgentCore environment value limit (5000 chars)",
                file=sys.stderr,
            )
            return 1
        extra["SYSTEM_PROMPT"] = system_prompt

    for k, v in extra.items():
        if len(v) > 5000:
            print(f"error: env value for {k} exceeds 5000 characters", file=sys.stderr)
            return 1

    ac = BedrockAgentCoreClient(region)
    try:
        cur = ac.get_agent_runtime(runtime_id)
    except ClientError as e:
        print(f"error: get_agent_runtime failed: {e}", file=sys.stderr)
        return 1

    artifact = cur.get("agentRuntimeArtifact")
    network = dict(cur.get("networkConfiguration") or {})
    network.pop("requireServiceS3Endpoint", None)
    role_arn = cur.get("roleArn")
    if not artifact or not network or not role_arn:
        print("error: runtime response missing artifact, networkConfiguration, or roleArn", file=sys.stderr)
        return 1

    env: Dict[str, str] = dict(cur.get("environmentVariables") or {})
    env.update(extra)

    if len(env) > 50:
        print(
            f"error: merged environment has {len(env)} keys; AgentCore allows at most 50",
            file=sys.stderr,
        )
        return 1

    params: Dict[str, Any] = {
        "agentRuntimeId": runtime_id,
        "agentRuntimeArtifact": artifact,
        "networkConfiguration": network,
        "roleArn": role_arn,
        "environmentVariables": env,
    }
    params.update(_optional_update_fields(cur))

    try:
        ac.client.update_agent_runtime(**params)
    except ClientError as e:
        print(f"error: update_agent_runtime failed: {e}", file=sys.stderr)
        return 1

    print(f"Updated runtime {runtime_id} with Langfuse / OTEL env; waiting for endpoint...")
    try:
        wait_result = ac.wait_for_agent_endpoint_ready(runtime_id, max_wait=args.max_wait_endpoint)
    except Exception as e:
        print(f"error: endpoint failed after update: {e}", file=sys.stderr)
        return 1
    if wait_result.startswith("Endpoint is taking longer"):
        print(f"warning: {wait_result}", file=sys.stderr)
        return 0
    print(f"Endpoint ready: {wait_result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
