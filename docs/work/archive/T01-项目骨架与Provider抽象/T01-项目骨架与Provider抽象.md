# T01-项目骨架与Provider抽象

## 1. 分析基线

### 1.1 仓库基线

| 对象 | 基线 |
| --- | --- |
| Re-UthCode | `316aa901d6951321fc38a2bf67c3bca070c00ddc` |
| 原 UthCode | `1c3507b761e48ac38d846bc39700ce0039f84a04` |
| 原 Day1 主任务书 | `docs/archive/work/Day1-项目骨架和Provider抽象/Day1-项目骨架和Provider抽象.md` |
| MewCode | `3_mewcode-python.zip` |

Re-UthCode 当前基线只包含初始化约束文件，Commit 信息为 `docs: initialize repository`。

### 1.2 已读取的新版约束

```text
AGENTS.md
SRe-AGENTS.md
```

本任务书遵守以下冻结决策：

- 在 Re-UthCode 中从零实现；
- 正式项目名和 Python 包名仍为 `UthCode / uthcode`；
- 完全脱离 LangGraph 和 LangChain Agent；
- Agent Core 无界面、可嵌入、可独立测试；
- Provider SDK 类型只能存在于 Integration；
- Core 使用 UthCode 自有模型；
- 不兼容旧 API、旧路径、旧类和旧状态；
- 不创建后续 Day 的占位目录或伪实现。

`SRe-AGENTS.md` 原本要求先实现 Fake 和一个真实 Provider。用户已明确将当前 Day1 范围调整为三个真实 Provider，因此本任务书同时实现：

```text
Anthropic
OpenAI Responses
OpenAI-compatible Chat Completions
```

### 1.3 实际读取的旧 UthCode 关键来源

#### 需求与实施记录

```text
docs/archive/work/Day1-项目骨架和Provider抽象/
├── Day1-项目骨架和Provider抽象.md
├── Day1-项目骨架和Provider抽象-tasks.md
└── Day1-项目骨架和Provider抽象-checklist.md
```

#### Provider 与核心模型

```text
src/uthcode/config.py
src/uthcode/conversation/models.py
src/uthcode/graph/events.py
src/uthcode/providers/types.py
src/uthcode/providers/fake.py
src/uthcode/providers/factory.py
src/uthcode/providers/anthropic.py
src/uthcode/providers/openai_responses.py
src/uthcode/providers/openai_compat.py
```

#### 关键测试证据

```text
tests/test_fake_provider.py
tests/test_provider_request_contract.py
tests/test_provider_services.py
tests/test_provider_factory.py
tests/test_anthropic_provider.py
tests/test_openai_responses_provider.py
```

旧 UthCode 已验证：

- Provider Request 为不可变、JSON-safe 数据；
- SDK 对象不能进入公共请求；
- Provider 原生项按协议顺序保存；
- Reasoning、Tool Call、Tool Result 和 Message 可保持原顺序；
- Provider 限流、Usage、异常与取消状态相互隔离；
- Anthropic Thinking 签名和 Redacted Thinking 可以保存；
- OpenAI Responses 交错 Tool Call、异常 EOF 和重复终态可以识别；
- 三类 Provider 可以在不发起网络请求时完成构造。

这些行为可以作为新版验收证据，但旧类型名称、文件路径和实现结构不保留。

### 1.4 实际读取的 MewCode 关键来源

```text
3_mewcode-python.zip!/mewcode/client.py
3_mewcode-python.zip!/mewcode/config.py
3_mewcode-python.zip!/mewcode/conversation.py
3_mewcode-python.zip!/mewcode/serialization.py
3_mewcode-python.zip!/mewcode/tools/base.py
3_mewcode-python.zip!/tests/test_serialization.py
3_mewcode-python.zip!/tests/test_context_window.py
```

直接相关代码位置：

| 范围 | 位置 |
| --- | --- |
| Anthropic 请求、Thinking、Tool Use、Usage | `mewcode/client.py:165-286` |
| OpenAI Responses 流式事件 | `mewcode/client.py:289-403` |
| OpenAI-compatible Tool Call 聚合 | `mewcode/client.py:404-559` |
| 三种协议消息序列化 | `mewcode/serialization.py:16-132` |
| 通用 Message 和 Tool Block | `mewcode/conversation.py:20-40` |

MewCode 只提供协议行为和历史实现参考，不复制文件，不作为运行时依赖。

### 1.5 其他参考源的实际用途

| 来源 | Day1 用途 | 处理 |
| --- | --- | --- |
| Pydantic AI 官方文档与源码 | 确认 Direct Model API、流式模型调用、Provider Details 和模型构造方式 | 直接影响实现 |
| Anthropic 官方 API | 确认 Thinking、Signature、Redacted Thinking 和 Tool Use 往返规则 | 直接影响测试 |
| OpenAI 官方 API | 确认 Responses Item、Reasoning、Function Call 和 Chat Completions 差异 | 直接影响测试 |
| OpenAI Codex | 参考 Provider 配置隔离和有序 Responses Item 处理 | 行为参考 |
| learn-claude-code | 证明模型调用层与 Agent Harness/Loop 应分离 | 不复制代码 |
| Claude Code 公共仓库 | 公共仓库不包含可直接分析的生产 Provider Core | 不作为实现来源 |
| FirstCoder | 仅为未来 TUI 参考 | Day1 不读取、不使用 |

