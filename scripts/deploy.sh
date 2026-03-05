#!/bin/bash

set -e

INFRA_STACK_NAME="kyc-agent"
REGION="${2:-us-east-1}"
VPC_STACK="${INFRA_STACK_NAME}-vpc"
STORAGE_STACK="${INFRA_STACK_NAME}-storage"
ROLES_STACK="${INFRA_STACK_NAME}-roles"
MAIN_STACK="${INFRA_STACK_NAME}-main"
AGENT_STACK="${INFRA_STACK_NAME}-agentcore-runtime"
LAMBDA_STACK="${INFRA_STACK_NAME}-lambda"
API_STACK="${INFRA_STACK_NAME}-api"
UI_STACK="${INFRA_STACK_NAME}-ui"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

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


#Package and upload agent source
echo ""
echo "[3/5] Packaging and uploading agent source..."
echo "Script directory: $SCRIPT_DIR"
ZIP_KEY="$("$SCRIPT_DIR/package_agent.sh")"
aws s3 cp "$SCRIPT_DIR/$ZIP_KEY" "s3://$KYC_RESULTS_BUCKET/$ZIP_KEY" --region "$REGION"
rm -f "$SCRIPT_DIR/$ZIP_KEY"
echo "✓ Agent source uploaded: s3://$KYC_RESULTS_BUCKET/$ZIP_KEY"



# Deploy agent stack
echo ""
echo "[4/6] Deploying agent stack..."
aws cloudformation deploy \
    --stack-name "$AGENT_STACK" \
    --template-file "$REPO_ROOT/templates/agentcore-stack.yaml" \
    --parameter-overrides \
        AgentName="kyc_agent" \
        RolesStackName="$ROLES_STACK" \
        SourceZipKey="$ZIP_KEY" \
        KycCasesTableName="$KYC_CASES_TABLE" \
        KycResultsBucketName="$KYC_RESULTS_BUCKET" \
    --disable-rollback \
    --region "$REGION"
echo "✓ Agent stack ready"

# Resolve ARNs needed by the Lambda stack
echo ""
echo "[5/6] Resolving queue and agent ARNs..."
KYC_INITIATED_QUEUE_ARN=$(aws cloudformation describe-stacks \
    --stack-name "$MAIN_STACK" \
    --query 'Stacks[0].Outputs[?OutputKey==`KycInitiatedQueueArn`].OutputValue' \
    --output text \
    --region "$REGION" 2>/dev/null || true)
if [ -z "$KYC_INITIATED_QUEUE_ARN" ] || [ "$KYC_INITIATED_QUEUE_ARN" == "None" ]; then
  echo "Warning: KycInitiatedQueueArn not found in $MAIN_STACK. Deploy main stack first."
fi
# Queue name for API Lambda (backend uses get_queue_url(QueueName=...)); derive from ARN if not exported
KYC_INITIATED_QUEUE_NAME=$(aws cloudformation describe-stacks --stack-name "$MAIN_STACK" --query 'Stacks[0].Outputs[?OutputKey==`KycInitiatedQueueName`].OutputValue' --output text --region "$REGION" 2>/dev/null || true)
if [ -z "$KYC_INITIATED_QUEUE_NAME" ] || [ "$KYC_INITIATED_QUEUE_NAME" == "None" ]; then
  KYC_INITIATED_QUEUE_NAME="${KYC_INITIATED_QUEUE_ARN##*:}"
fi
KYC_AGENT_ARN=$(aws cloudformation describe-stacks \
    --stack-name "$AGENT_STACK" \
    --query 'Stacks[0].Outputs[?OutputKey==`AgentRuntimeArn`].OutputValue' \
    --output text \
    --region "$REGION" 2>/dev/null || true)
if [ -z "$KYC_AGENT_ARN" ] || [ "$KYC_AGENT_ARN" == "None" ]; then
  echo "Warning: AgentRuntimeArn not found in $AGENT_STACK."
fi
echo "KYC Agent ARN: $KYC_AGENT_ARN"
KYC_LAMBDA_EXECUTION_ROLE_ARN=$(aws cloudformation describe-stacks \
    --stack-name "$ROLES_STACK" \
    --query 'Stacks[0].Outputs[?OutputKey==`KycLambdaExecutionRoleArn`].OutputValue' \
    --output text \
    --region "$REGION" 2>/dev/null || true)
if [ -z "$KYC_LAMBDA_EXECUTION_ROLE_ARN" ] || [ "$KYC_LAMBDA_EXECUTION_ROLE_ARN" == "None" ]; then
  echo "Warning: KycLambdaExecutionRoleArn not found in $ROLES_STACK."
fi

# Package and upload Lambda code
echo ""
echo "[6/6] Packaging and uploading Lambda, then deploying Lambda stack..."
LAMBDA_ZIP="lambda-kyc-processor-$(date +%s).zip"
if command -v zip >/dev/null 2>&1; then
  (cd "$REPO_ROOT/lambda" && zip -r "$SCRIPT_DIR/$LAMBDA_ZIP" . -x "*.pyc" -x "__pycache__/*" -x ".venv/*" -x "venv/*" >/dev/null 2>&1)
