from __future__ import annotations

import sys
from pathlib import Path

from agents import CodeReviewerAgent, GoalEffectValidatorAgent, TestValidatorAgent
from artifacts import write_json, write_yaml


def test_test_validator_agent_runs_command_successfully(tmp_path: Path) -> None:
    result = TestValidatorAgent().run(
        {
            "repo_root": str(tmp_path),
            "commands": [[sys.executable, "-c", "print('ok')"]],
        }
    )

    assert result.output["passed"] is True
    assert result.output["status"] == "passed"
    assert "ok" in result.output["results"][0]["stdout"]


def test_test_validator_agent_reports_failed_command(tmp_path: Path) -> None:
    result = TestValidatorAgent().run(
        {
            "repo_root": str(tmp_path),
            "commands": [[sys.executable, "-c", "raise SystemExit(2)"]],
        }
    )

    assert result.output["passed"] is False
    assert result.output["status"] == "failed"
    assert result.output["results"][0]["returncode"] == 2


def test_code_reviewer_agent_passes_when_tests_and_state_exist(tmp_path: Path) -> None:
    write_json(tmp_path, "workspace/tasks/validation-001/review/test_validation.json", {"passed": True})
    write_json(tmp_path, "workspace/tasks/validation-001/state.json", {"task_id": "validation-001"})

    result = CodeReviewerAgent().run({"repo_root": str(tmp_path), "task_id": "validation-001"})

    assert result.output["status"] == "passed"
    assert result.output["blocking_issues"] == []
    assert result.output["artifact_consistency"]["missing"] == []


def test_code_reviewer_agent_blocks_when_tests_fail(tmp_path: Path) -> None:
    write_json(tmp_path, "workspace/tasks/validation-001/review/test_validation.json", {"passed": False})
    write_json(tmp_path, "workspace/tasks/validation-001/state.json", {"task_id": "validation-001"})

    result = CodeReviewerAgent().run({"repo_root": str(tmp_path), "task_id": "validation-001"})

    assert result.output["status"] == "blocked"
    assert result.output["blocking_issues"][0]["id"] == "tests_passed"


def test_code_reviewer_agent_blocks_missing_state_artifact_path(tmp_path: Path) -> None:
    write_json(tmp_path, "workspace/tasks/opt-001/review/test_validation.json", {"passed": True})
    write_json(
        tmp_path,
        "workspace/tasks/opt-001/state.json",
        {
            "task_id": "opt-001",
            "artifacts": ["workspace/tasks/opt-001/final/missing.yaml"],
        },
    )

    result = CodeReviewerAgent().run({"repo_root": str(tmp_path), "task_id": "opt-001"})

    assert result.output["status"] == "blocked"
    assert result.output["blocking_issues"][0]["id"] == "state_artifacts_exist"
    assert result.output["artifact_consistency"]["missing"] == [
        "workspace/tasks/opt-001/final/missing.yaml"
    ]


def test_code_reviewer_agent_reports_acceptance_coverage(tmp_path: Path) -> None:
    write_json(tmp_path, "workspace/tasks/opt-001/review/test_validation.json", {"passed": True})
    write_json(
        tmp_path,
        "workspace/tasks/opt-001/state.json",
        {
            "task_id": "opt-001",
            "artifacts": ["workspace/tasks/opt-001/review/acceptance_check.json"],
        },
    )
    write_json(
        tmp_path,
        "workspace/tasks/opt-001/review/acceptance_check.json",
        {
            "checks": [
                {
                    "name": "coverage",
                    "evidence": "代码评审报告包含验收标准覆盖情况。",
                }
            ]
        },
    )
    write_yaml(
        tmp_path,
        "workspace/tasks/optimization-001/final/next_optimization_tasks.yaml",
        {
            "tasks": [
                {
                    "id": "opt-001",
                    "acceptance_criteria": [
                        "代码评审报告包含验收标准覆盖情况。",
                        "缺少 evidence 时产生 blocking issue 或 non-blocking recommendation。",
                    ],
                }
            ]
        },
    )

    result = CodeReviewerAgent().run({"repo_root": str(tmp_path), "task_id": "opt-001"})

    assert result.output["status"] == "passed"
    assert result.output["acceptance_coverage"]["covered"] == [
        "代码评审报告包含验收标准覆盖情况。"
    ]
    assert result.output["acceptance_coverage"]["missing_evidence"] == [
        "缺少 evidence 时产生 blocking issue 或 non-blocking recommendation。"
    ]
    assert result.output["non_blocking_issues"][0]["id"] == "acceptance_criteria_evidence"


def test_goal_effect_validator_agent_outputs_feedback(tmp_path: Path) -> None:
    write_yaml(
        tmp_path,
        "workspace/tasks/validation-001/input/validation_goal.yaml",
        {
            "goal": "自动化验证闭环可运行。",
            "required_artifacts": ["agents/base_agent.py"],
            "expected_effects": {
                "tests_pass": True,
                "code_review_passes": True,
            },
        },
    )
    (tmp_path / "agents").mkdir()
    (tmp_path / "agents/base_agent.py").write_text("# ok\n", encoding="utf-8")
    write_json(tmp_path, "workspace/tasks/validation-001/review/test_validation.json", {"passed": True})
    write_json(tmp_path, "workspace/tasks/validation-001/review/code_review.json", {"blocking_issues": []})

    result = GoalEffectValidatorAgent().run(
        {"repo_root": str(tmp_path), "task_id": "validation-001"}
    )

    assert result.output["status"] == "passed"
    assert result.output["alignment_score"] == 1.0
    assert result.output["feedback"] == ["目标对齐和效果验证通过，可以进入人工合并门。"]


def test_goal_effect_validator_agent_blocks_missing_effect(tmp_path: Path) -> None:
    write_yaml(
        tmp_path,
        "workspace/tasks/validation-001/input/validation_goal.yaml",
        {
            "goal": "自动化验证闭环可运行。",
            "required_artifacts": ["missing.py"],
            "expected_effects": {"tests_pass": True},
        },
    )

    result = GoalEffectValidatorAgent().run(
        {"repo_root": str(tmp_path), "task_id": "validation-001"}
    )

    assert result.output["status"] == "blocked"
    assert result.output["blocking_issues"]
