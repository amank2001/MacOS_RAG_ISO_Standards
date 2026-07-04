#!/bin/bash
# End-to-end smoke test (requires Python deps and optional Ollama)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

source .venv/bin/activate

FIXTURES="$ROOT/tests/fixtures"
DB="$ROOT/tests/test_library.db"
FIGURES="$ROOT/tests/test_figures"
rm -rf "$DB" "$FIGURES" "$FIXTURES"
mkdir -p "$FIXTURES" "$FIGURES"

python3 tests/create_fixtures.py
PYTHONPATH="$ROOT" python3 isokb.py --db "$DB" --figures "$FIGURES" ingest "$FIXTURES" --no-embed
PYTHONPATH="$ROOT" python3 isokb.py --db "$DB" search "access control" --mode keyword
PYTHONPATH="$ROOT" python3 isokb.py --db "$DB" ask "What are the policies for information security?"

echo "Smoke test passed."
