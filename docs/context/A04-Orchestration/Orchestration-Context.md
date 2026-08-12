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
- `[FACT]` `create_application -> create_run -> start_turn` 组合一个固定 `RuntimeHookSet`、Plan/Task 控制、同一 Turn Steering 和唯一 Agent Loop/driver；AgentLoop 始终先组合强制 Hook，再按固定顺序运行可选 Hook。
- `[FACT]` TUI 启动一个长生命周期 `AgentRun` 以保留多轮消息；`uthcode exec` 每次创建一个 Run 和一个 Turn。
- `[FACT]` Application `_TurnDriver` 把多个 Core execution segment 编排为一条持续事件流，并在暂停时等待 Interface 的 typed response。
- `[ABSENT]` Subagent、任务拆分器、Multi-Agent、Agent 间消息、并行 Worker、任务队列、通用 Scheduler。

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
  /status
  /quit
  /plan
  /do
  /build (alias of /do)

declared_but_not_implemented:
  /config
  /compact
  /new
  /resume
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
- `[ABSENT]` 通用 workflow engine、后台任务队列、跨进程恢复。
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
