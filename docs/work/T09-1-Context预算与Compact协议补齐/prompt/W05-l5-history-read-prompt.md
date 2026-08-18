# W05 L5 Independent Aging / HistoryRead Worker Prompt

## 任务范围与顺序

W01～W04完成后只执行Task 5“L5独立老化与 HistoryRead”。完成Feedback后停止，不接manual command或最终文档。

## 必须读取

全局规则、WorkPackageRules、本工作包四文件、A01/A03 Context、W01～W04 Feedback、Task 5源码测试、现有ToolResultRead/default tool composition。使用`re-uthcode`。

必须逐一读取：`application/context.py`、`application/tools.py`、`application/bootstrap.py`、`integrations/tools/factory.py`、现有`integrations/tools/tool_result_read.py`、`tests/test_timeline_contract.py`、`tests/test_context_compaction.py`、`tests/test_application_tools.py`、`tests/test_tool_result_persistence.py`、`tests/test_context_budget_gate.py`。

冻结文档不得改写；只勾选Task 5现有项并创建/追加Feedback。

## 冻结决策

- D1：L5使用当前主模型，内部request无Agent Tools并通过Hard Gate。
- D2：无Compact FSM。
- D3：L5 Fine Timeline pressure独立于Auto/Hard pressure。
- L5只选择old complete epoch并重读raw Transcript refs；不做summary-of-summary。
- HistoryRead current Session only、opaque exact ref、bounded、read-only、no path/search/cross-session。

## 修改范围与交付

仅Task 5文件，新增HistoryRead实现与测试。交付Fine pressure trigger、raw provenance、macro+checkpoint、logical supersession、no-safe-epoch和安全reader；保持ToolResultRead/Permission/FIFO不回退。

## 禁止

不实现Memory/retrieval/embedding、cross-session history、Timeline GC、通用Repository/Index、Command/TUI、Runtime recovery或Git写入。

## 验证与Feedback

执行Task 5 Checklist，证明L5在无Auto/Hard pressure下可触发且input来自raw evidence。创建`feedback/W05-l5-history-read-feedback.md`，记录epoch/coverage、安全边界、文件、精确测试、Checklist、差异、风险与cleanup。
