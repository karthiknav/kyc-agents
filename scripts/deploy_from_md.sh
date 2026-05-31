#!/usr/bin/env bash
# Scripted version of `templates/deploy.md`.
# Deploys the "manual" CloudFormation stacks and sets up CI/CD pipelines.
#
# Safe defaults:
# - Runs base stacks in order, then pipelines.
# - Does NOT deploy the mock-service pipeline unless explicitly enabled.
# - Lambda pipeline requires AgentCore AgentRuntimeArn; the script can wait/poll for it.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

usage() {
  cat <<'EOF'
Usage:
  bash scripts/deploy_from_md.sh [options]

Options:
  --base-name NAME                Base name prefix (default: kyc-agent)
  --region REGION                 AWS region (default: us-east-1)
  --profile PROFILE               AWS profile name (optional)

  --github-connection-arn ARN     (required for pipelines) CodeConnections/CodeStar connection ARN
  --github-repo OWNER/REPO        (required for pipelines) e.g. karthiknav/kyc-agents
  --github-branch BRANCH          (default: main)

  --default-model-id MODEL_ID     (default: us.anthropic.claude-3-5-sonnet-20241022-v2:0)
  --kyc-lambda-timeout SECONDS    (default: 700)
  --mock-service-url URL          (default: empty)

  --phase PHASE                   all|base|pipelines|lambda (default: all)
  --deploy-mock-service-pipeline  Also deploy mock-service pipeline stack

  --agent-arn ARN                 Provide AgentRuntimeArn explicitly (skips waiting)
  --wait-agentcore-seconds N      Max seconds to wait for AgentCore stack output (default: 1800)

  --dry-run                        Print aws commands without executing
  -h, --help                       Show help

Examples:
  bash scripts/deploy_from_md.sh --phase base --region us-east-1

  bash scripts/deploy_from_md.sh \
    --github-connection-arn arn:aws:codestar-connections:us-east-1:123:connection/abc \
    --github-repo myorg/kyc-agents \
    --github-branch main \
    --deploy-mock-service-pipeline

  # If AgentCore pipeline already deployed agentcore stack, run lambda pipeline:
  bash scripts/deploy_from_md.sh --phase lambda --agent-arn arn:aws:bedrock-agentcore:...
EOF
}

log() { printf '%s\n' "$*" >&2; }

die() {
  log "Error: $*"
  exit 1
}

require_file() {
  local path="$1"
  [[ -f "$path" ]] || die "Missing file: $path"
}

AWS_PROFILE_NAME=""
BASE_NAME="kyc-agent"
REGION="us-east-1"
PHASE="all"
DRY_RUN=0

GITHUB_CONNECTION_ARN=""
GITHUB_REPO=""
GITHUB_BRANCH="main"

DEFAULT_MODEL_ID="us.anthropic.claude-3-5-sonnet-20241022-v2:0"
KYC_LAMBDA_TIMEOUT="700"
MOCK_SERVICE_URL=""

DEPLOY_MOCK_SERVICE_PIPELINE=0

AGENT_ARN=""
WAIT_AGENTCORE_SECONDS=1800

while [[ $# -gt 0 ]]; do
  case "$1" in
    --base-name) BASE_NAME="$2"; shift 2 ;;
    --region) REGION="$2"; shift 2 ;;
    --profile) AWS_PROFILE_NAME="$2"; shift 2 ;;

    --github-connection-arn) GITHUB_CONNECTION_ARN="$2"; shift 2 ;;
    --github-repo) GITHUB_REPO="$2"; shift 2 ;;
    --github-branch) GITHUB_BRANCH="$2"; shift 2 ;;

    --default-model-id) DEFAULT_MODEL_ID="$2"; shift 2 ;;
    --kyc-lambda-timeout) KYC_LAMBDA_TIMEOUT="$2"; shift 2 ;;
    --mock-service-url) MOCK_SERVICE_URL="$2"; shift 2 ;;

    --phase) PHASE="$2"; shift 2 ;;
    --deploy-mock-service-pipeline) DEPLOY_MOCK_SERVICE_PIPELINE=1; shift 1 ;;

    --agent-arn) AGENT_ARN="$2"; shift 2 ;;
    --wait-agentcore-seconds) WAIT_AGENTCORE_SECONDS="$2"; shift 2 ;;

    --dry-run) DRY_RUN=1; shift 1 ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown arg: $1 (use --help)" ;;
  esac
