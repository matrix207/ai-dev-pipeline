# AI 开发流水线项目 / ai-dev-pipeline

本项目用于搭建一个务实、可演进的多 Agent AI 开发流水线，并用这条流水线逐步分析、设计和开发项目自身。

当前阶段：`dev-002` 已实现，等待自动代码评审和人工合并门；下一步是 `dev-003` 本地编排脚本。

## 项目目标

- 以结构化产物记录项目分析、架构设计、系统设计、评审和开发任务。
- 让 Agent 生成与评审职责分离，保留聚焦目标、风险和主线变更的人工审批质量门。
- 人定义目标和理想效果；Agent 负责设计、开发、测试验证和自动评审。
- 优先实现可运行的本地 MVP，再逐步扩展 Agent 能力、任务编排和持久化能力。
- 默认使用中文描述面向人的文档、Prompt、任务说明和协作规则，必要英文术语如 Agent、Prompt、MVP、PR、API、CLI 保留。

## 第一轮任务

```bash
./scripts/run_codex_bootstrap.sh
```

`bootstrap-001` 的预期产物：

- `workspace/tasks/bootstrap-001/analysis/project_context.yaml`
- `workspace/tasks/bootstrap-001/architecture/mvp_architecture.md`
- `workspace/tasks/bootstrap-001/design/mvp_system_design.yaml`
- `workspace/tasks/bootstrap-001/review/design_review.json`
- `workspace/tasks/bootstrap-001/final/next_dev_tasks.yaml`

## 后续开发

第一批开发任务从 `workspace/tasks/bootstrap-001/final/next_dev_tasks.yaml` 读取。每个开发任务都应保持范围小、可测试、可评审，并把中间产物保存在 `workspace/tasks/{task_id}/` 下。