else
  (cd "$REPO_ROOT/lambda" && python -c "
import zipfile, pathlib
p = pathlib.Path('.')
with zipfile.ZipFile('_lambda_pkg.zip', 'w', zipfile.ZIP_DEFLATED) as zf:
    for f in sorted(p.rglob('*')):
        if f.is_file() and '__pycache__' not in str(f) and '.venv' not in str(f) and 'venv' not in str(f) and f.name != '_lambda_pkg.zip':
            zf.write(f, f.as_posix())
")
  mv "$REPO_ROOT/lambda/_lambda_pkg.zip" "$SCRIPT_DIR/$LAMBDA_ZIP"
fi
aws s3 cp "$SCRIPT_DIR/$LAMBDA_ZIP" "s3://$KYC_RESULTS_BUCKET/$LAMBDA_ZIP" --region "$REGION"
rm -f "$SCRIPT_DIR/$LAMBDA_ZIP"
echo "✓ Lambda package uploaded: s3://$KYC_RESULTS_BUCKET/$LAMBDA_ZIP"

aws cloudformation deploy \
    --stack-name "$LAMBDA_STACK" \
    --template-file "$REPO_ROOT/templates/lambda-stack.yaml" \
    --parameter-overrides \
        AgentArn="$KYC_AGENT_ARN" \
        KycCasesTableName="$KYC_CASES_TABLE" \
        KycLambdaExecutionRoleArn="$KYC_LAMBDA_EXECUTION_ROLE_ARN" \
        LambdaSourceBucket="$KYC_RESULTS_BUCKET" \
        LambdaSourceKey="$LAMBDA_ZIP" \
        KycInitiatedQueueArn="$KYC_INITIATED_QUEUE_ARN" \
    --region "$REGION"
echo "✓ Lambda stack ready"

# Package and upload backend API (FastAPI) for API Gateway + Lambda
echo ""
echo "[7/7] Packaging and uploading backend API..."
BACKEND_ZIP="backend-api-$(date +%s).zip"
TMP_BACKEND=$(mktemp -d 2>/dev/null || echo "$SCRIPT_DIR/.backend_build_$$")
mkdir -p "$TMP_BACKEND"
# Install for Lambda (Linux x86_64, Python 3.11) so native deps like pydantic_core are included
pip install -q -r "$REPO_ROOT/backend/requirements.txt" -t "$TMP_BACKEND" --upgrade \
  --platform manylinux2014_x86_64 --python-version 3.11 --implementation cp --only-binary=:all:
cp "$REPO_ROOT/backend/main.py" "$TMP_BACKEND/"
if command -v zip >/dev/null 2>&1; then
  (cd "$TMP_BACKEND" && zip -r "$SCRIPT_DIR/$BACKEND_ZIP" . -x "*.pyc" -x "__pycache__/*" -x "*.dist-info/*" >/dev/null 2>&1)
else
  (cd "$TMP_BACKEND" && python -c "
import zipfile, pathlib
p = pathlib.Path('.')
with zipfile.ZipFile('_backend_pkg.zip', 'w', zipfile.ZIP_DEFLATED) as zf:
    for f in sorted(p.rglob('*')):
        if f.is_file() and '__pycache__' not in str(f) and '.pyc' not in str(f) and '.dist-info' not in str(f) and f.name != '_backend_pkg.zip':
            zf.write(f, f.as_posix())
")
  mv "$TMP_BACKEND/_backend_pkg.zip" "$SCRIPT_DIR/$BACKEND_ZIP"
fi
rm -rf "$TMP_BACKEND"
aws s3 cp "$SCRIPT_DIR/$BACKEND_ZIP" "s3://$KYC_RESULTS_BUCKET/$BACKEND_ZIP" --region "$REGION"
rm -f "$SCRIPT_DIR/$BACKEND_ZIP"
echo "✓ Backend API package uploaded: s3://$KYC_RESULTS_BUCKET/$BACKEND_ZIP"

aws cloudformation deploy \
    --stack-name "$API_STACK" \
    --template-file "$REPO_ROOT/templates/api-stack.yaml" \
    --parameter-overrides \
        BackendLambdaRoleArn="$KYC_LAMBDA_EXECUTION_ROLE_ARN" \
        BackendSourceBucket="$KYC_RESULTS_BUCKET" \
        BackendSourceKey="$BACKEND_ZIP" \
        KycCasesTableName="$KYC_CASES_TABLE" \
        KycInitiatedQueueName="$KYC_INITIATED_QUEUE_NAME" \
    --region "$REGION"
echo "✓ API stack ready"
API_ENDPOINT=$(aws cloudformation describe-stacks --stack-name "$API_STACK" --query 'Stacks[0].Outputs[?OutputKey==`ApiEndpoint`].OutputValue' --output text --region "$REGION" 2>/dev/null || true)
if [ -n "$API_ENDPOINT" ] && [ "$API_ENDPOINT" != "None" ]; then
  echo "  Backend API: $API_ENDPOINT"
fi

# Deploy UI stack (CloudFormation), then package frontend and sync via deploy_ui.py
echo ""
echo "[8/8] Deploying UI stack and syncing frontend..."
aws cloudformation deploy \
    --stack-name "$UI_STACK" \
    --template-file "$REPO_ROOT/templates/ui-stack.yaml" \
    --parameter-overrides \
        AcmCertificateArn="${ACM_CERTIFICATE_ARN:-}" \
    --region "$REGION"
echo "✓ UI stack ready"

export INFRA_STACK_NAME AWS_DEFAULT_REGION="$REGION"
# Prefer 'python' on Windows (Git Bash, conda, etc.); use python3 on Unix
case "$(uname -s 2>/dev/null)" in
  MINGW*|MSYS*|CYGWIN*) PYTHON=python ;;
  *) PYTHON=python3 ;;
esac
if ! command -v $PYTHON >/dev/null 2>&1; then
  PYTHON=python
fi
"$PYTHON" "$SCRIPT_DIR/deploy_ui.py" "$INFRA_STACK_NAME" "$REGION"

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
