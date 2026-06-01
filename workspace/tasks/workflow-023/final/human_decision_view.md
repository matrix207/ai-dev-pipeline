# 人工决策视图

## 目标效果
- 人工可以一屏查看目标效果、当前达成、剩余任务和下一步建议。
- 决策视图引用 run record、target_effect_report 和 recommendation_basis，方便追溯。

## 当前达成
- 本轮任务：workflow-023
- 来源运行记录：workspace/tasks/workflow-022/runs/workflow-022-run.yaml
- 目标效果报告：workspace/tasks/workflow-023/final/target_effect_report.md
- 人工选择：decision-view-001, task-library-001
- 质量门状态：waiting_for_human_approval
- 是否可以进入下一阶段：待人工审批

## 剩余任务
- 暂无未完成的自动生成任务。

## 下一步建议
- 任务：workflow-024
- 标题：端到端闭环持续优化
- 优先级：medium
- 原因：上一轮剩余任务已完成或已验证：ui-validation-001, feedback-002, dispatch-002, roadmap-001, decision-view-001, task-library-001。转入下一轮持续优化。

## 推荐依据
- 策略：previous_run_context
- 已完成源任务：ui-validation-001, feedback-002, dispatch-002, roadmap-001, decision-view-001, task-library-001
- 剩余开放任务：

## 关键证据
- run_record: workspace/tasks/workflow-023/runs/workflow-023-run.yaml
- recommendation_basis: workspace/tasks/workflow-023/runs/workflow-023-run.yaml#recommendation_basis
- target_effect_report: workspace/tasks/workflow-023/final/target_effect_report.md
