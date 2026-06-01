#!/usr/bin/env python3
"""Run a configured local workflow with placeholder agents."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from agents import (
    BaseAgent,
    CodeReviewerAgent,
    CoderAgent,
    DesignReviewerAgent,
    GoalEffectValidatorAgent,
    OptimizationDispatcherAgent,
    OptimizationExecutorAgent,
    OptimizationPlannerAgent,
    TestValidatorAgent,
)
from artifacts import read_json, read_yaml, write_json, write_yaml
from tasks import TaskState, load_state, save_state


class PlaceholderAgent(BaseAgent):
    """Local stand-in for future specialized agents."""

    def handle(self, payload: dict[str, Any]) -> Mapping[str, Any]:
        step = payload["step"]
        if step == "fail":
            raise RuntimeError("Placeholder step failed.")
        return {
            "task_id": payload["task_id"],
            "workflow": payload["workflow"],
            "step": step,
            "message": "placeholder agent completed step",
        }


def load_workflow_config(repo_root: str | Path, workflow_name: str) -> dict[str, Any]:
    config = read_yaml(repo_root, "config/pipeline.yaml")
    workflows = config.get("workflows", {})
    if workflow_name not in workflows:
        raise ValueError(f"Unknown workflow: {workflow_name}")
    return {
        "agent_config": config.get("agent_config", {}),
        "workflow": workflows[workflow_name],
    }


def _step_artifact_path(task_id: str, step: str) -> str:
    return f"workspace/tasks/{task_id}/orchestration/{step}.json"


def _step_name(step: str | dict[str, Any]) -> str:
    if isinstance(step, str):
        return step
    return str(step["name"])


def _step_options(step: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(step, str):
        return {}
    return {key: value for key, value in step.items() if key != "name"}


def _parent_task_id(task_id: str, suffix: str) -> str:
    # 端到端子任务使用固定后缀；从子任务反推父任务后可复用同一套 workflow 配置。
    if task_id.endswith(suffix):
        return task_id[: -len(suffix)]
    return task_id


def _run_step(
    repo_root: str | Path,
    workflow_name: str,
    task_id: str,
    step: str,
    step_options: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    step_options = step_options or {}
    if step == "design_review":
        result = DesignReviewerAgent().run({"repo_root": str(repo_root), "task_id": task_id})
        return f"workspace/tasks/{task_id}/review/design_review.json", result.output
    if step == "coding_plan":
        result = CoderAgent().run({"repo_root": str(repo_root), "task_id": task_id})
        return f"workspace/tasks/{task_id}/code/implementation_plan.json", result.output
    if step == "test_validation":
        result = TestValidatorAgent().run(
            {
                "repo_root": str(repo_root),
                "commands": step_options.get("commands"),
                "timeout_seconds": step_options.get("timeout_seconds", 120),
            }
        )
        return f"workspace/tasks/{task_id}/review/test_validation.json", result.output
    if step == "code_review":
        task_definition_path = step_options.get("task_definition_path")
        if task_definition_path is None and task_id.endswith("-review"):
            # review 子流程默认读取父任务生成的 review_tasks.yaml，避免配置里硬编码某个 workflow id。
            task_definition_path = f"workspace/tasks/{_parent_task_id(task_id, '-review')}/input/review_tasks.yaml"
        result = CodeReviewerAgent().run(
            {
                "repo_root": str(repo_root),
                "task_id": task_id,
                "validation_path": step_options.get("validation_path"),
                "task_definition_path": task_definition_path,
            }
        )
        return f"workspace/tasks/{task_id}/review/code_review.json", result.output
    if step == "goal_effect_validation":
        result = GoalEffectValidatorAgent().run(
            {
                "repo_root": str(repo_root),
                "task_id": task_id,
                "goal_spec_path": step_options.get(
                    "goal_spec_path",
                    "workspace/tasks/validation-001/input/validation_goal.yaml",
                ),
            }
        )
        return f"workspace/tasks/{task_id}/final/validation_feedback.json", result.output
    if step == "optimization_planning":
        task_id_prefix = step_options.get("task_id_prefix")
        if isinstance(task_id_prefix, str):
            # workflow 配置可用当前任务号生成本轮专属任务 ID 前缀，避免复用历史任务状态。
            task_id_prefix = task_id_prefix.format(task_id=task_id)
        result = OptimizationPlannerAgent().run(
            {
                "repo_root": str(repo_root),
                "feedback_path": step_options.get(
                    "feedback_path",
                    "workspace/tasks/validation-001/final/validation_feedback.json",
                ),
                "feedback_paths": step_options.get("feedback_paths"),
                "task_id_prefix": task_id_prefix,
            }
        )
        return f"workspace/tasks/{task_id}/final/next_optimization_tasks.yaml", result.output
    if step == "optimization_execution_plan":
        result = OptimizationExecutorAgent().run(
            {
                "repo_root": str(repo_root),
                "tasks_path": step_options.get(
                    "tasks_path",
                    "workspace/tasks/optimization-001/final/next_optimization_tasks.yaml",
                ),
                "risk_approved": step_options.get("risk_approved", False),
            }
        )
        return f"workspace/tasks/{task_id}/code/execution_plan.json", result.output
    if step == "optimization_dispatch":
        tasks_path = step_options.get("tasks_path")
        if tasks_path is None and task_id.endswith("-dispatch"):
            # dispatch 子流程默认读取父任务生成的 dispatch_tasks.yaml，保证 workflow-00N 都能复用。
            tasks_path = f"workspace/tasks/{_parent_task_id(task_id, '-dispatch')}/input/dispatch_tasks.yaml"
        if tasks_path is None:
            task_local_tasks_path = f"workspace/tasks/{task_id}/final/next_optimization_tasks.yaml"
            # 同一 workflow 先 planning 后 dispatch 时，优先消费刚生成的本任务优化队列。
            if (Path(repo_root) / task_local_tasks_path).exists():
                tasks_path = task_local_tasks_path
        result = OptimizationDispatcherAgent().run(
            {
                "repo_root": str(repo_root),
                "tasks_path": tasks_path or "workspace/tasks/optimization-001/final/next_optimization_tasks.yaml",
                "risk_approved": step_options.get("risk_approved", False),
                "dispatch_all": step_options.get("dispatch_all", False),
                "max_tasks": step_options.get(
                    "max_tasks",
                    0 if step_options.get("dispatch_all", False) else 1,
                ),
            }
        )
        return f"workspace/tasks/{task_id}/code/dispatch_result.json", result.output
    if step == "dispatched_task_validation":
        return _run_dispatched_task_validation(repo_root, task_id, step_options)

    result = PlaceholderAgent("placeholder-agent").run(
        {
            "task_id": task_id,
            "workflow": workflow_name,
            "step": step,
        }
    )
    return _step_artifact_path(task_id, step), result.output


def _load_or_create_state(repo_root: str | Path, task_id: str) -> TaskState:
    try:
        return load_state(repo_root, task_id)
    except Exception:
        return TaskState(
            task_id=task_id,
            step="created",
            status="pending",
            gates={"goal_approved": True},
        )


def _append_unique(values: list[str], new_values: list[str]) -> list[str]:
    result = list(values)
    for value in new_values:
        if value not in result:
            result.append(value)
    return result


def _task_validation_summary(
    *,
    parent_task_id: str,
    dispatched_task_id: str,
    status: str,
    artifacts: list[str],
    blocking_issues: list[dict[str, Any]],
    gates: dict[str, bool],
) -> dict[str, Any]:
    return {
        "task_id": parent_task_id,
        "status": status,
        "dispatched_task_id": dispatched_task_id,
        "artifacts": artifacts,
        "blocking_issues": blocking_issues,
        "gates": gates,
    }


def _persist_dispatched_validation(
    repo_root: str | Path,
    dispatch_result_path: str,
    dispatch_result: dict[str, Any],
    summary: dict[str, Any],
) -> None:
    dispatch_result["dispatched_task_validation"] = {
        "status": summary["status"],
        "dispatched_task_id": summary["dispatched_task_id"],
        "artifacts": summary["artifacts"],
        "blocking_issues": summary["blocking_issues"],
    }
    dispatch_result["written_artifacts"] = _append_unique(
        list(dispatch_result.get("written_artifacts", [])),
        list(summary["artifacts"]),
    )
    write_json(repo_root, dispatch_result_path, dispatch_result)


def _run_dispatched_task_validation(
    repo_root: str | Path,
    parent_task_id: str,
    step_options: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    dispatch_result_path = step_options.get(
        "dispatch_result_path",
        f"workspace/tasks/{parent_task_id}/code/dispatch_result.json",
    )
    dispatch_result = read_json(repo_root, dispatch_result_path)
    if dispatch_result.get("status") != "dispatched" or dispatch_result.get("dispatch_result") is None:
        blocking_issues = dispatch_result.get("blocking_issues") or [
            {
                "id": "no_dispatched_task",
                "severity": "medium",
                "description": "没有可验证的被调度任务。",
                "recommendation": "先提供 open 状态的优化任务并完成调度。",
            }
        ]
        summary = _task_validation_summary(
            parent_task_id=parent_task_id,
            dispatched_task_id="",
            status="blocked",
            artifacts=[],
            blocking_issues=blocking_issues,
            gates={},
        )
        _persist_dispatched_validation(repo_root, dispatch_result_path, dispatch_result, summary)
        return f"workspace/tasks/{parent_task_id}/review/dispatched_task_validation.json", summary

    if dispatch_result.get("dispatches"):
        summaries = []
        artifacts: list[str] = []
        blocking_issues: list[dict[str, Any]] = []
        # 批量调度时每个子任务独立验证，父任务只汇总所有子任务的阻塞问题和产物。
        for dispatch in dispatch_result["dispatches"]:
            summary = _validate_one_dispatched_task(repo_root, parent_task_id, dispatch, step_options)
            summaries.append(summary)
            artifacts = _append_unique(artifacts, summary["artifacts"])
            blocking_issues.extend(summary["blocking_issues"])
            dispatch["dispatched_task_validation"] = {
                "status": summary["status"],
                "dispatched_task_id": summary["dispatched_task_id"],
                "artifacts": summary["artifacts"],
                "blocking_issues": summary["blocking_issues"],
            }
            dispatch["written_artifacts"] = _append_unique(
                list(dispatch.get("written_artifacts", [])),
                summary["artifacts"],
            )

        summary = {
            "task_id": parent_task_id,
            "status": "passed" if not blocking_issues else "blocked",
            "dispatched_task_id": summaries[0]["dispatched_task_id"] if summaries else "",
            "dispatched_tasks": summaries,
            "artifacts": artifacts,
            "blocking_issues": blocking_issues,
            "gates": {},
        }
        dispatch_result["dispatched_task_validation"] = {
            "status": summary["status"],
            "dispatched_tasks": [
                {
                    "dispatched_task_id": item["dispatched_task_id"],
                    "status": item["status"],
                    "artifacts": item["artifacts"],
                    "blocking_issues": item["blocking_issues"],
                }
                for item in summaries
            ],
            "artifacts": artifacts,
            "blocking_issues": blocking_issues,
        }
        dispatch_result["written_artifacts"] = _append_unique(
            list(dispatch_result.get("written_artifacts", [])),
            artifacts,
        )
        write_json(repo_root, dispatch_result_path, dispatch_result)
        return f"workspace/tasks/{parent_task_id}/review/dispatched_task_validation.json", summary

    summary = _validate_one_dispatched_task(repo_root, parent_task_id, dispatch_result, step_options)
    _persist_dispatched_validation(repo_root, dispatch_result_path, dispatch_result, summary)
    return f"workspace/tasks/{parent_task_id}/review/dispatched_task_validation.json", summary


def _validate_one_dispatched_task(
    repo_root: str | Path,
    parent_task_id: str,
    dispatch_result: dict[str, Any],
    step_options: dict[str, Any],
) -> dict[str, Any]:
    selected_task = dispatch_result.get("selected_task") or {}
    dispatched_task_id = selected_task.get("id") or dispatch_result["dispatch_result"]["task_id"]
    task_definition_path = step_options.get(
        "task_definition_path",
        dispatch_result.get("tasks_path", "workspace/tasks/optimization-001/final/next_optimization_tasks.yaml"),
    )

    state = _load_or_create_state(repo_root, dispatched_task_id)
    artifacts: list[str] = []
    blocking_issues: list[dict[str, Any]] = []

    test_validation_path = f"workspace/tasks/{dispatched_task_id}/review/test_validation.json"
    state.update(step="test_validation", status="running")
    save_state(repo_root, state)
    validation = TestValidatorAgent().run(
        {
            "repo_root": str(repo_root),
            "commands": step_options.get("commands"),
            "timeout_seconds": step_options.get("timeout_seconds", 120),
        }
    ).output
    write_json(repo_root, test_validation_path, validation)
    state.record_artifact(test_validation_path)
    artifacts.append(test_validation_path)
    state.set_gate("tests_passed", bool(validation.get("passed")))
    if not validation.get("passed"):
        state.update(step="test_validation", status="blocked_by_test_validation")
        save_state(repo_root, state)
        blocking_issues.append(
            {
                "id": "dispatched_task_tests",
                "severity": "high",
                "description": "被调度任务测试验证未通过。",
                "recommendation": "修复被调度任务后重新运行调度验证闭环。",
            }
        )
        summary = _task_validation_summary(
            parent_task_id=parent_task_id,
            dispatched_task_id=dispatched_task_id,
            status="blocked",
            artifacts=artifacts,
            blocking_issues=blocking_issues,
            gates=state.gates,
        )
        return summary

    code_review_path = f"workspace/tasks/{dispatched_task_id}/review/code_review.json"
    state.update(step="code_review", status="running")
    save_state(repo_root, state)
    code_review = CodeReviewerAgent().run(
        {
            "repo_root": str(repo_root),
            "task_id": dispatched_task_id,
            "validation_path": test_validation_path,
            "task_definition_path": task_definition_path,
        }
    ).output
    write_json(repo_root, code_review_path, code_review)
    state.record_artifact(code_review_path)
    artifacts.append(code_review_path)
    state.set_gate("code_review_passed", not bool(code_review.get("blocking_issues")))
    if code_review.get("blocking_issues"):
        state.update(step="code_review", status="blocked_by_code_review")
        save_state(repo_root, state)
        blocking_issues.extend(code_review["blocking_issues"])
        summary = _task_validation_summary(
            parent_task_id=parent_task_id,
            dispatched_task_id=dispatched_task_id,
            status="blocked",
            artifacts=artifacts,
            blocking_issues=blocking_issues,
            gates=state.gates,
        )
        return summary

    validation_feedback_path = f"workspace/tasks/{dispatched_task_id}/final/validation_feedback.json"
    state.update(step="goal_effect_validation", status="running")
    save_state(repo_root, state)
    validation_feedback = GoalEffectValidatorAgent().run(
        {
            "repo_root": str(repo_root),
            "task_id": dispatched_task_id,
            "goal_spec_path": step_options.get(
                "goal_spec_path",
                "workspace/tasks/validation-001/input/validation_goal.yaml",
            ),
        }
    ).output
    write_json(repo_root, validation_feedback_path, validation_feedback)
    state.record_artifact(validation_feedback_path)
    artifacts.append(validation_feedback_path)
    blocking_issues.extend(validation_feedback.get("blocking_issues", []))

    if blocking_issues:
        state.update(step="goal_effect_validation", status="blocked_by_goal_effect_validation")
    else:
        state.update(step="dispatched_task_validation", status="waiting_for_human_merge_approval")
        state.set_gate("design_review_passed", True)
    save_state(repo_root, state)

    summary = _task_validation_summary(
        parent_task_id=parent_task_id,
        dispatched_task_id=dispatched_task_id,
        status="passed" if not blocking_issues else "blocked",
        artifacts=artifacts,
        blocking_issues=blocking_issues,
        gates=state.gates,
    )
    return summary


def run_local_task(
    repo_root: str | Path,
    workflow_name: str,
    *,
    task_id: str | None = None,
    goal_approved: bool = False,
) -> TaskState:
    """Run a configured workflow and persist task state after each step."""
    workflow_config = load_workflow_config(repo_root, workflow_name)
    workflow = workflow_config["workflow"]
    task_id = task_id or workflow["task_id"]
    steps = list(workflow.get("steps", []))
    human_gate_required = bool(
        workflow.get(
            "human_gate_required",
            workflow_config["agent_config"].get("human_gate_required", True),
        )
    )

    state = TaskState(
        task_id=task_id,
        step="start",
        status="running",
        gates={"goal_approved": goal_approved},
    )
    save_state(repo_root, state)

    for raw_step in steps:
        step = _step_name(raw_step)
        step_options = _step_options(raw_step)
        try:
            state.update(step=step, status="running")
            save_state(repo_root, state)

            artifact_path, output = _run_step(repo_root, workflow_name, task_id, step, step_options)
            # 每一步执行后立即落盘产物和状态，失败时仍能定位最后成功步骤。
            if artifact_path.endswith((".yaml", ".yml")):
                write_yaml(repo_root, artifact_path, output)
            else:
                write_json(repo_root, artifact_path, output)
            state.record_artifact(artifact_path)
            if step == "dispatched_task_validation":
                for child_artifact in output.get("artifacts", []):
                    state.record_artifact(child_artifact)
            if step == "design_review":
                if output["blocking_issues"]:
                    state.set_gate("design_review_passed", False)
                    state.update(step=step, status="blocked_by_design_review")
                    save_state(repo_root, state)
                    return state
                state.set_gate("design_review_passed", True)
            if step == "test_validation":
                if output["passed"]:
                    state.set_gate("tests_passed", True)
                else:
                    state.set_gate("tests_passed", False)
                    state.update(step=step, status="blocked_by_test_validation")
                    save_state(repo_root, state)
                    return state
            if step == "code_review":
                if output["blocking_issues"]:
                    state.set_gate("code_review_passed", False)
                    state.update(step=step, status="blocked_by_code_review")
                    save_state(repo_root, state)
                    return state
                state.set_gate("code_review_passed", True)
            if step == "goal_effect_validation" and output["blocking_issues"]:
                state.update(step=step, status="blocked_by_goal_effect_validation")
                save_state(repo_root, state)
                return state
            if step == "optimization_execution_plan" and output["blocking_issues"]:
                state.update(step=step, status="blocked_by_risk_gate")
                save_state(repo_root, state)
                return state
            if step == "optimization_dispatch" and output["blocking_issues"]:
                state.update(step=step, status="blocked_by_dispatch")
                save_state(repo_root, state)
                return state
            if step == "dispatched_task_validation" and output["blocking_issues"]:
                state.update(step=step, status="blocked_by_dispatched_task_validation")
                save_state(repo_root, state)
                return state
            save_state(repo_root, state)
        except Exception as exc:
            state.record_error(f"{step}: {exc}")
            save_state(repo_root, state)
            return state

    if human_gate_required:
        state.update(step="human_merge_gate", status="waiting_for_human_merge_approval")
    else:
        state.update(step="completed", status="completed")
        state.set_gate("human_merge_approved", True)
    save_state(repo_root, state)
    return state


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a local configured pipeline task.")
    parser.add_argument("--repo-root", default=".", help="Repository root. Defaults to cwd.")
    parser.add_argument("--workflow", default="local_dev", help="Workflow name in config/pipeline.yaml.")
    parser.add_argument("--task-id", help="Override the workflow task id.")
    parser.add_argument(
        "--goal-approved",
        action="store_true",
        help="Mark the human goal gate as approved for this local run.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    state = run_local_task(
        Path(args.repo_root),
        args.workflow,
        task_id=args.task_id,
        goal_approved=args.goal_approved,
    )
    print(json.dumps(state.to_dict(), ensure_ascii=False, indent=2))
    if state.status == "failed":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
