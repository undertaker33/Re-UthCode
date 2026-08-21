# W05：Application / Interface / Integration Feedback

## 执行范围

本次按 W05 Prompt 只执行 T05、T06；T01～T04 的既有 Feedback 与 Checklist 状态已核对。未执行 T07、T08、Git 写入或工作包归档。仓库中用户已有的 A04 文档与 PNG 未修改、未暂存。

## 已实施内容

- `src/uthcode/application/runs.py`
  - 为 AgentRun 增加 Session 级 durable message cursor。
  - 在每次 request preparation 前持久化新闭合 Message；工具批次完成后在下一次 Provider call 前落盘；终止时补齐 terminal tail。
  - 失败批次保留原 `session_id`、`turn_id` 与 Message identity，按 FIFO 重试；unknown durability 标记 pending batch 并阻断新 Turn。
  - terminal batch 只在整批闭合后计入 `committed_turns`，避免增量 append 重复计数。

- `src/uthcode/application/generation.py`
  - 删除生产路径中的同步 `compact_session` 占位调用，接入 `async compact_session()`。
  - manual、自动 L4、L5 和 Provider overflow recovery 共用 tool-free、独立 Hard Gate 的 Provider compaction request helper。
  - overflow handler 改为 awaitable；Core 既有“一次 retry”协议负责第二次 overflow 的 fail-closed。
  - active Turn 在进入 Core 前冻结 Provider、model、配置 input limit、Provider input/output/combined limits、tools 与 reasoning；后续 model 切换只影响下一 Turn。
  - Application diagnostics 暴露分维 Context budget、request accounting、Gate、Pressure、count fallback 与 compaction outcome。

- `src/uthcode/application/context.py`
  - 增加当前 Turn 的 Context projection 边界：durable Transcript 中的当前 Turn 不被当作可选旧历史重复计入，process-local current Turn 仍保留在 Provider-visible tail。
  - 为已经 Hard-gated 的 request 保留可供 `/status` 使用的安全维度诊断。

- `src/uthcode/application/commands/dispatcher.py`、`models.py`、`builtins.py`、`src/uthcode/interfaces/tui/app.py`
  - Dispatcher 新增 `dispatch_async` / `dispatch_text_async`，同步入口遇到 awaitable 时保持错误边界，原 sync command 行为不变。
  - `/compact` await Application 的同一 compaction orchestrator；低压无候选返回成功 no-op。
  - `/status` 输出 configured/provider/effective limits、output/combined limit、Hard/Auto Gate、count source、Pressure 与 compact outcome；不输出 Transcript、summary、Tool Result 或凭据。
  - TUI 只等待 structured command outcome，不新增 Context 编排。

## 关键边界与 Provider call 证据

| 场景 | Provider call 结果 |
| --- | --- |
| ordinary + unknown tool batch | 第一次 ordinary call 前已有 user fact；第二次 ordinary call 前已有 assistant ToolCall 与 ToolResult；terminal assistant 在结束边界追加；无重复 message identity |
| manual compact 低压 | 第一次 `compact_session()`：1 次 tool-free compact call；第二次无候选：0 次额外 Provider call，Timeline 不新增垃圾记录 |
| ordinary overflow 一次 | ordinary 2 次、compact 1 次；compact request `tools=()` 且 `context_gate.hard_safe=True`；两次 ordinary 使用同一 frozen budget |
| ordinary overflow 两次 | ordinary 2 次、compact 1 次；第二次 overflow 后停止，不改变 frozen limits |
| deterministic Transcript append failure | Provider call 0 次；同一批次执行两次 persistence attempt，`session_id`、`turn_id`、Message tuple 完全一致 |
| unknown durability | Provider call 0 次；Session quarantine，后续新 Run 被拒绝 |

所有正式 Provider-visible compaction request 均经过 `_prepare_compaction_request_async`；ordinary request 继续经过既有 count → rebuild → final Hard Gate 链。

## 验证结果

以下命令均使用 `re-uthcode` Conda 环境。

1. T05 精确回归：

   ```text
   conda run --no-capture-output -n re-uthcode python -m pytest tests/test_application_runtime.py tests/test_application_runs.py tests/test_session_files.py tests/test_t09_1_context_protocol_e2e.py -q
   ```

   结果：`99 passed in 9.69s`。