Codex 当前将 Provider 配置与 Core 调用分离，并以有序 `ResponseItem` 和流式 Output Item 处理 Responses 数据；但其当前主线只采用 Responses wire API，不能直接作为三 Provider 抽象模板。

learn-claude-code 的直接价值是说明 Agent 产品由模型和 Harness 组成，Provider 调用本身不应拥有 Tool 执行或 Agent Loop；其教学实现不具备生产级三 Provider 抽象，不能作为协议细节来源。

Claude Code 公共仓库主要提供产品入口、插件和安装资料，没有公开可用于迁移的生产 Provider Core，因此 Anthropic 协议行为以官方 API 文档和旧 UthCode 测试为准。

---

## 2. Day1 目标

### 2.1 最终交付

Day1 完成后，Re-UthCode 应具备：

1. 可安装、可导入的 `uthcode` Python 项目；
2. 无界面 Headless Application API；
3. UthCode 自有 Provider Request、Message、Response、Event、Usage、Error 和 Cancellation 模型；
4. 可脚本化的 Fake Provider；
5. 基于 Pydantic AI Direct Model API 的三个真实 Provider Integration；
6. Provider 特有响应项的 JSON-safe 保存和同 Provider 往返；
7. 完整 Mock 测试，不访问真实模型服务。

### 2.2 不交付

Day1 不包含：

```text
CLI / TUI
System Prompt 设计
Tool Registry 和 Tool 执行
Agent Loop
Permission
Journal / Snapshot / Session
Context / Memory / Dream
Sandbox
后续扩展目录
```

`ToolDefinition`、`ToolCallPart` 和 `ToolResultPart` 只作为 Provider 请求与响应数据结构存在，不代表 Tool 系统已经实现。

### 2.3 最小可运行调用链

```text
Headless Test / Embedding Caller
                │
                ▼
       UthCodeApplication
                │
                ▼
          ProviderPort
          ┌─────┴───────────────┐
          │                     │
          ▼                     ▼
     FakeProvider       PydanticAIProvider
                                │
                    ┌───────────┼─────────────┐
                    ▼           ▼             ▼
                Anthropic   OpenAI        OpenAI Chat
                            Responses     Compatible
```

依赖方向：

```text
Application
    ↓
Core Provider Contract
    ↑
Integration Adapters
```

Core 不导入 Pydantic AI、OpenAI SDK 或 Anthropic SDK。

---

## 3. 原 Day1 要求处理表

| 原要求 | 处理 | 新版落实方式 | 原因 | 验收方式 |
| --- | --- | --- | --- | --- |
| 使用 src-layout 和 `uthcode` 包名 | 保留 | 建立 `src/uthcode` | 与新版仓库策略一致 | Editable install 和 import 测试 |
| 项目可安装、可测试 | 保留 | `pyproject.toml`、pytest | Day1 基础工程要求 | 安装及完整测试通过 |
| Fake Provider | 保留 | 可注入脚本事件并记录请求 | Headless 测试不依赖网络 | Fake 流式测试 |
| Anthropic Provider | 调整 | 通过 Pydantic AI Direct Model API 接入 | 不再直接维护厂商 SDK 流解析 | Mock Model 测试 |
| OpenAI Responses Provider | 调整 | 使用 Pydantic AI Responses Model | 保留 Responses 原生项，不直接暴露 SDK | Reasoning、Function Call 测试 |
| OpenAI-compatible Provider | 调整 | 使用 Pydantic AI OpenAI Chat Model 和自定义 base URL | 与 Responses 明确分开 | Chat 消息格式测试 |
| ConversationManager | 废弃 | Day1 只定义不可变 Message 和 Request | 会话管理不属于 Provider 抽象 | 不存在 manager 文件 |
| 每种协议单独在 Core 序列化 | 调整 | 协议转换全部位于 Integration | Core 不感知 Provider 名称 | 架构依赖测试 |
| ThinkingBlock | 调整 | 通用 ReasoningPart + Provider Native Item | 通用文本无法保存签名和原生块 | Anthropic 往返测试 |
| Provider 原生数据 | 调整 | UthCode 自有 `NativeItem` 包装 JSON payload | 不泄漏 SDK 类型，同时防止信息损失 | JSON-safe 与顺序测试 |
| StreamEvent | 保留 | 定义 UthCode 自有流事件联合类型 | Interface 和 Core 需要稳定事件 | 全事件测试 |
| Usage 和完成原因 | 保留 | 标准字段加 JSON-safe details | 不同协议字段不完全相同 | 三 Provider 映射测试 |
| Provider 错误映射 | 保留 | UthCode 自有异常体系 | 不暴露 SDK 异常 | 异常测试 |
| Provider 取消 | 保留 | CancellationToken + Python task cancellation | 长请求必须可以终止 | 取消及资源关闭测试 |
| Provider Factory | 调整 | 只存在于 Integration，允许按配置选择实现 | Core 中禁止按 Provider 分支 | Factory 测试 |
| API Key 配置 | 调整 | 配置只保存环境变量名称 | 秘密不能进入配置模型和日志 | Secret 测试 |
| Context Window 获取与模型表 | 后置 | Day1 不实现远端模型元数据查询 | 不属于最小调用链 | 不存在相关函数 |
| 最小 CLI | 后置 | 使用 Headless Application 测试入口 | CLI 属于 Interface Adapter | 无 CLI 文件 |
| LangGraph State、Node、Router、Builder | 废弃 | 不创建任何 Graph 结构 | 与新版冻结约束冲突 | 禁止依赖测试 |
| InMemory Checkpoint | 废弃 | 不创建 Checkpoint | Persistence 后置 | 项目无 Checkpoint 文件 |
| Prompt 骨架 | 后置 | Day2 再建立真实 System Prompt | 禁止未来占位 | 无 prompts 目录 |
| Tool Registry 和假 Tool 执行 | 后置 | 仅保留 Tool 数据模型 | Tool 系统属于 Day3 | 无 tools 目录 |
| Permission、Context、Memory 等占位 | 废弃 | 不创建目录或模型 | 明确禁止未来占位 | 目录检查 |
| `_reference/mewcode` 源码副本 | 废弃 | 只在探索阶段读取压缩包 | 禁止整文件复制和旧项目依赖 | 仓库无 `_reference` 源码 |

