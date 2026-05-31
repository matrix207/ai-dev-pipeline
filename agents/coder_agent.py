"""Coder agent skeleton for planning local implementation tasks."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from agents import BaseAgent
from artifacts import read_yaml


DEFAULT_DEV_TASKS_PATH = "workspace/tasks/bootstrap-001/final/next_dev_tasks.yaml"


class CoderAgent(BaseAgent):
    """Read a development task and produce a structured implementation plan."""

    def __init__(self, name: str = "coder") -> None:
        super().__init__(name)

    def handle(self, payload: dict[str, Any]) -> Mapping[str, Any]:
        repo_root = Path(payload.get("repo_root", "."))
        task_id = payload["task_id"]
        tasks_path = payload.get("tasks_path", DEFAULT_DEV_TASKS_PATH)
        task = self._load_dev_task(repo_root, tasks_path, task_id)

        scope = list(task.get("scope", []))
        acceptance_criteria = list(task.get("acceptance_criteria", []))
        out_of_scope = list(task.get("out_of_scope", []))

        plan_steps = [
            {
                "order": index,
                "description": item,
                "expected_artifact": self._expected_artifact(task_id, item),
            }
            for index, item in enumerate(scope, start=1)
        ]

        return {
            "task_id": task_id,
            "title": task.get("title", ""),
            "priority": task.get("priority", "medium"),
            "scope": scope,
            "out_of_scope": out_of_scope,
            "acceptance_criteria": acceptance_criteria,
            "implementation_plan": plan_steps,
            "verification": {
                "required_commands": ["python -m pytest -q"],
                "acceptance_criteria": acceptance_criteria,
            },
            "safety": {
                "external_model_api": "not_used",
                "pr_or_merge": "not_allowed",
                "destructive_operations": "not_allowed",
            },
            "output_artifacts": [
                f"workspace/tasks/{task_id}/code/implementation_plan.json",
                f"workspace/tasks/{task_id}/review/acceptance_check.json",
                f"workspace/tasks/{task_id}/final/implementation_summary.yaml",
            ],
        }

    def _load_dev_task(self, repo_root: Path, tasks_path: str, task_id: str) -> dict[str, Any]:
        task_batch = read_yaml(repo_root, tasks_path)
        for task in task_batch.get("tasks", []):
            if task.get("id") == task_id:
                return dict(task)
        raise ValueError(f"Unknown dev task: {task_id}")

    def _expected_artifact(self, task_id: str, scope_item: str) -> str:
        if "Agent" in scope_item or "agent" in scope_item:
            return "agents/"
        if "测试" in scope_item or "test" in scope_item.lower():
            return "tests/"
        if "产物" in scope_item or "计划" in scope_item:
            return f"workspace/tasks/{task_id}/"
        return f"workspace/tasks/{task_id}/code/"
