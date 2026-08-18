# W04 L4 Proactive Compaction / Bounded Catch-up Worker Prompt

## 任务范围与顺序

W01～W03完成后只执行Task 4“L4 proactive semantic compaction 与 B′”。完成Feedback后停止；L5、HistoryRead、manual command由后续Worker负责。

## 必须读取

全局规则、WorkPackageRules、本工作包四文件、A01/A03/A04 Context、W01～W03 Feedback、Task 4源码与测试。使用`re-uthcode`。

必须逐一读取：`core/context.py`、`core/agent.py`（只核对既有awaitable/overflow合同）、`application/context.py`、`application/generation.py`、`application/sessions.py`、`tests/test_context_compaction.py`、`tests/test_context_budget_gate.py`、`tests/test_application_runs.py`、`tests/test_t09_1_context_protocol_e2e.py`（存在时）。

冻结文档不得改写；只勾选Task 4现有项并创建/追加Feedback。

## 冻结决策

- D1：active Turn使用冻结provider/model/C；compact request独立prompt/budget、无Agent Tools、不跨Provider fallback。
- D2：真实pressure后执行`1..N` bounded raw epochs；每批entries→checkpoint→rebuild/re-gate；attempt只在调用栈，无FSM。
- D3：L1-L3后仍高于Auto Gate必须L4；L4目标为retained profile；breaker后Hard safe记录`auto_pressure_unresolved`并发送，Hard unsafe拒绝。
- 每个L4内部model call自身通过Hard Gate；Provider count仍有uncertainty。

## 修改范围与交付

仅Task 4文件，新增E2E的L4初始范围。复用现有awaitable preparer与one-retry guard；原则上不改`core/agent.py`。交付async tool-free L4、parse/validate、checkpoint-last、single/multi epoch、retained target、cancel/crash/no-progress breaker。

## 禁止

不实现L5、HistoryRead、manual命令、docs收口、CompactionJob/CompactState/background worker/independent model、Runtime recovery、Memory、Timeline GC或Git写入。

## 验证与Feedback

执行Task 4 Checklist；记录call/epoch/coverage/checkpoint顺序和Auto/Hard终态。创建`feedback/W04-l4-proactive-catchup-feedback.md`，以简短教程说明调用流与无FSM恢复依据。
