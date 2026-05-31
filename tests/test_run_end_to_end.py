from __future__ import annotations

import json
import sys
from pathlib import Path

from artifacts import read_yaml, write_yaml
from scripts.run_end_to_end import format_end_to_end_summary, main, run_end_to_end
from tasks import load_state


def write_end_to_end_config(tmp_path: Path) -> None:
    write_yaml(
        tmp_path,
        "config/pipeline.yaml",
        {
            "agent_config": {"human_gate_required": True},
            "workflows": {
                "ui_validation": {
                    "task_id": "ui-validation-001",
                    "steps": [
                        {
                            "name": "test_validation",
                            "commands": [[sys.executable, "-c", "print('ok')"]],
                        },
                        "code_review",
                        "goal_effect_validation",
                    ],
                },
                "end_to_end_dispatch": {
                    "task_id": "workflow-001-dispatch",
                    "steps": [
                        {
                            "name": "optimization_dispatch",
                            "tasks_path": "workspace/tasks/workflow-001/input/dispatch_tasks.yaml",
                            "dispatch_all": True,
                        },
                        {
                            "name": "dispatched_task_validation",
                            "commands": [[sys.executable, "-c", "print('ok')"]],
                        },
                        {
                            "name": "test_validation",
                            "commands": [[sys.executable, "-c", "print('ok')"]],
                        },
                        "code_review",
                        "goal_effect_validation",
                    ],
                },
                "end_to_end_review": {
                    "task_id": "workflow-001-review",
                    "steps": [
                        {
                            "name": "test_validation",
                            "commands": [[sys.executable, "-c", "print('ok')"]],
                        },
                        {
                            "name": "code_review",
                            "task_definition_path": "workspace/tasks/workflow-001/input/review_tasks.yaml",
                        },
                        "goal_effect_validation",
                    ],
                },
            },
        },
    )


def write_validation_goal(tmp_path: Path) -> None:
    write_yaml(
        tmp_path,
        "workspace/tasks/validation-001/input/validation_goal.yaml",
        {
            "goal": "端到端闭环可运行。",
            "required_artifacts": ["config/pipeline.yaml"],
            "expected_effects": {"tests_pass": True, "code_review_passes": True},
        },
    )


def test_run_end_to_end_writes_decision_summary(tmp_path: Path) -> None:
    write_end_to_end_config(tmp_path)
    write_validation_goal(tmp_path)

    summary = run_end_to_end(tmp_path)

    assert summary["task_id"] == "workflow-001"
    assert summary["status"] == "ready_for_human_decision"
    assert summary["current_result"]["validation_state"]["status"] == "waiting_for_human_merge_approval"
    assert summary["current_result"]["dispatch_state"]["status"] == "waiting_for_human_merge_approval"
    assert summary["current_result"]["review_state"]["status"] == "waiting_for_human_merge_approval"
    assert summary["next_recommended_action"]["reason"] == "来自端到端反馈闭环生成的下一轮优化任务。"

    saved = read_yaml(tmp_path, "workspace/tasks/workflow-001/final/decision_summary.yaml")
    assert saved == summary
    state = load_state(tmp_path, "workflow-001")
    assert state.status == "waiting_for_human_merge_approval"
    assert "workspace/tasks/workflow-001/final/decision_summary.yaml" in state.artifacts

    dispatch_tasks = read_yaml(tmp_path, "workspace/tasks/workflow-001/input/dispatch_tasks.yaml")
    assert len(dispatch_tasks["tasks"]) >= 1
    assert all(task["id"].startswith("workflow-001-") for task in dispatch_tasks["tasks"])


def test_run_end_to_end_uses_unique_dispatch_task_ids_on_rerun(tmp_path: Path) -> None:
    write_end_to_end_config(tmp_path)
    write_validation_goal(tmp_path)

    first = run_end_to_end(tmp_path)
    second = run_end_to_end(tmp_path)

    assert first["current_result"]["dispatch_state"]["status"] == "waiting_for_human_merge_approval"
    assert second["current_result"]["dispatch_state"]["status"] == "waiting_for_human_merge_approval"
    dispatch_tasks = read_yaml(tmp_path, "workspace/tasks/workflow-001/input/dispatch_tasks.yaml")
    assert any(task["id"].endswith("-2") for task in dispatch_tasks["tasks"])


def test_format_end_to_end_summary_is_human_readable() -> None:
    summary = {
        "goal_effect": {
            "validation_status": "passed",
            "alignment_score": 1.0,
            "blocking_issues": [],
        },
        "current_result": {
            "dispatch_state": {"status": "waiting_for_human_merge_approval"},
            "review_state": {"status": "waiting_for_human_merge_approval"},
            "initial_plan_artifact": "workspace/tasks/workflow-001/final/initial_next_optimization_tasks.yaml",
            "dispatch_tasks_artifact": "workspace/tasks/workflow-001/input/dispatch_tasks.yaml",
            "final_plan_artifact": "workspace/tasks/workflow-001/final/final_next_optimization_tasks.yaml",
        },
        "next_recommended_action": {
            "task_id": "workflow-002",
            "title": "Next workflow task",
            "priority": "medium",
            "reason": "来自端到端反馈闭环生成的下一轮优化任务。",
        },
    }

    output = format_end_to_end_summary(summary)

    assert "AI Dev Pipeline End-to-End Summary" in output
    assert "Dispatch state: waiting_for_human_merge_approval" in output
    assert "workflow-002: Next workflow task" in output


def test_run_end_to_end_cli_json_output(tmp_path: Path, capsys) -> None:
    write_end_to_end_config(tmp_path)
    write_validation_goal(tmp_path)

    old_argv = sys.argv
    sys.argv = ["run_end_to_end.py", "--repo-root", str(tmp_path), "--json"]
    try:
        exit_code = main()
    finally:
        sys.argv = old_argv

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["task_id"] == "workflow-001"
