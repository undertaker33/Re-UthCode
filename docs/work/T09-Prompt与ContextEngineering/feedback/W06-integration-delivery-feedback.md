# W06 Integration Delivery Feedback

## 1. 执行结论

W06 已完成 Task 10（Integration）、Task 11（End-to-End Validation）和 Task 12（Cleanup）。正式链路已贯通：

```text
Prompt / AGENTS Instruction State
  -> Instruction Epoch / stable prefix
  -> Session History / Projection / Runtime messages
  -> Application Context Compiler（固定 258K Operating Budget）
  -> Instruction Plane + Conversation Plane + GenerationRequest.tools
  -> Provider Integration mapping
  -> Session Result / Tool Result ref / Eval diagnostics
```

本次没有归档工作包，也没有执行 commit、push 或其他 Git 写操作。Prompt、Spec、Tasks 原文及结构未修改；Checklist 只勾选了已完成项。

## 2. Task 10：Integration

### 2.1 Application 正式入口

- `UthCodeApplication.ensure_session()` 为 CLI、TUI 打开 fresh Session；`/new`、`/resume` 继续由 Application 负责 Session 切换。
- 一个 terminal Turn 的消息增量由 `AgentRun` 交给 Application，通过当前 Session writer 一次提交 History，并同步 Instruction State metadata。
- 同一进程内只把尚未提交的 Run 消息交给 Context Compiler，避免把已经持久化的 History 再次拼入 Conversation Plane。
- 跨进程 `/resume` 只从当前文件系统读取已提交的 Session History、Projection、Tool Result ref 和 Instruction State；它会启动新的 Run/Turn，不伪造 runtime checkpoint、Task 或 Plan checkpoint。
- History 消息转换与 identity-local reconstruction payload 收敛到 `history_entries_for_message`，移除了重复转换路径和无必要的 `HistoryCoordinator` 兼容别名。

### 2.2 Context、Tool Result 与 Provider 边界

- 正式生成请求由 `ApplicationContextService` 构造固定 258K Operating Budget 下的 Instruction Plane、Conversation Plane 和 `GenerationRequest.tools`。
- Tool Schema 的单一来源仍是 Tool System；Provider Integration 只做原生协议映射，不创建第二份 Tool Registry 或按 Provider 名称分支。
- 大 Tool Result 按 inline/ref 策略处理；`ToolResultRead` 只接受当前 Session 的 opaque ref、offset 和 limit，返回有界页，不接受任意文件路径或跨 Session ref。
- persistence failure 通过安全 diagnostics 暴露，不把未确认的持久化结果伪装为未执行，也不自动重试。
- Compaction、Projection、Instruction Epoch 和 stable prefix 继续由既有 Application/Core 边界负责；本次没有引入第二个 Agent Loop、scheduler 或 runtime checkpoint。

## 3. Task 11：End-to-End Validation

新增 `tests/test_w06_integration_delivery.py`，覆盖正式 `create_application` 链路中的：

- 多轮 Run/Turn、terminal History persistence、Session catalog、关闭后重建与 resume；
- `/resume` 使用当前文件系统 Instruction State：内容未变时 epoch/stable prefix 保持，离线修改 AGENTS 后 epoch 递增；
- 固定 258000 budget、缺少 `max_input_tokens`、两平面与 `GenerationRequest.tools`；
- Tool Schema 单一来源、authority spoof 不进入 system prompt；
- 超大 Tool Result 的 externalization、`ToolResultRead` bounded page、result ref 与 execution/persistence outcome；
- compactor overflow/failure boundary、结果 quota/ref diagnostics 与 fresh resumed Run iteration。

## 4. Task 12：Cleanup 与文档同步

清理范围限定在本工作包正式链路：删除重复的 Message 到 History payload 构造路径，去除未使用的 `HistoryCoordinator` 兼容别名，并让 CLI/TUI 释放 Application 资源。未删除仍被 `OutstandingDebtList` 记录且当前边界明确保留的能力欠账。

维护了实际存在的文档路由：

