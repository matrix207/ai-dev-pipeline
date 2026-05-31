"""Code review agent skeleton for local validation artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from agents import BaseAgent
from artifacts import read_json


class CodeReviewerAgent(BaseAgent):
    """Review local task artifacts after tests have run."""

    def __init__(self, name: str = "code-reviewer") -> None:
        super().__init__(name)

    def handle(self, payload: dict[str, Any]) -> Mapping[str, Any]:
        repo_root = Path(payload.get("repo_root", "."))
        task_id = payload["task_id"]
        validation_path = payload.get(
            "validation_path",
            f"workspace/tasks/{task_id}/review/test_validation.json",
        )

        checks: list[dict[str, str]] = []
        blocking_issues: list[dict[str, str]] = []

        validation = self._read_validation(repo_root, validation_path, checks, blocking_issues)
        if validation and validation.get("passed") is True:
            checks.append(
                {
                    "name": "tests_passed",
                    "result": "pass",
                    "notes": "测试验证已通过。",
                }
            )
        else:
            self._block(
                checks,
                blocking_issues,
                "tests_passed",
                "测试验证未通过或缺少测试验证产物。",
                "先修复测试失败，再进入人工合并门。",
            )

        if self._path_exists(repo_root, f"workspace/tasks/{task_id}/state.json"):
            checks.append(
                {
                    "name": "task_state_recorded",
                    "result": "pass",
                    "notes": "任务状态产物存在。",
                }
            )
        else:
            self._block(
                checks,
                blocking_issues,
                "task_state_recorded",
                "任务状态产物缺失。",
                "写入 workspace/tasks/{task_id}/state.json。",
            )

        approved = not blocking_issues
        return {
            "task_id": task_id,
            "status": "passed" if approved else "blocked",
            "decision": {
                "approved_for_human_merge_gate": approved,
                "requires_human_review": not approved,
            },
            "checks": checks,
            "blocking_issues": blocking_issues,
            "non_blocking_issues": [],
        }

    def _read_validation(
        self,
        repo_root: Path,
        validation_path: str,
        checks: list[dict[str, str]],
        blocking_issues: list[dict[str, str]],
    ) -> dict[str, Any] | None:
        try:
            validation = read_json(repo_root, validation_path)
        except Exception as exc:
            self._block(
                checks,
                blocking_issues,
                "test_validation_artifact",
                f"无法读取测试验证产物：{validation_path}",
                str(exc),
            )
            return None

        checks.append(
            {
                "name": "test_validation_artifact",
                "result": "pass",
                "notes": f"已读取 {validation_path}。",
            }
        )
        return validation

    def _path_exists(self, repo_root: Path, relative_path: str) -> bool:
        return (repo_root / relative_path).exists()

    def _block(
        self,
        checks: list[dict[str, str]],
        blocking_issues: list[dict[str, str]],
        check_name: str,
        description: str,
        recommendation: str,
    ) -> None:
        checks.append({"name": check_name, "result": "fail", "notes": description})
        blocking_issues.append(
            {
                "id": check_name,
                "severity": "high",
                "description": description,
                "recommendation": recommendation,
            }
        )
