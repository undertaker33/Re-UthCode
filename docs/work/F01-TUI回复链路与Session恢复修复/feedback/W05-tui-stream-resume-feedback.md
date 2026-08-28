# W05 TUI 流式时序与 Resume Hydrate Feedback

## 结果

W05 已完成 T07 -> T08 的 TUI 范围实施。TUI 只消费 Application 已提供的 `SessionReplayRecord` / `SessionChanged` 公共投影；没有读取 Session 文件、Core History、Provider 或 raw Tool payload，也没有执行 Git 写操作。

## 关键修复

- `AgentEventRenderer` 改为单一有序 block projection。reasoning segment、assistant block、Tool 和 terminal operation 保留事件到达顺序，不再以 `message_id:kind` 多字典分组 flush。
- reasoning 使用独立 `reasoning_message()` 和显式 `reasoning_accent` bar；安全 Markdown 块可按刷新周期提交，未闭合尾部留在 typed preview。
- assistant delta 只进入独立临时 preview；权威 `AssistantMessageCompleted` 使用 `authoritative=True`，永久 formal block 只提交一次。权威提交前会先冲刷更早 reasoning 尾部；correction 仅追加，不回写 scrollback。
- `RenderBatch.operations` 提供有序显示操作，TUI 按 operation 顺序消费，避免同一批 reasoning/final/tool 被重新分组；`_streams` 改为按时间线保存的列表。
- `SessionChanged(restored=True)` 替换 Run 后按 DTO 原顺序 hydrate。回放使用正式 user/reasoning/assistant/tool renderer，每 32 条记录一次 synchronized emit，批间 async yield；回放不伪造 AgentEvent/Turn/Provider 调用，不进入 live stream projection。
- TUI 启动移除无条件 `ensure_session()`；首条普通输入在启动 Turn 前惰性 ensure，失败时不启动 Run、不产生永久 user record，仍可关闭并继续输入。

## 修改文件

- `src/uthcode/interfaces/tui/app.py`
- `src/uthcode/interfaces/tui/rendering.py`
- `src/uthcode/interfaces/tui/terminal.py`
- `tests/test_tui.py`
- `docs/work/F01-TUI回复链路与Session恢复修复/F01-TUI回复链路与Session恢复修复-checklist.md`（仅更新已验证 checkbox）
- 本 Feedback 文件

## 验证

以下命令均在 `re-uthcode` Conda 环境执行：

- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_tui.py -q` -> **88 passed**。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_tui.py tests/test_w04_session_commands.py -q` -> **106 passed**。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q` -> **23 passed**。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests eval` -> 通过。
- `conda run --no-capture-output -n re-uthcode python -m pip check` -> `No broken requirements found.`
- `git diff --check` -> 通过；仅有 Git 关于 LF 将来转换为 CRLF 的提示，无 whitespace error。

新增/调整的 TUI 回归覆盖：交错 reasoning/assistant 多 segment 的 operation 顺序、reasoning/final 标题与 bar 色值、assistant preview 到 authority 的一次永久提交、late reasoning tail、真实 provider stream、replay 有序 hydrate、32 条 bounded batch 与批间 yield、live stream 隔离、lazy startup、无 Session 的 help/status/resume/exit。

## Checklist 证据

- T04 的 TUI cold-start 项：`test_tui_startup_is_lazy_and_first_input_ensures_session` 与 `test_tui_cold_start_help_status_picker_and_exit_do_not_create_session`。
- T07：精确 renderer timeline、真实 stream 顺序/标题次数、semantic bar 色值、assistant preview/authority、correction append-only 与 `_blocks` 列表 projection 测试；已勾选 Checklist 中有直接证据的项。
- T08：`test_resume_hydrate_is_ordered_bounded_and_does_not_enter_live_stream`、`test_resume_hydrate_yields_between_bounded_batches`，以及 W04 的 Application replay 安全/原子/无副作用测试；已勾选 safe replay 与 bounded batch 项。

未勾选的 Checklist 项保留给 W06 的跨层/真实跨进程入口验收，未把仅由静态代码推断的 preview 次数、完整跨进程重启、恢复后下一 Turn 和真实失败屏幕状态冒充已验证。

## 未验证项与风险

