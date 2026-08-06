# UthCode T05：ReAct 与 Agent Loop 任务书

> 对应原 UthCode Day4「ReAct、Agent Loop 与活动流」中仍适用于 Re-UthCode 的 Agent Core、统一事件流、Headless/CLI/TUI 接入能力。

## 1. 分析基线

### 1.1 仓库与提交

```text
目标仓库：https://github.com/undertaker33/Re-UthCode
固定基线：4802f1989deada8c6b64b05035760e1e2b231108
提交信息：feat: 完成 T04 工具系统
正式编号：T05-ReAct与AgentLoop
```

编码前必须执行：

```bash
git rev-parse HEAD
```

结果必须为固定 SHA，或仅包含用户明确允许的后续文档变更。不得基于更晚 HEAD、旧报告或记忆实施。

固定基线中的 `docs/work/T04-工具系统/` 已完成源码、Checklist 与 Feedback，但尚未由用户手动归档。不得由编码代理移动或归档。

### 1.2 最高级约束

实施前完整读取：

```text
AGENTS.md
SRe-AGENTS.md
docs/work/README.md
```

冻结依赖方向：

```text
interfaces → application → core
                  ↓
             integrations
```

必须遵守：

- Core 拥有 Agent Loop、权威 RunState、终止策略、Tool 调度语义和 AgentEvent。
- Application 是 Headless 与全部 Interface 的唯一入口，负责组合 Provider、System Prompt、Tool Runtime 和 Run/Turn 用例。
- Integration 只负责 Provider SDK、文件系统、进程等外部实现；第三方类型不得进入 Core。
- Agent Loop 是 RunState 的唯一写入者。
- 不使用 LangGraph、LangChain Agent、StateGraph、Node、Edge、Reducer、Checkpoint、Interrupt/Resume 或通用工作流框架。
- Tool Batch 严格 FIFO；每个 ToolCall 必须得到同 ID 的 ToolResult。
- Bash 仍是当前操作系统用户权限下的 unsandboxed process execution，不得描述为 Sandbox。
- TUI 只负责输入、AgentEvent 投影、显示状态和取消，不拥有 RunState。
- 不兼容旧 UthCode、MewCode 或 Re-UthCode 早期临时 API；被替代的正式调用链必须删除，不保留双轨兼容层。
- 不创建无真实调用方的 Protocol、Repository、Manager、Factory、未来目录或伪实现。

### 1.3 前置任务包

```text
docs/archive/work/T01-项目骨架与Provider抽象/
docs/archive/work/T01-2-移除pydantic改用原生SDK/
docs/archive/work/T02-SlashCommand与默认TUI/
docs/archive/work/T03-SystemPrompt设计/
docs/work/T04-工具系统/
```

重点读取：

```text
T02-SlashCommand与默认TUI.md
T03-SystemPrompt设计.md
T04-工具系统.md
T04-工具系统-spec.md
T04-工具系统-tasks.md
T04-工具系统-checklist.md
feedback/W04-application-delivery-feedback.md
```

前置稳定能力：

| 能力 | 当前实现 | T05 处理 |
| --- | --- | --- |
| Provider | 三种原生 SDK Adapter、Fake Provider、统一 DTO、流事件、错误与取消 | 直接复用 |
| System Prompt | Application 每次 generation 前构建并注入 | 每个 iteration 继续经过同一边界 |
| Tool | Core Registry/Executor、六个 Integration Tool、FIFO、统一结果 | 直接复用 |
| Application | Provider 快照、运行上下文、模型切换、低层 Generation/Tool API | 新增 Run/Turn 用例 |
| CLI/TUI | 单轮 ProviderEvent 消费 | 切换为 AgentEvent |
| Slash Command | Registry、Parser、Dispatcher、`/model` | 保持现有语义 |
| 配置 | 用户/项目 TOML、模型目录、Provider Factory | 不修改 |

### 1.4 历史参考

原 UthCode：

```text
仓库：https://github.com/undertaker33/UthCode
基线：1c3507b761e48ac38d846bc39700ce0039f84a04
任务包：docs/archive/work/Day4-ReAct-AgentLoop与活动流/
```

只提取：

- Provider 原生 Tool Calling；
- iteration、Tool 数量、unknown streak；
- ToolCall/ToolResult 协议闭合；
- progress/final/incomplete 分类；
- Usage 累计；
- 取消补偿；
- 统一活动事件；
- CLI stdout/stderr 产品语义；
- 测试场景与历史失败教训。

不得迁入 LangGraph、Graph State、节点/路由、Checkpoint、旧 Runtime、旧目录/API、Workspace Diff 或旧版大型 Textual 页面结构。

MewCode 来源：

```text
/mnt/data/3_mewcode-python.zip
```

只参考：

```text
mewcode/agent.py
mewcode/conversation.py
tests/test_agent.py
tests/test_recovery.py（只识别历史边界）
```

可重新实现显式顺序循环、assistant ToolCall 先入 conversation、结果按序回填、自然结束、Usage 和 unknown guard。不得迁入工具并发、两套 Loop、可变 ConversationManager、Pydantic 参数模型、恢复/压缩/Permission/Memory/Team 或大型 Agent 对象。

### 1.5 实际核对范围

```text
src/uthcode/core/provider.py
src/uthcode/core/tool.py
src/uthcode/core/__init__.py

src/uthcode/application/generation.py
src/uthcode/application/tools.py
src/uthcode/application/bootstrap.py
src/uthcode/application/__init__.py

src/uthcode/interfaces/cli.py
src/uthcode/interfaces/tui/app.py
src/uthcode/interfaces/tui/rendering.py
src/uthcode/interfaces/tui/state.py
src/uthcode/interfaces/tui/widgets.py

tests/test_application_tools.py
tests/test_application.py
tests/test_cli.py
tests/test_tui.py
tests/test_architecture_boundaries.py
tests/test_package.py

pyproject.toml
README.md
```

### 1.6 基线验证

T04 Feedback 最近一次记录：

```text
python -m compileall -q src tests  → 通过
pytest -q                         → 321 passed, 3 skipped
python -m pip check               → No broken requirements found.
git diff --check                  → 退出码 0
```

三个 skipped 为需显式授权的 live Provider 测试。固定提交没有可用 GitHub Actions Workflow Run。

任务书生成环境没有目标仓库工作树，未重复执行本地命令。编码前必须重新运行：

```bash
python -m compileall -q src tests
pytest -q
python -m pip check
git diff --check
```

若与上述记录存在实质差异，停止并报告，不得把基线问题混入 T05。

---

## 2. 当前实现基线

### 2.1 Provider

`core/provider.py` 已提供并必须复用：

```text
CancellationToken
ProviderPort
GenerationRequest
ProviderResponse
GenerationCompleted
Message / TextPart / ReasoningPart
ToolDefinition / ToolCallPart / ToolResultPart
Usage
FinishReason
ProviderEvent
```

关键事实：

- DTO frozen、深度不可变且 JSON-safe；
- `GenerationCompleted.response` 是权威完整响应；
- Application 当前验证 Provider 流必须以唯一合法终态结束；
- 增量事件不能直接成为权威 conversation；
- SDK 类型只存在于 Integration。

### 2.2 Tool

