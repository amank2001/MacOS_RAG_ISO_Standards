#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$ROOT/.venv"

if [ ! -d "$VENV" ]; then
  python3 -m venv "$VENV"
fi

source "$VENV/bin/activate"
pip install -q -r "$ROOT/requirements.txt"

echo "Python indexer environment ready at $VENV"
