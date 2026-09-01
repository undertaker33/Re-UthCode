# A02 Control（控制层）

```text
layer: A02-Control
context_file: docs/context/A02-Control/Control-Context.md
owns: permission + approval + cooperative pause/resume + ask-user + cancellation
current_shape: application-controlled boundaries over one Core Turn
explicit_absence: OS sandbox + dynamic hook registry/plugin lifecycle
```

## 当前结论

- `[FACT]` 已实现三段权限决策：`Guard -> Policy -> Strategy`，并支持 Run-local `SessionGrant`。
- `[FACT]` 已实现 `default`、`auto`、`full_access` 三种 Run-local 权限模式；用户配置可持久化安全默认值 `default|auto`，`full_access` 仍仅当前 Run 有效。
- `[FACT]` 已实现五类 typed pause kind：`USER_REQUESTED`、`USER_INPUT_REQUIRED`、`PROVIDER_UNAVAILABLE`、`PERMISSION_REQUIRED`、`PLAN_REVIEW_REQUIRED`；Provider unavailable 的 `PauseReason` 可区分 `NETWORK_ERROR`、`RATE_LIMITED` 与 `TIMEOUT`。
- `[FACT]` 暂停/恢复保持同一个 `AgentTurnExecution`、同一个 `TurnHandle` 和同一个事件流，不创建替代 Turn。
- `[FACT]` 取消优先于待处理的恢复或审批响应；取消幂等。
- `[FACT]` Agent Loop 在 trusted preflight 与 Permission 之间直接执行 PLAN 只读检查，并在 usage accounting 后、assistant final 提交前直接执行 unfinished-task 阻断；Plan Review 只由合法 `ProposePlan` 控制 ToolCall 触发。
- `[FACT]` Plan Review 使用现有 typed pause/resume，TodoWrite 与同一 Turn Steering 使用同一 Core execution 边界；不创建第二个控制 Runtime。
- `[BOUNDARY]` Permission Approval 是应用层授权，不是 OS Sandbox。
- `[ABSENT]` 当前没有 OS Sandbox、动态控制扩展 registry、第三方 Hook plugin 生命周期或可热插拔控制点。

## 权威源码索引

| 主题 | 文件 | 关键符号/检索词 |
| --- | --- | --- |
| 权限领域模型 | `src/uthcode/core/permission.py` | `PermissionMode`, `Effect`, `ResourceScope`, `Decision`, `PermissionAction`, `Rule`, `RuleSet`, `SessionGrant`, `PermissionEvaluator` |
| 暂停与响应协议 | `src/uthcode/core/interaction.py` | `PauseKind`, `PauseReason`, `PauseRequest`, `PauseResponse`, `UserInputRequest`, `PermissionApprovalRequest` |
| 控制事件 | `src/uthcode/core/agent_events.py` | `TurnPausing`, `TurnPaused`, `TurnResumed`, `UserInputRequested` |
| Runtime 控制点 | `src/uthcode/core/agent.py` | `run_segment`, `_run_tool_batch`, `_pause_*_segment`, `_apply_response`, `cancel` |
| Application 协调 | `src/uthcode/application/runs.py` | `AgentRun`, `_TurnDriver`, `TurnHandle.pause/resume/cancel`, `pending_pause` |
| 权限文件与默认 Guard | `src/uthcode/integrations/permissions.py` | `load_permission_rules`, `default_guard_rules`, `discover_permission_paths` |
| Tool Action preflight | `src/uthcode/integrations/tools/` | `PermissionAction`, `Effect`, `ResourceScope`, `classify_bash_command` |
| 安全摘要 | `src/uthcode/core/command_security.py`, `src/uthcode/application/tools.py` | `safe_bash_command_summary`, `_SecretRedactor` |
| TUI 控制投影 | `src/uthcode/interfaces/tui/interaction.py`, `app.py` | `TuiInteractionState`, `open_pause`, `TurnHandle.resume` |

## 权限决策顺序

