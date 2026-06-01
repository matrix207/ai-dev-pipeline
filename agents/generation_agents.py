"""Generation agents that create early-stage delivery artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from agents.base_agent import BaseAgent


class ProjectAnalysisAgent(BaseAgent):
    """Analyze repository context before requirements or design work."""

    def __init__(self, name: str = "project-analysis") -> None:
        super().__init__(name)

    def handle(self, payload: dict[str, Any]) -> Mapping[str, Any]:
        repo_root = Path(payload.get("repo_root", "."))
        task_id = payload["task_id"]
        selected_task = dict(payload.get("selected_task", {}))
        context_files = self._existing_context_files(repo_root)

        return {
            "task_id": task_id,
            "status": "passed",
            "artifact_type": "project_context",
            "summary": "项目已具备本地 Agent、任务编排、结构化产物和验证闭环基础。",
            "source_task": {
                "id": selected_task.get("id", task_id),
                "title": selected_task.get("title", ""),
                "scope": list(selected_task.get("scope", [])),
            },
            "context_files": context_files,
            "observations": [
                "代码以 Python 本地模块为主，适合继续通过小步可测试任务演进。",
                "workspace/tasks/{task_id}/ 已作为任务输入、评审和最终产物的持久化边界。",
                "人工审批质量门仍是进入下一阶段和合并前的必要控制点。",
            ],
            "recommended_next_artifacts": [
                f"workspace/tasks/{task_id}/requirements/requirements.json",
                f"workspace/tasks/{task_id}/architecture/architecture_analysis.json",
                f"workspace/tasks/{task_id}/design/system_design.json",
            ],
        }

    def _existing_context_files(self, repo_root: Path) -> list[str]:
        candidates = ["README.md", "AGENTS.md", "config/pipeline.yaml"]
        return [path for path in candidates if (repo_root / path).exists()]


class RequirementAnalysisAgent(BaseAgent):
    """Turn a task definition into requirements and acceptance criteria."""

    def __init__(self, name: str = "requirement-analysis") -> None:
        super().__init__(name)

    def handle(self, payload: dict[str, Any]) -> Mapping[str, Any]:
        task_id = payload["task_id"]
        selected_task = dict(payload.get("selected_task", {}))
        scope = list(selected_task.get("scope", []))
        acceptance_criteria = list(selected_task.get("acceptance_criteria", []))

        return {
            "task_id": task_id,
            "status": "passed",
            "artifact_type": "requirements",
            "goal": selected_task.get("title", "完成本地 Agent 流水线任务。"),
            "functional_requirements": scope or ["根据任务定义输出结构化需求。"],
            "acceptance_criteria": acceptance_criteria or ["结构化需求产物已生成。"],
            "out_of_scope": list(selected_task.get("out_of_scope", [])),
            "human_gates": {
                "goal_approval_required": True,
                "merge_approval_required": True,
            },
        }


class ArchitectAgent(BaseAgent):
    """Create a lightweight architecture analysis for a task."""

    def __init__(self, name: str = "architect") -> None:
        super().__init__(name)

    def handle(self, payload: dict[str, Any]) -> Mapping[str, Any]:
        task_id = payload["task_id"]
        selected_task = dict(payload.get("selected_task", {}))

        return {
            "task_id": task_id,
            "status": "passed",
            "artifact_type": "architecture_analysis",
            "architecture_goal": selected_task.get("title", "保持本地闭环可演进。"),
            "module_boundaries": [
                {
                    "module": "agents",
                    "responsibility": "实现独立 Agent 的本地结构化转换能力。",
                },
                {
                    "module": "scripts",
                    "responsibility": "负责编排 workflow、质量门和运行记录。",
                },
                {
                    "module": "workspace/tasks",
                    "responsibility": "持久化每个任务的输入、执行、评审和最终产物。",
                },
            ],
            "risks": [
                "Agent 直接耦合会降低可测试性，应继续通过结构化产物交互。",
                "自动化推进不能绕过人工审批质量门。",
            ],
            "recommended_design_artifact": f"workspace/tasks/{task_id}/design/system_design.json",
        }


class SystemDesignAgent(BaseAgent):
    """Create an implementation-oriented system design for a task."""

    def __init__(self, name: str = "system-design") -> None:
        super().__init__(name)

    def handle(self, payload: dict[str, Any]) -> Mapping[str, Any]:
        task_id = payload["task_id"]
        selected_task = dict(payload.get("selected_task", {}))

        return {
            "task_id": task_id,
            "status": "passed",
            "artifact_type": "system_design",
            "design_goal": selected_task.get("title", "输出可实现的系统设计。"),
            "modules": {
                "agent": {
                    "purpose": "执行单一职责的结构化输入输出转换。",
                    "inputs": ["repo_root", "task_id", "selected_task"],
                    "outputs": ["status", "artifact_type", "结构化设计数据"],
                },
                "dispatcher": {
                    "purpose": "选择本地 Agent 并写入任务产物和状态。",
                    "quality_gate": "调度后仍需测试、评审和人工审批。",
                },
            },
            "workflow": [
                "读取任务定义。",
                "生成结构化设计产物。",
                "写入 workspace/tasks/{task_id}/。",
                "等待验证和人工质量门。",
            ],
            "acceptance_criteria": list(selected_task.get("acceptance_criteria", [])),
        }
