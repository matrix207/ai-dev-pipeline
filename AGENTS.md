# AGENTS.md

## Project role

You are working inside `ai-dev-pipeline`, a project that builds a pragmatic, evolvable multi-agent AI development pipeline.

The project should eventually support:

- project analysis agent
- requirement analyst agent
- architecture analyst agent
- system design agent
- coder agent
- design reviewer agent
- code reviewer agent
- task orchestration
- artifact persistence
- human approval gates

## Current milestone

Current task: `bootstrap-001`.

Goal: use this project to analyze, design, and then gradually develop itself.

Do not overbuild. Prioritize a runnable MVP.

## Mandatory principles

1. Use structured artifacts.
2. Keep all paths relative to the repository root.
3. Preserve intermediate task outputs under `workspace/tasks/{task_id}/`.
4. Do not delete user files.
5. Do not introduce external services unless requested.
6. Do not hard-code API keys or secrets.
7. Prefer Python 3.10+.
8. Keep development tasks small and reviewable.
9. Generation and review responsibilities must be separated.
10. Human approval is required before PR/merge-related actions.

## Output rules

When producing artifacts for `bootstrap-001`, write exactly these files:

- `workspace/tasks/bootstrap-001/analysis/project_context.yaml`
- `workspace/tasks/bootstrap-001/architecture/mvp_architecture.md`
- `workspace/tasks/bootstrap-001/design/mvp_system_design.yaml`
- `workspace/tasks/bootstrap-001/review/design_review.json`
- `workspace/tasks/bootstrap-001/final/next_dev_tasks.yaml`

When implementing `dev-001`, write small, testable Python modules only.
