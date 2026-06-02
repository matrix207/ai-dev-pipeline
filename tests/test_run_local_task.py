from __future__ import annotations

import json
import sys
from pathlib import Path

from artifacts import read_json, read_yaml, write_json, write_yaml
from scripts.run_local_task import run_local_task
from tasks import load_state


def write_config(tmp_path: Path, steps: list, *, human_gate_required: bool = True) -> None:
    write_yaml(
        tmp_path,
        "config/pipeline.yaml",
        {
            "agent_config": {
                "human_gate_required": human_gate_required,
            },
            "workflows": {
                "local_dev": {
                    "task_id": "dev-003",
                    "steps": steps,
                }
            },
        },
    )


def write_design_artifacts(tmp_path: Path, task_id: str, *, valid_design: bool = True) -> None:
    write_yaml(
        tmp_path,
        f"workspace/tasks/{task_id}/analysis/project_context.yaml",
        {"task_id": task_id, "summary": "local MVP"},
    )
    (tmp_path / f"workspace/tasks/{task_id}/architecture").mkdir(parents=True, exist_ok=True)
    (tmp_path / f"workspace/tasks/{task_id}/architecture/mvp_architecture.md").write_text(
        "# 架构\n\n包含人工质量门。",
        encoding="utf-8",
    )
    design = {
        "modules": {"agents": {"purpose": "run agents"}},
        "workflow": {"bootstrap": {"steps": ["design_review"]}},
    }
    if not valid_design:
        design.pop("workflow")
    write_yaml(tmp_path, f"workspace/tasks/{task_id}/design/mvp_system_design.yaml", design)


def write_task_batch(tmp_path: Path, task_id: str = "dev-005") -> None:
    write_yaml(
        tmp_path,
        "workspace/tasks/bootstrap-001/final/next_dev_tasks.yaml",
        {
            "tasks": [
                {
                    "id": task_id,
                    "title": "编码 Agent 骨架",
                    "priority": "medium",
                    "scope": ["创建 coder Agent 的最小接口。"],
                    "out_of_scope": ["自动提交或自动合并。"],
                    "acceptance_criteria": ["输出结构化实现计划。"],
                }
            ]
        },
    )


def write_validation_goal(tmp_path: Path) -> None:
    write_yaml(
        tmp_path,
        "workspace/tasks/validation-001/input/validation_goal.yaml",
        {
            "goal": "自动化验证闭环可运行。",
            "required_artifacts": ["config/pipeline.yaml"],
            "expected_effects": {
                "tests_pass": True,
                "code_review_passes": True,
            },
        },
    )


def test_run_local_task_writes_state_and_step_artifacts(tmp_path: Path) -> None:
    write_config(tmp_path, ["load_config", "write_state"])

    state = run_local_task(tmp_path, "local_dev", goal_approved=True)

    assert state.task_id == "dev-003"
    assert state.step == "human_merge_gate"
    assert state.status == "waiting_for_human_merge_approval"
    assert state.gates["goal_approved"] is True
    assert state.gates["human_merge_approved"] is False
    assert state.artifacts == [
        "workspace/tasks/dev-003/orchestration/load_config.json",
        "workspace/tasks/dev-003/orchestration/write_state.json",
    ]
    assert load_state(tmp_path, "dev-003").to_dict() == state.to_dict()
    assert read_json(tmp_path, state.artifacts[0])["step"] == "load_config"


def test_run_local_task_records_failure_state(tmp_path: Path) -> None:
    write_config(tmp_path, ["load_config", "fail", "write_state"])

    state = run_local_task(tmp_path, "local_dev", goal_approved=True)

    assert state.step == "fail"
    assert state.status == "failed"
    assert state.errors == ["fail: Placeholder step failed."]
    assert state.artifacts == ["workspace/tasks/dev-003/orchestration/load_config.json"]
    assert load_state(tmp_path, "dev-003").to_dict() == state.to_dict()


