# W03 Electron Shell 与 Python Process 实施反馈

## 状态

W03 已开始实施。本文档为首次实施创建；只记录 T03 的实际结果，未执行 Git 写操作。

## 开工前取证

- 已读取 `AGENTS.md`、`docs/README.md`、`docs/Context-Index.md`、`docs/rules/WorkPackageRules.md`、`docs/rules/UserDecisionBoundary.md`、`docs/OutstandingDebtList.md`、T10 原始需求、Spec、Tasks、Checklist、本 Prompt，以及 W01/W02 Feedback。
- 已核对 W02 已实现的 Python Desktop Bridge contract 与 Bridge tests；本 Worker 不修改 `src/uthcode`。
- 已查阅 Electron 官方 Security 文档与 Electron Forge 官方 Webpack Plugin 文档。官方资料要求启用 context isolation/process sandbox、限制 CSP/navigation/new windows、校验 IPC sender，并通过 Webpack plugin 配置 main/renderer entry 与 preload。
- 版本核对：`npm view electron@44 version` 为 `44.0.0`；`npm view @electron-forge/cli@7.11.2 version`、`@electron-forge/plugin-webpack@7.11.2`、`@electron-forge/maker-squirrel@7.11.2` 均为 `7.11.2`。实现固定使用 Electron `44.0.0` 与 Forge `7.11.2`。

## 实施记录

### 测试先行

先创建 `desktop/tests/preload.test.ts` 与 `desktop/tests/runtime-process.test.ts`，在生产实现尚不存在时执行 `npm test`，得到两个 `MODULE_NOT_FOUND` 红灯；随后才建立实现与工具链。最终测试保持为 11 个通过用例。

### 实际实现

- `desktop/package.json` 与 `desktop/package-lock.json` 固定 Electron `44.0.0`、Electron Forge CLI/Webpack Plugin/Squirrel maker `7.11.2`，使用 npm、TypeScript、Webpack、React 和 `tsx` 测试入口。Forge 配置只接入官方 Webpack plugin；没有加入 T04+ Renderer 产品组件或 T08 打包 Runtime。
- `desktop/src/main.ts` 创建单个 `BrowserWindow`，固定 `nodeIntegration: false`、`contextIsolation: true`、`sandbox: true`、`webviewTag: false`、`webSecurity: true`，并拒绝 webview、任意新窗口、非 allowlist navigation 和非主 frame/origin IPC。folder picker 只返回 canonical absolute path；Explorer 只接受本进程 picker 登记的项目路径；Main 不承载 Agent 语义。
- `desktop/src/preload.ts` 通过 `contextBridge` 只暴露 `window.uthcode` 的 `openProject`、`openProjectInExplorer`、`requestRuntime`、`subscribeAgentEvents`、`readPreference`、`writePreference` 六个窄方法。Renderer 不接触 raw `ipcRenderer`、event、shell、fs 或 Node 对象；跨边界值均进行 JSON-safe 校验。
- `desktop/src/python-runtime.ts` 使用 `spawn(command, args, { shell: false, stdio: ["pipe", "pipe", "pipe"], windowsHide: true })`。开发态只接受显式 `UTHCODE_PYTHON` 或当前 `CONDA_PREFIX` 的 Python；生产态只从 `process.resourcesPath/uthcode-runtime/uthcode-desktop-runtime(.exe)` 解析，不回退 PATH/system Python。stdout 按 JSONL 做 response correlation、AgentEvent/runtime-state 分流，stderr 独立交给 diagnostics；request timeout、malformed response、process error/exit 都使用稳定 Runtime boundary error。shutdown 先请求 `runtime.shutdown`，再关闭 stdin，进行有界等待、terminate 和 reap。
- `desktop/src/desktop-preferences.ts` 以 userData 下 `desktop-preferences.json` 为单文件 UI metadata store，原子写入并只允许 theme、windowBounds、panelMode、recentProjects、projectAliases、pinnedProjectKeys、selectedProjectKey、selectedSessionId；未知字段（包含 API key/session body 等）拒绝，不落盘 Agent 权威事实。
- `desktop/src/renderer/index.html` 提供 production CSP（`script-src 'self'`、`object-src 'none'`、`frame-src 'none'`），`desktop/src/renderer/main.tsx` 只有无状态 boot shell，不预建 Project/Session/Chat/Interaction/Settings fake state。

