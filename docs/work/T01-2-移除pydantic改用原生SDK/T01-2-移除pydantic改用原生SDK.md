# T01-2-移除pydantic改用原生SDK

## 1. 分析基线

### 1.1 仓库基线

| 对象 | 基线 |
| --- | --- |
| Re-UthCode | `2d78b4300a236ada53ac104e547a30df380953ca` |
| 原 UthCode | `1c3507b761e48ac38d846bc39700ce0039f84a04` |
| 已完成前置任务 | `T01-项目骨架与Provider抽象`、`T02-SlashCommand与默认TUI` |
| 原 T01 主任务书 | `docs/work/T01-项目骨架与Provider抽象/T01-项目骨架与Provider抽象.md` |
| 当前开发环境 | Conda 环境 `re-uthcode` |

本任务是已经完成的 T01 Provider Integration 的一次破坏式替换，不重新建设项目骨架，不重新设计 Provider Core，不扩大到后续 Agent Loop、Tool、Permission、Context 或 Memory。

### 1.2 已读取的约束

```text
AGENTS.md
SRe-AGENTS.md
docs/work/README.md
```

本任务遵守以下冻结边界：

- `core` 继续拥有 UthCode 自有请求、消息、事件、响应、Usage、错误和取消模型；
- Provider SDK 类型只能存在于 `integrations`；
- `application` 仍通过 `ProviderPort` 使用 Provider，不感知具体厂商；
- Interface 只能调用 Application API；
- 不兼容被本任务替换的 Pydantic AI Integration 实现；
- 删除被替代的桥接层、测试入口和依赖，不保留双轨逻辑；
- 不修改已冻结的 T01、T02 需求、Spec、Tasks、Prompt 和 Checklist；
- 本次只生成并实施一个独立任务书，不生成完整工作包。

### 1.3 “移除 Pydantic”的准确边界

本任务中的“Pydantic”特指：

```text
Pydantic AI
pydantic-ai
pydantic-ai-slim
pydantic_graph / pydantic-graph
pydantic_ai Python 包及其桥接代码
```

必须完全移除：

- `pydantic-ai-slim[anthropic,openai]` 项目依赖；
- `pydantic_ai`、`pydantic_graph` 的源码和测试导入；
- `PydanticAIProvider`、`PydanticAICodec`、`FunctionModel` 等实现；
- 对 Pydantic AI 私有字段 `_response`、`_source_iter`、`source` 的访问；
- 仅为 Pydantic AI 事件归一化而存在的 Recorder、Codec 和桥接测试；
- Conda 环境 `re-uthcode` 中不再被项目需要的 Pydantic AI 发行包。

**不得把基础包 `pydantic` 视为本任务必须删除的对象。** OpenAI 和 Anthropic 官方 Python SDK 自身使用 Pydantic 数据模型；只要它仍是官方 SDK 的有效依赖，就必须保留。项目业务源码不得直接依赖或导入基础 `pydantic`，但不能为了字面上的“零 Pydantic 包”破坏官方 SDK。

### 1.4 当前实现基线

当前真实 Provider 调用链为：

```text
Application
    ↓
ProviderPort
    ↓
PydanticAIProvider
    ↓
Pydantic AI Model / Provider
    ↓
OpenAI SDK 或 Anthropic SDK
```

当前关键文件：

```text
pyproject.toml
src/uthcode/core/provider.py
src/uthcode/integrations/providers/
├── __init__.py
├── config.py
├── fake.py
├── factory.py
├── pydantic_ai.py
├── anthropic.py
├── openai_responses.py
└── openai_compat.py
```

当前实现已经通过以下机制补回 Pydantic AI 归一化后丢失或弱化的协议数据：

- `PydanticAICodec` 协议扩展点；
- 原始 SDK Stream Recorder；
- Anthropic Thinking Signature 和 Redacted Thinking 重建；
- OpenAI Responses Output Item 记录、去重和终态验证；
- OpenAI-compatible `reasoning_content`、Indexed Tool Call 和原始 Usage 记录；
- Pydantic AI 事件再次转换为 UthCode Event。

本任务不改变这些已经验收的产品行为，只删除中间归一化层，改由三个 Provider Integration 直接消费官方 SDK 请求和流事件。

### 1.5 关键参考来源

#### 当前 Re-UthCode

```text
src/uthcode/integrations/providers/pydantic_ai.py
src/uthcode/integrations/providers/anthropic.py
src/uthcode/integrations/providers/openai_responses.py
src/uthcode/integrations/providers/openai_compat.py
src/uthcode/integrations/providers/factory.py
src/uthcode/integrations/providers/config.py
src/uthcode/core/provider.py

tests/test_provider_factory.py
tests/test_anthropic_integration.py
tests/test_openai_responses_integration.py
tests/test_openai_compat_integration.py
tests/test_architecture_boundaries.py
tests/test_package.py
```

#### 原 UthCode 直接 SDK 实现

```text
src/uthcode/providers/anthropic.py
src/uthcode/providers/openai_responses.py
src/uthcode/providers/openai_compat.py
src/uthcode/providers/factory.py
```

原 UthCode 只作为直接 SDK 流解析、请求序列化和异常处理的行为参考。不得整文件复制，不得恢复其旧 `conversation`、`graph.events`、`LLMProvider` 或旧配置结构。

#### 官方 SDK

本任务以实施时安装的以下直接依赖为准：

```toml
openai>=2.46,<3
anthropic>=0.117,<1
```

使用官方公开 API，不依赖 SDK 私有字段。若实施时解析出的版本高于上述最低版本，必须运行完整测试后才能更新下限；不得无证据放宽到下一个主版本。

---

## 2. T01-2 目标

### 2.1 最终交付

完成后，Re-UthCode 必须具备：

1. 三个真实 Provider 直接使用官方 SDK：
   - Anthropic Messages；
   - OpenAI Responses；
   - OpenAI-compatible Chat Completions；
