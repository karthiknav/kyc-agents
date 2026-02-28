import boto3
import json

agent_arn = "arn:aws:bedrock-agentcore:us-east-1:206409480438:runtime/kyc_agent-UuWAt5DYf0"
agentcore_client = boto3.client(
    'bedrock-agentcore',
    region_name="us-east-1"
)

# KYC screening payload - pass caseId to fetch from DynamoDB
payload = {"caseId": "01HR9B5J7Z6J7PD5B6PKQJ2MM4"}

print("Invoking resume analyzer agent...")
print(f"Payload: {json.dumps(payload, indent=2)}")

boto3_response = agentcore_client.invoke_agent_runtime(
    agentRuntimeArn=agent_arn,
    qualifier="DEFAULT",
    payload=json.dumps(payload)
)
if "text/event-stream" in boto3_response.get("contentType", ""):
    content = []
    for line in boto3_response["response"].iter_lines(chunk_size=1):
        if line:
            line = line.decode("utf-8")
            if line.startswith("data: "):
                line = line[6:]
                print(line)
                content.append(line)
    print("\nFinal content:")
    print("\n".join(content))
else:
    try:
        events = []
        for event in boto3_response.get("response", []):
            events.append(event)
        print("Response events:")
        for event in events:
            print(json.dumps(json.loads(event.decode("utf-8")), indent=2))
    except Exception as e:
        print(f"Error reading response: {e}")
        print(f"Raw response: {boto3_response}")