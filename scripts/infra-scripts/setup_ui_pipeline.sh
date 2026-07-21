#!/usr/bin/env bash
# Deploys the UI infra and CI/CD pipeline stacks.
# 1. ui-stack.yaml   — S3 bucket + CloudFront distribution (idempotent)
# 2. ui-pipeline-stack.yaml — CodePipeline that builds and syncs the React frontend on every push.
#
# Optional env vars:
#   ACM_CERTIFICATE_ARN  — ACM cert ARN (must be in us-east-1) for the custom domain
#   CUSTOM_DOMAIN_NAME   — Custom domain alias, e.g. kyc.gen-ai-designs.com
#
# Both must be set together, or neither. If omitted, CloudFront uses its default cert/domain.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

REGION="us-east-1"

ROLES_STACK="kyc-agent-roles"
UI_STACK="kyc-agent-ui"
API_STACK="kyc-agent-api"
AGENT_PIPELINE_STACK="kyc-agent-pipeline"
UI_PIPELINE_STACK="kyc-agent-ui-pipeline"

GITHUB_CONNECTION_ARN="arn:aws:codeconnections:us-east-1:926529379586:connection/6ac4ec4b-58b4-4270-8a1b-80acae253b39"
GITHUB_REPO="karthiknav/kyc-agents"
GITHUB_BRANCH="improvements"
ACM_CERTIFICATE_ARN=arn:aws:acm:us-east-1:360946915124:certificate/885900ce-5f44-4ace-99d5-9df2dc867948
CUSTOM_DOMAIN_NAME=kyc.gen-ai-designs.com


# Validate: both must be set or both empty
if [[ -n "$ACM_CERTIFICATE_ARN" && -z "$CUSTOM_DOMAIN_NAME" ]] || \
   [[ -z "$ACM_CERTIFICATE_ARN" && -n "$CUSTOM_DOMAIN_NAME" ]]; then
    echo "ERROR: ACM_CERTIFICATE_ARN and CUSTOM_DOMAIN_NAME must both be set or both be empty."
    exit 1
fi

echo "=== UI pipeline deployment ==="
echo "  UI_PIPELINE_STACK    : $UI_PIPELINE_STACK"
echo "  UI_STACK             : $UI_STACK"
echo "  API_STACK            : $API_STACK"
echo "  AGENT_PIPELINE_STACK : $AGENT_PIPELINE_STACK"
echo "  GITHUB_REPO          : $GITHUB_REPO"
echo "  GITHUB_BRANCH        : $GITHUB_BRANCH"
echo "  REGION               : $REGION"
if [[ -n "$CUSTOM_DOMAIN_NAME" ]]; then
echo "  CUSTOM_DOMAIN_NAME   : $CUSTOM_DOMAIN_NAME"
echo "  ACM_CERTIFICATE_ARN  : $ACM_CERTIFICATE_ARN"
else
echo "  CUSTOM_DOMAIN_NAME   : (none — using default CloudFront domain)"
fi
echo ""

# ── Deploy ui-stack (S3 bucket + CloudFront) ─────────────────────────────────
echo "── Deploying $UI_STACK ──"

UI_STACK_PARAMS=""
if [[ -n "$CUSTOM_DOMAIN_NAME" ]]; then
    UI_STACK_PARAMS="AcmCertificateArn=$ACM_CERTIFICATE_ARN CustomDomainName=$CUSTOM_DOMAIN_NAME"
fi

aws cloudformation deploy \
    --template-file "$REPO_ROOT/templates/ui-stack.yaml" \
    --stack-name "$UI_STACK" \
    --capabilities CAPABILITY_NAMED_IAM \
    --region "$REGION" \
    --no-fail-on-empty-changeset \
    ${UI_STACK_PARAMS:+--parameter-overrides $UI_STACK_PARAMS}

echo "✓ $UI_STACK deployed"

# ── Create Route 53 alias record for custom domain ───────────────────────────
if [[ -n "$CUSTOM_DOMAIN_NAME" ]]; then
    echo "── Creating Route 53 alias record for $CUSTOM_DOMAIN_NAME ──"

    CF_DOMAIN=$(aws cloudformation describe-stacks \
        --stack-name "$UI_STACK" \
        --query "Stacks[0].Outputs[?OutputKey=='DistributionDomainName'].OutputValue" \
        --output text --region "$REGION")

    # Extract the apex domain (last two labels) from the custom domain
    APEX_DOMAIN=$(echo "$CUSTOM_DOMAIN_NAME" | awk -F. '{print $(NF-1)"."$NF}')

    ZONE_ID=$(aws route53 list-hosted-zones-by-name \
        --dns-name "$APEX_DOMAIN" \
        --query "HostedZones[?Name=='${APEX_DOMAIN}.'].Id" \
        --output text | cut -d/ -f3)

    if [[ -z "$ZONE_ID" ]]; then
        echo "WARNING: No Route 53 hosted zone found for $APEX_DOMAIN — skipping DNS record."
        echo "  Create a CNAME manually: $CUSTOM_DOMAIN_NAME → $CF_DOMAIN"
    else
        # Z2FDTNDATAQYW2 is the fixed hosted zone ID for all CloudFront distributions
        aws route53 change-resource-record-sets \
            --hosted-zone-id "$ZONE_ID" \
            --change-batch "{
              \"Changes\": [{
                \"Action\": \"UPSERT\",
                \"ResourceRecordSet\": {
                  \"Name\": \"$CUSTOM_DOMAIN_NAME\",
                  \"Type\": \"A\",
                  \"AliasTarget\": {
                    \"HostedZoneId\": \"Z2FDTNDATAQYW2\",
                    \"DNSName\": \"$CF_DOMAIN\",
                    \"EvaluateTargetHealth\": false
                  }
                }
              }]
            }"
        echo "✓ Route 53 alias record upserted: $CUSTOM_DOMAIN_NAME → $CF_DOMAIN"
    fi
fi

# ── Verify api-stack is deployed (needed for VITE_API_BASE_URL at build time) ──
echo "── Checking api-stack status ──"
API_STATUS=$(aws cloudformation describe-stacks \
    --stack-name "$API_STACK" \
    --query 'Stacks[0].StackStatus' \
    --output text --region "$REGION")

echo "  $API_STACK status: $API_STATUS"

if [[ "$API_STATUS" != "CREATE_COMPLETE" && "$API_STATUS" != "UPDATE_COMPLETE" ]]; then
    echo "ERROR: $API_STACK is not in a stable state ($API_STATUS)."
    echo "  Deploy the API stack before running this script."
    exit 1
fi

echo ""

# ── Deploy ui-pipeline-stack ──────────────────────────────────────────────────
echo "── Deploying $UI_PIPELINE_STACK ──"
aws cloudformation deploy \
    --template-file "$REPO_ROOT/templates/ui-pipeline-stack.yaml" \
    --stack-name "$UI_PIPELINE_STACK" \
    --parameter-overrides \
        GitHubConnectionArn="$GITHUB_CONNECTION_ARN" \
        GitHubRepo="$GITHUB_REPO" \
        GitHubBranch="$GITHUB_BRANCH" \
        RolesStackName="$ROLES_STACK" \
        UiStackName="$UI_STACK" \
        ApiStackName="$API_STACK" \
        AgentPipelineStackName="$AGENT_PIPELINE_STACK" \
    --capabilities CAPABILITY_NAMED_IAM \
    --region "$REGION"

echo "✓ $UI_PIPELINE_STACK deployed"
echo ""
echo "=== UI pipeline deployed successfully ==="
echo "  The pipeline will build and deploy the frontend on the next push to $GITHUB_BRANCH."
