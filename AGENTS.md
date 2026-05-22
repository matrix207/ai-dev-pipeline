# AGENTS.md

## 项目角色

你正在 `ai-dev-pipeline` 仓库内工作。本项目用于构建一个务实、可演进的多 Agent AI 开发流水线。

项目最终应支持：

- 项目分析 Agent
- 需求分析 Agent
- 架构分析 Agent
- 系统设计 Agent
- 编码 Agent
- 设计评审 Agent
- 代码评审 Agent
- 任务编排
- 产物持久化
- 人工审批质量门

## 当前里程碑

当前任务：`bootstrap-001`。

目标：使用本项目分析、设计并逐步开发项目自身。

不要过度设计。优先交付可运行的 MVP。

## 强制原则

1. 使用结构化产物。
2. 所有路径保持相对仓库根目录。
3. 中间任务输出保存在 `workspace/tasks/{task_id}/` 下。
4. 不要删除用户文件。
5. 未经要求不要引入外部服务。
6. 不要硬编码 API key 或 secret。
7. 优先使用 Python 3.10+。
8. 开发任务必须小而可评审。
9. 生成职责和评审职责必须分离。
10. PR 或 merge 相关操作前必须获得人工审批。

## 产物规则

为 `bootstrap-001` 生成产物时，只写入以下文件：

- `workspace/tasks/bootstrap-001/analysis/project_context.yaml`
- `workspace/tasks/bootstrap-001/architecture/mvp_architecture.md`
- `workspace/tasks/bootstrap-001/design/mvp_system_design.yaml`
- `workspace/tasks/bootstrap-001/review/design_review.json`
- `workspace/tasks/bootstrap-001/final/next_dev_tasks.yaml`

实现 `dev-001` 时，只编写小型、可测试的 Python 模块。
