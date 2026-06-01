from __future__ import annotations

import json
import sys
from pathlib import Path

from artifacts import read_text, read_yaml, write_json, write_yaml
from scripts.run_end_to_end import (
    _build_target_effect_report,
    _completed_template_task_ids,
    _fallback_recommended_task,
    _post_approval_action,
    _quality_gate,
    _quality_gate_config,
    approve_run_record,
    continue_run_record,
    format_continue_result,
    format_end_to_end_summary,
    main,
    run_end_to_end,
)
from tasks import load_state


def write_end_to_end_config(
    tmp_path: Path,
    *,
    validation_command: list[str] | None = None,
) -> None:
    validation_command = validation_command or [sys.executable, "-c", "print('ok')"]
    write_yaml(
        tmp_path,
        "config/pipeline.yaml",
        {
            "agent_config": {"human_gate_required": True},
            "workflows": {
                "ui_validation": {
                    "task_id": "ui-validation-001",
                    "steps": [
                        {
                            "name": "test_validation",
                            "commands": [validation_command],
                        },
                        "code_review",
                        "goal_effect_validation",
                    ],
                },
                "end_to_end_dispatch": {
                    "task_id": "workflow-001-dispatch",
                    "steps": [
                        {
                            "name": "optimization_dispatch",
                            "dispatch_all": True,
                        },
                        {
                            "name": "dispatched_task_validation",
                            "commands": [[sys.executable, "-c", "print('ok')"]],
                        },
                        {
                            "name": "test_validation",
                            "commands": [[sys.executable, "-c", "print('ok')"]],
                        },
                        "code_review",
                        "goal_effect_validation",
                    ],
                },
                "end_to_end_review": {
                    "task_id": "workflow-001-review",
                    "steps": [
                        {
                            "name": "test_validation",
                            "commands": [[sys.executable, "-c", "print('ok')"]],
                        },
                        "code_review",
                        "goal_effect_validation",
                    ],
                },
            },
        },
    )


def write_validation_goal(tmp_path: Path) -> None:
    write_yaml(
        tmp_path,
        "workspace/tasks/validation-001/input/validation_goal.yaml",
        {
            "goal": "端到端闭环可运行。",
            "required_artifacts": ["config/pipeline.yaml"],
            "expected_effects": {"tests_pass": True, "code_review_passes": True},
        },
    )


def test_run_end_to_end_writes_decision_summary(tmp_path: Path) -> None:
    write_end_to_end_config(tmp_path)
    write_validation_goal(tmp_path)

    summary = run_end_to_end(tmp_path, run_id="test-run-001")

    assert summary["task_id"] == "workflow-001"
    assert summary["status"] == "ready_for_human_decision"
    assert summary["run_metadata"]["run_id"] == "test-run-001"
    assert summary["run_metadata"]["started_at"].endswith("Z")
    assert summary["current_result"]["validation_state"]["status"] == "waiting_for_human_merge_approval"
    assert summary["current_result"]["dispatch_state"]["status"] == "waiting_for_human_merge_approval"
    assert summary["current_result"]["review_state"]["status"] == "waiting_for_human_merge_approval"
    assert len(summary["execution_summary"]["completed"]) == 3
    assert summary["execution_summary"]["skipped"] == []
    assert summary["execution_summary"]["failed"] == []
    assert summary["retry_plan"]["status"] == "not_required"
    assert {item["decision"] for item in summary["evidence_map"]} >= {
        "goal_effect_aligned",
        "tests_passed",
        "dispatch_validated",
        "code_review_passed",
        "retry_required",
        "next_action",
    }
    assert summary["next_recommended_action"]["reason"] == "来自端到端反馈闭环生成的下一轮优化任务。"

    saved = read_yaml(tmp_path, "workspace/tasks/workflow-001/final/decision_summary.yaml")
    assert saved == summary
    report = summary["target_effect_report"]
    assert report["artifact"] == "workspace/tasks/workflow-001/final/target_effect_report.md"
    assert (tmp_path / report["artifact"]).exists()
    state = load_state(tmp_path, "workflow-001")
    assert state.status == "waiting_for_human_merge_approval"
    assert "workspace/tasks/workflow-001/final/decision_summary.yaml" in state.artifacts
    assert "workspace/tasks/workflow-001/final/target_effect_report.md" in state.artifacts

    dispatch_tasks = read_yaml(tmp_path, "workspace/tasks/workflow-001/input/dispatch_tasks.yaml")
    assert len(dispatch_tasks["tasks"]) >= 1
    assert all(task["id"].startswith("workflow-001-") for task in dispatch_tasks["tasks"])


