"""Dispatch an open optimization task to a local Agent."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from agents.base_agent import BaseAgent
from agents.code_reviewer_agent import CodeReviewerAgent
from agents.coder_agent import CoderAgent
from agents.design_reviewer_agent import DesignReviewerAgent
from agents.generation_agents import (
    ArchitectAgent,
    ProjectAnalysisAgent,
    RequirementAnalysisAgent,
    SystemDesignAgent,
)
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
        dispatch_all = bool(payload.get("dispatch_all", False))
        max_tasks = int(payload.get("max_tasks", 0 if dispatch_all else 1))

        if dispatch_all or max_tasks > 1:
            return self._dispatch_many(repo_root, tasks_path, risk_approved, max_tasks)

        return self._dispatch_one(repo_root, tasks_path, risk_approved)

    def _dispatch_many(
        self,
        repo_root: Path,
        tasks_path: str,
        risk_approved: bool,
        max_tasks: int,
    ) -> Mapping[str, Any]:
        dispatches: list[dict[str, Any]] = []
        blocking_issues: list[dict[str, Any]] = []
        while max_tasks <= 0 or len(dispatches) < max_tasks:
            dispatch = dict(self._dispatch_one(repo_root, tasks_path, risk_approved))
            if dispatch["status"] == "no_open_tasks":
                break
            if dispatch.get("blocking_issues"):
                blocking_issues.extend(dispatch["blocking_issues"])
                break
            dispatches.append(dispatch)

        if not dispatches:
            return {
                "status": "no_open_tasks" if not blocking_issues else "blocked",
                "selected_task": None,
                "tasks_path": tasks_path,
                "task_batch": {},
                "execution": None,
                "dispatch_result": None,
                "dispatches": [],
                "written_artifacts": [],
                "blocking_issues": blocking_issues,
            }

        return {
            "status": "dispatched",
            "selected_task": dispatches[0]["selected_task"],
            "tasks_path": tasks_path,
            "task_batch": dispatches[0].get("task_batch", {}),
            "source_tasks": dispatches[0].get("source_tasks", []),
            "source_feedback_paths": dispatches[0].get("source_feedback_paths", []),
            "execution": dispatches[0].get("execution"),
            "dispatch_result": dispatches[0].get("dispatch_result"),
            "dispatches": dispatches,
            "written_artifacts": self._flatten_written_artifacts(dispatches),
            "blocking_issues": blocking_issues,
            "batch": {
                "requested": "all" if max_tasks <= 0 else max_tasks,
                "dispatched_count": len(dispatches),
            },
        }

    def _dispatch_one(
        self,
        repo_root: Path,
        tasks_path: str,
        risk_approved: bool,
    ) -> Mapping[str, Any]:
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
        elif recommended_agent in self._generation_agents():
            dispatch_result, written_artifacts = self._dispatch_generation_agent(
                repo_root,
                selected_task,
                recommended_agent,
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

    def _flatten_written_artifacts(self, dispatches: list[dict[str, Any]]) -> list[str]:
        artifacts: list[str] = []
        for dispatch in dispatches:
            for artifact in dispatch.get("written_artifacts", []):
                if artifact not in artifacts:
                    artifacts.append(artifact)
        return artifacts

    def _review_validation_agents(self) -> set[str]:
        return {
            "DesignReviewerAgent",
            "TestValidatorAgent",
            "CodeReviewerAgent",
            "GoalEffectValidatorAgent",
        }

    def _generation_agents(self) -> set[str]:
        return set(self._generation_agent_specs())

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

    def _generation_agent_specs(self) -> dict[str, dict[str, Any]]:
        return {
            "ProjectAnalysisAgent": {
                "agent": ProjectAnalysisAgent,
                "step": "project_analysis",
                "artifact_path": "workspace/tasks/{task_id}/analysis/project_context.json",
            },
            "RequirementAnalysisAgent": {
                "agent": RequirementAnalysisAgent,
                "step": "requirement_analysis",
                "artifact_path": "workspace/tasks/{task_id}/requirements/requirements.json",
            },
            "ArchitectAgent": {
                "agent": ArchitectAgent,
                "step": "architecture_analysis",
                "artifact_path": "workspace/tasks/{task_id}/architecture/architecture_analysis.json",
            },
            "SystemDesignAgent": {
                "agent": SystemDesignAgent,
                "step": "system_design",
                "artifact_path": "workspace/tasks/{task_id}/design/system_design.json",
            },
        }

    def _dispatch_generation_agent(
        self,
        repo_root: Path,
        selected_task: dict[str, Any],
        recommended_agent: str,
    ) -> tuple[dict[str, Any], list[str]]:
        spec = self._generation_agent_specs()[recommended_agent]
        task_id = selected_task["id"]
        artifact_path = spec["artifact_path"].format(task_id=task_id)
        agent_class = spec["agent"]
        result = agent_class().run(
            {
                "repo_root": str(repo_root),
                "task_id": task_id,
                "selected_task": selected_task,
            }
        ).output

        state = self._state_for_agent_result(repo_root, task_id, artifact_path)
        state.update(step=spec["step"], status="waiting_for_human_merge_approval")
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
