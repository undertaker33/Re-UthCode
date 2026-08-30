# W06 Desktop 全链路验收与交付反馈

## 状态

W06 已开始实施。本反馈记录 T09→T10→T11 的实际验证、文档收口和未验证边界；当前仍未完成 T10 的干净 Windows Installer 与人工 Feature Parity 验收，因此不将 T10 标记为 `implemented_unarchived`，不执行归档或任何 Git 写操作。

## 开工基线

- 工作区为 `D:\project\Re-UthCode`，分支为 `codex/T10-DesktopGUI与TUI全量能力迁移`，开工 `HEAD` 为 W05 合并提交 `86d3c80`；开工时工作树干净。
- 已完整读取 `AGENTS.md`、`docs/README.md`、`docs/Context-Index.md`、`docs/rules/WorkPackageRules.md`、`docs/rules/UserDecisionBoundary.md`、`docs/OutstandingDebtList.md`、T10 原始需求/Spec/Tasks/Checklist/W06 Prompt、W01～W05 Feedback、A02/A03/A04/TUI 当前上下文、用户手册、根 README，以及 T01～T08 当前生产代码、测试和构建配置。
- 环境为 Windows 11 x64：PyInstaller 输出 `Windows-11-10.0.26200-SP0`；`re-uthcode` 为 Python 3.12.13、PyInstaller 6.22.2；Node `v24.15.0`、npm `11.13.0`；Electron `44.0.0`；Electron Forge/Fuses/Squirrel 相关包为 `7.11.2`。

## T09 真实离线主链

### 实际改动

- 修改 `desktop/tests/runtime-process.test.ts`，增加一条真实离线 Desktop Runtime 集成测试。测试使用正式 `PythonRuntime` 子进程和临时用户配置，以现有 `fake` Provider 作为离线 Provider 输入，不在 Renderer 伪造状态。
- 测试依次请求 `runtime.initialize`、`project.open`、`session.new`、`turn.start`，校验同一 Run/Turn identity 的 `AgentEvent` 顺序、`turn_completed`、assistant 完成消息、Session safe replay，并通过 `runtime.shutdown` 验证 child close/reap。没有新增生产架构、第二 authority 或未来入口。

### 精确命令与结果

```text
npm ci  (cwd: desktop)
-> exit 0；added 740 packages；仅有 git dependency integrity/deprecation warnings

npm run typecheck  (cwd: desktop)
-> exit 0

npx tsx --test --test-name-pattern="offline Desktop Runtime" tests/runtime-process.test.ts  (cwd: desktop)
-> 1 passed，0 failed；真实 Python Runtime -> Bridge -> Application -> Core -> AgentEvent -> replay/shutdown

npm test  (cwd: desktop)
-> 58 passed，0 failed；包含新增真实离线主链测试、Renderer/Preload/Main/Runtime/packaging tests

conda run --no-capture-output -n re-uthcode python -m pytest tests/test_tui.py tests/test_cli.py tests/test_application_runs.py tests/test_agent_events.py tests/test_agent_interaction.py tests/test_architecture_boundaries.py -q
-> 273 passed，0 failed

conda run --no-capture-output -n re-uthcode python -m pytest tests/test_w06_integration_delivery.py tests/test_tui.py tests/test_cli.py tests/test_application_runs.py tests/test_agent_events.py tests/test_agent_interaction.py tests/test_architecture_boundaries.py -q
-> 285 passed，0 failed

conda run --no-capture-output -n re-uthcode uthcode --help
-> exit 0；正式 `uthcode` 入口仍为交互式 TUI 入口

conda run --no-capture-output -n re-uthcode uthcode exec --help
-> exit 0；正式 `uthcode exec` 入口仍为非交互 Headless 入口
```

正式入口的 TUI/Application 组合与 `exec` 事件流还由 `tests/test_cli.py`、`tests/test_tui.py` 的定向测试覆盖；本轮未改变 TUI、Headless 或 Core 产品语义。

### 静态收口结果

- `rg -n "alert\(|prompt\(|confirm\(|fake|mock session|demo" desktop/src` 仅命中 `SettingsView.tsx` 的当前 Provider schema 默认值与 `fake` Provider 选项（第 56、117 行）；这是可配置的真实离线 Provider，不是 fake session、demo 数据或原型按钮。未命中 `alert`、`prompt`、`confirm`、`mock session`、`demo`。
- `rg -n "DesktopAgentEvent|DesktopSession|DesktopPermission|DesktopPlan|DesktopTask|DesktopFailure|EventBus|RpcManager|RuntimeManager|TransportFactory|PluginHost|DeviceProtocol" src desktop tests` 未发现生产重复 authority/未来占位。
- `rg -n "Card(Grid)?|DashboardCard|SettingCard|ToolCard|工程参考|设计说明|GUI 化|演示|三栏|这里用于|该区域" desktop/src/renderer` 无命中。
- `rg -n "Subagent|Multi-Agent|Worktree|Git Diff|MCP|Skill|Auto Update|Tray|Windows Service|FastAPI|WebSocket|Named Pipe|gRPC" src/uthcode desktop/src` 无 T10 未来入口/协议占位；唯一系统层相关命中为 `process_tools.py` 的 Windows console code-page API 名称，不是未来能力入口。

## T10 Windows Feature Parity 与失败路径

### Runtime、package、make 和 packaged smoke

```text
conda run --no-capture-output -n re-uthcode python -m PyInstaller --clean --noconfirm desktop/packaging/uthcode-runtime.spec
-> exit 0；生成 `dist/uthcode-runtime/uthcode-desktop-runtime.exe` 与 `_internal`；prompt asset 存在

npm run build:runtime  (cwd: desktop)
-> exit 0；真实 onedir Runtime smoke 的 ready/status/shutdown JSONL、stderr、退出码和 prompt asset 检查通过

npm run package -- --platform=win32 --arch=x64  (cwd: desktop)
-> exit 0；Forge package 完成，生成 `desktop/out/UthCode-win32-x64`

npm run make -- --platform=win32 --arch=x64  (cwd: desktop)
-> exit 0；Squirrel make 完成，生成 `desktop/out/make/squirrel.windows/x64/UthCode Setup.exe`
```

直接 spawn packaged path `desktop/out/UthCode-win32-x64/resources/uthcode-runtime/uthcode-desktop-runtime.exe`，用临时 fake Provider 配置发送 `runtime.initialize`、`project.open`、`session.new`、`turn.start`、`runtime.shutdown`：13 行合法 JSONL，恰好 1 个 `runtime_state=ready`，五个 response（含 shutdown）均 `ok=true`，包含 `turn_completed`，stderr 0 bytes，exit code 0；`resources/uthcode-runtime/_internal/uthcode/prompt_assets/coding_agent.md` 存在。该 smoke 直接执行 bundled Runtime，没有 system Python fallback。

### 失败路径与人工边界

- Bridge/Python/Renderer 自动测试已覆盖 invalid IPC、配置 required/error、Runtime malformed output/exit、Session busy/corrupt/unknown、project/session 原子切换、active Turn command gate、pending interaction 不旁路、typed AskUser/Permission/Plan/Retry/Pause cancel 和 shutdown close/reap；这些结果保留在本轮 `npm test`、Python 定向测试与既有 W01～W05 Feedback 中。
- 当前机器虽然是 Windows 11 x64，但有系统 Python/Conda，且不是“无系统 Python”的干净机器。没有真实执行 Squirrel 安装目录中的安装→首配→打开项目→新 Session→对话/Tool→AskUser/Permission/Plan/Todo→Steering/Pause/Resume→Settings/Layout→退出/重启→旧 Session→卸载闭环。
- 没有进行 Windows Terminal 人工输入法、中文/粘贴/Shift+Enter、焦点与键盘、两主题、窄窗口、Runtime Panel 三形态、真实 Tool/AskUser/Permission/Plan/Todo 可视化验收。上述 T10 Feature Parity 与人工清单项保持未勾选，不能以自动测试或 packaged Runtime smoke 替代。
- PyInstaller 仍报告非致命 `Hidden import "tzdata" not found!` warning；当前 Runtime/package/make/smoke 均成功，但该 warning 是后续兼容性风险，未宣称已解决。
- Installer 未签名，仅可作为 development/release-candidate 验收，未宣称公开发行或 SmartScreen 就绪。