def test_target_effect_report_summarizes_render_evidence(tmp_path: Path) -> None:
    feedback_path = "workspace/tasks/workflow-018-validation/final/validation_feedback.json"
    screenshot_path = "workspace/tasks/workflow-018-validation/review/demo_render_main_view.png"
    write_json(
        tmp_path,
        feedback_path,
        {
            "task_id": "workflow-018-validation",
            "status": "passed",
            "alignment_score": 1.0,
            "blocking_issues": [],
            "demo_render_checks": [
                {
                    "id": "demo_render_main_view",
                    "expected_effect": "目标效果页可渲染并保留关键交互。",
                    "result": "pass",
                    "screenshot_artifact": screenshot_path,
                    "evidence": {
                        "screenshot": {
                            "artifact": screenshot_path,
                            "exists": True,
                            "bytes": 625004,
                            "min_bytes": 10000,
                            "passed": True,
                        },
                        "dom_terms": [
                            {"term": "AI开发流水线效果展示", "present": True},
                            {"term": "人工Gate", "present": True},
                        ],
                        "dom_selectors": [
                            {"selector": "#playBtn", "present": True},
                            {"selector": "[data-node=\"qa\"]", "present": True},
                        ],
                        "page_structure": {
                            "has_html": True,
                            "has_body": True,
                            "title": "AI开发流水线效果展示",
                        },
                    },
                    "acceptance_conclusion": {
                        "passed": True,
                        "summary": "目标效果渲染证据通过。",
                        "missing": {
                            "browser": [],
                            "screenshot": [],
                            "dom_terms": [],
                            "dom_selectors": [],
                        },
                    },
                }
            ],
        },
    )
    summary = {
        "task_id": "workflow-018",
        "goal_effect": {
            "validation_status": "passed",
            "alignment_score": 1.0,
            "blocking_issues": [],
        },
        "current_result": {
            "feedback_artifacts": [feedback_path],
        },
        "next_recommended_action": {
            "task_id": "workflow-019",
            "title": "继续优化",
        },
    }

    report = _build_target_effect_report(
        tmp_path,
        summary,
        "workspace/tasks/workflow-018/final/target_effect_report.md",
    )

    assert report["status"] == "passed"
    assert report["render_check_count"] == 1
    assert report["passed_render_check_count"] == 1
    assert report["screenshot_artifacts"] == [screenshot_path]
    text = read_text(tmp_path, report["artifact"])
    assert "目标效果验证报告" in text
    assert feedback_path in text
    assert screenshot_path in text
    assert "AI开发流水线效果展示" in text
    assert "#playBtn" in text
    assert "阻塞项：0" in text


def test_run_end_to_end_writes_run_record(tmp_path: Path) -> None:
    write_end_to_end_config(tmp_path)
    write_validation_goal(tmp_path)

    summary = run_end_to_end(tmp_path, task_id="workflow-004", run_id="run-record-001")

    assert summary["run_record_artifact"] == "workspace/tasks/workflow-004/runs/run-record-001.yaml"
    run_record = read_yaml(tmp_path, summary["run_record_artifact"])
    assert run_record["run_metadata"]["run_id"] == "run-record-001"
    assert run_record["execution_summary"] == summary["execution_summary"]
    assert run_record["evidence_map"] == summary["evidence_map"]
    assert run_record["quality_gate"] == summary["quality_gate"]
    assert run_record["quality_gate"]["human_approval"]["merge_approved"] is False
    assert run_record["post_approval_action"]["status"] == "approval_required"
    assert run_record["post_approval_action"]["can_continue"] is False
    latest_summary = read_yaml(tmp_path, "workspace/tasks/workflow-004/final/decision_summary.yaml")
    assert latest_summary["run_record_artifact"] == summary["run_record_artifact"]


