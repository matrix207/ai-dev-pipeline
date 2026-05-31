"""Minimal base abstraction for local pipeline agents."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Mapping


StructuredData = dict[str, Any]


@dataclass(frozen=True)
class AgentResult:
    """Structured result returned by an agent run."""

    agent_name: str
    status: str
    output: StructuredData = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    metadata: StructuredData = field(default_factory=dict)


class BaseAgent(ABC):
    """Small base class for agents that transform structured input."""

    def __init__(self, name: str) -> None:
        if not name.strip():
            raise ValueError("Agent name must not be empty.")
        self.name = name

    def run(self, payload: Mapping[str, Any]) -> AgentResult:
        """Run the agent with structured input and return a structured result."""
        if not isinstance(payload, Mapping):
            raise TypeError("Agent payload must be a mapping.")

        output = self.handle(dict(payload))
        if not isinstance(output, Mapping):
            raise TypeError("Agent output must be a mapping.")

        return AgentResult(
            agent_name=self.name,
            status="success",
            output=dict(output),
        )

    @abstractmethod
    def handle(self, payload: StructuredData) -> Mapping[str, Any]:
        """Implement the agent-specific transformation."""
