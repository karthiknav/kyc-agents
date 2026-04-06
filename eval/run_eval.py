"""
Full-pipeline KYC eval — real AI output + LLM-as-judge + Langfuse dataset experiment.

For each golden fixture the script:
  1. Runs the complete KYCCrew (all 4 agents) against the seeded DynamoDB case.
  2. Captures all 4 task outputs from the completed crew.
  3. Scores with two evaluators:
       a. decision-accuracy  — rule-based exact match (APPROVED / ESCALATED).
       b. decision-justification — GEval LLM judge: does the action and its
          reason[] logically follow from what the agents actually found?
  4. Posts scores to a Langfuse dataset experiment for side-by-side comparison.

Usage (from repo root):
  # First time: seed the Langfuse dataset
  python -m eval.run_eval --seed-dataset

  # Each experiment run (e.g. after a model or prompt change):
  python -m eval.run_eval --run-experiment --experiment-name "claude-sonnet-v1"

Prerequisites:
  1. Mock service running  (MOCK_SERVICE_URL in env)
  2. eval/case_ids.json    (produced by python -m eval.seed)
  3. AWS credentials + KYC_CASES_TABLE, KYC_RESULTS_BUCKET in env
  4. Langfuse env vars     (LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_BASE_URL)

env is read from crew/.env (auto-loaded).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / "crew" / ".env")

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

EVAL_DIR       = Path(__file__).parent
FIXTURES_DIR   = EVAL_DIR / "fixtures"
CASE_IDS_FILE  = EVAL_DIR / "case_ids.json"
GOLDEN_FILE    = EVAL_DIR / "golden_dataset.json"
LANGFUSE_DATASET_NAME = "kyc-pipeline-accuracy"

# ---------------------------------------------------------------------------
# Disable CrewAI / OpenInference auto-tracing during eval
# (Langfuse dataset experiment creates its own traces via run_experiment)
# ---------------------------------------------------------------------------

os.environ.setdefault("CREWAI_TRACING_ENABLED", "false")
os.environ.setdefault("LANGFUSE_ENABLED", "0")

# ---------------------------------------------------------------------------
# Patches — must happen before any crewai import
# ---------------------------------------------------------------------------

from crew.bedrock_tool_args_patch import apply_bedrock_tool_args_patch
from crew.bedrock_stop_sequences_patch import apply_bedrock_stop_sequences_patch
from crew.crewai_tool_observation_patch import apply_slim_tool_observations_patch

apply_bedrock_stop_sequences_patch()
apply_bedrock_tool_args_patch()
apply_slim_tool_observations_patch()

# ---------------------------------------------------------------------------
# OpenTelemetry CrewAI instrumentation (after patches, before crew import)
# ---------------------------------------------------------------------------

from opentelemetry.instrumentation.crewai import CrewAIInstrumentor
try:
    CrewAIInstrumentor().instrument()
except Exception as e:
    logger.warning("CrewAIInstrumentor failed: %s", e)

# ---------------------------------------------------------------------------
# Crew import (after patches)
# ---------------------------------------------------------------------------

from crew.crew import KYCCrew

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_case_ids() -> dict[str, str]:
    if not CASE_IDS_FILE.exists():
        sys.exit(
            f"ERROR: {CASE_IDS_FILE} not found. Run 'python -m eval.seed' first."
        )
    return json.loads(CASE_IDS_FILE.read_text())


def _load_golden() -> list[dict]:
    return json.loads(GOLDEN_FILE.read_text())


def _parse_json_output(raw: str | None) -> dict:
    """Parse JSON from a raw agent output string (strips markdown fences)."""
    if not raw:
        return {}
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"_raw": text}


def _extract_field(raw: str | None, field: str) -> str | None:
    """Regex fallback to extract a quoted JSON field value from raw text."""
    if not raw:
        return None
    m = re.search(rf'"{field}"\s*:\s*"([^"]+)"', raw)
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# Run the full KYC pipeline on a single case
# ---------------------------------------------------------------------------

def run_pipeline(case_id: str) -> dict[str, Any]:
    """
    Kick off the full KYCCrew for one case. Returns a dict with:
      - doc_output    : parsed document processing task output
      - risk_output   : parsed risk list screening task output
      - adverse_output: parsed adverse media task output
      - orch_output   : parsed orchestrator task output
      - action        : "APPROVED" | "ESCALATED" | None
      - context_summary: compact string of all upstream results (for the LLM judge)
    """
    crew_instance = KYCCrew()
    crew_obj = crew_instance.crew()

    logger.info("Running crew for caseId=%s ...", case_id)
    crew_output = crew_obj.kickoff(inputs={"caseId": case_id})

    # Read task outputs from the crew's task objects (populated after kickoff)
    tasks = crew_obj.tasks
    doc_raw     = tasks[0].output.raw if tasks[0].output else ""
    risk_raw    = tasks[1].output.raw if tasks[1].output else ""
    adverse_raw = tasks[2].output.raw if tasks[2].output else ""
    orch_raw    = tasks[3].output.raw if tasks[3].output else crew_output.raw or ""

    doc_out     = _parse_json_output(doc_raw)
    risk_out    = _parse_json_output(risk_raw)
    adverse_out = _parse_json_output(adverse_raw)
    orch_out    = _parse_json_output(orch_raw)

    action = orch_out.get("action") or _extract_field(orch_raw, "action")

    # Compact summary of what the agents actually found — used as LLM judge INPUT
    context_summary = json.dumps({
        "documentProcessing": {
            "comparison_result": doc_out.get("comparison_result"),
            "discrepancies":     doc_out.get("discrepancies", []),
        },
        "riskListScreening": {
            "result":           risk_out.get("result"),
            "pepStatus":        risk_out.get("pepStatus"),
            "sanctionsStatus":  risk_out.get("sanctionsStatus"),
            "datasetsMatched":  risk_out.get("datasetsMatched", []),
        },
        "adverseMedia": {
            "result":  adverse_out.get("result"),
            "summary": adverse_out.get("summary"),
        },
    }, indent=2)

    logger.info(
        "  caseId=%-40s  action=%s  doc=%s  risk=%s  adverse=%s",
        case_id,
        action,
        doc_out.get("comparison_result"),
        risk_out.get("result"),
        adverse_out.get("result"),
    )

    return {
        "case_id":         case_id,
        "action":          action,
        "doc_output":      doc_out,
        "risk_output":     risk_out,
        "adverse_output":  adverse_out,
        "orch_output":     orch_out,
        "orch_raw":        orch_raw,
        "context_summary": context_summary,
    }


# ---------------------------------------------------------------------------
# Langfuse helpers
# ---------------------------------------------------------------------------

def _langfuse_client():
    from langfuse import Langfuse
    return Langfuse(
        public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
        secret_key=os.environ["LANGFUSE_SECRET_KEY"],
        host=os.environ.get("LANGFUSE_BASE_URL", "https://cloud.langfuse.com"),
    )


# ---------------------------------------------------------------------------
# Seed Langfuse dataset (one-time)
# ---------------------------------------------------------------------------

def seed_dataset() -> None:
    golden   = _load_golden()
    case_ids = _load_case_ids()
    lf = _langfuse_client()

    lf.create_dataset(
        name=LANGFUSE_DATASET_NAME,
        description=(
            "Golden dataset for end-to-end KYC pipeline accuracy. "
            "Each item maps to a seeded DynamoDB case. "
            "The full 4-agent crew runs against real mock services."
        ),
    )
    logger.info("Dataset '%s' ready.", LANGFUSE_DATASET_NAME)

    # Collect existing item IDs to avoid duplicates
    existing: set[str] = set()
    try:
        ds = lf.get_dataset(LANGFUSE_DATASET_NAME)
        existing = {
            (item.metadata or {}).get("fixture", "")
            for item in ds.items
        }
    except Exception:
        pass

    created = 0
    for row in golden:
        fixture = row["fixture"]
        if fixture in existing:
            logger.info("  skip (exists): %s", fixture)
            continue
        if fixture not in case_ids:
            logger.warning("  skip (no case_id): %s — run eval.seed first", fixture)
            continue

        lf.create_dataset_item(
            dataset_name=LANGFUSE_DATASET_NAME,
            input={
                "fixture": fixture,
                "case_id": case_ids[fixture],
                "expected_doc_result":  row.get("expected_doc_result"),
                "expected_risk_result": row.get("expected_risk_result"),
            },
            expected_output={"action": row["expected_action"]},
            metadata={
                "fixture":     fixture,
                "description": row.get("description", ""),
            },
        )
        logger.info("  created: %s  (caseId=%s)", fixture, case_ids[fixture])
        created += 1

    lf.flush()
    logger.info("Seeding complete. %d item(s) created.", created)


# ---------------------------------------------------------------------------
# LLM judge (GEval via DeepEval + Bedrock)
# ---------------------------------------------------------------------------

def _build_judge():
    """Build a DeepEval-compatible judge backed by Bedrock Claude."""
    from deepeval.models.base_model import DeepEvalBaseLLM
    import boto3 as _boto3

    class BedrockClaudeJudge(DeepEvalBaseLLM):
        def __init__(self):
            self.model_id = os.environ.get("EVALMODEL", "deepseek.v3.2")
            self.client = _boto3.client("bedrock-runtime")

        def get_model_name(self) -> str:
            return self.model_id

        def load_model(self):
            return self

        def generate(self, prompt: str) -> str:
            resp = self.client.converse(
                modelId=self.model_id,
                messages=[{"role": "user", "content": [{"text": prompt}]}],
                inferenceConfig={"maxTokens": 1024, "temperature": 0.0},
            )
            return resp["output"]["message"]["content"][0]["text"]

        async def a_generate(self, prompt: str) -> str:
            return self.generate(prompt)

    return BedrockClaudeJudge()


def _build_justification_metric(judge):
    from deepeval.metrics import GEval
    from deepeval.test_case import LLMTestCaseParams

    return GEval(
        name="decision-justification",
        model=judge,
        evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT],
        criteria=(
            "Evaluate whether the KYC orchestrator's final decision (APPROVED or ESCALATED) "
            "is logically justified by what the agents actually found.\n\n"
            "The INPUT is a JSON summary of what the three upstream agents reported:\n"
            "  - documentProcessing.comparison_result: MATCH / PARTIAL_MATCH / MISMATCH\n"
            "  - riskListScreening.result: CLEAR / HIT / ERROR\n"
            "  - adverseMedia.result: OK / NOK / PENDING_REVIEW\n\n"
            "The ACTUAL OUTPUT is the orchestrator's final JSON decision.\n\n"
            "Decision rules:\n"
            "  - APPROVED is only valid when doc=MATCH AND risk=CLEAR AND adverse=OK\n"
            "  - ESCALATED is valid for any other combination\n"
            "  - Score LOW if the decision contradicts the upstream results\n"
            "  - Score LOW if reason[] is empty, vague, or does not name the failing check(s)\n"
            "  - Score HIGH if the decision is consistent and reason[] explicitly names "
            "every failing check with its actual result value"
        ),
        threshold=0.7,
    )


# ---------------------------------------------------------------------------
# Run experiment
# ---------------------------------------------------------------------------

def run_experiment(experiment_name: str) -> None:
    lf      = _langfuse_client()
    golden  = _load_golden()
    judge   = _build_judge()
    geval   = _build_justification_metric(judge)

    dataset = lf.get_dataset(LANGFUSE_DATASET_NAME)
    if not dataset.items:
        sys.exit(
            f"Dataset '{LANGFUSE_DATASET_NAME}' is empty. Run --seed-dataset first."
        )

    logger.info(
        "Running experiment '%s' on %d item(s) ...",
        experiment_name,
        len(dataset.items),
    )

    # Build a lookup: fixture → golden row (for expected values)
    golden_by_fixture = {row["fixture"]: row for row in golden}

    from langfuse import propagate_attributes, Evaluation

    def task_fn(*, item, **kwargs) -> dict[str, Any]:
        case_id = item.input["case_id"]
        fixture = item.input.get("fixture", case_id)
        with propagate_attributes(
            tags=["kyc", "experiment"],
            session_id=case_id,
            trace_name=fixture,
        ):
            return run_pipeline(case_id)

    def accuracy_evaluator(
        *,
        output: dict | None,
        expected_output: dict | None = None,
        **kwargs,
    ) -> Evaluation:
        got      = (output or {}).get("action")
        expected = (expected_output or {}).get("action")
        correct  = got == expected
        return Evaluation(
            name="decision-accuracy",
            value=1.0 if correct else 0.0,
            comment=f"got={got}  expected={expected}",
        )

    def justification_evaluator(
        *,
        input: dict,        # noqa: A002
        output: dict | None,
        **kwargs,
    ) -> Evaluation:
        from deepeval.test_case import LLMTestCase
        context_summary = (output or {}).get("context_summary", "")
        orch_raw        = (output or {}).get("orch_raw", "")
        if not context_summary or not orch_raw:
            return Evaluation(name="decision-justification", value=0.0, comment="missing output")
        try:
            test_case = LLMTestCase(input=context_summary, actual_output=orch_raw)
            geval.measure(test_case)
            return Evaluation(
                name="decision-justification",
                value=geval.score,
                comment=geval.reason or "",
            )
        except Exception as e:
            logger.warning("GEval failed: %s", e)
            return Evaluation(name="decision-justification", value=0.0, comment=str(e))

    result = dataset.run_experiment(
        name=experiment_name,
        task=task_fn,
        evaluators=[accuracy_evaluator, justification_evaluator],
        max_concurrency=1,  # sequential — one Bedrock call at a time
        metadata={"model": "deepseek.v3.2"},
    )

    # ---- Print summary ----
    item_results = result.item_results
    total  = len(item_results)
    passed = sum(
        1 for r in item_results
        if any(
            e.name == "decision-accuracy" and e.value == 1.0
            for e in r.evaluations
        )
    )

    logger.info("─" * 60)
    logger.info("Experiment  : %s", experiment_name)
    logger.info("Model       : %s", os.environ.get("MODEL", "(env not set)"))
    logger.info("Accuracy    : %d / %d passed (%.0f%%)", passed, total, 100 * passed / total if total else 0)
    logger.info("Langfuse    : %s", result.dataset_run_url)
    logger.info("─" * 60)

    for r in item_results:
        fixture  = (r.item.metadata or {}).get("fixture", "?")
        evals    = r.evaluations
        acc      = next((e for e in evals if e.name == "decision-accuracy"), None)
        just     = next((e for e in evals if e.name == "decision-justification"), None)
        status   = "PASS" if acc and acc.value == 1.0 else "FAIL"
        logger.info(
            "  [%s] %-20s  accuracy=%s  justification=%.2f  %s",
            status,
            fixture,
            acc.comment if acc else "",
            just.value if just else 0.0,
            f"({just.comment[:60]})" if just and just.comment else "",
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="KYC end-to-end pipeline eval — real AI output + LLM judge + Langfuse"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--seed-dataset",
        action="store_true",
        help="Create the Langfuse dataset and populate it with items (run once).",
    )
    mode.add_argument(
        "--run-experiment",
        action="store_true",
        help="Run the full pipeline on all dataset items and post scores to Langfuse.",
    )
    parser.add_argument(
        "--experiment-name",
        default=None,
        help="Label for this experiment run (column in Langfuse comparison table).",
    )
    args = parser.parse_args()

    if args.run_experiment:
        if not args.experiment_name:
            parser.error("--experiment-name is required with --run-experiment")
        run_experiment(args.experiment_name)
    else:
        seed_dataset()


if __name__ == "__main__":
    main()
