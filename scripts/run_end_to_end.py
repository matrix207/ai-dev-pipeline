#!/usr/bin/env python3
"""Run the local planning, dispatch, validation and feedback loop end to end."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agents import OptimizationPlannerAgent
from artifacts import read_json, read_yaml, write_yaml
from scripts.run_local_task import run_local_task
from tasks import TaskState, save_state


DEFAULT_TASK_ID = "workflow-001"
SUPPORTED_DISPATCH_AGENTS = {
    "CoderAgent",
    "DesignReviewerAgent",
    "TestValidatorAgent",
    "CodeReviewerAgent",
    "GoalEffectValidatorAgent",
}


def run_end_to_end(repo_root: str | Path = ".", *, task_id: str = DEFAULT_TASK_ID) -> dict[str, Any]:
    """Run a complete local feedback loop and persist a decision summary."""
    repo_root = Path(repo_root)
    paths = _workflow_paths(task_id)

    validation_task_id = f"{task_id}-validation"
    dispatch_task_id = f"{task_id}-dispatch"
    review_task_id = f"{task_id}-review"

    validation_state = run_local_task(
        repo_root,
        "ui_validation",
        task_id=validation_task_id,
        goal_approved=True,
    )
    validation_feedback_path = f"workspace/tasks/{validation_task_id}/final/validation_feedback.json"
    validation_feedback = read_json(repo_root, validation_feedback_path)

    initial_plan = OptimizationPlannerAgent().run(
        {
            "repo_root": str(repo_root),
            "feedback_paths": [validation_feedback_path],
        }
    ).output
    write_yaml(repo_root, paths["initial_plan"], initial_plan)

    dispatch_tasks = _dispatchable_task_batch(repo_root, task_id, initial_plan, validation_feedback_path)
    write_yaml(repo_root, paths["dispatch_tasks"], dispatch_tasks)

    review_tasks = _review_task_batch(task_id)
    write_yaml(repo_root, paths["review_tasks"], review_tasks)

    dispatch_state = run_local_task(
        repo_root,
        "end_to_end_dispatch",
        task_id=dispatch_task_id,
        goal_approved=True,
    )

    review_state = run_local_task(
        repo_root,
        "end_to_end_review",
        task_id=review_task_id,
        goal_approved=True,
    )

    feedback_paths = _existing_feedback_paths(
        repo_root,
        [
            validation_feedback_path,
            f"workspace/tasks/{dispatch_task_id}/final/validation_feedback.json",
            f"workspace/tasks/{review_task_id}/final/validation_feedback.json",
        ],
    )
    final_plan = OptimizationPlannerAgent().run(
        {
            "repo_root": str(repo_root),
            "feedback_paths": feedback_paths,
        }
    ).output
    write_yaml(repo_root, paths["final_plan"], final_plan)

    recommended_task = _recommended_task(repo_root, [final_plan])
    summary = {
        "task_id": task_id,
        "status": "ready_for_human_decision",
        "goal_effect": {
            "target": "一个命令运行目标验证、反馈规划、批量调度、验证评审和下一轮任务规划。",
            "validation_status": validation_feedback.get("status"),
            "alignment_score": validation_feedback.get("alignment_score"),
            "blocking_issues": validation_feedback.get("blocking_issues", []),
        },
        "current_result": {
            "validation_state": validation_state.to_dict(),
            "dispatch_state": dispatch_state.to_dict(),
            "review_state": review_state.to_dict(),
            "initial_plan_artifact": paths["initial_plan"],
            "dispatch_tasks_artifact": paths["dispatch_tasks"],
            "final_plan_artifact": paths["final_plan"],
            "feedback_artifacts": feedback_paths,
        },
        "remaining_work": _remaining_work(final_plan),
        "next_recommended_action": {
            "task_id": recommended_task.get("id"),
            "title": recommended_task.get("title"),
            "priority": recommended_task.get("priority"),
            "reason": "来自端到端反馈闭环生成的下一轮优化任务。",
        },
    }
    write_yaml(repo_root, paths["decision_summary"], summary)
    _save_parent_state(repo_root, task_id, paths, summary)
    return summary


def _workflow_paths(task_id: str) -> dict[str, str]:
    base = f"workspace/tasks/{task_id}"
    return {
        "initial_plan": f"{base}/final/initial_next_optimization_tasks.yaml",
        "dispatch_tasks": f"{base}/input/dispatch_tasks.yaml",
        "review_tasks": f"{base}/input/review_tasks.yaml",
        "final_plan": f"{base}/final/final_next_optimization_tasks.yaml",
        "decision_summary": f"{base}/final/decision_summary.yaml",
    }


def _dispatchable_task_batch(
    repo_root: Path,
    task_id: str,
    plan: dict[str, Any],
    source_feedback_path: str,
    *,
    max_tasks: int = 2,
) -> dict[str, Any]:
    tasks = []
    for task in plan.get("tasks", []):
        if task.get("recommended_agent") not in SUPPORTED_DISPATCH_AGENTS:
            continue
        cloned = dict(task)
        cloned["id"] = _unique_task_id(repo_root, f"{task_id}-{task['id']}")
        tasks.append(cloned)
        if len(tasks) >= max_tasks:
            break

    if not tasks:
        tasks.append(
            {
                "id": _unique_task_id(repo_root, f"{task_id}-fallback"),
                "title": "端到端闭环兜底调度任务",
                "priority": "medium",
                "recommended_agent": "CoderAgent",
                "risk_level": "medium",
                "human_gate": {
                    "goal_approval_required": True,
                    "risk_approval_required": False,
                    "merge_approval_required": True,
                },
                "scope": ["生成端到端闭环兜底任务的执行计划。"],
                "out_of_scope": ["自动 PR。", "自动 merge。"],
                "acceptance_criteria": ["python -m pytest -q 通过。"],
            }
        )

    return {
        "task_batch": {
            "source_task": task_id,
            "source_tasks": [task_id],
            "source_feedback_paths": [source_feedback_path],
            "goal": "端到端命令生成的可调度任务队列。",
        },
        "tasks": tasks,
    }


def _unique_task_id(repo_root: Path, base_task_id: str) -> str:
    if not (repo_root / "workspace/tasks" / base_task_id / "state.json").exists():
        return base_task_id
    index = 2
    while (repo_root / "workspace/tasks" / f"{base_task_id}-{index}" / "state.json").exists():
        index += 1
    return f"{base_task_id}-{index}"


def _review_task_batch(task_id: str) -> dict[str, Any]:
    review_task_id = f"{task_id}-review"
    return {
        "tasks": [
            {
                "id": review_task_id,
                "title": "端到端闭环决策摘要评审",
                "priority": "medium",
                "recommended_agent": "CodeReviewerAgent",
                "risk_level": "low",
                "human_gate": {
                    "goal_approval_required": True,
                    "risk_approval_required": False,
                    "merge_approval_required": True,
                },
                "scope": [
                    "输出决策摘要，包含目标效果、当前达成、剩余任务和下一步建议。",
                    "失败时保留结构化错误和已完成产物。",
                    "python -m pytest -q 通过。",
                ],
                "out_of_scope": ["自动 PR。", "自动 merge。"],
                "acceptance_criteria": [
                    "输出决策摘要，包含目标效果、当前达成、剩余任务和下一步建议。",
                    "失败时保留结构化错误和已完成产物。",
                    "python -m pytest -q 通过。",
                ],
            }
        ]
    }


def _existing_feedback_paths(repo_root: Path, paths: list[str]) -> list[str]:
    return [path for path in paths if (repo_root / path).exists()]


def _remaining_work(plan: dict[str, Any]) -> list[str]:
    tasks = plan.get("tasks", [])
    if not tasks:
        return ["暂无自动生成的剩余任务。"]
    return [f"{task.get('id')}: {task.get('title')}" for task in tasks[:5]]


def _recommended_task(repo_root: Path, task_batches: list[dict[str, Any]]) -> dict[str, Any]:
    tasks = []
    for task_batch in task_batches:
        tasks.extend(task_batch.get("tasks", []))
    tasks = [task for task in tasks if not (repo_root / "workspace/tasks" / task["id"] / "state.json").exists()]
    if not tasks:
        return {
            "id": "workflow-002",
            "title": "端到端闭环运行策略产品化",
            "priority": "medium",
        }
    priority_order = {"high": 0, "medium": 1, "low": 2}
    return sorted(tasks, key=lambda task: priority_order.get(task.get("priority", "low"), 9))[0]


def _save_parent_state(
    repo_root: Path,
    task_id: str,
    paths: dict[str, str],
    summary: dict[str, Any],
) -> None:
    state = TaskState(
        task_id=task_id,
        step="human_merge_gate",
        status="waiting_for_human_merge_approval",
        artifacts=[
            "scripts/run_end_to_end.py",
            "config/pipeline.yaml",
            paths["initial_plan"],
            paths["dispatch_tasks"],
            paths["review_tasks"],
            paths["final_plan"],
            paths["decision_summary"],
        ],
        gates={
            "goal_approved": True,
            "design_review_passed": True,
            "tests_passed": summary["current_result"]["validation_state"]["gates"].get(
                "tests_passed",
                False,
            ),
            "code_review_passed": summary["current_result"]["review_state"]["gates"].get(
                "code_review_passed",
                False,
            ),
            "human_merge_approved": False,
        },
    )
    save_state(repo_root, state)


def format_end_to_end_summary(summary: dict[str, Any]) -> str:
    goal_effect = summary["goal_effect"]
    current = summary["current_result"]
    next_action = summary["next_recommended_action"]
    return "\n".join(
        [
            "AI Dev Pipeline End-to-End Summary",
            "",
            f"Validation: {goal_effect['validation_status']}",
            f"Alignment score: {goal_effect['alignment_score']}",
            f"Dispatch state: {current['dispatch_state']['status']}",
            f"Review state: {current['review_state']['status']}",
            "",
            "Artifacts:",
            f"- Initial plan: {current['initial_plan_artifact']}",
            f"- Dispatch tasks: {current['dispatch_tasks_artifact']}",
            f"- Final plan: {current['final_plan_artifact']}",
            "",
            "Next recommended action:",
            f"- {next_action['task_id']}: {next_action['title']} ({next_action['priority']})",
            f"- Reason: {next_action['reason']}",
        ]
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the local end-to-end AI dev pipeline loop.")
    parser.add_argument("--repo-root", default=".", help="Repository root. Defaults to cwd.")
    parser.add_argument("--task-id", default=DEFAULT_TASK_ID, help="Parent task id for summary artifacts.")
    parser.add_argument("--json", action="store_true", help="Print full JSON summary.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    summary = run_end_to_end(args.repo_root, task_id=args.task_id)
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(format_end_to_end_summary(summary))
    return 0 if not summary["goal_effect"]["blocking_issues"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
