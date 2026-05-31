from __future__ import annotations

from pathlib import Path

from agents import DesignReviewerAgent
from artifacts import write_text, write_yaml


def write_design_artifacts(tmp_path: Path, task_id: str, *, valid_design: bool = True) -> None:
    write_yaml(
        tmp_path,
        f"workspace/tasks/{task_id}/analysis/project_context.yaml",
        {"task_id": task_id, "summary": "local MVP"},
    )
    write_text(
        tmp_path,
        f"workspace/tasks/{task_id}/architecture/mvp_architecture.md",
        "# 架构\n\n包含人工质量门。",
    )
    design = {
        "system": {"name": "ai-dev-pipeline"},
        "modules": {"agents": {"purpose": "run agents"}},
        "workflow": {"bootstrap": {"steps": ["design_review"]}},
    }
    if not valid_design:
        design.pop("modules")
    write_yaml(tmp_path, f"workspace/tasks/{task_id}/design/mvp_system_design.yaml", design)


def test_design_reviewer_agent_passes_valid_design(tmp_path: Path) -> None:
    write_design_artifacts(tmp_path, "bootstrap-001")

    result = DesignReviewerAgent().run({"repo_root": str(tmp_path), "task_id": "bootstrap-001"})

    assert result.output["status"] == "passed"
    assert result.output["decision"]["approved_for_implementation"] is True
    assert result.output["blocking_issues"] == []
    assert {check["name"] for check in result.output["checks"]} >= {
        "analysis_artifact",
        "architecture_artifact",
        "design_artifact",
        "design_modules",
        "design_workflow",
        "human_gate_design",
    }


def test_design_reviewer_agent_blocks_invalid_design(tmp_path: Path) -> None:
    write_design_artifacts(tmp_path, "bootstrap-001", valid_design=False)

    result = DesignReviewerAgent().run({"repo_root": str(tmp_path), "task_id": "bootstrap-001"})

    assert result.output["status"] == "blocked"
    assert result.output["decision"]["approved_for_implementation"] is False
    assert result.output["blocking_issues"][0]["id"] == "design_modules"


def test_design_reviewer_agent_blocks_missing_artifacts(tmp_path: Path) -> None:
    result = DesignReviewerAgent().run({"repo_root": str(tmp_path), "task_id": "missing-task"})

    assert result.output["status"] == "blocked"
    assert result.output["blocking_issues"]