- `docs/context/A01-AgentRuntime/AgentRuntime-Context.md`
- `docs/context/A03-State/State-Context.md`
- `docs/context/A04-Orchestration/Orchestration-Context.md`
- `docs/context/TUI/README.md`
- `docs/user-manual/commands.md`
- `docs/user-manual/getting-started.md`
- `docs/Tools.md`
- `docs/Context-Index.md`
- `docs/work/T09-Prompt与ContextEngineering/T09-Prompt与ContextEngineering-checklist.md`

工作包要求中的 `docs/UserManual.md` 在仓库中不存在，因此按 `docs/README.md` 的维护映射更新了 `docs/user-manual/` 下对应文档。`docs/OutstandingDebtList.md` 没有新增或删除条目：runtime checkpoint、persistent Memory/retrieval、Artifact GC、hierarchical compaction 以及 T09-1 的真实依赖欠账仍然成立。

## 5. 验证记录

基线（实施前）：

```text
1201 passed, 3 skipped in 99.74s (0:01:39)
```

本次验证：

```text
conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_w06_integration_delivery.py
1 passed in 0.84s

conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_architecture_boundaries.py tests/test_package.py tests/test_session_files.py tests/test_w06_integration_delivery.py
44 passed in 9.20s

conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_architecture_boundaries.py
23 passed in 4.60s

conda run --no-capture-output -n re-uthcode python -m pytest -q
1202 passed, 3 skipped in 96.33s (0:01:36)

conda run --no-capture-output -n re-uthcode python -m compileall -q src tests eval
exit 0

conda run --no-capture-output -n re-uthcode python -m pip check
No broken requirements found.
```

## 8. 第二轮返工记录：History append failure 后原始 Turn identity 保留

### 8.1 验收发现与根因

验收发现第一轮 History append 失败后，`_persisted_message_count` 虽然正确保持为 `0`，但 `AgentRun._complete_turn()` 下一次只把整个未提交消息切片和新的 `result.turn_id` 交给 Application。于是第一轮消息会被第二轮 ID 重新标记，破坏 Canonical History 的 Turn 边界；原有回归测试只检查 payload 和 sequence，没有检查跨轮 `turn_id`。

### 8.2 最终收口方案

`AgentRun` 在每次 `start_turn()` 记录当前 Message 起点，在 terminal 边界形成当前 Turn 的不可变 Message 批次。批次只在进程内保存：

```text
PendingPersistenceBatch
├─ original session_id
├─ original turn_id
└─ original tuple[Message, ...]
```

当前批次追加到 pending queue 后，Application 按 FIFO 依次调用 `_persist_run_messages()`，每批使用自身原始 `session_id` 和 `turn_id`。这只是当前 AgentRun 的重试元数据，不是第二套 History/Event Store，也不提供跨进程 Runtime checkpoint。

### 8.3 Cursor 与失败语义

- History append 成功：移除该 pending batch，并按 outcome 的 `persisted_message_count` 推进 `_persisted_message_count`；metadata sync 半失败仍按已 durable 消息推进。
- History append 失败：保留该 pending batch，`persisted_message_count=0`，cursor 不推进；后续批次不会越过它写入 History。
- pending batch 恢复时不按文本、payload 或内容相等去重；结构化 Message、ToolCall ID、ToolCall/ToolResult semantic unit 和严格 sequence 均按原批次保留。
- 新 Turn 的 process delta 仍从 durable cursor 计算，因此没有静默丢弃真实消息，也没有改变原有 single-writer 或 durable append 语义。

### 8.4 新增与加强测试

在 `tests/test_w06_integration_delivery.py` 中：

- 加强 `test_w06_history_append_failure_keeps_cursor_and_retries_unpersisted_messages`：断言第一轮 user/assistant payload 只归属 `first.turn_id`，第二轮 payload 只归属 `second.turn_id`，两轮 sequence 连续。
- 新增 `test_w06_history_append_retry_preserves_turn_and_tool_identity`：第一轮包含 `ToolCall`/`ToolResult`，append 失败后第二轮恢复提交；断言两种消息保留第一轮 ID，工具 semantic unit 与 `retry-call-1` 保持完整，第二轮消息使用第二轮 ID，payload 不丢失或重复。

### 8.5 第二轮精确验证结果

本轮仍使用 `conda run --no-capture-output -n re-uthcode`；pytest 前显式移除 `NO_COLOR` 并设置 `TERM=xterm-truecolor`。

