from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task
from crewai.agents.agent_builder.base_agent import BaseAgent
from typing import List

from crew.tools.dynamodb_tool import GetCaseDetailsTool
from crew.tools.search_person_tool import SearchPersonTool
from crew.tools.screening_analysis_tool import ScreeningAnalysisTool
from crew.update_case import update_screening_result


@CrewBase
class ResearchCrew():
    """KYC screening crew: single agent with get_case_details, search_person, and produce_screening_analysis tools."""

    agents: List[BaseAgent]
    tasks: List[Task]

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

    @task
    def screening_task(self) -> Task:
        return Task(
            config=self.tasks_config['screening_task'],
            callback=update_screening_result,
        )

    @crew
    def crew(self) -> Crew:
        """Creates the KYC screening crew with a single agent."""
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=True,
        )
