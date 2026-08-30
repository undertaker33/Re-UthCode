# T10：Desktop GUI 与 TUI 全量能力迁移 Checklist

## T01：用户配置 GUI 闭环

- [x] 执行 `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_configuration.py tests/test_config_contract.py tests/test_config_loader_integration.py -q`，全部通过。
- [x] 无配置、空模板、语义无效但 TOML 可解析时能返回可编辑安全视图；TOML 语法不可解析时返回稳定错误而不破坏原文件。
- [x] 安全读取只返回 Provider/Model 当前字段和 `api_key_configured`，不返回 literal/env key、`SecretValue`、未知字段或 project credentials。
- [x] 新增/修改/删除 Provider/Model、default model 和 default permission 的有效/无效路径均有测试；`full_access` 不可写为默认值。
- [x] 修改已配置 Provider 但未提供新 key 时保留原 literal/env 表达；提供新 key 时一次性替换且 response 不回显；删除被 Model 引用的 Provider 被拒绝。
- [x] 原子写入成功后 `load_effective_config` 和 `create_application` 可成功；写入失败不留部分文件，现有 `/model` 与 `/permission` 写回测试不退化。
- [x] 注入假 API Key 后，配置 DTO、`repr`、error、log 和 test snapshot 均不包含明文。

## T02：Python Desktop Bridge

- [x] 执行 `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_desktop_protocol.py tests/test_desktop_bridge.py tests/test_architecture_boundaries.py -q`，全部通过。
- [x] valid request 每次只调用对应 Application use case 一次；invalid JSON、unknown method/field、duplicate/unknown id 产生 protocol error 且不进入 Agent Runtime。
- [x] Bridge 只持有一个 Application、一个 Run 和最多一个 active Turn；second start 被拒绝，steer/pause/resume/cancel 都作用于同一 handle，terminal 释放 active slot。
- [x] pending typed interaction 截获普通输入和 Slash；stale/wrong-kind/duplicate response 被拒绝且不改变 pending；ResumeTurn、AskUser、Permission、Plan、Retry 具体 response 映射正确。
- [x] Plan/Retry/Pause Cancel 调用 `TurnHandle.cancel()`；Plan Revise 空 feedback 被拒绝；Permission 使用每次 request.choices，没有 SESSION choice 时不伪造该操作。
- [x] command completion 同时覆盖 command 与 argument candidates；active/pending 门禁与 TUI 当前行为一致，不允许 `/model`/`/new`/`/resume`/`/compact`/mode 命令绕过 active Turn。
- [x] session new/resume 与 project switch 都创建 fresh Run，旧 history/session grant/mode/active handle 不渗入；corrupt/busy/unknown/projection failure 不破坏原 active Session。
- [x] AgentEvent 保留原名、identity 与顺序；Runtime lifecycle/protocol error 与 TurnFailed/Provider failure 分域，子进程异常不伪装为 FailureReason。
- [x] 以子进程运行 `python -m uthcode.interfaces.desktop` 完成 ready/status/shutdown，stdout 每一行均为合法协议 JSON，stderr 不污染 parser，shutdown 调用 Application close。
- [x] 注入假 secret/native exception/raw ToolResult 后，response/event/error/stdout/stderr 的公开投影不包含该内容。

## T03：Electron Shell 与 Python Process

- [x] 在 `desktop` 执行 `npm ci`、`npm run typecheck`、`npm test`，全部通过。
- [x] 执行 `npm ls electron @electron-forge/cli @electron-forge/plugin-webpack @electron-forge/maker-squirrel`，记录实际解析版本，Electron 为冻结 44.x stable 线、Forge 为 7.11.2 stable 线。
- [x] BrowserWindow 断言 `nodeIntegration=false`、`contextIsolation=true`、`sandbox=true`；Renderer 中 `require`/`process`/`fs`/`child_process` 不可用，Preload 不暴露 raw `ipcRenderer` 或 event 对象。
- [x] production CSP、navigation/new-window deny/allowlist、no-webview、IPC sender/frame/origin 校验和本地内容限制有自动或打包后证据。
- [x] Python child 使用 `spawn` + `shell:false` + 三路 pipe + `windowsHide:true`；dev 只用当前项目 Python，production 只从 `process.resourcesPath` 解析 Runtime，无 PATH/system Python fallback。
- [x] request timeout、Bridge exit、malformed response 会拒绝对应 pending request 并显示 Runtime 边界错误，不伪装为 Agent/Provider failure。
- [x] folder picker 只返回选定绝对路径；Explorer 动作只处理已登记项目路径；Renderer 不能发起任意 shell/fs 操作。
- [x] Desktop preference 只持久化 theme/window/nav/panel/recent/alias/pin/selection 类 UI 元数据，无 API Key、Session 内容或 Agent 权威事实。
- [x] graceful shutdown 与有界 terminate/reap 测试通过，记录 child PID 并断言 Electron 退出后进程不存在。

