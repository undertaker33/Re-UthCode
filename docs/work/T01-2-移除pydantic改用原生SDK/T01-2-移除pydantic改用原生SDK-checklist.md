# T01-2-移除pydantic改用原生SDK Checklist

## Task 1：建立原生 SDK 共用辅助边界

- [x] 执行 `conda run --no-capture-output -n re-uthcode pytest -q tests/test_provider_sdk_common.py`，全部通过。
- [x] 将 JSON 基础值、嵌套 list/dict 和官方 SDK 可公开序列化对象输入辅助函数，得到 JSON-safe 值且键顺序和数据内容保持。
- [x] 输入任意非 JSON 对象和非字符串字典键，均得到明确拒绝；错误中不包含对象内部秘密内容。
- [x] Usage 读取接受非负整数和缺省值，拒绝 `bool`、负数、浮点数和字符串 token 值。
- [x] 分别传入只有 `aclose`、只有 `close`、两者均有和两者均无的 Stream Double，每个可用关闭方法按约定调用且异常路径可观测。
- [x] 对未取消和已取消的 `CancellationToken` 执行检查，前者继续、后者产生现有 `GenerationCancelled` 语义。
- [x] 执行 `rg -n "openai|anthropic|pydantic_ai|ProviderKind|ProviderPort" src/uthcode/integrations/providers/common.py`，返回 0 条厂商依赖、Provider 分支或第二抽象。
- [x] 执行 `rg --files src/uthcode/integrations/providers | rg "provider_(base|manager|registry|router|plugin|adapter)|legacy_pydantic|compat_pydantic|pydantic_shim"`，返回 0 条。
- [x] 比较 `src/uthcode/core/provider.py`、`src/uthcode/application`、三个真实 Provider、Factory 和 `pyproject.toml` 与 Task 1 开始前状态，除新增 `common.py` 外均未修改。

## Task 2：替换三个真实 Provider Integration

- [x] 执行 `conda run --no-capture-output -n re-uthcode python -m compileall -q src`，退出码为 0。
- [x] 执行 `conda run --no-capture-output -n re-uthcode pytest -q tests/test_provider_factory.py tests/test_provider_contract.py tests/test_application.py tests/test_application_runtime.py tests/test_configuration.py tests/test_cli.py tests/test_tui.py`，全部通过。
- [x] `pyproject.toml` 直接声明 `anthropic>=0.117,<1` 与 `openai>=2.46,<3`，不声明 `pydantic-ai`、`pydantic-ai-slim`、`pydantic-graph` 或新增直接 `httpx` 依赖。
- [x] 分别构造 Anthropic、OpenAI Responses 和 OpenAI-compatible Provider，网络拦截器记录 0 次请求，Identity、模型名、Base URL 和最大输出 token 配置符合现有配置语义。
- [x] Anthropic 请求按原顺序包含 system、user、assistant thinking/signature/redacted thinking/text/tool use 和 tool result；其他 Provider 的 Native Item 被忽略。
- [x] Anthropic 流产生文本、Reasoning、Tool Call、Native Item 和唯一完成事件，保留 Content Block 顺序、Signature、Redacted Data、Stop Reason 与 input/output/cache Usage。
- [x] Responses 请求使用 instructions/input/function_call_output 和扁平 function tool，不出现 Chat `messages`、`assistant.tool_calls` 或 `role=tool`。
- [x] Responses 流按 item id、output index、call id、sequence number 隔离交错调用，保留 Reasoning、Encrypted Content、Summary、Message、Function Call、顺序和 Usage。
- [x] Chat 请求使用 `system/user/assistant/tool`、`assistant.tool_calls`、`role=tool`、`tool_call_id`、`stream=true` 和 Usage Stream Option，不出现 Responses Item 格式。
- [x] Chat 流中两个 Tool Call 按 index 独立聚合 ID、名称和参数；Nullable Usage Details 归一为 0，正文与有界 Reasoning Content 保持。
- [x] 三个 Provider 在正常、SDK 错误、显式取消和 `asyncio.CancelledError` 路径均关闭 Stream；显式取消映射为现有取消异常，Task 取消原样传播。
- [x] 对 Anthropic/OpenAI Authentication、Permission、Rate Limit、Connection、Timeout 和其他 Status Error 逐类注入，得到规定的 UthCode 错误分类，输出不含 API Key、请求、响应体、完整 Header 或第三方异常文本。
- [x] `src/uthcode/integrations/providers/pydantic_ai.py` 不存在；执行 `rg -n "from pydantic_ai|import pydantic_ai|PydanticAIProvider|PydanticAICodec|record_model_stream" src/uthcode` 返回 0 条。
- [x] 执行 `rg -n "_response|_source_iter" src/uthcode/integrations/providers`，返回 0 条第三方私有流字段访问。
- [x] `src/uthcode/core/provider.py`、`src/uthcode/application`、`src/uthcode/integrations/providers/config.py`、`fake.py`、CLI 与 TUI 文件均未修改。

