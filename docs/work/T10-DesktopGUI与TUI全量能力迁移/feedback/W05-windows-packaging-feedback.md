# W05 Windows Runtime 打包与 Installer 实施反馈

## 状态

W05 已开始实施；本文件为首次执行创建。以下只记录 T08 的 Windows Runtime Bundle 与 Installer 实施、验证和未验证边界，不执行 T09～T11 或任何 Git 写操作。

## 开工基线

- 基线为已合并 W04 的 `8b9bdb9`；已读取 W01～W04 Feedback、T10 冻结工作包、项目规则、当前 Desktop/Bridge tests、`pyproject.toml` 与 `src/uthcode/prompt_assets/`。
- 已查阅 PyInstaller stable onedir/spec/runtime-information、Electron Forge `extraResource`/Squirrel.Windows、Electron security/fuses 官方资料。
- 初始环境与红测结果将在实施完成后追加；未验证项不会写成通过。

## 初次实施结果

### 实际改动

- 新增 `desktop/packaging/uthcode-runtime.spec`：以 `Analysis` 入口构建 PyInstaller onedir，显式收集 `src/uthcode/prompt_assets/coding_agent.md` 到 `uthcode/prompt_assets`，使用 `COLLECT` 生成 `uthcode-runtime/_internal`，并保持 `console=True`。没有 `--noconsole`、`--windowed`、`--collect-all everything`、输入复制、路径敏感 Hash 或构建专用完整性链。
- 新增 `desktop/scripts/build-python-runtime.mjs`：固定通过 `conda run --no-capture-output -n re-uthcode` 调用 PyInstaller，构建前只清理脚本自有的 `desktop/.runtime` 与 `desktop/packaging/.build`，构建后检查 Runtime exe 和 `_internal`。
- `desktop/forge.config.ts` 使用 `packagerConfig.extraResource` 将整个 onedir 放入 ASAR 外的 `resources/uthcode-runtime`，接入官方 Squirrel.Windows maker（`UthCode Setup.exe`），并接入 Forge Fuses plugin：RunAsNode、Node Options 环境变量、Node CLI inspect 关闭，Embedded ASAR integrity 与 OnlyLoadAppFromAsar 开启。
- `desktop/package.json`/lock 增加 `build:runtime`、package/make 前置 Runtime 构建、Squirrel startup、Forge Squirrel/Fuses 依赖、Windows `productName`/`author`；根 `pyproject.toml` 增加真实 dev/build 依赖 `pyinstaller>=6.22,<7`。
- 为满足 PyInstaller 将入口作为脚本执行的实际行为，`src/uthcode/interfaces/desktop/__main__.py` 将 Bridge 导入改为绝对包导入；否则首个 onedir smoke 会得到 `attempted relative import with no known parent package`。这是 T08 运行闭环所需的最小入口修复，但 Tasks T08 的“修改文件”列表未列出该文件，属于本轮任务书与实施所需文件的边界不一致，交由用户审查。
- `desktop/src/main.ts` 在正常窗口/Runtime 注册前引入 `electron-squirrel-startup`，对 install/updated/uninstall/obsolete 特殊参数提前 `app.quit()`，并禁止 lifecycle launch 进入正常 bootstrap，避免启动 Python child。该文件同样未列在 Tasks T08 的修改文件列表，但属于 Tasks 文字明确要求的 Main 早期收口，交由用户审查；未扩展 T09～T11。

### 版本与平台

- Windows 11 x64（PyInstaller 输出：`Windows-11-10.0.26200-SP0`）。
- Conda `re-uthcode`：Python `3.12.13`；PyInstaller `6.22.2`，contrib hooks `2026.7`。
- Node `v24.15.0`、npm `11.13.0`；Electron `44.0.0`；Electron Forge CLI/Webpack/Squirrel maker/Fuses plugin `7.11.2`；`@electron/fuses` `1.8.0`；`electron-squirrel-startup` `1.0.1`。

### 精确命令与结果

以下命令均在本机执行，未进行 Git 写操作：

