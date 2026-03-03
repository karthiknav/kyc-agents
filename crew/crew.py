from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task
from crewai.agents.agent_builder.base_agent import BaseAgent
from typing import List

from crew.tools.aggregate_results_tool import AggregateKYCResultsTool
from crew.tools.compare_identity_tool import CompareIdentityDocumentsTool
from crew.tools.dynamodb_tool import GetCaseDetailsTool
from crew.tools.escalate_human_tool import EscalateToHumanTool
from crew.tools.fanout_tool import FanoutSubagentsTool
from crew.tools.get_case_files_tool import GetCaseFilesTool
from crew.tools.get_case_stages_tool import GetCasestagesTool
from crew.tools.screening_analysis_tool import ScreeningAnalysisTool
from crew.tools.search_person_tool import SearchPersonTool
from crew.tools.textract_tool import ExtractDocumentTextTool
from crew.update_case import update_screening_result
from crew.update_document_result import update_document_result
from crew.update_orchestrator_result import update_orchestrator_result


@CrewBase
class KYCCrew():
    """KYC crew: orchestrator, document processing agent, and sanctions screening agent."""

    agents: List[BaseAgent]
    tasks: List[Task]

    # ------------------------------------------------------------------
    # Orchestrator
    # ------------------------------------------------------------------

    @agent
    def orchestrator_agent(self) -> Agent:
        return Agent(
            config=self.agents_config['orchestrator_agent'],  # type: ignore[index]
            verbose=True,
            tools=[
                GetCaseDetailsTool(),
                GetCasestagesTool(),
                FanoutSubagentsTool(),
                AggregateKYCResultsTool(),
                EscalateToHumanTool(),
            ],
        )

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
                CompareIdentityDocumentsTool(),
            ],
        )

    # ------------------------------------------------------------------
    # Sanctions Screening Agent
    # ------------------------------------------------------------------

    @agent
    def kyc_screening_agent(self) -> Agent:
        return Agent(
            config=self.agents_config['kyc_screening_agent'],  # type: ignore[index]
            verbose=True,
            tools=[
                GetCaseDetailsTool(),
                SearchPersonTool(),
                ScreeningAnalysisTool(),
            ],
        )

    # ------------------------------------------------------------------
    # Tasks
    # ------------------------------------------------------------------

    @task
    def orchestrator_task(self) -> Task:
        return Task(
            config=self.tasks_config['orchestrator_task'],  # type: ignore[index]
            callback=update_orchestrator_result,
        )

    @task
    def document_processing_task(self) -> Task:
        return Task(
            config=self.tasks_config['document_processing_task'],  # type: ignore[index]
            callback=update_document_result,
        )

    @task
    def screening_task(self) -> Task:
        return Task(
            config=self.tasks_config['screening_task'],  # type: ignore[index]
            callback=update_screening_result,
        )

    # ------------------------------------------------------------------
    # Crew
    # ------------------------------------------------------------------

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=True,
        )
