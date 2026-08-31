# W02 Application Context 与 Session 实施提示词

请在 `D:\project\Re-UthCode` 严格串行完整实施 F02 的 T03 → T04。只完成 Application Context/Compaction 安全投影、Session move 与 Plan replay，不提前修改 Desktop Renderer。

## 开工前必须读取

1. `AGENTS.md`、`docs/README.md`、`docs/Context-Index.md`、`docs/rules/WorkPackageRules.md`、`docs/rules/UserDecisionBoundary.md`、`docs/OutstandingDebtList.md`。
2. F02 原始需求、Spec、Tasks、Checklist 和本 Prompt。
3. A03、A04 及与 Context/Session 相关的 A01 当前上下文。
4. `feedback/W01-core-interaction-plan-feedback.md`，确认 T01/T02 公共事件合同和验证结果。
5. T03/T04 定位的 Application、Session、Bridge 源码与对应 tests。

## 已确认决策

- Application 是 Context budget/measurement/Compaction lifecycle 唯一用户安全投影来源；不改变 T09-3 Gate/Low Water/Hard Gate 语义。
- exact 只描述确有 Provider usage 的对应 request boundary；任何后续 Context mutation 后回到 estimate。
- 当前 open idle Session 在既有 writer lock 内同步、移动、成功释放；active Turn 拒绝，失败保持 source ownership。
- replay 只从 durable 完整 Plan 投影安全正文，不恢复未完成 draft/review waiter，不泄漏 raw tool body。

## 修改范围

- 独占 Tasks T03/T04 列出的 Application、Bridge 和 Python tests。
- 不修改 Renderer、Settings reveal、CDP harness、T10 冻结文件或 Persistent Runtime Recovery。
- 不创建 Desktop Context/Session facade、第二 runtime/store、跨项目文件 reader、后台 context agent 或新 Context 算法。
- 未经用户明确要求，不执行任何 Git 写操作。

## 实施与验证

1. T03 先建立 status DTO/measurement/compaction lifecycle tests，再实现 Application 投影；加入 terminal event 与 Application 收口时序回归。
2. 证明 default/configured/provider limit 与现有 ContextBudget 同源，resume/mutation measurement 正确，不解析 diagnostics 才能得到产品状态。
3. T04 以 current idle move、active reject、transaction failure、safe error 和 Plan replay tests 驱动实现。
4. 目标项目 catalog 只通过 mutation 或下次激活刷新，不新建第二 Application。
5. 运行 T03/T04 定向 tests、architecture tests 与 `git diff --check`。
6. 首次执行创建 `feedback/W02-application-context-session-feedback.md`；只勾选 T03/T04 已验证 Checklist。

## Feedback 要求

说明 Context/Compaction 状态来源和时序、Session move 事务与失败不变量、Plan replay 安全边界、修改文件、精确测试、Checklist、偏差、风险和清理结果。返工只追加。
