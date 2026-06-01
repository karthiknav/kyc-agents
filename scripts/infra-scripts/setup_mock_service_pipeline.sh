#!/usr/bin/env bash
# First-time setup of the mock-service CI/CD pipeline from CloudShell.
# Deploys mock-service-pipeline-stack (CodeBuild + CodePipeline + EB).
# After this runs, every push to mock-service/ triggers the pipeline automatically.
#
# Usage:
#   GITHUB_CONNECTION_ARN=arn:aws:codeconnections:... bash deploy_mock_service.sh
#
# The GitHub connection must already exist in CodeConnections (console: Developer Tools → Connections).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-1}}"
GITHUB_CONNECTION_ARN="arn:aws:codeconnections:us-east-1:360946915124:connection/24a1bf19-4ba9-42ee-ad2c-f37799f02447"

: "${GITHUB_CONNECTION_ARN:?GITHUB_CONNECTION_ARN is required (find it in AWS Console → Developer Tools → Connections)}"

ARTIFACTS_BUCKET=$(aws cloudformation describe-stacks \
    --stack-name kyc-agent-storage \
    --region "$REGION" \
    --query 'Stacks[0].Outputs[?OutputKey==`ArtifactsBucketName`].OutputValue' \
    --output text)

VPC_ID=$(aws cloudformation describe-stacks \
    --stack-name kyc-agent-vpc \
    --region "$REGION" \
    --query 'Stacks[0].Outputs[?OutputKey==`VpcId`].OutputValue' \
    --output text)

PUBLIC_SUBNET_1=$(aws cloudformation describe-stacks \
    --stack-name kyc-agent-vpc \
    --region "$REGION" \
    --query 'Stacks[0].Outputs[?OutputKey==`PublicSubnet1Id`].OutputValue' \
    --output text)

PUBLIC_SUBNET_2=$(aws cloudformation describe-stacks \
    --stack-name kyc-agent-vpc \
    --region "$REGION" \
    --query 'Stacks[0].Outputs[?OutputKey==`PublicSubnet2Id`].OutputValue' \
    --output text)

if [ -z "$ARTIFACTS_BUCKET" ] || [ "$ARTIFACTS_BUCKET" = "None" ]; then
    echo "Error: Could not resolve ArtifactsBucketName from kyc-agent-storage stack." >&2
    exit 1
fi

if [ -z "$VPC_ID" ] || [ "$VPC_ID" = "None" ]; then
    echo "Error: Could not resolve VpcId from kyc-agent-vpc stack." >&2
    exit 1
fi

if [ -z "$PUBLIC_SUBNET_1" ] || [ "$PUBLIC_SUBNET_1" = "None" ]; then
    echo "Error: Could not resolve PublicSubnet1Id from kyc-agent-vpc stack." >&2
    exit 1
fi

if [ -z "$PUBLIC_SUBNET_2" ] || [ "$PUBLIC_SUBNET_2" = "None" ]; then
    echo "Error: Could not resolve PublicSubnet2Id from kyc-agent-vpc stack." >&2
    echo "ALB requires subnets in at least 2 AZs. Ensure the kyc-agent-vpc stack exports PublicSubnet2Id." >&2
    exit 1
fi

PUBLIC_SUBNETS="$PUBLIC_SUBNET_1,$PUBLIC_SUBNET_2"

echo "Using artifacts bucket : $ARTIFACTS_BUCKET"
echo "Using VPC              : $VPC_ID"
echo "Using public subnets   : $PUBLIC_SUBNETS"
echo "Deploying pipeline stack: kyc-agent-mock-service-pipeline ..."

aws cloudformation deploy \
    --template-file "$REPO_ROOT/templates/mock-service-pipeline-stack.yaml" \
    --stack-name kyc-agent-mock-service-pipeline \
    --capabilities CAPABILITY_NAMED_IAM \
    --parameter-overrides \
        GitHubConnectionArn="$GITHUB_CONNECTION_ARN" \
        GitHubRepo="karthiknav/kyc-agents" \
        GitHubBranch="improvements" \
        MockServiceStackName="kyc-mock-service-eb" \
        KycResultsBucketName="$ARTIFACTS_BUCKET" \
        VpcId="$VPC_ID" \
        Subnets="$PUBLIC_SUBNETS" \
    --region "$REGION"

echo "✓ Pipeline stack deployed: kyc-agent-mock-service-pipeline"
echo "  The pipeline will now trigger automatically on pushes to mock-service/ on the improvements branch."
