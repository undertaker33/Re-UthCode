# W04 Renderer Feature Parity Feedback

## 状态

W04 T04 -> T05 -> T06 -> T07 已在 W03 合并基线 `106b405` 上完成 Renderer 范围实施；未实施 T08 打包，未执行 Git 写操作。原型 `uthcode-desktop-ui-prototype-v5.html` 在仓库与 `D:\project` 中仍缺失，本反馈不把原型视觉/交互视为已验证依据。

## T04：Project / Session

- Renderer 通过现有 `DesktopApi.requestRuntime` 调用 `project.open`、`project.sessions`、`session.new`、`session.resume`；Project/Session/Run 结果进入 `state.ts` 的唯一 Renderer projection。
- `project.open` 成功后以 Bridge 返回的安全 catalog 和 Run 替换当前项目的 Timeline/Run；激活项目立即刷新 catalog，非激活项目只保留 Desktop preference 中的导航缓存。
- Session 点击调用 `session.resume` 并按 safe replay 的 `sequence` 排序；新 Session 调用 `session.new`，Timeline 立即为空。别名、pin、recent、选中项只写 Desktop preference；移除项目只移除导航记录，不删除磁盘或 Session。
- `Sidebar.tsx` 使用连续列表/行/分隔线，包含 New chat、Open project、Pinned/Projects、Session、Settings 与明确的 Explorer 动作；没有 account/logout/usage、hover preview card 或浏览器 `prompt`/`confirm`。

## T05：Timeline / Composer

- `state.ts` reducer 按 AgentEvent 到达顺序合并 reasoning/assistant streaming block、同一 Tool activity 的 started/finished 终态、steering/pause/terminal 状态；assistant completed 的权威正文替换 preview，失败/取消删除未完成 preview，reasoning tail 在 assistant/tool/terminal 边界收口。
- `ChatTimeline.tsx` 只显示 safe replay/live 投影与安全 Tool summary，不读取或渲染 ToolResult 正文；TaskState 是 replace-all Todo 投影，CompletionBlocked 显示受控原因。
- `ChatTimeline.tsx` 提供受限 safe Markdown：heading、paragraph、list、quote、table、link、inline code/emphasis、fenced code；原始 HTML 走 React text escaping，链接只允许 `http`/`https`/`mailto`。
- `Composer.tsx` idle 普通输入走 `turn.start`，active 普通输入走 `turn.steer`；Pause、Cancel、Steer 明确分离。Slash completion/execute、Model、Permission、Behavior、New、Compact、clear、quit 均复用 Python Bridge/Registry/use case，不在 TypeScript 复制完整权威表。
- `RuntimePanel.tsx` 只显示 runtime/turn/run/context/mode/project/session 等安全事实，支持 hidden/docked/floating；不显示 prompt、transcript、ToolResult、secret 或 native exception。

## T06：Typed Interaction

- `InteractionSurface.tsx` 按 Bridge `turn_paused` 的 pause kind 渲染 user input、permission、plan review、provider retry 与用户 Pause；请求保留 pause/run/turn/tool identity。
- AskUser 覆盖 1～4 题、text/single-select/multi-select、选项描述、allow-other、前后移动、review/edit/submit；Other 仅提交用户输入的非空值，不提交 UI sentinel。
- Permission 按 request.choices 动态绘制，不假设每个请求都有 session choice；Plan approve/revise/cancel、Retry cancel、Pause cancel 均分别走 typed resume 或当前 handle 的 `turn.cancel`；Pause Continue 构造 `resume_turn`。
- pending interaction 时 Composer 禁止普通输入/Slash 旁路；`sendInteraction` 只发送 `turn.resume`，pending 清理与再次 interaction 由 Bridge AgentEvent reducer 事实驱动。

## T07：Settings / Theme

- `SettingsView.tsx` 使用当前 `settings.get` safe configuration view，连续设置行展示 Providers、Models、Permissions、Interface、About；不渲染 API key 明文，仅显示 configured/not configured，replacement/clear key 只存在短生命周期 local state，成功后清空。
- 保存请求映射 T01 当前 schema，并剥离 `api_key_configured` display-only 字段；配置校验/引用校验仍由 Python T01 use case 完成。active Turn 时阻止保存；idle 保存走 `settings.save`，随后 `runtime.shutdown` -> `runtime.initialize` -> durable Session resume。
- `app.css` 提供 system/dark/light 语义 token、focus/状态线索和连续行/时间线布局；无 CardGrid/SettingCard/dashboard tile 或设计说明产品文案。

## 状态所有权与数据流

