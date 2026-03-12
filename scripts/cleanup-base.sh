#!/bin/bash

set -e

BASE_NAME="${1:-kyc-agent}"
REGION="${2:-us-east-1}"

VPC_STACK="${BASE_NAME}-vpc"
STORAGE_STACK="${BASE_NAME}-storage"
ROLES_STACK="${BASE_NAME}-roles"
MAIN_STACK="${BASE_NAME}-main"

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
echo "Cleaning up BASE stacks"
echo "=========================================="
echo "Region: $REGION"
echo "Base:   $BASE_NAME"
echo "Base stacks:"
echo "  Main:    $MAIN_STACK"
echo "  Roles:   $ROLES_STACK"
echo "  Storage: $STORAGE_STACK"
echo "  VPC:     $VPC_STACK"
echo "=========================================="

echo ""
echo "[1/2] Emptying base S3 bucket (if present)..."
SOURCE_BUCKET=$(get_stack_output "$STORAGE_STACK" "SourceBucketName")
empty_bucket "$SOURCE_BUCKET"
echo "✓ Base bucket emptied"

echo ""
echo "[2/2] Deleting base stacks..."
# Order matters: main -> roles -> storage -> vpc
delete_stack "$MAIN_STACK"
delete_stack "$ROLES_STACK"
delete_stack "$STORAGE_STACK"
delete_stack "$VPC_STACK"

echo ""
echo "✓ Base cleanup complete"
