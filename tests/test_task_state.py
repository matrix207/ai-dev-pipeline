from __future__ import annotations

from pathlib import Path

import pytest

from tasks import DEFAULT_GATES, TaskState, load_state, save_state, state_file_path


def test_task_state_save_and_load_round_trip(tmp_path: Path) -> None:
    state = TaskState(task_id="dev-002", step="state_schema", status="running")
    state.record_artifact("workspace/tasks/dev-002/design/state_schema.yaml")
    state.set_gate("goal_approved", True)

    path = save_state(tmp_path, state)
    loaded = load_state(tmp_path, "dev-002")

    assert path == tmp_path / "workspace/tasks/dev-002/state.json"
    assert loaded.to_dict() == state.to_dict()


def test_task_state_update_records_status_artifact_error_and_gates() -> None:
    state = TaskState(task_id="dev-002")

    state.update(
        step="tests",
        status="running",
        artifact="workspace/tasks/dev-002/review/acceptance_check.json",
        gates={"tests_passed": True, "code_review_passed": True},
    )
    state.update(error="review blocked")

    assert state.step == "tests"
    assert state.status == "failed"
    assert state.artifacts == ["workspace/tasks/dev-002/review/acceptance_check.json"]
    assert state.errors == ["review blocked"]
    assert state.gates["tests_passed"] is True
    assert state.gates["code_review_passed"] is True


def test_task_state_defaults_all_known_quality_gates() -> None:
    state = TaskState(task_id="dev-002")

    assert state.gates == DEFAULT_GATES


def test_task_state_rejects_invalid_task_id() -> None:
    with pytest.raises(ValueError, match="single path segment"):
        TaskState(task_id="../outside")


def test_task_state_rejects_escaping_artifact_paths() -> None:
    state = TaskState(task_id="dev-002")

    with pytest.raises(ValueError, match="Artifact paths"):
        state.record_artifact("../outside.json")


def test_task_state_rejects_unknown_quality_gate() -> None:
    state = TaskState(task_id="dev-002")

    with pytest.raises(ValueError, match="Unknown quality gate"):
        state.set_gate("not_a_gate", True)


def test_state_file_path_is_under_workspace_task_root(tmp_path: Path) -> None:
    assert state_file_path(tmp_path, "dev-002") == tmp_path / "workspace/tasks/dev-002/state.json"