```text
python -m pytest -q tests/test_w06_integration_delivery.py -k 'history_append'
3 passed, 1 deselected in 5.25s

python -m pytest -q tests/test_w06_integration_delivery.py
4 passed in 1.09s

python -m pytest -q tests/test_application_runs.py
44 passed in 2.89s

python -m pytest -q tests/test_session_files.py
11 passed in 3.07s

python -m pytest -q tests/test_w04_session_commands.py
19 passed in 7.20s

python -m pytest -q tests/test_architecture_boundaries.py
23 passed in 4.27s

python -m pytest -q
1205 passed, 3 skipped in 138.87s (0:02:18)

python -m compileall -q src tests eval
exit 0

python -m pip check
No broken requirements found.

git diff --check
pass
```

同步更新了 `docs/Context-Index.md`、`docs/core-design/T03-system-prompt.md`、`docs/context/A01-AgentRuntime/AgentRuntime-Context.md`、`docs/context/A03-State/State-Context.md` 和 `docs/context/A04-Orchestration/Orchestration-Context.md`，补充 pending batch 的原始 Session/Turn identity 与 FIFO 边界。T09 Prompt、Spec、Tasks、Checklist 文字结构及 W01～W06 Prompt 未修改；未执行 Git 写操作、工作包归档或后置能力建设。

文档和交付边界检查：

- UTF-8 guard：10 个变更 Markdown 文件通过，无 replacement character、常见乱码或 Markdown fence 问题。
- Markdown 相对链接：7 个相对链接通过，0 个缺失目标。
- `git diff --check`：已通过；新增测试和本 Feedback 也纳入最终空白检查。
- Checklist 未完成项：0 个。
- 未执行 Git commit、push、merge、rebase、tag、release 或工作包归档。

## 6. 遗留与风险

本次没有新增 W06 能力欠账。当前已知边界仍为：

- 不恢复未提交的 runtime checkpoint、等待中的 Turn 或活跃 waiter；
- 不实现持久 Memory/retrieval、Artifact GC、hierarchical compaction；
- 真实 Provider 小窗口适配与模型 limits 仍由 T09-1 负责；258K 是当前固定 Operating Budget，不宣称远端模型物理窗口。

这些边界已同步到 Context、用户手册、Tools 和 Context-Index 文档，未扩大本工作包范围。

## 7. 定点返工记录：P0 半成功 persistence

### 7.1 根因

原实现把 `active.append_history(...)` 和 `active.persist_instruction_state()` 放在同一个 `try` 中，并用一个布尔值表示整体成功。History 已 durable append 后，如果 metadata sync 抛错，调用方仍然不推进 `_persisted_message_count`；下一轮于是同时把相同消息视为 Canonical History 和 process delta，造成 Provider request 与 Canonical History 重复。

### 7.2 最终 persistence outcome contract

`UthCodeApplication._persist_run_messages()` 现在返回 `HistoryPersistenceOutcome`，至少表达：

```text
history_appended: bool
instruction_state_synced: bool
failure_stage: history_append | instruction_state_sync | session_boundary | invalid_message | None
persisted_message_count: int
```

公开 diagnostics 同步包含 `status`、`error_code`、上述字段和累计 `committed_turns`：

- `committed`：History append 和 Instruction State metadata sync 都成功；
- `partial`：History 已 durable append，但 metadata sync 失败；
- `failed`：History append 失败，或在 append 前发生边界/输入错误；
- `not_available`：当前 Application 没有 durable Session。

### 7.3 Cursor 与重复防护

- History append 成功后立即由 outcome 返回本批 `persisted_message_count`；`AgentRun` 按这个数量推进 `_persisted_message_count`，不依赖 metadata sync 是否成功。
- metadata sync 失败时，真实已落盘消息不会再次作为 process delta，也不会再次 append Canonical History；diagnostics 保留 `partial` 与 `failure_stage=instruction_state_sync`。
- History append 失败时返回 `persisted_message_count=0`，cursor 不推进，未持久化的真实消息仍保留在 RunState，下一轮可按既有流程继续处理；不使用文本、payload 或内容相等的全局去重。
- ToolCall ID、ToolCall/ToolResult semantic unit、strict sequence、single writer 和 durable append 语义未改变。

