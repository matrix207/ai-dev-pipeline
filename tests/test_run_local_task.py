from __future__ import annotations

import json
from pathlib import Path

from artifacts import read_json, write_yaml
from scripts.run_local_task import run_local_task
from tasks import load_state


def write_config(tmp_path: Path, steps: list[str], *, human_gate_required: bool = True) -> None:
    write_yaml(
        tmp_path,
        "config/pipeline.yaml",
        {
            "agent_config": {
                "human_gate_required": human_gate_required,
            },
            "workflows": {
                "local_dev": {
                    "task_id": "dev-003",
                    "steps": steps,
                }
            },
        },
    )


def test_run_local_task_writes_state_and_step_artifacts(tmp_path: Path) -> None:
    write_config(tmp_path, ["load_config", "write_state"])

    state = run_local_task(tmp_path, "local_dev", goal_approved=True)

    assert state.task_id == "dev-003"
    assert state.step == "human_merge_gate"
    assert state.status == "waiting_for_human_merge_approval"
    assert state.gates["goal_approved"] is True
    assert state.gates["human_merge_approved"] is False
    assert state.artifacts == [
        "workspace/tasks/dev-003/orchestration/load_config.json",
        "workspace/tasks/dev-003/orchestration/write_state.json",
    ]
    assert load_state(tmp_path, "dev-003").to_dict() == state.to_dict()
    assert read_json(tmp_path, state.artifacts[0])["step"] == "load_config"


def test_run_local_task_records_failure_state(tmp_path: Path) -> None:
    write_config(tmp_path, ["load_config", "fail", "write_state"])

    state = run_local_task(tmp_path, "local_dev", goal_approved=True)

    assert state.step == "fail"
    assert state.status == "failed"
    assert state.errors == ["fail: Placeholder step failed."]
    assert state.artifacts == ["workspace/tasks/dev-003/orchestration/load_config.json"]
    assert load_state(tmp_path, "dev-003").to_dict() == state.to_dict()


def test_run_local_task_can_complete_without_human_gate(tmp_path: Path) -> None:
    write_config(tmp_path, ["load_config"], human_gate_required=False)

    state = run_local_task(tmp_path, "local_dev", goal_approved=True)

    assert state.step == "completed"
    assert state.status == "completed"
    assert state.gates["human_merge_approved"] is True


def test_run_local_task_cli_outputs_state(tmp_path: Path, capsys) -> None:
    write_config(tmp_path, ["load_config"])

    from scripts.run_local_task import main
    import sys

    old_argv = sys.argv
    sys.argv = [
        "run_local_task.py",
        "--repo-root",
        str(tmp_path),
        "--workflow",
        "local_dev",
        "--goal-approved",
    ]
    try:
        exit_code = main()
    finally:
        sys.argv = old_argv

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["task_id"] == "dev-003"
    assert output["status"] == "waiting_for_human_merge_approval"
