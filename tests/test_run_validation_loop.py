from __future__ import annotations

from pathlib import Path

from artifacts import read_yaml
from scripts.run_validation_loop import format_decision_summary, main, run_validation_loop


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


def test_format_decision_summary_is_human_readable() -> None:
    summary = {
        "goal_effect": {
            "validation_status": "passed",
            "alignment_score": 1.0,
            "blocking_issues": [],
        },
        "current_result": {
            "validation_state": {"status": "waiting_for_human_merge_approval"},
            "optimization_state": {"status": "waiting_for_human_merge_approval"},
            "feedback_artifact": "workspace/tasks/validation-001/final/validation_feedback.json",
            "optimization_tasks_artifact": "workspace/tasks/optimization-001/final/next_optimization_tasks.yaml",
        },
        "next_recommended_action": {
            "task_id": "product-002",
            "title": "增强人类可读 CLI 摘要",
            "priority": "medium",
            "reason": "来自 optimization_planning 生成的下一轮优化任务。",
        },
    }

    output = format_decision_summary(summary)

    assert "AI Dev Pipeline Decision Summary" in output
    assert "Alignment score: 1.0" in output
    assert "product-002: 增强人类可读 CLI 摘要" in output


def test_run_validation_loop_cli_json_output(tmp_path: Path, capsys) -> None:
    from artifacts import write_json, write_yaml
    import json
    import sys

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
        {"tasks": [{"id": "next", "title": "Next", "priority": "medium"}]},
    )

    old_argv = sys.argv
    sys.argv = ["run_validation_loop.py", "--repo-root", str(tmp_path), "--json"]
    try:
        exit_code = main()
    finally:
        sys.argv = old_argv

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["next_recommended_action"]["task_id"] == "next"
