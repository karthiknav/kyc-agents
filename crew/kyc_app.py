import logging
import os

from dotenv import load_dotenv

load_dotenv()

import boto3
from opentelemetry.instrumentation.crewai import CrewAIInstrumentor
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from crewai import Crew, Process
from opentelemetry import trace
tracer = trace.get_tracer(__name__)

from crew.crew import KYCCrew
CrewAIInstrumentor().instrument()

app = BedrockAgentCoreApp()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_ssm_parameter(name: str, with_decryption: bool = True, *, ssm_client=None) -> str:
    """Get a parameter value from AWS Systems Manager Parameter Store."""
    ssm = ssm_client or boto3.client("ssm")
    response = ssm.get_parameter(Name=name, WithDecryption=with_decryption)
    return response["Parameter"]["Value"]


logger.info("Setting up environment variables from SSM Parameter Store...")
try:
    if not os.getenv("MODEL"):
        os.environ["MODEL"] = get_ssm_parameter("/kyc-agent/model-id")
        logger.info("✅ MODEL environment variable set")
except Exception as e:
    logger.error(f"❌ Failed to set MODEL Id from SSM: {e}")




@app.entrypoint
def agent_invocation(payload, context):
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

        # Run only the sanctions screening agent and task
        
        
        with tracer.start_as_current_span("kyc_screening"):
            with tracer.start_as_current_span("crew_kickoff"):
                result = KYCCrew().crew().kickoff(inputs={"caseId": case_id})
        
        logger.info("Result: %s", result.raw)
        output = {"result": result.raw}
        return output

    except Exception as e:
        logger.exception("Agent invocation failed")
        return {"error": str(e)}


if __name__ == "__main__":
    app.run()
    # payload = {"caseId": "1234"}
    # logger.info("Testing locally with payload: %s", payload)
    # response = agent_invocation(payload)
    # logger.info("Response: %s", response)