done

case "$PHASE" in
  all|base|pipelines|lambda) ;;
  *) die "Invalid --phase '$PHASE' (expected all|base|pipelines|lambda)" ;;
esac

# Stack names (from deploy.md)
VPC_STACK="${BASE_NAME}-vpc"
STORAGE_STACK="${BASE_NAME}-storage"
ROLES_STACK="${BASE_NAME}-roles"
MAIN_STACK="${BASE_NAME}-main"
PIPELINE_STACK="${BASE_NAME}-pipeline"
AGENTCORE_STACK="${BASE_NAME}-agentcore"
API_PIPELINE_STACK="${BASE_NAME}-api-pipeline"
API_STACK="${BASE_NAME}-api"
LAMBDA_PIPELINE_STACK="${BASE_NAME}-lambda-pipeline"
LAMBDA_STACK="${BASE_NAME}-lambda"
MOCK_SERVICE_PIPELINE_STACK="${BASE_NAME}-mock-service-pipeline"
MOCK_SERVICE_STACK="${BASE_NAME}-mock-service-eb"

# Validate templates exist
require_file "$REPO_ROOT/templates/base/vpc-stack.yaml"
require_file "$REPO_ROOT/templates/base/storage-stack.yaml"
require_file "$REPO_ROOT/templates/base/main-stack.yaml"
require_file "$REPO_ROOT/templates/base/roles-stack.yaml"
require_file "$REPO_ROOT/templates/pipeline-stack.yaml"
require_file "$REPO_ROOT/templates/api-pipeline-stack.yaml"
require_file "$REPO_ROOT/templates/lambda-pipeline-stack.yaml"
require_file "$REPO_ROOT/templates/mock-service-pipeline-stack.yaml"

aws_args() {
  # Emits common aws args: region (+ optional profile)
  if [[ -n "$AWS_PROFILE_NAME" ]]; then
    printf '%s\n' "--profile" "$AWS_PROFILE_NAME" "--region" "$REGION"
  else
    printf '%s\n' "--region" "$REGION"
  fi
}

run() {
  if [[ "$DRY_RUN" -eq 1 ]]; then
    printf 'DRY-RUN: ' >&2
    printf '%q ' "$@" >&2
    printf '\n' >&2
    return 0
  fi
  "$@"
}

aws_cli() {
  # shellcheck disable=SC2046
  run aws "$@" $(aws_args)
}

get_stack_output() {
  local stack_name="$1"
  local output_key="$2"

  # If stack doesn't exist, aws returns non-zero; suppress and return empty.
  aws cloudformation describe-stacks \
    --stack-name "$stack_name" \
    --query "Stacks[0].Outputs[?OutputKey==\`$output_key\`].OutputValue" \
    --output text $(aws_args) 2>/dev/null || true
}

require_pipelines_vars() {
  [[ -n "$GITHUB_CONNECTION_ARN" ]] || die "Missing --github-connection-arn (required for pipeline stacks)"
  [[ -n "$GITHUB_REPO" ]] || die "Missing --github-repo (required for pipeline stacks)"
}

wait_for_agent_arn() {
  local timeout_seconds="$1"
  local start
  start="$(date +%s)"

  log "Waiting for AgentCore stack '$AGENTCORE_STACK' to export AgentRuntimeArn (timeout: ${timeout_seconds}s)..."

  while true; do
    local value
    value="$(get_stack_output "$AGENTCORE_STACK" "AgentRuntimeArn")"

    if [[ -n "$value" && "$value" != "None" ]]; then
      printf '%s' "$value"
      return 0
    fi

    local now
    now="$(date +%s)"
    if (( now - start >= timeout_seconds )); then
      die "Timed out waiting for AgentRuntimeArn from stack '$AGENTCORE_STACK'. Re-run later, or pass --agent-arn explicitly."
    fi

    sleep 20
  done
}

