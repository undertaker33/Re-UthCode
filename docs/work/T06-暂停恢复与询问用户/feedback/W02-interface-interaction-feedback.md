# W02-interface-interaction Feedback

## 执行范围与前置核对

本轮按 `prompt/W02-interface-interaction-prompt.md` 连续完成 Task 4、Task 5。已读取并遵守 `AGENTS.md`、`SRe-AGENTS.md`、`docs/work/README.md`、T06 原始需求/Spec/Tasks/Checklist 和 W01 Feedback。W01 Task 1–3 Feedback 存在且标记完成；当前 HEAD 为任务书要求的 `7d9dd1dfb328a60a3e2f0b09334667052f5e34ec`，没有执行 Git 写操作。

修改前按 T06 要求执行全量测试，旧 CLI 在暂停后没有收口，命令在 124 秒超时；这与 W01 记录的 W02 缺口一致。没有修改冻结的需求原文、Spec、Tasks 或 Prompt，也没有修改 Core、Application、Provider、普通 Tool、配置和 System Prompt。

## Task 4：非交互 CLI 暂停收口

`uthcode exec` 现在只消费 Application 公开的 `AgentEvent`。遇到 `TurnPaused` 时：

- `user_input_required` 输出 `generation requires interactive input`；
- `provider_unavailable` 输出 `provider temporarily unavailable`；
- 其他暂停原因输出不含运行细节的通用暂停诊断；
- 只调用一次公开 `turn.cancel()`，继续消费同一事件流直到 Application 关闭 Turn；
- 暂停期间不构造恢复响应、不读取 stdin、不自动回答或重试；
- 抑制取消收口中可能出现的 final projection，stdout 不输出伪 final，返回码固定为 1；
- 原有 completed=0、普通失败=1、Ctrl+C=130 和配置/usage=2 语义保持。

网络错误和限流错误均有离线测试，错误消息中的 secret 不会进入 stderr。

## Task 5：默认 TUI 暂停与结构化问答

新增 `interfaces/tui/interaction.py`，只保存临时焦点、动作选择、问题索引、答案草稿和复核状态；Application 的 `pending_pause` 仍是唯一权威事实。TUI 通过公开 `TurnHandle` 完成：

- 对话根页面双 Esc 请求 cooperative pause，先显示 `pausing…`，安全边界后显示 `paused`；原有直接 cancel 分支已替换；
- 暂停动作层提供 Resume/Cancel，网络暂停提供 Retry/Cancel；暂停期间保留原 run/turn 和活动句柄，不启动第二个 Turn；
- AskUser 面板支持 text、single-select、multi-select、Other、上一题、复核和提交；最终只调用 `turn.resume(UserInputResponse(...))`；
- `TurnPausing`、`TurnPaused`、`TurnResumed` 只更新临时活动状态，答案正文不进入工具活动或永久系统消息；
- modal、picker、Slash 候选和问题层优先消费 Esc，关闭交互层清空双 Esc arm；`/model` 等上下文不会串联触发根页面暂停；
- Ctrl+C、退出和 shutdown 仍取消当前 Turn，不显示“已保存”，不产生跨进程恢复；terminal 后关闭交互状态和事件消费任务。

## 实际修改文件

- `src/uthcode/interfaces/cli.py`
- `src/uthcode/interfaces/tui/interaction.py`（新增）
- `src/uthcode/interfaces/tui/app.py`
- `src/uthcode/interfaces/tui/rendering.py`
- `src/uthcode/interfaces/tui/terminal.py`
- `tests/test_cli.py`
- `tests/test_tui.py`
- `docs/TUI/README.md`
- `docs/work/T06-暂停恢复与询问用户/T06-暂停恢复与询问用户-checklist.md`：仅将 Task 4、Task 5 既有 checkbox 改为完成。
- 本 Feedback 文件。

没有删除整个文件；删除的旧行为是 TUI 根页面双 Esc 直接取消分支。没有新增 adapter、alias、兼容入口、第二套运行状态、Core waiter、持久化/恢复模块或 Interface 对 Core/Integration 的直接依赖。

## 测试与验证证据

以下命令均使用 `conda run --no-capture-output -n re-uthcode`，没有真实 Provider 请求：

```text
python -m pytest -q tests/test_cli.py tests/test_tui.py
56 passed in 14.90s

python -m pytest -q tests/test_agent_loop.py tests/test_application_runs.py tests/test_application_tools.py tests/test_package.py tests/test_architecture_boundaries.py
87 passed in 9.36s

python -m pytest -q
494 passed, 3 skipped in 36.17s

python -m compileall -q src tests
passed; no output

python -m pip check
No broken requirements found.

git diff --check
passed; only Git reported existing LF/CRLF working-copy warnings, no whitespace error
```