---

## 4. Day1 目标目录树

以下只列出 Day1 新增或实际修改的文件：

```text
Re-UthCode/
├── pyproject.toml
├── README.md
├── .gitignore
├── .env.example
├── src/
│   └── uthcode/
│       ├── __init__.py
│       ├── application.py
│       ├── config.py
│       ├── core/
│       │   ├── __init__.py
│       │   └── provider.py
│       └── integrations/
│           ├── __init__.py
│           └── providers/
│               ├── __init__.py
│               ├── fake.py
│               ├── pydantic_ai.py
│               ├── anthropic.py
│               ├── openai_responses.py
│               ├── openai_compat.py
│               └── factory.py
└── tests/
    ├── test_package.py
    ├── test_application.py
    ├── test_provider_contract.py
    ├── test_provider_factory.py
    ├── test_anthropic_integration.py
    ├── test_openai_responses_integration.py
    ├── test_openai_compat_integration.py
    └── test_architecture_boundaries.py
```

禁止创建：

```text
cli.py
__main__.py
runtime.py
graph/
tools/
prompts/
permissions/
context/
memory/
session/
storage/
journal/
sandbox/
commands/
hooks/
skills/
mcp/
agents/
worktree/
```

---

## 5. 核心数据契约

### 5.1 `core/provider.py`

该文件集中定义 Day1 Provider 调用链真正使用的模型。

#### 请求模型

```text
JsonPayload
ProviderIdentity
TextPart
ReasoningPart
ToolCallPart
ToolResultPart
NativeItem
Message
ToolDefinition
ReasoningOptions
GenerationRequest
```

#### 响应模型

```text
Usage
FinishReason
ProviderResponse
```

#### 流事件

```text
TextDelta
ReasoningDelta
ToolCallStarted
ToolCallArgumentsDelta
ToolCallCompleted
NativeItemCompleted
GenerationCompleted
```

#### 错误和取消

```text
ProviderError
ProviderConfigurationError
MissingSecretError
AuthenticationError
RateLimitError
NetworkError
InvalidProviderResponseError
GenerationCancelled
CancellationToken
```

#### Provider Port

```python
class ProviderPort(Protocol):
    @property
    def identity(self) -> ProviderIdentity: ...

    async def stream(
        self,
        request: GenerationRequest,
        *,
        cancellation: CancellationToken,
    ) -> AsyncIterator[ProviderEvent]: ...
```

### 5.2 Native Item 规则

`NativeItem` 必须由 UthCode 自己定义，至少包含：

```text
provider
protocol
model
schema_version
sequence_index
kind
payload: JsonPayload
```

规则：

1. `payload` 必须是 JSON-safe；
2. 不允许保存 SDK、Pydantic Model 或运行时对象；
3. 原生项必须保持协议返回顺序；
4. 同一个原生项只能完成一次；
5. 同 Provider 下一轮请求优先使用原生项恢复完整协议数据；
6. 不同 Provider 不得接收到另一个 Provider 的原生项；
7. 切换 Provider 时只能使用可移植的标准 Message Part；
8. Native Item 不进入 UI 专用模型。

### 5.3 三种协议必须保留的特有数据

#### Anthropic

至少保存：

```text
thinking
signature
redacted_thinking
tool_use
tool_result
content block 顺序
stop_reason
cache usage
```

Extended Thinking 的签名和 Redacted Thinking 是不透明数据，不能重新生成、解释或跨 Provider 使用。

#### OpenAI Responses

至少保存：

```text
reasoning item
reasoning summary
response item id
function_call
function_call_output
call_id
output item 顺序
incomplete reason
usage details
```

交错 Function Call 必须按 `item_id / output_index / call_id` 分离，不能只使用单个全局参数缓冲区。流结束时存在未完成 Tool Call 或不存在合法终态，必须抛出 `InvalidProviderResponseError`。

#### OpenAI-compatible Chat Completions

至少正确转换：

```text
工具定义：
type = function
function.name
function.description
function.parameters

助手 Tool Call：
assistant.tool_calls[]
tool_call.id
tool_call.function.name
tool_call.function.arguments

工具结果：
role = tool
tool_call_id
content
```

流式 Tool Call 必须按 `index` 分别聚合，`finish_reason == "tool_calls"` 时生成完整 Tool Call。

---

## 6. 文件级任务清单

