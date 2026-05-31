#!/usr/bin/env python3
"""Run validation and optimization planning, then write a decision summary."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from artifacts import read_json, read_yaml, write_yaml
from scripts.run_local_task import run_local_task


SUMMARY_PATH = "workspace/tasks/planning-002/final/decision_summary.yaml"


def run_validation_loop(repo_root: str | Path = ".") -> dict[str, Any]:
    repo_root = Path(repo_root)
    validation_state = run_local_task(repo_root, "automated_validation", goal_approved=True)
    optimization_state = run_local_task(repo_root, "optimization_planning", goal_approved=True)

    feedback = read_json(repo_root, "workspace/tasks/validation-001/final/validation_feedback.json")
    optimization_tasks = read_yaml(
        repo_root,
        "workspace/tasks/optimization-001/final/next_optimization_tasks.yaml",
    )
    product_tasks = _read_optional_yaml(
        repo_root,
        "workspace/tasks/planning-002/final/next_product_tasks.yaml",
    )

    recommended_task = _recommended_task(repo_root, [product_tasks, optimization_tasks])
    summary = {
        "task_id": "planning-002",
        "status": "ready_for_human_decision",
        "goal_effect": {
            "target": "一个命令运行验证、目标效果检查和优化任务规划，并给出下一步决策摘要。",
            "validation_status": feedback.get("status"),
            "alignment_score": feedback.get("alignment_score"),
            "blocking_issues": feedback.get("blocking_issues", []),
        },
        "current_result": {
            "validation_state": validation_state.to_dict(),
            "optimization_state": optimization_state.to_dict(),
            "feedback_artifact": "workspace/tasks/validation-001/final/validation_feedback.json",
            "optimization_tasks_artifact": "workspace/tasks/optimization-001/final/next_optimization_tasks.yaml",
        },
        "remaining_work": [
            "进一步产品化 CLI 输出和错误提示。",
            "增强优化任务优先级、owner/agent 建议和风险说明。",
            "让失败反馈可直接生成修复任务并进入下一轮执行。",
        ],
        "next_recommended_action": {
            "task_id": recommended_task.get("id"),
            "title": recommended_task.get("title"),
            "priority": recommended_task.get("priority"),
            "reason": "来自 optimization_planning 生成的下一轮优化任务。",
        },
    }
    write_yaml(repo_root, SUMMARY_PATH, summary)
    return summary


def _read_optional_yaml(repo_root: Path, relative_path: str) -> dict[str, Any]:
    try:
        return read_yaml(repo_root, relative_path)
    except Exception:
        return {}


def _recommended_task(repo_root: Path, task_batches: list[dict[str, Any]]) -> dict[str, Any]:
    tasks = []
    for task_batch in task_batches:
        tasks.extend(task_batch.get("tasks", []))
    tasks = [task for task in tasks if not (repo_root / "workspace/tasks" / task["id"] / "state.json").exists()]
    if not tasks:
        return {"id": None, "title": "暂无下一步任务", "priority": "none"}
    priority_order = {"high": 0, "medium": 1, "low": 2}
    return sorted(tasks, key=lambda task: priority_order.get(task.get("priority", "low"), 9))[0]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run validation loop and write decision summary.")
    parser.add_argument("--repo-root", default=".", help="Repository root. Defaults to cwd.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    summary = run_validation_loop(args.repo_root)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if not summary["goal_effect"]["blocking_issues"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