log "Repo root: $REPO_ROOT"
log "Base name: $BASE_NAME"
log "Region: $REGION"

if [[ "$PHASE" == "base" || "$PHASE" == "all" ]]; then
  log "--- Phase 1: Base infrastructure ---"

  aws_cli cloudformation deploy \
    --template-file "$REPO_ROOT/templates/base/vpc-stack.yaml" \
    --stack-name "$VPC_STACK"

  aws_cli cloudformation deploy \
    --template-file "$REPO_ROOT/templates/base/storage-stack.yaml" \
    --stack-name "$STORAGE_STACK" \
    --parameter-overrides StackName="$BASE_NAME"

  aws_cli cloudformation deploy \
    --template-file "$REPO_ROOT/templates/base/main-stack.yaml" \
    --stack-name "$MAIN_STACK" \
    --parameter-overrides DefaultModelId="$DEFAULT_MODEL_ID"

  aws_cli cloudformation deploy \
    --template-file "$REPO_ROOT/templates/base/roles-stack.yaml" \
    --stack-name "$ROLES_STACK" \
    --parameter-overrides BaseStackName="$BASE_NAME" \
    --capabilities CAPABILITY_NAMED_IAM
fi

KYC_RESULTS_BUCKET=""
KYC_CASES_TABLE=""
KYC_QUEUE_NAME=""
KYC_QUEUE_ARN=""

# Pipelines (or lambda) need stack outputs; fetch if needed.
if [[ "$PHASE" != "base" ]]; then
  log "--- Reading base stack outputs ---"

  KYC_RESULTS_BUCKET="$(get_stack_output "$STORAGE_STACK" "SourceBucketName")"
  KYC_CASES_TABLE="$(get_stack_output "$STORAGE_STACK" "KycCasesTableName")"
  KYC_QUEUE_NAME="$(get_stack_output "$MAIN_STACK" "KycInitiatedQueueName")"
  KYC_QUEUE_ARN="$(get_stack_output "$MAIN_STACK" "KycInitiatedQueueArn")"

  [[ -n "$KYC_RESULTS_BUCKET" && "$KYC_RESULTS_BUCKET" != "None" ]] || die "Could not read SourceBucketName from '$STORAGE_STACK'"
  [[ -n "$KYC_CASES_TABLE" && "$KYC_CASES_TABLE" != "None" ]] || die "Could not read KycCasesTableName from '$STORAGE_STACK'"
  [[ -n "$KYC_QUEUE_NAME" && "$KYC_QUEUE_NAME" != "None" ]] || die "Could not read KycInitiatedQueueName from '$MAIN_STACK'"
  [[ -n "$KYC_QUEUE_ARN" && "$KYC_QUEUE_ARN" != "None" ]] || die "Could not read KycInitiatedQueueArn from '$MAIN_STACK'"

  log "KycResultsBucketName: $KYC_RESULTS_BUCKET"
  log "KycCasesTableName: $KYC_CASES_TABLE"
  log "KycInitiatedQueueName: $KYC_QUEUE_NAME"
fi