2. T06 精确回归：

   ```text
   conda run --no-capture-output -n re-uthcode python -m pytest tests/test_command_dispatcher.py tests/test_w04_session_commands.py tests/test_cli.py tests/test_tui.py tests/test_application_runtime.py tests/test_t09_1_context_protocol_e2e.py -q
   ```

   结果：`155 passed, 3 failed in 25.48s`。3 个失败均为既有 Rich ANSI truecolor 断言：

   - `test_plan_revisions_and_task_state_append_as_distinct_permanent_blocks`
   - `test_renderer_restores_roles_surfaces_markdown_and_code_colours`
   - `test_tool_rows_keep_status_text_and_semantic_colour`

   本次未修改 `src/uthcode/interfaces/tui/rendering.py` 或相关颜色实现；T06 Checklist 的“精确命令全部通过”保持未勾选。

3. request preparer、overflow、cancel/error 与架构边界：

   ```text
   conda run --no-capture-output -n re-uthcode pytest tests/test_agent_loop.py tests/test_architecture_boundaries.py tests/test_application_runtime.py tests/test_command_dispatcher.py -q
   ```

   结果：`113 passed in 8.93s`。

4. 语法与 diff 检查：

   ```text
   conda run --no-capture-output -n re-uthcode python -m compileall -q src tests
   git diff --check
   ```

   两条命令均通过；`git diff --check` 仅报告 Windows 工作区的 LF/CRLF 转换提示，无 whitespace error。

5. 文档编码：Checklist 写回前确认 UTF-8 解码成功且无 replacement character/常见乱码；写回后 W05 Feedback 与 Checklist 通过 UTF-8 guard，Markdown fence 平衡。

## 未验证项与风险

- T06 精确命令仍受上述 3 个既有 Rich ANSI 渲染断言失败影响；本次没有为此扩大到 TUI renderer 修复。
- 按 W05 冻结边界未执行 T07 diagnostics/Eval/全量文档同步，也未执行 T08 遗留负担清理。
- 未执行真实网络 Provider；compact/overflow/持久化边界均使用离线测试 Provider 与 Session store。
- 未执行 commit、push、merge、rebase、tag、release 或归档。

## W05 第一次验收返工

### 返工范围与根因

本轮只修复验收确认的两个问题，未重新探索 Context Budget / Compact 主体架构，未实施 T07/T08，也没有修改 T05/T06 Checklist 的文字、结构、编号或顺序。

1. Active Turn 的闭合事实在 ordinary request preparation 前已经 durable append，但 L4、L5 和 overflow recovery 仍把完整 active Session Transcript 直接交给 compactor。当前 user message 或当前 Turn 的 ToolCall/ToolResult 因暂时表现为完整 semantic unit 而被选入 Fine；terminal assistant 随后使用同一 `turn_id` / `semantic_unit_id` 扩展该 unit，原 Fine ref 仍指向旧范围，最终形成 `Transcript range splits a semantic unit`，破坏 close/reload。
2. L4/L5 candidate 已有统一的 `input_tokens`、`output_tokens`，但 candidate 构建后没有严格 reduction gate，导致 `output_tokens >= input_tokens` 的合法 summary 仍可进入 Timeline append，手动 compact 产生无价值 Fine、Macro 或 checkpoint。

### 实际修复边界

- `ApplicationContextService.stable_transcript_for_compaction()` 按稳定 `active_turn_id` 找出整个 active Turn，并要求该 identity 形成 Transcript suffix；只有通过该 identity/suffix 校验后才保留稳定历史前缀。没有按最后一条 Message、角色、序号猜测或删除范围。
- ordinary Context 仍使用同一稳定历史前缀，再合并 process-local current Turn projection，因此当前 user/tool facts 仍进入 ordinary Provider request。该修复没有改变 closed-fact persistence 的三个时点：first Provider call 前 user fact、complete ToolCall + ToolResult 后/next Provider call 前、terminal assistant tail 结束边界仍原样 durable append；durable cursor、FIFO retry、unknown durability quarantine 也未改变。
- active Turn 的 `turn_id` 现在传入自动 L4、Provider overflow recovery 和 L5 aging；因此当前 Turn 不进入 L4 raw evidence，也不能被 L5 通过既有 Fine 间接覆盖。L5 仍只从已提交 Fine 的 raw Transcript refs 取证。manual compact 只在 idle Session 使用，不传 active identity；terminal 后完整 semantic unit 才能在后续 Turn 或 idle manual compact 中成为 raw evidence。
- candidate 只有严格满足 `output_tokens < input_tokens` 才可继续 commit。`==` 和 `>` 均转换为不提交的 `failure="no_reduction"`，丢弃候选 Timeline/batches，不调用 commit；判断复用 compactor 已计算的 token estimator/accounting 事实，没有使用 summary 字符数。
- manual `compact_session()` 将 `no_reduction` 与无候选 `no_safe_epoch` 归一化为 `changed=False, failure=None`，所以 `/compact` 返回成功的“无需压缩/无变化”。Auto L4、L5 和 overflow recovery 保留 `no_reduction` 失败诊断，不报告 recovered/completed，不伪造 headroom，不进行第二次 retry；overflow ordinary retry 仍最多一次。

