# T05 ReAct 与 Agent Loop Tasks

## Worker 分组与依赖

| Worker | 严格执行顺序 | 依赖 |
| --- | --- | --- |
| W01 `core-agent-runtime` | Task 1 → Task 2 | 无 |
| W02 `application-run` | Task 3 → Task 4 | W01 完成并通过定向测试 |
| W03 `interface-activity` | Task 5 → Task 6 | W02 完成并通过 Headless 端到端测试 |
| W04 `delivery-verification` | Task 7 → Task 8 → Task 9 | W01、W02、W03 全部完成 |

同一 Worker 内必须严格串行，后一 Task 只能建立在前一 Task 已测试、已审查的结果上。Worker 之间不得并行修改同一工作树。每个 Task 是独立测试、审查和回退边界；除非用户在派发时另行明确授权，Worker 不执行 Git commit、push、merge、rebase、tag 或工作树清理。

## 已确认的跨 Task 决策

1. TUI 视觉修改明确包含 `src/uthcode/interfaces/tui/tui.tcss`，不把同一套样式拆到 Python 内嵌 CSS。
2. Anthropic、OpenAI Responses、OpenAI-compatible 的线协议差异分别留在对应 Integration Adapter；Core Agent Loop 只消费统一 Provider DTO，不按 Provider 名称分支。
3. 三个 Adapter 先以现有映射为基线逐个增加回归验证；只有测试证明某个协议映射缺失时，才允许窄改对应 Adapter，不联动重写其他 Adapter 或 Provider DTO。
4. `TurnHandle.result()` 是异步等待接口。`start_turn()` 立即占用 Run；首次调用事件流或结果等待时启动唯一执行过程，两种消费方式共享同一结果，不要求 `start_turn()` 当下已有运行中的事件循环。
5. `src/uthcode/core/provider.py` 提供 Provider 无关的共享流终态校验；低层 Generation 与 Agent Loop 必须复用，不能各自维护一份。
6. 工作包创建与实施都不得移动或归档 T04/T05；归档只能由用户手动执行。

## Task 1：Agent policy、State 与统一事件契约

任务目标：建立不调用 Provider 或 Tool 的 Core Agent policy、不可变状态、安全快照、Turn 结果和统一 AgentEvent 契约。

新增文件：

- `src/uthcode/core/agent.py`：定义循环配置、运行状态、终止原因、assistant 分类、安全快照和 Turn 结果的权威 Core 模型；本 Task 不实现 Provider/Tool 调度。
- `src/uthcode/core/agent_events.py`：定义所有冻结 AgentEvent、稳定类型标识、序列化与恢复入口。
- `tests/test_agent_policy.py`：验证默认限制、非法值、深度不可变、新 Turn 重置和安全 Snapshot。
- `tests/test_agent_events.py`：验证所有事件的字段、关联 ID、JSON round-trip、reasoning 生命周期和非法 payload 拒绝。

修改文件：

- `src/uthcode/core/__init__.py`：只导出真实公共 Agent 类型，不导出内部状态写入 helper。
- `tests/test_package.py`：验证 Core/Application 的新导出与无副作用 import。

依赖任务：无。

参考资料定位：

- 原始需求第 3、4、8.1、8.2、15.1、15.2 节。
- `src/uthcode/core/provider.py` 的不可变 JSON 模型、Usage、Message 和序列化模式。
- 原 UthCode 固定提交的 policy、事件与终止场景只作行为证据，不迁移 Graph/Runtime API。

实施内容：