```text
conda run --no-capture-output -n re-uthcode python --version
-> Python 3.12.13

conda run --no-capture-output -n re-uthcode python -m PyInstaller --version
-> 6.22.2

npm ci                         (cwd: desktop)
-> exit 0
npm run typecheck              (cwd: desktop)
-> exit 0
npm test                       (cwd: desktop)
-> 55 passed, 0 failed

conda run --no-capture-output -n re-uthcode python -m PyInstaller --clean --noconfirm desktop/packaging/uthcode-runtime.spec
-> exit 0; dist/uthcode-runtime/uthcode-desktop-runtime.exe + _internal generated

npm run build:runtime          (cwd: desktop)
-> exit 0; desktop/.runtime/uthcode-runtime ready
npm run package -- --platform=win32 --arch=x64  (cwd: desktop)
-> exit 0; packaged app generated
npm run make -- --platform=win32 --arch=x64     (cwd: desktop)
-> exit 0; Squirrel artifacts generated
```

PyInstaller reported one non-fatal warning, `Hidden import "tzdata" not found!`; the Runtime initialize/status/shutdown smoke still completed with exit code 0. This warning remains a packaging risk to review rather than being claimed as resolved.

### Runtime、package 与 Installer 验收

- 直接 spawn `dist/uthcode-runtime/uthcode-desktop-runtime.exe`，通过 stdin 发送 `status.get` 与 `runtime.shutdown`：stdout 为 5 行合法 JSONL（ready、response、stopping、stopped、response），status/shutdown `ok=true`，退出码 `0`，stderr 长度 `0`；`dist/uthcode-runtime/_internal/uthcode/prompt_assets/coding_agent.md` 存在。
- 直接 spawn packaged path `desktop/out/UthCode-win32-x64/resources/uthcode-runtime/uthcode-desktop-runtime.exe`，发送相同请求：退出码 `0`、5 行合法 JSONL、两次 response `ok=true`、stderr 长度 `0`、prompt asset 存在。
- packaged Runtime 再以 `runtime.initialize(workdir="D:\\project\\Re-UthCode")`、`status.get`、`runtime.shutdown` 验证：退出码 `0`、6 行合法 JSONL、initialize/status/shutdown 均 `ok=true`、`application=true`、stderr 长度 `0`。该路径直接执行 resources 下的 bundled exe，未经过 system Python fallback。
- packaged tree 实际为 `resources/app.asar` 与 ASAR 外 `resources/uthcode-runtime/uthcode-desktop-runtime.exe`、`resources/uthcode-runtime/_internal/**`；prompt asset 位于 `_internal/uthcode/prompt_assets/coding_agent.md`。产物尺寸：packaged `UthCode.exe` 244,440,576 bytes，Runtime exe 12,731,696 bytes。
- package 产物：`desktop/out/UthCode-win32-x64`；make 产物：`desktop/out/make/squirrel.windows/x64/UthCode Setup.exe`（175,593,984 bytes）、`UthCode-0.1.0-full.nupkg`（174,913,071 bytes）、`RELEASES`（78 bytes）。
- 实际启动 packaged `UthCode.exe` 后观察到主进程及 GPU/utility/renderer 子进程；`CloseMainWindow()` 后主进程退出，随后 `UthCode.exe` 与 `uthcode-desktop-runtime.exe` 均无残留（leftover 0）。本机用户偏好没有选中项目，因此该 GUI smoke 没有启动 Runtime child；Runtime child 已由上述 packaged direct smoke 独立验证。
- 以 packaged app 运行 `--squirrel-obsolete`：退出码 `0`，`UthCode.exe` 与 Runtime child 残留为 `0`。install/updated/uninstall 三个分支已由 `electron-squirrel-startup` 入口代码静态检查，未实际触发快捷方式写入/删除，避免把开发目录当作真实安装目录。

### Squirrel、Fuses 与已有安全回归

