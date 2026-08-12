# W03 Interface Activity Feedback

## 1. 执行范围

本轮由用户明确派发 `prompt/W03-interface-activity-prompt.md`，严格按 Task 5 → Task 6 执行；没有开始 Task 7–Task 9，没有执行任何 Git 写操作，也没有归档工作包。

开始前确认：当前 `HEAD=20fc83f7275d532465d7f88c78c3e3a7c8ba0fcf` 为 W01/W02 交付后的工作基线；W02 已记录 Headless E2E 通过。本轮再次执行 `tests/test_application_runs.py tests/test_cli.py tests/test_tui.py`，结果为 `47 passed`。

## 2. Task 5：CLI AgentEvent 投影

`uthcode exec` 现在通过 `application.create_run()` 创建独立 `AgentRun`，再用 `start_turn(prompt)` 创建一个 `TurnHandle`，只消费 Application 公开的 `AgentEvent`。CLI 没有导入 Core、Integration、ProviderEvent 或 Textual。

输出映射如下：

| AgentEvent | 输出 | 处理 |
| --- | --- | --- |
| `ReasoningDelta` | stderr | 立即输出 reasoning 文本 |
| `AssistantMessageCompleted(kind=progress/incomplete)` | stderr | 读取安全的 assistant message 文本 |
| `AssistantMessageCompleted(kind=final)` | 暂存 | 不提前写 stdout |
| `ToolStarted/ToolFinished` | stderr | 只输出 status、Tool name 和 Application command 摘要 |
| `TurnCompleted` | stdout | 只在此时输出 `final_text`，补齐必要换行 |
| `TurnFailed` | stderr，退出码 1 | 输出安全终止原因 |
| `TurnCancelled` | stderr，退出码 130 | 输出取消诊断 |

`AssistantMessageDelta` 只进入 CLI 内部缓冲，不会直接写 stdout；事件对象、ToolResult 正文、原始 Tool arguments、traceback 和秘密均不进入输出。stdin 中的 `/help` 仍按普通 Prompt 启动 Agent Turn，Textual 继续延迟导入。

## 3. Task 6：TUI 活动流与视觉层级

`UthCodeTUI` 生命周期内创建一个 `_run: AgentRun`，每次普通输入只创建一个活动 `TurnHandle`。下一 Turn 复用该 Run 的 Application conversation；`/clear` 只清理 Transcript Widget 和显示状态，未替换 Run。活动期间普通输入与 `/model` 继续被拒绝，终态后模型切换只影响下一 Turn。双 Esc 只调用活动 TurnHandle 的取消，退出时停止 timer、取消活动 Turn 并收口任务。

`AgentEventRenderer` 只读取 AgentEvent 的公开显示字段：

- `TurnStarted` 创建 `UserMessageBlock`；
- reasoning/assistant delta 按 `message_id + kind` 聚合，定时器按 0.2 秒刷新到一个可复用 `AgentTextBlock`；
- `AssistantMessageCompleted` 强制刷新已分类的正文；reasoning 与 final 使用同一正常正文层级；
- `ToolStarted/ToolFinished` 更新同一 `tool_call_id` 对应的 `ToolActivityRow`；行内容只有状态、Tool name 和 Application 提供的 command；
- `TurnCompleted/TurnFailed/TurnCancelled` 只更新终态和界面活动状态。

`UserMessageBlock` 使用完整宽度、非零 padding 和 `$panel` 背景。`AgentTextBlock` 使用 `$text` 且未设置 dim/italic；`ToolActivityRow` 使用 `$text-muted` 和 `$surface`。`tui.tcss` 没有硬编码 RGB 或新增主题系统。

ToolResult 没有对应的 AgentEvent 投影入口。TUI 不保存原始事件、ToolResult 或 ToolCall arguments；state 只保存显示 entries、message/tool ID 到 Widget 的映射、滚动状态和取消提示。测试使用独特 ToolResult sentinel 搜索渲染 Widget、Transcript state 和 Run snapshot，均未发现正文，也没有展开按钮。长 command 测试证明显示值来自 Application 已截断摘要。

## 4. 修改文件

本轮 W03 修改：

