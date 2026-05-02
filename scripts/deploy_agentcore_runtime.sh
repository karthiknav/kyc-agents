#!/usr/bin/env bash
# Deploy AgentCore runtime + apply Langfuse/OTEL env update.
# Can be run standalone, or invoked from scripts/deploy.sh.
#
# Usage:
#   ./scripts/deploy_agentcore_runtime.sh --infra-stack-name kyc-agent --region us-east-1
#   eval "$(./scripts/deploy_agentcore_runtime.sh --print-env)"   # when calling from another script

set -euo pipefail

log() {
  # shellcheck disable=SC2145
  echo "$@" >&2
}

die() {
  log "Error: $*"
  exit 1
}

INFRA_STACK_NAME="kyc-agent"
REGION="us-east-1"
PRINT_ENV=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --infra-stack-name)
      INFRA_STACK_NAME="$2"; shift 2 ;;
    --region)
      REGION="$2"; shift 2 ;;
    --print-env)
      PRINT_ENV=1; shift ;;
    -h|--help)
      cat >&2 <<'EOF'
Deploy AgentCore runtime and (optionally) relaunch runtime with Langfuse/OTEL env.

Options:
  --infra-stack-name NAME   Stack prefix (default: kyc-agent)
  --region REGION           AWS region (default: us-east-1)
  --print-env               Print export lines to stdout for eval

Environment:
  MOCK_EB_STACK                  Mock service EB stack name (default: kyc-mock-service-eb)
  LANGFUSE_ENABLED                If truthy (1/true/yes/on), apply Langfuse/OTEL runtime env update
  SKIP_LANGFUSE_RUNTIME_UPDATE   Set to 1 to skip runtime env update
  LOG_SSM_PARAMETER_VALUES       (Only affects agent runtime logs) See crew/kyc_app.py
EOF
      exit 0 ;;
    *)
      die "Unknown arg: $1" ;;
  esac
done

# If we're being used as an eval-able env emitter, ensure *only* export lines reach stdout.
# Many AWS CLI commands print progress to stdout, which would break `eval "$(...)"`.
if [[ $PRINT_ENV -eq 1 ]]; then
  exec 3>&1
  exec 1>&2
fi

VPC_STACK="${INFRA_STACK_NAME}-vpc"
STORAGE_STACK="${INFRA_STACK_NAME}-storage"
ROLES_STACK="${INFRA_STACK_NAME}-roles"
MAIN_STACK="${INFRA_STACK_NAME}-main"
AGENT_STACK="${INFRA_STACK_NAME}-agentcore-runtime"
MOCK_EB_STACK="${MOCK_EB_STACK:-kyc-mock-service-eb}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Resolve mock-service (Beanstalk) base URL using EB CNAME (domain) instead of instance IP
MOCK_SERVICE_URL_VALUE=""
if aws cloudformation describe-stacks --stack-name "$MOCK_EB_STACK" --region "$REGION" &>/dev/null; then
  MOCK_ENV_NAME=$(aws cloudformation describe-stacks --stack-name "$MOCK_EB_STACK" --region "$REGION" \
    --query "Stacks[0].Outputs[?OutputKey=='EnvironmentName'].OutputValue" --output text 2>/dev/null || true)
  if [[ -n "$MOCK_ENV_NAME" && "$MOCK_ENV_NAME" != "None" ]]; then
    MOCK_CNAME=$(aws elasticbeanstalk describe-environments --environment-names "$MOCK_ENV_NAME" --region "$REGION" \
      --query 'Environments[0].CNAME' --output text 2>/dev/null || true)
    if [[ -n "$MOCK_CNAME" && "$MOCK_CNAME" != "None" ]]; then
      MOCK_SERVICE_URL_VALUE="http://${MOCK_CNAME}"
      log "Using MOCK_SERVICE_URL (Beanstalk domain): $MOCK_SERVICE_URL_VALUE"
    else
      MOCK_ENV_URL=$(aws cloudformation describe-stacks --stack-name "$MOCK_EB_STACK" --region "$REGION" \
        --query "Stacks[0].Outputs[?OutputKey=='EnvironmentURL'].OutputValue" --output text 2>/dev/null || true)
      if [[ -n "$MOCK_ENV_URL" && "$MOCK_ENV_URL" != "None" ]]; then
        MOCK_SERVICE_URL_VALUE="${MOCK_ENV_URL%/}"
        log "Using MOCK_SERVICE_URL (from stack): $MOCK_SERVICE_URL_VALUE"
      fi
    fi
  fi
fi

KYC_RESULTS_BUCKET=$(aws cloudformation describe-stacks \
  --stack-name "$STORAGE_STACK" \
  --query 'Stacks[0].Outputs[?OutputKey==`SourceBucketName`].OutputValue' \
  --output text \
  --region "$REGION")
log "Kyc bucket: $KYC_RESULTS_BUCKET"

KYC_CASES_TABLE=$(aws cloudformation describe-stacks \
  --stack-name "$STORAGE_STACK" \
  --query 'Stacks[0].Outputs[?OutputKey==`KycCasesTableName`].OutputValue' \
  --output text \
  --region "$REGION")
log "Kyc Cases Table: $KYC_CASES_TABLE"

