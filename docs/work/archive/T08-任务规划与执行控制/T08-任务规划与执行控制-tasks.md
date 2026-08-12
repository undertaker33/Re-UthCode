# T08 任务规划与执行控制 Tasks

## 1. Worker、分支、物理 Worktree 与依赖

本工作包使用一个前置合同 Worker、两个并行实施 Worker 和一个最终集成 Worker。W02、W03 只有在各自分支快进到 W01 完成提交后才可并行开工；W04 始终在最终保留分支工作。

| Worker | 分支 | 物理 worktree | 严格串行 Task | 依赖 |
| --- | --- | --- | --- | --- |
| W01 `core-contracts` | `T08-W01-core-contracts` | `D:\project\Re-UthCode-T08-W01` | Task 1 → Task 2 | 任务包基线提交 |
| W02 `runtime-application` | `T08-W02-runtime-application` | `D:\project\Re-UthCode-T08-W02` | Task 3 → Task 4 → Task 5 → Task 6 → Task 7 | 开工前必须 fast-forward 到 W01 tip |
| W03 `slash-tui` | `T08-W03-slash-tui` | `D:\project\Re-UthCode-T08-W03` | Task 8 → Task 9 | 开工前必须 fast-forward 到 W01 tip；可与 W02 并行 |
| W04 `integration-delivery` | `T08-任务规划与执行控制` | `D:\project\Re-UthCode` | Task 10 → Task 11 → Task 12 | W01、W02、W03 均已提交并写完 Feedback |

执行波次固定为：

```text
任务包基线
  ↓
W01 Core contracts
  ↓ W02/W03 各自 git merge --ff-only W01
  ├─ W02 Runtime + Application ─┐
  └─ W03 Slash + TUI ──────────┤ 并行
                               ↓
W04 merge W01 → W02 → W03
  → 接入主流程 → E2E → 遗留清理 → worktree 回收
```

Git 边界：

- W01、W02、W03 只在各自物理 worktree 工作，可提交各自实现、Checklist 勾选和对应 Feedback；不得 push、rebase、合并其他实施分支或清理 worktree。
- W02、W03 开工前只允许执行一次对 W01 的 `--ff-only` 同步；无法快进时立即停止，不得自行改历史。
- W04 负责本地合并、冲突消解、最终提交和已合并短期 worktree/分支清理；不得 push、删除远端分支、合并到 `main` 或删除 T05。
- 每个 Worker 开工前必须核对当前分支、仓库根目录和物理路径；不匹配时停止。
- 工作包首次派发后，需求、Spec、Tasks、Prompt 与 Checklist 文字冻结。Worker 只勾选自己 Task 的既有 Checklist 项，并首次创建同名 Feedback。

文件所有权：

- W01 独占 Core 合同、Hook、Prompt facts、Tool 规划可见性与相应合同测试；禁止修改 `core/agent.py`、Application 和 TUI。
- W02 独占 `core/agent.py`、`application/runs.py`、`application/generation.py`、`application/tools.py` 及对应运行测试。
- W03 独占 Slash Command 与 TUI 文件及其测试；跨层真实 E2E 留给 W04。
- W04 独占最终 composition、公共导出收口、`tests/test_t08_e2e.py`、跨分支修复和清理。

---

## Task 1 — Planning Domain、Tool 可见性与控制协议

### 任务目标

冻结 W02、W03 共同依赖的 Core 领域、控制协议、工具规划可见性和公开事件合同，使后续两个 Worker 能从同一强类型基线并行实施。

### 新增、修改和删除的文件

- 新增 `src/uthcode/core/planning.py`。
- 修改 `src/uthcode/core/tool.py`。
- 修改 `src/uthcode/core/interaction.py`。
- 修改 `src/uthcode/core/agent_events.py`。
- 修改 `src/uthcode/core/__init__.py`。
- 按现有职责修改 `src/uthcode/integrations/tools/file_tools.py`、`search_tools.py`、`process_tools.py`、`factory.py`，为全部内置普通工具声明规划可见性。
- 新增 `tests/test_planning.py`。
- 修改 `tests/test_tool_core.py`、`tests/test_agent_interaction.py`、`tests/test_agent_events.py` 及受影响的内置工具测试。
- 不删除整文件；删除被新最终合同取代且已有零调用方证据的旧枚举、别名或未实现占位。

