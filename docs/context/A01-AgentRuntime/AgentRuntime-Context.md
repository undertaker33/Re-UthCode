# A01 Agent Runtime（执行层）

```text
layer: A01-AgentRuntime
context_file: docs/context/A01-AgentRuntime/AgentRuntime-Context.md
owns: Provider + SystemPrompt + Tool + ReAct AgentLoop
current_shape: provider-independent single-agent sequential runtime
does_not_own: permission strategy, persistence, UI, multi-agent scheduling
```

## 当前结论

- `[FACT]` `core/agent.py` 实现显式、集中、顺序可读的 ReAct Agent Loop；没有图节点、边、Reducer 或 Runtime DSL。
- `[FACT]` Core 只消费 UthCode 自有 Provider、Message、Tool、Event、Permission 数据；第三方 SDK 类型止于 `integrations/providers/`。
- `[FACT]` 默认工具为 `ReadFile`、`WriteFile`、`EditFile`、`Glob`、`Grep`、`Bash`。
- `[FACT]` `AskUserQuestion` 是 Core 特殊工具协议：随 Turn 暴露给 Provider，但不进入普通 `ToolRegistry` 执行路径。
- `[FACT]` `RuntimeHookSet` 为 Agent Loop 提供固定的 `before_tool_execution` 与 `before_completion` 两个生命周期点：前者执行 PLAN 只读策略，后者只执行 unfinished-task completion block；普通 PLAN final 正常完成。
- `[FACT]` `ProposePlan` 是仅在 PLAN 可见的 Core 控制 Tool；必须独占 Provider ToolCall batch，合法调用创建/替换 `PlanState` 并进入 typed Plan Review，混合 batch 整批受控拒绝。
- `[FACT]` `BehaviorMode`、`PlanState`、`TaskState` 和同一 Turn 的 Steering 都属于当前 Core execution 事实；`TodoWrite` 是 Core 特殊控制工具，不是第二个 Tool Runtime。
- `[FACT]` 普通 Tool Batch 严格 FIFO；当前批次不会并行执行工具。
- `[FACT]` Agent Loop 是 `RunState` 的唯一写入者；Provider、Tool、Permission、Application、Interface 返回结果/事件/控制响应，不直接改写 Core 状态。
- `[FACT]` Application 通过 `ApplicationContextService.compose_generation_request` 统一构造固定 258K Operating Budget 的 Instruction Plane、Conversation Plane 与 `GenerationRequest.tools`；Provider Integration 只负责原生协议映射。
- `[FACT]` 配置中的逻辑 Model Profile ID 仅供 Application/TUI/命令状态使用；Application 在 AgentRun 与 direct generation 两条路径都将快照的 `ModelProfile.remote_id` 写入 `GenerationRequest.model`，并按快照的 `reasoning_effort` 形成 `ReasoningOptions`。
- `[FACT]` 大 Tool Result 由 Application 按 inline/ref 策略物化；`ToolResultRead` 只通过当前 Session 的 opaque ref 读取有界页，不接受任意路径。
- `[FACT]` terminal History persistence 将 JSONL append+fsync、reload、last-used/metadata touch 与 Instruction State metadata sync 分开记录 outcome；只有可判定 `durability=durable` 的 History append 才按 `persisted_message_count` 推进 Run 的 process cursor。append 后的 reload/touch 失败会保留 durable 事实并显示 partial diagnostics；无法通过结构化 History identity reconciliation 判定时，active Session writer 进入 quarantine，所有新 Run 与语义写入 fail closed，不重试未知批次。必须显式关闭 writer，再由 fresh writer 重新打开并验证/恢复后才解除 quarantine。真正未落盘的 append 失败则 cursor 不推进；失败批次在进程内保留原始 Session/Turn identity 并按 FIFO 重试。
- `[FACT]` Bash effect 与 scope 分开判定；可静态解析且始终留在 workdir 内的 `cd`/`chdir`/`Set-Location` 只读组合可保持 `inside`，Windows `cd /d <literal>` 参与相同物理范围演算；普通、嵌套 CMD 括号组按 group depth 递归聚合内部连接符两侧的可见 effect，不等同不透明嵌套执行。越界或控制流/目标不确定时保守为 `outside/unknown`。

## 权威源码索引

| 主题 | 文件 | 关键符号/检索词 |
| --- | --- | --- |
| Provider 无关协议 | `src/uthcode/core/provider.py` | `ProviderPort`, `GenerationRequest`, `ProviderResponse`, `ProviderEvent`, `Message`, `ToolCallPart`, `ToolResultPart`, `Usage`, `CancellationToken`, `validated_provider_stream` |
| System Prompt | `src/uthcode/core/prompt.py` | `SystemPromptContext`, `build_system_prompt` |
| Tool 抽象与执行 | `src/uthcode/core/tool.py` | `Tool`, `ToolRegistry`, `ToolExecutor`, `PreparedToolCall`, `ToolPreparation`, `ToolExecutionResult` |
| ReAct Runtime | `src/uthcode/core/agent.py` | `AgentLoop`, `AgentTurnExecution`, `AgentExecutionSegment`, `AgentLoopConfig` |
| Application Tool 门面 | `src/uthcode/application/tools.py` | `ApplicationToolService`, `_SecretRedactor`, `describe_tool_call`, `_create_agent_loop` |
| Turn 依赖快照与 Prompt 注入 | `src/uthcode/application/generation.py` | `_start_agent_turn`, `_prepare_request` |
| Context/History 组合 | `src/uthcode/application/context.py`, `src/uthcode/application/history.py` | `compose_generation_request`, `history_entries_for_message` |
| Session 结果与 History 边界 | `src/uthcode/application/sessions.py`, `src/uthcode/integrations/session_files.py` | `ApplicationSession`, `SessionWriter`, `ToolResultRead` |
| Provider 适配 | `src/uthcode/integrations/providers/` | `anthropic.py`, `openai_responses.py`, `openai_compat.py`, `fake.py`, `factory.py` |
| Tool 适配 | `src/uthcode/integrations/tools/` | `factory.py`, `file_tools.py`, `search_tools.py`, `process_tools.py`, `workspace.py` |