def test_run_end_to_end_uses_previous_run_record_as_decision_input(tmp_path: Path) -> None:
    write_end_to_end_config(tmp_path)
    write_validation_goal(tmp_path)
    previous_record_path = "workspace/tasks/workflow-013/runs/workflow-013-run.yaml"
    write_yaml(
        tmp_path,
        previous_record_path,
        {
            "task_id": "workflow-013",
            "run_metadata": {"run_id": "workflow-013-run"},
            "remaining_work": [
                "feedback-002: 把下一轮优化任务接入调度执行",
                "dispatch-002: 支持更多本地 Agent 调度",
            ],
            "next_recommended_action": {
                "task_id": "workflow-014",
                "title": "端到端闭环持续优化",
                "priority": "medium",
            },
            "quality_gate": {"status": "approved"},
            "post_approval_action": {"status": "allowed"},
            "evidence_map": [
                {
                    "decision": "goal_effect_aligned",
                    "status": "passed",
                    "evidence": ["goal.json"],
                    "notes": "alignment_score=1.0",
                },
                {
                    "decision": "next_action",
                    "status": "medium",
                    "evidence": ["next.yaml"],
                    "notes": "workflow-014",
                },
            ],
        },
    )

    summary = run_end_to_end(
        tmp_path,
        task_id="workflow-014",
        run_id="workflow-014-run",
        previous_run_record=previous_record_path,
    )

    assert summary["previous_run_context"]["source_run_record"] == previous_record_path
    assert summary["previous_run_context"]["evidence_decisions"] == [
        "goal_effect_aligned",
        "next_action",
    ]
    assert summary["previous_run_context"]["remaining_work_count"] == 2
    assert summary["current_result"]["previous_run_context_artifact"] == (
        "workspace/tasks/workflow-014/input/previous_run_context.yaml"
    )
    persisted_context = read_yaml(tmp_path, summary["current_result"]["previous_run_context_artifact"])
    assert persisted_context == summary["previous_run_context"]
    final_plan = read_yaml(tmp_path, "workspace/tasks/workflow-014/final/final_next_optimization_tasks.yaml")
    assert final_plan["task_batch"]["previous_run_record"] == previous_record_path
    assert final_plan["task_batch"]["previous_evidence_decisions"] == [
        "goal_effect_aligned",
        "next_action",
    ]


def test_run_end_to_end_recommends_unvalidated_previous_remaining_work(tmp_path: Path) -> None:
    write_end_to_end_config(tmp_path)
    write_validation_goal(tmp_path)
    previous_record_path = "workspace/tasks/workflow-014/runs/workflow-014-run.yaml"
    write_yaml(
        tmp_path,
        previous_record_path,
        {
            "task_id": "workflow-014",
            "run_metadata": {"run_id": "workflow-014-run"},
            "remaining_work": [
                "feedback-002: 把下一轮优化任务接入调度执行",
                "dispatch-002: 支持更多本地 Agent 调度",
                "ui-validation-001: 增加目标效果图的自动检查",
            ],
            "quality_gate": {"status": "approved"},
            "post_approval_action": {"status": "allowed"},
            "evidence_map": [
                {
                    "decision": "dispatch_validated",
                    "status": "waiting_for_human_merge_approval",
                    "evidence": ["dispatch.json"],
                    "notes": "completed=3; skipped=0",
                }
            ],
        },
    )

    summary = run_end_to_end(
        tmp_path,
        task_id="workflow-015",
        run_id="workflow-015-run",
        previous_run_record=previous_record_path,
    )

    assert summary["next_recommended_action"]["task_id"] == "workflow-016"
    assert summary["next_recommended_action"]["source_task_id"] == "ui-validation-001"
    assert "ui-validation-001" in summary["next_recommended_action"]["reason"]
    basis = summary["recommendation_basis"]
    assert basis["strategy"] == "previous_run_context"
    assert basis["selected_source_task_id"] == "ui-validation-001"
    assert basis["completed_this_run_task_ids"] == [
        "feedback-002",
        "dispatch-002",
    ]
    assert basis["deprioritized_task_ids"] == [
        "feedback-002",
        "dispatch-002",
    ]
    saved = read_yaml(tmp_path, "workspace/tasks/workflow-015/final/decision_summary.yaml")
    assert saved["recommendation_basis"] == basis


def test_run_end_to_end_deprioritizes_completed_previous_source_task(tmp_path: Path) -> None:
    write_end_to_end_config(tmp_path)
    write_validation_goal(tmp_path)
    previous_record_path = "workspace/tasks/workflow-018/runs/workflow-018-run.yaml"
    write_yaml(
        tmp_path,
        previous_record_path,
        {
            "task_id": "workflow-018",
            "run_metadata": {"run_id": "workflow-018-run"},
            "remaining_work": [
                "feedback-002: 把下一轮优化任务接入调度执行",
                "dispatch-002: 支持更多本地 Agent 调度",
                "ui-validation-001: 增加目标效果图的自动检查",
            ],
            "next_recommended_action": {
                "task_id": "workflow-019",
                "title": "增加目标效果图的自动检查",
                "priority": "medium",
                "source_task_id": "ui-validation-001",
            },
            "target_effect_report": {
                "artifact": "workspace/tasks/workflow-018/final/target_effect_report.md",
                "status": "passed",
                "render_check_count": 3,
                "passed_render_check_count": 3,
                "blocking_issue_count": 0,
            },
            "quality_gate": {"status": "approved"},
            "post_approval_action": {"status": "allowed"},
            "evidence_map": [
                {
                    "decision": "goal_effect_aligned",
                    "status": "passed",
                    "evidence": [
                        "workspace/tasks/workflow-018/final/target_effect_report.md"
                    ],
                    "notes": "alignment_score=1.0; blocking_issues=0",
                }
            ],
        },
    )

    summary = run_end_to_end(
        tmp_path,
        task_id="workflow-019",
        run_id="workflow-019-run",
        previous_run_record=previous_record_path,
    )

    assert summary["previous_run_context"]["completed_source_task_ids"] == ["ui-validation-001"]
    assert summary["recommendation_basis"]["completed_previous_source_task_ids"] == [
        "ui-validation-001"
    ]
    assert summary["recommendation_basis"]["selected_source_task_id"] == "roadmap-001"
    assert summary["next_recommended_action"]["source_task_id"] == "roadmap-001"
    assert summary["remaining_work"][0] == "roadmap-001: 持续优化路线图产品化"
    assert "roadmap-001" in summary["next_recommended_action"]["reason"]


