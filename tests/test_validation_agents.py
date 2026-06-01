from __future__ import annotations

import sys
from pathlib import Path

from agents import CodeReviewerAgent, GoalEffectValidatorAgent, TestValidatorAgent
from artifacts import write_json, write_yaml


def test_test_validator_agent_runs_command_successfully(tmp_path: Path) -> None:
    result = TestValidatorAgent().run(
        {
            "repo_root": str(tmp_path),
            "commands": [[sys.executable, "-c", "print('ok')"]],
        }
    )

    assert result.output["passed"] is True
    assert result.output["status"] == "passed"
    assert "ok" in result.output["results"][0]["stdout"]


def test_test_validator_agent_reports_failed_command(tmp_path: Path) -> None:
    result = TestValidatorAgent().run(
        {
            "repo_root": str(tmp_path),
            "commands": [[sys.executable, "-c", "raise SystemExit(2)"]],
        }
    )

    assert result.output["passed"] is False
    assert result.output["status"] == "failed"
    assert result.output["results"][0]["returncode"] == 2


def test_code_reviewer_agent_passes_when_tests_and_state_exist(tmp_path: Path) -> None:
    write_json(tmp_path, "workspace/tasks/validation-001/review/test_validation.json", {"passed": True})
    write_json(tmp_path, "workspace/tasks/validation-001/state.json", {"task_id": "validation-001"})

    result = CodeReviewerAgent().run({"repo_root": str(tmp_path), "task_id": "validation-001"})

    assert result.output["status"] == "passed"
    assert result.output["blocking_issues"] == []
    assert result.output["artifact_consistency"]["missing"] == []


def test_code_reviewer_agent_blocks_when_tests_fail(tmp_path: Path) -> None:
    write_json(tmp_path, "workspace/tasks/validation-001/review/test_validation.json", {"passed": False})
    write_json(tmp_path, "workspace/tasks/validation-001/state.json", {"task_id": "validation-001"})

    result = CodeReviewerAgent().run({"repo_root": str(tmp_path), "task_id": "validation-001"})

    assert result.output["status"] == "blocked"
    assert result.output["blocking_issues"][0]["id"] == "tests_passed"


def test_code_reviewer_agent_blocks_missing_state_artifact_path(tmp_path: Path) -> None:
    write_json(tmp_path, "workspace/tasks/opt-001/review/test_validation.json", {"passed": True})
    write_json(
        tmp_path,
        "workspace/tasks/opt-001/state.json",
        {
            "task_id": "opt-001",
            "artifacts": ["workspace/tasks/opt-001/final/missing.yaml"],
        },
    )

    result = CodeReviewerAgent().run({"repo_root": str(tmp_path), "task_id": "opt-001"})

    assert result.output["status"] == "blocked"
    assert result.output["blocking_issues"][0]["id"] == "state_artifacts_exist"
    assert result.output["artifact_consistency"]["missing"] == [
        "workspace/tasks/opt-001/final/missing.yaml"
    ]


