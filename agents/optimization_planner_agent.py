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
        feedback_paths = self._feedback_paths(payload)
        source_feedbacks = [
            {
                "path": feedback_path,
                "feedback": read_json(repo_root, feedback_path),
            }
            for feedback_path in feedback_paths
        ]

        blocking_issues = self._blocking_issues(source_feedbacks)
        alignment_score = self._alignment_score(source_feedbacks)
        if blocking_issues:
            tasks = self._repair_tasks(blocking_issues)
            planning_mode = "repair"
        else:
            tasks = self._enhancement_tasks(alignment_score)
            planning_mode = "enhancement"

        source_tasks = [
            str(item["feedback"].get("task_id", "validation-001")) for item in source_feedbacks
        ]
        return {
            "task_batch": {
                "source_task": source_tasks[0],
                "source_tasks": source_tasks,
                "source_feedback_paths": feedback_paths,
                "language": "zh-CN",
                "status": "ready_for_human_review",
                "goal": "基于自动化验证反馈生成下一轮优化任务。",
                "planning_mode": planning_mode,
                "alignment_score": alignment_score,
                "blocking_issue_count": len(blocking_issues),
            },
            "tasks": tasks,
            "human_gate": {
                "required_before_starting_dev": True,
                "required_before_pr_or_merge": True,
                "role": "人确认优化方向；Agent 执行设计、开发、验证和评审。",
            },
        }

    def _feedback_paths(self, payload: dict[str, Any]) -> list[str]:
        feedback_paths = payload.get("feedback_paths")
        if feedback_paths:
            if not isinstance(feedback_paths, list) or not all(
                isinstance(path, str) for path in feedback_paths
            ):
                raise TypeError("feedback_paths must be a list of strings.")
            return feedback_paths
        return [payload.get("feedback_path", DEFAULT_FEEDBACK_PATH)]

    def _blocking_issues(self, source_feedbacks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        for item in source_feedbacks:
            feedback = item["feedback"]
            source_path = item["path"]
            source_task = feedback.get("task_id", "validation-001")
            for issue in feedback.get("blocking_issues", []):
                enriched_issue = dict(issue)
                enriched_issue["source_task"] = source_task
                enriched_issue["source_feedback_path"] = source_path
                issues.append(enriched_issue)
        return issues

    def _alignment_score(self, source_feedbacks: list[dict[str, Any]]) -> float:
        scores = [
            float(item["feedback"].get("alignment_score", 0.0))
            for item in source_feedbacks
        ]
        return min(scores) if scores else 0.0

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
                        f"来源任务：{issue.get('source_task', 'validation-001')}。",
                        f"来源反馈：{issue.get('source_feedback_path', DEFAULT_FEEDBACK_PATH)}。",
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
                "id": "feedback-002",
                "title": "把下一轮优化任务接入调度执行",
                "priority": priority,
                "recommended_agent": "CoderAgent",
                "risk_level": "medium",
                "human_gate": {
                    "goal_approval_required": True,
                    "risk_approval_required": False,
                    "merge_approval_required": True,
                },
                "scope": [
                    "让 feedback_planning 生成的 next_optimization_tasks.yaml 可直接作为 optimization_dispatch 的 tasks_path。",
                    "运行调度后，父任务能记录来源反馈和被调度任务验证状态。",
                    "保留 goal approval 和 merge approval 人工质量门。",
                ],
                "out_of_scope": [
                    "接入外部代码托管平台 API。",
                    "执行自动 merge。",
                ],
                "acceptance_criteria": [
                    "optimization_dispatch 可读取 workspace/tasks/feedback-001/final/next_optimization_tasks.yaml。",
                    "调度产物能引用来源 validation_feedback。",
                    "python -m pytest -q 通过。",
                ],
            },
            {
                "id": "dispatch-002",
                "title": "支持更多本地 Agent 调度",
                "priority": "medium",
                "recommended_agent": "ArchitectAgent",
                "risk_level": "medium",
                "human_gate": {
                    "goal_approval_required": True,
                    "risk_approval_required": False,
                    "merge_approval_required": True,
                },
                "scope": [
                    "为 dispatcher 增加安全的本地 Agent 调度表。",
                    "支持 DesignReviewerAgent、TestValidatorAgent、CodeReviewerAgent、GoalEffectValidatorAgent 的最小调度适配。",
                    "不支持的 Agent 继续返回结构化 blocking issue。",
                ],
                "out_of_scope": [
                    "调用外部 Agent 服务。",
                    "自动 PR 或 merge。",
                ],
                "acceptance_criteria": [
                    "dispatcher 对支持的 Agent 有测试覆盖。",
                    "unsupported_agent 路径仍有测试覆盖。",
                    "python -m pytest -q 通过。",
                ],
            },
            {
                "id": "ui-validation-001",
                "title": "增加目标效果图的自动检查",
                "priority": "medium",
                "recommended_agent": "TestValidatorAgent",
                "risk_level": "low",
                "human_gate": {
                    "goal_approval_required": True,
                    "risk_approval_required": False,
                    "merge_approval_required": True,
                },
                "scope": [
                    "从 docs/demos/ai_dev_pipeline_demo.html 提取可机读页面结构和核心交互验收点。",
                    "让 GoalEffectValidatorAgent 报告目标效果图相关检查结果。",
                    "将目标效果检查结果写入 validation_feedback.json。",
                ],
                "out_of_scope": [
                    "重做前端 demo。",
                    "引入浏览器云服务。",
                ],
                "acceptance_criteria": [
                    "目标效果图检查有结构化产物。",
                    "validation_feedback.json 包含目标效果图检查结论。",
                    "python -m pytest -q 通过。",
                ],
            },
        ]