- `src/uthcode/interfaces/cli.py`
- `src/uthcode/interfaces/tui/app.py`
- `src/uthcode/interfaces/tui/rendering.py`
- `src/uthcode/interfaces/tui/state.py`
- `src/uthcode/interfaces/tui/widgets.py`
- `src/uthcode/interfaces/tui/tui.tcss`
- `tests/test_cli.py`
- `tests/test_tui.py`
- `docs/work/T05-ReAct与AgentLoop/T05-ReAct与AgentLoop-checklist.md`：只勾选 Task 5、Task 6 既有条目
- 本 Feedback 文件

旧的 ProviderEvent 流式投影 `StreamRenderer` 被 AgentEvent 专用的 `AgentEventRenderer` 替代，没有保留兼容别名或第二套自动 Loop。工作树中 W02 已有的 Application/Core/README/测试改动未被本轮回退或重写。

## 5. 验证结果

| 命令 | 结果 |
| --- | --- |
| `conda run --no-capture-output -n re-uthcode pytest -q tests/test_cli.py` | `17 passed` |
| `conda run --no-capture-output -n re-uthcode pytest -q tests/test_tui.py` | `18 passed` |
| `conda run --no-capture-output -n re-uthcode pytest -q tests/test_cli.py tests/test_tui.py tests/test_application_runs.py tests/test_application.py tests/test_application_runtime.py tests/test_architecture_boundaries.py tests/test_package.py` | `105 passed` |
| `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests` | 退出码 `0` |
| `conda run --no-capture-output -n re-uthcode python -m pip check` | `No broken requirements found.` |
| `git diff --check` | 通过；仅有既有 LF/CRLF 转换提示，无 whitespace error |
| Interface import scan | 未发现 `uthcode.core`、`uthcode.integrations`、`ProviderEvent` 或 `GenerationHandle` 普通输入依赖 |
| UTF-8 guard | Checklist 与 Feedback 均通过 |

## 6. Checklist 与边界

- Task 5：`7/7` 已勾选。
- Task 6：`13/13` 已勾选。
- Task 7–Task 9：未开始，保持未勾选。
- 未执行真实 Provider/live 测试、真实终端人工测试或网络请求；本轮证据来自 Fake/可控 Provider、Textual Pilot、离线测试和静态边界扫描。
- 未修改配置格式、Application Run/Core 语义、Permission、Session、Diff、主题系统或任何后置能力。
- 未执行 commit、push、merge、rebase、tag、分支写入或工作包归档。

## 7. UTF-8 guard

- files checked: `docs/work/T05-ReAct与AgentLoop/T05-ReAct与AgentLoop-checklist.md`、`docs/work/T05-ReAct与AgentLoop/feedback/W03-interface-activity-feedback.md`
- result: 写入后 UTF-8 解码、常见乱码标记和 Markdown fence parity 通过
- repaired encoding issues: 无

## W03-R1 返工记录

### 根因

1. `AssistantMessageCompleted.message` 是该 assistant message 的权威完整文本，但原 `AgentEventRenderer.flush()` 在发现完整文本与已渲染内容不一致时只生成了一段普通 `TextUpdate`；`UthCodeTUI._apply_batch()` 又无条件调用 `append_agent_text()`，因此已由 timer 刷新的 `partial-text` 会被错误追加为 `partial-textauthoritative-final`。原实现没有在 RenderBatch/TextUpdate 层表达“增量追加”和“权威替换”的不同语义。
2. 活动 Turn 测试使用固定 `delay=0.2` 和 `pause(0.03)` 推断业务状态。全量负载较高时，Provider 可能在第二条输入前已经完成，测试因此不再处于活动 Turn，导致 `/model` 被合法接受。

### 实际修改