真实链路为 `User -> App/Renderer callbacks -> Preload DesktopApi -> Main IPC -> PythonRuntime -> DesktopBridge -> Application/Core`；Bridge 返回 safe DTO，PythonRuntime 事件经 Main/Preload 传到 `reduceAgentEvent`。Agent Loop/Run/Session/Permission/Tool/Configuration 的权威状态仍在 Python Application/Core；Renderer 只持有可丢弃的显示投影、临时答案、主题/导航偏好。Renderer 不新增 Bridge/Core 方法，不创建 fake store，不扫描项目文件系统。

## 修改文件

- `desktop/src/renderer/App.tsx`
- `desktop/src/renderer/Sidebar.tsx`
- `desktop/src/renderer/RuntimePanel.tsx`
- `desktop/src/renderer/state.ts`
- `desktop/src/renderer/ChatTimeline.tsx`
- `desktop/src/renderer/Composer.tsx`
- `desktop/src/renderer/InteractionSurface.tsx`
- `desktop/src/renderer/SettingsView.tsx`
- `desktop/src/renderer/app.css`
- `desktop/src/renderer/main.tsx`
- `desktop/webpack.renderer.config.ts`
- `desktop/tests/renderer.test.tsx`
- `desktop/package.json`（仅将 Renderer 定向测试加入现有 `npm test`）

## 原型、人工验证与范围边界

- 原型未提供/未验证。
- 未执行真实 Electron Windows 交互、native folder picker、三真实 Session 连续切换、两主题人工可读性、窄窗口与 Runtime Panel 人工验收；这些留给后续集成/Windows 验收范围，不能记为通过。
- 未执行 T08 PyInstaller、`npm run package`、`npm run make` 或 Installer 验收。
- 未修改 `src/uthcode`、Bridge、Preload、Main 的公共 API；当前检查未发现 W02/W03 公共边界缺口。

## 验证（初始实现记录，最终结果追加于下）

- 初始红测：在新增 Renderer 测试首次运行时，`desktop/src/renderer/state.ts` 尚不存在，测试按预期失败。
- 随后实现过程中已有 29 项 Desktop/Renderer tests 通过；最终精确命令与结果在下方追加。

## 最终验证结果

- `desktop` 中执行 `npm ci`：成功，安装 733 packages；输出仅含上游依赖弃用提示。
- `desktop` 中执行 `npm test`：31 passed、0 failed、0 skipped（包含 Preload、Runtime process、Main bundle 与 Renderer tests）。
- `desktop` 中执行 `npm run typecheck`：退出码 0。
- `desktop` 中执行 `npx webpack --config webpack.renderer.config.ts --mode production --output-path .tmp-webpack-renderer`：退出码 0；产出 255 KiB renderer bundle，Webpack 仅报告推荐体积 warning，无编译错误。
- 执行 `git diff --check`：退出码 0；仅报告既有工作区换行提示。
- Renderer 静态检查：卡片/设计说明/未来能力关键字无命中；`fake` 的命中仅为当前真实 Provider kind 选项与测试配置，不是 fake store 或 fake interaction。`desktop/src` 无 `alert`/`prompt`/`confirm`/demo/mock session 命中。
- 运行 `C:\Users\93445\.codex\skills\uth-utf8-guard\scripts\check_utf8_docs.py` 检查本 Feedback：`OK: 1 file(s) passed UTF-8 guard`，无 replacement character/mojibake，Markdown fence 平衡。
- 清理精确删除本轮生成的 `desktop/node_modules` 与 `desktop/.tmp-webpack-renderer`；未删除源码、文档、配置或未知文件。

## Checklist 证据边界

本轮只对能由上述自动化证据与代码静态事实精确支持的 T04～T07 条目勾选；真实 Electron/Windows、native picker、配置首配、Bridge E2E、三 Session 人工连续性和两主题人工可读性仍保持未勾选，未把 Renderer SSR/reducer 测试扩大解释为真实 Desktop 验收。

## 验证记录更正

在补充 T04～T06 证据测试后，最终 `npm test` 实际为 36 passed、0 failed、0 skipped；此前“31 passed”的中间记录不代表最终总数。最终 Renderer webpack 产物实际为 256 KiB，仍仅有体积建议 warning。

## Reviewer CHANGES REQUIRED 第 1 轮返工

本节是对 Reviewer 返工要求的追加记录，不覆盖前文事实。返工仍严格限定在 T04→T07；未实施 T08 打包与任何 Git 写操作。

### 逐项修复与可观测证据

