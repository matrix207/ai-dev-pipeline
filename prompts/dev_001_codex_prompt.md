You are Codex running inside the `ai-dev-pipeline` repository.

Read:

- `AGENTS.md`
- `workspace/tasks/bootstrap-001/final/next_dev_tasks.yaml`
- `workspace/tasks/bootstrap-001/design/mvp_system_design.yaml`

Task: implement dev-001 only.

Expected scope:

- Create a minimal `agents/base_agent.py`.
- Create artifact read/write helpers.
- Create a local mock model/client abstraction if needed.
- Add tests under `tests/`.
- Do not call external model APIs yet.
- Do not implement all agents yet.

Acceptance:

- `python -m pytest` passes.
- Code is small and readable.
- No secrets are introduced.
- All paths are relative to repository root.
