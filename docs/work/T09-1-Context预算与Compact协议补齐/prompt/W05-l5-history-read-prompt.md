# W05 L5 Timeline Aging / HistoryRead Worker Prompt

## 任务范围与顺序

在 W01～W04 完成后，只执行 Task 5：L5 Timeline Aging 与 HistoryRead。完成 Feedback 后停止，不接 command lifecycle 或最终文档。

## 必须读取

1. `AGENTS.md`、`docs/README.md`、`docs/Context-Index.md`
2. `docs/rules/WorkPackageRules.md`
3. 本工作包原始需求、Spec、Tasks、Checklist
4. `docs/context/A01-AgentRuntime/AgentRuntime-Context.md`
5. `docs/context/A03-State/State-Context.md`
6. W01～W04 Feedback
7. Task 5 列出的源码、测试、现有 `ToolResultRead` 与 default tool composition

使用 Conda 环境 `re-uthcode`。冻结文档不得改写；只勾选 Task 5 已满足复选框并创建/追加 Feedback。

## 已确认决策

- L5 仅处理 old complete Compact Epoch；Epoch 由 checkpoint transaction 边界推导。
- L5 每次重新读取 raw Transcript refs，不把旧 fine/macro summary 当作权威证据，不做 summary-of-summary。
- 成功结果为一个 bounded EpochMacroSummary，随后最后提交 ActiveCheckpoint；旧 records 物理保留、逻辑由 coverage 替代。
- 当前模型无 safe epoch 时 fail closed，不静默切模型。
- HistoryRead 与 ToolResultRead 独立：current Session only、opaque exact ref、bounded page、read-only、no index/search、不接受路径、不递归 externalize。

## 修改范围

仅修改 Tasks Task 5 列出的文件；新增 `src/uthcode/integrations/tools/history_read.py`、`tests/test_history_read_tool.py`。若 default tool factory 需要机械注册可最小修改对应列出文件。

## 必须交付

- Fine Timeline > F 的 old complete epoch selection、raw evidence resolution、macro commit 与 logical supersede。
- no-safe-epoch、cancel、invalid result 继续 checkpoint-safe。
- HistoryRead same-session ownership、opaque ref validation、bounded pagination、cross-session/path denial。
- 保持 ToolResultRead、Permission/Tool FIFO 与大 Tool Result 行为不回退。

## 禁止

- 不实现 Memory、semantic search、embedding、cross-session history、Timeline GC、Artifact lifecycle。
- 不使用 summary-of-summary，不创建通用 History Repository/Manager/Index。
- 不修改 Command/TUI/status、Runtime recovery 或独立模型决策。
- 不执行 Git 写入或归档。

## 验证

逐项执行 Task 5 Checklist；测试必须证明 L5 request provenance 来自 raw Transcript，并覆盖 malformed/cross-session ref、bounded page、no-safe-epoch 与 ToolResultRead regression。

## Feedback

首次创建 `feedback/W05-l5-history-read-feedback.md`。说明 epoch/coverage、raw provenance、HistoryRead 安全边界、修改文件、精确测试、Checklist 状态、差异、风险与清理。
