# W01 core-agent-runtime Feedback

## 实际完成

本次只执行 W01 的 Task 1 → Task 2，没有开始 Task 3–Task 9，也没有执行任何 Git 写操作。

正式 Core 调用链为：

```text
AgentLoop.start_turn()
→ AgentTurnExecution
→ request_preparer(messages, ordered_tool_definitions)
→ validated_provider_stream()
→ 合法 GenerationCompleted.response
→ assistant message / Usage 提交
→ ToolExecutor.execute_call() 逐个 FIFO
→ 一个 role=tool Message
→ 下一次 Provider 调用
```

`AgentLoop` 是唯一的自动 Loop。Core 不导入 Application、Integration 或 Interface；工具仍通过既有 `ToolRegistry`、`ToolExecutor` 和 `execute_call()` 执行，没有复制 Schema 校验或截断逻辑。

## Task 1：State、Snapshot、Result 与 Event

- `AgentLoopConfig` 固定默认限制 `50 / 16 / 3`，拒绝 bool、非整数、零值和负值。
- `RunState` 是 frozen、深度不可变的权威状态，包含 run/turn 标识、conversation、iteration、Tool 数、unknown streak、Usage、status 和 termination reason。`new_turn()` 只追加新的 user Message，并重置 Turn 级计数、Usage、状态和原因。
- `RunSnapshot` 只暴露标识、状态、计数、Usage 和终止原因，不包含 messages；`TurnResult` 只暴露终态标识、原因、final 文本和统计。两者均提供 JSON-safe 序列化与恢复入口。
- `AgentEvent` 及其具体事件均为 frozen、JSON-safe，并拒绝未知类型、缺失字段、额外字段、native item、ToolResult 正文和非 JSON-safe 值。
- 事件覆盖 Turn、iteration、reasoning 段、assistant 增量/完成、Usage、Tool batch、Tool 生命周期及唯一 terminal。reasoning 只在收到非空 Provider reasoning delta 时产生 `started → delta → finished`；普通文本不会被猜测为 reasoning。
- `ToolStarted` 与 `ToolFinished` 共享 run/turn、iteration、batch、ToolCall ID、Tool 名和安全 command；`ToolFinished` 不携带 ToolResult content。

## Task 2：Provider 权威边界与 Agent Loop

`core.provider.validated_provider_stream()` 是低层 Generation 与 Agent Loop 共用的校验边界：

- `GenerationCompleted` 在底层 iterator 正常 EOF 前保持 held；
- 缺 terminal、多个 terminal、terminal 后事件和未知事件均转为 `InvalidProviderResponseError`；
- 每条退出路径都会关闭底层 stream；
- partial Text/Reasoning/ToolCall delta 只形成显示事件，不进入权威 conversation；
- 只有合法 terminal response 才能提交 assistant message 与 Usage。

Anthropic、OpenAI Responses、OpenAI-compatible 三个 Adapter 的现有映射已经满足 W01 用例，本次没有修改 Adapter 或 Provider DTO。离线验证结果分别为 Anthropic `16 passed, 1 skipped`、OpenAI Responses `11 passed, 1 skipped`、OpenAI-compatible `11 passed, 1 skipped`；3 个 skip 均为未授权 live gate。

Loop 行为如下：

- 每次 Provider 调用前递增 iteration；Tool 执行不增加 iteration。
- assistant terminal 先写入权威 conversation，再按原始顺序逐个调用 `execute_call()`；所有结果按原序组成一个 `role=tool` Message。
- 普通 unknown、invalid arguments、Tool error 和截断结果继续交给下一次 Provider 请求；unknown streak 由 Registry 查询事实计算，已注册 Tool 立即归零。
- 单响应 ToolCall 超过 16 时整批不执行，并为每个 ID 写入受控错误结果；LENGTH/INCOMPLETE 携带 ToolCall 时同样整批不执行。
- max iterations、max tool calls、unknown streak、max output、Provider error 和协议错误均产生受控唯一失败终态。
- Provider 阶段取消丢弃 partial assistant 影响；Tool 阶段保留已完成结果，并为当前及剩余 ToolCall 补齐同 ID cancelled 结果，不再请求 Provider。
- Usage 只累计合法 terminal response，按 Turn 重置；每次累计后发送 `UsageUpdated`。
- 每个 Turn 恰有一个 `TurnCompleted`、`TurnFailed` 或 `TurnCancelled`；terminal 后不再发事件、改状态、执行 Tool 或调用 Provider。