### 文件职责及实施内容

- 建立不可变、JSON-safe 的 BehaviorMode、TaskStatus、TaskItem、TaskState、PlanState、RuntimeFeedback 和 Todo replace-all 参数解析；TaskState 保持顺序、至多一个进行中项并允许显式清空。
- 建立 Plan Review request/response、revision 校验和专用 Steering request。Steering 不是 PauseKind，Plan Review 是现有 typed pause union 的正式成员。
- 为普通 Tool Core 建立显式规划访问元数据：只读工具可见，Bash 可见但必须依赖 trusted preflight 的实际 READ 效果，写工具不可见；未声明的工具不得默认进入规划视图。
- AskUserQuestion 在两种模式均可见，TodoWrite 只属于默认模式 Core control path；二者不进入普通 ToolRegistry。
- 增加 BehaviorModeChanged、TaskStateChanged、PlanProposed、CompletionBlocked、UserSteeringRequested、UserSteeringApplied 的冻结、display-safe、严格序列化事件。
- PlanProposed 携带完整 revision 与 Plan 文本；TaskStateChanged 携带完整 replace-all 投影；Steering 事件不得泄露未受控 payload。

### 依赖任务

无。

### 参考资料定位

- 原始需求第 4、7、9、10、12、17、18、22.1、22.4、22.5 节。
- `docs/A01-AgentRuntime/AgentRuntime-Context.md`、`docs/A02-Control/Control-Context.md`、`docs/A03-State/State-Context.md`。
- 当前 `core/tool.py`、`interaction.py`、`agent_events.py` 与对应测试。

### 完成边界

- 纯合同、schema、序列化、Tool metadata 与测试通过。
- 不修改 Agent Loop、Application、Slash 或 TUI，不接入真实执行路径。
- 不新增旧实现适配器、默认名称白名单、动态 registry、future placeholder 或第二份状态模型。

---

## Task 2 — Runtime Hook 与 Runtime Prompt Facts

### 任务目标

建立当前只有两个真实生命周期点的 HookSet、纯控制结果与最小 Runtime Prompt Context，为 W02 提供可直接接线的稳定合同。

### 新增、修改和删除的文件

- 新增 `src/uthcode/core/hooks.py`。
- 修改 `src/uthcode/core/prompt.py`。
- 按公共合同需要修改 `src/uthcode/core/__init__.py`。
- 新增 `tests/test_runtime_hooks.py`。
- 修改 `tests/test_system_prompt.py`、`tests/test_architecture_boundaries.py`。
- 不创建 hooks package、plugin 目录或配置文件。

### 文件职责及实施内容

- HookSet 只包含 `before_tool_execution` 与 `before_completion` 两组有序、不可变、同步 Hook。
- 工具执行前结果只有 Continue 或 Reject；完成前结果只有 Continue、Block 或 RequestPause。上下文与结果均为冻结 Core 值，禁止字典分发和字符串 Hook name。
- 提供规划模式只读策略、Plan proposal 与未完成 Task completion control 所需的纯 Hook 实现或纯构造函数；Hook 只计算结果，不生成 ID、不写状态、不调 Agent/Tool。
- 固定完成 Hook 顺序为 Plan completion 在前、Task completion 在后；意外异常由调用方 fail-closed。
- Runtime Prompt Context 只包含 behavior mode、TaskState、PlanState 与一次性反馈，不接收整个 RunState、Registry、Application 或 UI。
- 默认模式和规划模式生成明确不同的最小行为 section；Task、Plan、Steering 与 completion feedback 不伪装成 conversation message。
- 只精确放行 `core/hooks.py` 架构路径，继续禁止 Hook package、动态注册器、全局 registry 与范围外插件 Runtime。

### 依赖任务

Task 1。

### 参考资料定位

- 原始需求第 5、6、8、11、13、14、20、22.2、22.6 节。
- 当前 `core/prompt.py`、`tests/test_system_prompt.py`、`tests/test_architecture_boundaries.py`。

### 完成边界

- Hook 与 Prompt 合同测试、架构测试通过，W01 Feedback 明确公开合同和后续接线点。
- 不修改 `core/agent.py`，不产生真实 Tool、Pause、Message、Event 或 Turn 状态变化。

