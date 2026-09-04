# W05 Layout、Focus 与 Visual Feedback

## 交付范围

本轮严格按 T05 实施，未改写冻结的 Spec、Tasks 或 Prompt，未执行 Git 写操作，也未触碰 `.workbuddy/` 与 `临时目录/`。生产代码与测试改动仅限本 Worker 授权的 Desktop preference、renderer layout/state、RuntimePanel、CSS、locale、visual fixture、CDP driver 文件，另新增本 Feedback。

实现保留现有设计 token、字体和层级，仅补齐布局交互与必要的状态视觉；未引入依赖、UI/state/animation framework、第二 layout store 或 skeleton。

## 实现事实

### Width preference 生命周期与边界

- `sidebarWidth` 与 `runtimePanelWidth` 进入 Desktop preference schema，默认值分别为 `286` 与 `318`，合法整数在 `180..420` 与 `260..520` 内；旧文档缺少字段时迁移到默认值，越界值 clamp，非安全整数/小数回退到默认文档。
- Renderer hydrate、reducer 与 CSS custom properties 共用同一宽度投影。每次 viewport resize、panel mode 变化或 100%/125%/150% zoom 的 CSS-pixel 变化只做 presentation clamp，不回写 preference；docked 布局动态保留至少 `240px` Conversation。
- Pointer move 只更新 Renderer 预览状态；pointer release 和每次 keyboard Home/End/箭头操作在稳定边界各写一次 preference。separator 使用 `role="separator"`、vertical `aria-valuemin/max/now`、本地化 `aria-label` 与 `aria-controls="workspace-main"`。
- 宽屏保留双侧 separator；`<=680px` 隐藏 resize hit area，Runtime 延续现有 overlay/escape/outside-click/focus restore 语义。

### Focus Mode

`focusMode` 只存在 Renderer transient state。进入时隐藏 Sidebar 与 Runtime，不调用 `writePreference`，也不改变 durable `panelMode` 或宽度；Escape/按钮退出后恢复进入前的 panel mode、两个宽度并把 focus 交还入口按钮。

### Runtime 双 usage 与视觉层级

RuntimePanel 仍只消费 Application status DTO，不重算 Context/usage；现在按 Runtime status、Environment、Identity 分组，并独立呈现 Current Context 与 Last Provider Request Usage。两者各自带 available/unavailable 状态，输入、输出、总量和 cache read/write 使用本地化数值文案；技术标识使用 monospace token。

## 验证证据

- `conda run --no-capture-output -n re-uthcode npm --prefix desktop run typecheck`：exit code `0`。
- `conda run --no-capture-output -n re-uthcode npm --prefix desktop test`：`178` passed，`0` failed，`0` skipped，exit code `0`。包含 preference migration/clamp、layout helper/reducer、Pointer/keyboard stable write、Focus restore/no-write、RuntimePanel 双 usage、narrow drawer、locale 与既有 keyboard/IME/ARIA/focus regression。
- `conda run --no-capture-output -n re-uthcode npm --prefix desktop run package` 的 Runtime build 与 smoke 通过，但 Forge 复用旧 `desktop/out/UthCode-win32-x64/resources/app.asar` 时两次遇到 Windows `EBUSY`；确认无 UthCode/electron 进程后，使用同一 Forge API 输出到同样被 `desktop/out/` 忽略的 `desktop/out/f03-w05`，当前源码 packaged executable 成功生成：`desktop/out/f03-w05/UthCode-win32-x64/UthCode.exe`（244,440,576 bytes）。
- 真实 packaged Electron CDP（使用上述当前源码包）英文报告：`desktop/dist/ui-acceptance/f03-w05-en/acceptance-report.json`，`status=passed`；6 张截图覆盖 dark docked/focus/floating/hidden、light、narrow；验证 drag preview/no-write/release commit、reload rehydrate、Runtime keyboard Home、Focus transient/restore、split usage、narrow separator/overflow、680/520 CSS viewport 的 100%/125%/150% reduced-motion。
- 真实 packaged Electron CDP 中文报告：`desktop/dist/ui-acceptance/f03-w05-zh/acceptance-report.json`，`status=passed`；语言为 `zh-CN`，同样覆盖 dark/light、Focus、narrow、zoom/reduced-motion 与 ARIA/layout 边界。
- 上述两个报告的 `consoleErrors`、`consoleDiagnostics`、`rendererExceptions`、electron/driver unexplained stderr 均为 `0`，隔离 profile cleanup 均为 true；截图与日志均为 `desktop/dist/ui-acceptance/` 下可再生成产物。