### 7.4 新增回归测试

在 `tests/test_w06_integration_delivery.py` 新增：

- `test_w06_history_append_then_instruction_sync_failure_advances_cursor`：History 成功、metadata sync 失败；验证 partial diagnostics、cursor 推进、下一轮 Provider request 中上一轮结构化 Message identity 只出现一次，以及 Canonical History identity/sequence 不重复。
- `test_w06_history_append_failure_keeps_cursor_and_retries_unpersisted_messages`：History append 失败；验证 failure diagnostics、cursor 不推进、下一轮仍携带未持久化消息，恢复后两轮消息按 strict sequence 各出现一次。
- 既有 formal chain 测试继续验证完整成功 outcome 为 `committed`。

### 7.5 本轮文档同步范围

新增/更新了：

- `README.md`
- `docs/core-design/README.md`
- `docs/core-design/T03-system-prompt.md`
- `docs/context/A01-AgentRuntime/AgentRuntime-Context.md`
- `docs/context/A03-State/State-Context.md`
- `docs/context/A04-Orchestration/Orchestration-Context.md`
- `docs/user-manual/getting-started.md`
- `docs/user-manual/commands.md`
- `docs/Context-Index.md`

未修改 T09 Prompt、Spec、Tasks、W01～W06 Prompt 或其他冻结任务书；`T09-Prompt与ContextEngineering-checklist.md` 保持 Task 10～12 已完成，因为 P0 已关闭并通过验证。未新增或删除 `OutstandingDebtList` 条目。

### 7.6 精确验证结果

本轮使用 `conda run --no-capture-output -n re-uthcode`；pytest 前显式移除 `NO_COLOR` 并设置 `TERM=xterm-truecolor`。

```text
python -m pytest -q tests/test_w06_integration_delivery.py -k 'history_append'
2 passed, 1 deselected in 4.31s

python -m pytest -q tests/test_w06_integration_delivery.py
3 passed in 5.42s

python -m pytest -q tests/test_application_runs.py
44 passed in 2.43s

python -m pytest -q tests/test_session_files.py
11 passed in 3.07s

python -m pytest -q tests/test_w04_session_commands.py
19 passed in 8.06s

python -m pytest -q tests/test_architecture_boundaries.py
23 passed in 4.26s

python -m pytest -q
1204 passed, 3 skipped in 131.87s (0:02:11)

python -m compileall -q src tests eval
exit 0

python -m pip check
No broken requirements found.
```

## 9. 第三轮定点返工记录：append_history post-append durability

### 9.1 根因

`SessionWriter.append_history()` 原先把 JSONL append+fsync、`_reload(touch=True)` 和 last-used metadata touch 当作一个不可区分的操作。JSONL 已经 durable 写入后，如果 reload 或 touch 抛错，Application 会把异常误判为 History append 未提交，保持 `_persisted_message_count=0`；后续 pending FIFO 重试同一批次，导致 Canonical History 重复。

### 9.2 最终 persistence outcome contract

`SessionWriter.append_history()` 现在返回结构化 `HistoryAppendOutcome`，分开表达：

```text
history_appended: bool
reload_succeeded: bool
metadata_synced: bool
failure_stage: history_append | history_append_reconciled | history_reload | history_metadata_sync | history_durability_unknown | None
durability: not_attempted | durable | not_durable | unknown
```

Application 的 `HistoryPersistenceOutcome` 继续叠加 Instruction State metadata sync outcome、failure stages、diagnostics 和 `persisted_message_count`。因此可以区分：History append failure、append 后 reload/metadata failure、Instruction State sync failure、完整成功，以及无法判定的 unknown durability。

### 9.3 Reconciliation、cursor 与 fail-closed 边界

- `_append_jsonl()` 或 post-append reload 异常后，SessionWriter 重新读取结构化 `HistoryEntry`，按 append 前完整 History 加本批原始 entries 做 identity reconciliation；不使用文本、payload 或内容相等的全局去重。
- 已确认 `durability=durable` 的批次，即使 reload 或 last-used metadata touch 失败，也返回 `history_appended=True`；Application 推进 `_persisted_message_count`、移除 pending batch，并保留 `partial` diagnostics，不会再次注入 Provider 或 append Canonical History。
- 能确认没有落盘的 append failure 返回 `durability=not_durable`，cursor 不推进，真实消息仍留在 RunState 的 pending FIFO 中；无法确认时返回 `durability=unknown`，pending batch 被标记并 fail closed，不允许下一 Turn 盲目重试。
- 原始 Turn identity、ToolCall ID、ToolCall/ToolResult semantic unit、strict sequence、single-writer 和 durable append 语义保持不变；未引入第二套 History/Event Store 或 Runtime checkpoint。

