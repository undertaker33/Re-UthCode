# T01-项目骨架与Provider抽象 Spec

## 1. 背景

Re:UthCode 需要在空仓中建立第一批可运行能力。该批次只建立可安装的 Python 项目、无界面 Application API、UthCode 自有 Provider 契约，以及 Fake、Anthropic、OpenAI Responses、OpenAI-compatible Chat Completions 四类 Provider 接入。

旧 UthCode 与 MewCode 只提供行为证据，不作为迁移对象或运行时依赖。新版不兼容旧类、旧 API、旧模块路径、旧状态结构和旧输出格式，也不引入 LangGraph、LangChain Agent 或任何图运行时。

当前实现基于 Python 3.12 和 Pydantic AI Direct Model API。Pydantic AI 及厂商 SDK 只能位于 Integration；其传递安装的 Pydantic Graph 不得被 UthCode 直接声明、导入或使用。

## 2. 目标

完成本工作包后，项目应具备：

1. 可安装、可导入、可测试的 `uthcode` Python 包；
2. 不依赖终端或界面的 Headless Application 包与统一调用入口；
3. UthCode 自有且与厂商 SDK 隔离的请求、消息、响应、流事件、用量、错误和取消契约；
4. 可脚本化、可记录请求、不会联网的 Fake Provider；
5. Anthropic、OpenAI Responses、OpenAI-compatible Chat Completions 三种真实协议适配；
6. Provider 特有数据的 JSON-safe 保存、顺序保持和同协议往返；
7. 默认完全离线的自动化测试，以及显式凭据驱动的三协议真实端点验收；
8. 允许后续以独立物理模块增加 Provider，而不修改 Core 和 Application 语义。

## 3. 按 Task 划分的能力清单

### Task 1：建立可安装项目骨架

建立 Python 3.12 的 src-layout 项目、最小根包入口、依赖声明、测试配置、秘密示例和使用说明，不提前创建尚无实现的职责目录。

### Task 2：定义 Provider 核心契约

定义不可变、JSON-safe、第三方类型隔离的 Provider 请求、消息、内容部分、原生项、响应、事件、用量、错误、取消与端口契约。

### Task 3：打通 Headless Application 与 Fake Provider

建立 Application 物理包和最小无界面调用链，验证正常终态、异常结束、显式取消和 Python 原生任务取消。

### Task 4：建立 Pydantic AI Direct 集成边界

在 Integration 内建立唯一共用桥接层，负责通用请求、流事件、用量、错误、资源关闭和终态转换；协议特有逻辑不得进入该层。

### Task 5：实现 Anthropic 协议适配

通过独立物理模块支持 Anthropic 文本、Thinking、签名、Redacted Thinking、Tool Use、Tool Result、用量、错误、取消和同协议往返。

### Task 6：实现 OpenAI Responses 协议适配

通过独立物理模块支持有序 Responses Item、Reasoning、Function Call、Function Call Output、用量、终态、失败、取消和同协议往返。

### Task 7：实现 OpenAI-compatible Chat Completions 协议适配

通过独立物理模块支持自定义端点、Chat 消息、工具定义、索引化 Tool Call 聚合、Tool Result、用量、错误、取消和同协议往返。

### Task 8：实现配置与 Provider 构造

在 Provider Integration 内建立只保存秘密环境变量名称的配置，并完成 Fake 与三种真实协议的构造选择。

### Task 9：[接入主流程] 接入正式 Headless 调用链

通过 Application 的唯一公开组合入口连接 Integration 构造与 Headless 用例，移除仅供阶段开发使用的重复入口，并补齐公开使用说明。

### Task 10：[端到端验证] 验证离线链路与真实三协议

从正式 Headless 入口完成离线正常路径和关键失败路径验收；在显式提供环境变量后，使用同一 DeepSeek 凭据分别验证 Anthropic、Responses 和 Chat Completions 三种协议。

### Task 11：[遗留负担清理] 清除兼容层与重复职责

确认本工作包未引入旧 API 兼容、重复协议、旧入口、不可达代码、未来能力占位或对成熟依赖的重复实现。

## 4. 非功能要求

### 4.1 依赖与环境

- 正式开发和验证统一使用 Conda 环境 `re-uthcode`；
- Python 支持范围限定为 3.12 系列；
- Pydantic AI 依赖限定在已验证的 2.22 次版本范围；
- 只直接声明项目实际使用的生产与开发依赖；
- 允许 Pydantic AI 自身需要的传递依赖存在，但 UthCode 不得直接使用 Pydantic Graph；
- 每次调整依赖后执行依赖一致性检查，并清理不再被项目或传递链需要的包。

### 4.2 架构边界

- Core 不导入 Integration、Pydantic AI 或厂商 SDK；
- Application 的用例模块只依赖 UthCode Core 契约，组合模块可依赖 Integration 构造入口；Application 内不得按 Provider 名称分支；
- Provider 选择只发生在 Integration 构造边界；
- 后续 Interface 只能通过 Application 的公开入口使用 Core，不得直接装配 Integration；
- 每种真实协议拥有独立物理适配模块；
- 共用适配层不得累积 Provider 名称判断或协议字段；
- 新增 Provider 时以新增物理模块和构造注册为主，不修改 Core 数据所有权。

### 4.3 数据安全与秘密

