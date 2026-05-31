# AI 开发流水线项目 / ai-dev-pipeline

本项目用于搭建一个务实、可演进的多 Agent AI 开发流水线，并用这条流水线逐步分析、设计和开发项目自身。

当前阶段：自动化验证闭环已实现，等待人工合并门；下一步是基于验证反馈规划优化。

## 项目目标

- 以结构化产物记录项目分析、架构设计、系统设计、评审和开发任务。
- 让 Agent 生成与评审职责分离，保留聚焦目标、风险和主线变更的人工审批质量门。
- 人定义目标和理想效果；Agent 负责设计、开发、测试验证和自动评审。
- 优先实现可运行的本地 MVP，再逐步扩展 Agent 能力、任务编排和持久化能力。
- 默认使用中文描述面向人的文档、Prompt、任务说明和协作规则，必要英文术语如 Agent、Prompt、MVP、PR、API、CLI 保留。

## 目标效果

- 交互式效果展示：[docs/demos/ai_dev_pipeline_demo.html](docs/demos/ai_dev_pipeline_demo.html)

## 自动化验证

运行本地自动化验证闭环：

```bash
source .venv/bin/activate
python scripts/run_local_task.py --workflow automated_validation --goal-approved
```

验证流程会执行测试验证、代码评审和目标效果验证，并将反馈写入：

- `workspace/tasks/validation-001/review/test_validation.json`
- `workspace/tasks/validation-001/review/code_review.json`
- `workspace/tasks/validation-001/final/validation_feedback.json`

将验证反馈转换为下一轮优化任务：

```bash
python scripts/run_local_task.py --workflow optimization_planning --goal-approved
```

优化任务会写入：

- `workspace/tasks/optimization-001/final/next_optimization_tasks.yaml`

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
