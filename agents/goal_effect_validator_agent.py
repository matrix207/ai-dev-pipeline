"""Validate project state against target goals and expected effects."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from agents import BaseAgent
from artifacts import read_json, read_yaml


DEFAULT_GOAL_SPEC_PATH = "workspace/tasks/validation-001/input/validation_goal.yaml"


class GoalEffectValidatorAgent(BaseAgent):
    """Compare target goals/effects with local validation artifacts."""

    def __init__(self, name: str = "goal-effect-validator") -> None:
        super().__init__(name)

    def handle(self, payload: dict[str, Any]) -> Mapping[str, Any]:
        repo_root = Path(payload.get("repo_root", "."))
        task_id = payload["task_id"]
        goal_spec_path = payload.get("goal_spec_path", DEFAULT_GOAL_SPEC_PATH)
        goal_spec = read_yaml(repo_root, goal_spec_path)

        checks: list[dict[str, Any]] = []
        feedback: list[str] = []
        blocking_issues: list[dict[str, str]] = []

        for path in goal_spec.get("required_artifacts", []):
            if (repo_root / path).exists():
                checks.append({"name": path, "type": "artifact", "result": "pass"})
            else:
                checks.append({"name": path, "type": "artifact", "result": "fail"})
                blocking_issues.append(
                    {
                        "id": f"missing_artifact:{path}",
                        "severity": "high",
                        "description": f"缺少目标效果要求的产物：{path}",
                        "recommendation": "补齐产物后重新运行自动化验证。",
                    }
                )

        validation = self._read_optional_json(
            repo_root,
            f"workspace/tasks/{task_id}/review/test_validation.json",
        )
        code_review = self._read_optional_json(
            repo_root,
            f"workspace/tasks/{task_id}/review/code_review.json",
        )

        expected_effects = goal_spec.get("expected_effects", {})
        if expected_effects.get("tests_pass"):
            self._check_boolean_effect(
                checks,
                blocking_issues,
                "tests_pass",
                validation is not None and validation.get("passed") is True,
                "测试验证必须通过。",
            )
        if expected_effects.get("code_review_passes"):
            self._check_boolean_effect(
                checks,
                blocking_issues,
                "code_review_passes",
                code_review is not None and not code_review.get("blocking_issues"),
                "代码评审不能存在 blocking issues。",
            )

        if blocking_issues:
            feedback.append("先处理 blocking issues，再进入人工合并门。")
        else:
            feedback.append("目标对齐和效果验证通过，可以进入人工合并门。")

        score = self._score(checks)
        return {
            "task_id": task_id,
            "status": "passed" if not blocking_issues else "blocked",
            "goal": goal_spec.get("goal", ""),
            "alignment_score": score,
            "checks": checks,
            "blocking_issues": blocking_issues,
            "feedback": feedback,
        }

    def _read_optional_json(self, repo_root: Path, relative_path: str) -> dict[str, Any] | None:
        try:
            return read_json(repo_root, relative_path)
        except Exception:
            return None

    def _check_boolean_effect(
        self,
        checks: list[dict[str, Any]],
        blocking_issues: list[dict[str, str]],
        name: str,
        passed: bool,
        description: str,
    ) -> None:
        checks.append({"name": name, "type": "effect", "result": "pass" if passed else "fail"})
        if not passed:
            blocking_issues.append(
                {
                    "id": name,
                    "severity": "high",
                    "description": description,
                    "recommendation": "根据验证反馈修复后重新运行自动化验证。",
                }
            )

    def _score(self, checks: list[dict[str, Any]]) -> float:
        if not checks:
            return 0.0
        passed = sum(1 for check in checks if check["result"] == "pass")
        return round(passed / len(checks), 3)
