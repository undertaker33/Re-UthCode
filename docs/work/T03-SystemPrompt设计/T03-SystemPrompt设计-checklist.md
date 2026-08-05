# T03 System Prompt 设计 Checklist

## Task 1：建立 Core System Prompt 模块

- [x] 执行 `conda run --no-capture-output -n re-uthcode pytest -q tests/test_system_prompt.py`，全部用例通过。
- [x] 使用两个内容与优先级相同的固定上下文连续构建 Prompt，输出字节完全一致且输入 Section 未改变。
- [x] 构造乱序、同优先级和空白 Section，观察到升序稳定排列、空段不输出、段间恰为两个换行且无尾部空白。
- [x] 使用包含换行、反引号、引号和反斜杠的运行值，确认其不能生成新的 Section 标题或破坏运行环境字段边界。
- [x] 扫描 Prompt 文本和 Context 字段，Tool、Permission、Plan、Memory、Hook、Skill、MCP、Subagent、Sandbox 等未来能力声明为 0 条。

## Task 2：替换 Core 请求中的临时 System Message 语义

- [x] 执行 `conda run --no-capture-output -n re-uthcode pytest -q tests/test_provider_contract.py`，全部用例通过。
- [x] 对无 Prompt 和合法 Prompt 请求执行 dict/JSON round-trip，恢复后值与原请求一致。
- [x] 构造空白 Prompt、非字符串 Prompt、`system` 角色和未知角色，均观察到明确拒绝且没有兼容转换。
- [x] 对请求嵌套数据尝试外部修改，确认深度不可变性保持。

## Task 3：重写三种 Provider 的 System Prompt 映射

- [x] 执行 `conda run --no-capture-output -n re-uthcode pytest -q tests/test_anthropic_integration.py tests/test_openai_responses_integration.py tests/test_openai_compat_integration.py`，全部离线用例通过，live 用例仅按既有门禁跳过。
- [x] Anthropic 有 Prompt 时只在顶层 `system` 出现，无 Prompt 时该参数不发送，历史消息中无 Core System Message。
- [x] Responses 有 Prompt 时只在顶层 `instructions` 出现，无 Prompt 时该参数不发送，input 中无 System Item。
- [x] Chat 有 Prompt 时只有首项 `role=system`，无 Prompt 时没有该项，后续历史顺序不变。
- [x] 三协议的 Tool Result、Reasoning/Native Item、Usage、错误、显式取消、Task 取消和流关闭既有用例全部通过。

## Task 4：建立 Application 运行上下文与权威请求准备

- [x] 执行 `conda run --no-capture-output -n re-uthcode pytest -q tests/test_application.py tests/test_application_runtime.py`，全部用例通过。
- [x] 使用固定 workdir、平台、日期和 Fake Provider 启动 Headless 生成，Fake 记录到完整权威 Prompt。
- [x] 生成后比较调用方原请求，确认其 System Prompt 和嵌套内容均未被修改。
- [x] 调用方自带 Prompt 或 Prompt 构建失败时，观察到请求被拒绝且 Provider 调用计数为 0。
- [x] 模型切换成功后下一请求的 Model Ref、协议和远端模型 ID 全部刷新；Provider 构造或配置写回失败后仍保持旧身份。
- [x] 两个并存 GenerationHandle 分别取消，确认取消互不影响。
- [x] 执行 `rg -n 'workdir|platform_name|platform_release|current_date' src/uthcode/application/configuration.py src/uthcode/integrations/config`，确认没有新增运行上下文字段。

## Task 5：统一 CLI、TUI 与 Headless 的运行上下文

- [x] 执行 `conda run --no-capture-output -n re-uthcode pytest -q tests/test_cli.py tests/test_tui.py`，全部用例通过。
- [x] 分别使用默认 cwd 与显式 `--cwd` 执行 Fake `uthcode exec`，配置发现目录与 Prompt workdir 完全一致。
- [x] 使用 stdin 和位置参数输入 Prompt，确认 stdout、stderr 和退出码保持既有 contract。
- [x] 运行 Textual Pilot，确认 TUI Topbar 与 Fake Provider 记录的 Prompt workdir 同源。
- [x] 通过模型 Picker 切换模型后生成下一请求，确认 Topbar 选择与 Prompt 模型身份一致。
- [x] 既有流式定时刷新、单 Widget 复用、双 Esc 取消和退出清理用例全部通过。
- [x] 执行 `rg -n 'system_prompt|build_system_prompt|SystemPromptContext' src/uthcode/interfaces`，返回 0 条。
- [x] 检查 README 示例，不存在 `Message("system", ...)` 或调用方覆盖 System Prompt 的用法。

