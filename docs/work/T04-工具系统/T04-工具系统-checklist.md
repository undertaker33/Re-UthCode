# T04 工具系统 Checklist

## Task 1：修复配置 Integration 反向依赖

- [x] 执行 `pytest -q tests/test_config_loader_integration.py tests/test_configuration.py`，配置加载、优先级、秘密字段限制、初始化模板和模型写回用例全部通过。
- [x] 执行 `pytest -q tests/test_architecture_boundaries.py tests/test_package.py`，Integration 全目录导入边界与包导出用例全部通过。
- [x] 执行 `rg -n "uthcode\.application|uthcode\.interfaces" src/uthcode/integrations`，返回 0 条。
- [x] 执行 `rg -n "load_effective_config" src/uthcode/integrations/config`，返回 0 条。
- [x] Integration 测试观察到不可变原始配置数据；Application 测试观察到等价的最终有效配置及 path、field、template path 证据。

## Task 2：建立 Core Tool 契约、Registry 与 FIFO Executor

- [x] 执行 `pytest -q tests/test_tool_core.py tests/test_package.py`，全部用例通过。
- [x] 注册合法工具后多次读取 definitions，名称顺序与注册顺序一致且返回 tuple。
- [x] 重复名称和非法 JSON Schema 在注册时硬失败，Registry 不发生静默覆盖。
- [x] unknown、invalid arguments 和普通异常分别返回同 call ID 的 error 结果，后续调用继续执行。
- [x] batch 前取消时没有工具启动；batch 中取消后不再启动新工具，全部剩余 call 仍有同 ID 取消结果。
- [x] 超长成功和错误输出均只出现一次稳定截断后缀。

## Task 3：实现工作区、文件状态与文件工具

- [x] 执行 `pytest -q tests/test_builtin_file_tools.py tests/test_architecture_boundaries.py`，全部用例通过。
- [x] ReadFile 的正常读取、1-based 分页、空文件、目录、不存在和编码错误结果均可观察且符合 schema。
- [x] 新文件 Write 可创建父目录；已有文件未读时 Write/Edit 返回 error 且内容不变。
- [x] 已读文件被外部修改、替换、删除，或内容变化后恢复 mtime 时，Write/Edit 均拒绝副作用。
- [x] Edit 对空 old string、未找到和多次命中返回 error；唯一命中成功后共享 tracker 刷新。
- [x] `..`、工作区外绝对路径、外部文件符号链接和外部目录符号链接均不能被访问。
- [x] 取消发生在写入前时文件内容不变；超长读取经 Core Executor 统一截断。

## Task 4：实现安全 Glob 与 Grep

- [x] 执行 `pytest -q tests/test_builtin_search_tools.py`，全部用例通过。
- [x] Glob 只返回文件；Grep 返回稳定的工作区相对路径与行号；多次执行顺序一致。
- [x] 无匹配返回非错误空结果说明，非法 Python regex 返回 error。
- [x] `.git`、`.venv`、`node_modules`、`__pycache__`、`.tox`、`.mypy_cache`、`.pytest_cache` 内文件不出现在结果中。
- [x] parent pattern、工作区外文件符号链接和目录符号链接均不能越过工作区边界。
- [x] 执行 `rg -n "subprocess|shell=True|\brg\b|\bgrep\b|\bfind\b" src/uthcode/integrations/tools/search_tools.py`，人工确认没有调用系统搜索命令。
- [x] 大搜索结果经 Core Executor 统一截断一次。

## Task 5：实现 Bash 进程工具

- [x] 执行 `pytest -q tests/test_builtin_process_tool.py`，全部用例通过。
- [x] 命令观察到的 cwd 与规范化 Application runtime workdir 相同。
- [x] stdout、stderr、空输出和非零退出状态均可区分，非零退出返回 error。
- [x] schema 拒绝越界 timeout；默认和最大超时边界均有测试。
- [x] timeout 和 cancellation 均终止并 await 回收进程；平台支持时验证子进程未遗留。
- [x] 超长命令输出经 Core Executor 统一截断一次。
- [x] README 与代码明确当前 OS shell 和 unsandboxed process execution，不含 Sandbox 成功承诺。

