# W02 Transcript / Timeline / Session v2 Worker Prompt

## 任务范围与顺序

W01完成后只执行Task 2“Transcript / Timeline 与 Session v2 持久事实”。完成Feedback后停止，不实现Compiler dual gate或L4/L5。

## 必须读取

`AGENTS.md`、文档路由、Context Index、WorkPackageRules、本工作包四文件、A03 Context、W01 Feedback、Task 2源码/测试；完整理解现有Session writer append/fsync/reconciliation/quarantine。使用`re-uthcode`。

必须逐一读取：`core/history.py`、`core/prompt.py`、`core/__init__.py`、`application/history.py`、`application/sessions.py`、`integrations/session_files.py`、`tests/test_history_contract.py`、`tests/test_session_files.py`及W01新增budget contracts。

工作包已冻结；只勾选既有Task 2 Checklist并创建/追加本Worker Feedback。

## 冻结决策

- Transcript是current Session raw durable closed facts。
- Timeline只含SemanticEntry、EpochMacroSummary、ActiveCheckpoint；Epoch由checkpoint边界推导。
- L4/L5 transaction最后提交ActiveCheckpoint；只采用latest valid checkpoint前的logical state。
- old `history.jsonl`不迁移、不dual read/write、不兼容。
- runtime log不成为Context/Run/Compact authority。
- D1：L4/L5复用当前主Provider/model，无独立compaction model；本Worker不实现model call。
- D2：未来B′只用`1..N` bounded catch-up与checkpoint重算，无持久Compact FSM。
- D3：Auto proactive与Hard send safety分离，Working Headroom adaptive + absolute cap；本Worker只提供后续Gate所需的durable facts。

## 修改范围与交付

仅Task 2文件并新增`tests/test_timeline_contract.py`。交付Core contracts、fresh Session v2布局、strict sequence、complete Tool group、checkpoint-last recovery、old-schema reject与writer safety。

## 禁止

不实现Gate、L4/L5、HistoryRead、manual compact、Runtime checkpoint、Timeline GC、路径ref、compat alias或Git写入。

## 验证与Feedback

执行Task 2 Checklist与architecture tests。创建`feedback/W02-transcript-timeline-v2-feedback.md`，记录布局、三record contract、checkpoint recovery、writer safety、文件、精确测试、Checklist、差异、风险与cleanup。
