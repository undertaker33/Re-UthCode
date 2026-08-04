# T01-项目骨架与Provider抽象 Checklist

所有命令从仓库根目录执行，并使用 Conda 环境 `re-uthcode`。除 Task 10 明确标记的 live 验收外，其余命令不得访问网络模型服务。

## Task 1：建立可安装项目骨架

- [x] 执行 `conda run -n re-uthcode python --version`，输出为 Python 3.12.x。
- [x] 执行 `conda run -n re-uthcode python -m pip install -e . --group dev`，editable install 成功。
- [x] 执行 `conda run -n re-uthcode python -m pip check`，输出 `No broken requirements found.`。
- [x] 执行 `conda run -n re-uthcode python -c "import uthcode; print(uthcode.__version__)"`，成功输出版本且不发起网络请求。
- [x] 执行 `conda run -n re-uthcode pytest -q tests/test_package.py`，全部通过。
- [x] 执行 `rg --files src/uthcode`，结果中除根包文件外不存在 `core/`、`application/`、`integrations/`、`interfaces/`、`cli.py`、`__main__.py` 或 `runtime.py` 占位内容。

## Task 2：定义 Provider 核心契约

- [x] 执行 `conda run -n re-uthcode pytest -q tests/test_provider_contract.py`，全部通过。
- [x] 测试证明请求、响应、事件和 Native Item 可 JSON round-trip，嵌套 list/dict 在构造后不可被外部修改。
- [x] 测试向 JSON payload 传入 SDK、Pydantic Model、集合或任意运行时对象，均被拒绝。
- [x] 测试构造来自不同 Provider 的 Native Item，目标 Provider 只能恢复属于自身身份的项。
- [x] 测试重复调用取消操作，状态转换幂等且等待者均能观察到取消。
- [x] 执行 `rg -n "pydantic|openai|anthropic|langgraph|langchain" src/uthcode/core`，返回 0 条第三方导入或 Provider 名称分支。

## Task 3：打通 Headless Application 与 Fake Provider

- [x] 执行 `conda run -n re-uthcode pytest -q tests/test_application.py`，全部通过。
- [x] 从 Application 正式方法向 Fake Provider 发送一次文本请求，逐项观察到文本事件、用量和唯一完成终态。
- [x] 使用 Fake Provider 输出完整 Tool Call 流，每个开始、参数增量和完成事件保持原顺序。
- [x] 分别模拟无终态、重复终态和终态后追加事件，Application 均拒绝该流且不生成伪成功响应。
- [x] 分别触发 UthCode 显式取消与 `asyncio` Task 取消，观察到不同且符合契约的结果。
- [x] 执行测试期间阻断网络构造，Fake 与 Application 测试仍全部通过。
- [x] 执行 `rg --files src/uthcode/application src/uthcode/integrations`，Application 为物理包，Integration 目录与 Fake Provider 同时出现，不存在根级 `application.py`。

## Task 4：建立 Pydantic AI Direct 集成边界

- [x] 执行 `conda run -n re-uthcode pytest -q tests/test_architecture_boundaries.py`，全部通过。
- [x] 使用 Pydantic AI Test/Function Model 流经共用桥接层，观察到 UthCode 自有事件、用量和终态。
- [x] 检查 Application、Core 公共注解和事件实例，不包含 Pydantic AI 或厂商 SDK 类型。
- [x] 模拟认证、限流、网络和非法响应异常，映射后的错误不包含测试秘密值。
- [x] 中途取消流后，Mock 资源记录显示异步上下文已退出且客户端所有权规则得到遵守。
- [x] 执行 `rg -n "pydantic_ai\.Agent|pydantic_graph|langgraph|langchain" src tests`，UthCode 实现中返回 0 条禁止使用记录；架构测试自身的禁止字符串断言除外。

## Task 5：实现 Anthropic 协议适配