- `AgentLoopConfig` 的默认限制固定为 `max_iterations=50`、`max_tool_calls_per_iteration=16`、`max_consecutive_unknown_tools=3`，并拒绝 bool、零值、负值和非法类型。
- Core 公共模型至少包含 `AgentLoopConfig`、`RunStatus`、`TerminationReason`、`AssistantMessageKind`、`RunState`、`RunSnapshot`、`TurnResult`、`AgentLoop` 和 `AgentTurnExecution`；不得为旧命名提供 alias。
- RunState 深度不可变，每次变化创建新对象；只有后续 Agent Loop 能创建下一版。
- 新 Turn 保留此前权威 messages，重置 Turn 级 iteration、Tool 数、unknown streak、Usage、状态和终止原因。
- RunSnapshot 不含 messages、Provider native payload、SDK 类型、Exception、Path、bytes 或 Task。
- TurnResult 只包含标识、状态、原因、final 文本和统计；reasoning 不重复进入结果。
- AgentEvent 至少覆盖 `TurnStarted`、`IterationStarted`、`ReasoningStarted`、`ReasoningDelta`、`ReasoningFinished`、`AssistantMessageDelta`、`AssistantMessageCompleted`、`UsageUpdated`、`ToolBatchStarted`、`ToolStarted`、`ToolFinished`、`ToolBatchFinished`、`TurnCompleted`、`TurnFailed` 和 `TurnCancelled`，并提供 dict/JSON 恢复入口。
- 第一个非空 reasoning chunk 打开一段；非 reasoning 事件关闭当前段；后续 reasoning 可重新开启，保持 Provider 实际顺序。
- ToolStarted/ToolFinished 使用同一安全摘要字段；ToolFinished 不含 ToolResult content。
- 反序列化必须拒绝未知类型、缺失必需字段和非 JSON-safe 值。

完成边界：

- 本 Task 不导入、构造或调用 ProviderPort、ToolRegistry、ToolExecutor、Application 或 Interface。
- 不创建运行任务、事件队列、存储、Journal、Session、Context、Permission 或未来字段。
- 定向测试通过，公开类型与原始需求一致，无兼容 alias。

## Task 2：Provider 权威流与显式 Agent Loop

任务目标：复用现有 Provider/Tool 契约实现唯一显式 ReAct Loop，并使所有状态提交、Tool FIFO、限制、Usage、错误和取消路径可验证。

修改文件：

- `src/uthcode/core/provider.py`：提取 Provider 无关的共享流终态校验，保证唯一合法 terminal、EOF 后公开和 finally 关闭。
- `src/uthcode/core/agent.py`：实现 AgentLoop 与单 Turn 执行过程。
- `tests/test_provider_contract.py`：验证共享终态校验及既有 Provider DTO 行为不变。
- `tests/test_agent_loop.py`：新增完整 Loop 行为矩阵。

按需修改文件：

- `src/uthcode/integrations/providers/anthropic.py`
- `src/uthcode/integrations/providers/openai_responses.py`
- `src/uthcode/integrations/providers/openai_compat.py`
- 对应的三个 `tests/test_*_integration.py`

按需修改仅限各自线协议到统一 `FinishReason`、Message、ToolCall、Usage、错误或取消的映射。现有映射已满足用例时不得制造源码改动；不得修改 Provider DTO 字段或让 Core 感知 Provider 名称。

依赖任务：Task 1。

参考资料定位：

- 原始需求第 8.3、9、15.3 节。
- `src/uthcode/application/generation.py` 当前 terminal-held-until-EOF 逻辑。
- `src/uthcode/core/tool.py` 的 Registry 查询、`execute_call()`、取消和统一截断。
- 三个 Provider Integration 当前终态映射和离线 SDK Test Double。
- MewCode 只参考 assistant ToolCall 先入 conversation、结果原序回填、自然结束、Usage 和 unknown guard；禁止并行、双 Loop、Permission、恢复和可变 Conversation Manager。

实施内容：