def test_completed_template_task_ids_handles_new_id_suffixes() -> None:
    events = [
        {
            "artifacts": [
                "workspace/tasks/workflow-019-feedback-002-2/final/validation_feedback.json",
                "workspace/tasks/workflow-019-dispatch-002-2/final/validation_feedback.json",
            ]
        }
    ]

    completed = _completed_template_task_ids(
        "workflow-019",
        events,
        ["feedback-002", "dispatch-002", "ui-validation-001"],
    )

    assert completed == ["feedback-002", "dispatch-002"]


def test_run_end_to_end_carries_completed_tasks_after_remaining_work_converges(tmp_path: Path) -> None:
    write_end_to_end_config(tmp_path)
    write_validation_goal(tmp_path)
    previous_record_path = "workspace/tasks/workflow-019/runs/workflow-019-run.yaml"
    write_yaml(
        tmp_path,
        previous_record_path,
        {
            "task_id": "workflow-019",
            "run_metadata": {"run_id": "workflow-019-run"},
            "remaining_work": ["暂无未完成的自动生成任务。"],
            "recommendation_basis": {
                "completed_this_run_task_ids": [
                    "ui-validation-001",
                    "feedback-002",
                    "dispatch-002",
                ],
                "remaining_open_task_ids": [],
                "selected_source_task_id": None,
            },
            "next_recommended_action": {
                "task_id": "workflow-020",
                "title": "端到端闭环持续优化",
                "priority": "medium",
            },
            "target_effect_report": {
                "artifact": "workspace/tasks/workflow-019/final/target_effect_report.md",
                "status": "passed",
                "blocking_issue_count": 0,
            },
            "quality_gate": {"status": "approved"},
            "post_approval_action": {"status": "allowed"},
            "evidence_map": [
                {
                    "decision": "goal_effect_aligned",
                    "status": "passed",
                    "evidence": ["workspace/tasks/workflow-019/final/target_effect_report.md"],
                    "notes": "alignment_score=1.0; blocking_issues=0",
                }
            ],
        },
    )

    summary = run_end_to_end(
        tmp_path,
        task_id="workflow-020",
        run_id="workflow-020-run",
        previous_run_record=previous_record_path,
    )

    assert summary["previous_run_context"]["completed_source_task_ids"] == [
        "ui-validation-001",
        "feedback-002",
        "dispatch-002",
    ]
    assert summary["recommendation_basis"]["selected_source_task_id"] == "roadmap-001"
    assert summary["remaining_work"][0] == "roadmap-001: 持续优化路线图产品化"
    assert summary["next_recommended_action"]["task_id"] == "workflow-021"
    assert summary["next_recommended_action"]["source_task_id"] == "roadmap-001"


def test_quality_gate_blocks_missing_required_evidence() -> None:
    summary = {
        "execution_summary": {"failed": []},
        "retry_plan": {"status": "not_required"},
        "evidence_map": [
            {"decision": "goal_effect_aligned", "status": "passed", "evidence": ["goal.json"]},
            {"decision": "tests_passed", "status": "passed", "evidence": []},
            {"decision": "dispatch_validated", "status": "passed", "evidence": ["dispatch.json"]},
            {"decision": "code_review_passed", "status": "passed", "evidence": ["review.json"]},
            {"decision": "next_action", "status": "medium", "evidence": ["next.yaml"]},
        ],
    }

    gate = _quality_gate(summary)

    assert gate["status"] == "blocked"
    assert gate["can_continue"] is False
    assert gate["blocking_issues"][0]["id"] == "missing_evidence_tests_passed"


def test_quality_gate_can_warn_on_missing_evidence() -> None:
    summary = {
        "execution_summary": {"failed": []},
        "retry_plan": {"status": "not_required"},
        "evidence_map": [
            {"decision": "tests_passed", "status": "passed", "evidence": []},
        ],
    }

    gate = _quality_gate(
        summary,
        {
            "required_evidence": ["tests_passed"],
            "missing_evidence": "warning",
            "failed_evidence": "blocking",
            "human_approval_required": True,
        },
    )

    assert gate["status"] == "waiting_for_human_approval"
    assert gate["blocking_issues"] == []
    assert gate["warnings"][0]["id"] == "missing_evidence_tests_passed"