---

## Task 3 — Behavior Mode 与 Dynamic Tool View

### 任务目标

把 Behavior Mode 接入唯一 Agent Loop 和每次 Provider request，在保持 Turn 内 Provider、model 与 Tool universe 稳定的同时支持批准后的动态可见工具切换。

### 新增、修改和删除的文件

- 修改 `src/uthcode/core/agent.py`。
- 修改 `src/uthcode/application/generation.py`。
- 修改 `src/uthcode/application/tools.py`。
- 修改 `tests/test_agent_loop.py`、`tests/test_application.py`、`tests/test_application_runtime.py`、`tests/test_application_tools.py`。
- 按当前真实职责新增窄化 request-composition 测试时，优先扩充上述文件，不复制重复夹具。

### 文件职责及实施内容

- Turn 开始时将 idle behavior mode 快照进入 RunState；新 Turn 重置 TaskState、PlanState 与一次性反馈。
- Request preparer 每次 iteration 接收当前结构化 Runtime facts 与可见 Tool View，而不是忽略 Core 传入值并永久复用完整 definitions。
- PLAN view 只包含 ReadFile、Glob、Grep、Bash 与 AskUserQuestion；DEFAULT view 在此基础上包含 WriteFile、EditFile 与 TodoWrite。
- 普通工具保持 `registered/schema → trusted preflight → before-tool Hook → permission → execute`；PLAN 非 READ 在权限前受控拒绝，full_access 不得绕过。
- 构造但不可见的 Write/Edit、PLAN 中构造的 TodoWrite、未知工具和非法参数均闭合原 call ID，且不建立第二套执行器。

### 依赖任务

Task 2；W02 分支必须已 fast-forward 到 W01 tip。

### 参考资料定位

- 原始需求第 4、6.3、11.4～11.5、12、19.2～19.3、22.3、22.8、22.9 节。
- 当前 `core/agent.py` 的 request preparation、Tool batch 与 Permission 链。
- W01 Feedback 中冻结的 Tool access、Hook 与 Runtime Prompt 合同。

### 完成边界

- Mode 与动态 Tool View 的 Core/Application 定向测试通过。
- 不实现 Plan Review、Todo completion、Steering 或 TUI；不得通过重建 Turn、按 Provider 名称分支或散落工具名称过滤完成切换。

---

## Task 4 — Plan Proposal / Review / Approve

### 任务目标

完成规划模式候选 final 到 Plan proposal、typed review、完整替代修订与同 Turn 批准实施的权威状态机。

### 新增、修改和删除的文件

- 修改 `src/uthcode/core/agent.py`。
- 修改 `src/uthcode/application/runs.py`。
- 修改 `tests/test_agent_loop.py`、`tests/test_application_runs.py`。
- 只在 W01 合同缺陷被证实时停止并记录；不得在 W02 悄然改写冻结合同文件。

### 文件职责及实施内容

- Provider candidate final 在普通 assistant commit 前经过完成 Hook；PLAN candidate 生成或替换 PlanState、递增 revision、发布 PlanProposed 并进入 PLAN_REVIEW_REQUIRED pause。
- Plan candidate 不写普通 assistant message，不发送普通完成事件，不结束 Turn；用量先按真实调用计入。
- REVISE 必须验证全部关联 ID 与 revision，把非空反馈作为真实 user Message 写入同一 Turn，并要求下一版本完整替代。
- APPROVE 标记当前 Plan 已批准，切换为 DEFAULT，发布 mode change 与 resume 事实；同一 run、turn、handle 继续下一 iteration 并看到完整 Tool View。
- cancel 在 proposal、review、resume 与 candidate completion 竞态中始终优先。

### 依赖任务

Task 3。

### 参考资料定位

- 原始需求第 6.4、10、11.6～11.7、19.4～19.6、22.3、22.7 节。
- 当前 T06 typed pause/response 与 Application driver 实现。

### 完成边界

- Headless Core/Application 测试覆盖 Plan v1 → revise → Plan v2 → approve、stale revision、取消和 Tool View 切换。
- 不修改 Slash 或 TUI，不自动把 Plan 编译成 Todo。

---