1. T04 Settings 保存现在由 `rebootstrapProject` 严格调用 `runtime.shutdown` → `runtime.initialize(workdir=currentPath)` → `project.open(currentPath)`，由 `project.open` 返回 candidate Application/fresh Run，再按保存前的 durable `sessionId` 调用 `session.resume`；Renderer 不自行重建 Run。新增测试记录完整调用顺序，并验证 initialize 失败时不会继续 project.open/resume。
2. `/quit` 的 Bridge/Application shutdown 仍由现有 `command.execute` 完成，新增窄 `DesktopApi.closeShell`、`desktop.shell.close` IPC 和 Main handler；Renderer 收到 `quit_interface` 后请求该动作，Main 复用已有 `beginApplicationShutdown`，共同收口 Python child 与 Electron window。Preload 暴露、sender 校验、handler 回调均有测试；未扩展 Bridge。
3. Project remove 现在区分非当前与当前：非当前仅更新导航 preference 并保留当前 selection；当前项目先等待 active Turn 收口，再经真实 `project.open` 切换到剩余项目，或经 `runtime.shutdown` + workspace clear 清空，成功后才持久化移除结果。Reducer 记录并拒绝已替换/已清空 Run 的旧事件，避免旧 Timeline 继续写。新增 plan、切换和清空后的 stale event 测试；未删除磁盘、Session 或 Project 内容。
4. `InteractionSurface` 同时使用 `key={pauseId}` 重挂载和 `useEffect([pauseId])` 清理 answers/step/review/otherText/planFeedback；新增同一 Turn 连续 AskUser→Plan 的不同 pause key 测试。
5. 核对现有 Bridge `status.get`、runtime/run snapshot 与 `command.execute` 投影：fresh Run 的 status/run DTO 没有 permission mode，只有明确的 `permission_mode_selected` command action 返回该事实。因此未修改 W02 Bridge/Core；Renderer 在 project/session/new Run 边界显示 `Unavailable`，只在 Settings 默认配置或该 command action 返回后显示具体 mode，不猜测并不跨 fresh Run 残留。新增 reducer/Composer 测试。
6. Settings 当前 schema 编辑补齐真实 Provider ID、Model ref、`provider_profile_id`、`remote_id`、`display_name`、`context_window`、`max_output_tokens`、`reasoning_effort` 以及 default model/permission；Provider/Model ID 重命名会同步当前引用和 default model，提交仍只包含 T01 当前字段。新增 schema field/ID helper 与 SSR 投影测试。
7. `turn_completed` 现在只移除该 Turn 的 streaming assistant preview，将 streaming reasoning 改为 completed 并保留 tail，再固化 authoritative final；failed/cancelled 继续沿冻结语义删除未完成 streaming entries。新增 reasoning tail reducer 测试，既有失败路径继续通过。
8. panel hidden 时 Header 与 Sidebar 保留 `Show Runtime` 恢复入口，点击沿现有 preference 持久化路径恢复 docked；新增隐藏状态 SSR 测试。
9. Slash completion 新增 token-level `applyCompletion`：命令候选使用 Python 返回的 canonical value，参数候选只替换当前参数 token，保留已有 canonical/alias 前缀与前置参数；新增 canonical、alias、当前 argument 覆盖测试。

### 返工后的验证

