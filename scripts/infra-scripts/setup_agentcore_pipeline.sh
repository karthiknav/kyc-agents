#!/usr/bin/env bash
# Deploys the AgentCore CI/CD pipeline stack (Phase 2, Step 5a).
# Builds the crew/ Docker image, pushes to ECR, and deploys agentcore-stack.
# Triggers automatically on any push to the configured branch.
#
# No inputs required — all values are hardcoded or resolved from stack outputs.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

REGION="us-east-1"

STORAGE_STACK="kyc-agent-storage"
MOCK_SERVICE_STACK="kyc-mock-service-eb"
PIPELINE_STACK="kyc-agent-pipeline"
ROLES_STACK="kyc-agent-roles"
AGENTCORE_STACK="kyc-agent-agentcore-runtime"

GITHUB_CONNECTION_ARN="arn:aws:codeconnections:us-east-1:360946915124:connection/24a1bf19-4ba9-42ee-ad2c-f37799f02447"
GITHUB_REPO="karthiknav/kyc-agents"
GITHUB_BRANCH="improvements"

echo "=== AgentCore pipeline deployment ==="
echo "  PIPELINE_STACK   : $PIPELINE_STACK"
echo "  AGENTCORE_STACK  : $AGENTCORE_STACK"
echo "  GITHUB_REPO      : $GITHUB_REPO"
echo "  GITHUB_BRANCH    : $GITHUB_BRANCH"
echo "  REGION           : $REGION"
echo ""

echo "── Fetching outputs from base stacks ──"
KYC_RESULTS_BUCKET=$(aws cloudformation describe-stacks \
    --stack-name "$STORAGE_STACK" \
    --query 'Stacks[0].Outputs[?OutputKey==`SourceBucketName`].OutputValue' \
    --output text --region "$REGION")

KYC_CASES_TABLE=$(aws cloudformation describe-stacks \
    --stack-name "$STORAGE_STACK" \
    --query 'Stacks[0].Outputs[?OutputKey==`KycCasesTableName`].OutputValue' \
    --output text --region "$REGION")

MOCK_SERVICE_URL=$(aws cloudformation describe-stacks \
    --stack-name "$MOCK_SERVICE_STACK" \
    --query 'Stacks[0].Outputs[?OutputKey==`EnvironmentURL`].OutputValue' \
    --output text --region "$REGION")

echo "  KYC_RESULTS_BUCKET : $KYC_RESULTS_BUCKET"
echo "  KYC_CASES_TABLE    : $KYC_CASES_TABLE"
echo "  MOCK_SERVICE_URL   : $MOCK_SERVICE_URL"
echo ""

aws cloudformation deploy \
    --template-file "$REPO_ROOT/templates/pipeline-stack.yaml" \
    --stack-name "$PIPELINE_STACK" \
    --parameter-overrides \
        GitHubConnectionArn="$GITHUB_CONNECTION_ARN" \
        GitHubRepo="$GITHUB_REPO" \
        GitHubBranch="$GITHUB_BRANCH" \
        RolesStackName="$ROLES_STACK" \
        AgentcoreStackName="$AGENTCORE_STACK" \
        KycCasesTableName="$KYC_CASES_TABLE" \
        KycResultsBucketName="$KYC_RESULTS_BUCKET" \
        MockServiceUrl="$MOCK_SERVICE_URL" \
    --capabilities CAPABILITY_NAMED_IAM \
    --region "$REGION"

echo "✓ $PIPELINE_STACK deployed"
echo ""
echo "=== AgentCore pipeline deployed successfully ==="
echo "  The pipeline will build and deploy $AGENTCORE_STACK on the next push to $GITHUB_BRANCH."
echo "  Once complete, fetch the AgentRuntimeArn before deploying the lambda pipeline (Phase 3)."