## T11 全量回归、文档与清理

### 已执行/待收口命令

```text
conda run --no-capture-output -n re-uthcode python -m pytest -q
-> 待最终收口重跑并把精确 passed/failed/skipped 写入本节

conda run --no-capture-output -n re-uthcode python -m compileall -q src tests
-> 待最终收口执行

conda run --no-capture-output -n re-uthcode python -m pip check
-> 待最终收口执行

git diff --check
-> 待文档/Checklist/Feedback 写入后最终执行
```

### 文档、欠账与 Git 边界

- 本轮将同步根 `README.md`、`docs/user-manual/getting-started.md`、`docs/user-manual/configuration.md`、`docs/user-manual/commands.md`、A04 编排当前事实、TUI 共存事实和 `docs/Context-Index.md`；不修改冻结的 T10 原始需求、Spec、Tasks、Prompt 文字。
- 已核对 `docs/OutstandingDebtList.md`：T10 能力欠账仍为无；既有 Persistent Runtime Recovery 等欠账不属于本包实施范围，清单不改。
- 本包不执行 `commit`、`push`、`merge`、`rebase`、`tag`、`release` 或自动归档；只保留源码、测试、当前事实文档、Checklist 与本 Feedback。
- `desktop/node_modules`、`desktop/.runtime`、`desktop/.webpack`、`desktop/out`、`desktop/packaging/.build`、仓库根 `build`/`dist` 均为构建/测试可再生成物，最终收口时仅按这些明确路径 dry-run 后清理，不删除业务源码、文档或未知文件。

## Checklist 证据状态

- T09 的真实离线主链、静态重复 authority/原型/未来入口检查、Python 定向回归和正式入口回归已有本反馈精确证据，可在最终复核后勾选对应项。
- T10 的完整 Windows Feature Parity、Installer 干净机和人工 UI 项无真实证据，保持未勾选。
- T11 的全量 pytest、compileall、pip check、diff check、最终 Desktop 重跑、文档 UTF-8 guard、清理和 Checklist 更新须在本反馈追加收口记录后再判断；在全部 Checklist 未满足前不更新 Context Index 为 `implemented_unarchived`。

## 收口第 1 轮（2026-08-30）

### 最终全量回归与静态收口

```text
conda run --no-capture-output -n re-uthcode python -m pytest -q
-> exit 0；1380 passed，3 skipped，0 failed；178.11s（2:58）

conda run --no-capture-output -n re-uthcode python -m compileall -q src tests
-> exit 0；无输出

conda run --no-capture-output -n re-uthcode python -m pip check
-> exit 0；No broken requirements found.

git diff --check
-> exit 0；仅报告现有工作树文件的 LF -> CRLF autocrlf warning，无 whitespace error
```

此前全量首次运行出现 1 个既有 TUI picker 偶发失败（`1379 passed，3 skipped，1 failed`）；随后单例重跑、W06 文件级重跑和本次全量重跑均通过，未修改该 TUI 逻辑。

### Packaged Electron 边界

- 已尝试从 `desktop/out/UthCode-win32-x64/UthCode.exe` 启动真实 Electron 并通过 CDP 驱动 Renderer；在等待窗口调试目标的超时内得到 `CDP target did not appear; stdout= stderr=`，最终确认没有残留 `UthCode` 或 `uthcode-desktop-runtime` 进程。该项按真实环境未验证处理，不把失败尝试写成通过。
- packaged Runtime 的直接 spawn smoke 仍是通过证据：13 行合法 JSONL、ready 1 次、initialize/open/new/turn/shutdown response 全部正常、`turn_completed` 出现、stderr 0 bytes、exit code 0、prompt asset 存在。

### 任务书第 33 节逐项记录

- 安装：Squirrel `make` 产物已生成；未在无系统 Python 的干净 Windows 11 x64 机执行安装/卸载，因此安装后首配与卸载项未验证。
- Project：绝对路径校验、已登记 Explorer 边界、项目切换与项目持久化逻辑有自动测试；真实 native folder picker、别名和磁盘/Session 人工操作未验证。
- Session：new/resume、fresh Run、safe replay、busy/corrupt/unknown 与关闭回收有自动测试和 packaged Runtime smoke；真实 packaged UI 三个 Session 连续点击未验证。
- Chat：Renderer Timeline、Markdown、stream/complete/failure、composer gate 有自动测试；真实窗口焦点、中文输入、粘贴、Shift+Enter 和窄窗口未验证。
- Interaction：Permission/Retry/Pause 的 typed 映射及 gate/cancel 有自动测试；真实 AskUser 多题/选择/Other、Plan revision/review 的窗口验收未验证。
- Settings：配置 DTO、Provider/Model 校验、secret 脱敏与偏好白名单有 Python/Renderer 测试；无配置首配、API key 输入清空、主题可读性和 active save 的真实 UI 未验证。
- Layout：Renderer 对 floating/docked/hidden/runtime panel 状态有测试；system/dark/light、窄窗口和焦点/键盘路径人工未验证。
- Exit：Runtime shutdown、child close/reap、Squirrel lifecycle early path 有自动测试；真实 Installer 安装后退出/重启/卸载闭环未验证。

### 文档、欠账、清理与最终 Checklist 状态

- 已同步根 README、getting-started、configuration、commands、A04 编排当前事实、TUI 共存边界与 Context Index；A02/A03 未命中需更新的当前事实项。`docs/OutstandingDebtList.md` 已核对并保持不变，T10 能力欠账仍为无。
- `uth-utf8-guard` 对本反馈、Checklist、Context Index、OutstandingDebt、根 README、用户手册、A04 和 TUI 文档共 10 个 Markdown 文件执行通过：`OK: 10 file(s) passed UTF-8 guard`；均可解码、无 replacement character/常见乱码，fenced code block 成对。
- 通过 `git clean -nd -- desktop/node_modules desktop/.runtime desktop/.webpack desktop/out desktop/packaging/.build build dist` 核对后，执行同一明确路径的 `git clean -fd -- ...`，只移除本轮生成的依赖、Runtime、Webpack、package/make、PyInstaller build/dist 产物；未清理 `.pytest_cache`、`.uthcode` 或未知路径。
- 已勾选的 Checklist 仅限静态收口、Python 回归、自动化 gate/failure/session 证据、文档/清理和无 Git/归档动作；真实 Electron Renderer、干净无系统 Python Installer、完整 Windows Feature Parity、AskUser/Plan/UI 人工项、Installer E2E 和“全部 Checklist 后标 implemented_unarchived”继续未勾选。
- Context Index 的 T10 状态保持 `not_implemented`，没有因本轮部分证据而改成 `implemented_unarchived`。本包未执行 commit、push、merge、rebase、tag、release 或归档。

## 收口第 2 轮（2026-08-30）

- 首轮 `git clean -fd -- ...` 后发现 ignored 父目录仍保留，已对同一明确路径补执行 `git clean -fdX -- desktop/node_modules desktop/.runtime desktop/.webpack desktop/out desktop/packaging/.build build dist`；最终七个路径均 `ABSENT`，未清理 `.pytest_cache`、`.uthcode` 或未知路径。
- 最终进程复核 `Get-Process UthCode,uthcode-desktop-runtime -ErrorAction SilentlyContinue` 无匹配输出；没有遗留 Electron 或 packaged Runtime child。
- 追加 Feedback/Checklist 后再次执行同一 10 文件 `uth-utf8-guard`：`OK: 10 file(s) passed UTF-8 guard`。最终 `git diff --check` exit 0，仅有 LF -> CRLF autocrlf warning，无 whitespace error。
- 最终工作树仅保留本轮源码测试、当前事实文档、Checklist 与 W06 Feedback 改动；无 commit、push、merge、rebase、tag、release 或归档。因干净无系统 Python Installer、真实 Electron Renderer/人工 Feature Parity 与完整 Installer E2E 缺失，T10 仍未完成，Context Index 保持 `not_implemented`。

