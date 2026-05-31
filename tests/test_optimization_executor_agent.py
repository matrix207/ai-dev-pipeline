from __future__ import annotations

from pathlib import Path

from agents import OptimizationExecutorAgent
from artifacts import write_json, write_yaml


def write_optimization_tasks(tmp_path: Path, *, risk_level: str = "medium") -> None:
    write_yaml(
        tmp_path,
        "workspace/tasks/optimization-001/final/next_optimization_tasks.yaml",
        {
            "task_batch": {
                "source_tasks": ["source-parent", "source-child"],
                "source_feedback_paths": [
                    "workspace/tasks/source-parent/final/validation_feedback.json",
                    "workspace/tasks/source-child/final/validation_feedback.json",
                ],
            },
            "tasks": [
                {
                    "id": "done-task",
                    "title": "Done",
                    "priority": "high",
                    "recommended_agent": "CoderAgent",
                    "risk_level": "medium",
                    "human_gate": {
                        "goal_approval_required": True,
                        "risk_approval_required": False,
                        "merge_approval_required": True,
                    },
                    "scope": ["already done"],
                    "acceptance_criteria": ["done"],
                },
                {
                    "id": "next-task",
                    "title": "Next",
                    "priority": "medium",
                    "recommended_agent": "CoderAgent",
                    "risk_level": risk_level,
                    "human_gate": {
                        "goal_approval_required": True,
                        "risk_approval_required": risk_level == "high",
                        "merge_approval_required": True,
                    },
                    "scope": ["do next"],
                    "acceptance_criteria": ["next done"],
                },
            ]
        },
    )
    write_json(tmp_path, "workspace/tasks/done-task/state.json", {"task_id": "done-task"})


def test_optimization_executor_selects_next_open_task(tmp_path: Path) -> None:
    write_optimization_tasks(tmp_path)

    result = OptimizationExecutorAgent().run({"repo_root": str(tmp_path)})

    assert result.output["status"] == "ready"
    assert result.output["tasks_path"] == "workspace/tasks/optimization-001/final/next_optimization_tasks.yaml"
    assert result.output["task_batch"]["source_tasks"] == ["source-parent", "source-child"]
    assert result.output["selected_task"]["id"] == "next-task"
    assert result.output["selected_task"]["recommended_agent"] == "CoderAgent"
    assert result.output["selected_task"]["source_feedback_paths"] == [
        "workspace/tasks/source-parent/final/validation_feedback.json",
        "workspace/tasks/source-child/final/validation_feedback.json",
    ]
    assert result.output["execution_allowed"] is True
    assert result.output["execution_plan"] == [
        {"order": 1, "description": "do next", "recommended_agent": "CoderAgent"}
    ]


def test_optimization_executor_reports_no_open_tasks(tmp_path: Path) -> None:
    write_optimization_tasks(tmp_path)
    write_json(tmp_path, "workspace/tasks/next-task/state.json", {"task_id": "next-task"})

    result = OptimizationExecutorAgent().run({"repo_root": str(tmp_path)})

    assert result.output["status"] == "no_open_tasks"
    assert result.output["selected_task"] is None


def test_optimization_executor_blocks_high_risk_without_approval(tmp_path: Path) -> None:
    write_optimization_tasks(tmp_path, risk_level="high")

    result = OptimizationExecutorAgent().run({"repo_root": str(tmp_path)})

    assert result.output["status"] == "blocked"
    assert result.output["blocking_issues"][0]["id"] == "risk_gate_required"


def test_optimization_executor_allows_high_risk_with_approval(tmp_path: Path) -> None:
    write_optimization_tasks(tmp_path, risk_level="high")

    result = OptimizationExecutorAgent().run(
        {"repo_root": str(tmp_path), "risk_approved": True}
    )

    assert result.output["status"] == "ready"
    assert result.output["blocking_issues"] == []
