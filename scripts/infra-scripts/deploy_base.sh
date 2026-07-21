#!/usr/bin/env bash
# Deploys the four base infrastructure stacks (Phase 1) in order:
#   1. vpc-stack
#   2. storage-stack
#   3. main-stack
#   4. roles-stack
#
# Usage:
#   bash scripts/infra-scripts/deploy_base.sh [BASE_NAME] [REGION] [--skip-main-stack]
#   bash scripts/infra-scripts/deploy_base.sh --skip-main-stack
#
# Defaults: BASE_NAME=kyc-agent, REGION=us-east-1
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

BASE_NAME="kyc-agent"
REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-1}}"
SKIP_MAIN_STACK=false
POSITIONAL_ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip-main-stack)
            SKIP_MAIN_STACK=true
            shift
            ;;
        -h|--help)
            echo "Usage: bash scripts/infra-scripts/deploy_base.sh [BASE_NAME] [REGION] [--skip-main-stack]"
            exit 0
            ;;
        *)
            POSITIONAL_ARGS+=("$1")
            shift
            ;;
    esac
done

if [[ ${#POSITIONAL_ARGS[@]} -ge 1 ]]; then
    BASE_NAME="${POSITIONAL_ARGS[0]}"
fi

if [[ ${#POSITIONAL_ARGS[@]} -ge 2 ]]; then
    REGION="${POSITIONAL_ARGS[1]}"
fi

if [[ ${#POSITIONAL_ARGS[@]} -gt 2 ]]; then
    echo "Error: too many positional arguments"
    echo "Usage: bash scripts/infra-scripts/deploy_base.sh [BASE_NAME] [REGION] [--skip-main-stack]"
    exit 1
fi

DEFAULT_MODEL_ID="${DEFAULT_MODEL_ID:-us.anthropic.claude-sonnet-4-6}"
LANGFUSE_PROJECT_NAME="${LANGFUSE_PROJECT_NAME:-kyc-agents}"
LANGFUSE_HOST="https://langfuse.gen-ai-designs.com"
LANGFUSE_PUBLIC_KEY="${LANGFUSE_PUBLIC_KEY:-}"
LANGFUSE_SECRET_KEY="${LANGFUSE_SECRET_KEY:-}"

VPC_STACK="${BASE_NAME}-vpc"
STORAGE_STACK="${BASE_NAME}-storage"
MAIN_STACK="${BASE_NAME}-main"
ROLES_STACK="${BASE_NAME}-roles"

echo "=== Base infrastructure deployment ==="
echo "  BASE_NAME : $BASE_NAME"
echo "  REGION    : $REGION"
echo "  SKIP_MAIN : $SKIP_MAIN_STACK"
echo ""

# ── 1. VPC ────────────────────────────────────────────────────────────────────
echo "── Step 1: VPC ($VPC_STACK) ──"
aws cloudformation deploy \
    --template-file "$REPO_ROOT/templates/base/vpc-stack.yaml" \
    --stack-name "$VPC_STACK" \
    --region "$REGION"
echo "✓ $VPC_STACK deployed"
echo ""

# ── 2. Storage (S3 + DynamoDB) ───────────────────────────────────────────────
echo "── Step 2: Storage ($STORAGE_STACK) ──"
aws cloudformation deploy \
    --template-file "$REPO_ROOT/templates/base/storage-stack.yaml" \
    --stack-name "$STORAGE_STACK" \
    --parameter-overrides StackName="$BASE_NAME" \
    --region "$REGION"
echo "✓ $STORAGE_STACK deployed"
echo ""

# ── 3. Main stack (SQS + SSM model ID) ───────────────────────────────────────
if [[ "$SKIP_MAIN_STACK" == "true" ]]; then
    echo "── Step 3: Main ($MAIN_STACK) ──"
    echo "Skipping main stack deployment (--skip-main-stack)"
else
    echo "── Step 3: Main ($MAIN_STACK) ──"
    aws cloudformation deploy \
        --template-file "$REPO_ROOT/templates/base/main-stack.yaml" \
        --stack-name "$MAIN_STACK" \
        --parameter-overrides \
            DefaultModelId="$DEFAULT_MODEL_ID" \
            LangfuseProjectName="$LANGFUSE_PROJECT_NAME" \
            LangfuseHost="$LANGFUSE_HOST" \
            LangfusePublicKey="$LANGFUSE_PUBLIC_KEY" \
            LangfuseSecretKey="$LANGFUSE_SECRET_KEY" \
        --region "$REGION"
    echo "✓ $MAIN_STACK deployed"
fi
echo "── Step 3: Main ($MAIN_STACK) ──"
main_stack_parameters=(
    "DefaultModelId=$DEFAULT_MODEL_ID"
)

if [[ -n "$LANGFUSE_PROJECT_NAME" ]]; then
    main_stack_parameters+=("LangfuseProjectName=$LANGFUSE_PROJECT_NAME")
fi
if [[ -n "$LANGFUSE_HOST" ]]; then
    main_stack_parameters+=("LangfuseHost=$LANGFUSE_HOST")
fi
if [[ -n "$LANGFUSE_PUBLIC_KEY" ]]; then
    main_stack_parameters+=("LangfusePublicKey=$LANGFUSE_PUBLIC_KEY")
fi
if [[ -n "$LANGFUSE_SECRET_KEY" ]]; then
    main_stack_parameters+=("LangfuseSecretKey=$LANGFUSE_SECRET_KEY")
fi

aws cloudformation deploy \
    --template-file "$REPO_ROOT/templates/base/main-stack.yaml" \
    --stack-name "$MAIN_STACK" \
    --parameter-overrides "${main_stack_parameters[@]}" \
    --region "$REGION"
echo "✓ $MAIN_STACK deployed"
echo ""

# ── 4. Roles stack (IAM) ─────────────────────────────────────────────────────
echo "── Step 4: Roles ($ROLES_STACK) ──"
aws cloudformation deploy \
    --template-file "$REPO_ROOT/templates/base/roles-stack.yaml" \
    --stack-name "$ROLES_STACK" \
    --parameter-overrides BaseStackName="$BASE_NAME" \
    --capabilities CAPABILITY_NAMED_IAM \
    --region "$REGION"
echo "✓ $ROLES_STACK deployed"
echo ""

echo "=== All base stacks deployed successfully ==="
echo "  Next: deploy the CI/CD pipeline stacks (Phase 2)."