| 文件路径 | 操作 | 职责 | 核心类型/函数 | 允许依赖 | 禁止依赖 | 来源参考 | 对应测试 | 验收条件 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `AGENTS.md` | 保留不动 | 仓库最高级规则入口 | 无 | 无 | 任何修改 | Re-UthCode 基线 | 人工检查 | 内容与 SHA 对应版本一致 |
| `SRe-AGENTS.md` | 保留不动 | 重构冻结约束 | 无 | 无 | 任何修改 | Re-UthCode 基线 | 人工检查 | 内容保持不变 |
| `pyproject.toml` | 新增 | Python 工程、构建和依赖 | project metadata、dev dependencies | hatchling、Pydantic AI Slim | LangGraph、LangChain Agent | 原 Day1 工程要求 | `test_package.py` | Editable install 成功 |
| `README.md` | 新增 | 说明 Day1 边界、Headless 示例和测试命令 | Headless 示例 | `uthcode.application`、Core 类型 | CLI、TUI、后续能力说明 | 新版约束 | 文档命令验证 | 示例可以运行 |
| `.gitignore` | 新增 | 忽略虚拟环境、缓存和本地秘密 | 无 | 无 | 忽略正式源码 | 原 Day1 | 人工检查 | 不跟踪 `.env`、缓存 |
| `.env.example` | 新增 | 只列出真实 Provider 所需环境变量名称 | `ANTHROPIC_API_KEY`、`OPENAI_API_KEY`、兼容端点变量 | 无 | 真实秘密值 | 配置约束 | Secret 测试 | 文件不含真实 Key |
| `src/uthcode/__init__.py` | 新增 | 轻量包入口 | `__version__` | 标准库 | Integration、SDK 初始化 | 原 Day1 | `test_package.py` | 导入无副作用 |
| `src/uthcode/application.py` | 新增 | Headless Application API 和流终态校验 | `UthCodeApplication.stream_generation()` | `core.provider` | Pydantic AI、SDK、stdin/stdout | Agent Core 约束 | `test_application.py` | Fake 调用完整运行 |
| `src/uthcode/config.py` | 迁移后重写 | Provider Integration 配置 | `ProviderKind`、`ProviderConfig` | 标准库、Core identity | SDK Client、API Key 真实值 | 旧 `config.py` | `test_provider_factory.py` | 配置不可携带明文秘密 |
| `src/uthcode/core/__init__.py` | 新增 | 导出稳定 Core 公共类型 | 显式 `__all__` | `core.provider` | integrations | 新版结构 | `test_package.py` | 无第三方导入 |
| `src/uthcode/core/provider.py` | 迁移后重写 | UthCode 自有 Provider 数据契约 | 请求、消息、事件、响应、错误、取消、Port | 标准库 | Pydantic、OpenAI、Anthropic、LangGraph | 旧 `conversation/models.py`、`graph/events.py`、`providers/types.py` | `test_provider_contract.py` | 深度不可变、JSON-safe、顺序稳定 |
| `src/uthcode/integrations/__init__.py` | 新增 | Integration 命名空间 | 无 | 无 | 业务导出 | 新版结构 | 架构测试 | 导入无网络副作用 |
| `src/uthcode/integrations/providers/__init__.py` | 新增 | 只导出 Factory 和必要公共构造入口 | `create_provider` | Integration 内部模块 | Core 反向依赖 | 旧 providers 包 | Factory 测试 | 不导出 SDK 类型 |
| `src/uthcode/integrations/providers/fake.py` | 迁移后重写 | 可脚本化无网络 Provider | `FakeProvider` | Core contract | Pydantic AI、SDK | 旧 `providers/fake.py` | Application 和 contract 测试 | 可记录请求、分批返回事件、模拟取消和错误 |
| `src/uthcode/integrations/providers/pydantic_ai.py` | 迁移后重写 | Pydantic AI Direct Model API 共用适配器 | `PydanticAIProvider`、内部 Codec 契约、事件转换 | Core、Pydantic AI Direct API | Pydantic AI Agent、Graph、Tool 执行 | 旧三个 Provider 行为、Pydantic 官方 Direct API | 三个 Integration 测试 | Pydantic 类型不越界 |
| `src/uthcode/integrations/providers/anthropic.py` | 迁移后重写 | 构造 Anthropic Model 并处理协议特有数据 | `build_anthropic_provider()`、Anthropic Codec | 共用适配器、Pydantic Anthropic Model | Core 分支、直接 Tool 执行 | 旧 Anthropic Provider、MewCode client | `test_anthropic_integration.py` | Thinking 和签名可往返 |
| `src/uthcode/integrations/providers/openai_responses.py` | 迁移后重写 | 构造 Responses Model 并处理原生 Item | `build_openai_responses_provider()`、Responses Codec | 共用适配器、Pydantic Responses Model | Chat Completions 格式混入 | 旧 Responses Provider、Codex | `test_openai_responses_integration.py` | Reasoning 和 Function Call 顺序稳定 |
| `src/uthcode/integrations/providers/openai_compat.py` | 迁移后重写 | 构造自定义 base URL 的 Chat Model | `build_openai_compat_provider()`、Chat Codec | 共用适配器、Pydantic OpenAI Chat Model | Responses Item 格式混入 | 旧 Compat Provider、MewCode serialization | `test_openai_compat_integration.py` | `tool_calls` 和 `role=tool` 正确 |
| `src/uthcode/integrations/providers/factory.py` | 迁移后重写 | 根据配置构造 Provider | `create_provider()` | config、四个 Provider 实现 | Core、UI、网络探测 | 旧 factory | `test_provider_factory.py` | 构造不发网络、未知类型失败 |
| `tests/test_package.py` | 新增 | 包安装、导入和公共导出测试 | import tests | 已安装包 | 网络 | 原 Day1 验收 | 自身 | 根包导入无副作用 |
| `tests/test_application.py` | 新增 | Headless Application + Fake 完整链路 | Fake 流、终态、异常 EOF | Core、Fake | 真实 Provider | 新版调用链 | 自身 | 无界面完成调用 |
| `tests/test_provider_contract.py` | 新增 | Core 模型和 Provider Port 契约 | JSON、不可变、顺序、取消 | Core | Integration SDK | 旧 request contract tests | 自身 | SDK 对象被拒绝 |
| `tests/test_provider_factory.py` | 新增 | 四种 Provider 构造和秘密处理 | Factory、配置验证 | Integration | 网络 | 旧 factory tests | 自身 | 构造过程零网络 |
| `tests/test_anthropic_integration.py` | 新增 | Anthropic 特有数据转换 | Thinking、Signature、Tool Use、Usage | Pydantic AI 测试对象 | 真实 API | 旧 Anthropic tests | 自身 | 原生数据同 Provider 往返 |
| `tests/test_openai_responses_integration.py` | 新增 | Responses Item 与流式终态转换 | Reasoning、Function Call、Incomplete、EOF | Pydantic AI 测试对象 | 真实 API | 旧 Responses tests、Codex | 自身 | 交错调用不串线 |
| `tests/test_openai_compat_integration.py` | 新增 | Chat Completions 消息与 Tool Call 转换 | `type=function`、`tool_calls`、`role=tool` | Pydantic AI 测试对象 | 真实 API | 旧 Compat 实现、MewCode | 自身 | Indexed Tool Call 正确聚合 |
| `tests/test_architecture_boundaries.py` | 新增 | 静态依赖和范围检查 | AST/import 扫描 | 标准库 | 外部扫描工具强依赖 | SRe-AGENTS | 自身 | 无 LangGraph、旧项目或 SDK 越界 |

