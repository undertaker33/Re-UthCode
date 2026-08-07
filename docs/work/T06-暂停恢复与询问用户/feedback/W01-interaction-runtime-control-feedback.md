# W01-interaction-runtime-control Feedback

## 返工轮次 1 — W01 正式返工

### 返工原因

旧 W01 未通过验收，且旧 Prompt 与旧 Feedback 已由用户删除。本轮按新的 `W01-interaction-runtime-control-prompt.md` 重新读取并实施 Task 1、Task 2、Task 3；没有回退全部既有改动，而是逐项复核了 Task 1 候选协议、事件、序列化和测试。

本轮没有修改需求原文、Spec、Tasks 或 Prompt，没有执行 Git 写操作，也没有修改 Provider DTO、普通 Tool 公共协议、第三方集成协议、Interface、配置或 System Prompt。

### Task 1：保留、修改和删除

保留并复核的成果：

- `core/interaction.py` 的 frozen dataclass、Enum、严格 JSON 解码、答案校验和 `AskUserQuestion` schema；
- `agent_events.py` 的 `TurnPausing`、`UserInputRequested`、`TurnPaused`、`TurnResumed` 及其严格序列化；
- Core 与 Application 的稳定交互类型导出；
- `tests/test_agent_interaction.py` 的合法往返、边界和非法输入证据。

本轮修改：

- 补齐并复核空 ID/空文本、错误基础类型、`bool` iteration、缺失/额外字段、非法 PauseKind/PauseReason/response 组合、嵌套 ID、答案边界、选择项数量和 schema `additionalProperties: false` 测试；
- `core/__init__.py` 增加执行分段结果的正式边界导出，但不导出内部 continuation 类型；
- Application 导出 Headless 所需的 PauseRequest、Question 和三类 typed response。

删除：

- Task 1 路径没有保留任何异步协调对象、持久化对象或旧兼容入口；
- 旧 Core waiter 不在 Task 1 协议或事件模型中复用。

### Task 2：Core 最终运行方式

`AgentTurnExecution` 已按 T05 Agent Loop 基线改为显式分段执行：

- `run_segment(pause_signal=..., response=...)` 每次运行到 paused 或 terminal boundary 后返回 `AgentExecutionSegment`；Core 不等待用户回答；
- 暂停返回后，Core 协程已经结束，Core execution 只保存业务状态、取消信号和显式 continuation facts，不保存等待回答的协程栈、Python frame 或后台驱动任务；
- 私有 `_TurnContinuation` 实际保存且仅保存以下八类事实：`stage`、`iteration`、`provider_retry_pending`、`assistant_tool_message`、`tool_calls`、`completed_tool_results`、`next_tool_index`、`pending_pause`；
- Provider 用户暂停取消当前 attempt signal，丢弃未权威提交的 partial conversation，并在同一 iteration 重试；网络/限流返回 provider retry boundary，不重复 `IterationStarted`、Usage 或 assistant message；
- 普通 Tool 不被 pause 强行打断，当前调用闭合后保存已完成结果和下一索引，FIFO 继续；
- AskUser answer 使用原始 ToolCall ID 生成 ToolResult；AskUser pending 时取消会闭合当前及剩余 ToolCall，并只产生一次 cancelled `ToolBatchFinished` 与一次 `TurnCancelled`；
- terminal 后再次 `run_segment()` 只返回空事件的 terminal result，不产生新事件。

已完全删除的旧 Core waiter/API 和测试设计：

- 删除 `_resume_future`、`_wait_for_pause`、Core `pending_pause` property、Core `pause()`、Core `resume()`；
- 删除 Core 的 event queue、producer task、result Future、completion listener、Core `events()`/`result()`/`start()` 运行机制；
- 删除 `tests/test_agent_loop.py` 中由同一个 Core execution 等待回答、读取 Core pending、直接唤醒 Core Future、由事件消费者恢复 Core 协程的旧测试；
- `tests/test_agent_loop.py` 已改为直接驱动执行分段，验证 paused boundary、continuation facts、同轮重试、Tool 安全边界、Ask FIFO、取消和 terminal-only result。

### Task 3：Application 私有协调

`application/runs.py` 新增私有 `_TurnDriver`，Application 独占：

- 连续调用 Core `run_segment()` 的私有驱动 task；
- 单事件流的 `asyncio.Queue`；
- terminal-only、可重复读取的 result Future；
- 当前 pause 的 response waiter、当前 segment signal、pending PauseRequest。

公共 `TurnHandle` 只提供 `pause()`、`pending_pause`、`paused`、typed `resume()`、`cancel()`、`events()`、`result()` 和 `cancelled()`。错误 pause/turn/tool ID、错误 response kind、过期回答和重复回答不会改变 pending；cancel 在 pause、resume、Provider 和 AskUser 竞争中优先，不产生 `TurnResumed`。

