from crewai import Agent, Crew, Process, Task, LLM
from crewai.project import CrewBase, agent, crew, task
from crewai.agents.agent_builder.base_agent import BaseAgent
from typing import List
import logging
import os

logger = logging.getLogger(__name__)


def _resolve_bedrock_model_from_env(*, default_model: str) -> str:
    model_env = (os.getenv("MODEL") or "").strip()
    if not model_env:
        return default_model
    return model_env if model_env.startswith("bedrock/") else f"bedrock/{model_env}"

# Monkey-patch CrewAI native Bedrock: correct tool-call arg parsing (input vs arguments).
# Empty-response retry: on by default (Bedrock Converse sometimes returns message.content=[]).
# Disable with KYC_BEDROCK_EMPTY_RESPONSE_RETRY=0 if you need a stable message list for debugging.
# Optional: KYC_BEDROCK_EMPTY_RESPONSE_MAX_RETRIES (default 3) for continuation nudges after empty replies.
# Slim tool observations: apply_slim_tool_observations_patch() removes CrewAI's periodic full tool-list
# append after every 3rd tool (huge context). Set KYC_CREWAI_TOOL_FORMAT_REMINDERS=1 to restore default.
from crew.bedrock_tool_args_patch import (
    apply_bedrock_tool_args_patch,
)
from crew.crewai_tool_observation_patch import apply_slim_tool_observations_patch
from crew.crewai_guardrail_scratchpad_patch import apply_guardrail_scratchpad_patch
from crew.bedrock_assistant_prefill_patch import apply_bedrock_assistant_prefill_patch

apply_bedrock_tool_args_patch()
apply_slim_tool_observations_patch()
apply_guardrail_scratchpad_patch()
apply_bedrock_assistant_prefill_patch()

from crew.tools.adverse_media_analysis_tool import AdverseMediaAnalysisTool, get_last_adverse_id, reset_adverse_state
from crew.tools.compare_identity_tool import CompareIdentityDocumentsTool, get_last_run_id, reset_run_id
from crew.tools.risk_list_screening_tool import RiskListScreeningTool, get_last_screening_id, reset_screening_state
from crew.tools.dynamodb_tool import GetCaseDetailsTool
from crew.tools.escalate_human_tool import EscalateToHumanTool
from crew.tools.get_case_files_tool import GetCaseFilesTool

from crew.tools.get_case_stage_details_tool import GetCaseStageDetailsTool
from crew.tools.analyze_override_tool import AnalyzeOverrideTool

from crew.tools.textract_tool import ExtractDocumentTextTool
from crew.tools.verify_identity_tool import VerifyIdentityDocumentTool
from crew.update_case import update_adverse_media_result, update_risk_list_screening_result
from crew.update_document_result import update_document_result
from crew.update_orchestrator_result import update_orchestrator_result
from crew.update_override_result import update_override_result