### 迁移后重写统一要求

所有标记为 `迁移后重写` 的文件必须：

1. 只保留行为和测试意图；
2. 删除 LangGraph、Graph Event 和旧 Runtime 耦合；
3. 删除旧 `ConversationManager` 耦合；
4. 不保留旧类名和模块路径；
5. 不复制完整函数或完整文件；
6. 不导入 `mewcode` 或旧 UthCode；
7. 根据新版调用链重新实现。

---

## 7. 第三方依赖

### 7.1 生产依赖

```toml
dependencies = [
    "pydantic-ai-slim[anthropic,openai]>=2.15,<3",
]
```

Pydantic AI Direct Model API 仅用于 Integration 内部的模型构造、请求转换和流式响应转换。

禁止使用：

```text
pydantic_ai.Agent
pydantic_graph
Pydantic AI Tool 执行
Pydantic AI Agent retry loop
Pydantic AI conversation ownership
```

Pydantic AI 消息、Part、Usage、Model、Provider 和异常类型都不得出现在：

```text
uthcode.application
uthcode.core
ProviderPort 公共签名
Interface Adapter
```

### 7.2 开发依赖

```toml
[dependency-groups]
dev = [
    "pytest>=8.4,<10",
    "pytest-asyncio>=1.1,<2",
]
```

### 7.3 依赖说明

| 依赖 | 解决的问题 | 使用边界 | 是否进入 Core | 不自行实现原因 | 替换成本 |
| --- | --- | --- | --- | --- | --- |
| Pydantic AI Slim | 三种模型协议、流式模型调用和 SDK 集成 | 仅 `integrations/providers` | 否 | 避免重复维护三套 SDK 流协议 | 只重写 Integration 和对应测试 |
| Anthropic extra | Anthropic Model 和底层 SDK | Integration 内部 | 否 | 厂商协议持续变化 | 中等 |
| OpenAI extra | Responses、Chat Model 和兼容端点 | Integration 内部 | 否 | Responses 流事件复杂 | 中等 |
| pytest | 测试运行 | tests | 否 | 成熟测试框架 | 低 |
| pytest-asyncio | 异步流测试 | tests | 否 | 避免自建事件循环 fixture | 低 |

不单独声明 `openai`、`anthropic`、`httpx` 或 `pydantic`，由 Pydantic AI extras 管理其兼容版本。

---

## 8. 实施任务拆分

## Task 1：建立可安装项目骨架

### 目标

建立最小 Python 工程，不创建任何未来模块。

### 前置条件

- 当前位于 Re-UthCode 基线；
- `AGENTS.md` 和 `SRe-AGENTS.md` 未修改。

### 涉及文件

```text
pyproject.toml
README.md
.gitignore
.env.example
src/uthcode/__init__.py
src/uthcode/core/__init__.py
src/uthcode/integrations/__init__.py
src/uthcode/integrations/providers/__init__.py
tests/test_package.py
```

### 完成结果

- `pip install -e .` 成功；
- 根包可导入；
- 导入时不构造 Provider；
- 无 CLI、Graph 或未来目录。

### 测试

```text
tests/test_package.py
```

### 不允许顺带实现

```text
Provider 模型
真实 Provider
CLI
System Prompt
Tool
Agent Loop
```

### 推荐提交边界

```text
t01-01: initialize installable headless package
```

---

## Task 2：定义 UthCode Provider 核心契约

### 目标

完成 Provider 所需的全部 UthCode 自有数据模型。

