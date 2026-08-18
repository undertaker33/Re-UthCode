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
- `[FACT]` CLI/TUI 进入正式运行前通过 Application `ensure_session()` 打开一个 fresh Session；terminal Turn 的 History、Tool Result ref 与 Instruction State 由 Application 提交并在退出时释放 writer。History 的 JSONL append+fsync、reload、last-used/metadata touch 与 Instruction State sync 分阶段进入安全 diagnostics，Run cursor 只按可判定 durable 的消息推进；append 后异常先做结构化 identity reconciliation，无法判定时 active Session writer quarantine，新的 Run/语义写入均 fail closed，必须 close 后 fresh writer 验证/恢复才可继续；真正未落盘的 pending batch 才保留原始 Session/Turn identity 并在后续 terminal 边界按 FIFO 重试。
- `[FACT]` `ApplicationContextService` 是正式请求组合入口：Context Snapshot 的 Instruction Plane、Conversation Plane 和 `GenerationRequest.tools` 进入同一 Provider-independent DTO；Integration 不重新编译 Context。
- `[FACT]` `create_application -> create_run -> start_turn` 组合用户级安全 Permission 默认值、固定 `RuntimeHookSet`、`ProposePlan`/Task 控制、同一 Turn Steering 和唯一 Agent Loop/driver；AgentLoop 始终先组合强制 Hook，再按固定顺序运行可选 Hook。
- `[FACT]` `/permission default|auto` 先原子写回用户配置并更新 Application 默认值，再由结构化 action 更新当前 Run；`full_access` 不写配置、不改变新 Run 默认值，TUI picker 复用同一命令路径。
- `[FACT]` TUI 启动一个长生命周期 `AgentRun` 以保留多轮消息；`uthcode exec` 每次创建一个 Run 和一个 Turn。
- `[FACT]` Application `_TurnDriver` 把多个 Core execution segment 编排为一条持续事件流，并在暂停时等待 Interface 的 typed response。
- `[ABSENT]` Subagent、任务拆分器、Multi-Agent、Agent 间消息、并行 Worker、任务队列、通用 Scheduler。

## 私有 Eval 手动链路

- `[FACT]` `eval/runner.py` 是仓库级手动入口；它读取版本化任务，创建仓库外的专用 attempt 根，再通过 `uthcode.application` 公共导出交给 `eval/execution.py` 完成一个 Application/Run/Turn 和一条事件流。
- `[FACT]` verifier 作为独立离线子进程读取 attempt workspace；`eval/metrics.py` 与 `eval/reporting.py` 只消费公开事件、终态、verifier 和受控 diagnostics，报告并列保留六个维度，不生成总分。
- `[FACT]` 真实 Eval 运行必须显式提供 `--model` 远端模型标识；该标识进入 attempt 和聚合报告的 `model_id` 指纹。报告同时保存 `task_sample_counts`；Compare 先校验每份报告的映射非空、键集合等于 `task_ids` 且计数总和等于 `sample_count`，再要求两边逐任务样本计数映射完全一致。
- `[BOUNDARY]` Eval 不注册正式 `uthcode` CLI，不接入 CI，不修改 `src/uthcode/**`；workspace、home、artifact、cache 和 report 都必须位于物理校验过的仓库外专用根。
- `[FACT]` Eval diagnostics 可以消费固定预算、selected/omitted blocks、Projection/Compaction、epoch/prefix、Tool externalization、Session recovery 和 Provider Usage 的安全投影；Memory/retrieval 仍保持 `not_available`。

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
  -> CLI/TUI: application.ensure_session()
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
  slash input -> CommandParser -> CommandDispatcher -> CommandOutcome/UiAction
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
  -> reasoning/tool/failure 写 stderr
  -> 若 Turn 需要 AskUser/Permission/Retry/Resume：exec 无响应通道，取消同一 Turn 并返回失败
```

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

## 当前命令编排

```text
implemented:
  /help
  /clear
  /model [model-ref]
  /permission [default|auto|full_access]
  /compact
  /new
  /resume [session-id]
  /status
  /quit
  /plan
  /do
  /build (alias of /do)

declared_but_not_implemented:
  /config
  /login
  /memory
  /dream
  /review
```

命令注册表中保留的未实现命令只返回 `NOT_IMPLEMENTED`；`/plan` 与 `/do` 已由同一 Registry 选择 Behavior Mode，`/build` 只是 `/do` alias。Plan/Task/Steering 状态仍由 Core/Application 权威链路持有，不由命令或 TUI 复制。

## 编排不变量

- Interface 只能通过 `uthcode.application` 公共导出工作。
- 一个 `AgentRun` 同时最多一个 active Turn；不允许 Interface 绕过该独占约束直接驱动 Core。
- 同一个 Turn 的事件与结果来自同一次 execution；不得为事件消费和结果等待创建双执行。
- Application 手工 `execute_tool_calls` 路径被硬拒绝；普通 Tool 必须经过 `AgentRun.start_turn` 的权限与暂停链。
- active Turn 捕获 Provider/model/tool definitions；运行中切换模型不得改变它。
- 编排异常必须收口为 Core terminal result、关闭事件流并释放 Run active slot。
- 新 Interface 应复用 Application Command、Run、Turn、Event 合同，不复制 Agent Loop 或状态机。

## 不属于当前编排层

- `[ABSENT]` Subagent 创建、Agent 身份/角色、Agent 间协议。
- `[ABSENT]` 自动任务拆分、依赖图、并行 Worker、合并结果策略。
- `[ABSENT]` Multi-Agent 共享 Context、共享 Memory、资源锁和调度策略。
- `[BOUNDARY]` 不恢复跨进程 Runtime checkpoint；resume 只重建已提交 Session History/Projection/Instruction State，并从新 Run/Turn 开始。
- `[DEFER]` Web/Desktop/IDE 等新 Interface；新增时仍必须只接 Application。

## 修改路由

```text
启动/依赖组装           -> application/bootstrap.py
公共用例/API            -> application/generation.py + application/__init__.py
Run/Turn 驱动与竞态      -> application/runs.py
Slash 命令定义/解析/派发 -> application/commands/
CLI/exec 投影            -> interfaces/cli.py
TUI 编排                 -> interfaces/tui/app.py
Subagent/Multi-Agent     -> 当前不存在；需先定义新需求与 Application/Core 边界
```

## 最小验证索引

```powershell
conda activate re-uthcode
python -m pytest tests/test_application.py tests/test_application_runtime.py tests/test_application_runs.py tests/test_cli.py tests/test_command_dispatcher.py -q
python -m pytest tests/test_tui.py tests/test_architecture_boundaries.py -q
```
