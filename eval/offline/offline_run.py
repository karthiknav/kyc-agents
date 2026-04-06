"""
Offline tool-coverage checker for KYC experiment traces.

Fetches recent KYC traces from Langfuse, inspects which tools were actually
called (TOOL-type observations created by the Langfuse CrewAI patch), compares
against the expected tool set for each pipeline stage, and pushes a
"tool-coverage" score back to each trace.

Requirements:
  - Traces must have been produced by eval/experiments/run_eval.py, which
    applies the Langfuse tool patch so each tool call is recorded as a
    TOOL observation named after the tool.
  - Langfuse env vars: LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_BASE_URL

Usage (from repo root):
  # Check last 1 experiment trace (dry run — good for testing)
  python -m eval.offline.offline_run --last 1

  # Check and push scores back to Langfuse
  python -m eval.offline.offline_run --last 5 --push-scores

  # Check a specific trace
  python -m eval.offline.offline_run --trace-id <id> --push-scores
"""

from __future__ import annotations

import argparse
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent / "crew" / ".env")

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Expected tools per pipeline stage
# Order doesn't matter — we check presence only.
# ---------------------------------------------------------------------------

EXPECTED_TOOLS: dict[str, list[str]] = {
    "document_processing": [
        "get_case_details",
        "get_case_files",
        "extract_document_text",
        "verify_identity_document",
        "compare_identity_documents",
    ],
    "risk_list_screening": [
        "risk_list_screening",
    ],
    "adverse_media": [
        "search_internet",
        "produce_adverse_media_analysis",
    ],
}

ALL_EXPECTED_TOOLS: set[str] = {t for tools in EXPECTED_TOOLS.values() for t in tools}


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class StageCoverage:
    stage: str
    expected: list[str]
    called: list[str]
    missing: list[str] = field(default_factory=list)

    @property
    def score(self) -> float:
        if not self.expected:
            return 1.0
        return len(self.called) / len(self.expected)


@dataclass
class TraceCoverage:
    trace_id: str
    trace_name: str
    session_id: str
    stages: list[StageCoverage]
    all_tool_observations: list[str]

    @property
    def overall_score(self) -> float:
        called = {t for s in self.stages for t in s.called}
        if not ALL_EXPECTED_TOOLS:
            return 1.0
        return len(called) / len(ALL_EXPECTED_TOOLS)

    @property
    def missing_tools(self) -> list[str]:
        called = {t for s in self.stages for t in s.called}
        return sorted(ALL_EXPECTED_TOOLS - called)


# ---------------------------------------------------------------------------
# Langfuse client
# ---------------------------------------------------------------------------

def _langfuse_client():
    from langfuse import Langfuse
    return Langfuse(
        public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
        secret_key=os.environ["LANGFUSE_SECRET_KEY"],
        host=os.environ.get("LANGFUSE_BASE_URL", "https://cloud.langfuse.com"),
    )


# ---------------------------------------------------------------------------
# Trace + observation fetching
# ---------------------------------------------------------------------------

def fetch_recent_traces(lf, n: int) -> list:
    """Return up to n recent KYC traces (identified by the CrewAI root span name)."""
    result = lf.api.trace.list(
        name="crewai-index-trace",
        limit=n,
        order_by="timestamp.desc",
    )
    return list(result.data)


def fetch_tool_observations(lf, trace_id: str) -> list[str]:
    """
    Return the names of all tool observations in a trace.
    These are created by langfuse_crewai_patches.patch_crewai_structured_tool_for_langfuse()
    as observations with as_type="tool".
    Falls back to fetching all observations and filtering by name against known tools
    if no TOOL-typed observations are found (type casing varies by Langfuse version).
    """
    resp = lf.api.observations.get_many(
        trace_id=trace_id,
        type="TOOL",
        fields="core,basic",
    )
    names = [obs.name for obs in resp.data if obs.name]

    # Fallback: if TOOL type returned nothing, scan all observations by name
    if not names:
        resp_all = lf.api.observations.get_many(
            trace_id=trace_id,
            fields="core,basic",
        )
        names = [
            obs.name for obs in resp_all.data
            if obs.name and obs.name in ALL_EXPECTED_TOOLS
        ]

    return names


# ---------------------------------------------------------------------------
# Coverage computation
# ---------------------------------------------------------------------------

