#!/bin/bash

set -e

BASE_NAME="${1:-basic-agent-demo}"
REGION="${2:-us-east-1}"
S3_STACK="${BASE_NAME}-s3"
ROLES_STACK="${BASE_NAME}-roles"
MAIN_STACK="${BASE_NAME}-main"

echo "=========================================="
echo "Deploying Agent Runtime Stacks"
echo "=========================================="
echo "S3 Stack: $S3_STACK"
echo "Roles Stack: $ROLES_STACK"
echo "Main Stack: $MAIN_STACK"
echo "Region: $REGION"
echo "=========================================="

# Deploy S3 stack
echo ""
echo "[1/4] Deploying S3 stack..."
aws cloudformation deploy \
    --stack-name "$S3_STACK" \
    --template-file templates/s3-stack.yaml \
    --parameter-overrides StackName="$S3_STACK" \
    --region "$REGION"
echo "✓ S3 stack ready"

# Get bucket name
SOURCE_BUCKET=$(aws cloudformation describe-stacks \
    --stack-name "$S3_STACK" \
    --query 'Stacks[0].Outputs[?OutputKey==`SourceBucketName`].OutputValue' \
    --output text \
    --region "$REGION")
echo "Source bucket: $SOURCE_BUCKET"

# Upload agent source as zip
echo ""
echo "[2/4] Uploading agent source..."
cd agent
TIMESTAMP=$(date +%s)
ZIP_KEY="agent-source-${TIMESTAMP}.zip"
zip -r ../$ZIP_KEY . \
    -x "venv/*" \
    -x "__pycache__/*" \
    -x "*.pyc" \
    -x ".git/*" \
    -x "*.log" > /dev/null
cd ..
aws s3 cp $ZIP_KEY "s3://$SOURCE_BUCKET/$ZIP_KEY" --region "$REGION"
rm $ZIP_KEY
echo "✓ Agent source uploaded: $ZIP_KEY"

# Deploy roles stack
echo ""
echo "[3/4] Deploying roles stack..."
aws cloudformation deploy \
    --stack-name "$ROLES_STACK" \
    --template-file templates/roles-stack.yaml \
    --parameter-overrides StackName="$ROLES_STACK" BaseStackName="$BASE_NAME" \
    --capabilities CAPABILITY_NAMED_IAM \
    --region "$REGION"
echo "✓ Roles stack ready"

# Deploy main stack
echo ""
echo "[4/4] Deploying main stack..."
aws cloudformation deploy \
    --stack-name "$MAIN_STACK" \
    --template-file templates/main-stack.yaml \
    --parameter-overrides \
        RolesStackName="$ROLES_STACK" \
        SourceBucketName="$SOURCE_BUCKET" \
        SourceZipKey="$ZIP_KEY" \
    --disable-rollback
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
