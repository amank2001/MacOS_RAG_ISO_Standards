#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if [ ! -d ".venv" ]; then
  bash scripts/setup.sh
fi

source .venv/bin/activate
exec python3 isokb.py serve "$@"