## Task 3：重写协议测试并保持行为等价

- [x] 执行 `conda run --no-capture-output -n re-uthcode pytest -q tests/test_anthropic_integration.py`，全部离线通过。
- [x] 执行 `conda run --no-capture-output -n re-uthcode pytest -q tests/test_openai_responses_integration.py`，全部离线通过且 live 用例默认 skipped。
- [x] 执行 `conda run --no-capture-output -n re-uthcode pytest -q tests/test_openai_compat_integration.py`，全部离线通过且 live 用例默认 skipped。
- [x] 执行 `conda run --no-capture-output -n re-uthcode pytest -q tests/test_provider_factory.py`，全部通过且网络拦截器记录 0 次请求。
- [x] Anthropic 黑盒测试完成 `user → thinking → signature → redacted_thinking → text → tool_use → tool_result → 下一次请求` 往返，并逐项断言顺序、原始数据、Usage 和 Stop Reason。
- [x] Anthropic 测试删除 `message_stop` 或非空 Stop Reason 时失败；Tool JSON、Signature、Redacted Data 类型非法时失败；取消和异常时 Stream 已关闭。
- [x] Responses 黑盒测试完成 Reasoning、A/B 交错 Function Call、Message、Function Call Output 和下一次请求往返，逐项断言 Item ID、Call ID、Output Index 与顺序。
- [x] Responses 相同重复 Delta/Done/Terminal 只发布一次；内容冲突、Terminal 冲突、Unfinished Call、`incomplete`、`failed`、`error` 与 EOF 均不产生成功终态。
- [x] Chat 黑盒测试完成 Reasoning Content、Text、两个 Indexed Tool Call、`role=tool` 和下一次请求往返，逐项断言 Tool Call ID、名称、参数和消息格式。
- [x] Chat 缺少合法 Finish Reason、Tool Call 缺少 ID/名称、参数非 JSON Object、重复或冲突完成时失败；Nullable Usage Details 为 0。
- [x] 三个测试文件直接使用官方 SDK 类型，或仅模拟公开 Client 方法；执行 `rg -n "pydantic_ai|PydanticAI|Codec|FunctionModel" tests/test_anthropic_integration.py tests/test_openai_responses_integration.py tests/test_openai_compat_integration.py tests/test_provider_factory.py` 返回 0 条。
- [x] 默认测试环境清除真实 API Key 后仍全部通过且网络访问为 0；live 用例只有 `UTHCODE_RUN_LIVE=1` 时才可运行。

## Task 4：[接入主流程] 收敛构造与架构边界

- [x] 执行 `conda run --no-capture-output -n re-uthcode pytest -q tests/test_architecture_boundaries.py tests/test_package.py`，全部通过。
- [x] 执行 `conda run --no-capture-output -n re-uthcode pytest -q tests/test_application.py tests/test_application_runtime.py tests/test_provider_factory.py tests/test_provider_contract.py`，全部通过。
- [x] 执行 `conda run --no-capture-output -n re-uthcode pytest -q tests/test_configuration.py tests/test_cli.py tests/test_tui.py`，全部通过。
- [x] 搜索 `create_provider` 定义和调用，只有 Factory 定义、正式 Bootstrap 调用与测试引用，不存在第二构造根。
- [x] 执行 `rg -n "openai|anthropic|pydantic" src/uthcode/core src/uthcode/application src/uthcode/interfaces`，除普通英文语境或架构测试禁止字符串外无 SDK/Pydantic Import 和 Provider 协议分支。
- [x] 检查 `src/uthcode/integrations/providers/__init__.py` 和根包导出，不包含官方 SDK Client、具体 Provider、旧 Bridge 或 Codec。
- [x] 执行 `rg -n "pydantic_ai|PydanticAIProvider|PydanticAICodec|FunctionModel|pydantic_graph" src tests pyproject.toml README.md`，返回 0 条。
- [x] 从正式 Bootstrap 创建 Fake 和三个真实 Provider，Application 无需接触 SDK 类型；所有真实 Provider 构造网络访问为 0。
- [x] 通过 Fake Provider 分别运行 Headless、`uthcode exec` 和 TUI 一次请求，输出、终态、退出码和 UI 行为与基线一致。
- [x] `src/uthcode/core/provider.py` 公共类型和 `ProviderPort` 签名与基线一致，配置 TOML 结构、Provider Kind、模型选择语义、Application Command/Event、CLI 参数和 TUI 交互未变化。