## Reviewer 返工第 1 轮（2026-08-30）

### Reviewer finding 与 Provider rename 修复

- Reviewer P2-1：上一轮没有把已配置非 fake Provider 的 ID rename 作为显式写请求处理，存在未输入新 key 时丢失原 key 表达的风险。本轮增加当前 schema 明确的 `provider_renames` mapping，未增加未知字段 passthrough、兼容层或第二 authority。
- `SettingsView` 在 Provider ID 失焦提交 rename 时合并 mapping，并同步当前 Model Profile 的 Provider ID；连续 rename 会收敛为原始 source 到最终 destination 的单一 mapping。`configurationRequest` 只复制 Provider/Model 非秘密字段和 rename ID。
- Application `UserConfigurationWriteRequest` 对 mapping 做类型、非空和 source/destination 区分校验；`DesktopBridge settings.save` 只接受现有请求字段加该显式 mapping。Provider/Model 配置引用仍由 Application 与 writer 校验。
- Config writer 在内存 TOML candidate 上先检查 source 存在、destination 不冲突且 destination 唯一，再移动原 Provider table，保留原 `api_key` literal 或 `env:VARIABLE_NAME` 表达，并更新已有 Model 的 `provider` 引用；随后沿现有 validate -> 一次原子替换路径写入。冲突、缺失 source、空 ID 和其他无效 mapping 在替换前失败，原文件 bytes 不变。
- safe configuration view、`UserConfigurationWriteRequest.to_dict()`、`repr`、Bridge response 和 Renderer DOM 不含 key 明文；replacement key 只在用户本次提交时进入 writer，保存完成后 transient input 清空。

### Provider rename 精确回归证据

```text
conda run --no-capture-output -n re-uthcode python -m pytest tests/test_configuration.py tests/test_desktop_bridge.py -q
-> 104 passed，0 failed，4.50s

npx tsx --test tests/renderer.test.tsx  (cwd: desktop)
-> 36 passed，0 failed；rename mapping、连续 rename、Model 引用和 safe request 覆盖

真实 GUI request -> Application -> writer（tests/test_desktop_bridge.py）
-> literal/no replacement、env/no replacement、literal replacement 三种写入；Provider table 与 Model 引用迁移；conflict/invalid request 均拒绝且 bytes 不变
```

在真实 Desktop Settings 中以临时 user config 做了同样链路：先将已配置 Provider 从 `offline` 改为 `remote`，不输入 replacement，文件仍保留原 key expression 且 Model 指向 `remote`；再次输入 replacement 后文件只保存 replacement。两次设置页面、body、safe response 和保存后的 transient password input 均未回显秘密。该临时配置仅用于验收，最终会随临时目录清理。

### Reviewer finding 与固定端口 CDP

- Reviewer P2-2：上一轮 packaged target 未出现不能归因环境。本轮改用固定端口和可靠目标发现：通过 `/json/list` 读取 `type=page` 的 `webSocketDebuggerUrl`，不依赖随机 target 等待。
- dev 命令（cwd=`D:\project\Re-UthCode\desktop`）为：

```text
conda run --no-capture-output -n re-uthcode npx electron-forge start --enable-logging -- --remote-debugging-port=9229 --disable-gpu
```

使用临时 `HOME/USERPROFILE/APPDATA/LOCALAPPDATA` 和 fake Provider 离线配置，等待 Forge main compile、Webpack renderer/dev server、`DevTools listening on ws://127.0.0.1:9229` 和 `/json/list` page target 后才执行 DOM/CDP 操作。真实 Renderer URL 为 `http://localhost:3000/main_window/index.html`；首次缺少 Conda Runtime 环境的尝试被终止，随后以明确 `re-uthcode` 命令和临时配置重启成功。通过 `/quit`/`closeShell` 收口，Electron 与 Python child 均不存在；PTY 输出含 React/Electron console 日志，无 Runtime parser 污染。
- packaged 命令使用 `desktop/out/UthCode-win32-x64/UthCode.exe`，固定 `--remote-debugging-port=9233 --disable-gpu`、显式临时 `--user-data-dir`、`--enable-logging` 和 `--log-file=<temp>\electron.log`，以 `Start-Process -PassThru -Wait` 等待；`/json/list` target 为 `file:///D:/project/Re-UthCode/desktop/out/UthCode-win32-x64/resources/app.asar/.webpack/renderer/main_window/index.html`。bundled Runtime ready 后通过真实 Renderer 新建 Session、发送离线消息并得到 `fake response`，`closeShell` 后 `PACKAGED_EXIT=0`，日志仅有既有 GPU overlay warning，无 orphan child。

### CDP/DOM 实际覆盖与明确缺口

dev Renderer 通过真实 Preload/Main/Bridge/Application 链路完成：

- 临时项目打开、Session catalog、三个已有 Session 的切换/安全 replay/继续输入（`first live turn`、`second live turn`、`third live turn`），New Session 后空 Timeline 与 `(no user message)`；
- 正常 live fake response、bad-key 的真实 `Turn failed: authentication`，`/status` command result、`/compact` 的受控 `repeated_failure` notice、model picker 选择、permission `auto` 选择、DEFAULT/PLAN 切换；
- active Turn 的 steering：UI 显示 `Pause`/`Cancel`/`Steer`，实际收到 `Steering requested`、`Steering applied`，随后 provider failure；Pause/Cancel 控件也实际 dispatch，但该 provider fixture 最终以 authentication failure 收口，未将其写成成功 cancel terminal；
- Settings 已配置 key 的 replacement/no-echo/rebootstrap，active Turn 时 `Save settings` 实际 disabled；Theme `dark` 与 Runtime Panel `floating`/`hidden`/`docked` 对应真实 `app-shell`/panel class；`/quit` 后 child close/reap；
- packaged Renderer 在 `app.asar` file URL 下完成 Runtime initialize、New Session、真实 offline turn 和 clean exit。

当前 fixture 与主机边界不能真实触发的项目保持未勾选：AskUser 多题 text/single-select/multi-select/Other/review/同 Turn 再请求；动态 Permission request（含无 Session choice）；Plan approve/revise/cancel；Provider Retry interaction；真实 streaming/tool Agent event；无系统 Python 的干净 Installer 首配/对话/卸载；人工 IME、中文粘贴、Shift+Enter、窄窗口、焦点/键盘与颜色可读性。相应 typed response、dynamic choices、stream/tool reducer、gate/cancel 语义由 Renderer/Python 组件及定向测试覆盖，但没有冒充真实 CDP E2E。未执行 GitHub 请求，因此没有把 GitHub 443 与 CDP target 混为同一网络失败。

### 返工第 1 轮命令结果

```text
npm run typecheck  (cwd: desktop)
-> exit 0

npx tsx --test tests/renderer.test.tsx  (cwd: desktop)
-> 36 passed，0 failed

npx tsx --test tests/runtime-process.test.ts  (cwd: desktop)
-> 11 passed，0 failed

conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q
-> 23 passed，0 failed

npm test  (cwd: desktop)
-> 58 passed，0 failed

npm run build:runtime  (cwd: desktop)
-> exit 0；PyInstaller 6.22.2 / Python 3.12.13 / Windows-11-10.0.26200-SP0；Bundled Runtime ready/status/shutdown smoke passed；既有 warning：Hidden import "tzdata" not found!

npm run package  (cwd: desktop)
-> exit 0；Forge packaged `desktop/out/UthCode-win32-x64`

npm run make  (cwd: desktop)
-> exit 0；Squirrel artifact 位于 `desktop/out/make`

conda run --no-capture-output -n re-uthcode python -m compileall -q src tests
-> exit 0；无输出

conda run --no-capture-output -n re-uthcode python -m pip check
-> exit 0；No broken requirements found.
```

