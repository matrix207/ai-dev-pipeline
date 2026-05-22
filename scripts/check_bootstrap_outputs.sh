#!/usr/bin/env bash
set -euo pipefail

required=(
  "workspace/tasks/bootstrap-001/analysis/project_context.yaml"
  "workspace/tasks/bootstrap-001/architecture/mvp_architecture.md"
  "workspace/tasks/bootstrap-001/design/mvp_system_design.yaml"
  "workspace/tasks/bootstrap-001/review/design_review.json"
  "workspace/tasks/bootstrap-001/final/next_dev_tasks.yaml"
)

missing=0
for file in "${required[@]}"; do
  if [ ! -f "$file" ]; then
    echo "MISSING: $file"
    missing=1
  else
    echo "OK: $file"
  fi
done

exit "$missing"
