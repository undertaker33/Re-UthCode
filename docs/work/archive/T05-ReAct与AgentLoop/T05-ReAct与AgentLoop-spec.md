# T05 ReAct 与 Agent Loop Spec

## 背景

Re:UthCode 已具备 Provider 抽象、统一请求与响应模型、System Prompt、六个基础 Tool、配置系统、Headless Application、CLI 和简单 Textual TUI，但普通输入仍停留在单轮 Provider 调用。Tool 调用需要 Headless 调用方手工执行和回填，CLI/TUI 直接消费 Provider 事件，尚无统一的多步 Agent 运行语义。

本工作包在 T04 完成基线上建立唯一的显式 ReAct Agent Loop。旧 UthCode 与 MewCode 只用于提取 ToolCall/ToolResult 闭合、循环限制、Usage、取消和活动流教训；不迁移 LangGraph、旧 Runtime、可变 Conversation Manager、并行工具、Permission、Session、恢复或其他后置能力。

## 目标

- 建立 Provider 无关、无界面、可嵌入测试的显式 Agent Loop。
- 由 Core 独占权威运行状态、终止策略、工具批次语义和统一 Agent 事件。
- 支持一个内存 Run 中的多个 Turn，并保证不同 Run 相互隔离。
- 自动完成 assistant ToolCall、FIFO ToolResult 和下一次 Provider 请求之间的闭环。
- 对正常、错误、未知工具、限制、截断和取消路径保持协议闭合。
- 让 Headless、CLI 和 TUI 通过同一 Application Run/Turn API 消费统一 Agent 事件。
- 公开 Provider 实际提供的 reasoning 文本，但不把增量流当作权威会话。
- 只向 Interface 展示 Tool 生命周期和安全摘要，不展示 ToolResult 正文。
- 重建 TUI 中用户消息、Agent 正文和 Tool 活动的视觉层级。
- 删除 CLI/TUI 普通输入直连 Provider 事件的旧路径，同时保留低层单轮 Generation 与手动 Tool API。

## 能力清单

### Task 1：Agent policy、State 与统一事件契约

- 定义不可变的循环策略、权威运行状态、安全快照和 Turn 结果。
- 定义冻结、可序列化、无 SDK/UI/native payload 的统一 Agent 事件。
- 覆盖 Turn、iteration、reasoning、assistant、Usage、Tool batch、Tool 和唯一终态生命周期。
- Snapshot 只公开安全计数和状态，不公开 conversation 正文。

### Task 2：Provider 权威流与显式 Agent Loop

- 抽取低层 Generation 与 Agent Loop 共用的 Provider 流终态校验。
- 实现集中、顺序可读的显式异步循环，不引入 Graph、节点、路由或工作流框架。
- 只以 Provider 权威终态更新 conversation 和 Usage。
- 自动注入当前 Tool definitions，严格 FIFO 执行，并闭合每个 ToolCall。
- 实现 iteration、单响应工具数、连续未知工具、截断、错误和取消控制。
- Provider 协议差异在对应 Integration 中分别归一，Core 不按 Provider 名称分支。

### Task 3：Application Run/Turn 与安全 Tool 摘要

- Application 创建相互隔离的内存 Run，并为每个 Turn 固定 Provider、模型、Tool definitions 和摘要能力。
- 同一 Run 的后续 Turn 自动携带此前权威 conversation。
- 同一 Run 同时最多一个活动 Turn；终态后可继续下一 Turn。
- Turn 句柄提供单消费者事件流、幂等取消、异步结果等待和安全快照。
- Tool 摘要由 Application 基于当前正式 Tool Runtime 生成，Interface 不解析原始参数。
- 低层 Generation 和手动 Tool API 保持独立、可用，但不形成第二套自动 Loop。

### Task 4：Headless Agent 端到端闭环

