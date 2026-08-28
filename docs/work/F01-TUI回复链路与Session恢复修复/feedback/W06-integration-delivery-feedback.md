# W06 F01 接入、验收与清理 Feedback

## 结论

W06 已按 `T09 -> T10 -> T11` 串行完成当前可执行范围。W01～W05 的实现已接入同一 Application 主链；本轮新增跨层回归覆盖模型切换、正式 TUI 四输入和 Session Picker 惰性生命周期，并同步当前事实文档。未执行 Git 写操作、分支操作、推送、PR、合并或工作包归档。

真实 Windows Terminal 当前不可交互，因此人工视觉验收明确记为 `NOT VERIFIED`，没有把它写成通过。若按 WorkPackageRules 的状态定义，因 Checklist 仍有未完成项，F01 在 `docs/Context-Index.md` 保持 `not_implemented`，工作包目录仍留在 `docs/work/`。

## 唯一正式调用链

```text
interfaces/cli.py 或 interfaces/tui/app.py
  -> application/bootstrap.py:create_application
  -> application/generation.py:UthCodeApplication.create_run
  -> 真实 prompt: ensure_session()
     或显式 /new: new_session_for_command()
     或显式 /resume: resume_session_for_command()
  -> application/runs.py:AgentRun.start_turn
  -> core/agent.py:AgentLoop / AgentTurnExecution
  -> core/provider.py:ProviderPort
  -> core/tool.py:ToolExecutor + core/permission.py:PermissionEvaluator
  -> application/runs.py:_TurnDriver
  -> AgentEvent / TurnResult
  -> Application Transcript/replay projection
  -> CLI/TUI
```

`ApplicationContextService.compose_generation_request` 是唯一正式 Context/Prompt request 组合入口。模型切换只更新下一 Turn 的快照；本轮 `test_unique_application_chain_preserves_history_across_model_switch` 证明同一个 Run 的第一、第二 Turn 分别使用两个 remote model，第二次请求仍包含第一轮历史且最后一条 user message 精确等于第二轮输入。

## 四个现象与九类问题证据矩阵

| 编号 | 问题 | 关闭证据 | 状态 |
| --- | --- | --- | --- |
| F-1 | reasoning 与正式回复顺序错乱 | W05 `test_renderer_keeps_interleaved_reasoning_and_assistant_blocks_in_event_order`、`test_real_stream_keeps_reasoning_before_one_formal_permanent_block`；TUI 使用单一有序 `_streams`/operations，reasoning 先于 formal authority | 自动关闭；真实终端视觉未验证 |
| F-2 | agent 混淆 system/user/自身回复 | W01 Context Compiler、三 Provider mapping、普通历史伪 system 标签和 exact current-user-tail 测试；A01 `03-系统指令权威链路` 已同步独立来源边界 | 自动关闭 |
| F-3 | 思考内容进入最终回复 | W02 typed `ReasoningPart`/`TextPart`、STOP 非空正文 gate、`TurnResult.final_text` 只取正式正文；W05 TUI final/preview 回归；reasoning 不降级为正文 | 自动关闭 |
| F-4 | `/resume` 无法恢复原 session 聊天记录 | W03 safe replay DTO/staged resume，W05 ordered bounded hydrate，W06 `test_resume_uses_transcript_and_starts_a_fresh_run`；恢复后继续请求包含 durable marker 和唯一新 user tail | 自动关闭；完整跨进程组合仍未验证 |
| P-1 | 当前 user 边界丢失 | W01 exact tail 回归；W06 正式 TUI 四输入回归对 `你好`、`你是什么模型`、`当前工作环境是？`、`？` 逐条捕获请求，最后一条 Message 为独立 `TextPart(prompt)` | 自动关闭 |
| P-2 | Prompt 组合双轨 | `rg -n 'build_system_prompt\\|SystemPromptContext' src/uthcode` 返回 0 条；`compose_generation_request` 仅一个定义和两个 Application 调用点，W01 Feedback 已记录入口审计 | 自动关闭 |
| P-3 | reasoning 产品合同不一致 | W02 Provider event/terminal/history contract、W05 chronological renderer 和 semantic bar tests；`tests/test_provider_contract.py`、`test_agent_events.py`、`test_agent_loop.py` 全部通过 | 自动关闭 |
| P-4 | reasoning 历史污染 | W02 同 identity carrier 与跨 identity 不降级测试；reasoning/final 独立 Transcript part；本轮 reasoning fallback 负向扫描仅命中合法测试 fixture | 自动关闭 |
| P-5 | reasoning-only stop 被当作成功 | W02 `test_reasoning_only_stop_is_invalid`、空 `TextPart` terminal tests；全量回归通过 | 自动关闭 |
| P-6 | Windows stdout/stderr 乱码 | W04 `_decode_process_output`、UTF-8/OEM/ANSI/非法 bytes/空输出/非零退出测试及中文路径 Bash 回归；无新增编码猜测依赖 | 自动关闭；真实 Windows Terminal 人工视觉未验证 |
| P-7 | Tool 活动名称/摘要/FIFO 混乱 | W04 Application Tool summary、FIFO、状态、脱敏和 ToolResult 排除测试；W05 TUI Tool projection；同 batch 每 call 一个 ToolFinished | 自动关闭 |
| P-8 | Transcript 放大与 replay 缺口 | W02 part-local storage/typed round-trip，W03 Application safe replay projection，W04 legacy v3 read-only；W06 resume 后新 Turn 只追加新 user/final 两条 entry | 自动关闭；跨进程两 ToolCall 组合仍未验证 |
| P-9 | 空 Session 累积 | W03 CLI lazy tests、W05 startup/exit/help/status，W06 正式 TUI 首条输入与 Picker open/close 回归；启动/Picker 不创建新 Session，普通输入只创建一个 | 自动关闭 |

