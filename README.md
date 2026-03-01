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

2. **Create a virtual environment and install dependencies:**

   From the project root:
   ```bash
   cd crew
   uv venv
   uv pip install -r requirements.txt
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

---

### Option 2: Using venv only

Python’s built-in `venv` module:

1. **Create a virtual environment** (from the `crew` directory):

   ```bash
   cd crew
   python -m venv .venv
   ```

2. **Activate the environment:**

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

3. **Install requirements:**

   ```bash
   pip install -r requirements.txt
   ```

---

### Requirements

Dependencies are listed in `crew/requirements.txt`. After setup, run your scripts with the virtual environment activated.

---

## Running the agent locally

Run the KYC screening agent from the **project root** (`kyc-agents`):

1. **Activate the virtual environment** (from the project root, if the venv is in `crew/`):

   **Windows (PowerShell):**
   ```powershell
   crew\.venv\Scripts\Activate.ps1
   ```

   **macOS/Linux:**
   ```bash
   source crew/.venv/bin/activate
   ```

2. **Set environment variables** (or use a `.env` file in the project root):
   - `OPENAI_API_KEY` – required for the screening analysis LLM
   - `TAVILY_API_KEY` – required for web search
   - Optional: `KYC_CASES_TABLE` (DynamoDB table name, default `kyc-cases`), `KYC_RESULTS_BUCKET` (S3 bucket for reports, default `kyc-results`)

   For local runs without AWS SSM, create a `.env` with these keys or export them in your shell.

3. **Run the agent:**

   From the project root:
   ```bash
   python -m crew.research_crew
   ```

   This runs a local test with a default payload (`caseId: "01HR9B5J7Z6J7PD5B6PKQJ2MM4"`). To use a different case ID, edit the payload in `crew/research_crew.py`.

---

### Tavily Search (API key)

The crew uses [Tavily](https://tavily.com) for web search. Set your API key before running:

```bash
export TAVILY_API_KEY=your-api-key
```

Get a key at [app.tavily.com](https://app.tavily.com).