`core/tool.py` 已提供：

```text
ToolRegistry
ToolExecutor.execute_call()
ToolExecutor.execute_batch()
```

Registry 保持注册顺序。Executor 负责 JSON Schema 校验、FIFO、unknown、参数错误、普通异常、取消和统一截断。

Agent Loop 必须复用现有 `execute_call()` 并按原顺序逐个执行，以产生单 Tool 生命周期事件和处理中途取消。不得重写 Executor，不得在 Loop 内复制 Schema 校验或结果截断规则。

### 2.3 Application

当前 API：

```text
start_generation()
stream_generation()
tool_definitions()
execute_tool_calls()
```

当前行为：

- GenerationHandle 独立取消并固定 Provider；
- Application 拒绝调用方覆盖 `model`、`system_prompt`；
- 每次请求前构建 System Prompt；
- raw generation 不自动注入工具；
- Tool 调用与消息回填由调用方手动完成。

这些低层 API 有真实 Headless 和契约测试调用方，继续保留；但 README 必须明确：

```text
低层单轮 Provider API
≠
自动 Agent Run/Turn API
```

低层 API 不构成第二套自动 Agent Loop。

### 2.4 Interface

当前正式普通输入路径：

```text
CLI / TUI
→ GenerationRequest
→ GenerationHandle
→ ProviderEvent
```

当前限制：

- 每次输入完全单轮；
- TUI Transcript 只是显示记录，不是权威会话；
- `exec` 将全部 `TextDelta` 写 stdout；
- TUI 已能接收 Provider reasoning，但没有统一 Agent 活动协议；
- 没有自动 Tool 闭环、RunState、Turn 或 AgentEvent；
- 用户消息和 Agent 消息的视觉层级不够明确；
- Tool 活动尚未形成稳定、低噪声的展示方式。

### 2.5 架构门禁

当前测试仍禁止 `runtime.py`、`graph`、`permissions`、`context`、`memory`、`session`、`storage`、`journal`、`sandbox` 等未来模块。

T05 只放行真实新增的 Core Agent 文件，继续禁止：

```text
runtime.py
graph/
Permission / Context / Memory
Session / Storage / Journal
Sandbox
Hook / Skill / MCP
Worktree / Subagent / Multi-Agent
```

---

## 3. 冻结产品决策

### 3.1 Run / Turn 生命周期

```text
一个内存 Run 包含多个 Turn
当前阶段不做 Run 持久化与历史管理
```

- `UthCodeApplication.create_run()` 创建独立内存 Run。
- 同一 Run 的下一 Turn 自动携带此前权威 conversation。
- 不同 Run 的 Agent state、conversation、TurnHandle 和取消令牌隔离。
- Tool Runtime 继续由 Application 所有：同一 Application 的 Runs 共享 T04 已建立的 Registry、Executor 和文件读取状态；不同 Application 隔离。
- 每个 Run 同时最多一个活动 Turn。
- 不提供跨 Run 调度、全局串行或并行安全承诺；每个 Tool Batch 内部必须 FIFO。
- TUI 生命周期内创建一个 Run，普通输入形成多轮对话。
- 不写磁盘，不提供 Run 列表、恢复、重命名、删除或历史浏览。

### 3.2 Reasoning 公开语义

```text
Provider 提供的 reasoning 文本公开给 Headless、CLI 和 TUI
不合成不存在的 reasoning
```

- AgentEvent 必须包含 reasoning 生命周期与增量文本事件。
- Provider 发出 reasoning 增量时，按实际顺序投影为 AgentEvent；Provider 未提供时不伪造。
- reasoning 文本是公开显示流，不是 RunState 的独立写入来源。
- 权威 conversation 仍只从 `GenerationCompleted.response` 更新。
- CLI 将 reasoning 文本写入 stderr。
- TUI 将 reasoning 文本作为普通 Agent 文本显示，不使用灰暗、斜体、隐藏或折叠样式。
- 不把 Provider native payload、SDK 对象、配置秘密、traceback 或内部诊断混入 reasoning 事件。

### 3.3 `uthcode exec` 输出

```text
stdout：只输出 final answer
stderr：reasoning、progress、Tool 活动、incomplete、失败与取消
```

退出码：

```text
completed                 0
failed                    1
cancelled / Ctrl+C      130
CLI 参数或配置错误        2
```

要求：

- final 文本不加前缀；
- stdout 不得出现 reasoning、progress、Tool output、事件字典或内部诊断；
- stderr 中 Tool 活动只显示 Tool 名和安全命令/参数摘要，不显示 ToolResult 正文；
- CLI 必须先知道 assistant message 的最终分类，再决定写 stdout 还是 stderr，不能把尚未分类的 TextDelta 直接写 stdout。

### 3.4 TUI 信息层级

冻结为以下视觉语义：

1. 用户消息使用独立的整块背景容器，背景覆盖完整消息行/块，而不是仅给文字本身加底色。
2. 用户消息块与 Agent 输出之间保留明确垂直间距，使双方内容无需依赖标签即可区分。
3. Agent reasoning 文本与最终回复文本均使用正常正文颜色，和用户消息正文使用同一文本色变量。
4. reasoning 不使用弱化色、斜体、小号字体、隐藏区或折叠区。
5. Tool 调用使用低强调度的浅色/次要文本样式。
6. Tool 活动只展示状态、Tool 名和安全命令/参数摘要；不展示 ToolResult 正文，不提供结果展开入口。
7. Tool 完成后更新原活动行的状态或追加同层级完成行，不创建大块结果卡片。
8. TUI 保持当前主题系统，不硬编码某一套具体 RGB 颜色；通过现有 Textual theme 变量表达正文、背景和 muted 层级。

建议文本形态：

```text
[用户消息整块背景]
› 随便调用一个只读工具

我调用一个只读工具，读取当前工作目录。

• Running  Get-Location

只读命令仍在等待返回，我继续等待其结果。

• Finished Get-Location

最终回复正文……
```

其中 `Get-Location` 仅为展示形态示例；实际内容必须来自真实 ToolCall。

---

## 4. 交付目标

T05 必须交付：

1. Provider 原生 Tool Calling 驱动的显式 ReAct Loop；
2. Core 自有 policy、RunState、RunSnapshot、TurnResult 和 AgentEvent；
3. Agent Loop 作为 RunState 唯一写入者；
4. iteration 等于 Provider 调用次数；
5. Agent 请求自动注入当前有序 Tool Definitions；
6. assistant ToolCall → FIFO ToolResult → 下一次 Provider 请求的自动闭环；
7. 正常、错误、unknown、超限、截断、取消路径的协议闭合；
8. 默认限制 `50 / 16 / 3`；
9. Turn 级 Usage 累计；
10. `progress / final / incomplete` 协议分类；
11. 每 Turn 唯一 completed / failed / cancelled 终态；
12. 内存 Run 多 Turn、Provider/Model 快照和独立 TurnHandle；
13. Headless、CLI、TUI 消费同一 AgentEvent 语义；
14. reasoning 文本通过统一 AgentEvent 公开；
15. Tool 活动通过安全摘要公开，不公开 ToolResult 正文；
16. TUI 完成用户消息块、Agent 正文、Tool 浅色活动流的重新分层；
17. 删除 Interface 正式普通输入直连 ProviderEvent 的旧路径；
18. 保留低层 Generation 与手动 Tool API。