自动测试和静态证据关闭了可执行的十三类问题；“真实入口完整组合”和 Windows Terminal 人工项按实际情况保留未验证，不虚构通过。

## D-F01-01～04 决策证据

- `D-F01-01`：W05 chronological event projection、reasoning 独立标题/语义 bar 色、safe Markdown incremental flush、assistant preview 到 authority 单次永久提交；TUI 自动回归通过。
- `D-F01-02`：W03 Application-owned `SessionReplayRecord` 安全投影、staged atomic resume；W05 ordered bounded hydrate；W06 恢复历史到下一请求的回归通过。raw ToolResult、native、secret、pending interaction 不进入 replay。
- `D-F01-03`：W03 CLI lazy lifecycle、W05 TUI lazy startup；W06 `test_formal_tui_four_prompt_sequence_preserves_current_user_tail` 与 `test_tui_session_picker_open_close_does_not_create_session` 通过。`/new`/`/resume` 仍由 Application 显式命令拥有。
- `D-F01-04`：W04/W05 保留原 Tool 摘要脱敏、环境值 token 边界脱敏和 FIFO；本轮未放宽 Secret/ToolResult 边界，未引入第二脱敏系统。

## T09～T11 验证命令

以下命令均使用 `re-uthcode` Conda 环境；结果为本轮实际输出：

- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_system_prompt.py tests/test_context_compiler.py tests/test_provider_contract.py tests/test_agent_events.py tests/test_agent_loop.py tests/test_openai_compat_integration.py tests/test_openai_responses_integration.py tests/test_anthropic_integration.py tests/test_history_contract.py tests/test_session_files.py tests/test_w04_session_commands.py tests/test_builtin_process_tool.py tests/test_application_tools.py tests/test_application_runs.py tests/test_cli.py tests/test_tui.py tests/test_w06_integration_delivery.py tests/test_t08_e2e.py tests/test_t07_1_e2e.py tests/test_permission_delivery.py -q` -> **620 passed, 3 skipped in 54.48s**。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_w06_integration_delivery.py -q` -> **8 passed in 3.38s**。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q` -> **23 passed in 6.19s**。
- `conda run --no-capture-output -n re-uthcode python -m pytest -q -rs` -> **1304 passed, 3 skipped in 157.59s**；三个 skip 分别为 `test_anthropic_integration.py:754`、`test_openai_compat_integration.py:606`、`test_openai_responses_integration.py:660` 的 live validation，均需 `UTHCODE_RUN_LIVE=1`，不是本地回归失败。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests eval` -> exit code **0**。
- `conda run --no-capture-output -n re-uthcode python -m pip check` -> **No broken requirements found.**
- `git diff --check` -> exit code **0**；仅有 Git 的 LF/CRLF 转换提示，没有 whitespace error。

