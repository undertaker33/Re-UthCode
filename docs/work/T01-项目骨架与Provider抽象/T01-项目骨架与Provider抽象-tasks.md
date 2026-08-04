# T01-项目骨架与Provider抽象 Tasks

## Worker 分组与执行规则

任务只能在用户显式指派后开始。每组由同一 Worker 按组内顺序严格串行完成；未完成前置组时不得开始后续组。

| Worker 组 | Task | 串行理由 |
| --- | --- | --- |
| Foundation Worker | Task 1—Task 4 | 项目骨架、Core 契约、Application 与 Direct 边界共同冻结基础依赖方向 |
| Protocol Worker | Task 5—Task 7 | 三个物理协议模块共享同一边界约定，需要统一 Native Item 与流映射规则 |
| Delivery Worker | Task 8—Task 11 | 配置、正式接入、端到端验证和遗留清理必须基于完整协议能力收口 |

所有 Python、安装和测试命令均在 Conda 环境 `re-uthcode` 中运行。不得修改旧 UthCode 或 MewCode；不得自动移动本工作包到归档目录。

## Task 1：建立可安装项目骨架

### 任务目标

建立 Python 3.12 的最小可安装 src-layout 工程，声明已确认的生产与开发依赖，并保持根包导入无副作用。

### 新增文件

- `pyproject.toml`：项目元数据、Python 版本范围、构建后端、Pydantic AI 2.22 次版本依赖、dev 依赖组和 pytest 配置；
- `README.md`：Day1 范围、Conda 环境用法、安装测试命令和 Headless 定位；
- `.gitignore`：忽略缓存、构建产物、虚拟环境、本地环境文件与测试缓存；
- `.env.example`：只列出允许使用的秘密环境变量名称，不包含值；
- `src/uthcode/__init__.py`：轻量根包入口与版本信息；
- `tests/test_package.py`：安装、导入、副作用和范围测试。

### 修改文件

无。

### 删除文件

无。

### 依赖任务

无。

### 参考资料定位

- 当前需求：第 4 节目标目录树、第 7 节第三方依赖、第 10.1 节工程验收；
- `SRe-AGENTS.md`：第 1、3、5、8、13 节；
- Pydantic AI 安装文档：OpenAI 与 Anthropic extra；
- 已验证环境：Python 3.12.13、Pydantic AI Slim 2.22.0、pytest 9.1.1、pytest-asyncio 1.4.0。

### 完成边界

- editable install 和根包导入成功；
- 不创建空的 `core/`、`application/`、`integrations/` 或 `interfaces/`；这些目录只在首次加入真实职责文件的 Task 中创建；
- 不实现 Provider 模型、Application、CLI、Prompt、Tool 或 Runtime；
- 不直接声明 OpenAI、Anthropic、HTTPX、Pydantic Graph 等传递依赖；
- 不创建任何未来能力目录。

## Task 2：定义 Provider 核心契约

### 任务目标

建立 UthCode 自有的 Provider 数据与行为契约，保证深度不可变、JSON-safe、协议顺序稳定且不泄漏第三方类型。

### 新增文件

- `src/uthcode/core/__init__.py`：显式导出稳定 Core 公共类型；
- `src/uthcode/core/provider.py`：集中定义请求、消息内容、Native Item、工具描述、响应、流事件、用量、完成原因、错误、取消与 Provider Port；
- `tests/test_provider_contract.py`：不可变性、JSON round-trip、非法对象拒绝、顺序、Provider 隔离与取消测试。

### 修改文件

无。

### 删除文件

无。

### 依赖任务

Task 1。

### 参考资料定位

- 当前需求：第 5 节核心数据契约、第 9 节测试矩阵；
- 旧 UthCode：`src/uthcode/conversation/models.py`、`src/uthcode/graph/events.py`、`src/uthcode/providers/types.py`；
- 旧测试：`tests/test_provider_request_contract.py`、`tests/test_provider_services.py`；
- Pydantic AI：消息 Part、流 Part Event 和 Usage 只作为 Integration 映射证据。