定向测试包含：CLI AskUser/network pause-cancel、stderr 敏感信息隔离、stdout final 抑制；TUI 根页面双 Esc pause/resume、AskUser 文本往返、选择/多选/Other/复核状态、暂停取消、焦点与模型 picker Esc、scrollback/Unicode/Slash/渲染回归。TUI 取消测试确认 `_generation_task`、活动 Turn 和 `_background_tasks` 均收口；W01 Application 回归确认 terminal/shutdown 后私有 waiter 清理。

## Checklist 证据

### Task 4

- 5 项已勾选；CLI 测试从 Application 公开入口触发三类可见暂停，检查安全诊断、只取消一次、事件流收口、stdout 为空和退出码 1。
- Ctrl+C 既有测试仍通过并返回 130；暂停路径没有恢复命令或 stdin 读取。

### Task 5

- 4 项已勾选；TUI 测试覆盖独立交互状态、根页面双 Esc、暂停菜单、问答复核提交、选择/多选/Other、Esc 上下文、取消和后台清理。
- `docs/TUI/README.md` 已记录双 Esc cooperative pause、Resume/Retry/Cancel、结构化问答和同进程非持久化边界。

Task 6–8 仍由后续 Worker 负责，本轮没有勾选或实施。

## 未决风险与范围外事项

- 任务书要求的 Windows Terminal 人工验收尚未由本轮自动测试替代；需要用户在真实 Windows Terminal 中检查双 Esc、IME、窗口缩放和宿主 scrollback。
- Provider 集成测试仍遵守既有 skip 门禁，未产生真实费用请求。
- 本轮不提供进程退出、重启、崩溃或断电恢复；下次启动仍创建全新内存 Run。

## 遗留负担清理

本轮未保留被替代的根页面取消入口，也未引入兼容层或双轨逻辑。CLI/TUI 只调用 Application 公共 API；TUI 的 asyncio 任务只属于 Interface 生命周期，退出/取消时会收口。架构测试和全量测试通过，Task 8 的正式遗留扫描与交付收口仍留给 W03。

## 返工轮次 1

### 返工原因与三个验收问题根因

本轮只处理用户指出的三个 W02 验收问题，没有扩大到 W01、W03、Core、Application 或 Provider，也没有修改冻结的需求原文、Spec、Tasks、Prompt 或 Checklist。

1. CLI 的根因是暂停时 projection 已抑制 `turn_cancelled`/`turn_completed`，但 `_stream_exec` 仍在循环结束后先检查 `terminal_code is None`。取消终态因此没有写入 projection code，正常暂停收口被误判为缺少 terminal event，追加了虚假的 Provider 错误。
2. TUI 返回上一题的根因是 `TuiInteractionState.previous_question()` 已恢复 `draft`、答案和选择状态，但 Left 与 Review Esc 的界面路径随后无条件把 prompt_toolkit Buffer 清空；同时旧的 `_load_answer_draft()` 没有把 Other 自定义文本和选择焦点恢复到草稿状态。Review 中若 `other_mode` 仍为真，Esc 还会被误当作退出 Other，而不是返回上一题。
3. TUI Provider retry/cancel 的根因是 `tests/test_tui.py` 只有正常 Provider 和人工探测到的 Retry 行为，没有用 NetworkError/RateLimitError 驱动真实 `UthCodeTUI` 的自动化 Pilot，因此 W02 Feedback 没有正式证据证明同一 Turn 的 Retry、Cancel 和清理边界。

### 实际修复

#### CLI 暂停终态判断

- 保留原有 `TurnPaused` 安全摘要、同一事件流消费和一次 `turn.cancel()`；暂停期间不读取 stdin、不构造恢复响应、不自动重试。
- 循环结束后先判断 `paused_for_noninteractive` 并固定返回 `1`，再进入普通缺失 terminal 的错误分支。因此暂停取消终态不会输出 `turn ended without a terminal event` 或额外 `provider error`。
- 未暂停的 completed、failed、cancelled 和缺失 terminal 路径仍沿用原 projection/诊断语义；Ctrl+C 仍返回 `130`，stdout 不输出 partial 或伪 final。

#### TUI Buffer、draft 和选择状态同步

- 在 `UthCodeTUI` 增加 Interface 内部 `_sync_interaction_buffer()`，Left 和上一题路径统一调用它：文本问题恢复 `interaction.draft`，Other 恢复自定义文本并把光标放到文本末尾；普通单选/多选清空 Buffer。
- `TuiInteractionState._load_answer_draft()` 现在同步恢复文本/Other draft、`selected_options` 和 `option_index`；Other 返回时保持 `other_mode`，单选/多选恢复选择标记。
- Review Esc 只在 `QUESTIONS` 模式下退出 Other；Review 模式始终通过 `previous_question()` 返回最后一题。未修改直接 Enter 会重新提交已有答案进入 Review，修改后才替换对应答案；返回路径不会调用 `TurnHandle.resume()`、提交空答案或创建第二份 pending。

