import logging
import os

from dotenv import load_dotenv

load_dotenv()

import boto3
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from crewai import Crew, Process

from crew.crew import KYCCrew

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


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

        # Run only the sanctions screening agent and task
        result = KYCCrew().crew().kickoff(inputs={"caseId": case_id})

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