def compute_coverage(trace_id: str, trace_name: str, session_id: str, tool_names: list[str]) -> TraceCoverage:
    called_set = set(tool_names)
    stages = []
    for stage, expected in EXPECTED_TOOLS.items():
        called = [t for t in expected if t in called_set]
        missing = [t for t in expected if t not in called_set]
        stages.append(StageCoverage(
            stage=stage,
            expected=expected,
            called=called,
            missing=missing,
        ))
    return TraceCoverage(
        trace_id=trace_id,
        trace_name=trace_name,
        session_id=session_id,
        stages=stages,
        all_tool_observations=tool_names,
    )


# ---------------------------------------------------------------------------
# Score pushing
# ---------------------------------------------------------------------------

def push_scores(lf, coverage: TraceCoverage) -> None:
    """Push overall + per-stage tool coverage scores to the trace."""
    lf.create_score(
        trace_id=coverage.trace_id,
        name="tool-coverage",
        value=coverage.overall_score,
        comment=(
            f"missing: {coverage.missing_tools}" if coverage.missing_tools
            else "all tools called"
        ),
    )
    for stage in coverage.stages:
        lf.create_score(
            trace_id=coverage.trace_id,
            name=f"tool-coverage.{stage.stage}",
            value=stage.score,
            comment=(
                f"missing: {stage.missing}" if stage.missing
                else "all tools called"
            ),
        )
    lf.flush()


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def print_coverage(coverage: TraceCoverage) -> None:
    status = "FULL" if coverage.overall_score == 1.0 else "PARTIAL"
    logger.info(
        "[%s] trace=%-36s  name=%-20s  overall=%.2f",
        status,
        coverage.trace_id,
        coverage.trace_name or "(unnamed)",
        coverage.overall_score,
    )
    for stage in coverage.stages:
        stage_status = "OK" if stage.score == 1.0 else "MISS"
        logger.info(
            "       [%s] %-25s  %.0f/%d called%s",
            stage_status,
            stage.stage,
            len(stage.called),
            len(stage.expected),
            f"  missing={stage.missing}" if stage.missing else "",
        )
    if coverage.all_tool_observations:
        unexpected = sorted(set(coverage.all_tool_observations) - ALL_EXPECTED_TOOLS)
        if unexpected:
            logger.info("       [INFO] unexpected tool calls: %s", unexpected)


# ---------------------------------------------------------------------------
# Main logic
# ---------------------------------------------------------------------------

def run_coverage_check(
    last_n: Optional[int] = None,
    trace_id: Optional[str] = None,
    push: bool = False,
) -> None:
    lf = _langfuse_client()

    if trace_id:
        traces = [lf.api.trace.get(trace_id)]
    else:
        traces = fetch_recent_traces(lf, last_n or 10)

    if not traces:
        logger.warning("No traces found.")
        return

    logger.info("Checking tool coverage for %d trace(s) ...", len(traces))
    logger.info("─" * 70)

    coverages: list[TraceCoverage] = []
    for trace in traces:
        tid  = trace.id
        name = getattr(trace, "name", None) or ""
        sid  = getattr(trace, "session_id", None) or ""

        tool_names = fetch_tool_observations(lf, tid)
        coverage   = compute_coverage(tid, name, sid, tool_names)
        coverages.append(coverage)

        print_coverage(coverage)
        logger.info("")

    # Summary
    total    = len(coverages)
    full     = sum(1 for c in coverages if c.overall_score == 1.0)
    avg      = sum(c.overall_score for c in coverages) / total if total else 0.0
    logger.info("─" * 70)
    logger.info("Summary  : %d / %d full coverage  (avg %.2f)", full, total, avg)

    if push:
        logger.info("Pushing scores to Langfuse ...")
        for coverage in coverages:
            push_scores(lf, coverage)
        logger.info("Done.")
    else:
        logger.info("(dry run — add --push-scores to write scores to Langfuse)")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Offline tool-coverage checker for KYC experiment traces"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--last",
        type=int,
        metavar="N",
        help="Check the last N traces tagged 'kyc'.",
    )
    group.add_argument(
        "--trace-id",
        metavar="ID",
        help="Check a specific trace by ID.",
    )
    parser.add_argument(
        "--push-scores",
        action="store_true",
        default=False,
        help="Push tool-coverage scores back to each trace in Langfuse (default: dry run).",
    )
    args = parser.parse_args()

    run_coverage_check(
        last_n=args.last,
        trace_id=args.trace_id,
        push=args.push_scores,
    )


if __name__ == "__main__":
    main()
