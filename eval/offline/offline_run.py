"""
Offline evals for KYC experiment traces.

Two evaluations are available:

  tool-coverage
    Fetches recent KYC traces from Langfuse, groups tool observations by the
    agent that called them, compares against the expected tool set per agent,
    and pushes per-agent tool-coverage scores back to each trace.

  orchestrator-decision-quality
    Fetches recent KYC traces, finds the GENERATION observation belonging to
    the KYC Decision Orchestrator agent, and uses Claude as a judge to score
    decision correctness and reason completeness (0.0–1.0).

The hierarchy in each trace is:
  crewai-index-trace (root)
    └── {role}.agent  (SPAN, one per agent)
          └── GENERATION observations (type=GENERATION, name starts with role)
          └── tool observations (type=TOOL, name=tool_name)

Usage (from repo root):
  # Tool-coverage check — last 5 traces, dry run
  python -m eval.offline.offline_run --last 5

  # Decision-quality check — last 10 traces, push scores back
  python -m eval.offline.offline_run --last 10 --eval decision-quality --push-scores

  # Both evals on a single trace
  python -m eval.offline.offline_run --trace-id <id> --eval all --push-scores

  # Use a specific judge model (default: claude-haiku-4-5-20251001)
  python -m eval.offline.offline_run --last 5 --eval decision-quality --model claude-sonnet-4-6
"""

from __future__ import annotations

import argparse
import json
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

ORCHESTRATOR_ROLE = "KYC Decision Orchestrator"

# ---------------------------------------------------------------------------
# Judge prompt for orchestrator-decision-quality
# ---------------------------------------------------------------------------

JUDGE_PROMPT = """\
You are a compliance QA reviewer auditing an automated KYC decision.

The agent's reasoning and tool execution (shows what the agent actually found):
<input>
{input}
</input>

The agent's final structured decision:
<output>
{output}
</output>

Evaluate on TWO dimensions, return a score from 0.0 to 1.0:

1. DECISION CORRECTNESS (did the right action follow from the findings?)
   - APPROVED is only valid if document=MATCH AND risk=CLEAR AND adverse=OK
   - ESCALATED is valid if at least one check failed

2. REASON COMPLETENESS (does reason[] reflect what the agent actually found?)
   - Compare the detail in <input> (Thought + Observation) against reason[] in <output>
   - Penalise if reason[] is vague (e.g. "Adverse media result is NOK") when the \
input reveals specific findings (e.g. fraud conviction, money laundering)
   - A good reason[] should mention the person, the specific finding, and the result

Score HIGH (0.8-1.0): correct decision AND reason[] captures the specific findings from input
Score MEDIUM (0.5-0.7): correct decision BUT reason[] is vague relative to what input shows
Score LOW (0.0-0.4): wrong decision OR reason[] contradicts the input OR output is not valid JSON

Respond with a JSON object only, no preamble:
{{"score": <float 0.0-1.0>, "reasoning": "<one sentence>"}}
"""



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


@dataclass
class DecisionQualityResult:
    trace_id: str
    trace_name: str
    session_id: str
    obs_id: Optional[str]
    score: Optional[float]
    reasoning: str


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
    """Fetch all observations for a trace, paginating through all pages (v1 API)."""
    all_obs = []
    page = 1
    while True:
        resp = lf.api.legacy.observations_v1.get_many(trace_id=trace_id, page=page, limit=100)
        all_obs.extend(resp.data)
        if page >= resp.meta.total_pages:
            break
        page += 1
    return all_obs


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
            if obs.name.startswith(f"{role}") and obs.type == "GENERATION":
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
# Tool-coverage score pushing
# ---------------------------------------------------------------------------

def push_coverage_scores(lf, coverage: TraceCoverage) -> None:
    """Push per-agent tool-coverage scores to each agent observation."""
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
# Tool-coverage reporting
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
# Decision quality helpers
# ---------------------------------------------------------------------------

def _stringify(value) -> str:
    """Convert any Langfuse observation input/output value to a string."""
    if value is None:
        return "(empty)"
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, indent=2, default=str)
    except Exception:
        return str(value)


def find_orchestrator_generation(observations: list):
    """Return the GENERATION observation whose parent span is the KYC Decision Orchestrator, or None."""
    by_id = {obs.id: obs for obs in observations}
    for obs in observations:
        if obs.type != "GENERATION":
            continue
        parent_id = getattr(obs, "parent_observation_id", None)
        if not parent_id:
            continue
        parent = by_id.get(parent_id)
        if parent and parent.name and parent.name.startswith(ORCHESTRATOR_ROLE):
            return obs
    return None


