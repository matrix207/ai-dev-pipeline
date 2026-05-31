from __future__ import annotations

import sys
from pathlib import Path

from agents import OptimizationDispatcherAgent
from artifacts import read_json, write_json, write_yaml


def write_tasks(
    tmp_path: Path,
    *,
    risk_level: str = "medium",
    agent: str = "CoderAgent",
    task_id: str = "dispatch-task",
    extra: dict | None = None,
) -> None:
    task = {
        "id": task_id,
        "title": "Dispatch Task",
        "priority": "medium",
        "recommended_agent": agent,
        "risk_level": risk_level,
        "human_gate": {
            "goal_approval_required": True,
            "risk_approval_required": risk_level == "high",
            "merge_approval_required": True,
        },
        "scope": ["生成执行计划。"],
        "out_of_scope": ["自动 merge。"],
        "acceptance_criteria": ["执行后产生任务状态和验证反馈。"],
    }
    task.update(extra or {})
    write_yaml(
        tmp_path,
        "workspace/tasks/optimization-001/final/next_optimization_tasks.yaml",
        {
            "task_batch": {
                "source_tasks": ["source-parent"],
                "source_feedback_paths": [
                    "workspace/tasks/source-parent/final/validation_feedback.json"
                ],
            },
            "tasks": [task]
        },
    )


def test_optimization_dispatcher_dispatches_coder_agent(tmp_path: Path) -> None:
    write_tasks(tmp_path)

    result = OptimizationDispatcherAgent().run({"repo_root": str(tmp_path)})

    assert result.output["status"] == "dispatched"
    assert result.output["selected_task"]["id"] == "dispatch-task"
    assert result.output["tasks_path"] == "workspace/tasks/optimization-001/final/next_optimization_tasks.yaml"
    assert result.output["source_tasks"] == ["source-parent"]
    assert result.output["source_feedback_paths"] == [
        "workspace/tasks/source-parent/final/validation_feedback.json"
    ]
    assert result.output["dispatch_result"]["task_id"] == "dispatch-task"
    assert result.output["dispatch_result"]["safety"]["pr_or_merge"] == "not_allowed"
    assert result.output["written_artifacts"] == [
        "workspace/tasks/dispatch-task/code/implementation_plan.json",
        "workspace/tasks/dispatch-task/state.json",
    ]
    state = read_json(tmp_path, "workspace/tasks/dispatch-task/state.json")
    assert state["status"] == "waiting_for_validation"
    assert state["gates"]["design_review_passed"] is True
    assert state["artifacts"] == ["workspace/tasks/dispatch-task/code/implementation_plan.json"]


def test_optimization_dispatcher_returns_no_open_tasks(tmp_path: Path) -> None:
    write_tasks(tmp_path)
    write_json(tmp_path, "workspace/tasks/dispatch-task/state.json", {"task_id": "dispatch-task"})

    result = OptimizationDispatcherAgent().run({"repo_root": str(tmp_path)})

    assert result.output["status"] == "no_open_tasks"
    assert result.output["dispatch_result"] is None


def test_optimization_dispatcher_blocks_high_risk_without_approval(tmp_path: Path) -> None:
    write_tasks(tmp_path, risk_level="high")

    result = OptimizationDispatcherAgent().run({"repo_root": str(tmp_path)})

    assert result.output["status"] == "blocked"
    assert result.output["blocking_issues"][0]["id"] == "risk_gate_required"


def test_optimization_dispatcher_blocks_unsupported_agent(tmp_path: Path) -> None:
    write_tasks(tmp_path, agent="UnknownAgent")

    result = OptimizationDispatcherAgent().run({"repo_root": str(tmp_path)})

    assert result.output["status"] == "blocked"
    assert result.output["blocking_issues"][0]["id"] == "unsupported_agent"


def test_optimization_dispatcher_dispatches_design_reviewer(tmp_path: Path) -> None:
    write_tasks(tmp_path, agent="DesignReviewerAgent", extra={"target_task_id": "target-design"})
    write_yaml(
        tmp_path,
        "workspace/tasks/target-design/analysis/project_context.yaml",
        {"task_id": "target-design", "summary": "local MVP"},
    )
    (tmp_path / "workspace/tasks/target-design/architecture").mkdir(parents=True)
    (tmp_path / "workspace/tasks/target-design/architecture/mvp_architecture.md").write_text(
        "# 架构\n\n包含人工质量门。",
        encoding="utf-8",
    )
    write_yaml(
        tmp_path,
        "workspace/tasks/target-design/design/mvp_system_design.yaml",
        {"modules": {"agents": {"purpose": "run agents"}}, "workflow": {"local": ["review"]}},
    )

    result = OptimizationDispatcherAgent().run({"repo_root": str(tmp_path)})

    assert result.output["status"] == "dispatched"
    assert result.output["dispatch_result"]["status"] == "passed"
    assert result.output["written_artifacts"] == [
        "workspace/tasks/dispatch-task/review/design_review.json",
        "workspace/tasks/dispatch-task/state.json",
    ]
    state = read_json(tmp_path, "workspace/tasks/dispatch-task/state.json")
    assert state["gates"]["design_review_passed"] is True