正式 Agent 路径：

```text
CLI / TUI / Headless
          │
          ▼
UthCodeApplication.create_run()
          │
          ▼
AgentRun.start_turn()
          │
          ├── Provider + Model Ref 快照
          ├── Application 请求准备
          ├── 有序 Tool Definitions
          ├── Tool 调用安全摘要函数
          └── 独立 CancellationToken
          │
          ▼
Core AgentLoop / AgentTurnExecution
          │
          ├── 唯一创建下一版 RunState
          ├── ProviderPort.stream()
          ├── ToolRegistry + ToolExecutor
          └── AgentEvent
          │
          ▼
TurnHandle.events() / TurnResult
```

单 Turn：

```text
append user Message
→ 检查 iteration 预算
→ iteration += 1
→ Application 准备 GenerationRequest
→ Provider stream
→ 实时产生 reasoning / assistant display events
→ 仅以 GenerationCompleted.response 更新权威状态
   ├─ 无 ToolCall：final / incomplete / failed
   └─ 有 ToolCall：
        append assistant Message
        → 严格 FIFO 执行
        → append 一个 role=tool Message
        → 下一次 Provider 调用
```

---

## 5. 明确不做

```text
Permission / Pending Permission / 审批
OS Sandbox
Journal / Checkpoint / 持久 Snapshot
Interrupt / Resume 框架
完整 Session 与历史浏览
Context Compiler / Budget / 压缩
Memory / Dream
WorkspaceChange / unified Diff / Diff Viewer
Hook / Skill / MCP
Worktree / Subagent / Multi-Agent
工具并行
Bash 全工作区副作用扫描
Web / Desktop / IDE
Artifact 仓库
跨 Run 大输出存储、去重和 GC
通用任务调度器或工作流引擎
```

特别禁止：

- 创建 `graph/` 或 `runtime.py`；
- 使用 node/router/edge 模拟工作流框架；
- 创建后续能力占位；
- 复制旧 `src/uthcode/graph/*`；
- 同时保留两套自动 Loop；
- 迁入 MewCode 的双 Loop；
- TUI 直连 ProviderPort、ToolRegistry 或 ToolExecutor；
- 匹配 ToolResult 文案判断 unknown/cancelled；
- 将普通 Tool 错误默认升级为 TurnFailed；
- 把 Bash 描述为 Sandbox；
- 在 TUI 中展示 ToolResult 正文或为其创建展开组件；
- 在 Interface 中根据原始 Tool 参数自行拼接可能泄露内容的命令摘要。

---

## 6. 原 Day4 要求处理

| 原要求 | 处理 | 新版落实 |
| --- | --- | --- |
| Provider 原生 Tool Calling | 保留 | 复用现有 Tool DTO 与 Adapter |
| 显式 ReAct | 调整 | 集中式 async Loop，不使用 Graph |
| iteration=Provider 调用 | 保留 | Provider 调用前递增 |
| Tool 严格串行 | 保留 | 按原序逐个 `execute_call()` |
| ToolCall/Result 闭合 | 保留 | 包含错误、超限、截断、取消 |
| 同批结果原序回填 | 保留 | 一个 `role=tool` Message |
| max iterations | 保留 | 默认 50 |
| 单响应 Tool 上限 | 保留 | 默认 16，超限整批零执行 |
| unknown streak | 保留 | 默认 3，Registry 预检查 |
| progress/final/incomplete | 保留 | FinishReason + ToolCall 分类 |
| Usage 累计 | 保留 | 只累计权威终态 |
| 统一活动事件 | 调整 | 无 UI、无 SDK 的 AgentEvent |
| Provider reasoning | 调整 | 通过 AgentEvent 公开文本，权威状态仍取 terminal |
| CLI/TUI 同协议 | 保留 | 只消费 Application Agent API |
| 每工具持久 checkpoint | 废弃 | 仅内存不可变状态 |
| LangGraph recursion limit | 废弃 | 只保留业务 max iterations |
| Workspace Diff | 后置 | 不进入 T05 |
| 旧版完整 Textual 页面 | 废弃 | 只实现当前 TUI 所需基础活动流 |
| 取消补偿 | 保留 | partial 丢弃、ToolResult 补齐 |
| 完整多 Session | 后置 | 仅内存 Run 多 Turn |

---

## 7. 目标目录树

```text
src/uthcode/
├── core/
│   ├── __init__.py                         [修改]
│   ├── provider.py                         [修改]
│   ├── tool.py                             [保留]
│   ├── agent.py                            [新增]
│   └── agent_events.py                     [新增]
├── application/
│   ├── __init__.py                         [修改]
│   ├── generation.py                       [修改]
│   ├── tools.py                            [修改]
│   ├── bootstrap.py                        [修改]
│   └── runs.py                             [新增]
└── interfaces/
    ├── cli.py                              [修改]
    └── tui/
        ├── app.py                          [修改]
        ├── rendering.py                    [修改]
        ├── state.py                        [修改]
        └── widgets.py                      [修改]

tests/
├── test_agent_policy.py                    [新增]
├── test_agent_events.py                    [新增]
├── test_agent_loop.py                      [新增]
├── test_application_runs.py                [新增]
├── test_provider_contract.py               [修改]
├── test_application.py                     [修改]
├── test_application_tools.py               [修改]
├── test_cli.py                             [修改]
├── test_tui.py                             [修改]
├── test_architecture_boundaries.py         [修改]
└── test_package.py                         [修改]

README.md                                    [修改]
```

禁止创建：

```text
src/uthcode/graph/
src/uthcode/runtime.py
src/uthcode/session/
src/uthcode/storage/
src/uthcode/journal/
src/uthcode/permissions/
src/uthcode/context/
src/uthcode/memory/
src/uthcode/sandbox/
```

---

## 8. 核心协议

### 8.1 `core/agent.py`

至少定义：

```text
AgentLoopConfig
RunStatus
TerminationReason
AssistantMessageKind
RunState
RunSnapshot
TurnResult
AgentLoop
AgentTurnExecution
```

默认值：

```python
max_iterations = 50
max_tool_calls_per_iteration = 16
max_consecutive_unknown_tools = 3
```

终止原因至少覆盖：

```text
final_answer
max_iterations
max_tool_calls
consecutive_unknown_tools
max_output_tokens
provider_error
invalid_provider_response
user_cancelled
internal_error
```

`RunState` 最低事实：

```text
run_id
turn_id
messages
iteration_count
tool_call_count
consecutive_unknown_tools
usage
status
termination_reason
```

约束：

- frozen、深度不可变；
- 每次变化创建新 State；
- 只有 AgentLoop/AgentTurnExecution 创建下一版；
- 新 Turn 保留 messages，重置 Turn 计数、usage、status、reason；
- Provider SDK、Exception、Path、bytes、Task 不进入 State；
- Application 私有保存 Core 返回的 State 引用，不修改字段；
- `RunSnapshot` 由 Core 从 State 生成，只公开 Run/Turn 标识、状态、计数、Usage 和终止原因，不包含 conversation 原文或 Provider native payload；
- reasoning 是否公开由 AgentEvent 决定，不通过 Snapshot 暴露完整历史；
- Interface 不接触 RunState 或 RunSnapshot。