正常结束、取消、异常和恢复后的 terminal 都会清理 driver task、当前 signal、response waiter 和 pending；terminal result Future 保留为同一不可变结果的重复读取入口，事件队列通过唯一事件流消费 sentinel。Run active slot 在 terminal 事实成立后释放。

`AskUserQuestion` 只在 Application 自动 Agent path 中追加到六个普通 Tool definitions 之后；普通 Tool Registry 拒绝保留名，手动 `execute_tool_calls()` 拒绝控制 Tool，raw generation 不自动注入 AskUser。

### 实际修改文件

- `src/uthcode/core/interaction.py`
- `src/uthcode/core/agent_events.py`
- `src/uthcode/core/__init__.py`
- `src/uthcode/core/agent.py`
- `src/uthcode/application/runs.py`
- `src/uthcode/application/generation.py`
- `src/uthcode/application/tools.py`
- `src/uthcode/application/__init__.py`
- `tests/test_agent_interaction.py`
- `tests/test_agent_loop.py`
- `tests/test_application_runs.py`
- `tests/test_application_tools.py`
- `tests/test_package.py`
- `docs/work/T06-暂停恢复与询问用户/T06-暂停恢复与询问用户-checklist.md`：只修改 Task 1–3 现有 checkbox 状态；未改文字、结构、编号、顺序或 Task 4–8 状态。
- 本 Feedback 文件。

### 验证命令与精确结果

以下 Python 命令均通过 `conda run --no-capture-output -n re-uthcode` 执行：

```text
python -m pytest -q tests/test_agent_interaction.py tests/test_package.py
55 passed in 0.48s

python -m pytest -q tests/test_agent_loop.py tests/test_agent_interaction.py
74 passed in 0.43s

python -m pytest -q tests/test_agent_events.py tests/test_provider_contract.py tests/test_tool_core.py tests/test_package.py
56 passed in 0.49s

python -m pytest -q --ignore=tests/test_cli.py
465 passed, 3 skipped in 29.44s

python -m pytest -q tests/test_architecture_boundaries.py
21 passed in 3.46s

python -m compileall -q src tests
passed; no output

python -m pip check
No broken requirements found.

git diff --check
passed with only Git's LF/CRLF working-copy warnings; no whitespace error
```

补充的 Task 3 Application/Tool 定向命令为 `python -m pytest -q tests/test_application_runs.py tests/test_application_tools.py`，结果为 `28 passed in 4.15s`；新增的 resume/cancel race 单测也通过。

CLI 已知缺口单独验证：

```text
python -m pytest -q tests/test_cli.py
exit code 124; command timed out after 64047ms
```

该 CLI NetworkError/暂停收口属于 Task 4，未在本轮修改 CLI，也没有把排除 CLI 的 `465 passed, 3 skipped` 描述为项目全量通过。

### 负向扫描证据

- `src/uthcode/core/interaction.py` 的 token 扫描未发现 `Future`、`Event`、`Queue`、`Task`、`Lock`；
- Core continuation/waiter scan 通过：`agent.py` 不含 `_resume_future`、`_wait_for_pause`、Core `pending_pause`/`pause()`/`resume()` API、Core queue/task/result Future/waiter 字段；`AgentTurnExecution.__slots__` 没有 `_queue`、`_task`、`_result_future`、`_waiter`；
- `_TurnContinuation` runtime fields 与八项 continuation facts 完全一致；
- `src/uthcode/core/agent.py`、`interaction.py` 和 Task 3 Application 文件没有新增 recovery/session/storage/journal/checkpoint/replay；
- 单 Agent Loop 定义及 Application 构造路径扫描通过；
- Core Tool 并行执行扫描通过；
- AskUser 名称只出现在 Core 交互协议/Agent 控制分支和 Application 注入/隔离路径，不进入 `integrations` 或普通 Tool Registry。

### Task 1–3 Checklist 逐项证据

Task 1 的五项均已勾选：协议模型和严格 schema 由 `test_agent_interaction.py` 的 48 项测试与 package 测试覆盖；事件 round-trip 和 nested ID 由同一测试集覆盖；负向扫描通过。

Task 2 的六项均已勾选：`test_agent_loop.py` 的 26 项直接分段测试覆盖 terminal/paused boundary、Provider partial、同轮 retry、async request preparer pause、Tool safe boundary、AskUser、网络/限流、错误、取消、ID 错配、重复 terminal；Core slots/source negative scan 证明没有回答 waiter。

Task 3 的六项均已勾选：`test_application_runs.py` 覆盖 driver、pending 可见时机、单事件流、result、active slot、wrong/stale/duplicate response、pause/cancel、resume/cancel、network retry、Ask answer/cancel、terminal 清理；`test_application_tools.py` 覆盖保留名和手动 API 隔离；`test_package.py` 覆盖公共导出边界。