- [ ] 执行 `conda run -n re-uthcode pytest -q tests/test_anthropic_integration.py`，全部通过且无真实 HTTP 请求。
- [ ] Mock Anthropic 流依次返回 Thinking、Signature、Redacted Thinking、Text 和 Tool Use，UthCode 事件及 Native Item 保持原顺序。
- [ ] 将完成响应加入下一轮同协议请求，Mock Client 捕获的请求中签名、Redacted Thinking 数据、Tool Use ID 和参数保持不变。
- [ ] 将同一响应切换到非 Anthropic Provider，捕获请求中不存在 Anthropic Native Item 或签名。
- [ ] Mock 用量覆盖输入、输出、缓存读取与缓存写入，UthCode Usage 映射值正确。
- [ ] Mock 认证、限流、网络错误及取消，观察到对应 UthCode 错误并确认资源关闭。

## Task 6：实现 OpenAI Responses 协议适配

- [ ] 执行 `conda run -n re-uthcode pytest -q tests/test_openai_responses_integration.py`，全部通过且无真实 HTTP 请求。
- [ ] Mock Responses 流返回 Reasoning、Reasoning Summary、交错 Function Calls 和 Function Call Output，Item ID、Call ID、输出索引及顺序保持稳定。
- [ ] 对至少两个交错 Function Call 分批发送参数，完成结果不串线且各自参数 JSON 正确。
- [ ] Delta、Done 与 Terminal Snapshot 重复携带同一 Item 时只完成一次；完成后冲突内容被拒绝。
- [ ] 分别模拟 completed、incomplete、failed、无终态 EOF 和终态时未完成调用，结果符合契约且非法流不生成成功终态。
- [ ] 将完成响应加入下一轮 Responses 请求，Mock Client 捕获到 Reasoning、Function Call、Function Call Output 及关联 ID；切换其他 Provider 时这些 Native Item 不被发送。

## Task 7：实现 OpenAI-compatible Chat Completions 协议适配

- [ ] 执行 `conda run -n re-uthcode pytest -q tests/test_openai_compat_integration.py`，全部通过且无真实 HTTP 请求。
- [ ] Mock Client 捕获的工具定义使用 Chat Completions function tool 结构，并保持名称、描述和参数 Schema。
- [ ] Mock Chat 流按至少两个 index 交错返回 Tool Call，聚合后的 ID、名称和参数分别正确。
- [ ] 下一轮请求中的 Tool Result 使用 `role=tool`、对应 Tool Call ID 和结果内容。
- [ ] 捕获请求中不存在 Responses 专用 Function Call Item 或 Function Call Output Item。
- [ ] Mock 文本、Thinking/Reasoning Carrier、缓存用量、完成原因、错误和取消均映射为 UthCode 类型。

## Task 8：实现配置与 Provider 构造

- [ ] 执行 `conda run -n re-uthcode pytest -q tests/test_provider_factory.py`，全部通过。
- [ ] 分别构造 Fake、Anthropic、OpenAI Responses 和 OpenAI-compatible Provider，构造期间网络拦截器记录 0 次请求。
- [ ] 缺失秘密环境变量时构造真实 Provider，错误仅包含环境变量名称，不包含任何秘密值。
- [ ] 检查配置对象、异常、repr 和测试输出，不出现注入的测试 Key。
- [ ] 未提供自定义 base URL 时构造 OpenAI-compatible Provider 被拒绝；Fake 构造不要求秘密。
- [ ] 构造两个相同配置的实例并分别修改可观测内部状态，实例之间互不影响。
- [ ] 执行 `rg -n "create_provider|factory" src/uthcode/core src/uthcode/application/generation.py`，Core 和 Application 生成用例均不依赖 Factory 实现。
- [ ] 执行 `Test-Path src/uthcode/config.py`，结果为 `False`；Provider 配置只存在于 `src/uthcode/integrations/providers/config.py`。

## Task 9：[接入主流程] 接入正式 Headless 调用链

