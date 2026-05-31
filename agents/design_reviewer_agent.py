"""Design review agent skeleton for local pipeline artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from agents import BaseAgent
from artifacts import read_text, read_yaml


def default_design_artifact_paths(task_id: str) -> dict[str, str]:
    return {
        "analysis": f"workspace/tasks/{task_id}/analysis/project_context.yaml",
        "architecture": f"workspace/tasks/{task_id}/architecture/mvp_architecture.md",
        "design": f"workspace/tasks/{task_id}/design/mvp_system_design.yaml",
    }


class DesignReviewerAgent(BaseAgent):
    """Review analysis, architecture, and system design artifacts."""

    def __init__(self, name: str = "design-reviewer") -> None:
        super().__init__(name)

    def handle(self, payload: dict[str, Any]) -> Mapping[str, Any]:
        task_id = payload["task_id"]
        repo_root = Path(payload.get("repo_root", "."))
        artifact_paths = dict(payload.get("artifact_paths") or default_design_artifact_paths(task_id))

        checks: list[dict[str, str]] = []
        blocking_issues: list[dict[str, str]] = []

        analysis = self._read_yaml_artifact(
            repo_root,
            artifact_paths.get("analysis", ""),
            "analysis_artifact",
            checks,
            blocking_issues,
        )
        architecture = self._read_text_artifact(
            repo_root,
            artifact_paths.get("architecture", ""),
            "architecture_artifact",
            checks,
            blocking_issues,
        )
        design = self._read_yaml_artifact(
            repo_root,
            artifact_paths.get("design", ""),
            "design_artifact",
            checks,
            blocking_issues,
        )

        if isinstance(design, dict) and "modules" in design:
            checks.append(
                {
                    "name": "design_modules",
                    "result": "pass",
                    "notes": "系统设计包含 modules 定义。",
                }
            )
        else:
            self._blocking_issue(
                checks,
                blocking_issues,
                "design_modules",
                "系统设计缺少 modules 定义。",
                "在设计产物中补充模块边界和职责。",
            )

        if isinstance(design, dict) and "workflow" in design:
            checks.append(
                {
                    "name": "design_workflow",
                    "result": "pass",
                    "notes": "系统设计包含 workflow 定义。",
                }
            )
        else:
            self._blocking_issue(
                checks,
                blocking_issues,
                "design_workflow",
                "系统设计缺少 workflow 定义。",
                "在设计产物中补充任务执行流程。",
            )

        if architecture and "人工" in architecture and "质量门" in architecture:
            checks.append(
                {
                    "name": "human_gate_design",
                    "result": "pass",
                    "notes": "架构文档描述了人工质量门。",
                }
            )
        else:
            self._blocking_issue(
                checks,
                blocking_issues,
                "human_gate_design",
                "架构文档未明确人工质量门。",
                "补充目标门、风险门或合并门的职责边界。",
            )

        approved = not blocking_issues
        return {
            "task_id": task_id,
            "status": "passed" if approved else "blocked",
            "decision": {
                "approved_for_implementation": approved,
                "requires_human_review": not approved,
            },
            "checks": checks,
            "blocking_issues": blocking_issues,
            "non_blocking_issues": [],
            "reviewed_artifacts": artifact_paths,
        }

    def _read_yaml_artifact(
        self,
        repo_root: Path,
        artifact_path: str,
        check_name: str,
        checks: list[dict[str, str]],
        blocking_issues: list[dict[str, str]],
    ) -> Any:
        try:
            content = read_yaml(repo_root, artifact_path)
        except Exception as exc:
            self._blocking_issue(
                checks,
                blocking_issues,
                check_name,
                f"无法读取 YAML 产物：{artifact_path}",
                str(exc),
            )
            return None
        if content:
            checks.append(
                {
                    "name": check_name,
                    "result": "pass",
                    "notes": f"已读取 {artifact_path}。",
                }
            )
            return content
        self._blocking_issue(
            checks,
            blocking_issues,
            check_name,
            f"YAML 产物为空：{artifact_path}",
            "补充结构化内容。",
        )
        return None

    def _read_text_artifact(
        self,
        repo_root: Path,
        artifact_path: str,
        check_name: str,
        checks: list[dict[str, str]],
        blocking_issues: list[dict[str, str]],
    ) -> str:
        try:
            content = read_text(repo_root, artifact_path)
        except Exception as exc:
            self._blocking_issue(
                checks,
                blocking_issues,
                check_name,
                f"无法读取文本产物：{artifact_path}",
                str(exc),
            )
            return ""
        if content.strip():
            checks.append(
                {
                    "name": check_name,
                    "result": "pass",
                    "notes": f"已读取 {artifact_path}。",
                }
            )
            return content
        self._blocking_issue(
            checks,
            blocking_issues,
            check_name,
            f"文本产物为空：{artifact_path}",
            "补充设计说明。",
        )
        return ""

    def _blocking_issue(
        self,
        checks: list[dict[str, str]],
        blocking_issues: list[dict[str, str]],
        check_name: str,
        description: str,
        recommendation: str,
    ) -> None:
        checks.append(
            {
                "name": check_name,
                "result": "fail",
                "notes": description,
            }
        )
        blocking_issues.append(
            {
                "id": check_name,
                "severity": "high",
                "description": description,
                "recommendation": recommendation,
            }
        )
