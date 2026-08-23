# A03 State（状态层）

```text
layer: A03-State
context_file: docs/context/A03-State/State-Context.md
owns: current in-memory Run/Turn facts + conversation + events + safe projections
current_shape: immutable Core state with Application-owned lifecycle
explicit_absence: persistent runtime checkpoint + memory/retrieval
```

## 当前结论

- `[FACT]` `RunState` 是单个 Run 当前 Turn 的权威、不可变 Core 状态。
- `[FACT]` 同一 `AgentRun` 的连续 Turn 保留 `messages`；不同 `AgentRun` 完全隔离。
- `[FACT]` `RunSnapshot` 是不含 conversation content 的安全投影；`TurnResult` 是稳定终态投影。
- `[FACT]` `AgentEvent` 是 Interface/Application 的增量观察协议，不是第二份状态仓库。
- `[FACT]` `RunState`、`RunSnapshot`、`TurnResult`、Event、交互协议有 JSON round-trip；这只说明可序列化，不表示 Runtime checkpoint 已持久化。
- `[FACT]` Application 在首次 Provider call 前、完整 Tool batch 后/下一次 call 前和 terminal Turn 边界把新增 Message 转换为 Transcript，通过 active Session 的单 writer 提交，并同步最小 Instruction State；`HistoryAppendOutcome` 分开表达 JSONL append+fsync、reload、last-used/metadata touch 与 durability，`HistoryPersistenceOutcome` 再表达 Instruction State sync、failure stage 和 durable message cursor。可判定 durable 的半成功不会把已落盘消息再次作为 process delta；append 后异常先按结构化 identity reconciliation 判定，仍未知则 active Session writer quarantine，所有新 Run、Transcript、Timeline、Context 与 Tool Result 语义写入 fail closed。只有显式 close 后 fresh writer 重新打开并验证/恢复，quarantine 才解除。真正未落盘的 pending batch 保留原始 Session/Turn identity，恢复时按 FIFO 提交，不改写原 Turn 边界。
- `[FACT]` `ApplicationContextService` 从 Prompt/AGENTS/Transcript/Timeline/Application runtime facts/Tool Schema 组成动态 Context Snapshot；configured/provider/effective limits、Pressure/Preflight Count、Auto/Hard Gate 与每次 request 的最终 accounting 一起记录安全诊断。Instruction scope/content 变化才创建新的 instruction epoch。
- `[FACT]` L4/L5、manual `/compact` 和 ordinary overflow recovery 复用同一 Application Context orchestrator；Compact request tool-free、bounded、使用冻结或当前模型，并在 commit 前通过 Hard Gate。成功 transaction 先写 Fine/Macro，最后写 `ActiveCheckpoint`；失败、取消、无 safe epoch 和 unknown durability 不产生伪提交。
- `[FACT]` 当前 `RunState` 已持有 `BehaviorMode`、可选 `PlanState`、replace-all `TaskState` 和 one-shot `RuntimeFeedback`；新 Turn 保留 conversation 并重置这些当前 Turn 控制事实。
- `[FACT]` Plan revision/approval、TodoWrite、CompletionBlocked 与同一 Turn Steering 均通过 Core 状态和事件协议闭合；Steering 追加一条真实 user message，不创建第二个 Turn。
- `[BOUNDARY]` Session v3 持久化 metadata（schema 3）、Transcript、Timeline、Tool Result ref、writer lock 和 Instruction State；record envelope 仍为 schema 2。v1/v2 明确 incompatible，不迁移、不双读；不提供跨进程 Runtime checkpoint、持久 Memory 或 retrieval。

## 权威源码索引

