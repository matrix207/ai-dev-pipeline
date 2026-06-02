# llm-agent-001 目标效果报告

## 目标效果

- 本地确定性 Agent 可以在配置允许时由 LLM wrapper 增强。
- 未配置或未启用 LLM 时，现有本地 Agent 行为保持不变。
- LLM 配置不允许把密钥写入仓库。
- 测试不依赖真实外部 LLM 服务。

## 当前达成

- 新增 `agents/llm_agent.py`，包含 `LLMConfig`、`LLMRequest`、`LLMResponse`、`LLMClient`、`StaticLLMClient` 和 `LLMAgent`。
- `scripts/run_local_task.py` 的 `coding_plan` step 支持 `llm_model` 配置。
- `config/pipeline.yaml` 新增 `coding_plan_mock` 和 `llm_coding_plan_demo` 示例。
- `README.md` 增加可配置 LLM Agent 使用说明。

## 验证结果

- `python -m pytest tests/test_llm_agent.py tests/test_run_local_task.py -q`：21 passed
- `python -m pytest -q`：115 passed

## 限制

- 当前只内置 `provider: mock` 离线客户端。
- `openai` 等真实 provider 尚未接入，启用前需要实现对应 `LLMClient`。
- 当前只把 `coding_plan` step 接入可选 LLM wrapper，其它 Agent 可复用同一机制逐步接入。