def test_quality_gate_config_reads_pipeline_yaml(tmp_path: Path) -> None:
    write_yaml(
        tmp_path,
        "config/pipeline.yaml",
        {
            "quality_gate": {
                "required_evidence": ["tests_passed"],
                "missing_evidence": "warning",
                "failed_evidence": "blocking",
                "human_approval_required": False,
            }
        },
    )

    assert _quality_gate_config(tmp_path) == {
        "required_evidence": ["tests_passed"],
        "missing_evidence": "warning",
        "failed_evidence": "blocking",
        "human_approval_required": False,
    }


def test_post_approval_action_controls_continue_permission() -> None:
    pending = {
        "task_id": "workflow-008",
        "quality_gate": {
            "status": "waiting_for_human_approval",
            "can_continue": False,
        },
    }
    approved = {
        "task_id": "workflow-008",
        "quality_gate": {
            "status": "approved",
            "can_continue": True,
        },
        "approval_record": {"decision": "approved", "comment": "同意继续。"},
    }
    rejected = {
        "task_id": "workflow-008",
        "quality_gate": {
            "status": "rejected",
            "can_continue": False,
        },
        "approval_record": {"decision": "rejected", "comment": "证据不足。"},
    }

    assert _post_approval_action(pending) == {
        "status": "approval_required",
        "can_continue": False,
        "allowed_actions": ["view_run_record", "approve_run"],
        "blocked_actions": ["continue_next_stage"],
        "recommended_action": "补充人工审批记录后再决定是否继续。",
        "reason": "当前运行尚未获得人工审批。",
    }
    assert _post_approval_action(approved)["status"] == "allowed"
    assert _post_approval_action(approved)["can_continue"] is True
    rejected_action = _post_approval_action(rejected)
    assert rejected_action["status"] == "blocked"
    assert rejected_action["can_continue"] is False
    assert rejected_action["blocked_actions"] == ["continue_next_stage"]
    assert "证据不足" in rejected_action["reason"]


def test_run_end_to_end_uses_unique_dispatch_task_ids_on_rerun(tmp_path: Path) -> None:
    write_end_to_end_config(tmp_path)
    write_validation_goal(tmp_path)

    first = run_end_to_end(tmp_path)
    second = run_end_to_end(tmp_path)

    assert first["current_result"]["dispatch_state"]["status"] == "waiting_for_human_merge_approval"
    assert second["current_result"]["dispatch_state"]["status"] == "waiting_for_human_merge_approval"
    dispatch_tasks = read_yaml(tmp_path, "workspace/tasks/workflow-001/input/dispatch_tasks.yaml")
    assert any(task["id"].endswith("-2") for task in dispatch_tasks["tasks"])


def test_run_end_to_end_dry_run_does_not_write_artifacts(tmp_path: Path) -> None:
    write_end_to_end_config(tmp_path)
    write_validation_goal(tmp_path)

    summary = run_end_to_end(tmp_path, dry_run=True, run_id="dry-run-001")

    assert summary["status"] == "dry_run"
    assert summary["run_metadata"]["run_id"] == "dry-run-001"
    assert summary["run_strategy"] == {"dry_run": True, "rerun_policy": "new_ids"}
    assert summary["execution_summary"]["next"]
    assert summary["evidence_map"][0]["decision"] == "dry_run_plan"
    assert not (tmp_path / "workspace/tasks/workflow-001/final/decision_summary.yaml").exists()
    assert not (tmp_path / "workspace/tasks/workflow-001/state.json").exists()


def test_run_end_to_end_skip_completed_reuses_existing_subworkflows(tmp_path: Path) -> None:
    write_end_to_end_config(tmp_path)
    write_validation_goal(tmp_path)

    first = run_end_to_end(tmp_path)
    second = run_end_to_end(tmp_path, rerun_policy="skip_completed")

    assert first["execution_summary"]["completed"]
    assert len(second["execution_summary"]["skipped"]) == 3
    assert second["execution_summary"]["completed"] == []
    dispatch_tasks = read_yaml(tmp_path, "workspace/tasks/workflow-001/input/dispatch_tasks.yaml")
    assert all(not task["id"].endswith("-2") for task in dispatch_tasks["tasks"])


def test_run_end_to_end_outputs_retry_plan_when_a_stage_fails(tmp_path: Path) -> None:
    write_end_to_end_config(
        tmp_path,
        validation_command=[sys.executable, "-c", "raise SystemExit(1)"],
    )
    write_validation_goal(tmp_path)

    summary = run_end_to_end(tmp_path)

    assert summary["execution_summary"]["failed"][0]["step"] == "validation"
    assert summary["retry_plan"]["status"] == "retry_required"
    assert summary["retry_plan"]["failed_step"] == "validation"
    assert summary["retry_plan"]["recommended_command"] == (
        "python scripts/run_end_to_end.py --rerun-policy skip_completed"
    )
    retry_evidence = [item for item in summary["evidence_map"] if item["decision"] == "retry_required"]
    assert retry_evidence[0]["status"] == "retry_required"


