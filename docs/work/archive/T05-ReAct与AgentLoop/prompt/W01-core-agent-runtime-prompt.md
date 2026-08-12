# W01 core-agent-runtime Prompt

请在 `D:\project\Re-UthCode` 中严格按 Task 1 → Task 2 实施 T05 Core Agent 契约与唯一显式 Agent Loop，完成后写入 `docs/work/T05-ReAct与AgentLoop/feedback/W01-core-agent-runtime-feedback.md`。只执行本 Worker，不开始 Task 3–Task 9。每个 Task 完成后先运行对应定向测试并审查差异；未经用户另行授权，不执行任何 Git 写操作。

## 必读资料

1. `AGENTS.md`、`SRe-AGENTS.md`、`docs/work/README.md`。
2. T05 原始需求、Spec、Tasks、Checklist。
3. `src/uthcode/core/provider.py`、`src/uthcode/core/tool.py`、`src/uthcode/core/__init__.py`。
4. `src/uthcode/application/generation.py`，只用于提取现有 Provider terminal-held-until-EOF 逻辑，不在 Task 1 修改。
5. `tests/test_provider_contract.py`、`tests/test_tool_core.py`、`tests/test_package.py`。
6. 三个 Provider Integration 及其离线测试，重点核对各自 wire terminal 到统一 FinishReason/Message/ToolCall/Usage 的现有映射。
7. 原 UthCode 固定提交 `1c3507b761e48ac38d846bc39700ce0039f84a04` 的 Day4 测试场景；MewCode `agent.py`、`conversation.py`、`test_agent.py` 只提取顺序 Loop、消息闭合、Usage 和 unknown guard，不复制旧 API、并行、恢复或后置能力。

## 已确认决策

- Core 拥有 Agent Loop、权威 RunState、终止策略、Tool batch 语义和 AgentEvent。
- Agent Loop 是 RunState 的唯一写入者，每次状态变化创建新 frozen 对象。
- Provider partial 只产生显示事件；只有合法 `GenerationCompleted.response` 能提交 conversation 和 Usage。
- Provider 线协议差异分别留在 Anthropic、OpenAI Responses、OpenAI-compatible Integration；Core 禁止 Provider 名称分支。
- 三个 Adapter 先以现状增加定向回归；只有测试证明映射缺失时才窄改对应 Adapter，不修改 Provider DTO。
- Tool 严格 FIFO，逐个复用现有 `ToolExecutor.execute_call()`；禁止 `gather`、TaskGroup 和任何并行窗口。
- ToolCall 在正常、普通错误、unknown、超限、截断和取消路径都必须得到同 ID 结果。
- reasoning 公开为 AgentEvent，但不成为独立权威状态写入来源。
- 每 Turn 恰有一个 completed、failed 或 cancelled terminal。

## 修改范围与顺序

### Task 1

严格修改/新增 Tasks 中 Task 1 文件。先完成 policy、State/Snapshot/Result 和 AgentEvent contract，不调用 Provider/Tool，不创建异步执行任务。

### Task 2

在 Task 1 通过后：

- 提取 Core 共享 Provider stream terminal 校验，并让现有 Generation 后续可复用。
- 实现唯一显式 Agent Loop、请求准备 callable、FIFO Tool 调度、限制、Usage、错误和取消闭合。
- 增加完整 `test_agent_loop.py`。
- 分别验证三个 Provider Integration；只有协议映射测试失败且证据指向 Adapter 时才修改该 Adapter。

不得修改 Tool DTO/Protocol、六个内置 Tool、配置、System Prompt 正文、Slash Command、Application Run、CLI 或 TUI。不得创建 Graph、Runtime、Permission、Context、Session、Journal、Memory、Diff 或未来占位。

## 实施与验证

- 所有命令使用 `conda run --no-capture-output -n re-uthcode ...`。
- 先执行 Task 1 Checklist；通过后再执行 Task 2 Checklist。
- 必须覆盖普通回答、reasoning、单/多 Tool、多步 Loop、普通 Tool 错误、unknown reset/limit、Tool 数超限、max iteration、LENGTH/INCOMPLETE、Provider 协议错误、Provider/Tool 取消、Usage 和下一 Turn 可继续。
- 三个 Adapter 测试使用现有 SDK Test Double，不发真实请求；未授权 live 用例保持 skip。
- 完成后运行 Core/Provider/Tool/package 定向回归、`python -m compileall -q src tests`、`python -m pip check` 和 `git diff --check`。
- Checklist 只允许勾选 Task 1、Task 2 的现有复选框，不修改文字、结构、编号或顺序。
- 修改任何 Markdown 后执行 UTF-8 解码、常见乱码标记和 Markdown fence parity 检查。

## Feedback

创建 `feedback/W01-core-agent-runtime-feedback.md`，说明：

- policy、State/Snapshot/Result 的实际结构和所有权；
- AgentEvent、reasoning 段和唯一 terminal；
- Provider 权威流校验及三个协议各自适配/验证结果；
- Tool FIFO、同 ID 闭合、限制、unknown、Usage 和取消；
- 修改文件、定向测试精确结果、Checklist 状态；
- 与任务书不同的实际情况、未完成项和风险；
- Graph、双 Loop、Provider 分支、并行和未来能力扫描结果。

若必须修改 Provider DTO、Tool DTO/Protocol、默认 Tool、System Prompt、配置，或无法在取消后闭合全部 ToolCall，停止相关范围并在 Feedback 中记录。