def test_run_local_task_can_complete_without_human_gate(tmp_path: Path) -> None:
    write_config(tmp_path, ["load_config"], human_gate_required=False)

    state = run_local_task(tmp_path, "local_dev", goal_approved=True)

    assert state.step == "completed"
    assert state.status == "completed"
    assert state.gates["human_merge_approved"] is True


def test_run_local_task_cli_outputs_state(tmp_path: Path, capsys) -> None:
    write_config(tmp_path, ["load_config"])

    from scripts.run_local_task import main
    import sys

    old_argv = sys.argv
    sys.argv = [
        "run_local_task.py",
        "--repo-root",
        str(tmp_path),
        "--workflow",
        "local_dev",
        "--goal-approved",
    ]
    try:
        exit_code = main()
    finally:
        sys.argv = old_argv

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["task_id"] == "dev-003"
    assert output["status"] == "waiting_for_human_merge_approval"


def test_run_local_task_stops_when_design_review_blocks(tmp_path: Path) -> None:
    write_config(tmp_path, ["design_review", "write_state"])
    write_design_artifacts(tmp_path, "dev-003", valid_design=False)

    state = run_local_task(tmp_path, "local_dev", goal_approved=True)

    assert state.step == "design_review"
    assert state.status == "blocked_by_design_review"
    assert state.gates["design_review_passed"] is False
    assert state.artifacts == ["workspace/tasks/dev-003/review/design_review.json"]
    review = read_json(tmp_path, state.artifacts[0])
    assert review["blocking_issues"][0]["id"] == "design_workflow"


def test_run_local_task_continues_when_design_review_passes(tmp_path: Path) -> None:
    write_config(tmp_path, ["design_review", "write_state"])
    write_design_artifacts(tmp_path, "dev-003")

    state = run_local_task(tmp_path, "local_dev", goal_approved=True)

    assert state.step == "human_merge_gate"
    assert state.status == "waiting_for_human_merge_approval"
    assert state.gates["design_review_passed"] is True
    assert state.artifacts == [
        "workspace/tasks/dev-003/review/design_review.json",
        "workspace/tasks/dev-003/orchestration/write_state.json",
    ]


def test_run_local_task_writes_coding_plan_artifact(tmp_path: Path) -> None:
    write_config(tmp_path, ["coding_plan"])
    write_task_batch(tmp_path, "dev-003")

    state = run_local_task(tmp_path, "local_dev", goal_approved=True)

    assert state.step == "human_merge_gate"
    assert state.status == "waiting_for_human_merge_approval"
    assert state.artifacts == ["workspace/tasks/dev-003/code/implementation_plan.json"]
    plan = read_json(tmp_path, state.artifacts[0])
    assert plan["task_id"] == "dev-003"
    assert plan["safety"]["pr_or_merge"] == "not_allowed"


def test_run_local_task_can_configure_llm_for_coding_plan(tmp_path: Path) -> None:
    write_yaml(
        tmp_path,
        "config/pipeline.yaml",
        {
            "agent_config": {"human_gate_required": True},
            "models": {
                "coding_llm": {
                    "enabled": True,
                    "provider": "mock",
                    "model": "static-coding-plan",
                    "system_prompt": "增强编码计划，但不要绕过人工质量门。",
                    "response": {
                        "title": "LLM 增强编码计划",
                        "llm_notes": ["已根据模型配置增强结构化计划。"],
                    },
                }
            },
            "workflows": {
                "local_dev": {
                    "task_id": "dev-003",
                    "steps": [
                        {
                            "name": "coding_plan",
                            "llm_model": "coding_llm",
                        }
                    ],
                }
            },
        },
    )
    write_task_batch(tmp_path, "dev-003")

    state = run_local_task(tmp_path, "local_dev", goal_approved=True)

    assert state.step == "human_merge_gate"
    assert state.artifacts == ["workspace/tasks/dev-003/code/implementation_plan.json"]
    plan = read_json(tmp_path, state.artifacts[0])
    assert plan["title"] == "LLM 增强编码计划"
    assert plan["llm_notes"] == ["已根据模型配置增强结构化计划。"]
    assert plan["llm"] == {
        "used": True,
        "provider": "mock",
        "model": "static-coding-plan",
    }
    assert plan["safety"]["external_model_api"] == "not_used"