清理后 T11 最终复核再次执行：`tests/test_w06_integration_delivery.py -q` -> **8 passed in 5.40s**；`tests/test_architecture_boundaries.py -q` -> **23 passed in 5.31s**；`pytest -q -rs` -> **1304 passed, 3 skipped in 150.98s**；compileall exit code **0**；pip check 为 **No broken requirements found.**；`git diff --check` exit code **0**；UTF-8 guard -> **OK: 11 file(s) passed UTF-8 guard**。

## 负向扫描与 caller audit

- `rg -n 'build_system_prompt|SystemPromptContext' src/uthcode` -> **0 条**；合法的旧名字断言只存在于 `tests/test_context_compiler.py`，生产代码没有旧入口。
- `rg -n 'ReasoningPart.*TextPart|text_values.*reasoning|reasoning.*text_values' src/uthcode/integrations/providers tests` -> 仅命中 W02/W03 合法 typed contract fixtures（如空 TextPart、ReasoningPart+非空 TextPart），`src/uthcode/integrations/providers` 无降级实现。
- `rg -n 'ensure_session\(' src/uthcode/interfaces` -> 两处：`interfaces/cli.py:203` 位于真实 `exec` prompt 前，`interfaces/tui/app.py:786` 位于首条普通输入 `_start_turn`；没有 startup ensure。
- `rg -n 'ReplayManager|HistoryManager|SessionMigration|EncodingManager|SecretManager' src tests` -> **0 条**。
- `rg -n 'chardet|charset_normalizer|EncodingManager|EncodingRegistry' src tests` -> **0 条**。
- `rg -n 'alternate screen|alternate_screen|CSI 3J|\\x1b\[3J|mouse_support=True|full_screen=True' src/uthcode/interfaces` -> **0 条**。
- `rg -n 'compose_generation_request\(' src/uthcode tests` -> 一个定义、两个 Application 正式调用，测试调用均为该公共入口；不存在第二 production composer。
- renderer 状态为 `_blocks: list` 与 `_streams: list[_StreamProjection]`，没有按 `message_id:kind` 分组 flush 的第二状态仓库；TUI 只消费 Application `SessionReplayRecord`，不导入 Core History、SessionFileStore、Provider SDK 或 Secret internals。

扫描命中中的 `message_id:kind:block-number` 仅是时间线 block identity，不是分类型 flush 字典；ReasoningPart/TextPart 命中均为合法测试类型合同，已在本节说明。

## 真实 Windows Terminal 人工验收

结果：**NOT VERIFIED**。

本轮只做了只读环境确认，没有启动或自动化 Windows Terminal：PowerShell 输出为 `TERM=dumb`、无 `WT_SESSION`、无 `TERM_PROGRAM`、无 `WindowsTerminal` 进程；`sky.list_apps()` 返回的当前应用窗口中没有 Windows Terminal，虽然 `wt.exe` 命令可用。由于没有唯一可交互的目标 Terminal 窗口，未执行以下人工步骤：reasoning/final 流式刷新、不同 bar 色、Markdown fence、中文 shell 输出、scrollback、resize、复制和快捷键。没有把 PTY 测试结果冒充 Windows Terminal 视觉验收。

## Checklist 与未完成项

本轮只把存在本轮或前序 Feedback 精确证据的条目由 `[ ]` 改为 `[x]`，未修改 Checklist 文字、结构、编号或顺序。当前仍未勾选：

当前 Checklist 统计为 **58 项 `[x]`、8 项 `[ ]`**；8 项未勾选均在下列范围内。

