#!/usr/bin/env python3
"""Run the local planning, dispatch, validation and feedback loop end to end."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agents import OptimizationPlannerAgent
from artifacts import read_json, read_yaml, write_json, write_text, write_yaml
from scripts.run_local_task import run_local_task
from tasks import TaskState, load_state, save_state


DEFAULT_TASK_ID = "workflow-001"
RERUN_POLICIES = {"new_ids", "skip_completed", "force"}
SUCCESS_STATUSES = {"waiting_for_human_merge_approval", "completed"}
REQUIRED_EVIDENCE_DECISIONS = {
    "goal_effect_aligned",
    "tests_passed",
    "dispatch_validated",
    "code_review_passed",
    "next_action",
}
DEFAULT_QUALITY_GATE_CONFIG = {
    "required_evidence": sorted(REQUIRED_EVIDENCE_DECISIONS),
    "missing_evidence": "blocking",
    "failed_evidence": "blocking",
    "human_approval_required": True,
}
SUPPORTED_DISPATCH_AGENTS = {
    "ArchitectAgent",
    "CoderAgent",
    "DesignReviewerAgent",
    "TestValidatorAgent",
    "CodeReviewerAgent",
    "GoalEffectValidatorAgent",
    "ProjectAnalysisAgent",
    "RequirementAnalysisAgent",
    "SystemDesignAgent",
}


def run_end_to_end(
    repo_root: str | Path = ".",
    *,
    task_id: str = DEFAULT_TASK_ID,
    dry_run: bool = False,
    rerun_policy: str = "new_ids",
    run_id: str | None = None,
    previous_run_record: str | None = None,
) -> dict[str, Any]:
    """Run a complete local feedback loop and persist a decision summary."""
    if rerun_policy not in RERUN_POLICIES:
        raise ValueError(f"Unknown rerun policy: {rerun_policy}")

    repo_root = Path(repo_root)
    paths = _workflow_paths(task_id)
    run_metadata = _run_metadata(run_id)
    previous_context = _previous_run_context(repo_root, previous_run_record)

    validation_task_id = f"{task_id}-validation"
    dispatch_task_id = f"{task_id}-dispatch"
    review_task_id = f"{task_id}-review"

    # dry-run 只返回可执行计划，不写任务产物；用于人工在正式运行前确认影响范围。
    if dry_run:
        return _dry_run_summary(
            repo_root,
            task_id=task_id,
            paths=paths,
            run_metadata=run_metadata,
            rerun_policy=rerun_policy,
            previous_context=previous_context,
            validation_task_id=validation_task_id,
            dispatch_task_id=dispatch_task_id,
            review_task_id=review_task_id,
        )

    events: list[dict[str, Any]] = []
    # 端到端闭环拆成 validation、dispatch、review 三个可复用子流程，便于失败后跳过已完成步骤。
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

    # 第一轮规划只看目标验证反馈，用来生成本次可调度任务队列。
    initial_plan = OptimizationPlannerAgent().run(
        {
            "repo_root": str(repo_root),
            "feedback_paths": [validation_feedback_path],
        }
    ).output
    _annotate_plan_with_previous_context(initial_plan, previous_context)
    write_yaml(repo_root, paths["initial_plan"], initial_plan)
    if previous_context["available"]:
        write_yaml(repo_root, paths["previous_run_context"], previous_context)

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
    # 最终规划汇总 validation、dispatch、review 的反馈，作为下一步人工决策依据。
    final_plan = OptimizationPlannerAgent().run(
        {
            "repo_root": str(repo_root),
            "feedback_paths": feedback_paths,
        }
    ).output
    _annotate_plan_with_previous_context(final_plan, previous_context)
    write_yaml(repo_root, paths["final_plan"], final_plan)

    recommended_task = _recommended_task(
        repo_root,
        task_id,
        [final_plan],
        previous_context=previous_context,
        events=events,
    )
    execution_summary = _execution_summary(events, recommended_task)
    recommendation_basis = dict(recommended_task.get("selection_basis", {}))
    next_recommended_action = {
        "task_id": recommended_task.get("id"),
        "title": recommended_task.get("title"),
        "priority": recommended_task.get("priority"),
        "reason": _recommendation_reason(recommended_task),
    }
    if recommended_task.get("source_task_id"):
        next_recommended_action["source_task_id"] = recommended_task["source_task_id"]
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
            "previous_run_context_artifact": (
                paths["previous_run_context"] if previous_context["available"] else None
            ),
            "initial_plan_artifact": paths["initial_plan"],
            "dispatch_tasks_artifact": paths["dispatch_tasks"],
            "final_plan_artifact": paths["final_plan"],
            "feedback_artifacts": feedback_paths,
        },
        "previous_run_context": previous_context,
        "execution_summary": execution_summary,
        "recommendation_basis": recommendation_basis,
        "retry_plan": _retry_plan(execution_summary),
        "remaining_work": _remaining_work(
            final_plan,
            completed_task_ids=recommendation_basis.get("completed_this_run_task_ids", []),
        ),
        "next_recommended_action": next_recommended_action,
    }
    summary["run_record_artifact"] = _run_record_path(task_id, run_metadata["run_id"])
    summary["target_effect_report"] = _build_target_effect_report(
        repo_root,
        summary,
        paths["target_effect_report"],
    )
    roadmap = _build_continuous_optimization_roadmap(
        repo_root,
        summary,
        final_plan,
        paths["continuous_optimization_roadmap"],
    )
    if roadmap:
        summary["continuous_optimization_roadmap"] = roadmap
        summary["next_recommended_action"] = {
            "task_id": None,
            "title": "等待人工选择路线图任务",
            "priority": "human_decision",
            "reason": "roadmap-001 已产出持续优化路线图，需由人工选择哪些任务进入下一阶段。",
        }
        summary["execution_summary"]["next"] = [
            {
                "task_id": None,
                "title": "等待人工选择路线图任务",
                "priority": "human_decision",
            }
        ]
    summary["evidence_map"] = _evidence_map(summary)
    summary["quality_gate"] = _quality_gate(summary, _quality_gate_config(repo_root))
    summary["post_approval_action"] = _post_approval_action(summary)
    # run record 是不可覆盖的单次运行记录；decision_summary.yaml 保留“最新摘要”入口。
    write_yaml(repo_root, summary["run_record_artifact"], summary)
    write_yaml(repo_root, paths["decision_summary"], summary)
    _save_parent_state(repo_root, task_id, paths, summary)
    return summary


def _workflow_paths(task_id: str) -> dict[str, str]:
    base = f"workspace/tasks/{task_id}"
    return {
        "previous_run_context": f"{base}/input/previous_run_context.yaml",
        "initial_plan": f"{base}/final/initial_next_optimization_tasks.yaml",
        "dispatch_tasks": f"{base}/input/dispatch_tasks.yaml",
        "review_tasks": f"{base}/input/review_tasks.yaml",
        "final_plan": f"{base}/final/final_next_optimization_tasks.yaml",
        "decision_summary": f"{base}/final/decision_summary.yaml",
        "target_effect_report": f"{base}/final/target_effect_report.md",
        "continuous_optimization_roadmap": f"{base}/final/continuous_optimization_roadmap.yaml",
    }


def _run_metadata(run_id: str | None) -> dict[str, str]:
    started_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return {
        "run_id": run_id or started_at.replace("-", "").replace(":", ""),
        "started_at": started_at,
    }


def _safe_run_id(run_id: str) -> str:
    return "".join(char if char.isalnum() or char in "._-" else "_" for char in run_id)


def _run_record_path(task_id: str, run_id: str) -> str:
    return f"workspace/tasks/{task_id}/runs/{_safe_run_id(run_id)}.yaml"


def _previous_run_context(repo_root: Path, previous_run_record: str | None) -> dict[str, Any]:
    if not previous_run_record:
        return {
            "available": False,
            "source_run_record": None,
            "source_task_id": None,
            "source_run_id": None,
            "quality_gate_status": None,
            "post_approval_action_status": None,
            "evidence_decisions": [],
            "evidence_summary": [],
            "remaining_work": [],
            "remaining_work_count": 0,
            "next_recommended_action": None,
        }

    record = read_yaml(repo_root, previous_run_record)
    evidence_map = list(record.get("evidence_map", []))
    remaining_work = list(record.get("remaining_work", []))
    completed_source_task_ids = _completed_source_task_ids(record)
    # 上一轮上下文只保留决策所需索引，完整证据仍通过 source_run_record 追溯。
    return {
        "available": True,
        "source_run_record": previous_run_record,
        "source_task_id": record.get("task_id"),
        "source_run_id": (record.get("run_metadata") or {}).get("run_id"),
        "quality_gate_status": (record.get("quality_gate") or {}).get("status"),
        "post_approval_action_status": (record.get("post_approval_action") or {}).get("status"),
        "evidence_decisions": [
            str(item.get("decision"))
            for item in evidence_map
            if item.get("decision")
        ],
        "evidence_summary": [
            {
                "decision": item.get("decision"),
                "status": item.get("status"),
                "evidence_count": len(item.get("evidence", [])),
                "notes": item.get("notes"),
            }
            for item in evidence_map
        ],
        "remaining_work": remaining_work,
        "remaining_work_count": len(remaining_work),
        "completed_source_task_ids": completed_source_task_ids,
        "next_recommended_action": record.get("next_recommended_action"),
    }


def _completed_source_task_ids(record: dict[str, Any]) -> list[str]:
    """从已审批运行记录中识别已完成的源任务，避免下一轮重复推荐。"""
    if (record.get("quality_gate") or {}).get("status") != "approved":
        return []
    if (record.get("post_approval_action") or {}).get("status") != "allowed":
        return []

    completed: list[str] = []
    next_action = record.get("next_recommended_action") or {}
    source_task_id = next_action.get("source_task_id")
    target_effect_report = record.get("target_effect_report") or {}
    if (
        source_task_id == "ui-validation-001"
        and target_effect_report.get("status") == "passed"
        and int(target_effect_report.get("blocking_issue_count", 0)) == 0
    ):
        completed.append(str(source_task_id))

    for task_id_value in record.get("completed_source_task_ids", []):
        task_id_text = str(task_id_value)
        if task_id_text not in completed:
            completed.append(task_id_text)
    recommendation_basis = record.get("recommendation_basis") or {}
    for task_id_value in recommendation_basis.get("completed_this_run_task_ids", []):
        task_id_text = str(task_id_value)
        if task_id_text not in completed:
            completed.append(task_id_text)
    return completed


def _annotate_plan_with_previous_context(
    plan: dict[str, Any],
    previous_context: dict[str, Any],
) -> None:
    if not previous_context.get("available"):
        return
    task_batch = dict(plan.get("task_batch", {}))
    task_batch["previous_run_record"] = previous_context["source_run_record"]
    task_batch["previous_evidence_decisions"] = list(previous_context["evidence_decisions"])
    task_batch["previous_remaining_work_count"] = previous_context["remaining_work_count"]
    plan["task_batch"] = task_batch


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
        # skip_completed 只复用已通过质量门且关键产物存在的子流程，避免误跳过半成品。
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
    # 即使前置验证失败，也落盘结构化反馈，保证后续 planner 和 retry_plan 有稳定输入。
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
        # new_ids 用于保留历史运行，skip_completed/force 则固定任务 ID，便于复用或覆盖。
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


def _remaining_work(
    plan: dict[str, Any],
    *,
    completed_task_ids: list[str] | None = None,
) -> list[str]:
    tasks = plan.get("tasks", [])
    completed = set(completed_task_ids or [])
    remaining_tasks = [
        task for task in tasks if str(task.get("id")) not in completed
    ]
    if not remaining_tasks:
        return ["暂无未完成的自动生成任务。"]
    return [f"{task.get('id')}: {task.get('title')}" for task in remaining_tasks[:5]]


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
    # evidence_map 把人工审批问题和具体产物路径绑定，避免只靠自然语言判断是否可继续。
    current = summary["current_result"]
    execution = summary["execution_summary"]
    retry = summary["retry_plan"]
    goal = summary["goal_effect"]
    validation_state = current["validation_state"]
    dispatch_state = current["dispatch_state"]
    review_state = current["review_state"]
    target_effect_report = summary.get("target_effect_report") or {}
    goal_effect_evidence = list(current.get("feedback_artifacts", []))
    if target_effect_report.get("artifact"):
        goal_effect_evidence.append(target_effect_report["artifact"])
    roadmap = summary.get("continuous_optimization_roadmap") or {}
    next_action_evidence = [current["final_plan_artifact"]]
    if roadmap.get("artifact"):
        next_action_evidence.append(roadmap["artifact"])
    return [
        _evidence_item(
            decision="goal_effect_aligned",
            status=str(goal.get("validation_status")),
            evidence=goal_effect_evidence,
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
            evidence=next_action_evidence,
            notes=f"{summary['next_recommended_action'].get('task_id')}: {summary['next_recommended_action'].get('title')}",
        ),
    ]


def _build_target_effect_report(
    repo_root: str | Path,
    summary: dict[str, Any],
    report_artifact: str,
) -> dict[str, Any]:
    """把目标效果 evidence 汇总成面向人工审批的 Markdown 报告。"""
    repo_root = Path(repo_root)
    feedback_artifacts = list(summary.get("current_result", {}).get("feedback_artifacts", []))
    render_checks = _collect_render_checks(repo_root, feedback_artifacts)
    blocking_issues = list(summary.get("goal_effect", {}).get("blocking_issues", []))
    blocking_issues.extend(_collect_feedback_blocking_issues(repo_root, feedback_artifacts))
    failed_checks = [check for check in render_checks if check.get("result") != "pass"]
    screenshot_artifacts = [
        str(check.get("screenshot_artifact"))
        for check in render_checks
        if check.get("screenshot_artifact")
    ]
    status = "passed" if not failed_checks and not blocking_issues else "blocked"
    report = {
        "artifact": report_artifact,
        "status": status,
        "feedback_artifacts": feedback_artifacts,
        "render_check_count": len(render_checks),
        "passed_render_check_count": len(render_checks) - len(failed_checks),
        "failed_render_check_count": len(failed_checks),
        "screenshot_artifacts": screenshot_artifacts,
        "blocking_issue_count": len(blocking_issues),
    }
    write_text(
        repo_root,
        report_artifact,
        _format_target_effect_report(summary, report, render_checks, blocking_issues),
    )
    return report


def _collect_render_checks(repo_root: Path, feedback_artifacts: list[str]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for feedback_artifact in feedback_artifacts:
        feedback_path = repo_root / feedback_artifact
        if not feedback_path.exists():
            continue
        feedback = read_json(repo_root, feedback_artifact)
        for check in feedback.get("demo_render_checks", []):
            item = dict(check)
            item["feedback_artifact"] = feedback_artifact
            checks.append(item)
    return checks


def _collect_feedback_blocking_issues(
    repo_root: Path,
    feedback_artifacts: list[str],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    seen: set[str] = set()
    for feedback_artifact in feedback_artifacts:
        feedback_path = repo_root / feedback_artifact
        if not feedback_path.exists():
            continue
        feedback = read_json(repo_root, feedback_artifact)
        for issue in feedback.get("blocking_issues", []):
            issue_id = str(issue.get("id") or issue)
            key = f"{feedback_artifact}:{issue_id}"
            if key in seen:
                continue
            seen.add(key)
            item = dict(issue)
            item["feedback_artifact"] = feedback_artifact
            issues.append(item)
    return issues


def _format_target_effect_report(
    summary: dict[str, Any],
    report: dict[str, Any],
    render_checks: list[dict[str, Any]],
    blocking_issues: list[dict[str, Any]],
) -> str:
    goal = summary.get("goal_effect", {})
    next_action = summary.get("next_recommended_action") or {}
    lines = [
        "# 目标效果验证报告",
        "",
        f"- 任务：{summary.get('task_id')}",
        f"- 状态：{report['status']}",
        f"- 目标验证：{goal.get('validation_status')}",
        f"- 对齐分数：{goal.get('alignment_score')}",
        f"- 渲染检查：{report['passed_render_check_count']}/{report['render_check_count']} 通过",
        f"- 阻塞项：{report['blocking_issue_count']}",
        "",
        "## 证据来源",
    ]
    if report["feedback_artifacts"]:
        lines.extend(f"- {artifact}" for artifact in report["feedback_artifacts"])
    else:
        lines.append("- 暂无 validation_feedback 产物。")

    lines.extend(["", "## 渲染证据"])
    if not render_checks:
        lines.append("- 暂无 demo_render_checks；当前报告仅保留目标验证汇总和反馈来源。")
    for check in render_checks:
        evidence = check.get("evidence") or {}
        screenshot = evidence.get("screenshot") or {}
        page = evidence.get("page_structure") or {}
        conclusion = check.get("acceptance_conclusion") or {}
        lines.extend(
            [
                f"- 检查：{check.get('id')}（{check.get('result')}）",
                f"  - 来源：{check.get('feedback_artifact')}",
                f"  - 期望效果：{check.get('expected_effect', '')}",
                f"  - 截图：{screenshot.get('artifact') or check.get('screenshot_artifact')}，大小 {screenshot.get('bytes', check.get('screenshot_bytes', 0))} / {screenshot.get('min_bytes', check.get('min_screenshot_bytes', 0))} bytes",
                f"  - 页面结构：title={page.get('title', '')}，html={page.get('has_html')}，body={page.get('has_body')}",
                f"  - 结论：{conclusion.get('summary', '')}",
            ]
        )
        lines.extend(_format_presence_items("DOM 文本", evidence.get("dom_terms", []), "term"))
        lines.extend(_format_presence_items("DOM 选择器", evidence.get("dom_selectors", []), "selector"))

    lines.extend(["", "## 阻塞项"])
    if blocking_issues:
        for issue in blocking_issues:
            lines.append(
                f"- {issue.get('id', 'unknown')}：{issue.get('description', '')} "
                f"建议：{issue.get('recommendation', '')}"
            )
    else:
        lines.append("- 无。")

    lines.extend(
        [
            "",
            "## 下一步建议",
            f"- {next_action.get('task_id')}: {next_action.get('title')}",
        ]
    )
    return "\n".join(lines) + "\n"


def _format_presence_items(label: str, items: list[dict[str, Any]], key: str) -> list[str]:
    if not items:
        return [f"  - {label}：无结构化证据。"]
    passed = [str(item.get(key)) for item in items if item.get("present") is True]
    missing = [str(item.get(key)) for item in items if item.get("present") is not True]
    lines = [f"  - {label}命中：{', '.join(passed) if passed else '无'}"]
    if missing:
        lines.append(f"  - {label}缺失：{', '.join(missing)}")
    return lines


def _build_continuous_optimization_roadmap(
    repo_root: str | Path,
    summary: dict[str, Any],
    final_plan: dict[str, Any],
    roadmap_artifact: str,
) -> dict[str, Any] | None:
    """为 roadmap-001 生成路线图，生成后等待人工选择后续任务。"""
    previous_next_action = summary.get("previous_run_context", {}).get("next_recommended_action") or {}
    if previous_next_action.get("source_task_id") != "roadmap-001":
        return None
    if previous_next_action.get("task_id") != summary.get("task_id"):
        return None

    repo_root = Path(repo_root)
    completed = set(summary.get("recommendation_basis", {}).get("completed_this_run_task_ids", []))
    candidate_tasks = [
        _roadmap_candidate(task)
        for task in final_plan.get("tasks", [])
        if task.get("id") not in completed and task.get("id") != "roadmap-001"
    ]
    roadmap = {
        "task_id": summary.get("task_id"),
        "source_task_id": "roadmap-001",
        "status": "waiting_for_human_selection",
        "goal": "让人工基于价值、风险和验收方式选择下一组高价值任务。",
        "context": {
            "previous_run_record": summary.get("previous_run_context", {}).get("source_run_record"),
            "target_effect_report": summary.get("target_effect_report", {}).get("artifact"),
            "completed_source_task_ids": list(completed),
        },
        "candidate_tasks": candidate_tasks,
        "recommended_order": [task["id"] for task in candidate_tasks],
        "decision_gate": {
            "required": True,
            "decision_owner": "human",
            "allowed_decisions": ["select_tasks", "defer", "stop"],
            "notes": "路线图只提供候选方向，不自动进入下一阶段。",
        },
    }
    write_yaml(repo_root, roadmap_artifact, roadmap)
    return {
        "artifact": roadmap_artifact,
        "status": roadmap["status"],
        "candidate_count": len(candidate_tasks),
        "candidate_task_ids": [task["id"] for task in candidate_tasks],
        "requires_human_selection": True,
    }


def _roadmap_candidate(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": task.get("id"),
        "title": task.get("title"),
        "priority": task.get("priority"),
        "recommended_agent": task.get("recommended_agent"),
        "risk_level": task.get("risk_level"),
        "value": _candidate_value(task),
        "risk": _candidate_risk(task),
        "acceptance_criteria": list(task.get("acceptance_criteria", [])),
        "recommended_next_step": f"人工确认后执行 {task.get('id')}。",
    }


def _candidate_value(task: dict[str, Any]) -> str:
    scope = list(task.get("scope", []))
    return scope[0] if scope else "补齐持续优化能力。"


def _candidate_risk(task: dict[str, Any]) -> str:
    risk_level = task.get("risk_level", "medium")
    if risk_level == "low":
        return "低风险，主要影响结构化产物和人工决策表达。"
    return "中等风险，执行前需确认影响范围和验收标准。"


def _quality_gate_config(repo_root: str | Path = ".") -> dict[str, Any]:
    """读取质量门配置；未配置时使用保守默认值。"""
    config = dict(DEFAULT_QUALITY_GATE_CONFIG)
    try:
        pipeline_config = read_yaml(repo_root, "config/pipeline.yaml")
    except Exception:
        return config
    custom_config = pipeline_config.get("quality_gate", {}) or {}
    if custom_config.get("required_evidence"):
        config["required_evidence"] = list(custom_config["required_evidence"])
    if custom_config.get("missing_evidence"):
        config["missing_evidence"] = str(custom_config["missing_evidence"])
    if custom_config.get("failed_evidence"):
        config["failed_evidence"] = str(custom_config["failed_evidence"])
    if "human_approval_required" in custom_config:
        config["human_approval_required"] = bool(custom_config["human_approval_required"])
    return config


def _quality_gate(summary: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    """根据运行状态和 evidence_map 生成进入人工审批前的质量门结论。"""
    config = config or DEFAULT_QUALITY_GATE_CONFIG
    blocking_issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    evidence_by_decision = {
        item.get("decision"): item
        for item in summary.get("evidence_map", [])
    }

    def add_issue(kind: str, issue: dict[str, Any]) -> None:
        if kind == "warning":
            warnings.append(issue)
        else:
            blocking_issues.append(issue)

    # 必需 evidence 和缺失策略来自配置；默认保持 blocking，保障质量门保守可靠。
    for decision in sorted(config.get("required_evidence", [])):
        item = evidence_by_decision.get(decision)
        if not item or not item.get("evidence"):
            add_issue(
                str(config.get("missing_evidence", "blocking")),
                {
                    "id": f"missing_evidence_{decision}",
                    "severity": "medium" if config.get("missing_evidence") == "warning" else "high",
                    "description": f"质量门缺少必要 evidence：{decision}。",
                    "recommendation": "补齐对应验证产物后重新运行端到端闭环。",
                },
            )
            continue
        if item.get("status") in {"failed", "blocked", "not_passed"}:
            add_issue(
                str(config.get("failed_evidence", "blocking")),
                {
                    "id": f"failed_evidence_{decision}",
                    "severity": "medium" if config.get("failed_evidence") == "warning" else "high",
                    "description": f"质量门 evidence 未通过：{decision}。",
                    "recommendation": "修复失败验证或评审结论后重新运行端到端闭环。",
                },
            )

    if summary.get("execution_summary", {}).get("failed"):
        blocking_issues.append(
            {
                "id": "failed_execution_steps",
                "severity": "high",
                "description": "端到端运行存在失败步骤。",
                "recommendation": "先按 retry_plan 修复失败步骤。",
            }
        )
    if summary.get("retry_plan", {}).get("status") == "retry_required":
        blocking_issues.append(
            {
                "id": "retry_required",
                "severity": "high",
                "description": "当前运行需要重试，不能进入合并审批。",
                "recommendation": "执行 retry_plan 中的 recommended_command。",
            }
        )

    status = "blocked" if blocking_issues else "waiting_for_human_approval"
    return {
        "status": status,
        "can_continue": False,
        "blocking_issues": blocking_issues,
        "warnings": warnings,
        "config": config,
        "human_approval": {
            "required": bool(config.get("human_approval_required", True)),
            "merge_approved": False,
            "status": "pending" if not blocking_issues else "blocked",
        },
        "next_allowed_action": (
            "人工审批通过后继续。"
            if not blocking_issues
            else "先修复质量门阻塞问题，再重新运行端到端闭环。"
        ),
    }


def _post_approval_action(summary: dict[str, Any]) -> dict[str, Any]:
    """把审批状态转换成机器可读的后续动作控制结论。"""
    quality_gate = summary.get("quality_gate") or {}
    gate_status = quality_gate.get("status")
    approval_record = summary.get("approval_record") or {}
    approval_comment = str(approval_record.get("comment") or "").strip()

    if gate_status == "approved" and quality_gate.get("can_continue") is True:
        return {
            "status": "allowed",
            "can_continue": True,
            "allowed_actions": ["continue_next_stage", "view_run_record"],
            "blocked_actions": [],
            "recommended_action": "继续执行下一阶段任务。",
            "reason": "人工审批已通过。",
        }

    if gate_status == "rejected":
        reason = "人工审批未通过，需修正后重新运行。"
        if approval_comment:
            reason = f"{reason} 审批意见：{approval_comment}"
        return {
            "status": "blocked",
            "can_continue": False,
            "allowed_actions": ["view_run_record", "rerun_after_fix"],
            "blocked_actions": ["continue_next_stage"],
            "recommended_action": "根据审批意见修正后重新运行端到端闭环。",
            "reason": reason,
        }

    if gate_status == "blocked":
        return {
            "status": "blocked",
            "can_continue": False,
            "allowed_actions": ["view_run_record", "rerun_after_fix"],
            "blocked_actions": ["approve_run", "continue_next_stage"],
            "recommended_action": "先修复质量门阻塞问题，再重新运行端到端闭环。",
            "reason": "当前运行存在质量门阻塞问题。",
        }

    if gate_status == "dry_run":
        return {
            "status": "not_applicable",
            "can_continue": False,
            "allowed_actions": ["run_end_to_end"],
            "blocked_actions": ["approve_run", "continue_next_stage"],
            "recommended_action": "正式运行端到端闭环后再进入人工审批。",
            "reason": "dry-run 只预览计划，不产生可审批运行记录。",
        }

    return {
        "status": "approval_required",
        "can_continue": False,
        "allowed_actions": ["view_run_record", "approve_run"],
        "blocked_actions": ["continue_next_stage"],
        "recommended_action": "补充人工审批记录后再决定是否继续。",
        "reason": "当前运行尚未获得人工审批。",
    }


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
    previous_context: dict[str, Any],
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
            "artifacts": [
                paths["final_plan"],
                paths["decision_summary"],
                paths["target_effect_report"],
                paths["continuous_optimization_roadmap"],
            ],
            "errors": [],
        },
    ]
    execution_summary = {
        "completed": [],
        "skipped": [event for event in events if event["status"] == "skipped"],
        "failed": [],
        "next": [event for event in events if event["status"] == "next"],
    }
    summary = {
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
            "previous_run_context_artifact": (
                paths["previous_run_context"] if previous_context["available"] else None
            ),
            "initial_plan_artifact": paths["initial_plan"],
            "dispatch_tasks_artifact": paths["dispatch_tasks"],
            "final_plan_artifact": paths["final_plan"],
            "feedback_artifacts": [],
        },
        "previous_run_context": previous_context,
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
                    paths["target_effect_report"],
                    paths["continuous_optimization_roadmap"],
                ],
                notes="dry-run 仅预览计划，不写入产物。",
            )
        ],
        "quality_gate": {
            "status": "dry_run",
            "can_continue": False,
            "blocking_issues": [],
            "human_approval": {
                "required": True,
                "merge_approved": False,
                "status": "not_requested",
            },
            "next_allowed_action": "正式运行端到端闭环后再进入人工审批。",
        },
    }
    summary["post_approval_action"] = _post_approval_action(summary)
    return summary


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
        "workflow-005": "端到端闭环运行记录质量门",
        "workflow-006": "端到端闭环质量门配置化",
        "workflow-007": "端到端闭环人工审批记录",
        "workflow-008": "端到端闭环审批后动作控制",
        "workflow-009": "端到端闭环任务推进命令",
    }
    return {
        "id": next_task_id,
        "title": title_by_task_id.get(next_task_id, "端到端闭环持续优化"),
        "priority": "medium",
    }


def _recommended_task(
    repo_root: Path,
    task_id: str,
    task_batches: list[dict[str, Any]],
    *,
    previous_context: dict[str, Any] | None = None,
    events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    tasks = []
    for task_batch in task_batches:
        tasks.extend(task_batch.get("tasks", []))
    if previous_context and previous_context.get("available"):
        return _recommended_from_previous_context(repo_root, task_id, tasks, previous_context, events or [])

    tasks = [
        task
        for task in tasks
        if not (repo_root / "workspace/tasks" / task["id"] / "state.json").exists()
    ]
    if not tasks:
        return _fallback_recommended_task(task_id)
    priority_order = {"high": 0, "medium": 1, "low": 2}
    return sorted(tasks, key=lambda task: priority_order.get(task.get("priority", "low"), 9))[0]


def _recommended_from_previous_context(
    repo_root: Path,
    task_id: str,
    tasks: list[dict[str, Any]],
    previous_context: dict[str, Any],
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    remaining_task_ids = _previous_remaining_task_ids(previous_context)
    completed_previous_source_task_ids = list(previous_context.get("completed_source_task_ids", []))
    completed_task_ids = _merge_unique(
        completed_previous_source_task_ids,
        _completed_template_task_ids(task_id, events, remaining_task_ids),
    )
    priority_order = {"high": 0, "medium": 1, "low": 2}
    remaining_order = {remaining_task_id: index for index, remaining_task_id in enumerate(remaining_task_ids)}
    task_order = {str(task.get("id")): index for index, task in enumerate(tasks)}
    selectable_tasks = [
        task
        for task in tasks
        if str(task.get("id")) not in completed_task_ids
    ]

    def recommendation_key(task: dict[str, Any]) -> tuple[int, int, int, str]:
        task_id_value = str(task.get("id"))
        if task_id_value in remaining_order and task_id_value not in completed_task_ids:
            group = 0
        elif task_id_value not in remaining_order:
            group = 1
        else:
            # 本轮已经调度验证过的上一轮剩余任务降级，避免下一步重复投入。
            group = 2
        return (
            group,
            remaining_order.get(task_id_value, 999),
            priority_order.get(task.get("priority", "low"), 9),
            task_order.get(task_id_value, 999),
        )

    available_tasks = sorted(selectable_tasks, key=recommendation_key)
    if not available_tasks:
        fallback = _fallback_recommended_task(task_id)
        fallback["selection_basis"] = {
            "strategy": "previous_run_context",
            "previous_remaining_task_ids": remaining_task_ids,
            "completed_this_run_task_ids": completed_task_ids,
            "completed_previous_source_task_ids": completed_previous_source_task_ids,
            "deprioritized_task_ids": completed_task_ids,
            "remaining_open_task_ids": [],
            "selected_source_task_id": None,
            "selected_task_id": fallback["id"],
        }
        return fallback

    selected_source = dict(available_tasks[0])
    next_workflow_task = _fallback_recommended_task(task_id)
    selected = {
        "id": next_workflow_task["id"],
        "title": selected_source.get("title", next_workflow_task["title"]),
        "priority": selected_source.get("priority", next_workflow_task["priority"]),
        "source_task_id": selected_source.get("id"),
    }
    deprioritized = [
        task_id_value for task_id_value in remaining_task_ids if task_id_value in completed_task_ids
    ]
    selected["selection_basis"] = {
        "strategy": "previous_run_context",
        "previous_remaining_task_ids": remaining_task_ids,
        "completed_this_run_task_ids": completed_task_ids,
        "completed_previous_source_task_ids": completed_previous_source_task_ids,
        "deprioritized_task_ids": deprioritized,
        "remaining_open_task_ids": [
            task_id_value for task_id_value in remaining_task_ids if task_id_value not in completed_task_ids
        ],
        "candidate_task_ids": [str(task.get("id")) for task in available_tasks],
        "selected_source_task_id": selected["source_task_id"],
        "selected_task_id": selected["id"],
        "source_task_state_exists": (
            repo_root / "workspace/tasks" / str(selected["source_task_id"]) / "state.json"
        ).exists(),
    }
    return selected


def _merge_unique(*groups: list[str]) -> list[str]:
    merged: list[str] = []
    for group in groups:
        for item in group:
            if item not in merged:
                merged.append(item)
    return merged


def _previous_remaining_task_ids(previous_context: dict[str, Any]) -> list[str]:
    task_ids = []
    for item in previous_context.get("remaining_work", []):
        task_id_value = str(item).split(":", 1)[0].strip()
        if task_id_value.startswith("暂无"):
            continue
        if task_id_value and task_id_value not in task_ids:
            task_ids.append(task_id_value)
    return task_ids


def _completed_template_task_ids(
    parent_task_id: str,
    events: list[dict[str, Any]],
    candidate_task_ids: list[str],
) -> list[str]:
    completed = []
    prefix = f"{parent_task_id}-"
    for event in events:
        for artifact in event.get("artifacts", []):
            parts = Path(str(artifact)).parts
            if len(parts) < 3 or parts[0] != "workspace" or parts[1] != "tasks":
                continue
            task_dir = parts[2]
            if not task_dir.startswith(prefix):
                continue
            template_task_id = _template_task_id(task_dir[len(prefix) :], candidate_task_ids)
            if template_task_id in candidate_task_ids and template_task_id not in completed:
                completed.append(template_task_id)
    return completed


def _template_task_id(task_dir_suffix: str, candidate_task_ids: list[str]) -> str:
    if task_dir_suffix in candidate_task_ids:
        return task_dir_suffix
    for candidate_task_id in candidate_task_ids:
        if re.fullmatch(rf"{re.escape(candidate_task_id)}-\d+", task_dir_suffix):
            return candidate_task_id
    return task_dir_suffix


def _recommendation_reason(recommended_task: dict[str, Any]) -> str:
    basis = recommended_task.get("selection_basis") or {}
    if basis.get("strategy") != "previous_run_context":
        return "来自端到端反馈闭环生成的下一轮优化任务。"

    source_task_id = basis.get("selected_source_task_id")
    deprioritized = basis.get("deprioritized_task_ids", [])
    if not source_task_id:
        completed = basis.get("completed_this_run_task_ids", [])
        if completed:
            return f"上一轮剩余任务已完成或已验证：{', '.join(completed)}。转入下一轮持续优化。"
        return "previous_run_context 未发现可继续推荐的开放任务，转入下一轮持续优化。"
    reason = f"基于 previous_run_context.remaining_work 和 evidence_summary 选择 {source_task_id}。"
    if deprioritized:
        reason += f" 本轮已验证 {', '.join(deprioritized)}，因此降低其重复推荐优先级。"
    return reason


def _save_parent_state(
    repo_root: Path,
    task_id: str,
    paths: dict[str, str],
    summary: dict[str, Any],
) -> None:
    failed_steps = summary.get("execution_summary", {}).get("failed", [])
    status = "blocked_by_end_to_end_step" if failed_steps else "waiting_for_human_merge_approval"
    artifacts = [
        "scripts/run_end_to_end.py",
        "scripts/run_local_task.py",
        "config/pipeline.yaml",
        "tests/test_run_end_to_end.py",
        paths["initial_plan"],
        paths["dispatch_tasks"],
        paths["review_tasks"],
        paths["final_plan"],
        paths["decision_summary"],
        paths["target_effect_report"],
    ]
    previous_context_artifact = summary.get("current_result", {}).get("previous_run_context_artifact")
    if previous_context_artifact:
        artifacts.insert(4, previous_context_artifact)
    if summary.get("run_record_artifact"):
        artifacts.append(summary["run_record_artifact"])
    roadmap = summary.get("continuous_optimization_roadmap") or {}
    if roadmap.get("artifact"):
        artifacts.append(roadmap["artifact"])
    state = TaskState(
        task_id=task_id,
        step="retry_plan" if failed_steps else "human_merge_gate",
        status=status,
        artifacts=artifacts,
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
    quality_gate = summary.get("quality_gate", {})
    previous_context = summary.get("previous_run_context") or {}
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
            f"Quality gate: {quality_gate.get('status', 'unknown')}",
            f"Quality blocking issues: {len(quality_gate.get('blocking_issues', []))}",
            f"Quality warnings: {len(quality_gate.get('warnings', []))}",
            f"Previous run record: {previous_context.get('source_run_record') or 'none'}",
            f"Post approval action: {summary.get('post_approval_action', {}).get('status', 'unknown')}",
            f"Can continue: {summary.get('post_approval_action', {}).get('can_continue', False)}",
            f"Allowed next action: {summary.get('post_approval_action', {}).get('recommended_action', 'unknown')}",
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
            f"- Target effect report: {(summary.get('target_effect_report') or {}).get('artifact', 'none')}",
            f"- Continuous optimization roadmap: {(summary.get('continuous_optimization_roadmap') or {}).get('artifact', 'none')}",
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


def list_run_records(repo_root: str | Path = ".", *, task_id: str = DEFAULT_TASK_ID) -> list[dict[str, Any]]:
    """列出指定任务的端到端运行记录，供人工追溯和决策复盘使用。"""
    repo_root = Path(repo_root)
    runs_dir = repo_root / "workspace/tasks" / task_id / "runs"
    if not runs_dir.exists():
        return []

    records = []
    for path in sorted(runs_dir.glob("*.yaml")):
        relative_path = path.relative_to(repo_root).as_posix()
        data = read_yaml(repo_root, relative_path)
        metadata = data.get("run_metadata", {})
        # 列表只返回决策索引信息，完整 evidence 仍保留在单个 run record 中。
        records.append(
            {
                "run_id": metadata.get("run_id", path.stem),
                "started_at": metadata.get("started_at"),
                "status": data.get("status"),
                "quality_gate_status": (data.get("quality_gate") or {}).get("status"),
                "post_approval_action_status": (data.get("post_approval_action") or {}).get("status"),
                "artifact": relative_path,
                "next_recommended_action": data.get("next_recommended_action"),
            }
        )
    return sorted(records, key=lambda item: item.get("started_at") or "", reverse=True)


def continue_run_record(
    repo_root: str | Path = ".",
    *,
    task_id: str = DEFAULT_TASK_ID,
    run_id: str,
) -> dict[str, Any]:
    """读取审批后动作控制结果，判断指定运行记录是否允许推进下一阶段。"""
    repo_root = Path(repo_root)
    record_path = _run_record_path(task_id, run_id)
    record = read_yaml(repo_root, record_path)
    action = record.get("post_approval_action") or _post_approval_action(record)
    can_continue = action.get("status") == "allowed" and action.get("can_continue") is True
    next_action = record.get("next_recommended_action") or {}
    next_task_id = next_action.get("task_id")

    result = {
        "task_id": task_id,
        "run_id": run_id,
        "status": "allowed" if can_continue else "blocked",
        "can_continue": can_continue,
        "post_approval_action_status": action.get("status"),
        "allowed_actions": list(action.get("allowed_actions", [])),
        "blocked_actions": list(action.get("blocked_actions", [])),
        "reason": action.get("reason"),
        "recommended_action": action.get("recommended_action"),
        "next_recommended_action": next_action,
        "run_record_artifact": record_path,
        "recommended_command": None,
    }
    if can_continue and next_task_id:
        result["recommended_command"] = (
            f"python scripts/run_end_to_end.py --task-id {next_task_id} --rerun-policy skip_completed"
        )
    return result


def approve_run_record(
    repo_root: str | Path = ".",
    *,
    task_id: str = DEFAULT_TASK_ID,
    run_id: str,
    approver: str,
    decision: str,
    comment: str,
    decided_at: str | None = None,
) -> dict[str, Any]:
    """写入人工审批记录，并同步更新 run record 与最新决策摘要。"""
    if decision not in {"approved", "rejected"}:
        raise ValueError("decision must be approved or rejected.")
    repo_root = Path(repo_root)
    record_path = _run_record_path(task_id, run_id)
    record = read_yaml(repo_root, record_path)
    decided_at = decided_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    approval_record = {
        "approver": approver,
        "decision": decision,
        "comment": comment,
        "decided_at": decided_at,
    }
    record["approval_record"] = approval_record
    quality_gate = dict(record.get("quality_gate", {}))
    human_approval = dict(quality_gate.get("human_approval", {}))
    human_approval.update(
        {
            "required": True,
            "merge_approved": decision == "approved",
            "status": decision,
        }
    )
    quality_gate["human_approval"] = human_approval
    quality_gate["status"] = decision
    quality_gate["can_continue"] = decision == "approved"
    quality_gate["next_allowed_action"] = (
        "人工审批已通过，可以继续后续动作。"
        if decision == "approved"
        else "人工审批未通过，需根据审批意见修正后重新运行。"
    )
    record["quality_gate"] = quality_gate
    record["post_approval_action"] = _post_approval_action(record)
    write_yaml(repo_root, record_path, record)

    latest_summary_path = _workflow_paths(task_id)["decision_summary"]
    latest_summary_file = repo_root / latest_summary_path
    if latest_summary_file.exists():
        latest_summary = read_yaml(repo_root, latest_summary_path)
        if latest_summary.get("run_record_artifact") == record_path:
            latest_summary["approval_record"] = approval_record
            latest_summary["quality_gate"] = quality_gate
            latest_summary["post_approval_action"] = record["post_approval_action"]
            write_yaml(repo_root, latest_summary_path, latest_summary)
    _sync_approval_state(repo_root, task_id, decision)
    return record


def _sync_approval_state(repo_root: Path, task_id: str, decision: str) -> None:
    """审批结果同步到父任务状态，后续编排可直接判断是否能推进。"""
    try:
        state = load_state(repo_root, task_id)
    except Exception:
        return
    state.step = "post_approval_action"
    state.gates["human_merge_approved"] = decision == "approved"
    if decision == "approved":
        state.status = "completed"
    else:
        state.record_error(
            "人工审批未通过，需按审批意见修正后重新运行。",
            status="blocked_by_human_approval",
        )
    save_state(repo_root, state)


def format_run_records(records: list[dict[str, Any]]) -> str:
    if not records:
        return "No run records found."
    lines = ["AI Dev Pipeline Run Records", ""]
    for record in records:
        next_action = record.get("next_recommended_action") or {}
        lines.append(
            f"- {record['run_id']} ({record.get('status')}): {record['artifact']}"
        )
        if next_action:
            lines.append(
                f"  next: {next_action.get('task_id')}: {next_action.get('title')}"
            )
    return "\n".join(lines)


def format_continue_result(result: dict[str, Any]) -> str:
    next_action = result.get("next_recommended_action") or {}
    lines = [
        "AI Dev Pipeline Continue Check",
        "",
        f"Status: {result.get('status')}",
        f"Run id: {result.get('run_id')}",
        f"Can continue: {result.get('can_continue')}",
        f"Post approval action: {result.get('post_approval_action_status')}",
        f"Reason: {result.get('reason')}",
        f"Recommended action: {result.get('recommended_action')}",
    ]
    if next_action:
        lines.append(
            f"Next task: {next_action.get('task_id')}: {next_action.get('title')} ({next_action.get('priority')})"
        )
    if result.get("recommended_command"):
        lines.append(f"Command: {result['recommended_command']}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the local end-to-end AI dev pipeline loop.")
    parser.add_argument("--repo-root", default=".", help="Repository root. Defaults to cwd.")
    parser.add_argument("--task-id", default=DEFAULT_TASK_ID, help="Parent task id for summary artifacts.")
    parser.add_argument("--json", action="store_true", help="Print full JSON summary.")
    parser.add_argument("--dry-run", action="store_true", help="Preview the run plan without writing artifacts.")
    parser.add_argument("--list-runs", action="store_true", help="List persisted run records for the task.")
    parser.add_argument("--approve-run", help="Run id to approve or reject.")
    parser.add_argument("--continue-run", help="Run id to check before continuing to the next task.")
    parser.add_argument("--approver", help="Human approver name for --approve-run.")
    parser.add_argument("--decision", choices=["approved", "rejected"], help="Approval decision for --approve-run.")
    parser.add_argument("--comment", default="", help="Approval comment for --approve-run.")
    parser.add_argument("--decided-at", help="Approval timestamp for --approve-run.")
    parser.add_argument("--run-id", help="Optional stable id to record for this run.")
    parser.add_argument(
        "--previous-run-record",
        help="Previous run record artifact to use as decision input for this run.",
    )
    parser.add_argument(
        "--rerun-policy",
        choices=sorted(RERUN_POLICIES),
        default="new_ids",
        help="How to handle existing task state.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.approve_run:
        if not args.approver or not args.decision:
            raise SystemExit("--approve-run requires --approver and --decision.")
        updated = approve_run_record(
            args.repo_root,
            task_id=args.task_id,
            run_id=args.approve_run,
            approver=args.approver,
            decision=args.decision,
            comment=args.comment,
            decided_at=args.decided_at,
        )
        if args.json:
            print(json.dumps(updated, ensure_ascii=False, indent=2))
        else:
            print(format_end_to_end_summary(updated))
        return 0

    if args.list_runs:
        records = list_run_records(args.repo_root, task_id=args.task_id)
        if args.json:
            print(json.dumps(records, ensure_ascii=False, indent=2))
        else:
            print(format_run_records(records))
        return 0

    if args.continue_run:
        result = continue_run_record(
            args.repo_root,
            task_id=args.task_id,
            run_id=args.continue_run,
        )
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(format_continue_result(result))
        return 0 if result.get("can_continue") else 1

    summary = run_end_to_end(
        args.repo_root,
        task_id=args.task_id,
        dry_run=args.dry_run,
        rerun_policy=args.rerun_policy,
        run_id=args.run_id,
        previous_run_record=args.previous_run_record,
    )
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(format_end_to_end_summary(summary))
    quality_blocked = summary.get("quality_gate", {}).get("status") == "blocked"
    return 0 if not summary["goal_effect"]["blocking_issues"] and not summary["execution_summary"]["failed"] and not quality_blocked else 1


if __name__ == "__main__":
    raise SystemExit(main())