## T04：Desktop 主界面、Project 与 Session

- [x] 执行 Renderer 定向测试，New chat/Open project、pinned/projects/recent、Settings 和 Runtime Panel floating/docked/hidden 均通过。
- [ ] 打开项目调用 native folder picker；编辑显示别名不改变 filesystem/workdir/project key；移除项目不删磁盘或 Session。
- [ ] 项目激活时 catalog 从 Application 刷新；非当前项目 last-known catalog 只用于导航，resume 内容不来自该缓存或 Renderer 文件扫描。
- [x] 点击三个不同 Session 时各自的 safe replay 原子替换 Timeline，标签使用 preview/short ID，后续输入进入被选 Session。
- [x] 新建 Session 后 Timeline 立即为空、绑定 fresh Run，不显示上一 Session 消息、mode 或 grant。
- [ ] active Turn 时切 Session/Project 严格经过 cancel -> terminal -> close/recreate -> fresh Run -> resume，不同时启动多项目 Runtime。
- [x] 生产 UI 不存在恢复会话页、account/logout/usage、hover preview cards、第二全局左栏、fake projectStore 或浏览器 prompt/confirm。

## T05：Conversation Timeline、Streaming 与 Composer

- [x] Renderer 测试覆盖 replay `user/steering/reasoning/assistant/tool` 按 sequence 排序，与 live stream 连续且不伪造 replay 不包含的 Plan/Todo/pause/failure 持久事实。
- [x] assistant delta 仅更新 preview，completed 以权威正文替换且只显示一次，failed/cancelled 丢弃未完成 preview。
- [x] reasoning tail 在 assistant/tool/terminal 前收口，tool started -> finished/failed 同一 activity 只固化一次，事件不按类型重排，ToolResult 正文不显示。
- [x] Markdown headings/paragraphs/lists/quote/table/link/inline/fenced code 可读，raw HTML/script 不执行，link 走明确安全路径。
- [ ] idle composer 调用 start_turn，active ordinary input 调用 steer 且不创建第二 Turn，pause 与 cancel 状态/结果明确区分。
- [x] TaskState 为 replace-all 投影，CompletionBlocked 显示原因且不显示被丢弃 final，Runtime Panel 不暴露 prompt/transcript/ToolResult/secret/native exception。
- [ ] Slash completion 的 command/alias/arguments 均来自 Python；Model/Permission/Behavior/New/Compact GUI 操作与 Slash 复用同一 Application authority。
- [ ] `/clear` 只清当前 visible Timeline，不换 Run/删 durable Session；`/quit` 走正常 Runtime shutdown。

## T06：Typed Interaction Surface

- [ ] AskUser 组件测试覆盖 1～4 题、text/single-select/multi-select、2～6 选项、Other、前后移动、返回修改和提交前 review。
- [ ] AskUser request/waiting/answered 都在 Timeline 有可观察状态，answer 后同一 Turn 继续 Markdown/Tool/Reasoning 并可再次产生 interaction。
- [x] Permission 测试动态渲染 request.choices，覆盖包含/不包含 Session 授权的 request，Session grant 不写 Desktop preference。
- [ ] Plan 每个 revision 显示完整内容，Approve/Revise 走 typed resume，Revise 需非空 feedback，Cancel 走 handle.cancel。
- [x] Provider Retry 只展示 Runtime 投影并提交 `RetryProviderResponse`，Cancel 走 handle.cancel，Renderer 无 HTTP/backoff/reconnect state machine。
- [x] 用户 Pause Continue 提交 `ResumeTurnResponse`，Cancel 走 handle.cancel；pending 时 Composer 和 Slash 不旁路为 Steering/command/new Turn。