### 9.4 新增回归测试

新增并通过：

- `test_w06_history_append_touch_failure_is_durable_and_not_retried`：JSONL append+fsync 成功、metadata touch 失败；验证 durable outcome、partial diagnostics、cursor 推进、pending 清空、下一轮只出现一次且 History sequence 连续。
- `test_append_history_reports_durable_when_post_append_touch_fails`：Integration 层验证 History 已实际落盘并可恢复。
- `test_append_history_reconciles_post_append_reload_failure`：验证 append 后 reload 异常可通过结构化 identity reconciliation 判定 durable。
- `test_append_history_reports_unknown_when_post_append_reconciliation_fails` 与 `test_w06_unknown_history_append_durability_fails_closed`：验证无法读取/判定时不推进 cursor、不重试未知批次，并保留明确 unknown diagnostics。

### 9.5 文档与 Checklist

同步更新 `docs/Context-Index.md`、`docs/context/A01-AgentRuntime/AgentRuntime-Context.md`、`docs/context/A03-State/State-Context.md`、`docs/context/A04-Orchestration/Orchestration-Context.md` 和 `docs/core-design/T03-system-prompt.md`，补充 append/reload/metadata touch 分层、结构化 reconciliation 和 unknown fail-closed 边界。复核 Checklist：P0 已关闭后 Task 10～12 仍可保持完成；未修改冻结的任务书、Spec、Tasks、Prompt 或 W01～W06 Prompt。

### 9.6 精确验证结果

以下命令均在 Conda 环境 `re-uthcode` 中执行。由于当前环境原有 `NO_COLOR=1`、`TERM=dumb`，pytest 验证命令仅在子进程内移除 `NO_COLOR` 并设置 `TERM=xterm-truecolor`；没有修改持久环境。

```text
新增 persistence regression selection（5 个新增边界测试）
5 passed in 0.75s

python -m pytest -q tests/test_w06_integration_delivery.py
6 passed in 4.25s

python -m pytest -q tests/test_application_runs.py
44 passed in 2.91s

python -m pytest -q tests/test_session_files.py
14 passed in 3.32s

python -m pytest -q tests/test_w04_session_commands.py
19 passed in 7.47s

python -m pytest -q tests/test_architecture_boundaries.py
23 passed in 4.76s

python -m pytest -q
1210 passed, 3 skipped in 133.48s (0:02:13)

python -m compileall -q src tests eval
exit 0

python -m pip check
No broken requirements found.

git diff --check
exit 0；仅有既有 LF→CRLF 工作树提示，无 whitespace error。

NO_COLOR=1、TERM=dumb：tests/test_tui.py 为 69 passed, 3 failed；失败为既有 truecolor 断言。
移除 NO_COLOR、TERM=xterm-truecolor：tests/test_tui.py 为 72 passed。

uth-utf8-guard：6 个本轮受影响 Markdown 文件通过 UTF-8、replacement/mojibake 和 fence 检查。
```

本轮未执行 Git commit、push、PR、merge、rebase、tag、release 或工作包归档；无新增能力欠账。

## 10. Unknown durability 的 Session 级隔离与恢复

### 10.1 根因

上一轮虽然保留了 pending batch 的原始 Turn identity，并在无法判定 History 是否 durable 时阻断当前 `AgentRun`，但 `blocked` 状态仍只属于 `_pending_persistence_batches`。调用方可以创建新的 `AgentRun`，绕过旧 Run 的状态，基于过期 Session snapshot 再次调用 Provider 和 History append，最终写入重复 sequence 并破坏 `history.jsonl`。

### 10.2 最终 Session durability contract