def test_run_local_task_runs_automated_validation_workflow(tmp_path: Path) -> None:
    write_config(
        tmp_path,
        [
            {
                "name": "test_validation",
                "commands": [[sys.executable, "-c", "print('ok')"]],
            },
            "code_review",
            "goal_effect_validation",
        ],
    )
    write_validation_goal(tmp_path)

    state = run_local_task(tmp_path, "local_dev", task_id="validation-001", goal_approved=True)

    assert state.step == "human_merge_gate"
    assert state.status == "waiting_for_human_merge_approval"
    assert state.gates["tests_passed"] is True
    assert state.gates["code_review_passed"] is True
    assert state.artifacts == [
        "workspace/tasks/validation-001/review/test_validation.json",
        "workspace/tasks/validation-001/review/code_review.json",
        "workspace/tasks/validation-001/final/validation_feedback.json",
    ]
    feedback = read_json(tmp_path, state.artifacts[-1])
    assert feedback["status"] == "passed"


def test_run_local_task_stops_when_test_validation_fails(tmp_path: Path) -> None:
    write_config(
        tmp_path,
        [
            {
                "name": "test_validation",
                "commands": [[sys.executable, "-c", "raise SystemExit(1)"]],
            },
            "code_review",
        ],
    )

    state = run_local_task(tmp_path, "local_dev", task_id="validation-001", goal_approved=True)

    assert state.step == "test_validation"
    assert state.status == "blocked_by_test_validation"
    assert state.gates["tests_passed"] is False


def test_run_local_task_generates_optimization_tasks(tmp_path: Path) -> None:
    write_config(tmp_path, ["optimization_planning"])

    write_json(
        tmp_path,
        "workspace/tasks/validation-001/final/validation_feedback.json",
        {
            "task_id": "validation-001",
            "alignment_score": 1.0,
            "blocking_issues": [],
        },
    )

    state = run_local_task(tmp_path, "local_dev", task_id="optimization-001", goal_approved=True)

    assert state.step == "human_merge_gate"
    assert state.status == "waiting_for_human_merge_approval"
    assert state.artifacts == ["workspace/tasks/optimization-001/final/next_optimization_tasks.yaml"]
    generated = read_yaml(tmp_path, state.artifacts[0])
    assert generated["task_batch"]["planning_mode"] == "enhancement"


def test_run_local_task_generates_optimization_tasks_from_multiple_feedbacks(
    tmp_path: Path,
) -> None:
    write_config(
        tmp_path,
        [
            {
                "name": "optimization_planning",
                "feedback_paths": [
                    "workspace/tasks/parent/final/validation_feedback.json",
                    "workspace/tasks/child/final/validation_feedback.json",
                ],
            }
        ],
    )
    write_json(
        tmp_path,
        "workspace/tasks/parent/final/validation_feedback.json",
        {
            "task_id": "parent",
            "alignment_score": 1.0,
            "blocking_issues": [],
        },
    )
    write_json(
        tmp_path,
        "workspace/tasks/child/final/validation_feedback.json",
        {
            "task_id": "child",
            "alignment_score": 1.0,
            "blocking_issues": [],
        },
    )

    state = run_local_task(tmp_path, "local_dev", task_id="feedback-001", goal_approved=True)

    assert state.step == "human_merge_gate"
    assert state.status == "waiting_for_human_merge_approval"
    assert state.artifacts == ["workspace/tasks/feedback-001/final/next_optimization_tasks.yaml"]
    generated = read_yaml(tmp_path, state.artifacts[0])
    assert generated["task_batch"]["source_tasks"] == ["parent", "child"]
    assert generated["task_batch"]["source_feedback_paths"] == [
        "workspace/tasks/parent/final/validation_feedback.json",
        "workspace/tasks/child/final/validation_feedback.json",
    ]