@CrewBase
class KYCCrew():
    """KYC crew: document processing → sanctions screening → final decision (sequential)."""

    agents_config = 'config/kyc_agents.yaml'
    tasks_config = 'config/kyc_tasks.yaml'

    agents: List[BaseAgent]
    tasks: List[Task]
    # Use a Bedrock model that supports both system prompts and tool use (e.g. Claude 3.5 Sonnet v2, Nova Pro).
    # Models without tool use (e.g. Titan, Claude 2.x, Mistral Instruct) will fail when agents use tools.

    _default_bedrock_model = "bedrock/openai.gpt-oss-120b-1:0"

    def get_llm(self) -> LLM:
        """Create (and refresh) the LLM using the current MODEL env var.

        NOTE: AgentCore runtimes are long-lived; `crew/kyc_app.py` refreshes
        `os.environ['MODEL']` from SSM between invocations. We must therefore
        resolve the model at runtime (not import time).
        """

        resolved_model = _resolve_bedrock_model_from_env(
            default_model=self._default_bedrock_model
        )

        logger.info(
                "Using Bedrock model: %s (MODEL env=%r)",
                resolved_model,
                (os.getenv("MODEL") or "").strip(),
            )
        self._llm_model = resolved_model
        self._llm_instance = LLM(
                model=resolved_model,
                temperature=0,
            )
            

        return self._llm_instance

    # ------------------------------------------------------------------
    # Document Processing Agent
    # ------------------------------------------------------------------

    @agent
    def document_processing_agent(self) -> Agent:
        return Agent(
            config=self.agents_config['document_processing_agent'],  # type: ignore[index]
            verbose=True,
            tools=[
                GetCaseDetailsTool(),
                GetCaseFilesTool(),
                ExtractDocumentTextTool(),
                VerifyIdentityDocumentTool(),
                CompareIdentityDocumentsTool(),
            ],
            llm=self.get_llm(),
        )

    # ------------------------------------------------------------------
    # Risk List Screening Agent (PEP + sanctions API)
    # ------------------------------------------------------------------

    @agent
    def risk_list_screening_agent(self) -> Agent:
        return Agent(
            config=self.agents_config['risk_list_screening_agent'],  # type: ignore[index]
            verbose=True,
            tools=[
                RiskListScreeningTool(),
            ],
            llm=self.get_llm(),
        )

    # ------------------------------------------------------------------
    # Adverse Media Agent (web search)
    # ------------------------------------------------------------------

    @agent
    def adverse_media_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["adverse_media_agent"],  # type: ignore[index]
            verbose=True,
            tools=[
                AdverseMediaAnalysisTool(),
            ],
            llm=self.get_llm(),
        )

    # ------------------------------------------------------------------
    # Orchestrator Agent (final decision-maker)
    # ------------------------------------------------------------------

    @agent
    def orchestrator_agent(self) -> Agent:
        return Agent(
            config=self.agents_config['orchestrator_agent'],  # type: ignore[index]
            verbose=True,
            tools=[
                EscalateToHumanTool(),
            ],
            llm=self.get_llm(),
        )

    # ------------------------------------------------------------------
    # Tasks — order determines sequential execution:
    #   1. document_processing_task
    #   2. risk_list_screening_task
    #   3. adverse_media_task
    #   4. orchestrator_task  (context: outputs of 1 + 2 + 3)
    # ------------------------------------------------------------------

    @task
    def document_processing_task(self) -> Task:
        reset_run_id()

        def _guardrail(output) -> tuple[bool, str]:
            """Reject outputs that don't contain the nonce from compare_identity_documents.

            compare_identity_documents generates a UUID run_id only when it successfully
            processes real OCR data. The agent cannot know this value without calling the
            tool — and the tool rejects empty/fabricated OCR arrays — so a matching run_id
            proves the full pipeline (get_case_files → extract_document_text →
            verify_identity_document → compare_identity_documents) actually ran.
            """
            import json as _json
            raw = output.raw if hasattr(output, "raw") else str(output)
            try:
                parsed = _json.loads(raw)
            except Exception:
                parsed = {}

            # Detect the "tool call as Final Answer" failure mode: the model outputs
            # {"tool": "...", "tool_input": {...}} as text instead of calling the tool via the API.
            if isinstance(parsed, dict) and "tool" in parsed and "tool_input" in parsed:
                tool_name = parsed.get("tool", "unknown")
                return (
                    False,
                    f"REJECTED: Your final answer IS a tool call (tool='{tool_name}'). "
                    "You must EXECUTE tools by calling them — do not describe tool calls in your final answer. "
                    "Start over: call get_case_details, get_case_files, extract_document_text, "
                    "verify_identity_document, then compare_identity_documents. "
                    "Only after all five tools have returned results should you produce your final JSON output.",
                )

            expected = get_last_run_id()
            if not expected:
                return (
                    False,
                    "REJECTED: compare_identity_documents was never called (no run_id issued). "
                    "You MUST complete all 5 steps — get_case_details, get_case_files, "
                    "extract_document_text, verify_identity_document, compare_identity_documents "
                    "— before producing your final output.",
                )

            actual = parsed.get("run_id")
            if actual != expected:
                return (
                    False,
                    f"REJECTED: run_id in your output ('{actual}') does not match the one "
                    f"returned by compare_identity_documents. Copy the exact run_id from the "
                    f"compare_identity_documents tool result into your final JSON.",
                )

            return (True, output.raw)

        return Task(
            config=self.tasks_config['document_processing_task'],  # type: ignore[index]
            callback=update_document_result,
            guardrail=_guardrail,
            guardrail_max_retries=3,
        )

    @task
    def risk_list_screening_task(self) -> Task:
        reset_screening_state()

        def _guardrail(output) -> tuple[bool, str]:
            import json as _json
            raw = output.raw if hasattr(output, "raw") else str(output)
            try:
                parsed = _json.loads(raw)
            except Exception:
                parsed = {}

            if isinstance(parsed, dict) and "tool" in parsed and "tool_input" in parsed:
                tool_name = parsed.get("tool", "unknown")
                return (
                    False,
                    f"REJECTED: Your final answer IS a tool call (tool='{tool_name}'). "
                    "You must EXECUTE tools by calling them — do not describe tool calls in your final answer. "
                    "Call get_case_details, then risk_list_screening. Only after both tools return results "
                    "should you produce your final JSON output.",
                )

            expected = get_last_screening_id()
            if not expected:
                return (
                    False,
                    "REJECTED: risk_list_screening was never called (no screening_id issued). "
                    "You MUST call get_case_details then risk_list_screening before giving your "
                    "final answer. Copy the exact screening_id from the tool result into your JSON.",
                )
            actual = parsed.get("screening_id")
            if actual != expected:
                return (
                    False,
                    f"REJECTED: screening_id in your output ('{actual}') does not match the one "
                    f"returned by risk_list_screening. Copy the exact screening_id from the "
                    f"risk_list_screening tool result into your final JSON.",
                )
            return (True, output.raw)

        return Task(
            config=self.tasks_config["risk_list_screening_task"],  # type: ignore[index]
            callback=update_risk_list_screening_result,
            guardrail=_guardrail,
            guardrail_max_retries=3,
        )

    @task
    def adverse_media_task(self) -> Task:
        reset_adverse_state()

        def _guardrail(output) -> tuple[bool, str]:
            import json as _json
            raw = output.raw if hasattr(output, "raw") else str(output)
            try:
                parsed = _json.loads(raw)
            except Exception:
                parsed = {}

            if isinstance(parsed, dict) and "tool" in parsed and "tool_input" in parsed:
                tool_name = parsed.get("tool", "unknown")
                return (
                    False,
                    f"REJECTED: Your final answer IS a tool call (tool='{tool_name}'). "
                    "You must EXECUTE tools by calling them — do not describe tool calls in your final answer. "
                    "Call get_case_details, search_internet, then produce_adverse_media_analysis. "
                    "Only after all tools return results should you produce your final JSON output.",
                )

            expected = get_last_adverse_id()
            if not expected:
                return (
                    False,
                    "REJECTED: produce_adverse_media_analysis was never called (no analysis_id issued). "
                    "You MUST call get_case_details, search_internet, then produce_adverse_media_analysis "
                    "before giving your final answer. Copy the exact analysis_id from the tool result "
                    "into your final JSON.",
                )
            actual = parsed.get("analysis_id")
            if actual != expected:
                return (
                    False,
                    f"REJECTED: analysis_id in your output ('{actual}') does not match the one "
                    f"returned by produce_adverse_media_analysis. Copy the exact analysis_id from "
                    f"the produce_adverse_media_analysis tool result into your final JSON.",
                )
            return (True, output.raw)

        return Task(
            config=self.tasks_config["adverse_media_task"],  # type: ignore[index]
            callback=update_adverse_media_result,
            guardrail=_guardrail,
            guardrail_max_retries=3,
        )

    @task
    def orchestrator_task(self) -> Task:
        return Task(
            config=self.tasks_config['orchestrator_task'],  # type: ignore[index]
            callback=update_orchestrator_result,
            context=[self.document_processing_task(), self.risk_list_screening_task(), self.adverse_media_task()]
        )

    # ------------------------------------------------------------------
    # Crew
    # ------------------------------------------------------------------

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents=[
                self.document_processing_agent(),
                self.risk_list_screening_agent(),
                self.adverse_media_agent(),
                self.orchestrator_agent(),
            ],
            tasks=[
                self.document_processing_task(),
                self.risk_list_screening_task(),
                self.adverse_media_task(),
                self.orchestrator_task(),
            ],
            process=Process.sequential,
            verbose=True,
        )