- `desktop` 执行 `npm ci`：成功，新增/解析 733 packages；仅有上游依赖弃用与 git dependency integrity warning。
- `desktop` 执行 `npm run typecheck`：退出码 0。
- `desktop` 执行 `npm test`：46 passed、0 failed、0 skipped，包含新增返工可观测测试、Preload/Main shell-close、Runtime process、Renderer reducer/SSR。
- `desktop` 执行 `npx webpack --config webpack.renderer.config.ts --mode production --output-path .tmp-webpack-renderer`：退出码 0；renderer bundle 260 KiB，只有 3 条 webpack 推荐体积 warning，无编译错误。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_desktop_protocol.py tests/test_desktop_bridge.py tests/test_architecture_boundaries.py -q`：79 passed in 12.83s。
- `git diff --check`：返工完成后执行，退出码 0；换行提示不构成 diff error。
- 返工后 UTF-8 guard 覆盖本 Feedback 与 Checklist：`OK: 2 file(s) passed UTF-8 guard`，无 replacement character/mojibake，Markdown fence 平衡。

### Checklist 复核与未验证项

本轮没有把静态/SSR/Reducer 证据扩大为真实 Windows/Electron 验收，也没有新增未经真实证据支持的 `[x]`；既有 T04～T07 勾选保持原证据边界。Native folder picker、真实 Electron close/child 联动、三 Session/Project 人工连续性、无配置首配、完整 GUI 保存/引用校验、两主题人工可读性和 T10 E2E 仍未验证，相关 Checklist 继续保持 `[ ]`。

返工后实际修改范围新增 `desktop/src/desktop-api.ts`、`desktop/src/preload.ts`、`desktop/src/main.ts`；其余 Renderer/测试文件均仍在 W04 范围。原型 `uthcode-desktop-ui-prototype-v5.html` 仍缺失。`desktop/node_modules` 与 `.tmp-webpack-renderer` 为本轮验证生成物，完成交付前按精确路径清理；不删除源码、文档或未知文件。

## 返工第2轮（用户批准最小重开W02/W03）

本轮依据用户明确批准，只最小重开 W03 Runtime/Main shutdown-restart 与 W02 Bridge/Application safe projection；同时修正 W04 已发现的 terminal reducer 和窄屏 Runtime 入口。未实施 T08、未执行 Git 写操作，也未扩展为通用重启管理器或第二状态权威。

### 批准边界内的更正

1. `PythonRuntime` 新增窄 `shutdownAfterRequest()` close/reap 阶段；Main 对 `runtime.shutdown` 先等待 Bridge response，再等待真实 child close/reap，未确认 close 前不会允许下一次 child 启动。真实 Node child 测试按 `runtime.initialize` → `project.open` → `session.resume` → `runtime.shutdown` 验证旧 PID 保持到 reap，随后新 PID 发生替换；`rebootstrapProject` 另覆盖 shutdown/initialize/project.open/session.resume 各阶段失败即停止后续调用。
2. Bridge 在现有 safe Run/status 投影上仅加入 allowlist 后的当前 `AgentRun.permission_mode` 字符串，并让 permission command result 带同一 safe Run 投影；未暴露 Core/native 对象。Renderer 的 `runtime_initialized`、project/session/fresh Run、turn accepted 和 command result 只从 safe Run 更新 permission；`settings_loaded` 不再把 default permission 冒充当前 Run，fresh Run 缺少权威值时保持 `unknown`。
3. `turn_failed` 与 `turn_cancelled` 先将当前 Turn 的 reasoning streaming tail 固化为 completed，再只移除 assistant streaming preview；分别新增 failed/cancelled reducer 断言。
4. <=1080 窗口在 Header/Sidebar 始终保留 Runtime 开关；开关用现有 panel preference 在 hidden 与 floating 间切换，floating 在窄屏表现为可恢复的右侧 drawer。新增 SSR/CSS 可观测测试；没有新增未来入口或装饰布局。

### 本轮实际修改与验证

- 修改：`desktop/src/python-runtime.ts`、`desktop/src/main.ts`、`desktop/src/renderer/state.ts`、`desktop/src/renderer/App.tsx`、`desktop/src/renderer/Sidebar.tsx`、`desktop/src/renderer/app.css`、`src/uthcode/interfaces/desktop/bridge.py`，以及对应 `desktop/tests/runtime-process.test.ts`、`desktop/tests/preload.test.ts`、`desktop/tests/renderer.test.tsx`、`tests/test_desktop_bridge.py`。
- `desktop` 执行 `npm ci`：成功，解析 733 packages；仅有依赖提示。
- `desktop` 执行 `npm run typecheck`：退出码 0。
- `desktop` 执行 `npm test`：54 passed、0 failed、0 skipped；包含真实 child PID 替换、Main reap 顺序、failed/cancelled reasoning、safe permission 和窄屏 drawer 证据。
- `desktop` 执行 `npx webpack --config webpack.renderer.config.ts --mode production --output-path .tmp-webpack-renderer`：退出码 0，renderer bundle 262 KiB，仅有 3 条 Webpack 体积建议 warning。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_desktop_protocol.py tests/test_desktop_bridge.py tests/test_architecture_boundaries.py -q`：80 passed in 11.21s。
- 本轮没有发现 W02 Bridge/Protocol 公共边界缺口；没有修改 Core、Provider、Tool、Session Store 或新增 authority。真实 Electron Windows/native picker、配置首配、三 Session 连续人工切换、窄屏视觉/键盘人工验收仍未验证；原型 `uthcode-desktop-ui-prototype-v5.html` 仍缺失。
- Checklist 仅保留已有精确自动化证据勾选，未把本轮 SSR/单元测试扩大成真实 Electron/E2E 勾选；未修改冻结 Checklist 文字或顺序。
- 完成交付前清理精确路径 `desktop/node_modules`、`desktop/dist`（以及若存在的 `.tmp-webpack-renderer`），不删除源码、文档或未知文件；随后对本 Feedback/Checklist 执行 UTF-8 guard，并执行 `git diff --check`。
