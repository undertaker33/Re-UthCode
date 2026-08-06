# W03 interface-activity Prompt

请在 `D:\project\Re-UthCode` 中严格按 Task 5 → Task 6 实施 T05 CLI/TUI AgentEvent 投影，完成后写入 `docs/work/T05-ReAct与AgentLoop/feedback/W03-interface-activity-feedback.md`。开始前确认 W01、W02 已完成，Headless E2E 已通过；只执行本 Worker，不开始 Task 7–Task 9。未经用户另行授权，不执行 Git 写操作。

## 必读资料

1. `AGENTS.md`、`SRe-AGENTS.md`、`docs/work/README.md`。
2. T05 原始需求、Spec、Tasks、Checklist 和 W01/W02 Feedback。
3. Application 公开 Agent API、AgentEvent 和 `tests/test_application_runs.py`；不得从 Core 内部文件导入类型。
4. `src/uthcode/interfaces/cli.py`、`tests/test_cli.py`。
5. `src/uthcode/interfaces/tui/app.py`、`rendering.py`、`state.py`、`widgets.py`、`tui.tcss`、`tests/test_tui.py`。
6. T02 的 CLI/TUI 冻结行为与现有 Completion、Picker、Composer、滚动、Slash Command 和双 Esc 测试。

## 已确认决策

- Interface 只能依赖 `uthcode.application`；不得导入 Core、Integration、Provider SDK、Registry 或 Executor。
- CLI/TUI 普通输入改为 Application Run/Turn；ReAct 逻辑不得写进 Interface handler。
- CLI final 只进 stdout；reasoning、progress、incomplete、Tool 活动、失败和取消进 stderr。
- TUI 生命周期内使用一个 Run，多次普通输入形成多个 Turn；`/clear` 只清显示。
- reasoning 与 final 都使用正常正文色，不使用 dim、italic、隐藏或折叠。
- 用户消息使用完整背景容器；Tool 活动使用 muted/secondary 层级。
- Tool 行只显示 status/name/Application command，不显示 ToolResult，也不解析原始 arguments。
- `tui.tcss` 明确属于 Task 6 修改范围，样式继续使用 Textual theme token。
- 既有 Slash Command、Completion、Model Picker、滚动、Composer、Topbar 和双 Esc 语义必须保留。

## 修改范围与顺序

### Task 5

只修改 CLI 和其测试：

- `exec` 创建独立 Run/Turn；
- 根据 AgentEvent 的 assistant 分类决定输出目的地，未分类 delta 不直接写 stdout；
- 隐藏 ToolResult 正文和内部事件对象；
- 保持参数、配置、stdin、错误脱敏、退出码和 Textual 延迟导入。

先完成全部 Task 5 Checklist 并运行 `tests/test_cli.py`。

### Task 6

Task 5 通过后修改 TUI 六个列出文件：

- TUI 创建并持有一个 AgentRun，只持有活动 TurnHandle，不接触 RunState；
- renderer 只消费 AgentEvent，按事件顺序复用文本 block、创建/更新 Tool 行；
- state 只保存显示所需 ID、Widget 映射、滚动和取消提示；
- widgets 实现 UserMessageBlock、AgentTextBlock、ToolActivityRow 或等价最小组件；
- `tui.tcss` 用 `$surface`/`$panel`/`$text`/`$text-muted` 等现有语义 token 表达层级；
- ToolResult 正文不进入 DOM、render tree、state 或任何展开入口。

不得创建新的通用 UI 框架、时间线、Tool 结果卡片、Permission UI、Session Picker、Diff 或主题系统。

## 实施与验证

- 使用 `conda run --no-capture-output -n re-uthcode ...`。
- CLI 测试必须使用 Fake Application/Provider，不访问网络。
- TUI 使用 Textual Pilot 和可控 Fake Provider/Tool，验证多 Turn、模型 snapshot、`/clear`、Tool 行、正文隐藏、流式 batching、弹层 Esc 和双 Esc。
- 为 ToolResult 正文使用独特 sentinel，显式搜索 stdout、stderr、DOM、render tree 和 state。
- 检查长 command 来自 Application 已截断值；Interface 不读取 ToolCall arguments。
- 执行 Interface 导入扫描，确认 `uthcode.core`、`uthcode.integrations`、ProviderEvent 和 GenerationHandle 不再用于普通输入。
- 完成后运行 CLI/TUI/Application Run/架构/package 回归、compileall、pip check 和 diff check。
- Checklist 只勾选 Task 5、Task 6 现有项。
- 修改 CSS、README 或 Feedback 后执行 UTF-8 与 Markdown fence 检查。

## Feedback

创建 `feedback/W03-interface-activity-feedback.md`，说明：

- CLI AgentEvent 到 stdout/stderr/exit code 的实际映射；
- TUI 一个 Run、多 Turn、模型切换、`/clear` 和取消生命周期；
- 用户背景块、Agent 正文、reasoning 和 Tool muted 行的实际 Widget/CSS 结构；
- ToolResult 正文隐藏和无原始参数解析证据；
- Slash Command、Picker、Composer、滚动等回归；
- 修改文件、测试精确结果、Checklist 状态、差异和风险。

若 Application Agent API 不足且需要 Interface 直连 Core/Integration，或必须展示 ToolResult 正文才能继续，停止并记录，不得绕过边界。
