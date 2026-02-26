import logging
from crew.crew import ResearchCrew
import boto3
import os
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
    os.environ['OPENAI_API_KEY'] = openai_key
    logger.info("✅ OPENAI_API_KEY environment variable set")
    tavily_api_key = get_ssm_parameter("/ops-orchestrator/tavily-api-key")
    os.environ["TAVILY_API_KEY"] = tavily_api_key
    logger.info("✅ TAVILY_API_KEY environment variable set")
except Exception as e:
    logger.error(f"❌ Failed to set OPENAI_API_KEY or TAVILY_API_KEY: {e}")
   

app = BedrockAgentCoreApp()


@app.entrypoint
def agent_invocation(payload):
    """Handler for KYC screening: pass full name in payload.prompt; returns JSON with name, analysis_result, analysis_summary."""
    try:
        full_name = payload.get("prompt", "").strip() or payload.get("name", "")
        if not full_name:
            logger.warning("No name provided in payload")
            return {"error": "Missing 'prompt' or 'name' in payload"}
        logger.info("KYC screening for name: %s", full_name)

        research_crew_instance = ResearchCrew()
        crew = research_crew_instance.crew()
        result = crew.kickoff(inputs={"name": full_name})

        logger.info("Result: %s", result.raw)
        output = {"result": result.raw}
        return output

    except Exception as e:
        logger.exception("Agent invocation failed")
        return {"error": str(e)}


if __name__ == "__main__":
    app.run()
    # logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    # test_names = ["Vijay Mallya"]

    # for name in test_names:
    #     logger.info("KYC screening: %s", name)
    #     response = agent_invocation({"prompt": name})
    #     logger.info("Response: %s", response)