## 修改文件

新增：

- `src/uthcode/core/agent.py`
- `src/uthcode/core/agent_events.py`
- `tests/test_agent_policy.py`
- `tests/test_agent_events.py`
- `tests/test_agent_loop.py`
- 本 Feedback 文件

修改：

- `src/uthcode/core/provider.py`：新增共享 Provider stream 校验。
- `src/uthcode/application/generation.py`：复用共享校验，保留原低层 Generation API。
- `src/uthcode/core/__init__.py`：导出真实 Core Agent/Event 类型和共享校验。
- `tests/test_provider_contract.py`：增加共享终态校验测试。
- `tests/test_package.py`：增加 Core Agent 导出测试。
- `docs/work/T05-ReAct与AgentLoop/T05-ReAct与AgentLoop-checklist.md`：只勾选 Task 1、Task 2 的现有复选框。

未修改：三个 Provider Adapter、Provider DTO、Tool DTO/Protocol、六个内置 Tool、配置、System Prompt 正文、Slash Command、Application Run、CLI 和 TUI。

## 验证结果

- Task 1 定向测试：`41 passed`。
- Task 2 Core/Provider/Tool 定向测试：`93 passed`。
- 三个 Provider Integration 离线测试：`38 passed, 3 skipped`。
- 全量测试：`383 passed, 3 skipped`。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests`：通过。
- `conda run --no-capture-output -n re-uthcode python -m pip check`：`No broken requirements found.`
- `git diff --check`：退出码 0。
- Checklist UTF-8 解码、常见乱码标记和 Markdown fence parity：通过。

## 范围差异、风险与清理

- 为使既有低层 Generation 复用共享终态校验，按 Prompt 要求窄改了 `application/generation.py`；没有保留第二份终态校验逻辑。
- 本机没有 Prompt 中提及的 MewCode 压缩包，因此没有从其源码迁移任何内容；旧 UthCode 只提取了策略和协议边界，没有复制 Graph/Runtime/API。
- Core Agent Loop 扫描未发现 Provider 名称分支、Application/Integration/Interface 反向依赖、`asyncio.gather`、TaskGroup、Graph、LangGraph/LangChain、旧项目 Runtime 或未来能力占位。
- 未引入兼容 alias、Facade、Shim、第二套自动 Loop、并行 Tool、Permission、Context、Session、Journal、Memory、Diff、Sandbox、Hook、Skill、MCP、Worktree 或 Subagent。
- W02 的 Application Run/Turn、W03 的 CLI/TUI 投影和 W04 的主流程接入/最终清理仍未实现，符合本 Worker 的执行边界；Task 3–Task 9 Checklist 保持未勾选。
- T05 工作包仍位于 `docs/work/`，未由 Agent 归档。

## W01-R1 返工

### 返工范围与根因

本轮只处理 W01 验收发现的两个 AgentEvent 契约问题，没有开始 Task 3–Task 9，也没有修改原始需求、Spec、Tasks、Prompt 或 Checklist 的文字、结构、编号和勾选状态。

1. `AssistantMessageCompleted` 的事件投影此前复制了 Provider terminal message 的全部 parts，而事件构造器也允许 `ToolCallPart`，因此 ToolCall arguments 会进入公开事件的 Message 序列化结果。
2. reasoning、assistant delta 和 completed 事件此前只有 run/turn/iteration 等上下文，没有稳定的事件级 `message_id`；原有严格恢复 schema 也没有该字段，无法完成同一 assistant message 的跨事件关联。

### 最终事件安全投影

- `AgentTurnExecution` 仍先把完整 `provider_response.message` 写入权威 `RunState`，然后才构造公开事件。
- `AssistantMessageCompleted` 的 Loop 投影现在只保留 `TextPart` 和 `ReasoningPart`；`ToolCallPart`、ToolCall arguments、`ToolResultPart`、ToolResult 正文和 `native_items` 均不进入公开 Message。
- `AgentEvent` 的 Message 构造器自身只接受 display-safe text parts，并拒绝 ToolCall、ToolResult 和 native items。调用方直接构造含 `ToolCallPart` 的 `AssistantMessageCompleted` 也会失败，不依赖 Loop 调用方主动过滤。
- Tool 调用仍只通过 `ToolBatchStarted`、`ToolStarted`、`ToolFinished`、`ToolBatchFinished` 暴露；`ToolStarted`/`ToolFinished` 继续使用 Core 收到的安全 command 摘要，不从 Interface 读取或重新解析原始 arguments。

### message_id 生成、生命周期与关联规则

- `TurnStarted.message_id` 为确定性的 `run_id:turn:turn_id:user`，标识该 Turn 的用户消息。
- 每次 Provider iteration 生成确定性的 `run_id:turn:turn_id:iteration:N:assistant`，并由该 iteration 的 `ReasoningStarted`、`ReasoningDelta`、`ReasoningFinished`、`AssistantMessageDelta` 和 `AssistantMessageCompleted` 共同使用。
- 同一 iteration 的多段 reasoning 继续以 `segment_index` 区分，但共享同一个 assistant `message_id`；不同 iteration、Turn 或 Run 的 ID 不相同。
- `message_id` 是非空字符串，进入 dict/JSON；恢复时缺少、类型错误或向不应携带该字段的事件额外添加 `message_id` 都由严格字段校验拒绝。Provider Message DTO 未修改。

### 回归证据

- 真实 AgentLoop 测试在 ToolCall arguments 中放入唯一标记 `W01-R1-UNIQUE-SECRET`。`RecordingTool` 实际收到完整原始参数；权威 state 中保留带该参数的完整 assistant `ToolCallPart`；下一次 Provider 请求同时保留同 ID 的 assistant ToolCall 和同 ID 的 ToolResult。
- 测试对执行产生的每个 AgentEvent 做 dict/JSON round-trip，并断言该秘密和 `arguments` 均不出现在任何事件的 dict/JSON 中。
- 测试断言 `AssistantMessageCompleted` 不含 ToolCallPart/ToolResultPart，且 ToolStarted/ToolFinished 的 batch_id、tool_call_id、name、command 完全一致。
- 真实 Loop 事件断言所有 run_id/turn_id 正确、TurnStarted 用户 message_id 稳定、同 iteration 的 reasoning/assistant 事件共享 ID、下一 iteration 使用不同 ID；另有真实 Turn/Run 隔离回归。

### 本轮修改文件

- `src/uthcode/core/agent.py`
- `src/uthcode/core/agent_events.py`
- `tests/test_agent_events.py`
- `tests/test_agent_loop.py`
- 本 Feedback 文件仅在末尾追加本节，旧记录未覆盖或重写。

### 本轮验证结果

- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_agent_policy.py tests/test_agent_events.py tests/test_package.py`：`44 passed`。
- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_provider_contract.py tests/test_agent_policy.py tests/test_agent_events.py tests/test_agent_loop.py tests/test_tool_core.py`：`97 passed`。
- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_anthropic_integration.py`：`16 passed, 1 skipped`。
- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_openai_responses_integration.py`：`11 passed, 1 skipped`。
- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_openai_compat_integration.py`：`11 passed, 1 skipped`。
- `conda run --no-capture-output -n re-uthcode pytest -q`：`387 passed, 3 skipped`；skip 均为未授权 live Provider gate，未发起网络或费用请求。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests`：退出码 `0`。
- `conda run --no-capture-output -n re-uthcode python -m pip check`：`No broken requirements found.`
- `git diff --check`：退出码 `0`；输出的 LF/CRLF 提示不是 whitespace error。
- 对当前全部 `14` 个尚未跟踪 W01 文本文件执行等价 trailing-whitespace/space-before-tab 检查：无错误。
- Core AgentLoop 扫描确认不存在 `asyncio.gather`、`TaskGroup`、Graph/Runtime、Provider 名称分支或 Application/Integration/Interface 反向依赖。

### 未完成项、风险与停止声明

- Task 3–Task 9 仍未执行；Application Run/Turn、CLI、TUI 和正式主流程接入不属于本轮范围。
- 未授权 live Provider 用例保持 skip；本轮没有真实 Provider 网络请求。
- 本轮没有修改 Provider DTO、Tool DTO/Protocol、Provider Adapter、默认 Tool、配置、System Prompt 或 Interface。
- 本轮未执行任何 Git 写操作（未 stage、commit、push、merge、rebase、tag 或清理工作树）。现在停止，等待独立验收；本 Feedback 不宣布 W01 已验收通过。

## W01-R2 message_id 碰撞返工

### 碰撞根因

W01-R1 中的 `_user_message_id()` 和 `_assistant_message_id()` 使用未转义的冒号拼接任意合法 `run_id`、`turn_id`。因此 `run_id="a", turn_id="b:turn:c"` 与 `run_id="a:turn:b", turn_id="c"` 会得到相同的 user 和 assistant message_id，造成不同 Run/Turn 的事件关联混淆。

### 新生成与复用规则

- 删除上述两个旧字符串拼接 helper，不保留旧格式、alias 或兼容入口。
- `AgentTurnExecution._execute()` 为 `TurnStarted` 生成一次 `uuid.uuid4().hex` user message_id，并在该事件构造中固定使用。
- 每个实际 Provider iteration 在请求准备完成后只生成一次 `uuid.uuid4().hex` assistant message_id，保存为 iteration 局部变量。
- 该局部变量同时传给同一 iteration 的 `ReasoningStarted`、`ReasoningDelta`、`ReasoningFinished`、`AssistantMessageDelta` 和 `AssistantMessageCompleted`；下一 iteration 重新生成新的 ID。
- message_id 不依赖 run_id/turn_id 的拼接格式，也没有收紧调用方 ID 输入或禁止冒号；Provider Message DTO 未修改。

### 回归与安全证据

- 真实 AgentLoop 回归使用 `run_id="a", turn_id="b:turn:c"` 与 `run_id="a:turn:b", turn_id="c"` 两组会碰撞的合法输入，并额外验证第三个 Run/Turn；各执行产生的 user message_id 和 assistant message_id 均不同。
- 真实 Loop 继续验证同一 iteration 的 reasoning/assistant 事件共享一个 ID、下一 iteration 使用不同 ID，并对执行产生的所有事件执行 dict/JSON round-trip。
- W01-R1 的唯一秘密 `W01-R1-UNIQUE-SECRET` 回归仍通过：完整 ToolCall arguments 保留在权威 conversation 并传入 ToolExecutor/下一次 Provider 请求，但秘密、`arguments`、ToolResult 和 native payload 不进入任何 AgentEvent；ToolStarted/ToolFinished 的 batch、tool_call、name、command 关联未退化。

### 本轮修改文件

- `src/uthcode/core/agent.py`
- `tests/test_agent_loop.py`
- 本 Feedback 文件仅在末尾追加本节；W01-R1 及更早记录未覆盖或改写。

### 本轮验证结果

- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_agent_policy.py tests/test_agent_events.py tests/test_package.py`：`44 passed`。
- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_provider_contract.py tests/test_agent_policy.py tests/test_agent_events.py tests/test_agent_loop.py tests/test_tool_core.py`：`97 passed`。
- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_anthropic_integration.py tests/test_openai_responses_integration.py tests/test_openai_compat_integration.py`：`38 passed, 3 skipped`；skip 均为未授权 live Provider gate。
- `conda run --no-capture-output -n re-uthcode pytest -q`：`387 passed, 3 skipped`；未发起网络或费用请求。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests`：退出码 `0`。
- `conda run --no-capture-output -n re-uthcode python -m pip check`：`No broken requirements found.`
- `git diff --check`：退出码 `0`；LF/CRLF 提示不是 whitespace error。
- 对全部 `14` 个尚未跟踪 W01 文本文件执行等价 whitespace 检查：无错误。
- 对全部 `9` 个尚未跟踪 W01 Markdown 文件执行 UTF-8、乱码标记和 Markdown fence parity 检查：通过。
- Core AgentLoop 扫描确认没有 Provider 名称分支、并行 Tool 原语、Graph/Runtime 或 Core 反向依赖。

### 停止声明

本轮只修复 message_id 碰撞，Task 3–Task 9 未开始；未执行任何 Git 写操作。现在停止，等待独立验收，不自行宣布 W01 已通过。