- T07 长 reasoning 至少两次 terminal preview 更新；assistant delta 持续变化的独立 preview 计数。
- T08 真正跨进程创建含 reasoning/final/两个 ToolCall 的完整 Session；replay 前后 Provider/Turn/Transcript 计数与 `/new` 不回放；busy/corrupt/unknown 的完整当前屏幕原子替换。
- T10 从正式入口完成 reasoning→Tool batch→final→退出→重启→`/resume`→继续的单一组合验收。
- T10 Windows Terminal 人工验收。
- T11 “W01～W06 Feedback 齐全且全部 Checklist 有证据后，将 F01 标记 `implemented_unarchived`”尚不能勾选，因为上述项目仍未完成；因此 Context Index 按规则保留 `not_implemented`。

## 文档同步

已按 `docs/README.md` 维护映射核对并同步当前代码事实：

- `docs/context/A01-AgentRuntime/AgentRuntime-Context.md`
- `docs/context/A03-State/State-Context.md`
- `docs/context/A04-Orchestration/Orchestration-Context.md`
- `docs/context/TUI/README.md`
- `docs/core-design/A01-AgentRuntime/02-原生协议快照.md`
- `docs/core-design/A01-AgentRuntime/03-系统指令权威链路.md`
- `docs/core-design/A04-Orchestration/02-可替换交互层.md`
- `docs/user-manual/getting-started.md`
- `docs/Context-Index.md`

`docs/user-manual/commands.md`、`docs/Tools.md` 和 `docs/README.md` 已审阅，当前内容与本轮代码无需修改。F01 原始需求、Spec、Tasks、Prompts、已有 W01～W05 Feedback 未修改。

## 修改文件与清理

- 新增跨层测试：`tests/test_w06_integration_delivery.py`（模型切换、正式 TUI 四输入、Picker open/close、resume 后唯一 current user tail）。W06 未修改生产代码；生产修复来自 W01～W05，入口审计证明仍走唯一主链。
- 同步 9 份当前事实/设计/用户手册文档、F01 Checklist 和本 Feedback。
- 本包未产生需要提交的 probe、Session、日志、截图或缓存文件；pytest `tmp_path` 产物由测试框架放在临时目录并自动清理。仓库中既有 `.pytest_cache`、`.uthcode`、`临时目录` 未触碰，也未删除旧 Session 或用户文件。
- `docs/OutstandingDebtList.md` 保持不变，F01 Spec 的“能力欠账：无”核对通过；Out of Scope 未登记为欠账。

## UTF-8 guard

- files checked: 本 Feedback、F01 Checklist、`docs/Context-Index.md`、A01/A03/A04/TUI current context、A01/A04 core design、`docs/user-manual/getting-started.md`，共 11 个实际修改 Markdown。
- result: `conda run --no-capture-output -n re-uthcode python C:\Users\93445\.codex\skills\uth-utf8-guard\scripts\check_utf8_docs.py docs/Context-Index.md docs/context/A01-AgentRuntime/AgentRuntime-Context.md docs/context/A03-State/State-Context.md docs/context/A04-Orchestration/Orchestration-Context.md docs/context/TUI/README.md "docs/core-design/A01-AgentRuntime/02-原生协议快照.md" "docs/core-design/A01-AgentRuntime/03-系统指令权威链路.md" "docs/core-design/A04-Orchestration/02-可替换交互层.md" docs/user-manual/getting-started.md "docs/work/F01-TUI回复链路与Session恢复修复/F01-TUI回复链路与Session恢复修复-checklist.md" "docs/work/F01-TUI回复链路与Session恢复修复/feedback/W06-integration-delivery-feedback.md"` -> **OK: 11 file(s) passed UTF-8 guard**。
- repaired encoding issues: none。

## 返工 R1：首审 CHANGES REQUESTED 自动阻断补齐

首审提出的六项可自动化阻断已在现有 W01～W05 实现上补齐回归证据；本轮没有新增生产入口或第二状态仓库，也没有等待无法交互的 Windows Terminal。

### 六项阻断的新增证据

