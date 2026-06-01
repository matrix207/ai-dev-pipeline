from __future__ import annotations

from pathlib import Path

from agents import OptimizationPlannerAgent
from artifacts import write_json


def test_optimization_planner_outputs_enhancement_tasks_when_validation_passes(
    tmp_path: Path,
) -> None:
    write_json(
        tmp_path,
        "workspace/tasks/validation-001/final/validation_feedback.json",
        {
            "task_id": "validation-001",
            "alignment_score": 1.0,
            "blocking_issues": [],
        },
    )

    result = OptimizationPlannerAgent().run({"repo_root": str(tmp_path)})

    assert result.output["task_batch"]["planning_mode"] == "enhancement"
    assert [task["id"] for task in result.output["tasks"]] == [
        "feedback-002",
        "dispatch-002",
        "ui-validation-001",
        "roadmap-001",
        "decision-view-001",
        "task-library-001",
    ]
    assert all("recommended_agent" in task for task in result.output["tasks"])
    assert all("risk_level" in task for task in result.output["tasks"])
    assert all("human_gate" in task for task in result.output["tasks"])
    assert result.output["tasks"][0]["recommended_agent"] == "CoderAgent"
    assert result.output["tasks"][0]["human_gate"]["merge_approval_required"] is True
    assert result.output["human_gate"]["required_before_pr_or_merge"] is True


def test_optimization_planner_outputs_repair_tasks_for_blocking_issues(tmp_path: Path) -> None:
    write_json(
        tmp_path,
        "workspace/tasks/validation-001/final/validation_feedback.json",
        {
            "task_id": "validation-001",
            "alignment_score": 0.4,
            "blocking_issues": [
                {
                    "id": "tests_pass",
                    "description": "测试验证必须通过。",
                    "recommendation": "修复测试失败。",
                }
            ],
        },
    )

    result = OptimizationPlannerAgent().run({"repo_root": str(tmp_path)})

    assert result.output["task_batch"]["planning_mode"] == "repair"
    assert result.output["tasks"][0]["id"] == "fix-001"
    assert result.output["tasks"][0]["priority"] == "high"
    assert result.output["tasks"][0]["risk_level"] == "high"
    assert result.output["tasks"][0]["human_gate"]["risk_approval_required"] is True


def test_optimization_planner_prefixes_task_ids_for_reusable_batches(tmp_path: Path) -> None:
    write_json(
        tmp_path,
        "workspace/tasks/validation-001/final/validation_feedback.json",
        {
            "task_id": "validation-001",
            "alignment_score": 1.0,
            "blocking_issues": [],
        },
    )

    result = OptimizationPlannerAgent().run(
        {
            "repo_root": str(tmp_path),
            "task_id_prefix": "feedback-execution-001",
        }
    )

    assert result.output["task_batch"]["task_id_prefix"] == "feedback-execution-001"
    assert result.output["tasks"][0]["id"] == "feedback-execution-001-feedback-002"
    assert result.output["tasks"][0]["source_task_id"] == "feedback-002"
    assert [task["source_task_id"] for task in result.output["tasks"]] == [
        "feedback-002",
        "dispatch-002",
        "ui-validation-001",
        "roadmap-001",
        "decision-view-001",
        "task-library-001",
    ]


def test_optimization_planner_combines_multiple_feedback_sources(tmp_path: Path) -> None:
    write_json(
        tmp_path,
        "workspace/tasks/parent/final/validation_feedback.json",
        {
            "task_id": "parent",
            "alignment_score": 1.0,
            "blocking_issues": [],
        },
    )
    write_json(
        tmp_path,
        "workspace/tasks/child/final/validation_feedback.json",
        {
            "task_id": "child",
            "alignment_score": 0.8,
            "blocking_issues": [
                {
                    "id": "child_effect",
                    "description": "子任务目标效果未达成。",
                    "recommendation": "补齐子任务效果验证。",
                }
            ],
        },
    )

    result = OptimizationPlannerAgent().run(
        {
            "repo_root": str(tmp_path),
            "feedback_paths": [
                "workspace/tasks/parent/final/validation_feedback.json",
                "workspace/tasks/child/final/validation_feedback.json",
            ],
        }
    )

    assert result.output["task_batch"]["planning_mode"] == "repair"
    assert result.output["task_batch"]["source_tasks"] == ["parent", "child"]
    assert result.output["task_batch"]["source_feedback_paths"] == [
        "workspace/tasks/parent/final/validation_feedback.json",
        "workspace/tasks/child/final/validation_feedback.json",
    ]
    assert result.output["task_batch"]["alignment_score"] == 0.8
    assert result.output["task_batch"]["blocking_issue_count"] == 1
    assert result.output["tasks"][0]["priority"] == "high"
    assert "来源任务：child。" in result.output["tasks"][0]["scope"]
    assert (
        "来源反馈：workspace/tasks/child/final/validation_feedback.json。"
        in result.output["tasks"][0]["scope"]
    )
