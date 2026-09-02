# A04 Orchestration（编排层）

```text
layer: A04-Orchestration
context_file: docs/context/A04-Orchestration/Orchestration-Context.md
owns: entrypoint composition + application use cases + interface adaptation
current_shape: single-agent orchestration
explicit_absence: subagent + task decomposition + multi-agent scheduler
```

## 当前结论

- `[FACT]` 当前编排单位是 `UthCodeApplication -> AgentRun -> TurnHandle`，不是 Agent Team。
- `[FACT]` Application 是全部 Interface 的统一入口；TUI/CLI 不直接导入 Core、Integration 或 Provider SDK。
- `[FACT]` `create_application` 组合配置、Provider、默认 Tool、权限规则加载器和 Runtime Context。
- `[FACT]` 用户配置使用 `default_model`、Provider `api_key`、Model `remote_id`/`display_name`；`/model` 原子写回只修改用户级 `default_model`。逻辑 Model Profile ID 只用于界面和状态，GenerationRequest 使用快照的远端 `remote_id`。
- `[FACT]` Session 只在真实请求或显式 Session 命令需要时打开：`exec <prompt>` 与 TUI 首条普通输入调用 `ensure_session()`，`/new` 显式创建，`/resume` 直接锁定并恢复目标；TUI 启动、退出、help/status 和打开/关闭 Picker 不创建 Session。Session v3 只持久化 metadata（schema 3）、Transcript、Timeline、Tool Result、writer lock 与 Instruction State；metadata 还可保存 Session 自身的 `model_ref`。v1/v2 明确 incompatible。terminal Turn 的 History、Tool Result ref 与 Instruction State 由 Application 提交并在退出时释放 writer。History 的 JSONL append+fsync、reload、last-used/metadata touch 与 Instruction State sync 分阶段进入安全 diagnostics，Run cursor 只按可判定 durable 的消息推进；append 后异常先做结构化 identity reconciliation，无法判定时 active Session writer quarantine，新的 Run/语义写入均 fail closed，必须 close 后 fresh writer 验证/恢复才可继续；真正未落盘的 pending batch 才保留原始 Session/Turn identity 并在后续 terminal 边界按 FIFO 重试。
- `[FACT]` `ApplicationContextService` 是正式请求组合入口：Context Snapshot 的 Instruction Plane、Conversation Plane、default/configured/provider/effective budget provenance 和 `GenerationRequest.tools` 进入同一 Provider-independent DTO；effective input 为 `256_000` 时，该正式 resolver 使用 Eval 选定的 `balanced-208k` profile，其它窗口保留有界自适应派生并服从 configured/provider 收紧；Integration 不重新编译 Context。
- `[FACT]` `/compact` 已通过 Command/Application/Session 路径调用同一 Context orchestrator；低 pressure 也可手动执行，无完整候选或无 reduction value 时返回成功 no-op。L4/L5 与 overflow recovery 使用 tool-free、bounded、Hard-gated 的 Compact request；ordinary overflow 最多 forced reduction/rebuild/re-gate/retry 一次。
- `[FACT]` `create_application -> create_run -> start_turn` 组合用户级安全 Permission 默认值、固定 PLAN/unfinished 控制检查、`ProposePlan`/Task 控制、同一 Turn Steering 和唯一 Agent Loop/driver；没有可插拔 Hook 组合阶段。
- `[FACT]` `/permission default|auto` 先原子写回用户配置并更新 Application 默认值，再由结构化 action 更新当前 Run；`full_access` 不写配置、不改变新 Run 默认值，TUI picker 复用同一命令路径。
- `[FACT]` TUI 启动一个长生命周期 `AgentRun` 以保留多轮消息，但直到真实普通输入或显式 Session 命令才创建持久 Session；`uthcode exec` 每次创建一个 Run 和一个 Turn，并在真实 prompt 前惰性 ensure。
- `[FACT]` Windows Desktop 通过 `desktop/src/main.ts`、`desktop/src/preload.ts`、`desktop/src/python-runtime.ts` 与 `src/uthcode/interfaces/desktop/bridge.py` 接入同一个 Application/Run/Turn/AgentEvent 链；Renderer 只投影 Bridge 的安全结果，配置、Session、Command 和 typed Interaction 不在 TypeScript 中复制。真实配置的 Desktop 为每个已打开 Session 保存独立 Application/Run runtime，`session.new`、`session.resume` 和 `project.open` 可停放旧 Session 的 active Turn 并切换显示而不取消它；background 事件携带 Session/Project identity，由 Renderer 按 Session 缓存，完成后 Bridge 关闭回收。Bridge 暴露 Application 的 `context_status`/`compaction_status` 安全投影以及 AskUser、Permission、Plan、Pause、Retry typed interaction；Context ring、Runtime panel 和交互控件不取得 Core/Application 内部 authority。
- `[FACT]` Application `_TurnDriver` 把多个 Core execution segment 编排为一条持续事件流，并在暂停时等待 Interface 的 typed response。
- `[ABSENT]` Subagent、任务拆分器、Multi-Agent、Agent 间消息、并行 Worker、任务队列、通用 Scheduler。

