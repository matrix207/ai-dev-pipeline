from __future__ import annotations

from pathlib import Path

import pytest

from artifacts import read_json, read_text, read_yaml, repo_path, write_json, write_text, write_yaml


def test_yaml_artifact_round_trip_creates_parent_directories(tmp_path: Path) -> None:
    data = {"task_id": "dev-001", "items": ["base-agent", "artifact-io"]}

    path = write_yaml(tmp_path, "workspace/tasks/dev-001/final/result.yaml", data)

    assert path == tmp_path / "workspace/tasks/dev-001/final/result.yaml"
    assert read_yaml(tmp_path, "workspace/tasks/dev-001/final/result.yaml") == data


def test_json_artifact_round_trip(tmp_path: Path) -> None:
    data = {"status": "success", "errors": []}

    write_json(tmp_path, "workspace/tasks/dev-001/review/result.json", data)

    assert read_json(tmp_path, "workspace/tasks/dev-001/review/result.json") == data


def test_text_artifact_round_trip(tmp_path: Path) -> None:
    write_text(tmp_path, "workspace/tasks/dev-001/logs/run.log", "dev-001 complete\n")

    assert read_text(tmp_path, "workspace/tasks/dev-001/logs/run.log") == "dev-001 complete\n"


def test_artifact_path_rejects_absolute_paths(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="relative"):
        repo_path(tmp_path, tmp_path / "outside.json")


def test_artifact_path_rejects_parent_escape(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="inside"):
        repo_path(tmp_path, "../outside.json")
