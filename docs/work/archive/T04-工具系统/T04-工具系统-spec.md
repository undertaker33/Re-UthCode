# T04 工具系统 Spec

## 背景

Re:UthCode 已完成 Provider、配置、System Prompt、Headless Application 与简单交互层的前置基线，但尚无可供后续 Agent Loop 复用的权威工具系统。当前配置加载还存在 Integration 反向依赖 Application 的已知边界缺陷，必须在引入工具 Integration 前先消除。

本工作包以提交 `210d47da84fb012c9672680bf03033c6c5cf58c8` 为冻结代码基线。原 UthCode 与 MewCode 仅用于提取产品行为和历史教训，不迁移其旧 API、Pydantic 参数模型、LangGraph 结构或未来能力。

## 目标

- 建立 Provider 无关、由 Core 拥有的工具契约、稳定注册表、参数校验、严格 FIFO 执行与统一结果语义。
- 提供读取、写入、编辑、文件匹配、文本搜索和当前操作系统命令执行六项基础能力。
- 对文件和搜索能力实施统一工作区边界、符号链接防逃逸及 read-before-write/edit 保护。
- 让 Headless Application 成为查询工具定义和执行工具调用的唯一公开入口。
- 支持调用方手动完成一次 Provider 工具调用与结果回填，同时明确不实现自动 Agent Loop。
- 修复配置加载的反向依赖，并保持既有配置行为不变。

## 能力清单

### Task 1：修复配置 Integration 反向依赖

- Integration 只负责发现、读取、校验、合并并返回不可变的原始配置数据。
- Application 负责将原始配置数据转换为权威有效配置。
- 保留配置来源、路径、字段和初始化模板等诊断证据。
- 配置格式、发现规则、合并优先级、秘密来源和模型选择行为不变。

### Task 2：建立 Core Tool 契约、Registry 与 FIFO Executor

- 复用既有 Tool 定义、调用、结果和取消模型，不建立第二套 DTO。
- 注册表保持注册顺序并拒绝重复名称和非法 schema。
- 执行器在调用前校验参数，严格串行执行批次，并保证每个调用都有同 ID 结果。
- 未知工具、非法参数、普通异常和取消均收口为稳定工具结果。
- 所有工具输出由 Core 统一、确定性地截断。

### Task 3：实现工作区、文件状态与文件工具

- 文件路径必须限制在 Application 的规范化工作区内。
- 读取支持稳定的行号与分页语义。
- 新文件可以直接创建；覆盖或编辑已有文件前必须成功读取且文件未发生外部变化。
- 文件状态结合内容摘要和文件元数据判断，不能仅依赖修改时间。
- 编辑目标必须非空且唯一，成功写入后刷新共享读取状态。

### Task 4：实现安全 Glob 与 Grep

- 使用 Python 文件遍历、glob 与正则能力，不调用 shell 搜索命令。
- 搜索只返回安全的工作区内文件，不跟随目录符号链接。
- 固定跳过版本库、虚拟环境、依赖和缓存目录。
- 结果使用工作区相对路径、稳定排序和可观察的空结果语义。

### Task 5：实现 Bash 进程工具

- 在 Application 工作目录中使用当前操作系统 shell、当前用户权限执行命令。
- 区分标准输出、标准错误、空输出和非零退出状态。
- 支持有界超时和调用方取消；结束时终止并回收进程及其子进程。
- 明确该能力不是 Sandbox，也不在本任务实现危险命令策略或审批。

### Task 6：默认工具 Factory 与 Application Headless API

- 每个 Application 独立装配固定顺序的六个默认工具。
- 三个文件工具共享同一工作区解析器和读取状态，不同 Application 之间隔离。
- Application 公开不可变工具定义集合和批量执行入口，不泄漏具体 Integration 工具。
- 支持显式注入完整替代默认集合的测试或 Embedded 工具。
- 工具工作目录与 Application 运行上下文使用同一事实来源。

### Task 7：[接入主流程] 打通手动单次工具往返

