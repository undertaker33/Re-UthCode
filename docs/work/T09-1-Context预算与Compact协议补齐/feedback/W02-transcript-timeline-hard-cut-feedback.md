# W02：Transcript、Timeline 与 Session v2 一次性硬切 Feedback

## 交付结论

W02 已按 Prompt 完成。T02 Checklist 七项均已取得源码或测试证据并勾选；T03～T08 未实施，未执行 Git 写入、提交、推送或工作包归档。

本次采用一次性 hard cut：Transcript/Timeline 成为当前 authority，Application、Context Compiler 和 Session store 全部迁移到 v2；不保留旧 Projection、旧 writer 或双轨兼容层，避免同一 Session 同时存在两套语义。

## 实际完成

- Core 建立 `Transcript`、`TranscriptEntry`、`SemanticUnit`、opaque `TranscriptRef`，以及仅包含 `SemanticEntry`（Fine）、`EpochMacroSummary`（Macro）、`ActiveCheckpoint` 三类产品记录的 `Timeline`。
- Transcript 强制 Session ownership、严格连续 sequence、closed semantic fact，以及 ToolCall/ToolResult ID 集合完整匹配；open continuation 不进入 durable Transcript。
- Timeline transaction 按“derived records 先写、ActiveCheckpoint 最后写”组织。加载时只把最新有效 checkpoint 之前的完整事务作为 logical state；checkpoint 前崩溃留下的 trailing records 保留物理可审计性但不生效。
- Session v2 fresh layout 固定为：

  ```text
  transcript.jsonl
  timeline.jsonl
  runtime.jsonl
  metadata.json
  writer.lock
  tool-results/
  ```

- store 保留 single writer、append/fsync、metadata-last、sequence/identity reconciliation、unknown durability quarantine、半失败恢复和 close/reopen 行为。
- 旧 v1 `history.jsonl` 或 schema version 1 会明确抛出 `SessionIncompatibleError`，不迁移、不双读写、不提供 alias/wrapper compatibility。
- Context Compiler、Application history/context/generation/sessions、命令状态展示和 Integration Session store 均改用 Transcript/Timeline；W01 的动态 limits、Hard Gate 与 L1-L3 行为保持不变，未实现 T03 L4。

## 主要文件范围

- Core：`src/uthcode/core/history.py`、`src/uthcode/core/context.py`、`src/uthcode/core/prompt.py`、`src/uthcode/core/__init__.py`。
- Application：`src/uthcode/application/history.py`、`src/uthcode/application/context.py`、`src/uthcode/application/generation.py`、`src/uthcode/application/sessions.py`、`src/uthcode/application/commands/builtins.py`。
- Integration：`src/uthcode/integrations/session_files.py`。
- 合同与回归：`tests/test_history_contract.py`、新增 `tests/test_timeline_contract.py`、`tests/test_context_compiler.py`、`tests/test_context_compaction.py`、`tests/test_session_files.py`、`tests/test_w04_session_commands.py`、`tests/test_w05_diagnostics.py`、`tests/test_w06_integration_delivery.py`、`tests/test_architecture_boundaries.py`、`tests/test_project_instructions.py`。

其中 `tests/test_history_contract.py` 的消息转换断言改为比较稳定的语义字段，不把每次转换生成的 wall-clock `created_at` 当作身份；这只消除测试非确定性，不改变生产语义。

## 验证证据

以下命令均使用 Conda 环境 `re-uthcode`：