## 未验证项与风险

- 额外运行的真实 fixture Provider `stream` packaged CDP 未通过：既有 provider flow 在 `assertCommandCandidate` 等待 `fixture/fixture-model` 时达到 120s driver deadline，报告为 `desktop/dist/ui-acceptance/f03-w05-stream-en/acceptance-report.json`（`status=failed`）。该结果未计入通过，也未将其归因于 T05 layout helper；因此本轮没有声称真实 Provider available usage 的 packaged E2E，通过自动化 RuntimePanel available/unavailable projection 测试与 visual unavailable boundary 验证了显示契约，Provider 全矩阵留给 W07。
- 未执行人工视觉评审、干净 Windows 环境与完整 acceptance 矩阵；未把这些场景描述为通过。Forge 旧输出目录的 EBUSY 是环境锁定风险，当前验证包已从独立 ignored output 生成。

## Checklist

本轮只更新 F03 Checklist 的 T05 八项勾选状态；T06/T07/T08/T09 保持原状，等待对应 Worker/收口任务提供证据。

## 返工第 1 轮追加（Reviewer REQUEST CHANGES）

### P1：wide → wide viewport clamp

- `desktop/src/renderer/App.tsx` 新增真实 CSS viewport 宽度 state；现有 `resize` listener 同步 `window.innerWidth`，clamp effect 以 viewport、panel mode 与两条 track 为依赖。resize/zoom 只更新展示 state，不写入 `sidebarWidth`/`runtimePanelWidth` preference。
- 新增 `desktop/tests/renderer.test.tsx` 测试 `T05 wide-to-wide resize clamps docked tracks to the current CSS viewport`：JSDOM 真实 `resize` 事件把 `1280` 缩至 `800`，断言 docked tracks 为 `sidebar=180`、`runtime=380`、Conversation 为 `240`，并断言 CSS variables。
- 当前源码 Forge 包 `desktop/out/f03-w05-r1/UthCode-win32-x64/UthCode.exe`（244,440,576 bytes，SHA-256 `22a71860c08f98a922d92e0203377ba7e39ec39785b7f6749437a3a6c0a2eef8`）的 packaged CDP 严格 synthetic resize 证据：`f03-w05-r1-zh-final/driver.stdout.log` 与 `f03-w05-r1-en-final/driver.stdout.log` 均记录 `viewportWidth=800`、`sidebarWidth=180`、`runtimePanelWidth=380`、`conversationWidth=240`、`scrollWidth=clientWidth=800`，strict `wide-to-wide viewport clamp` PASS。driver 明确在 `Emulation.setDeviceMetricsOverride(800)` 后发出 DOM `resize`，报告描述为 synthetic resize，不冒充 native window resize。
- 为排除旧文档误读，`f03-w05-r1-zh-timeorigin` 使用 `performance.timeOrigin` 变化与 DOM preference hydrate 等待后仍记录真实 `800/420/520`，严格断言失败；临时 probe 进一步记录 `window resize=0`、`visualViewport resize=0`。`Browser.getWindowForTarget` 在当前 Electron page endpoint 返回 “wasn't found”，故 native window resize 未通过，交由 Reviewer 判断；未添加生产兜底或放宽断言。

### P2：Session boundary provider usage