| 阻断 | 自动化证据 | 结果 |
| --- | --- | --- |
| long reasoning 在 terminal 前至少两次 preview，并安全增量进入 scrollback | `test_tui_reasoning_preview_commits_safe_markdown_incrementally`：两次不同 preview 快照；完整 Markdown 段落先进入 committed，未闭合尾部仍留在 pending | 通过 |
| assistant 至少两次 distinct preview，最终权威永久一次 | `test_tui_assistant_preview_deltas_commit_one_authoritative_final`：两次 preview 内容不同；两次相同 authoritative update 只输出一次 final，draft 不进入永久输出 | 通过 |
| fresh Application/process-boundary 等价 seed/reconstruct/resume | `test_process_boundary_resume_replays_mixed_turn_once_and_new_is_empty`：Application 1 创建并关闭含 user、reasoning、final、两个 ToolCall/ToolResult 的 Session；Application 2 重建并 resume，按 durable sequence 得到一次安全 replay | 通过 |
| replay 计数不变且 `/new` 不回放旧 Session | 同一测试在 hydrate 前后断言 Provider call=0、Turn iteration=0、Transcript entry 数不变；`/new` 的新 Session replay 为空且旧 Transcript hash-equivalent 内容不变 | 通过 |
| busy/corrupt/unknown resume 原子失败 | `test_tui_failed_resume_keeps_screen_session_and_run_atomic` 覆盖三种错误；保留当前 preview、Session 对象、Run 对象、Session catalog 和 picker 状态，只追加对应用户可见错误 | 通过 |
| formal reasoning→two-tool FIFO batch→final→restart→resume→continue | `test_formal_tui_entry_tools_restart_resume_and_continue_in_order` 走真实 TUI `_start_turn`/`_handle_submission`/`_hydrate_replay`；第一 Application 输出顺序为 reasoning、ReadFile、Glob、final，关闭后 fresh Application resume，再继续对话且新请求只有唯一 current user tail | 通过 |

### R1 矩阵修订

原矩阵中 F-1、F-4、P-6、P-8 的“自动关闭”表述已改为“自动证据已关闭”，并在各行写明对应 R1 测试和剩余的真实 Windows Terminal 视觉边界；F-4/P-8 的跨 Application 证据明确标为 process-boundary 等价，不冒充独立 OS 进程。其余九类问题的既有自动证据保持不变。十三类问题的可执行自动证据现已齐全；Windows Terminal 的视觉/交互验收仍为 NOT VERIFIED。

### R1 定向与全量验证

- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_w06_integration_delivery.py` -> **13 passed in 4.43s**。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_system_prompt.py tests/test_context_compiler.py tests/test_provider_contract.py tests/test_agent_events.py tests/test_agent_loop.py tests/test_openai_compat_integration.py tests/test_openai_responses_integration.py tests/test_anthropic_integration.py tests/test_history_contract.py tests/test_session_files.py tests/test_w04_session_commands.py tests/test_builtin_process_tool.py tests/test_application_tools.py tests/test_application_runs.py tests/test_cli.py tests/test_tui.py tests/test_w06_integration_delivery.py tests/test_t08_e2e.py tests/test_t07_1_e2e.py tests/test_permission_delivery.py -q` -> **625 passed, 3 skipped in 65.62s**。
- `conda run --no-capture-output -n re-uthcode python -m pytest -q -rs` -> **1309 passed, 3 skipped in 230.91s**；三个 skip 仍为 Anthropic/OpenAI Compat/OpenAI Responses live validation，均明确要求 `UTHCODE_RUN_LIVE=1`。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q` -> **23 passed in 4.67s**。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests eval` -> exit code **0**。
- `conda run --no-capture-output -n re-uthcode python -m pip check` -> **No broken requirements found.**
- `git diff --check` -> exit code **0**；仅有 LF/CRLF 转换提示，没有 whitespace error。

### R1 负向扫描与状态

