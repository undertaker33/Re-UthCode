# T10：Desktop GUI 与 TUI 全量能力迁移 Tasks

## Worker 分组、顺序与依赖

| Worker | 执行任务 | 前置 | 写集与串行边界 |
| --- | --- | --- | --- |
| W01 | T01 | 无 | 独占 Application 配置 use case、config loader/writer 与对应 Python tests |
| W02 | T02 | W01 | 独占 `interfaces/desktop` Python Bridge、协议与 Bridge tests |
| W03 | T03 | W02 | 独占 Electron Main/Preload、Python child lifecycle、Desktop preferences 与对应 tests |
| W04 | T04 -> T05 -> T06 -> T07 | W03 | 独占 Renderer、共享 reducer/CSS/组件 tests；四个 Task 严格串行，不允许多 Worker 同时改 `App.tsx`/`state.ts`/`app.css` |
| W05 | T08 | W04 | 独占 PyInstaller spec/build script、Forge packaging/maker、构建依赖与打包验收 |
| W06 | T09 -> T10 -> T11 | W05 | 独占全链路接入、真实 Windows E2E、全量回归、文档、Checklist 与最终清理 |

所有 Worker 必须由用户指定 Prompt 依次派发，不得自行开始实施。每个 Worker 开工前完整读取原始需求、Spec、Tasks、Checklist、自己的 Prompt 和所有前序 Feedback。首次派发后，原始需求、Spec、Tasks、Prompt 和 Checklist 文字/结构冻结；Checklist 只允许将有精确证据的 `[ ]` 改为 `[x]`。

原型参考件 `uthcode-desktop-ui-prototype-v5.html` 在拆分时未于仓库或 `D:\project` 找到。如后续由用户提供，只能作为视觉/交互参考，不得覆盖当前 `src/ + tests/`、冻结决策或 Spec；其缺失不授权 Worker 补造产品行为。

## T01：用户配置 GUI 闭环

### 任务目标

提供可在 `create_application` 失败前调用的窄配置读写闭环，让 Desktop 能从无有效配置收敛到可启动 Application 的当前 user config。

### 新增文件

- 无预设生产文件；现有文件无法清晰承载时，只允许新增职责单一的配置测试文件。

### 修改文件

- `src/uthcode/application/configuration.py`、`bootstrap.py`、`__init__.py`
- `src/uthcode/integrations/config/writer.py`，只在真实需要时修改 `loader.py`、`data.py`
- `tests/test_configuration.py`、`tests/test_config_contract.py`、`tests/test_config_loader_integration.py`
- 写入器的现有定向测试；若当前没有匹配文件，新增 `tests/test_config_writer.py`

### 删除文件

- 无预设整文件删除；删除被 current-schema writer 替代的重复默认模型写回帮助链仅限真实 caller 已统一时。

### 文件职责及实施内容

- Application DTO 只表达当前 root/provider/model 字段、引用关系和 `api_key_configured`；不暴露 `SecretValue` 或明文。
- 写请求支持 Provider/Model profile 增删改、default model 与 default permission，复用当前 provider kind、base URL、key、positive limit、reasoning effort 与引用校验。
- 集成层使用现有 `tomlkit` 与 same-filesystem temp + `os.replace`，尽量保留注释/顺序，拒绝未知字段。
- 保持项目配置禁止 Provider/凭据/等价重定向字段，不将项目配置变成 GUI credential store。
- 安全读/写 use case 不依赖已构造 Provider/Application；保持 CLI/TUI 现有默认模型写回语义。

### 依赖任务

- 无。

### 参考资料定位

- 原始需求 D-T10-01、15 节、31/T01、32.1、33 Settings、38。
- `docs/context/A04-Orchestration/Orchestration-Context.md`、`docs/user-manual/configuration.md`。
- 当前 `application/configuration.py`、`bootstrap.py`、`integrations/config/*` 与对应 tests。

### 完成边界

无有效用户配置时能读取安全视图、写入有效配置并成功 `load_effective_config`/`create_application`；任何读响应、错误或测试 snapshot 都不包含 API Key。

## T02：Python Desktop Bridge

### 任务目标

新增仅通过 `uthcode.application` 工作的 Desktop Interface 子进程，实现窄 JSONL 请求/响应/事件协议和单 Runtime 生命周期。

### 新增文件