def test_run_local_task_writes_optimization_execution_plan(tmp_path: Path) -> None:
    write_config(tmp_path, ["optimization_execution_plan"])
    write_yaml(
        tmp_path,
        "workspace/tasks/optimization-001/final/next_optimization_tasks.yaml",
        {
            "tasks": [
                {
                    "id": "next-task",
                    "title": "Next",
                    "priority": "medium",
                    "recommended_agent": "CoderAgent",
                    "risk_level": "medium",
                    "human_gate": {
                        "goal_approval_required": True,
                        "risk_approval_required": False,
                        "merge_approval_required": True,
                    },
                    "scope": ["do next"],
                    "acceptance_criteria": ["next done"],
                }
            ]
        },
    )

    state = run_local_task(tmp_path, "local_dev", task_id="planning-003", goal_approved=True)

    assert state.step == "human_merge_gate"
    assert state.status == "waiting_for_human_merge_approval"
    assert state.artifacts == ["workspace/tasks/planning-003/code/execution_plan.json"]
    plan = read_json(tmp_path, state.artifacts[0])
    assert plan["selected_task"]["id"] == "next-task"


def test_run_local_task_dispatches_optimization_task(tmp_path: Path) -> None:
    write_config(tmp_path, ["optimization_dispatch"])
    write_yaml(
        tmp_path,
        "workspace/tasks/optimization-001/final/next_optimization_tasks.yaml",
        {
            "tasks": [
                {
                    "id": "dispatch-task",
                    "title": "Dispatch Task",
                    "priority": "medium",
                    "recommended_agent": "CoderAgent",
                    "risk_level": "medium",
                    "human_gate": {
                        "goal_approval_required": True,
                        "risk_approval_required": False,
                        "merge_approval_required": True,
                    },
                    "scope": ["生成执行计划。"],
                    "out_of_scope": ["自动 merge。"],
                    "acceptance_criteria": ["执行后产生任务状态和验证反馈。"],
                }
            ]
        },
    )

    state = run_local_task(tmp_path, "local_dev", task_id="exec-003", goal_approved=True)

    assert state.step == "human_merge_gate"
    assert state.status == "waiting_for_human_merge_approval"
    assert state.artifacts == ["workspace/tasks/exec-003/code/dispatch_result.json"]
    result = read_json(tmp_path, state.artifacts[0])
    assert result["status"] == "dispatched"
    assert result["dispatch_result"]["task_id"] == "dispatch-task"
    dispatched_state = read_json(tmp_path, "workspace/tasks/dispatch-task/state.json")
    assert dispatched_state["status"] == "waiting_for_validation"