## Task 5 — Todo / Execution Planning / Completion Control

### 任务目标

把 TodoWrite 接入 Agent Core control path，并以 TaskState、Runtime Prompt facts 与完成 Hook形成默认模式的持续执行和防提前结束闭环。

### 新增、修改和删除的文件

- 修改 `src/uthcode/core/agent.py`。
- 修改 `src/uthcode/application/generation.py`。
- 修改 `tests/test_agent_loop.py`、`tests/test_application_runtime.py`、`tests/test_application_runs.py`。

### 文件职责及实施内容

- TodoWrite 不进入普通 ToolRegistry、Permission 或手工 Application Tool API；参数由 W01 schema 校验，Agent Loop 以 replace-all 写 TaskState并返回原 call ID 的 ToolResult。
- 合法清空、重写、至多一个进行中项、暂停恢复保留和新 Turn 重置均由权威 RunState 表达。
- 默认模式请求持续看到结构化 TaskState、已批准 Plan 与一次性反馈；模型负责是否建立 Todo、何时推进和何时整体重写，Runtime 不使用复杂度启发式。
- DEFAULT candidate final 在权威 commit 前检查 TaskState；存在未完成项时发布 CompletionBlocked、设置一次性反馈并进入下一 iteration。
- blocked candidate 的 usage 计入，但正文不进入 messages、普通 assistant 完成事件、TurnCompleted 或 TUI final；清空或全部完成后才允许一次普通完成。

### 依赖任务

Task 4。

### 参考资料定位

- 原始需求第 7、8、11.6～11.7、13、14、19.7、19.9 节。
- W01 Planning/Hook/Prompt 合同及其 Feedback。

### 完成边界

- Todo、重规划、完成拦截、max-iteration、Hook exception 和新 Turn reset 测试通过。
- 不增加 Todo Manager、第二状态仓库、自动 Plan→Todo 编译或第二 planning loop。

---

## Task 6 — User Steering

### 任务目标

让 active Turn 在 Provider generation 与 Tool batch 安全边界接受真实用户目标更新，同时维持 ToolCall ID 闭合、TaskState 不被 Runtime 自动改写和取消优先。

### 新增、修改和删除的文件

- 修改 `src/uthcode/core/agent.py`。
- 修改 `src/uthcode/application/runs.py`。
- 修改 `tests/test_agent_loop.py`、`tests/test_application_runs.py`。

### 文件职责及实施内容

- Core execution 使用独立 pending Steering 事实，不复用普通 pause、Plan Review 或 typed response；同一时刻最多一个尚未应用的请求。
- Provider attempt 被合作式中断后丢弃未提交的 partial candidate；Steering 成为真实 role=user Message并设置一次性反馈，再进入下一 iteration。
- 当前普通 Tool 不被强杀；它完成后，当前 batch 剩余未启动调用逐一得到受控 skipped/error ToolResult，ToolBatch 正常闭合后应用 Steering。
- Steering 不自动完成、清空或重写 TaskState；模型在下一 request 中根据真实用户事实决定保持、更新或整体重写。
- PLAN generation 中可 Steering；任何 AskUser、Permission、Provider retry 或 Plan Review typed pause pending 时拒绝普通 Steering 路径。
- Cancel > Steering > candidate completion，所有终态、重复请求和竞态均清理 pending steering。

### 依赖任务

Task 5。

### 参考资料定位

- 原始需求第 9、14.4、19.8、22.3、22.7 及关键场景 C、D、H、I、J。
- T06 cooperative pause 与 Tool safe-boundary 现有实现。

### 完成边界

- Provider、Tool batch、PLAN、typed pause、重复 Steering、stale request 与 cancel race 测试通过。
- 不创建新 Turn、不伪造 system/tool feedback、不让 Interface 直接写 messages。

---

## Task 7 — Application Run Mode 与 Steering Control

### 任务目标

收口 Run-local idle mode、active mode 同步、`TurnHandle` Steering API 和 Application 异步协调，使 W03 可只通过公开用例投影行为。

### 新增、修改和删除的文件

