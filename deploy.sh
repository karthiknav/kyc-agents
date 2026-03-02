#!/bin/bash

set -e

INFRA_STACK_NAME="kyc-agent"
REGION="${2:-us-east-1}"
VPC_STACK="${INFRA_STACK_NAME}-vpc"
STORAGE_STACK="${INFRA_STACK_NAME}-storage"
ROLES_STACK="${INFRA_STACK_NAME}-roles"
MAIN_STACK="${INFRA_STACK_NAME}-main"
AGENT_STACK="${INFRA_STACK_NAME}-agentcore"

KYC_RESULTS_BUCKET=$(aws cloudformation describe-stacks \
    --stack-name "$STORAGE_STACK" \
    --query 'Stacks[0].Outputs[?OutputKey==`SourceBucketName`].OutputValue' \
    --output text \
    --region "$REGION")
echo "Kyc bucket: $KYC_RESULTS_BUCKET"
KYC_CASES_TABLE=$(aws cloudformation describe-stacks \
    --stack-name "$STORAGE_STACK" \
    --query 'Stacks[0].Outputs[?OutputKey==`KycCasesTableName`].OutputValue' \
    --output text \
    --region "$REGION")
echo "Kyc Cases Table: $KYC_CASES_TABLE"

echo "=========================================="
echo "Deploying Agent Runtime Stacks"
echo "=========================================="
echo "VPC Stack: $VPC_STACK"
echo "S3 Stack: $STORAGE_STACK"
echo "Roles Stack: $ROLES_STACK"
echo "Main Stack: $MAIN_STACK"
echo "Region: $REGION"
echo "=========================================="


# Package and upload agent source
echo ""
echo "[3/5] Packaging and uploading agent source..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "Script directory: $SCRIPT_DIR"
ZIP_KEY="$("$SCRIPT_DIR/package_agent.sh")"
aws s3 cp "$SCRIPT_DIR/$ZIP_KEY" "s3://$KYC_RESULTS_BUCKET/$ZIP_KEY" --region "$REGION"
rm -f "$SCRIPT_DIR/$ZIP_KEY"
echo "✓ Agent source uploaded: s3://$KYC_RESULTS_BUCKET/$ZIP_KEY"



# Deploy main stack
echo ""
echo "[5/5] Deploying main stack..."
aws cloudformation deploy \
    --stack-name "$AGENT_STACK" \
    --template-file templates/main-stack.yaml \
    --parameter-overrides \
        VpcStackName="$VPC_STACK" \
        RolesStackName="$ROLES_STACK" \
        SourceZipKey="$ZIP_KEY" \
        KycCasesTableName="$KYC_CASES_TABLE" \
        KycResultsBucketName="$KYC_RESULTS_BUCKET" \
    --disable-rollback \
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
