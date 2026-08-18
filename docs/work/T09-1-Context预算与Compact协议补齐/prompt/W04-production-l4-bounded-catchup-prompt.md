# W04 Production L4 / Bounded Catch-up Worker Prompt

## 任务范围与顺序

在 W01～W03 完成后，只执行 Task 4：Production L4 与 bounded catch-up。完成 Feedback 后停止；L5、HistoryRead、manual command lifecycle 由后续 Worker 负责。

## 必须读取

1. `AGENTS.md`、`docs/README.md`、`docs/Context-Index.md`
2. `docs/rules/WorkPackageRules.md`
3. 本工作包原始需求、Spec、Tasks、Checklist
4. `docs/context/A01-AgentRuntime/AgentRuntime-Context.md`
5. `docs/context/A03-State/State-Context.md`
6. `docs/context/A04-Orchestration/Orchestration-Context.md`
7. W01～W03 Feedback
8. Task 4 列出的源码与测试

使用 Conda 环境 `re-uthcode`。冻结文档不得改写；只勾选 Task 4 已满足复选框并创建/追加 Feedback。

## 已确认决策

- L4 使用当前主模型：active Turn 内使用 frozen provider/model/C，idle manual use case 未来使用 Application 当前选择。
- Compact request 使用独立 Prompt、独立 request/budget、无 Agent Tools，不进入普通 Tool loop，不跨 Provider fallback。
- 大窗口尊重 C；发生真实 pressure 后同一次 Gate 可执行 1..N bounded raw epochs。
- 每批成功先写 SemanticEntry、最后写 ActiveCheckpoint；commit 后 rebuild+Gate。
- attempts/coverage/estimate/cancellation 只在当前调用栈，不写 RunState、Transcript、Timeline 或 Runtime log 作为恢复依据。
- crash 后从 Transcript + latest valid checkpoint 推导 next uncovered epoch；必须有 finite/no-progress/repeated-failure breaker。

## 修改范围

仅修改 Tasks Task 4 列出的文件；新增 `tests/test_t09_1_context_protocol_e2e.py` 的 L4 初始范围。必要 async typing 可在列出文件内最小收口。

## 必须交付

- AgentLoop awaited request-preparer，且 AgentLoop 不接收 Transcript/Timeline/phase。
- tool-free bounded L4 request、结构化 parse/validate、one entry per Turn、checkpoint-last commit。
- single/multi epoch、1M pressure、same Turn snapshot、cancel、crash before/after checkpoint、invalid/no-progress/finite-attempt tests。
- 删除同步 `summarize=None` 与旧 Projection/overflow compactor 生产路径中由本 Task 直接失效的部分。

## 禁止

- 不实现 L5、HistoryRead、manual `/compact` command、status 文案或 full docs sync。
- 不新增 CompactionJob、CompactState、BackgroundCompactor、独立 compaction model、持久 FSM。
- 不实现 Runtime recovery、Memory、Timeline GC 或 Provider-specific server compaction Core contract。
- 不执行 Git 写入或归档。

## 验证

逐项执行 Task 4 Checklist；测试不得依赖真实网络。明确记录 provider call count、epoch count、coverage、checkpoint order 和 cancellation outcome。

## Feedback

首次创建 `feedback/W04-production-l4-bounded-catchup-feedback.md`。以简短教程说明 Gate→epoch→commit→rebuild 流程、无 FSM 恢复依据、修改文件、精确测试、Checklist 状态、差异、风险与清理。