```text
Tool.prepare_call
  -> PreparedToolCall(action=PermissionAction)
  -> PermissionEvaluator.evaluate(action, run.mode, run.session_grants)
     1. 匹配可信 circuit breaker
        用户/项目显式 Guard DENY -> DENY
        否则 -> ASK（所有模式，仅 ONCE/REJECT）
     2. 选择用户/项目显式 Guard
        DENY -> deny
        ASK  -> ask
        ALLOW -> 记录 guard_allowed，继续
     3. mode == full_access
        -> 跳过内置普通 Guard、普通 Policy 与 Strategy并 ALLOW
     4. 选择内置普通 Guard，再选择匹配 Policy
        -> policy 的 ALLOW/ASK/DENY 是终态
     5. Strategy fallback
        default: inside+read=ALLOW，其余=ASK
        auto: inside+(read|write)=ALLOW，其余=ASK
     5. 仅 Strategy ASK 可被精确 SessionGrant 替换为 ALLOW
```

## 权限数据边界

- `PermissionAction` 只能由可信 Tool preflight 产生，维度为 `tool/action/effect/resource/scope`。
- `Effect` 固定为 `read/write/destructive/external/unknown`；`ResourceScope` 固定为 `inside/outside/unknown`。
- 权限规则文件与普通 `config.toml` 分离：用户级 `~/.uthcode/permissions.toml`，项目级 `<scope>/.uthcode/permissions.toml`。
- `load_permission_rules` 在 `AgentRun` 创建时加载一次不可变 `RuleSet`；运行中修改文件不热加载。
- 来源优先级：内置默认规则 < 用户规则 < 从 Git 根到 cwd 的项目规则；同来源同优先级按 `DENY > ASK > ALLOW`。规则的 builtin/configured/circuit-breaker 权威等级是 Core 结构属性，权限 TOML 不能声明。
- 内置普通 Guard 在 `default`/`auto` 下保护敏感凭据路径和高置信危险 Bash 行为；`full_access` 跳过它。用户/项目显式 Guard ASK/DENY 在三种模式均为终态。
- circuit breaker 只覆盖根目录/Home 递归删除、磁盘/卷破坏、裸设备写入。事实由 Bash Tool preflight 的段级解析器写入 `PermissionAction.circuit_breakers`，并对已支持的 `sh/bash/zsh -c`、`cmd /c`、PowerShell `-Command`、命令替换/反引号和 `clean | diskpart` 做有界递归检查；不从 rule ID、source 或展示摘要猜测。三种模式均 ASK，普通 ALLOW 不能覆盖，显式 DENY 可收紧。
- 其他普通高风险事实（敏感读取、提权、远程脚本管道、fork bomb、关键进程、递归权限修改、嵌套执行、UNKNOWN 等）仍可在普通模式命中内置 Guard，但不属于 circuit breaker。
- `SESSION` 审批只写入当前内存 `AgentRun`，按动作维度与有界资源匹配；不写持久规则。只有 Strategy fallback ASK 且 Action 含非空有界 resource 时才提供该选项。
- Guard ASK、Policy ASK 和 resource-less ASK 只提供 `ONCE/REJECT`；Policy ALLOW/ASK/DENY 保持终态，Session Grant 不覆盖 Guard 或 Policy。
- Bash 权限与活动摘要会脱敏带有 `KEY`/`AUTH` 独立段及既有 token/secret/password/credential 词汇的赋值；普通名称片段不得误判为秘密。

## 暂停状态机