- 修改 `src/uthcode/application/runs.py`。
- 修改 `src/uthcode/application/generation.py`、`src/uthcode/application/tools.py`。
- 修改 `tests/test_application_runs.py`、`tests/test_application_runtime.py`、`tests/test_application_tools.py`。
- 顶层公共导出统一留给 Task 10，避免与 W03 并行修改同一聚合文件。

### 文件职责及实施内容

- 新 Run 默认 DEFAULT；idle setter 幂等，active Turn 外部切模稳定拒绝，且不改变 PermissionMode。
- Turn 启动时捕获 idle mode；Plan approve 后 Application 立即同步 Core 最终 mode，Turn 结束后保留该 mode 供下一 Turn 使用。
- `TurnHandle.steer(text)` 只接受 active、非空、无 typed pause 的请求，返回是否被接受；它不创建新 Turn。
- `_TurnDriver` 继续独占 asyncio task、queue、signal、waiter 和 pending coordination；Steering 与 pause/cancel 的资源在 terminal 后全部清理。
- formal composition 只复用一个 ToolRegistry、ToolExecutor 和 RuntimeHookSet，不保留手工执行旁路。

### 依赖任务

Task 6。

### 参考资料定位

- 原始需求第 4.3、9.2、9.7～9.8、15.4～15.5、22.7～22.9 节。
- 当前 `application/runs.py`、`generation.py`、`tools.py` 与 T06/T07 Application 测试。

### 完成边界

- W02 所有定向测试通过，Feedback 给出 W03 所需公共 API 与事件事实。
- 不修改命令、TUI、CLI，不导出 Interface-owned mode/state，不执行 Git merge/push。

---

## Task 8 — Slash Command 产品入口

### 任务目标

把 `/plan`、`/do` 与 `/build` 收口为最终无参数行为模式入口，并通过现有 Registry、help 与 completion 提供唯一命令事实。

### 新增、修改和删除的文件

- 修改 `src/uthcode/application/commands/builtins.py`、`models.py`、`commands/__init__.py`。
- 按公共 Action 暴露需要修改 `src/uthcode/application/__init__.py`；冲突由 W04 最终统一。
- 修改 `tests/test_command_dispatcher.py`、`tests/test_command_registry.py`、`tests/test_command_completion.py`。

### 文件职责及实施内容

- `/plan` 产生 PLAN mode-selected Action；`/do` 产生 DEFAULT mode-selected Action；`/build` 只作为 `/do` alias，不建立第三种 canonical mode。
- 三者均无参数；旧 Prompt `/do` query 语义直接删除，`/do anything` 返回 usage error。
- 删除需求未保留的旧 `/p` alias，不增加兼容入口。
- Action 只表达 interface-neutral 用户意图；TUI 将其应用到当前 AgentRun，Headless 可直接使用 Run mode API。
- help、completion 与别名继续由同一 Registry 生成，三条最终命令均标记已实现。

### 依赖任务

Task 2；W03 分支必须已 fast-forward 到 W01 tip。W03 可与 W02 并行并使用 fake Run 验证预期公共 API。

### 参考资料定位

- 原始需求第 15、22.10、23 Task 8。
- 当前 Slash Command Registry、Dispatcher、Completion 与 `/permission` UI Action 结构。

### 完成边界

- command、help、completion、alias、无参数和旧语义删除测试通过。
- 不修改 Agent Loop、Application driver 或 PermissionMode，不自行接线真实 TUI Turn。

---

## Task 9 — TUI Plan / Todo / Steering 产品闭环

### 任务目标

在现有 prompt_toolkit 主缓冲区 TUI 中投影行为模式、Plan Review、Todo、Steering 和完成拦截，同时保持 append-only scrollback 和 typed interaction 优先。

### 新增、修改和删除的文件

- 修改 `src/uthcode/interfaces/tui/app.py`、`interaction.py`、`rendering.py`、`terminal.py`。
- 修改 `tests/test_tui.py`；不新建重复的 `test_tui_app.py` 或 `test_tui_rendering.py`。
- 修改 `docs/TUI/README.md`，只同步最终 T08 TUI 行为，不写未实现未来能力。

### 文件职责及实施内容