2. 三个 Provider 各自直接实现 `ProviderPort`；
3. 保持现有 UthCode Core Provider Contract 和 Application API 不变；
4. 保持现有文本、Reasoning、Tool Call、Native Item、Usage、错误、取消和终态行为；
5. 删除 Pydantic AI 共用桥接层和所有对应测试入口；
6. `pyproject.toml` 直接声明 OpenAI 和 Anthropic SDK；
7. `re-uthcode` 环境中移除 Pydantic AI 发行包并通过依赖完整性检查；
8. 默认测试继续完全离线，真实 Provider 构造不得发起网络请求；
9. 已完成的 CLI、TUI、配置加载和 Headless Application 行为不回退。

### 2.2 不交付

本任务不包含：

```text
新增第四种 Provider
统一多厂商 HTTP Client
Provider 自动发现
模型列表查询
模型能力注册表
自动重试策略
Fallback / Router
负载均衡
Provider Plugin 系统
Responses WebSocket
Anthropic Prompt Cache 策略扩展
OpenAI Realtime
Agent Loop
Tool 执行
System Prompt 改造
配置格式改造
TUI / CLI 功能改造
历史工作包重写
```

### 2.3 目标调用链

```text
Interface / Headless Caller
            ↓
       Application API
            ↓
        ProviderPort
   ┌────────┼───────────┐
   ↓        ↓           ↓
Anthropic  OpenAI      OpenAI-compatible
Provider   Responses   Chat Provider
   ↓        ↓           ↓
Anthropic  OpenAI      OpenAI
Async SDK  Async SDK   Async SDK
```

依赖方向保持：

```text
interfaces → application → core
                  ↓
             integrations
```

删除后的调用链中不得再次出现：

```text
Pydantic AI Message
Pydantic AI Model
Pydantic AI Stream Event
Pydantic AI Codec
Pydantic AI Provider
```

---

## 3. 现有 T01 行为处理表

| 现有能力或实现 | 处理 | 新实现方式 | 原因 | 验收方式 |
| --- | --- | --- | --- | --- |
| `ProviderPort` | 保留不动 | 三个原生 SDK Provider 直接实现 | Core 边界已经验收 | Core diff 与类型测试 |
| `GenerationRequest`、`Message`、Part | 保留不动 | Integration 直接序列化为厂商请求 | 不重新设计公共模型 | Provider 请求断言 |
| `ProviderEvent` | 保留不动 | 直接从 SDK Stream Event 映射 | Application 和 TUI 已依赖 | 全事件测试 |
| `NativeItem` | 保留不动 | 从官方 SDK Event/Item 生成 JSON-safe payload | 保留协议保真能力 | 同 Provider 往返测试 |
| `CancellationToken` | 保留不动 | Provider 循环主动检查并关闭 SDK Stream | 保留取消语义 | 显式取消、Task 取消测试 |
| `PydanticAIProvider` | 删除 | 每个真实 Provider 自己实现 `stream()` | 中间层收益不足且增加转换 | 文件不存在、零引用 |
| `PydanticAICodec` | 删除 | 协议逻辑归属对应 Provider 文件 | 避免双重适配 | 文件不存在、零引用 |
| Stream Recorder | 删除 | 直接读取官方 SDK 流事件 | 不再需要访问私有字段 | 私有字段扫描 |
| 通用异常归一化 | 调整 | 共用安全辅助函数 + Provider 显式捕获官方异常 | 不复制秘密文本，不按类名猜测为主路径 | 错误矩阵测试 |
| JSON-safe 校验 | 保留并下沉 | 放入无 SDK 依赖的 Provider 内部辅助模块 | 三个 Provider 都需要 | 非 JSON 值拒绝测试 |
| Anthropic Codec | 删除并重写 | `AnthropicProvider` 直接处理 Messages 事件 | 保留 Signature、Redacted Thinking | Anthropic 往返测试 |
| Responses Codec | 删除并重写 | `OpenAIResponsesProvider` 直接处理 Responses Event | 保留 Item、ID、顺序和终态 | Responses 全矩阵 |
| Chat Codec | 删除并重写 | `OpenAICompatProvider` 直接处理 Chat Chunk | 保留 Indexed Tool Call 和 reasoning carrier | Chat 全矩阵 |
| Provider Factory | 修改 | 直接构造官方 SDK Client 和 Provider | 移除 Pydantic Model/Profile/Settings | 零网络构造测试 |
| `ProviderConfig` / `ProviderKind` | 保留不动 | 继续提供相同配置输入 | T02 配置链已验收 | 配置回归测试 |
| Fake Provider | 保留不动 | 继续作为离线 Application 测试 Provider | 与本任务无关 | Fake 回归测试 |
| T01/T02 文档中的 Pydantic 历史记录 | 保留 | 视为冻结历史证据 | 实施阶段禁止改写 | 文档 diff 检查 |
| Conda 中 Pydantic AI 包 | 删除 | 卸载无调用方发行包 | 避免环境残留掩盖依赖错误 | `pip show` / `find_spec` |
| 基础 `pydantic` 包 | 按 SDK 依赖保留 | 仅由官方 SDK 间接使用 | 官方 SDK 运行依赖 | `pip check` |

---

## 4. 目标目录树

以下只列出本任务涉及的文件：

```text
Re-UthCode/
├── pyproject.toml                                      # 修改
├── README.md                                           # 保留不动
├── src/uthcode/
│   ├── core/provider.py                                # 保留不动
│   ├── application/                                    # 保留不动
│   └── integrations/providers/
│       ├── __init__.py                                 # 保留不动
│       ├── config.py                                   # 保留不动
│       ├── fake.py                                     # 保留不动
│       ├── common.py                                   # 新增
│       ├── factory.py                                  # 修改
│       ├── anthropic.py                                # 迁移后重写
│       ├── openai_responses.py                         # 迁移后重写
│       ├── openai_compat.py                            # 迁移后重写
│       └── pydantic_ai.py                              # 删除
└── tests/
    ├── test_package.py                                 # 修改
    ├── test_provider_factory.py                        # 修改
    ├── test_provider_sdk_common.py                     # 新增
    ├── test_anthropic_integration.py                   # 迁移后重写
    ├── test_openai_responses_integration.py            # 迁移后重写
    ├── test_openai_compat_integration.py               # 迁移后重写
    └── test_architecture_boundaries.py                 # 修改
```

