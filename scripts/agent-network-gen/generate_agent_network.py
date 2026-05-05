"""
Generate agent-network.json by RAG-querying the crew/ codebase.

Usage (from repo root):
    cd scripts/agent-network-gen
    python -m venv .venv
    .venv/Scripts/pip install -r requirements.txt
    python generate_agent_network.py
"""

import json
import pathlib
import sys

from llama_index.core import SimpleDirectoryReader, VectorStoreIndex, Settings
from llama_index.embeddings.bedrock import BedrockEmbedding
from llama_index.llms.bedrock_converse import BedrockConverse

# ── Paths ─────────────────────────────────────────────────────────────────
SCRIPT_DIR = pathlib.Path(__file__).parent
REPO_ROOT   = SCRIPT_DIR.parent.parent          # kyc-agents/
CREW_DIR    = REPO_ROOT / "crew"
OUT_FILE    = REPO_ROOT / "frontend" / "src" / "agent-network.json"

if not CREW_DIR.exists():
    sys.exit(f"ERROR: crew/ directory not found at {CREW_DIR}")

# ── Models ────────────────────────────────────────────────────────────────
Settings.embed_model = BedrockEmbedding(model_name="amazon.titan-embed-text-v2:0")
Settings.llm = BedrockConverse(
    model="us.amazon.nova-pro-v1:0",
    max_tokens=4096,
    temperature=0,
)

# ── Load crew/ source files ───────────────────────────────────────────────
print(f"Reading {CREW_DIR} ...")
docs = SimpleDirectoryReader(
    input_dir=str(CREW_DIR),
    exclude_hidden=True,
    exclude=["__pycache__", ".venv", "venv", "*.pyc", "output"],
    required_exts=[".py", ".yaml", ".yml", ".toml"],
    recursive=True,
).load_data()
print(f"  {len(docs)} files loaded")

# ── Build in-memory RAG index ─────────────────────────────────────────────
print("Building index...")
index = VectorStoreIndex.from_documents(docs)
qe    = index.as_query_engine(similarity_top_k=8)
print("  Index ready")


# ── Helpers ───────────────────────────────────────────────────────────────
def ask(question: str) -> "dict | list":
    """Query the index; parse the LLM reply as JSON."""
    result = qe.query(
        f"{question}\n\nReply with valid JSON only. No explanation. No markdown."
    )
    text = str(result).strip()
    # Strip accidental code-fence wrappers
    for fence in ("```json", "```"):
        if text.startswith(fence):
            text = text[len(fence):]
        if text.endswith("```"):
            text = text[:-3]
    return json.loads(text.strip())


# ── Structured queries ────────────────────────────────────────────────────
print("Querying...")

manifest = {
    "agents": ask(
        "List every agent or autonomous unit in this codebase. "
        "Return a JSON array where each item has: "
        "id (snake_case), label (display name), role (one sentence), "
        "tools (list of tool/function names it can call), "
        "outputs (possible result values like APPROVED, MATCH, OK)."
    ),
    "flow": ask(
        "What is the execution order or graph between agents? "
        "Return a JSON array of edges, each with: "
        "from (agent id or START), to (agent id or END), "
        "label (optional — what triggers this edge)."
    ),
    "integrations": ask(
        "What external services, APIs, databases, or queues does this system use? "
        "Return a JSON array, each with: "
        "name, type (database/api/queue/storage/llm/search), "
        "used_by (list of agent ids)."
    ),
    "decision_logic": ask(
        "What conditions determine the final outcome? "
        "Return a JSON object with keys for each possible outcome "
        "and the condition that triggers it as the value."
    ),
    "metadata": ask(
        "What agent framework is used (CrewAI, LangGraph, AutoGen, custom etc)? "
        "Is execution sequential, parallel, or graph-based? "
        "What is the main entry point file? "
        "Return a JSON object with keys: framework, execution_model, entry_point."
    ),
}

# ── Write output ──────────────────────────────────────────────────────────
OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
OUT_FILE.write_text(json.dumps(manifest, indent=2))

print(f"\nDone — written to {OUT_FILE}")
print(f"  {len(manifest['agents'])} agents")
print(f"  {len(manifest['flow'])} flow edges")