```text
conda run --no-capture-output -n re-uthcode python -m pytest tests/test_history_contract.py tests/test_timeline_contract.py tests/test_context_compiler.py tests/test_context_compaction.py tests/test_session_files.py tests/test_application_runtime.py tests/test_application_runs.py tests/test_w04_session_commands.py -q
93 passed in 8.43s

conda run --no-capture-output -n re-uthcode python -m pytest tests/test_w05_diagnostics.py tests/test_w06_integration_delivery.py tests/test_architecture_boundaries.py tests/test_project_instructions.py -q
47 passed in 6.58s

conda run --no-capture-output -n re-uthcode python -m pytest -q --deselect tests/test_tui.py::test_plan_revisions_and_task_state_append_as_distinct_permanent_blocks --deselect tests/test_tui.py::test_renderer_restores_roles_surfaces_markdown_and_code_colours --deselect tests/test_tui.py::test_tool_rows_keep_status_text_and_semantic_colour
1199 passed, 3 skipped, 3 deselected in 107.66s (0:01:47)

conda run --no-capture-output -n re-uthcode python -m pytest tests/test_tui.py -q
69 passed, 3 failed in 8.98s
```

未通过的三条 TUI 测试与 W01 已记录的 ANSI truecolor 断言相同：

- `test_plan_revisions_and_task_state_append_as_distinct_permanent_blocks`
- `test_renderer_restores_roles_surfaces_markdown_and_code_colours`
- `test_tool_rows_keep_status_text_and_semantic_colour`

本 W02 未修改 `src/uthcode/interfaces/tui/terminal.py`，也未把这三条失败描述为通过；排除它们后的全量回归已通过。

## 残留扫描

- `CanonicalHistory`、`HistoryEntry`、`HistoryKind`、`HISTORY_SCHEMA_VERSION`、`HistoryProjectionSource`、`ProjectionAppendOutcome`、`HistoryAppendOutcome`、`projection_revision`、`canonical_history`、`append_history`、`append_projection`：`src/` 与 `tests/` 无命中。
- `ContextAuthority.HISTORY_PROJECTION`、`ContextSourceKind.PROJECTION`、`HistoryProjectionSource`：`src/` 与 `tests/` 无命中。
- `rg -n "\bProjection\b|\bCanonicalHistory\b|history\.jsonl" src/uthcode tests` 仅命中 `history.jsonl` 的三处预期证据：`session_files.py` 的旧 v1 incompatible 检测，以及两个断言新 Session 不创建旧文件；没有旧 writer 或生产兼容 contract。
- Timeline 产品 record 仅保留 Fine、Macro、Active checkpoint；未引入持久 Compact FSM、Job、pointer、跨 Provider fallback 或独立 Manager/Registry/Scheduler。

## 未完成项、风险与边界

- T03～T08 的 L4/L5、正式 Compact 生命周期、HistoryRead、端到端命令收口、遗留负担清理和文档全包验收不属于 W02，未实施。
- 三条 TUI ANSI truecolor 测试仍失败，原因和 W01 一致；修复它们需要扩大到 TUI renderer 范围，留待相应工作包处理。
- 未执行真实 Provider 网络调用；本次验证使用现有 fake/provider test doubles，W01 的动态 limits/Gate 回归仍由当前测试集合覆盖。
- 未执行任何 Git commit、push、merge、rebase、tag、release 或工作包归档。工作区中已有的 `AGENTS.md` 及其它非 W02 改动未被清理或覆盖。

## Artifact 索引

- Checklist：`docs/work/T09-1-Context预算与Compact协议补齐/T09-1-Context预算与Compact协议补齐-checklist.md`
- 本 Feedback：`docs/work/T09-1-Context预算与Compact协议补齐/feedback/W02-transcript-timeline-hard-cut-feedback.md`
- W02 关键合同测试：`tests/test_history_contract.py`、`tests/test_timeline_contract.py`、`tests/test_session_files.py`

## W02 第一次验收返工

### 验收问题与根因

