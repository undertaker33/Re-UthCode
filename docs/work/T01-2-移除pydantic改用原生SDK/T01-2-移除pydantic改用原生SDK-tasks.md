# T01-2-移除pydantic改用原生SDK Tasks

## Worker 分组与执行规则

任务只能由用户通过对应 Prompt 文件显式派发。每组由同一 Worker 按组内顺序严格串行完成；未完成前置组并经用户决定继续时，不得开始后续组。

| Worker 组 | Task | 串行理由 |
| --- | --- | --- |
| W01 Native SDK Provider Worker | Task 1—Task 3 | 共用辅助边界、三个 Provider 的破坏式替换和协议黑盒测试必须共同维护同一协议语义，禁止中间出现双轨实现 |
| W02 Integration Delivery Worker | Task 4—Task 6 | 正式接入、端到端验收和环境卸载必须在源码与协议测试稳定后统一收口 |

Worker 依赖顺序固定为 W01 → W02。所有 Python、安装和测试命令使用 Conda 环境 `re-uthcode`，优先采用 `conda run --no-capture-output -n re-uthcode ...`。不得修改旧 `D:\project\UthCode`、已冻结 T01/T02 工作包或工作包外功能；不得执行 Git 写入或自动归档。

已验证基线：当前提交为 `2d78b4300a236ada53ac104e547a30df380953ca`，全量测试为 `201 passed, 3 skipped`；环境中 OpenAI 为 `2.53.0`、Anthropic 为 `0.120.2`、Pydantic AI Slim 与 Pydantic Graph 为 `2.22.0`，清理前 `pip check` 通过。

## Task 1：建立原生 SDK 共用辅助边界

### 任务目标

在不修改 Core 契约和任何真实 Provider 的前提下，建立三个原生 SDK Provider 可共同使用的最小纯辅助模块，并用独立测试冻结其边界。

### 新增文件

- `src/uthcode/integrations/providers/common.py`
  - 保存 JSON-safe 深度转换与对象校验、Usage 整数读取、Stream 关闭和 Cancellation Token 检查。
  - 只依赖标准库与现有 Core 类型，不导入任何厂商 SDK，不拥有请求序列化、事件聚合或终态判断。
- `tests/test_provider_sdk_common.py`
  - 独立验证基础值、嵌套 JSON、非法对象、布尔 token 值、同步/异步关闭方法、无关闭方法和取消状态。

### 修改和删除文件

- 无。

### 依赖任务

- 无；必须在基线提交、冻结工作包和全量测试结果确认后开始。

### 参考资料定位

- 原始需求第 3、5.1、6、8 节。
- `src/uthcode/core/provider.py` 中现有 JSON、Usage、取消与错误契约。
- `src/uthcode/integrations/providers/pydantic_ai.py` 中仅可提炼的厂商无关行为，不复制 Pydantic AI 类型或桥接结构。

### 完成边界

- 新辅助函数有直接测试且不依赖 `openai`、`anthropic`、`pydantic_ai`。
- 非 JSON 对象与布尔 token 值被明确拒绝；合法整数与缺省 Usage 行为可观测。
- `close`、`aclose` 和无关闭方法三类对象均有测试，取消检查保持现有 Core 异常语义。
- 未创建 Provider Base Class、Manager、Registry、Router、Adapter 或未来占位。
- 未修改任何具体 Provider、Factory、项目依赖或环境。

## Task 2：替换三个真实 Provider Integration

### 任务目标

一次性删除 Pydantic AI 调用链，使 Anthropic、OpenAI Responses 和 OpenAI-compatible Chat 三个 Provider 直接实现现有 `ProviderPort`，并切换项目依赖与唯一 Factory。

### 新增文件

- 无。

### 修改文件