| 状态 | 文件 | 关键符号/检索词 |
| --- | --- | --- |
| 对话与执行状态 | `src/uthcode/core/agent.py` | `RunState`, `RunStatus`, `RunSnapshot`, `TurnResult`, `_TurnContinuation`, `AgentExecutionSegment` |
| Provider 消息内容 | `src/uthcode/core/provider.py` | `Message`, `TextPart`, `ReasoningPart`, `ToolCallPart`, `ToolResultPart`, `Usage` |
| 公开事件 | `src/uthcode/core/agent_events.py` | `AgentEvent`, `agent_event_from_dict`, `agent_event_from_json` |
| 暂停事实 | `src/uthcode/core/interaction.py` | `PauseRequest`, typed `PauseResponse` |
| Run 生命周期 | `src/uthcode/application/runs.py` | `AgentRun._state`, `_active_turn`, `_TurnDriver`, `TurnHandle` |
| Application 环境快照 | `src/uthcode/application/runtime_context.py` | `ApplicationRuntimeContext` |
| 配置模型 | `src/uthcode/application/configuration.py` | `EffectiveConfig`, `ProviderProfile`, `ModelProfile`, `ConfigSource` |
| TUI 投影状态 | `src/uthcode/interfaces/tui/` | `rendering.py`, `interaction.py`, `state.py` |

## 状态所有权矩阵

| 事实 | 唯一权威所有者 | 生命周期 | 对外暴露 |
| --- | --- | --- | --- |
| `workdir/platform/date` | `ApplicationRuntimeContext` | Application | 只读属性 |
| 当前 Provider/model ref | `UthCodeApplication` | Application；切换影响下一 Turn | `status`, configured model profiles |
| Permission RuleSet | `PermissionEvaluator` | AgentRun 创建时快照 | 只暴露决策，不暴露可变规则 |
| permission mode | `AgentRun` + `UthCodeApplication` | 当前 Run；安全默认值为用户配置偏好 | Run-local `set_permission_mode`；Application 默认仅允许 `default|auto` |
| SessionGrant | `AgentRun` | 当前进程、当前 Run | 不可变 tuple 视图 |
| conversation messages | `RunState` | 当前 Run，跨 Turn 保留 | 不通过 `RunSnapshot` 暴露 |
| committed Transcript | active `ApplicationSession` / `SessionWriter` | request preparation、complete tool batch 和 terminal tail 边界追加；resume 读取当前 Session | `ApplicationSession.transcript`、Context Compiler、HistoryRead |
| committed Timeline | active `ApplicationSession` / `SessionWriter` | L4/L5 合法 candidate 先写派生 record、最后写 checkpoint；物理记录 append-only，logical view 按最新有效 checkpoint 计算 | Context Compiler、Context diagnostics |
| Instruction State metadata | `InstructionLoader` + Session metadata | Session create/resume/terminal close 边界 | epoch/fingerprint/reason diagnostics |
| iteration/tool count/usage/status | `RunState` | 当前 Turn；新 Turn 重置 | `RunSnapshot`, `TurnResult` |
| behavior mode | `RunState` / `AgentRun` idle selection | 当前 Turn；批准 Plan 后切回 DEFAULT，下一 Turn 继承最终 mode | `BehaviorModeChanged`, `Run.behavior_mode` |
| PlanState / TaskState | `RunState` | 当前 Turn；Plan revision/approval 与 Todo replace-all | `PlanProposed`, `TaskStateChanged`, prompt facts |
| runtime feedback / Steering | `RunState` | 一次性反馈；Steering 为同一 Turn 的 user message | `UserSteeringRequested`, `UserSteeringApplied` |
| 暂停 continuation | `AgentTurnExecution._TurnContinuation` | 当前 Turn 的暂停边界 | 仅通过 `PauseRequest` 投影必要事实 |
| asyncio task/queue/waiter | `application.runs._TurnDriver` | 当前活动 Turn | 不进入 Core/JSON 状态 |
| UI 草稿/候选/渲染尾部 | Interface | 当前界面/当前 Turn | 非业务权威状态 |

## Run/Turn 状态结构

```text
RunState:
  run_id
  turn_id
  messages[]
  iteration_count
  tool_call_count
  consecutive_unknown_tools
  usage
  status = running | completed | failed | cancelled
  termination_reason
  behavior_mode
  task_state
  plan_state?
  runtime_feedback?

RunSnapshot:
  RunState - messages

TurnResult:
  run_id + turn_id + terminal status/reason + final_text? + usage + counts
```

## 状态转换