def test_format_end_to_end_summary_is_human_readable() -> None:
    summary = {
        "status": "ready_for_human_decision",
        "run_metadata": {"run_id": "summary-run", "started_at": "2026-05-31T00:00:00Z"},
        "run_strategy": {"rerun_policy": "skip_completed"},
        "goal_effect": {
            "validation_status": "passed",
            "alignment_score": 1.0,
            "blocking_issues": [],
        },
        "current_result": {
            "dispatch_state": {"status": "waiting_for_human_merge_approval"},
            "review_state": {"status": "waiting_for_human_merge_approval"},
            "initial_plan_artifact": "workspace/tasks/workflow-001/final/initial_next_optimization_tasks.yaml",
            "dispatch_tasks_artifact": "workspace/tasks/workflow-001/input/dispatch_tasks.yaml",
            "final_plan_artifact": "workspace/tasks/workflow-001/final/final_next_optimization_tasks.yaml",
        },
        "target_effect_report": {
            "artifact": "workspace/tasks/workflow-001/final/target_effect_report.md",
            "status": "passed",
        },
        "next_recommended_action": {
            "task_id": "workflow-002",
            "title": "Next workflow task",
            "priority": "medium",
            "reason": "来自端到端反馈闭环生成的下一轮优化任务。",
        },
        "execution_summary": {
            "completed": [{"step": "validation"}],
            "skipped": [{"step": "dispatch"}],
            "failed": [],
        },
        "retry_plan": {"status": "not_required"},
        "quality_gate": {"status": "waiting_for_human_approval", "warnings": [{"id": "warning"}]},
        "post_approval_action": {
            "status": "approval_required",
            "can_continue": False,
            "recommended_action": "补充人工审批记录后再决定是否继续。",
        },
        "evidence_map": [
            {
                "decision": "goal_effect_aligned",
                "status": "passed",
                "evidence": ["workspace/tasks/workflow-001/final/validation_feedback.json"],
            }
        ],
    }

    output = format_end_to_end_summary(summary)

    assert "AI Dev Pipeline End-to-End Summary" in output
    assert "Run id: summary-run" in output
    assert "Rerun policy: skip_completed" in output
    assert "- Completed:" in output
    assert "- Skipped:" in output
    assert "Evidence:" in output
    assert "Quality gate: waiting_for_human_approval" in output
    assert "Quality warnings: 1" in output
    assert "Post approval action: approval_required" in output
    assert "Can continue: False" in output
    assert "Dispatch state: waiting_for_human_merge_approval" in output
    assert "Target effect report: workspace/tasks/workflow-001/final/target_effect_report.md" in output
    assert "workflow-002: Next workflow task" in output


def test_run_end_to_end_cli_json_output(tmp_path: Path, capsys) -> None:
    write_end_to_end_config(tmp_path)
    write_validation_goal(tmp_path)

    old_argv = sys.argv
    sys.argv = [
        "run_end_to_end.py",
        "--repo-root",
        str(tmp_path),
        "--rerun-policy",
        "skip_completed",
        "--run-id",
        "cli-run",
        "--json",
    ]
    try:
        exit_code = main()
    finally:
        sys.argv = old_argv

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["task_id"] == "workflow-001"
    assert output["run_metadata"]["run_id"] == "cli-run"
    assert output["run_strategy"]["rerun_policy"] == "skip_completed"


def test_run_end_to_end_cli_accepts_previous_run_record(tmp_path: Path, capsys) -> None:
    write_end_to_end_config(tmp_path)
    write_validation_goal(tmp_path)
    previous_record_path = "workspace/tasks/workflow-013/runs/workflow-013-run.yaml"
    write_yaml(
        tmp_path,
        previous_record_path,
        {
            "task_id": "workflow-013",
            "run_metadata": {"run_id": "workflow-013-run"},
            "evidence_map": [
                {"decision": "next_action", "status": "medium", "evidence": ["next.yaml"]}
            ],
            "remaining_work": ["feedback-002: 把下一轮优化任务接入调度执行"],
            "quality_gate": {"status": "approved"},
            "post_approval_action": {"status": "allowed"},
        },
    )

    old_argv = sys.argv
    sys.argv = [
        "run_end_to_end.py",
        "--repo-root",
        str(tmp_path),
        "--task-id",
        "workflow-014",
        "--run-id",
        "cli-previous-run",
        "--previous-run-record",
        previous_record_path,
        "--json",
    ]
    try:
        exit_code = main()
    finally:
        sys.argv = old_argv

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["previous_run_context"]["source_run_record"] == previous_record_path
    assert output["current_result"]["previous_run_context_artifact"] == (
        "workspace/tasks/workflow-014/input/previous_run_context.yaml"
    )


