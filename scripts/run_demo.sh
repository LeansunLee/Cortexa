#!/usr/bin/env bash
set -euo pipefail

if [ ! -d ".venv" ]; then
  echo "Missing .venv — run: uv sync"
  exit 1
fi

if [ ! -f ".env" ]; then
  echo "Missing .env — copy .env.example and fill OPENAI_API_KEY"
  exit 1
fi

uv run cortexa --goal "Research LangGraph and draft a short multi-agent project outline using search, RAG, and a simple exec helper"