- `rg -n 'build_system_prompt|SystemPromptContext' src/uthcode` -> **0 条**。
- `rg -n 'ReasoningPart.*TextPart|text_values.*reasoning|reasoning.*text_values' src/uthcode/integrations/providers` -> **0 条**；同一扫描扩展到 `tests` 的命中均为合法 typed contract fixture，未出现生产降级逻辑。
- `rg -n 'ensure_session\(' src/uthcode/interfaces` -> 两处，分别位于 CLI 真实 exec prompt 和 TUI `_start_turn`；无启动路径命中。
- `rg -n 'ReplayManager|HistoryManager|SessionMigration|EncodingManager|SecretManager' src tests` -> **0 条**。
- `rg -n 'chardet|charset_normalizer|EncodingManager|EncodingRegistry' src tests` -> **0 条**。
- `rg -n 'alternate screen|alternate_screen|CSI 3J|\\x1b\[3J|mouse_support=True|full_screen=True' src/uthcode/interfaces` -> **0 条**。
- `rg -n 'compose_generation_request\(' src/uthcode` -> 一个定义、两个 Application 正式调用点。

当前 Checklist 为 **64 项 `[x]`、2 项 `[ ]`**。仅保留真实 Windows Terminal 人工验收，以及因该验收未完成而不能成立的 T11 `implemented_unarchived` 状态门槛；未把这两项虚构为自动通过。`docs/Context-Index.md` 因此继续保持 F01 `not_implemented`，工作包未归档、未 commit、未 push。

### R1 Windows Terminal 边界

结果仍为 **NOT VERIFIED**：只读环境没有 Windows Terminal 窗口（`TERM=dumb`，无 `WT_SESSION`/`TERM_PROGRAM`/`WindowsTerminal` 进程；`wt.exe` 仅表示命令可用）。没有自动启动或操控 Windows Terminal，也没有把 DummyOutput/PTY 回归冒充视觉验收。reasoning/final 流式刷新、bar 色、Markdown fence、中文 shell 输出、scrollback、resize、复制和快捷键仍待人工执行并记录。

### R1 UTF-8 guard

R1 文档修改后重新执行：`conda run --no-capture-output -n re-uthcode python C:\Users\93445\.codex\skills\uth-utf8-guard\scripts\check_utf8_docs.py docs/Context-Index.md docs/context/A01-AgentRuntime/AgentRuntime-Context.md docs/context/A03-State/State-Context.md docs/context/A04-Orchestration/Orchestration-Context.md docs/context/TUI/README.md "docs/core-design/A01-AgentRuntime/02-原生协议快照.md" "docs/core-design/A01-AgentRuntime/03-系统指令权威链路.md" "docs/core-design/A04-Orchestration/02-可替换交互层.md" docs/user-manual/getting-started.md "docs/work/F01-TUI回复链路与Session恢复修复/F01-TUI回复链路与Session恢复修复-checklist.md" "docs/work/F01-TUI回复链路与Session恢复修复/feedback/W06-integration-delivery-feedback.md"` -> **OK: 11 file(s) passed UTF-8 guard**。

## 返工 R2：复审更正与最终自动证据

### 更正说明

R1 复审指出 preview 证据直接构造 `RenderBatch` 并调用 `_apply_batch`，以及 combined 测试没有核对恢复后的完整 typed request。本轮已将两个直接 preview 测试替换为 `test_tui_streaming_previews_commit_safe_reasoning_before_final`：scripted Provider 真实发送多个带 0.25 秒可观察间隔的 `ReasoningDelta`/`TextDelta`，通过 TUI `_start_turn` 和 `_consume_turn` 消费；在 generation task 完成前采样两组不同 reasoning/assistant preview，并确认 safe reasoning block 已进入 emitted permanent scrollback，terminal authority 后 formal answer 只出现一次。没有修改生产代码。

`test_formal_tui_entry_tools_restart_resume_and_continue_in_order` 现进一步检查 fresh Application 的第一个 continuation request：旧 formal user request、带 `ReasoningPart` 的双 `ToolCallPart`、双 `ToolResultPart`、带 `ReasoningPart` 的 final `TextPart` 按 typed 顺序存在，最后才是唯一 `Message("user", (TextPart("continue"),))`。R1 的首轮矩阵、首轮总结和 R1 记录保持原文；本节只追加 R2 的更正和当前结论。

### Checklist 56/57/82 重新核对

