from __future__ import annotations

import pytest

from agents import BaseAgent
from agents.llm_agent import LLMConfig, LLMAgent, LLMRequest, StaticLLMClient


class LocalPlanAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__("local-plan")

    def handle(self, payload):
        return {
            "task_id": payload["task_id"],
            "title": "本地计划",
            "implementation_plan": [{"order": 1, "description": "本地步骤"}],
        }


def test_llm_config_rejects_inline_secret() -> None:
    with pytest.raises(ValueError, match="不能直接写入"):
        LLMConfig.from_mapping(
            {
                "enabled": True,
                "provider": "openai",
                "model": "gpt-test",
                "api_key": "sk-not-allowed",
            }
        )


def test_llm_agent_uses_local_agent_when_disabled() -> None:
    agent = LLMAgent(
        fallback_agent=LocalPlanAgent(),
        config=LLMConfig(enabled=False, provider="disabled", model=""),
    )

    result = agent.run({"task_id": "llm-agent-001"})

    assert result.output == {
        "task_id": "llm-agent-001",
        "title": "本地计划",
        "implementation_plan": [{"order": 1, "description": "本地步骤"}],
    }


def test_llm_agent_merges_static_llm_output() -> None:
    requests: list[LLMRequest] = []
    client = StaticLLMClient(
        {
            "title": "LLM 增强计划",
            "llm_notes": ["根据上下文补充架构风险。"],
        },
        captured_requests=requests,
    )
    agent = LLMAgent(
        fallback_agent=LocalPlanAgent(),
        config=LLMConfig(
            enabled=True,
            provider="mock",
            model="static-test",
            system_prompt="输出结构化实现计划。",
        ),
        client=client,
    )

    result = agent.run({"task_id": "llm-agent-001", "repo_root": "."})

    assert result.output["title"] == "LLM 增强计划"
    assert result.output["implementation_plan"] == [{"order": 1, "description": "本地步骤"}]
    assert result.output["llm_notes"] == ["根据上下文补充架构风险。"]
    assert result.output["llm"]["used"] is True
    assert result.output["llm"]["provider"] == "mock"
    assert result.output["llm"]["model"] == "static-test"
    assert requests[0].agent_name == "local-plan"
    assert requests[0].fallback_output["title"] == "本地计划"
