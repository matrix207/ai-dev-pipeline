from __future__ import annotations

from pathlib import Path

from artifacts import read_yaml
from scripts.run_validation_loop import run_validation_loop


def test_run_validation_loop_writes_decision_summary(tmp_path: Path) -> None:
    # Use the real repository through repo_root in integration tests elsewhere;
    # this test only verifies summary selection logic with minimal generated files.
    from artifacts import write_json, write_yaml

    write_yaml(
        tmp_path,
        "config/pipeline.yaml",
        {
            "agent_config": {"human_gate_required": True},
            "workflows": {
                "automated_validation": {"task_id": "validation-001", "steps": []},
                "optimization_planning": {"task_id": "optimization-001", "steps": []},
            },
        },
    )
    write_json(
        tmp_path,
        "workspace/tasks/validation-001/final/validation_feedback.json",
        {"status": "passed", "alignment_score": 1.0, "blocking_issues": []},
    )
    write_yaml(
        tmp_path,
        "workspace/tasks/optimization-001/final/next_optimization_tasks.yaml",
        {
            "tasks": [
                {"id": "low-task", "title": "Low", "priority": "low"},
                {"id": "high-task", "title": "High", "priority": "high"},
            ]
        },
    )

    summary = run_validation_loop(tmp_path)

    assert summary["status"] == "ready_for_human_decision"
    assert summary["next_recommended_action"]["task_id"] == "high-task"
    saved = read_yaml(tmp_path, "workspace/tasks/planning-002/final/decision_summary.yaml")
    assert saved == summary