Python 全量第二次重跑仍有同一顺序相关 TUI picker 异步失败，不能记为通过：

```text
conda run --no-capture-output -n re-uthcode python -m pytest -q
-> exit 1；1387 passed，3 skipped，1 failed；178.14s
-> failed: tests/test_w06_integration_delivery.py::test_tui_session_picker_open_close_does_not_create_session

conda run --no-capture-output -n re-uthcode python -m pytest tests/test_w06_integration_delivery.py::test_tui_session_picker_open_close_does_not_create_session -q
-> 1 passed，0 failed，1.64s

conda run --no-capture-output -n re-uthcode python -m pytest tests/test_w06_integration_delivery.py -q
-> 12 passed，0 failed

conda run --no-capture-output -n re-uthcode python -m pytest tests/test_configuration.py tests/test_desktop_bridge.py tests/test_w06_integration_delivery.py -q
-> 116 passed，0 failed

conda run --no-capture-output -n re-uthcode python -m pytest --ignore=tests/test_w06_integration_delivery.py -q
-> 1376 passed，3 skipped，0 failed
```

该 failure 在单例、W06 文件级及相关配置/Bridge 组合中均通过，表现为全量顺序/异步泄漏型既有不稳定；本轮没有未经授权改动无关 TUI 逻辑。Checklist 的命令执行与精确结果记录项已勾选，但全量 clean run 这一 DoD 仍未满足。

### 文档、Checklist、清理与状态

- `docs/user-manual/configuration.md` 已补充 Provider rename 的 literal/env 保留、replacement 和原子失败边界；其余根 README、用户手册、A04/TUI 当前事实与 Context Index 延续前轮同步。
- `docs/OutstandingDebtList.md` 已核对，T10 能力欠账仍为无；没有把普通 Out of Scope 或本轮全量 flaky failure 记为能力欠账。
- 已重新执行 `uth-utf8-guard`（当前 9 个实际修改/相关 Markdown）：`OK: 9 file(s) passed UTF-8 guard`；无 replacement/常见 mojibake，fenced blocks 成对。
- 本轮不执行 `commit`、`push`、`merge`、`rebase`、`tag`、`release` 或归档。构建物、依赖和临时 CDP user-data 仅在最终安全边界按明确路径/目录清理；不删除业务源码、文档、`.pytest_cache`、`.uthcode` 或未知文件。
- 当前 DoD 仍未满足：真实无系统 Python Installer/人工 Feature Parity、AskUser/Plan/Retry/stream/tool CDP E2E 以及全量 pytest clean run 缺失；Context Index 必须继续保持 `not_implemented`，不得改为 `implemented_unarchived`。

## Reviewer 返工第 2 轮（2026-08-30）

### P2 Provider rename：来源身份与三层写入闭环

- 修复来源语义：`SettingsView` 为已有 Provider 保存 `providerOriginalIds`，新建 draft 不产生 rename mapping；已有 `A -> X` 再改回 `A` 会删除 mapping；同一请求的 `A -> X, B -> A` 允许目标先由 source `A` 释放，仍拒绝目标被非 source 占用、source 缺失、空 ID、重复目标等无效请求。
- Renderer `configurationRequest` 在发送前移除 renderer-only 的 source metadata；Bridge 只接收明确的 `provider_renames`；Application 做 mapping 形状/引用校验；writer 在内存 TOML candidate 上验证并一次原子替换。失败时不改文件，Model `provider` 引用与 `default_model` 在同一 candidate 中同步迁移。
- literal 与 `env:VARIABLE_NAME` 都在无新 key 时保留原始表达；提供新 key 时只替换为本次输入；safe view、request DTO、Bridge response、错误、日志和 Renderer DOM 不回显秘密。

精确回归结果：

```text
conda run --no-capture-output -n re-uthcode pytest -q tests/test_configuration.py -k provider_rename tests/test_desktop_bridge.py -k rename
-> 10 passed, 96 deselected, 0 failed, 0.67s

conda run --no-capture-output -n re-uthcode python -m pytest tests/test_configuration.py tests/test_desktop_bridge.py -q
-> 104 passed, 0 failed, 4.50s

npx tsx --test tests/renderer.test.tsx  (cwd=desktop)
-> 36 passed, 0 failed；覆盖 source metadata、new draft、A->X->A、A->X/B->A、literal/env/no-key、new-key、Model/default 与 secret stripping

真实 GUI-shaped request -> Bridge -> Application -> writer
-> tests/test_desktop_bridge.py 覆盖 literal/env/no-key、replacement、Model/default 引用迁移、conflict/invalid 原子拒绝且 bytes 不变
```

### P2 TUI picker flaky：完整 traceback、生命周期修复与压力证据

此前首个完整失败日志保存在 `C:\Users\93445\AppData\Local\Temp\uthcode-w06-tui-picker-round2-isolated-714049a1991446bb9dd8a3e76b5283ee.log`，具体为：

```text
tests/test_w06_integration_delivery.py::test_tui_session_picker_open_close_does_not_create_session
tests/test_w06_integration_delivery.py:630: await wait_until(lambda: not tui.session_picker.open)
tests/test_w06_integration_delivery.py:622: raise AssertionError("condition did not become true")
E AssertionError: condition did not become true
```

traceback 的失败断言是 Picker close 条件未变为真；测试尚未走到 TUI shutdown 断言，故不是 shutdown 失败。修复为在测试 fixture 的 `pipe.attach` 生命周期真正完成后再发送 Kitty Escape `\x1b[27u`，并等待 `tui.ui.is_running and input_attached.is_set()`；没有通过盲目增加 sleep 或跳过测试解决。当前源码位置为 `tests/test_w06_integration_delivery.py:611-617`（attach signal）、`:638-644`（同步与 Escape）。

```text
20 次隔离 picker 压力（日志：C:\Users\93445\AppData\Local\Temp\uthcode-w06-tui-picker-round2-attached-46a6803fd6564346b338246e2676a436.log）
-> 20/20 passed，ISOLATED_FAILURES=0；每次约 1.04-1.12s

conda run --no-capture-output -n re-uthcode python -m pytest -q --tb=long  （第一轮）
-> exit 0；1390 passed，3 skipped，0 failed；173.70s（2:53）

conda run --no-capture-output -n re-uthcode python -m pytest -q --tb=long  （第二轮）
-> exit 0；1390 passed，3 skipped，0 failed；176.63s（2:56）
```

两轮完整输出分别保存在 `C:\Users\93445\AppData\Local\Temp\uthcode-w06-full-pytest-round2-python-1.log` 和 `C:\Users\93445\AppData\Local\Temp\uthcode-w06-full-pytest-round2-python-2.log`。此前误用环境外 `pytest.exe` 的收集错误另存为 `uthcode-w06-full-pytest-round2-1.log`，仅因 `all-in-rag` 的 executable 未将仓库 `eval/` 置于该环境导入路径，不计为项目规范入口结果。

### 固定端口 CDP driver 与真实 Renderer 证据

新增持久测试资产：

- `desktop/scripts/cdp-driver.mjs`：Node 20+ 内建 WebSocket，固定端口 `/json/list` target discovery，记录完整 Electron/target/CDP request/action/assertion/failure/exit；selectors 和每个 flow 的有界等待均在文件中。
- `desktop/scripts/cdp-openai-fixture.mjs`：本地 OpenAI-compatible Chat Completions HTTP/SSE fixture，`stream`、`tool`、`ask`、`permission`、`plan`、`retry`（前 3 次 HTTP 504）、`delay` 场景，日志只记录请求 metadata，不记录 key。
- 静态语法：`node --check scripts/cdp-driver.mjs; node --check scripts/cdp-openai-fixture.mjs`（cwd=`desktop`）-> exit 0。