- 每次 Provider 调用前检查并增加 iteration；Tool 执行不增加 iteration。
- 每个 iteration 通过调用方提供的请求准备 callable 获取 System Prompt、当前 conversation 和已固定 tools 的请求。
- 使用共享 Provider 流 helper；Text/Reasoning/ToolCall 增量只形成显示事件，不直接写入 conversation。
- 只从合法 `GenerationCompleted.response` 累计 Usage、读取 assistant message、finish reason 和 ToolCall。
- assistant 分类顺序为：长度或不完整终态、包含 ToolCall、普通 final；Provider error/cancelled/unknown 由统一错误与终止语义收口。
- 有 ToolCall 时先提交完整 assistant terminal Message，再按原序逐个调用同一个 ToolExecutor，最后把同批结果组成一个 tool Message。
- 单 iteration ToolCall 超限时整批零执行，为每个 call 生成同 ID 受控结果并终止；不得只执行前一部分。
- unknown streak 由 Registry 查询事实判断；已注册 Tool 立即归零，不读取 ToolResult 文案。
- 普通 unknown、invalid arguments、tool error 和截断结果默认允许下一次 Provider 调用纠正。
- LENGTH/INCOMPLETE 与 ToolCall 同时出现时不执行工具，生成同 ID 未执行结果并安全终止。
- Provider 阶段取消丢弃 partial 对 conversation 的影响；Tool 阶段取消保留已完成结果，并为当前及剩余 call 补齐 cancelled 结果。
- 每个 Turn 只产生一个 terminal；terminal 后不再发事件、写状态、调用 Provider 或执行 Tool。
- `Usage` 只累计权威 terminal，按 Turn 重置。

Provider 逐协议验证：

- Anthropic 根据自身 stop reason 和 content blocks 产生统一 final、tool calls、length、error 与取消结果。
- OpenAI-compatible 根据 choices finish reason 和 tool call deltas 产生统一结果。
- OpenAI Responses 根据 response terminal event、status、incomplete details 和 output items 产生统一结果；失败终态不能伪装为成功。
- 三组 Integration 测试分别固化各自行为，Agent Loop 测试只使用统一 Fake Provider。

完成边界：

- 不修改 Tool DTO、Tool Protocol、六个默认 Tool、System Prompt 正文或配置。
- 不创建 Graph、Node、Router、Runtime 大对象、并行 Tool 或第二套自动 Loop。
- Core 不导入 Application/Integration/Interface；Provider Integration 不导入 Application/Interface。

## Task 3：Application Run/Turn 与安全 Tool 摘要

任务目标：在 Application 中组合 Core Agent Loop、现有 Provider、System Prompt 和同一 Tool Runtime，提供隔离的内存 Run、TurnHandle 与安全 Tool 摘要。

新增文件：

- `src/uthcode/application/runs.py`：实现 AgentRun、TurnHandle、Run 生命周期、Turn 资源快照、事件生产与结果等待。
- `tests/test_application_runs.py`：验证 Run/Turn、多 Turn、隔离、快照、并发占用、模型快照和失败后继续。

修改文件：

- `src/uthcode/application/generation.py`：复用共享 Provider 校验并抽取可供每个 Agent iteration 使用的请求准备逻辑；保留低层 GenerationHandle。
- `src/uthcode/application/tools.py`：复用唯一 Registry/Executor，向 Application 内部提供逐个执行、known 查询和安全摘要能力。
- `src/uthcode/application/bootstrap.py`：装配 Run 所需真实依赖，不创建 Service Locator。
- `src/uthcode/application/__init__.py`：导出 AgentRun、TurnHandle、AgentEvent、RunSnapshot 和 TurnResult 等 Headless API，不导出 RunState/Registry/Executor。
- `tests/test_application.py`、`tests/test_application_tools.py`、`tests/test_application_runtime.py`、`tests/test_package.py`：补充低层 API、模型快照、Tool Runtime 和导出回归。

依赖任务：Task 2。

参考资料定位：

- 原始需求第 3.1、8.4、8.5、8.6、15.4 节。
- 当前 `generation.py` 的 Provider/model 快照、System Prompt 准备和模型切换。
- 当前 `tools.py` 的单一 Registry/Executor 所有权。
- T04 Application Tool API、手动往返测试与 W04 Feedback。

实施内容：