## 私有 Eval 手动链路

- `[FACT]` `eval/runner.py` 是仓库级手动入口；它读取版本化任务，创建仓库外的专用 attempt 根，再通过 `uthcode.application` 公共导出交给 `eval/execution.py` 完成一个 Application/Run/Turn 和一条事件流。
- `[FACT]` verifier 作为独立离线子进程读取 attempt workspace；`eval/metrics.py` 与 `eval/reporting.py` 只消费公开事件、终态、verifier 和受控 diagnostics，报告并列保留六个维度，不生成总分。
- `[FACT]` 真实 Eval 运行必须显式提供 `--model` 远端模型标识；该标识进入 attempt 和聚合报告的 `model_id` 指纹。报告同时保存 `task_sample_counts`；Compare 先校验每份报告的映射非空、键集合等于 `task_ids` 且计数总和等于 `sample_count`，再要求两边逐任务样本计数映射完全一致。
- `[BOUNDARY]` Eval 不注册正式 `uthcode` CLI，不接入 CI，不修改 `src/uthcode/**`；workspace、home、artifact、cache 和 report 都必须位于物理校验过的仓库外专用根。
- `[FACT]` Eval diagnostics 可以消费 configured/provider/default/effective limits、tightened sources、selected/omitted block IDs、Pressure/Preflight、Auto/Hard、Timeline/Compaction、epoch/prefix、Tool externalization、Session recovery、Provider cache usage 与 terminal FailureReason/PauseReason 的安全投影；Memory/retrieval 仍保持 `not_available`，报告继续保留六个并列维度，不生成总分。

## 物理依赖边界

```text
interfaces -> application -> core
                  |
                  v
             integrations -> core

forbidden:
  core -> application|integrations|interfaces|third-party SDK
  integrations -> application|interfaces
  interfaces -> core|integrations|Provider SDK
```

- `application/bootstrap.py` 是允许组合具体 Integration 的 composition root。
- `application` 其余模块只使用 Core 合同；少量 Provider 配置枚举是已测试的明确边界。
- SDK import 仅允许存在于对应 `integrations/providers/*.py`。
- Headless Application 不导入 Interface tree。

## 启动编排

```text
python -m uthcode / uthcode
  -> src/uthcode/__main__.py
  -> interfaces/cli.py:main
  -> ApplicationRuntimeContext.from_system(cwd)
  -> load_effective_config
     -> integrations/config/loader.py
     -> 用户 config + 项目 config 合并与安全校验
  -> create_application
     -> provider factory
     -> create_default_tools(workdir)
     -> permission rule loader
     -> ApplicationToolService
     -> UthCodeApplication
  -> CLI exec / TUI 普通输入: 有真实 prompt 时 application.ensure_session()
  -> `/new`: 显式创建 fresh Session；`/resume`: 直接恢复目标 Session
```

## 普通请求编排