`SessionWriter` 现在持有 `durability_unknown` quarantine 状态。`append_history()` 在 append 后 reload 或 reconciliation 无法判定时会设置该状态；Application 侧也会将任何翻译为 `durability=unknown` 的 outcome 归属到当前 `ApplicationSession`。在 quarantine 未解除前：

- 新 Run 在生成 Provider request 之前被拒绝；
- History、Projection、Runtime、Tool Result 和 Instruction State 等语义写入均 fail closed；
- 不会再次调用 Provider、append History 或推进 persistence cursor；
- diagnostics 明确保留 `history_durability_unknown` / `history_durability=unknown`，不伪装成完整成功。

显式 `ApplicationSession.close()` 会在 quarantine 状态下只释放 writer，不再执行可能产生新写入的 close sync。随后必须通过新的 `resume_session()` 重新打开并验证 Session；只有 fresh writer 完成 snapshot/History 验证后，quarantine 才自然解除并允许继续。该方案没有引入第二套 History/Event Store、Runtime checkpoint 或文本去重。

### 10.3 Cursor、sequence 与恢复边界

Run-local pending batch 不再是唯一保护边界。跨 Run 回归证明：Run 1 进入 unknown 后，Run 2 在 Provider 层被拒绝，`history.jsonl` 字节数和记录数不变，没有产生重复 sequence。关闭并重新打开 Session 后，恢复验证成功才允许 Run 3 继续；此前 pending History 不被再次 append，恢复后的 sequence 严格连续，原始 Turn identity 仍保持不变。

### 10.4 新增回归测试

新增并通过：

- `test_w06_unknown_history_append_durability_fails_closed`：验证 Run 1 unknown 后 Run 2 被拒绝、Provider request 不增加、History bytes/records 不变化；显式 close/reopen 验证成功后新 Run 才能继续。
- `test_append_history_reports_unknown_when_post_append_reconciliation_fails`：验证 writer quarantine 后 History 与 Projection 写入均被拒绝，并保留结构化 unknown outcome。

### 10.5 文档同步与精确验证

同步更新 `docs/Context-Index.md`、`docs/context/A01-AgentRuntime/AgentRuntime-Context.md`、`docs/context/A03-State/State-Context.md`、`docs/context/A04-Orchestration/Orchestration-Context.md` 和 `docs/core-design/T03-system-prompt.md`，补充 Session writer quarantine、跨 Run fail-closed 以及 close/reopen recovery 边界。未修改冻结任务书、Spec、Tasks、Prompt 或 W01～W06 Prompt。

本轮实际结果：

```text
cross-Run unknown durability regression：1 passed in 0.74s
same-writer quarantine regression：1 passed in 0.42s
tests/test_w06_integration_delivery.py：6 passed in 1.45s
tests/test_session_files.py：14 passed in 3.16s
tests/test_application_runs.py：44 passed in 2.68s
tests/test_w04_session_commands.py：19 passed in 6.01s
tests/test_architecture_boundaries.py：23 passed in 4.53s
python -m pytest -q：1210 passed, 3 skipped in 104.15s
python -m compileall -q src tests eval：exit 0
python -m pip check：No broken requirements found.
git diff --check：exit 0；仅有既有 LF→CRLF 工作树提示，无 whitespace error。
NO_COLOR=1、TERM=dumb：tests/test_tui.py 为 69 passed, 3 failed；失败均为既有 truecolor 断言。
移除 NO_COLOR、TERM=xterm-truecolor：tests/test_tui.py 为 72 passed in 8.94s。
```

最终 UTF-8/replacement/mojibake/fence 检查和相对链接检查通过；相对链接检查结果为 `relative_links_checked=23`、`relative_links_missing=0`。本轮未执行 Git commit、push、PR、merge、rebase、tag、release 或工作包归档。

## 11. 第四轮定点修复：Projection、Message identity、AGENTS fail-closed 与 Markdown fence

### 11.1 Projection post-append durability contract

根因是 Projection 记录与后续 reload、metadata touch 仍被当成一个无返回值写入步骤；append 已落盘而 reload/touch 失败时，调用方无法知道是否可以重试，且 unknown 情况没有把当前 SessionWriter 隔离。现在 `SessionWriter.append_projection()` 返回结构化 `ProjectionAppendOutcome`：

