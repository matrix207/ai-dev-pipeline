"""Validate project state against target goals and expected effects."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Mapping

from agents import BaseAgent
from artifacts import read_json, read_yaml


DEFAULT_GOAL_SPEC_PATH = "workspace/tasks/validation-001/input/validation_goal.yaml"


class GoalEffectValidatorAgent(BaseAgent):
    """Compare target goals/effects with local validation artifacts."""

    def __init__(self, name: str = "goal-effect-validator") -> None:
        super().__init__(name)

    def handle(self, payload: dict[str, Any]) -> Mapping[str, Any]:
        repo_root = Path(payload.get("repo_root", "."))
        task_id = payload["task_id"]
        goal_spec_path = payload.get("goal_spec_path", DEFAULT_GOAL_SPEC_PATH)
        goal_spec = read_yaml(repo_root, goal_spec_path)

        checks: list[dict[str, Any]] = []
        feedback: list[str] = []
        blocking_issues: list[dict[str, str]] = []

        for path in goal_spec.get("required_artifacts", []):
            if (repo_root / path).exists():
                checks.append({"name": path, "type": "artifact", "result": "pass"})
            else:
                checks.append({"name": path, "type": "artifact", "result": "fail"})
                blocking_issues.append(
                    {
                        "id": f"missing_artifact:{path}",
                        "severity": "high",
                        "description": f"缺少目标效果要求的产物：{path}",
                        "recommendation": "补齐产物后重新运行自动化验证。",
                    }
                )

        mapping_results = self._check_target_effect_mappings(repo_root, goal_spec, checks, blocking_issues)
        demo_check_results = self._check_demo_effects(repo_root, goal_spec, checks, blocking_issues)
        demo_visual_results = self._check_demo_visuals(repo_root, goal_spec, checks, blocking_issues)
        demo_render_results = self._check_demo_rendering(
            repo_root,
            task_id,
            goal_spec,
            checks,
            blocking_issues,
        )

        validation = self._read_optional_json(
            repo_root,
            f"workspace/tasks/{task_id}/review/test_validation.json",
        )
        code_review = self._read_optional_json(
            repo_root,
            f"workspace/tasks/{task_id}/review/code_review.json",
        )

        expected_effects = goal_spec.get("expected_effects", {})
        if expected_effects.get("tests_pass"):
            self._check_boolean_effect(
                checks,
                blocking_issues,
                "tests_pass",
                validation is not None and validation.get("passed") is True,
                "测试验证必须通过。",
            )
        if expected_effects.get("code_review_passes"):
            self._check_boolean_effect(
                checks,
                blocking_issues,
                "code_review_passes",
                code_review is not None and not code_review.get("blocking_issues"),
                "代码评审不能存在 blocking issues。",
            )

        if blocking_issues:
            feedback.append("先处理 blocking issues，再进入人工合并门。")
        else:
            feedback.append("目标对齐和效果验证通过，可以进入人工合并门。")

        score = self._score(checks)
        return {
            "task_id": task_id,
            "status": "passed" if not blocking_issues else "blocked",
            "goal": goal_spec.get("goal", ""),
            "alignment_score": score,
            "checks": checks,
            "target_effect_mappings": mapping_results,
            "demo_effect_checks": demo_check_results,
            "demo_visual_checks": demo_visual_results,
            "demo_render_checks": demo_render_results,
            "blocking_issues": blocking_issues,
            "feedback": feedback,
        }

    def _read_optional_json(self, repo_root: Path, relative_path: str) -> dict[str, Any] | None:
        try:
            return read_json(repo_root, relative_path)
        except Exception:
            return None

    def _check_boolean_effect(
        self,
        checks: list[dict[str, Any]],
        blocking_issues: list[dict[str, str]],
        name: str,
        passed: bool,
        description: str,
    ) -> None:
        checks.append({"name": name, "type": "effect", "result": "pass" if passed else "fail"})
        if not passed:
            blocking_issues.append(
                {
                    "id": name,
                    "severity": "high",
                    "description": description,
                    "recommendation": "根据验证反馈修复后重新运行自动化验证。",
                }
            )

    def _check_target_effect_mappings(
        self,
        repo_root: Path,
        goal_spec: dict[str, Any],
        checks: list[dict[str, Any]],
        blocking_issues: list[dict[str, str]],
    ) -> list[dict[str, Any]]:
        workflows = self._configured_workflows(repo_root)
        mapping_results = []

        for mapping in goal_spec.get("target_effect_mappings", []):
            missing_artifacts = [
                path for path in mapping.get("required_artifacts", []) if not (repo_root / path).exists()
            ]
            missing_workflows = [
                name for name in mapping.get("required_workflows", []) if name not in workflows
            ]
            missing_terms = [
                term
                for term in mapping.get("required_demo_terms", [])
                if not self._demo_contains(repo_root, term)
            ]
            missing = {
                "artifacts": missing_artifacts,
                "workflows": missing_workflows,
                "demo_terms": missing_terms,
            }
            passed = not any(missing.values())
            result = {
                "id": mapping["id"],
                "demo_effect": mapping.get("demo_effect", ""),
                "implemented_by": mapping.get("implemented_by", []),
                "result": "pass" if passed else "fail",
                "missing": missing,
            }
            mapping_results.append(result)
            checks.append(
                {
                    "name": mapping["id"],
                    "type": "target_effect_mapping",
                    "result": result["result"],
                }
            )
            if not passed:
                blocking_issues.append(
                    {
                        "id": f"target_effect_mapping:{mapping['id']}",
                        "severity": "high",
                        "description": f"目标效果映射未被真实能力完整支撑：{mapping['id']}",
                        "recommendation": "补齐缺失 workflow、Agent、产物或 demo 信号后重新验证。",
                    }
                )

        return mapping_results

    def _configured_workflows(self, repo_root: Path) -> set[str]:
        try:
            config = read_yaml(repo_root, "config/pipeline.yaml")
        except Exception:
            return set()
        return set(config.get("workflows", {}).keys())

    def _demo_contains(self, repo_root: Path, term: str) -> bool:
        demo_path = repo_root / "docs/demos/ai_dev_pipeline_demo.html"
        if not demo_path.exists():
            return False
        return term in demo_path.read_text(encoding="utf-8")

    def _check_demo_effects(
        self,
        repo_root: Path,
        goal_spec: dict[str, Any],
        checks: list[dict[str, Any]],
        blocking_issues: list[dict[str, str]],
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for demo_check in goal_spec.get("demo_effect_checks", []):
            demo_path = demo_check.get("demo_path", "docs/demos/ai_dev_pipeline_demo.html")
            html = self._read_optional_text(repo_root, demo_path)
            missing = {
                "terms": [
                    term for term in demo_check.get("required_terms", []) if not html or term not in html
                ],
                "selectors": [
                    selector
                    for selector in demo_check.get("required_selectors", [])
                    if not html or not self._selector_exists(html, selector)
                ],
            }
            passed = not any(missing.values())
            result = {
                "id": demo_check["id"],
                "demo_path": demo_path,
                "expected_effect": demo_check.get("expected_effect", ""),
                "result": "pass" if passed else "fail",
                "missing": missing,
                "required_terms": list(demo_check.get("required_terms", [])),
                "required_selectors": list(demo_check.get("required_selectors", [])),
            }
            results.append(result)
            checks.append(
                {
                    "name": demo_check["id"],
                    "type": "demo_effect_check",
                    "result": result["result"],
                }
            )
            if not passed:
                blocking_issues.append(
                    {
                        "id": f"demo_effect_check:{demo_check['id']}",
                        "severity": "high",
                        "description": f"目标效果 demo 检查未通过：{demo_check['id']}",
                        "recommendation": "补齐 demo 文案、DOM 结构或更新目标检查配置后重新验证。",
                    }
                )
        return results

    def _check_demo_visuals(
        self,
        repo_root: Path,
        goal_spec: dict[str, Any],
        checks: list[dict[str, Any]],
        blocking_issues: list[dict[str, str]],
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for visual_check in goal_spec.get("demo_visual_checks", []):
            demo_path = visual_check.get("demo_path", "docs/demos/ai_dev_pipeline_demo.html")
            html = self._read_optional_text(repo_root, demo_path)
            css_text = self._extract_tag_content(html, "style")
            script_text = self._extract_tag_content(html, "script")
            missing = {
                "css_terms": [
                    term for term in visual_check.get("required_css_terms", []) if term not in css_text
                ],
                "script_terms": [
                    term for term in visual_check.get("required_script_terms", []) if term not in script_text
                ],
            }
            passed = not any(missing.values())
            result = {
                "id": visual_check["id"],
                "demo_path": demo_path,
                "expected_effect": visual_check.get("expected_effect", ""),
                "result": "pass" if passed else "fail",
                "missing": missing,
                "required_css_terms": list(visual_check.get("required_css_terms", [])),
                "required_script_terms": list(visual_check.get("required_script_terms", [])),
            }
            results.append(result)
            checks.append(
                {
                    "name": visual_check["id"],
                    "type": "demo_visual_check",
                    "result": result["result"],
                }
            )
            if not passed:
                blocking_issues.append(
                    {
                        "id": f"demo_visual_check:{visual_check['id']}",
                        "severity": "high",
                        "description": f"目标效果视觉信号检查未通过：{visual_check['id']}",
                        "recommendation": "补齐 demo 的关键布局、状态色、动效或交互脚本信号后重新验证。",
                    }
                )
        return results

    def _check_demo_rendering(
        self,
        repo_root: Path,
        task_id: str,
        goal_spec: dict[str, Any],
        checks: list[dict[str, Any]],
        blocking_issues: list[dict[str, str]],
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for render_check in goal_spec.get("demo_render_checks", []):
            check_id = render_check["id"]
            demo_path = render_check.get("demo_path", "docs/demos/ai_dev_pipeline_demo.html")
            screenshot_artifact = render_check.get(
                "screenshot_artifact",
                f"workspace/tasks/{task_id}/review/{check_id}.png",
            )
            viewport = render_check.get("viewport", {})
            width = int(viewport.get("width", 1280))
            height = int(viewport.get("height", 720))
            min_screenshot_bytes = int(render_check.get("min_screenshot_bytes", 2048))
            browser_path = self._resolve_browser_path(render_check.get("browser_path"))
            missing = {"browser": [], "screenshot": [], "dom_terms": [], "dom_selectors": []}
            screenshot_bytes = 0
            dom_output = ""

            if not browser_path:
                missing["browser"].append("local_browser")
            else:
                screenshot_bytes = self._capture_screenshot(
                    browser_path,
                    repo_root,
                    demo_path,
                    screenshot_artifact,
                    width,
                    height,
                    int(render_check.get("virtual_time_budget_ms", 1200)),
                )
                if screenshot_bytes < min_screenshot_bytes:
                    missing["screenshot"].append(screenshot_artifact)
                dom_output = self._dump_rendered_dom(
                    browser_path,
                    repo_root,
                    demo_path,
                    int(render_check.get("virtual_time_budget_ms", 1200)),
                )
                missing["dom_terms"] = [
                    term for term in render_check.get("required_dom_terms", []) if term not in dom_output
                ]
                missing["dom_selectors"] = [
                    selector
                    for selector in render_check.get("required_dom_selectors", [])
                    if not self._selector_exists(dom_output, selector)
                ]

            passed = not any(missing.values())
            evidence = self._render_evidence(
                dom_output=dom_output,
                screenshot_artifact=screenshot_artifact,
                screenshot_bytes=screenshot_bytes,
                min_screenshot_bytes=min_screenshot_bytes,
                required_dom_terms=list(render_check.get("required_dom_terms", [])),
                required_dom_selectors=list(render_check.get("required_dom_selectors", [])),
                missing=missing,
            )
            result = {
                "id": check_id,
                "demo_path": demo_path,
                "expected_effect": render_check.get("expected_effect", ""),
                "result": "pass" if passed else "fail",
                "missing": missing,
                "browser_path": browser_path,
                "viewport": {"width": width, "height": height},
                "screenshot_artifact": screenshot_artifact,
                "screenshot_bytes": screenshot_bytes,
                "min_screenshot_bytes": min_screenshot_bytes,
                "required_dom_terms": list(render_check.get("required_dom_terms", [])),
                "required_dom_selectors": list(render_check.get("required_dom_selectors", [])),
                "evidence": evidence,
                "acceptance_conclusion": {
                    "passed": passed,
                    "summary": "目标效果渲染证据通过。" if passed else "目标效果渲染证据存在缺口。",
                    "missing": missing,
                },
            }
            results.append(result)
            checks.append(
                {
                    "name": check_id,
                    "type": "demo_render_check",
                    "result": result["result"],
                }
            )
            if not passed:
                blocking_issues.append(
                    {
                        "id": f"demo_render_check:{check_id}",
                        "severity": "high",
                        "description": f"目标效果本地浏览器渲染检查未通过：{check_id}",
                        "recommendation": "确认本机浏览器可用、截图产物非空，并补齐渲染后的关键 DOM 信号。",
                    }
                )
        return results

    def _render_evidence(
        self,
        *,
        dom_output: str,
        screenshot_artifact: str,
        screenshot_bytes: int,
        min_screenshot_bytes: int,
        required_dom_terms: list[str],
        required_dom_selectors: list[str],
        missing: dict[str, list[str]],
    ) -> dict[str, Any]:
        # evidence 面向人工判断，显式列出每类目标效果证据是否命中。
        return {
            "screenshot": {
                "artifact": screenshot_artifact,
                "exists": screenshot_bytes > 0,
                "bytes": screenshot_bytes,
                "min_bytes": min_screenshot_bytes,
                "passed": screenshot_bytes >= min_screenshot_bytes,
            },
            "dom_terms": [
                {"term": term, "present": term not in missing["dom_terms"]}
                for term in required_dom_terms
            ],
            "dom_selectors": [
                {"selector": selector, "present": selector not in missing["dom_selectors"]}
                for selector in required_dom_selectors
            ],
            "page_structure": {
                "has_html": "<html" in dom_output.lower(),
                "has_body": "<body" in dom_output.lower(),
                "title": self._first_tag_content(dom_output, "title"),
            },
        }

    def _resolve_browser_path(self, configured_path: str | None) -> str | None:
        if configured_path:
            configured = Path(configured_path)
            if configured.exists():
                return str(configured)
            return shutil.which(configured_path)

        candidates = [
            os.environ.get("AI_DEV_PIPELINE_BROWSER"),
            "google-chrome",
            "google-chrome-stable",
            "chromium",
            "chromium-browser",
        ]
        for candidate in candidates:
            if not candidate:
                continue
            candidate_path = Path(candidate)
            path = shutil.which(candidate) if not candidate_path.exists() else str(candidate_path)
            if path:
                return path
        return None

    def _capture_screenshot(
        self,
        browser_path: str,
        repo_root: Path,
        demo_path: str,
        screenshot_artifact: str,
        width: int,
        height: int,
        virtual_time_budget_ms: int,
    ) -> int:
        screenshot_path = repo_root / screenshot_artifact
        screenshot_path.parent.mkdir(parents=True, exist_ok=True)
        command = self._browser_base_command(browser_path, virtual_time_budget_ms) + [
            f"--window-size={width},{height}",
            f"--screenshot={screenshot_path}",
            self._file_url(repo_root, demo_path),
        ]
        try:
            subprocess.run(
                command,
                cwd=repo_root,
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
        except Exception:
            return 0
        if not screenshot_path.exists():
            return 0
        return screenshot_path.stat().st_size

    def _dump_rendered_dom(
        self,
        browser_path: str,
        repo_root: Path,
        demo_path: str,
        virtual_time_budget_ms: int,
    ) -> str:
        command = self._browser_base_command(browser_path, virtual_time_budget_ms) + [
            "--dump-dom",
            self._file_url(repo_root, demo_path),
        ]
        try:
            completed = subprocess.run(
                command,
                cwd=repo_root,
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
        except Exception:
            return ""
        return completed.stdout

    def _browser_base_command(self, browser_path: str, virtual_time_budget_ms: int) -> list[str]:
        return [
            browser_path,
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            f"--virtual-time-budget={virtual_time_budget_ms}",
        ]

    def _file_url(self, repo_root: Path, relative_path: str) -> str:
        return (repo_root / relative_path).resolve().as_uri()

    def _read_optional_text(self, repo_root: Path, relative_path: str) -> str:
        try:
            return (repo_root / relative_path).read_text(encoding="utf-8")
        except Exception:
            return ""

    def _extract_tag_content(self, html: str, tag_name: str) -> str:
        # 目标效果图检查只需要静态 HTML 中的内联 style/script 信号，保持本地快速可运行。
        pattern = re.compile(rf"<{tag_name}\b[^>]*>(.*?)</{tag_name}>", re.IGNORECASE | re.DOTALL)
        return "\n".join(match.group(1) for match in pattern.finditer(html))

    def _first_tag_content(self, html: str, tag_name: str) -> str:
        pattern = re.compile(rf"<{tag_name}\b[^>]*>(.*?)</{tag_name}>", re.IGNORECASE | re.DOTALL)
        match = pattern.search(html)
        return match.group(1).strip() if match else ""

    def _selector_exists(self, html: str, selector: str) -> bool:
        selector = selector.strip()
        if not selector:
            return False
        if selector.startswith("#"):
            return self._id_exists(html, selector[1:])
        if selector.startswith("."):
            return self._class_exists(html, selector[1:])
        data_attr_match = re.fullmatch(r"\[([a-zA-Z0-9_-]+)=['\"]([^'\"]+)['\"]\]", selector)
        if data_attr_match:
            attr, value = data_attr_match.groups()
            return self._attribute_value_exists(html, attr, value)
        return f"<{selector}" in html

    def _id_exists(self, html: str, element_id: str) -> bool:
        return self._attribute_value_exists(html, "id", element_id)

    def _class_exists(self, html: str, class_name: str) -> bool:
        pattern = re.compile(r"class=['\"]([^'\"]*)['\"]")
        return any(class_name in value.split() for value in pattern.findall(html))

    def _attribute_value_exists(self, html: str, attribute: str, value: str) -> bool:
        pattern = re.compile(rf"{re.escape(attribute)}=['\"]{re.escape(value)}['\"]")
        return bool(pattern.search(html))

    def _score(self, checks: list[dict[str, Any]]) -> float:
        if not checks:
            return 0.0
        passed = sum(1 for check in checks if check["result"] == "pass")
        return round(passed / len(checks), 3)