- idle 普通文本继续 start Turn；active Turn 且无 typed interaction 时调用当前 handle 的 Steering；typed AskUser、Permission、Provider retry 或 Plan Review 始终优先消费输入。
- separator 与 status 分别投影 Behavior Mode 和 PermissionMode；Plan approve 后立即恢复默认 separator。
- Palette 增加可区分的 plan accent/background；Plan proposal 以 `UthCode · Plan vN` 和完整 Markdown append 到 scrollback，每个 revision 保留独立 block。
- Plan Review 提供 Approve and execute、Revise plan、Cancel；revision input 提交现有 typed response，不保存 PlanState。
- TaskStateChanged 投影紧凑 checklist；Steering user message恰好显示一次，状态活动文本不制造第二个 Turn 分隔。
- CompletionBlocked 只显示短活动/状态，不显示已被 Core 丢弃的 candidate final。
- 保持非全屏、无鼠标、无 `CSI 3J`、永久输出不可回写、一个 RenderBatch 一次永久提交等现有 TUI 不变量。

### 依赖任务

Task 8；W03 与 W02 可并行，跨层真实运行只在 Task 10～11 验证。

### 参考资料定位

- 原始需求第 16、17、22.11、23 Task 9。
- `docs/TUI/README.md` 与当前 `app.py`、`interaction.py`、`rendering.py`、`terminal.py`。
- W01 event/interaction contracts 与 Feedback。

### 完成边界

- fake Run/event 驱动的 TUI、renderer、terminal、command 回归通过；UTF-8 guard 检查 TUI 文档通过。
- 不持有第二份 RunState、TaskState 或 PlanState，不绕过 Application，不改 Core/Runtime 文件。

---

## Task 10 [接入主流程] — 正式 Composition 与分支整合

### 任务目标

在最终保留分支依次合并三个 Worker，统一公共导出与共享合同，证明 T08 只存在一条正式生产调用链。

### 新增、修改和删除的文件

- 先读取三个 Feedback 与 branch diff，再依次合并 `T08-W01-core-contracts`、`T08-W02-runtime-application`、`T08-W03-slash-tui`。
- 按冲突实际修改 W01～W03 已涉及的生产文件与测试；修改应限于合同统一、正式接线和缺失 glue，不重做无冲突的完整实现。
- 修改 `src/uthcode/application/bootstrap.py`、`src/uthcode/core/__init__.py`、`src/uthcode/application/__init__.py`、必要的 package exports。
- 修改 `tests/test_architecture_boundaries.py`、`tests/test_package.py`。
- 新增 `tests/test_t08_e2e.py` 的正式组合骨架。

### 文件职责及实施内容

- 检查 W01/W02/W03 tip 均来自任务包基线，Feedback 与各自 Checklist 有真实证据，且工作树无未提交业务修改。
- 使用 merge commit 保留三个 Worker 的交付边界；冲突按 Spec、Tasks、当前源码事实与测试统一，禁止简单选择整侧覆盖。
- `create_application → create_run → set mode/start_turn` 必须使用唯一 RuntimeHookSet、Tool universe、动态 view、AgentLoop 和 Application driver。
- pre-tool Hook 位于 trusted preflight 与 Permission 之间；completion Hook 位于 usage accounting 之后、assistant authoritative commit 之前。
- TodoWrite、Plan Review 和 Steering 只通过 Core/Application control path；TUI 不删除 Tool schema、不写 RunState、不直接导入 Core internal hook。
- PermissionMode 与 BehaviorMode 正交；Headless 无 TUI 也能完成全部 typed interaction。
- 公共导出只包含当前真实用例需要的类型；删除 merge 后形成的重复 helper、临时 alias、分支特有 glue 和不可达测试夹具。

### 依赖任务

Task 1～9；W01、W02、W03 Feedback 和提交均存在。

### 参考资料定位

- 三个 Worker Feedback、各分支 diff 与原始需求第 19～22、23 Task 10。
- AGENTS.md 分层与非兼容原则、当前 Context 文档。

### 完成边界

- 合并完成、冲突全部解析、正式 composition/architecture/package 定向测试通过。
- 未开始最终 E2E 与全量清理前，不删除任何 worktree 或短期分支。

---

## Task 11 [端到端验证] — Plan + Execution Planning + Steering

### 任务目标

从正式 Application 入口验证 T08 的完整正常路径和关键失败/竞态路径，而不是直接调用私有 continuation 或用 Interface 伪造状态。

