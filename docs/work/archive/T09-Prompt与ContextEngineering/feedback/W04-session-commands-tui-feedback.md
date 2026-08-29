# W04 Session Commands 与 TUI Feedback

## 1. 执行范围

本轮只执行 W04：Session Slash Commands、Application Session 切换、独立 Session Picker、`/status` 固定 258K usage 投影与 TUI 输入区 ring。没有实现 Task/Plan/Pending Tool/Permission/AskUser/Provider continuation 的跨进程 checkpoint，也没有把 T09 固定预算解释为远端模型物理窗口。

## 2. 实际实现

- `CommandRegistry` 现已把 `/compact`、`/new`、`/resume [session_id]` 接入 Application handler；`/compact` 没有 focus 参数，额外文本由 parser 返回 usage error。
- `/compact` 只通过 Application 的 `compact_session()` 生成 Projection candidate；失败原因以用户可见的受控文本返回，canonical History 不改写。缺少 summarizer 时明确返回 `summarizer_unavailable`，不伪造成功。
- `/new` 在 idle 边界释放旧 writer、创建新 Session、刷新 Context usage projection；`/resume <id>` 先释放当前 Session，再由 `ApplicationSessionService` 获取目标 Session 的 single-writer lock，恢复最后一个完整 History/Projection，并使用持久化的 activated directory scopes 加载当前文件系统中的 AGENTS 内容重建 Instruction State。
- Session resume 完成后返回新的 `SessionChanged` UI action；TUI 创建新的 in-memory `AgentRun`，不会恢复 Task、Plan、Pending Tool 或其他 Runtime checkpoint。
- Session catalog 由 Application 提供，按精确 `project_key` 过滤，沿用 Integration 的 durable `last_used_at DESC` 排序；每行包含 first User Message 的单行 bounded preview、last-used 时间和恢复错误可见的 corrupt 占位。
- TUI 增加独立 `SessionPickerState`：固定 10 条/页，↑/↓ 选择，←/→ 翻页，Enter 恢复，Esc 仅关闭 Picker。它不访问 Session store、Provider、Instruction Loader 或 Context Compiler。
- `ApplicationStatus` 增加 `ContextUsage`、Projection revision、Instruction epoch、compact count 及 prefix/tool-schema diagnostics；`/status` 显示线性 usage bar、`used/258K`、Operating Budget 说明和 unavailable 状态。
- TUI 输入区 ring 与 `/status` 均读取 Application 当前 usage projection；分母固定为 `258K`，不可用显示 `unavailable/258K`，窄终端保留 ring 与 permission 状态且不改变输入 buffer 语义。Headless Application 不导入 TUI。

## 3. 关键文件

- `src/uthcode/application/commands/builtins.py`
- `src/uthcode/application/commands/models.py`
- `src/uthcode/application/sessions.py`
- `src/uthcode/application/generation.py`
- `src/uthcode/interfaces/tui/app.py`
- `src/uthcode/interfaces/tui/picker.py`
- `src/uthcode/interfaces/tui/rendering.py`
- `tests/test_w04_session_commands.py`
- 更新旧命令测试，使 `/compact`、`/new`、`/resume` 的 implemented 状态与当前行为一致。

## 4. 验证记录

最终复验命令与结果：