if [[ "$PHASE" == "pipelines" || "$PHASE" == "all" ]]; then
  require_pipelines_vars

  log "--- Phase 2: CI/CD pipelines ---"

  aws_cli cloudformation deploy \
    --template-file "$REPO_ROOT/templates/pipeline-stack.yaml" \
    --stack-name "$PIPELINE_STACK" \
    --parameter-overrides \
        GitHubConnectionArn="$GITHUB_CONNECTION_ARN" \
        GitHubRepo="$GITHUB_REPO" \
        GitHubBranch="$GITHUB_BRANCH" \
        RolesStackName="$ROLES_STACK" \
        AgentcoreStackName="$AGENTCORE_STACK" \
        KycCasesTableName="$KYC_CASES_TABLE" \
        KycResultsBucketName="$KYC_RESULTS_BUCKET" \
        VpcStackName="$VPC_STACK" \
        MockServiceUrl="$MOCK_SERVICE_URL" \
    --capabilities CAPABILITY_NAMED_IAM

  aws_cli cloudformation deploy \
    --template-file "$REPO_ROOT/templates/api-pipeline-stack.yaml" \
    --stack-name "$API_PIPELINE_STACK" \
    --parameter-overrides \
        GitHubConnectionArn="$GITHUB_CONNECTION_ARN" \
        GitHubRepo="$GITHUB_REPO" \
        GitHubBranch="$GITHUB_BRANCH" \
        RolesStackName="$ROLES_STACK" \
        ApiStackName="$API_STACK" \
        KycResultsBucketName="$KYC_RESULTS_BUCKET" \
        KycCasesTableName="$KYC_CASES_TABLE" \
        KycInitiatedQueueName="$KYC_QUEUE_NAME" \
        VpcStackName="$VPC_STACK"

  if [[ "$DEPLOY_MOCK_SERVICE_PIPELINE" -eq 1 ]]; then
    aws_cli cloudformation deploy \
      --template-file "$REPO_ROOT/templates/mock-service-pipeline-stack.yaml" \
      --stack-name "$MOCK_SERVICE_PIPELINE_STACK" \
      --capabilities CAPABILITY_NAMED_IAM \
      --parameter-overrides \
          GitHubConnectionArn="$GITHUB_CONNECTION_ARN" \
          GitHubRepo="$GITHUB_REPO" \
          GitHubBranch="$GITHUB_BRANCH" \
          MockServiceStackName="$MOCK_SERVICE_STACK" \
          KycResultsBucketName="$KYC_RESULTS_BUCKET"
  else
    log "Skipping mock-service pipeline (enable with --deploy-mock-service-pipeline)"
  fi
fi

if [[ "$PHASE" == "lambda" || "$PHASE" == "all" ]]; then
  require_pipelines_vars

  log "--- Phase 3: Lambda pipeline (requires AgentCore deployed by pipeline) ---"

  if [[ -z "$AGENT_ARN" ]]; then
    if [[ "$DRY_RUN" -eq 1 ]]; then
      log "DRY-RUN: would wait for AgentRuntimeArn from stack '$AGENTCORE_STACK'"
      AGENT_ARN="<AgentRuntimeArn>"
    else
      AGENT_ARN="$(wait_for_agent_arn "$WAIT_AGENTCORE_SECONDS")"
    fi
  fi

  [[ -n "$AGENT_ARN" && "$AGENT_ARN" != "None" ]] || die "Agent ARN is empty. Pass --agent-arn or re-run after AgentCore pipeline finishes."
  log "AgentArn: $AGENT_ARN"

  aws_cli cloudformation deploy \
    --template-file "$REPO_ROOT/templates/lambda-pipeline-stack.yaml" \
    --stack-name "$LAMBDA_PIPELINE_STACK" \
    --parameter-overrides \
        GitHubConnectionArn="$GITHUB_CONNECTION_ARN" \
        GitHubRepo="$GITHUB_REPO" \
        GitHubBranch="$GITHUB_BRANCH" \
        RolesStackName="$ROLES_STACK" \
        LambdaStackName="$LAMBDA_STACK" \
        KycResultsBucketName="$KYC_RESULTS_BUCKET" \
        KycCasesTableName="$KYC_CASES_TABLE" \
        KycInitiatedQueueArn="$KYC_QUEUE_ARN" \
        AgentArn="$AGENT_ARN" \
        VpcStackName="$VPC_STACK" \
        KycLambdaTimeout="$KYC_LAMBDA_TIMEOUT"
fi

log "✓ Done"
