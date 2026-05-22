你是 Codex，正在 `ai-dev-pipeline` 仓库内运行。

请读取：

- `AGENTS.md`
- `workspace/tasks/bootstrap-001/final/next_dev_tasks.yaml`
- `workspace/tasks/bootstrap-001/design/mvp_system_design.yaml`

任务：只实现 `dev-001`。

预期范围：

- 创建最小化的 `agents/base_agent.py`。
- 创建产物读写辅助模块。
- 如有需要，创建本地 mock model/client 抽象。
- 在 `tests/` 下添加测试。
- 暂时不要调用外部模型 API。
- 暂时不要实现所有 Agent。

验收标准：

- `python -m pytest` 通过。
- 代码小而可读。
- 不引入 secret。
- 所有路径都相对仓库根目录。
