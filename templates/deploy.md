# Deployment Guide

## Stack dependency overview

```
vpc-stack ──────────────────────────────────────────────────────────┐
storage-stack ──────────────────────────────────────────────────────┤
main-stack (SQS) ───────────────────────────────────────────────────┤
roles-stack ────────────────────────────────────────────────────────┤
                                                                     ↓
                                          pipeline-stack (AgentCore CI/CD)
                                          api-pipeline-stack
                                                     │
                                          [pipelines run on push]
                                                     │
                                          agentcore-stack  ←── pipeline-stack deploys this
                                          api-stack         ←── api-pipeline-stack deploys this
                                                     │
                                          [get AgentArn from agentcore-stack]
                                                     │
                                          lambda-pipeline-stack
                                                     │
                                          [pipeline runs on push]
                                                     │
                                          lambda-stack  ←── lambda-pipeline-stack deploys this
```

**Manually deployed (you run these):** vpc-stack, storage-stack, main-stack, roles-stack, pipeline-stack, api-pipeline-stack, lambda-pipeline-stack

**Pipeline-managed (never deploy these directly after initial setup):** agentcore-stack, api-stack, lambda-stack

---

## Step 0 — Set variables

```bash
AWS_REGION=eu-west-1
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

# Stack names — adjust to your environment/naming convention
VPC_STACK=kyc-vpc
STORAGE_STACK=kyc-storage
MAIN_STACK=kyc-main
ROLES_STACK=kyc-roles           # IMPORTANT: must equal the StackName parameter passed to roles-stack
PIPELINE_STACK=kyc-agent-pipeline
AGENTCORE_STACK=kyc-agentcore   # name the pipeline will give the agentcore stack
API_PIPELINE_STACK=kyc-api-pipeline
API_STACK=kyc-api               # name the api pipeline will give the api stack
LAMBDA_PIPELINE_STACK=kyc-lambda-pipeline
LAMBDA_STACK=kyc-lambda         # name the lambda pipeline will give the lambda stack

# GitHub — used by all three pipelines
GITHUB_CONNECTION_ARN=arn:aws:codestar-connections:$AWS_REGION:$AWS_ACCOUNT_ID:connection/<id>
GITHUB_REPO=myorg/kyc-agents
GITHUB_BRANCH=main

# Application config
DEFAULT_MODEL_ID=us.anthropic.claude-3-5-sonnet-20241022-v2:0
KYC_LAMBDA_TIMEOUT=700          # seconds, default 700
MOCK_SERVICE_URL=               # leave empty for production
```

---

## Phase 1 — Base infrastructure (one-time, in order)

### 1. VPC

No dependencies. Exports `${VPC_STACK}-VpcId`, `PrivateSubnet1Id`, `PrivateSubnet2Id`.

```bash
aws cloudformation deploy \
  --template-file templates/base/vpc-stack.yaml \
  --stack-name $VPC_STACK \
  --region $AWS_REGION
```

### 2. Storage (S3 + DynamoDB)

No dependencies. Exports bucket name and DynamoDB table name under the `StackName` prefix.

```bash
aws cloudformation deploy \
  --template-file templates/base/storage-stack.yaml \
  --stack-name $STORAGE_STACK \
  --parameter-overrides StackName=$STORAGE_STACK \
  --region $AWS_REGION
```

### 3. Main stack (SQS queue + SSM model ID)

No dependencies. Exports queue name, URL, and ARN.

```bash
aws cloudformation deploy \
  --template-file templates/base/main-stack.yaml \
  --stack-name $MAIN_STACK \
  --parameter-overrides DefaultModelId=$DEFAULT_MODEL_ID \
  --region $AWS_REGION
```

### 4. Roles stack (IAM)

Depends on storage-stack and pipeline stack names (baked into IAM policy resource patterns).
The `StackName` parameter controls the export key prefix — it **must** equal `$ROLES_STACK`.

```bash
aws cloudformation deploy \
  --template-file templates/base/roles-stack.yaml \
  --stack-name $ROLES_STACK \
  --parameter-overrides \
      StackName=$ROLES_STACK \
      BaseStackName=$STORAGE_STACK \
      PipelineStackName=$PIPELINE_STACK \
      ApiPipelineStackName=$API_PIPELINE_STACK \
  --capabilities CAPABILITY_NAMED_IAM \
  --region $AWS_REGION
```

---

## Phase 2 — CI/CD pipelines

Fetch the values needed from the base stacks first:

```bash
KYC_RESULTS_BUCKET=$(aws cloudformation describe-stacks \
  --stack-name $STORAGE_STACK \
  --query 'Stacks[0].Outputs[?OutputKey==`SourceBucketName`].OutputValue' \
  --output text --region $AWS_REGION)

KYC_CASES_TABLE=$(aws cloudformation describe-stacks \
  --stack-name $STORAGE_STACK \
  --query 'Stacks[0].Outputs[?OutputKey==`KycCasesTableName`].OutputValue' \
  --output text --region $AWS_REGION)

KYC_QUEUE_NAME=$(aws cloudformation describe-stacks \
  --stack-name $MAIN_STACK \
  --query 'Stacks[0].Outputs[?OutputKey==`KycInitiatedQueueName`].OutputValue' \
  --output text --region $AWS_REGION)

KYC_QUEUE_ARN=$(aws cloudformation describe-stacks \
  --stack-name $MAIN_STACK \
  --query 'Stacks[0].Outputs[?OutputKey==`KycInitiatedQueueArn`].OutputValue' \
  --output text --region $AWS_REGION)
```