- 未执行真实 Windows Terminal 的人工视觉验收；颜色、窄终端布局和 ANSI 渲染仍需 W06/T10 按真实入口检查。
- W05 未修改 Application replay DTO、Session persistence、Provider、Core、process tool 或当前事实文档；这些边界由 W01-W04/W06 负责。

## 返工 R1：首审 CHANGES REQUESTED 后修复

### Reviewer findings

首审指出两项 P1：Tool/failed/cancelled 边界会把未收到 `AssistantMessageCompleted` 的 assistant delta force 成正式块；以及 TUI preview 使用了未在 prompt_toolkit `Style` 中声明的 `preview.reasoning(.role)` 样式。

### 修复

- 新增 `_render_forced_reasoning()`，ToolStarted/ToolFinished 边界只提交 reasoning 尾部；assistant preview 保留在临时 projection，等待权威完成。
- failed/cancelled terminal 和 consumer cancellation/failure 清理 assistant pending/open 状态，不把未完成 assistant 预览写入永久 scrollback；completed terminal 仍由唯一 `final_text` authority 提交一次。
- `_style()` 增加 `preview.reasoning` 与 `preview.reasoning.role`，role 使用 `PALETTE.reasoning_accent`，formal preview 继续使用 `PALETTE.success`。
- 新增精确回归：Tool 边界 reasoning/assistant 分离、failed 与 cancelled 丢弃 assistant preview、completed final 单次提交，以及 prompt_toolkit 实际 style/fragment 解析结果。

### R1 验证

- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_tui.py -q -k "reasoning_preview or tool_boundary or failed_or_cancelled or completed_terminal"` -> **5 passed**。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_tui.py -q` -> **93 passed**。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_tui.py tests/test_w04_session_commands.py -q` -> **111 passed**。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q` -> **23 passed**。
- `conda run --no-capture-output -n re-uthcode python -m pytest -q` -> **1298 passed, 3 skipped**。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests eval` -> 通过。
- `conda run --no-capture-output -n re-uthcode python -m pip check` -> `No broken requirements found.`
- UTF-8 guard（W05 Feedback 与 F01 Checklist）-> `OK: 2 file(s) passed UTF-8 guard`。
- `git diff --check` -> 通过；仅有 LF/CRLF 转换提示，无 whitespace error。

R1 仍未执行真实 Windows Terminal 人工视觉验收；该项保留给 W06/T10。未执行 Git 写操作。

## 返工 R2：二审 CHANGES REQUESTED 后修复

### Reviewer finding

二审发现 `_consume_turn()` 的 `terminal is None` flush 被缩进到事件循环内部，导致每个非 terminal 事件后立即 force assistant preview 并错误设置 `ready`。

### 修复与回归

- 将 `if terminal is None: await _flush_streams()` 恢复到 `while True` 结束后的同级位置；生成期间只由 renderer interval flush，assistant delta 保持 preview，直到 `AssistantMessageCompleted` / completed terminal 权威提交。
- 新增真实 `_consume_turn()` 回归：delayed `AssistantMessageCompleted` 前 assistant delta 仅存在 preview；真实 consumer cancellation 与 projection failure 均丢弃 draft；completed final 只产生一个 formal 标题和一次正文。
- 保留 R1 的 Tool、failed、cancelled 边界与 prompt_toolkit reasoning preview style 回归。

### R2 验证

- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_tui.py -q -k "real_consumer"` -> **3 passed**。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_tui.py tests/test_w04_session_commands.py -q` -> **114 passed**。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_tui.py -q` -> **96 passed**。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q` -> **23 passed**。
- 首次全量回归出现 1 个既有硬件光标时序失败（1300 passed, 3 skipped）；该测试单独重跑通过，随后全量重跑 -> **1301 passed, 3 skipped**。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests eval` -> 通过。
- `conda run --no-capture-output -n re-uthcode python -m pip check` -> `No broken requirements found.`
- UTF-8 guard（R2 追加后的 Feedback 与 F01 Checklist）-> 通过。
- `git diff --check` -> 通过；仅有 LF/CRLF 转换提示，无 whitespace error。

R2 未执行真实 Windows Terminal 人工视觉验收，未修改 Application/Core/Provider/History/process tool，未执行 Git 写操作。
