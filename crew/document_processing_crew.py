from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task
from crewai.agents.agent_builder.base_agent import BaseAgent
from typing import List

from crew.tools.dynamodb_tool import GetCaseDetailsTool
from crew.tools.get_case_files_tool import GetCaseFilesTool
from crew.tools.textract_tool import ExtractDocumentTextTool
from crew.tools.compare_identity_tool import CompareIdentityDocumentsTool
from crew.update_document_result import update_document_result


@CrewBase
class DocumentProcessingCrew():
    """KYC document processing crew: fetches files, extracts text, compares identity fields."""

    agents: List[BaseAgent]
    tasks: List[Task]

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

    @task
    def document_processing_task(self) -> Task:
        return Task(
            config=self.tasks_config['document_processing_task'],
            callback=update_document_result,
        )

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=True,
        )