### 前置条件

Task 1 完成。

### 涉及文件

```text
src/uthcode/core/provider.py
src/uthcode/core/__init__.py
tests/test_provider_contract.py
```

### 完成结果

- Request、Message、Part、Native Item、Event、Response、Usage、Error 和 Cancellation 完整；
- 所有公共 Payload JSON-safe；
- 数据模型不包含任何第三方类型；
- Native Item 顺序和 Provider Identity 可验证。

### 测试

- 深度不可变；
- JSON round-trip；
- 非 JSON 对象拒绝；
- Native Item 顺序；
- 不同 Provider Native Item 隔离；
- CancellationToken 幂等。

### 不允许顺带实现

```text
序列化到任何厂商协议
ConversationManager
RunState
Storage
```

### 推荐提交边界

```text
t01-02: define provider core contract
```

---

## Task 3：打通 Headless Application 和 Fake Provider

### 目标

先建立最小可测试调用链。

### 前置条件

Task 2 完成。

### 涉及文件

```text
src/uthcode/application.py
src/uthcode/integrations/providers/fake.py
tests/test_application.py
```

### 完成结果

```text
UthCodeApplication
    → ProviderPort
    → FakeProvider
    → Stream Events
```

Application 必须验证：

- 正常流恰好出现一个 `GenerationCompleted`；
- 流提前结束时抛出 `InvalidProviderResponseError`；
- 终态之后继续出现事件时抛错；
- 显式取消产生 `GenerationCancelled`；
- `asyncio.CancelledError` 保持 Python 原生取消语义。

### 测试

```text
Headless 文本流
Tool Call 流
Usage
完成原因
异常终态
显式取消
Task 取消
```

### 不允许顺带实现

```text
Provider Factory
真实 Provider
Agent Loop
Tool 执行
```

### 推荐提交边界

```text
t01-03: add headless application and fake provider
```

---

## Task 4：实现 Pydantic AI Direct 共用适配器

### 目标

完成 UthCode Core Contract 与 Pydantic AI Direct Model API 的唯一桥接层。

### 前置条件

Task 3 完成。

### 涉及文件

```text
src/uthcode/integrations/providers/pydantic_ai.py
tests/test_architecture_boundaries.py
```

### 完成结果

共用适配器负责：

1. UthCode `GenerationRequest` 转 Pydantic Model Request；
2. Tool Schema 转换；
3. Model Stream Event 转 UthCode Event；
4. Pydantic `provider_details` 转 JSON-safe Native Item；
5. Usage 和 Finish Reason 标准化；
6. Pydantic/SDK 异常转 UthCode 异常；
7. 流取消和资源关闭；
8. 检查合法终态。

协议特有字段不在该文件硬编码，交给对应 Codec。

### 测试

- Core 导入不触发 Pydantic；
- Pydantic 类型不进入 UthCode Event；
- Provider Details 为 JSON-safe；
- 异常消息不包含 API Key；
- Application 不依赖具体 Model 类型。

### 不允许顺带实现

```text
Pydantic AI Agent
Tool 执行
自动重试 Agent Loop
消息持久化
```

### 推荐提交边界

```text
t01-04: add direct model integration boundary
```

---

## Task 5：实现 Anthropic Integration

### 目标

支持 Anthropic 文本、Tool Use、Usage 和 Extended Thinking。

### 前置条件

Task 4 完成。

### 涉及文件

```text
src/uthcode/integrations/providers/anthropic.py
tests/test_anthropic_integration.py
```

### 必须覆盖

```text
text delta
thinking delta
thinking signature
redacted thinking
tool_use
tool_result
stop reason
cache read/write usage
authentication error
rate limit
network error
cancel
```

### 往返要求

构造一次包含以下内容的 Mock 响应：

```text
thinking
→ signature
→ tool_use
```

将完成的 `ProviderResponse.message` 重新放入下一次 `GenerationRequest`，验证：

- Thinking 顺序不变；
- Signature 字节内容不变；
- Tool Use ID 和参数不变；
- 未转成普通文本；
- 未发送给非 Anthropic Provider。

### 不允许顺带实现

```text
Anthropic Prompt Cache 策略优化
模型列表发现
Context Window 远端查询
```

### 推荐提交边界

```text
t01-05: add anthropic direct model integration
```

---

## Task 6：实现 OpenAI Responses Integration

### 目标

支持 Responses API 的有序原生 Item、Reasoning 和 Function Call。

### 前置条件

Task 4 完成。

### 涉及文件

```text
src/uthcode/integrations/providers/openai_responses.py
tests/test_openai_responses_integration.py
```

### 必须覆盖

```text
output_text delta
reasoning item
reasoning summary
function_call arguments delta
function_call complete
function_call_output
response item ID
call ID
output index
usage details
completed
incomplete
failed
EOF without terminal
cancel
```

### 流聚合规则

```text
key = item_id + output_index + call_id
```

不得只按 Tool 名称或全局当前 Tool Call 聚合。

### 终态规则

以下情况必须失败：

- 流无 `completed / incomplete / failed`；
- Terminal 到达时仍有未完成 Function Call；
- 同一 Item 被完成后内容发生冲突；
- Provider 返回非 JSON-safe details。

相同 Item 在 Delta、Done 和 Terminal Snapshot 重复出现时必须去重。

### 不允许顺带实现

```text
Responses WebSocket
previous_response_id Session 优化
服务端 Conversation State
Context Compaction
```

