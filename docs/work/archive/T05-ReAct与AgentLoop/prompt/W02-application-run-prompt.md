# W02 application-run Prompt

请在 `D:\project\Re-UthCode` 中严格按 Task 3 → Task 4 实施 T05 Application Run/Turn 与 Headless 自动闭环，完成后写入 `docs/work/T05-ReAct与AgentLoop/feedback/W02-application-run-feedback.md`。开始前确认 W01 Feedback、Task 1–Task 2 Checklist 和定向测试均已完成；只执行本 Worker，不开始 Task 5–Task 9。未经用户另行授权，不执行 Git 写操作。

## 必读资料

1. `AGENTS.md`、`SRe-AGENTS.md`、`docs/work/README.md`。
2. T05 原始需求、Spec、Tasks、Checklist 和 W01 Feedback。
3. W01 实际交付的 `core/agent.py`、`core/agent_events.py`、共享 Provider 校验及测试。
4. `src/uthcode/application/generation.py`、`tools.py`、`bootstrap.py`、`runtime_context.py`、`__init__.py`。
5. `tests/test_application.py`、`test_application_runtime.py`、`test_application_tools.py`、`test_package.py`。
6. T04 Spec、Tasks 和 W04 Feedback，重点核对同一 Tool Registry/Executor、默认六工具顺序、Application 隔离和手动低层往返。
7. T03 最终 System Prompt 行为，重点核对每次请求准备、调用方不能覆盖 prompt/model 和模型切换边界。

## 已确认决策

- Application 是 Headless 与 Interface 的唯一 Agent 入口；Core 不导入 Application。
- 同一 Application 的 Runs 复用同一 T04 Tool Runtime，不同 Application 隔离。
- 同一 Run 多 Turn 保留 Core 权威 conversation，不同 Run 隔离；每个 Run 同时最多一个活动 Turn。
- Turn 开始时固定 Provider、Model Ref、有序 Tool definitions、安全摘要 callable 和 CancellationToken。
- `start_turn()` 立即占用 Run，但不要求当前已有事件循环。
- `events()` 或异步 `result()` 的首次调用启动唯一执行过程；事件流单消费者，结果可重复等待，两者共享同一 terminal。
- System Prompt 每 iteration 继续由 Application 构建；当前 Turn 不受中途模型切换影响。
- Tool 摘要只能由 Application 根据正式 Tool Runtime 生成，Interface 不读取原始 arguments。
- raw Generation 不自动注入 tools；手动 Tool API 保留且不构成第二套自动 Loop。

## 修改范围与顺序

### Task 3

按 Tasks 新增 `application/runs.py` 和 `test_application_runs.py`，并窄改 generation/tools/bootstrap/Application exports 及直接回归测试。

必须：

- 不公开 RunState、Registry、Executor、具体 Integration Tool 或 Provider 内部对象；
- 不创建第二 Registry/Executor、Run Manager、Session、存储或 Service Locator；
- Tool 摘要不泄露写入正文、秘密、环境变量值、ToolResult 或 unknown 参数；
- 摘要异常不能阻止 Tool 执行；
- 失败/取消后保存最后一版已协议闭合状态并释放 Run。

### Task 4

Task 3 通过后，从正式 `create_application → create_run → start_turn` 入口建立离线 Headless E2E：

- Fake Provider 产生 reasoning 与 ReadFile ToolCall；
- 真实临时 workdir Integration Tool 执行；
- ToolResult 自动进入下一请求；
- final 与唯一 terminal 返回；
- ToolResult 正文不进入事件、Snapshot 或 TurnResult；
- 同 Run 多 Turn与不同 Run 隔离同时得到证明。

更新 README 的 Agent API 和低层 API 区分，但不得承诺 Permission、Sandbox、Session、Context、Memory 或持久化。

## 实施与验证

- 使用 `conda run --no-capture-output -n re-uthcode ...`。
- 严格完成 Task 3 Checklist 后再进入 Task 4。
- 保留 T04 手动 Tool 往返测试，证明自动 Agent API 没有破坏低层 API。
- 使用 Fake Provider 和临时目录，不访问真实 Provider、网络或用户工作区外路径。
- 完成后运行 Application/Tool/Core/package 定向测试、Headless E2E、compileall、pip check 和 diff check。
- 检查 Headless import 过程中没有加载 `uthcode.interfaces`。
- Checklist 只勾选 Task 3、Task 4 现有项。
- README 与 Feedback 使用 UTF-8 guard 等价检查：严格 UTF-8 解码、乱码标记、Markdown fence parity。

## Feedback

创建 `feedback/W02-application-run-feedback.md`，说明：

- AgentRun/TurnHandle 的占用、惰性启动、单生产者、事件与结果等待；
- Provider/Model/Tool snapshot 和每 iteration Prompt 准备；
- 同 Run 多 Turn、不同 Run 隔离和失败/取消后继续；
- Tool 摘要的安全规则与截断；
- Headless E2E 的真实消息/Tool 数据流及正文隐藏证据；
- raw Generation/Tool API 回归；
- 修改文件、测试精确结果、Checklist 状态、差异和风险。

若必须创建持久 Run/Session、修改配置/System Prompt/Tool DTO、向 Interface 暴露 Core State，或必须建立第二套自动 Loop，停止并记录。
