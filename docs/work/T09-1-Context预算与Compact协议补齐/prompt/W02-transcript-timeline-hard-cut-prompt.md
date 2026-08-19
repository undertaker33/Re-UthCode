# W02 Worker Prompt：Transcript/Timeline 与 Session v2 一次性硬切

你负责执行 T09-1 的 T02。前置 T01 必须已完成并有 Feedback；否则停止。不得执行 T03～T08，不做 Git 写入或归档。

## 实施起点与事实核对

以用户实际派发本 Prompt 时的当前仓库状态为实施起点，不要求 HEAD 等于任何固定 SHA，也不要求 checkout 历史 Commit。完整读取前置 W01 Feedback 与下列文件后，必须重新核对当前真实 `src/ + tests/` 与冻结任务定义；只有源码实质变化已经使产品语义、架构边界或 T02 hard-cut 完成范围失效时，才停止相关范围并按 Feedback 规则报告。普通后续 Commit、Feedback 追加或 Checklist 勾选不构成基线冲突。

## 开始前必须完整读取

1. `AGENTS.md`、`docs/README.md`、`docs/Context-Index.md`、`docs/rules/WorkPackageRules.md`
2. T09-1 任务书、Spec、Tasks、Checklist、W01 Feedback
3. `core/history.py`、`core/context.py`、`core/prompt.py`、`application/history.py`、`application/context.py`、`application/generation.py`、`application/sessions.py`、`integrations/session_files.py` 及所有 `CanonicalHistory|Projection|history.jsonl` 调用方与测试

## 目标与完成边界

一次性建立 Transcript/Timeline/Session v2，并迁移所有生产 Compiler/Application/Integration 调用方；同一任务删除旧 authority。禁止只定义新 DTO 或 store、却把正式 callers 留在旧 Projection。

## 冻结语义

- Transcript 是 current Session closed raw semantic fact authority；不保存 open continuation。
- Timeline 产品记录恰为 Fine semantic entry、Epoch macro summary、Active checkpoint 三类。
- 派生 records 先写，checkpoint 最后写；loader 只认最后有效 checkpoint，忽略 trailing incomplete transaction。
- fresh Session 只写 `transcript.jsonl`、`timeline.jsonl`、`runtime.jsonl`、metadata、lock、tool-results。
- old v1 `history.jsonl` 明确 incompatible；不迁移、不双读写、不 alias/wrapper compatibility。
- strict sequence、完整 ToolCall/ToolResult group、single writer、append/fsync、metadata-last、reconciliation、quarantine、close/reopen 必须保留。

## 实施要求

- 先用 `rg` 列全生产/测试 callers，按 authority→store→Application→Compiler→tests 的顺序硬切。
- 删除 `CanonicalHistory`、`Projection` 的生产 contract/export 和旧 writer；old-v1 fixture 只能用于证明 incompatible。
- T01 动态 limits/Gate/L1-L3 行为必须保持通过；不得实现 T03 L4 或未来命令。
- 未知 durability 继续 fail closed，不盲目 retry。

## 验证与反馈

执行 Checklist T02 命令、T01 关键回归和架构测试。勾选真实完成项，并写：

`docs/work/T09-1-Context预算与Compact协议补齐/feedback/W02-transcript-timeline-hard-cut-feedback.md`

记录实际 layout、旧 v1 错误行为、扫描残留、精确测试统计、未验证项和风险。需扩大范围时停止并反馈。