def test_optimization_dispatcher_dispatches_test_validator(tmp_path: Path) -> None:
    write_tasks(
        tmp_path,
        agent="TestValidatorAgent",
        extra={"commands": [[sys.executable, "-c", "print('ok')"]]},
    )

    result = OptimizationDispatcherAgent().run({"repo_root": str(tmp_path)})

    assert result.output["status"] == "dispatched"
    assert result.output["dispatch_result"]["passed"] is True
    assert result.output["written_artifacts"] == [
        "workspace/tasks/dispatch-task/review/test_validation.json",
        "workspace/tasks/dispatch-task/state.json",
    ]
    state = read_json(tmp_path, "workspace/tasks/dispatch-task/state.json")
    assert state["gates"]["tests_passed"] is True


def test_optimization_dispatcher_dispatches_code_reviewer(tmp_path: Path) -> None:
    write_tasks(
        tmp_path,
        agent="CodeReviewerAgent",
        extra={
            "target_task_id": "review-target",
            "validation_path": "workspace/tasks/review-target/review/test_validation.json",
        },
    )
    write_json(
        tmp_path,
        "workspace/tasks/review-target/review/test_validation.json",
        {"passed": True, "results": []},
    )
    write_json(
        tmp_path,
        "workspace/tasks/review-target/state.json",
        {
            "task_id": "review-target",
            "step": "test_validation",
            "status": "waiting_for_code_review",
            "artifacts": ["workspace/tasks/review-target/review/test_validation.json"],
            "errors": [],
            "gates": {"tests_passed": True},
        },
    )

    result = OptimizationDispatcherAgent().run({"repo_root": str(tmp_path)})

    assert result.output["status"] == "dispatched"
    assert result.output["dispatch_result"]["status"] == "passed"
    assert result.output["written_artifacts"] == [
        "workspace/tasks/dispatch-task/review/code_review.json",
        "workspace/tasks/dispatch-task/state.json",
    ]
    state = read_json(tmp_path, "workspace/tasks/dispatch-task/state.json")
    assert state["gates"]["code_review_passed"] is True


def test_optimization_dispatcher_dispatches_goal_effect_validator(tmp_path: Path) -> None:
    write_tasks(
        tmp_path,
        agent="GoalEffectValidatorAgent",
        extra={"target_task_id": "goal-target"},
    )
    write_yaml(
        tmp_path,
        "workspace/tasks/validation-001/input/validation_goal.yaml",
        {
            "goal": "目标效果通过。",
            "required_artifacts": [],
            "expected_effects": {"tests_pass": True, "code_review_passes": True},
        },
    )
    write_json(
        tmp_path,
        "workspace/tasks/goal-target/review/test_validation.json",
        {"passed": True, "results": []},
    )
    write_json(
        tmp_path,
        "workspace/tasks/goal-target/review/code_review.json",
        {"blocking_issues": []},
    )

    result = OptimizationDispatcherAgent().run({"repo_root": str(tmp_path)})

    assert result.output["status"] == "dispatched"
    assert result.output["dispatch_result"]["status"] == "passed"
    assert result.output["written_artifacts"] == [
        "workspace/tasks/dispatch-task/final/validation_feedback.json",
        "workspace/tasks/dispatch-task/state.json",
    ]


def test_optimization_dispatcher_dispatches_multiple_open_tasks(tmp_path: Path) -> None:
    write_yaml(
        tmp_path,
        "workspace/tasks/optimization-001/final/next_optimization_tasks.yaml",
        {
            "tasks": [
                {
                    "id": "batch-one",
                    "title": "Batch One",
                    "priority": "high",
                    "recommended_agent": "CoderAgent",
                    "risk_level": "medium",
                    "human_gate": {
                        "goal_approval_required": True,
                        "risk_approval_required": False,
                        "merge_approval_required": True,
                    },
                    "scope": ["生成第一个执行计划。"],
                    "acceptance_criteria": ["第一个任务完成。"],
                },
                {
                    "id": "batch-two",
                    "title": "Batch Two",
                    "priority": "medium",
                    "recommended_agent": "CoderAgent",
                    "risk_level": "medium",
                    "human_gate": {
                        "goal_approval_required": True,
                        "risk_approval_required": False,
                        "merge_approval_required": True,
                    },
                    "scope": ["生成第二个执行计划。"],
                    "acceptance_criteria": ["第二个任务完成。"],
                },
            ]
        },
    )

    result = OptimizationDispatcherAgent().run(
        {"repo_root": str(tmp_path), "dispatch_all": True}
    )

    assert result.output["status"] == "dispatched"
    assert result.output["batch"]["dispatched_count"] == 2
    assert [item["selected_task"]["id"] for item in result.output["dispatches"]] == [
        "batch-one",
        "batch-two",
    ]
    assert read_json(tmp_path, "workspace/tasks/batch-one/state.json")["status"] == "waiting_for_validation"
    assert read_json(tmp_path, "workspace/tasks/batch-two/state.json")["status"] == "waiting_for_validation"
