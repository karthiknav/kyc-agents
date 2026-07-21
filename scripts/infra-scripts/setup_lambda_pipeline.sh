#!/usr/bin/env bash
# Deploys the Lambda CI/CD pipeline stack (Phase 3, Step 7).
# Requires agentcore-stack to already be deployed (Phase 2, Step 5a).
# Packages lambda/ as a Lambda zip and deploys lambda-stack.
# Triggers automatically on changes to lambda/** or templates/lambda-stack.yaml.
#
# No inputs required — all values are hardcoded or resolved from stack outputs.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

REGION="us-east-1"

STORAGE_STACK="kyc-agent-storage"
MAIN_STACK="kyc-agent-main"
ROLES_STACK="kyc-agent-roles"
VPC_STACK="kyc-agent-vpc"
AGENTCORE_STACK="kyc-agent-agentcore-runtime"
LAMBDA_PIPELINE_STACK="kyc-agent-lambda-pipeline"
LAMBDA_STACK="kyc-agent-lambda"
KYC_LAMBDA_TIMEOUT=700

GITHUB_CONNECTION_ARN="arn:aws:codeconnections:us-east-1:926529379586:connection/6ac4ec4b-58b4-4270-8a1b-80acae253b39"
GITHUB_REPO="karthiknav/kyc-agents"
GITHUB_BRANCH="improvements"

echo "=== Lambda pipeline deployment ==="
echo "  LAMBDA_PIPELINE_STACK : $LAMBDA_PIPELINE_STACK"
echo "  LAMBDA_STACK          : $LAMBDA_STACK"
echo "  AGENTCORE_STACK       : $AGENTCORE_STACK"
echo "  GITHUB_REPO           : $GITHUB_REPO"
echo "  GITHUB_BRANCH         : $GITHUB_BRANCH"
echo "  REGION                : $REGION"
echo ""

# ── Step 6: Verify agentcore-stack is stable and fetch AgentRuntimeArn ────────
echo "── Step 6: Checking agentcore-stack status ──"
AGENTCORE_STATUS=$(aws cloudformation describe-stacks \
    --stack-name "$AGENTCORE_STACK" \
    --query 'Stacks[0].StackStatus' \
    --output text --region "$REGION")

echo "  $AGENTCORE_STACK status: $AGENTCORE_STATUS"

if [[ "$AGENTCORE_STATUS" != "CREATE_COMPLETE" && "$AGENTCORE_STATUS" != "UPDATE_COMPLETE" ]]; then
    echo "ERROR: $AGENTCORE_STACK is not in a stable state ($AGENTCORE_STATUS)."
    echo "  Wait for the AgentCore pipeline to finish deploying it, then re-run this script."
    exit 1
fi

AGENT_ARN=$(aws cloudformation describe-stacks \
    --stack-name "$AGENTCORE_STACK" \
    --query 'Stacks[0].Outputs[?OutputKey==`AgentRuntimeArn`].OutputValue' \
    --output text --region "$REGION")

echo "  AGENT_ARN: $AGENT_ARN"
echo ""

# ── Fetch outputs from base stacks ────────────────────────────────────────────
echo "── Fetching outputs from base stacks ──"
KYC_RESULTS_BUCKET=$(aws cloudformation describe-stacks \
    --stack-name "$STORAGE_STACK" \
    --query 'Stacks[0].Outputs[?OutputKey==`SourceBucketName`].OutputValue' \
    --output text --region "$REGION")

KYC_CASES_TABLE=$(aws cloudformation describe-stacks \
    --stack-name "$STORAGE_STACK" \
    --query 'Stacks[0].Outputs[?OutputKey==`KycCasesTableName`].OutputValue' \
    --output text --region "$REGION")

KYC_QUEUE_ARN=$(aws cloudformation describe-stacks \
    --stack-name "$MAIN_STACK" \
    --query 'Stacks[0].Outputs[?OutputKey==`KycInitiatedQueueArn`].OutputValue' \
    --output text --region "$REGION")

echo "  KYC_RESULTS_BUCKET : $KYC_RESULTS_BUCKET"
echo "  KYC_CASES_TABLE    : $KYC_CASES_TABLE"
echo "  KYC_QUEUE_ARN      : $KYC_QUEUE_ARN"
echo ""

# ── Step 7: Deploy lambda-pipeline-stack ──────────────────────────────────────
echo "── Step 7: Deploying $LAMBDA_PIPELINE_STACK ──"
aws cloudformation deploy \
    --template-file "$REPO_ROOT/templates/lambda-pipeline-stack.yaml" \
    --stack-name "$LAMBDA_PIPELINE_STACK" \
    --parameter-overrides \
        GitHubConnectionArn="$GITHUB_CONNECTION_ARN" \
        GitHubRepo="$GITHUB_REPO" \
        GitHubBranch="$GITHUB_BRANCH" \
        RolesStackName="$ROLES_STACK" \
        LambdaStackName="$LAMBDA_STACK" \
        KycResultsBucketName="$KYC_RESULTS_BUCKET" \
        KycCasesTableName="$KYC_CASES_TABLE" \
        KycInitiatedQueueArn="$KYC_QUEUE_ARN" \
        AgentArn="$AGENT_ARN" \
        VpcStackName="$VPC_STACK" \
        KycLambdaTimeout="$KYC_LAMBDA_TIMEOUT" \
    --region "$REGION"

echo "✓ $LAMBDA_PIPELINE_STACK deployed"
echo ""
echo "=== Lambda pipeline deployed successfully ==="
echo "  The pipeline will build and deploy $LAMBDA_STACK on the next push to $GITHUB_BRANCH."