def test_run_end_to_end_cli_lists_run_records(tmp_path: Path, capsys) -> None:
    write_end_to_end_config(tmp_path)
    write_validation_goal(tmp_path)
    run_end_to_end(tmp_path, task_id="workflow-004", run_id="list-run-001")

    old_argv = sys.argv
    sys.argv = [
        "run_end_to_end.py",
        "--repo-root",
        str(tmp_path),
        "--task-id",
        "workflow-004",
        "--list-runs",
        "--json",
    ]
    try:
        exit_code = main()
    finally:
        sys.argv = old_argv

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output[0]["run_id"] == "list-run-001"
    assert output[0]["artifact"] == "workspace/tasks/workflow-004/runs/list-run-001.yaml"


def test_approve_run_record_updates_run_and_latest_summary(tmp_path: Path) -> None:
    write_end_to_end_config(tmp_path)
    write_validation_goal(tmp_path)
    run_end_to_end(tmp_path, task_id="workflow-007", run_id="approval-run-001")

    updated = approve_run_record(
        tmp_path,
        task_id="workflow-007",
        run_id="approval-run-001",
        approver="dennis",
        decision="approved",
        comment="同意继续。",
        decided_at="2026-06-01T00:00:00Z",
    )

    approval = updated["approval_record"]
    assert approval == {
        "approver": "dennis",
        "decision": "approved",
        "comment": "同意继续。",
        "decided_at": "2026-06-01T00:00:00Z",
    }
    assert updated["quality_gate"]["status"] == "approved"
    assert updated["quality_gate"]["can_continue"] is True
    assert updated["quality_gate"]["human_approval"]["merge_approved"] is True
    assert updated["post_approval_action"]["status"] == "allowed"
    assert updated["post_approval_action"]["can_continue"] is True
    latest = read_yaml(tmp_path, "workspace/tasks/workflow-007/final/decision_summary.yaml")
    assert latest["approval_record"] == approval
    assert latest["post_approval_action"] == updated["post_approval_action"]
    state = load_state(tmp_path, "workflow-007")
    assert state.status == "completed"
    assert state.step == "post_approval_action"
    assert state.gates["human_merge_approved"] is True


def test_run_end_to_end_cli_approves_run_record(tmp_path: Path, capsys) -> None:
    write_end_to_end_config(tmp_path)
    write_validation_goal(tmp_path)
    run_end_to_end(tmp_path, task_id="workflow-007", run_id="cli-approval-run")

    old_argv = sys.argv
    sys.argv = [
        "run_end_to_end.py",
        "--repo-root",
        str(tmp_path),
        "--task-id",
        "workflow-007",
        "--approve-run",
        "cli-approval-run",
        "--approver",
        "dennis",
        "--decision",
        "rejected",
        "--comment",
        "证据不足。",
        "--decided-at",
        "2026-06-01T00:00:00Z",
        "--json",
    ]
    try:
        exit_code = main()
    finally:
        sys.argv = old_argv

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["approval_record"]["decision"] == "rejected"
    assert output["quality_gate"]["status"] == "rejected"
    assert output["quality_gate"]["can_continue"] is False
    assert output["post_approval_action"]["status"] == "blocked"
    assert output["post_approval_action"]["can_continue"] is False
    state = load_state(tmp_path, "workflow-007")
    assert state.status == "blocked_by_human_approval"
    assert state.gates["human_merge_approved"] is False


def test_continue_run_record_allows_approved_run(tmp_path: Path) -> None:
    write_end_to_end_config(tmp_path)
    write_validation_goal(tmp_path)
    run_end_to_end(tmp_path, task_id="workflow-008", run_id="continue-approved-run")
    approve_run_record(
        tmp_path,
        task_id="workflow-008",
        run_id="continue-approved-run",
        approver="dennis",
        decision="approved",
        comment="同意继续。",
        decided_at="2026-06-01T00:00:00Z",
    )

    result = continue_run_record(tmp_path, task_id="workflow-008", run_id="continue-approved-run")

    assert result["status"] == "allowed"
    assert result["can_continue"] is True
    next_task_id = result["next_recommended_action"]["task_id"]
    assert next_task_id
    assert result["recommended_command"] == (
        f"python scripts/run_end_to_end.py --task-id {next_task_id} --rerun-policy skip_completed"
    )


