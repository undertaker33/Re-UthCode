# T05 ReAct 与 Agent Loop Checklist

## Task 1：Agent policy、State 与统一事件契约

- [x] 执行 `conda run --no-capture-output -n re-uthcode pytest -q tests/test_agent_policy.py tests/test_agent_events.py tests/test_package.py`，全部用例通过。
- [x] 断言循环配置默认限制符合原始需求，零值、负值、bool 和非法类型全部被拒绝。
- [x] 断言 RunState、RunSnapshot、TurnResult 和每种 AgentEvent 均为 frozen；调用方不能修改内部 tuple 或 JSON payload。
- [x] 断言新 Turn 保留此前 messages，并重置 iteration、Tool 数、unknown streak、Usage、状态和终止原因。
- [x] 将 RunSnapshot 和 TurnResult 序列化后检查，不包含 conversation 正文、Provider native payload、SDK 对象、Exception、Path、bytes 或 Task。
- [x] 对所有 AgentEvent 执行 dict/JSON round-trip；unknown type、缺失字段和非 JSON-safe payload 均被拒绝。
- [x] 输入多段 reasoning 序列，观察到每段严格按 started → delta → finished 输出；无 reasoning 时没有伪 reasoning 事件。
- [x] 同一 ToolCall 的 ToolStarted/ToolFinished 具有相同 ID、name 和 command，ToolFinished 序列化结果不含 ToolResult content。

## Task 2：Provider 权威流与显式 Agent Loop

- [x] 执行 `conda run --no-capture-output -n re-uthcode pytest -q tests/test_provider_contract.py tests/test_agent_policy.py tests/test_agent_events.py tests/test_agent_loop.py tests/test_tool_core.py`，全部用例通过。
- [x] 共享 Provider 流校验测试证明：唯一 terminal 只在底层 EOF 后公开；缺 terminal、多个 terminal、terminal 后事件均失败；stream 始终关闭。
- [x] 普通回答测试观察到一次 Provider 调用、一次 iteration、一个 final assistant message 和唯一 TurnCompleted。
- [x] reasoning + Tool + final 测试观察到 reasoning 事件按实际顺序公开，权威 conversation 只来自两个 Provider terminal。
- [x] 多 Tool 测试使用活动计数器证明并发峰值为 1，执行与结果顺序严格等于 Provider ToolCall 顺序。
- [x] 多步 Loop 测试证明 Provider 调用次数等于 iteration，Tool 数不增加 iteration。
- [x] unknown、invalid arguments、tool error 和 truncated output 后，下一次 Provider 请求能读取同 ID ToolResult 并继续。
- [x] known Tool 出现时 unknown streak 立即归零；连续 unknown 达到限制后，在当前 batch 全部闭合后唯一失败。
- [x] 单响应 ToolCall 超限测试证明整批零执行、每个 call 获得同 ID 结果、Turn 以工具数限制失败。
- [x] LENGTH/INCOMPLETE 与 ToolCall 同时出现时，所有 Tool 零执行、同 ID 未执行结果按原序回填、Turn 受控失败。
- [x] max iterations 测试证明预算耗尽后不再调用 Provider，已产生的 ToolResult 保持闭合。
- [x] Provider error、无 terminal、尾随事件、统一 DTO 协议矛盾分别产生唯一失败终态，partial assistant 不进入 conversation。
- [x] Provider 阶段取消和首个/中间 Tool 阶段取消测试证明：每个 ToolCall 均有同 ID 结果、无后续 Provider 调用、只有一个 TurnCancelled。
- [x] Usage 测试证明只累计合法 terminal、Tool 不修改 Usage、下一 Turn 重置。
- [x] 分别运行三个 Provider Integration 定向测试，Anthropic、OpenAI Responses、OpenAI-compatible 各自的 final、ToolCall、长度/不完整、错误和取消映射符合统一 DTO；Agent Loop 源码中无 Provider 名称分支。

## Task 3：Application Run/Turn 与安全 Tool 摘要