## Task 6：默认工具 Factory 与 Application Headless API

- [x] 执行 `pytest -q tests/test_application_tools.py tests/test_application.py tests/test_package.py`，全部用例通过。
- [x] `application.tool_definitions()` 返回按 `ReadFile`、`WriteFile`、`EditFile`、`Glob`、`Grep`、`Bash` 排列的不可变 tuple。
- [x] 两个 Application 的文件读取状态互不共享，三个文件工具在同一 Application 内共享状态。
- [x] 显式注入 fake tools 时完整替代默认集合，不发生合并。
- [x] Application 公共 API 只返回 UthCode Core DTO，不返回具体 Integration Tool、Registry 或 Executor。
- [x] 工具 workdir 与 Application runtime context 的规范化 workdir 相同。
- [x] 既有 generation、模型切换、Provider 快照、取消和 System Prompt 用例保持通过。

## Task 7：[接入主流程] 打通手动单次工具往返

- [x] 单独执行 `pytest -q tests/test_application_tools.py -k "round_trip or tool"`，正式 Headless 手动往返用例通过。
- [x] 第一次 Fake Provider 请求中的 Tool Definition 来自 Application Registry。
- [x] Fake Provider 返回 ReadFile ToolCall 后，结果 ID 与 Provider call ID 相同且内容来自临时 workdir。
- [x] 调用方构造的 `Message(role="tool")` 出现在第二次 Fake Provider 请求中。
- [x] 两次请求使用同一 Application runtime context，链路不导入 Interface。
- [x] 测试断言 Application 没有内部自动循环、自动追加消息或自动执行 Provider ToolCall。
- [x] 执行三种 Provider tool schema/call 映射回归，全部通过。

## Task 8：[端到端验证] 全量测试与边界验证

- [x] 执行 `python -m compileall -q src tests`，退出码为 0。
- [x] 执行 `pytest -q tests/test_tool_core.py tests/test_builtin_file_tools.py tests/test_builtin_search_tools.py tests/test_builtin_process_tool.py tests/test_application_tools.py`，全部通过。
- [x] 执行 `pytest -q tests/test_config_loader_integration.py tests/test_configuration.py`，全部通过。
- [x] 执行 `pytest -q tests/test_provider_contract.py tests/test_anthropic_integration.py tests/test_openai_responses_integration.py tests/test_openai_compat_integration.py`，全部通过。
- [x] 执行 `pytest -q tests/test_system_prompt.py tests/test_application.py tests/test_application_runtime.py tests/test_cli.py tests/test_tui.py`，全部通过。
- [x] 执行 `pytest -q tests/test_architecture_boundaries.py tests/test_package.py`，全部通过。
- [x] 执行 `pytest -q`，全量通过且未授权 live Provider 用例仍为 skip。
- [x] 执行 `python -m pip check` 和 `git diff --check`，两条命令退出码均为 0。

## Task 9：[遗留负担清理] 删除重复入口与未来占位

- [x] 执行 `rg -n "from mewcode|import mewcode|langgraph|langchain" src tests README.md`，返回 0 条。
- [x] 执行 `rg -n "BaseModel|pydantic" src/uthcode/core src/uthcode/integrations/tools src/uthcode/application/tools.py`，返回 0 条。
- [x] AST/导出测试确认不存在第二套 ToolCall、ToolResult、ToolDefinition 或 CancellationToken。
- [x] 扫描确认不存在 Tool Manager、Repository、Facade、Shim、兼容别名和新旧双入口。
- [x] 扫描确认不存在 enable/disable、deferred/discovered、parallel、Permission、Agent Loop、MCP、Skill、Hook、Memory 或 Sandbox 占位实现。
- [x] 执行 `rg -n "uthcode\.application|uthcode\.interfaces" src/uthcode/integrations`，返回 0 条；Interface 依赖门禁测试通过。
- [x] `integrations.config` 不公开有效配置构造入口，Application 是唯一配置和工具公共入口。
- [x] 重新执行架构、package 和全量测试，全部通过；没有为测试新增边界白名单。