def test_continue_run_record_blocks_rejected_or_pending_runs(tmp_path: Path) -> None:
    write_end_to_end_config(tmp_path)
    write_validation_goal(tmp_path)
    run_end_to_end(tmp_path, task_id="workflow-008", run_id="continue-pending-run")
    run_end_to_end(tmp_path, task_id="workflow-008", run_id="continue-rejected-run")
    approve_run_record(
        tmp_path,
        task_id="workflow-008",
        run_id="continue-rejected-run",
        approver="dennis",
        decision="rejected",
        comment="证据不足。",
        decided_at="2026-06-01T00:00:00Z",
    )

    pending = continue_run_record(tmp_path, task_id="workflow-008", run_id="continue-pending-run")
    rejected = continue_run_record(tmp_path, task_id="workflow-008", run_id="continue-rejected-run")

    assert pending["status"] == "blocked"
    assert pending["can_continue"] is False
    assert pending["post_approval_action_status"] == "approval_required"
    assert "补充人工审批记录" in pending["recommended_action"]
    assert rejected["status"] == "blocked"
    assert rejected["can_continue"] is False
    assert rejected["post_approval_action_status"] == "blocked"
    assert "证据不足" in rejected["reason"]


def test_continue_run_record_blocks_dry_run_record(tmp_path: Path) -> None:
    summary = run_end_to_end(
        tmp_path,
        task_id="workflow-008",
        dry_run=True,
        run_id="continue-dry-run",
    )
    write_yaml(tmp_path, "workspace/tasks/workflow-008/runs/continue-dry-run.yaml", summary)

    result = continue_run_record(tmp_path, task_id="workflow-008", run_id="continue-dry-run")

    assert result["status"] == "blocked"
    assert result["can_continue"] is False
    assert result["post_approval_action_status"] == "not_applicable"
    assert "正式运行端到端闭环" in result["recommended_action"]


def test_run_end_to_end_cli_continue_run_returns_status_code(tmp_path: Path, capsys) -> None:
    write_end_to_end_config(tmp_path)
    write_validation_goal(tmp_path)
    run_end_to_end(tmp_path, task_id="workflow-008", run_id="cli-continue-run")
    approve_run_record(
        tmp_path,
        task_id="workflow-008",
        run_id="cli-continue-run",
        approver="dennis",
        decision="approved",
        comment="同意继续。",
        decided_at="2026-06-01T00:00:00Z",
    )

    old_argv = sys.argv
    sys.argv = [
        "run_end_to_end.py",
        "--repo-root",
        str(tmp_path),
        "--task-id",
        "workflow-008",
        "--continue-run",
        "cli-continue-run",
        "--json",
    ]
    try:
        exit_code = main()
    finally:
        sys.argv = old_argv

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "allowed"
    assert output["can_continue"] is True
    assert output["next_recommended_action"]["task_id"]


def test_format_continue_result_is_human_readable() -> None:
    output = format_continue_result(
        {
            "status": "allowed",
            "run_id": "continue-run",
            "can_continue": True,
            "post_approval_action_status": "allowed",
            "reason": "人工审批已通过。",
            "recommended_action": "继续执行下一阶段任务。",
            "next_recommended_action": {
                "task_id": "workflow-010",
                "title": "端到端闭环持续优化",
                "priority": "medium",
            },
            "recommended_command": (
                "python scripts/run_end_to_end.py --task-id workflow-010 --rerun-policy skip_completed"
            ),
        }
    )

    assert "AI Dev Pipeline Continue Check" in output
    assert "Status: allowed" in output
    assert "Can continue: True" in output
    assert "workflow-010: 端到端闭环持续优化" in output
    assert "python scripts/run_end_to_end.py --task-id workflow-010 --rerun-policy skip_completed" in output


def test_fallback_recommended_task_uses_known_workflow_titles() -> None:
    assert _fallback_recommended_task("workflow-003") == {
        "id": "workflow-004",
        "title": "端到端闭环决策产物可追溯化",
        "priority": "medium",
    }
    assert _fallback_recommended_task("workflow-004") == {
        "id": "workflow-005",
        "title": "端到端闭环运行记录质量门",
        "priority": "medium",
    }
    assert _fallback_recommended_task("workflow-005") == {
        "id": "workflow-006",
        "title": "端到端闭环质量门配置化",
        "priority": "medium",
    }
    assert _fallback_recommended_task("workflow-006") == {
        "id": "workflow-007",
        "title": "端到端闭环人工审批记录",
        "priority": "medium",
    }
    assert _fallback_recommended_task("workflow-007") == {
        "id": "workflow-008",
        "title": "端到端闭环审批后动作控制",
        "priority": "medium",
    }
    assert _fallback_recommended_task("workflow-008") == {
        "id": "workflow-009",
        "title": "端到端闭环任务推进命令",
        "priority": "medium",
    }
