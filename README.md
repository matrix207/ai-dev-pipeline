# AI 开发流水线项目 / ai-dev-pipeline

本项目用于搭建一个务实、可演进的多 Agent AI 开发流水线，并用这条流水线逐步分析、设计和开发项目自身。

当前阶段：验证反馈到优化任务的闭环已实现并收口；下一步是规划下一轮产品化增强。

## 项目目标

- 以结构化产物记录项目分析、架构设计、系统设计、评审和开发任务。
- 让 Agent 生成与评审职责分离，保留聚焦目标、风险和主线变更的人工审批质量门。
- 人定义目标和理想效果；Agent 负责设计、开发、测试验证和自动评审。
- 优先实现可运行的本地 MVP，再逐步扩展 Agent 能力、任务编排和持久化能力。
- 默认使用中文描述面向人的文档、Prompt、任务说明和协作规则，必要英文术语如 Agent、Prompt、MVP、PR、API、CLI 保留。

## 目标效果

- 交互式效果展示：[docs/demos/ai_dev_pipeline_demo.html](docs/demos/ai_dev_pipeline_demo.html)

## 项目架构预览

```text
config/pipeline.yaml          # 本地 workflow 编排配置
agents/                       # 各类 Agent 的最小本地实现
scripts/run_local_task.py     # 执行单个配置化 workflow
scripts/run_end_to_end.py     # 执行端到端验证、调度、评审和反馈闭环
artifacts/                    # 仓库相对路径的结构化产物读写工具
tasks/                        # 任务状态模型和持久化工具
workspace/tasks/{task_id}/    # 每个任务的输入、实现、评审、最终产物
tests/                        # 用例验证，新增功能要求用例先行
```

核心流向：

```text
目标/任务定义
  -> Agent 生成结构化产物
  -> 测试验证和代码评审
  -> 目标效果验证
  -> 反馈规划下一轮任务
  -> 人工审批质量门
```

## Agent 与现实岗位

| Agent | 现实岗位角色 | 主要职责 |
| --- | --- | --- |
| `ProjectAnalysisAgent` | 技术负责人 / 资深工程师 | 分析项目现状、上下文、已有约束和可复用能力。 |
| `RequirementAnalysisAgent` | 产品经理 / 业务分析师 | 澄清目标、范围、验收标准和非目标。 |
| `ArchitectAgent` | 架构师 / Tech Lead | 拆分模块边界、识别技术风险、给出架构方向。 |
| `SystemDesignAgent` | 系统设计工程师 / 方案设计负责人 | 将架构落成可实现的模块、接口和数据流设计。 |
| `DesignReviewerAgent` | 架构评审委员会 / 资深工程师 | 评审设计完整性、可实现性和是否过度设计。 |
| `CoderAgent` | 软件工程师 | 实现代码、脚本、配置和结构化实现计划。 |
| `TestValidatorAgent` | 测试工程师 / QA / 自动化测试工程师 | 运行测试命令并输出可诊断的验证结果。 |
| `CodeReviewerAgent` | Code Reviewer / 资深工程师 | 审查代码质量、风险、验收标准和 evidence。 |
| `GoalEffectValidatorAgent` | 验收负责人 / QA Lead / 产品验收 | 验证最终效果是否对齐目标和预期效果。 |
| `OptimizationPlannerAgent` | 项目经理 / 迭代计划负责人 | 根据验证反馈规划下一轮优化任务。 |
| `OptimizationExecutorAgent` | 交付经理 / Scrum Master | 判断任务是否可执行、是否命中风险或人工审批门。 |
| `OptimizationDispatcherAgent` | 工程经理 / 任务调度员 | 将 open 任务分配给合适的本地 Agent 并记录调度产物。 |

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

一个命令运行完整验证闭环并输出决策摘要：

```bash
python scripts/run_validation_loop.py
```

如需完整 JSON 输出：

```bash
python scripts/run_validation_loop.py --json
```

决策摘要会写入：

- `workspace/tasks/planning-002/final/decision_summary.yaml`

## 使用说明

准备环境：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

运行全量用例：

```bash
python -m pytest -q
```

预览端到端闭环，不写入任务产物：

```bash
python scripts/run_end_to_end.py --task-id workflow-004 --dry-run --rerun-policy skip_completed
```

正式运行端到端闭环，并记录运行 ID：

```bash
python scripts/run_end_to_end.py --task-id workflow-004 --rerun-policy skip_completed --run-id workflow-004-run
```

查看完整 JSON 摘要：

```bash
python scripts/run_end_to_end.py --task-id workflow-004 --rerun-policy skip_completed --run-id workflow-004-run --json
```

查看指定任务的历史运行记录：

```bash
python scripts/run_end_to_end.py --task-id workflow-009 --list-runs
python scripts/run_end_to_end.py --task-id workflow-009 --list-runs --json
```

人工审批运行记录。审批通过会把质量门状态改为 `approved`，并允许后续推进；审批拒绝会把状态改为 `rejected`，后续推进命令会返回阻塞：

```bash
python scripts/run_end_to_end.py \
  --task-id workflow-009 \
  --approve-run workflow-009-run \
  --approver dennis \
  --decision approved \
  --comment "同意进入下一阶段。"
```

拒绝审批示例：

```bash
python scripts/run_end_to_end.py \
  --task-id workflow-009 \
  --approve-run workflow-009-run \
  --approver dennis \
  --decision rejected \
  --comment "证据不足，需补充验证。"
```

审批后检查是否允许继续。`--continue-run` 只做推进前检查，不自动 merge，也不调用外部服务；通过时输出下一任务和推荐命令，阻塞时输出修正建议：

```bash
python scripts/run_end_to_end.py --task-id workflow-009 --continue-run workflow-009-run
python scripts/run_end_to_end.py --task-id workflow-009 --continue-run workflow-009-run --json
```

退出码语义：

- `0`：当前运行已审批通过，允许按推荐命令进入下一阶段。
- `1`：当前运行未审批、审批拒绝、质量门阻塞或 dry-run，不允许继续。

生成下一阶段优化任务执行计划：

```bash
python scripts/run_local_task.py --workflow optimization_execution --goal-approved
```

执行计划会写入：

- `workspace/tasks/planning-003/code/execution_plan.json`

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