def test_run_local_task_dispatches_feedback_generated_tasks(tmp_path: Path) -> None:
    write_config(
        tmp_path,
        [
            {
                "name": "optimization_dispatch",
                "tasks_path": "workspace/tasks/feedback-001/final/next_optimization_tasks.yaml",
            }
        ],
    )
    write_yaml(
        tmp_path,
        "workspace/tasks/feedback-001/final/next_optimization_tasks.yaml",
        {
            "task_batch": {
                "source_tasks": ["dispatch-001", "dispatch-validation-demo"],
                "source_feedback_paths": [
                    "workspace/tasks/dispatch-001/final/validation_feedback.json",
                    "workspace/tasks/dispatch-validation-demo/final/validation_feedback.json",
                ],
            },
            "tasks": [
                {
                    "id": "feedback-002",
                    "title": "把下一轮优化任务接入调度执行",
                    "priority": "medium",
                    "recommended_agent": "CoderAgent",
                    "risk_level": "medium",
                    "human_gate": {
                        "goal_approval_required": True,
                        "risk_approval_required": False,
                        "merge_approval_required": True,
                    },
                    "scope": ["调度反馈生成的任务。"],
                    "out_of_scope": ["自动 merge。"],
                    "acceptance_criteria": ["调度产物能引用来源 validation_feedback。"],
                }
            ],
        },
    )

    state = run_local_task(tmp_path, "local_dev", task_id="feedback-dispatch-001", goal_approved=True)

    assert state.step == "human_merge_gate"
    assert state.status == "waiting_for_human_merge_approval"
    assert state.artifacts == ["workspace/tasks/feedback-dispatch-001/code/dispatch_result.json"]
    dispatch_result = read_json(tmp_path, state.artifacts[0])
    assert dispatch_result["selected_task"]["id"] == "feedback-002"
    assert dispatch_result["source_feedback_paths"] == [
        "workspace/tasks/dispatch-001/final/validation_feedback.json",
        "workspace/tasks/dispatch-validation-demo/final/validation_feedback.json",
    ]
    dispatched_state = read_json(tmp_path, "workspace/tasks/feedback-002/state.json")
    assert dispatched_state["status"] == "waiting_for_validation"


def test_run_local_task_dispatches_task_local_feedback_plan(tmp_path: Path) -> None:
    write_config(
        tmp_path,
        [
            {
                "name": "optimization_planning",
                "task_id_prefix": "{task_id}",
            },
            "optimization_dispatch",
        ],
    )
    write_json(
        tmp_path,
        "workspace/tasks/validation-001/final/validation_feedback.json",
        {
            "task_id": "validation-001",
            "alignment_score": 1.0,
            "blocking_issues": [],
        },
    )

    state = run_local_task(tmp_path, "local_dev", task_id="feedback-execution-001", goal_approved=True)

    assert state.step == "human_merge_gate"
    assert state.status == "waiting_for_human_merge_approval"
    assert state.artifacts == [
        "workspace/tasks/feedback-execution-001/final/next_optimization_tasks.yaml",
        "workspace/tasks/feedback-execution-001/code/dispatch_result.json",
    ]
    dispatch_result = read_json(
        tmp_path,
        "workspace/tasks/feedback-execution-001/code/dispatch_result.json",
    )
    assert dispatch_result["status"] == "dispatched"
    assert dispatch_result["selected_task"]["id"] == "feedback-execution-001-feedback-002"
    assert dispatch_result["selected_task"]["source_task_id"] == "feedback-002"
    assert dispatch_result["tasks_path"] == (
        "workspace/tasks/feedback-execution-001/final/next_optimization_tasks.yaml"
    )
    assert dispatch_result["selected_task"]["source_feedback_paths"] == [
        "workspace/tasks/validation-001/final/validation_feedback.json"
    ]


