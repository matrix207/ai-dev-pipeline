# MVP 架构方案

## 目标

`ai-dev-pipeline` 的 MVP 目标是提供一个本地可运行的多 Agent 开发流水线骨架。它应能读取任务输入，调用明确职责的 Agent 或占位实现，写入结构化产物，并在关键步骤保留人工审批质量门。

## 架构原则

1. 本地优先：MVP 使用本地文件系统保存任务状态和产物，不依赖外部服务。
2. 结构化产物：Agent 之间通过 YAML、JSON 和 Markdown 产物交接。
3. 职责分离：生成型 Agent 与评审型 Agent 分离，避免同一职责自我确认。
4. 小步演进：先实现可运行 CLI 和基础抽象，再逐步扩展模型接入、编排策略和更多 Agent。
5. 可恢复：每个任务的输入、中间结果、评审和最终任务拆分都保存到 `workspace/tasks/{task_id}/`。
6. 人定目标，Agent 端到端执行：人负责目标、效果、范围和关键风险决策；Agent 负责设计、开发、测试、验证和互相评审。

## 人机职责边界

MVP 的人工质量门不是要求人逐行检查每个产物，而是在关键决策点确认方向和风险。人的职责应聚焦在：

- 目标门：确认任务要解决的问题、理想效果和验收标准。
- 范围门：确认本轮是否过度设计、是否遗漏必须能力。
- 风险门：确认架构、安全、secret、外部依赖和数据破坏风险是否可接受。
- 合并门：确认 commit、PR、merge 或 release 等主线变更是否可以执行。

Agent 的职责应覆盖从任务理解到产物生成的日常执行工作：

- 需求、架构、系统设计和开发任务拆分。
- 编码实现、单元测试和本地验证。
- 设计评审、代码评审和验收结果汇总。
- 将中间过程和最终结果写入 `workspace/tasks/{task_id}/`。

因此，编排器应默认让 Agent 持续推进到自动评审和测试验证完成；只有遇到目标确认、阻塞风险或主线变更时才停在人工质量门。

## MVP 模块

### Agent 层

- `agents/base_agent.py`：定义基础 Agent 接口、输入输出约定和运行结果。
- 后续 Agent 骨架包括 project analyst、architecture analyst、system design、design reviewer 和 coder。
- 初期允许使用 mock model/client，避免在 MVP 阶段绑定外部模型 API。

### 产物层

- 产物根目录为 `workspace/tasks`。
- 每个任务使用 `workspace/tasks/{task_id}/` 保存输入、分析、设计、评审和最终输出。
- 读写逻辑应集中在小型 helper 模块中，避免各 Agent 自行拼接路径。

### 状态层

- 任务状态使用本地 JSON 或 YAML 保存。
- 状态至少包含 task id、当前步骤、执行状态、产物路径、错误信息和质量门状态。
- 质量门状态应能表达 `goal_approved`、`design_review_passed`、`tests_passed`、`code_review_passed`、`human_merge_approved` 等关键检查点。
- 状态管理只负责记录和读取，不承担 Agent 业务逻辑。

### 编排层

- 本地 CLI 或脚本按固定步骤执行 MVP workflow。
- 编排器负责加载配置、创建任务目录、调用 Agent、写入状态、停在人工质量门。
- MVP 不需要复杂调度、并发执行或远程队列。

### 评审层

- 设计评审 Agent 读取分析和设计产物，输出结构化评审报告。
- 代码评审 Agent 读取代码变更、测试结果和任务验收标准，输出结构化评审报告。
- 评审结果应包含结论、风险、阻塞问题、建议和是否允许继续编排。
- 未通过评审时，编排流程应停止并等待人工处理。

## 目录约定

- `config/pipeline.yaml`：流水线配置。
- `prompts/`：Agent 和任务使用的 Prompt。
- `workspace/tasks/{task_id}/input/`：任务输入。
- `workspace/tasks/{task_id}/analysis/`：项目分析产物。
- `workspace/tasks/{task_id}/architecture/`：架构产物。
- `workspace/tasks/{task_id}/design/`：系统设计产物。
- `workspace/tasks/{task_id}/review/`：评审产物。
- `workspace/tasks/{task_id}/final/`：最终交付和下一步任务。

## MVP 执行流程

1. 读取 `AGENTS.md`、`config/pipeline.yaml` 和任务输入。
2. 人确认任务目标、理想效果、范围和验收标准。
3. Agent 生成或读取项目上下文产物。
4. Agent 生成架构、系统设计或实现方案。
5. 评审 Agent 执行设计评审并写入评审报告。
6. 编码 Agent 实现小型开发任务。
7. 测试或验证 Agent 运行本地测试并记录结果。
8. 代码评审 Agent 自动评审变更与验收标准。
9. 如果自动评审可接受，输出下一步建议并等待人工合并门审批。

## 暂不实现

- Web UI 和移动端 App。
- 自动创建、合并或审批 PR。
- 多租户、权限系统和远程执行。
- 大规模 Agent 市场。
- 真实外部模型调用的完整适配层。

## 关键风险

- 如果任务状态和产物 schema 不稳定，后续 Agent 之间会难以复用。
- 如果编排器过早复杂化，会影响第一阶段交付速度。
- 如果缺少评审质量门，生成结果容易在后续开发中放大偏差。