### close/reload 与 Timeline 证据

- overflow recovery：已有可压缩历史 `turn-1`，新 active Turn 的 user fact 先 durable append；第一次 ordinary 抛 `ContextOverflowError`，compact request 只覆盖 `turn-1`，Provider call 为 ordinary `2`、compact `1`，Fine `1`、Macro `0`、ActiveCheckpoint `1`。retry terminal 后 close，再 resume 同一 Session 成功；所有 committed refs 均用最终 Transcript `select(..., complete_only=True)` 解析，active Turn 不在 Fine coverage。
- 自动 L4：active Turn user fact 已在首次 ordinary preparation 前持久化；本次 fake Provider 实际产生 ordinary `1`、compact `1`，Fine `1`、Macro `0`、ActiveCheckpoint `1`。compact epoch 只包含之前稳定历史，active `turn_id` 不在 coverage；terminal 后 close/reload 成功，最终所有 Timeline refs 均为完整 semantic boundary。
- post-tool overflow：第二次 ordinary request 到达 Provider 前，active Turn 的 ToolCall 和 matched ToolResult 已在 durable Transcript 中；该次 overflow compact 仍只覆盖 `turn-1`。Provider call 为 ordinary `3`、compact `1`，Fine `1`、Macro `0`、ActiveCheckpoint `1`；terminal 后 close/reload 成功，active Turn 没有进入 compact coverage。
- L5 回归额外断言当前 active Turn 不在 `context_timeline_aging_epoch_turns`；L5 的 Macro 只来自既有 Fine raw refs，没有通过 active Turn 产生 Macro。

### non-reduction 与命令结果证据

- manual 大窗口合法 non-reduction：`output_tokens == input_tokens` 和 `output_tokens > input_tokens` 两种结构化结果均 commit `0` 次，physical/logical Timeline 保持原状，Fine/Macro/ActiveCheckpoint 均不新增；`/compact` Provider call 为 `1`，structured outcome 为 `SUCCESS`，输出“无需压缩”。
- manual 明显 reduction：既有成功路径仍为 compact `1`、`changed=True`，正常追加 Fine + ActiveCheckpoint；第二次无候选为 compact 增量 `0`、`changed=False, failure=None`，Timeline 不变。
- Auto non-reduction：compact `1`、ordinary `0`，不产生 Timeline record，diagnostics 保留 `no_reduction`，不报告 recovered/completed。
- overflow non-reduction：第一次 ordinary overflow 后 compact `1`，ordinary 总数仍为 `1`，没有 retry、Fine、Macro 或 checkpoint，diagnostics 保留 `no_reduction`。

### 本轮实际修改文件

- `src/uthcode/application/context.py`
- `src/uthcode/application/generation.py`
- `tests/test_t09_1_context_protocol_e2e.py`
- `tests/test_w04_session_commands.py`
- 本 Feedback 文件（仅在末尾追加本章节）

Checklist、Requirement、Spec、Tasks、Prompt 和 W01～W04 Feedback 未改写；工作区中此前已存在的 Checklist 勾选、W05 既有实现改动和 `docs/core-design/A04-Orchestration/` 用户文件均保留。本轮未实施 T07/T08，也未修改 A04 用户文件。

### 本轮新增/定向测试

```text
conda run --no-capture-output -n re-uthcode python -m pytest tests/test_t09_1_context_protocol_e2e.py::test_w05_context_overflow_recovers_once_then_retries_with_frozen_limits tests/test_t09_1_context_protocol_e2e.py::test_w05_post_tool_overflow_excludes_whole_active_turn_and_reloads tests/test_t09_1_context_protocol_e2e.py::test_l4_is_tool_free_bounded_and_commits_one_fine_entry_per_turn tests/test_t09_1_context_protocol_e2e.py::test_l4_equal_or_larger_output_is_a_non_committing_no_reduction tests/test_t09_1_context_protocol_e2e.py::test_w05_auto_non_reduction_is_not_recovered_or_committed tests/test_t09_1_context_protocol_e2e.py::test_w05_overflow_non_reduction_does_not_retry_or_commit tests/test_w04_session_commands.py::test_compact_command_reports_non_reducing_candidate_as_successful_noop -q
8 passed
```

