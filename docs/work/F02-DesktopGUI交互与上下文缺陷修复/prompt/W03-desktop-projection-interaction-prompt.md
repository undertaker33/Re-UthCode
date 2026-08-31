# W03 Desktop Projection 与 Interaction 实施提示词

请在 `D:\project\Re-UthCode` 严格串行完整实施 F02 的 T05 → T06。完成 Desktop command/context/session 投影与 Chat/Tool/Todo/AskUser/Plan 交互，不实施 Settings T07 或最终审查验收。

## 开工前必须读取

1. `AGENTS.md`、`docs/README.md`、`docs/Context-Index.md`、`docs/rules/WorkPackageRules.md`、`docs/rules/UserDecisionBoundary.md`、`docs/OutstandingDebtList.md`。
2. F02 原始需求、Spec、Tasks、Checklist 和本 Prompt。
3. A02、A03、A04 与 TUI 当前上下文。
4. W01、W02 Feedback；以实际 Application/Bridge DTO 和 tests 为唯一前置合同。
5. T05/T06 定位的 Desktop source/tests 与现有 renderer shared fixtures。

## 已确认决策

- Renderer 只消费 Application Context/Compaction/Command/Session 权威，不推导预算或解析 diagnostics。
- Slash direct action 不作为用户消息；Model catalog 与 `/model` 同源；普通 catalog refresh 不改变 Session 展示顺序。
- Tool/Todo/AskUser/Plan 各自只更新同一视觉实体；Plan draft 按 turn/tool-call identity 追加并由最终 Plan 原地封口。
- UI 只保存 menu/focus/draft/timer 等 ephemeral state；键盘、IME、ARIA、窄屏与 reduced motion 属于当前交付。

## 修改范围

- 独占 Tasks T05/T06 的 Renderer、locale/CSS 和 Renderer tests。
- 不修改 T07 Settings 生产逻辑、Python Bridge/Application、CDP harness、current-facts docs 或 T10 冻结文件。
- 若前序 DTO 有关键缺口，停止对应范围并在 W03 Feedback 记录，不以 TS fallback/第二 authority 绕过。
- 可按当前 feature suite 拆分 100KB tests，但共享 fixture truth 保持单一，旧入口删除；不新增通用 store/framework。
- 未经用户明确要求，不执行任何 Git 写操作。

## 实施与验证

1. T05 先删除 Context 第二 authority，以实际 status DTO 更新 reducer/Composer/RuntimePanel tests。
2. 用显式 action reason 固化 Session new/message/pin 与 refresh/resume/rename 的不同排序；move 遵循 authoritative result。
3. 处理 terminal event 到 Application result 收口竞态，禁止 per-delta status RPC。
4. T06 完成 Plan draft/final/cancel、AskUser multi-step、Tool elapsed、Todo、keyboard/IME/focus/ARIA/layout/reduced-motion tests。
5. 运行 typecheck、Desktop tests、T05/T06 Checklist 扫描与 `git diff --check`。
6. 首次执行创建 `feedback/W03-desktop-projection-interaction-feedback.md`；只勾选 T05/T06 已验证 Checklist。

## Feedback 要求

说明 reducer 状态所有权、status refresh 时序、Session presentation ordering、direct command、Plan/AskUser/Tool/Todo DOM identity、可访问性与布局、修改文件、精确测试、Checklist、未验证人工项和清理结果。返工只追加。