`npx electron-fuses read --app out/UthCode-win32-x64/UthCode.exe` 退出码 `0`，实际输出为：RunAsNode Disabled、EnableNodeOptionsEnvironmentVariable Disabled、EnableNodeCliInspectArguments Disabled、EnableEmbeddedAsarIntegrityValidation Enabled、OnlyLoadAppFromAsar Enabled；同时输出 EnableCookieEncryption Disabled、LoadBrowserProcessSpecificV8Snapshot Disabled、GrantFileProtocolExtraPrivileges Enabled，以及 `undefined is Enabled`。最后一行表示当前 `@electron/fuses@1.8.0` CLI 对 Electron 44 的第 9 个 fuse 没有名称映射，本反馈保留该事实，不宣称所有 fuse 已无歧义。既有 production CSP、navigation/new-window、IPC sender/frame/origin、preload 边界由 `npm test` 的 55 个 Desktop tests 覆盖并通过。

### Checklist、未验证项与清理

- 本轮只更新 T08 Checklist 的复选框；T01～T07、T09～T11 文字和状态未改。
- 当前主机虽为 Windows 11 x64，但拥有 Conda/Python，且不是无系统 Python 的干净环境；未执行真实 Squirrel 安装、首配、对话、关闭、卸载闭环。因此“无系统 Python Windows 11 x64 安装 -> 启动 -> 首配 -> 对话 -> 关闭 -> 卸载”保持未勾选，不写成通过。
- Installer 未签名，仅用于 development/release-candidate 本机验收；未宣称公开发行或 SmartScreen 就绪。没有实施自动更新、Service、Tray、Daemon、签名平台或完整性链。
- 已清理可再生成产物：`build/`、`dist/`、`desktop/.runtime/`、`desktop/.webpack/`、`desktop/out/`、`desktop/node_modules/`、`desktop/packaging/.build/`；保留源码 spec、build script 和测试。清理前均使用与构建相同的明确路径做 dry-run，未删除业务源码/文档。

剩余 T08 Checklist 证据以 Checklist 文件中的勾选为准；以上未验证和 Fuses 未命名状态保留给后续人工审查/W06。

## 收尾核验补充

- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_desktop_bridge.py tests/test_desktop_protocol.py tests/test_system_prompt.py`：60 passed，0 failed。
- `git diff --check`：exit 0；没有执行 commit、push、branch、merge、rebase、tag 或归档。
- `python C:\\Users\\93445\\.codex\\skills\\uth-utf8-guard\\scripts\\check_utf8_docs.py docs/work/T10-DesktopGUI与TUI全量能力迁移/feedback/W05-windows-packaging-feedback.md docs/work/T10-DesktopGUI与TUI全量能力迁移/T10-DesktopGUI与TUI全量能力迁移-checklist.md`：`OK: 2 file(s) passed UTF-8 guard`。

## 返工第 1 轮：package/make 前置 Runtime 自动 smoke

### Reviewer finding 与最小修复

- Reviewer 的唯一 finding 是：首次 package/make 前虽然构建了 Runtime，但没有把真实 bundled exe 的自动 smoke 串入 Forge 前置链。本轮只补这一项，没有进入 T09～T11，也没有增加自动更新、服务、完整性链或其他产品协议。
- `desktop/scripts/build-python-runtime.mjs` 在 PyInstaller onedir 生成并检查 exe、`_internal` 后，使用 `spawn`（`shell:false`、三路 pipe、`windowsHide:true`）直接执行刚生成的 `uthcode-desktop-runtime.exe`。smoke 在临时 HOME/USERPROFILE 下写入最小 fake Provider 配置，依次发送 `runtime.initialize`、`session.new`、`status.get`、`runtime.shutdown`。
- smoke 要求 stdout 每一行均可 JSON 解析且非空，恰好一个 `runtime_state=ready`，response id 与四个 request 精确对应且无重复/未知 id，四个 response 均 `ok=true`，stderr 为空，进程在 15 秒界限内以 exit code `0` 结束。`status.get` 的 Application diagnostics context 必须为 `available` 并含 `stable_prefix_fingerprint`；`session.new` 触发当前 `ApplicationContextService` 通过 `importlib.resources` 读取 bundled `coding_agent.md`，因此不是只检查资源文件名。
- smoke 任一校验失败、进程异常/超时、JSONL 无效、stderr 污染或 exit 非零都会令 build script 非零；`package`、`make` 的 `npm run build:runtime && electron-forge ...` 因此在进入 Forge 前被阻止。临时 HOME 在成功和失败路径均清理。
- `desktop/tests/windows-packaging.test.ts` 新增真实集成测试，直接执行 `node scripts/build-python-runtime.mjs` 并断言实际 smoke 成功输出；不是只 regex 检查静态配置。该测试实际重新构建并 spawn onedir Runtime。

### 返工重跑命令与结果

以下命令均在 Windows 11 x64、本仓库 `desktop` cwd（Python 命令使用 `re-uthcode`）实际执行：

```text
npm ci
-> exit 0；重新安装 740 packages，只有依赖完整性/deprecation 类 warning，无下载、网络或权限阻断

