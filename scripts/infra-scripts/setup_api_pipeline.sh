#!/usr/bin/env bash
# Deploys the API CI/CD pipeline stack (Phase 2, Step 5b).
# Packages backend/ as a Lambda zip and deploys api-stack.
# Triggers automatically on changes to backend/** or templates/api-stack.yaml.
#
# No inputs required — all values are hardcoded or resolved from stack outputs.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

REGION="us-east-1"

STORAGE_STACK="kyc-agent-storage"
MAIN_STACK="kyc-agent-main"
API_PIPELINE_STACK="kyc-agent-api-pipeline"
ROLES_STACK="kyc-agent-roles"
API_STACK="kyc-agent-api"
VPC_STACK="kyc-agent-vpc"

GITHUB_CONNECTION_ARN="arn:aws:codeconnections:us-east-1:360946915124:connection/24a1bf19-4ba9-42ee-ad2c-f37799f02447"
GITHUB_REPO="karthiknav/kyc-agents"
GITHUB_BRANCH="improvements"

echo "=== API pipeline deployment ==="
echo "  API_PIPELINE_STACK : $API_PIPELINE_STACK"
echo "  API_STACK          : $API_STACK"
echo "  GITHUB_REPO        : $GITHUB_REPO"
echo "  GITHUB_BRANCH      : $GITHUB_BRANCH"
echo "  REGION             : $REGION"
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

KYC_QUEUE_NAME=$(aws cloudformation describe-stacks \
    --stack-name "$MAIN_STACK" \
    --query 'Stacks[0].Outputs[?OutputKey==`KycInitiatedQueueName`].OutputValue' \
    --output text --region "$REGION")

echo "  KYC_RESULTS_BUCKET : $KYC_RESULTS_BUCKET"
echo "  KYC_CASES_TABLE    : $KYC_CASES_TABLE"
echo "  KYC_QUEUE_NAME     : $KYC_QUEUE_NAME"
echo ""

aws cloudformation deploy \
    --template-file "$REPO_ROOT/templates/api-pipeline-stack.yaml" \
    --stack-name "$API_PIPELINE_STACK" \
    --parameter-overrides \
        GitHubConnectionArn="$GITHUB_CONNECTION_ARN" \
        GitHubRepo="$GITHUB_REPO" \
        GitHubBranch="$GITHUB_BRANCH" \
        RolesStackName="$ROLES_STACK" \
        ApiStackName="$API_STACK" \
        KycResultsBucketName="$KYC_RESULTS_BUCKET" \
        KycCasesTableName="$KYC_CASES_TABLE" \
        KycInitiatedQueueName="$KYC_QUEUE_NAME" \
        VpcStackName="$VPC_STACK" \
    --region "$REGION"

echo "✓ $API_PIPELINE_STACK deployed"
echo ""
echo "=== API pipeline deployed successfully ==="
echo "  The pipeline will build and deploy $API_STACK on the next push to $GITHUB_BRANCH."
