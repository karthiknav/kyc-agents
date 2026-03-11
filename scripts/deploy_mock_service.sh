#!/usr/bin/env bash
# Deploy mock-service to AWS via CloudFormation (Elastic Beanstalk).
# Run from repo root. Deploy mock-service first so the agent can use BRP_API_URL.
#
# 1. By default creates an S3 bucket (stack: kyc-mock-service-artifacts) for deploy.zip
# 2. Packages the app (mock-service/deploy.zip) via package_mock_service_for_eb.sh
# 3. Uploads deploy.zip to S3 and creates/updates the Beanstalk stack
#
# Usage (from repo root):
#   ./scripts/deploy_mock_service.sh
#   S3_BUCKET=my-bucket ./scripts/deploy_mock_service.sh   # use existing bucket instead
#
# Env:
#   S3_BUCKET          - Use this bucket; if unset, deploy and use kyc-mock-service-artifacts stack
#   S3_KEY             - S3 key for deploy.zip (default: mock-service/deploy.zip)
#   STACK_NAME         - Beanstalk CFN stack name (default: kyc-mock-service-eb)
#   MOCK_SERVICE_BUCKET_STACK - Bucket stack name when creating default bucket (default: kyc-mock-service-artifacts)
#   DEPLOY_SKIP_PACKAGE - Set to 1 to skip packaging (use existing mock-service/deploy.zip)
#   AWS_REGION / AWS_DEFAULT_REGION - Region for EB and CloudFormation (default: us-east-1)

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
MOCK_SERVICE_DIR="$REPO_ROOT/mock-service"
DEPLOY_ZIP="$MOCK_SERVICE_DIR/deploy.zip"
# Use relative paths for AWS CLI file:// (avoids Windows/Git Bash path issues)
BUCKET_TEMPLATE_FILE="templates/mock-service/s3-artifacts-bucket.yaml"
EB_TEMPLATE_FILE="templates/mock-service/elastic-beanstalk.yaml"

S3_KEY="${S3_KEY:-mock-service/deploy.zip}"
STACK_NAME="${STACK_NAME:-kyc-mock-service-eb}"
MOCK_SERVICE_BUCKET_STACK="${MOCK_SERVICE_BUCKET_STACK:-kyc-mock-service-artifacts}"
REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-1}}"

# --- 0. Ensure S3 bucket exists (create default bucket stack if S3_BUCKET not set) ---
if [ -z "$S3_BUCKET" ]; then
  if ! aws cloudformation describe-stacks --stack-name "$MOCK_SERVICE_BUCKET_STACK" --region "$REGION" &>/dev/null; then
    echo "=== Creating S3 bucket stack: $MOCK_SERVICE_BUCKET_STACK ==="
    if [ ! -f "$REPO_ROOT/$BUCKET_TEMPLATE_FILE" ]; then
      echo "Error: Template not found: $REPO_ROOT/$BUCKET_TEMPLATE_FILE" >&2
      exit 1
    fi
    ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text 2>/dev/null || echo "local")
    DEFAULT_BUCKET_NAME="kyc-mock-service-artifacts-${ACCOUNT_ID}"
    (cd "$REPO_ROOT" && aws cloudformation create-stack --stack-name "$MOCK_SERVICE_BUCKET_STACK" \
      --template-body "file://$BUCKET_TEMPLATE_FILE" \
      --parameters ParameterKey=BucketName,ParameterValue="$DEFAULT_BUCKET_NAME" \
      --region "$REGION")
    echo "Waiting for bucket stack to be ready..."
    aws cloudformation wait stack-create-complete --stack-name "$MOCK_SERVICE_BUCKET_STACK" --region "$REGION"
  fi
  S3_BUCKET=$(aws cloudformation describe-stacks --stack-name "$MOCK_SERVICE_BUCKET_STACK" \
    --query "Stacks[0].Outputs[?OutputKey=='BucketName'].OutputValue" --output text 2>/dev/null || true)
  if [ -z "$S3_BUCKET" ] || [ "$S3_BUCKET" = "None" ]; then
    echo "Error: Could not get bucket name from stack $MOCK_SERVICE_BUCKET_STACK" >&2
    exit 1
  fi
  echo "=== Using bucket: $S3_BUCKET ==="
fi

# --- 1. Package ---
if [ "${DEPLOY_SKIP_PACKAGE}" != "1" ]; then
  echo "=== Packaging mock-service ==="
  bash "$SCRIPT_DIR/package_mock_service_for_eb.sh"
