#!/usr/bin/env bash
# Deploys the UI infra and CI/CD pipeline stacks.
# 1. ui-stack.yaml   — S3 bucket + CloudFront distribution (idempotent)
# 2. ui-pipeline-stack.yaml — CodePipeline that builds and syncs the React frontend on every push.
#
# No inputs required — all values are hardcoded or resolved from stack outputs.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

REGION="us-east-1"

ROLES_STACK="kyc-agent-roles"
UI_STACK="kyc-agent-ui"
API_STACK="kyc-agent-api"
AGENT_PIPELINE_STACK="kyc-agent-pipeline"
UI_PIPELINE_STACK="kyc-agent-ui-pipeline"

GITHUB_CONNECTION_ARN="arn:aws:codeconnections:us-east-1:360946915124:connection/24a1bf19-4ba9-42ee-ad2c-f37799f02447"
GITHUB_REPO="karthiknav/kyc-agents"
GITHUB_BRANCH="improvements"

echo "=== UI pipeline deployment ==="
echo "  UI_PIPELINE_STACK    : $UI_PIPELINE_STACK"
echo "  UI_STACK             : $UI_STACK"
echo "  API_STACK            : $API_STACK"
echo "  AGENT_PIPELINE_STACK : $AGENT_PIPELINE_STACK"
echo "  GITHUB_REPO          : $GITHUB_REPO"
echo "  GITHUB_BRANCH        : $GITHUB_BRANCH"
echo "  REGION               : $REGION"
echo ""

# ── Deploy ui-stack (S3 bucket + CloudFront) ─────────────────────────────────
echo "── Deploying $UI_STACK ──"
aws cloudformation deploy \
    --template-file "$REPO_ROOT/templates/ui-stack.yaml" \
    --stack-name "$UI_STACK" \
    --capabilities CAPABILITY_NAMED_IAM \
    --region "$REGION" \
    --no-fail-on-empty-changeset

echo "✓ $UI_STACK deployed"

# ── Verify api-stack is deployed (needed for VITE_API_BASE_URL at build time) ──
echo "── Checking api-stack status ──"
API_STATUS=$(aws cloudformation describe-stacks \
    --stack-name "$API_STACK" \
    --query 'Stacks[0].StackStatus' \
    --output text --region "$REGION")

echo "  $API_STACK status: $API_STATUS"

if [[ "$API_STATUS" != "CREATE_COMPLETE" && "$API_STATUS" != "UPDATE_COMPLETE" ]]; then
    echo "ERROR: $API_STACK is not in a stable state ($API_STATUS)."
    echo "  Deploy the API stack before running this script."
    exit 1
fi

echo ""

# ── Deploy ui-pipeline-stack ──────────────────────────────────────────────────
echo "── Deploying $UI_PIPELINE_STACK ──"
aws cloudformation deploy \
    --template-file "$REPO_ROOT/templates/ui-pipeline-stack.yaml" \
    --stack-name "$UI_PIPELINE_STACK" \
    --parameter-overrides \
        GitHubConnectionArn="$GITHUB_CONNECTION_ARN" \
        GitHubRepo="$GITHUB_REPO" \
        GitHubBranch="$GITHUB_BRANCH" \
        RolesStackName="$ROLES_STACK" \
        UiStackName="$UI_STACK" \
        ApiStackName="$API_STACK" \
        AgentPipelineStackName="$AGENT_PIPELINE_STACK" \
    --capabilities CAPABILITY_NAMED_IAM \
    --region "$REGION"

echo "✓ $UI_PIPELINE_STACK deployed"
echo ""
echo "=== UI pipeline deployed successfully ==="
echo "  The pipeline will build and deploy the frontend on the next push to $GITHUB_BRANCH."
