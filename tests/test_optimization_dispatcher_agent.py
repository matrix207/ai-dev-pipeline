from __future__ import annotations

from pathlib import Path

from agents import OptimizationDispatcherAgent
from artifacts import read_json, write_json, write_yaml


def write_tasks(tmp_path: Path, *, risk_level: str = "medium", agent: str = "CoderAgent") -> None:
    write_yaml(
        tmp_path,
        "workspace/tasks/optimization-001/final/next_optimization_tasks.yaml",
        {
            "tasks": [
                {
                    "id": "dispatch-task",
                    "title": "Dispatch Task",
                    "priority": "medium",
                    "recommended_agent": agent,
                    "risk_level": risk_level,
                    "human_gate": {
                        "goal_approval_required": True,
                        "risk_approval_required": risk_level == "high",
                        "merge_approval_required": True,
                    },
                    "scope": ["生成执行计划。"],
                    "out_of_scope": ["自动 merge。"],
                    "acceptance_criteria": ["执行后产生任务状态和验证反馈。"],
                }
            ]
        },
    )


def test_optimization_dispatcher_dispatches_coder_agent(tmp_path: Path) -> None:
    write_tasks(tmp_path)

    result = OptimizationDispatcherAgent().run({"repo_root": str(tmp_path)})

    assert result.output["status"] == "dispatched"
    assert result.output["selected_task"]["id"] == "dispatch-task"
    assert result.output["dispatch_result"]["task_id"] == "dispatch-task"
    assert result.output["dispatch_result"]["safety"]["pr_or_merge"] == "not_allowed"
    assert result.output["written_artifacts"] == [
        "workspace/tasks/dispatch-task/code/implementation_plan.json",
        "workspace/tasks/dispatch-task/state.json",
    ]
    state = read_json(tmp_path, "workspace/tasks/dispatch-task/state.json")
    assert state["status"] == "waiting_for_validation"
    assert state["artifacts"] == ["workspace/tasks/dispatch-task/code/implementation_plan.json"]


def test_optimization_dispatcher_returns_no_open_tasks(tmp_path: Path) -> None:
    write_tasks(tmp_path)
    write_json(tmp_path, "workspace/tasks/dispatch-task/state.json", {"task_id": "dispatch-task"})

    result = OptimizationDispatcherAgent().run({"repo_root": str(tmp_path)})

    assert result.output["status"] == "no_open_tasks"
    assert result.output["dispatch_result"] is None


def test_optimization_dispatcher_blocks_high_risk_without_approval(tmp_path: Path) -> None:
    write_tasks(tmp_path, risk_level="high")

    result = OptimizationDispatcherAgent().run({"repo_root": str(tmp_path)})

    assert result.output["status"] == "blocked"
    assert result.output["blocking_issues"][0]["id"] == "risk_gate_required"


def test_optimization_dispatcher_blocks_unsupported_agent(tmp_path: Path) -> None:
    write_tasks(tmp_path, agent="UnknownAgent")

    result = OptimizationDispatcherAgent().run({"repo_root": str(tmp_path)})

    assert result.output["status"] == "blocked"
    assert result.output["blocking_issues"][0]["id"] == "unsupported_agent"