else
  echo "=== Skipping package (DEPLOY_SKIP_PACKAGE=1) ==="
  if [ ! -f "$DEPLOY_ZIP" ]; then
    echo "Error: $DEPLOY_ZIP not found. Run without DEPLOY_SKIP_PACKAGE or create it first." >&2
    exit 1
  fi
fi

# --- 2. Upload to S3 ---
echo "=== Uploading deploy.zip to s3://$S3_BUCKET/$S3_KEY ==="
aws s3 cp "$DEPLOY_ZIP" "s3://$S3_BUCKET/$S3_KEY"

# --- 3. CloudFormation create/update (Beanstalk) ---
if [ -n "$STACK_NAME" ]; then
  if [ ! -f "$REPO_ROOT/$EB_TEMPLATE_FILE" ]; then
    echo "Error: Template not found: $REPO_ROOT/$EB_TEMPLATE_FILE" >&2
    exit 1
  fi
  if aws cloudformation describe-stacks --stack-name "$STACK_NAME" --region "$REGION" &>/dev/null; then
    echo "=== Updating CloudFormation stack: $STACK_NAME ==="
    if (cd "$REPO_ROOT" && aws cloudformation update-stack --stack-name "$STACK_NAME" \
      --template-body "file://$EB_TEMPLATE_FILE" \
      --capabilities CAPABILITY_NAMED_IAM \
      --region "$REGION" \
      --parameters \
        ParameterKey=S3Bucket,UsePreviousValue=true \
        ParameterKey=S3Key,ParameterValue="$S3_KEY" \
        ParameterKey=ApplicationName,UsePreviousValue=true \
        ParameterKey=EnvironmentName,UsePreviousValue=true \
        ParameterKey=InstanceType,UsePreviousValue=true \
        ParameterKey=SeedDefaultTestCases,UsePreviousValue=true); then
      echo "Waiting for stack update to complete (this can take several minutes for Beanstalk)..."
      aws cloudformation wait stack-update-complete --stack-name "$STACK_NAME" --region "$REGION"
      echo "✓ Stack update complete."
    else
      echo "No stack update (no changes or update failed)."
    fi
  else
    echo "=== Creating CloudFormation stack: $STACK_NAME ==="
    (cd "$REPO_ROOT" && aws cloudformation create-stack --stack-name "$STACK_NAME" \
      --template-body "file://$EB_TEMPLATE_FILE" \
      --capabilities CAPABILITY_NAMED_IAM \
      --region "$REGION" \
      --parameters \
        ParameterKey=S3Bucket,ParameterValue="$S3_BUCKET" \
        ParameterKey=S3Key,ParameterValue="$S3_KEY")
    echo "Waiting for stack creation to complete (this can take several minutes for Beanstalk)..."
    aws cloudformation wait stack-create-complete --stack-name "$STACK_NAME" --region "$REGION"
    echo "✓ Stack creation complete."
  fi
  # Use EB CNAME (domain) instead of instance IP for stable, bookmarkable URL
  echo ""
  MOCK_ENV_NAME=$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" --region "$REGION" \
    --query "Stacks[0].Outputs[?OutputKey=='EnvironmentName'].OutputValue" --output text 2>/dev/null || true)
  if [ -n "$MOCK_ENV_NAME" ] && [ "$MOCK_ENV_NAME" != "None" ]; then
    MOCK_CNAME=$(aws elasticbeanstalk describe-environments --environment-names "$MOCK_ENV_NAME" --region "$REGION" \
      --query 'Environments[0].CNAME' --output text 2>/dev/null || true)
    if [ -n "$MOCK_CNAME" ] && [ "$MOCK_CNAME" != "None" ]; then
      echo "Mock-service base URL (domain): http://$MOCK_CNAME"
      echo "BRP_API_URL for agent:          http://$MOCK_CNAME/api/v1/brp/personen/document-lookup"
    else
      echo "Mock-service URL (from stack):"
      aws cloudformation describe-stacks --stack-name "$STACK_NAME" --region "$REGION" \
        --query "Stacks[0].Outputs[?OutputKey=='EnvironmentURL'].OutputValue" --output text 2>/dev/null || true
    fi
  else
    echo "Mock-service URL (from stack):"
    aws cloudformation describe-stacks --stack-name "$STACK_NAME" --region "$REGION" \
      --query "Stacks[0].Outputs[?OutputKey=='EnvironmentURL'].OutputValue" --output text 2>/dev/null || true
  fi
fi

echo "=== Done ==="
