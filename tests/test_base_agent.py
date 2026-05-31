from __future__ import annotations

import pytest

from agents import AgentResult, BaseAgent


class EchoAgent(BaseAgent):
    def handle(self, payload):
        return {"received": payload, "ok": True}


def test_base_agent_returns_structured_result() -> None:
    agent = EchoAgent("echo")

    result = agent.run({"task_id": "dev-001"})

    assert result == AgentResult(
        agent_name="echo",
        status="success",
        output={"received": {"task_id": "dev-001"}, "ok": True},
    )


def test_base_agent_requires_non_empty_name() -> None:
    with pytest.raises(ValueError, match="name"):
        EchoAgent(" ")


def test_base_agent_requires_mapping_input() -> None:
    agent = EchoAgent("echo")

    with pytest.raises(TypeError, match="payload"):
        agent.run(["not", "structured"])  # type: ignore[arg-type]


def test_base_agent_requires_mapping_output() -> None:
    class BadAgent(BaseAgent):
        def handle(self, payload):
            return ["not", "structured"]

    with pytest.raises(TypeError, match="output"):
        BadAgent("bad").run({"task_id": "dev-001"})