- 通过正式 Headless Application 和 Fake Provider 完成一次工具定义暴露、Provider 返回调用、工具执行、结果消息回填和第二次请求。
- 保证调用 ID、运行上下文、工具定义和文件内容在整条链路中一致。
- Application 不自动循环、不自动追加消息，CLI/TUI 行为保持不变。

### Task 8：[端到端验证] 全量测试与边界验证

- 验证工具系统、配置修复、Application、Provider、CLI、TUI、System Prompt 和架构边界共同工作。
- 保持未授权 live Provider 测试跳过。
- 完成编译、依赖完整性、全量测试和差异格式检查。

### Task 9：[遗留负担清理] 删除重复入口与未来占位

- 确保只有一套工具契约、一个配置转换所有者和一条 Application 工具入口。
- 清除反向依赖、旧配置入口、重复 DTO、兼容层、不可达代码及无调用方扩展。
- 扫描并确认没有旧项目运行时依赖、LangGraph/LangChain、Pydantic 工具模型或 Sandbox 误导描述。

## 非功能要求

- 依赖方向保持 `interfaces → application → core`，Application 组合根可装配 Integration，Integration 只能依赖 Core。
- Core 不依赖文件系统具体实现、进程实现、Provider SDK 或交互层。
- Tool Batch 严格 FIFO，不因只读工具而并行。
- 所有公开集合不可变且顺序稳定；第三方校验库类型不得越过 Core。
- 文件和搜索路径必须同时通过词法与物理路径边界检查。
- 取消和超时不得产生虚假成功；无法确认进程收口时必须返回明确错误。
- 代码与文档不得把普通命令执行描述为 Sandbox。
- 复用成熟 JSON Schema 校验依赖，不自制同等校验器。
- 不保留为了兼容旧 UthCode、MewCode 或 Re:UthCode 早期实现而存在的入口或适配层。

## 设计骨架

```text
Headless caller
    │
    ▼
Application tool API
    │
    ▼
Core registry + schema validation + FIFO executor
    │
    ▼
Integration file/search/process tools
    │
    ▼
Core tool results
```

配置加载采用单向数据流：Integration 生成不可变原始数据，Application 将其转换为唯一的运行配置对象。默认工具由 Application 组合根按其运行工作目录创建；文件工具共享 Application 局部的读取状态，任何状态都不得跨 Application 全局共享。

## Out of Scope

- 自动 ReAct Agent Loop、自动工具暴露、自动执行或自动消息回填。
- Run/Turn 状态机、最大轮数、预算、恢复、终态和跨 Run 输出仓库。
- Permission、危险命令判断、人工审批和 OS Sandbox。
- 工具并行、启停配置、延迟发现及无调用方 metadata。
- Context、Memory、Hook、Skill、MCP、Subagent、Worktree。
- TUI/CLI 工具状态、权限弹窗或交互改造。
- System Prompt 工具能力声明和真实 Provider 费用请求。
- 旧类、旧 API、旧数据结构、兼容层、Facade、Shim 或双轨实现。

## 验收标准

- 六个默认工具可由正式 Application API 发现并执行，名称和顺序稳定。
- 每个工具调用都得到数量、顺序和 ID 对应的结果；普通失败不使批次崩溃。
- 文件、搜索和命令输出统一受确定性长度限制。
- 工作区外绝对路径、父目录逃逸及指向外部的文件或目录符号链接均不能被文件或搜索能力访问。
- 已有文件未经读取、读取后被外部修改或替换时不能写入或编辑。
- 命令超时或取消后进程与子进程被终止并回收，输出明确当前 OS shell 语义。
- Headless Fake Provider 链路完成一次真实文件读取工具往返，第二次请求包含对应工具结果。
- Integration 不导入 Application 或 Interface；Interface 不直连 Core/Integration 工具。
- 配置既有产品行为、三 Provider 映射、System Prompt、模型切换、CLI 和 TUI 回归通过。
- 全量测试、编译、依赖检查、架构扫描与差异检查通过，live Provider 用例保持门禁跳过。
- 没有 Agent Loop、Permission、Sandbox、并行、deferred、MCP 或其他后置能力偷跑。