@CrewBase
class OverrideValidationCrew():
    """Single-agent crew that evaluates an analyst's override justification against persisted risk flags."""

    agents_config = 'config/override_agents.yaml'
    tasks_config = 'config/override_tasks.yaml'

    agents: List[BaseAgent]
    tasks: List[Task]

    _default_bedrock_model = "bedrock/us.anthropic.claude-sonnet-4-6"

    def get_llm(self) -> LLM:
        resolved_model = _resolve_bedrock_model_from_env(
            default_model=self._default_bedrock_model
        )
        logger.info(
            "OverrideValidationCrew using Bedrock model: %s (MODEL env=%r)",
            resolved_model,
            (os.getenv("MODEL") or "").strip(),
        )
        return LLM(model=resolved_model, temperature=0)

    @agent
    def override_validation_agent(self) -> Agent:
        return Agent(
            config=self.agents_config['override_validation_agent'],  # type: ignore[index]
            verbose=True,
            tools=[
                GetCaseDetailsTool(),
                GetCaseStageDetailsTool(),
                AnalyzeOverrideTool(),
            ],
            llm=self.get_llm(),
        )

    @task
    def override_validation_task(self) -> Task:
        return Task(
            config=self.tasks_config['override_validation_task'],  # type: ignore[index]
            callback=update_override_result,
        )

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents=[self.override_validation_agent()],
            tasks=[self.override_validation_task()],
            process=Process.sequential,
            verbose=True,
        )