### 8.2 `core/agent_events.py`

至少提供：

```text
TurnStarted
IterationStarted
ReasoningStarted
ReasoningDelta
ReasoningFinished
AssistantMessageDelta
AssistantMessageCompleted
UsageUpdated
ToolBatchStarted
ToolStarted
ToolFinished
ToolBatchFinished
TurnCompleted
TurnFailed
TurnCancelled
AgentEvent
agent_event_from_dict()
agent_event_from_json()
```

所有事件：

- frozen、JSON-safe；
- 有稳定 `type`；
- 携带 run/turn 及必要 message/batch/tool ID；
- 保持实际到达顺序；
- 每 Turn 只出现一个终态；
- 不携带 SDK 对象、Exception、Path、bytes、Task；
- 不携带 API key、Base URL、traceback、内部绝对路径或 Provider native payload。

Reasoning 事件：

```text
ReasoningStarted
ReasoningDelta(text)
ReasoningFinished
```

规则：

- 第一个非空 reasoning chunk 前发送 `ReasoningStarted`；
- 每个非空 chunk 发送 `ReasoningDelta`；
- 当前 reasoning 段结束时发送 `ReasoningFinished`；
- 同一 iteration 允许出现多个 reasoning 段，必须保持 Provider 实际顺序；
- 不根据普通 `TextDelta` 猜测 reasoning；
- Provider stream 未取得权威 terminal 时，已发送的 reasoning 仍只是显示事件，不写入权威 conversation。

assistant 分类：

```text
LENGTH / INCOMPLETE → incomplete
含 ToolCall         → progress
否则                → final
```

纯 ToolCall 且文本为空时，不发送空 assistant 文本事件。

Tool 事件最少字段：

```text
ToolStarted:
  tool_call_id
  tool_name
  command

ToolFinished:
  tool_call_id
  tool_name
  command
  status
  is_error
```

其中 `command` 是面向显示的安全摘要，不是原始参数 JSON；`ToolFinished` 不携带 ToolResult 正文。

### 8.3 Provider 权威边界

把 `generation.py` 当前通用终态校验提取为 `core/provider.py` 的共享 helper，供低层 GenerationHandle 与 AgentTurnExecution 共用：

- 必须产生一个 `GenerationCompleted`；
- terminal 后不得再有事件；
- terminal 仅在底层 iterator 正常 EOF 后公开；
- finally 关闭 stream；
- 缺终态或尾随事件映射 `InvalidProviderResponseError`；
- 不修改 Provider DTO 或三个 Adapter。

未取得权威 terminal 时：

- TextDelta、ToolCall delta 和 ReasoningDelta 不进入 conversation；
- display event 可以已经被消费，但 Turn 必须以 failed/cancelled 明确结束；
- 不允许用 partial delta 构造伪 `ProviderResponse`。

### 8.4 Application 请求准备与 Turn 快照

`start_turn()` 时固定：

```text
Provider
Model Ref
有序 Tool Definitions
Tool 调用安全摘要函数
CancellationToken
```

每个 iteration：

```text
captured provider identity
+ captured model ref
+ ApplicationRuntimeContext
+ current conversation
+ captured Tool Definitions
→ Application 构建 GenerationRequest
```

要求：

- System Prompt 每 iteration 由 Application 构建；
- 当前 Turn 不受中途模型切换影响；
- 模型切换只影响下一 Turn；
- Agent 请求自动注入 tools；
- raw generation 仍不自动注入 tools；
- Core 通过真实调用方使用的普通 callable 获取已准备请求，不导入 Application，不创建空 Protocol/Factory。

### 8.5 Tool 调用安全摘要

在 `application/tools.py` 为当前正式 Tool Runtime 增加一个真实调用方使用的描述能力，例如：

```python
describe_tool_call(tool_call: ToolCallPart) -> str
```

职责：

- 根据当前已注册 Tool 的 schema 与语义生成单行摘要；
- 命令型 Tool 显示命令；
- 文件型 Tool 显示操作和路径；
- 搜索型 Tool 显示 pattern 与 scope；
- 不显示待写入文件的完整 content；
- 不显示 ToolResult；
- 不显示 API key、token、环境变量值或配置秘密；
- unknown Tool 只显示 Tool 名和安全占位，不回显任意参数值；
- 使用稳定截断，默认最大 240 个 Unicode 字符；
- 失败时返回安全占位，不得影响 Tool 执行。

Core Agent Loop 通过 callable 获取该字符串并放入 Tool 事件；Interface 不读取 Tool Registry、Tool schema 或原始参数来重新生成摘要。

不得为此修改 `ToolDefinition`、`ToolCallPart` 或六个 Tool 的公共协议，除非当前真实代码证明无法在现有边界内完成；出现该情况必须停止报告。

### 8.6 Application API

`UthCodeApplication` 新增：

```python
create_run(*, run_id: str | None = None) -> AgentRun
```

`AgentRun`：

```python
start_turn(user_input: str) -> TurnHandle
snapshot() -> RunSnapshot
```

`TurnHandle`：

```python
events() -> AsyncIterator[AgentEvent]
cancel() -> bool
cancelled() -> bool
result() -> TurnResult
```

行为：

- `start_turn()` 立即占用当前 Run；
- 同 Run 活动 Turn 未结束时再次调用必须失败；
- 空白输入拒绝；
- `events()` 单消费者；
- `result()` 等待 terminal 并可重复读取同一不可变结果；
- `cancel()` 幂等；
- terminal 后释放 Run，使下一 Turn 可启动；
- 失败/取消后的下一 Turn继续沿用最后一版协议闭合的 conversation；
- TurnHandle 不公开 RunState、Provider、ToolExecutor 或 CancellationToken。

`TurnResult` 至少包含：

```text
run_id
turn_id
status
termination_reason
final_text
usage
iteration_count
tool_call_count
```

`final_text` 只在 final completed 时存在；reasoning 通过事件流消费，不重复塞入 TurnResult。

---

## 9. Agent Loop 行为规范

### 9.1 Turn 启动

1. 校验输入非空。
2. 创建新 `turn_id`。
3. 在此前权威 messages 尾部追加一个 user Message。
4. 重置 Turn 级计数、Usage、状态和终止原因。
5. 发送 `TurnStarted`。
6. 进入显式循环。

### 9.2 iteration

- iteration 定义为 Provider 调用次数。
- 每次 Provider 调用前检查预算并递增。
- Tool 调用不增加 iteration。
- 达到 `max_iterations` 后不得继续请求 Provider。
- 如果上一 iteration 已产生并闭合 ToolResult，预算耗尽时直接 `TurnFailed(max_iterations)`。

### 9.3 Provider 流

每次 Provider 调用：

1. Application 基于当前权威 conversation 构建请求。
2. 发送 `IterationStarted`。
3. 按到达顺序公开 reasoning 与 assistant 增量事件。
4. 使用共享 helper 验证唯一 terminal。
5. 只从 terminal response 读取权威 Message、Usage、FinishReason 和 ToolCall。
6. 累加 Usage 并发送 `UsageUpdated`。
7. 对 assistant message 分类。