def test_code_reviewer_agent_reports_acceptance_coverage(tmp_path: Path) -> None:
    write_json(tmp_path, "workspace/tasks/opt-001/review/test_validation.json", {"passed": True})
    write_json(
        tmp_path,
        "workspace/tasks/opt-001/state.json",
        {
            "task_id": "opt-001",
            "artifacts": ["workspace/tasks/opt-001/review/acceptance_check.json"],
        },
    )
    write_json(
        tmp_path,
        "workspace/tasks/opt-001/review/acceptance_check.json",
        {
            "checks": [
                {
                    "name": "coverage",
                    "evidence": "代码评审报告包含验收标准覆盖情况。",
                }
            ]
        },
    )
    write_yaml(
        tmp_path,
        "workspace/tasks/optimization-001/final/next_optimization_tasks.yaml",
        {
            "tasks": [
                {
                    "id": "opt-001",
                    "acceptance_criteria": [
                        "代码评审报告包含验收标准覆盖情况。",
                        "缺少 evidence 时产生 blocking issue 或 non-blocking recommendation。",
                    ],
                }
            ]
        },
    )

    result = CodeReviewerAgent().run({"repo_root": str(tmp_path), "task_id": "opt-001"})

    assert result.output["status"] == "passed"
    assert result.output["acceptance_coverage"]["covered"] == [
        "代码评审报告包含验收标准覆盖情况。"
    ]
    assert result.output["acceptance_coverage"]["missing_evidence"] == [
        "缺少 evidence 时产生 blocking issue 或 non-blocking recommendation。"
    ]
    assert result.output["acceptance_coverage"]["acceptance_evidence_map"] == [
        {
            "criterion": "代码评审报告包含验收标准覆盖情况。",
            "status": "matched",
            "matched_evidence": [
                {
                    "path": "workspace/tasks/opt-001/review/acceptance_check.json",
                    "match": "exact_text",
                }
            ],
            "missing_evidence": [],
            "recommendation": "",
        },
        {
            "criterion": "缺少 evidence 时产生 blocking issue 或 non-blocking recommendation。",
            "status": "missing",
            "matched_evidence": [],
            "missing_evidence": [
                "缺少 evidence 时产生 blocking issue 或 non-blocking recommendation。"
            ],
            "recommendation": "在 acceptance_check.json、implementation_summary.yaml 或相关产物中补充该验收标准的明确 evidence。",
        },
    ]
    assert result.output["non_blocking_issues"][0]["id"] == "acceptance_criteria_evidence"


def test_goal_effect_validator_agent_outputs_feedback(tmp_path: Path) -> None:
    write_yaml(
        tmp_path,
        "workspace/tasks/validation-001/input/validation_goal.yaml",
        {
            "goal": "自动化验证闭环可运行。",
            "required_artifacts": ["agents/base_agent.py"],
            "expected_effects": {
                "tests_pass": True,
                "code_review_passes": True,
            },
        },
    )
    (tmp_path / "agents").mkdir()
    (tmp_path / "agents/base_agent.py").write_text("# ok\n", encoding="utf-8")
    write_json(tmp_path, "workspace/tasks/validation-001/review/test_validation.json", {"passed": True})
    write_json(tmp_path, "workspace/tasks/validation-001/review/code_review.json", {"blocking_issues": []})

    result = GoalEffectValidatorAgent().run(
        {"repo_root": str(tmp_path), "task_id": "validation-001"}
    )

    assert result.output["status"] == "passed"
    assert result.output["alignment_score"] == 1.0
    assert result.output["feedback"] == ["目标对齐和效果验证通过，可以进入人工合并门。"]
    assert result.output["target_effect_mappings"] == []
    assert result.output["demo_effect_checks"] == []
    assert result.output["demo_visual_checks"] == []


def test_goal_effect_validator_agent_blocks_missing_effect(tmp_path: Path) -> None:
    write_yaml(
        tmp_path,
        "workspace/tasks/validation-001/input/validation_goal.yaml",
        {
            "goal": "自动化验证闭环可运行。",
            "required_artifacts": ["missing.py"],
            "expected_effects": {"tests_pass": True},
        },
    )

    result = GoalEffectValidatorAgent().run(
        {"repo_root": str(tmp_path), "task_id": "validation-001"}
    )

    assert result.output["status"] == "blocked"
    assert result.output["blocking_issues"]


def test_goal_effect_validator_agent_checks_target_effect_mappings(tmp_path: Path) -> None:
    write_yaml(
        tmp_path,
        "workspace/tasks/validation-001/input/validation_goal.yaml",
        {
            "goal": "目标效果映射可验证。",
            "target_effect_mappings": [
                {
                    "id": "human_merge_gate",
                    "demo_effect": "等待人工合并。",
                    "implemented_by": ["run_local_task"],
                    "required_demo_terms": ["等待人工合并"],
                    "required_artifacts": ["scripts/run_local_task.py"],
                    "required_workflows": ["automated_validation"],
                }
            ],
        },
    )
    write_yaml(
        tmp_path,
        "config/pipeline.yaml",
        {"workflows": {"automated_validation": {"steps": []}}},
    )
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/run_local_task.py").write_text("# ok\n", encoding="utf-8")
    (tmp_path / "docs/demos").mkdir(parents=True)
    (tmp_path / "docs/demos/ai_dev_pipeline_demo.html").write_text(
        "<p>等待人工合并</p>",
        encoding="utf-8",
    )

    result = GoalEffectValidatorAgent().run(
        {"repo_root": str(tmp_path), "task_id": "validation-001"}
    )

    assert result.output["status"] == "passed"
    assert result.output["target_effect_mappings"][0]["result"] == "pass"


