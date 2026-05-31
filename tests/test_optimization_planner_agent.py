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
    assert [task["id"] for task in result.output["tasks"]] == ["opt-001", "opt-002", "opt-003"]
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