- `conda run --no-capture-output -n re-uthcode python -m pytest -q`：**1181 passed, 3 skipped**，101.86s。
- `conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_w04_session_commands.py`：**9 passed**，7.41s。
- `conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_architecture_boundaries.py`：**23 passed**。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests`：退出码 **0**。
- `conda run --no-capture-output -n re-uthcode python C:\Users\93445\.codex\skills\uth-utf8-guard\scripts\check_utf8_docs.py docs/work/T09-Prompt与ContextEngineering/T09-Prompt与ContextEngineering-checklist.md docs/work/T09-Prompt与ContextEngineering/feedback/W04-session-commands-tui-feedback.md`：**2 file(s) passed UTF-8 guard**。

上述定向复验覆盖命令路由、`/compact -- focus`、Session History/Projection/Instruction State 恢复、new/resume writer 切换、busy/corrupt/unknown、21 条 Picker 分页、固定 ring 阈值、TUI Enter/Esc 和架构依赖边界；全量 pytest 也覆盖 Headless 与既有 TUI 回归。

## 5. 工作包边界与偏差

- `docs/rules/WorkPackageRules.md` 要求首次 Worker Prompt 后冻结 Tasks/Prompt/Spec/Checklist 的正文、结构与顺序；因此 W04 Prompt 中“同步 Tasks/Checklist”与冻结规则存在冲突。本轮不修改 `T09-Prompt与ContextEngineering-tasks.md`，只在 Checklist 中把已有的 `[ ]` 验收框勾为 `[x]`，并在此记录该边界。
- 没有修改已冻结的 W04 Prompt、T09 Spec、T09 Tasks 正文，也没有归档工作包。
- T09 包级 Context/README 文档维护不在当前 W04 的最小实现范围；包级验收时再按 Task 12 维护映射同步。
- 没有执行 Git commit、push、merge、rebase、tag 或 release。

## 6. 未完成项与安全边界

- 默认 ContextCompactor 没有可用 summarizer 时，`/compact` 会 fail closed 并显示失败；需要由后续已授权的 Provider-independent summarizer 组合入口提供成功候选，不能用普通 Agent Tool/AskUser/Plan 流程冒充。
- T09 仍不发现真实 Context Window，不按模型动态改变 denominator；在 T09-1 完成前，不保证真实输入窗口小于 258K 的模型能安全运行到长上下文规模。
- 跨进程恢复只承诺 durable History/Projection 与 Instruction State；Runtime、Task、Plan、Pending Tool 和交互 checkpoint 明确不恢复。

## 7. Checklist

- [x] Task 8 命令路由、`/compact`、`/new`、`/resume`、`/clear` Session 边界与定向测试。
- [x] Task 8 同 project key、durable last-used、10 条/页、首 User preview、21 条分页和键盘语义。
- [x] Task 8 busy/corrupt/unknown、History/Projection/Instruction State 恢复与新 Turn 边界。
- [x] Task 8 `/status` 与 TUI ring 共享 Application usage、固定 `used/258K`、unavailable、窄终端和 Headless。

## 8. Cleanup

未发现因本轮实现产生且应删除的临时、缓存或构建产物；只保留源代码、测试和本 Feedback。

## 第一轮定点返工

### 1. restored History 已进入正式 Provider request

- `ApplicationContextService.compose_generation_request()` 现在显式接收恢复后的 `canonical_history`，并由正式 `UthCodeApplication._start_agent_turn()` 在每次准备 request 时传入当前 active Session 的 `history`。
- Context Compiler 的输入组合顺序为：`Canonical History/base history` → `Projection`（若存在，过滤已覆盖范围）→ raw history tail → same-process Run/Turn delta → 当前 user。实际 `ContextSnapshot` 仍由 Core Compiler 决定最终选择和顺序，current user 保持 Conversation Plane 尾部。
- Projection 覆盖的 unit 不会再次作为 raw unit 发送；历史与本进程 delta 只按有序、相邻的语义身份重叠做局部协调，忽略 sequence/timestamp 和适配器附加的完整 `message` 字段，不做消息内容全局去重。
- `ToolCallPart`/`ToolResultPart` 通过既有 `history_entries_from_message()` 和 `messages_from_context_snapshot()` 保持原生角色、part 和 `tool_call_id`，没有文本化、拆断或把恢复 History 提升为 system/instruction authority。
- 新增 Headless 正式调用链测试：无 Projection 恢复 History、Projection + raw tail、原生 Tool pair，以及同一 Run 两轮 continuation；覆盖 `create_application → resume_session_for_command → create_run → start_turn → Provider request`。

### 2. Session 切换改为 staged transaction

- `ApplicationSessionService` 先通过 `_stage_resume_session()` 获取目标 writer lock，读取/修复目标 durable snapshot，并在独立的 `InstructionLoader.fork_for_session()` 上按当前文件系统重建目标 Instruction State；只有这些步骤全部成功后才进入 `_commit_staged()`。
- 提交阶段才同步并释放旧 Session writer，把已经验证的 loader state 原子采纳到当前 loader，再让目标成为唯一 `active_session`。staged writer 在失败路径通过 writer-only close 释放，不会用当前 loader 状态覆盖目标，也不会泄漏 lock 或产生额外 sequence。
- `busy`、`unknown`、`corrupt`、storage failure 发生在 staging 阶段时，当前 Session、当前 writer、当前 History/Projection 和当前 Instruction State 保持不变；错误后仍可从当前 Session 发起新 Turn。目标 Instruction State 只在提交时成为当前有效状态，目标 AGENTS 按当前文件系统读取。
- `/new` 也改为先创建并锁定 staged target，再提交切换；创建失败不会先清空当前 active Session。相同 active Session 的 `/resume` 在现有 writer lock 下重建候选 Instruction State，避免为重新获取同一把锁而制造空窗；重建失败同样不改变当前 loader。

### 3. `/status` 阶段限制

`/status` 现在同时显示固定 `used/258K Operating Budget`、`not a remote physical window`，以及：

```text
stage limitation: before T09-1, a real model window <258K is not guaranteed safe at 258K long-context scale
```

没有引入动态模型窗口发现、`ResolvedModelLimits`、模型名猜测或新的 ring denominator。

### 4. 本轮测试与验证

- `conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_w04_session_commands.py`：**16 passed**。
- `tests/test_context_compaction.py`：**24 passed**；`tests/test_context_compiler.py`：**21 passed**；`tests/test_session_files.py`：**11 passed**。
- `tests/test_command_dispatcher.py tests/test_command_completion.py`：**29 passed**；`tests/test_architecture_boundaries.py`：**23 passed**。
- `tests/test_application.py`：**12 passed**；`tests/test_application_runs.py`：**44 passed**；`tests/test_application_runtime.py`：**15 passed**。
- `tests/test_tui.py`：**69 passed, 3 failed**。3 个失败均为既有 `RichTerminalRenderer` ANSI 前景/背景色断言；本轮没有修改该渲染实现，W04 Session/Context/status 专项测试通过，因此不在本轮定点范围内修复。
- 全量 `conda run --no-capture-output -n re-uthcode python -m pytest -q`：**1185 passed, 3 failed, 3 skipped**；失败即上述 3 个既有 TUI ANSI 颜色断言。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests eval`：退出码 **0**。
- `conda run --no-capture-output -n re-uthcode python -m pip check`：**No broken requirements found**。
- `git diff --check`：退出码 **0**；仅报告仓库既有的 LF→CRLF 工作树提示，没有 whitespace error。
- `check_utf8_docs.py` 检查 Checklist 与本 Feedback：**2 file(s) passed UTF-8 guard**。
- 本轮未执行任何 Git commit、push、PR、merge、rebase、tag、release 或 archive；保留用户及 W01～W04 既有工作树改动。

