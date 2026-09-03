#!/usr/bin/env bash
set -euo pipefail

if [ ! -d ".venv" ]; then
  echo "Missing .venv — run: uv sync"
  exit 1
fi

uv run agentdevstu-web --port 8000 --reload
