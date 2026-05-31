"""Select the next optimization task and create an execution plan."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from agents import BaseAgent
from artifacts import read_yaml


DEFAULT_OPTIMIZATION_TASKS_PATH = "workspace/tasks/optimization-001/final/next_optimization_tasks.yaml"


class OptimizationExecutorAgent(BaseAgent):
    """Plan execution for the next not-yet-completed optimization task."""

    def __init__(self, name: str = "optimization-executor") -> None:
        super().__init__(name)

    def handle(self, payload: dict[str, Any]) -> Mapping[str, Any]:
        repo_root = Path(payload.get("repo_root", "."))
        tasks_path = payload.get("tasks_path", DEFAULT_OPTIMIZATION_TASKS_PATH)
        risk_approved = bool(payload.get("risk_approved", False))

        task_batch = read_yaml(repo_root, tasks_path)
        task = self._next_open_task(repo_root, task_batch.get("tasks", []))
        if task is None:
            return {
                "status": "no_open_tasks",
                "selected_task": None,
                "execution_allowed": False,
                "blocking_issues": [],
                "execution_plan": [],
            }

        blocking_issues = []
        human_gate = dict(task.get("human_gate", {}))
        if task.get("risk_level") == "high" and human_gate.get("risk_approval_required", True):
            if not risk_approved:
                blocking_issues.append(
                    {
                        "id": "risk_gate_required",
                        "severity": "high",
                        "description": "高风险任务需要人工风险审批。",
                        "recommendation": "确认风险后以 risk_approved=true 重新运行执行规划。",
                    }
                )

        execution_allowed = not blocking_issues
        return {
            "status": "ready" if execution_allowed else "blocked",
            "selected_task": {
                "id": task["id"],
                "title": task["title"],
                "priority": task.get("priority"),
                "recommended_agent": task.get("recommended_agent"),
                "risk_level": task.get("risk_level"),
                "human_gate": human_gate,
            },
            "execution_allowed": execution_allowed,
            "blocking_issues": blocking_issues,
            "execution_plan": self._execution_plan(task) if execution_allowed else [],
            "out_of_scope": task.get("out_of_scope", []),
            "acceptance_criteria": task.get("acceptance_criteria", []),
        }

    def _next_open_task(self, repo_root: Path, tasks: list[dict[str, Any]]) -> dict[str, Any] | None:
        priority_order = {"high": 0, "medium": 1, "low": 2}
        open_tasks = [
            task
            for task in tasks
            if not (repo_root / "workspace" / "tasks" / task["id"] / "state.json").exists()
        ]
        if not open_tasks:
            return None
        return sorted(open_tasks, key=lambda task: priority_order.get(task.get("priority", "low"), 9))[0]

    def _execution_plan(self, task: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {
                "order": index,
                "description": scope_item,
                "recommended_agent": task.get("recommended_agent"),
            }
            for index, scope_item in enumerate(task.get("scope", []), start=1)
        ]