不得创建：

```text
provider_base.py
provider_manager.py
provider_registry.py
provider_router.py
provider_plugin.py
provider_adapter.py
legacy_pydantic.py
compat_pydantic.py
pydantic_shim.py
```

不得为了共享几十行流解析代码建立抽象基类。共享模块只保存与厂商协议无关、已有多个真实调用方的纯辅助逻辑。

---

## 5. 原生 SDK Integration 设计

### 5.1 `common.py`

该文件是 Provider Integration 内部辅助模块，不是新的公共框架。

允许包含：

```text
JSON-safe 深度转换与对象校验
整数 Usage 字段安全读取
异步 Stream close / aclose 兼容关闭
CancellationToken 检查
无秘密的通用兜底错误构造
```

建议内部函数：

```python
def plain_json(value: object) -> JsonValue: ...
def require_json_object(value: object, label: str) -> dict[str, JsonValue]: ...
def usage_int(value: object, label: str, *, default: int = 0) -> int: ...
async def close_stream(stream: object) -> None: ...
def raise_if_cancelled(token: CancellationToken) -> None: ...
```

规则：

- 不导入 `openai`、`anthropic` 或 `pydantic_ai`；
- 不按 Provider 名称分支；
- 不定义 `ProviderPort` 的第二套抽象；
- 不拥有请求序列化、事件聚合或终态判断；
- 不复制 SDK 异常文本；
- 不访问任何以下划线开头的第三方字段。

### 5.2 Anthropic Provider

`anthropic.py` 必须定义直接实现 `ProviderPort` 的 `AnthropicProvider`，并保留 `build_anthropic_provider()` 作为 Factory 和测试使用的真实构造入口。

目标构造边界：

```python
def build_anthropic_provider(
    model_name: str,
    *,
    client: AsyncAnthropic | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    http_client: object | None = None,
    max_output_tokens: int | None = None,
) -> ProviderPort: ...
```

构造过程不得调用模型、模型列表或网络探测。

请求转换必须覆盖：

- System Message 转 Anthropic 顶层 `system`；
- User Message 转 `role=user` Content Blocks；
- Assistant Text、Thinking、Tool Use 按原顺序序列化；
- Tool Result 转 Anthropic `tool_result` Block；
- Tool Definition 转 `name / description / input_schema`；
- `ReasoningOptions` 转官方 Thinking 请求字段；
- 同一 `ProviderIdentity` 的 Native Item 优先恢复 Thinking Signature、Redacted Thinking 和 Tool Use；
- 其他 Provider 的 Native Item 完全忽略，只使用标准 Part。

流处理必须覆盖：

```text
message_start
content_block_start
content_block_delta
content_block_stop
message_delta
message_stop
```

必须产生：

```text
TextDelta
ReasoningDelta
ToolCallStarted
ToolCallArgumentsDelta
ToolCallCompleted
NativeItemCompleted
GenerationCompleted
```

必须保存：

```text
thinking
signature
redacted_thinking
tool_use
text block
content block 顺序
stop_reason
input/output/cache usage
```

终态规则：

- 缺少 `message_stop`：`InvalidProviderResponseError`；
- 缺少非空 `stop_reason`：`InvalidProviderResponseError`；
- Tool JSON 非对象：`InvalidProviderResponseError`；
- Thinking Signature、Redacted Data 类型错误：`InvalidProviderResponseError`；
- 显式取消必须关闭 Stream 后抛出 `GenerationCancelled`；
- `asyncio.CancelledError` 必须关闭 Stream 后原样传播。

### 5.3 OpenAI Responses Provider

`openai_responses.py` 必须定义直接实现 `ProviderPort` 的 `OpenAIResponsesProvider`，并保留 `build_openai_responses_provider()`。

目标构造边界：

```python
def build_openai_responses_provider(
    model_name: str,
    *,
    client: AsyncOpenAI | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    http_client: object | None = None,
    max_output_tokens: int | None = None,
) -> ProviderPort: ...
```

请求转换必须覆盖：

- System Message 合并为 `instructions`；
- User Text 转 Responses Input Message；
- Assistant Native Reasoning、Message、Function Call 按原 `sequence_index` 恢复；
- Tool Result 转 `function_call_output`；
- Tool Definition 转 Responses `type=function` 扁平格式；
- `ReasoningOptions` 转 Responses Reasoning 配置；
- 不得发送 Chat Completions 的 `messages`、`assistant.tool_calls` 或 `role=tool` 格式。

流状态必须至少按以下标识隔离：

```text
item_id
output_index
call_id
sequence_number
```

不得使用单个全局 Tool 参数缓冲区。

必须处理：

```text
response.output_text.delta
response.reasoning_summary_text.delta
response.output_item.added
response.function_call_arguments.delta
response.function_call_arguments.done
response.output_item.done
response.completed
response.incomplete
response.failed
error
```

必须保留：

```text
reasoning item
encrypted_content
reasoning summary
message item
function_call
function_call_output
item id
call id
output index
output item 顺序
usage details
```

去重和冲突规则保持现有行为：

- 相同 Delta、Done 或 Terminal Snapshot 可以重复出现，但只能发布一次；
- 相同身份帧内容冲突必须失败；
- Terminal Snapshot 冲突必须失败；
- Terminal 到达时存在未完成 Function Call 必须失败；
- 无 Terminal 必须失败；
- `incomplete`、`failed` 和 `error` 不得生成成功 `GenerationCompleted`；
- Function Call Arguments 必须解析为 JSON Object。

### 5.4 OpenAI-compatible Chat Provider

`openai_compat.py` 必须定义直接实现 `ProviderPort` 的 `OpenAICompatProvider`，并保留 `build_openai_compat_provider()`。

目标构造边界：

```python
def build_openai_compat_provider(
    model_name: str,
    *,
    base_url: str,
    client: AsyncOpenAI | None = None,
    api_key: str | None = None,
    http_client: object | None = None,
    max_output_tokens: int | None = None,
) -> ProviderPort: ...
```

请求格式必须保持：