Provider partial、缺 terminal、terminal 后事件或协议矛盾均不得进入 conversation。

### 9.4 无 ToolCall

- 正常停止：assistant message 追加到 conversation，发送 `AssistantMessageCompleted(final)`，然后 `TurnCompleted(final_answer)`。
- LENGTH/INCOMPLETE：assistant message 追加到 conversation，发送 `AssistantMessageCompleted(incomplete)`，然后 `TurnFailed(max_output_tokens)`。
- Provider error：不追加 partial assistant，发送 `TurnFailed(provider_error)`。
- 协议错误：不追加 partial assistant，发送 `TurnFailed(invalid_provider_response)`。

### 9.5 有 ToolCall

1. assistant terminal Message 先追加到 conversation。
2. 发送 `AssistantMessageCompleted(progress)`。
3. 检查单 iteration ToolCall 数量。
4. 发送 `ToolBatchStarted`。
5. 按原始顺序逐个处理。
6. 每个调用发送 `ToolStarted`，执行 `execute_call()`，随后发送 `ToolFinished`。
7. 所有结果按原序组成一个 `role=tool` Message 并追加到 conversation。
8. 发送 `ToolBatchFinished`。
9. 若未触发终止条件，进入下一 iteration。

### 9.6 Tool 数量超限

当单次 assistant response 的 ToolCall 数量大于 16：

- 整批零执行；
- 为每个 ToolCall 生成同 ID 的受控错误 ToolResult；
- 按原顺序写入一个 `role=tool` Message；
- 发送 batch 与单 Tool 的受控失败事件，但不含结果正文；
- Turn 以 `max_tool_calls` 失败；
- 不允许只执行前 16 个。

### 9.7 unknown streak

- unknown 由 `ToolRegistry` 查询结果判断，禁止匹配错误文案。
- unknown Tool 仍必须获得同 ID ToolResult。
- 连续 unknown 调用达到 3 后，在当前 batch 全部闭合后终止。
- 遇到已注册 Tool 时 streak 立即归零，无论该 Tool 最终成功还是普通执行错误。
- streak 是当前 Turn 状态，下一 Turn 重置。

### 9.8 普通 Tool 错误

以下结果默认不终止 Turn：

```text
unknown_tool（未达到 streak）
invalid_arguments
tool_error
truncated_output
```

模型通过下一次 Provider 调用读取 ToolResult 并自行纠正。

### 9.9 LENGTH/INCOMPLETE 与 ToolCall 同时出现

- 不执行任何 Tool；
- assistant terminal Message 先追加到 conversation；
- 为其中每个 ToolCall 生成同 ID 的受控未执行 ToolResult；
- 结果按原序写入一个 `role=tool` Message；
- 以 `max_output_tokens` 失败；
- 不允许在截断参数上冒险执行副作用。

### 9.10 Usage

- 只累计权威 `GenerationCompleted.response.usage`；
- partial event 不累计；
- Tool 不修改 Usage；
- Usage 按 Turn 重置；
- 每次权威增量后发送 `UsageUpdated`；
- `TurnResult.usage` 与最终 RunSnapshot 一致。

### 9.11 取消

Provider 阶段取消：

- 请求 CancellationToken；
- 丢弃 partial assistant/reasoning 对 conversation 的影响；
- 关闭 stream；
- 发送唯一 `TurnCancelled`；
- 不产生伪 completed。

Tool 阶段取消：

- 已完成 ToolResult 保留；
- 当前及剩余 ToolCall 必须得到同 ID cancelled ToolResult；
- 所有结果按原序写入一个 `role=tool` Message；
- 发送对应 ToolFinished/ToolBatchFinished；
- 不再调用 Provider；
- 发送唯一 `TurnCancelled`。

取消事件不得携带 ToolResult 正文。

### 9.12 terminal 唯一性

每个 Turn 只能产生以下之一：

```text
TurnCompleted
TurnFailed
TurnCancelled
```

terminal 后：

- 不再发送任何 AgentEvent；
- 不再修改 RunState；
- 不再执行 Tool；
- 不再调用 Provider；
- `result()` 返回固定不可变对象。

---

## 10. Interface 投影规范

### 10.1 Headless

Headless 调用方只通过：

```text
UthCodeApplication
→ AgentRun
→ TurnHandle
```

可消费完整 AgentEvent，包括 reasoning 文本和 Tool 状态，但 ToolFinished 不提供结果正文。需要直接执行 Tool 或读取完整 ToolResult 的调用方继续使用 T04 的低层 API。

### 10.2 CLI

`uthcode exec`：

- 创建独立 Application Run；
- 输入形成一个 Turn；
- reasoning delta 写 stderr；
- progress/incomplete assistant 文本写 stderr；
- ToolStarted/ToolFinished 以单行摘要写 stderr；
- ToolResult 正文不写 stdout 或 stderr；
- final answer 在 TurnCompleted 后写 stdout；
- failed 返回 1，cancelled/Ctrl+C 返回 130；
- 不加载 Textual/TUI 模块。

建议 Tool 行：

```text
• Running  <tool-name>  <command>
• Finished <tool-name>  <command>
• Failed   <tool-name>  <command>
```

不得打印 AgentEvent 字典或 JSON 作为默认用户输出。

### 10.3 TUI Run 生命周期

- TUI 启动后创建一个 AgentRun。
- 每次普通输入在同一 Run 中启动新 Turn。
- 活动 Turn 期间拒绝第二次普通输入。
- 活动 Turn 期间 `/model` 保持现有阻止语义。
- Turn 完成后模型切换只影响下一 Turn。
- `/clear` 只清理当前显示，不修改权威 Run conversation。
- TUI 退出即丢弃内存 Run。
- TUI 不保存权威 messages、Usage、iteration 或 termination reason。

### 10.4 TUI Widget 职责

`widgets.py` 应形成最小但明确的显示组件：

```text
UserMessageBlock
AgentTextBlock
ToolActivityRow
```

可使用不同命名，但职责必须保持：

#### UserMessageBlock

- 容器级背景，覆盖完整消息块；
- 具有左右内边距和上下内边距；
- 正文使用主题正常文本色；
- 不把背景只施加到 Rich Text span；
- 长文本自动换行；
- 复制文本时不混入视觉标签。

#### AgentTextBlock

- 承载 reasoning、progress 和 final 文本；
- 使用主题正常文本色；
- 不使用 dim、italic 或次要字体颜色区分 reasoning；
- reasoning 与 final 可按事件边界拆成不同 block，但文本视觉权重一致；
- 流式增量必须追加到当前正确 block，不反复创建单字符 Widget。

#### ToolActivityRow

- 只显示 status、tool name、command；
- 使用 muted/secondary 文本色；
- 不显示 ToolResult；
- 不提供展开按钮；
- 同一 tool_call_id 的 started/finished 应更新同一行，或以稳定成对行显示；
- command 过长时使用 Application 已截断的安全摘要，不在 TUI 二次读取原始参数。

### 10.5 TUI rendering/state

`rendering.py`：