## 单 Turn 执行算法

```text
AgentRun.start_turn(user_input)
  -> AgentLoop.start_turn(previous_state, user_input)
  -> RunState.new_turn: 保留历史 messages，追加 user message，重置本 Turn 计数
  -> AgentTurnExecution.run_segment
     -> TurnStarted（仅一次）
     -> IterationStarted
     -> request_preparer
        -> Application 编译 Context Snapshot，注入 system_prompt、Conversation 与固定 ToolDefinition 顺序
     -> validated_provider_stream
        -> reasoning/text delta 转 AgentEvent
        -> 验证唯一终态与完整 ProviderResponse
     -> candidate final:
        -> usage accounting
        -> before_completion Hook
           -> ordinary PLAN final: normal completion
           -> unfinished TaskState: completion block + one-shot feedback
           -> accepted completion: TurnCompleted
     -> 有 ToolCall: ToolBatchStarted
        -> 对每个 ToolCall 严格 FIFO:
           ToolStarted
           -> trusted preflight
           -> before_tool Hook
           -> Control 层 PermissionDecision
           -> execute 或受控错误 ToolResultPart
           -> ToolFinished
        -> 将全部原始 call_id 对应结果组成一个 role=tool Message
        -> ToolBatchFinished
        -> 下一 iteration
     -> terminal: TurnCompleted | TurnFailed | TurnCancelled
```

## 执行不变量

- `ProviderPort` 的具体 Provider 名称不得进入 Runtime 分支判断。
- Application 独占 `system_prompt` 与 `model` 注入；外部请求传入这两个字段会被拒绝。
- Provider/model、ToolDefinition 顺序、请求准备器在 Turn 启动时固定；Turn 中途切换模型只影响后续 Turn。
- Provider 流必须经过 `validated_provider_stream`；不完整、矛盾或缺终态的流不能提交 Assistant Message/Usage。
- 每个 Provider 给出的原始 `tool_call_id` 必须恰好得到一个 `ToolResultPart`；未知工具、参数错误、拒绝、异常、超限、取消也必须闭合 ID。
- Tool 先 `prepare_call`，再权限判断，再 `execute_prepared`；审批恢复不得二次 preflight 或二次执行。
- 单个 Tool 被拒绝或普通失败时，当前批次继续；错误作为 Tool Result 回给模型。
- 工具成功/错误正文进入模型消息，但公开 Tool 事件只携带脱敏、截断摘要。
- 默认限制：`max_iterations=50`、`max_tool_calls_per_iteration=16`、`max_consecutive_unknown_tools=3`。

## Provider 与 Tool 当前矩阵

```text
provider.kind:
  fake              -> integrations/providers/fake.py
  anthropic         -> integrations/providers/anthropic.py
  openai_responses  -> integrations/providers/openai_responses.py
  openai_compat     -> integrations/providers/openai_compat.py

tool:
  ReadFile  -> workspace 内文件读取
  WriteFile -> workspace 内文件写入
  EditFile  -> 基于已读取版本的精确替换
  Glob      -> workspace 内路径匹配
  Grep      -> workspace 内内容搜索
  Bash      -> workdir 下未沙箱化进程执行
  ToolResultRead -> 当前 Session opaque ref 的有界页读取
```

## 不属于当前执行层

- `[ABSENT]` 并行 Tool Batch、DAG、通用工作流引擎。
- `[ABSENT]` LangGraph/LangChain Runtime 或旧 Runtime 兼容入口。
- `[ABSENT]` 动态 Hook registry、第三方 Hook plugin 生命周期、Skill、MCP、Subagent/Multi-Agent；不要从工作包名称推断这些能力已实现。
- `[FACT]` Context Compiler、固定 258K Operating Budget、Projection 数据模型、Compactor 有界分批/校验机制与 Session History 已由 Application 接入正式 Agent path；Run 内未提交消息只作为当前进程增量编译。生产组合未提供 summarizer，因此 `/compact` 和 Provider overflow compaction 当前返回 `summarizer_unavailable`，不会生成新 Projection。
- `[BOUNDARY]` Session 只恢复已完整提交的 History、Projection、Tool Result ref 和最小 Instruction State；不恢复 Runtime checkpoint、Pending Tool、Permission、AskUser waiter 或 Provider 协程位置。
- `[DEFER]` 生产 tool-free summarizer、Memory、retrieval 与真实模型窗口解析仍不属于当前执行层。

## 修改路由

```text
Provider 通用数据/流语义 -> core/provider.py + tests/test_provider_contract.py
某 SDK 映射             -> integrations/providers/<provider>.py + 对应 integration test
Prompt 能力声明          -> core/prompt.py + tests/test_system_prompt.py
Tool 通用生命周期        -> core/tool.py + tests/test_tool_core.py
具体文件/搜索/进程工具   -> integrations/tools/ + tests/test_builtin_*_tools.py
ReAct/终态/批次语义      -> core/agent.py + tests/test_agent_loop.py
Application Tool 摘要    -> application/tools.py + tests/test_application_tools.py
```

## 最小验证索引

```powershell
conda activate re-uthcode
python -m pytest tests/test_provider_contract.py tests/test_tool_core.py tests/test_agent_loop.py tests/test_system_prompt.py -q
python -m pytest tests/test_architecture_boundaries.py -q
```
