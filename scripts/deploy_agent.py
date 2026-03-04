#!/usr/bin/env python3
"""Deploy Resume Analyzer Agent to Bedrock AgentCore Runtime"""

import os
import boto3
from bedrock_agentcore_starter_toolkit import Runtime

def get_stack_output(stack_name: str, output_key: str, region: str) -> str:
    """Get CloudFormation stack output value"""
    cf = boto3.client('cloudformation', region_name=region)
    response = cf.describe_stacks(StackName=stack_name)
    outputs = response['Stacks'][0]['Outputs']
    for output in outputs:
        if output['OutputKey'] == output_key:
            return output['OutputValue']
    raise ValueError(f"Output {output_key} not found in stack {stack_name}")

def main():
    region = os.getenv('AWS_DEFAULT_REGION', 'us-east-1')
    execution_role = "arn:aws:iam::206409480438:role/AmazonBedrockAgentCoreExecutionRolev1"
    # Configure AgentCore
    print("🔧 Configuring AgentCore...")
    agentcore_runtime = Runtime()
    response = agentcore_runtime.configure(
        entrypoint="crew/research_crew.py",
        execution_role=execution_role,
        auto_create_ecr=True,
        requirements_file="crew/requirements.txt",
        region=region,
        agent_name="kyc_agent"
    )
    print(f"✅ Configuration completed: {response}")
    
    # Launch agent
    print("🚀 Launching agent...")
    launch_result = agentcore_runtime.launch()
    print(f"✅ Launch completed: {launch_result.agent_arn}")
    
    agent_arn = launch_result.agent_arn
    status_response = agentcore_runtime.status()
    status = status_response.endpoint["status"]
    
    print(f"📊 Final status: {status}")
    print(f"🎉 Agent deployed successfully!")
    print(f"\n📋 Agent ARN: {agent_arn}")

if __name__ == "__main__":
    main()