### 完成边界

- Core 只依赖标准库；
- Native Item 是 UthCode 自有 JSON-safe 快照，不接受 SDK 或 Pydantic 对象；
- 不实现厂商协议序列化、Conversation Manager、RunState 或 Storage；
- 不保留旧类型名称或兼容别名。

## Task 3：打通 Headless Application 与 Fake Provider

### 任务目标

建立 Application 物理包和最小无界面调用链，并由 Fake Provider 覆盖正常、异常和取消语义。

### 新增文件

- `src/uthcode/application/__init__.py`：Application 包的最小公开出口；
- `src/uthcode/application/generation.py`：只依赖 Core Provider Port 的流式生成用例与流终态校验；
- `src/uthcode/integrations/__init__.py`：Integration 顶层命名空间，与首个真实 Integration 实现同时创建；
- `src/uthcode/integrations/providers/__init__.py`：Provider Integration 命名空间，与 Fake Provider 同时创建；
- `src/uthcode/integrations/providers/fake.py`：可脚本化事件、请求记录、延迟、错误和取消的 Fake Provider；
- `tests/test_application.py`：Headless 文本流、Tool Call、用量、终态、异常 EOF 与取消测试。

### 修改文件

无。

### 删除文件

无。

### 依赖任务

Task 2。

### 参考资料定位

- 当前需求：第 2.3 节最小调用链、Task 3、验收标准 10.2；
- 旧 UthCode：`src/uthcode/providers/fake.py`；
- 旧测试：`tests/test_fake_provider.py`。

### 完成边界

- 成功流恰好接受一个完成终态；
- EOF、重复终态和终态后事件均失败；
- 显式取消与 Python Task 取消保持不同语义；
- Application 生成用例不感知 Provider 名称且不导入 Integration；
- 不实现 Factory、真实 Provider、Agent Loop 或 Tool 执行。

## Task 4：建立 Pydantic AI Direct 集成边界

### 任务目标

建立 Core Contract 与 Pydantic AI Direct Model API 的唯一通用桥接层，并冻结协议模块接口。

### 新增文件

- `src/uthcode/integrations/providers/pydantic_ai.py`：通用请求、工具 Schema、流事件、用量、异常、取消、资源关闭和终态转换；
- `tests/test_architecture_boundaries.py`：静态导入、第三方类型越界、禁止依赖、禁止未来目录和共用边界测试；共用边界可使用 Pydantic AI Test/Function Model，但不能代替厂商协议测试。

### 修改文件

- `src/uthcode/integrations/providers/__init__.py`：维持第三方类型不外露的 Integration 公共边界。

### 删除文件

无。

### 依赖任务

Task 3。

### 参考资料定位

- 当前需求：Task 4、Provider 边界验收；
- Pydantic AI Direct Model Requests：`model_request`、`model_request_stream`；
- 已安装 Pydantic AI 2.22：`pydantic_ai/direct.py`、`pydantic_ai/models/__init__.py`、`pydantic_ai/messages.py`；
- Pydantic AI Provider 生命周期与 HTTP 错误文档。

### 完成边界

- 共用层不包含 Anthropic、Responses 或 Chat 特有字段映射；
- Core 与 Application 不导入 Pydantic AI；
- 不使用 Pydantic AI Agent、Tool 执行、重试 Loop 或 Pydantic Graph；
- Mock 测试不建立网络连接。

## Task 5：实现 Anthropic 协议适配

### 任务目标

以独立物理模块实现 Anthropic 协议转换，保存并恢复 Thinking、签名、Redacted Thinking、Tool Use、Tool Result 与用量细节。

### 新增文件

