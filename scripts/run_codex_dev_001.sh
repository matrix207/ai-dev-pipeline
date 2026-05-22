#!/usr/bin/env bash
set -euo pipefail

if ! command -v codex >/dev/null 2>&1; then
  echo "Codex CLI not found. Install with: sudo npm install -g @openai/codex" >&2
  exit 1
fi

if [ ! -f AGENTS.md ]; then
  echo "Please run this script from the project root." >&2
  exit 1
fi

echo "Creating pre-dev-001 checkpoint commit if possible..."
git add .
git commit -m "chore: checkpoint before dev-001" || true

echo "Starting Codex dev-001 task..."
codex "$(cat prompts/dev_001_codex_prompt.md)"

echo "Running tests..."
python3 -m venv .venv || true
source .venv/bin/activate
pip install -e . pytest pyyaml pydantic
python -m pytest

echo "dev-001 finished. Review changes before committing."
git status --short