### 推荐提交边界

```text
t01-06: add openai responses integration
```

---

## Task 7：实现 OpenAI-compatible Integration

### 目标

支持 OpenAI Chat Completions 兼容端点。

### 前置条件

Task 4 完成。

### 涉及文件

```text
src/uthcode/integrations/providers/openai_compat.py
tests/test_openai_compat_integration.py
```

### 必须覆盖

```text
自定义 base_url
system message
text delta
assistant.tool_calls
tool call index
function name
function arguments
role=tool
tool_call_id
finish_reason
usage
cached tokens
error
cancel
```

### 明确格式

Tool Definition：

```json
{
  "type": "function",
  "function": {
    "name": "...",
    "description": "...",
    "parameters": {}
  }
}
```

Tool Result：

```json
{
  "role": "tool",
  "tool_call_id": "...",
  "content": "..."
}
```

不得将 Responses 的：

```text
function_call
function_call_output
```

直接用于 Chat Completions 请求。

### 不允许顺带实现

```text
兼容所有非标准厂商扩展
特定国产模型补丁
Provider 名称硬编码兼容表
```

只有测试或真实端点证明确有差异时，才能增加有界兼容逻辑。

### 推荐提交边界

```text
t01-07: add openai compatible chat integration
```

---

## Task 8：实现配置与 Provider Factory

### 目标

统一构造 Fake 和三个真实 Provider。

### 前置条件

Task 5—Task 7 完成。

### 涉及文件

```text
src/uthcode/config.py
src/uthcode/integrations/providers/factory.py
src/uthcode/integrations/providers/__init__.py
tests/test_provider_factory.py
```

### 配置字段

```text
kind
model
api_key_env
base_url
max_output_tokens
```

允许的 `kind`：

```text
fake
anthropic
openai_responses
openai_compat
```

### Secret 规则

- 配置只保存环境变量名；
- API Key 仅在 Factory 构造阶段读取；
- 缺失 Secret 时抛出 `MissingSecretError`；
- 错误文本可以包含环境变量名；
- 错误、日志、repr 不得包含真实 Key；
- Fake 不需要 Secret；
- OpenAI-compatible 必须显式配置 base URL。

### 测试

- 四种 Provider 构造；
- 构造不发网络；
- 未知 kind 拒绝；
- 缺失 Secret 安全失败；
- Provider 实例状态互相隔离；
- Core 不导入 Factory。

### 不允许顺带实现

```text
config.toml 加载
用户级和项目级配置合并
Permission 配置
模型自动发现
```

### 推荐提交边界

```text
t01-08: add provider configuration and factory
```

---

## Task 9：收敛文档与架构验收

### 目标

确认 Day1 没有带入未来能力和旧架构。

### 前置条件

Task 1—Task 8 全部完成。

### 涉及文件

```text
README.md
tests/test_architecture_boundaries.py
```

### 必须检查

```text
src/uthcode/core 不导入 integrations
src/uthcode/application 不导入 Pydantic AI 或厂商 SDK
Core 中不出现 Provider 名称分支
项目不依赖 LangGraph 或 LangChain
项目不导入 mewcode
项目不导入旧 UthCode
项目不存在未来模块目录
测试不访问网络
```

### 推荐提交边界

```text
t01-09: finalize day1 architecture boundaries
```

---

## 9. 测试矩阵

| 能力 | Fake | Anthropic | Responses | OpenAI-compatible | 测试文件 |
| --- | --- | --- | --- | --- | --- |
| 项目可安装 | — | — | — | — | `test_package.py` |
| Core 独立导入 | ✓ | ✓ | ✓ | ✓ | `test_architecture_boundaries.py` |
| Headless 调用 | ✓ | — | — | — | `test_application.py` |
| 文本流 | ✓ | ✓ | ✓ | ✓ | 四个 Provider 测试 |
| Reasoning Delta | 可脚本化 | ✓ | ✓ | 能力存在时映射 | 协议测试 |
| Tool Call Start/Delta/Complete | ✓ | ✓ | ✓ | ✓ | 协议测试 |
| Tool Result 请求转换 | ✓ | `tool_result` | `function_call_output` | `role=tool` | 协议测试 |
| Usage | ✓ | ✓ | ✓ | ✓ | 协议测试 |
| Cache Usage | 可脚本化 | ✓ | ✓ | 支持时映射 | 协议测试 |
| 完成原因 | ✓ | ✓ | ✓ | ✓ | 协议测试 |
| Authentication Error | 可脚本化 | ✓ | ✓ | ✓ | 协议测试 |
| Rate Limit | 可脚本化 | ✓ | ✓ | ✓ | 协议测试 |
| Network Error | 可脚本化 | ✓ | ✓ | ✓ | 协议测试 |
| 显式取消 | ✓ | ✓ | ✓ | ✓ | 协议测试 |
| Task 取消 | ✓ | ✓ | ✓ | ✓ | 协议测试 |
| Native Item JSON-safe | ✓ | ✓ | ✓ | ✓ | `test_provider_contract.py` |
| Native Item 顺序 | ✓ | ✓ | ✓ | ✓ | 协议测试 |
| 同 Provider 往返 | ✓ | ✓ | ✓ | ✓ | 协议测试 |
| 跨 Provider 原生项隔离 | ✓ | ✓ | ✓ | ✓ | `test_provider_contract.py` |
| Anthropic Signature | — | ✓ | — | — | `test_anthropic_integration.py` |
| Anthropic Redacted Thinking | — | ✓ | — | — | `test_anthropic_integration.py` |
| Responses Reasoning Item | — | — | ✓ | — | `test_openai_responses_integration.py` |
| Responses 交错 Tool Call | — | — | ✓ | — | `test_openai_responses_integration.py` |
| Responses 异常 EOF | — | — | ✓ | — | `test_openai_responses_integration.py` |
| Chat indexed Tool Call | — | — | — | ✓ | `test_openai_compat_integration.py` |
| Chat `role=tool` | — | — | — | ✓ | `test_openai_compat_integration.py` |
| SDK 类型不越界 | ✓ | ✓ | ✓ | ✓ | `test_architecture_boundaries.py` |
| 无 LangGraph | ✓ | ✓ | ✓ | ✓ | `test_architecture_boundaries.py` |
| 无旧项目依赖 | ✓ | ✓ | ✓ | ✓ | `test_architecture_boundaries.py` |