```text
running segment
  -> USER_REQUESTED:
       pause_signal 中断 Provider attempt 或在 Tool 安全边界等待当前 Tool 结束
       response = ResumeTurnResponse
  -> USER_INPUT_REQUIRED:
       AskUserQuestion -> UserInputRequest -> UserInputResponse
  -> PROVIDER_UNAVAILABLE:
       NetworkError/RateLimitError -> RetryProviderResponse
       重试同一 iteration，不提交失败 attempt 的 partial message/usage
  -> PERMISSION_REQUIRED:
       PreparedToolCall 保留但不执行 -> PermissionApprovalResponse
       ONCE/SESSION 执行一次；REJECT 生成受控 Tool error
  -> PLAN_REVIEW_REQUIRED:
       ProposePlan ToolCall -> Core 创建 PlanState -> PlanReviewRequest
       APPROVE -> PlanState.approved + PLAN -> DEFAULT
       REVISE -> ToolFinished -> role=tool Message -> ToolBatchFinished
              -> 追加真实 role=user Message + one-shot revision feedback
              -> 保持 PLAN，在同一 Turn 重新请求 Provider
       Cancel -> cancellation wins -> TurnCancelled

任意 pending pause
  -> cancel
  -> cancellation wins
  -> 原 ToolCall ID 全部闭合
  -> TurnCancelled
```

## 控制不变量

- Core segment 到 `PAUSED` 或 `TERMINAL` 边界即返回；Core 内不保存 asyncio waiter、queue、task。
- `_TurnDriver` 独占 asyncio task、事件 queue、响应 waiter；Interface 只使用 `TurnHandle`。
- `PauseRequest` 与响应必须严格匹配 `pause_id/run_id/turn_id`；工具型暂停还必须匹配 `tool_call_id`，权限暂停还匹配 `permission_id`。
- `AskUserQuestion` 支持 1—4 个问题，类型为 text/single-select/multi-select；text 不携带 options，single-select/multi-select 各自要求 2—3 个结构化 options。选择题的自由文本输入始终由 Interface 提供，非空选项外答案与选项答案一样通过 typed response 校验；当前协议不接受旧的 `allow_other` 字段或 “Other” 选项分支。
- `PLAN_REVIEW_REQUIRED`（Plan Review）、`USER_INPUT_REQUIRED`（AskUser）、`PERMISSION_REQUIRED`（Permission）、`PROVIDER_UNAVAILABLE`（Retry，区分 network/rate-limit/timeout）与 `USER_REQUESTED` 是互斥的 typed interaction；pending typed interaction 存在时拒绝普通 Steering，输入优先交给对应 typed response。
- 用户主动暂停是 cooperative pause，不等于取消；Provider attempt 可被暂停信号打断，正在执行的普通 Tool 不因暂停被强杀。
- `Bash` 取消会尝试终止进程树，但执行仍使用当前 OS 用户权限；不得描述为沙箱。
- 未知错误对外转为稳定、无内部异常正文的失败事件/结果。

## 不属于当前控制层

- `[ABSENT]` OS 级文件、网络、系统调用 Sandbox。
- `[FACT]` 固定 PLAN 非 `READ` 与 unfinished-task 检查已在 Agent Loop 的唯一顺序中实现其受控拒绝/继续结果。
- `[ABSENT]` 动态 Hook registry、第三方 Hook plugin 生命周期、after-tool/事件控制扩展链。
- `[ABSENT]` 跨进程 pending pause 恢复；进程退出后控制状态丢失。
- `[ABSENT]` 持久化 permission decision；只有显式规则文件与 Run-local SessionGrant。

## 修改路由

```text
权限矩阵/Rule 匹配         -> core/permission.py
权限文件发现/解析/默认 Guard -> integrations/permissions.py
具体 Tool effect/scope/action -> integrations/tools/*.py
暂停协议/AskUser 数据       -> core/interaction.py
暂停产生与 Tool 审批接入    -> core/agent.py
等待、恢复、取消竞态        -> application/runs.py
TUI 问答/审批交互           -> interfaces/tui/interaction.py + app.py
PLAN/unfinished 固定控制检查 -> core/agent.py + tests/test_agent_loop.py；不提供可插拔 registry 或旧入口兼容层
```

## 最小验证索引

```powershell
conda activate re-uthcode
python -m pytest tests/test_permission.py tests/test_permission_rules.py tests/test_permission_integration.py tests/test_agent_interaction.py tests/test_application_runs.py -q
python -m pytest tests/test_permission_delivery.py tests/test_builtin_process_tool.py -q
```