```text
Interface
  -> application.create_run()
  -> idle: run.start_turn(prompt)
  -> active ordinary input: TurnHandle.steer(text)
  -> typed interaction pending: TurnHandle.resume(typed response) / cancel()
  -> TurnHandle.events(): 单消费者增量流
  -> TurnHandle.result(): 可重复等待终态
  -> terminal: Application 分别完成 History append/reload/metadata touch 与 Instruction State sync；按可判定 durable outcome 推进 message cursor，按原始 Turn identity FIFO 重试 pending batch，未知 durability quarantine active Session writer 并要求 close/reopen recovery，再记录 diagnostics
```

### TUI

```text
interfaces/tui/app.py
  owns one AgentRun for process lifetime
  slash input -> CommandParser -> await CommandDispatcher.dispatch_async -> CommandOutcome/UiAction
  idle ordinary input -> same AgentRun.start_turn
  active Turn ordinary input -> same TurnHandle.steer
  typed interaction -> same TurnHandle.resume/cancel; typed interaction 优先于 Steering
  AgentEvent -> rendering/interaction projection
```

- TUI 是 prompt_toolkit 主缓冲区适配器；详细界面约束见 `docs/context/TUI/README.md`。
- TUI 不拥有 RunState、Tool Registry、Permission Store 或 Provider。
- `/clear` 只改变 Interface 投影；模型切换只影响下一 Turn。

### 非交互 `exec`

```text
uthcode exec <prompt>
  -> one Application
  -> one AgentRun
  -> one TurnHandle
  -> final answer 写 stdout
  -> Application 的 PauseReason/FailureReason 文案与 reasoning/tool diagnostics 写 stderr
  -> 若 Turn 需要 AskUser/Permission/Retry/Resume：exec 无响应通道，取消同一 Turn 并返回失败
```

### Windows Desktop

```text
desktop/src/renderer/App.tsx
  -> desktop/src/preload.ts（窄 contextBridge API）
  -> desktop/src/main.ts（IPC sender/frame/origin 校验与窗口生命周期）
  -> desktop/src/python-runtime.ts（console JSONL child，windowsHide）
  -> src/uthcode/interfaces/desktop/bridge.py
  -> UthCodeApplication -> AgentRun -> TurnHandle -> Core AgentEvent
  -> Python Runtime JSONL -> Main -> Preload -> Renderer state projection
```

Desktop 的 `PythonRuntime` 只负责一个受控 child 的 stdio、请求相关和 close/reap；Bridge 负责 Application/Run 生命周期和安全 DTO 投影。未提交的 Runtime checkpoint 不跨进程恢复，Runtime crash/protocol error 仍与 Provider/Turn failure 分离。

```text
Desktop Session A active
  -> session.new / session.resume(B) / project.open(B)
  -> Bridge 保存 A 的 application/run/handle/task
  -> 切换到 B 已有 runtime，或新建共享 durable Session store 的 Application
  -> A 的 AgentEvent 附 session_id + project_key，Renderer 在 A 的缓存更新 timeline/Todo/status
  -> A terminal 后可关闭回收；Desktop shutdown 才统一 cancel/close 所有仍活跃 runtime
```

同一 Session 的 `AgentRun` 仍只允许一个 active Turn；可见 Session 的 Steering、Pause、Resume 和 Cancel 始终落到该 Session 的同一 handle。rename/move 在任何已保存 runtime 有 active Turn 时不会越过 Bridge 的 Session 边界。

## Application 职责索引

| 主题 | 文件 | 关键符号/检索词 |
| --- | --- | --- |
| Composition root | `src/uthcode/application/bootstrap.py` | `load_effective_config`, `create_application` |
| Application 门面 | `src/uthcode/application/generation.py` | `UthCodeApplication`, `create_run`, `_start_agent_turn`, `select_model`, `status` |
| Run/Turn 驱动 | `src/uthcode/application/runs.py` | `AgentRun`, `_TurnDriver`, `TurnHandle` |
| Tool 门面 | `src/uthcode/application/tools.py` | `ApplicationToolService` |
| Runtime 环境 | `src/uthcode/application/runtime_context.py` | `ApplicationRuntimeContext` |
| 配置公共模型 | `src/uthcode/application/configuration.py` | `EffectiveConfig`, `LaunchOptions` |
| Slash Command | `src/uthcode/application/commands/` | `CommandRegistry`, `CommandParser`, `CommandDispatcher`, `CommandOutcome` |
| CLI/exec | `src/uthcode/interfaces/cli.py` | `main`, `_stream_exec`, `_ExecProjection` |
| TUI | `src/uthcode/interfaces/tui/` | `UthCodeTUI`, `AgentEventRenderer`, `TuiInteractionState` |
| Desktop | `desktop/src/` + `src/uthcode/interfaces/desktop/bridge.py` | `App`, `PythonRuntime`, `DesktopBridge`, `DesktopApi` |

