# T10：Desktop GUI 与 TUI 全量能力迁移 Spec

## 背景

当前 UthCode 已由 Python TUI 承载交互式用户能力，`uthcode exec` 承载 Headless 路径，Application 与 Core 保持无界面产品语义。本包在不改变这些语义的前提下，增加面向普通用户的 Windows Desktop Interface，以 GUI-native 方式完整承载当前 TUI 已有能力。

代码事实基线固定为 `c46f3654b5b38d255027eda689befdbd1e5f832c`。拆分时当前 `HEAD` 为其 F01 第二父系上的 `539cb8c11e13ebb1b9540dcb99a2e8e3d4d0437d`，两者源码树无差异。任务书引用的 `uthcode-desktop-ui-prototype-v5.html` 在拆分时未提供；它只是视觉/交互参考，不是产品事实或实施前提。

## 目标

- 新增 Electron + React/TypeScript Desktop，通过本机私有 JSONL 子进程协议调用 Python UthCode Runtime。
- 保持 `interfaces -> application -> core`，Desktop Renderer、Electron Main 和 Python Bridge 都不创建第二套 Agent、Session、Permission、Plan/Todo 或 Event 真相。
- 完整迁移当前 TUI 用户能力：对话、流式、reasoning、Tool、Steering、pause/resume/cancel、typed interaction、Todo、Slash Command、Model/Permission/Behavior Mode、Session、Compact 和 status。
- 提供当前 user config 字段的窄读写闭环，即使 Application 因未配置而尚未创建，GUI 也能完成首次配置。
- 生成 Windows 11 x64 可安装 `Setup.exe`，捆绑 PyInstaller onedir Runtime，用户机器不依赖系统 Python。
- 保留 `uthcode` TUI 与 `uthcode exec` Headless 入口及现有行为。

## 能力清单

### T01：用户配置 GUI 闭环

- 在 Application 边界提供可脱离已成功构造 Agent Application 调用的安全用户配置视图与当前 schema 写请求。
- 只管理现有 Provider、Model、默认模型和允许持久化的默认权限。
- API Key 只暴露是否已配置，新值仅在一次性写请求中进入原子写入边界。
- 保持现有 user/project 配置隔离、引用校验、秘密边界和原子替换。

### T02：Python Desktop Bridge

- 在 `interfaces/desktop` 增加 stdin/stdout JSONL 私有协议与进程入口。
- 维持 one Application / one Run / one active Turn，负责项目切换、Session、Turn、Command、status 与 settings 窄编排。
- AgentEvent 只包 envelope；typed response 根据当前 pending request 校验并恢复同一 Turn。
- stdout 仅输出合法协议行，diagnostics 只进 stderr，shutdown 有界取消并关闭 Application。

### T03：Electron Shell 与 Python Process

- 建立 Electron Main、Preload、窄 contextBridge、Python child lifecycle 和 Desktop preference 存储。
- Renderer 无 Node/fs/process/child_process 权限；Main 校验 IPC sender，只提供本地资源、文件夹选择与明确的 Explorer 动作。
- 正确拒绝超时、进程异常退出后的 pending request，关闭时不遗留 Python child。

### T04：Desktop 主界面、Project 与 Session

- 建立单左栏的 Project/Session 导航、中部 Chat 与可隐藏/停靠/浮动 Runtime Panel。
- 项目显示别名、pin、recent 及 last-known catalog 只是 Desktop-local 导航事实；不改磁盘目录，不成为 Session authority。
- 点击 Session 直接走 Application resume + safe replay；新 Session 必须原子清空可见 Timeline。

### T05：Conversation Timeline、Streaming 与 Composer

- 只从 `SessionReplayRecord` 和当前 Turn `AgentEvent` 投影连续 Timeline。
- 保留 user/steering/reasoning/assistant/tool 顺序，支持安全 Markdown、streaming、Tool 终态、failure/retry、Todo 和 CompletionBlocked。
- Composer 支持 start/steer/pause/cancel、Model/Permission/Behavior Mode、Slash completion/execute、`/clear` 可见投影和 `/quit` 关闭。