### 冻结工作包冲突、未完成项与用户决定

本轮没有遇到必须越界修改 Provider DTO、普通 Tool 公共协议、第三方集成协议或 Interface 行为的跨层冲突，因此没有阻塞 Task 1–3，也没有终止或重建本工作包。

与旧失败 W01 事实不同之处是：Core 不再保存或公开回答 waiter，Core 只返回执行分段和显式 continuation；暂停响应协调完全移动到 Application 私有 driver。旧 Prompt/Feedback 已删除，本 Feedback 不把旧 waiter 实现描述为可保留替代方案。

W01 Task 1–3 没有未完成项，也不需要用户决定。CLI NetworkError/暂停用例仍等待 Task 4，W02/W03 后续工作包未开始。本轮不开始 W02，不执行 commit、push、归档或其他 Git 写操作。

### UTF-8 guard

在 Feedback 和 Checklist 写入后执行：

```text
conda run --no-capture-output -n re-uthcode python C:\Users\93445\.codex\skills\uth-utf8-guard\scripts\check_utf8_docs.py docs/work/T06-暂停恢复与询问用户/feedback/W01-interaction-runtime-control-feedback.md docs/work/T06-暂停恢复与询问用户/T06-暂停恢复与询问用户-checklist.md
OK: 2 file(s) passed UTF-8 guard
```

## 返工轮次 2

### 复查问题与根因

本轮只处理复查指出的两个 W01 阻断问题，没有扩大到 W02、CLI/TUI、Provider DTO、普通 Tool 公共协议或 Git 操作。

1. 实时事件不可见的根因是 `_TurnDriver._drive()` 等待 `run_segment()` 返回后，才通过旧的 `_publish_segment()` 把整个 `segment.events` 批量放入 Application 队列。Provider 或 Tool 在 segment 内等待时，已经产生的 `TurnStarted`、`IterationStarted`、reasoning/text delta 和 Tool 事件因此不可见。
2. Driver 异常不闭合的根因是 `_drive()` 的 `Exception`/`CancelledError` 分支只清理局部引用后重新抛出，没有生成终态结果、结束事件流或调用 `AgentRun._complete_turn()`，导致 result Future、事件消费者和活动 Turn 槽位悬挂，并触发未处理 Task 异常。

### 实际修复方式

#### 实时事件发布

- `AgentTurnExecution.run_segment()` 增加临时 `event_sink` 调用参数。
- Core 使用只在当前 segment 调用期间存在的 `_SegmentEventBuffer`：事件先进入当前 segment 的本地事件列表，再立即调用 sink；segment 返回后只保留事件 tuple，sink 不进入 `_TurnContinuation`、`AgentTurnExecution.__slots__` 或任何跨 segment 状态。
- Application 传入 `_TurnDriver._emit_event`，不再等待 segment 返回后批量遍历 `segment.events`，因此每个事件只发布一次并保持原顺序。Core 直接调用仍可从 `segment.events` 读取同一批事件。
- `_emit_event()` 遇到 `TurnPaused` 时，先设置 `_pending_pause` 并创建 `_response_waiter`，再 `put_nowait()` 公开事件，保证用户看到暂停事件时对应 waiter 已经存在。
- `TurnHandle.resume()` 不提前清空 pending；由 Driver 在取得响应后清理，避免回答先于 paused boundary 处理时丢失 pending。跨多次 pause/resume 的同一单消费者事件流继续使用同一个 Application queue。
- partial Provider delta 只进入 AgentEvent 流。Core 仍只在 `GenerationCompleted` 后提交 assistant message 和 Usage，因此 partial 文本不会进入权威 conversation、Usage 或 continuation；retry 继续使用原 iteration，不重复 `IterationStarted` 或 `UsageUpdated`。

#### 异常确定性闭合

- Core 增加仅用于 Driver 失去 `run_segment()` 调用能力时的 terminal closure：意外异常形成 `RunStatus.FAILED`、`TerminationReason.INTERNAL_ERROR` 和唯一 `TurnFailed`；任务取消形成现有 `RunStatus.CANCELLED`/`TurnCancelled` 语义。
- `_TurnDriver._drive()` 不再把意外异常重新抛出。异常路径生成安全的 failed terminal，完成 result Future，调用 `_complete_turn()` 释放活动槽位，向 queue 放入唯一 `_END`，并吞掉内部异常/traceback，不将异常文本写入 AgentEvent 或 TurnResult。
- 正常、失败、取消和暂停恢复终态统一清理 `_response_waiter`、`_segment_signal`、pending、pause request 和 driver task。`_end_enqueued` 防止重复结束信号，`_result_value`/result Future 防止重复或覆盖 terminal result。
- 外部取消 Driver task 时先形成 Core cancellation terminal；不会留下 `Task exception was never retrieved`。既有 `TurnHandle.cancel()`、Provider cancel、AskUser cancel 和 pause/resume 路径保持原语义。

