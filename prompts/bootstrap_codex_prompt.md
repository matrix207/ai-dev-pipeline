你是 Codex，正在 `ai-dev-pipeline` 仓库内运行。

请先读取：

- `AGENTS.md`
- `workspace/tasks/bootstrap-001/input/project_brief.yaml`
- `config/pipeline.yaml`

任务：完成本项目的初始自举分析、MVP 架构设计、MVP 系统设计和设计评审。

只创建或更新以下文件：

1. `workspace/tasks/bootstrap-001/analysis/project_context.yaml`
2. `workspace/tasks/bootstrap-001/architecture/mvp_architecture.md`
3. `workspace/tasks/bootstrap-001/design/mvp_system_design.yaml`
4. `workspace/tasks/bootstrap-001/review/design_review.json`
5. `workspace/tasks/bootstrap-001/final/next_dev_tasks.yaml`

要求：

- 保持 MVP 小而可运行。
- 暂时不要构建 Web UI 或移动端 App。
- 不要添加 API key 或 secret。
- 只使用相对路径。
- `next_dev_tasks.yaml` 应包含小型开发任务，例如：
  - dev-001：基础 Agent 抽象和产物 I/O
  - dev-002：任务状态管理器
  - dev-003：本地编排脚本
  - dev-004：设计评审 Agent 骨架
  - dev-005：编码 Agent 骨架
- 为每个任务添加清晰的验收标准。
- 如果做出假设，必须显式写出。
- 不要运行破坏性命令。

写入文件后，总结创建的内容，并列出人类下一步应运行的命令。
