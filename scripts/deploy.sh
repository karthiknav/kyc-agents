#!/bin/bash
# Full-stack deploy: agent, Lambda, API, UI. Requires base stacks (VPC, storage, roles, main) to exist.
#
# Deploy order: Deploy mock-service (Beanstalk) first so the agent can call mock endpoints (BRP + PEP):
#   1. ./scripts/deploy_mock_service.sh   (with S3_BUCKET and STACK_NAME)
#   2. Get the mock-service URL from the stack output and set MOCK_SERVICE_URL for the agent runtime
#   3. ./scripts/deploy.sh                (this script)

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
MOCK_EB_STACK="${MOCK_EB_STACK:-kyc-mock-service-eb}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Resolve mock-service (Beanstalk) base URL using EB CNAME (domain) instead of instance IP
MOCK_SERVICE_URL_VALUE=""
if aws cloudformation describe-stacks --stack-name "$MOCK_EB_STACK" --region "$REGION" &>/dev/null; then
  MOCK_ENV_NAME=$(aws cloudformation describe-stacks --stack-name "$MOCK_EB_STACK" --region "$REGION" \
    --query "Stacks[0].Outputs[?OutputKey=='EnvironmentName'].OutputValue" --output text 2>/dev/null || true)
  if [ -n "$MOCK_ENV_NAME" ] && [ "$MOCK_ENV_NAME" != "None" ]; then
    MOCK_CNAME=$(aws elasticbeanstalk describe-environments --environment-names "$MOCK_ENV_NAME" --region "$REGION" \
      --query 'Environments[0].CNAME' --output text 2>/dev/null || true)
    if [ -n "$MOCK_CNAME" ] && [ "$MOCK_CNAME" != "None" ]; then
      MOCK_SERVICE_URL_VALUE="http://${MOCK_CNAME}"
      echo "Using MOCK_SERVICE_URL (Beanstalk domain): $MOCK_SERVICE_URL_VALUE"
    else
      MOCK_ENV_URL=$(aws cloudformation describe-stacks --stack-name "$MOCK_EB_STACK" --region "$REGION" \
        --query "Stacks[0].Outputs[?OutputKey=='EnvironmentURL'].OutputValue" --output text 2>/dev/null || true)
      if [ -n "$MOCK_ENV_URL" ] && [ "$MOCK_ENV_URL" != "None" ]; then
        MOCK_SERVICE_URL_VALUE="${MOCK_ENV_URL%/}"
        echo "Using MOCK_SERVICE_URL (from stack): $MOCK_SERVICE_URL_VALUE"
      fi
    fi
  fi
fi

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
ZIP_KEY="$("$SCRIPT_DIR/package_agent.sh" | tail -n 1)"
echo "Generated zip key: $ZIP_KEY"
echo "Uploading agent source to s3://$KYC_RESULTS_BUCKET/$ZIP_KEY..."
aws s3 cp "$SCRIPT_DIR/$ZIP_KEY" "s3://$KYC_RESULTS_BUCKET/$ZIP_KEY" --region "$REGION"
rm -f "$SCRIPT_DIR/$ZIP_KEY"
echo "✓ Agent source uploaded: s3://$KYC_RESULTS_BUCKET/$ZIP_KEY"



#Deploy agent stack
echo ""
echo "[4/6] Deploying agent stack..."
aws cloudformation deploy \
    --stack-name "$AGENT_STACK" \
    --template-file "$REPO_ROOT/templates/agentcore-stack.yaml" \
    --parameter-overrides \
        AgentName="kyc_agent" \
        RolesStackName="$ROLES_STACK" \
        SourceZipKey="$ZIP_KEY" \
        ImageTag="latest" \
        KycCasesTableName="$KYC_CASES_TABLE" \
        KycResultsBucketName="$KYC_RESULTS_BUCKET" \
    MockServiceUrl="$MOCK_SERVICE_URL_VALUE" \
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