每轮都先以如下固定端口命令启动 dev Main、真实 Webpack Renderer 和 Runtime，再等待 `DevTools listening on ws://127.0.0.1:<port>` 与 `/json/list` page target；driver 默认超时 45s，sessions 为 60s，超时即落盘 failure selector 并退出，不无限等待：

```text
conda run --no-capture-output -n re-uthcode npx electron-forge start --enable-logging -- --remote-debugging-port=<fixed-port> --disable-gpu
```

以下为 exit 0 的 driver 日志（均在 `C:\Users\93445\AppData\Local\Temp`，日志末尾为 `driver_complete exitCode=0`）：

```text
9229  uthcode-w06-cdp-dev-driver-round2-fixed-20260830.jsonl
9231  uthcode-w06-cdp-tool-driver-round2.jsonl
9232  uthcode-w06-cdp-ask-driver-round2.jsonl
9233  uthcode-w06-cdp-permission-driver-round2.jsonl
9234  uthcode-w06-cdp-plan-driver-round2-final.jsonl
9236  uthcode-w06-cdp-retry-driver-round2-504.jsonl
9237  uthcode-w06-cdp-delay-driver-round2.jsonl
9240  uthcode-w06-cdp-sessions-driver-round2-3-rerun3.jsonl
9241  uthcode-w06-cdp-delay-cancel-driver-round2.jsonl
9242  uthcode-w06-cdp-packaged-driver-round2.jsonl
```

真实 dev Renderer 覆盖证据：

- basic：真实 Shell/Composer、New blank、fixture streamed response、Settings、dark、Runtime Panel floating/hidden、回到 Chat、status、secret absence、`closeShell`；
- tool：Provider -> Core -> Application -> Bridge -> Renderer 的 ReadFile tool call/result，必要时 dynamic Permission；fixture 日志第二请求含 assistant/tool；
- AskUser：三题 single-select Other、text、多选 README/tests/Other、Review、Submit、同一 Turn continuation；日志中的 `AskUser questions/choice/text/multi-select/review/same-turn continuation` assertions 全部通过；
- Permission：真实动态 Permission surface、Allow once 和 continuation；
- Plan：点击 DEFAULT -> PLAN，真实 Plan review、Approve and execute、tool/result；
- retry：fixture 前 3 次 HTTP 504，Renderer 出现 Provider retry，点击 Retry 后输出；driver `uthcode-w06-cdp-retry-driver-round2-504.jsonl`，fixture `uthcode-w06-cdp-fixture-retry-round2-504.log`；
- delay：真实 Pause -> Turn paused -> Continue -> output，以及独立 Cancel -> cancelled；
- sessions：连续创建三 Session，分别提交消息，按可见 label 选择第二 Session 与第一条请求进行 safe replay，再继续输入；首次按索引实现的失败日志保留，修复为等待当前 Timeline/精确 label 后，`...sessions-driver-round2-3-rerun3.jsonl` exit 0；
- 每个成功 flow 都通过真实 DOM selector/action/assertion，并验证 Renderer body 不含 fixture secret；未用协议注入或 SSR 静态文字代替交互。

真实 packaged Renderer 证据：

```text
npm run package -- --platform=win32 --arch=x64  (cwd=desktop)
-> exit 0；desktop/out/UthCode-win32-x64/UthCode.exe，resources/app.asar + resources/uthcode-runtime/uthcode-desktop-runtime.exe/_internal

启动：desktop/out/UthCode-win32-x64/UthCode.exe --enable-logging --remote-debugging-port=9242 --disable-gpu
target：file:///D:/project/Re-UthCode/desktop/out/UthCode-win32-x64/resources/app.asar/.webpack/renderer/main_window/index.html
driver：uthcode-w06-cdp-packaged-driver-round2.jsonl -> exit 0；真实 file:// Renderer 新 Session、fixture response、Settings/theme/panel/status/secret absence/closeShell 均通过；退出后 UthCode 与 uthcode-desktop-runtime 子进程均不存在。
```

fixture 是测试侧的真实 OpenAI-compatible HTTP/SSE 服务，未新增生产协议注入；当前主机可触发的 streaming/tool/AskUser/dynamic Permission/Plan/retry/delay/session/Settings/theme/layout/quit 均已用 DOM assertion 覆盖。仍不能将 fixture 当作真实外部 Agent typed events 或公开 Provider：没有真实远端凭据/网络 Agent 事件验证；steer 没有在该 fixture 中单独形成独立成功 terminal，Pause/Continue 与 Cancel 已分别验证。人工 IME、中文粘贴、Shift+Enter、窄窗口、焦点/颜色可读性，以及无系统 Python 干净 Windows 11 安装首配/对话/卸载仍未验证；这些项保持 Checklist 未勾选。

### Package/make、静态检查与文档收口

本轮执行结果：

```text
npm ci                         -> exit 0；added 740 packages in 11s
npm run typecheck              -> exit 0
npm test                       -> exit 0；58 passed，0 failed/skip
conda run ... python -m compileall -q src tests
                               -> exit 0；无输出
conda run ... python -m pip check
                               -> exit 0；No broken requirements found.
conda run ... python -m pytest tests/test_architecture_boundaries.py -q
                               -> 23 passed，0 failed，5.35s
conda run ... python -m PyInstaller --clean --noconfirm desktop/packaging/uthcode-runtime.spec
                               -> exit 0；PyInstaller 6.22.2 / Python 3.12.13 / Windows 11 x64；仅有 Hidden import "tzdata" not found warning
node scripts/build-python-runtime.mjs
                               -> exit 0；Bundled Runtime ready/status/shutdown JSONL smoke、prompt asset 通过
npm run package -- --platform=win32 --arch=x64
                               -> exit 0；package 产物与 bundled Runtime smoke 通过
```

同一 cwd/参数的 `npm run make -- --platform=win32 --arch=x64` 未通过：Forge 在 Copying files、Preparing native dependencies、Finalizing package、Packaging for x64 on win32 阶段均报 `RequestError: connect ETIMEDOUT 20.205.243.166:443`，exit 1；没有把旧/部分 `desktop/out/make` 产物写成当前通过证据。该外部 443 阻断与 CDP fixed-port target 连接不同；CDP dev/packaged target 均已连接并完成 driver。因 make 失败，Squirrel Installer 的干净机安装/首配/对话/卸载仍未勾选。

静态清理检查（排除明确生成目录 `desktop/node_modules`, `.runtime`, `.webpack`, `out`, `packaging/.build`）结果：重复 authority 与 UI card/设计说明两组均 0 条；未来能力组仅 1 条 `src/uthcode/integrations/tools/process_tools.py:2012`，是现有 Windows API 字符串 `GetOEMCP` 被正则中的 `MCP` 子串误报，不是未来入口。`git diff --check` exit 0，仅 LF -> CRLF autocrlf warning，无 whitespace error。

本轮确认并延续同步根 README、用户手册、A04/TUI 当前事实和 Context Index；`docs/OutstandingDebtList.md` 核对后 T10 能力欠账仍为无。新增/修改 Markdown 执行 `uth-utf8-guard`：`OK: 10 file(s) passed UTF-8 guard`，无 replacement character/常见乱码，fence 成对。Context Index 的 T10 仍保持 `not_implemented`，因为无系统 Python Installer/人工 Feature Parity 与 make/完整安装闭环缺真实证据；没有擅自标记 `implemented_unarchived`。

构建清理：仅按 dry-run 后的明确可再生成路径清理 `desktop/node_modules`、`.runtime`、`.webpack`、`out`、`packaging/.build`、仓库根 `build`/`dist`；保留 `desktop/scripts/cdp-driver.mjs`、`cdp-openai-fixture.mjs`、源码、测试、文档、Checklist、Feedback。最终进程复核无 UthCode 或 `uthcode-desktop-runtime` 残留；无 Git commit/push/merge/rebase/tag/release/归档。