- 只消费 AgentEvent；
- 维护 `tool_call_id → ToolActivityRow` 的显示映射；
- 按事件顺序创建/更新用户、Agent、Tool 显示；
- reasoning delta 直接追加到 Agent 正文块；
- 不接触 ProviderEvent、ProviderPort、ToolRegistry、ToolExecutor 或 RunState。

`state.py`：

- 只保存界面显示状态，例如活动 Turn、当前 block 标识、Tool row 映射、取消状态；
- 不保存权威 conversation；
- 不保存 ToolResult 正文；
- 不复制 RunState；
- 不保存 Provider native item。

`app.py`：

- 负责 Run/Turn 生命周期和事件消费；
- 保持现有 Slash Command、滚动、Composer、模型 Picker、状态栏与双 Esc 取消；
- 不把 ReAct 逻辑写入 UI handler；
- 不直接调用 Provider 或 Tool。

### 10.6 TUI CSS 验收语义

必须通过 Textual CSS 或现有 theme token 实现：

```text
.user-message-block
  width: 100%
  background: theme surface/panel token
  padding: 非零

.agent-text-block
  color: theme normal text token
  text-style: none

.reasoning-text
  color: 与 agent-text-block 相同
  text-style: none

.tool-activity-row
  color: theme muted/secondary token
```

实际 selector 名可不同，但测试和人工验收必须确认：

- 用户消息整块背景真实覆盖容器；
- Agent reasoning 与 final 不是灰色；
- Tool 活动比正文更弱；
- ToolResult 正文完全不可见；
- 主题切换后仍使用语义 token，不出现硬编码导致的不可读配色。

---

## 11. 文件级修改要求

| 文件 | 动作 | 职责 | 禁止 |
| --- | --- | --- | --- |
| `core/agent.py` | 新增 | policy、State、Snapshot、Result、显式 Loop | SDK/UI/Application 类型 |
| `core/agent_events.py` | 新增 | frozen、JSON-safe AgentEvent，含 reasoning 文本与安全 Tool 摘要 | SDK/UI/Path/Exception/native payload |
| `core/provider.py` | 修改 | 提取共享 Provider stream 终态校验 | 修改 DTO/Adapter 行为 |
| `core/__init__.py` | 修改 | 只导出真实公共 Agent 类型 | Registry/Executor/SDK 越界导出 |
| `application/runs.py` | 新增 | AgentRun、TurnHandle、Run 生命周期 | UI、SDK 细节、State mutation |
| `application/generation.py` | 修改 | 复用共享校验、抽取请求准备 | 第二套 Loop |
| `application/tools.py` | 修改 | 复用同一 Registry/Executor；生成安全 Tool 调用摘要 | 暴露 Registry/Executor/ToolResult 到 Interface |
| `application/bootstrap.py` | 修改 | 组装 Run 所需真实依赖 | Service Locator/未来占位 |
| `application/__init__.py` | 修改 | 导出 Application Agent API | 导出 Core 内部 State |
| `interfaces/cli.py` | 修改 | exec 走 Run/Turn；stdout/stderr 分流 | Core/Integration import、ToolResult 输出 |
| `tui/app.py` | 修改 | 一个内存 Run、多 Turn、TurnHandle 取消 | RunState 所有权、Provider 直连 |
| `tui/rendering.py` | 修改 | AgentEvent → User/Agent/Tool 投影 | ProviderEvent、原始 Tool 参数解析 |
| `tui/state.py` | 修改 | 仅保存显示状态 | conversation/usage/ToolResult 权威状态 |
| `tui/widgets.py` | 修改 | 用户背景块、Agent 正文块、Tool 浅色活动行 | ToolResult 展开、大型时间线框架 |
| `test_agent_policy.py` | 新增 | 默认值、非法值、冻结、安全 Snapshot | 私有 helper 替代正式 contract |
| `test_agent_events.py` | 新增 | 序列化、reasoning、Tool 摘要、关联 ID、非法 payload | SDK/UI fixture |
| `test_agent_loop.py` | 新增 | 完整 ReAct、限制、错误、取消、Usage、顺序 | Interface helper |
| `test_application_runs.py` | 新增 | Run/Turn、Prompt、快照、隔离、Headless E2E | Interface |
| 既有 application/provider tests | 修改 | raw API 与前置能力回归 | 改写已验收语义 |
| `test_cli.py` | 修改 | stdout/stderr、reasoning、Tool、失败、取消、exit code | Core direct import |
| `test_tui.py` | 修改 | 多 Turn、视觉层级、reasoning、Tool 隐藏结果、Esc、Slash | Core direct import |
| `test_architecture_boundaries.py` | 修改 | 放行 Agent 文件，继续禁止 runtime/graph/后置能力 | 白名单逃逸 |
| `test_package.py` | 修改 | 导出与无副作用 import | 公开 Registry/Executor/SDK |
| `README.md` | 修改 | Agent API、低层 API 区别、CLI、TUI、Reasoning、Bash 边界 | 后置能力承诺 |

默认不修改：

```text
integrations/providers/*
integrations/tools/*
application/configuration.py
application/commands/*
core/prompt.py
pyproject.toml
```

如必须修改 Provider DTO、Tool DTO/Protocol、六个内置 Tool、配置格式、System Prompt 正文或 Slash Command 公共协议，停止并请求批准。

---

## 12. 依赖与数据流

```text
interfaces
    │
    ▼
application.runs / generation / tools
    │
    ├────────► core.agent
    │            ├── core.provider
    │            ├── core.tool
    │            └── core.agent_events
    │
    └────────► integrations.providers / tools
```

禁止：

```text
core → application/integrations/interfaces
interfaces → core/integrations
integrations → application/interfaces
```

所有权：

```text
AgentLoop
→ 创建下一版 RunState
→ AgentTurnExecution 产生 Event/TurnResult
→ AgentRun 私有保存返回的 State 引用
→ RunSnapshot 为 Core 生成的安全只读投影
→ Interface 只消费 AgentEvent
```

Tool：

```text
ApplicationToolService 的同一 Registry/Executor
→ describe_tool_call() 生成显示摘要
→ AgentLoop 逐个 execute_call()
→ ToolResultPart 写回 conversation
→ Interface 只看到 Tool 生命周期与显示摘要
```

不得创建第二 Registry/Executor 或向 Interface 暴露它们。

---

## 13. 第三方依赖

不新增 Agent Runtime 依赖。现有 Python 3.12 stdlib、Provider SDK、jsonschema、Textual、TOMLKit、pytest 足够。

禁止新增 LangGraph、LangChain Agent、工作流/DAG 库、第三方 ReAct、Session 或 Checkpoint 框架。

---

## 14. 实施任务

每个 Task 单独提交、测试、审查、回退。

### Task 1：Agent policy、State 与 Event contract

文件：

```text
新增 core/agent.py、core/agent_events.py
新增 test_agent_policy.py、test_agent_events.py
修改 core/__init__.py、test_package.py
```

完成：

- policy 默认值与校验；
- frozen RunState/RunSnapshot/TurnResult；
- 完整 AgentEvent；
- reasoning lifecycle + delta；
- ToolStarted/Finished 的安全显示字段；
- JSON round-trip 和非法 payload 拒绝。

不得调用 Provider/Tool。

```bash
pytest -q tests/test_agent_policy.py tests/test_agent_events.py tests/test_package.py
```