- `src/uthcode/interfaces/desktop/__init__.py`
- `src/uthcode/interfaces/desktop/__main__.py`
- `src/uthcode/interfaces/desktop/protocol.py`
- `src/uthcode/interfaces/desktop/bridge.py`
- `tests/test_desktop_protocol.py`
- `tests/test_desktop_bridge.py`

### 修改文件

- `tests/test_architecture_boundaries.py`
- `src/uthcode/application/sessions.py`、`generation.py`、`__init__.py`（仅 GUI 确实缺少只读 catalog/safe projection 时做最小扩展）
- T01 配置 use case 只作为调用方，不重写其语义

### 删除文件

- 无。

### 文件职责及实施内容

- 定义 request/response/error/agent_event/runtime_state envelope、correlation 和严格字段校验；未知 method/字段/非法 JSON 返回 protocol error。
- 只为真实 GUI caller 实现 runtime、project、session、turn、command、status、settings 方法；可合并重复方法，但不得变成 arbitrary reflection/eval。
- 保持 one Application / one AgentRun / one active Turn，project switch 先收口 active Turn，再 close/recreate Application 和 Run。
- Session catalog/new/resume/replay、start/steer/pause/resume/cancel、CompletionEngine/CommandDispatcher 与 status 复用 Application 权威。
- Agent event payload 直接使用公开安全序列化；typed resume 必须匹配当前 pending request kind/identity，只构造当前真实具体 response 类型；用户 Pause 恢复使用 `ResumeTurnResponse`，Plan/Retry/Pause 取消均调用 `TurnHandle.cancel()` 而不伪造 response。
- Bridge 在 command dispatch 前实施与 TUI 等价的 pending/active Turn 门禁，区分可在 active 期间使用的现有命令与禁止产生副作用的 model/new/resume/compact/mode 路径；门禁不在 TypeScript 复制。
- Session new/resume 与 project switch 必须绑定 fresh AgentRun，旧 Run history、Session grant、mode 与 active handle 不得跨边界渗入。
- stdout 每行只能是协议 JSON，stderr 承载 diagnostics；shutdown 有界取消 active Turn、消费 terminal result 并关闭 Application。

### 依赖任务

- T01。

### 参考资料定位

- 原始需求 19～23 节、31/T02、32.1、38。
- A03/A04/TUI 当前上下文，`application/runs.py`、`sessions.py`、`commands/`、`core/agent_events.py`、`core/interaction.py`。
- Electron security/process 仅是边界对照，Bridge 不引入 Electron 或 Provider SDK 类型。

### 完成边界

从 `python -m uthcode.interfaces.desktop` 可用假 Application/Provider 完成 ready -> project/config initialize -> session -> turn/event/typed resume -> shutdown；顺序、独占、过期响应、错误和秘密安全均有离线测试。

## T03：Electron Shell 与 Python Process

### 任务目标

建立安全 Electron Shell，让 Main 稳定拥有 Python child lifecycle，Renderer 只拿到窄、typed Desktop API。

### 新增文件

- `desktop/package.json`、`desktop/package-lock.json`
- `desktop/forge.config.ts`、`desktop/tsconfig.json`
- `desktop/webpack.main.config.ts`、`desktop/webpack.renderer.config.ts`、仅真实需要时的 `desktop/webpack.rules.ts`
- `desktop/src/main.ts`、`python-runtime.ts`、`preload.ts`、`desktop-api.ts`、`desktop-preferences.ts`
- `desktop/src/renderer/index.html`、`desktop/src/renderer/main.tsx`（只建立空壳入口，不预建 fake product state）
- `desktop/tests/preload.test.ts`、`desktop/tests/runtime-process.test.ts`

### 修改文件

- 无 Python 生产文件预设修改；只在 Bridge 真实 process contract 暴露错误时串行回到 W02 Feedback 说明，不得直接改冻结工作包。

### 删除文件

- 无。

### 文件职责及实施内容