```text
system / user / assistant / tool messages
assistant.tool_calls[]
role=tool
tool_call_id
stream=true
stream_options.include_usage=true
```

Tool Definition 必须为：

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

流处理必须覆盖：

- `delta.content`；
- 有界支持 `delta.reasoning_content`；
- `delta.tool_calls[*].index`；
- Tool Call ID、名称和参数可跨多个 Chunk 分批到达；
- `finish_reason`；
- 最终 Usage Chunk；
- `prompt_tokens_details=None`；
- `completion_tokens_details=None`；
- Cached Token 和 Reasoning Token。

Tool Call 聚合必须以 `index` 为主键，每个 Tool Call 独立保存：

```text
id
name
arguments buffer
started
completed
```

终态规则：

- 无任何合法 `finish_reason`：失败；
- `finish_reason=tool_calls` 时所有 Tool Call 必须拥有 ID、名称和 JSON Object 参数；
- 重复完成或冲突完成：失败；
- 不得把 Responses 的 `function_call_output` 格式混入 Chat 请求；
- 不得增加没有真实测试证据的厂商名称补丁表。

### 5.5 错误映射

错误必须在对应 Provider 物理模块中显式捕获官方 SDK 异常。

#### OpenAI

至少映射：

```text
openai.AuthenticationError     → uthcode.AuthenticationError
openai.RateLimitError          → uthcode.RateLimitError
openai.APIConnectionError      → uthcode.NetworkError
openai.APITimeoutError         → uthcode.NetworkError
openai.APIStatusError(401/403) → uthcode.AuthenticationError
其他 APIStatusError            → uthcode.ProviderError
```

#### Anthropic

至少映射：

```text
anthropic.AuthenticationError     → uthcode.AuthenticationError
anthropic.PermissionDeniedError   → uthcode.AuthenticationError
anthropic.RateLimitError          → uthcode.RateLimitError
anthropic.APIConnectionError      → uthcode.NetworkError
anthropic.APITimeoutError         → uthcode.NetworkError
其他 APIStatusError                → uthcode.ProviderError
```

统一安全规则：

- 不把 SDK 异常文本写入 UthCode 异常；
- 不保留可能携带请求或 API Key 的 `cause/context`；
- 使用 `raise ... from None`；
- 允许保存安全的 HTTP Status、Retry-After 数字或分类字段；
- 不保存 Response Body、Headers 全量或 Request 对象。

---

## 6. 文件级任务清单

| 文件路径 | 操作 | 文件职责 | 核心类型/函数 | 允许依赖 | 禁止依赖 | 来源参考 | 对应测试 | 验收条件 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `AGENTS.md` | 保留不动 | 仓库最高级规则 | 无 | 无 | 任何修改 | 当前基线 | diff 检查 | 内容不变 |
| `SRe-AGENTS.md` | 保留不动 | 重构冻结约束 | 无 | 无 | 任何修改 | 当前基线 | diff 检查 | 内容不变 |
| `docs/work/T01-项目骨架与Provider抽象/**` | 保留不动 | 已冻结历史工作包 | 无 | 无 | 删除 Pydantic 历史文字 | 工作包规则 | diff 检查 | 全部不变 |
| `docs/work/T02-SlashCommand与默认TUI/**` | 保留不动 | 已冻结历史工作包 | 无 | 无 | 任何修改 | 工作包规则 | diff 检查 | 全部不变 |
| `pyproject.toml` | 修改 | 生产依赖声明 | `openai`、`anthropic` | 官方 SDK | `pydantic-ai*`、`pydantic-graph` | 官方 SDK、当前依赖 | `test_package.py`、`pip check` | 项目直接安装官方 SDK |
| `README.md` | 保留不动 | 当前安装和使用说明 | 无 | 无 | 无必要改写 | 当前基线 | README 命令回归 | 现有命令仍正确 |
| `src/uthcode/core/provider.py` | 保留不动 | Provider 公共契约 | 全部现有公共类型 | 标准库 | 官方 SDK、Pydantic AI | 已完成 T01 | Core 测试 | 无行为和签名变化 |
| `src/uthcode/application/**` | 保留不动 | Application 调用与终态验证 | `UthCodeApplication`、Bootstrap | Core、Factory composition root | SDK 事件类型 | 已完成 T01/T02 | Application/CLI/TUI 回归 | 无 Provider 特有分支 |
| `src/uthcode/integrations/providers/config.py` | 保留不动 | Provider 构造配置 | `ProviderKind`、`ProviderConfig` | 标准库 | SDK Client | 当前基线 | Factory/Configuration 测试 | 配置格式不变 |
| `src/uthcode/integrations/providers/fake.py` | 保留不动 | 离线 Provider | `FakeProvider` | Core | 官方 SDK | 当前基线 | Fake/Application 测试 | 行为不变 |
| `src/uthcode/integrations/providers/common.py` | 新增 | 三个 SDK Provider 共用的纯辅助逻辑 | JSON、Usage、关闭、取消辅助 | Core、标准库 | `openai`、`anthropic`、Provider 分支 | 当前桥接中可复用的无框架逻辑 | `test_provider_sdk_common.py` | 无第二套 Provider 框架 |
| `src/uthcode/integrations/providers/pydantic_ai.py` | 删除 | 被替代的 Pydantic AI 桥接 | 全部删除 | 无 | 保留 Shim、Alias、转发入口 | 当前实现 | 零引用扫描 | 文件不存在 |
| `src/uthcode/integrations/providers/anthropic.py` | 迁移后重写 | 直接 Anthropic Messages Integration | `AnthropicProvider`、`build_anthropic_provider` | Core、common、`anthropic` | `pydantic_ai`、OpenAI 格式 | 当前行为、原 UthCode、官方 SDK | Anthropic 测试 | Thinking/Tool/Usage/取消完整 |
| `src/uthcode/integrations/providers/openai_responses.py` | 迁移后重写 | 直接 OpenAI Responses Integration | `OpenAIResponsesProvider`、`build_openai_responses_provider` | Core、common、`openai` | `pydantic_ai`、Chat 格式 | 当前行为、原 UthCode、官方 SDK | Responses 测试 | Item/ID/去重/终态完整 |
| `src/uthcode/integrations/providers/openai_compat.py` | 迁移后重写 | 直接 Chat Completions Integration | `OpenAICompatProvider`、`build_openai_compat_provider` | Core、common、`openai` | `pydantic_ai`、Responses 格式 | 当前行为、原 UthCode、官方 SDK | Chat 测试 | Indexed Tool/Usage/Reasoning 完整 |
| `src/uthcode/integrations/providers/factory.py` | 修改 | 唯一真实 Provider 构造根 | `create_provider` | config、三个 Provider、Fake | Pydantic Model/Profile/Settings | 当前 Factory | Factory/Bootstrap 测试 | 构造不发网络 |
| `src/uthcode/integrations/providers/__init__.py` | 保留不动 | 空 Integration 包入口 | 当前 `__all__` | 无 | 导出 SDK 类型 | 当前架构 | 架构测试 | 不扩大公共表面 |
| `tests/test_package.py` | 修改 | 包与依赖边界 | 元数据和根包导入 | 标准库 | `pydantic_ai` 测试依赖 | 当前测试 | 自身 | 根包无 SDK 副作用 |
| `tests/test_provider_factory.py` | 修改 | 原生 SDK Provider 构造 | 四 Provider、Secret、零网络 | Provider Integration | Pydantic Model | 当前测试 | 自身 | Identity 与配置保持 |
| `tests/test_provider_sdk_common.py` | 新增 | 共用辅助函数测试 | JSON、Usage、关闭、取消 | Core、common | 官方网络 | 新 common | 自身 | 边界明确 |
| `tests/test_anthropic_integration.py` | 迁移后重写 | 直接 SDK Anthropic Mock 流测试 | 官方 Raw Event、Mock Client | `anthropic` 类型、Core | `pydantic_ai`、Codec | 当前测试 | 自身 | 现有行为等价或更严格 |
| `tests/test_openai_responses_integration.py` | 迁移后重写 | 直接 SDK Responses Mock 流测试 | 官方 Responses Event | `openai` 类型、Core | `pydantic_ai`、Codec | 当前测试 | 自身 | 交错、重复、冲突覆盖 |
| `tests/test_openai_compat_integration.py` | 迁移后重写 | 直接 SDK Chat Mock 流测试 | `ChatCompletionChunk` | `openai` 类型、Core | `pydantic_ai`、Codec | 当前测试 | 自身 | Nullable Usage 回归保留 |
| `tests/test_architecture_boundaries.py` | 修改 | 依赖与残留扫描 | AST、Metadata、Composition Root | 标准库 | `FunctionModel`、Pydantic Bridge | 当前测试 | 自身 | 源码测试零 Pydantic AI |