1. Timeline trailing transaction 复活的根因是 logical view 只按最新 checkpoint 的物理前缀计算。checkpoint 前已落盘但未提交的 derived records 虽然首次加载时被识别为 trailing，仍留在 `Timeline.records`；后续追加的新 transaction 使用新的 checkpoint 时，旧 trailing 被物理前缀重新吸收。
2. 非 Tool open continuation 的根因是 `_recoverable_incomplete_unit` 将没有 ToolCall/ToolResult 的 incomplete semantic unit 也视为可恢复。于是 `commit_boundary=False` 的普通消息先被写入并报告 durable，reopen 时才被截断，造成写入结果与恢复结果不一致。
3. 半失败/reconciliation 覆盖不足的根因是 `tests/test_session_files.py` 被缩减为少量 v2 基础测试，原有真实 append、reload、metadata 和未知落盘结果异常路径没有以 Transcript/Timeline v2 API 等价恢复；仅手工调用 quarantine 不能证明 unknown durability 的真实入口。

### 本次修复语义

- Timeline 在仍然只有 Fine `SemanticEntry`、Macro `EpochMacroSummary`、`ActiveCheckpoint` 三种产品 record 的前提下，为同一 append transaction 的现有记录携带同一 transaction identity。derived records 先写，checkpoint 仍最后写。logical committed view 只纳入以对应 checkpoint 结束的 transaction group；checkpoint 前崩溃留下的旧 trailing 可以继续保留为物理审计事实，但永久不进入 committed view。reopen 后的新 transaction 使用新的 identity，因此旧 trailing 不会混入或被后续 checkpoint 提交；没有伪造 checkpoint、删除 Timeline 或静默重写历史。
- 非 Tool 的 `commit_boundary=False`/open continuation 在写入前明确拒绝，抛出受控 `SessionFileError`；拒绝路径不增加文件内容或内存 snapshot。普通 closed message 仍正常 durable。跨 writer/process boundary 的 incomplete ToolCall 仍可保留，但只能由同一 semantic unit 中匹配且未重复的 ToolResult 闭合；不匹配、重复、缺少对应 ToolCall 或含非 Tool open fragment 的结果均失败。

### 补回的半失败与 reconciliation 测试

- Transcript 与 Timeline 分别覆盖：append 已 fsync 后报告异常但实际 durable；reload 异常后从磁盘 reconciliation；metadata touch/sync 异常但数据 durable；append 未写入的确定性 `not_durable`；真实 append 写入额外有效记录后结果不确定的 `unknown`。
- 每个 append outcome 均断言 durable/not_durable/unknown、`reload_succeeded`、`metadata_synced` 与 `failure_stage`；真实 unknown 路径会 quarantine 并阻止继续写入，close/reopen 后解除 quarantine 并从真实磁盘状态继续。
- 补回 trailing transaction 的 crash/reopen/新 transaction/再次 reopen 回归；非 Tool open continuation 的文件与内存不变回归；closed message；ToolCall 跨 boundary 后 matching ToolResult；mismatched ToolResult 不写入；incomplete byte/semantic tail；middle corruption fail closed；single writer/busy；Session identity、sequence、project ownership 与 Timeline ref ownership 校验。

### 实际修改文件

- `src/uthcode/core/history.py`
- `src/uthcode/integrations/session_files.py`
- `tests/test_timeline_contract.py`
- `tests/test_session_files.py`
- 本 Feedback 文件仅在原记录末尾追加本章节。

本次返工未修改 Application 文件；Checklist 的文字、结构、编号、顺序和七项已勾选状态保持不变。未处理 `AGENTS.md` 和 `docs/core-design` 下的用户改动，也未清理、覆盖、暂存或回退其它既有工作区修改。

### 验证命令与结果

- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_history_contract.py tests/test_timeline_contract.py tests/test_session_files.py -q`：29 passed。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_history_contract.py tests/test_timeline_contract.py tests/test_context_compiler.py tests/test_context_compaction.py tests/test_session_files.py tests/test_application_runtime.py tests/test_application_runs.py tests/test_w04_session_commands.py -q`：110 passed。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_w05_diagnostics.py tests/test_w06_integration_delivery.py tests/test_architecture_boundaries.py tests/test_project_instructions.py -q`：47 passed。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_provider_model_limits.py tests/test_context_budget_gate.py -q`：23 passed。
- `conda run --no-capture-output -n re-uthcode python -m pytest -q --deselect tests/test_tui.py::test_plan_revisions_and_task_state_append_as_distinct_permanent_blocks --deselect tests/test_tui.py::test_renderer_restores_roles_surfaces_markdown_and_code_colours --deselect tests/test_tui.py::test_tool_rows_keep_status_text_and_semantic_colour`：1216 passed，3 skipped，3 deselected。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_tui.py -q`：69 passed，3 failed。失败仍为既有 ANSI truecolor 断言：`test_plan_revisions_and_task_state_append_as_distinct_permanent_blocks`、`test_renderer_restores_roles_surfaces_markdown_and_code_colours`、`test_tool_rows_keep_status_text_and_semantic_colour`；本次未修改 TUI renderer。
- `git diff --check`：通过；仅输出工作区既有的 LF/CRLF 转换提示，无 whitespace error。
- Checklist 与本 Feedback 均通过 UTF-8、replacement character 和 Markdown fence 检查；无 replacement character，fence 数量为偶数。

### 残留扫描

执行 `rg -n "\bProjection\b|\bCanonicalHistory\b|history\.jsonl" src/uthcode tests`，仅有三处预期 `history.jsonl` 证据：`src/uthcode/integrations/session_files.py:382` 的 old-v1 incompatible 检测，以及 `tests/test_session_files.py:35`、`tests/test_w06_integration_delivery.py:72` 的新 Session 不创建旧文件断言。没有旧 Projection/CanonicalHistory writer 或兼容 alias 命中。

### 未验证项与范围边界

- 未执行真实 Provider 网络调用；本次使用现有 fake/provider test doubles。
- 三条完整 TUI ANSI 测试仍失败，修复需要扩大到 TUI renderer 范围，留待相应任务处理。
- 明确未实施 T03～T08，不重新设计 Transcript、Timeline 或 Session v2，不修改 T01～T08 冻结任务定义。
- 未执行 Git commit、push、PR、merge、rebase、tag、release 或工作包归档，等待重新验收。

## W02 第二次验收返工

本次验收发现的根因是：`SemanticUnit.complete` 在同一 semantic unit 存在 ToolCall/ToolResult 时只校验 Tool ID 集合是否完整匹配，未同时校验该 unit 内其它非 Tool entry 的 `commit_boundary`。因此，`commit_boundary=False` 的普通消息可以被一组匹配的 ToolCall/ToolResult 掩盖，并被错误判定为 complete、以 durable Transcript 写入并在 reopen 后保留。

修复为：`SemanticUnit.complete` 必须同时满足两项条件：所有非 Tool entry 均已闭合（`commit_boundary=True`），且 ToolCall/ToolResult 的 ID 非空、唯一并完整匹配。Session writer 因此会在写入前拒绝“非 Tool open continuation + 匹配 Tool pair”组合，不增加内存 snapshot 或磁盘记录。

新增两条组合回归测试：

- `test_matching_tool_pair_does_not_close_a_non_tool_open_entry`：验证 Core semantic unit 不会被匹配 Tool pair 错误闭合，并拒绝跨越该 open entry 的 TranscriptRef。
- `test_non_tool_open_continuation_cannot_hide_in_a_matching_tool_pair`：验证 Session v2 append 写入前失败，文件、内存 snapshot 与 close/reopen 结果均保持 0 条记录。

最新精确验证结果：

- W02：`112 passed`。
- 架构/诊断/集成：`47 passed`。
- W01：`23 passed`。
- 全量排除三条已知 ANSI 测试：`1218 passed, 3 skipped, 3 deselected`。
- 残留扫描、UTF-8、Markdown fence 与 `git diff --check`：通过。

本次未修改 T03～T08、未修改用户已有文件（包括 `AGENTS.md` 与 `docs/core-design` 下的用户改动），未改写既有 Feedback 章节，未执行 Git commit、push、PR、merge、rebase、tag、release 或其它 Git 写操作。
