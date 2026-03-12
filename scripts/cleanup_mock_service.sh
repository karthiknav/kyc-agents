#!/usr/bin/env bash
# Clean up mock-service: empty S3 bucket, delete EB stack, then delete bucket stack.
# Run from repo root. Uses the same stack names as deploy_mock_service.sh.
#
# Usage (from repo root):
#   ./scripts/cleanup_mock_service.sh
#
# Env:
#   STACK_NAME         - EB CloudFormation stack name (default: kyc-mock-service-eb)
#   MOCK_SERVICE_BUCKET_STACK - Bucket stack name (default: kyc-mock-service-artifacts)
#   AWS_REGION / AWS_DEFAULT_REGION - Region (default: us-east-1)

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

STACK_NAME="${STACK_NAME:-kyc-mock-service-eb}"
MOCK_SERVICE_BUCKET_STACK="${MOCK_SERVICE_BUCKET_STACK:-kyc-mock-service-artifacts}"
REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-1}}"

stack_exists() {
  aws cloudformation describe-stacks --stack-name "$1" --region "$REGION" &>/dev/null
}

get_stack_output() {
  aws cloudformation describe-stacks \
    --stack-name "$1" \
    --query "Stacks[0].Outputs[?OutputKey==\`$2\`].OutputValue | [0]" \
    --output text \
    --region "$REGION" 2>/dev/null || true
}

empty_bucket() {
  local bucket="$1"
  if [ -z "$bucket" ] || [ "$bucket" = "None" ]; then
    return 0
  fi
  echo "Emptying bucket: $bucket"
  aws s3 rm "s3://$bucket" --recursive --region "$REGION" 2>/dev/null || true
  while read -r key version_id; do
    [ -n "$key" ] && [ -n "$version_id" ] || continue
    aws s3api delete-object --bucket "$bucket" --key "$key" --version-id "$version_id" --region "$REGION" 2>/dev/null || true
  done < <(aws s3api list-object-versions --bucket "$bucket" --query 'Versions[].{Key:Key,VersionId:VersionId}' --output text --region "$REGION" 2>/dev/null || true)
  while read -r key version_id; do
    [ -n "$key" ] && [ -n "$version_id" ] || continue
    aws s3api delete-object --bucket "$bucket" --key "$key" --version-id "$version_id" --region "$REGION" 2>/dev/null || true
  done < <(aws s3api list-object-versions --bucket "$bucket" --query 'DeleteMarkers[].{Key:Key,VersionId:VersionId}' --output text --region "$REGION" 2>/dev/null || true)
  echo "✓ Bucket emptied"
}

echo "=========================================="
echo "Cleanup: mock-service (S3 + Elastic Beanstalk)"
echo "=========================================="
echo "Bucket stack: $MOCK_SERVICE_BUCKET_STACK"
echo "EB stack:     $STACK_NAME"
echo "Region:       $REGION"
echo "=========================================="

# Get bucket from bucket stack (same source deploy_mock_service.sh uses)
BUCKET=""
if stack_exists "$MOCK_SERVICE_BUCKET_STACK"; then
  BUCKET=$(get_stack_output "$MOCK_SERVICE_BUCKET_STACK" "BucketName")
fi

if [ -n "$BUCKET" ] && [ "$BUCKET" != "None" ]; then
  echo ""
  echo "[1/3] Emptying S3 bucket..."
  empty_bucket "$BUCKET"
else
  echo ""
  echo "[1/3] No bucket stack or BucketName output; skipping bucket empty."
fi

echo ""
echo "[2/3] Deleting EB stack: $STACK_NAME"
if stack_exists "$STACK_NAME"; then
  aws cloudformation delete-stack --stack-name "$STACK_NAME" --region "$REGION"
  echo "Waiting for stack delete (this can take several minutes for Elastic Beanstalk)..."
  aws cloudformation wait stack-delete-complete --stack-name "$STACK_NAME" --region "$REGION"
  echo "✓ Deleted: $STACK_NAME"
else
  echo "Stack $STACK_NAME does not exist; skipping."
fi

echo ""
echo "[3/3] Deleting bucket stack: $MOCK_SERVICE_BUCKET_STACK"
if stack_exists "$MOCK_SERVICE_BUCKET_STACK"; then
  aws cloudformation delete-stack --stack-name "$MOCK_SERVICE_BUCKET_STACK" --region "$REGION"
  aws cloudformation wait stack-delete-complete --stack-name "$MOCK_SERVICE_BUCKET_STACK" --region "$REGION"
  echo "✓ Deleted: $MOCK_SERVICE_BUCKET_STACK"
else
  echo "Stack $MOCK_SERVICE_BUCKET_STACK does not exist; skipping."
fi

echo ""
echo "=== Mock-service cleanup complete ==="
