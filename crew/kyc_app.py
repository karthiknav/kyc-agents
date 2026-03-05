import logging
import os

from dotenv import load_dotenv

load_dotenv()

import boto3
from bedrock_agentcore.runtime import BedrockAgentCoreApp

from crew.crew import KYCCrew

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_ssm_parameter(name: str, with_decryption: bool = True) -> str:
    ssm = boto3.client("ssm")
    response = ssm.get_parameter(Name=name, WithDecryption=with_decryption)
    return response["Parameter"]["Value"]


logger.info("Setting up environment variables from SSM Parameter Store...")
try:
    openai_key = get_ssm_parameter("/ops-orchestrator/openai-api-key")
    os.environ["OPENAI_API_KEY"] = openai_key
    logger.info("✅ OPENAI_API_KEY set")
except Exception as e:
    logger.error("❌ Failed to set OPENAI_API_KEY: %s", e)


app = BedrockAgentCoreApp()


@app.entrypoint
def agent_invocation(payload):
    """
    Handler for the full KYC workflow (sequential).
    Receives {caseId} and runs: document processing → screening → final decision.
    """
    try:
        case_id = payload.get("caseId", "").strip()
        if not case_id:
            logger.warning("No caseId provided in payload")
            return {"error": "Missing 'caseId' in payload"}

        logger.info("KYC sequential workflow for caseId: %s", case_id)
        result = KYCCrew().crew().kickoff(inputs={"caseId": case_id})
        logger.info("KYC workflow result: %s", result.raw)
        return {"result": result.raw}

    except Exception as e:
        logger.exception("KYC workflow invocation failed")
        return {"error": str(e)}


if __name__ == "__main__":
    app.run()
    # payload = {"caseId": "test-case-id"}
    # logger.info("Testing locally with payload: %s", payload)
    # response = agent_invocation(payload)
    # logger.info("Response: %s", response)
