# W03 ContextCompiler / L1-L3 Worker Prompt

## 任务范围与顺序

在 W01、W02 完成后，只执行 Task 3：ContextCompiler logical view 与确定性 L1-L3。完成 Feedback 后停止，不接真实 L4/L5 model call。

## 必须读取

1. `AGENTS.md`、`docs/README.md`、`docs/Context-Index.md`
2. `docs/rules/WorkPackageRules.md`
3. 本工作包原始需求、Spec、Tasks、Checklist
4. `docs/context/A01-AgentRuntime/AgentRuntime-Context.md`
5. `docs/context/A03-State/State-Context.md`
6. `docs/core-design/T09-context-engineering.md`
7. W01、W02 Feedback
8. Task 3 列出的源码与测试以及现有 Tool Result externalization contract

使用 Conda 环境 `re-uthcode`。冻结文档不得修改；只勾选 Task 3 已满足复选框并创建/追加 Feedback。

## 已确认决策

- ContextCompiler 是唯一 model-view builder；Application 只编排 plan/rebuild/Gate。
- Instruction Plane authority 不变；Transcript/Timeline summary 只能进入 Conversation/History authority。
- L1 externalization、L2 preview shrink、L3 inactive raw omission 完全 deterministic，不调用模型。
- reduction 只按完整 Turn / semantic unit；ToolCall/ToolResult 不拆分。
- required protected context + current turn 本身不可装入 C 时直接 fail closed，不调用 L4 掩盖必需内容。
- macro coverage 在 logical view 中替代旧 fine entries，physical Timeline 増长不改变 F。

## 修改范围

仅修改 Tasks Task 3 列出的文件与必要 fixture；不得修改 AgentLoop、Session bytes layout、Command/TUI、Provider adapter 或 Eval/docs。

## 必须交付

- Transcript + latest committed Timeline + runtime facts 的 deterministic logical view。
- request precheck、L1-L3 plan/apply/rebuild 与 typed Gate result。
- protected block、complete tool pair、active/inactive raw turn、macro coverage、25K impossible、1M no-premature-compact tests。
- diagnostics 只含 ID/count/token/budget/reason，无正文。

## 禁止

- 不实现 embedding/relevance、Memory、topic graph、L4/L5 provider call 或 background agent。
- 不建立第二个 compiler 或在 Integration/Interface 拼装 model messages。
- 不修改 frozen D1/D2，不执行 Git 写入或归档。

## 验证

逐项执行 Task 3 Checklist；运行 compiler、budget gate、tool result persistence 与 architecture tests。fake reduction fixture 可以表示尚未接通的 L4 plan/result，但生产不得调用空 summarizer。

## Feedback

首次创建 `feedback/W03-context-compiler-l1-l3-feedback.md`。说明 logical view、每层确定性 reduction、不可解析失败、diagnostics 安全、修改文件、精确测试、Checklist 状态、差异和风险。