def test_goal_effect_validator_agent_blocks_missing_target_effect_mapping(
    tmp_path: Path,
) -> None:
    write_yaml(
        tmp_path,
        "workspace/tasks/validation-001/input/validation_goal.yaml",
        {
            "goal": "目标效果映射可验证。",
            "target_effect_mappings": [
                {
                    "id": "missing_mapping",
                    "demo_effect": "缺失能力。",
                    "required_artifacts": ["missing.py"],
                    "required_workflows": ["missing_workflow"],
                    "required_demo_terms": ["missing demo text"],
                }
            ],
        },
    )

    result = GoalEffectValidatorAgent().run(
        {"repo_root": str(tmp_path), "task_id": "validation-001"}
    )

    assert result.output["status"] == "blocked"
    assert result.output["target_effect_mappings"][0]["result"] == "fail"
    assert result.output["blocking_issues"][0]["id"] == "target_effect_mapping:missing_mapping"


def test_goal_effect_validator_agent_checks_demo_effects(tmp_path: Path) -> None:
    write_yaml(
        tmp_path,
        "workspace/tasks/validation-001/input/validation_goal.yaml",
        {
            "goal": "目标效果 demo 可验证。",
            "demo_effect_checks": [
                {
                    "id": "demo_controls",
                    "demo_path": "docs/demos/ai_dev_pipeline_demo.html",
                    "expected_effect": "可运行演示。",
                    "required_terms": ["运行演示", "当前阶段"],
                    "required_selectors": [
                        "#playBtn",
                        "#phaseValue",
                        ".artifact-list",
                        "[data-node=\"ra\"]",
                    ],
                }
            ],
        },
    )
    (tmp_path / "docs/demos").mkdir(parents=True)
    (tmp_path / "docs/demos/ai_dev_pipeline_demo.html").write_text(
        """
        <button id="playBtn">运行演示</button>
        <div id="phaseValue">当前阶段</div>
        <div class="artifact-list"></div>
        <div data-node="ra"></div>
        """,
        encoding="utf-8",
    )

    result = GoalEffectValidatorAgent().run(
        {"repo_root": str(tmp_path), "task_id": "validation-001"}
    )

    assert result.output["status"] == "passed"
    assert result.output["demo_effect_checks"][0]["result"] == "pass"
    assert result.output["demo_effect_checks"][0]["missing"] == {
        "terms": [],
        "selectors": [],
    }


def test_goal_effect_validator_agent_blocks_missing_demo_effects(tmp_path: Path) -> None:
    write_yaml(
        tmp_path,
        "workspace/tasks/validation-001/input/validation_goal.yaml",
        {
            "goal": "目标效果 demo 可验证。",
            "demo_effect_checks": [
                {
                    "id": "demo_controls",
                    "demo_path": "docs/demos/ai_dev_pipeline_demo.html",
                    "expected_effect": "可运行演示。",
                    "required_terms": ["运行演示"],
                    "required_selectors": ["#playBtn", ".missing-card"],
                }
            ],
        },
    )
    (tmp_path / "docs/demos").mkdir(parents=True)
    (tmp_path / "docs/demos/ai_dev_pipeline_demo.html").write_text(
        "<button id=\"playBtn\">Demo</button>",
        encoding="utf-8",
    )

    result = GoalEffectValidatorAgent().run(
        {"repo_root": str(tmp_path), "task_id": "validation-001"}
    )

    assert result.output["status"] == "blocked"
    assert result.output["demo_effect_checks"][0]["result"] == "fail"
    assert result.output["demo_effect_checks"][0]["missing"] == {
        "terms": ["运行演示"],
        "selectors": [".missing-card"],
    }
    assert result.output["blocking_issues"][0]["id"] == "demo_effect_check:demo_controls"