另：返工准备 fixture 时曾误以 PowerShell 内建只读变量 `$home` 作为临时 HOME，并覆盖当前用户 `C:\Users\93445\.uthcode\config.toml` 为本地 fixture 配置；原文件内容没有在覆盖前留存，当前无法声称已恢复。该工作区外部用户配置风险已向调度者报告，后续不得把该 fixture 配置视作用户原配置或交付证据。

### 返工第 2 轮追加：CDP 长等待诊断与收口

收到“长时间 CDP 卡住”反馈后即时盘点进程与监听端口：没有 `electron.exe`、`UthCode.exe` 或 `uthcode-desktop-runtime.exe`；仅发现两个本轮 fixture：PID 3868，命令 `node desktop/scripts/cdp-openai-fixture.mjs --port 18766 --scenario stream`；PID 10992，命令 `node scripts/cdp-openai-fixture.mjs --port 18776 --scenario stream`。其启动 wrapper PID 35584/28860 的命令行同样只指向上述 fixture。已按命令行确认停止 3868、10992，wrapper 随之退出；18766/18776 监听已释放。Codex 自身的长期 `cua_node ./server` 进程未触碰。

历史长等待不是无界运行，而是 driver 的有界 selector 失败，完整日志仍保留：

```text
uthcode-w06-cdp-dev-driver-round2.jsonl
-> 30s，Provider output fixture response，last=false（初次错误临时配置/Runtime 未初始化）
uthcode-w06-cdp-plan-driver-round2-fixed.jsonl
-> 45s，Plan review，selector [aria-label="Plan review"] 未出现
uthcode-w06-cdp-plan-driver-round2-retry.jsonl
-> 45s，同一 Plan review selector 未出现
uthcode-w06-cdp-retry-driver-round2.jsonl
-> 45s，Provider retry surface or output，selector [aria-label="Provider retry"] 未出现（HTTP 503 被 SDK 内部重试吸收）
uthcode-w06-cdp-sessions-driver-round2.jsonl
-> 60s，first session replay，旧索引选择逻辑未得到 Timeline 文本
uthcode-w06-cdp-sessions-driver-round2-3.jsonl
-> 60s，second composer ready，旧全局 composer predicate 未满足
```

修正后另有两次即时 selector/action 失败（均落盘并结束，不是卡住）：`...sessions-driver-round2-3-rerun.jsonl` 为 `second session row not found`，`...sessions-driver-round2-3-rerun2.jsonl` 为 `button text not found: Send`。最终改为等待当前 Timeline 的精确可见 label、发送按钮 enabled 和 Session row 文本后，`...sessions-driver-round2-3-rerun3.jsonl` exit 0。

`cdp-driver.mjs` 现同时对 `/json/list` fetch、WebSocket open、每个 CDP request 设置默认 5s `requestTimeoutMs`，所有 flow 仍受 `timeoutMs` 总预算约束；`Runtime.consoleAPICalled` 与 `Runtime.exceptionThrown` 以不带参数值/秘密的摘要写入日志。无 target 自测：

```text
node scripts/cdp-driver.mjs --port 29999 --timeout-ms 1000 --request-timeout-ms 200 --log C:\Users\93445\AppData\Local\Temp\uthcode-w06-cdp-target-timeout-round2.jsonl
-> 1.1s 内 exit 1；driver_failure: CDP target did not appear on fixed port 29999: fetch failed；无残留进程
node --check scripts/cdp-driver.mjs
node --check scripts/cdp-openai-fixture.mjs
-> 均 exit 0
```

因此当前没有等待中的 interaction/selector；可复现成功 flow 的 driver 日志、失败 flow 的具体 selector/action 与外部启动日志均已保存，后续场景应独立启动、独立超时、独立 finally 收口。

### 用户配置覆盖事故与恢复（2026-08-30）

本轮安全复核确认：前一轮准备 fixture 时误用了 PowerShell 内建只读变量 `$home` 作为临时 HOME，导致真实用户配置 `C:\Users\93445\.uthcode\config.toml` 被本地 fixture 配置覆盖。覆盖前没有备份，原文件内容不可恢复；本 Feedback 不声称恢复了原内容，也不把 fixture 配置当作用户原配置或交付证据。

用户已明确授权由调度者重建该配置；调度者已将 `C:\Users\93445\.uthcode\config.toml` 重建为空白安全配置，仅保留 `default_permission_mode = "default"`，不含 Provider、Model 或 Key。TOML 解析和 safe view 已由调度者验证。本 Worker 后续没有读取、输出或重新写入该真实配置内容。

为阻止同类事故，新增 `desktop/scripts/cdp-test-guard.mjs`；driver/fixture 在任何日志写出、server listen 或 CDP 请求前执行 guard：

- 解析后的 `HOME`、`USERPROFILE`、`APPDATA`、`LOCALAPPDATA` 以及 `UTHCODE_CONFIG_PATH` 若指向真实用户 profile、真实 config，或 profile 下非系统临时目录的路径，立即拒绝；没有显式隔离 HOME 时 `homedir()` 回退到真实 profile，也会拒绝。
- `--log` 与 fixture `--ready-file` 也作为输出路径检查，只允许仓库工作区或系统临时目录，避免拒绝分支或启动前日志写入真实 config。
- 测试状态只允许位于仓库工作区或系统临时目录；Python `tests/conftest.py` 为每个测试建立唯一临时 HOME，W06 测试和 Desktop runtime 测试另外对 project/user/config 路径做硬断言。
- `desktop/tests/cdp-isolation.test.ts` 只用唯一临时 HOME 启动 fixture/driver 做正常隔离验证；guard 拒绝真实 profile 和真实 config 的场景均在真实文件 I/O 之前结束。真实配置回归只读取 size/mtime 指纹，前后不变断言不读取、不打印配置内容或 secret。
- 已停止并清理本 Worker 启动的 fixture/构建进程；当前没有继续运行会触碰真实 HOME 的 CDP。未再执行真实用户 HOME 下的 Electron/fixture flow。

安全收口验证证据：

```text
conda run --no-capture-output -n re-uthcode python -m pytest -q --tb=long
-> 1391 passed, 3 skipped in 184.03s

conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_w06_integration_delivery.py
-> 13 passed in 5.29s

npx tsx --test tests/cdp-isolation.test.ts tests/runtime-process.test.ts  (cwd=desktop)
-> 14 passed, 0 failed, 9143.0283ms；追加覆盖 `--log` 指向真实 config 时 fixture/driver 均在写入前拒绝

npm test  (cwd=desktop)
-> 61 passed, 0 failed, 0 skipped, 79648.8669ms

node --check scripts/cdp-test-guard.mjs
node --check scripts/cdp-driver.mjs
node --check scripts/cdp-openai-fixture.mjs  (cwd=desktop)
-> 全部 exit 0
```

路径审计覆盖 `tests/conftest.py`、`tests/test_w06_integration_delivery.py`、`desktop/tests/cdp-isolation.test.ts`、`desktop/tests/runtime-process.test.ts`、`desktop/scripts/cdp-test-guard.mjs`、`desktop/scripts/cdp-driver.mjs` 和 `desktop/scripts/cdp-openai-fixture.mjs`；未发现测试或 fixture 将 HOME/config 指向真实用户目录的未保护写路径。所有子进程与临时目录均在 `finally` 中收口，生成的 `node_modules`、runtime、webpack、package/build 目录按明确路径 dry-run 后清理。此安全事故及其恢复边界不改变 Checklist 的未验证项，Context Index 继续保持 `not_implemented`。

### 返工第 3 轮追加：安全 launcher、纯词法隔离与 global deadline（2026-08-30）

按最终 Reviewer 四项只做窄范围返工，未启动产品 Electron、未执行产品 CDP flow、未执行 pytest 全量：

