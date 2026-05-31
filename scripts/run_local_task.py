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
    TestValidatorAgent,
)
from artifacts import read_yaml, write_json
from tasks import TaskState, save_state


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
        result = CodeReviewerAgent().run({"repo_root": str(repo_root), "task_id": task_id})
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

    result = PlaceholderAgent("placeholder-agent").run(
        {
            "task_id": task_id,
            "workflow": workflow_name,
            "step": step,
        }
    )
    return _step_artifact_path(task_id, step), result.output


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
            write_json(repo_root, artifact_path, output)
            state.record_artifact(artifact_path)
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
