from strands import Agent, tool
from strands_tools import calculator # Import the calculator tool
import json
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands.models import BedrockModel

# Create the AgentCore app
app = BedrockAgentCoreApp()

# Create a custom tool
@tool
def weather():
    """Get the current weather. Always returns sunny weather."""
    return "It's sunny and 72°F today!"

model_id = "global.anthropic.claude-haiku-4-5-20251001-v1:0"
model = BedrockModel(
    model_id=model_id,
)

agent = Agent(
    model=model,
    tools=[calculator, weather],
    system_prompt="You're a helpful assistant. You can do simple math calculation, and tell the weather.",
    callback_handler=None
)

@app.entrypoint
async def agent_invocation(payload):
    """
    Invoke the agent with a payload

    IMPORTANT: Payload structure varies depending on invocation method:
    - Direct invocation (Python SDK, Console, agentcore CLI): {"prompt": "..."}
    - AWS SDK invocation (JS/Java/etc via InvokeAgentRuntimeCommand): {"input": {"prompt": "..."}}

    The AWS SDK automatically wraps payloads in an "input" field as part of the API contract.
    This function handles both formats for maximum compatibility.
    """
    # Handle both dict and string payloads
    if isinstance(payload, str):
        payload = json.loads(payload)

    # Extract the prompt from the payload
    # Try AWS SDK format first (most common for production): {"input": {"prompt": "..."}}
    # Fall back to direct format: {"prompt": "..."}
    user_input = None
    if isinstance(payload, dict):
        if "input" in payload and isinstance(payload["input"], dict):
            user_input = payload["input"].get("prompt")
        else:
            user_input = payload.get("prompt")

    if not user_input:
        raise ValueError(f"No prompt found in payload. Expected {{'prompt': '...'}} or {{'input': {{'prompt': '...'}}}}. Received: {payload}")

    # response = agent(user_input)
    # response_text = response.message['content'][0]['text']
    stream = agent.stream_async(user_input)
    async for event in stream:
        if (event.get('event',{}).get('contentBlockDelta',{}).get('delta',{}).get('text')):
            print(event.get('event',{}).get('contentBlockDelta',{}).get('delta',{}).get('text'))
            yield (event.get('event',{}).get('contentBlockDelta',{}).get('delta',{}).get('text'))

    # return response_text

# Local testing
async def test_agent_locally():
    """Test the agent locally without deploying"""
    test_prompts = [
        #"What is 2+2?",
        "What's the weather like?",
        #"Calculate 15 * 7"
    ]
    
    for prompt in test_prompts:
        print(f"\n{'='*50}")
        print(f"Testing: {prompt}")
        print('='*50)
        
        payload = {"prompt": prompt}
        async for chunk in agent_invocation(payload):
            pass  # Chunks already printed in agent_invocation
        print()

if __name__ == "__main__":
    app.run()
    # import sys
    # if len(sys.argv) > 1 and sys.argv[1] == "test":
    #     import asyncio
    #     asyncio.run(test_agent_locally())