- 从正式 Application 入口完成 reasoning、只读 ToolCall、真实 Integration Tool、自动结果回填和 final 的离线闭环。
- 证明 ToolResult 进入下一次 Provider 请求，但不进入 AgentEvent 或 TurnResult 正文。
- 证明同一 Run 多 Turn 保留权威历史，不同 Run 状态隔离。
- README 提供正式 Headless Agent API，并区分自动 Run/Turn 与低层单轮 API。

### Task 5：CLI AgentEvent 投影

- `uthcode exec` 通过独立 Run/Turn 执行。
- final answer 只输出到 stdout。
- reasoning、progress、incomplete、Tool 活动、失败和取消输出到 stderr。
- Tool 活动只显示状态、名称和安全摘要，不显示 ToolResult。
- 保持参数、配置、stdin、退出码和不加载 Textual 的既有行为。

### Task 6：TUI 活动流与视觉层级

- TUI 生命周期内使用一个内存 Run，普通输入形成多个 Turn。
- TUI 只消费 AgentEvent，并只保存界面投影状态。
- 用户消息使用完整背景块；Agent reasoning 与 final 使用正常正文色；Tool 活动使用低强调度样式。
- Tool 行只展示状态、名称和安全摘要，不提供结果展开入口。
- 保持 Slash Command、Completion、模型 Picker、滚动保护、Composer 和双 Esc 取消。
- `/clear` 只清显示，不修改 Run conversation。

### Task 7：[接入主流程] 统一正式 Agent 路径

- Headless、CLI 和 TUI 的普通 Agent 输入统一进入 Application Run/Turn，再进入唯一 Core Agent Loop。
- 删除 Interface 直接消费 ProviderEvent 的普通输入路径和仅服务旧单轮 TUI 的投影结构。
- 保留低层 Generation/Tool API 及其现有调用方。
- 更新公开导出、架构门禁和 README，使正式路径唯一且可发现。

### Task 8：[端到端验证] 全链路与回归验证

- 验证普通问答、多步 Tool、reasoning、限制、错误、取消、多 Turn 和唯一终态。
- 分别验证 Anthropic、OpenAI Responses 和 OpenAI-compatible Integration 对各自协议的归一结果。
- 验证 CLI stdout/stderr 和 TUI 视觉、内容隐藏、取消、Slash Command 与模型切换。
- 完成编译、分层测试、全量测试、依赖完整性和差异检查。
- 未授权 live Provider 测试继续保持跳过。

### Task 9：[遗留负担清理] 删除旧路径与重复职责

- 删除 Interface 普通输入的 ProviderEvent 路径、旧 renderer 和旧单轮显示状态。
- 删除 ToolResult 展示入口、Interface 原始参数解析、兼容别名、重复 Loop 和不可达代码。
- 确认不存在旧项目 Runtime、LangGraph/LangChain、SDK 越界和未来能力占位。
- 确认 Application 不公开 Registry、Executor、RunState 或 Provider 内部对象。

## 非功能要求

- 依赖方向保持 `interfaces → application → core`，Application 组合根可装配 Integration。
- Core 不依赖 Application、Integration、Interface、Provider SDK、Textual、文件存储或进程实现。
- Interface 不直连 Core 或 Integration，只依赖 Application 公共 API。
- Agent Loop 是权威 RunState 的唯一写入者；其他组件只能返回结果或事件。
- Provider partial stream 不进入权威 conversation；只有合法唯一终态可以提交状态。
- Tool batch 严格 FIFO，不使用并行执行原语。
- 每个 ToolCall 在成功、普通错误、未知、限制、截断和取消路径均得到同 ID 结果。
- AgentEvent、Snapshot 和 TurnResult 必须冻结、JSON-safe，并避免秘密、绝对内部路径、异常对象和 native payload。
- Provider 协议差异由三个 Integration 各自适配为统一 Core 模型，Agent Loop 中不得出现 Provider 名称分支。
- TUI 使用 Textual 主题语义 token，不硬编码只适用于单一主题的颜色。
- Bash 继续是当前操作系统用户权限下的 unsandboxed process execution，不得描述为 Sandbox。
- 不新增 Agent Runtime 第三方依赖，不自制工作流框架或通用事件总线。
- 不保留为了兼容旧 UthCode、MewCode 或 Re:UthCode 早期实现而存在的适配层。

