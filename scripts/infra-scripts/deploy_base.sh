#!/usr/bin/env bash
# Deploys the four base infrastructure stacks (Phase 1) in order:
#   1. vpc-stack
#   2. storage-stack
#   3. main-stack
#   4. roles-stack
#
# Usage:
#   bash scripts/infra-scripts/deploy_base.sh [BASE_NAME] [REGION]
#
# Defaults: BASE_NAME=kyc-agent, REGION=us-east-1
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

BASE_NAME="${1:-kyc-agent}"
REGION="${2:-${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-1}}}"
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