- 使用任务书冻结的 Electron/Forge 稳定版线、Forge Webpack Plugin、npm lockfile 和普通 React/CSS。
- BrowserWindow 设置 nodeIntegration/contextIsolation/sandbox，限制 CSP/navigation/webview，校验 IPC sender，Preload 逐能力暴露方法而非 raw IPC。
- Main 通过 `child_process.spawn` + `shell:false` + pipe stdio 启动 Bridge，独立收集 stderr，负责 correlation、timeout、exit rejection 和事件订阅。
- 开发态使用当前项目 Python；生产路径从 `process.resourcesPath` 解析捆绑 Runtime，不调系统 Python。
- 文件夹选择、明确项目 Explorer 动作和 Desktop-local preference 使用窄 Main API；preference 不存 key 或 Agent 事实。
- Window close 先走 graceful shutdown，有界等待后才 terminate/reap child；测试覆盖无 orphan process。

### 依赖任务

- T02。

### 参考资料定位

- 原始需求 19、20、23、24、30、31/T03、32.2。
- Electron 官方 Process Model、Security Checklist、Context Isolation、Sandbox、contextBridge、IPC；Forge 官方 Webpack Plugin。

### 完成边界

本地 Electron 壳可通过窄 API 启动/请求/订阅/关闭假或真 Bridge，Renderer 无 Node 能力，child 异常可观察且关闭无残留。

## T04：Desktop 主界面、Project 与 Session

### 任务目标

建立连接真实 Desktop API 的主界面与 Project/Session 导航，固化“点击 Session 即恢复”和“新 Session 为空视图”。

### 新增文件

- `desktop/src/renderer/App.tsx`、`Sidebar.tsx`、`RuntimePanel.tsx`、`state.ts`、`app.css`
- `desktop/tests/renderer.test.tsx`（或一个现有 Renderer test file 承载，不按组件机械拆分）

### 修改文件

- T03 的 `desktop-api.ts`、`main.ts`、`preload.ts`、`desktop-preferences.ts`（仅 Project/Session 真实 caller 需要的窄方法）

### 删除文件

- 删除实施中产生的 static project/session fake store 或原型 stub；不删除 Python TUI。

### 文件职责及实施内容

- 左栏只包含 New chat/Open project、pinned/projects/recent 和 Settings，项目操作为列表内联或轻量菜单。
- 文件夹选择走 Main；显示别名、pin、recent、session pin 只写 Desktop preference，移除项目不删磁盘或 Session。
- 点击 Session 时先收口 active Turn，按需切换 Application，再走 resume/safe replay 并原子替换 Timeline；标签使用 preview/ID fallback。
- 新建 Session 后 Timeline 为空；非当前项目 catalog 只可是 last-known navigation cache，项目激活后立即刷新。
- 删除 account/logout/usage、hover preview card、fake interaction 入口、第二全局左栏与浏览器 prompt/confirm。

### 依赖任务

- T03。

### 参考资料定位

- 原始需求 8、9、16、18、25、26、31/T04、33 Project/Session/Layout。
- `SessionCatalogEntry`、`SessionReplayRecord`、Application session use cases 与 W02/W03 Feedback。

### 完成边界

在至少三个真实 Session 间切换时 Timeline 正确替换，继续输入写入被选 Session；新 Session 不残留旧视图。

## T05：Conversation Timeline、Streaming 与 Composer

### 任务目标

完成普通对话、运行控制、Slash 与 Runtime 信息的 GUI parity。

### 新增文件

- `desktop/src/renderer/ChatTimeline.tsx`、`Composer.tsx`

### 修改文件

- `desktop/src/renderer/App.tsx`、`RuntimePanel.tsx`、`state.ts`、`app.css`
- `desktop/tests/renderer.test.tsx`
- T03 Desktop API 文件（仅已有 Bridge method 的类型与调用线）

### 删除文件

- 删除 fake timeline/session messages 与 TypeScript hard-coded 完整 Slash/Model/Permission 权威表。

### 文件职责及实施内容

- reducer 只合并 streaming block、更新同一 Tool activity 至终态、append 其余时序事件和用 authoritative final 收口；assistant delta 只是 preview，completed 以权威正文替换且不重复，failed/cancelled 丢弃未完成 preview，reasoning tail 在 assistant/tool/terminal 边界先收口，running tool 到 terminal tool 只固化一次。
- safe Markdown 覆盖 headings/list/quote/table/link/inline/fenced code，不执行 raw HTML/script，首轮不引入大型高亮框架。
- idle 输入 start Turn，active ordinary 输入 steer，Pause 与 Cancel 明确分离，Turn status/failure/retry 来自 Runtime 投影。
- Todo 按 replace-all `TaskStateChanged` 替换，CompletionBlocked 显示原因；Runtime Panel 只显示安全 status/context facts。
- Slash completion/execute 与 GUI-native Model/Permission/Behavior/New/Compact 操作复用 Python Registry/use case，`/clear` 只清 visible Timeline，`/quit` 正常 shutdown。

