#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP_BUNDLE="${1:-$ROOT/build/ISOStandardsKB.app/Contents/Resources/indexer}"

mkdir -p "$APP_BUNDLE"
cp -R "$ROOT/indexer" "$APP_BUNDLE/"
cp "$ROOT/requirements.txt" "$APP_BUNDLE/"
cp "$ROOT/isokb.py" "$APP_BUNDLE/"

echo "Indexer bundled to $APP_BUNDLE"
echo "Note: Run scripts/setup.sh in the app bundle directory to create venv on first launch."
