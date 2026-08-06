# W04 delivery-verification Prompt

请在 `D:\project\Re-UthCode` 中严格按 Task 7 → Task 8 → Task 9 完成 T05 主流程接入、全链验证和遗留清理，并写入 `docs/work/T05-ReAct与AgentLoop/feedback/W04-delivery-verification-feedback.md`。开始前确认 W01–W03 Feedback、Task 1–Task 6 Checklist 和各自定向测试全部完成；不重新设计已审查的 Core 语义。未经用户另行授权，不执行 Git 写操作。

## 必读资料

1. `AGENTS.md`、`SRe-AGENTS.md`、`docs/work/README.md`。
2. T05 原始需求、Spec、Tasks、Checklist 和 W01–W03 Feedback。
3. 当前 Core Agent、Application Run/Turn、CLI、TUI、三个 Provider Integration 及全部新增/修改测试。
4. T04 最终 Feedback，确认低层 Generation/Tool API、默认 Tool 顺序、Application 隔离和 Bash 边界必须保留。
5. T02/T03 既有 Slash Command、配置、模型切换、System Prompt 和 Interface 依赖边界。

## 已确认决策

- 正式 Agent 路径唯一：Headless/CLI/TUI → Application Run/Turn → Core AgentLoop。
- 低层 `start_generation`/`stream_generation` 和手动 Tool API 保留，但不得形成第二套自动 Loop。
- 三个 Provider 各自在 Integration 中适配 wire protocol；Core 无 Provider 名称分支。
- Interface 不再消费 ProviderEvent 或 GenerationHandle 处理普通输入。
- ToolResult 正文在 CLI/TUI 完全隐藏；TUI 不拥有 RunState。
- TUI 样式通过 `tui.tcss` 和现有 theme token 实现。
- 不引入 LangGraph、Permission、Context、Session、Journal、Memory、Diff 或其他后置能力。
- T04/T05 不由 Agent 归档。

## 修改范围与顺序

### Task 7

- 收口正式导出与调用链。
- 删除 Interface 旧 ProviderEvent 普通输入路径、无调用方 renderer/state/helper 和 ToolResult 展示入口。
- 保留并回归低层 Generation/Tool API。
- 更新架构门禁、包测试和 README。

只删除经调用方、测试和静态扫描证明已被替代的代码；不得删除 T04 真实低层调用方。

### Task 8

严格按 Checklist 顺序运行：

- compileall；
- Core Agent/Application Run 定向测试；
- Application Tool/CLI/TUI 回归；
- Anthropic、OpenAI Responses、OpenAI-compatible 各自协议测试；
- 架构/package；
- 全量 pytest、pip check、diff check。

未授权 live Provider 测试必须继续 skip，不发网络请求或产生费用。只修复 T05 范围内缺陷。

### Task 9

- 执行 Checklist 中全部否定性扫描。
- 删除重复 Loop、兼容层、旧 renderer、不可达代码、Interface 原始参数解析和未来占位。
- 重新运行受影响定向测试、架构/package 和全量测试。
- 若扫描结果来自测试门禁自身，使用运行时字符串拼接避免自命中，不删除门禁语义。

## 实施与验证

- 使用 `conda run --no-capture-output -n re-uthcode ...`。
- 对每个 Task 分别记录开始基线、修改范围、测试结果和审查结论。
- Headless E2E 必须使用正式入口和真实临时目录只读 Tool。
- CLI E2E 必须证明 final stdout 与 activity stderr 分离。
- TUI Pilot 必须证明用户背景块、正常 Agent/reasoning 正文、muted Tool 行和 ToolResult 正文不可见。
- 检查 Provider 调用次数、Tool FIFO、所有 call ID 闭合、唯一 terminal、多 Turn 和失败/取消后继续。
- README、Checklist 和 Feedback 修改后执行严格 UTF-8 解码、乱码标记和 Markdown fence parity 检查。
- Checklist 只勾选 Task 7–Task 9 现有项；不得修改任何冻结工作包文字、结构、编号或顺序。

## Feedback

创建 `feedback/W04-delivery-verification-feedback.md`，以人工审查为目标精简说明：

- 最终 Agent 调用链与低层 API 的保留边界；
- Run/Turn、Provider snapshot、State/Event、reasoning、Tool FIFO、限制、Usage 和取消；
- 三个 Provider 各自协议适配/回归结果；
- CLI stdout/stderr 和退出码；
- TUI 多 Turn、视觉层级、Tool 行与正文隐藏；
- 实际新增、修改、删除文件；
- Task 7、Task 8、Task 9 的精确测试结果和全量总数；
- Checklist 完成情况、与任务书差异、风险或未完成项；
- 双路径、兼容层、旧 renderer、未来占位和旧项目依赖清理结果。

若发现冻结工作包错误、必须扩大到后置能力、Tool 副作用状态无法确认、Provider DTO 必须重设计或 Interface 必须越界，停止相关范围并在 Feedback 中记录，由用户决定是否终止并重建工作包。