### 依赖任务

- T04。

### 参考资料定位

- 原始需求 6、10、13、14、18、26、31/T05、32.3、33 Chat。
- `docs/context/TUI/README.md`、AgentEvent/replay/status/command 当前源码与 tests。

### 完成边界

使用真实 Bridge 与 fake Provider 可观察 replay + live continuity、Markdown streaming、reasoning、Tool、failure/retry、Steering/Pause/Cancel、Todo/CompletionBlocked、Slash 与运行选择器。

## T06：Typed Interaction Surface

### 任务目标

迁移 AskUser、Permission、Plan Review 和 Provider Retry 的完整 typed pause/resume 页面状态。

### 新增文件

- `desktop/src/renderer/InteractionSurface.tsx`

### 修改文件

- `ChatTimeline.tsx`、`Composer.tsx`、`state.ts`、`App.tsx`、`app.css`
- `desktop/tests/renderer.test.tsx`

### 删除文件

- 删除 fake AskUser/Permission/Plan/Retry button 或 Renderer 自有 retry/backoff state machine。

### 文件职责及实施内容

- typed request 先在 Timeline 记录 request/waiting，再在 Composer 上方显示连续 Surface；完成后 Timeline 保留完成态。
- AskUser 覆盖 1～4 题、text/single-select/multi-select、2～6 选项、allow-other、前后移动、返回修改与提交前 review；Permission 动态渲染每个 `PermissionApprovalRequest.choices`，不假设每次都存在 Session grant；Plan 只提供 Approve/Revise/Cancel，Revise feedback 非空。
- AskUser/Permission/Plan approve-or-revise/Retry 通过 Bridge 调用同一 `TurnHandle.resume`；Plan Cancel、Retry Cancel 和用户 Pause Cancel 调用 `TurnHandle.cancel()`，用户 Pause Continue 提交 `ResumeTurnResponse`。恢复后允许再次出现新 interaction。
- pending typed interaction 时普通 Composer 不得发送 Steering 或开新 Turn；Session grant 仍只属于 AgentRun。

### 依赖任务

- T05。

### 参考资料定位

- 原始需求 11、12、31/T06、32.3、33 Interaction。
- `core/interaction.py`、`application/runs.py`、TUI interaction 与 `tests/test_agent_interaction.py`/`tests/test_tui.py`。

### 完成边界

四类 interaction 都能离线证明 request -> waiting -> typed response -> same Turn continue -> 可再次暂停，过期/类型错误 response 被拒绝。

## T07：Settings 与 Theme

### 任务目标

将 T01 配置闭环与 Desktop-local theme 落到真实 Settings，不增加空分类或卡片式设置平台。

### 新增文件

- `desktop/src/renderer/SettingsView.tsx`

### 修改文件

- `App.tsx`、`Sidebar.tsx`、`Composer.tsx`、`RuntimePanel.tsx`、`state.ts`、`app.css`
- `desktop/src/desktop-preferences.ts`、Desktop API/Preload/Main 的已有窄调用
- `desktop/tests/renderer.test.tsx`、`preload.test.ts`

### 删除文件

- 删除 fake/empty settings category、API Key persisted form state、SettingCard/CardGrid 类通用布局和设计说明文案。

### 文件职责及实施内容

- 以分类导航 + 连续设置行 + 细分隔线展示真实模型/提供商、默认权限、界面与有实内容的关于。
- API Key 只显示 configured/masked 状态，replace 输入成功后立即清空，不写 Renderer persisted state。
- runtime-affecting save 在 idle 时 validate -> close -> reload -> recreate -> resume durable Session；active Turn 时给出真实阻止并要求先收口 Turn。
- Theme 默认 system，支持 dark/light 覆盖并持久化；使用少量语义 CSS token，颜色不是唯一状态线索。
- 在两主题检查 message、Markdown、reasoning、Tool、interaction、Plan/Todo、warning/error、code、focus 和 Runtime/Settings。

### 依赖任务

- T06。

### 参考资料定位