- Core 公共数据必须可安全序列化为 JSON；
- Native Item 不保存 SDK、Pydantic Model、客户端或其他运行时对象；
- Native Item 只保存对应物理协议模块能够验证并恢复的协议数据；
- 不属于当前 Provider 的 Native Item 不得发送到目标 Provider；
- API Key 只从进程环境变量读取，不进入配置文件、repr、错误、测试报告或版本库；
- 默认测试不得读取真实 Key 或建立网络连接。

### 4.4 流与取消

- 每个成功流恰好产生一个完成终态；
- 无合法终态、终态后继续产出、未完成 Tool Call 或冲突完成数据必须失败；
- 显式取消映射为 UthCode 取消结果；
- Python 任务取消保持原生取消语义；
- 退出流时必须关闭由 Integration 拥有的网络资源。

### 4.5 可测试性

- Fake Provider 覆盖 Application 的完整无网络链路；
- 真实协议离线测试通过注入 Mock SDK Client 或 Mock Transport，实际经过对应 Pydantic AI Model 的协议转换；
- Pydantic AI Test Model 只能用于共用边界测试，不能代替三种厂商协议测试；
- 真实端点测试必须显式标记且默认跳过，避免 CI 和普通开发命令产生网络调用或费用。

## 5. 设计骨架

调用方向为：

```text
Embedding Caller / Headless Test
              ↓
     Application Public Package
          ↙              ↘
 Composition Entry     Generation Use Case
          ↓                    ↓
 Integration Factory    UthCode Provider Port
          ↓                    ↑
  Physical Protocol Modules ───┘
    ↙          ↓           ↘
Anthropic   Responses   Chat Compatible
              ↑
        Shared Direct Bridge
```

Core 拥有统一语义；Application 用例只通过 Core Port 工作；Application 组合入口负责调用 Integration Factory，但不拥有 Provider 分支；Integration 拥有协议选择、协议转换和第三方类型。协议特有的 Native Item 编解码分别留在各自物理模块，共用桥接层只协调 Pydantic AI Direct Model API 的公共生命周期。

Native Item 是 UthCode 自有的协议快照，而不是 SDK 对象镜像。它需要覆盖本批次明确列出的协议字段，并能通过对应协议模块恢复；未知 Provider 数据不自动跨协议传播。

## 6. Out of Scope

本工作包不实现：

- CLI、TUI、Web、Desktop 或 IDE 交互层；
- System Prompt；
- Tool Registry、Tool 执行或 Agent Loop；
- Permission、Journal、Snapshot、Session 或持久化；
- Context、Memory、Dream 或压缩；
- Sandbox、Slash Command、Hook、Skill、MCP、Worktree 或 Multi-Agent；
- Provider 模型发现、远端 Context Window 查询或宽泛厂商兼容补丁；
- Pydantic AI Agent、Pydantic Graph 或第三方 Agent Loop；
- Responses WebSocket、服务端 Conversation State 或跨 Run 内容仓库；
- 任意旧 UthCode API 的兼容层。

## 7. 验收标准

### 7.1 工程与环境

- 项目可在 `re-uthcode` 环境中完成 editable install、字节码编译和全量测试；
- 根包、Core 和 Application 导入无网络及 Provider 构造副作用；Application 是物理包而非根级功能模块；
- 依赖检查无破损项，直接依赖清单不包含未使用依赖；
- UthCode 源码不导入 Pydantic Graph、LangGraph 或 LangChain Agent。

### 7.2 Core 与 Application

- Core 公共签名不出现 Pydantic AI、OpenAI 或 Anthropic 类型；
- Application 用例模块不导入 Integration，组合模块是 Application 内唯一允许依赖 Integration Factory 的位置；
- 请求、消息、事件和 Native Item 可 JSON round-trip，且拒绝非 JSON-safe 对象；
- Fake Provider 可从正式 Application 入口完成文本与 Tool Call 流；
- 异常 EOF、重复终态、终态后事件和取消路径产生可区分结果。

### 7.3 三种协议

- Anthropic 推理内容、不透明签名、脱敏推理块与工具调用顺序可保存并同协议恢复；
- Responses 推理内容、摘要、输出项身份、函数调用及结果关联和输出顺序可保存并同协议恢复；
- Chat Completions 的工具定义、助手工具调用、索引化聚合、工具结果和调用身份可正确转换；
- 任一 Provider 不接收其他 Provider 的 Native Item；
- 三种协议的离线测试实际经过对应 Pydantic AI Model，且不建立真实网络连接。

### 7.4 真实端点

- 未设置 live 标记或秘密环境变量时，普通测试不访问网络；
- 显式提供秘密环境变量后，可使用 DeepSeek 官方端点和当前稳定公开模型从正式 Headless 入口分别完成三种协议的文本、推理内容、工具调用及工具结果续轮验证；
- 真实端点测试不打印、保存或回显 Key；
- 网络失败与协议能力差异必须作为真实验收结果报告，不得通过放宽离线契约掩盖。

### 7.5 范围与遗留负担

- 项目不存在未来能力空目录或占位实现；
- 不存在旧类、旧 API、旧行为适配器、别名、Facade 或双轨 Runtime；
- 不存在职责重复的 Provider 协议实现或绕过正式构造入口的残留调用链；
- 后续新增 Provider 可以通过独立物理 Integration 模块接入，而无需修改 Core 和 Application 语义。