- [x] 执行 `conda run --no-capture-output -n re-uthcode pytest -q tests/test_application.py tests/test_application_runtime.py tests/test_application_tools.py tests/test_application_runs.py tests/test_package.py`，全部用例通过。
- [x] 同一 Run 连续两个 Turn 时，第二次 Provider 请求可观察到第一 Turn 的权威 conversation；不同 Run 不共享 messages、状态或取消。
- [x] 活动 Turn 尚未 terminal 时再次 `start_turn()` 明确失败；terminal 后下一 Turn 可以启动。
- [x] 只消费 `events()`、只等待异步 `result()`、两者同时使用三种场景均只启动一次 Provider/Tool 执行。
- [x] `events()` 第二个消费者被拒绝；`result()` 可重复 await 并返回同一个不可变结果值。
- [x] `cancel()` 首次返回状态转换、后续幂等；terminal 后 Run 被释放。
- [x] Turn 开始后切换 Application 模型，当前 Turn 的 Provider/Model/System Prompt 不变，下一 Turn 使用新选择。
- [x] Agent iteration 请求自动包含固定有序 Tool definitions；raw generation 请求仍不自动注入 tools。
- [x] 同一 Application 的 Runs 使用同一 T04 Tool Runtime，不同 Application 的文件读取状态继续隔离。
- [x] Bash、文件、搜索和 unknown Tool 摘要分别验证；写入正文、秘密、环境变量值和 unknown 参数值均不出现。
- [x] 超长摘要稳定截断，摘要生成异常返回安全占位且对应 Tool 仍实际执行。
- [x] Application 公共导出不包含 RunState、ToolRegistry、ToolExecutor 或具体 Integration Tool。

## Task 4：Headless Agent 端到端闭环

- [x] 执行 `conda run --no-capture-output -n re-uthcode pytest -q tests/test_agent_loop.py tests/test_application_runs.py`，全部用例通过。
- [x] 从 `create_application(temp_workdir) → create_run() → start_turn()` 正式入口运行离线 E2E，不直接调用私有 helper。
- [x] Fake Provider 先产生 reasoning 和 ReadFile ToolCall，真实 Integration Tool 读取临时文件，第二次 Provider 请求包含同 ID、真实内容的 ToolResult。
- [x] E2E 事件流包含 reasoning、ToolStarted、ToolFinished、final 和唯一 TurnCompleted，事件顺序与实际执行一致。
- [x] ToolStarted command 是安全摘要；ToolFinished、TurnResult、RunSnapshot 均不包含临时文件正文。
- [x] `TurnResult.final_text` 只包含 final answer，不包含 reasoning、progress 或 ToolResult。
- [x] Headless E2E 模块加载记录证明没有导入 `uthcode.interfaces`。
- [x] README Headless 示例使用正式 Run/Turn API，并明确其与低层单轮 Generation/手动 Tool API 的区别。

## Task 5：CLI AgentEvent 投影

- [x] 执行 `conda run --no-capture-output -n re-uthcode pytest -q tests/test_cli.py`，全部用例通过。
- [x] final 场景断言 stdout 只有 final answer 和必要结尾换行，reasoning、progress、事件字典和内部诊断均不在 stdout。
- [x] reasoning、progress、incomplete 和 Tool activity 场景断言对应文本只进入 stderr。
- [x] Tool 行只出现 status、tool name 和安全 command；构造含独特秘密的 ToolResult 后，stdout/stderr 均搜索不到该秘密。
- [x] failed 返回 1，cancelled 和 Ctrl+C 返回 130，参数/配置错误返回 2，completed 返回 0。
- [x] stdin 输入 `/help` 时仍作为普通 Prompt 进入 Agent Turn，不进入 Slash Command Dispatcher。
- [x] 模块导入与正式 `uthcode exec` 测试证明未加载 Textual/TUI。

## Task 6：TUI 活动流与视觉层级

- [x] 执行 `conda run --no-capture-output -n re-uthcode pytest -q tests/test_tui.py`，全部用例通过。
- [x] 普通输入通过 AgentRun 启动 Turn；第二 Turn 的 Fake Provider 请求包含第一 Turn conversation。
- [x] 活动 Turn 期间第二普通输入和 `/model` 均被拒绝；完成后模型切换只影响下一 Turn。
- [x] `/clear` 后 DOM 显示为空，但下一 Turn 的 Provider 请求仍包含清除前 conversation。
- [x] 用户消息 Widget 是宽度覆盖完整消息容器的背景块，具有非零 padding，并使用主题正常文本色。
- [x] Agent reasoning 与 final 使用相同正常正文 token，均无 dim/italic；Tool 行使用 muted/secondary token。
- [x] Tool 行显示 running/finished/failed 状态、name 和 Application command，并按 tool_call_id 更新或稳定成对显示。
- [x] 构造带独特正文的 ToolResult 后，DOM、render tree、Transcript state 和 snapshot 均搜索不到该正文，且不存在展开按钮。
- [x] 长 command 使用 Application 已截断摘要；TUI 测试证明没有读取原始 Tool arguments。
- [x] reasoning 流式增量复用当前 Agent block，不为每个字符创建新 Widget。
- [x] 双 Esc 只取消活动 TurnHandle；Completion/Picker 打开时 Esc 只关闭对应弹层；退出时 timer 和活动任务完成收口。
- [x] Slash Command、Completion、Model Picker、Composer Enter/Shift+Enter、滚动保护和 Topbar 回归通过。
- [x] `tui.tcss` 使用 Textual 主题 token，无硬编码 RGB；主题切换后用户背景、正文和 muted Tool 层级仍可读。