- `create_run()` 创建独立 Core 初始状态；不同 Run 不共享 conversation、活动 Turn 或取消令牌。
- `start_turn()` 同步校验输入并立即占用 Run；活动 Turn 存在时拒绝第二次启动。
- Turn 开始时固定 Provider、Model Ref、有序 Tool definitions、安全摘要 callable 和独立 CancellationToken。
- System Prompt 每个 iteration 继续由 Application 基于已固定 Provider/Model 和当前 conversation 构建。
- `events()` 保持单消费者；`result()` 为可重复等待的异步接口；二者首次调用时只启动一次后台执行。
- terminal 后把 Core 返回的最新状态引用保存到 AgentRun，释放占用；失败/取消后的下一 Turn 沿用最后一版已闭合 conversation。
- `/model` 或 Headless 模型切换在活动 Turn 中不影响该 Turn，只影响下一 Turn。
- 安全摘要按 Tool schema/语义生成单行文本：命令型显示命令，文件型显示操作与路径，搜索型显示 pattern/scope。
- 不显示写入 content、ToolResult、秘密、环境变量值或 unknown 参数；unknown 使用安全占位；默认最多保留 240 个 Unicode 字符并稳定截断。
- 摘要失败返回安全占位，不能阻止 Tool 执行。
- Application 内部可把同一 Registry/Executor 传给 Core Loop，但公共 API 不泄漏它们。

完成边界：

- raw generation 不自动注入 tools，手动 Tool API 仍按 T04 语义工作。
- 不创建第二 Registry/Executor、第二 System Prompt 路径、Session、持久化或全局 Run Manager。
- Interface 不参与本 Task。

## Task 4：Headless Agent 端到端闭环

任务目标：从正式 Application 入口证明 reasoning、真实只读 Tool、自动回填、final、多 Turn 和结果隐藏完整工作。

修改文件：

- `tests/test_application_runs.py`：增加正式 Headless E2E 和多 Turn/多 Run场景。
- `tests/test_agent_loop.py`：补齐 E2E 暴露的 Core 协议闭合断言。
- `README.md`：增加 Run/Turn Headless 示例、事件消费、低层 API 区别和 Bash 边界说明。

依赖任务：Task 3。

参考资料定位：

- 原始需求 Task 4、第 10.1、15.8 节。
- T04 `test_application_tools.py` 手动往返，用于对照自动路径而非复制。
- Fake Provider 和真实临时 workdir 的 ReadFile Tool。

实施内容：

- 使用 `create_application()`、`create_run()`、`start_turn()` 正式入口。
- Fake Provider 先发 reasoning 和只读 ToolCall；Application 通过真实 ReadFile 执行并自动回填；第二次 Provider 请求返回 final。
- 断言 ToolResult 的 ID、顺序和真实文件内容进入下一次请求。
- 断言 AgentEvent 只公开 reasoning 和 Tool 安全摘要，ToolFinished 与 TurnResult 不含 ToolResult 正文。
- 断言同 Run 第二 Turn 包含第一 Turn 权威 conversation，不同 Run 请求隔离。
- 断言只等待 `result()` 和消费 `events()` 两种方式都能完成同一唯一执行过程。
- Headless 测试不得导入 Interface，不访问网络或真实 Provider。

完成边界：

- README 不承诺 Permission、Sandbox、Session、Context、Memory 或持久化。
- 不以私有 helper 代替正式入口，不删除 T04 手动低层往返测试。

## Task 5：CLI AgentEvent 投影

任务目标：把 `uthcode exec` 切换到正式 Run/Turn，并稳定分离 final stdout 与活动 stderr。

修改文件：

- `src/uthcode/interfaces/cli.py`
- `tests/test_cli.py`

依赖任务：Task 4。

参考资料定位：

- 原始需求第 3.3、10.2、15.5 节。
- 当前 CLI 的参数、配置、stdin、错误脱敏和 Textual 延迟导入测试。

实施内容：

- `exec` 为每次调用创建独立 Run 和单个 Turn。
- 根据 AssistantMessageCompleted 分类缓冲/投影文本；未分类 TextDelta 不直接写 stdout。
- final answer 只在 TurnCompleted 后写 stdout，不加前缀。
- reasoning、progress、incomplete、Tool started/finished、失败和取消写 stderr。
- Tool 行只包含状态、name 和 Application 提供的 command 摘要。
- stdout/stderr 都不得包含 ToolResult content、AgentEvent dict、traceback、秘密或内部绝对路径。
- 保持 completed、failed、cancelled/Ctrl+C、参数/配置错误的既有退出码。
- stdin 中以 `/` 开头的文本继续作为普通 Prompt。
- `exec` import 和运行路径不得加载 Textual/TUI。

