"""Code review agent skeleton for local validation artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from agents import BaseAgent
from artifacts import read_json, read_yaml


class CodeReviewerAgent(BaseAgent):
    """Review local task artifacts after tests have run."""

    def __init__(self, name: str = "code-reviewer") -> None:
        super().__init__(name)

    def handle(self, payload: dict[str, Any]) -> Mapping[str, Any]:
        repo_root = Path(payload.get("repo_root", "."))
        task_id = payload["task_id"]
        validation_path = payload.get("validation_path") or (
            f"workspace/tasks/{task_id}/review/test_validation.json"
        )
        task_definition_path = payload.get("task_definition_path") or (
            "workspace/tasks/optimization-001/final/next_optimization_tasks.yaml"
        )

        checks: list[dict[str, str]] = []
        blocking_issues: list[dict[str, str]] = []
        non_blocking_issues: list[dict[str, str]] = []
        recommendations: list[str] = []

        validation = self._read_validation(repo_root, validation_path, checks, blocking_issues)
        if validation and validation.get("passed") is True:
            checks.append(
                {
                    "name": "tests_passed",
                    "result": "pass",
                    "notes": "测试验证已通过。",
                }
            )
        else:
            self._block(
                checks,
                blocking_issues,
                "tests_passed",
                "测试验证未通过或缺少测试验证产物。",
                "先修复测试失败，再进入人工合并门。",
            )

        state_path = f"workspace/tasks/{task_id}/state.json"
        state = self._read_state(repo_root, state_path, checks, blocking_issues)
        if state is not None:
            checks.append(
                {
                    "name": "task_state_recorded",
                    "result": "pass",
                    "notes": "任务状态产物存在。",
                }
            )
        else:
            self._block(
                checks,
                blocking_issues,
                "task_state_recorded",
                "任务状态产物缺失。",
                "写入 workspace/tasks/{task_id}/state.json。",
            )

        artifact_consistency = self._check_artifacts_exist(repo_root, state, checks, blocking_issues)
        acceptance_coverage = self._check_acceptance_coverage(
            repo_root,
            task_definition_path,
            task_id,
            checks,
            non_blocking_issues,
            recommendations,
        )

        approved = not blocking_issues
        return {
            "task_id": task_id,
            "status": "passed" if approved else "blocked",
            "decision": {
                "approved_for_human_merge_gate": approved,
                "requires_human_review": not approved,
            },
            "checks": checks,
            "blocking_issues": blocking_issues,
            "non_blocking_issues": non_blocking_issues,
            "recommendations": recommendations,
            "acceptance_coverage": acceptance_coverage,
            "artifact_consistency": artifact_consistency,
        }

    def _read_validation(
        self,
        repo_root: Path,
        validation_path: str,
        checks: list[dict[str, str]],
        blocking_issues: list[dict[str, str]],
    ) -> dict[str, Any] | None:
        try:
            validation = read_json(repo_root, validation_path)
        except Exception as exc:
            self._block(
                checks,
                blocking_issues,
                "test_validation_artifact",
                f"无法读取测试验证产物：{validation_path}",
                str(exc),
            )
            return None

        checks.append(
            {
                "name": "test_validation_artifact",
                "result": "pass",
                "notes": f"已读取 {validation_path}。",
            }
        )
        return validation

    def _path_exists(self, repo_root: Path, relative_path: str) -> bool:
        return (repo_root / relative_path).exists()

    def _read_state(
        self,
        repo_root: Path,
        state_path: str,
        checks: list[dict[str, str]],
        blocking_issues: list[dict[str, str]],
    ) -> dict[str, Any] | None:
        try:
            return read_json(repo_root, state_path)
        except Exception as exc:
            self._block(
                checks,
                blocking_issues,
                "task_state_recorded",
                f"无法读取任务状态产物：{state_path}",
                str(exc),
            )
            return None

    def _check_artifacts_exist(
        self,
        repo_root: Path,
        state: dict[str, Any] | None,
        checks: list[dict[str, str]],
        blocking_issues: list[dict[str, str]],
    ) -> dict[str, Any]:
        artifacts = list((state or {}).get("artifacts", []))
        missing = [path for path in artifacts if not self._path_exists(repo_root, path)]
        if missing:
            self._block(
                checks,
                blocking_issues,
                "state_artifacts_exist",
                "任务状态中存在缺失的 artifact 路径。",
                "修复状态产物或补齐缺失 artifact。",
            )
        else:
            checks.append(
                {
                    "name": "state_artifacts_exist",
                    "result": "pass",
                    "notes": "任务状态中的 artifact 路径均存在。",
                }
            )
        return {
            "checked": artifacts,
            "missing": missing,
        }

    def _check_acceptance_coverage(
        self,
        repo_root: Path,
        task_definition_path: str,
        task_id: str,
        checks: list[dict[str, str]],
        non_blocking_issues: list[dict[str, str]],
        recommendations: list[str],
    ) -> dict[str, Any]:
        task = self._load_task_definition(repo_root, task_definition_path, task_id)
        criteria = list((task or {}).get("acceptance_criteria", []))
        if not criteria:
            checks.append(
                {
                    "name": "acceptance_criteria_coverage",
                    "result": "pass_with_notes",
                    "notes": "未找到任务验收标准，跳过 evidence 覆盖检查。",
                }
            )
            recommendations.append("为任务定义 acceptance_criteria，以便代码评审检查 evidence 覆盖。")
            return {"criteria": [], "covered": [], "missing_evidence": []}

        evidence_sources = self._collect_evidence_sources(repo_root, task_id)
        evidence_text = "\n".join(source["text"] for source in evidence_sources)
        evidence_map = []
        for criterion in criteria:
            matched_evidence = self._matched_evidence(criterion, evidence_sources)
            if matched_evidence:
                evidence_map.append(
                    {
                        "criterion": criterion,
                        "status": "matched",
                        "matched_evidence": matched_evidence,
                        "missing_evidence": [],
                        "recommendation": "",
                    }
                )
            else:
                evidence_map.append(
                    {
                        "criterion": criterion,
                        "status": "missing",
                        "matched_evidence": [],
                        "missing_evidence": [criterion],
                        "recommendation": "在 acceptance_check.json、implementation_summary.yaml 或相关产物中补充该验收标准的明确 evidence。",
                    }
                )

        covered = [item["criterion"] for item in evidence_map if item["status"] == "matched"]
        missing = [item["criterion"] for item in evidence_map if item["status"] == "missing"]

        if missing:
            checks.append(
                {
                    "name": "acceptance_criteria_coverage",
                    "result": "pass_with_notes",
                    "notes": "部分验收标准缺少明确 evidence。",
                }
            )
            non_blocking_issues.append(
                {
                    "id": "acceptance_criteria_evidence",
                    "severity": "medium",
                    "description": "部分验收标准缺少明确 evidence。",
                    "recommendation": "在 acceptance_check.json 或 summary 中补充每条验收标准的 evidence。",
                }
            )
            recommendations.append("补充验收标准到 evidence 的逐条映射，提升自动评审可信度。")
        else:
            checks.append(
                {
                    "name": "acceptance_criteria_coverage",
                    "result": "pass",
                    "notes": "验收标准均找到 evidence。",
                }
            )

        return {
            "criteria": criteria,
            "covered": covered,
            "missing_evidence": missing,
            "acceptance_evidence_map": evidence_map,
        }

    def _load_task_definition(
        self,
        repo_root: Path,
        task_definition_path: str,
        task_id: str,
    ) -> dict[str, Any] | None:
        try:
            task_batch = read_yaml(repo_root, task_definition_path)
        except Exception:
            return None
        for task in task_batch.get("tasks", []):
            if task.get("id") == task_id:
                return dict(task)
        return None

    def _collect_evidence_sources(self, repo_root: Path, task_id: str) -> list[dict[str, str]]:
        task_root = repo_root / "workspace" / "tasks" / task_id
        if not task_root.exists():
            return []
        evidence_sources: list[dict[str, str]] = []
        for path in task_root.rglob("*"):
            if path.suffix not in {".json", ".yaml", ".yml", ".md", ".txt"}:
                continue
            try:
                evidence_sources.append(
                    {
                        "path": str(path.relative_to(repo_root)),
                        "text": path.read_text(encoding="utf-8"),
                    }
                )
            except UnicodeDecodeError:
                continue
        return evidence_sources

    def _collect_evidence_text(self, repo_root: Path, task_id: str) -> str:
        return "\n".join(
            source["text"] for source in self._collect_evidence_sources(repo_root, task_id)
        )

    def _matched_evidence(
        self,
        criterion: str,
        evidence_sources: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        matches = []
        for source in evidence_sources:
            if self._criterion_has_evidence(criterion, source["text"]):
                matches.append(
                    {
                        "path": source["path"],
                        "match": self._evidence_match_reason(criterion, source["text"]),
                    }
                )
        return matches

    def _evidence_match_reason(self, criterion: str, evidence_text: str) -> str:
        normalized = criterion.strip().rstrip("。.")
        if normalized and normalized in evidence_text:
            return "exact_text"
        return "keyword_coverage"

    def _criterion_has_evidence(self, criterion: str, evidence_text: str) -> bool:
        normalized = criterion.strip().rstrip("。.")
        if normalized and normalized in evidence_text:
            return True
        keywords = [part for part in normalized.replace("，", " ").replace(",", " ").split() if len(part) >= 4]
        return len(keywords) > 1 and all(keyword in evidence_text for keyword in keywords)

    def _block(
        self,
        checks: list[dict[str, str]],
        blocking_issues: list[dict[str, str]],
        check_name: str,
        description: str,
        recommendation: str,
    ) -> None:
        checks.append({"name": check_name, "result": "fail", "notes": description})
        blocking_issues.append(
            {
                "id": check_name,
                "severity": "high",
                "description": description,
                "recommendation": recommendation,
            }
        )