```text
AgentRun 创建
  -> RunState.initial(run_id, turn_id="initial")

start_turn(user_input)
  -> new_turn:
       保留旧 messages
       追加 user Message
       重置 iteration/tool/unknown/usage
       status=running, termination_reason=None
  -> active Turn 独占 Run

run_segment
  -> PAUSED boundary:
       RunStatus 仍为 running
       continuation 保存纯业务事实
       Application 持有 pending PauseRequest 与 waiter
  -> resume:
       校验 typed response
       从同一 continuation 继续
  -> TERMINAL boundary:
       status=completed|failed|cancelled
       termination_reason 必填
       TurnResult 固定且重复 await 返回同一结果
       AgentRun 提交 execution.state 并释放 active slot
```

## 事件序列事实

```text
turn_started
iteration_started
reasoning_started / reasoning_delta / reasoning_finished
assistant_message_delta / assistant_message_completed
usage_updated
tool_batch_started
tool_started / tool_finished
tool_batch_finished
turn_pausing? / user_input_requested? / turn_paused / turn_resumed?
turn_completed | turn_failed | turn_cancelled
```

- `events()` 只有一个消费者；`result()` 可重复等待并返回相同终态。
- Event 是内容安全投影：工具原始结果、写入正文、秘密值不得进入工具活动事件。
- `AssistantMessageCompleted.message` 是公开化后的消息；Provider 原生 item 不应泄漏到 Interface。
- TUI 对已提交终端内容只追加，不维护可替代 Core conversation 的 transcript 状态。
- `/clear` 清理视口投影，不替换 `AgentRun`，因此不清除 conversation。

## Context 当前含义

```text
implemented context:
  ApplicationRuntimeContext = workdir + platform + current_date
  Instruction Plane         = Prompt Asset + Core Contract + current AGENTS State
  Conversation Plane        = Timeline logical view + Transcript recent facts + current Run delta
  Tool System               = Application Tool definitions -> GenerationRequest.tools
  Context Budget            = configured/provider/effective limits + adaptive working profile
  Context Gates              = Pressure Estimate/Auto Gate + Preflight Safety Count/Hard Gate
  Compact                    = bounded L4/L5, manual no-op/success, one overflow retry
  Planning context          = BehaviorMode + PlanState + TaskState + RuntimeFeedback
  Turn snapshots            = provider/model/tool definitions/rules captured at defined boundaries

not implemented context:
  retrieval context
  persistent Memory
```

## 状态不变量

- running 状态不能有 termination reason；terminal 状态必须有 reason。
- completed 只能使用 `final_answer`；cancelled 只能使用 `user_cancelled`。
- completed `TurnResult` 必须有 `final_text`；failed/cancelled 不得有 `final_text`。
- `RunSnapshot` 不得新增 conversation、Tool result 或秘密正文。
- 同一 Run 同时最多一个 active Turn；终态必须释放 active slot。
- Pause 不是 `RunStatus`；不要新增第二套 paused state 与 Core continuation 竞争权威性。
- JSON 方法不等于 Runtime checkpoint；只有 Application Session lifecycle 明确调用时才执行 durable Transcript/Timeline append，不由 Core 或 Interface 隐式写盘。

## 修改路由

```text
Run/Turn 权威字段与终态 -> core/agent.py
消息/usage 序列化       -> core/provider.py
事件 schema             -> core/agent_events.py
暂停 schema             -> core/interaction.py
Run 生命周期/并发独占    -> application/runs.py
环境事实                -> application/runtime_context.py
配置事实                -> application/configuration.py + integrations/config/
Memory                    -> 当前不存在持久 Memory；出现需求时先定义存储边界
Todo/Plan/Steering        -> core/planning.py + core/agent.py + application/runs.py；不复用 UI 投影状态
```

## 最小验证索引

```powershell
conda activate re-uthcode
python -m pytest tests/test_application_runs.py tests/test_agent_events.py tests/test_agent_interaction.py -q
python -m pytest tests/test_application_runtime.py tests/test_configuration.py tests/test_config_loader_integration.py -q
```
