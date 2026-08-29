# W04 Renderer Feature Parity 实施提示词

请在 `D:\project\Re-UthCode` 严格串行完整实施 T10 的 T04 -> T05 -> T06 -> T07，完成 Project/Session、Timeline/Composer、Typed Interaction、Settings/Theme，不得实施 T08 打包。

## 开工前必须读取

1. `AGENTS.md`、`docs/README.md`、`docs/Context-Index.md`、工作包/用户决策/欠账规则
2. T10 原始需求、Spec、Tasks、Checklist 和本 Prompt
3. `docs/context/TUI/README.md`、A03/A04 当前上下文
4. W01～W03 Feedback、Bridge/Preload 实际公共边界和 tests
5. T04～T07 定位的 Renderer/Desktop files/tests

原型 `uthcode-desktop-ui-prototype-v5.html` 在拆分时未提供。若开工时仍缺失，以冻结任务书和真实 API 继续，在 Feedback 标记“原型未验证”；若已提供，只用于视觉/交互参考，不复制假功能。

## 已确认决策

- Timeline 只来自 safe replay 五类记录 + live AgentEvent，保持时序，completed authoritative replacement，failed/cancelled 丢 preview。
- Session 点击即 resume，New Session 视图为空，fresh Run；Project alias/remove 不改磁盘。
- AskUser 覆盖多题/文本/单选/多选/Other/回看；Permission 动态 choices；Plan/Retry/Pause Cancel 是 handle.cancel。
- Slash/Model/Permission/Mode/Session/Compact 语义来自 Python，pending/active 门禁不在 TS 另造 authority。
- UI 使用连续页面/列表/时间线/行/分隔线，禁止卡片矩阵与解释设计的产品文案。

## 修改范围

- 独占 Tasks T04～T07 列出的 Renderer、小范围 Desktop API/preferences 与 Renderer tests，严格按 Task 顺序。
- 首次实施创建 `feedback/W04-renderer-feature-parity-feedback.md`；返工只追加；只勾选 T04～T07 已验证 Checklist。
- 禁止修改 Python Core/Provider/Tool 语义、扩大 Bridge、建 fake store、新增未来入口、Git 写/归档。若 Bridge 有真实缺口，在 Feedback 记录并停止该范围。

## 实施与验证

1. T04 先以真实 API 完成 Project/Session/fresh Run/replay，再进入 Timeline，不先用 fake data 做完整 UI。
2. T05 为 streaming/reasoning/tool/order/authoritative final/failure/Todo/command guard 编写 reducer 测试。
3. T06 逐个覆盖 AskUser 数据形状、Permission choices、Plan/Retry/Pause resume/cancel 与再次 interaction。
4. T07 复用 T01 config use case，测试首配、key 清空、idle rebootstrap、active block 和两主题。
5. 执行 typecheck、Renderer/Desktop tests、T04～T07 Checklist 静态检查与 `git diff --check`。

## Feedback 要求

Feedback 按 T04～T07 说明真实数据流、状态所有权、replay/live reducer、interaction 映射、config rebootstrap、theme/layout、原型可用性、修改文件、精确测试结果、Checklist、未验证人工项和清理结果。
