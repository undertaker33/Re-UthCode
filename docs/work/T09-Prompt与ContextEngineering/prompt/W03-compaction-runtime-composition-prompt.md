# W03 Tool Result / Compaction / Runtime Composition Worker Prompt

## 任务范围

只执行：

- Task 6：大 Tool Result 外置与资源上限
- Task 7：有界 Compaction 与 Runtime Request Composition

先读取 W01/W02 Feedback，核验 History、Compiler、Session store 和 fixed 258K budget contract。

## 必须读取

- `AGENTS.md`、项目路由/规则、本工作包四个主文件、W01/W02 Feedback。
- Tool Core/Application/Integration、Session files、AgentLoop/Run/generation、Provider mapper 与对应 tests。

## 必须交付

1. 用代表性输出和文件系统测试确定并在 Feedback 解释 inline/preview/single-result hard cap/session quota/read page limit。
2. durable externalization、opaque session-scoped ref、bounded ToolResultRead、hash/size 校验；quota 错误不留 partial/dangling ref。
3. 分别表达 Tool execution outcome 与 result materialization/persistence outcome；副作用已发生后不伪造 Tool 未执行，不自动重试。
4. CompactionInputBudget、OutputReserve、SummaryHardCap、single-flight。
5. 超大候选按完整 semantic units 有界滚动分批；ToolCall/ToolResult 不拆，Compactor tool-free。
6. Summary 保持 history authority，失败保留旧 Projection/History。
7. Runtime 每次请求统一经 Compiler；Core/Application 将 Instruction Plane、Conversation Plane 与 Tool Definitions 形成 provider-independent GenerationRequest，Integration 只做原生协议映射；ordinary history 不能进入 Instruction Plane，overflow 仅一次最后保护。
8. 写入 W03 Feedback 并同步 Tasks/Checklist。

## 禁止

- 不提供任意路径读取，不做跨 Session ref，不建 Artifact GC。
- 不绕过 compactor 自身预算，不做复杂 summary graph。
- 不实现 relevance/embedding/Memory、Slash/TUI、Eval 或 Git 写入。

## 验证

覆盖 hard cap、session quota、partial cleanup、ref isolation、execution/persistence failure、不自动重试已产生副作用的 Tool、compactor-input overflow、合法 boundary 分批、summary authority、Compaction 不创建 Instruction Epoch、ordinary-history spoof rejection、三类 Provider 两平面映射、single-flight、Provider overflow 不作为 discovery、Core 不依赖 Provider SDK。

## Feedback

首次创建 `feedback/W03-compaction-runtime-composition-feedback.md`，记录资源上限选择证据、正式 request 数据流、精确测试结果、Checklist 状态和未完成项。不能在合法 semantic boundary 内处理或副作用状态不明时停止。
