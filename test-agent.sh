#!/bin/bash

RUNTIME_ID=$(aws cloudformation describe-stacks \
  --stack-name basic-agent-demo-main \
  --region us-east-1 \
  --query 'Stacks[0].Outputs[?OutputKey==`AgentRuntimeId`].OutputValue' \
  --output text)

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGION="us-east-1"
RUNTIME_ARN="arn:aws:bedrock-agentcore:${REGION}:${ACCOUNT_ID}:runtime/${RUNTIME_ID}"

PAYLOAD=$(echo -n '{"prompt": "Explain what Amazon Bedrock in simple terms"}' | base64)

aws bedrock-agentcore invoke-agent-runtime \
  --agent-runtime-arn $RUNTIME_ARN \
  --qualifier DEFAULT \
  --payload $PAYLOAD \
  --region us-east-1 \
  response.json

cat response.json