### 迁移后重写统一要求

所有标记为“迁移后重写”的文件必须：

1. 保留当前已验收的 UthCode 行为和测试意图；
2. 删除 Pydantic AI Message、Model、Provider、Codec 和 Event；
3. 直接使用官方 Async Client 和公开流事件；
4. 不复制原 UthCode 的旧 Core 类型、旧 Event 或旧配置；
5. 不保留临时适配器、旧类别名或双实现开关；
6. 不通过 `Any` 绕过所有协议边界；只允许在 SDK 版本差异或 Mock 注入点有界使用；
7. 不访问第三方对象的私有字段；
8. Provider 特有字段只存在于对应物理模块；
9. 每个完成事件只能发布一次；
10. 所有 Stream 在正常、错误、显式取消和 Task 取消路径都必须关闭。

---

## 7. 第三方依赖与 Conda 环境清理

### 7.1 `pyproject.toml`

生产依赖由：

```toml
"pydantic-ai-slim[anthropic,openai]>=2.22,<2.23"
```

替换为：

```toml
"anthropic>=0.117,<1"
"openai>=2.46,<3"
```

保留现有：

```toml
"textual>=8.2,<9"
"tomlkit>=0.15,<0.16"
```

不得额外直接声明：

```text
pydantic-ai
pydantic-ai-slim
pydantic-graph
httpx（除非项目代码新增了不经 SDK 的真实直接调用）
```

基础 `pydantic` 不应成为 UthCode 的显式生产依赖；由官方 SDK 按其兼容范围解析。

### 7.2 清理顺序

环境清理必须在源码和 `pyproject.toml` 已完成替换后进行，禁止先破坏环境再实施代码。

在 `re-uthcode` 中执行：

```powershell
conda activate re-uthcode

python -m pip uninstall -y pydantic-ai pydantic-ai-slim pydantic-graph
python -m pip install -e . --group dev --upgrade
python -m pip check
```

然后执行发行包检查：

```powershell
python -m pip show pydantic-ai
python -m pip show pydantic-ai-slim
python -m pip show pydantic-graph
```

三条命令都必须报告未安装。

执行导入检查：

```powershell
python -c "import importlib.util; assert importlib.util.find_spec('pydantic_ai') is None"
python -c "import openai, anthropic; print(openai.__version__, anthropic.__version__)"
```

### 7.3 禁止盲目卸载

不得仅因以下包曾被 Pydantic AI 间接使用就盲目删除：

```text
pydantic
pydantic-core
httpx
anyio
sniffio
typing-extensions
certifi
idna
distro
jiter
```

只有在 `pip` 元数据证明某包无任何剩余反向依赖，并且完整测试、`pip check` 均通过时，才允许额外清理。

不得安装 `pip-autoremove` 或其他临时依赖清理工具污染环境。

### 7.4 环境验收记录

实施反馈必须记录：

```text
清理前 openai / anthropic / pydantic-ai-slim 版本
清理后 openai / anthropic 版本
被卸载的 Pydantic AI 发行包
pip check 结果
find_spec('pydantic_ai') 结果
完整 pytest 结果
```

不得记录 API Key、配置文件中的秘密或完整环境变量值。

---

## 8. 实施任务拆分

## Task 1：冻结现有公共行为并建立原生 SDK 辅助边界

### 目标

在不修改 Core 契约的前提下，建立原生 SDK Provider 共用的最小纯辅助模块，并明确当前行为基线。

### 前置条件