- `src/uthcode/integrations/providers/anthropic.py`
  - 重写为直接使用 `AsyncAnthropic.messages.create(..., stream=True)` 的 Integration。
  - 实现 Core 请求到 Anthropic Messages 的序列化、公开流事件到 Provider Event 的映射、Native Item 往返、Usage/Stop Reason、取消关闭和官方异常映射。
- `src/uthcode/integrations/providers/openai_responses.py`
  - 重写为直接使用 `AsyncOpenAI.responses.create(..., stream=True)` 的 Integration。
  - 按 item id、output index、call id 与 sequence number 维护有界状态，处理 Reasoning、Message、Function Call、重复/冲突帧、失败终态和 Usage。
- `src/uthcode/integrations/providers/openai_compat.py`
  - 重写为直接使用 `AsyncOpenAI.chat.completions.create(..., stream=True)` 的 Integration。
  - 维护 Chat 消息格式、Reasoning Content、按 index 隔离的 Tool Call 聚合、最终 Usage 与合法 Finish Reason。
- `src/uthcode/integrations/providers/factory.py`
  - 保持唯一 `create_provider()` 构造根，直接传递官方 Client 构造参数和最大输出 token 配置。
  - 保持 Fake、Secret、显式 OpenAI-compatible Base URL 和零网络构造语义。
- `pyproject.toml`
  - 删除 Pydantic AI Slim 直接依赖，直接声明 Anthropic 与 OpenAI 官方 SDK 版本范围。
  - 不新增直接 `httpx` 依赖或其他协议框架。

### 删除文件

- `src/uthcode/integrations/providers/pydantic_ai.py`
  - 删除 Bridge、Codec、Recorder、Pydantic Model/Event 转换和第三方私有字段访问，不保留 Shim、Alias 或转发入口。

### 依赖任务

- Task 1 完成并通过其独立测试。

### 参考资料定位

- 原始需求第 3—7、8 节及错误矩阵。
- 当前三个 Provider、Factory、Core Provider 契约及对应 Integration 测试。
- 只读参考仓库 `D:\project\UthCode` 提交 `1c3507b761e48ac38d846bc39700ce0039f84a04` 下三个直接 SDK Provider 与 Factory；只参考流解析、序列化和异常处理事实，不复制旧 Core、Conversation、Graph Event、配置或 Provider 抽象。
- Anthropic 和 OpenAI 官方 Python SDK 的公开 Client、请求参数与流事件类型。

### 完成边界

- 三个 Provider 直接满足原有 `ProviderPort`，Core Provider 文件、Application API、配置模型、Fake Provider、CLI 和 TUI 未修改。
- Anthropic 完整保存 Thinking、Signature、Redacted Thinking、Text、Tool Use、Content Block 顺序、Stop Reason 和 Usage。
- Responses 完整保存 Reasoning、Encrypted Content、Summary、Message、Function Call、标识、顺序、Usage，并拒绝冲突、失败、不完整或无终态流。
- Chat 保持 `system/user/assistant/tool`、`assistant.tool_calls`、`role=tool`、`tool_call_id` 格式，Tool Call 按 index 独立聚合并处理 Nullable Usage。
- 三个 Builder 构造不发网络；所有流在正常、错误、显式取消和 Task 取消路径关闭。
- 官方 SDK 异常被安全分类，不复制第三方异常文本、请求、响应体、完整 Header 或秘密。
- 源码中不再导入 Pydantic AI，不访问第三方私有字段，不存在双轨 Provider。
- `python -m compileall -q src`、现有非 Integration 测试和改写后的 Factory 构造测试通过。
- 本 Task 不卸载 Conda 环境发行包；环境清理留给 Task 6。

## Task 3：重写协议测试并保持行为等价

### 任务目标

删除 Codec 与 Pydantic AI 测试入口，围绕官方 SDK Client、公开请求参数和公开流事件重写三种协议测试，承接全部既有行为和关键失败路径。

### 新增和删除文件

- 无；旧 Codec 专用测试应在对应文件内转换为 Provider 黑盒测试或删除，不创建同义测试文件。