### T06：Typed Interaction Surface

- AskUser、Permission、Plan Review 与 Provider Retry 都从真实 typed pause 产生连续 Interaction Surface；AskUser 保留当前多题/多选/Other/回看能力，Permission 按每次 request choices 动态展示。
- 提交现有具体 typed response 后恢复同一 Turn，Timeline 保留请求、等待与完成痕迹；Plan/Retry/Pause 的 Cancel 调用当前 Turn cancel，不伪造 response。
- pending interaction 优先于 Steering 和新 Turn，不产生 Desktop 自有权限、计划或重试状态机。

### T07：Settings 与 Theme

- Settings 只显示现有真实分类和可读写字段，支持 Provider/Model 增删改、默认模型/权限与 API Key replace。
- 影响 Runtime construction 的配置在 idle 时安全 rebootstrap 并恢复当前 durable Session；active Turn 时禁止直接重建。
- 支持 system/dark/light 与 Desktop-local 持久化，用语义 CSS token 完成两主题可读性。

### T08：Windows Runtime Bundle 与 Installer

- 使用 PyInstaller onedir 构建 `uthcode-desktop-runtime.exe`，只收集真实 Runtime 依赖与资源。
- 通过 Forge `extraResource` 打包 Runtime，使用 Squirrel.Windows 生成 Windows 11 x64 Installer。
- 覆盖无系统 Python 启动、安装/卸载、Runtime smoke 与启停进程验收。

### T09：[接入主流程] Desktop 全链路接入

- 将 Renderer -> Preload -> Main -> Python Bridge -> Application -> Core -> AgentEvent 接入唯一正式链路。
- 删除 prototype stub、fake runtime/session/interaction/settings、浏览器 `alert/prompt/confirm` 和重复命令/事件模型。
- 证明 TUI 与 Headless 入口不退化。

### T10：[端到端验证] Windows Feature Parity

- 在 Windows 11 x64 完成安装、首次配置、Project/Session、对话、Tool、typed interaction、Todo、控制、Compact/status、退出/重启/恢复和继续对话的真实 E2E。
- 覆盖 invalid config、Provider failure、invalid IPC、Runtime crash、Session corrupt/busy、active Turn 关闭/切项目等失败路径。

### T11：[遗留负担清理] 迁移收口

- 清除重复 authority、未使用抽象/组件/IPC、未来占位、原型假数据、卡片式通用组件和设计说明式产品文案。
- 完成 Python/Desktop/Installer 全面回归、文档同步、Checklist/Feedback 与工作包状态收口。

## 非功能要求

- Windows 11 x64 是本轮唯一打包、Installer 与真实 E2E 平台。
- Electron BrowserWindow 必须使用 `nodeIntegration=false`、`contextIsolation=true`、`sandbox=true`，且只加载本地打包内容。
- Production CSP 不允许任意远程 script，不使用 `<webview>`，不允许任意 navigation，不暴露 raw `ipcRenderer`。
- 跨进程输入按不可信数据校验；未知方法、未知字段、过期 typed response 和非法 JSON 不进入 Agent Runtime。
- 不允许 API Key、raw transcript、raw ToolResult、Provider native payload、exception/traceback 进入 UI、协议诊断、持久偏好或 snapshot。
- UI 使用连续页面、列表、分隔线、时间线、行级状态与必要 Surface；禁止卡片矩阵和解释设计本身的产品文案。
- 保持显式串行 Agent Loop、Permission/Secret/Session 安全边界，不新增通用 Manager、Registry、Event Bus、RPC reflection 或双轨兼容逻辑。
- Python 版本与依赖以 `pyproject.toml` 为唯一 authority；Desktop 使用 npm + lockfile，不建 monorepo/workspace。

## 设计骨架

```text
Electron Renderer
  -> narrow preload API
  -> validated Main IPC
  -> one Python child over JSONL
  -> interfaces.desktop bridge
  -> UthCodeApplication
  -> AgentRun / TurnHandle
  -> AgentEvent + SessionReplayRecord
  -> Renderer timeline projection
```