- 原始需求 D-T10-01/04、15～18、31/T07、32.3/32.4、33 Settings/Layout。
- W01 Feedback 与 T01 配置公共出口。

### 完成边界

可从未配置启动错误页进入 Settings 并创建有效配置；idle save 安全重建 Runtime，active Turn save 不绕过独占边界，system/dark/light 通过组件与人工验收。

## T08：Windows Runtime Bundle 与 Installer

### 任务目标

构建不依赖用户系统 Python 的 Windows 11 x64 Desktop 安装包。

### 新增文件

- `desktop/packaging/uthcode-runtime.spec`
- `desktop/scripts/build-python-runtime.mjs`
- 必要的打包 smoke/integration test，优先收敛到现有 `desktop/tests/runtime-process.test.ts`

### 修改文件

- `desktop/forge.config.ts`、`desktop/package.json`、`desktop/package-lock.json`
- `desktop/src/python-runtime.ts`
- `pyproject.toml`（只增加真实 Python build/dev 依赖）

### 删除文件

- 无生产文件预设删除；构建结束后删除或忽略任务生成的 `.runtime`、PyInstaller work/dist、Forge out 等可再生成产物。

### 文件职责及实施内容

- PyInstaller 使用 onedir 且保留 console subsystem stdio，以支持 Bridge stdin/stdout JSONL；Electron 用 `windowsHide` 隐藏子进程窗口，不用 `--noconsole/--windowed` 破坏 pipe stdio。
- spec 明确收集当前 `src/uthcode/prompt_assets/coding_agent.md`，smoke 证明 `importlib.resources` 路径可用；不使用 `--collect-all everything`。
- 构建 `uthcode-desktop-runtime.exe`，通过 smoke 验证 ready/request/shutdown；只收集 UthCode 真实 package data/prompt assets。
- Forge 以官方 `extraResource` 或等价机制带入整个 onedir，production path 从 resources 解析。
- Squirrel.Windows maker 生成 `Setup.exe`，Main 在启动早期处理 install/update/uninstall 特殊参数，避免重复启动 child；本轮不做自动更新、服务、tray 或签名平台。
- 打包后检查 production CSP、navigation/new-window 限制、IPC sender/frame/origin 校验、preload 不透传 event 对象与 Electron Fuses 的实际安全状态。
- 在干净 Windows 11 x64 环境验证无系统 Python 启动、配置、对话、启停和卸载。

### 依赖任务

- T07。

### 参考资料定位

- 原始需求 23.2、28、29、31/T08、33 Installation/Exit。
- PyInstaller stable onedir/spec/runtime-information 官方文档，Forge packager `extraResource` 与 Squirrel.Windows maker 官方文档。

### 完成边界

`npm` 构建链能先构建并 smoke Python Runtime，再 package/make Installer；无系统 Python 的 Windows 11 x64 机器可安装、启动、正常关闭与卸载。

## T09：[接入主流程] Desktop 全链路接入

### 任务目标

将 T01～T08 全部接入真实 Desktop 唯一主链，删除过渡 stub 和重复 authority。

### 新增文件

- 无预设生产文件；仅现有 E2E 结构无法承载时新增一个 Desktop integration/E2E test file。

### 修改文件

- T01～T08 已有 Python/Desktop 主链文件与 tests，仅为解决真实接入缺口做最小修改
- `tests/test_cli.py`、`tests/test_tui.py`、`tests/test_architecture_boundaries.py`

### 删除文件

- 删除 prototype stub、fake runtime/session/interaction/settings、重复 TS command/event/domain 与 dead IPC。

### 文件职责及实施内容

- 验证 `User -> Renderer -> Preload -> Main -> Bridge -> Application -> Core -> AgentEvent -> Renderer` 的同一 request/turn/session identity 与事件顺序。
- 从真实 Desktop 启动及配置错误页进入主界面，全部功能不依赖 HTML prototype 或 fake store。
- 删除 `alert()`/`prompt()`/`confirm()`、fake button/category/message、Desktop truth 与未来占位方法。
- 确认 `uthcode` 仍启动 TUI，`uthcode exec` 仍为 headless，Desktop 依赖不进入 Python Core/Integration/TUI。

### 依赖任务

- T08。

### 参考资料定位

- 原始需求 5、6、19～26、31/T09、32、38、39。
- W01～W05 Feedback 与全部新增测试。