1. `desktop/tests/cdp-isolation.test.ts` 不再对真实 config 做 `stat`、fingerprint、`existsSync`、`resolve` 或其他文件 I/O；`C:\Users\93445\.uthcode\config.toml` 与 profile 只作为字符串传给拒绝用例。所有 I/O 顺序与“不写入”证明改用系统临时目录中的 `temporary-sentinel.txt`。`tests/conftest.py` 的比较改为 `ntpath.abspath` + `normpath` + `normcase` 纯词法 Windows 语义，不调用 `resolve`/`expanduser`；每个测试的 HOME、USERPROFILE、APPDATA、LOCALAPPDATA、HOMEDRIVE、HOMEPATH 和 UTHCODE_CONFIG_PATH 均指向临时状态。
2. 新增 `desktop/scripts/cdp-launcher.mjs`。launcher 先创建唯一系统临时 root，再校验并设置六个 Windows 用户状态变量及临时 config；workspace 不允许作为 HOME，`--log`、`--ready-file`、`--log-file`、`--user-data-dir` 输出参数也必须落在同一 root。任何 preflight 失败都在 spawn、fixture server、Electron 或日志写入前清理 root、无 stdout/stderr、无被启动的命令进程。`cdp-isolation` 的正常 fixture、driver、环境变量、真实 profile/config 字符串拒绝和真实 config 输出路径拒绝均通过 launcher 执行；Feedback 与两个 CDP 脚本中的可执行启动示例均改为 launcher，不再提供手工启动 Electron 的示例。
3. `cdp-driver.mjs` 以一次 `flowDeadline` 贯穿 target discovery、WebSocket open、CDP request、selector wait 和 DOM action/evaluate；每一步只使用 remaining budget，request timeout 取 remaining 与单请求上限的较小值。新增“target discovery 无法完成时共享总时限”隔离测试，证明不会按 selector 重置总时限。
4. `docs/Context-Index.md` 的 T10 当前事实已校正为 package 与固定端口 CDP/离线链路有通过证据；最终 make/Installer 因 `20.205.243.166:443 ETIMEDOUT` 未完成，Checklist 第 84、116 项未勾，状态仍为 `not_implemented`。未修改旧轮历史记录，只在本节追加更正。

本轮命令与结果：

```text
npm ci  (cwd=desktop)
-> exit 0；added 740 packages in 15s

npx tsx --test tests/cdp-isolation.test.ts  (cwd=desktop)
-> 3 passed，0 failed，3679.8814ms

npm run typecheck  (cwd=desktop)
-> exit 0

node --check scripts/cdp-launcher.mjs
node --check scripts/cdp-test-guard.mjs
node --check scripts/cdp-driver.mjs
node --check scripts/cdp-openai-fixture.mjs  (cwd=desktop)
-> 全部 exit 0
```

本轮未重跑 Python 全量、Desktop 全量测试、package/make 或任何产品 Electron/CDP flow；只验证安全隔离与 driver 时限。验证后按 dry-run 使用明确路径清理 `desktop/node_modules`、`.runtime`、`.webpack`、`out`、`packaging/.build`、仓库根 `build`/`dist`；未修改、提交或归档 Git。最终 `uth-utf8-guard` 为 `OK: 9 file(s) passed UTF-8 guard`，`git diff --check` exit 0（仅 autocrlf warning）；上述生成目录均不存在，`git clean -ndX`/`git clean -nd` 均为 0，W06 UthCode/CDP/fixture/build 进程为 none。

### 返工第4轮：历史证据恢复与未来复现规则（2026-08-30）

Reviewer 指出旧轮历史证据被后来新增的 launcher 回写。本轮仅恢复历史真实性，没有删除或改写旧轮的其他事实：198、201-202、341、377、418 和 442 行现分别记录当时实际执行的直接命令/事实。旧轮没有 `cdp-launcher.mjs`：dev 使用 `conda run --no-capture-output -n re-uthcode npx electron-forge start --enable-logging -- --remote-debugging-port=9229 --disable-gpu`（以及 `<fixed-port>` 变体），packaged 直接启动 `desktop/out/UthCode-win32-x64/UthCode.exe --enable-logging --remote-debugging-port=9242 --disable-gpu`，fixture 直接使用 `node desktop/scripts/cdp-openai-fixture.mjs --port 18766 --scenario stream` 与 `node scripts/cdp-openai-fixture.mjs --port 18776 --scenario stream`，无 target 自测直接使用 `node scripts/cdp-driver.mjs --port 29999 --timeout-ms 1000 --request-timeout-ms 200 --log C:\Users\93445\AppData\Local\Temp\uthcode-w06-cdp-target-timeout-round2.jsonl`。这些 raw 命令与当时的进程收口事实不能以后来的 launcher 视角重述。

旧轮还确实发生过 PowerShell `$home` 误用导致真实用户配置被 fixture 覆盖；覆盖前没有备份。用户授权、由调度者把 `C:\Users\93445\.uthcode\config.toml` 重建为空白安全配置（仅 `default_permission_mode = "default"`）不等于恢复原内容，本 Feedback 不声称原配置已恢复，也不把重建文件作为旧证据。

从返工第3轮起，未来所有 CDP、fixture 和 Electron 复现必须先经 `desktop/scripts/cdp-launcher.mjs`：由 launcher 创建并校验唯一系统临时 root，统一隔离用户环境、状态、日志和输出，再在有界 deadline 内启动目标；不得再提供或执行绕过 launcher 的新复现命令。该未来规则不回写旧轮，旧轮 raw 记录保持上述实际事实。

### 返工第 5 轮追加：Forge 离线校验与打包复验（2026-08-30）

本轮根据 Reviewer 的缓存校验 finding 做最小修复：`desktop/forge.config.ts` 通过 `createRequire(import.meta.url)` 加载本地 `electron/checksums.json`，并将其设置为 `packagerConfig.download.checksums`。未设置 `unsafelyDisableChecksums`，未复制 ZIP，也未引入绝对路径。当前本地缓存 `C:\Users\93445\AppData\Local\electron\Cache\16cfa46effad3eaba32b3370f8ae31cae8ea2624490eaa5f736d489be8e9c6c4\electron-v44.0.0-win32-x64.zip` 大小为 157455369 bytes，SHA256 为 `e61aa3bcea8152bc0730abd015e47c032d778a0ef10e2a1c78ba3c4ea47942f9`，与已安装包的对应 checksum 一致。`desktop/tests/windows-packaging.test.ts` 新增真实配置回归，比较上述 artifact checksum。

本轮所有外部启动均经 `desktop/scripts/cdp-launcher.mjs`，用户配置仍由临时 HOME/USERPROFILE/APPDATA/LOCALAPPDATA 隔离；Forge cache 通过 `ELECTRON_FORGE_PACKAGER_CONFIG_DOWNLOAD_CACHE_ROOT` 显式指向已存在的 Electron cache，只读使用，不访问 `C:\Users\93445\.uthcode\config.toml`。package/make 不是 CDP/fixture/Electron 应用复现，均使用本地 ZIP 和内置 checksums 完成，没有重试 GitHub。

本轮命令与精确结果：