完成边界：

- CLI 不导入 Core/Integration，不解析原始 Tool arguments，不实现 ReAct 逻辑。
- 不增加新 CLI 子命令或改变配置格式。

## Task 6：TUI 活动流与视觉层级

任务目标：让当前简单 TUI 使用一个内存 Run 进行多 Turn，并把 AgentEvent 投影为清晰、低噪声的用户、Agent 和 Tool 活动流。

修改文件：

- `src/uthcode/interfaces/tui/app.py`：拥有一个 AgentRun，启动/消费 TurnHandle，保持命令、模型和双 Esc 生命周期。
- `src/uthcode/interfaces/tui/rendering.py`：只消费 AgentEvent，批量追加 reasoning/assistant 文本并维护 Tool 行更新。
- `src/uthcode/interfaces/tui/state.py`：只保存显示块、Tool 行映射、滚动、活动 Turn 和取消提示状态。
- `src/uthcode/interfaces/tui/widgets.py`：实现用户背景块、Agent 正文块和 Tool 低强调活动行。
- `src/uthcode/interfaces/tui/tui.tcss`：使用现有主题 token 实现完整用户背景、正常正文色和 muted Tool 样式。
- `tests/test_tui.py`：覆盖多 Turn、视觉层级、Tool 隐藏、流式 batching、Slash Command、模型切换、滚动和取消。

依赖任务：Task 5。

参考资料定位：

- 原始需求第 3.4、10.3–10.6、15.6、15.7 节。
- 当前 TUI 的 Completion、Picker、Composer、滚动保护、0.2 秒批量刷新和双 Esc 行为。
- Textual 当前 theme token 和 Pilot 测试模式。

实施内容：

- TUI 启动时创建一个 AgentRun；每次普通输入在同一 Run 中启动新 Turn。
- 活动 Turn 拒绝第二次普通输入并阻止 `/model`；终态后模型切换只影响下一 Turn。
- `/clear` 只删除显示 Widget/状态，不替换 AgentRun 或清除 conversation。
- UserMessageBlock 使用容器级背景、完整可用宽度、非零 padding 和正常文本色。
- AgentTextBlock 承载 reasoning、progress、final，均使用正常正文色且不使用 dim/italic。
- ToolActivityRow 只显示 status/name/command，使用 muted/secondary token；同 call ID 更新同一行或稳定成对显示。
- ToolResult content 不进入 DOM、render tree、state 或 snapshot，不提供展开按钮。
- 流式 reasoning/assistant 复用当前 block，不为每个字符创建 Widget。
- 双 Esc 只取消活动 TurnHandle；关闭界面时收口活动任务和 timer。
- TUI 只从 Application 导入公共 Agent API，不接触 ProviderEvent、RunState、Registry、Executor 或原始 Tool 参数。

完成边界：

- 不创建时间线框架、结果卡片、Permission UI、Diff、Session Picker 或新的主题系统。
- Completion、Picker、Composer、Topbar、滚动和 Slash Command 既有语义保持。

## Task 7：[接入主流程] 统一正式 Agent 路径

任务目标：收口唯一正式 Agent 路径，删除被替代的 Interface ProviderEvent 普通输入路径，同时保留低层 API。

修改文件：

- `src/uthcode/application/__init__.py`
- `src/uthcode/interfaces/cli.py`
- `src/uthcode/interfaces/tui/app.py`
- `src/uthcode/interfaces/tui/rendering.py`
- `src/uthcode/interfaces/tui/state.py`
- `src/uthcode/interfaces/tui/widgets.py`
- `tests/test_application_runs.py`
- `tests/test_cli.py`
- `tests/test_tui.py`
- `tests/test_architecture_boundaries.py`
- `tests/test_package.py`
- `README.md`

