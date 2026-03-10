#!/bin/bash

set -e

BASE_NAME="${1:-kyc-agent}"
REGION="${2:-us-east-1}"

VPC_STACK="${BASE_NAME}-vpc"
STORAGE_STACK="${BASE_NAME}-storage"
ROLES_STACK="${BASE_NAME}-roles"
MAIN_STACK="${BASE_NAME}-main"

AGENT_STACK="${BASE_NAME}-agentcore-runtime"
LAMBDA_STACK="${BASE_NAME}-lambda"
API_STACK="${BASE_NAME}-api"
UI_STACK="${BASE_NAME}-ui"

stack_exists() {
    aws cloudformation describe-stacks --stack-name "$1" --region "$REGION" >/dev/null 2>&1
}

get_stack_output() {
    local stack="$1"
    local key="$2"
    aws cloudformation describe-stacks \
        --stack-name "$stack" \
        --query "Stacks[0].Outputs[?OutputKey==\`$key\`].OutputValue | [0]" \
        --output text \
        --region "$REGION" 2>/dev/null || true
}

empty_bucket() {
    local bucket="$1"
    if [ -z "$bucket" ] || [ "$bucket" = "None" ]; then
        return 0
    fi

    echo "Emptying bucket: $bucket"

    # Delete current objects
    aws s3 rm "s3://$bucket" --recursive --region "$REGION" >/dev/null 2>&1 || true

    # If bucket is versioned, also delete versions and delete markers
    while read -r key version_id; do
        [ -n "$key" ] || continue
        [ -n "$version_id" ] || continue
        aws s3api delete-object --bucket "$bucket" --key "$key" --version-id "$version_id" --region "$REGION" >/dev/null 2>&1 || true
    done < <(aws s3api list-object-versions --bucket "$bucket" --query 'Versions[].{Key:Key,VersionId:VersionId}' --output text --region "$REGION" 2>/dev/null || true)

    while read -r key version_id; do
        [ -n "$key" ] || continue
        [ -n "$version_id" ] || continue
        aws s3api delete-object --bucket "$bucket" --key "$key" --version-id "$version_id" --region "$REGION" >/dev/null 2>&1 || true
    done < <(aws s3api list-object-versions --bucket "$bucket" --query 'DeleteMarkers[].{Key:Key,VersionId:VersionId}' --output text --region "$REGION" 2>/dev/null || true)
}

delete_stack() {
    local stack="$1"
    if ! stack_exists "$stack"; then
        echo "- Skipping (not found): $stack"
        return 0
    fi
    echo "Deleting stack: $stack"
    aws cloudformation delete-stack --stack-name "$stack" --region "$REGION"
    aws cloudformation wait stack-delete-complete --stack-name "$stack" --region "$REGION"
    echo "✓ Deleted: $stack"
}

echo "=========================================="
echo "Cleaning up KYC stacks"
echo "=========================================="
echo "Region: $REGION"
echo "Base:   $BASE_NAME"
echo ""
echo "Runtime stacks:"
echo "  UI:     $UI_STACK"
echo "  API:    $API_STACK"
echo "  Lambda: $LAMBDA_STACK"
echo "  Agent:  $AGENT_STACK"
echo "Base stacks:"
echo "  Main:    $MAIN_STACK"
echo "  Roles:   $ROLES_STACK"
echo "  Storage: $STORAGE_STACK"
echo "  VPC:     $VPC_STACK"
echo "=========================================="

echo ""
echo "[1/3] Emptying S3 buckets (if present)..."
UI_BUCKET=$(get_stack_output "$UI_STACK" "StaticBucketName")
STORAGE_BUCKET=$(get_stack_output "$STORAGE_STACK" "SourceBucketName")
empty_bucket "$UI_BUCKET"
empty_bucket "$STORAGE_BUCKET"
echo "✓ Buckets emptied"

echo ""
echo "[2/3] Deleting runtime stacks..."
delete_stack "$UI_STACK"
delete_stack "$API_STACK"
delete_stack "$LAMBDA_STACK"
delete_stack "$AGENT_STACK"

echo ""
echo "[3/3] Deleting base stacks..."
delete_stack "$MAIN_STACK"
delete_stack "$ROLES_STACK"
delete_stack "$STORAGE_STACK"
delete_stack "$VPC_STACK"

echo ""
echo "✓ Cleanup complete"
