# Setup & Deployment Guide

This guide walks through deploying the full KYC Agents stack in the correct order.

---

## Prerequisites

- AWS CLI configured with credentials that have CloudFormation, IAM, CodePipeline, CodeBuild, ECR, S3, DynamoDB, SQS, and SSM permissions
- A GitHub CodeConnections connection already created in AWS (Console → Developer Tools → Connections)
- All scripts run from the **repo root**

---

## Step 1 — Langfuse credentials

Langfuse provides tracing for all agent and tool calls. Retrieve your API keys before deploying infrastructure so they are written to SSM during the base stack deploy.

1. Open [https://langfuse.gen-ai-designs.com](https://langfuse.gen-ai-designs.com) and sign in.
2. Go to **Settings → API Keys**.
3. Copy the **Public Key** (starts with `pk-lf-`) and **Secret Key** (starts with `sk-lf-`).
4. Export them in your shell (CloudShell or local terminal):

```bash
export LANGFUSE_PUBLIC_KEY="pk-lf-..."
export LANGFUSE_SECRET_KEY="sk-lf-..."
```

These will be picked up automatically by the base deployment script in the next step.

---

## Step 2 — Base infrastructure

Run the base deployment script. This deploys four CloudFormation stacks in order: VPC, Storage (S3 + DynamoDB), Main (SQS + SSM parameters including Langfuse keys), and Roles (IAM).

```bash
bash scripts/infra-scripts/deploy_base.sh [BASE_NAME] [REGION]
# Defaults: BASE_NAME=kyc-agent, REGION=us-east-1
```

The Langfuse public and secret keys exported in Step 1 are written to SSM at `/langfuse/public_key` and `/langfuse/secret_key`.

Stacks deployed:
- `kyc-agent-vpc`
- `kyc-agent-storage`
- `kyc-agent-main`
- `kyc-agent-roles`

---

## Step 3 — Mock service pipeline

Deploys the Elastic Beanstalk mock service used by the AgentCore crew during development and testing.

Edit `scripts/infra-scripts/setup_mock_service_pipeline.sh` and set your `GITHUB_CONNECTION_ARN`, then run:

```bash
bash scripts/infra-scripts/setup_mock_service_pipeline.sh
```

Stack deployed: `kyc-agent-mock-service-pipeline`  
This pipeline manages: `kyc-mock-service-eb`

Wait for the pipeline to run and the mock service EB environment to reach a healthy state before proceeding.

---

## Step 4 — AgentCore pipeline

Builds the `crew/` Docker image, pushes it to ECR, and deploys the Bedrock AgentCore runtime.

Edit `scripts/infra-scripts/setup_agentcore_pipeline.sh` and confirm the hardcoded values (GitHub connection ARN, repo, branch), then run:

```bash
bash scripts/infra-scripts/setup_agentcore_pipeline.sh
```

Stack deployed: `kyc-agent-pipeline`  
This pipeline manages: `kyc-agent-agentcore-runtime`

**Wait for the pipeline to finish and `kyc-agent-agentcore-runtime` to reach `CREATE_COMPLETE` or `UPDATE_COMPLETE` before proceeding to Step 6.**

---

## Step 5 — API pipeline

Packages `backend/` as a Lambda zip and deploys the REST API stack. Can be run in parallel with Step 4.

Edit `scripts/infra-scripts/setup_api_pipeline.sh` and confirm the hardcoded values, then run:

```bash
bash scripts/infra-scripts/setup_api_pipeline.sh
```

Stack deployed: `kyc-agent-api-pipeline`  
This pipeline manages: `kyc-agent-api`

Wait for the pipeline to finish and `kyc-agent-api` to reach a stable state before proceeding to Step 7.

---

## Step 6 — Lambda pipeline

Packages `lambda/` and deploys the SQS-triggered KYC processor Lambda. **Requires the AgentCore stack from Step 4 to be fully deployed** — the script reads the `AgentRuntimeArn` output automatically and will exit with an error if the stack is not stable.

```bash
bash scripts/infra-scripts/setup_lambda_pipeline.sh
```

Stack deployed: `kyc-agent-lambda-pipeline`  
This pipeline manages: `kyc-agent-lambda`

---

## Step 7 — UI pipeline

Deploys the CloudFront + S3 frontend infrastructure and the CodePipeline that builds and syncs the React app on every push. **Requires `kyc-agent-api` (Step 5) to be deployed** — the script reads the API URL at build time.

Optionally set a custom domain:

```bash
# Optional: provide your ACM certificate and custom domain
export ACM_CERTIFICATE_ARN=arn:aws:acm:us-east-1:<account>:certificate/<id>
export CUSTOM_DOMAIN_NAME=kyc.example.com

bash scripts/infra-scripts/setup_ui_pipeline.sh
```

Stacks deployed: `kyc-agent-ui`, `kyc-agent-ui-pipeline`

---

## Deployment order summary

```
Step 1: Get Langfuse API keys → export LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY
           ↓
Step 2: deploy_base.sh              (writes keys to SSM)
           ↓
Step 3: setup_mock_service_pipeline.sh   (wait for EB to be healthy)
           ↓
Step 4: setup_agentcore_pipeline.sh      (wait for agentcore-runtime stack)
Step 5: setup_api_pipeline.sh            (can run in parallel with Step 4)
           ↓
Step 6: setup_lambda_pipeline.sh         (needs Step 4 complete)
Step 7: setup_ui_pipeline.sh             (needs Step 5 complete)
```

---

## Updating stacks after initial setup

For the pipeline-managed stacks (`agentcore-runtime`, `api`, `lambda`, `ui`), **do not redeploy them directly** — push code to the configured GitHub branch and the relevant CodePipeline will handle it automatically.

To update pipeline infrastructure or pass-through parameters (e.g. `AgentArn`, Langfuse keys), re-run the corresponding `setup_*_pipeline.sh` script with updated values.