- `desktop/src/renderer/state-session.ts` 的既有 Session runtime snapshot 现在携带 `lastProviderRequestUsage`；`session_new`、`project_opened`、非恢复的 `session_changed` 与 `workspace_cleared` 按既有 boundary reset 到 unavailable，`session_resumed`/snapshot restore 恢复目标 Session 自己的 projection。
- `desktop/src/renderer/state.ts` 的 `status_loaded` 只把当前可见 Session 的 usage 投影到顶层；延迟的旧 Session status 仍缓存到其 owner snapshot，不会覆盖当前 Session。未新增 store。
- 新增 `desktop/tests/renderer-state.test.ts` 测试 `T05 Provider usage follows Session boundaries, snapshots, and delayed status`：覆盖 A=`111/22/133` → `session_new` B 清空、B snapshot restore、`project_opened` 清空、`session_resumed` 恢复 B usage，以及延迟 failed status 不污染当前 B。

### 返工验证

- `conda run --no-capture-output -n re-uthcode npx tsx --test --test-name-pattern="T05" tests/renderer-state.test.ts tests/renderer.test.tsx`：`28` passed，`0` failed，exit code `0`。
- `conda run --no-capture-output -n re-uthcode npm --prefix desktop test`：`180` passed，`0` failed，`0` skipped，exit code `0`。
- `conda run --no-capture-output -n re-uthcode npm --prefix desktop run typecheck`：exit code `0`；`npm --prefix desktop run build:runtime`：exit code `0`；Forge API 独立 outDir 当前源码包构建：exit code `0`。
- `node --check desktop/scripts/cdp-driver.mjs`：exit code `0`；`git diff --check`：无 diff error（仅 CRLF normalization warnings）。
- 返工 packaged CDP 在严格 synthetic wide-to-wide 后，zh 顺序报告 `desktop/dist/ui-acceptance/f03-w05-r1-zh-final2/acceptance-report.json`、en 报告 `desktop/dist/ui-acceptance/f03-w05-r1-en-final/acceptance-report.json` 均因后续 `Input.dispatchMouseEvent(mouseMoved)` 5 秒超时而 `status=failed`，因此本追加不宣称 pointer release 当前轮通过。此前同包旧时序 `f03-w05-r1-en`/`f03-w05-r1-zh-retry` 的 pointer press/move/release PASS 仍保留，但其 wide-to-wide 断言发生在 reload 旧文档竞态下，不作为本轮 P1 native resize 通过证据。
- `stream` Provider flow 既有 120 秒 candidate/deadline failure 保持未通过，未归因于本 T05 返工，也未把 Provider available usage packaged E2E 记为通过。

本轮未修改冻结 Spec/Tasks/Prompt 或 Checklist 正文，未执行 Git 写操作，未触碰 `.workbuddy/` 与 `临时目录/`。

## 返工第 2 轮追加（Reviewer P2 driver REQUEST CHANGES）

- 仅修改 `desktop/scripts/cdp-driver.mjs`：将 Pointer separator 的 ARIA、真实 `Input.dispatchMouseEvent` press/move、preview/no-write、release commit 与 persistence reload 整段移到该函数第一处 `Emulation.setDeviceMetricsOverride` 之前；pointer commit 后的 `Page.reload` 现在严格等待 `performance.timeOrigin` 变化、新 shell/composer 与 committed `aria-valuenow`，不再用旧页面目标宽度虚报 reload persistence。
- `node --check desktop/scripts/cdp-driver.mjs`：exit code `0`。
- 按要求顺序执行当前 r1 packaged executable（SHA-256 `22a71860c08f98a922d92e0203377ba7e39ec39785b7f6749437a3a6c0a2eef8`）：
  - `f03-w05-r2-en/driver.stdout.log`：尚未发生任何 Emulation command；`Input.dispatchMouseEvent(mousePressed)` 返回后，`Input.dispatchMouseEvent(mouseMoved)` 在 5 秒 request timeout，report `status=failed`。
  - `f03-w05-r2-zh/driver.stdout.log`：同一失败点，语言 observed 为 `zh-CN`，report `status=failed`。
- 因 pointer move 在 emulation 前仍失败，本轮不宣称 preview/no-write/release/reload 通过，也未弱化原断言；r1 已通过的 synthetic CSS viewport `800/180/380/240` 证据仍保留。native window resize 与真实 zoom 继续如实标记未验证。生产源码未改，故不重复 npm/typecheck/full production matrix。