- `src/uthcode/integrations/providers/anthropic.py`：Anthropic Model 构造、请求/响应 Codec、Native Item 编解码和错误映射；
- `tests/test_anthropic_integration.py`：注入 Mock Anthropic Client/Transport，经过真实 Pydantic AI Anthropic Model 验证协议。

### 修改文件

- `src/uthcode/integrations/providers/pydantic_ai.py`：只接入协议 Codec 扩展点，不加入 Anthropic 分支。

### 删除文件

无。

### 依赖任务

Task 4。

### 参考资料定位

- 当前需求：第 5.3 节 Anthropic、Task 5；
- 旧 UthCode：`src/uthcode/providers/anthropic.py`、`tests/test_anthropic_provider.py`；
- MewCode：`mewcode/client.py` 的 Anthropic 请求和流处理；
- Pydantic AI 2.22：`pydantic_ai/models/anthropic.py` 中 Thinking/Redacted Thinking 响应映射与请求回放；
- DeepSeek Anthropic API 官方兼容文档。

### 完成边界

- 离线测试覆盖文本、Thinking Delta、签名、Redacted Thinking、Tool Use/Result、缓存用量、错误和取消；
- 同协议续轮保持块顺序和不透明签名；
- 不实现 Prompt Cache 策略优化、模型发现或 Context Window 查询；
- Anthropic 协议字段不进入共用桥接层或 Core 类型分支。

## Task 6：实现 OpenAI Responses 协议适配

### 任务目标

以独立物理模块实现 Responses 协议转换，保持 Reasoning、输出 Item、Function Call 与 Function Call Output 的身份、顺序和终态。

### 新增文件

- `src/uthcode/integrations/providers/openai_responses.py`：Responses Model 构造、请求/响应 Codec、Native Item 编解码、终态和错误映射；
- `tests/test_openai_responses_integration.py`：注入 Mock OpenAI Client/Transport，经过真实 Pydantic AI Responses Model 验证协议。

### 修改文件

- `src/uthcode/integrations/providers/pydantic_ai.py`：只接入协议 Codec 扩展点，不加入 Responses 字段分支。

### 删除文件

无。

### 依赖任务

Task 5；协议 Worker 组内严格串行。

### 参考资料定位

- 当前需求：第 5.3 节 OpenAI Responses、Task 6；
- 旧 UthCode：`src/uthcode/providers/openai_responses.py`、`tests/test_openai_responses_provider.py`；
- Pydantic AI 2.22：`pydantic_ai/models/openai.py` 中 Responses Model、流终态、Reasoning 与 Function Call 映射；
- OpenAI Responses API：Streaming Events、Function Calling、Responses 迁移常见错误。

### 完成边界

- 离线测试覆盖交错 Function Call、Reasoning 摘要、重复 Item、incomplete、failed、异常 EOF 和取消；
- 聚合关系不能退化为单一全局 Tool Call 缓冲区；
- 不实现 WebSocket、服务端会话、previous-response 优化或 Context Compaction；
- Responses Item 格式不进入 Chat 模块。

## Task 7：实现 OpenAI-compatible Chat Completions 协议适配

### 任务目标

以独立物理模块实现自定义端点的 Chat Completions 协议转换和索引化 Tool Call 聚合。

### 新增文件

- `src/uthcode/integrations/providers/openai_compat.py`：Chat Model 构造、请求/响应 Codec、Native Item 编解码和错误映射；
- `tests/test_openai_compat_integration.py`：注入 Mock OpenAI-compatible Client/Transport，经过真实 Pydantic AI Chat Model 验证协议。

### 修改文件

- `src/uthcode/integrations/providers/pydantic_ai.py`：只接入协议 Codec 扩展点，不加入 Chat 字段分支。

### 删除文件

无。

### 依赖任务

Task 6；协议 Worker 组内严格串行。

### 参考资料定位