### 5a. AgentCore pipeline (pipeline-stack)

Builds the crew/ Docker image, pushes to ECR, and deploys `agentcore-stack`.
Triggers automatically on any push to `$GITHUB_BRANCH`.

```bash
aws cloudformation deploy \
  --template-file templates/pipeline-stack.yaml \
  --stack-name $PIPELINE_STACK \
  --parameter-overrides \
      GitHubConnectionArn=$GITHUB_CONNECTION_ARN \
      GitHubRepo=$GITHUB_REPO \
      GitHubBranch=$GITHUB_BRANCH \
      RolesStackName=$ROLES_STACK \
      AgentcoreStackName=$AGENTCORE_STACK \
      KycCasesTableName=$KYC_CASES_TABLE \
      KycResultsBucketName=$KYC_RESULTS_BUCKET \
      VpcStackName=$VPC_STACK \
      MockServiceUrl=$MOCK_SERVICE_URL \
  --capabilities CAPABILITY_NAMED_IAM \
  --region $AWS_REGION
```

### 5b. API pipeline (api-pipeline-stack)

Packages `backend/` as a Lambda zip and deploys `api-stack`. Can be deployed in parallel with 5a.
Triggers automatically on changes to `backend/**` or `templates/api-stack.yaml`.

```bash
aws cloudformation deploy \
  --template-file templates/api-pipeline-stack.yaml \
  --stack-name $API_PIPELINE_STACK \
  --parameter-overrides \
      GitHubConnectionArn=$GITHUB_CONNECTION_ARN \
      GitHubRepo=$GITHUB_REPO \
      GitHubBranch=$GITHUB_BRANCH \
      RolesStackName=$ROLES_STACK \
      ApiStackName=$API_STACK \
      KycResultsBucketName=$KYC_RESULTS_BUCKET \
      KycCasesTableName=$KYC_CASES_TABLE \
      KycInitiatedQueueName=$KYC_QUEUE_NAME \
      VpcStackName=$VPC_STACK \
  --region $AWS_REGION
```

---

## Phase 3 — Lambda pipeline (requires AgentCore to be deployed first)

The lambda-pipeline-stack needs the Bedrock AgentCore runtime ARN, which is only available after
the AgentCore pipeline (step 5a) has run and successfully deployed `agentcore-stack`.

### 6. Wait for the AgentCore pipeline to complete, then fetch the agent ARN

```bash
# Check that agentcore-stack exists and is in a stable state
aws cloudformation describe-stacks \
  --stack-name $AGENTCORE_STACK \
  --query 'Stacks[0].StackStatus' \
  --output text --region $AWS_REGION

# Fetch the agent runtime ARN
AGENT_ARN=$(aws cloudformation describe-stacks \
  --stack-name $AGENTCORE_STACK \
  --query 'Stacks[0].Outputs[?OutputKey==`AgentRuntimeArn`].OutputValue' \
  --output text --region $AWS_REGION)

echo "AgentArn: $AGENT_ARN"
```

### 7. Lambda pipeline (lambda-pipeline-stack)

Packages `lambda/` as a Lambda zip and deploys `lambda-stack` (the SQS-triggered KYC processor).
Triggers automatically on changes to `lambda/**` or `templates/lambda-stack.yaml`.

```bash
aws cloudformation deploy \
  --template-file templates/lambda-pipeline-stack.yaml \
  --stack-name $LAMBDA_PIPELINE_STACK \
  --parameter-overrides \
      GitHubConnectionArn=$GITHUB_CONNECTION_ARN \
      GitHubRepo=$GITHUB_REPO \
      GitHubBranch=$GITHUB_BRANCH \
      RolesStackName=$ROLES_STACK \
      LambdaStackName=$LAMBDA_STACK \
      KycResultsBucketName=$KYC_RESULTS_BUCKET \
      KycCasesTableName=$KYC_CASES_TABLE \
      KycInitiatedQueueArn=$KYC_QUEUE_ARN \
      AgentArn=$AGENT_ARN \
      VpcStackName=$VPC_STACK \
      KycLambdaTimeout=$KYC_LAMBDA_TIMEOUT \
  --region $AWS_REGION
```

---

## Summary: what deploys what

| Stack you deploy | Deploys (via pipeline) |
|---|---|
| `pipeline-stack` | `agentcore-stack` |
| `api-pipeline-stack` | `api-stack` |
| `lambda-pipeline-stack` | `lambda-stack` |

## Updating a deployed stack

For the three pipeline stacks, **do not redeploy the application stacks directly** — push code to GitHub and let the pipeline handle it. To update pipeline infrastructure or pass-through parameters (e.g. `AgentArn`, `KycLambdaTimeout`), re-run the relevant `aws cloudformation deploy` command above with updated values.