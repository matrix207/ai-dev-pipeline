#!/usr/bin/env python3
"""Run the local planning, dispatch, validation and feedback loop end to end."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agents import OptimizationPlannerAgent
from artifacts import read_json, read_yaml, write_json, write_yaml
from scripts.run_local_task import run_local_task
from tasks import TaskState, load_state, save_state


DEFAULT_TASK_ID = "workflow-001"
RERUN_POLICIES = {"new_ids", "skip_completed", "force"}
SUCCESS_STATUSES = {"waiting_for_human_merge_approval", "completed"}
SUPPORTED_DISPATCH_AGENTS = {
    "CoderAgent",
    "DesignReviewerAgent",
    "TestValidatorAgent",
    "CodeReviewerAgent",
    "GoalEffectValidatorAgent",
}


def run_end_to_end(
    repo_root: str | Path = ".",
    *,
    task_id: str = DEFAULT_TASK_ID,
    dry_run: bool = False,
    rerun_policy: str = "new_ids",
    run_id: str | None = None,
) -> dict[str, Any]:
    """Run a complete local feedback loop and persist a decision summary."""
    if rerun_policy not in RERUN_POLICIES:
        raise ValueError(f"Unknown rerun policy: {rerun_policy}")

    repo_root = Path(repo_root)
    paths = _workflow_paths(task_id)
    run_metadata = _run_metadata(run_id)

    validation_task_id = f"{task_id}-validation"
    dispatch_task_id = f"{task_id}-dispatch"
    review_task_id = f"{task_id}-review"

    if dry_run:
        return _dry_run_summary(
            repo_root,
            task_id=task_id,
            paths=paths,
            run_metadata=run_metadata,
            rerun_policy=rerun_policy,
            validation_task_id=validation_task_id,
            dispatch_task_id=dispatch_task_id,
            review_task_id=review_task_id,
        )

    events: list[dict[str, Any]] = []
    validation_state = _run_or_skip_workflow(
        repo_root,
        workflow_name="ui_validation",
        task_id=validation_task_id,
        rerun_policy=rerun_policy,
        required_artifacts=[f"workspace/tasks/{validation_task_id}/final/validation_feedback.json"],
        label="validation",
        events=events,
    )
    validation_feedback_path = f"workspace/tasks/{validation_task_id}/final/validation_feedback.json"
    validation_feedback = _read_feedback_or_placeholder(repo_root, validation_feedback_path, validation_state)

    initial_plan = OptimizationPlannerAgent().run(
        {
            "repo_root": str(repo_root),
            "feedback_paths": [validation_feedback_path],
        }
    ).output
    write_yaml(repo_root, paths["initial_plan"], initial_plan)

    dispatch_tasks = _dispatchable_task_batch(
        repo_root,
        task_id,
        initial_plan,
        validation_feedback_path,
        rerun_policy=rerun_policy,
    )
    write_yaml(repo_root, paths["dispatch_tasks"], dispatch_tasks)

    review_tasks = _review_task_batch(task_id)
    write_yaml(repo_root, paths["review_tasks"], review_tasks)

    dispatch_state = _run_or_skip_workflow(
        repo_root,
        workflow_name="end_to_end_dispatch",
        task_id=dispatch_task_id,
        rerun_policy=rerun_policy,
        required_artifacts=[f"workspace/tasks/{dispatch_task_id}/final/validation_feedback.json"],
        label="dispatch",
        events=events,
    )

    review_state = _run_or_skip_workflow(
        repo_root,
        workflow_name="end_to_end_review",
        task_id=review_task_id,
        rerun_policy=rerun_policy,
        required_artifacts=[f"workspace/tasks/{review_task_id}/final/validation_feedback.json"],
        label="review",
        events=events,
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

    recommended_task = _recommended_task(repo_root, task_id, [final_plan])
    execution_summary = _execution_summary(events, recommended_task)
    summary = {
        "task_id": task_id,
        "status": "ready_for_human_decision",
        "run_metadata": run_metadata,
        "run_strategy": {
            "dry_run": False,
            "rerun_policy": rerun_policy,
        },
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
        "execution_summary": execution_summary,
        "retry_plan": _retry_plan(execution_summary),
        "remaining_work": _remaining_work(final_plan),
        "next_recommended_action": {
            "task_id": recommended_task.get("id"),
            "title": recommended_task.get("title"),
            "priority": recommended_task.get("priority"),
            "reason": "来自端到端反馈闭环生成的下一轮优化任务。",
        },
    }
    summary["evidence_map"] = _evidence_map(summary)
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


def _run_metadata(run_id: str | None) -> dict[str, str]:
    started_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return {
        "run_id": run_id or started_at.replace("-", "").replace(":", ""),
        "started_at": started_at,
    }


def _task_succeeded(state: TaskState, required_artifacts: list[str], repo_root: Path) -> bool:
    if state.status not in SUCCESS_STATUSES:
        return False
    return all((repo_root / artifact).exists() for artifact in required_artifacts)


def _state_event(label: str, state: TaskState, action: str) -> dict[str, Any]:
    if action == "skipped":
        category = "skipped"
    elif state.status in SUCCESS_STATUSES:
        category = "completed"
    else:
        category = "failed"
    return {
        "step": label,
        "task_id": state.task_id,
        "status": category,
        "state_status": state.status,
        "artifacts": state.artifacts,
        "errors": state.errors,
    }


def _run_or_skip_workflow(
    repo_root: Path,
    *,
    workflow_name: str,
    task_id: str,
    rerun_policy: str,
    required_artifacts: list[str],
    label: str,
    events: list[dict[str, Any]],
) -> TaskState:
    if rerun_policy == "skip_completed":
        try:
            existing_state = load_state(repo_root, task_id)
        except Exception:
            existing_state = None
        if existing_state and _task_succeeded(existing_state, required_artifacts, repo_root):
            events.append(_state_event(label, existing_state, "skipped"))
            return existing_state

    state = run_local_task(
        repo_root,
        workflow_name,
        task_id=task_id,
        goal_approved=True,
    )
    events.append(_state_event(label, state, "completed"))
    return state


def _read_feedback_or_placeholder(repo_root: Path, path: str, state: TaskState) -> dict[str, Any]:
    if (repo_root / path).exists():
        return read_json(repo_root, path)
    feedback = {
        "task_id": state.task_id,
        "status": "failed",
        "alignment_score": 0.0,
        "blocking_issues": [
            {
                "id": "missing_validation_feedback",
                "severity": "high",
                "description": f"Expected validation feedback was not written: {path}",
                "recommendation": "修复失败步骤后使用 --rerun-policy skip_completed 或 force 重新运行。",
            }
        ],
    }
    write_json(repo_root, path, feedback)
    state.record_artifact(path)
    save_state(repo_root, state)
    return feedback


def _dispatchable_task_batch(
    repo_root: Path,
    task_id: str,
    plan: dict[str, Any],
    source_feedback_path: str,
    *,
    max_tasks: int = 2,
    rerun_policy: str = "new_ids",
) -> dict[str, Any]:
    tasks = []
    for task in plan.get("tasks", []):
        if task.get("recommended_agent") not in SUPPORTED_DISPATCH_AGENTS:
            continue
        cloned = dict(task)
        cloned["id"] = _dispatch_task_id(repo_root, f"{task_id}-{task['id']}", rerun_policy)
        tasks.append(cloned)
        if len(tasks) >= max_tasks:
            break

    if not tasks:
        tasks.append(
            {
                "id": _dispatch_task_id(repo_root, f"{task_id}-fallback", rerun_policy),
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


def _dispatch_task_id(repo_root: Path, base_task_id: str, rerun_policy: str) -> str:
    if rerun_policy == "new_ids":
        return _unique_task_id(repo_root, base_task_id)
    return base_task_id


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


def _execution_summary(
    events: list[dict[str, Any]],
    recommended_task: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    summary = {
        "completed": [],
        "skipped": [],
        "failed": [],
        "next": [
            {
                "task_id": recommended_task.get("id"),
                "title": recommended_task.get("title"),
                "priority": recommended_task.get("priority"),
            }
        ],
    }
    for event in events:
        summary[event["status"]].append(event)
    return summary


def _retry_plan(execution_summary: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    failed = execution_summary.get("failed", [])
    if not failed:
        return {
            "status": "not_required",
            "reason": "自动化步骤已完成，等待人工质量门决策。",
            "recommended_command": None,
        }
    first_failed = failed[0]
    reusable = execution_summary.get("completed", []) + execution_summary.get("skipped", [])
    return {
        "status": "retry_required",
        "failed_step": first_failed["step"],
        "failed_task_id": first_failed["task_id"],
        "reason": first_failed.get("errors") or first_failed.get("state_status"),
        "reusable_steps": [
            {"step": item["step"], "task_id": item["task_id"], "status": item["status"]}
            for item in reusable
        ],
        "recommended_command": "python scripts/run_end_to_end.py --rerun-policy skip_completed",
    }


def _evidence_item(
    *,
    decision: str,
    status: str,
    evidence: list[str],
    notes: str,
) -> dict[str, Any]:
    return {
        "decision": decision,
        "status": status,
        "evidence": evidence,
        "notes": notes,
    }


def _evidence_map(summary: dict[str, Any]) -> list[dict[str, Any]]:
    current = summary["current_result"]
    execution = summary["execution_summary"]
    retry = summary["retry_plan"]
    goal = summary["goal_effect"]
    validation_state = current["validation_state"]
    dispatch_state = current["dispatch_state"]
    review_state = current["review_state"]
    return [
        _evidence_item(
            decision="goal_effect_aligned",
            status=str(goal.get("validation_status")),
            evidence=list(current.get("feedback_artifacts", [])),
            notes=f"alignment_score={goal.get('alignment_score')}; blocking_issues={len(goal.get('blocking_issues', []))}",
        ),
        _evidence_item(
            decision="tests_passed",
            status="passed" if validation_state.get("gates", {}).get("tests_passed") else "not_passed",
            evidence=list(validation_state.get("artifacts", [])),
            notes=f"validation_state={validation_state.get('status')}",
        ),
        _evidence_item(
            decision="dispatch_validated",
            status=dispatch_state.get("status", "unknown"),
            evidence=list(dispatch_state.get("artifacts", [])),
            notes=f"completed={len(execution.get('completed', []))}; skipped={len(execution.get('skipped', []))}",
        ),
        _evidence_item(
            decision="code_review_passed",
            status="passed" if review_state.get("gates", {}).get("code_review_passed") else "not_passed",
            evidence=list(review_state.get("artifacts", [])),
            notes=f"review_state={review_state.get('status')}",
        ),
        _evidence_item(
            decision="retry_required",
            status=retry.get("status", "unknown"),
            evidence=[
                item["task_id"]
                for item in execution.get("failed", [])
                if item.get("task_id")
            ],
            notes=str(retry.get("reason")),
        ),
        _evidence_item(
            decision="next_action",
            status=summary["next_recommended_action"].get("priority", "unknown"),
            evidence=[current["final_plan_artifact"]],
            notes=f"{summary['next_recommended_action'].get('task_id')}: {summary['next_recommended_action'].get('title')}",
        ),
    ]


def _planned_event(
    repo_root: Path,
    *,
    label: str,
    task_id: str,
    rerun_policy: str,
    required_artifacts: list[str],
) -> dict[str, Any]:
    try:
        existing_state = load_state(repo_root, task_id)
    except Exception:
        existing_state = None
    if rerun_policy == "skip_completed" and existing_state and _task_succeeded(
        existing_state,
        required_artifacts,
        repo_root,
    ):
        return _state_event(label, existing_state, "skipped")
    return {
        "step": label,
        "task_id": task_id,
        "status": "next",
        "state_status": "planned",
        "artifacts": required_artifacts,
        "errors": [],
    }


def _dry_run_summary(
    repo_root: Path,
    *,
    task_id: str,
    paths: dict[str, str],
    run_metadata: dict[str, str],
    rerun_policy: str,
    validation_task_id: str,
    dispatch_task_id: str,
    review_task_id: str,
) -> dict[str, Any]:
    events = [
        _planned_event(
            repo_root,
            label="validation",
            task_id=validation_task_id,
            rerun_policy=rerun_policy,
            required_artifacts=[f"workspace/tasks/{validation_task_id}/final/validation_feedback.json"],
        ),
        {
            "step": "planning",
            "task_id": task_id,
            "status": "next",
            "state_status": "planned",
            "artifacts": [paths["initial_plan"], paths["dispatch_tasks"], paths["review_tasks"]],
            "errors": [],
        },
        _planned_event(
            repo_root,
            label="dispatch",
            task_id=dispatch_task_id,
            rerun_policy=rerun_policy,
            required_artifacts=[f"workspace/tasks/{dispatch_task_id}/final/validation_feedback.json"],
        ),
        _planned_event(
            repo_root,
            label="review",
            task_id=review_task_id,
            rerun_policy=rerun_policy,
            required_artifacts=[f"workspace/tasks/{review_task_id}/final/validation_feedback.json"],
        ),
        {
            "step": "final_planning",
            "task_id": task_id,
            "status": "next",
            "state_status": "planned",
            "artifacts": [paths["final_plan"], paths["decision_summary"]],
            "errors": [],
        },
    ]
    execution_summary = {
        "completed": [],
        "skipped": [event for event in events if event["status"] == "skipped"],
        "failed": [],
        "next": [event for event in events if event["status"] == "next"],
    }
    return {
        "task_id": task_id,
        "status": "dry_run",
        "run_metadata": run_metadata,
        "run_strategy": {
            "dry_run": True,
            "rerun_policy": rerun_policy,
        },
        "goal_effect": {
            "target": "一个命令运行目标验证、反馈规划、批量调度、验证评审和下一轮任务规划。",
            "validation_status": "not_run",
            "alignment_score": None,
            "blocking_issues": [],
        },
        "current_result": {
            "validation_state": {"task_id": validation_task_id, "status": "planned"},
            "dispatch_state": {"task_id": dispatch_task_id, "status": "planned"},
            "review_state": {"task_id": review_task_id, "status": "planned"},
            "initial_plan_artifact": paths["initial_plan"],
            "dispatch_tasks_artifact": paths["dispatch_tasks"],
            "final_plan_artifact": paths["final_plan"],
            "feedback_artifacts": [],
        },
        "execution_summary": execution_summary,
        "retry_plan": {
            "status": "not_required",
            "reason": "Dry run only; no workflow steps were executed.",
            "recommended_command": None,
        },
        "remaining_work": ["dry-run 未执行实际验证；正式运行后生成剩余任务列表。"],
        "next_recommended_action": {
            "task_id": task_id,
            "title": "执行端到端闭环正式运行",
            "priority": "medium",
            "reason": "dry-run 只预览运行计划，不写入产物。",
        },
        "evidence_map": [
            _evidence_item(
                decision="dry_run_plan",
                status="planned",
                evidence=[
                    paths["initial_plan"],
                    paths["dispatch_tasks"],
                    paths["review_tasks"],
                    paths["final_plan"],
                    paths["decision_summary"],
                ],
                notes="dry-run 仅预览计划，不写入产物。",
            )
        ],
    }


def _fallback_recommended_task(task_id: str) -> dict[str, Any]:
    prefix, separator, suffix = task_id.rpartition("-")
    if separator and suffix.isdigit():
        next_task_id = f"{prefix}-{int(suffix) + 1:0{len(suffix)}d}"
    else:
        next_task_id = f"{task_id}-next"
    title_by_task_id = {
        "workflow-002": "端到端闭环运行策略产品化",
        "workflow-003": "端到端闭环持续优化",
        "workflow-004": "端到端闭环决策产物可追溯化",
    }
    return {
        "id": next_task_id,
        "title": title_by_task_id.get(next_task_id, "端到端闭环持续优化"),
        "priority": "medium",
    }


def _recommended_task(repo_root: Path, task_id: str, task_batches: list[dict[str, Any]]) -> dict[str, Any]:
    tasks = []
    for task_batch in task_batches:
        tasks.extend(task_batch.get("tasks", []))
    tasks = [task for task in tasks if not (repo_root / "workspace/tasks" / task["id"] / "state.json").exists()]
    if not tasks:
        return _fallback_recommended_task(task_id)
    priority_order = {"high": 0, "medium": 1, "low": 2}
    return sorted(tasks, key=lambda task: priority_order.get(task.get("priority", "low"), 9))[0]


def _save_parent_state(
    repo_root: Path,
    task_id: str,
    paths: dict[str, str],
    summary: dict[str, Any],
) -> None:
    failed_steps = summary.get("execution_summary", {}).get("failed", [])
    status = "blocked_by_end_to_end_step" if failed_steps else "waiting_for_human_merge_approval"
    state = TaskState(
        task_id=task_id,
        step="retry_plan" if failed_steps else "human_merge_gate",
        status=status,
        artifacts=[
            "scripts/run_end_to_end.py",
            "scripts/run_local_task.py",
            "config/pipeline.yaml",
            "tests/test_run_end_to_end.py",
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
    for failed_step in failed_steps:
        state.record_error(f"{failed_step['step']}: {failed_step['state_status']}")
    save_state(repo_root, state)


def format_end_to_end_summary(summary: dict[str, Any]) -> str:
    goal_effect = summary["goal_effect"]
    current = summary["current_result"]
    next_action = summary["next_recommended_action"]
    execution = summary.get("execution_summary", {})
    retry = summary.get("retry_plan", {})
    run_metadata = summary.get("run_metadata", {})
    return "\n".join(
        [
            "AI Dev Pipeline End-to-End Summary",
            "",
            f"Status: {summary['status']}",
            f"Run id: {run_metadata.get('run_id', 'unknown')}",
            f"Started at: {run_metadata.get('started_at', 'unknown')}",
            f"Rerun policy: {summary.get('run_strategy', {}).get('rerun_policy', 'new_ids')}",
            f"Validation: {goal_effect['validation_status']}",
            f"Alignment score: {goal_effect['alignment_score']}",
            f"Dispatch state: {current['dispatch_state']['status']}",
            f"Review state: {current['review_state']['status']}",
            f"Retry plan: {retry.get('status', 'not_required')}",
            "",
            "Execution:",
            *_format_execution_group("Completed", execution.get("completed", [])),
            *_format_execution_group("Skipped", execution.get("skipped", [])),
            *_format_execution_group("Failed", execution.get("failed", [])),
            *_format_execution_group("Next", execution.get("next", [])),
            "",
            "Evidence:",
            *_format_evidence(summary.get("evidence_map", [])),
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


def _format_execution_group(label: str, items: list[dict[str, Any]]) -> list[str]:
    if not items:
        return [f"- {label}: none"]
    lines = [f"- {label}:"]
    for item in items:
        task_id = item.get("task_id", "")
        title = item.get("title") or item.get("step", "")
        status = item.get("state_status") or item.get("status", "")
        lines.append(f"  - {task_id}: {title} ({status})")
    return lines


def _format_evidence(items: list[dict[str, Any]]) -> list[str]:
    if not items:
        return ["- none"]
    return [
        f"- {item.get('decision')}: {item.get('status')} -> {len(item.get('evidence', []))} evidence item(s)"
        for item in items
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the local end-to-end AI dev pipeline loop.")
    parser.add_argument("--repo-root", default=".", help="Repository root. Defaults to cwd.")
    parser.add_argument("--task-id", default=DEFAULT_TASK_ID, help="Parent task id for summary artifacts.")
    parser.add_argument("--json", action="store_true", help="Print full JSON summary.")
    parser.add_argument("--dry-run", action="store_true", help="Preview the run plan without writing artifacts.")
    parser.add_argument("--run-id", help="Optional stable id to record for this run.")
    parser.add_argument(
        "--rerun-policy",
        choices=sorted(RERUN_POLICIES),
        default="new_ids",
        help="How to handle existing task state.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    summary = run_end_to_end(
        args.repo_root,
        task_id=args.task_id,
        dry_run=args.dry_run,
        rerun_policy=args.rerun_policy,
        run_id=args.run_id,
    )
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(format_end_to_end_summary(summary))
    return 0 if not summary["goal_effect"]["blocking_issues"] and not summary["execution_summary"]["failed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
