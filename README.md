# KYC Agents

## Setup

### Option 1: Using uv

[uv](https://github.com/astral-sh/uv) is a fast Python package installer and resolver.

1. **Install uv** (if not already installed):

   **Windows (PowerShell):**
   ```powershell
   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
   ```

   **macOS/Linux:**
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. **Create a virtual environment:**

   From the project root:
   ```bash
   cd crew
   # Python 3.10+ is required (CrewAI currently requires <=3.13).
   # On macOS, /usr/bin/python3 is often 3.9.x, so explicitly pick a newer Python.
   uv python install 3.13
   uv venv --python 3.13
   ```

3. **Activate the environment:**

   **Windows (PowerShell):**
   ```powershell
   .\.venv\Scripts\Activate.ps1
   ```

   **Windows (cmd):**
   ```cmd
   .\.venv\Scripts\activate.bat
   ```

   **macOS/Linux:**
   ```bash
   source .venv/bin/activate
   ```

   **Windows (Git Bash):**
   ```bash
   source .venv/Scripts/activate
   ```

4. **Install requirements:**

   ```bash
   uv pip install -r requirements.txt
   ```


### Requirements

Dependencies are listed in `crew/requirements.txt`.

If dependency resolution fails with a message like "current Python version (3.9.x) does not satisfy Python>=3.10", recreate the venv with a newer interpreter:

```bash
cd crew
rm -rf .venv
uv python install 3.13
uv venv --python 3.13
source .venv/bin/activate
uv pip install -r requirements.txt
```

---

## Components

This repo contains multiple components with separate dependency sets. For Python components, prefer **one virtual environment per component** (`crew/.venv`, `backend/.venv`, etc.) to avoid dependency conflicts.

If `uv venv --python 3.13` fails because Python 3.13 isn’t available, run `uv python install 3.13` first.

### 1) Agent (CrewAI) — `crew/`

**Install & run locally** (from repo root):

```bash
cd crew
uv python install 3.13
uv venv --python 3.13
source .venv/bin/activate
uv pip install -r requirements.txt

# run
python -m crew.kyc_app
```

**Local testing (publish a case)**

With the `crew/.venv` activated, you can push a test case to DynamoDB + SQS using the publisher:

```bash
cd ../utils
python kyc_publisher.py
```

Expected output:

```
OK: case pushed to DynamoDB and SQS
```

**Environment variables** (export them or put them in a `.env` file):
- `OPENAI_API_KEY` – required for the screening analysis LLM
- `TAVILY_API_KEY` – required for web search
- Optional: `KYC_CASES_TABLE` (DynamoDB table name, default `kyc-cases`), `KYC_RESULTS_BUCKET` (S3 bucket for reports, default `kyc-results`)

**Tavily key**:

```bash
export TAVILY_API_KEY=your-api-key
```

### 2) Lambda processor — `lambda/`

For deployment, `scripts/deploy.sh` packages `lambda/` and deploys it via CloudFormation. You typically **don’t need a local venv** for the lambda unless you want to run/debug it locally.

Optional local install (from repo root):

```bash
cd lambda
uv venv --python 3.13
source .venv/bin/activate
uv pip install -r requirements.txt
```

### 3) Backend API (FastAPI) — `backend/`

Local dev (from repo root):

```bash
cd backend
uv venv --python 3.13
source .venv/bin/activate
uv pip install -r requirements.txt

python -m uvicorn main:app --reload --port 8000
```

### 4) Frontend (Vite + React) — `frontend/`

Local dev (from repo root):

```bash
cd frontend
npm install
npm run dev
```

By default the UI calls `http://localhost:8000`. To point the UI at a deployed API, set `VITE_API_BASE_URL`, for example:

```bash
VITE_API_BASE_URL=https://your-api.example.com npm run dev
```

---

## Deploy (scripts)

Deployment is automated via shell scripts in `scripts/`. On macOS/Linux you may need to mark them as executable.

```bash
cd scripts
# Mark all shell scripts executable (deploy.sh calls other scripts like package_agent.sh)
chmod +x *.sh

# 1) Deploy base infrastructure (VPC, storage, IAM roles, main resources)
./deploy-base.sh

# 2) Deploy mock-service (Elastic Beanstalk) — used by the agent as MOCK_SERVICE_URL (base URL)
./deploy_mock_service.sh

# 3) Deploy agent runtime, lambdas, API, and UI (uses default region us-east-1)
./deploy.sh
```

To enable Langfuse/OTEL integration during deploy (and apply the runtime env update), first ensure the following SSM Parameter Store parameters exist in AWS:

| Parameter | Type | Description |
|---|---|---|
| `/langfuse/host` | String | Langfuse server URL |
| `/langfuse/project_name` | String | Langfuse project name |
| `/langfuse/public_key` | String | Langfuse public API key |
| `/langfuse/secret_key` | SecureString | Langfuse secret API key |

Then run:

```bash
export LANGFUSE_ENABLED=1
./deploy.sh
```

Notes:
- Requires `aws` CLI configured with credentials/permissions to deploy CloudFormation and related resources.
- If you prefer not to `chmod`, you can run: `bash deploy-base.sh` and `bash deploy.sh`.

---

## CI/CD Pipeline Setup (one-time, admin only)

> **Run these steps once** when setting up a new environment. After this, every push to `main` automatically builds and deploys the agent — no manual steps needed.

### Prerequisites

- A GitHub CodeConnections connection in AWS must exist and be in `Available` status.
  Create one in the AWS Console under **Developer Tools → Settings → Connections**.
  Note the connection ARN once available.

### Step 1 — Deploy the roles stack

The pipeline requires two new IAM roles (`CodePipelineRole`, `CloudFormationDeployRole`).
Pass `PipelineStackName` so the roles are scoped to the correct artifact bucket:

```bash
aws cloudformation deploy \
  --stack-name kyc-roles \
  --template-file templates/base/roles-stack.yaml \
  --parameter-overrides \
      StackName=kyc-roles \
      BaseStackName=kyc-base \
      PipelineStackName=kyc-pipeline \
  --capabilities CAPABILITY_NAMED_IAM
```

### Step 2 — Deploy the pipeline stack

```bash
aws cloudformation deploy \
  --stack-name kyc-agent-pipeline \
  --template-file templates/pipeline-stack.yaml \
  --parameter-overrides \
      GitHubConnectionArn=arn:aws:codeconnections:us-east-1:926529379586:connection/ce0bf520-65e4-4687-9f8c-9d25aa9e62ef \
      GitHubRepo=karthiknav/kyc-agents \
      GitHubBranch=agent_network \
      RolesStackName=kyc-agent-roles \
      AgentcoreStackName=kyc-agent-agentcore-runtime \
      KycCasesTableName=kyc-agent-storage-kyc-cases-926529379586-us-east-1 \
      KycResultsBucketName=kyc-agent-storage-926529379586-us-east-1 \
      MockServiceUrl=http://mock-service-env.eba-mbm8enda.us-east-1.elasticbeanstalk.com \
  --capabilities CAPABILITY_NAMED_IAM
```

#### Deploy the API pipeline stack

```bash
aws cloudformation deploy \
   --stack-name kyc-agent-api-pipeline \
   --template-file templates/api-pipeline-stack.yaml \
   --parameter-overrides \
             GitHubConnectionArn=arn:aws:codeconnections:us-east-1:926529379586:connection/ce0bf520-65e4-4687-9f8c-9d25aa9e62ef \
             GitHubRepo=karthiknav/kyc-agents \
             GitHubBranch=main \
             RolesStackName=kyc-agent-roles \
             ApiStackName=kyc-agent-api \
             KycInitiatedQueueName=kyc-agent-main-kyc-initiated \
             KycCasesTableName=kyc-agent-storage-kyc-cases-926529379586-us-east-1 \
             KycResultsBucketName=kyc-agent-storage-926529379586-us-east-1 \
   --capabilities CAPABILITY_NAMED_IAM
```

Once this completes, the pipeline triggers automatically and deploys `kyc-agentcore` for the first time.
All subsequent deployments happen on every push to `main` — no further manual action required.


#### Deploy the UI pipeline stack

```bash
aws cloudformation deploy \
   --stack-name kyc-agent-ui-pipeline \
   --template-file templates/ui-pipeline-stack.yaml \
   --parameter-overrides \
             GitHubConnectionArn=arn:aws:codeconnections:us-east-1:926529379586:connection/ce0bf520-65e4-4687-9f8c-9d25aa9e62ef \
             GitHubRepo=karthiknav/kyc-agents \
             GitHubBranch=agent_network \
             RolesStackName=kyc-agent-roles \
             UiStackName=kyc-agent-ui \
             AgentPipelineStackName=kyc-agent-pipeline \
             ApiStackName=kyc-agent-api \
   --capabilities CAPABILITY_NAMED_IAM
```
