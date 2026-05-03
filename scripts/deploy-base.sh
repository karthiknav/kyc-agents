#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TEMPLATE_DIR="$REPO_ROOT/templates/base"

BASE_NAME="${1:-kyc-agent}"
REGION="${2:-us-east-1}"
VPC_STACK="${BASE_NAME}-vpc"
STORAGE_STACK="${BASE_NAME}-storage"
ROLES_STACK="${BASE_NAME}-roles"
MAIN_STACK="${BASE_NAME}-main"
PIPELINE_STACK="${BASE_NAME}-pipeline"
API_PIPELINE_STACK="${BASE_NAME}-api-pipeline"


echo "=========================================="
echo "Deploying KYC Main Stack"
echo "=========================================="
echo "VPC Stack: $VPC_STACK"
echo "Storage Stack: $STORAGE_STACK"
echo "Roles Stack: $ROLES_STACK"
echo "Main Stack: $MAIN_STACK"
echo "Pipeline Stack: $PIPELINE_STACK"
echo "API Pipeline Stack: $API_PIPELINE_STACK"
echo "Region: $REGION"
echo "=========================================="

# Deploy VPC stack
echo ""
echo "[1/5] Deploying VPC stack..."
aws cloudformation deploy \
    --stack-name "$VPC_STACK" \
    --template-file "$TEMPLATE_DIR/vpc-stack.yaml" \
    --parameter-overrides StackName="$VPC_STACK" \
    --region "$REGION"
echo "✓ VPC stack ready"

# Deploy storage stack (S3 + DynamoDB)
echo ""
echo "[2/5] Deploying storage stack..."
aws cloudformation deploy \
    --stack-name "$STORAGE_STACK" \
    --template-file "$TEMPLATE_DIR/storage-stack.yaml" \
    --parameter-overrides StackName="$STORAGE_STACK" \
    --region "$REGION"
echo "✓ Storage stack ready"

# Get bucket name
SOURCE_BUCKET=$(aws cloudformation describe-stacks \
    --stack-name "$STORAGE_STACK" \
    --query 'Stacks[0].Outputs[?OutputKey==`SourceBucketName`].OutputValue' \
    --output text \
    --region "$REGION")
echo "Source bucket: $SOURCE_BUCKET"

# Deploy roles stack 
echo ""
echo "[3/5] Deploying roles stack..."
aws cloudformation deploy \
    --stack-name "$ROLES_STACK" \
    --template-file "$TEMPLATE_DIR/roles-stack.yaml" \
    --parameter-overrides StackName="$ROLES_STACK" BaseStackName="$BASE_NAME" PipelineStackName="$PIPELINE_STACK" ApiPipelineStackName="$API_PIPELINE_STACK" \
    --capabilities CAPABILITY_NAMED_IAM \
    --region "$REGION"
echo "✓ Roles stack ready"

# Deploy main stack (KYC: DynamoDB, SQS)
echo ""
echo "[5/5] Deploying main stack..."
aws cloudformation deploy \
    --stack-name "$MAIN_STACK" \
    --template-file "$TEMPLATE_DIR/main-stack.yaml" \
    --capabilities CAPABILITY_NAMED_IAM \
    --region "$REGION"
echo "✓ Main stack ready"

echo ""
echo "=========================================="
echo "✓ Deployment complete!"
echo "=========================================="
echo ""
aws cloudformation describe-stacks \
    --stack-name "$MAIN_STACK" \
    --query 'Stacks[0].Outputs' \
    --output table \
    --region "$REGION"
echo ""
echo "To delete: ./cleanup.sh $BASE_NAME $REGION"