### 修改文件

- `tests/test_anthropic_integration.py`
  - 使用官方 Raw Event 类型或只模拟 `messages.create` 的 Test Double。
  - 覆盖 Thinking、Signature、Redacted Thinking、Text、Tool Use/Result、顺序、Usage、缺失终态、错误、显式取消、Task 取消和流关闭。
- `tests/test_openai_responses_integration.py`
  - 使用官方 Responses Event 类型或只模拟 `responses.create` 的 Test Double。
  - 覆盖 Reasoning、Message、A/B 交错 Function Call、Item/Call/Index/顺序、重复去重、冲突、Unfinished Call、失败终态、EOF、Usage、取消和关闭。
- `tests/test_openai_compat_integration.py`
  - 使用官方 `ChatCompletionChunk` 或只模拟 `chat.completions.create` 的 Test Double。
  - 覆盖 Reasoning Content、Text、两个 Indexed Tool Call、Tool Result、Nullable Usage、缺失 Finish Reason、冲突、取消和关闭。
- `tests/test_provider_factory.py`
  - 删除 Pydantic Model 构造断言，验证四类 Provider Identity、Secret、安全错误和官方 Client 零网络构造。

### 依赖任务

- Task 2 完成；测试必须针对单一原生 SDK 实现，不得为过渡保留 Pydantic AI 测试路径。

### 参考资料定位

- 原始需求第 3、5、6、8、9、10.5—10.7 节。
- 当前四个测试文件的已验收测试意图。
- 官方 SDK 公开事件类型和请求参数；不得访问第三方私有字段。

### 完成边界

- Mock Client 只暴露官方公开方法；Mock Stream 可观测正常结束、错误、延迟和关闭。
- 请求断言直接对应各厂商协议，不复刻 Pydantic AI Message、Model、Codec 或 Event。
- 三种协议的正常路径、关键失败路径、Native Item 同 Provider 往返与跨 Provider 隔离均有直接测试。
- 默认测试不读取真实 API Key、不建立网络；live 测试仍受显式环境开关保护。
- 分别运行三个 Provider 测试和 Factory 测试均通过。

## Task 4：[接入主流程] 收敛构造与架构边界

### 任务目标

确认正式 Application 调用链只经过唯一 Factory 和三个原生 SDK Provider，删除旧入口并用架构测试固定依赖方向与包边界。

### 新增和删除文件

- 无。

### 修改文件

- `tests/test_architecture_boundaries.py`
  - 删除 `FunctionModel`、Pydantic AI Bridge/Codec 测试，改为验证原生 SDK 依赖只位于对应 Integration、唯一 Factory、无私有字段访问和无旧标识。
- `tests/test_package.py`
  - 验证根包不导出或触发官方 SDK Client/具体 Provider，不再依赖 Pydantic AI 测试环境。
- `src/uthcode/integrations/providers/factory.py`
  - 仅在前述测试发现正式组合根缺口时允许窄幅修正，不扩大配置或 Application API。

### 依赖任务

- Task 3 完成且三种协议测试通过。

### 参考资料定位

- 原始需求第 1.2、2.3、4、6、8、10.3—10.4 节。
- `src/uthcode/application` 正式 Bootstrap、Factory、Provider 包入口和现有架构测试。

### 完成边界

- `create_provider()` 仍只在 Factory 定义并由 Bootstrap 使用。
- Core 不导入 OpenAI、Anthropic 或基础 Pydantic；Application 不导入官方 SDK；Interface 不导入 Integration 或官方 SDK。
- Provider 包入口不导出 SDK Client 或具体 Provider，旧桥接文件和标识不存在。
- CLI、TUI、Headless Application、配置与 Fake Provider 回归测试通过。
- 不新增兼容入口、第二 Factory、第二 Provider 抽象或 Provider 名称分支。

## Task 5：[端到端验证] 验证三 Provider 与现有交互入口

### 任务目标

