import logging
import os

from dotenv import load_dotenv

load_dotenv()

import boto3
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from crewai import Agent, Crew, Process, Task

from crew.tools.aggregate_results_tool import AggregateKYCResultsTool
from crew.tools.dynamodb_tool import GetCaseDetailsTool
from crew.tools.escalate_human_tool import EscalateToHumanTool
from crew.tools.fanout_tool import FanoutSubagentsTool
from crew.tools.get_case_stages_tool import GetCasestagesTool
from crew.crew import KYCCrew
from crew.update_orchestrator_result import update_orchestrator_result

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_ssm_parameter(name: str, with_decryption: bool = True) -> str:
    """Get a parameter value from AWS Systems Manager Parameter Store."""
    ssm = boto3.client("ssm")
    response = ssm.get_parameter(Name=name, WithDecryption=with_decryption)
    return response["Parameter"]["Value"]


logger.info("Setting up environment variables from SSM Parameter Store...")
try:
    openai_key = get_ssm_parameter("/ops-orchestrator/openai-api-key")
    os.environ["OPENAI_API_KEY"] = openai_key
    logger.info("✅ OPENAI_API_KEY environment variable set")
except Exception as e:
    logger.error("❌ Failed to set OPENAI_API_KEY: %s", e)


app = BedrockAgentCoreApp()


@app.entrypoint
def agent_invocation(payload):
    """
    Handler for KYC orchestration.
    Payload must include caseId.
    On first invocation: fans out to sub-agents.
    On subsequent invocations: aggregates results and makes final decision.
    """
    try:
        case_id = payload.get("caseId", "").strip()
        if not case_id:
            logger.warning("No caseId provided in payload")
            return {"error": "Missing 'caseId' in payload"}

        logger.info("KYC orchestration for caseId: %s", case_id)

        # Build a focused crew with only the orchestrator agent and task
        kyc_crew = KYCCrew()
        crew = Crew(
            agents=[kyc_crew.orchestrator_agent()],
            tasks=[kyc_crew.orchestrator_task()],
            process=Process.sequential,
            verbose=True,
        )
        result = crew.kickoff(inputs={"caseId": case_id})

        logger.info("Orchestrator result: %s", result.raw)
        return {"result": result.raw}

    except Exception as e:
        logger.exception("Orchestrator invocation failed")
        return {"error": str(e)}


if __name__ == "__main__":
    payload = {"caseId": "test-case-id"}
    logger.info("Testing locally with payload: %s", payload)
    response = agent_invocation(payload)
    logger.info("Response: %s", response)
