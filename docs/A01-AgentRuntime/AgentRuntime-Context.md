# A01 Agent Runtime（执行层）

```text
layer: A01-AgentRuntime
context_file: docs/A01-AgentRuntime/AgentRuntime-Context.md
owns: Provider + SystemPrompt + Tool + ReAct AgentLoop
current_shape: provider-independent single-agent sequential runtime
does_not_own: permission strategy, persistence, UI, multi-agent scheduling
```

## 当前结论

- `[FACT]` `core/agent.py` 实现显式、集中、顺序可读的 ReAct Agent Loop；没有图节点、边、Reducer 或 Runtime DSL。
- `[FACT]` Core 只消费 UthCode 自有 Provider、Message、Tool、Event、Permission 数据；第三方 SDK 类型止于 `integrations/providers/`。
- `[FACT]` 默认工具为 `ReadFile`、`WriteFile`、`EditFile`、`Glob`、`Grep`、`Bash`。
- `[FACT]` `AskUserQuestion` 是 Core 特殊工具协议：随 Turn 暴露给 Provider，但不进入普通 `ToolRegistry` 执行路径。
- `[FACT]` `RuntimeHookSet` 为 Agent Loop 提供固定的 `before_tool_execution` 与 `before_completion` 两个生命周期点：前者执行 PLAN 只读策略，后者执行 Plan Review 与 unfinished-task completion block。
- `[FACT]` `BehaviorMode`、`PlanState`、`TaskState` 和同一 Turn 的 Steering 都属于当前 Core execution 事实；`TodoWrite` 是 Core 特殊控制工具，不是第二个 Tool Runtime。
- `[FACT]` 普通 Tool Batch 严格 FIFO；当前批次不会并行执行工具。
- `[FACT]` Agent Loop 是 `RunState` 的唯一写入者；Provider、Tool、Permission、Application、Interface 返回结果/事件/控制响应，不直接改写 Core 状态。

## 权威源码索引

| 主题 | 文件 | 关键符号/检索词 |
| --- | --- | --- |
| Provider 无关协议 | `src/uthcode/core/provider.py` | `ProviderPort`, `GenerationRequest`, `ProviderResponse`, `ProviderEvent`, `Message`, `ToolCallPart`, `ToolResultPart`, `Usage`, `CancellationToken`, `validated_provider_stream` |
| System Prompt | `src/uthcode/core/prompt.py` | `SystemPromptContext`, `build_system_prompt` |
| Tool 抽象与执行 | `src/uthcode/core/tool.py` | `Tool`, `ToolRegistry`, `ToolExecutor`, `PreparedToolCall`, `ToolPreparation`, `ToolExecutionResult` |
| ReAct Runtime | `src/uthcode/core/agent.py` | `AgentLoop`, `AgentTurnExecution`, `AgentExecutionSegment`, `AgentLoopConfig` |
| Application Tool 门面 | `src/uthcode/application/tools.py` | `ApplicationToolService`, `_SecretRedactor`, `describe_tool_call`, `_create_agent_loop` |
| Turn 依赖快照与 Prompt 注入 | `src/uthcode/application/generation.py` | `_start_agent_turn`, `_prepare_request` |
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
        -> Application 注入 system_prompt、固定 model/provider、固定 ToolDefinition 顺序
     -> validated_provider_stream
        -> reasoning/text delta 转 AgentEvent
        -> 验证唯一终态与完整 ProviderResponse
     -> candidate final:
        -> usage accounting
        -> before_completion Hook
           -> PLAN: PlanProposed -> PLAN_REVIEW_REQUIRED
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
```

## 不属于当前执行层

- `[ABSENT]` 并行 Tool Batch、DAG、通用工作流引擎。
- `[ABSENT]` LangGraph/LangChain Runtime 或旧 Runtime 兼容入口。
- `[ABSENT]` 动态 Hook registry、第三方 Hook plugin 生命周期、Skill、MCP、Subagent/Multi-Agent；不要从工作包名称推断这些能力已实现。
- `[DEFER]` 完整 Context Compiler、Context Budget、压缩和持久 Memory；当前 Provider 请求直接使用 Run 内消息历史。

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
