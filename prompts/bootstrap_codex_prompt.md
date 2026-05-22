You are Codex running inside the `ai-dev-pipeline` repository.

Read first:

- `AGENTS.md`
- `workspace/tasks/bootstrap-001/input/project_brief.yaml`
- `config/pipeline.yaml`

Task: perform the initial project bootstrap analysis, architecture design, system design, and review for this project.

Create or update exactly these files:

1. `workspace/tasks/bootstrap-001/analysis/project_context.yaml`
2. `workspace/tasks/bootstrap-001/architecture/mvp_architecture.md`
3. `workspace/tasks/bootstrap-001/design/mvp_system_design.yaml`
4. `workspace/tasks/bootstrap-001/review/design_review.json`
5. `workspace/tasks/bootstrap-001/final/next_dev_tasks.yaml`

Requirements:

- Keep the MVP small and executable.
- Do not build a web UI or mobile app yet.
- Do not add API keys or secrets.
- Use relative paths only.
- Make `next_dev_tasks.yaml` contain small development tasks such as:
  - dev-001: base agent abstraction and artifact I/O
  - dev-002: task state manager
  - dev-003: local orchestrator script
  - dev-004: design reviewer agent skeleton
  - dev-005: coder agent skeleton
- Add clear acceptance criteria for every task.
- If you make assumptions, write them explicitly.
- Do not run destructive commands.

After writing files, summarize what you created and list the next command the human should run.