```text
node scripts/cdp-launcher.mjs -- conda run --no-capture-output -n re-uthcode npm run typecheck  (cwd=desktop)
-> exit 0

node scripts/cdp-launcher.mjs -- conda run --no-capture-output -n re-uthcode npx tsx --test --test-name-pattern='Forge packaging uses' tests/windows-packaging.test.ts  (cwd=desktop)
-> 1 passed, 0 failed

node scripts/cdp-launcher.mjs -- conda run --no-capture-output -n re-uthcode npx tsx --test tests/windows-packaging.test.ts  (cwd=desktop)
-> 4 passed, 0 failed, 56277.4541ms

node scripts/cdp-launcher.mjs --env ELECTRON_FORGE_PACKAGER_CONFIG_DOWNLOAD_CACHE_ROOT=C:\Users\93445\AppData\Local\electron\Cache -- conda run --no-capture-output -n re-uthcode npm run package  (cwd=desktop)
-> exit 0；PyInstaller onedir + Runtime smoke、Forge packaged app 均成功

node scripts/cdp-launcher.mjs --env ELECTRON_FORGE_PACKAGER_CONFIG_DOWNLOAD_CACHE_ROOT=C:\Users\93445\AppData\Local\electron\Cache -- conda run --no-capture-output -n re-uthcode npm run make  (cwd=desktop)
-> exit 0；Squirrel distributable 成功，`desktop/out/make/squirrel.windows/x64/UthCode Setup.exe` 已生成

node scripts/cdp-launcher.mjs -- conda run --no-capture-output -n re-uthcode npm test  (cwd=desktop)
-> 63 passed, 0 failed, 0 skipped, 56322.5626ms
```

Checklist 仅将第 84 项复选框由未完成改为完成；其原有括号中的旧轮外部网络失败说明保留为历史记录。第 87、116、119 项以及 Windows 干净机、Installer 首配/对话/卸载、完整真实 Feature Parity 和人工 UI 清单仍未完成，未将其写成通过。`docs/Context-Index.md` 当前事实同步为 package/make 与完整 Desktop 自动化测试已有证据，但 T10 仍保持 `not_implemented`。

### 返工第 6 轮追加：Electron 隔离模式、shell driver 与 packaged 启动复核（2026-08-30）

本轮处理 Reviewer 的 packaged `UthCode.exe` `0x80000003` finding。最小对照先在唯一系统临时目录复制同一 packaged 目录，均通过当时的全 profile 隔离 launcher 启动：原 Fuse 产物、仅关闭 `EnableEmbeddedAsarIntegrityValidation` 的副本、仅关闭 `OnlyLoadAppFromAsar` 的副本、替换为 pristine Electron 44 的副本，以及有/无 `--disable-gpu` 的最终产物均立即 exit 1；stderr 只有 Chromium allocator verbose 行。该对照排除了 Fuse 单项、`@electron/fuses` 的 Electron 44 wire 第 9 项、rcedit/Forge 最终 EXE 和 GPU 作为根因。此前 Windows Application Error 1000 的同一故障记录为 `UthCode.exe` exception `0x80000003`、offset `0x31f2805`（Report ID `d377047e-f5b9-4e89-ba90-b4cbe9858e39`；后续对照同 offset），但对照均使用错误隔离模式，不能归因于产品 EXE。

根因是旧 launcher 将 Windows Electron 启动所需的 `HOME`、`USERPROFILE`、`APPDATA`、`LOCALAPPDATA`、`HOMEDRIVE`、`HOMEPATH` 全部重写为临时目录。`desktop/scripts/cdp-launcher.mjs` 现增加明确 `--electron` 模式：保留上述六个 Windows profile identity 值，只将 `UTHCODE_CONFIG_PATH` 指向 launcher 创建的唯一临时 root 内路径，并强制追加同一 root 内唯一 `--user-data-dir`；调用者覆盖 profile、真实配置或自带 user-data-dir 均在 spawn 前静默拒绝。默认模式仍对 fixture、driver、Python helper 全量隔离六个 profile 变量；日志、ready-file、log-file 和 user-data-dir 输出继续必须在临时 root 内。该模式不读取或写入 `C:\Users\93445\.uthcode\config.toml`。

本轮用新模式对新 packaged 产物完成真实 Renderer/CDP smoke：

```text
node scripts/cdp-launcher.mjs --electron -- out/UthCode-win32-x64/UthCode.exe --remote-debugging-port=9250 --disable-gpu --enable-logging=stderr
-> Electron 在固定端口启动并保持运行；target 为
   file:///D:/project/Re-UthCode/desktop/out/UthCode-win32-x64/resources/app.asar/.webpack/renderer/main_window/index.html

node scripts/cdp-launcher.mjs -- node scripts/cdp-driver.mjs --port 9250 --flow shell --timeout-ms 30000 --request-timeout-ms 5000
-> exit 0；Project navigation、Composer、Renderer ready
   (readyState=complete,title=UthCode,bodyReady=true)、window.uthcode.closeShell 通过；
   Electron launcher 随后 exit 0，无残留 UthCode/runtime 进程。
```

为防止 shell smoke 回退到 Provider 流程，`desktop/scripts/cdp-driver.mjs` 增加最小 `flow=shell` 分支：完成 shell/Composer 断言后记录 Renderer ready、请求 close、记录 `driver_complete` 并直接返回。`desktop/tests/cdp-isolation.test.ts` 增加固定 target 缺失时的 shell-mode bounded regression；shell mode 与两种 launcher 模式/逃逸拒绝共 6 项通过。

本轮验证结果：

```text
npx tsx --test tests/cdp-isolation.test.ts
-> 6 passed，0 failed，0 skipped

npm run typecheck
-> exit 0

npm test
-> 66 passed，0 failed，0 skipped

package/make
-> 本轮 checksum 修复后的 package、make 已均 exit 0；新 packaged app 与
   desktop/out/make/squirrel.windows/x64/UthCode Setup.exe 已生成（本轮不重复执行）。
```

P2：Checklist 第 84 项括号已改为当前 package/make exit 0 与 Setup.exe 已生成；旧轮 `20.205.243.166:443` ETIMEDOUT 只保留在本 Feedback 历史记录。P3：`windows-packaging.test.ts` 从已安装 `electron/package.json` 的版本动态组装 win32-x64 artifact，断言 checksums mapping 一致且值为 64 位十六进制，不再硬编码 v44 或固定摘要。Checklist 第 87、116、119 项以及 Windows 干净机 Installer、首配/对话/卸载、完整真实 Feature Parity 和人工 UI 清单仍未完成；Context Index 继续保持 T10 `not_implemented`，不得更新为 `implemented_unarchived`。

本轮 governed Markdown 写回前后均执行 `uth-utf8-guard`，只修改当前 Checklist 第 84 项并在 Feedback 末尾追加本节；未覆盖旧轮历史记录。无 Git commit/push/merge/rebase/tag/release/归档。

### 返工第 7 轮追加：Windows 环境变量大小写保护（2026-08-30）

Reviewer 发现 Windows 环境变量名大小写不敏感，而 launcher 的 protected-env 判断曾大小写敏感；`--electron --env home=...` 与 `--env uthcode_config_path=...` 因此可能绕过 preflight。现已在 `desktop/scripts/cdp-launcher.mjs` 对 env key 使用大写规范化：Electron 模式和默认 isolated 模式均拒绝六个 Windows profile key 及 `UTHCODE_CONFIG_PATH` 的任意大小写形式；同一请求内的 case-variant duplicate key 也在创建临时 root、spawn、日志或 server 之前拒绝。默认 isolated 模式的完整 profile 隔离行为保持不变，Electron 模式仍保留 Windows profile identity 并只使用临时 config/user-data-dir。

`desktop/tests/cdp-isolation.test.ts` 新增 lower/mixed-case profile/config 逃逸及默认模式重复 key 用例；每个拒绝断言均确认 child 未 spawn 且 stdout/stderr 为空。未读取或写入真实用户配置，未执行 Git 写操作。

本轮精确验证：

```text
node --check scripts/cdp-launcher.mjs
-> exit 0

npx tsx --test tests/cdp-isolation.test.ts
-> 7 passed，0 failed，0 skipped

npm run typecheck
-> exit 0

npm test（此前同一修复后的完整回归）
-> 67 passed，0 failed，0 skipped
```

`uth-utf8-guard` 与 `git diff --check` 在本轮 Feedback 追加后复跑并通过；Context Index 仍保持 T10 `not_implemented`。Checklist 第 87、116、119 项、干净 Windows/Installer、首配/对话/卸载、完整真实 Feature Parity 与人工 UI 仍未验证。