- 当前 Commit 为 `2d78b4300a236ada53ac104e547a30df380953ca`；
- `AGENTS.md`、`SRe-AGENTS.md` 和已冻结工作包未修改；
- 当前完整测试结果已记录。

### 涉及文件

```text
src/uthcode/integrations/providers/common.py
tests/test_provider_sdk_common.py
```

### 完成结果

- JSON-safe、Usage 整数、Stream 关闭和取消辅助函数可独立测试；
- `common.py` 不依赖任何厂商 SDK；
- 未创建 Provider Base Class、Manager 或 Registry；
- 当前 Core 和 Application 公共签名未改变。

### 测试

```text
JSON 基础值和嵌套对象
非 JSON 对象拒绝
bool 不得当作 token integer
close / aclose / 无关闭方法
CancellationToken 未取消和已取消
```

### 不允许顺带实现

```text
任何具体 Provider
Factory 改造
依赖卸载
```

### 推荐提交边界

```text
t01-2-01: add native provider sdk common utilities
```

---

## Task 2：一次性替换三个真实 Provider Integration

### 目标

删除 Pydantic AI 调用链，三个 Provider 直接实现 `ProviderPort`。

### 前置条件

Task 1 完成。

### 涉及文件

```text
src/uthcode/integrations/providers/pydantic_ai.py          # 删除
src/uthcode/integrations/providers/anthropic.py            # 重写
src/uthcode/integrations/providers/openai_responses.py     # 重写
src/uthcode/integrations/providers/openai_compat.py        # 重写
src/uthcode/integrations/providers/factory.py              # 修改
pyproject.toml                                              # 修改
```

### 完成结果

```text
ProviderPort
├── AnthropicProvider → AsyncAnthropic
├── OpenAIResponsesProvider → AsyncOpenAI.responses
└── OpenAICompatProvider → AsyncOpenAI.chat.completions
```

必须同时完成：

- 删除所有 Pydantic AI Import；
- 删除 Recorder、Codec 和 Pydantic Model 构造；
- Factory 直接传递 Client 构造参数和 `max_output_tokens`；
- 三个 Builder 构造不发网络；
- Core、Application 和配置模型不变；
- 不出现临时双轨 Provider。

### 测试

本 Task 完成时至少要求：

```text
python -m compileall -q src
现有非 Integration 测试通过
Provider Factory 构造测试完成改写并通过
```

### 不允许顺带实现

```text
新增 Provider
重构配置系统
修改 Application API
修改 TUI
```

### 推荐提交边界

```text
t01-2-02: replace pydantic ai bridge with native provider sdks
```

---

## Task 3：重写三种协议测试并保持行为等价

### 目标

测试直接围绕官方 SDK Client、请求参数和流事件，不再测试 Pydantic AI Codec。

### 前置条件

Task 2 完成。

### 涉及文件

```text
tests/test_anthropic_integration.py
tests/test_openai_responses_integration.py
tests/test_openai_compat_integration.py
tests/test_provider_factory.py
```

### 完成结果

- Mock Client 直接暴露官方 `messages.create`、`responses.create` 或 `chat.completions.create`；
- Mock Stream 支持正常结束、错误、延迟和关闭观测；
- 请求参数直接断言官方协议格式；
- 当前 T01 验收行为全部有测试承接；
- Codec 单元测试转换成 Provider 黑盒流测试或删除；
- 默认测试不读取真实 API Key、不建立网络。

### 测试

分别执行：

```powershell
pytest -q tests/test_anthropic_integration.py
pytest -q tests/test_openai_responses_integration.py
pytest -q tests/test_openai_compat_integration.py
pytest -q tests/test_provider_factory.py
```

### 不允许顺带实现

```text
测试 Pydantic AI 兼容层
保留 Codec 名称用于过渡
修改 Core 预期以迁就 SDK
```

### 推荐提交边界

```text
t01-2-03: validate native sdk provider protocol behavior
```

---

## Task 4：[接入主流程] 收敛 Factory、Application 与架构边界

### 目标

确认正式调用链只经过原生 SDK Provider，并删除所有旧入口。

### 前置条件

Task 3 完成。

### 涉及文件

```text
tests/test_architecture_boundaries.py
tests/test_package.py
```

必要时允许修改：

```text
src/uthcode/integrations/providers/factory.py
```

### 完成结果

- `create_provider()` 仍是唯一正式构造根；
- Application Bootstrap 无需知道官方 SDK 类型；
- `providers/__init__.py` 不导出 SDK Client 或具体 Provider；
- `pydantic_ai.py` 不存在；
- `src` 和 `tests` 中没有 `pydantic_ai`、`PydanticAIProvider`、`PydanticAICodec`、`FunctionModel`；
- Interface 依赖方向不变；
- CLI、TUI、Headless Application 继续通过 Factory 运行。

### 测试

```powershell
pytest -q tests/test_architecture_boundaries.py tests/test_package.py
pytest -q tests/test_application.py tests/test_application_runtime.py
pytest -q tests/test_cli.py tests/test_tui.py
```

若实际 TUI 测试文件名称不同，使用当前仓库真实文件，不新增同义测试文件。

### 推荐提交边界

```text
t01-2-04: connect native providers to the formal application path
```

---

## Task 5：[端到端验证] 验证三 Provider 与现有交互入口

### 目标

从正式入口证明依赖替换没有改变产品行为。

### 前置条件

Task 4 完成。

### 默认离线验证

```powershell
python -m compileall -q src tests
pytest -q
python -m pip check
```

必须覆盖：

- Fake Headless 请求；
- 三个真实 Provider Mock Stream；
- Provider Factory；
- 配置加载；
- `uthcode exec` Fake 模型；
- TUI Fake 模型启动与一次请求；
- Provider 错误和取消在 Application / CLI / TUI 中维持原行为。

### 真实端点验证

真实验证只能在用户已经配置相应 Key，并显式启用 `UTHCODE_RUN_LIVE=1` 时运行。

至少执行当前已经可用的 OpenAI-compatible 真实请求：

```powershell
$env:UTHCODE_RUN_LIVE = "1"
pytest -q tests/test_openai_compat_integration.py -m live
```