## Task 6：[接入主流程] 收口正式调用链

- [x] 执行 `conda run --no-capture-output -n re-uthcode pytest -q tests/test_architecture_boundaries.py tests/test_package.py`，全部用例通过。
- [x] 通过正式 Bootstrap + Fake 从 CLI、TUI、Embedded Headless 各发起一次生成，三者都只产生一个 Application 构建的 Prompt。
- [x] 在子进程中阻断 `uthcode.interfaces` 导入后执行 Headless Fake 生成，仍收到完整 Provider Event。
- [x] 根包与 Application 包导入时，确认未加载 Anthropic/OpenAI SDK、Textual 或具体 Provider Client。
- [x] AST 边界检查确认 `interfaces → application → core` 和 `application → integrations`，无禁止方向依赖。

## Task 7：[端到端验证] 验证三协议与全部正式入口

- [x] 执行 `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests`，退出码为 0。
- [x] 执行 `conda run --no-capture-output -n re-uthcode pytest -q tests/test_system_prompt.py tests/test_provider_contract.py`，全部通过。
- [x] 执行 `conda run --no-capture-output -n re-uthcode pytest -q tests/test_anthropic_integration.py tests/test_openai_responses_integration.py tests/test_openai_compat_integration.py`，全部离线用例通过。
- [x] 执行 `conda run --no-capture-output -n re-uthcode pytest -q tests/test_application.py tests/test_application_runtime.py tests/test_cli.py tests/test_tui.py`，全部通过。
- [x] 执行 `conda run --no-capture-output -n re-uthcode pytest -q tests/test_architecture_boundaries.py tests/test_package.py`，全部通过。
- [x] 执行 `conda run --no-capture-output -n re-uthcode pytest -q`，全量离线测试通过，live Provider 测试保持显式跳过。
- [x] 执行 `conda run --no-capture-output -n re-uthcode python -m pip check`，输出 `No broken requirements found.`。
- [x] Feedback 记录 Headless、CLI、TUI 和三协议请求形状的离线端到端证据及精确测试总数。

## Task 8：[遗留负担清理] 删除临时语义和未来占位

- [x] 执行 `rg -n 'Message\([^\n]*["'']system["'']|role\s*=\s*["'']system["'']' src tests`，逐项确认业务 Core/Test 调用为 0，匹配仅限 Chat 厂商映射及其协议测试。
- [x] 执行 `rg -n 'custom_instructions|hook_prompts|memory_section|skill_section|agent_catalog|deferred_tool|plan_mode' src/uthcode/core/prompt.py src/uthcode/application/runtime_context.py`，返回 0 条。
- [x] 执行 `rg -n 'MewCode|xiaolincoding|xiaolinnote|公众号|Go版' src tests README.md`，返回 0 条。
- [x] 执行 `rg --files src/uthcode | rg 'prompt_(manager|registry|loader|cache)|prompts/|plan.py'`，返回 0 条。
- [x] 执行 `rg -n 'system_prompt' src/uthcode/interfaces`，返回 0 条。
- [x] 执行 `rg -n 'workdir|platform_name|platform_release|current_date' src/uthcode/application/configuration.py src/uthcode/integrations/config`，确认没有 Runtime 字段。
- [x] 审查 T03 diff，确认没有 Alias、Facade、Shim、Fallback、双轨 API、重复职责、不可达分支或为兼容早期实现保留的逻辑。
- [x] 重新执行 `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests` 和 `conda run --no-capture-output -n re-uthcode pytest -q`，均通过。
- [x] 执行 `git diff --check`，退出码为 0；执行 `git status --short`，仅包含 T03 工作包和已批准实现范围内文件。
- [x] Feedback 明确记录未运行真实 Provider/live 测试、未归档工作包、未执行 Git 写操作。
