"""
Offline tool-coverage checker for KYC experiment traces.

Fetches recent KYC traces from Langfuse, groups tool observations by the agent
that called them, compares against the expected tool set per agent, and pushes
per-agent tool-coverage scores back to each trace.

The hierarchy in each trace is:
  crewai-index-trace (root)
    └── {role}.agent  (SPAN, one per agent)
          └── tool observations (type=TOOL, name=tool_name)

Tool observations are created by langfuse_crewai_patches.patch_crewai_structured_tool_for_langfuse().
Agent spans are created by the CrewAI OTEL instrumentor.

Usage (from repo root):
  # Check last 1 trace (dry run — good for testing)
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
# Agent → expected tools mapping
# Keys are the CrewAI agent role names (set in agents.yaml).
# The OTEL instrumentor names each span "{role}.agent".
# ---------------------------------------------------------------------------

AGENT_EXPECTED_TOOLS: dict[str, list[str]] = {
    "Document Processing Agent": [
        "get_case_details",
        "get_case_files",
        "extract_document_text",
        "verify_identity_document",
        "compare_identity_documents",
    ],
    "Risk List Screening Agent": [
        "get_case_details",
        "risk_list_screening",
    ],
    "Adverse Media Screening Agent": [
        "get_case_details",
        "search_internet",
        "produce_adverse_media_analysis",
    ],
    "KYC Decision Orchestrator": [
        "escalate_to_human",  # only present on ESCALATED cases
    ],
}

ALL_EXPECTED_TOOLS: set[str] = {
    t for tools in AGENT_EXPECTED_TOOLS.values() for t in tools
}

# Agents where missing tools are always a hard failure (vs. conditional)
OPTIONAL_TOOLS: set[str] = {"escalate_to_human"}


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class AgentCoverage:
    agent_name: str
    agent_obs_id: str
    expected: list[str]
    called: list[str]
    missing: list[str] = field(default_factory=list)

    @property
    def score(self) -> float:
        # Exclude optional tools from the denominator
        required = [t for t in self.expected if t not in OPTIONAL_TOOLS]
        if not required:
            return 1.0
        called_required = [t for t in self.called if t not in OPTIONAL_TOOLS]
        return len(called_required) / len(required)


@dataclass
class TraceCoverage:
    trace_id: str
    trace_name: str
    session_id: str
    agents: list[AgentCoverage]

    @property
    def overall_score(self) -> float:
        if not self.agents:
            return 0.0
        return sum(a.score for a in self.agents) / len(self.agents)


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
# Trace fetching
# ---------------------------------------------------------------------------

def fetch_recent_traces(lf, n: int) -> list:
    """Return up to n recent KYC traces by the CrewAI root span name."""
    result = lf.api.trace.list(
        name="crewai-index-trace",
        limit=n,
        order_by="timestamp.desc",
    )
    return list(result.data)


# ---------------------------------------------------------------------------
# Observation fetching + grouping by agent
# ---------------------------------------------------------------------------

def fetch_observations(lf, trace_id: str) -> list:
    """Fetch all observations for a trace in one call (v1 API, self-hosted compatible)."""
    resp = lf.api.legacy.observations_v1.get_many(trace_id=trace_id)
    return list(resp.data)


def group_by_agent(observations: list) -> list[AgentCoverage]:
    """
    Single pass over all observations:
      1. Find agent spans by name prefix matching agent role names.
      2. For each TOOL observation, walk parent_observation_id up until
         an agent span is found — this correctly handles overlap (e.g.
         get_case_details called by multiple agents).

    Returns one AgentCoverage per recognized agent, with called/missing filled in.
    """
    by_id = {obs.id: obs for obs in observations}

    # agent obs.id → AgentCoverage
    agent_spans: dict[str, AgentCoverage] = {}
    for obs in observations:
        if not obs.name:
            continue
        for role in AGENT_EXPECTED_TOOLS:
            if obs.name.startswith(f"{role}."):
                agent_spans[obs.id] = AgentCoverage(
                    agent_name=role,
                    agent_obs_id=obs.id,
                    expected=AGENT_EXPECTED_TOOLS[role],
                    called=[],
                )
                break

    # Walk each TOOL observation up to its parent agent span
    for obs in observations:
        if obs.type != "TOOL" or not obs.name:
            continue
        parent_id = getattr(obs, "parent_observation_id", None)
        while parent_id:
            if parent_id in agent_spans:
                agent_spans[parent_id].called.append(obs.name)
                break
            parent_obs = by_id.get(parent_id)
            parent_id = getattr(parent_obs, "parent_observation_id", None) if parent_obs else None

    # Compute missing
    for ac in agent_spans.values():
        called_set = set(ac.called)
        ac.missing = [t for t in ac.expected if t not in called_set]

    return list(agent_spans.values())


# ---------------------------------------------------------------------------
# Coverage computation
# ---------------------------------------------------------------------------

def compute_coverage(lf, trace_id: str, trace_name: str, session_id: str) -> TraceCoverage:
    observations = fetch_observations(lf, trace_id)
    agents = group_by_agent(observations)
    return TraceCoverage(
        trace_id=trace_id,
        trace_name=trace_name,
        session_id=session_id,
        agents=agents,
    )


# ---------------------------------------------------------------------------
# Score pushing
# ---------------------------------------------------------------------------

def delete_existing_scores(lf, trace_id: str) -> None:
    """Delete all existing tool-coverage scores on a trace before re-pushing."""
    resp = lf.api.legacy.score_v1.get_many(trace_id=trace_id)
    for score in resp.data:
        if score.name and score.name.startswith("tool-coverage"):
            try:
                lf.api.legacy.score_v1.delete(score.id)
                logger.debug("Deleted score %s (%s)", score.id, score.name)
            except Exception as e:
                logger.warning("Could not delete score %s: %s", score.id, e)


def push_scores(lf, coverage: TraceCoverage) -> None:
    """Delete stale scores, then push per-agent tool-coverage scores to each agent observation."""
    delete_existing_scores(lf, coverage.trace_id)

    for agent in coverage.agents:
        lf.create_score(
            trace_id=coverage.trace_id,
            observation_id=agent.agent_obs_id,
            name="tool-coverage",
            value=agent.score,
            comment=(
                f"missing: {agent.missing}" if agent.missing else "all tools called"
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

    if not coverage.agents:
        logger.info("       (no recognized agent spans found — check OTEL instrumentor is active)")
        return

    for agent in coverage.agents:
        agent_status = "OK" if agent.score == 1.0 else "MISS"
        logger.info(
            "       [%s] %-35s  %d/%d tools  called=%s%s",
            agent_status,
            agent.agent_name,
            len(agent.called),
            len([t for t in agent.expected if t not in OPTIONAL_TOOLS]),
            agent.called,
            f"  missing={agent.missing}" if agent.missing else "",
        )



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

        coverage = compute_coverage(lf, tid, name, sid)
        coverages.append(coverage)

        print_coverage(coverage)
        logger.info("")

    total = len(coverages)
    full  = sum(1 for c in coverages if c.overall_score == 1.0)
    avg   = sum(c.overall_score for c in coverages) / total if total else 0.0
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
        description="Offline tool-coverage checker — groups tools by agent, pushes scores to Langfuse"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--last",
        type=int,
        metavar="N",
        help="Check the last N traces named 'crewai-index-trace'.",
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