- [ ] 执行 `conda run -n re-uthcode pytest -q tests/test_application.py tests/test_provider_factory.py`，全部通过。
- [ ] 从正式配置与 Provider 构造入口创建 Fake Provider，再由 Application 完成一次 Headless 请求并观察到唯一终态。
- [ ] README 中的 Headless Fake 示例在 `re-uthcode` 环境直接运行成功，且不使用 CLI、stdin 或交互 UI。
- [ ] 执行 `rg -n "anthropic|openai_responses|openai_compat" src/uthcode/application src/uthcode/core`，返回 0 条 Provider 名称分支。
- [ ] 检查 `src/uthcode/application/bootstrap.py`，它是 Application 内唯一依赖 Integration Factory 的组合模块；`generation.py` 不导入 Integration。
- [ ] 执行 `rg -n "FakeProvider\(|AnthropicModel\(|OpenAIResponsesModel\(|OpenAIChatModel\(" src/uthcode --glob '*.py'`，除各物理 Integration 模块和 Factory 外不存在阶段性直构入口。
- [ ] 检查 `src/uthcode/application/__init__.py`，只从 Application 包公开用例、组合入口和调用方必需的 UthCode 类型；检查 `src/uthcode/integrations/providers/__init__.py`，不暴露 SDK 类型或第二个公开组合入口。

## Task 10：[端到端验证] 验证离线链路与真实三协议

- [ ] 在未设置 live 标记和 `DEEPSEEK_API_KEY` 时执行 `conda run -n re-uthcode pytest -q`，全量离线测试通过，live 用例明确显示 skipped，网络拦截器记录 0 次请求。
- [ ] 执行 `conda run -n re-uthcode python -m compileall -q src tests`，退出码为 0。
- [ ] 执行 `conda run -n re-uthcode python -m pip check`，输出 `No broken requirements found.`。
- [ ] 在用户确认请求数量和费用影响后，仅在当前 PowerShell 会话设置 `DEEPSEEK_API_KEY`，不写入 `.env`、配置文件、命令日志或版本库。
- [ ] 显式运行 Anthropic live 用例，从正式 Headless 入口观察到文本、Thinking、Tool Call、Tool Result 续轮和成功终态。
- [ ] 显式运行 Responses live 用例，从正式 Headless 入口观察到文本、Reasoning、Function Call、Function Call Output 续轮和成功终态。
- [ ] 显式运行 Chat Completions live 用例，从正式 Headless 入口观察到文本、Reasoning Carrier、Tool Call、`role=tool` 续轮和成功终态。
- [ ] live 测试输出、pytest 报告、异常和 Git diff 中均搜索不到 API Key；测试结束后从当前进程环境移除该变量。
- [ ] 若任一真实协议失败，记录 HTTP 状态、脱敏错误、协议和阶段，并保持对应测试失败，不通过删减断言或改走其他协议伪造通过。

## Task 11：[遗留负担清理] 清除兼容层与重复职责

- [ ] 执行 `conda run -n re-uthcode pytest -q tests/test_architecture_boundaries.py`，全部通过。
- [ ] 执行 `rg -ni "langgraph|langchain|StateGraph|GraphState|Checkpoint|mewcode" pyproject.toml src tests`，除架构测试的禁止字符串断言外返回 0 条运行时依赖或导入。
- [ ] 执行 `rg --files src/uthcode`，不存在 `interfaces/` 以及 Prompt、Tool 执行、Permission、Context、Memory、Session、Storage、Journal、Sandbox、Command、Hook、Skill、MCP、Agent 或 Worktree 占位模块。
- [ ] 搜索旧 Day1 公共类名、模块路径和旧入口，源码中返回 0 条兼容 Adapter、别名、Facade、包装层或双轨逻辑。
- [ ] 检查三个真实协议文件，协议特有字段分别只位于对应物理模块；共用桥接层不存在 Provider 名称 switch/if 分支。
- [ ] 检查 Factory 与包导出，Provider 构造只有一个正式出口，不存在已替代旧入口或不可达分支。
- [ ] 执行 `Get-ChildItem src/uthcode -Force | Select-Object -ExpandProperty Name`，功能目录只包含当前实际存在的 `core`、`application`、`integrations`；根级除 `__init__.py` 外不存在承担上述职责的平级功能模块。
- [ ] 执行 `conda run -n re-uthcode python -m pip list --not-required --format=freeze` 并结合 `pyproject.toml` 审查顶层包；移除不再被项目或传递链需要的额外依赖后，重新执行 `pip check` 通过。
- [ ] 执行 `conda run -n re-uthcode python -m compileall -q src tests` 和 `conda run -n re-uthcode pytest -q`，全部通过。
- [ ] 查看 `git diff --check`，无空白错误；查看 `git status --short`，没有真实秘密、缓存、构建产物或工作包外的意外文件。
