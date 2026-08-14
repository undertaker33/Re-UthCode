# W03 Compaction / Runtime Composition Worker Prompt

## 执行范围

在 W01、W02 完成后，严格串行执行 Task 6 → Task 7。不执行 Slash/TUI、Eval 或包级文档收口。

## 必须读取

1. `AGENTS.md`、`docs/rules/WorkPackageRules.md`，本工作包原始需求、Spec、Tasks、Checklist 和 W01/W02 Feedback。
2. A01/A03/A04 current context，Task 6～7 列出的当前源码/测试，T05/T06/T08 归档中 Loop、Pause、Plan/Task/Steering 边界。

## 已确认决策

- 路线 B：按需 model compaction；不创建 Context Agent、Worker、Scheduler、Graph 或第二 Agent Loop。
- manual 仅 idle，auto 仅安全 request boundary，reactive 仅明确 context overflow 且同一逻辑请求最多一次 retry。
- Compactor tool-free，只接受 prior summary + stable semantic head；只在完整有效文本后 commit Projection。
- completed Turn 收口 active Task/Plan；failed/cancelled + unfinished Task 在同 Session 下一 Turn 延续；one-shot feedback 不延续。

## 实施与禁止边界

- 所有正式 Agent requests 消费 ContextSnapshot；不再无条件传全量 messages。
- 保持 Provider/model/tool/rule Turn 快照、Pause/Resume、Permission、Steering、FIFO 和 single RunState writer。
- Compaction 不读写 TaskState/PlanState 权威值，不恢复或重放可能已产生副作用的 Tool。
- 冻结文件规则与 Checklist 勾选规则同 W01。

## 测试与验收

执行 Checklist Task 6～7 全部项、T06/T08 定向回归和 architecture boundaries。为 compactor failure/cancel/toolcall/invalid/second overflow 全部断言 history/projection 不破坏。

## Feedback

创建 `feedback/W03-compaction-runtime-composition-feedback.md`。记录正式 request 数据流、跨 Turn 状态规则、取消/重试边界、命令精确结果和未完成项。需要第二 Runtime、Provider-specific Core 分支或 side-effect replay 时停止并记录。