def score_with_llm(input_text: str, output_text: str) -> tuple[float, str]:
    """Call the Bedrock judge (EVALMODEL env var). Returns (score, reasoning)."""
    import boto3

    model_id = os.environ.get("EVALMODEL", "deepseek.v3.2")
    client = boto3.client("bedrock-runtime")
    prompt = JUDGE_PROMPT.format(input=input_text, output=output_text)
    resp = client.converse(
        modelId=model_id,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": 512, "temperature": 0.0},
    )
    raw = resp["output"]["message"]["content"][0]["text"].strip()
    try:
        data = json.loads(raw)
        return float(data["score"]), str(data.get("reasoning", ""))
    except Exception:
        logger.warning("Judge returned non-JSON: %r", raw)
        return 0.0, f"parse error: {raw[:120]}"


def compute_decision_quality(
    lf,
    trace_id: str,
    trace_name: str,
    session_id: str,
) -> DecisionQualityResult:
    observations = fetch_observations(lf, trace_id)
    obs = find_orchestrator_generation(observations)
    if obs is None:
        logger.warning("[%s] No orchestrator GENERATION found — skipping.", trace_id)
        return DecisionQualityResult(
            trace_id=trace_id,
            trace_name=trace_name,
            session_id=session_id,
            obs_id=None,
            score=None,
            reasoning="no orchestrator generation found",
        )

    input_text = _stringify(getattr(obs, "input", None))
    output_text = _stringify(getattr(obs, "output", None))
    score, reasoning = score_with_llm(input_text, output_text)
    return DecisionQualityResult(
        trace_id=trace_id,
        trace_name=trace_name,
        session_id=session_id,
        obs_id=obs.id,
        score=score,
        reasoning=reasoning,
    )


def push_decision_quality_score(lf, result: DecisionQualityResult) -> None:
    """Push the decision-quality score to the orchestrator observation."""
    if result.score is None or result.obs_id is None:
        return
    lf.create_score(
        trace_id=result.trace_id,
        observation_id=result.obs_id,
        name="orchestrator-decision-quality",
        value=result.score,
        comment=result.reasoning,
    )
    lf.flush()


def print_decision_quality(result: DecisionQualityResult) -> None:
    if result.score is None:
        logger.info(
            "[SKIP] trace=%-36s  name=%-20s  %s",
            result.trace_id,
            result.trace_name or "(unnamed)",
            result.reasoning,
        )
        return
    band = "HIGH" if result.score >= 0.8 else ("MED" if result.score >= 0.5 else "LOW")
    logger.info(
        "[%-4s] trace=%-36s  name=%-20s  score=%.2f  %s",
        band,
        result.trace_id,
        result.trace_name or "(unnamed)",
        result.score,
        result.reasoning,
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
            push_coverage_scores(lf, coverage)
        logger.info("Done.")
    else:
        logger.info("(dry run — add --push-scores to write scores to Langfuse)")


def run_decision_quality_check(
    last_n: Optional[int] = None,
    trace_id: Optional[str] = None,
    push: bool = False
) -> None:
    lf = _langfuse_client()

    if trace_id:
        traces = [lf.api.trace.get(trace_id)]
    else:
        traces = fetch_recent_traces(lf, last_n or 10)

    if not traces:
        logger.warning("No traces found.")
        return

    logger.info(
        "Checking orchestrator-decision-quality for %d trace(s) (judge: %s) ...",
        len(traces),
        os.environ.get("EVALMODEL", "deepseek.v3.2"),
    )
    logger.info("─" * 70)

    results: list[DecisionQualityResult] = []
    for trace in traces:
        tid  = trace.id
        name = getattr(trace, "name", None) or ""
        sid  = getattr(trace, "session_id", None) or ""

        result = compute_decision_quality(lf, tid, name, sid)
        results.append(result)

        print_decision_quality(result)

    scored = [r for r in results if r.score is not None]
    avg = sum(r.score for r in scored) / len(scored) if scored else 0.0  # type: ignore[arg-type]
    logger.info("─" * 70)
    logger.info(
        "Summary  : %d / %d scored  (avg %.2f)",
        len(scored),
        len(results),
        avg,
    )

    if push:
        logger.info("Pushing scores to Langfuse ...")
        for result in results:
            push_decision_quality_score(lf, result)
        logger.info("Done.")
    else:
        logger.info("(dry run — add --push-scores to write scores to Langfuse)")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Offline evals for KYC traces: tool-coverage and/or orchestrator-decision-quality"
        )
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
        "--eval",
        choices=["tool-coverage", "decision-quality", "all"],
        default="tool-coverage",
        help=(
            "Which eval to run: tool-coverage (default), decision-quality, or all."
        ),
    )
    parser.add_argument(
        "--push-scores",
        action="store_true",
        default=False,
        help="Push scores back to each trace in Langfuse (default: dry run).",
    )
    args = parser.parse_args()

    run_coverage = args.eval in ("tool-coverage", "all")
    run_quality  = args.eval in ("decision-quality", "all")

    if run_coverage:
        run_coverage_check(
            last_n=args.last,
            trace_id=args.trace_id,
            push=args.push_scores,
        )

    if run_quality:
        if run_coverage:
            logger.info("")
        run_decision_quality_check(
            last_n=args.last,
            trace_id=args.trace_id,
            push=args.push_scores,
        )


if __name__ == "__main__":
    main()
