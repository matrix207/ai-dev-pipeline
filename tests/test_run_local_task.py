from __future__ import annotations

import json
import sys
from pathlib import Path

from artifacts import read_json, write_yaml
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
