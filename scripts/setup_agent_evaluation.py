#!/usr/bin/env python3

import argparse
import os
import sys
from typing import List, Optional

import boto3
from bedrock_agentcore_starter_toolkit import Evaluation


def _derive_region(explicit_region: Optional[str]) -> str:
    if explicit_region:
        return explicit_region
    session = boto3.session.Session()
    return session.region_name or os.getenv("AWS_DEFAULT_REGION") or os.getenv("AWS_REGION") or "us-east-1"


def _runtime_id_from_arn(agent_runtime_arn: str) -> str:
    # Expected: arn:aws:bedrock-agentcore:<region>:<account>:runtime/<runtime-id>
    marker = ":runtime/"
    if marker in agent_runtime_arn:
        return agent_runtime_arn.split(marker, 1)[1]
    marker2 = "runtime/"
    if marker2 in agent_runtime_arn:
        return agent_runtime_arn.split(marker2, 1)[1]
    return agent_runtime_arn


def _build_evaluator_list(custom_evaluator_id: Optional[str]) -> List[str]:
    evaluators: List[str] = [
        "Builtin.GoalSuccessRate",
        "Builtin.Correctness",
        "Builtin.ToolParameterAccuracy",
        "Builtin.ToolSelectionAccuracy",
    ]
    if custom_evaluator_id:
        evaluators.append(custom_evaluator_id)
    return evaluators


def _find_existing_config_id(eval_client: Evaluation, config_name: str) -> Optional[str]:
    # Best-effort idempotency: different toolkit versions may or may not expose list APIs.
    list_fn = getattr(eval_client, "list_online_configs", None)
    if not callable(list_fn):
        return None

    try:
        result = list_fn()
    except Exception:
        return None

    if isinstance(result, dict):
        items = result.get("onlineEvaluationConfigs") or result.get("configs") or result.get("items")
    else:
        items = result

    if not isinstance(items, list):
        return None

    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("configName") == config_name or item.get("name") == config_name:
            return item.get("onlineEvaluationConfigId") or item.get("configId") or item.get("id")

    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Create/enable Bedrock AgentCore online evaluation config")
    parser.add_argument("--agent-runtime-arn", required=True, help="Bedrock AgentCore Runtime ARN")
    parser.add_argument("--region", default=None, help="AWS region (defaults to current boto3 session region)")
    parser.add_argument("--config-name", default="langgraph_agent_eval", help="Online evaluation config name")
    parser.add_argument(
        "--config-description",
        default="LangGraph agent online evaluation test",
        help="Online evaluation config description",
    )
    parser.add_argument("--sampling-rate", type=int, default=100, help="Sampling rate (0-100)")
    parser.add_argument(
        "--custom-evaluator-id",
        default=os.getenv("EVALUATOR_ID") or os.getenv("CUSTOM_EVALUATOR_ID"),
        help="Optional custom evaluator id (also via EVALUATOR_ID env var)",
    )
    parser.add_argument(
        "--auto-create-execution-role",
        default=True,
        action=argparse.BooleanOptionalAction,
        help="Auto-create execution role for evaluation",
    )

    args = parser.parse_args()

    region = _derive_region(args.region)
    agent_id = _runtime_id_from_arn(args.agent_runtime_arn)

    print(f"Region: {region}")
    print(f"Agent runtime ARN: {args.agent_runtime_arn}")
    print(f"Agent id (derived): {agent_id}")

    eval_client = Evaluation(region=region)

    evaluator_list = _build_evaluator_list(args.custom_evaluator_id)

    # Try to reuse existing config if already present
    existing_id = _find_existing_config_id(eval_client, args.config_name)
    if existing_id:
        print(f"Online Evaluation Configuration Id (existing): {existing_id}")
        details = eval_client.get_online_config(config_id=existing_id)
        print(details)
        return 0

    response = eval_client.create_online_config(
        agent_id=agent_id,
        config_name=args.config_name,
        sampling_rate=args.sampling_rate,
        evaluator_list=evaluator_list,
        config_description=args.config_description,
        auto_create_execution_role=args.auto_create_execution_role,
    )

    config_id = response.get("onlineEvaluationConfigId") or response.get("configId") or response.get("id")
    if not config_id:
        print(f"Unexpected create response (missing config id): {response}")
        return 2

    print("Online Evaluation Configuration Id:", config_id)

    details = eval_client.get_online_config(config_id=config_id)
    print(details)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
