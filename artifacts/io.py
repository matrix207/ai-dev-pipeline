"""Read and write local artifacts using paths relative to the repository root."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml


def repo_path(repo_root: str | Path, relative_path: str | Path) -> Path:
    """Return an absolute path for a repository-relative artifact path."""
    root = Path(repo_root).resolve()
    rel_path = Path(relative_path)

    if rel_path.is_absolute():
        raise ValueError("Artifact paths must be relative to the repository root.")

    candidate = (root / rel_path).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError("Artifact path must stay inside the repository root.")

    return candidate


def read_yaml(repo_root: str | Path, relative_path: str | Path) -> Any:
    with repo_path(repo_root, relative_path).open("r", encoding="utf-8") as file:
        return yaml.safe_load(file)


def write_yaml(repo_root: str | Path, relative_path: str | Path, data: Any) -> Path:
    path = repo_path(repo_root, relative_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        yaml.safe_dump(data, file, allow_unicode=True, sort_keys=False)
    return path


def read_json(repo_root: str | Path, relative_path: str | Path) -> Any:
    with repo_path(repo_root, relative_path).open("r", encoding="utf-8") as file:
        return json.load(file)


def write_json(repo_root: str | Path, relative_path: str | Path, data: Any) -> Path:
    path = repo_path(repo_root, relative_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
        file.write("\n")
    return path


def read_text(repo_root: str | Path, relative_path: str | Path) -> str:
    return repo_path(repo_root, relative_path).read_text(encoding="utf-8")


def write_text(repo_root: str | Path, relative_path: str | Path, data: str) -> Path:
    path = repo_path(repo_root, relative_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data, encoding="utf-8")
    return path