### 完成边界

真实 Desktop 唯一主链离线 E2E 通过，无假数据、重复 authority 或未来方法，TUI/Headless 定向回归通过。

## T10：[端到端验证] Windows Feature Parity

### 任务目标

从可安装产物逐条验收 TUI -> GUI Feature Parity Matrix 及关键失败路径。

### 新增文件

- 仅当现有 Desktop E2E 文件不能清晰承载 Installer 场景时，新增一个职责单一的 Windows E2E test/script。

### 修改文件

- `desktop/tests/**`、关联 Python tests 及被真实 E2E 暴露问题的最小生产文件
- `docs/work/T10-DesktopGUI与TUI全量能力迁移/feedback/W06-integration-delivery-feedback.md`

### 删除文件

- 删除验收产生的可再生成安装/运行临时文件；可审查的精确命令/结果写入 Feedback，不保留机器专属产物。

### 文件职责及实施内容

- Windows 11 x64 真实 E2E 覆盖安装 -> 首配 -> 项目 -> 新 Session -> 对话/Tool -> AskUser/Permission/Plan/Todo -> Steering/Pause/Resume -> Model/Permission/Mode -> Compact/status -> 退出/重启 -> 旧 Session -> 继续对话。
- 失败路径覆盖 invalid config、bad key/provider failure、invalid IPC、Runtime crash、Session corrupt/busy、active Turn close/project switch。
- 人工检查两主题、窄窗口、Runtime Panel 三形态、产品文案、非卡片化布局和无终端窗口产品入口。
- 每项测试记录环境、命令、精确结果和未验证项；不把手工未执行项写成通过。

### 依赖任务

- T09。

### 参考资料定位

- 原始需求 6、32、33、38。
- W06 开工时的 Setup.exe、PyInstaller smoke、Desktop tests 与 Python regressions。

### 完成边界

Feature Parity Matrix、Windows 人工清单和关键失败路径均有真实可审查证据；任何因环境/授权未执行项均明确标记未验证。

## T11：[遗留负担清理] 迁移收口

### 任务目标

删除 T10 迁移后的重复真相、过渡实现、未来占位、不可达代码与可再生成产物，完成代码、测试、文档与工作包收口。

### 新增文件

- 无。

### 修改文件

- 实际能力命中的 `README.md`、`docs/user-manual/getting-started.md`、`configuration.md`、`commands.md`
- `docs/context/A04-Orchestration/Orchestration-Context.md`、`docs/context/TUI/README.md`（仅 TUI 共存事实受影响时），必要的 A02/A03 当前事实文档
- `docs/Context-Index.md`、本包 Checklist 和 W06 Feedback
- T01～T10 产生的生产/测试文件，仅用于删除已确认的重复、dead 或临时实现

### 删除文件

- 删除 unused abstraction/component/IPC、fake HTML data/stub、重复 authority、未来 protocol placeholder、兼容 wrapper 和任务产生的可再生成产物。

### 文件职责及实施内容

- 静态搜索并删除重复 command/event/session/permission/plan/todo truth，通用 Manager/Registry/EventBus/reflective RPC，future device/plugin/subagent/git 占位。
- 静态检查 Renderer 生产字符串和组件，确认无设计说明文案、Card/CardGrid/DashboardCard/SettingCard/ToolCard 通用卡片布局。
- 执行 Python 定向/架构/全量/编译/依赖检查，Desktop unit/integration/E2E/build/package/make 和 PyInstaller smoke，重跑 Windows Installer 关键路径。
- 按 `docs/README.md` 维护映射同步用户手册、当前事实与索引；不修改已冻结工作包文字。
- 核对能力欠账为无且清单不变；Checklist/Feedback 齐全后将 T10 在 Context Index 标为 `implemented_unarchived`，不自动归档。

### 依赖任务

- T10。

### 参考资料定位

- 原始需求 32.4/32.5、34～39。
- `docs/README.md`、`docs/Context-Index.md`、`docs/OutstandingDebtList.md`、W01～W06 Feedback。

### 完成边界

全部 Checklist 有精确证据、W01～W06 Feedback 齐全、文档与 `src/ + tests/` 一致，仓库无 T10 产生的重复 authority、占位/兼容/dead code 或可再生成临时产物；不执行归档或 Git 写操作。
