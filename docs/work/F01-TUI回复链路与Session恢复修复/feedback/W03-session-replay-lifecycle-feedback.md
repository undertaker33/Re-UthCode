# W03 Feedback：Session Replay 与惰性生命周期

## 范围与结论

- 本次严格实施 F01/T04：Application 安全 replay DTO、staged resume 原子边界、惰性 Session 生命周期和必要 CLI cold-start 调整。
- 未修改 `src/uthcode/interfaces/tui/`、Provider/History contract、process tool、Tool redaction policy、当前事实文档、其它 Worker Feedback，也未执行任何 Git 写操作。
- Application 现在在 resume 成功提交前准备完整 safe replay；`exec <prompt>` 仍在真实 prompt 前 lazy ensure；默认 CLI 启动不再无条件创建 Session。
- TUI 的实际 cold-start ensure 移除、replay hydrate 和流式展示仍由 W05 负责，本 Worker 未提前修改 TUI。

## Replay DTO 与安全投影

- 新增 `SessionReplayRecord`，字段为 `session_id`、durable `sequence`、`turn_id`、`kind`、`text`，以及 Tool 终态所需的 `tool_name`、`tool_call_id`、`status`、`is_error`、`created_at`；DTO 不携带 Provider、History、Session file 或 UI 类型，并提供 JSON-safe `to_dict()`。
- `ApplicationSession.replay` 和 `/resume` 的 `SessionChanged.replay` 均为按 durable sequence 排序的不可变记录元组。
- Projection 只遍历 `Transcript.semantic_units(complete_only=True)`：
  - `USER_MESSAGE` 首条投影为 `user`，同一 Turn 后续用户输入或显式 `USER_STEERING` 投影为 `steering`。
  - typed `ReasoningPart`、正式 `TextPart` 分别投影为 `reasoning`、`assistant`。
  - ToolCall 只建立内部 call-to-summary 映射；ToolResult 只产生一个 safe `tool` terminal record，复用 `ApplicationToolService.describe_tool_call()`，摘要有界且不接收 raw result。
  - 不完整 semantic unit、raw ToolResult content/metadata、Tool arguments、native payload、pending interaction 和 Runtime checkpoint 均不进入 DTO。

## 原子 resume 与生命周期

- staged resume 在 writer 已加载的 snapshot 上先构造 replay，再执行 instruction-state 更新并提交 Session；projection/build、busy、unknown、corrupt、storage 失败均在切换前释放 staged writer，保留当前 active Session、锁和 replay。
- 已持有目标 Session 的 `/resume <id>` 使用同一 writer 下的候选 replay/loader 刷新，不重复打开锁或创建 throwaway Session。
- `session_catalog()`、`status()`、`create_run()`、`close()` 在无 active Session 时保持只读/安全；`/new` 只创建一个新 Session；`exec` 仅因真实 prompt 调用 `ensure_session()`。
- 默认 CLI 入口删除无 prompt 的提前 `ensure_session()`；故障注入验证 lazy ensure 失败时没有 active Session、永久用户记录或 Provider request。

## 修改文件

生产代码：

- `src/uthcode/application/sessions.py`
- `src/uthcode/application/generation.py`
- `src/uthcode/application/commands/models.py`
- `src/uthcode/application/commands/builtins.py`
- `src/uthcode/application/commands/__init__.py`
- `src/uthcode/application/__init__.py`
- `src/uthcode/interfaces/cli.py`

测试与工作包记录：

- `tests/test_w04_session_commands.py`
- `tests/test_cli.py`
- `docs/work/F01-TUI回复链路与Session恢复修复/F01-TUI回复链路与Session恢复修复-checklist.md`
- `docs/work/F01-TUI回复链路与Session恢复修复/feedback/W03-session-replay-lifecycle-feedback.md`

## 验证结果

- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_w04_session_commands.py tests/test_application.py tests/test_cli.py tests/test_session_files.py -q`：`65 passed`。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q`：`23 passed`。
- `conda run --no-capture-output -n re-uthcode python -m pytest -q`：`1265 passed, 3 skipped`。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests eval`：退出码 `0`。
- `conda run --no-capture-output -n re-uthcode python -m pip check`：`No broken requirements found.`
- `git diff --check`：退出码 `0`；仅有 Windows 工作副本的 LF/CRLF 提示，无 whitespace 错误。

## Checklist 证据

- 已勾选 T04 的定向测试、Application replay DTO、安全过滤与 pending 排除、无 Provider/Turn/Transcript 追加副作用及 busy/corrupt/unknown/storage 原子失败、exec/`/resume`/`/new` 生命周期和 lazy ensure failure 项。
- T04“ TUI 冷启动后立即退出、只执行 help/status、打开并关闭 Session Picker 均不新增 Session ID”保持未勾选：TUI 启动入口、Picker hydrate 和流式显示明确属于 W05，当前仍有待 W05 移除的 `interfaces/tui/app.py` 启动 ensure。

## 偏差、未完成项与风险

- 未进行真实 Windows Terminal 人工视觉验收；reasoning/final 颜色、流式 preview、scrollback 和 `/resume` hydrate 由 W05/T07/T08 负责。
- 未修改 `runs.py` 或 TUI：Application headless `create_run()` 仍是无持久副作用的 Run 构造；支持入口的真实普通 prompt 由 CLI `exec` 在 Provider/Turn 前 lazy ensure，TUI 首条输入接线由 W05 完成。
- 没有新增依赖、没有 Session 删除/GC/migration、没有新增第二 replay store。

## UTF-8 guard

- files checked: `docs/work/F01-TUI回复链路与Session恢复修复/feedback/W03-session-replay-lifecycle-feedback.md`、`docs/work/F01-TUI回复链路与Session恢复修复/F01-TUI回复链路与Session恢复修复-checklist.md`
- result: `conda run --no-capture-output -n re-uthcode python C:\Users\93445\.codex\skills\uth-utf8-guard\scripts\check_utf8_docs.py docs/work/F01-TUI回复链路与Session恢复修复/feedback/W03-session-replay-lifecycle-feedback.md docs/work/F01-TUI回复链路与Session恢复修复/F01-TUI回复链路与Session恢复修复-checklist.md`：`OK: 2 file(s) passed UTF-8 guard`。
- repaired encoding issues: none

## 返工第一轮（Reviewer CHANGES REQUESTED）

### Finding

- P1：`src/uthcode/application/sessions.py::_entry_parts` 只处理当前 part-local `payload["part"]`/`payload["parts"]`，未处理 W02 保留的合法 Session v3 full-message `payload["message"]`，旧 Session resume 会被错误映射为 corrupt。
- Reviewer 同时要求 lazy ensure failure 必须从普通 `exec` 的真实 Application 路径触发，而不是直接调用 `ensure_session()`，并证明没有永久 user、Provider call 或半个 Run。

### 实际修改

- `_entry_parts` 增加只读兼容分支：当 payload 携带旧 v3 `message` Mapping 时调用既有 `Message.from_dict()`，按原 `ReasoningPart -> TextPart` 顺序生成 replay；不改写 Transcript 文件，不引入 migration 或第二存储。
- 新增旧 v3 full-message replay 回归：reasoning/text 各投影一次且顺序不变；resume 前后 `transcript.jsonl` bytes 与 `st_mtime_ns` 均保持不变。
- 将 lazy ensure failure 回归改为真实 `_stream_exec()` 普通 prompt 路径：注入 Session create failure 后断言返回受控失败、Session ID 集合为空、Provider request 为空、`create_run` 未被调用，随后关闭 Application 安全。
- 未修改 TUI、Provider/History contract、process/tool redaction、其它 Feedback 或 Git；T04 Checklist 已有勾选项均保持不变，TUI cold-start 项仍留给 W05。

### 返工验证

- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_w04_session_commands.py tests/test_application.py tests/test_cli.py tests/test_session_files.py -q`：`66 passed`。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q`：`23 passed`。
- `conda run --no-capture-output -n re-uthcode python -m pytest -q`：`1266 passed, 3 skipped`。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests eval`：退出码 `0`。
- `conda run --no-capture-output -n re-uthcode python -m pip check`：`No broken requirements found.`
- `git diff --check`：退出码 `0`；仅有 Windows 工作副本 LF/CRLF 提示，无 whitespace 错误。
- UTF-8 guard：`conda run --no-capture-output -n re-uthcode python C:\Users\93445\.codex\skills\uth-utf8-guard\scripts\check_utf8_docs.py docs/work/F01-TUI回复链路与Session恢复修复/feedback/W03-session-replay-lifecycle-feedback.md docs/work/F01-TUI回复链路与Session恢复修复/F01-TUI回复链路与Session恢复修复-checklist.md`：`OK: 2 file(s) passed UTF-8 guard`。

## 返工第二轮（Reviewer CHANGES REQUESTED）

### Finding

- P1：真实 pre-W02 legacy writer 会为 `ReasoningPart + TextPart` 写两条 Transcript entry；两条 entry 各自重复同一个完整 `payload["message"]`，因此旧实现会把同一 logical Message replay 两遍。

### 实际修改

- `_project_replay()` 增加仅针对 legacy full-message payload 的 `(session_id, turn_id, message_id)` identity 集合；相同 logical Message 的后续 envelope 跳过，当前 W02 part-local `payload["part"]` entry 不进入该去重分支。
- 回归测试改为真实两条 legacy entry（reasoning/text envelope 各一条，共享完整 message 与 message_id），断言 replay 中 `reasoning`、`assistant` 各出现一次且顺序正确。
- 同一回归继续断言 resume 前后 `transcript.jsonl` bytes 和 `st_mtime_ns` 不变，证明兼容 replay 不改写 durable Transcript。
- 未修改 TUI、Provider/History contract、process/tool redaction、其它 Feedback 或 Git；Checklist 原有证据保持不变。

### 二审验证

- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_w04_session_commands.py tests/test_application.py tests/test_cli.py tests/test_session_files.py -q`：`66 passed`。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q`：`23 passed`。
- `conda run --no-capture-output -n re-uthcode python -m pytest -q`：`1266 passed, 3 skipped`。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests eval`：退出码 `0`。
- `conda run --no-capture-output -n re-uthcode python -m pip check`：`No broken requirements found.`
- `git diff --check`：退出码 `0`；仅有 Windows 工作副本 LF/CRLF 提示，无 whitespace 错误。
- UTF-8 guard：`conda run --no-capture-output -n re-uthcode python C:\Users\93445\.codex\skills\uth-utf8-guard\scripts\check_utf8_docs.py docs/work/F01-TUI回复链路与Session恢复修复/feedback/W03-session-replay-lifecycle-feedback.md docs/work/F01-TUI回复链路与Session恢复修复/F01-TUI回复链路与Session恢复修复-checklist.md`：`OK: 2 file(s) passed UTF-8 guard`。