## 设计骨架

```text
Headless / CLI / TUI
          │
          ▼
Application Run / Turn
          │
          ├── 固定当前 Provider 与模型
          ├── 准备每次 Provider 请求
          ├── 固定有序 Tool definitions
          └── 生成安全 Tool 摘要
          │
          ▼
Core explicit Agent Loop
          │
          ├── 创建下一版不可变 RunState
          ├── 校验 Provider 权威终态
          ├── 严格 FIFO 执行 Tool
          └── 产生统一 AgentEvent
          │
          ▼
Turn result / safe snapshot
```

三个 Provider Integration 分别解释自己的线协议并转换为同一 Provider DTO。Agent Loop 只处理统一 finish reason、assistant message、ToolCall、Usage、Provider error 与取消，不感知具体厂商。

Run 在 Application 内存中私有持有 Core 返回的最新状态引用。Turn 启动时立即占用 Run；实际执行由首次异步消费事件或等待结果触发，并由事件流与结果等待共享唯一生产过程。TUI 只维护显示块、Tool 行映射、滚动和取消提示，不复制权威状态。

## Out of Scope

- Permission、审批、Pending Permission 或权限规则。
- OS Sandbox、命令黑名单、工作区副作用扫描。
- Journal、Checkpoint、持久 Snapshot、Interrupt/Resume 框架。
- 完整 Session、Run 历史、恢复、重命名、删除或浏览。
- Context Compiler、Context Budget、压缩、Memory 或 Dream。
- Workspace Diff、Diff Viewer、Artifact 仓库或跨 Run 大输出存储。
- Hook、Skill、MCP、Worktree、Subagent 或 Multi-Agent。
- Tool 并行、通用任务调度、DAG 或工作流 DSL。
- Web、Desktop、IDE 或大型 TUI 框架。
- Provider DTO、Tool DTO、六个内置 Tool、配置格式、System Prompt 正文和 Slash Command 公共协议重设计。
- 旧类、旧 API、旧数据结构、兼容层、Facade、Shim 或双 Runtime。

## 验收标准

- 普通问答和多步 Tool 任务通过同一 Application Agent API 完成。
- 同一 Run 多 Turn 保留权威 conversation，不同 Run 状态隔离。
- Provider 调用次数等于 iteration 数，Tool 执行不增加 iteration。
- Tool 严格 FIFO，所有调用在所有受控终止路径均按原序闭合。
- 普通 Tool 错误可由下一次 Provider 调用读取并纠正，不默认使 Run 崩溃。
- 循环、工具数量、未知工具和输出长度限制均产生受控唯一终态。
- RunState 只有 Agent Loop 能创建下一版；公开 Snapshot 不泄露 conversation 或 native payload。
- 每个 Turn 恰有一个 completed、failed 或 cancelled 终态。
- Provider partial stream 不写入权威 conversation，Usage 只累计合法终态。
- 三个 Provider 协议分别在 Integration 测试中完成正确归一，Core Agent Loop 无厂商分支。
- reasoning 按 Provider 实际内容和顺序公开；Provider 未提供时不伪造。
- Tool 活动包含安全摘要，CLI/TUI 均不展示 ToolResult 正文。
- CLI stdout 只含 final answer，其他活动进入 stderr，退出码保持稳定。
- TUI 支持多 Turn、Tool 状态、用户背景块、正常 Agent 正文色、低强调 Tool 行和双 Esc 取消。
- Headless 不导入 Interface；Interface 不导入 Core/Integration。
- 低层 Generation/Tool API 继续可用，但不存在第二套自动 Agent Loop。
- 无 LangGraph、Graph Runtime、兼容层、旧 renderer、重复职责或后置能力占位。
- 编译、全部离线测试、依赖检查、架构扫描和差异检查通过；未授权 live 测试继续跳过。
