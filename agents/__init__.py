"""Agent abstractions for the local AI development pipeline."""

from agents.base_agent import AgentResult, BaseAgent
from agents.design_reviewer_agent import DesignReviewerAgent

__all__ = ["AgentResult", "BaseAgent", "DesignReviewerAgent"]
