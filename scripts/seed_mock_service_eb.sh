#!/usr/bin/env bash
# Reseed the mock service deployed on Elastic Beanstalk with default test cases (BRP + PEP).
# Resolves the EB environment URL from CloudFormation, then runs the seed script against it.
#
# Run from repo root. Requires AWS CLI configured and the mock-service stack already deployed.
#
# Usage (from repo root):
#   ./scripts/seed_mock_service_eb.sh
#   MOCK_SERVICE_URL=https://my-env.elasticbeanstalk.com ./scripts/seed_mock_service_eb.sh  # override URL
#
# Env:
#   STACK_NAME - Beanstalk CloudFormation stack name (default: kyc-mock-service-eb)
#   MOCK_SERVICE_URL - Override: base URL of mock service (no trailing slash). If set, skips AWS lookup.
#   AWS_REGION / AWS_DEFAULT_REGION - Region (default: us-east-1)

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
MOCK_SERVICE_DIR="$REPO_ROOT/mock-service"

STACK_NAME="${STACK_NAME:-kyc-mock-service-eb}"
REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-1}}"

if [ -n "$MOCK_SERVICE_URL" ]; then
  BASE_URL="${MOCK_SERVICE_URL%/}"
  echo "=== Using MOCK_SERVICE_URL: $BASE_URL ==="
else
  if ! aws cloudformation describe-stacks --stack-name "$STACK_NAME" --region "$REGION" &>/dev/null; then
    echo "Error: Stack '$STACK_NAME' not found in region $REGION. Deploy first with ./scripts/deploy_mock_service.sh" >&2
    exit 1
  fi
  MOCK_ENV_NAME=$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" --region "$REGION" \
    --query "Stacks[0].Outputs[?OutputKey=='EnvironmentName'].OutputValue" --output text 2>/dev/null || true)
  if [ -z "$MOCK_ENV_NAME" ] || [ "$MOCK_ENV_NAME" = "None" ]; then
    echo "Error: Could not get EnvironmentName from stack $STACK_NAME" >&2
    exit 1
  fi
  MOCK_CNAME=$(aws elasticbeanstalk describe-environments --environment-names "$MOCK_ENV_NAME" --region "$REGION" \
    --query 'Environments[0].CNAME' --output text 2>/dev/null || true)
  if [ -z "$MOCK_CNAME" ] || [ "$MOCK_CNAME" = "None" ]; then
    echo "Error: Could not get CNAME for environment $MOCK_ENV_NAME" >&2
    exit 1
  fi
  BASE_URL="http://$MOCK_CNAME"
  echo "=== Mock-service (EB): $BASE_URL ==="
fi

echo "Seeding BRP + PEP test cases..."
(cd "$MOCK_SERVICE_DIR" && MOCK_SERVICE_URL="$BASE_URL" npm run seed)

echo "=== Done ==="