npm run typecheck
-> exit 0

npm test
-> 56 passed，0 failed；包含真实 build-python-runtime smoke 集成测试

conda run --no-capture-output -n re-uthcode python -m pytest tests/test_desktop_bridge.py tests/test_desktop_protocol.py tests/test_system_prompt.py
-> 60 passed，0 failed

npm run build:runtime
-> exit 0；PyInstaller 6.22.2 生成 desktop/.runtime/uthcode-runtime，随后输出
   "Bundled Runtime smoke passed: ready/status/shutdown JSONL and importlib.resources prompt asset"

npm run package -- --platform=win32 --arch=x64
-> exit 0；smoke 先通过后 Forge package 完成

npm run make -- --platform=win32 --arch=x64
-> exit 0；smoke 先通过后 Forge/Squirrel make 完成
```

本轮 `npm ci` 及 package/make 触发的 Electron/Forge 依赖准备均允许外部依赖下载并实际完成；没有遇到网络 reset、依赖下载失败、Windows 路径、Squirrel 或安装权限阻断。Node `v24.15.0` 下集成测试使用 `process.execPath` 直接调用 build script；命令行 `npm run` 的 build/package/make 均正常。

### 返工后的 packaged path smoke 与产物

- 直接 spawn `desktop/out/UthCode-win32-x64/resources/uthcode-runtime/uthcode-desktop-runtime.exe`，发送 `runtime.initialize`、`session.new`、`status.get`、`runtime.shutdown`：stdout `7` 行、恰好 `1` 个 ready、四个 response 全部 `ok=true`、stderr `0` bytes、exit code `0`；status diagnostics context 为 `available` 且有 fingerprint，确认 `resources/uthcode-runtime/_internal/uthcode/prompt_assets/coding_agent.md` 可经 `importlib.resources` 读取。该路径没有 system Python fallback。
- 实际启动 `out/UthCode-win32-x64/UthCode.exe` 后调用 `CloseMainWindow()`：先观察到未退出，再正常退出，exit code `0`，`UthCode.exe` 与 `uthcode-desktop-runtime.exe` leftover `0`。
- 实际运行 packaged `UthCode.exe --squirrel-obsolete`：exit code `0`，两个进程 leftover `0`。
- 返工后产物尺寸：`UthCode.exe` `244,440,576` bytes；Runtime exe `12,731,696` bytes；`coding_agent.md` `1,029` bytes；`desktop/out/make/squirrel.windows/x64/UthCode Setup.exe` `175,595,008` bytes；`UthCode-0.1.0-full.nupkg` `174,913,440` bytes；`RELEASES` `78` bytes。

### Fuses、warning、清理与未验证项

- 返工后再次执行 `npx electron-fuses read --app out/UthCode-win32-x64/UthCode.exe`：exit `0`；RunAsNode、NodeOptions 环境变量、Node CLI inspect 均 Disabled，Embedded ASAR integrity 与 OnlyLoadAppFromAsar Enabled；CLI 仍显示 `undefined is Enabled`。这不是新增 fuse 配置：`@electron/fuses@1.8.0` 对 Electron `44.0.0` 当前第 9 个 fuse 没有名称映射，本反馈保留该第 9 位的实际状态，不宣称名称已解析。
- PyInstaller 仍报告非致命 `Hidden import "tzdata" not found!` warning；上述真实 Runtime smoke、package、make 均成功，warning 保留为后续兼容性风险。
- 本轮 build/package/make 后已按精确路径清理可再生成内容：`desktop/node_modules`、`desktop/.runtime`、`desktop/.webpack`、`desktop/out`、`desktop/packaging/.build`、`desktop/.tmp-fuse-electron.exe`；保留 `desktop/packaging/uthcode-runtime.spec`、`desktop/scripts/build-python-runtime.mjs`、测试与 Feedback。清理前用相同明确路径 dry-run，未删除业务源码/文档。
- 当前机器具备 Conda/Python，不是无 system Python 的干净 Windows 环境；真实 Squirrel install/update/uninstall 快捷方式闭环及“安装 -> 首配 -> 对话 -> 关闭 -> 卸载”仍未验证，T08 Checklist 第 87 项继续不勾选。未执行任何 Git commit、push、branch、merge、rebase、tag 或归档。
- 返工后 `git diff --check`：exit `0`；UTF-8 guard 需在本节写入后重新执行并以其结果为准。

## 返工第 2 轮：smoke failure 与 Forge `&&` 门禁

### P2 修复与直接失败证据

- 针对 Reviewer 余下的唯一 P2，本轮只在 build script/test 内加入私有测试注入：设置 `UTHCODE_TEST_SMOKE_ONLY=1` 与临时 `UTHCODE_TEST_SMOKE_FIXTURE` 时，`build-python-runtime.mjs` 跳过构建步骤，仅把同一个 smoke validator 指向测试 fixture；该分支不进入产品协议，生产默认环境仍构建并真实 spawn `desktop/.runtime/uthcode-runtime/uthcode-desktop-runtime.exe`。
- 测试 fixture 是临时生成的 `.mjs` Runtime 替代进程，真实消费 stdin、输出一个 ready JSON 后再输出 `not-json`，最后以 code `0` 结束。smoke 因 JSONL parse 失败抛出 `Runtime smoke stdout contained invalid JSONL`，命令返回非零；因此不是 PyInstaller/Conda 早期失败，也不是静态 regex。
- 测试随后执行 package 的同一前缀 `npm run build:runtime && node "<Forge sentinel>"`，其中 sentinel 只是 Forge 的替代命令：若 `&&` 后半段被执行便创建 sentinel 文件。fixture smoke 返回非零，整条链返回非零且 sentinel 文件不存在，直接证明 Forge 后半段未执行。

### 本轮实际命令与结果

```text
npx tsx --test --test-name-pattern "smoke failure" tests/windows-packaging.test.ts
-> 1 passed，0 failed；直接断言 malformed fixture 的 smoke 命令非零及 Forge sentinel 未创建

