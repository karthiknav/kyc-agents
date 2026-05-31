#!/usr/bin/env bash
# Deploy ONLY the mock-service Elastic Beanstalk CloudFormation stack.
# This script does NOT package/upload the app bundle and does NOT create the artifacts bucket.
# Ensure the source bundle already exists in S3.
#
# Required env:
#   S3_BUCKET          - Bucket containing the EB source bundle
# Optional env:
#   S3_KEY             - S3 key for the EB source bundle
#                        Default matches scripts/deploy_mock_service.sh:
#                        mock-service/deploy-$(date +%Y%m%d%H%M%S).zip
#   STACK_NAME         - CloudFormation stack name (default: kyc-mock-service-eb)
#   APPLICATION_NAME   - EB application name (default: kyc-mock-service)
#   ENVIRONMENT_NAME   - EB environment name (default: mock-service-env)
#   SOLUTION_STACK_NAME- EB platform (default from template)
#   INSTANCE_TYPE      - EC2 instance type (default: t3.micro)
#   SEED_DEFAULT_TEST_CASES - "1" or "0" (default: "1")
#   AWS_REGION / AWS_DEFAULT_REGION - Region (default: us-east-1)

set -euo pipefail

usage() {
	cat <<'USAGE' >&2
Usage:
  S3_BUCKET=... [S3_KEY=...] [STACK_NAME=...] ./scripts/infra-scripts/deploy_mock_service.sh

Required env:
  S3_BUCKET

Optional env:
  S3_KEY (default: mock-service/deploy-<timestamp>.zip)
  STACK_NAME (default: kyc-mock-service-eb)
  APPLICATION_NAME (default: kyc-mock-service)
  ENVIRONMENT_NAME (default: mock-service-env)
  SOLUTION_STACK_NAME (default: 64bit Amazon Linux 2023 v6.9.0 running Node.js 20)
  INSTANCE_TYPE (default: t3.micro)
  SEED_DEFAULT_TEST_CASES (default: 1)
  AWS_REGION / AWS_DEFAULT_REGION (default: us-east-1)
USAGE
}

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
BASE_NAME="${1:-kyc-agent}"
TEMPLATE_FILE="$REPO_ROOT/templates/mock-service/elastic-beanstalk.yaml"
MOCK_SERVICE_DIR="$REPO_ROOT/mock-service"

S3_BUCKET="${S3_BUCKET:-}"

# If S3_BUCKET is not set, try to get it from the ArtifactsBucketName output of the base storage stack
if [ -z "$S3_BUCKET" ]; then
	BASE_STACK_NAME="${BASE_STACK_NAME:-kyc-base-storage}"
	S3_BUCKET=$(aws cloudformation describe-stacks \
		--stack-name "$BASE_STACK_NAME" \
		--region "$REGION" \
		--query 'Stacks[0].Outputs[?OutputKey==`ArtifactsBucketName`].OutputValue' \
		--output text)
fi
S3_KEY="${S3_KEY:-mock-service/deploy-$(date +%Y%m%d%H%M%S).zip}"
STACK_NAME="${STACK_NAME:-kyc-mock-service-eb}"
REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-1}}"

APPLICATION_NAME="${APPLICATION_NAME:-kyc-mock-service}"
ENVIRONMENT_NAME="${ENVIRONMENT_NAME:-mock-service-env}"
SOLUTION_STACK_NAME="${SOLUTION_STACK_NAME:-64bit Amazon Linux 2023 v6.9.0 running Node.js 20}"
INSTANCE_TYPE="${INSTANCE_TYPE:-t3.micro}"
SEED_DEFAULT_TEST_CASES="${SEED_DEFAULT_TEST_CASES:-1}"

if [ -z "$S3_BUCKET" ]; then
	echo "Error: S3_BUCKET is required and could not be determined from the base storage stack." >&2
	usage
	exit 1
fi

if [ ! -f "$TEMPLATE_FILE" ]; then
	echo "Error: Template not found: $TEMPLATE_FILE" >&2
	exit 1
fi

aws cloudformation deploy \
	--template-file "$TEMPLATE_FILE" \
	--stack-name "$STACK_NAME" \
	--capabilities CAPABILITY_NAMED_IAM \
	--parameter-overrides \
		ApplicationName="$APPLICATION_NAME" \
		EnvironmentName="$ENVIRONMENT_NAME" \
		SolutionStackName="$SOLUTION_STACK_NAME" \
		S3Bucket="$S3_BUCKET" \
		S3Key="$S3_KEY" \
		InstanceType="$INSTANCE_TYPE" \
		SeedDefaultTestCases="$SEED_DEFAULT_TEST_CASES" \
	--region "$REGION"

echo "✓ Deployed mock-service stack: $STACK_NAME"
