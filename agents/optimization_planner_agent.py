"""Plan next optimization tasks from validation feedback."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from agents import BaseAgent
from artifacts import read_json


DEFAULT_FEEDBACK_PATH = "workspace/tasks/validation-001/final/validation_feedback.json"


class OptimizationPlannerAgent(BaseAgent):
    """Turn validation feedback into small, reviewable optimization tasks."""

    def __init__(self, name: str = "optimization-planner") -> None:
        super().__init__(name)

    def handle(self, payload: dict[str, Any]) -> Mapping[str, Any]:
        repo_root = Path(payload.get("repo_root", "."))
        feedback_path = payload.get("feedback_path", DEFAULT_FEEDBACK_PATH)
        source_feedback = read_json(repo_root, feedback_path)

        blocking_issues = list(source_feedback.get("blocking_issues", []))
        alignment_score = float(source_feedback.get("alignment_score", 0.0))
        if blocking_issues:
            tasks = self._repair_tasks(blocking_issues)
            planning_mode = "repair"
        else:
            tasks = self._enhancement_tasks(alignment_score)
            planning_mode = "enhancement"

        return {
            "task_batch": {
                "source_task": source_feedback.get("task_id", "validation-001"),
                "language": "zh-CN",
                "status": "ready_for_human_review",
                "goal": "基于自动化验证反馈生成下一轮优化任务。",
                "planning_mode": planning_mode,
                "alignment_score": alignment_score,
            },
            "tasks": tasks,
            "human_gate": {
                "required_before_starting_dev": True,
                "required_before_pr_or_merge": True,
                "role": "人确认优化方向；Agent 执行设计、开发、验证和评审。",
            },
        }

    def _repair_tasks(self, blocking_issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
        tasks = []
        for index, issue in enumerate(blocking_issues, start=1):
            issue_id = issue.get("id", f"issue-{index}")
            tasks.append(
                {
                    "id": f"fix-{index:03d}",
                    "title": f"修复验证阻塞问题：{issue_id}",
                    "priority": "high",
                    "recommended_agent": "CoderAgent",
                    "risk_level": "high",
                    "human_gate": {
                        "goal_approval_required": True,
                        "risk_approval_required": True,
                        "merge_approval_required": True,
                    },
                    "scope": [
                        issue.get("description", "分析并修复验证阻塞问题。"),
                        issue.get("recommendation", "修复后重新运行 automated_validation workflow。"),
                    ],
                    "out_of_scope": [
                        "自动 merge。",
                        "绕过失败验证。",
                    ],
                    "acceptance_criteria": [
                        "blocking issue 不再出现在 validation_feedback.json 中。",
                        "automated_validation workflow 通过。",
                    ],
                }
            )
        return tasks

    def _enhancement_tasks(self, alignment_score: float) -> list[dict[str, Any]]:
        priority = "high" if alignment_score < 0.9 else "medium"
        return [
            {
                "id": "opt-001",
                "title": "增强代码评审 Agent 的检查深度",
                "priority": priority,
                "recommended_agent": "CoderAgent",
                "risk_level": "medium",
                "human_gate": {
                    "goal_approval_required": True,
                    "risk_approval_required": False,
                    "merge_approval_required": True,
                },
                "scope": [
                    "扩展 CodeReviewerAgent，检查任务验收标准是否都有对应 evidence。",
                    "检查测试结果、任务状态和产物路径是否一致。",
                    "输出更具体的 non_blocking_issues 和 recommendations。",
                ],
                "out_of_scope": [
                    "接入外部代码托管平台 API。",
                    "执行自动 merge。",
                ],
                "acceptance_criteria": [
                    "代码评审报告包含验收标准覆盖情况。",
                    "缺少 evidence 时产生 blocking issue 或 non-blocking recommendation。",
                    "python -m pytest -q 通过。",
                ],
            },
            {
                "id": "opt-002",
                "title": "将目标效果 demo 映射到真实 workflow 能力",
                "priority": "medium",
                "recommended_agent": "DesignReviewerAgent",
                "risk_level": "medium",
                "human_gate": {
                    "goal_approval_required": True,
                    "risk_approval_required": False,
                    "merge_approval_required": True,
                },
                "scope": [
                    "从 docs/demos/ai_dev_pipeline_demo.html 提取关键用户效果。",
                    "将关键效果映射到现有 workflow、Agent 和产物。",
                    "更新 validation_goal.yaml，使目标效果验证覆盖这些映射。",
                ],
                "out_of_scope": [
                    "重做前端 demo。",
                    "引入 Web 服务。",
                ],
                "acceptance_criteria": [
                    "validation_goal.yaml 包含目标效果映射项。",
                    "validation_feedback.json 能报告目标效果映射通过或缺失。",
                ],
            },
            {
                "id": "opt-003",
                "title": "把验证反馈转换为可执行任务的端到端 workflow",
                "priority": "medium",
                "recommended_agent": "CoderAgent",
                "risk_level": "medium",
                "human_gate": {
                    "goal_approval_required": True,
                    "risk_approval_required": False,
                    "merge_approval_required": True,
                },
                "scope": [
                    "新增 optimization_planning workflow。",
                    "运行后生成 workspace/tasks/optimization-001/final/next_optimization_tasks.yaml。",
                    "在 README 中说明从验证到优化任务的闭环命令。",
                ],
                "out_of_scope": [
                    "自动执行生成的优化任务。",
                    "自动提交或合并。",
                ],
                "acceptance_criteria": [
                    "workflow 能读取 validation_feedback.json 并生成优化任务。",
                    "验证通过和验证失败两种反馈都有测试覆盖。",
                ],
            },
        ]