npm ci                         (cwd: desktop)
-> exit 0；added 740 packages；仅 git dependency integrity/deprecation warning

npm run typecheck              (cwd: desktop)
-> exit 0

npm test                       (cwd: desktop)
-> 57 passed，0 failed；包含成功路径真实 bundled Runtime smoke 与本轮 failure/sentinel 测试

npm run build:runtime          (cwd: desktop)
-> exit 0；PyInstaller 6.22.2 onedir 构建完成，ready/status/shutdown JSONL、stderr、exit code 与 prompt asset smoke 全部通过

conda run --no-capture-output -n re-uthcode python -m pytest tests/test_desktop_bridge.py tests/test_desktop_protocol.py tests/test_system_prompt.py
-> 60 passed，0 failed

git diff --check
-> exit 0
```

本轮没有重复耗时的 package/make 产物构建；上一轮的真实 package/make exit `0` 及产物证据保留在上节，本轮用 package 同一 `npm run build:runtime &&` 前缀配 Forge sentinel 专门验证 failure gate。

### 清理与边界

- 已按精确路径 dry-run 后清理本轮生成的 `desktop/node_modules`、`desktop/.runtime`、`desktop/.webpack`、`desktop/out`、`desktop/packaging/.build`、`desktop/.tmp-fuse-electron.exe`；fixture 测试目录使用 `finally` 清理，未保留临时 fixture。保留 spec、build script、测试和 Feedback 源文件。
- 本轮 `uth-utf8-guard` 在本节写入后实际执行：`OK: 2 file(s) passed UTF-8 guard`。没有执行 Git commit、push、branch、merge、rebase、tag 或归档；T09～T11 未实施。