### 5. 未实施范围

本轮没有实施 Task 9～12、T09-1、动态 Model Limits、Memory、Eval、Runtime/Task/Plan/Pending Tool 跨进程 checkpoint，也没有回退 W04 已正确实现的命令、Picker、Instruction State、固定 258K ring 或 Headless 边界。

## 第二轮定点返工

### 1. 提交阶段同步失败保持当前 Session

- `ApplicationSession.close()` 现在拆分为 `_prepare_close()` 与 `_release_after_sync()`：先同步当前 Instruction State，只有同步成功后才标记 closed、释放 writer 并清空 active 引用。
- `_commit_staged()` 在释放旧 writer 前执行可失败的 close preparation；旧 Session 同步失败时 staged target 会关闭，但旧 Session 对象、`active_session`、writer lock、History/Projection 和 Instruction State 均保持不变。
- 成功同步后才采纳 target loader，并在已同步旧状态的前提下释放旧 writer，避免用 target Instruction State 二次同步旧 Session。
- 新增 `test_commit_sync_failure_keeps_current_session_open_and_locked`，注入旧 Session sync failure，验证 `active_session` 未清空、当前对象未 closed、当前 writer 仍 busy、target staged writer 已释放。

### 2. 相同文本的独立 Turn 不再被去重

- 移除按 `kind`、payload、`commit_boundary` 和任意 History 位置寻找 overlap 的内容比较逻辑。
- request composition 现在明确把恢复的 durable Canonical History 作为 base，把当前进程 Run/Turn messages 转换为 process delta；delta entries 全量按新 sequence 追加，即使 payload 文本相同也保留独立语义事实。
- Projection 仍只过滤 durable base 已覆盖的 sequence range；process delta 位于其后，不会被错误识别为已覆盖的 durable record。ToolCall/ToolResult 仍使用原生 History entry，不文本化。
- 新增 `test_same_text_process_turn_is_not_deduplicated_against_durable_history`，验证 durable user `repeat`、process user `repeat`、current user `repeat` 三条独立 User 事实全部进入 request，并保留当前 user 尾部。

### 3. 第二轮验证结果

- `conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_w04_session_commands.py tests/test_context_compaction.py tests/test_context_compiler.py tests/test_session_files.py`：**75 passed**；其中 W04 定向测试现为 **19 passed**。
- `tests/test_application_runs.py`：**44 passed**；`tests/test_application_runtime.py`：**15 passed**；命令与架构测试：**52 passed**。
- 全量 `conda run --no-capture-output -n re-uthcode python -m pytest -q`：**1188 passed, 3 failed, 3 skipped**。默认 `NO_COLOR=1, TERM=dumb` 下 3 个失败仍为既有 TUI ANSI 颜色断言；启用 ANSI 色彩环境后的 TUI 复验为 **72 passed**，颜色失败确认为环境差异。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests eval`：退出码 **0**。
- `conda run --no-capture-output -n re-uthcode python -m pip check`：**No broken requirements found**。
- `git diff --check`：退出码 **0**；仅有既有 LF→CRLF 工作树提示。
- 本轮未执行任何 Git commit、push、PR、merge、rebase、tag、release 或 archive。

### 4. 未实施范围

本轮仍未实施 Task 9～12、T09-1、动态 Model Limits、Memory、Eval、Runtime/Task/Plan/Pending Tool 跨进程 checkpoint，也未修改冻结的 Prompt、Spec、Tasks、Checklist 或无关 TUI 渲染实现。