### 官方资料与版本核对

- Electron 官方 [Security](https://www.electronjs.org/docs/latest/tutorial/security) 文档核对了 context isolation、process sandbox、CSP、navigation/new-window 限制与 IPC sender 校验。
- Electron Forge 官方 [Webpack Plugin](https://www.electronforge.io/config/plugins/webpack) 文档核对了 main/renderer/preload entry、`nodeIntegration=false` 的 renderer target 与 dev CSP 配置。
- `npm view electron dist-tags.latest` 与 `npm view electron@44 version` 均指向 `44.0.0`；Forge CLI、Webpack Plugin、Squirrel maker 的 `dist-tags.latest` 均为 `7.11.2`，指定版本查询也均返回 `7.11.2`。

## 修改文件

- `desktop/package.json`
- `desktop/package-lock.json`
- `desktop/forge.config.ts`
- `desktop/tsconfig.json`
- `desktop/webpack.main.config.ts`
- `desktop/webpack.renderer.config.ts`
- `desktop/src/main.ts`
- `desktop/src/python-runtime.ts`
- `desktop/src/preload.ts`
- `desktop/src/desktop-api.ts`
- `desktop/src/desktop-preferences.ts`
- `desktop/src/renderer/index.html`
- `desktop/src/renderer/main.tsx`
- `desktop/tests/preload.test.ts`
- `desktop/tests/runtime-process.test.ts`
- `docs/work/T10-DesktopGUI与TUI全量能力迁移/feedback/W03-electron-shell-process-feedback.md`
- `docs/work/T10-DesktopGUI与TUI全量能力迁移/T10-DesktopGUI与TUI全量能力迁移-checklist.md`（仅勾选 T03 现有项目）

## 精确验证

| 命令 | 结果 |
| --- | --- |
| `npm ci`（`desktop`） | 退出码 0；安装 733 packages |
| `npm ls electron @electron-forge/cli @electron-forge/plugin-webpack @electron-forge/maker-squirrel --depth=0` | `electron@44.0.0`、`@electron-forge/cli@7.11.2`、`@electron-forge/plugin-webpack@7.11.2`、`@electron-forge/maker-squirrel@7.11.2` |
| `npm run typecheck`（`desktop`） | 退出码 0 |
| `npm test`（`desktop`） | **11 passed, 0 failed** |
| `npx webpack --config webpack.main.config.ts --mode production --output-path .tmp-webpack-main` | 编译成功；临时输出已删除 |
| `npx webpack --config webpack.renderer.config.ts --mode production --output-path .tmp-webpack-renderer` | 编译成功；临时输出已删除 |
| `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_desktop_protocol.py tests/test_desktop_bridge.py tests/test_architecture_boundaries.py -q` | **79 passed in 10.19s** |
| `git diff --check` | 退出码 0；无 whitespace error |

W03 测试包含：secure BrowserWindow policy、restrictive CSP、Renderer Node 能力排除、Preload API 与 IPC/event 隔离、sender/frame 校验、picker 注册与 Explorer gate、dev/prod Runtime 路径、精确 spawn 参数、response/event/stderr correlation、timeout/malformed/exit rejection、Bridge shutdown、fixture child terminate/reap、实际 Node child PID 消失和 preferences allowlist。

## Checklist 状态

T03 Checklist 9/9 项已在上述精确证据后勾选；T01/T02 和 T04+ 项未修改。未修改 Spec、Tasks、Prompt、原始需求或其他冻结文字。

## 未完成项、风险与边界

- 未启动真实 Electron GUI 窗口做 Windows 桌面交互 E2E；现有测试通过可注入 BrowserWindow policy/IPC handler 与实际 child PID 覆盖 Main/Preload 核心边界。
- 未验证 Windows 生产安装包、Squirrel maker、PyInstaller onedir、捆绑 Runtime、签名、安装/卸载或系统 Python 缺失场景；这些属于后续 T08/W06 打包与全链路验收。
- 未运行真实用户配置下的 `runtime.initialize` Electron→Python 全链路；W02 已验证 Python module 子进程协议，本 Worker 的 Node fixture 验证 child transport/lifecycle contract。
- 尚未验证真实 Electron 安全审计工具、CSP 在打包后加载、OS-level process policy 或 renderer visual behavior；不把这些未运行项目宣称为通过。
- 未发现任务书冲突、能力欠账触发或需要用户拍板的产品/架构/安全决策。未新增或修改 `docs/OutstandingDebtList.md`。
- 未引入兼容层、旧 API、重复 Agent/Session/Permission/Event authority、通用 RPC、后台 Agent、Tray、Service 或未来 Renderer 产品状态；未执行任何 `git add`、`commit`、`push`、`merge`、`rebase`、`tag`、`release` 或归档。

## 遗留负担清理

- `rg` 复核 `desktop/src` 只有 T03 Main/Preload/runtime/preferences 与最小 boot shell；未创建 T04+ 产品组件、fake state、第二套 Runtime/Session/Permission/Plan/Event authority。
- Webpack 配置使用现有官方 plugin 约定；没有额外 monorepo、Vite experimental、Redux/Zustand/MobX/XState、通用 transport manager 或未来设备协议。
- 测试临时 Webpack 输出已清理，工作区只保留源码、测试、配置和 npm lockfile；Python 源码与 W02 写集未变。

UTF-8 guard:
- files checked: `docs/work/T10-DesktopGUI与TUI全量能力迁移/feedback/W03-electron-shell-process-feedback.md`、`docs/work/T10-DesktopGUI与TUI全量能力迁移/T10-DesktopGUI与TUI全量能力迁移-checklist.md`（写入前、写入后）。
- result: `check_utf8_docs.py` 返回 `OK: 2 file(s) passed UTF-8 guard`；replacement character、常见 mojibake 和 Markdown fence 不平衡均为 0。
- repaired encoding issues: none。

## 接管复核记录（第 2 轮）

### 接管原因与审计结论

上一轮 W03 已形成完整事实记录，但总控会话在交付前中断。本轮先保留并复核该记录、当前未提交 diff、Electron 实际类型与 W02 Python fixture，再在原有 T03 写集内收敛边界问题；未修改原记录、冻结任务书、Python Bridge 或 T04+ Renderer。Electron 44.0.0 的 `will-frame-navigate` 类型确认是单个 `details` 事件对象，既有实现与该版本 API 一致，因此没有引入无效改动。

### 接管期间实际修改

- `desktop/src/python-runtime.ts`：为内部 shutdown 请求增加独立 timeout，并用单一 deadline 约束 shutdown request、stdin close、graceful wait 和 terminate/reap；进程事件按 child identity 绑定，只有 `close` 完成等待，先发 `SIGTERM`，仍未退出再发 `SIGKILL`。Runtime state、Agent event 和 response envelope 拒绝未知状态/字段、空事件类型和不符合安全形状的 error，异常仍统一落在 Runtime boundary，不伪装成 Agent/Provider failure。
- `desktop/src/desktop-preferences.ts`：原子写入失败时清理同目录临时文件，成功 rename 后同样不遗留临时文件；allowlist、UI metadata 范围和 API Key/Session/Agent 事实隔离不变。
- `desktop/tests/runtime-process.test.ts`：将 stuck-child fixture 的普通 request timeout 调大到 1 秒而 shutdown deadline 保持 10ms，并断言 shutdown 在 500ms 内完成，证明关闭不会被普通请求 timeout 拖延；其余 child PID、force-reap、偏好隔离覆盖保持不变。
- 清理了本轮 `npm ci` 产生的可再生成 `desktop/node_modules`；保留源码、测试、配置和 `package-lock.json`，未修改 `.gitignore` 或其他用户文件。

### 接管后精确验证

| 命令 | 结果 |
| --- | --- |
| `npm ci`（`desktop`） | 退出码 0；安装 733 packages（npm 仅报告既有 deprecated dependency 警告） |
| `npm ls electron @electron-forge/cli @electron-forge/plugin-webpack @electron-forge/maker-squirrel`（`desktop`） | `electron@44.0.0`；`@electron-forge/cli@7.11.2`；`@electron-forge/plugin-webpack@7.11.2`；`@electron-forge/maker-squirrel@7.11.2` |
| `npm run typecheck`（`desktop`） | 退出码 0 |
| `npm test`（`desktop`） | **11 passed, 0 failed** |
| `npx webpack --config webpack.main.config.ts --mode production --output-path .tmp-webpack-main`（`desktop`） | 编译成功；临时输出已删除 |
| `npx webpack --config webpack.renderer.config.ts --mode production --output-path .tmp-webpack-renderer`（`desktop`） | 编译成功；临时输出已删除 |
| `npm run package`（`desktop`） | 退出码 0；Forge 完成 win32/x64 packaged app smoke，未执行 `make`/Installer 验收；生成的 `.webpack`/`out` 已删除 |
| `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_desktop_protocol.py tests/test_desktop_bridge.py tests/test_architecture_boundaries.py -q` | **79 passed in 6.67s** |
| `git diff --check` | 退出码 0；无 whitespace error |

接管后 T03 Checklist 的 9/9 项继续为 `[x]`；没有勾选 T04 及之后项目，也没有执行任何 Git 写操作。

### 接管后的未验证项与风险

- 未启动真实 Electron 窗口做 Windows UI/E2E；虽已执行 `npm run package` smoke，仍未执行 Forge `make`/Installer、PyInstaller onedir、捆绑 Runtime、安装/卸载、签名或无系统 Python 验收，这些仍属于 T08/W06 范围。
- 未在打包产物中复核 CSP/navigation 或通过 OS 级工具审计 child policy；本轮验证了两套 Webpack production 编译、源码安全约束、注入式 Main/Preload 边界、真实 Node child PID 消失和 Python Bridge fixture。
- 未执行真实用户配置下 Electron → Python `runtime.initialize` 全链路；W02 fixture 的 Python module 子进程协议验证仍是当前证据。

### 接管轮次 UTF-8 guard

- files checked: `docs/work/T10-DesktopGUI与TUI全量能力迁移/feedback/W03-electron-shell-process-feedback.md`、`docs/work/T10-DesktopGUI与TUI全量能力迁移/T10-DesktopGUI与TUI全量能力迁移-checklist.md`。
- result: 写入前和写入后均执行 `check_utf8_docs.py`，结果为 `OK: 2 file(s) passed UTF-8 guard`；replacement character、常见 mojibake 和 Markdown fence 不平衡均为 0。
- repaired encoding issues: none。

## 返工第 1 轮（审查未通过后）

### 返工原因与边界

本轮针对审查指出的四项问题返工：Webpack Main bundle 不能依赖 `require.main === module`；malformed stdout、process error 或 Bridge `runtime_state=failed` 后，旧 child 尚未 close/reap 时不得被新 child 覆盖；shutdown 不能因 graceful 阶段耗尽 deadline 而在未确认 close 时清除 child；production `createRuntime` 必须把 stderr 与 Runtime failure 通过稳定、秘密安全的事件 sink 暴露。仍只修改 T03 Electron Main/Preload、Python child lifecycle、preferences/test 写集，没有进入 T04+，没有 Git 写操作。

### 实际修改

- `desktop/webpack.main.config.ts` 增加 `DefinePlugin` 的显式 `UTHCODE_DESKTOP_MAIN_BUNDLE=true`；`desktop/src/main.ts` 将启动逻辑收敛为导出的 `bootstrapMain()`，仅由生产 Main bundle 的编译期 gate 无条件触发，源码 helper import 仍保持惰性。新增 `desktop/tests/main-bundle.test.ts`，实际编译 Webpack Main bundle，通过 Electron stub 执行 bundle，观测 `app.whenReady()` 与 `BrowserWindow` 创建及安全 WebPreferences，而非只测试源码 helper。
- `desktop/src/python-runtime.ts` 保留 failed child 的所有权直到 `close` 事件；`start()` 在 child 仍存在时拒绝 replacement，close/reap 后才允许下一次 start。malformed/process error/runtime-state failure 会转为 Runtime boundary failed state，并可通过 `onRuntimeState` 观察。shutdown 将 bounded graceful request、stdin close wait、SIGTERM wait、SIGKILL wait 分成独立有限窗口，检查 `kill()` 返回值；没有确认 close/reap 时保持 child/PID、保留 failed state 并抛出 `shutdown_timeout`，不会伪造 stopped。
- `desktop/src/main.ts` 的 production `createRuntime` 现在动态绑定当前 Main window 的 `onAgentEvent`、`onRuntimeState`、`onDiagnostic` sink。stderr 只产生固定 `runtime_diagnostic` 事件，不复制原始异常/凭据/Node child；内部 idle child failure 通过 `runtime_state=failed` 事件可观察。shutdown boundary failure 不再吞掉后直接退出 Electron，而是保留窗口和 child 所有权并允许后续有界重试。
- `desktop/tests/runtime-process.test.ts` 新增 malformed→start、process-error→start、runtime-state-failed→start 回归，以及 `kill=false`/无 close 保留 PID、延迟 close 在 terminate 窗口内成功的测试，并断言 SIGTERM/SIGKILL 序列与 failure state。`desktop/tests/preload.test.ts` 新增 production Runtime sink 的真实 `createRuntime` wiring 与 native secret 不外泄断言。测试脚本纳入 Webpack Main bundle 测试。

### 返工后精确验证

| 命令 | 结果 |
| --- | --- |
| `npm ci`（`desktop`） | 退出码 0；安装 733 packages |
| `npm ls electron @electron-forge/cli @electron-forge/plugin-webpack @electron-forge/maker-squirrel --depth=0`（`desktop`） | `electron@44.0.0`；三个 Forge 包均为 `7.11.2` |
| `npm run typecheck`（`desktop`） | 退出码 0 |
| `npm test`（`desktop`） | **16 passed, 0 failed**；包含实际 Webpack Main bundle 启动/窗口创建观测 |
| `npm run package`（`desktop`）首次执行 | 退出码 1；真实原因是 Forge 加载配置时 `webpack` CommonJS 包没有名为 `DefinePlugin` 的 ESM named export |
| 修正 `webpack.main.config.ts` 为 CJS-safe default import 后再次 `npm run package`（`desktop`） | 退出码 0；Forge 完成 win32/x64 packaged app smoke，证明 Main/Renderer bundle 可构建 |
| `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_desktop_protocol.py tests/test_desktop_bridge.py tests/test_architecture_boundaries.py -q` | **79 passed in 12.14s** |
| `git diff --check` | 退出码 0；无 whitespace error（仅有既有 LF/CRLF 提示） |
| `check_utf8_docs.py`（本 Feedback 与 Checklist，追加前/后） | 均为 `OK: 2 file(s) passed UTF-8 guard`；无 replacement character、常见乱码或不平衡 fenced code block |

本轮 package/npm 执行没有出现 `ECONNRESET`；不以未发生的网络错误替代上述失败原因或成功重跑证据。Forge `make`/Installer、PyInstaller、真实 Windows GUI/E2E 和生产捆绑 Runtime 仍未执行。

### Checklist 与清理状态

T03 Checklist 9/9 项继续保留 `[x]`，证据已覆盖新的 bundle 副作用、failed-child replacement gate、kill=false/no-close ownership 和 production sink；T04+ 未勾选，冻结 Checklist 文字/结构未改动。`desktop/.webpack`、`desktop/out` 和 `desktop/node_modules` 均为本轮验证产生的可再生成产物，已在最终检查后清理；源码、测试、配置和 lockfile 保留。

### 返工轮次 UTF-8 guard

- files checked: `docs/work/T10-DesktopGUI与TUI全量能力迁移/feedback/W03-electron-shell-process-feedback.md`、`docs/work/T10-DesktopGUI与TUI全量能力迁移/T10-DesktopGUI与TUI全量能力迁移-checklist.md`。
- result: 追加前、追加后均执行 `check_utf8_docs.py`，返回 `OK: 2 file(s) passed UTF-8 guard`；replacement character、常见 mojibake 和 Markdown fence 不平衡均为 0。
- repaired encoding issues: none。
