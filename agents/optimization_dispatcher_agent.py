"""Dispatch an open optimization task to a local Agent."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from agents import BaseAgent, CoderAgent
from agents.optimization_executor_agent import DEFAULT_OPTIMIZATION_TASKS_PATH, OptimizationExecutorAgent


class OptimizationDispatcherAgent(BaseAgent):
    """Select an optimization task and dispatch it to the recommended local Agent."""

    def __init__(self, name: str = "optimization-dispatcher") -> None:
        super().__init__(name)

    def handle(self, payload: dict[str, Any]) -> Mapping[str, Any]:
        repo_root = Path(payload.get("repo_root", "."))
        tasks_path = payload.get("tasks_path", DEFAULT_OPTIMIZATION_TASKS_PATH)
        risk_approved = bool(payload.get("risk_approved", False))

        execution = OptimizationExecutorAgent().run(
            {
                "repo_root": str(repo_root),
                "tasks_path": tasks_path,
                "risk_approved": risk_approved,
            }
        ).output
        if not execution.get("execution_allowed"):
            return {
                "status": execution["status"],
                "selected_task": execution.get("selected_task"),
                "execution": execution,
                "dispatch_result": None,
                "blocking_issues": execution.get("blocking_issues", []),
            }

        selected_task = execution["selected_task"]
        recommended_agent = selected_task.get("recommended_agent")
        if recommended_agent == "CoderAgent":
            dispatch_result = CoderAgent().run(
                {
                    "repo_root": str(repo_root),
                    "task_id": selected_task["id"],
                    "tasks_path": tasks_path,
                }
            ).output
        else:
            return {
                "status": "blocked",
                "selected_task": selected_task,
                "execution": execution,
                "dispatch_result": None,
                "blocking_issues": [
                    {
                        "id": "unsupported_agent",
                        "severity": "medium",
                        "description": f"暂不支持调度 Agent：{recommended_agent}",
                        "recommendation": "为该 recommended_agent 增加本地调度适配。",
                    }
                ],
            }

        return {
            "status": "dispatched",
            "selected_task": selected_task,
            "execution": execution,
            "dispatch_result": dispatch_result,
            "blocking_issues": [],
        }
