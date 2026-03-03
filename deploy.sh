#!/bin/bash

set -e

INFRA_STACK_NAME="kyc-agent"
REGION="${2:-us-east-1}"
VPC_STACK="${INFRA_STACK_NAME}-vpc"
STORAGE_STACK="${INFRA_STACK_NAME}-storage"
ROLES_STACK="${INFRA_STACK_NAME}-roles"
MAIN_STACK="${INFRA_STACK_NAME}-main"
AGENT_STACK="${INFRA_STACK_NAME}-agentcore"
LAMBDA_STACK="${INFRA_STACK_NAME}-lambda"

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



# Deploy agent/main stack
echo ""
echo "[4/6] Deploying agent stack..."
aws cloudformation deploy \
    --stack-name "$AGENT_STACK" \
    --template-file templates/agentcore-stack.yaml \
    --parameter-overrides \
        AgentName="kyc_agent" \
        VpcStackName="$VPC_STACK" \
        RolesStackName="$ROLES_STACK" \
        SourceZipKey="$ZIP_KEY" \
        KycCasesTableName="$KYC_CASES_TABLE" \
        KycResultsBucketName="$KYC_RESULTS_BUCKET" \
    --disable-rollback \
    --region "$REGION"
echo "✓ Agent stack ready"

# Get queue ARN from main stack (output key KycInitiatedQueueArn) and Agent ARN from agent stack
echo ""
echo "[5/6] Resolving queue and agent ARNs..."
KYC_INITIATED_QUEUE_ARN=$(aws cloudformation describe-stacks \
    --stack-name "$MAIN_STACK" \
    --query 'Stacks[0].Outputs[?OutputKey==`KycInitiatedQueueArn`].OutputValue' \
    --output text \
    --region "$REGION" 2>/dev/null || true)
if [ -z "$KYC_INITIATED_QUEUE_ARN" ] || [ "$KYC_INITIATED_QUEUE_ARN" == "None" ]; then
  echo "Warning: KycInitiatedQueueArn not found in $MAIN_STACK; Lambda stack may need it. Deploy main stack first if it defines the queue."
fi
AGENT_ARN=$(aws cloudformation describe-stacks \
    --stack-name "$AGENT_STACK" \
    --query 'Stacks[0].Outputs[?OutputKey==`AgentRuntimeArn`].OutputValue' \
    --output text \
    --region "$REGION" 2>/dev/null || true)
if [ -z "$AGENT_ARN" ] || [ "$AGENT_ARN" == "None" ]; then
  echo "Warning: AgentRuntimeArn not found in $AGENT_STACK."
fi
KYC_LAMBDA_EXECUTION_ROLE_ARN=$(aws cloudformation describe-stacks \
    --stack-name "$ROLES_STACK" \
    --query 'Stacks[0].Outputs[?OutputKey==`KycLambdaExecutionRoleArn`].OutputValue' \
    --output text \
    --region "$REGION" 2>/dev/null || true)
if [ -z "$KYC_LAMBDA_EXECUTION_ROLE_ARN" ] || [ "$KYC_LAMBDA_EXECUTION_ROLE_ARN" == "None" ]; then
  echo "Warning: KycLambdaExecutionRoleArn not found in $ROLES_STACK. Deploy roles stack with KYC Lambda role first."
fi

# Package and upload Lambda code
echo ""
echo "[6/6] Packaging and uploading Lambda, then deploying Lambda stack..."
LAMBDA_ZIP="lambda-kyc-processor-$(date +%s).zip"
if command -v zip >/dev/null 2>&1; then
  (cd "$SCRIPT_DIR/lambda" && zip -r "../$LAMBDA_ZIP" . -x "*.pyc" -x "__pycache__/*" -x ".venv/*" -x "venv/*" >/dev/null 2>&1)
else
  (cd "$SCRIPT_DIR/lambda" && python -c "
import zipfile, pathlib
p = pathlib.Path('.')
with zipfile.ZipFile('_lambda_pkg.zip', 'w', zipfile.ZIP_DEFLATED) as zf:
    for f in sorted(p.rglob('*')):
        if f.is_file() and '__pycache__' not in str(f) and '.venv' not in str(f) and 'venv' not in str(f) and f.name != '_lambda_pkg.zip':
            zf.write(f, f.as_posix())
")
  mv "$SCRIPT_DIR/lambda/_lambda_pkg.zip" "$SCRIPT_DIR/$LAMBDA_ZIP"
fi
aws s3 cp "$SCRIPT_DIR/$LAMBDA_ZIP" "s3://$KYC_RESULTS_BUCKET/$LAMBDA_ZIP" --region "$REGION"
rm -f "$SCRIPT_DIR/$LAMBDA_ZIP"
echo "✓ Lambda package uploaded: s3://$KYC_RESULTS_BUCKET/$LAMBDA_ZIP"

aws cloudformation deploy \
    --stack-name "$LAMBDA_STACK" \
    --template-file templates/lambda-stack.yaml \
    --parameter-overrides \
        AgentArn="$AGENT_ARN" \
        KycCasesTableName="$KYC_CASES_TABLE" \
        KycLambdaExecutionRoleArn="$KYC_LAMBDA_EXECUTION_ROLE_ARN" \
        LambdaSourceBucket="$KYC_RESULTS_BUCKET" \
        LambdaSourceKey="$LAMBDA_ZIP" \
        KycInitiatedQueueArn="$KYC_INITIATED_QUEUE_ARN" \
    --region "$REGION"
echo "✓ Lambda stack ready"

echo ""
echo "=========================================="
echo "✓ Deployment complete!"
echo "=========================================="
echo ""
aws cloudformation describe-stacks \
    --stack-name "$AGENT_STACK" \
    --query 'Stacks[0].Outputs' \
    --output table \
    --region "$REGION"
echo ""
echo "To delete: ./cleanup.sh $INFRA_STACK_NAME $REGION"
