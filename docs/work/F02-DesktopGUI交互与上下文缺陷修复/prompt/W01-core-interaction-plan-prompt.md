# W01 Core Interaction 与 Plan 实施提示词

请在 `D:\project\Re-UthCode` 严格串行完整实施 F02 的 T01 → T02。只完成 AskUser Core 合同硬切与 Plan 真流式公共事件，不提前实施 Application Context/Session 或 Desktop 主界面任务。

## 开工前必须读取

1. `AGENTS.md`、`docs/README.md`、`docs/Context-Index.md`。
2. `docs/rules/WorkPackageRules.md`、`docs/rules/UserDecisionBoundary.md`。
3. F02 原始需求、Spec、Tasks、Checklist 和本 Prompt。
4. A01、A02、A03 与 TUI 当前上下文。
5. T01/T02 定位的 Core、TUI、Desktop interaction 源码与对应 tests。

用户首次派发本 Prompt 后，原始需求、Spec、Tasks、Prompt 和 Checklist 文字/结构立即冻结；Checklist 只允许勾选有精确证据的已有项。

## 已确认决策

- 所有 select 问题均始终接受自然语言自由答案；结构化 options 为 2～3 个；`allow_other` 硬删除，不兼容旧 payload。
- `PlanContentDelta` 只携带已解码的 `ProposePlan.plan` 新增自然语言内容；不得暴露 raw JSON/arguments/SDK payload。
- `PlanProposed` 与 Core PlanState 继续是完整正式 Plan、revision 和 Review 的唯一权威。

## 修改范围

- 独占 Tasks T01/T02 列出的 Core、TUI interaction、最小 Desktop interaction 适配和对应 tests。
- W01 不修改 Application Context/Session、Desktop Settings、CDP harness、current-facts 文档或 T10 冻结文件。
- 不新增通用 Tool JSON streaming、EventBus、Manager/Registry、旧合同兼容层或跨进程 pending interaction 恢复。
- 原需求中的“提交边界”只表示逻辑 diff 边界；未经用户明确要求，不执行 commit/push/merge/rebase/tag/release。

## 实施与验证

1. T01 先写/调整 Core contract tests，完成字段删除、options 上限、自由答案校验，再适配 TUI/Desktop。
2. 运行 T01 定向 tests 与 `allow_other` active source/tests 否定扫描，证据满足后再进入 T02。
3. T02 以 chunk/escape/unicode/tool-call identity tests 驱动私有 decoder 与公共事件；保持 final parser 权威。
4. 运行 T02 定向 tests、architecture tests 与 `git diff --check`；检查没有 raw arguments 穿过公共事件。
5. 首次执行创建 `feedback/W01-core-interaction-plan-feedback.md`；只勾选 T01/T02 已验证 Checklist。

## Feedback 要求

说明 AskUser 新合同、Plan 增量到最终 Review 的事件顺序、修改文件、精确测试/扫描结果、Checklist、与任务书不同的实际事实、未完成项和清理结果。返工只在同一 Feedback 末尾追加新章节。
