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

git status --short

echo "Creating pre-Codex checkpoint commit if possible..."
git add .
git commit -m "chore: bootstrap project scaffold before codex" || true

echo "Starting Codex bootstrap task..."
codex "$(cat prompts/bootstrap_codex_prompt.md)"

echo "Codex finished. Review artifacts under workspace/tasks/bootstrap-001/"
git status --short