- `TextUpdate.mode` 明确限定为 `append` 或 `replace`。普通 delta 和权威文本的自然延续只发 `append`；权威文本与已渲染内容完全一致不再发文本更新；权威文本不以已渲染内容开头时发完整权威文本并标记 `replace`。未刷新 pending delta 也会在 terminal 决策中一并正确处理。
- `UthCodeTUI._apply_batch()` 按 `TextUpdate.mode` 分派；`TranscriptWidget.replace_agent_text()` 只更新已有 `AgentTextBlock` 的内容和对应 state entry，不清空整个 Transcript，也不创建第二个 assistant Widget。Tool activity、reasoning、progress、incomplete、final 仍通过既有批量和视觉层级处理。
- `tests/test_tui.py` 新增真实 Application Run/Turn + Textual Pilot 的 terminal correction 回归：受控 Provider 先发 `TextDelta("partial-text")`，等待 `0.25` 秒确认 timer 已进入 Transcript，再发不同的权威 terminal 文本；断言最终 state/DOM 都只有 `authoritative-final`、assistant Widget 仍为 1 个，并断言 timer、活动 Turn、generation task 和 activity 状态均正常收口。
- 新增 renderer 的真实 Run/Turn 语义测试，覆盖 terminal 与 delta 一致、terminal 是自然延续、terminal 与已显示文本冲突三种情况；既有 reasoning batching、failed/cancelled 刷新及资源清理测试继续保留。
- 活动 Turn 测试新增仅存在于 tests 的 `_TurnGateProvider`，用 `asyncio.Event` 明确同步 Provider 进入阻塞点和释放点；用例按 gate 顺序验证第一 Turn 活动时拒绝普通输入和模型切换，释放后正常 terminal，再切换模型并确认下一 Turn 使用 `two/ref`。该用例用参数化在同一 pytest 进程执行 5 次，没有增加业务 delay、sleep、重试或放宽断言。

### 回归测试与精确结果

| 命令 | 结果 |
| --- | --- |
| `conda run --no-capture-output -n re-uthcode pytest -q tests/test_tui.py -k "agent_event_renderer or replaces_flushed_partial or active_turn_rejects"` | `10 passed, 16 deselected` |
| `conda run --no-capture-output -n re-uthcode pytest -q tests/test_cli.py` | `17 passed` |
| `conda run --no-capture-output -n re-uthcode pytest -q tests/test_tui.py` | `26 passed` |
| `conda run --no-capture-output -n re-uthcode pytest -q tests/test_cli.py tests/test_tui.py tests/test_application_runs.py tests/test_application.py tests/test_application_runtime.py tests/test_architecture_boundaries.py tests/test_package.py` | `113 passed` |
| `conda run --no-capture-output -n re-uthcode pytest -q` | `416 passed, 3 skipped` |
| `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests` | 退出码 `0` |
| `conda run --no-capture-output -n re-uthcode python -m pip check` | `No broken requirements found.` |
| `git diff --check` | 通过；只有既有 LF/CRLF 转换提示，没有 whitespace error |
| `rg -n "uthcode\.core|uthcode\.integrations|ProviderEvent|GenerationHandle" src/uthcode/interfaces` | `0` 条匹配 |

### 范围与剩余风险

- 本次 R1 实际修改文件仅为：`src/uthcode/interfaces/tui/rendering.py`、`src/uthcode/interfaces/tui/app.py`、`src/uthcode/interfaces/tui/widgets.py`、`tests/test_tui.py` 和本 Feedback 文件；没有修改 CLI，也没有触及 Application/Core/Provider/Tool DTO。
- Checklist 本轮未修改：写入代码前后 `git hash-object docs/work/T05-ReAct与AgentLoop/T05-ReAct与AgentLoop-checklist.md` 均为 `c19ad00cd8a4b63f39296444cbfc0cf8636d2510`。Task 7–Task 9 和 W04 未开始。
- 验证使用 Fake/受控 Provider、真实 Application Run/Turn 和 Textual Pilot；未执行真实 Provider、联网或人工终端测试，因此这些环境差异仍是已知边界。
- 全量结果中的 3 个 skipped 为现有测试的跳过项，本轮没有跳过、删除、放宽或延长任何回归断言。
- 本轮没有执行任何 Git 写操作：没有 `git add`、commit、push、checkout、switch、merge、rebase、tag 或创建分支。

## W03-R2 包级返工记录

包级独立验收发现 terminal 的公开 assistant Message 可同时包含 TextPart 与
ReasoningPart，而 CLI/TUI 原先按“存在 text 属性”提取所有 part，可能把
reasoning 再拼入 assistant/final 正文。

本轮让 CLI 与 TUI renderer 只投影 Application 公开的 `TextPart`；reasoning
仍只通过独立 ReasoningDelta 事件显示，不再重复进入 assistant block。没有
修改 Core 公开事件、Provider DTO 或 Run/Turn 语义。

回归测试使用真实 terminal Message 同时携带 ReasoningPart 与 TextPart：

- CLI stdout 只包含 final，stderr 只包含独立 reasoning。
- TUI reasoning entry 为 `think`，assistant entry 仅为 `answer`。
- CLI：`17 passed`；TUI：`26 passed`。
- 全量测试：`416 passed, 3 skipped`。
- 未修改 Checklist，未执行 Git 写操作。
