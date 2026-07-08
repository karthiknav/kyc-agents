#!/usr/bin/env bash
# Deploys the MLOps CD pipeline stack.
# Triggered by EventBridge (model approved in SageMaker Model Registry) rather
# than a GitHub push — see templates/mlops-cd-pipeline-stack.yaml for details.
#
# Prerequisites:
#   - Base stacks deployed (kyc-agent-roles, kyc-agent-storage)
#   - GitHub CodeConnections connection in "Available" state
#   - At least one model version in the 'kyc-risk-scorer' model package group
#     (approve one after deploy to verify the end-to-end trigger)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

REGION="us-east-1"

ROLES_STACK="kyc-agent-roles"
STORAGE_STACK="kyc-agent-storage"
PIPELINE_STACK="kyc-mlops-cd-pipeline"

GITHUB_CONNECTION_ARN="arn:aws:codeconnections:us-east-1:926529379586:connection/2cba1788-cf66-42c9-bde2-97944abf843b"
GITHUB_REPO="karthiknav/kyc-agents"
GITHUB_BRANCH="kyc_risk_engine"

echo "=== MLOps CD pipeline deployment ==="
echo "  PIPELINE_STACK : $PIPELINE_STACK"
echo "  ROLES_STACK    : $ROLES_STACK"
echo "  STORAGE_STACK  : $STORAGE_STACK"
echo "  GITHUB_REPO    : $GITHUB_REPO"
echo "  GITHUB_BRANCH  : $GITHUB_BRANCH"
echo "  REGION         : $REGION"
echo ""

# ── Fetch SageMaker execution role ARN from roles stack ───────────────────────
echo "── Fetching outputs from base stacks ──"
SM_ROLE_ARN=$(aws cloudformation describe-stacks \
    --stack-name "$ROLES_STACK" \
    --query 'Stacks[0].Outputs[?OutputKey==`SageMakerExecutionRoleArn`].OutputValue' \
    --output text --region "$REGION")

# ── Fetch MLOps bucket name from storage stack ────────────────────────────────
MLOPS_BUCKET=$(aws cloudformation describe-stacks \
    --stack-name "$STORAGE_STACK" \
    --query 'Stacks[0].Outputs[?OutputKey==`KycMlOpsBucketName`].OutputValue' \
    --output text --region "$REGION")

echo "  SM_ROLE_ARN  : $SM_ROLE_ARN"
echo "  MLOPS_BUCKET : $MLOPS_BUCKET"
echo ""

# ── Deploy the stack ──────────────────────────────────────────────────────────
echo "── Deploying $PIPELINE_STACK ──"
aws cloudformation deploy \
    --template-file "$REPO_ROOT/templates/mlops-cd-pipeline-stack.yaml" \
    --stack-name "$PIPELINE_STACK" \
    --capabilities CAPABILITY_NAMED_IAM \
    --parameter-overrides \
        RolesStackName="$ROLES_STACK" \
        StorageStackName="$STORAGE_STACK" \
        GitHubConnectionArn="$GITHUB_CONNECTION_ARN" \
        GitHubRepo="$GITHUB_REPO" \
        GitHubBranch="$GITHUB_BRANCH" \
        SageMakerExecutionRoleArn="$SM_ROLE_ARN" \
        KycMlOpsBucketName="$MLOPS_BUCKET" \
    --region "$REGION"

echo "✓ $PIPELINE_STACK deployed"
echo ""
echo "=== MLOps CD pipeline deployed successfully ==="
echo "  Approve a model version in the SageMaker Model Registry ('kyc-risk-scorer' group)"
echo "  to trigger the pipeline and verify end-to-end deployment."
