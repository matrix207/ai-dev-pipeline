from __future__ import annotations

from pathlib import Path


def test_readme_documents_end_to_end_approval_commands() -> None:
    # README 是人工和 Agent 协作入口，关键闭环命令必须在文档中可发现。
    readme = Path("README.md").read_text(encoding="utf-8")

    required_fragments = [
        "--list-runs",
        "--approve-run",
        "--continue-run",
        "--decision approved",
        "--decision rejected",
        "退出码",
        "workflow-009-run",
    ]
    for fragment in required_fragments:
        assert fragment in readme