- Checklist 56：现在由真实 scripted Provider→TUI 流式链证明，两次 reasoning preview、safe Markdown committed scrollback 和 terminal 前置观察均通过，保持 `[x]`。
- Checklist 57：同一真实链证明两次 assistant preview distinct、draft 不写入 permanent、final authority 只提交一次，保持 `[x]`。
- Checklist 82：真实 TUI adapter 链已覆盖 reasoning→two-tool FIFO batch→final→关闭首 Application→fresh Application `/resume`→continue，并核对 typed continuation request，保持 `[x]`。
- Checklist 83 真实 Windows Terminal 人工项继续 `[ ]`；Checklist 100 是依赖全部 Checklist 的最终状态门槛，继续 `[ ]`。当前统计为 **64 项 `[x]`、2 项 `[ ]`**，`docs/Context-Index.md` 继续为 F01 `not_implemented`。

### R2 更新后的十三类问题矩阵

下表是本次复审后的最终自动证据视图；此前首轮矩阵仍保留在文件前部，R1/R2 均为 append-only 记录。

| 编号 | 当前自动证据 | 状态 |
| --- | --- | --- |
| F-1 | R2 `test_tui_streaming_previews_commit_safe_reasoning_before_final` 真实 Provider/TUI 链、W05 有序 renderer 测试、R2 combined 顺序测试 | 自动证据已关闭；真实 Windows Terminal 视觉未验证 |
| F-2 | W01 Context Compiler、三 Provider mapping、普通 history 伪 system 标签和 exact current-user-tail 测试 | 自动证据已关闭 |
| F-3 | W02 typed `ReasoningPart`/`TextPart`、STOP gate、`TurnResult.final_text` 与 W05 preview/final 回归 | 自动证据已关闭 |
| F-4 | W03 staged safe replay、W05 bounded hydrate、R1 fresh Application replay 测试、R2 continuation typed history request | 自动证据已关闭；真实 Windows Terminal 视觉未验证 |
| P-1 | W06 正式 TUI 四输入测试逐条断言独立 current user tail | 自动证据已关闭 |
| P-2 | Prompt caller audit：无 `build_system_prompt`/`SystemPromptContext`，唯一 `compose_generation_request` 定义 | 自动证据已关闭 |
| P-3 | W02 Provider/event/history contract、W05 chronological renderer 和 semantic bar 测试 | 自动证据已关闭 |
| P-4 | W02 同/跨 identity carrier、part-local Transcript 与 fallback 负向扫描 | 自动证据已关闭 |
| P-5 | W02 reasoning-only/空 TextPart STOP 受控失败测试 | 自动证据已关闭 |
| P-6 | W04 UTF-8/OEM/ANSI/非法 bytes/中文路径 Bash 回归和无编码猜测依赖扫描 | 自动证据已关闭；真实 Windows Terminal 人工视觉未验证 |
| P-7 | W04 Tool summary/FIFO/status/redaction、W05 Tool projection、R2 two-tool combined chain | 自动证据已关闭 |
| P-8 | W02 part-local storage、W03 replay、W04 v3 compatibility、R1 fresh Application two-tool replay/counts/`/new` 测试 | 自动证据已关闭；真实 Windows Terminal 视觉未验证 |
| P-9 | W03 CLI lazy、W05 startup/help/status/picker、W06 first-input/picker 测试 | 自动证据已关闭 |

矩阵中不再把缺少真实 Terminal 视觉或真实 OS 进程的内容写成“自动关闭”；F-4/P-8 的“fresh Application”明确是 process-boundary 等价自动证据，不是独立进程验收。

### R2 验证结果

- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_w06_integration_delivery.py` -> **12 passed in 5.46s**。
- 定向 F01/T09～T11 集合（同 R1 命令）-> **624 passed, 3 skipped in 70.84s**；skip 仍为三个需 `UTHCODE_RUN_LIVE=1` 的 live Provider 验证。
- `conda run --no-capture-output -n re-uthcode python -m pytest -q -rs` -> **1308 passed, 3 skipped in 229.00s**。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q` -> **23 passed in 5.79s**。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests eval` -> exit code **0**。
- `conda run --no-capture-output -n re-uthcode python -m pip check` -> **No broken requirements found.**
- `git diff --check` -> exit code **0**；仅有 LF/CRLF 转换提示，没有 whitespace error。

### R2 文档与交付边界

最终 UTF-8 guard 重新覆盖 11 个实际修改 Markdown，结果为 **OK: 11 file(s) passed UTF-8 guard**。真实 Windows Terminal 仍为 **NOT VERIFIED**：没有可交互窗口，未执行视觉流式、bar 色、Markdown fence、中文 shell、scrollback、resize、复制或快捷键验收。未执行 commit、push、PR、merge、归档或其他 Git 写入。

## 返工 R3：真实界面验收与 JSONL 最终收口

用户实际界面验收原话：`界面基本没问题`。本节只记录该结论，不扩写成用户逐项确认了某个具体视觉/交互子项。

### 真实 Session JSONL 只读核验

- Session：`3f73e6a2b55d4bcf9c14803fb9aa4989`
- metadata schema=3；project=`D:\project\Re-UthCode`；4 turns；36 transcript entries；seq `1..36` 严格连续。
- role/part 矩阵为 `user/text`；`assistant/reasoning,text,tool_call`；`tool/tool_result`；无 `system` entry 污染。
- exact reasoning/formal 互相包含计数均为 0；U+FFFD 计数为 0。
- 7 个 ToolCall/ToolResult 配对全部 ID 匹配、无 pending；FIFO result seq 为 `8,19,20,24,28,33,34`；包含双 Glob 以及双 ToolResultRead+Grep 场景。
- 正式 `UthCodeApplication.session_replay()` 产出 29 条 safe replay：`user/reasoning/assistant/tool terminal` 有序；7 条 tool 仅为安全摘要（Bash/Glob/ReadFile/ToolResultRead/Grep），Grep failed 状态正确；不投影 tool_call 或 raw result 正文。
- replay 读取前后 transcript SHA256 与 mtime 均不变。
- transcript 多轮输入精确存在：`你好`、组合 reasoning+Bash+fence、`当前运行环境`、`agent.py说明`；最后 Turn 含多轮 tool 与 final，证明持续对话 durable。
- `writer.lock` 仍由用户进程持有，未触碰；timeline 为空，不据此声称 active checkpoint 恢复。

### JSONL 与 `/resume` 的证据边界

JSONL 不记录 `/resume` 动作本身。Session 恢复结论由用户的实际界面验收与既有 W06 E2E 支撑（`test_process_boundary_resume_replays_mixed_turn_once_and_new_is_empty`、`test_formal_tui_entry_tools_restart_resume_and_continue_in_order`），不从 JSONL 反推用户未逐项说明的视觉观察。

### R3 最终状态

- 用户界面验收结论已写入本 Feedback；据此 Checklist 最后两项已勾选，当前全部 Checklist 均有证据。
- `docs/Context-Index.md` 已将 F01 从 `not_implemented` 移至 `implemented_unarchived`；工作包目录仍在 `docs/work/`，未归档。
- 本 Worker 未执行 commit、push、PR、merge 或其他 Git 写入。

### R3 最终验证记录

- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_w06_integration_delivery.py` -> **12 passed in 6.50s**。
- F01/T09～T11 定向集合（与 R1/R2 相同命令）-> **624 passed, 3 skipped in 82.02s**；3 个 skip 均为需显式设置 `UTHCODE_RUN_LIVE=1` 的 live Provider 验证。
- `conda run --no-capture-output -n re-uthcode python -m pytest -q -rs` -> **1308 passed, 3 skipped in 207.23s**；3 个 skip 仍为 Anthropic/OpenAI Compat/OpenAI Responses live validation。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q` -> **23 passed in 6.64s**。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests eval` -> exit code **0**。
- `conda run --no-capture-output -n re-uthcode python -m pip check` -> **No broken requirements found.**
- UTF-8 guard 覆盖 11 个实际修改 Markdown -> **OK: 11 file(s) passed UTF-8 guard**。
- `git diff --check` -> exit code **0**；仅有工作区 LF 将在 Git 下次触碰时转换为 CRLF 的提示，无 whitespace error。
- Checklist 统计为 **66 项 `[x]`、0 项 `[ ]`**；F01 当前状态为 `implemented_unarchived`。本 Worker 仍未执行 Git 写入或归档。