- 当前需求：第 5.3 节 OpenAI-compatible、Task 7；
- 旧 UthCode：`src/uthcode/providers/openai_compat.py`；
- MewCode：`mewcode/client.py` 的 Chat 流聚合、`mewcode/serialization.py` 的 Chat 序列化；
- Pydantic AI OpenAI-compatible Model 与 Model Profile 文档；
- DeepSeek 官方 OpenAI-compatible API 文档。

### 完成边界

- 离线测试覆盖工具定义、assistant Tool Calls、按 index 聚合、Tool Result、Thinking/Reasoning Carrier、用量、错误和取消；
- 只增加测试或真实端点证明必要的有界兼容逻辑；
- 不引入 Provider 名称补丁表；
- Chat 模块不使用 Responses 的 Function Call Item 格式。

## Task 8：实现配置与 Provider 构造

### 任务目标

统一构造 Fake 与三种真实协议 Provider，确保配置只引用秘密来源且构造过程不联网。

### 新增文件

- `src/uthcode/integrations/providers/config.py`：本批次最小 Provider 配置、Provider 种类和秘密环境变量名称校验；
- `src/uthcode/integrations/providers/factory.py`：Integration 内的 Provider 构造选择与秘密读取；
- `tests/test_provider_factory.py`：四类构造、秘密安全、实例隔离和零网络测试。

### 修改文件

- `src/uthcode/integrations/providers/__init__.py`：保持 Integration 内部命名空间，不建立与 Application 竞争的公开组合入口；
- `.env.example`：补齐离线与 live 验收需要的环境变量名称；

### 删除文件

无。

### 依赖任务

Task 7。

### 参考资料定位

- 当前需求：Task 8、第 12 节配置约束；
- 旧 UthCode 实际来源：`src/uthcode/config/models.py`、`src/uthcode/config/loader.py`、`src/uthcode/providers/factory.py`、`tests/test_provider_factory.py`；
- Pydantic AI Provider 构造文档；
- DeepSeek 官方 OpenAI 与 Anthropic base URL 文档。

### 完成边界

- 配置和错误不携带真实 Key；
- Fake 不要求秘密，真实 Provider 在缺失秘密时安全失败；
- OpenAI-compatible 要求显式端点；
- Factory 在本 Task 由测试直接验证，并在 Task 9 获得正式 Application 组合调用方；
- 不实现 config.toml 加载、用户/项目配置合并、权限配置或模型发现。

## Task 9：[接入主流程] 接入正式 Headless 调用链

### 任务目标

在 Application 包内建立唯一公开组合入口，由该入口调用 Integration Factory 并装配生成用例；清理阶段性直连入口，形成唯一 Headless 调用链。

### 新增文件

- `src/uthcode/application/bootstrap.py`：Application 的唯一组合根，调用 Integration Factory 并返回可用的 Headless Application；不得包含 Provider 名称分支。

### 修改文件

- `src/uthcode/application/__init__.py`：只导出 Application 用例、组合入口和调用方必需的 UthCode 配置类型，不导出 SDK 类型；
- `src/uthcode/application/generation.py`：确认生成用例只通过 Provider Port 工作；
- `src/uthcode/integrations/providers/__init__.py`：保持内部命名空间，不额外导出第二个公开组合入口；
- `README.md`：增加 Fake 与真实 Provider 的 Headless 示例、环境激活和测试命令；
- `tests/test_application.py`：从正式构造入口覆盖调用链；
- `tests/test_provider_factory.py`：验证构造结果能进入 Application。

### 删除文件

- 删除 Task 1—Task 8 期间被正式入口替代的临时入口、重复导出或不可达辅助代码；具体目标以实施时 diff 为准，不得删除用户文件。

### 依赖任务

Task 8。

### 参考资料定位

- 当前需求：第 2.3 节最小调用链、验收标准 10.2 和 10.4；
- `SRe-AGENTS.md`：第 5、9、13 节；
- 前序 Task 的正式 API 和测试。

### 完成边界