def test_goal_effect_validator_agent_checks_demo_visual_signals(tmp_path: Path) -> None:
    write_yaml(
        tmp_path,
        "workspace/tasks/validation-001/input/validation_goal.yaml",
        {
            "goal": "目标效果视觉信号可验证。",
            "demo_visual_checks": [
                {
                    "id": "demo_visual_contract",
                    "demo_path": "docs/demos/ai_dev_pipeline_demo.html",
                    "expected_effect": "演示页面保留关键视觉布局和交互信号。",
                    "required_css_terms": [
                        "grid-template-columns",
                        "@keyframes pulse",
                        "--ok:",
                    ],
                    "required_script_terms": [
                        "addEventListener('click', play)",
                        "document.querySelectorAll('.node')",
                    ],
                }
            ],
        },
    )
    (tmp_path / "docs/demos").mkdir(parents=True)
    (tmp_path / "docs/demos/ai_dev_pipeline_demo.html").write_text(
        """
        <style>
          :root { --ok: #30e394; }
          .grid { grid-template-columns: 1fr 2fr; }
          @keyframes pulse { from { opacity: .5; } to { opacity: 1; } }
        </style>
        <script>
          const nodes = document.querySelectorAll('.node');
          playBtn.addEventListener('click', play);
        </script>
        """,
        encoding="utf-8",
    )

    result = GoalEffectValidatorAgent().run(
        {"repo_root": str(tmp_path), "task_id": "validation-001"}
    )

    assert result.output["status"] == "passed"
    assert result.output["demo_visual_checks"][0]["result"] == "pass"
    assert result.output["demo_visual_checks"][0]["missing"] == {
        "css_terms": [],
        "script_terms": [],
    }


def test_goal_effect_validator_agent_blocks_missing_demo_visual_signals(tmp_path: Path) -> None:
    write_yaml(
        tmp_path,
        "workspace/tasks/validation-001/input/validation_goal.yaml",
        {
            "goal": "目标效果视觉信号可验证。",
            "demo_visual_checks": [
                {
                    "id": "demo_visual_contract",
                    "demo_path": "docs/demos/ai_dev_pipeline_demo.html",
                    "expected_effect": "演示页面保留关键视觉布局和交互信号。",
                    "required_css_terms": ["grid-template-columns"],
                    "required_script_terms": ["addEventListener('click', play)"],
                }
            ],
        },
    )
    (tmp_path / "docs/demos").mkdir(parents=True)
    (tmp_path / "docs/demos/ai_dev_pipeline_demo.html").write_text(
        "<style>.grid { display: grid; }</style><script>reset();</script>",
        encoding="utf-8",
    )

    result = GoalEffectValidatorAgent().run(
        {"repo_root": str(tmp_path), "task_id": "validation-001"}
    )

    assert result.output["status"] == "blocked"
    assert result.output["demo_visual_checks"][0]["result"] == "fail"
    assert result.output["demo_visual_checks"][0]["missing"] == {
        "css_terms": ["grid-template-columns"],
        "script_terms": ["addEventListener('click', play)"],
    }
    assert result.output["blocking_issues"][0]["id"] == "demo_visual_check:demo_visual_contract"


def write_fake_browser(tmp_path: Path, *, screenshot_bytes: int = 4096, dom: str = "运行演示") -> Path:
    browser = tmp_path / "fake_browser.py"
    browser.write_text(
        f"""#!/usr/bin/env python3
from pathlib import Path
import sys

for arg in sys.argv:
    if arg.startswith("--screenshot="):
        path = Path(arg.split("=", 1)[1])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\\x89PNG\\r\\n\\x1a\\n" + b"0" * {screenshot_bytes})
        raise SystemExit(0)

if "--dump-dom" in sys.argv:
    print({dom!r})
    raise SystemExit(0)

raise SystemExit(0)
""",
        encoding="utf-8",
    )
    browser.chmod(browser.stat().st_mode | 0o111)
    return browser