### 要求的回归命令与准确结果

以下命令均使用 Conda `re-uthcode` 环境；测试使用 fake Provider / Session store，没有真实网络调用。

```text
conda run --no-capture-output -n re-uthcode python -m pytest tests/test_application_runtime.py tests/test_application_runs.py tests/test_session_files.py tests/test_t09_1_context_protocol_e2e.py -q
104 passed in 9.91s

conda run --no-capture-output -n re-uthcode python -m pytest tests/test_command_dispatcher.py tests/test_w04_session_commands.py tests/test_cli.py tests/test_tui.py tests/test_application_runtime.py tests/test_t09_1_context_protocol_e2e.py -q
161 passed, 3 failed in 25.98s
失败仍为三条既有 TUI ANSI truecolor 断言：
- tests/test_tui.py::test_plan_revisions_and_task_state_append_as_distinct_permanent_blocks
- tests/test_tui.py::test_renderer_restores_roles_surfaces_markdown_and_code_colours
- tests/test_tui.py::test_tool_rows_keep_status_text_and_semantic_colour

conda run --no-capture-output -n re-uthcode python -m pytest tests/test_command_dispatcher.py tests/test_w04_session_commands.py tests/test_cli.py tests/test_tui.py tests/test_application_runtime.py tests/test_t09_1_context_protocol_e2e.py -q --deselect tests/test_tui.py::test_plan_revisions_and_task_state_append_as_distinct_permanent_blocks --deselect tests/test_tui.py::test_renderer_restores_roles_surfaces_markdown_and_code_colours --deselect tests/test_tui.py::test_tool_rows_keep_status_text_and_semantic_colour
161 passed, 3 deselected in 24.51s

conda run --no-capture-output -n re-uthcode pytest tests/test_agent_loop.py tests/test_architecture_boundaries.py tests/test_application_runtime.py tests/test_command_dispatcher.py -q
113 passed in 9.13s

conda run --no-capture-output -n re-uthcode python -m pytest tests/test_session_files.py tests/test_timeline_contract.py tests/test_history_contract.py tests/test_t09_1_context_protocol_e2e.py::test_w05_context_overflow_recovers_once_then_retries_with_frozen_limits tests/test_t09_1_context_protocol_e2e.py::test_w05_post_tool_overflow_excludes_whole_active_turn_and_reloads tests/test_t09_1_context_protocol_e2e.py::test_l4_is_tool_free_bounded_and_commits_one_fine_entry_per_turn -q
34 passed in 2.21s

conda run --no-capture-output -n re-uthcode python -m pytest -q --deselect tests/test_tui.py::test_plan_revisions_and_task_state_append_as_distinct_permanent_blocks --deselect tests/test_tui.py::test_renderer_restores_roles_surfaces_markdown_and_code_colours --deselect tests/test_tui.py::test_tool_rows_keep_status_text_and_semantic_colour
1250 passed, 3 skipped, 3 deselected in 103.79s

conda run --no-capture-output -n re-uthcode python -m compileall -q src tests
通过

git diff --check
通过；仅有 Windows 工作区既有 LF/CRLF 转换提示，无 whitespace error
```

新增的 L5 active Turn 断言在上述 T05 定向回归之后补入，随后独立 L5/non-reduction 命令为 `4 passed in 1.24s`；不改变生产代码或冻结限制。完整全量结果中的三条排除项仍仅为用户指定的既有 ANSI 测试，没有扩大排除范围。

### 未验证项、风险与 Git 边界

- 未执行真实 Provider 网络调用；Provider input/output token 事实、overflow、L4/L5 和 reload 均由离线 fake Provider 与 Session store 验证。
- 三条既有 TUI ANSI truecolor 断言仍失败；本轮未修改 TUI renderer，也未新增排除项。
- 未执行 T07/T08、文档大范围同步、commit、push、merge、rebase、tag、release、归档、暂存或其它 Git 写操作。未修改 frozen limits、closed-fact persistence 时点、Transcript/Timeline/Session v2、Macro supersede、checkpoint-last、HistoryRead、A04 用户文件或其它范围外能力。
