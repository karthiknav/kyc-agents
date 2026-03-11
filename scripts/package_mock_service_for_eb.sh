#!/usr/bin/env bash
# Package mock-service for Elastic Beanstalk: build TypeScript and zip dist/, mocks/, config.
# Run from repo root. Writes mock-service/deploy.zip.
# Usage: ./scripts/package_mock_service_for_eb.sh

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
MOCK_SERVICE_DIR="$REPO_ROOT/mock-service"
OUT_ZIP="${1:-$MOCK_SERVICE_DIR/deploy.zip}"

cd "$MOCK_SERVICE_DIR"
echo "Building TypeScript in mock-service..."
# Full install so devDependencies (typescript, tsc) are available for build. Use install not ci to avoid EPERM on Windows.
npm install
npm run build

echo "Creating deployment package: $OUT_ZIP"
rm -f "$OUT_ZIP"

if command -v zip >/dev/null 2>&1; then
  zip -r "$OUT_ZIP" \
    dist \
    mocks \
    package.json \
    package-lock.json \
    Procfile \
    .ebextensions \
    -x "*.git*" -x "*.DS_Store"
else
  # Windows often doesn't have zip; use Node (archiver is in devDependencies)
  node -e "
const archiver = require('archiver');
const fs = require('fs');
const path = require('path');
const out = path.resolve('deploy.zip');
const output = fs.createWriteStream(out);
const archive = archiver('zip', { zlib: { level: 9 } });
archive.pipe(output);
archive.directory('dist', 'dist');
archive.directory('mocks', 'mocks');
archive.file('package.json', { name: 'package.json' });
archive.file('package-lock.json', { name: 'package-lock.json' });
archive.directory('.ebextensions', '.ebextensions');
archive.file('Procfile', { name: 'Procfile' });
archive.finalize();
output.on('close', () => console.log('Done. deploy.zip is at', out));
archive.on('error', (err) => { console.error(err); process.exit(1); });
  "
  [ "$OUT_ZIP" = "$MOCK_SERVICE_DIR/deploy.zip" ] || mv -f "$MOCK_SERVICE_DIR/deploy.zip" "$OUT_ZIP"
fi

echo "Done. deploy.zip is at $OUT_ZIP"