- Application 生成用例只依赖 Core；Application 组合模块可以依赖 Integration Factory，但不出现 Provider 名称分支；
- 后续 Interface 只需调用 Application 公开组合入口，不需要直接导入 Integration；
- 正式调用链不依赖 CLI、TUI、stdin 或 stdout；
- 不新增 Agent Loop、Tool 执行或 Session；
- Application 是唯一对外组合入口，Integration Factory 是其内部唯一构造实现，无平级重复入口残留。

## Task 10：[端到端验证] 验证离线链路与真实三协议

### 任务目标

从正式 Headless 入口验证完整离线链路和关键失败路径；在用户显式提供凭据后，对 DeepSeek V4 Flash 的三种协议执行真实 smoke 验收。

### 新增文件

无。

### 修改文件

- `pyproject.toml`：注册 live 测试标记并确保普通测试排除网络验收；
- `README.md`：记录 PowerShell 临时环境变量设置、live 测试命令、请求会产生网络和费用的提示；
- `tests/test_architecture_boundaries.py`：阻止普通测试意外联网；
- `tests/test_anthropic_integration.py`：增加显式 live 标记的 Anthropic 真实端点用例；
- `tests/test_openai_responses_integration.py`：增加显式 live 标记的 Responses 真实端点用例；
- `tests/test_openai_compat_integration.py`：增加显式 live 标记的 Chat Completions 真实端点用例。

### 删除文件

无。

### 依赖任务

Task 9。

### 参考资料定位

- 当前需求：第 9 节测试矩阵、第 10 节验收标准；
- DeepSeek 官方首次调用、Anthropic API、Thinking Mode 与当前模型文档；
- OpenAI Responses Streaming Events 与 Function Calling 文档。

### 完成边界

- 普通 `pytest` 全程离线；
- live 测试仅在显式标记和 `DEEPSEEK_API_KEY` 同时存在时运行；
- 使用官方稳定模型 ID `deepseek-v4-flash`，分别验证 Anthropic、Responses 和 Chat Completions；
- live 测试前向用户说明请求数量与费用影响；
- 认证失败、端点差异或协议缺口如实报告，不以跳过断言伪造通过。

## Task 11：[遗留负担清理] 清除兼容层与重复职责

### 任务目标

对完整工作包进行静态与行为审查，删除旧兼容、重复职责、不可达入口和未来占位，确认交付边界可供下一批次直接使用。

### 新增文件

无。

### 修改文件

- `tests/test_architecture_boundaries.py`：补齐旧 API、旧路径、重复入口、禁止依赖、未来目录和物理协议隔离检查；
- `README.md`：仅保留实际已交付能力与正式入口；
- `src/uthcode/**`、`tests/**`：删除审查发现的兼容层、重复实现和不可达代码，不扩大功能范围。

### 删除文件

- 删除任何仅面向旧 UthCode 或 Re:UthCode 早期实现的 Adapter、Facade、别名、包装层、旧入口和不可达文件；
- 删除与成熟依赖重复或与三个物理协议模块职责重叠的实现；
- 删除本批次误建的未来能力占位目录或文件。

### 依赖任务

Task 10。

### 参考资料定位

- `AGENTS.md`：非兼容性原则；
- `SRe-AGENTS.md`：第 2、3、8、13、15 节；
- `docs/work/README.md`：`[遗留负担清理]` 要求；
- 本工作包 spec 的 Out of Scope 与验收标准。

### 完成边界

- 不保留旧类、旧 API、旧行为的兼容逻辑；
- 不保留重复 Provider 协议、重复构造入口或不可达分支；
- Core 不反向依赖 Application 或 Integration；Application 用例不依赖 Integration；Application 组合模块到 Integration 的单向依赖通过静态检查；
- 完整离线测试、编译和依赖检查通过；
- 不自动归档工作包，不执行 Git 提交、推送或 PR 操作。
