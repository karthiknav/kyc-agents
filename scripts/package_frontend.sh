#!/bin/bash
# Build the frontend (Vite/React) for deployment.
# Produces frontend/dist/ — deploy.sh uses this for S3 sync to the UI stack bucket.
# Usage: ./package_frontend.sh
# Output (stdout): absolute path to the dist directory (for deploy scripts).

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$SCRIPT_DIR/frontend"
DIST_DIR="$FRONTEND_DIR/dist"

if [ ! -f "$FRONTEND_DIR/package.json" ]; then
  echo "Error: frontend/package.json not found" >&2
  exit 1
fi

echo "Building frontend..." >&2
cd "$FRONTEND_DIR"
if [ -f "package-lock.json" ]; then
  npm ci --silent 2>/dev/null || npm install --silent
else
  npm install --silent
fi
# Use npx so vite is found on Windows when PATH doesn't include node_modules/.bin
npx vite build

if [ ! -d "$DIST_DIR" ]; then
  echo "Error: build did not produce $DIST_DIR" >&2
  exit 1
fi

echo "Frontend built: $DIST_DIR" >&2
echo "$DIST_DIR"
