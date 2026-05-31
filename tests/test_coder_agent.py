from __future__ import annotations

from pathlib import Path

import pytest

from agents import CoderAgent
from artifacts import write_yaml


def write_task_batch(tmp_path: Path) -> None:
    write_yaml(
        tmp_path,
        "workspace/tasks/bootstrap-001/final/next_dev_tasks.yaml",
        {
            "tasks": [
                {
                    "id": "dev-005",
                    "title": "编码 Agent 骨架",
                    "priority": "medium",
                    "scope": [
                        "创建 coder Agent 的最小接口。",
                        "支持从任务说明读取开发范围和验收标准。",
                        "输出代码变更计划或草稿产物。",
                    ],
                    "out_of_scope": [
                        "自动修改大量文件。",
                        "自动提交或自动合并。",
                    ],
                    "acceptance_criteria": [
                        "coder Agent 能读取 dev task 并输出结构化实现计划。",
                        "默认不执行 PR 或 merge 操作。",
                        "生成产物保存在 workspace/tasks/{task_id}/ 下。",
                    ],
                }
            ]
        },
    )


def test_coder_agent_reads_dev_task_and_outputs_structured_plan(tmp_path: Path) -> None:
    write_task_batch(tmp_path)

    result = CoderAgent().run({"repo_root": str(tmp_path), "task_id": "dev-005"})

    assert result.output["task_id"] == "dev-005"
    assert result.output["title"] == "编码 Agent 骨架"
    assert len(result.output["implementation_plan"]) == 3
    assert result.output["verification"]["required_commands"] == ["python -m pytest -q"]
    assert result.output["safety"]["pr_or_merge"] == "not_allowed"
    assert "workspace/tasks/dev-005/code/implementation_plan.json" in result.output["output_artifacts"]


def test_coder_agent_rejects_unknown_task(tmp_path: Path) -> None:
    write_task_batch(tmp_path)

    with pytest.raises(ValueError, match="Unknown dev task"):
        CoderAgent().run({"repo_root": str(tmp_path), "task_id": "dev-999"})