EVAL_AGENT_RUNTIME_ARN="$KYC_AGENT_ARN"
EVAL_REGION="$REGION"

export INFRA_STACK_NAME AWS_DEFAULT_REGION="$REGION"

have_deploy_deps () {
  "$1" -c "import boto3; import bedrock_agentcore_starter_toolkit" >/dev/null 2>&1
}

UI_VENV="$SCRIPT_DIR/.venv"
REQS_UI="$SCRIPT_DIR/requirements-deploy-ui.txt"

PYTHON=""
if [ -n "$VIRTUAL_ENV" ] && [ -x "$VIRTUAL_ENV/bin/python" ] && have_deploy_deps "$VIRTUAL_ENV/bin/python"; then
  PYTHON="$VIRTUAL_ENV/bin/python"
else
  if [ ! -x "$UI_VENV/bin/python" ]; then
    python3 -m venv "$UI_VENV"
    "$UI_VENV/bin/python" -m pip install -q --upgrade pip
  fi

  if ! have_deploy_deps "$UI_VENV/bin/python"; then
    "$UI_VENV/bin/python" -m pip install -q -r "$REQS_UI"
  fi

  PYTHON="$UI_VENV/bin/python"
fi

# Apply Langfuse + OTEL env from SSM right after AgentCore stack deploy (UpdateAgentRuntime).
if [ -z "${SKIP_LANGFUSE_RUNTIME_UPDATE:-}" ] && [ -n "$KYC_AGENT_ARN" ] && [ "$KYC_AGENT_ARN" != "None" ]; then
  echo ""
  echo "Applying Langfuse / OTEL environment to agent runtime..."
  "$PYTHON" "$SCRIPT_DIR/relaunch_agent_runtime_langfuse.py" \
    --agent-runtime-arn "$KYC_AGENT_ARN" \
    --region "$REGION" \
    --tracing-environment "default" \
    || echo "Warning: Langfuse runtime env update failed (set SKIP_LANGFUSE_RUNTIME_UPDATE=1 to skip)."
fi

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
uv pip install -q -r "$REPO_ROOT/backend/requirements.txt" -t "$TMP_BACKEND" --upgrade \
  --python-platform manylinux_2_17_x86_64 \
  --python-version 3.11 \
  --only-binary=:all:
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

# Deploy X-Ray Transaction Search config (CloudFormation)
# echo ""
# echo "[8/9] Deploying X-Ray Transaction Search config..."
# XRAY_STACK="${INFRA_STACK_NAME}-xray-transaction-search"
# aws cloudformation deploy \
#   --stack-name "$XRAY_STACK" \
#   --template-file "$REPO_ROOT/templates/xray-transaction-search-stack.yaml" \
#   --region "$REGION"
# echo "✓ X-Ray Transaction Search stack ready"

# Deploy UI stack (CloudFormation), then package frontend and sync via deploy_ui.py
echo ""
echo "[9/9] Deploying UI stack and syncing frontend..."
aws cloudformation deploy \
    --stack-name "$UI_STACK" \
    --template-file "$REPO_ROOT/templates/ui-stack.yaml" \
    --parameter-overrides \
        AcmCertificateArn="${ACM_CERTIFICATE_ARN:-}" \
    --region "$REGION"
echo "✓ UI stack ready"

# Run evaluation config setup (PYTHON + venv were prepared after agent deploy)
# if [ -n "$EVAL_AGENT_RUNTIME_ARN" ] && [ "$EVAL_AGENT_RUNTIME_ARN" != "None" ]; then
#   "$PYTHON" "$SCRIPT_DIR/setup_agent_evaluation.py" \
#     --agent-runtime-arn "$EVAL_AGENT_RUNTIME_ARN" \
#     --region "$EVAL_REGION"
# else
#   echo "Warning: skipping evaluation setup (missing agent runtime ARN)."
# fi

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
