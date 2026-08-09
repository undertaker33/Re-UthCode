# T03 System Prompt 设计 Spec

## 背景

当前 UthCode 已具备自有 Provider 请求模型、Application 生成用例、三种真实 Provider Integration、CLI、TUI 与 Headless 入口，但 System Prompt 仍借用普通历史消息临时表达，工作目录也尚未成为 Application 的统一运行事实。T03 将这部分临时语义替换为正式、单一且可测试的调用链。

## 目标

- 在 Core 中建立唯一、无第三方依赖、确定性输出的中文 System Prompt 语义。
- 将 System Prompt 与普通对话消息分离，并冻结普通消息的合法角色边界。
- 由 Application 在每次生成前根据稳定运行上下文和当前模型身份构建权威 Prompt。
- 让 CLI、TUI 与 Embedded Headless 共用同一运行上下文和 Prompt 注入路径。
- 让三种 Provider Integration 将统一 Prompt 映射到各自公开协议，而不改变响应、事件、工具、用量、错误或取消语义。
- 删除旧 System Message 路径，不保留兼容层或双轨入口。

## 能力清单

### Task 1：建立 Core System Prompt 模块

- 提供不可变的 Prompt 分段和值上下文。
- 固定身份、工作原则、代码质量与安全、沟通与结果真实性、当前运行环境五个 Section。
- 保证稳定排序、空段过滤、运行值安全渲染和相同上下文的确定性输出。
- 静态规则位于动态运行环境之前，且不声明尚未实现的能力。

### Task 2：替换 Core 请求中的临时 System Message 语义

- 为统一生成请求建立独立的可选 System Prompt 数据。
- 保证该数据可序列化、可恢复且保持请求不可变。
- 普通消息只允许用户、助手和工具三类角色，拒绝 System 及未知角色。

### Task 3：重写三种 Provider 的 System Prompt 映射

- Anthropic 使用消息请求的顶层系统指令入口。
- OpenAI Responses 使用请求级指令入口。
- OpenAI-compatible Chat 在历史消息之前生成唯一系统消息。
- 无 Prompt 时不发送对应协议内容，既有历史、Reasoning、工具、用量、错误、取消与资源关闭行为不变。

### Task 4：建立 Application 运行上下文与权威请求准备

- Application 独立持有工作目录、平台和日期等运行事实。
- 每次生成根据当前模型选择和 Provider 身份构建新的权威 Prompt 请求。
- 不修改调用方请求，不允许调用方覆盖或拼接权威 Prompt。
- 模型切换成功后刷新身份，切换失败时维持原身份。

### Task 5：统一 CLI、TUI 与 Headless 的运行上下文

- CLI 只解析一个规范化工作目录，并同时用于配置发现与运行上下文。
- TUI 从 Application 读取工作目录，不保留第二份所有权。
- CLI、TUI 与 Embedded Headless 均经 Application 注入 Prompt，Interface 不直接依赖 Core Prompt。

### Task 6：[接入主流程] 收口正式调用链

- 所有正式生成入口仅通过 Application 构建一次 Prompt。
- 删除普通 System Message、Interface 拼接、Provider 扫描历史和配置承载运行事实等旧路径。
- 保持 Interface 可替换性和既有分层依赖方向。

### Task 7：[端到端验证] 验证三协议与全部正式入口

- 使用离线 Fake 与 Mock 从 Headless、CLI、TUI 验证完整 Prompt。
- 验证三种厂商请求形状以及既有历史、Reasoning、工具、用量、错误和取消回归。
- 完成全量离线测试、字节码编译和依赖一致性检查。

### Task 8：[遗留负担清理] 删除临时语义和未来占位

- 扫描并清除旧 System Message Core 入口、重复上下文和双轨 Prompt。
- 确认未引入 Prompt 管理框架、缓存实现、兼容层或未来能力占位。
- 确认文档只描述正式入口，且无旧品牌与推广文本。

## 非功能要求

- Prompt 构建必须是无 I/O、无全局状态、可重复测试的纯逻辑。
- Core 不依赖 Application、Integration、Interface、Provider SDK、配置文件、环境变量或系统状态。
- Interface 只能通过 Application 使用 Prompt 能力；SDK 类型只能存在于 Integration。
- 相同 Application 与模型选择下 Prompt 文本完全一致；动态运行信息只能位于末尾。
- 不新增第三方依赖，不启用真实 Provider 请求，不泄漏端点、凭据来源或秘密。
- 保持现有流式事件、终态、错误分类、取消隔离、资源关闭及 stdout/stderr/退出码行为。
- 不为兼容 Re:UthCode 早期实现新增适配器、别名、包装层或双轨逻辑。

## 设计骨架

```text
CLI / TUI / Embedded Headless
            ↓
Application 运行上下文 + 当前模型身份
            ↓
Application 权威请求准备
            ↓
Core System Prompt 构建
            ↓
统一生成请求
            ↓
Provider Integration 协议映射
            ↓
Anthropic / Responses / OpenAI-compatible Chat
```

数据所有权固定为：Core 拥有 Prompt 语义和统一请求；Application 拥有运行上下文、模型选择和请求准备；Integration 拥有厂商协议映射；Interface 只拥有启动参数、交互和显示。

## Out of Scope

- Tool、Permission、Agent Loop、完整 Context、压缩、Memory、Dream、Plan Mode。
- Hook、Skill、MCP、Subagent、Multi-Agent、Worktree、Sandbox。
- 项目自定义指令加载、Prompt Manager、Registry、Loader 或模板框架。
- Prompt Cache API、缓存键、缓存控制、缓存存储或缓存评测。
- Provider Factory、配置格式、Provider Response/Event、Native Item、Usage 和取消公共语义调整。
- 新 Provider、SDK 升级、真实付费请求或大规模 Prompt 质量评测。
- 工作包归档以及 Git 提交、推送、PR、合并、标签或发布。

## 验收标准

- Core 是 Prompt 正文和构建语义的唯一所有者，输出中文、确定、顺序稳定且无未来能力声明。
- System Prompt 与普通消息协议完全分离，普通消息只接受用户、助手和工具角色，不存在兼容入口。
- Application 在每次生成前从统一运行上下文和当前模型身份准备新请求，原请求保持不变，调用方无法覆盖权威 Prompt。
- CLI、TUI 与 Embedded Headless 使用相同工作目录事实和 Prompt 注入路径，Interface 不直接依赖 Core Prompt。
- Anthropic、Responses 与 Chat 的厂商请求分别落入其正式协议位置，无 Prompt 时不产生对应内容。
- 三协议既有历史、Reasoning、工具、Native Item、Usage、错误、取消和资源关闭回归通过。
- Interface 删除后，Headless 链路仍可独立运行；根包导入不加载 SDK 或 Interface 副作用。
- 全量离线测试、字节码编译、依赖检查、架构扫描、遗留扫描和文档检查全部通过。
- 未新增兼容层、重复职责、未来占位、旧品牌文本或缓存实现。