Anthropic-compatible 和 Responses Live Test 只有在端点真实支持对应协议时执行，不得为了通过测试伪造协议支持。

真实验证必须确认：

```text
正文增量
合法终态
Usage 可解析
Stream 正常关闭
无重复失败提示
API Key 不进入输出和日志
```

### 推荐提交边界

```text
t01-2-05: verify native provider sdk end-to-end behavior
```

---

## Task 6：[遗留负担清理] 清理源码、测试和 Conda 环境

### 目标

证明 Pydantic AI 已从运行时、测试和 `re-uthcode` 环境中完全退出。

### 前置条件

Task 5 完成。

### 涉及范围

```text
pyproject.toml
src/
tests/
Conda 环境 re-uthcode
```

历史工作包不参与文字清理。

### 必须执行

```powershell
conda activate re-uthcode
python -m pip uninstall -y pydantic-ai pydantic-ai-slim pydantic-graph
python -m pip install -e . --group dev --upgrade
python -m pip check
python -m compileall -q src tests
pytest -q
```

### 残留扫描

```powershell
rg -n "pydantic_ai|PydanticAIProvider|PydanticAICodec|FunctionModel|pydantic_graph" src tests pyproject.toml README.md
```

结果必须为 0 条。

以下扫描只针对运行时代码，不扫描冻结历史文档：

```powershell
rg -n "_response|_source_iter|record_model_stream|provider_details" src/uthcode/integrations/providers
```

要求：

- `_response`、`_source_iter`、`record_model_stream` 为 0 条；
- `provider_details` 只有在官方 SDK 的公开字段确有当前调用方时才允许存在，并须在 Feedback 中解释；
- `src/uthcode/integrations/providers/pydantic_ai.py` 不存在；
- 不存在兼容 Shim、Alias 或双轨开关。

### 环境检查

```powershell
python -m pip show pydantic-ai
python -m pip show pydantic-ai-slim
python -m pip show pydantic-graph
python -c "import importlib.util; assert importlib.util.find_spec('pydantic_ai') is None"
```

### 推荐提交边界

```text
t01-2-06: remove pydantic ai runtime and environment residue
```

---

## 9. 测试矩阵

| 能力 | Fake | Anthropic SDK | OpenAI Responses SDK | OpenAI Chat SDK | 测试文件 |
| --- | --- | --- | --- | --- | --- |
| Core Contract 不变 | ✓ | ✓ | ✓ | ✓ | `test_provider_contract.py`、架构测试 |
| Factory 零网络构造 | ✓ | ✓ | ✓ | ✓ | `test_provider_factory.py` |
| 文本流 | ✓ | ✓ | ✓ | ✓ | Provider 测试 |
| Reasoning Delta | 可脚本化 | Thinking | Summary | `reasoning_content` 有界支持 | Provider 测试 |
| Tool Call Start/Delta/Complete | ✓ | ✓ | ✓ | ✓ | Provider 测试 |
| Tool Result 请求 | ✓ | `tool_result` | `function_call_output` | `role=tool` | Provider 测试 |
| Usage | ✓ | ✓ | ✓ | ✓ | Provider 测试 |
| Cache Usage | 可脚本化 | ✓ | ✓ | Nullable Details | Provider 测试 |
| Native Item JSON-safe | ✓ | ✓ | ✓ | ✓ | Common/Contract/Provider 测试 |
| Native Item 顺序 | ✓ | Content Block | Output Item | Assistant Parts | Provider 测试 |
| 同 Provider 往返 | ✓ | Signature/Tool Use | Reasoning/Call | Reasoning/Tool Calls | Provider 测试 |
| 跨 Provider Native 隔离 | ✓ | ✓ | ✓ | ✓ | Contract/Provider 测试 |
| 合法终态 | ✓ | `message_stop` | `response.completed` | `finish_reason` | Provider 测试 |
| 异常 EOF | 可脚本化 | ✓ | ✓ | ✓ | Provider 测试 |
| 重复终态去重 | 可脚本化 | 按协议需要 | ✓ | 按 Chunk 规则 | Provider 测试 |
| 冲突重复拒绝 | 可脚本化 | 按协议需要 | ✓ | Tool Call 冲突 | Provider 测试 |
| Authentication | 可脚本化 | ✓ | ✓ | ✓ | Provider 测试 |
| Rate Limit | 可脚本化 | ✓ | ✓ | ✓ | Provider 测试 |
| Network / Timeout | 可脚本化 | ✓ | ✓ | ✓ | Provider 测试 |
| 错误无 Secret | ✓ | ✓ | ✓ | ✓ | Provider/架构测试 |
| 显式取消 | ✓ | ✓ | ✓ | ✓ | Provider 测试 |
| Task 取消 | ✓ | ✓ | ✓ | ✓ | Provider 测试 |
| Stream 所有路径关闭 | ✓ | ✓ | ✓ | ✓ | Provider 测试 |
| CLI 回归 | ✓ | 间接 | 间接 | 间接 | CLI 测试 |
| TUI 回归 | ✓ | 间接 | 间接 | 间接 | TUI 测试 |
| 无 Pydantic AI 源码依赖 | ✓ | ✓ | ✓ | ✓ | 架构测试、`rg` |
| 无 Pydantic AI 环境包 | ✓ | ✓ | ✓ | ✓ | `pip show`、`find_spec` |
| 无旧 UthCode 运行时依赖 | ✓ | ✓ | ✓ | ✓ | 架构测试 |

默认测试必须使用官方 SDK 类型构造离线 Event/Chunk，或使用只模拟官方公开 Client 方法的 Test Double。不得通过重新实现一套假 Pydantic Model 来维持旧测试。

---

## 10. 验收标准

T01-2 只有同时满足以下条件才算完成。

### 10.1 工程验收

```powershell
conda activate re-uthcode
python -m pip install -e . --group dev --upgrade
python -m compileall -q src tests
pytest -q
python -m pip check
```

全部成功。

### 10.2 依赖验收

`pyproject.toml` 必须：

