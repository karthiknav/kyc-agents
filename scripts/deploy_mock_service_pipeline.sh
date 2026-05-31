#!/usr/bin/env bash
# Deploy mock-service CI/CD pipeline (CodePipeline + CodeBuild) via CloudFormation.
# Run from repo root.
#
# Required env:
#   GITHUB_CONNECTION_ARN  - CodeConnections/CodeStar connection ARN to GitHub
#   GITHUB_REPO            - owner/repo (e.g. karthiknav/kyc-agents)
# Optional env:
#   GITHUB_BRANCH          - default: improvements
#   PIPELINE_STACK_NAME    - default: kyc-agent-mock-service-pipeline
#   MOCK_SERVICE_STACK_NAME- default: kyc-mock-service-eb
#   KYC_RESULTS_BUCKET_NAME- if unset, derived from STORAGE_STACK_NAME's SourceBucketName output
#   STORAGE_STACK_NAME     - default: kyc-agent-storage
#   AWS_REGION/AWS_DEFAULT_REGION - default: us-east-1

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-1}}"

GITHUB_BRANCH="${GITHUB_BRANCH:-improvements}"
PIPELINE_STACK_NAME="${PIPELINE_STACK_NAME:-kyc-agent-mock-service-pipeline}"
MOCK_SERVICE_STACK_NAME="${MOCK_SERVICE_STACK_NAME:-kyc-mock-service-eb}"
STORAGE_STACK_NAME="${STORAGE_STACK_NAME:-kyc-agent-storage}"

: "${GITHUB_CONNECTION_ARN:?Set GITHUB_CONNECTION_ARN}"
: "${GITHUB_REPO:?Set GITHUB_REPO}"

if [ -z "${KYC_RESULTS_BUCKET_NAME:-}" ]; then
  KYC_RESULTS_BUCKET_NAME=$(aws cloudformation describe-stacks \
    --stack-name "$STORAGE_STACK_NAME" \
    --query 'Stacks[0].Outputs[?OutputKey==`SourceBucketName`].OutputValue' \
    --output text --region "$REGION")
fi

if [ -z "$KYC_RESULTS_BUCKET_NAME" ] || [ "$KYC_RESULTS_BUCKET_NAME" = "None" ]; then
  echo "Error: Could not determine KYC_RESULTS_BUCKET_NAME" >&2
  exit 1
fi

aws cloudformation deploy \
  --template-file "$REPO_ROOT/templates/mock-service-pipeline-stack.yaml" \
  --stack-name "$PIPELINE_STACK_NAME" \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
      GitHubConnectionArn="$GITHUB_CONNECTION_ARN" \
      GitHubRepo="$GITHUB_REPO" \
      GitHubBranch="$GITHUB_BRANCH" \
      MockServiceStackName="$MOCK_SERVICE_STACK_NAME" \
      KycResultsBucketName="$KYC_RESULTS_BUCKET_NAME" \
  --region "$REGION"

echo "✓ Deployed pipeline stack: $PIPELINE_STACK_NAME"