### 新增、修改和删除的文件

- 完成 `tests/test_t08_e2e.py`。
- 按 E2E 暴露的真实缺陷窄化修改生产文件和现有测试。
- 不发真实网络请求，不修改旧 Provider SDK 映射以制造测试捷径。

### 文件职责及实施内容

- 使用正式 Application、Fake Provider、真实 builtin Tool、临时 workspace、PermissionMode.AUTO 与初始 PLAN。
- 捕获第一 request 的 PLAN Tool View，执行真实 ReadFile，生成 Plan v1，REVISE 后同 Turn 生成完整 Plan v2，APPROVE 后自动 DEFAULT。
- 证明下一 request 出现 full Tool View + TodoWrite；建立多步 TaskState、部分实施后接受 active Turn Steering，并把更新作为真实 user Message。
- 在 Tool batch 中触发 Steering，证明当前 Tool 完成、stale remainder 不执行且全部 call ID 闭合；Cancel 与 Steering race 中 Cancel wins。
- 尝试 unfinished Todo final，证明 CompletionBlocked 后继续；真实写/改/验证并将任务全部完成后只出现一个 TurnCompleted。
- 新 Turn 重置 TaskState、PlanState 与一次性 feedback，同时保留 Run 的最终 BehaviorMode。
- 额外覆盖 PLAN + full_access 写入拒绝、PLAN 敏感只读仍 Ask、Plan Review pending 不接受普通 Steering、stale revision/response 拒绝。

### 依赖任务

Task 10。

### 参考资料定位

- 原始需求第 23 Task 11、测试矩阵和关键场景 A～J。
- W01～W03 Feedback 中的合同、竞态和界面测试证据。

### 完成边界

- `tests/test_t08_e2e.py` 与全部受影响定向测试通过，事件序列、request capture、文件副作用和资源清理均有断言。
- 失败时保留 worktree/分支和可复现证据，不提前声明完成。

---

## Task 12 [遗留负担清理] — 单 Runtime 收口与 Worktree 回收

### 任务目标

证明最终仓库只有一套规划/执行控制语义，完成全量回归、文档状态同步和已合并短期 worktree/分支的安全回收。

### 新增、修改和删除的文件

- 清理本任务全部生产文件和测试中的旧入口、重复状态、重复 helper、不可达分支与分支合并残留。
- 修改 `docs/Context-Index.md`：只有当前源码已实现、Checklist 全部完成且四份 Feedback 齐全时，才将 T08 标为 `implemented_unarchived`。
- 创建并完成 `feedback/W04-integration-delivery-feedback.md`；不移动或归档工作包。
- 删除已验证合并的本地短期 worktree 与 `T08-W01-*`、`T08-W02-*`、`T08-W03-*` 分支；不删除远端、T05、main 或最终 T08 分支。

### 文件职责及实施内容

- 否定性扫描确认：只有 DEFAULT/PLAN；`/plan` 无参数；`/build` 只是 `/do` alias；无旧 `/p`、旧 Prompt `/do`、第三 Build mode。
- 确认无第二 planning/runtime loop、Todo Manager、Interface-owned Plan/Task state、Plan→Todo 编译器、complexity detector、动态 Hook registry、未使用 Hook point或第二 Tool executor。
- 运行 T08 全部定向测试、architecture/package、全量 pytest、compileall、pip check、diff check 和 UTF-8 guard。
- 对 W01～W03 每个 tip 执行祖先验证；只在最终分支包含 tip、工作树已提交且测试完成后，以精确绝对路径移除 worktree，再用安全删除删除本地短期分支。
- 最终核对 `git worktree list` 只剩主工作树，分支列表保留 main、T05 与最终 T08；远端状态未改变。

### 依赖任务

Task 11。

### 参考资料定位

- 原始需求第 23 Task 12、第 26～30 节。
- `docs/work/README.md` 的 Feedback、冻结、索引与归档规则。
- AGENTS.md 非兼容原则与本文件顶部 Git/worktree 边界。

### 完成边界

- Checklist 全部有真实证据，四份 Feedback 齐全，T08 状态正确，最终分支提交完整且工作树干净。
- 物理 worktree 和短期本地分支已安全回收；不 push、不删远端、不合并 main、不自行归档。