def test_goal_effect_validator_agent_checks_demo_rendering(tmp_path: Path) -> None:
    browser = write_fake_browser(tmp_path, dom="<html><body>运行演示 当前阶段</body></html>")
    write_yaml(
        tmp_path,
        "workspace/tasks/validation-001/input/validation_goal.yaml",
        {
            "goal": "目标效果本地浏览器渲染可验证。",
            "demo_render_checks": [
                {
                    "id": "demo_render_main",
                    "demo_path": "docs/demos/ai_dev_pipeline_demo.html",
                    "browser_path": str(browser),
                    "screenshot_artifact": "workspace/tasks/validation-001/review/demo_render.png",
                    "viewport": {"width": 960, "height": 640},
                    "min_screenshot_bytes": 128,
                    "required_dom_terms": ["运行演示", "当前阶段"],
                }
            ],
        },
    )
    (tmp_path / "docs/demos").mkdir(parents=True)
    (tmp_path / "docs/demos/ai_dev_pipeline_demo.html").write_text(
        "<html><body>Demo</body></html>",
        encoding="utf-8",
    )

    result = GoalEffectValidatorAgent().run(
        {"repo_root": str(tmp_path), "task_id": "validation-001"}
    )

    render_check = result.output["demo_render_checks"][0]
    assert result.output["status"] == "passed"
    assert render_check["result"] == "pass"
    assert render_check["screenshot_artifact"] == "workspace/tasks/validation-001/review/demo_render.png"
    assert render_check["screenshot_bytes"] >= 128
    assert render_check["missing"] == {"browser": [], "screenshot": [], "dom_terms": []}


def test_goal_effect_validator_agent_blocks_missing_demo_rendering(tmp_path: Path) -> None:
    browser = write_fake_browser(tmp_path, screenshot_bytes=4, dom="<html><body>缺少目标文本</body></html>")
    write_yaml(
        tmp_path,
        "workspace/tasks/validation-001/input/validation_goal.yaml",
        {
            "goal": "目标效果本地浏览器渲染可验证。",
            "demo_render_checks": [
                {
                    "id": "demo_render_main",
                    "demo_path": "docs/demos/ai_dev_pipeline_demo.html",
                    "browser_path": str(browser),
                    "screenshot_artifact": "workspace/tasks/validation-001/review/demo_render.png",
                    "min_screenshot_bytes": 128,
                    "required_dom_terms": ["运行演示"],
                }
            ],
        },
    )
    (tmp_path / "docs/demos").mkdir(parents=True)
    (tmp_path / "docs/demos/ai_dev_pipeline_demo.html").write_text(
        "<html><body>Demo</body></html>",
        encoding="utf-8",
    )

    result = GoalEffectValidatorAgent().run(
        {"repo_root": str(tmp_path), "task_id": "validation-001"}
    )

    render_check = result.output["demo_render_checks"][0]
    assert result.output["status"] == "blocked"
    assert render_check["result"] == "fail"
    assert render_check["missing"]["screenshot"] == ["workspace/tasks/validation-001/review/demo_render.png"]
    assert render_check["missing"]["dom_terms"] == ["运行演示"]
    assert result.output["blocking_issues"][0]["id"] == "demo_render_check:demo_render_main"


def test_goal_effect_validator_agent_blocks_missing_local_browser(tmp_path: Path) -> None:
    write_yaml(
        tmp_path,
        "workspace/tasks/validation-001/input/validation_goal.yaml",
        {
            "goal": "目标效果本地浏览器渲染可验证。",
            "demo_render_checks": [
                {
                    "id": "demo_render_main",
                    "demo_path": "docs/demos/ai_dev_pipeline_demo.html",
                    "browser_path": str(tmp_path / "missing-browser"),
                    "required_dom_terms": ["运行演示"],
                }
            ],
        },
    )

    result = GoalEffectValidatorAgent().run(
        {"repo_root": str(tmp_path), "task_id": "validation-001"}
    )

    assert result.output["status"] == "blocked"
    assert result.output["demo_render_checks"][0]["missing"]["browser"] == ["local_browser"]