### 新增测试名称

- `test_application_stream_events_are_visible_before_segment_boundary_and_not_repeated`
- `test_application_pause_resume_keeps_one_live_event_consumer`
- `test_segment_event_sink_is_temporary_and_core_keeps_only_event_facts`
- `test_application_driver_unexpected_exception_closes_result_events_and_active_slot`
- `test_application_driver_task_cancellation_closes_turn_without_unhandled_exception`

先补失败测试并复现：

```text
conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_application_runs.py -k "stream_events_are_visible or pause_resume_keeps_one_live_event_consumer or driver_unexpected_exception"
3 failed, 22 deselected in 3.03s
```

修复后上述三项及新增 Driver task cancellation 测试结果为：

```text
4 passed, 22 deselected in 0.47s
```

Core sink 临时性测试单独结果为：

```text
1 passed, 26 deselected in 0.32s
```

### 本轮实际修改文件

- `src/uthcode/core/agent.py`
- `src/uthcode/application/runs.py`
- `tests/test_agent_loop.py`
- `tests/test_application_runs.py`
- 本 Feedback 文件末尾追加本章节。

本轮没有修改 Spec、Tasks、Prompt、Checklist、Interface、CLI、Provider DTO、普通 Tool 公共协议、第三方集成协议、配置或 System Prompt，也没有执行 commit、stage、push、restore 或其他 Git 写操作。

### 全部验证命令与精确结果

以下 Python 命令均使用 `conda run --no-capture-output -n re-uthcode`：

```text
python -m pytest -q tests/test_agent_interaction.py tests/test_agent_loop.py tests/test_application_runs.py tests/test_application_tools.py tests/test_package.py tests/test_architecture_boundaries.py
135 passed in 7.58s

python -m pytest -q --ignore=tests/test_cli.py
470 passed, 3 skipped in 22.00s

python -m compileall -q src tests
passed; no output

python -m pip check
No broken requirements found.

git diff --check
passed; only LF/CRLF working-copy warnings, no whitespace error
```

`tests/test_cli.py` 属于 W02 已知范围，本轮未修改或接入 CLI；`470 passed, 3 skipped` 明确是排除 CLI 的结果，不代表项目全量测试通过。

### Core 负向扫描

重新执行的扫描结果：

```text
$hits = rg -n '_resume_future|_wait_for_pause|^\s*(async\s+)?def\s+(pause|resume)\(|^\s*def\s+pending_pause' src/uthcode/core/agent.py src/uthcode/core/interaction.py
NONE: Core old waiter/API scan

$hits = rg -n '\basyncio\.(Queue|Future|Task|Event|Lock)\b|\b(Future|Event|Queue|Task|Lock)\b|response[ -]?waiter' src/uthcode/core/agent.py src/uthcode/core/interaction.py
NONE: Core async primitive/response waiter scan

AgentTurnExecution slot scan
persistent_sink_slot=False
forbidden_core_slots=[]

$hits = rg -ni 'recovery|session|storage|journal|checkpoint|replay' src/uthcode/core/agent.py src/uthcode/application/runs.py
NONE: no persistence/recovery additions in changed runtime files

$hits = rg -ni 'parallel|gather|create_task|taskgroup' src/uthcode/core/agent.py
NONE: no second/parallel Core runtime
```

`pending_pause` 仍只作为 `_TurnContinuation` 的显式业务事实存在；没有 `AgentTurnExecution.pending_pause` 公共属性，也没有 Core pause/resume 响应等待器。Application 的 queue/Future/Task/waiter 仍只位于 `_TurnDriver` 私有实现。

### 未完成项与风险

本轮两个复查阻断均已修复，W01 Task 1–3 没有新增未完成项。W02 的 CLI/TUI 工作和 `tests/test_cli.py` 仍未开始；这是工作包既定范围，不在本轮处理。除此之外没有发现需要用户决定的跨层冲突。

### UTF-8 guard

追加前先检查既有 Feedback，追加后执行：

```text
conda run --no-capture-output -n re-uthcode python C:\Users\93445\.codex\skills\uth-utf8-guard\scripts\check_utf8_docs.py docs/work/T06-暂停恢复与询问用户/feedback/W01-interaction-runtime-control-feedback.md
OK: 1 file(s) passed UTF-8 guard
```

未修复或重写既有编码内容；本轮追加内容通过 UTF-8 解码、乱码标记和 Markdown 围栏检查。
