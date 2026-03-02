#!/bin/bash
# Package the KYC agent for Bedrock AgentCore deployment.
# Creates a zip with the structure expected by the Dockerfile:
#   - Dockerfile (at root, for docker build)
#   - requirements.txt (at root)
#   - crew/ (Python package with all agent code)
#
# The CMD runs: opentelemetry-instrument python -m crew.research_crew
# so Python needs the crew package at the working directory (/app).

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# If no files match a glob, expand to nothing instead of literal "crew/*"
shopt -s nullglob 2>/dev/null || true

TIMESTAMP=$(date +%s)
ZIP_NAME="agent-source-${TIMESTAMP}.zip"
TEMP_DIR=$(mktemp -d 2>/dev/null || echo "/tmp/package_agent_$$")
trap "rm -rf $TEMP_DIR" EXIT

echo "Packaging agent for Bedrock AgentCore..." >&2
echo "  Temp dir: $TEMP_DIR" >&2

# Copy Dockerfile and requirements.txt to build root
cp crew/Dockerfile "$TEMP_DIR/" || { echo "Error: failed to copy crew/Dockerfile" >&2; exit 1; }
cp crew/requirements.txt "$TEMP_DIR/" || { echo "Error: failed to copy crew/requirements.txt" >&2; exit 1; }

# Copy crew package (exclude Dockerfile, requirements.txt, venv, cache)
mkdir -p "$TEMP_DIR/crew"
echo "  Copying crew/..." >&2
for item in crew/*; do
  [ -e "$item" ] || [ -L "$item" ] || continue
  case "$(basename "$item")" in
    Dockerfile|requirements.txt|venv|.venv|__pycache__) ;;
    *)
      cp -r "$item" "$TEMP_DIR/crew/" || { echo "Error: failed to copy $item" >&2; exit 1; }
      ;;
  esac
done
find "$TEMP_DIR/crew" -type f -name "*.pyc" -delete 2>/dev/null || true

# Create zip (use zip if available, else Python - works on Windows without zip installed)
# Python writes to cwd (temp dir) then we move it, so we never pass Git Bash paths to Python
echo "  Creating zip..." >&2
cd "$TEMP_DIR"
if command -v zip >/dev/null 2>&1; then
  zip -r "$SCRIPT_DIR/$ZIP_NAME" . -x "*.DS_Store" || { echo "Error: zip failed" >&2; exit 1; }
else
  python -c "
import zipfile, pathlib
p = pathlib.Path('.')
with zipfile.ZipFile('_agent_package.zip', 'w', zipfile.ZIP_DEFLATED) as zf:
    for f in sorted(p.rglob('*')):
        if f.is_file() and '.DS_Store' not in str(f) and f.name != '_agent_package.zip':
            zf.write(f, f.as_posix())
" || { echo "Error: python zip failed" >&2; exit 1; }
  mv "$TEMP_DIR/_agent_package.zip" "$SCRIPT_DIR/$ZIP_NAME" || { echo "Error: failed to move zip" >&2; exit 1; }
fi
cd "$SCRIPT_DIR"

echo "  Created: $ZIP_NAME" >&2
echo "  Contents: Dockerfile, requirements.txt, crew/" >&2
echo "$ZIP_NAME"