## T07：Settings 与 Theme

- [ ] 无有效配置时 Desktop 可直接进入 Settings，完成 Provider/Model/default 配置并启动 Application。
- [x] Settings 只显示有真实内容的模型与提供商、权限与安全、界面、关于；无空分类、虚构字段或通用 Settings schema。
- [ ] Provider/Model 增删改、引用校验、default model/permission 通过 GUI 与 T01 use case 完成，不在 TypeScript 复制校验 authority。
- [ ] API Key 仅显示 configured/masked，replace 成功后输入清空，Renderer persisted state/Main log/Bridge event/error 不含 key。
- [x] idle runtime-affecting save 执行 validate -> close -> reload -> recreate -> resume durable Session；active Turn 时保持原 Runtime 并明确阻止应用。
- [ ] system/dark/light 选择与持久化通过，两主题下 message/Markdown/reasoning/tool/interaction/plan/todo/error/code/focus/runtime/settings 可读，颜色不是唯一线索。
- [x] Settings 是连续行/分隔线布局，不存在 SettingCard/CardGrid/dashboard tile 或设计说明文案。

## T08：Windows Runtime Bundle 与 Installer

- [x] 执行 `conda run --no-capture-output -n re-uthcode python -m PyInstaller --clean --noconfirm desktop/packaging/uthcode-runtime.spec`，生成 onedir `uthcode-desktop-runtime.exe` 与 `_internal`。
- [x] Runtime 保留 console subsystem stdio，未使用 `--noconsole/--windowed`；通过 Electron `windowsHide:true` 隐藏窗口且三路 pipe 可用。
- [x] 直接 spawn packaged Runtime 完成 ready/status/shutdown，stdout 每行合法 JSON、退出码 0，`prompt_assets/coding_agent.md` 可由 `importlib.resources` 读取。
- [x] 构建 spec 只收集真实依赖/资源，不存在 `--collect-all everything`、构建输入复制、路径敏感 Hash 或构建专用完整性链。
- [x] 在 `desktop` 执行 `npm run package -- --platform=win32 --arch=x64` 和 `npm run make -- --platform=win32 --arch=x64`，成功生成 packaged app 与 `UthCode Setup.exe`。（本轮 package 与 make 均 exit 0，已生成 packaged app 与 `desktop/out/make/squirrel.windows/x64/UthCode Setup.exe`；旧轮 `20.205.243.166:443` ETIMEDOUT 仅保留在 Feedback 历史记录。）
- [x] packaged app `resources` 中完整存在 Runtime exe + `_internal`，production 启动无 system Python fallback，关闭后无 orphan child。
- [x] Squirrel install/update/uninstall 特殊启动参数在 Main 早期收口，没有因 lifecycle 启动多个 Python child；Electron Fuses 实际打包状态已检查并记录。
- [ ] 在无系统 Python 的 Windows 11 x64 环境执行安装 -> 启动 -> 首配 -> 对话 -> 关闭 -> 卸载，精确环境/结果记入 W05 Feedback。
- [x] 未签名 Installer 明确标记为 development/release-candidate 验收，不宣称已满足公开发行签名/SmartScreen 要求。

## T09：[接入主流程] Desktop 全链路接入

- [ ] 从真实 Desktop 启动完成 Renderer -> Preload -> Main -> Bridge -> Application -> Core -> AgentEvent -> Renderer，request/session/run/turn/pause identity 和事件顺序一致。
- [ ] 配置未初始化、正常对话、Session replay、typed interaction、命令与关闭均不依赖 fake state/prototype stub。
- [x] `rg -n "alert\\(|prompt\\(|confirm\\(|fake|mock session|demo" desktop/src`的生产命中为 0 或逐条证明不是原型/假产品行为。
- [x] TypeScript 不定义第二 AgentEvent/Session/Permission/Plan/Todo/Failure taxonomy 或完整 Slash/Model authority，Bridge 不直接访问 Core/Provider/Tool/Session Store。
- [x] 执行 `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_tui.py tests/test_cli.py tests/test_application_runs.py tests/test_agent_events.py tests/test_agent_interaction.py tests/test_architecture_boundaries.py -q`，全部通过。
- [x] 从正式入口证明 `uthcode` 仍启动 TUI，`uthcode exec` 仍运行 Headless，Desktop 没有改写两者产品语义。

