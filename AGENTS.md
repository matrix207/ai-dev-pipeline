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

## 编码规范

1. 新功能必须先补充或更新用例，再实现代码，用测试验证驱动开发。
2. Python 代码优先保持小函数、小模块，单个函数只承担一个清晰职责。
3. 代码、脚本和配置中的关键逻辑必须有必要且合理的中文说明，避免无意义注释。
4. 面向人的错误、日志、任务说明和评审结论默认使用中文。
5. 所有文件读写优先使用仓库已有 `artifacts`、`tasks` 等结构化工具。
6. 不在业务逻辑中硬编码绝对路径、密钥、个人环境或外部服务地址。
7. 自动化脚本必须支持失败可诊断，保留错误信息、关键输入和输出产物路径。
8. 变更应保持可回滚、可评审，避免混入无关重构。
9. 新增功能完成前必须运行相关用例；影响公共流程时运行全量测试。

## 产物规则

为 `bootstrap-001` 生成产物时，只写入以下文件：

- `workspace/tasks/bootstrap-001/analysis/project_context.yaml`
- `workspace/tasks/bootstrap-001/architecture/mvp_architecture.md`
- `workspace/tasks/bootstrap-001/design/mvp_system_design.yaml`
- `workspace/tasks/bootstrap-001/review/design_review.json`
- `workspace/tasks/bootstrap-001/final/next_dev_tasks.yaml`

实现 `dev-001` 时，只编写小型、可测试的 Python 模块。
