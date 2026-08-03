# SRe-AGENTS.md

## 1. 仓库策略

- 在独立空仓 Re-UthCode 中从零实现新版。
- 旧 UthCode 仓库保持只读，仅作为任务书、源码、测试和历史经验参考。
- 新旧仓不共享 Git 历史、分支和远端；新版不合并回旧仓 main。
- 正式项目名、Python 包名和 CLI 仍为 UthCode / uthcode，不使用长期 v2 命名。

## 2. 重做定位

- 保留原 Day1—Day5 已确认的产品目标、行为要求和验收场景。
- 废弃现有 Day1—Day5 代码结构和 LangGraph Runtime。
- 旧代码不是迁移对象，不做逐文件映射，不整文件照搬。
- 不兼容旧 API、类、函数、模块路径、状态结构和输出格式。
- 禁止长期 Adapter、Facade、新旧双实现和双 Runtime。

## 3. 实施方式

- 按原 Day1—Day5 逐日或按单一批次重新设计、实现、测试和审查。
- 一份任务书可以描述完整目标，但编码代理一次只实施用户明确指定的 Day/批次。
- 每个批次必须可运行、可测试、可审查、可回退。
- 不提前创建未来 Day 的目录、协议、服务或占位实现。
- Agent Loop 完成后优先交给用户审查；未审查前不得擅自改变核心语义。

## 4. LangGraph

- 完全脱离 LangGraph 和 LangChain Agent。
- 不保留 StateGraph、Node、Edge、Reducer、Checkpoint、Interrupt/Resume 等框架结构。
- 不自行实现通用图框架、工作流 DSL、DAG 调度器或“小型 LangGraph”。
- Runtime 使用面向 Coding Agent 的显式、集中、可顺序阅读的 Agent Loop。

## 5. Agent Core

- UthCode 首先是完全无界面、可嵌入、可独立测试的 Agent Core。
- Core 不读取 stdin、不写 stdout，不依赖 Textual、HTTP、Electron 或其他交互技术。
- Core 通过 Application Command 接收操作，通过统一 Agent Event 输出状态。
- TUI、CLI、Web、桌面客户端、IDE 插件和 Headless Driver 都是独立 Interface Adapter。
- 删除或替换任意交互层，不得修改 Agent Loop、Provider、Tool、Permission 和运行状态语义。
- 移除 interfaces 后，Headless 测试仍必须能够完整运行 Agent Core。

## 6. 当前交互层

- 当前实现一个克制的简单 TUI，作为 Agent Core 的参考交互适配器。
- 简单 TUI 只负责输入、事件渲染、Tool 状态、权限确认、取消和恢复。
- TUI 不拥有 RunState，不直接访问 Provider、Tool Registry、Permission Store 或持久化实现。
- 文件树、Diff Viewer、多会话、主题、Web、Desktop 和正式完整 TUI 后置。

## 7. 当前范围

- Provider 抽象。
- System Prompt。
- Tool 系统。
- 显式 ReAct Agent Loop。
- Permission 系统。
- 为上述链路必需的最小 Run/Turn、事件、错误、取消和终态语义。
- 必需时实现最小 Journal、Snapshot、Pending Permission 和 Run-local 大输出引用。

## 8. 明确后置

- 完整 Context、Context Compiler、Context Budget 和结构化压缩。
- Memory、Dream、完整 Session 产品和历史浏览。
- OS Sandbox。
- Slash Command、Hook、Skill、MCP、Worktree。
- Subagent、Multi-Agent。
- Web、桌面客户端、正式完整 TUI。
- Artifact 系统、跨 Run 内容仓库、全局去重和 GC。
- 通用任务调度和工作流引擎。

## 9. Provider

- Provider SDK 类型只能存在于 Integration Adapter。
- Core 使用 UthCode 自有的统一请求、响应、流事件、ToolCall、Usage、错误和取消模型。
- Runtime 中禁止按 Provider 名称写分支。
- 先用 Fake Provider 和一个真实 Provider 打通链路，再按实际需求补齐其他 Provider。
- 通用 SDK、HTTP、校验和重试能力优先使用成熟库。

## 10. Tool 与 Agent Loop

- Tool Batch 严格 FIFO，不并行执行有副作用的 Tool。
- 每个 ToolCall 都必须得到对应 ToolResult。
- 单个 Tool 被拒绝或发生普通执行错误，不应直接导致整个 Run 崩溃。
- Agent Loop 是 RunState 的唯一写入者。
- Tool、Provider、Permission、Storage 和 Interface 只能返回结果或事件，不能直接修改 RunState。
- 普通 Bash 执行是当前用户权限下的 unsandboxed process execution，不得描述为 Sandbox。

## 11. Permission

- 权限模式为 default、auto、full_access。
- full_access 是用户明确启用的完全应用层访问模式。
- full_access 下跳过 Project/Local/User 规则、普通危险动作检查和人工审批。
- full_access 仍受 Tool 注册、参数校验、操作系统当前用户权限、第三方权限和普通执行错误约束。
- Permission Approval 不等于 OS Sandbox。
- 项目配置不得静默启用 full_access。
- 支持 Allow、Deny、Ask，以及精确动作、有界类似动作和持久 exact 决定。
- Permission Ask 必须能够暂停；拒绝后 Agent Loop 可以继续。

## 12. 配置

- 用户级配置：~/.uthcode/config.toml。
- 项目级配置：<workdir>/.uthcode/config.toml。
- 普通配置按“默认值 → 用户配置 → 项目配置”合并。
- 项目配置只能覆盖允许字段或收紧权限，不能修改秘密来源或提升到 full_access。
- API key 真实值只从环境变量读取，不写入配置、事件、日志、Journal 或 Snapshot。
- Permission 具体动作规则与普通 config.toml 分离。

## 13. 代码结构

- 采用模块化单体，按稳定职责划分，而不是按 LangGraph、Day 编号或框架节点划分。
- 交互层、应用层、Agent Core、Capability 和 Integration 依赖单向流动。
- Kernel/Core 不依赖具体 SDK、TUI、存储、进程实现和权限规则文件。
- 不机械套用 Clean Architecture，不采用一个类型一个文件。
- 禁止无真实调用方的 Protocol、Repository、Manager、Factory 和未来占位目录。
- 文件数量不是验收指标，以职责内聚、依赖方向和可读性为准。

## 14. 文档与探索

- 不再追求一次性冻结 Day1—Day5 所有文件和异常语义的超大型任务书。
- 旧任务书负责提供需求，旧源码负责提供证据和教训，新版实现从零设计。
- 已拍板内容不得反复论证。
- 文档应结论优先，避免全仓考古、无限探索和多套完整候选架构。
- 普通工程细节由任务书直接决定，不把所有局部问题都交给用户拍板。

## 15. 停止条件

- 产品语义与已拍板约束冲突时停止。
- 必须扩大到后置能力才能继续时停止。
- 需要引入 LangGraph、通用工作流框架或长期兼容层时停止。
- Permission 可能产生越权或宽泛授权时停止。
- Tool 是否已经产生副作用无法确认时停止，禁止盲目重试。
- 实施需要超出用户当前指定 Day/批次时停止。
- 普通编译错误、测试失败和局部实现缺陷不属于停止条件，应自行修复。