### Task 2：共享 Provider 校验与 Core Agent Loop

文件：

```text
修改 core/provider.py、core/agent.py
修改 test_provider_contract.py
新增/完善 test_agent_loop.py
```

完成唯一显式 Loop、Provider terminal 复用、reasoning event、FIFO、限制、Usage、错误与取消。不得修改 Provider DTO 或 Adapter。

```bash
pytest -q \
  tests/test_provider_contract.py \
  tests/test_agent_policy.py \
  tests/test_agent_events.py \
  tests/test_agent_loop.py \
  tests/test_tool_core.py
```

### Task 3：Application Run/Turn 与 Tool 摘要

文件：

```text
新增 application/runs.py、test_application_runs.py
修改 generation.py、tools.py、bootstrap.py、application/__init__.py
修改 test_application.py、test_application_tools.py、test_package.py
```

完成：

- create_run、AgentRun、TurnHandle；
- 请求准备；
- Provider/Model/Tool 快照；
- 多 Turn；
- Tool 调用安全摘要；
- raw API 保留。

```bash
pytest -q \
  tests/test_application.py \
  tests/test_application_tools.py \
  tests/test_application_runs.py \
  tests/test_package.py
```

### Task 4：Headless 端到端

正式入口：

```text
create_application(temp_workdir)
→ create_run()
→ start_turn()
→ Fake Provider 返回只读 ToolCall
→ 真实 Integration Tool
→ 自动回填
→ final
```

测试必须同时证明：

- reasoning 文本按事件公开；
- ToolStarted 含安全摘要；
- ToolFinished 不含 ToolResult 正文；
- ToolResult 实际写入下一次 Provider 请求；
- TurnResult 只提供 final 与统计。

修改 `test_application_runs.py`、`test_agent_loop.py` 和 README Headless 示例。不得使用真实 Provider。

```bash
pytest -q tests/test_agent_loop.py tests/test_application_runs.py
```

### Task 5：CLI AgentEvent 投影

修改 `interfaces/cli.py`、`test_cli.py`：

- exec 创建 Run/Turn；
- reasoning → stderr；
- progress/incomplete → stderr；
- Tool name + command summary → stderr；
- ToolResult 正文不输出；
- final → stdout；
- 保持配置错误与退出码；
- exec 不导入 TUI/Textual。

```bash
pytest -q tests/test_cli.py
```

### Task 6：TUI 活动流与视觉层级

修改：

```text
tui/app.py
tui/rendering.py
tui/state.py
tui/widgets.py
test_tui.py
```

完成：

- 一个内存 Run、多 Turn；
- 用户消息整块背景；
- Agent reasoning 和 final 使用正常正文色；
- Tool 活动使用低强调度浅色；
- 只显示 Tool 名和安全命令/参数摘要；
- ToolResult 正文不可见且无展开入口；
- started/finished 状态更新；
- 双 Esc 取消；
- 保持 Slash Command、滚动、Composer 和模型 Picker。

不得把视觉改造扩张为新的通用 UI 框架。

```bash
pytest -q tests/test_tui.py
```

### Task 7：[接入主流程]

建立唯一正式 Agent 路径：

```text
Headless / CLI / TUI
→ Application Run/Turn
→ Core AgentLoop
```

删除 Interface 的 ProviderEvent 普通输入路径，保留低层 Generation/Tool API。

修改架构测试、包测试和 README。

```bash
pytest -q \
  tests/test_application_runs.py \
  tests/test_cli.py \
  tests/test_tui.py \
  tests/test_architecture_boundaries.py \
  tests/test_package.py
```

### Task 8：[端到端验证]

```bash
python -m compileall -q src tests

pytest -q \
  tests/test_agent_policy.py \
  tests/test_agent_events.py \
  tests/test_agent_loop.py \
  tests/test_application_runs.py

pytest -q \
  tests/test_application.py \
  tests/test_application_tools.py \
  tests/test_cli.py \
  tests/test_tui.py

pytest -q \
  tests/test_provider_contract.py \
  tests/test_anthropic_integration.py \
  tests/test_openai_responses_integration.py \
  tests/test_openai_compat_integration.py

pytest -q tests/test_architecture_boundaries.py tests/test_package.py

pytest -q
python -m pip check
git diff --check
```

live Provider 用例继续保持显式授权门禁。

### Task 9：[遗留负担清理]

必须删除：

- Interface 直接消费 ProviderEvent 的普通输入路径；
- 第二套自动 Loop；
- 无调用方旧 renderer；
- 仅服务旧单轮 TUI 的 message widget/state；
- ToolResult 正文展示入口；
- Interface 解析原始 Tool 参数的逻辑；
- 兼容 alias；
- 后续能力占位；
- MewCode/旧 UthCode runtime import；
- SDK 类型越界；
- Application 对 Registry/Executor 的公共导出。

扫描：

```bash
rg -n "from mewcode|import mewcode|langgraph|langchain" src tests README.md
rg -n "StateGraph|GraphState|checkpoint|ConversationManager" src tests
rg -n "uthcode\.core|uthcode\.integrations" src/uthcode/interfaces
rg -n "uthcode\.application|uthcode\.interfaces" src/uthcode/integrations
rg -n "ProviderEvent" src/uthcode/interfaces
rg -n "tool_result|ToolResultPart" src/uthcode/interfaces/tui
rg -n "asyncio\.gather|TaskGroup" src/uthcode/core/agent.py
```

否定性架构测试中的关键词可运行时拼接，避免扫描自命中。不得移动或归档工作包。

---

## 15. 测试矩阵

### 15.1 Core policy/state

- 默认值 50/16/3；
- 非法零值、负值和 bool 值拒绝；
- State/Snapshot/Result frozen；
- 新 Turn 保留 messages、重置 Turn 计数；
- Snapshot 不含 conversation 或 native payload。

### 15.2 AgentEvent

- 所有 event JSON-safe；
- run/turn/message/batch/tool ID 关联正确；
- reasoning started/delta/finished 顺序；
- 多 reasoning 段顺序；
- 无 reasoning Provider 不产生伪文本；
- ToolStarted/Finished 含相同安全 command；
- ToolFinished 不含结果正文；
- SDK、Exception、Path、bytes、native payload 拒绝；
- 每 Turn 唯一 terminal。

### 15.3 Agent Loop

- 普通问答；
- reasoning + final；
- reasoning + Tool + final；
- 单 Tool；
- 多 Tool FIFO；
- 多步 Loop；
- Tool 普通错误后继续；
- unknown streak 与 known reset；
- ToolCall 超限整批零执行；
- max iterations；
- LENGTH/INCOMPLETE；
- ProviderError；
- 无 terminal；
- terminal 后事件；
- 协议矛盾；
- Provider 阶段取消；
- 首个/中间 Tool 取消；
- 结果 ID、数量、顺序闭合；
- Usage 累计；
- 失败/取消后下一 Turn 可继续。

### 15.4 Application

- 每 iteration System Prompt 由 Application 准备；
- Agent 请求自动注入 tools；
- raw generation 仍不自动注入；
- Provider/Model 快照只影响当前 Turn；
- 同 Run 多 Turn 保留 conversation；
- 不同 Run 的 Agent state 隔离；
- 同一 Application 共享 T04 Tool Runtime，不同 Application 隔离；
- Tool 摘要不包含写入正文、秘密或任意 unknown 参数值；
- 摘要稳定截断；
- 摘要生成失败不影响 Tool 执行；
- Headless 不导入 Interface。