- append 后 reload 失败会重新读取结构化 Session snapshot，并按 History、Projection、record sequence 做 reconciliation；确认 durable 时只更新当前 writer，不再次 append，确认 not durable 时才允许安全重试。
- metadata touch 失败不撤销已 durable 的 Projection，返回 `metadata_synced=False`；Projection revision 与全局 record sequence 仍严格递增。
- append/reload 后无法判定时返回 `durability="unknown"` 并设置 SessionWriter quarantine；History、Projection、Runtime、Tool Result、Instruction State 和新 Run 均 fail closed，必须 close/reopen 后再验证。
- Application compact/overflow path 只在 Projection outcome 确认 durable 后刷新 Context；not durable/unknown 不把候选 Projection 暴露为成功。新 Run 在 quarantine 时不会调用 Provider。

### 11.2 同 Turn 消息 identity 与恢复

根因是恢复 identity 只使用 `(session_id, turn_id, role)`，导致 Steering 产生的相邻 user Message 和同角色独立结构化 Message 被合并或跳过。Core history adapter 现在为每个 Message 写入 deterministic `message_id` 与 `message_part_index`；Context reconstruction 以该 identity 局部合并 multipart parts，并保留同 Turn 相邻同角色 Message，不使用全局文本去重。ToolCall/ToolResult payload 和 semantic unit 关系保持不变。

### 11.3 AGENTS include formal path fail-closed

正式 `create_session`、staged create、direct/staged resume 与 active refresh 均使用 `strict=True`。严格失败在 writer/metadata/loader commit 前结束；staged resume 失败时不采用候选 Loader，当前 active Session、scope、epoch 和 resume metadata 不被部分更新。`load_session(strict=False)` 仍只供直接 Loader 诊断调用，正式 Session 不会让失败 include 的父 AGENTS block 生效。

### 11.4 Markdown fence boundary

`parse_instruction_references()` 现在记录 opening fence 的字符和长度，只有相同字符且 closing 长度不短于 opening、尾部仅为空白时才关闭；因此四反引号中的三反引号、不同字符或更短 closing 都不会提前结束，围栏内 `@include` 永远不解析。反引号、波浪号及 opening/closing 长度边界均有回归覆盖。

### 11.5 新增回归与精确验证

新增或补充：

- `tests/test_session_files.py`：Projection post-append touch/reload reconciliation、unknown quarantine、strict record sequence/reopen revision 和其他写入口阻断。
- `tests/test_context_compaction.py`、`tests/test_w04_session_commands.py`：同 Turn 相邻同角色、Steering、multipart Message 的 compile/resume 恢复。
- `tests/test_w06_integration_delivery.py`：formal create/resume/refresh include fail-closed，以及 Projection unknown 后新 Run 阻断和 reopen 恢复。
- `tests/test_project_instructions.py`：反引号/波浪号 fence 相同字符、短/长 closing boundary。

本轮命令结果：

```text
定向集合（session/context/project-instructions/W04/W06/architecture）：110 passed in 16.44s
python -m pytest -q：1215 passed, 3 skipped, 3 failed in 100.88s
默认环境的 3 个失败均为既知 NO_COLOR 下 tests/test_tui.py truecolor 断言；非本轮改动。
清除 NO_COLOR、TERM=xterm-truecolor 后 python -m pytest -q：1218 passed, 3 skipped in 102.65s
python -m compileall -q src tests eval：exit 0
python -m pip check：No broken requirements found.
git diff --check：exit 0；仅有既有 LF→CRLF 工作树提示，无 whitespace error。
uth-utf8-guard：本 Feedback 写回前后均通过，无 replacement character、mojibake 或不平衡 fence。
```

Checklist 已全部处于 `[x]`，本轮没有重复修改；T09 Prompt、Spec、Tasks、Checklist 与 W01～W06 Prompt 保持冻结。未修改 Environment Plane 文档，不实施 `/compact`、summarizer 或自动阈值后置能力；未执行 commit、push、PR、merge、rebase、tag、release 或工作包归档。

## 12. 复审追加：schema v1 兼容、direct create 隔离与 Compaction diagnostics

### 12.1 对第四轮记录的更正