def test_run_local_task_validates_dispatched_task(tmp_path: Path) -> None:
    write_config(
        tmp_path,
        [
            "optimization_dispatch",
            {
                "name": "dispatched_task_validation",
                "commands": [[sys.executable, "-c", "print('ok')"]],
            },
        ],
    )
    write_validation_goal(tmp_path)
    write_yaml(
        tmp_path,
        "workspace/tasks/optimization-001/final/next_optimization_tasks.yaml",
        {
            "tasks": [
                {
                    "id": "dispatch-task",
                    "title": "Dispatch Task",
                    "priority": "medium",
                    "recommended_agent": "CoderAgent",
                    "risk_level": "medium",
                    "human_gate": {
                        "goal_approval_required": True,
                        "risk_approval_required": False,
                        "merge_approval_required": True,
                    },
                    "scope": ["生成执行计划。"],
                    "out_of_scope": ["自动 merge。"],
                    "acceptance_criteria": ["执行后产生任务状态和验证反馈。"],
                }
            ]
        },
    )

    state = run_local_task(tmp_path, "local_dev", task_id="exec-003", goal_approved=True)

    assert state.step == "human_merge_gate"
    assert state.status == "waiting_for_human_merge_approval"
    assert state.artifacts == [
        "workspace/tasks/exec-003/code/dispatch_result.json",
        "workspace/tasks/exec-003/review/dispatched_task_validation.json",
        "workspace/tasks/dispatch-task/review/test_validation.json",
        "workspace/tasks/dispatch-task/review/code_review.json",
        "workspace/tasks/dispatch-task/final/validation_feedback.json",
    ]
    summary = read_json(tmp_path, "workspace/tasks/exec-003/review/dispatched_task_validation.json")
    assert summary["status"] == "passed"
    assert summary["dispatched_task_id"] == "dispatch-task"
    assert summary["artifacts"] == [
        "workspace/tasks/dispatch-task/review/test_validation.json",
        "workspace/tasks/dispatch-task/review/code_review.json",
        "workspace/tasks/dispatch-task/final/validation_feedback.json",
    ]
    dispatch_result = read_json(tmp_path, "workspace/tasks/exec-003/code/dispatch_result.json")
    assert dispatch_result["dispatched_task_validation"]["status"] == "passed"
    dispatched_state = read_json(tmp_path, "workspace/tasks/dispatch-task/state.json")
    assert dispatched_state["status"] == "waiting_for_human_merge_approval"
    assert dispatched_state["gates"]["tests_passed"] is True
    assert dispatched_state["gates"]["code_review_passed"] is True


def test_run_local_task_validates_multiple_dispatched_tasks(tmp_path: Path) -> None:
    write_config(
        tmp_path,
        [
            {
                "name": "optimization_dispatch",
                "dispatch_all": True,
            },
            {
                "name": "dispatched_task_validation",
                "commands": [[sys.executable, "-c", "print('ok')"]],
            },
        ],
    )
    write_validation_goal(tmp_path)
    write_yaml(
        tmp_path,
        "workspace/tasks/optimization-001/final/next_optimization_tasks.yaml",
        {
            "tasks": [
                {
                    "id": "batch-one",
                    "title": "Batch One",
                    "priority": "high",
                    "recommended_agent": "CoderAgent",
                    "risk_level": "medium",
                    "human_gate": {
                        "goal_approval_required": True,
                        "risk_approval_required": False,
                        "merge_approval_required": True,
                    },
                    "scope": ["生成第一个执行计划。"],
                    "acceptance_criteria": ["第一个任务完成。"],
                },
                {
                    "id": "batch-two",
                    "title": "Batch Two",
                    "priority": "medium",
                    "recommended_agent": "CoderAgent",
                    "risk_level": "medium",
                    "human_gate": {
                        "goal_approval_required": True,
                        "risk_approval_required": False,
                        "merge_approval_required": True,
                    },
                    "scope": ["生成第二个执行计划。"],
                    "acceptance_criteria": ["第二个任务完成。"],
                },
            ]
        },
    )

    state = run_local_task(tmp_path, "local_dev", task_id="dispatch-003", goal_approved=True)

    assert state.step == "human_merge_gate"
    assert state.status == "waiting_for_human_merge_approval"
    summary = read_json(tmp_path, "workspace/tasks/dispatch-003/review/dispatched_task_validation.json")
    assert summary["status"] == "passed"
    assert [item["dispatched_task_id"] for item in summary["dispatched_tasks"]] == [
        "batch-one",
        "batch-two",
    ]
    dispatch_result = read_json(tmp_path, "workspace/tasks/dispatch-003/code/dispatch_result.json")
    assert dispatch_result["batch"]["dispatched_count"] == 2
    assert dispatch_result["dispatched_task_validation"]["status"] == "passed"
    assert read_json(tmp_path, "workspace/tasks/batch-one/state.json")["status"] == (
        "waiting_for_human_merge_approval"
    )
    assert read_json(tmp_path, "workspace/tasks/batch-two/state.json")["status"] == (
        "waiting_for_human_merge_approval"
    )
