import logging
import os

from dotenv import load_dotenv

load_dotenv()

from crew.crew import ResearchCrew
import boto3
from bedrock_agentcore.runtime import BedrockAgentCoreApp

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
    tavily_api_key = get_ssm_parameter("/ops-orchestrator/tavily-api-key")
    os.environ["TAVILY_API_KEY"] = tavily_api_key
    logger.info("✅ TAVILY_API_KEY environment variable set")
except Exception as e:
    logger.error("❌ Failed to set OPENAI_API_KEY or TAVILY_API_KEY: %s", e)


app = BedrockAgentCoreApp()


@app.entrypoint
def agent_invocation(payload):
    """
    Handler for KYC screening.
    Payload must include caseId. Optionally KYC_CASES_TABLE env var for DynamoDB table name.
    Returns JSON with name, analysis_result, analysis_summary.
    """
    try:
        case_id = payload.get("caseId", "").strip()
        if not case_id:
            logger.warning("No caseId provided in payload")
            return {"error": "Missing 'caseId' in payload"}

        logger.info("KYC screening for caseId: %s", case_id)

        research_crew_instance = ResearchCrew()
        crew_instance = research_crew_instance.crew()
        result = crew_instance.kickoff(inputs={"caseId": case_id})

        logger.info("Result: %s", result.raw)
        output = {"result": result.raw}
        return output

    except Exception as e:
        logger.exception("Agent invocation failed")
        return {"error": str(e)}


if __name__ == "__main__":
    #app.run()
    payload = {"caseId": "1234"}
    logger.info("Testing locally with payload: %s", payload)
    response = agent_invocation(payload)
    logger.info("Response: %s", response)