log "=========================================="
log "Deploying AgentCore runtime"
log "=========================================="
log "Infra Stack: $INFRA_STACK_NAME"
log "VPC Stack: $VPC_STACK"
log "S3 Stack: $STORAGE_STACK"
log "Roles Stack: $ROLES_STACK"
log "Main Stack: $MAIN_STACK"
log "Agent Stack: $AGENT_STACK"
log "Region: $REGION"
log "=========================================="

# Package and upload agent source
log ""
log "Packaging and uploading agent source..."
ZIP_KEY="$($SCRIPT_DIR/package_agent.sh | tail -n 1)"
log "Generated zip key: $ZIP_KEY"
log "Uploading agent source to s3://$KYC_RESULTS_BUCKET/$ZIP_KEY..."
aws s3 cp "$SCRIPT_DIR/$ZIP_KEY" "s3://$KYC_RESULTS_BUCKET/$ZIP_KEY" --region "$REGION"
rm -f "$SCRIPT_DIR/$ZIP_KEY"
log "✓ Agent source uploaded: s3://$KYC_RESULTS_BUCKET/$ZIP_KEY"

# Deploy agent stack
log ""
log "Deploying agent stack..."
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
log "✓ Agent stack ready"

# Resolve agent ARN
KYC_AGENT_ARN=$(aws cloudformation describe-stacks \
  --stack-name "$AGENT_STACK" \
  --query 'Stacks[0].Outputs[?OutputKey==`AgentRuntimeArn`].OutputValue' \
  --output text \
  --region "$REGION" 2>/dev/null || true)
if [[ -z "$KYC_AGENT_ARN" || "$KYC_AGENT_ARN" == "None" ]]; then
  log "Warning: AgentRuntimeArn not found in $AGENT_STACK."
else
  log "KYC Agent ARN: $KYC_AGENT_ARN"
fi

export INFRA_STACK_NAME AWS_DEFAULT_REGION="$REGION"

is_truthy() {
  case "${1:-}" in
    1|true|TRUE|True|yes|YES|Yes|y|Y|on|ON|On) return 0 ;;
    *) return 1 ;;
  esac
}

have_deploy_deps () {
  "$1" -c "import boto3; import bedrock_agentcore_starter_toolkit" >/dev/null 2>&1
}

UI_VENV="$SCRIPT_DIR/.venv"
REQS_UI="$SCRIPT_DIR/requirements-deploy-ui.txt"

PYTHON=""
if [[ -n "${VIRTUAL_ENV:-}" && -x "${VIRTUAL_ENV}/bin/python" ]] && have_deploy_deps "${VIRTUAL_ENV}/bin/python"; then
  PYTHON="${VIRTUAL_ENV}/bin/python"
else
  if [[ ! -x "$UI_VENV/bin/python" ]]; then
    python3 -m venv "$UI_VENV"
    "$UI_VENV/bin/python" -m pip install -q --upgrade pip
  fi

  if ! have_deploy_deps "$UI_VENV/bin/python"; then
    "$UI_VENV/bin/python" -m pip install -q -r "$REQS_UI"
  fi

  PYTHON="$UI_VENV/bin/python"
fi

# Apply Langfuse + OTEL env from SSM right after AgentCore stack deploy (UpdateAgentRuntime).
# Only do this when LANGFUSE_ENABLED is truthy.
if is_truthy "${LANGFUSE_ENABLED:-0}" && [[ -z "${SKIP_LANGFUSE_RUNTIME_UPDATE:-}" && -n "$KYC_AGENT_ARN" && "$KYC_AGENT_ARN" != "None" ]]; then
  log ""
  log "Applying Langfuse / OTEL environment to agent runtime..."
  "$PYTHON" "$SCRIPT_DIR/relaunch_agent_runtime_langfuse.py" \
    --agent-runtime-arn "$KYC_AGENT_ARN" \
    --region "$REGION" \
    --tracing-environment "default" \
    || log "Warning: Langfuse runtime env update failed (set SKIP_LANGFUSE_RUNTIME_UPDATE=1 to skip)."
fi

if [[ $PRINT_ENV -eq 1 ]]; then
  # Emit eval-safe export lines on the original stdout.
  printf 'export INFRA_STACK_NAME=%q\n' "$INFRA_STACK_NAME" >&3
  printf 'export AWS_DEFAULT_REGION=%q\n' "$REGION" >&3
  printf 'export REGION=%q\n' "$REGION" >&3
  printf 'export VPC_STACK=%q\n' "$VPC_STACK" >&3
  printf 'export STORAGE_STACK=%q\n' "$STORAGE_STACK" >&3
  printf 'export ROLES_STACK=%q\n' "$ROLES_STACK" >&3
  printf 'export MAIN_STACK=%q\n' "$MAIN_STACK" >&3
  printf 'export AGENT_STACK=%q\n' "$AGENT_STACK" >&3
  printf 'export KYC_RESULTS_BUCKET=%q\n' "$KYC_RESULTS_BUCKET" >&3
  printf 'export KYC_CASES_TABLE=%q\n' "$KYC_CASES_TABLE" >&3
  printf 'export KYC_AGENT_ARN=%q\n' "$KYC_AGENT_ARN" >&3
  printf 'export PYTHON=%q\n' "$PYTHON" >&3
fi