- 直接声明 `openai`；
- 直接声明 `anthropic`；
- 不声明 `pydantic-ai`、`pydantic-ai-slim` 或 `pydantic-graph`；
- 不为了代替官方 SDK 新增手写 HTTP 协议依赖。

`re-uthcode` 必须：

- `pydantic-ai` 未安装；
- `pydantic-ai-slim` 未安装；
- `pydantic-graph` 未安装；
- `find_spec('pydantic_ai') is None`；
- `openai`、`anthropic` 可导入；
- `pip check` 无损坏依赖。

### 10.3 源码验收

以下文件不存在：

```text
src/uthcode/integrations/providers/pydantic_ai.py
```

以下标识在 `src`、`tests`、`pyproject.toml`、`README.md` 中为 0 条：

```text
pydantic_ai
PydanticAIProvider
PydanticAICodec
FunctionModel
pydantic_graph
```

冻结历史文档允许保留事实记录，不视为运行时残留。

### 10.4 Core 与 Application 回归

必须证明：

- `core/provider.py` 公共类型和 `ProviderPort` 签名未改变；
- Core 不导入 OpenAI、Anthropic 或基础 Pydantic；
- Application 不导入官方 SDK；
- Interface 不导入 Integration 或官方 SDK；
- `create_provider()` 仍只在 Factory 定义并由 Bootstrap 调用；
- Fake Provider 和现有 T02 交互入口正常运行。

### 10.5 Anthropic 验收

以下完整往返成功：

```text
user
→ thinking
→ signature
→ redacted_thinking
→ text
→ tool_use
→ tool_result
→ 下一次 Anthropic 请求
```

并证明：

- 顺序不变；
- Signature 和 Redacted Data 不变；
- Tool ID、名称和参数不变；
- Usage 和 Stop Reason 正确；
- 缺少 `message_stop` 会失败；
- 取消后 Stream 已关闭。

### 10.6 OpenAI Responses 验收

以下完整往返成功：

```text
reasoning
→ function_call A/B 交错增量
→ message
→ function_call_output
→ 下一次 Responses 请求
```

并证明：

- Item ID、Call ID、Output Index 和顺序不变；
- 重复帧去重；
- 冲突帧失败；
- Unfinished Call 失败；
- `incomplete / failed / error / EOF` 不产生成功终态；
- Usage Details JSON-safe。

### 10.7 OpenAI-compatible 验收

以下完整往返成功：

```text
reasoning_content
→ text
→ 两个 Indexed Tool Call 交错参数
→ role=tool
→ 下一次 Chat Completions 请求
```

并证明：

- Tool Call 按 Index 独立聚合；
- `assistant.tool_calls` 格式正确；
- `role=tool` 和 `tool_call_id` 正确；
- Nullable Usage Details 归一为 0；
- 缺少 `finish_reason` 会失败；
- 不产生 Responses Item 格式。

### 10.8 性能边界验收

本任务不要求建立复杂基准系统，但必须通过一个离线微基准证明没有残留双重事件转换。

微基准只比较当前分支内：

```text
SDK Event / Chunk
→ UthCode ProviderEvent
```

要求：

- 处理 10,000 个纯文本 Delta 时无网络；
- 不创建 Pydantic AI Message/Event；
- 不访问或复制整个 Stream 历史来处理普通 Text Delta；
- Responses 为终态验证保留的有界状态允许存在；
- 结果记录在实施 Feedback，不作为固定硬毫秒门槛。

### 10.9 范围验收

本任务不得改变：

```text
配置 TOML 结构
ProviderKind 值
Model 选择语义
Application Command / Event
CLI 参数
TUI 交互
Fake Provider 行为
System Prompt
Tool 系统
Agent Loop
Permission
```

---

## 11. 编码停止条件

编码代理遇到以下情况必须停止并报告：

1. 必须修改 `ProviderPort`、Core Message/Event 或 Application API 才能使用官方 SDK；
2. 必须扩大到配置格式、TUI、CLI、Agent Loop、Tool 或 Permission；
3. 官方 SDK 的公开 API 无法保留已冻结的 Native Item 数据；
4. 必须访问 OpenAI 或 Anthropic SDK 私有字段才能继续；
5. 必须重新引入 Pydantic AI、LangGraph、LangChain 或通用 Provider 框架；
6. 必须保留 Pydantic AI 和原生 SDK 双轨运行；
7. 必须为旧 Pydantic 类型增加兼容 Adapter、Alias 或 Shim；
8. Anthropic Signature 或 Redacted Thinking 无法原样往返；
9. Responses Item ID、Call ID、Output Index 或顺序无法保留；
10. Chat Tool Call 无法按 Index 正确聚合；
11. 官方 SDK 版本与任务书范围发生主版本不兼容；
12. Conda 环境中有其他已安装项目明确依赖 `pydantic-ai*`，卸载会破坏环境；
13. Provider 请求可能已经产生不可确认的外部副作用，禁止盲目重试；
14. 需要修改冻结的 T01/T02 工作包文件；
15. 实际改动明显超出本任务目录树。

以下情况不属于停止条件，应自行解决：

```text
官方 SDK 类型名称变化
Mock Event 构造问题
普通类型错误
普通测试失败
私有函数拆分
局部状态机实现
格式化和 lint
Usage 可空字段处理
Stream close / aclose 差异
```

---

## 12. 最终范围冻结

```text
T01-2 =
保留 UthCode ProviderPort
+
删除 Pydantic AI Bridge / Codec / Recorder
+
Anthropic 官方 Async SDK 直接接入
+
OpenAI Responses 官方 Async SDK 直接接入
+
OpenAI-compatible Chat 官方 Async SDK 直接接入
+
保持现有协议保真、错误、取消和终态语义
+
重写对应 Mock 与架构测试
+
清理 re-uthcode 中 Pydantic AI 发行包
+
完整回归现有 Application / CLI / TUI
```

```text
T01-2 ≠
重做 Core Provider Contract
重做配置系统
新增 Provider
建立 Provider Plugin / Router / Manager
建立通用 HTTP 协议层
修改 Agent 产品能力
改写冻结历史工作包
生成 Spec / Tasks / Checklist / Prompt / Feedback
```