## T10：[端到端验证] Windows Feature Parity

- [ ] 在 Windows 11 x64 安装产物上完成：安装 -> 首配 -> 打开 Re-UthCode -> 新 Session -> 对话 -> Tool -> AskUser -> Permission -> Plan -> Todo -> Steering -> Pause/Resume -> Model/Permission/Mode -> Compact/status -> 退出/重启 -> 旧 Session -> 继续对话。
- [ ] AskUser E2E 包含多题、单选、多选、Other、回退修改/review；Permission 包含不提供 Session choice 的 request；Plan/Retry/Pause Cancel 均产生 cancel terminal 而非 resume。
- [x] active Turn 期间 `/model`/`/new`/`/resume`/`/compact`/`/plan`/`/do`/`/build` 不绕过门禁；pending Interaction 期间输入 Slash 不 dispatch，而是继续当前 interaction。
- [x] Session/Project 切换后旧 Run history/grant/mode 不带入 fresh Run，new Session 空视图、resume safe replay 与 live continuity 通过。
- [x] invalid config、bad key/provider failure、invalid IPC、Python Runtime crash、Session corrupt/busy、active Turn close/project switch 都有可理解结果，Runtime crash/protocol error 不伪装为 Provider/TurnFailed。
- [ ] system/dark/light、Runtime Panel floating/docked/hidden、窄窗口 Chat 可用性与焦点/键盘路径通过真实人工验收。
- [x] 安装、Project、Session、Chat、Interaction、Settings、Layout、Exit 的任务书第 33 节每一项均在 W06 Feedback 记录通过或精确未验证原因。

## T11：[遗留负担清理] 迁移收口

- [x] `rg -n "DesktopAgentEvent|DesktopSession|DesktopPermission|DesktopPlan|DesktopTask|DesktopFailure|EventBus|RpcManager|RuntimeManager|TransportFactory|PluginHost|DeviceProtocol" src desktop tests`返回 0 条生产重复 authority/未来占位，其他命中在 Feedback 逐条说明。
- [x] `rg -n "Card(Grid)?|DashboardCard|SettingCard|ToolCard|工程参考|设计说明|GUI 化|演示|三栏|这里用于|该区域" desktop/src/renderer`返回 0 条生产卡片布局/设计说明文案，用户数据命中例外在 Feedback 说明。
- [x] `rg -n "Subagent|Multi-Agent|Worktree|Git Diff|MCP|Skill|Auto Update|Tray|Windows Service|FastAPI|WebSocket|Named Pipe|gRPC" src/uthcode desktop/src`不存在 T10 未来能力入口/协议占位，必要否定语义命中在 Feedback 说明。
- [x] 执行 `conda run --no-capture-output -n re-uthcode python -m pytest -q`，将精确 passed/failed/skipped 写入 W06 Feedback。
- [x] 执行 `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests`、`conda run --no-capture-output -n re-uthcode python -m pip check`、`git diff --check`，全部退出码 0。
- [ ] 在 `desktop` 重新执行 `npm ci`、typecheck、unit/integration/E2E、build、package、make，并重跑 PyInstaller smoke 与 Installer 关键 E2E，精确结果写入 W06 Feedback。
- [x] `README.md`、用户手册、A04/命中的 A02/A03/TUI 当前事实、`docs/Context-Index.md` 与最终 `src/ + tests/` 一致；不把 Desktop 规划写成未实现事实。
- [x] UTF-8 检查覆盖本包、Context Index、Outstanding Debt 和实际修改的 Markdown，均可解码，无 replacement character/常见乱码，fenced code block 成对。
- [ ] `docs/OutstandingDebtList.md` 已核对且因“能力欠账：无”保持不变；W01～W06 Feedback 齐全、全部 Checklist 有证据后，Context Index 将 T10 标为 `implemented_unarchived`。
- [x] 本包未自动归档，未执行 commit、push、merge、rebase、tag 或 release，并保留用户开工前的手动归档改动。
