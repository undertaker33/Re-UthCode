# W02 Transcript / Timeline / Session v2 Worker Prompt

## 任务范围与顺序

在 W01 已完成并可用后，只执行 Task 2：Transcript / Timeline Contract 与 Session v2。完成 Feedback 后停止，不提前实现 Context logical view 或真实 L4/L5。

## 必须读取

1. `AGENTS.md`、`docs/README.md`、`docs/Context-Index.md`
2. `docs/rules/WorkPackageRules.md`
3. 本工作包原始需求、Spec、Tasks、Checklist
4. `docs/context/A03-State/State-Context.md`
5. W01 Feedback
6. Task 2 列出的源码与测试，重点完整理解现有 Session writer append/fsync/reconciliation/quarantine

使用 Conda 环境 `re-uthcode`。工作包已冻结；不得改写冻结文档，只能勾选 Task 2 已满足复选框并创建/追加本 Worker Feedback。

## 已确认决策

- Transcript 是 current Session raw durable closed semantic fact authority。
- Timeline 物理 append-only，产品记录只允许 SemanticEntry、EpochMacroSummary、ActiveCheckpoint 三类。
- Compact Epoch 是 checkpoint 边界推导概念，不是第四种记录。
- 每个 L4/L5 transaction 最后提交 ActiveCheckpoint；loader 只采用 latest valid checkpoint 之前的记录。
- Session schema 硬切；旧 `history.jsonl` 不迁移、不 dual read/write、不加兼容层。
- `runtime.jsonl` 可保留，但不成为 Context/Run/Compact recovery authority。

## 修改范围

仅修改 Tasks Task 2 列出的文件；新增 `tests/test_timeline_contract.py`。机械 export/import 跟随允许，其他 Application/Context/Command 文件禁止修改。

## 必须交付

- Core Transcript/Timeline/ref/checkpoint contract 与严格校验。
- fresh Session v2 文件布局与 deterministic old-schema rejection。
- Transcript strict sequence、stable range、same-Session ownership、complete Tool semantic group。
- checkpoint-last Timeline append/recovery；trailing entries、partial line 不进入 logical committed view。
- 继续满足 single writer、durability unknown quarantine、close/reopen recovery，不把异常当成未写而盲重试。

## 禁止

- 不实现 L4 caller、L5、HistoryRead、Budget Gate、manual compact 或 async AgentLoop。
- 不把 stable ref 变成路径；不实现 Timeline GC 或 Runtime checkpoint。
- 不保留 Projection authority、Session v1 新写入或 compatibility alias。
- 不执行 Git 写入或归档。

## 验证

逐项执行 Task 2 Checklist；至少运行 history、timeline、session files 与 architecture tests。验证 partial JSON、incomplete Tool group、checkpoint crash、single writer、old schema incompatibility 和 unknown durability。

## Feedback

首次创建 `feedback/W02-transcript-timeline-session-v2-feedback.md`。说明硬切后的文件布局、三记录 contract、checkpoint recovery、writer safety、修改文件、精确测试、Checklist 状态、差异、风险和遗留清理。