```text
configuration bootstrap
  -> safe user config view
  -> validated current-schema write request
  -> atomic user config write
  -> load effective config
  -> create/recreate Application
  -> resume current durable Session when idle
```

```text
Desktop close/project switch
  -> stop accepting requests
  -> cancel active Turn when present
  -> await bounded terminal result
  -> Application.close
  -> close child stdin / await exit
  -> terminate only after bounded graceful path
  -> reap child
```

## 能力欠账

无。

本包关闭 Desktop 时收口 active Runtime，重启后只从 durable Session safe boundary 开始新 Turn，因此不触发 T05/T06/T09 已记录的 Persistent Runtime Recovery 欠账。本包未引入 Skill/MCP/Subagent，也不触发 T03/T04/T07 对应欠账。`docs/OutstandingDebtList.md` 保持不变。

## Out of Scope

- Subagent、Multi-Agent、Agent Team、通用调度器。
- Git Diff/staging/commit/branch/PR、Worktree、Code Review UI。
- Memory、Skill、MCP、Plugin 平台、Everything-is-plugin、通用 Event Store/Agent SDK。
- Remote Device、Android/iOS/watch/car、Voice/STT/TTS、Computer Use、Browser、IDE/Web UI、Cloud sync。
- Account/Login、usage billing、Automations、Background Agent、Windows Service、Tray Host、Auto Update。
- durable Session title、项目目录重命名、Runtime checkpoint、active/paused Turn restart recovery。
- FastAPI/HTTP/WebSocket/Named Pipe/gRPC/MCP transport，macOS/Linux 打包与签名/证书平台。
- 绑定大型 UI framework、Redux/Zustand/MobX/XState、通用主题引擎或为语法高亮引入的大型框架，除非当前实现有可证明的真实需求。

## 验收标准

1. Windows Desktop 能启动捆绑 Runtime，普通用户不需安装 Python或打开终端。
2. 当前 TUI Feature Parity Matrix 所有产品能力在 GUI 中有真实等价路径，且不依赖 fake state。
3. Desktop 仅通过 Application 公共边界使用 Core；Session/Run/Turn/Event/Permission/Plan/Todo/Model/Context 权威仍在 Python。
4. Session 点击即 resume，safe replay 原子替换 Timeline，新 Session 为空视图，后续输入写入选中 Session。
5. AskUser、Permission、Plan Review、Retry 都完成 request -> waiting -> response -> same Turn continue，pending 期间不能旁路为 Steering；AskUser 全数据形状、Permission 动态 choices 与 Plan/Retry/Pause cancel 语义与当前代码一致。
6. Slash completion/execute、Model/Permission/Behavior Mode、Session/Compact/status 均复用 Python authority，TypeScript 不维护第二份语义表。
7. 首次未配置状态可读写当前 user config；API Key 不回显且不进入日志/协议事件/持久 UI state。
8. Renderer 无 Node/fs/process/child_process 权限，IPC sender、navigation、CSP、本地内容和跨进程输入校验满足冻结边界。
9. Desktop 关闭或切项目时 active Turn 被取消收口，无 orphan Python child；重启只恢复 durable Session。
10. system/dark/light 与 Runtime Panel 形态通过；产品无卡片式 Dashboard、设计说明文案和未来能力入口。
11. PyInstaller smoke、Electron unit/integration/E2E、Forge package/make、Windows 11 x64 安装/卸载/无 Python 运行与 Python 定向/架构/全量回归全部有精确记录。
12. `uthcode` TUI 与 `uthcode exec` 不退化，无重复 authority、兼容层、未来占位、dead code 或任务产生的构建临时产物。

## 冻结决策追踪

| 决策 | 覆盖 |
| --- | --- |
| D-T10-01 GUI 配置范围 1B | T01、T07、验收 7 |
| D-T10-02 Windows 11 x64 | T08、T10、验收 1/11 |
| D-T10-03 只迁移已有能力 | T02～T11、Out of Scope |
| D-T10-04 禁止设计说明文案与卡片化 | T04～T07、T09～T11、验收 10 |