## Task 5：[端到端验证] 验证三 Provider 与现有交互入口

- [x] 执行 `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests`，退出码为 0。
- [x] 执行 `conda run --no-capture-output -n re-uthcode pytest -q`，全量离线测试通过，live 测试明确 skipped。
- [x] 执行 `conda run --no-capture-output -n re-uthcode python -m pip check`，输出 `No broken requirements found.`。
- [x] 从正式入口完成 Fake Headless 请求、三个真实 Provider Mock Stream、Provider Factory、配置加载、`uthcode exec` Fake 模型和 TUI Fake 模型一次请求。
- [x] 在 Application、CLI 和 TUI 路径分别注入 Provider Authentication、Rate Limit、Network、Invalid Response 和取消结果，错误分类、退出码、终态与用户可见输出保持基线且不泄露秘密。
- [x] 分别触发显式取消与 Task 取消，当前 Stream 被关闭，不发布重复失败或成功终态，不影响其他独立 Fake Generation Handle。
- [x] 运行离线微基准处理 10,000 个纯文本 Delta，网络访问为 0、Pydantic AI 对象创建为 0、普通 Delta 不复制整个流历史；在 W02 Feedback 记录用时和观察结果。
- [x] 未设置 `UTHCODE_RUN_LIVE=1` 时不执行任何真实端点请求，并在 Feedback 明确记录 live 测试未运行。
- [x] 验证 live 门禁：若用户未显式授权，证明 `UTHCODE_RUN_LIVE` 未启用、真实端点测试保持 skipped，并在 Feedback 记录“未运行”；若用户已配置凭据并显式授权，则执行 `conda run --no-capture-output -n re-uthcode pytest -q tests/test_openai_compat_integration.py -m live`，观察正文增量、合法终态、Usage、关闭、无重复错误和无 Key 泄漏。

## Task 6：[遗留负担清理] 清理源码、测试和 Conda 环境

- [x] 在卸载前记录 `openai`、`anthropic`、`pydantic-ai-slim` 版本，并通过发行包元数据确认除当前 `uthcode` 外没有其他已安装项目反向依赖 `pydantic-ai*` 或 `pydantic-graph`。
- [x] 在源码和 `pyproject.toml` 已完成替换后，执行 `conda run --no-capture-output -n re-uthcode python -m pip uninstall -y pydantic-ai pydantic-ai-slim pydantic-graph`，仅处理这三个发行包。
- [x] 执行 `conda run --no-capture-output -n re-uthcode python -m pip install -e . --group dev --upgrade`，安装成功。
- [x] 执行 `conda run --no-capture-output -n re-uthcode python -m pip check`，输出 `No broken requirements found.`。
- [x] 分别执行 `conda run --no-capture-output -n re-uthcode python -m pip show pydantic-ai`、`pydantic-ai-slim`、`pydantic-graph`，三者均报告未安装。
- [x] 执行 `conda run --no-capture-output -n re-uthcode python -c "import importlib.util; assert importlib.util.find_spec('pydantic_ai') is None"`，退出码为 0。
- [x] 执行 `conda run --no-capture-output -n re-uthcode python -c "import openai, anthropic; print(openai.__version__, anthropic.__version__)"`，两 SDK 均可导入并在指定主版本范围内。
- [x] 执行 `rg -n "pydantic_ai|PydanticAIProvider|PydanticAICodec|FunctionModel|pydantic_graph" src tests pyproject.toml README.md`，返回 0 条。
- [x] 执行 `rg -n "_response|_source_iter|record_model_stream" src/uthcode/integrations/providers`，返回 0 条。
- [x] 执行 `rg -n "provider_details" src/uthcode/integrations/providers`；返回 0 条，或每一条均对应官方公开字段的真实调用方并在 W02 Feedback 逐项解释。
- [x] 执行 `rg --files src tests | rg "legacy_pydantic|compat_pydantic|pydantic_shim|provider_(base|manager|registry|router|plugin|adapter)"`，返回 0 条。
- [x] 搜索 `legacy_`、旧 Codec/Recorder、双轨开关、重复 Provider 抽象和不可达分支，不存在仅为兼容 Re:UthCode 早期实现而保留的逻辑。
- [x] 执行 `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests` 和 `conda run --no-capture-output -n re-uthcode pytest -q`，全部通过。
- [x] 执行 `git diff --check`，无空白错误；执行 `git status --short`，没有秘密、缓存、构建产物、旧仓改动或工作包外意外文件。
- [x] W02 Feedback 记录清理前后 SDK 版本、卸载发行包、`pip check`、`find_spec`、完整 pytest、微基准、live 测试状态、Checklist 完成情况和遗留风险。