## 当前命令编排

```text
implemented:
  /help
  /clear
  /model [model-ref]
  /permission [default|auto|full_access]
  /new
  /resume [session-id]
  /status
  /quit
  /plan
  /do
  /build (alias of /do)
  /compact
```

命令注册表只保留上述已实现命令，每个定义都有 handler；未注册的 Slash 名称返回普通 `UNKNOWN_COMMAND`。Dispatcher 只提供异步入口。`/compact` 进入正式 Session use case，并与 automatic L4/L5 复用同一 Application orchestrator；`/plan` 与 `/do` 已由同一 Registry 选择 Behavior Mode，`/build` 只是 `/do` alias。Plan/Task/Steering 状态仍由 Core/Application 权威链路持有，不由命令或 TUI 复制；`/plan`、`/do`、`/compact` 与 `/status` 的 completion/execution 均经由 Application command/use-case 边界，不在 Renderer 另建命令或状态入口。

## 编排不变量

- Interface 只能通过 `uthcode.application` 公共导出工作。
- 一个 `AgentRun` 同时最多一个 active Turn；不允许 Interface 绕过该独占约束直接驱动 Core。
- Desktop 可并存多个 Session runtime，但每个 runtime 都是独立 `Application -> AgentRun -> TurnHandle` 链；Renderer 的 per-Session 缓存不能成为共享 RunState 或持久 Runtime checkpoint。
- 同一个 Turn 的事件与结果来自同一次 execution；不得为事件消费和结果等待创建双执行。
- 普通 Tool 必须经过 `AgentRun.start_turn` 的唯一权限与暂停链；Application 不提供独立的手工 Tool 执行门面。
- active Turn 捕获 Provider/model/tool definitions；运行中切换模型不得改变它。
- 编排异常必须收口为 Core terminal result、关闭事件流并释放 Run active slot。
- 新 Interface 应复用 Application Command、Run、Turn、Event 合同，不复制 Agent Loop 或状态机。

## 不属于当前编排层

- `[ABSENT]` Subagent 创建、Agent 身份/角色、Agent 间协议。
- `[ABSENT]` 自动任务拆分、依赖图、并行 Worker、合并结果策略。
- `[ABSENT]` Multi-Agent 共享 Context、共享 Memory、资源锁和调度策略。
- `[BOUNDARY]` 不恢复跨进程 Runtime checkpoint；resume 只重建已提交 Transcript/Timeline/Instruction State/Session `model_ref`，并从新 Run/Turn 开始。
- `[FACT]` 当前 Windows Desktop 已接入上述 Application 主链；未来 Web/IDE 等新 Interface 仍必须单独设计并只接 Application。

## 修改路由

```text
启动/依赖组装           -> application/bootstrap.py
公共用例/API            -> application/generation.py + application/__init__.py
Run/Turn 驱动与竞态      -> application/runs.py
Slash 命令定义/解析/派发 -> application/commands/
CLI/exec 投影            -> interfaces/cli.py
TUI 编排                 -> interfaces/tui/app.py
Desktop 编排/进程边界    -> desktop/src/ + interfaces/desktop/bridge.py
Subagent/Multi-Agent     -> 当前不存在；需先定义新需求与 Application/Core 边界
```

## 最小验证索引

```powershell
conda activate re-uthcode
python -m pytest tests/test_application.py tests/test_application_runtime.py tests/test_application_runs.py tests/test_cli.py tests/test_command_dispatcher.py -q
python -m pytest tests/test_tui.py tests/test_architecture_boundaries.py -q
```