删除文件：仅删除经调用方和测试证明已被替代且无剩余职责的旧 Interface renderer/state/helper；不得仅因文件名旧而删除仍承载显示功能的文件。

依赖任务：Task 1–Task 6。

参考资料定位：

- 原始需求第 7、11、12、16 节。
- 当前架构边界、包导出和低层 Generation/Tool API 测试。

实施内容：

- 正式普通输入固定为 `Headless/CLI/TUI → Application Run/Turn → Core AgentLoop`。
- Interface 中不再导入或消费 ProviderEvent、GenerationHandle、ProviderPort、Tool Registry/Executor。
- Application 公开 Agent API 但不公开 Core RunState 或 Tool Runtime 内部对象。
- `start_generation()`、`stream_generation()`、`tool_definitions()`、`execute_tool_calls()` 保留并继续通过原测试。
- README 明确自动 Agent API 与低层单轮/手动 Tool API 的区别。
- 架构门禁只放行真实 Agent 文件和依赖边，不以宽泛白名单规避扫描。

完成边界：

- 不保留 Interface 旧自动路径的 Adapter、Facade、Shim、deprecated alias 或双 renderer。
- 不删除 T04 的真实低层调用方和测试。

## Task 8：[端到端验证] 全链路与回归验证

任务目标：用离线、可复现证据验证 Core、Application、三个 Provider、CLI、TUI 和既有能力共同工作。

修改文件：仅限验证发现的 T05 范围内缺陷对应文件、测试、README、Checklist 和本 Worker Feedback。

依赖任务：Task 7。

参考资料定位：

- 原始需求第 14、15、17 节。
- 本工作包 Checklist。
- T04 最终 Feedback 中的基线测试分组。

验证顺序：

1. 编译 Core、Application、Integration、Interface 和 tests。
2. 运行 Agent policy/event/loop/Application Run 定向测试。
3. 运行既有 Application Tool、CLI、TUI 回归。
4. 分别运行 Anthropic、OpenAI Responses、OpenAI-compatible 的协议测试。
5. 运行架构和 package 测试。
6. 运行全量 pytest、pip check 和 `git diff --check`。
7. live Provider 测试保持显式授权门禁，不发起真实费用请求。

完成边界：

- 不为通过测试放宽安全断言、删除既有验收或加入 Provider 特判。
- 不修复无关历史问题；发现范围外问题写入 Feedback。

## Task 9：[遗留负担清理] 删除旧路径与重复职责

任务目标：确认 T05 最终只保留一套自动 Agent Loop、一条正式 Agent 路径和职责清晰的低层 API。

检查及按需修改范围：

- `src/`、`tests/`、`README.md` 中由 T05 引入、替代或暴露的实现。

依赖任务：Task 8。

参考资料定位：

- 原始需求第 14 Task 9、第 16、17 节。
- `AGENTS.md` 非兼容性原则。

必须检查：

- Interface 不含普通输入 ProviderEvent 路径或 Core/Integration import。
- TUI 不含 ToolResult content 展示、展开入口、原始 arguments 解析或权威 conversation 副本。
- Core Agent Loop 不含 `asyncio.gather`、TaskGroup、Graph、Provider 名称分支或 Application/Integration import。
- 不存在第二套自动 Loop、无调用方旧 renderer、兼容 alias、Facade、Shim、Runtime 大对象和不可达分支。
- Application 不公开 Registry、Executor、RunState 或 Provider native payload；T04 低层 API 已公开的取消类型保持原有边界。
- 不存在 MewCode/旧 UthCode runtime import、LangGraph/LangChain、Permission、Context、Memory、Session、Journal、Diff、MCP、Skill、Worktree、Subagent 或未来占位。
- README 不把 Bash 描述为 Sandbox，不承诺未交付能力。

完成边界：

- 只删除经引用、测试和正式入口证明已被替代的代码，不移动或归档工作包。
- 若扫描无需源码清理，不制造无意义改动。