## Task 7：[接入主流程] 统一正式 Agent 路径

- [x] 执行 `conda run --no-capture-output -n re-uthcode pytest -q tests/test_application_runs.py tests/test_cli.py tests/test_tui.py tests/test_architecture_boundaries.py tests/test_package.py`，全部用例通过。
- [x] 从 Headless、CLI、TUI 三个正式入口分别观察到 `Application Run/Turn → Core AgentLoop`，不存在 Interface 自动执行的第二条路径。
- [x] 执行 `rg -n "ProviderEvent|GenerationHandle" src/uthcode/interfaces`，普通输入实现返回 0 条；若仅剩明确的低层类型说明，逐条记录并证明无运行调用方。
- [x] 执行 `rg -n "uthcode\.core|uthcode\.integrations" src/uthcode/interfaces`，返回 0 条。
- [x] 低层 `start_generation()`、`stream_generation()`、`tool_definitions()`、`execute_tool_calls()` 的既有测试全部通过。
- [x] 包导出测试确认 Application 公开 Agent API，但不公开 RunState、ToolRegistry、ToolExecutor 或 SDK 类型。
- [x] README 只描述一条正式 Agent 路径，并保留低层 API 的明确用途说明。

## Task 8：[端到端验证] 全链路与回归验证

- [x] 执行 `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests`，退出码为 0。
- [x] 执行 `conda run --no-capture-output -n re-uthcode pytest -q tests/test_agent_policy.py tests/test_agent_events.py tests/test_agent_loop.py tests/test_application_runs.py`，全部通过。
- [x] 执行 `conda run --no-capture-output -n re-uthcode pytest -q tests/test_application.py tests/test_application_runtime.py tests/test_application_tools.py tests/test_cli.py tests/test_tui.py`，全部通过。
- [x] 执行 `conda run --no-capture-output -n re-uthcode pytest -q tests/test_provider_contract.py tests/test_anthropic_integration.py tests/test_openai_responses_integration.py tests/test_openai_compat_integration.py`，全部离线用例通过，live 用例保持 skip。
- [x] 执行 `conda run --no-capture-output -n re-uthcode pytest -q tests/test_architecture_boundaries.py tests/test_package.py`，全部通过。
- [x] 执行 `conda run --no-capture-output -n re-uthcode pytest -q`，全量测试通过，未授权 live Provider 用例没有发起网络请求。
- [x] 执行 `conda run --no-capture-output -n re-uthcode python -m pip check`，输出 `No broken requirements found.`。
- [x] 执行 `git diff --check`，退出码为 0。
- [x] Headless、CLI 和 TUI 三条真实离线 E2E 同时证明 reasoning 可见、Tool activity 可见、ToolResult 正文隐藏、final 正确且 terminal 唯一。

## Task 9：[遗留负担清理] 删除旧路径与重复职责

- [x] 执行 `rg -n "from mewcode|import mewcode|langgraph|langchain" src tests README.md`，返回 0 条。
- [x] 执行 `rg -n "StateGraph|GraphState|checkpoint|ConversationManager" src tests`，除否定性测试的运行时拼接外返回 0 条。
- [x] 执行 `rg -n "uthcode\.application|uthcode\.interfaces" src/uthcode/integrations`，返回 0 条。
- [x] 执行 `rg -n "uthcode\.core|uthcode\.integrations" src/uthcode/interfaces`，返回 0 条。
- [x] 执行 `rg -n "ProviderEvent" src/uthcode/interfaces`，返回 0 条。
- [x] 执行 `rg -n "tool_result|ToolResultPart" src/uthcode/interfaces/tui`，返回 0 条。
- [x] 执行 `rg -n "asyncio\.gather|TaskGroup" src/uthcode/core/agent.py`，返回 0 条。
- [x] AST/导出测试确认只有一套 Agent Loop、AgentEvent、RunState 和 Tool DTO；不存在 Manager/Repository/Facade/Shim/deprecated alias。
- [x] 扫描确认不存在无调用方旧 renderer、旧单轮 state、ToolResult 展开入口、Interface 原始参数摘要逻辑和不可达分支。
- [x] 扫描确认没有 Permission、Context、Memory、Session、Journal、Diff、Sandbox、Hook、Skill、MCP、Worktree、Subagent 或 Multi-Agent 实现/占位。
- [x] README 与源码中的 Bash 描述明确为当前用户权限的 unsandboxed process execution，不包含 Sandbox 成功承诺。
- [x] 重新执行架构、package 和全量测试，全部通过；T04/T05 工作包仍在 `docs/work/` 且未被 Agent 归档。