### Provider Retry/Cancel Pilot 与新增测试名称

新增真实 `UthCodeTUI` Pilot：

- `test_tui_provider_retry_pilot_uses_one_turn_and_cleans_up` 参数化 `NetworkError` 与 `RateLimitError`，验证 `provider_unavailable`、默认 Retry、一次公共 `TurnHandle.resume(RetryProviderResponse)`、同一 Turn 第二次 Provider 请求、单次 `AgentRun.start_turn`，以及 `_generation_task`、interaction、活动句柄和 `_background_tasks` 清理。
- `test_tui_provider_cancel_pilot_stops_retry_and_cleans_up` 验证 Provider 暂停后选择 Cancel 不触发第二次请求、不调用 resume、Turn 进入 cancelled、没有保存/恢复提示，并清理同一组 TUI 生命周期对象。
- `test_real_tui_question_back_restores_buffer_and_draft_without_resuming` 覆盖两个文本问题、Review 返回、Buffer 原文与末尾光标、不修改 Enter、新文本替换和最终一次 UserInput resume。
- `test_real_tui_question_back_restores_other_and_selection_state` 覆盖真实 TUI 的 Other 自定义文本、Other 模式、单选标记、多选标记和普通选择的空 Buffer。
- 加强 `test_exec_cancels_turn_when_agent_pauses_for_user_input` 与参数化的 `test_exec_cancels_turn_when_provider_pauses`，验证暂停返回 1、stdout 为空、无缺失 terminal/provider 错误及 cancel 只调用一次；新增 `test_exec_keeps_missing_terminal_diagnostic_for_non_pause_stream` 固化非暂停缺失 terminal 诊断。

### 本轮实际修改文件

- `src/uthcode/interfaces/cli.py`
- `src/uthcode/interfaces/tui/interaction.py`
- `src/uthcode/interfaces/tui/app.py`
- `tests/test_cli.py`
- `tests/test_tui.py`
- 本 Feedback 文件末尾追加本章节。

本轮没有修改 `docs/TUI/README.md`，因为本轮只修正既有实现的终态判断、草稿同步和测试证据，文档描述的最终行为没有新增变化；没有修改 Core、Application、Integration、Provider DTO、普通 Tool 协议或 Checklist，也没有执行任何 Git 写操作。

### 全部验证命令与精确结果

以下命令均通过 `conda run --no-capture-output -n re-uthcode` 执行：

```text
python -m pytest -q tests/test_cli.py tests/test_tui.py
62 passed in 14.98s

python -m pytest -q tests/test_agent_loop.py tests/test_application_runs.py tests/test_application_tools.py tests/test_package.py tests/test_architecture_boundaries.py
87 passed in 9.93s

python -m pytest -q
500 passed, 3 skipped in 40.16s

python -m compileall -q src tests
passed; no output

python -m pip check
No broken requirements found.

git diff --check
passed; only existing LF/CRLF working-copy warnings, no whitespace error
```

新增回归定向结果：

```text
python -m pytest -q tests/test_cli.py -k "pauses_for_user_input or provider_pauses or missing_terminal"
4 passed, 17 deselected in 0.38s

python -m pytest -q tests/test_tui.py -k "real_tui_question_back or provider_retry_pilot or provider_cancel_pilot"
5 passed, 36 deselected in 1.50s
```

### 分层扫描

执行：

```text
conda run --no-capture-output -n re-uthcode rg -n "uthcode\.core|uthcode\.integrations" src/uthcode/interfaces/
```

结果：无匹配；`src/uthcode/interfaces/` 没有直接导入 `uthcode.core` 或 `uthcode.integrations`。扫描命令的 `rg` 无命中状态按扫描成功处理。

### 未完成项与风险

- Windows Terminal 人工验收仍待用户执行；自动化没有替代真实 Windows Terminal 下的双 Esc、IME、窗口缩放和宿主 append-only scrollback 检查。
- Provider 真实网络请求仍遵守既有离线 skip 门禁；本轮只使用离线 NetworkError/RateLimitError Fake Provider，不产生真实费用请求。
- Task 6–8、W03 正式交付收口仍未实施，属于本轮明确范围外；本轮没有修改或勾选其 Checklist。
- 当前工作树已有 W01 和其他前序 W02 改动；本轮只在上述限定文件内追加修复，未执行 commit、stage、push、reset、restore 或其他 Git 写操作。完成后停止，等待再次验收。

### UTF-8 guard

追加前已按字节读取既有 Feedback 并确认 UTF-8 解码正常、无 replacement character 和已知 mojibake 标记。追加后执行：

```text
conda run --no-capture-output -n re-uthcode python C:\Users\93445\.codex\skills\uth-utf8-guard\scripts\check_utf8_docs.py docs/work/T06-暂停恢复与询问用户/feedback/W02-interface-interaction-feedback.md
OK: 1 file(s) passed UTF-8 guard
```
