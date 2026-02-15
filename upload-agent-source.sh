#!/bin/bash

# Upload agent source to S3 (mimics CDK BucketDeployment)
# Usage: ./upload-agent-source.sh <stack-name> <region>

set -e

STACK_NAME="${1:-basic-agent-demo-main}"
REGION="${2:-us-east-1}"
SOURCE_BUCKET="${STACK_NAME}-agent-source"

echo "Packaging and uploading agent source..."

# Create temporary directory
TEMP_DIR=$(mktemp -d)
trap "rm -rf $TEMP_DIR" EXIT

# Copy agent files excluding unwanted directories
rsync -av --exclude='venv/' \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    --exclude='.git/' \
    --exclude='node_modules/' \
    --exclude='.DS_Store' \
    --exclude='*.log' \
    --exclude='build/' \
    --exclude='dist/' \
    agent/ "$TEMP_DIR/"

# Upload to S3
aws s3 sync "$TEMP_DIR/" "s3://$SOURCE_BUCKET/agent-source/" \
    --delete \
    --region "$REGION"

echo "✓ Agent source uploaded to s3://$SOURCE_BUCKET/agent-source/"
