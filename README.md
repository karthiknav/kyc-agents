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
python -m crew.research_crew
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

# 2) Deploy agent runtime, lambdas, API, and UI (uses default region us-east-1)
./deploy.sh 
```

Notes:
- Requires `aws` CLI configured with credentials/permissions to deploy CloudFormation and related resources.
- If you prefer not to `chmod`, you can run: `bash deploy-base.sh` and `bash deploy.sh`.
