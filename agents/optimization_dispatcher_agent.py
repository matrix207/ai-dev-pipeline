"""Dispatch an open optimization task to a local Agent."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from agents.base_agent import BaseAgent
from agents.code_reviewer_agent import CodeReviewerAgent
from agents.coder_agent import CoderAgent
from agents.design_reviewer_agent import DesignReviewerAgent
from agents.goal_effect_validator_agent import GoalEffectValidatorAgent
from agents.optimization_executor_agent import DEFAULT_OPTIMIZATION_TASKS_PATH, OptimizationExecutorAgent
from agents.test_validator_agent import TestValidatorAgent
from artifacts import write_json
from tasks import TaskState, load_state, save_state


class OptimizationDispatcherAgent(BaseAgent):
    """Select an optimization task and dispatch it to the recommended local Agent."""

    def __init__(self, name: str = "optimization-dispatcher") -> None:
        super().__init__(name)

    def handle(self, payload: dict[str, Any]) -> Mapping[str, Any]:
        repo_root = Path(payload.get("repo_root", "."))
        tasks_path = payload.get("tasks_path", DEFAULT_OPTIMIZATION_TASKS_PATH)
        risk_approved = bool(payload.get("risk_approved", False))

        execution = OptimizationExecutorAgent().run(
            {
                "repo_root": str(repo_root),
                "tasks_path": tasks_path,
                "risk_approved": risk_approved,
            }
        ).output
        if not execution.get("execution_allowed"):
            return {
                "status": execution["status"],
                "selected_task": execution.get("selected_task"),
                "tasks_path": tasks_path,
                "task_batch": execution.get("task_batch", {}),
                "execution": execution,
                "dispatch_result": None,
                "blocking_issues": execution.get("blocking_issues", []),
            }

        selected_task = execution["selected_task"]
        recommended_agent = selected_task.get("recommended_agent")
        if recommended_agent == "CoderAgent":
            dispatch_result = CoderAgent().run(
                {
                    "repo_root": str(repo_root),
                    "task_id": selected_task["id"],
                    "tasks_path": tasks_path,
                }
            ).output
            dispatched_task_id = selected_task["id"]
            implementation_plan_path = (
                f"workspace/tasks/{dispatched_task_id}/code/implementation_plan.json"
            )
            write_json(repo_root, implementation_plan_path, dispatch_result)
            dispatched_state = TaskState(
                task_id=dispatched_task_id,
                step="dispatched",
                status="waiting_for_validation",
                artifacts=[implementation_plan_path],
                gates={
                    "goal_approved": True,
                    "design_review_passed": True,
                    "tests_passed": False,
                    "code_review_passed": False,
                    "human_merge_approved": False,
                },
            )
            save_state(repo_root, dispatched_state)
            written_artifacts = [
                f"workspace/tasks/{selected_task['id']}/code/implementation_plan.json",
                f"workspace/tasks/{selected_task['id']}/state.json",
            ]
        elif recommended_agent in self._review_validation_agents():
            dispatch_result, written_artifacts = self._dispatch_review_validation_agent(
                repo_root,
                selected_task,
                recommended_agent,
                tasks_path,
            )
        else:
            return {
                "status": "blocked",
                "selected_task": selected_task,
                "execution": execution,
                "dispatch_result": None,
                "blocking_issues": [
                    {
                        "id": "unsupported_agent",
                        "severity": "medium",
                        "description": f"暂不支持调度 Agent：{recommended_agent}",
                        "recommendation": "为该 recommended_agent 增加本地调度适配。",
                    }
                ],
            }

        return {
            "status": "dispatched",
            "selected_task": selected_task,
            "tasks_path": tasks_path,
            "task_batch": execution.get("task_batch", {}),
            "source_tasks": selected_task.get("source_tasks", []),
            "source_feedback_paths": selected_task.get("source_feedback_paths", []),
            "execution": execution,
            "dispatch_result": dispatch_result,
            "written_artifacts": written_artifacts,
            "blocking_issues": [],
        }

    def _review_validation_agents(self) -> set[str]:
        return {
            "DesignReviewerAgent",
            "TestValidatorAgent",
            "CodeReviewerAgent",
            "GoalEffectValidatorAgent",
        }

    def _dispatch_review_validation_agent(
        self,
        repo_root: Path,
        selected_task: dict[str, Any],
        recommended_agent: str,
        tasks_path: str,
    ) -> tuple[dict[str, Any], list[str]]:
        task_id = selected_task["id"]
        target_task_id = selected_task.get("target_task_id", task_id)
        if recommended_agent == "DesignReviewerAgent":
            artifact_path = f"workspace/tasks/{task_id}/review/design_review.json"
            result = DesignReviewerAgent().run(
                {
                    "repo_root": str(repo_root),
                    "task_id": target_task_id,
                    "artifact_paths": selected_task.get("artifact_paths"),
                }
            ).output
            state = self._state_for_agent_result(repo_root, task_id, artifact_path)
            state.update(
                step="design_review",
                status="waiting_for_human_merge_approval"
                if not result.get("blocking_issues")
                else "blocked_by_design_review",
            )
            state.set_gate("design_review_passed", not bool(result.get("blocking_issues")))
        elif recommended_agent == "TestValidatorAgent":
            artifact_path = f"workspace/tasks/{task_id}/review/test_validation.json"
            result = TestValidatorAgent().run(
                {
                    "repo_root": str(repo_root),
                    "commands": selected_task.get("commands"),
                    "timeout_seconds": selected_task.get("timeout_seconds", 120),
                }
            ).output
            state = self._state_for_agent_result(repo_root, task_id, artifact_path)
            state.update(
                step="test_validation",
                status="waiting_for_code_review" if result.get("passed") else "blocked_by_test_validation",
            )
            state.set_gate("tests_passed", bool(result.get("passed")))
        elif recommended_agent == "CodeReviewerAgent":
            artifact_path = f"workspace/tasks/{task_id}/review/code_review.json"
            result = CodeReviewerAgent().run(
                {
                    "repo_root": str(repo_root),
                    "task_id": target_task_id,
                    "validation_path": selected_task.get(
                        "validation_path",
                        f"workspace/tasks/{target_task_id}/review/test_validation.json",
                    ),
                    "task_definition_path": selected_task.get("task_definition_path", tasks_path),
                }
            ).output
            state = self._state_for_agent_result(repo_root, task_id, artifact_path)
            state.update(
                step="code_review",
                status="waiting_for_human_merge_approval"
                if not result.get("blocking_issues")
                else "blocked_by_code_review",
            )
            state.set_gate("code_review_passed", not bool(result.get("blocking_issues")))
        else:
            artifact_path = f"workspace/tasks/{task_id}/final/validation_feedback.json"
            result = GoalEffectValidatorAgent().run(
                {
                    "repo_root": str(repo_root),
                    "task_id": target_task_id,
                    "goal_spec_path": selected_task.get(
                        "goal_spec_path",
                        "workspace/tasks/validation-001/input/validation_goal.yaml",
                    ),
                }
            ).output
            state = self._state_for_agent_result(repo_root, task_id, artifact_path)
            state.update(
                step="goal_effect_validation",
                status="waiting_for_human_merge_approval"
                if not result.get("blocking_issues")
                else "blocked_by_goal_effect_validation",
            )

        state.set_gate("goal_approved", True)
        write_json(repo_root, artifact_path, result)
        save_state(repo_root, state)
        return result, [artifact_path, f"workspace/tasks/{task_id}/state.json"]

    def _state_for_agent_result(self, repo_root: Path, task_id: str, artifact_path: str) -> TaskState:
        try:
            state = load_state(repo_root, task_id)
        except Exception:
            state = TaskState(task_id=task_id, step="dispatched", status="running")
        state.record_artifact(artifact_path)
        return state
