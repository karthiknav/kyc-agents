#!/bin/bash

set -e

BASE_NAME="${1:-basic-agent-demo}"
REGION="${2:-us-east-1}"
S3_STACK="${BASE_NAME}-s3"
ROLES_STACK="${BASE_NAME}-roles"
MAIN_STACK="${BASE_NAME}-main"

echo "Deleting stacks..."
echo "Main Stack: $MAIN_STACK"
echo "Roles Stack: $ROLES_STACK"
echo "S3 Stack: $S3_STACK"

# Delete main stack first
echo ""
echo "[1/3] Deleting main stack..."
aws cloudformation delete-stack --stack-name "$MAIN_STACK" --region "$REGION"
aws cloudformation wait stack-delete-complete --stack-name "$MAIN_STACK" --region "$REGION"
echo "✓ Main stack deleted"

# Delete roles stack
echo ""
echo "[2/3] Deleting roles stack..."
aws cloudformation delete-stack --stack-name "$ROLES_STACK" --region "$REGION"
aws cloudformation wait stack-delete-complete --stack-name "$ROLES_STACK" --region "$REGION"
echo "✓ Roles stack deleted"

# Empty and delete S3 bucket, then delete stack
echo ""
echo "[3/3] Deleting S3 stack..."
SOURCE_BUCKET=$(aws cloudformation describe-stacks \
    --stack-name "$S3_STACK" \
    --query 'Stacks[0].Outputs[?OutputKey==`SourceBucketName`].OutputValue' \
    --output text \
    --region "$REGION" 2>/dev/null || echo "")

if [ -n "$SOURCE_BUCKET" ]; then
    echo "Emptying bucket: $SOURCE_BUCKET"
    aws s3 rm "s3://$SOURCE_BUCKET" --recursive --region "$REGION" 2>/dev/null || true
fi

aws cloudformation delete-stack --stack-name "$S3_STACK" --region "$REGION"
aws cloudformation wait stack-delete-complete --stack-name "$S3_STACK" --region "$REGION"
echo "✓ S3 stack deleted"

echo ""
echo "✓ All stacks deleted successfully"