真实 Provider 测试必须：

```text
Mock Pydantic AI Model / Stream
不读取真实 API Key
不建立 HTTP 连接
不依赖外部模型服务
```

---

## 10. 验收标准

Day1 只有同时满足以下条件才算完成。

### 10.1 工程验收

```bash
python -m pip install -e ".[dev]"
python -m compileall src tests
pytest -q
```

全部成功。

### 10.2 Headless 验收

```bash
pytest -q tests/test_application.py
```

必须证明：

- 无 CLI、TUI、stdin 或 stdout；
- Fake Provider 可以完成一次请求；
- 调用方能够逐个接收事件；
- 取消能够中断流；
- 异常流不会生成伪造成功终态。

### 10.3 Core 独立性验收

在阻止以下模块导入的情况下：

```text
pydantic_ai
openai
anthropic
```

以下导入仍成功：

```python
import uthcode
import uthcode.core
import uthcode.application
```

### 10.4 Provider 边界验收

必须证明：

- Core 公共签名中没有 Pydantic AI 或 SDK 类型；
- Application 不感知 Provider 名称；
- Provider Factory 分支只存在于 Integration；
- Provider 特有字段只存在于 JSON-safe Native Item 或 Integration 内；
- 同 Provider 可恢复完整原生项；
- 不同 Provider 不接收不属于自己的原生项。

### 10.5 三 Provider 验收

#### Anthropic

```text
thinking + signature + tool_use
```

能够保存并在下一次 Anthropic 请求中恢复。

#### OpenAI Responses

```text
reasoning + function_call + function_call_output
```

能够保持 Item 顺序、ID 和调用关系。

#### OpenAI-compatible

```text
assistant.tool_calls
+
role=tool
+
tool_call_id
```

能够正确序列化和流式聚合。

### 10.6 范围验收

项目中不得出现：

```text
langgraph
langchain
StateGraph
GraphState
Node
Edge
Reducer
Checkpoint
mewcode runtime import
旧 UthCode runtime import
未来能力空目录
Tool 假执行
Permission 假实现
Prompt 占位
```

### 10.7 可继续设计验收

完成 Day1 后，后续任务可以直接使用：

```text
GenerationRequest
Message
ToolDefinition
ProviderEvent
ProviderResponse
ProviderPort
UthCodeApplication
```

继续实现真实 System Prompt、Tool 系统和 Agent Loop，无需推翻：

- Provider Port；
- Core 数据类型所有权；
- SDK 隔离边界；
- Headless Application API；
- Provider 特有数据保存方式。

---

## 11. 编码停止条件

后续编码代理遇到以下情况必须停止并报告：

1. 实现与 `AGENTS.md`、`SRe-AGENTS.md` 或本任务书中的用户拍板冲突；
2. Pydantic AI Direct Model API 无法保留某个协议必需的原生字段；
3. 必须让 Pydantic AI、OpenAI 或 Anthropic 类型进入 Core 才能继续；
4. 必须使用 Pydantic AI Agent、Pydantic Graph、LangGraph 或通用工作流框架；
5. 必须扩大到 System Prompt、Tool 执行、Agent Loop、Permission 或其他后续 Day；
6. 必须长期兼容旧 UthCode API；
7. 必须整文件复制旧 UthCode 或 MewCode；
8. 实际文件范围明显超过本任务书目录树；
9. Anthropic Thinking 签名或 Redacted Thinking 无法安全往返；
10. OpenAI Responses Reasoning Item 或 Function Call 无法保持顺序和 ID；
11. OpenAI-compatible 端点必须加入宽泛、无证据的厂商补丁；
12. 两项冻结决策发生实质冲突；
13. Provider 是否已产生外部副作用无法确认，禁止盲目重试。

以下情况不属于停止条件，应自行解决：

```text
普通类型错误
普通编译错误
测试失败
Mock 构造问题
局部命名问题
私有函数拆分问题
lint 或格式问题
```

---

## 12. 最终范围冻结

```text
Day1 =
可安装项目骨架
+
无界面 Application API
+
UthCode 自有 Provider Contract
+
Fake Provider
+
Pydantic AI Direct Model API
+
Anthropic Integration
+
OpenAI Responses Integration
+
OpenAI-compatible Integration
+
协议特有数据安全往返
+
无网络完整测试
```

```text
Day1 ≠
Agent
Agent Loop
Tool 执行
System Prompt
Permission
Context
Memory
Session
Persistence
CLI
TUI
未来占位
```