### 15.5 CLI

- final 只进 stdout；
- reasoning 进 stderr；
- progress/incomplete 进 stderr；
- Tool 活动只含 name + command summary；
- ToolResult 正文不输出；
- failed=1；
- cancelled=130；
- stdout 无事件字典或内部诊断；
- stdin `/help` 仍是普通 Prompt；
- exec 不加载 TUI。

### 15.6 TUI 功能

- 普通输入走 AgentRun；
- 第二 Turn 带第一 Turn conversation；
- 活动 Turn 拒绝第二输入；
- 双 Esc 取消；
- 活动 Turn 阻止 `/model`；
- 完成后切换模型影响下一 Turn；
- Slash Command 回归；
- `/clear` 只清显示，不修改 Run conversation；
- TUI 不接触 RunState。

### 15.7 TUI 视觉与内容

- 用户消息 Widget 是容器级背景，不是 Text span 背景；
- 用户消息背景覆盖整块可用宽度或定义的完整消息容器宽度；
- 用户正文使用正常文本色；
- Agent reasoning 使用正常文本色；
- Agent final 使用正常文本色；
- reasoning 不含 dim/italic 样式；
- Tool 活动使用 muted/secondary 色；
- Tool 行展示 status、name、command；
- ToolResult 正文不出现在 DOM、render tree 或 snapshot；
- Tool 活动无展开按钮；
- 长 command 已在 Application 截断，TUI 不二次读取原始参数；
- 流式 reasoning 不产生每字符 Widget；
- 滚动位置、Composer、状态栏不回归。

### 15.8 真正端到端

Headless：

```text
user
→ reasoning event
→ Fake Provider ToolCall
→ temp-workdir 真实只读 Tool
→ ToolResult 自动回填
→ final
→ TurnCompleted
```

Interface：

```text
uthcode exec
→ Application Run/Turn
→ 多步 Fake Provider
→ reasoning stderr
→ Tool name/command stderr
→ Tool 自动执行并隐藏结果正文
→ final stdout
→ exit 0
```

TUI：

```text
用户消息背景块
→ reasoning 正文
→ 浅色 Tool running/finished 行
→ 不出现 ToolResult 正文
→ final 正文
```

不得直接调用私有 helper 代替正式入口。

---

## 16. 删除与清理边界

必须替换：

- CLI/TUI 普通输入的 GenerationHandle 路径；
- TUI ProviderEvent renderer；
- 旧用户/Agent 消息无层级展示结构；
- ToolResult 正文展示结构；
- 仅服务旧单轮 Interface 的测试断言。

必须保留：

```text
start_generation()
stream_generation()
tool_definitions()
execute_tool_calls()
Provider DTO 与三个 Adapter
Tool Registry/Executor 与六个 Tool
System Prompt 正文
Slash Command
配置与模型选择
```

不得保留旧 Interface 自动路径的 Adapter、Facade、Shim 或 deprecated alias。

---

## 17. 验收标准

1. 普通问答与多步 Tool 任务通过同一 Application Agent API。
2. 同一 Run 多 Turn 保留权威 conversation；不同 Run 的 Agent state 隔离。
3. Provider 调用次数等于 iteration；Tool 不增加 iteration。
4. Tool 严格 FIFO，无并行执行窗口。
5. 所有 ToolCall 在正常、错误、unknown、超限、截断、取消路径均有同 ID 结果。
6. 同批结果按原序写入一个 tool Message。
7. 普通 Tool 错误可继续 Loop。
8. 50/16/3 与截断均受控停止。
9. Agent Loop 是 RunState 唯一写入者；公开 Snapshot 不泄露 conversation/native payload。
10. 每 Turn 恰有一个终态事件。
11. Provider partial stream 不进入权威 conversation。
12. Usage 只累计权威 terminal，并按 Turn 重置。
13. Provider、Model Ref、Tool Definitions 和 Tool 摘要函数在 Turn 开始时固定。
14. System Prompt 每 iteration 仍由 Application 构建。
15. AgentEvent frozen、JSON-safe、无 SDK、配置秘密和 native payload。
16. Provider reasoning 文本按事件公开；无 reasoning 时不伪造。
17. `exec` stdout 只含 final；reasoning、progress 和 Tool 活动进入 stderr。
18. CLI/TUI 均不展示 ToolResult 正文。
19. TUI 用户消息具有整块背景，Agent reasoning/final 使用正常正文色，Tool 活动使用浅色次要样式。
20. TUI 支持多 Turn、Tool 状态、双 Esc，且不拥有 RunState。
21. Headless 不导入 Interface。
22. raw Generation/Tool API 保留但不形成第二 Loop。
23. 无 LangGraph、Graph、Runtime 大对象或工作流框架。
24. 无 Permission、Context、Memory、Session、Journal、Diff 等后置能力偷跑。
25. 三 Provider、Tool、配置、Prompt、模型切换、Slash Command 回归通过。
26. 编译、全量测试、pip check、diff check 全部通过。
27. 未授权 live Provider 测试继续 skip。

---

## 18. 编码停止条件

出现以下情况停止并报告：

- HEAD 或基线测试与记录实质不一致；
- 与全局约束或本任务冻结决策冲突；
- 必须修改 Provider DTO、Tool DTO/Protocol、默认 Tool、配置格式、Prompt 正文或 Slash Command 公共协议；
- 必须让 Core 依赖 Application/Integration/Interface；
- 必须让 Interface 直连 Core/Integration；
- 必须引入 LangGraph、工作流框架或兼容层；
- 必须扩大到 Permission、Context、Session、Journal、Diff、持久化；
- 必须创建第二套自动 Loop；
- Tool 副作用是否发生无法确认；
- 取消后无法闭合全部 ToolCall；
- Provider 协议矛盾无法安全映射；
- Tool 调用摘要无法在不泄露内容的前提下生成，且必须修改 T04 公共协议才能继续；
- 实际文件范围明显超出任务书；
- 未授权真实 Provider 请求、费用或不可逆外部副作用。

普通编译错误、测试失败和局部实现缺陷应在范围内自行修复。

---

## 19. 完成反馈要求

Feedback 应说明：

- 实际 Agent 调用链；
- Run/Turn、Provider snapshot、State/Event；
- reasoning 事件公开方式；
- Tool FIFO、协议闭合、显示摘要、限制、Usage 与取消；
- CLI stdout/stderr 行为；
- TUI 用户消息背景、Agent 正文和 Tool 活动的实际实现；
- ToolResult 正文隐藏验证；
- 修改、新增、删除文件；
- 每个 Task 的测试结果；
- 全量测试、依赖和 diff 检查；
- 与任务书不同的实际情况；
- 未完成项、风险或待决问题；
- 双路径、兼容层、旧 renderer、未来占位和旧项目依赖清理结果。

不得用大段源码替代机制说明，不得声称实现 Permission、Sandbox、Session、Context、Memory 或其他未交付能力，不得自行归档 T04/T05。