从正式入口证明原生 SDK 替换未改变产品行为，并通过离线微基准确认普通流事件不再经过双重转换。

### 新增、修改和删除文件

- 原则上无。
- 仅允许为修复本任务范围内的真实接入缺陷修改 Task 2—Task 4 已列文件及其既有测试；不得扩大到 Core、Application API、配置格式、CLI 或 TUI 功能。

### 依赖任务

- Task 4 完成且正式调用链、架构边界与交互回归通过。

### 参考资料定位

- 原始需求第 8 Task 5、9、10.1、10.4—10.9 节。
- `tests/test_application*.py`、`tests/test_cli.py`、`tests/test_tui.py`、配置和 Provider 测试中的正式入口场景。

### 完成边界

- 默认离线完成 Fake Headless、三个真实 Provider Mock Stream、Factory、配置、`uthcode exec` Fake 模型和 TUI Fake 请求验证。
- Provider 错误、显式取消和 Task 取消经 Application、CLI、TUI 保持既有分类、终态和输出行为。
- `python -m compileall -q src tests`、全量 `pytest -q` 和 `python -m pip check` 通过，live 测试默认跳过。
- 离线处理 10,000 个纯文本 Delta，不访问网络、不创建 Pydantic AI 对象、不复制整个 Stream 历史；记录吞吐用时和实现观察，不设硬毫秒阈值。
- 只有用户已配置相应 Key 并显式设置 `UTHCODE_RUN_LIVE=1` 时才运行真实端点测试；未经授权不得执行。
- 不为了通过验证降低断言、伪造协议支持或修改冻结产品语义。

## Task 6：[遗留负担清理] 清理源码、测试和 Conda 环境

### 任务目标

证明 Pydantic AI 已从运行时、测试、项目依赖和 `re-uthcode` 环境完全退出，同时保留官方 SDK 所需共享依赖并清理兼容负担。

### 新增、修改和删除文件

- 原则上无；只允许清理 Task 1—Task 5 范围内发现的旧引用、不可达代码、重复职责或测试残留。
- 环境操作仅限 Conda 环境 `re-uthcode` 中卸载 `pydantic-ai`、`pydantic-ai-slim`、`pydantic-graph`，随后按项目元数据重新安装并验证。

### 依赖任务

- Task 5 全部离线验收完成。

### 参考资料定位

- 原始需求第 1.3、6、7、8 Task 6、10.1—10.4、10.8—10.9 节。
- `pyproject.toml`、Python 发行包元数据、源码和测试残留扫描结果。

### 完成边界

- 清理前记录 OpenAI、Anthropic、Pydantic AI Slim 版本；确认没有工作包外项目反向依赖待卸载发行包。
- 严格按“源码与依赖声明完成替换 → 卸载三个发行包 → 重新安装项目与开发组 → 验证”的顺序执行。
- 不卸载基础 `pydantic`、`pydantic-core`、`httpx`、`anyio` 或其他共享依赖，除非元数据证明无反向依赖且用户另行授权。
- `pip show` 与 `find_spec` 证明三个 Pydantic AI 发行包和导入包不可用；OpenAI、Anthropic 可导入且 `pip check` 通过。
- `src`、`tests`、`pyproject.toml`、`README.md` 中旧 Pydantic AI 标识扫描为 0；旧桥接文件不存在。
- Provider 目录不存在 `_response`、`_source_iter`、`record_model_stream`；如保留 `provider_details`，只能基于官方公开字段的真实调用方并在 Feedback 解释。
- 不存在兼容 Shim、Alias、Adapter、双轨开关、重复职责、不可达旧代码或旧 UthCode 运行时依赖。
- 全量测试、编译、依赖检查、空白检查通过；工作区不含秘密、缓存、构建产物或范围外意外文件。
- Feedback 记录清理前后版本、卸载发行包、`pip check`、`find_spec`、全量测试、微基准、live 测试是否执行及遗留风险。