第 11 节此前只明确了带新 `message_id` 的 multipart 恢复，没有明确覆盖修复前同 schema v1、每个 History entry 携带完整 `message` 的合法 multipart；Projection persistence 结果也已落盘，但 Application Compaction diagnostics 尚未与最终返回结果统一；此外 direct `create_session()` 虽然使用 strict Loader，却仍会先清空当前 Loader。以上三项声明与实现边界现已补正如下。

### 12.2 schema v1 legacy multipart contract

保留 schema v1，不引入迁移。没有 `message_id` 的旧 full-message entry 只有在以下条件同时成立时才按相邻 multipart continuation 处理：同一 session/turn/role、严格相邻 sequence、完整 Message 相同、当前 `part` 等于 Message 的下一顺序 part，并且首 part 与下一 part 不产生无法区分的重复歧义；否则视为独立 Message 或 fail closed。新 `message_id` 路径保持原有 identity-local 规则，不使用全局文本/内容去重。ToolCall/ToolResult pair、重复文本独立 Message、Steering 和新旧 multipart 均有回归覆盖。

### 12.3 direct create 与 Compaction diagnostics

- `ApplicationSessionService.create_session()` 现在复用 staged/fork Loader，候选严格加载成功后才 commit；include 失败不会清空当前 blocks、epoch、fingerprint、activated scopes，也不会创建 Session metadata/目录或留下 writer。成功路径再原子采用 candidate。
- `ApplicationContextService.finalize_compaction()` 在 Projection persistence 返回后回写同一最后事件。unknown、not-durable 和 append exception 均让最终 `CompactionResult` 与 `application.diagnostics()["compaction"]` 一致地显示 `failed`、`changed=false` 和对应 failure；manual compact 与 Provider overflow commit failure 共用该边界。

### 12.4 本轮新增回归与精确验证

- `test_context_message_projection_restores_schema_v1_legacy_multipart_identity`：旧 v1 multipart、重复同内容独立 Message、ToolCall/ToolResult。
- `test_w06_direct_create_failure_preserves_loader_until_successful_commit`：direct create 失败状态、无 Session 目录、成功后 candidate commit。
- `test_w06_compaction_diagnostics_match_projection_persistence_failure`：unknown/not-durable/append failure 三种 manual compact outcome。
- `test_formal_overflow_projection_append_failure_updates_compaction_diagnostics`：overflow commit failure diagnostics。

```text
定向集合（context/W06/session/project-instructions/W04/architecture）：110 passed in 16.44s
python -m pytest -q：1221 passed, 3 skipped, 3 failed in 99.29s
默认环境的 3 个失败仍为既知 NO_COLOR 下 tests/test_tui.py truecolor 断言。
清除 NO_COLOR、TERM=xterm-truecolor 后 python -m pytest -q：1224 passed, 3 skipped in 100.34s
python -m compileall -q src tests eval：exit 0
python -m pip check：No broken requirements found.
git diff --check：exit 0；仅有既有 LF→CRLF 工作树提示，无 whitespace error。
uth-utf8-guard：本 Feedback 写回前后通过，无 replacement character、mojibake 或不平衡 fence。
```

未修改 Environment Plane 文档；未修改冻结 task/spec/tasks/checklist/prompts；未执行 commit、push、PR、merge、rebase、tag、release 或工作包归档。

## 13. 收口更正：删除无事实前提的旧 Session 兼容

第 12.2 节将“同 schema v1 且没有 `message_id`”假定为已存在的旧持久化数据，该前提没有代码、发布或生产 Session 样本证据。Session History 持久化是 T09 当前新建能力，项目又明确禁止为不存在的旧数据保留兼容逻辑，因此不进行虚构的迁移演练。

当前正式 contract 收口为：

- `history_entries_from_message()` 为每个 Message 持久化明确 `message_id` 和 `message_part_index`；
- Context reconstruction 只按该结构化 identity 合并 multipart，不做全局文本去重；
- History Message 缺少 `message_id` 时 fail closed，不尝试推断或兼容未证实的旧格式；
- 删除 legacy multipart 推断分支和对应的人工剥离字段“迁移”测试，改为缺失 identity 的 fail-closed 回归。

direct create 事务隔离、Compaction diagnostics 最终结果同步以及第 11 节的其余实施修复均保留，本次更正不扩大 T09 范围。
