"""Local JSON task state management."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from artifacts.io import read_json, repo_path, write_json


DEFAULT_GATES: dict[str, bool] = {
    "goal_approved": False,
    "design_review_passed": False,
    "tests_passed": False,
    "code_review_passed": False,
    "human_merge_approved": False,
}

STATE_FILENAME = "state.json"


def _validate_task_id(task_id: str) -> None:
    if not task_id.strip():
        raise ValueError("Task id must not be empty.")
    if "/" in task_id or "\\" in task_id or task_id in {".", ".."}:
        raise ValueError("Task id must be a single path segment.")


def _validate_relative_path(path: str) -> None:
    rel_path = Path(path)
    if rel_path.is_absolute() or ".." in rel_path.parts:
        raise ValueError("Artifact paths must be relative and stay inside the repository root.")


@dataclass
class TaskState:
    """Serializable state for one local pipeline task."""

    task_id: str
    step: str = "created"
    status: str = "pending"
    artifacts: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    gates: dict[str, bool] = field(default_factory=lambda: dict(DEFAULT_GATES))

    def __post_init__(self) -> None:
        _validate_task_id(self.task_id)
        if not self.step.strip():
            raise ValueError("Task step must not be empty.")
        if not self.status.strip():
            raise ValueError("Task status must not be empty.")
        for artifact in self.artifacts:
            _validate_relative_path(artifact)

        merged_gates = dict(DEFAULT_GATES)
        merged_gates.update(self.gates)
        self.gates = merged_gates

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "step": self.step,
            "status": self.status,
            "artifacts": list(self.artifacts),
            "errors": list(self.errors),
            "gates": dict(self.gates),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskState":
        return cls(
            task_id=data["task_id"],
            step=data.get("step", "created"),
            status=data.get("status", "pending"),
            artifacts=list(data.get("artifacts", [])),
            errors=list(data.get("errors", [])),
            gates=dict(data.get("gates", {})),
        )

    def record_artifact(self, relative_path: str) -> None:
        _validate_relative_path(relative_path)
        if relative_path not in self.artifacts:
            self.artifacts.append(relative_path)

    def record_error(self, message: str, *, status: str = "failed") -> None:
        if not message.strip():
            raise ValueError("Error message must not be empty.")
        self.errors.append(message)
        self.status = status

    def set_gate(self, name: str, value: bool) -> None:
        if name not in DEFAULT_GATES:
            raise ValueError(f"Unknown quality gate: {name}")
        self.gates[name] = value

    def update(
        self,
        *,
        step: str | None = None,
        status: str | None = None,
        artifact: str | None = None,
        error: str | None = None,
        gates: dict[str, bool] | None = None,
    ) -> None:
        if step is not None:
            if not step.strip():
                raise ValueError("Task step must not be empty.")
            self.step = step
        if status is not None:
            if not status.strip():
                raise ValueError("Task status must not be empty.")
            self.status = status
        if artifact is not None:
            self.record_artifact(artifact)
        if error is not None:
            self.record_error(error)
        if gates is not None:
            for name, value in gates.items():
                self.set_gate(name, value)


def state_file_path(repo_root: str | Path, task_id: str) -> Path:
    _validate_task_id(task_id)
    return repo_path(repo_root, Path("workspace") / "tasks" / task_id / STATE_FILENAME)


def save_state(repo_root: str | Path, state: TaskState) -> Path:
    return write_json(
        repo_root,
        Path("workspace") / "tasks" / state.task_id / STATE_FILENAME,
        state.to_dict(),
    )


def load_state(repo_root: str | Path, task_id: str) -> TaskState:
    data = read_json(repo_root, Path("workspace") / "tasks" / task_id / STATE_FILENAME)
    return TaskState.from_dict(data)
