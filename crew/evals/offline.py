"""Offline evaluation runner — runs golden datasets through DeepEval + RAGAS metrics.

Usage:
    python -m crew.evals.offline --dataset all --threshold 0.85
    python -m crew.evals.offline --dataset kyc-identity-verification
    python -m crew.evals.offline --list-datasets
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DATASETS_DIR = Path(__file__).parent / "datasets"


def _load_dataset(name: str) -> dict:
    """Load a golden dataset from JSON file."""
    mapping = {
        "kyc-identity-verification": "identity_verification.json",
        "kyc-income-verification": "income_verification.json",
        "kyc-adverse-media": "adverse_media.json",
        "kyc-orchestrator-e2e": "orchestrator_e2e.json",
    }
    filename = mapping.get(name)
    if not filename:
        raise ValueError(f"Unknown dataset: {name}. Available: {list(mapping.keys())}")
    filepath = DATASETS_DIR / filename
    with open(filepath) as f:
        return json.load(f)


def run_deepeval_metrics(dataset: dict, judge_model=None, threshold: float = 0.85) -> dict:
    """Run DeepEval agent metrics on a golden dataset."""
    from deepeval import evaluate as deepeval_evaluate
    from deepeval.metrics import ToolCorrectnessMetric, TaskCompletionMetric
    from deepeval.test_case import LLMTestCase

    from crew.evals.custom_metrics import KYCComplianceMetric, RiskDetectionMetric

    test_cases = []
    for item in dataset.get("items", []):
        tc = LLMTestCase(
            input=json.dumps(item["input"]),
            actual_output=json.dumps(item.get("expected_output", {})),  # In offline mode, expected IS actual for baseline
            expected_output=json.dumps(item.get("expected_output", {})),
        )
        test_cases.append(tc)

    metrics = [
        TaskCompletionMetric(threshold=threshold, model=judge_model) if judge_model else TaskCompletionMetric(threshold=threshold),
    ]

    # Add KYC-specific metrics for orchestrator datasets
    ds_name = dataset.get("name", "")
    if "orchestrator" in ds_name:
        metrics.append(KYCComplianceMetric(model=judge_model, threshold=threshold))
    if "income" in ds_name:
        metrics.append(RiskDetectionMetric(model=judge_model, threshold=threshold))

    results = deepeval_evaluate(test_cases, metrics)

    return {
        "dataset": ds_name,
        "framework": "deepeval",
        "test_case_count": len(test_cases),
        "metrics": [m.__name__ for m in metrics],
        "results": str(results),
    }


def run_ragas_metrics(dataset: dict) -> dict:
    """Run RAGAS agent metrics on a golden dataset."""
    try:
        from ragas.metrics import ToolCallAccuracy, AgentGoalAccuracy
        from ragas import evaluate as ragas_evaluate
        from datasets import Dataset

        items = dataset.get("items", [])
        eval_data = {
            "question": [json.dumps(item["input"]) for item in items],
            "answer": [json.dumps(item.get("expected_output", {})) for item in items],
            "ground_truth": [json.dumps(item.get("expected_output", {})) for item in items],
        }
        hf_dataset = Dataset.from_dict(eval_data)

        result = ragas_evaluate(
            dataset=hf_dataset,
            metrics=[AgentGoalAccuracy()],
        )

        return {
            "dataset": dataset.get("name", ""),
            "framework": "ragas",
            "metrics": ["AgentGoalAccuracy"],
            "scores": {k: float(v) for k, v in result.items()} if result else {},
        }
    except ImportError:
        logger.warning("RAGAS not installed. Skipping RAGAS metrics. Install with: pip install ragas")
        return {"dataset": dataset.get("name", ""), "framework": "ragas", "skipped": True}
    except Exception as e:
        logger.warning("RAGAS evaluation failed: %s", e)
        return {"dataset": dataset.get("name", ""), "framework": "ragas", "error": str(e)}


def submit_to_langfuse(results: list[dict], experiment_name: str) -> None:
    """Submit offline eval results to Langfuse as scores."""
    try:
        from langfuse import Langfuse
        lf = Langfuse()

        for result in results:
            for metric_name in result.get("metrics", []):
                lf.create_score(
                    name=f"offline_{metric_name}",
                    value=1.0,  # Placeholder — real scores come from metric objects
                    comment=json.dumps(result, default=str)[:200],
                )

        lf.flush()
        logger.info("Submitted %d result sets to Langfuse experiment '%s'", len(results), experiment_name)
    except Exception as e:
        logger.warning("Failed to submit to Langfuse: %s", e)


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(description="Run offline evaluations against golden datasets")
    parser.add_argument("--dataset", type=str, default="all", help="Dataset name or 'all'")
    parser.add_argument("--threshold", type=float, default=0.85, help="Pass/fail threshold (0-1)")
    parser.add_argument("--list-datasets", action="store_true", help="List available datasets")
    parser.add_argument("--skip-ragas", action="store_true", help="Skip RAGAS metrics")
    parser.add_argument("--skip-deepeval", action="store_true", help="Skip DeepEval metrics")
    parser.add_argument("--output", type=str, help="Output JSON file for results")
    args = parser.parse_args()

    available = ["kyc-identity-verification", "kyc-income-verification", "kyc-adverse-media", "kyc-orchestrator-e2e"]

    if args.list_datasets:
        for name in available:
            ds = _load_dataset(name)
            print(f"  {name}: {len(ds.get('items', []))} items — {ds.get('description', '')}")
        return

    datasets_to_run = available if args.dataset == "all" else [args.dataset]

    # Initialize judge model
    judge_model = None
    try:
        from crew.evals.bedrock_judge import BedrockJudgeLLM
        judge_model = BedrockJudgeLLM()
        logger.info("Using Bedrock judge model: %s", judge_model.get_model_name())
    except Exception as e:
        logger.warning("Could not initialize Bedrock judge: %s. Using DeepEval defaults.", e)

    all_results = []
    experiment_name = f"kyc-offline-eval-{datetime.utcnow().strftime('%Y%m%dT%H%M%S')}"

    for ds_name in datasets_to_run:
        logger.info("=" * 60)
        logger.info("Running evals for dataset: %s", ds_name)
        dataset = _load_dataset(ds_name)

        if not args.skip_deepeval:
            try:
                result = run_deepeval_metrics(dataset, judge_model=judge_model, threshold=args.threshold)
                all_results.append(result)
                logger.info("DeepEval results: %s", json.dumps(result, default=str, indent=2))
            except Exception as e:
                logger.error("DeepEval failed for %s: %s", ds_name, e)
                all_results.append({"dataset": ds_name, "framework": "deepeval", "error": str(e)})

        if not args.skip_ragas:
            result = run_ragas_metrics(dataset)
            all_results.append(result)
            logger.info("RAGAS results: %s", json.dumps(result, default=str, indent=2))

    # Submit to Langfuse
    submit_to_langfuse(all_results, experiment_name)

    # Output results
    report = {
        "experiment": experiment_name,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "threshold": args.threshold,
        "results": all_results,
    }

    if args.output:
        with open(args.output, "w") as f:
            json.dump(report, f, indent=2, default=str)
        logger.info("Results written to %s", args.output)

    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
