# W05 GUI Review 与 Integration 实施反馈

## 首次实施

本反馈记录 W05 按 Prompt 串行实施 T08 → T09 的 review、范围内修复和生产链回归；后续返工只在本文 EOF 追加，不覆盖本节。

### 开工边界

- 已完整读取 `AGENTS.md`、`docs/README.md`、`docs/Context-Index.md`、`docs/rules/WorkPackageRules.md`、`docs/rules/UserDecisionBoundary.md`、`docs/OutstandingDebtList.md`、F02 需求/Spec/Tasks/Checklist、W05 Prompt 及 W01～W04 Feedback。
- 审查对象为 `desktop/src/**`、`src/uthcode/interfaces/desktop/**`、F02 前序公共投影修改点及其测试；按 correctness、architecture、maintainability、privacy 检查，并重点复核颜色、动画偏好、窄屏、焦点/ARIA、Run/Turn/pause identity、秘密和重复入口。
- 严格先完成 T08 finding 处理，再进行 T09 接线回归。不修改 T10、`desktop/src/main.ts`、`desktop/src/preload.ts`、`desktop/src/python-runtime.ts`、CDP harness 或 current-facts 文档；未执行任何 Git 写操作。
- 归属检查后，本轮 finding 均属于 W05 指定的 GUI/Bridge/公共投影审查范围；没有发现必须停止并重新派发 W01～W04 原 Prompt 的产品缺陷，因此没有代写其他 Worker Feedback。

## T08 review 与 finding 处置

### Correctness / identity

- **P1-COR-01：同一 Run 的旧 Turn 事件可污染当前投影。** `desktop/src/renderer/state.ts` 原先只按 `run_id` 过滤，旧 `turn_id` 的 delta、task、terminal 仍可能写入新 Turn。现在对 turn-scoped event 要求完整且匹配当前 Run/Turn identity，`turn_started`、terminal 事件也必须先通过完整 identity 门禁；`desktop/tests/renderer.test.tsx` 的 `T08 reducer rejects stale same-Run events from an older Turn`（约第 977 行）覆盖 assistant、TaskState 和 terminal。
- **P1-COR-02：terminal 后的迟到 stream、重复 tool terminal 和乱序 TaskState 缺少收口。** Reducer 现在对已 settled Turn 忽略 stream/task/interaction 事件；已完成的 reasoning/assistant 行不重新打开；已终止的 Tool row 不被第二个 terminal 覆写；TaskState 保存最新 `iteration`，旧 iteration 不得回滚可见 Todo。`T08 reducer ignores late stream data and duplicate tool terminals` 与 `T08 TaskState projection keeps the newest iteration`（约第 995～1025 行）通过。
- **P1-COR-03：生命周期 owner 变化后旧 RPC/Session mutation/command/interaction 结果可能迟到写回。** `desktop/src/renderer/App.tsx` 的 catalog/status/config refresh 在未持有 owner 时也检查 restarting/owner；command、completion、interaction resume、cancel、rename、move 均增加 in-flight、generation、mounted 和 owner 检查，旧结果不能 dispatch、继续 recovery 或覆盖新 Session。既有 T05/T07 ownership、rebootstrap、Save/导航 supersede、terminal cleanup 测试及完整 Desktop suite 通过；本轮还补上 completion 在 status refresh 后的 current-generation 门禁。

### Architecture / production chain

- **P1-ARCH-01：review 发现的 identity 和状态门禁通过现有投影收口，不新增 authority。** `RendererState.todoIteration` 只是 TaskState UI projection 的乱序过滤元数据，Run/Turn/Plan/Todo/Permission/Context 的权威仍来自 Application 事件和 DTO；Renderer 没有 Context safety 计算、durable Session 写入或第二 Run/Application。
- **P1-ARCH-02：唯一生产链复核通过。** Renderer 仍只经 `DesktopApi.requestRuntime` / `subscribeAgentEvents`；Bridge 仍把请求委托给既有 Application/Run 和公开 DTO；没有 Desktop Core facade、第二 Runtime、跨项目文件扫描或通用 EventBus/Manager/Store/Registry/Protocol/streaming/modal/menu framework。T09 offline Desktop integration 用例实际穿过 Bridge → Application → Core；Main/Preload/Python transport 保持不变。
- `rg -n "DesktopManager|SessionManager|SessionStore|ContextManager|ContextEngine|PlanManager|TodoManager|EventBus|PluginRegistry|TransportFactory" src/uthcode desktop/src tests desktop/tests`：无匹配（exit code 1，表示无新增生产抽象）。

### Privacy / boundary

- **P1-PRIV-01：通用 Bridge Mapping 投影只过滤 secret 字段，命名为 raw/native/private/provider payload 的私有内容仍可能穿过边界。** `src/uthcode/interfaces/desktop/bridge.py` 增加 `_PRIVATE_FIELD_NAMES` 与 `_is_private_field`，`_safe_value` 在所有普通 Mapping、DTO、event、status、diagnostics、snapshot 和 error 投影中同时排除 secret/private 字段；仍保留专用 `settings.reveal_api_key` 窄路径语义。`tests/test_desktop_bridge.py` 的 `test_secret_sentinel_stays_out_of_all_non_reveal_bridge_projections` 加入 `raw_provider_payload`、`arguments_delta`、`private_body`、`native_payload` sentinel，配置/状态/event/error 回归通过。
- 复核确认 Session path、native exception、raw Provider/tool body、internal diagnostics 和 API Key 不进入非授权 Interface payload；测试使用 synthetic sentinel，不写入真实凭据。

### Maintainability / UI review

- **P2-MAINT-01：`isJsonValue` 把共享 JSON 子对象误判为循环。** `desktop/src/desktop-api.ts` 现在以递归路径为 `seen` 的生命周期，在 `finally` 删除已返回的对象；真正 back-edge 仍拒绝，共享 DAG 允许通过。`T08 DesktopApi JSON validation accepts shared data and rejects cycles` 通过。
- **P2-MAINT-02：无调用方的旧 idle helper。** 删除 `App.tsx` 导出的 `IdleWaitResult`、`IdleWaitOptions`、`waitForIdle` 及其 test-only 测试；生产只保留并使用 `waitForAuthoritativeIdle`。`rg -n "waitForIdle|IdleWait" desktop/src desktop/tests` 无匹配。
- **P2-UX-01：Interaction Surface 的 permission/plan/retry/resume/AskUser 快速重复提交和 cancel/Escape 竞争。** `InteractionSurface.tsx` 统一 `submitResponse`/`cancelInteraction`，使用本地 submit lock、`interaction.submitting`、disabled 控件和 `aria-busy`；Escape 保留 typed cancel 但提交进行中不再竞争。`T08 Interaction Surface submits one response and blocks cancel while submitting` 与既有 AskUser focus/typed response 测试通过。
- **P2-UX-02：Composer 状态仅由视觉文本表达。** `Composer.tsx` 的 `#composer-state` 增加 `role="status"` 和 `aria-live="polite"`，restarting 状态继续通过 `aria-describedby` 关联输入框；既有 Composer markup/accessibility 测试通过。
- **P2-UX-03：accent 文本和按钮背景散落硬编码颜色。** `app.css` 把用户气泡、发送/interaction/settings accent 的前景和背景统一到 `--on-accent`、`--accent-user`、`--accent-action` 主题 token，并在 light/system 主题补齐 token；视觉契约测试改为检查语义 token。没有新增动画，现有 `prefers-reduced-motion` 关闭非必要 transition/scroll 行为的规则保持不变。
- **P2-UX-04：响应式与焦点审查。** 本轮未改窄屏结构，只验证新增 disabled/ARIA 不破坏现有 Runtime drawer、modal focus trap/restore、menu/select geometry、keyboard/IME 和 wide/narrow 规则；对应 T05/T06/T07/Prompt 4 renderer tests 全部通过。真实窗口、DPI/zoom 和可访问性树仍留给 T10/W06，不在本轮伪称通过。

### 大文件与删除决策

- 保留 `App.tsx`：它仍是当前唯一 Renderer orchestration 边界，集中 lifecycle owner、Desktop API 请求、Session/Runtime 导航、Settings durable flow 和组件 wiring；没有独立当前调用方/测试边界可以安全拆分的私有模块。
- 保留 `state.ts`：它仍是当前单一 Renderer reducer/projection 边界，Run/Turn、timeline、Todo、interaction、Context、Settings 和 preference action 必须按顺序收口；拆分会复制 reducer authority。
- `SettingsView.tsx` 未因行数机械拆分：其 Provider/Model modal、draft/reveal/save boundary 仍有完整当前调用方和测试边界，W05 没有新增 Settings 公共抽象。
- 删除内容只有已证实无调用方的 `waitForIdle` helper/types/test；未删除现有 Tool in-place、Todo replace-all、Plan draft/review 或正式 command registry。没有引入 Manager/Store/EventBus/Registry/Protocol 或第二套 UI framework。

## T09 唯一生产链集成

- AskUser response builders、Permission、Plan approve/revise、Provider retry、user resume/cancel 均保留 pause/run/turn/tool identity；Interaction Surface 只生成 typed response，不发送 raw JSON 或伪用户消息。
- Plan delta/final/review、Tool start/finish、Todo replace-all、BehaviorMode、Context/Compact status、Session move/replay、direct Slash/model/status、Settings reveal/save/rebootstrap 均沿现有 `Renderer → DesktopApi → Main/Preload transport → DesktopBridge → Application → Core` 链路接入或复核；没有新增入口。
- `App.tsx` 的 accepted Run/Turn boundary、terminal status convergence、pending interaction、compact running、Runtime lifecycle owner 和 stale response guard 共同约束单一可见 Run/Turn；Bridge 继续将普通错误收敛为稳定安全结果。
- 本轮未执行真实 Desktop dev shell、人工矩阵、CDP/packaged 最终验收；T09 Checklist 中相应的真实 shell 条目不勾选，T10/W06 继续负责这些场景。现有 `npm test` 中的 packaged/CDP isolation 和 T08 build smoke 只作为未改冻结 harness 的回归证据，不替代人工/CDP acceptance。

## 修改文件

- Renderer/API：`desktop/src/renderer/state.ts`、`desktop/src/renderer/App.tsx`、`desktop/src/renderer/InteractionSurface.tsx`、`desktop/src/renderer/Composer.tsx`、`desktop/src/renderer/app.css`、`desktop/src/desktop-api.ts`。
- Bridge/tests：`src/uthcode/interfaces/desktop/bridge.py`、`tests/test_desktop_bridge.py`、`desktop/tests/renderer.test.tsx`。
- 工作包记录：本文件及 F02 Checklist 只做 W05 证据写回。
- 明确未改：T10 文件、`desktop/src/main.ts`、`desktop/src/preload.ts`、`desktop/src/python-runtime.ts`、CDP scripts/harness、current-facts docs；工作区未执行 Git commit/push/merge/rebase/tag/release/归档。

## 精确验证与扫描

- `conda run --no-capture-output -n re-uthcode npm run typecheck`（cwd=`desktop`）：exit 0。
- `conda run --no-capture-output -n re-uthcode npx tsx --test tests/renderer.test.tsx`（cwd=`desktop`）：101 passed、0 failed，exit 0。
- `conda run --no-capture-output -n re-uthcode npm test`（cwd=`desktop`）：138 passed、0 failed，exit 0；包含 Preload、Runtime process、Main bundle、Renderer、Windows packaging、CDP isolation 和 T08 build smoke。
- `conda run --no-capture-output -n re-uthcode python -m pytest -q`：1446 passed、3 skipped、0 failed，exit 0，耗时 356.06s。
- `rg -n "waitForIdle|IdleWait" desktop/src desktop/tests`：无匹配。
- `rg -n "DEFAULT_CONTEXT_WINDOW|configuredContextWindow|renameModelRef|model-1|arguments_delta" desktop/src desktop/tests desktop/scripts`：无匹配。
- `rg -n "DesktopManager|SessionManager|SessionStore|ContextManager|ContextEngine|PlanManager|TodoManager|EventBus|PluginRegistry|TransportFactory" src/uthcode desktop/src tests desktop/tests`：无匹配。
- `rg -n "allow_other" src tests desktop/src desktop/tests desktop/scripts`：仅命中冻结的 `desktop/scripts/cdp-openai-fixture.mjs` 两处；按 W05 Prompt 不修改 CDP/T10，后续由 T10/W06 处理，不能把该扫描描述为全仓 0。
- `git diff --name-only -- docs/work/T10-DesktopGUI与TUI全量能力迁移`：空；`git diff --name-only -- desktop/src/main.ts desktop/src/preload.ts desktop/src/python-runtime.ts`：空。
- `git diff --check`：exit 0；Git 仅提示工作副本 LF/CRLF 转换，无 whitespace error。

## Checklist 与未关闭风险

- 本轮只勾选 Checklist 的 T08 已有证据项（第 76～84 行）和 T09 自动/静态证据项（第 89～94 行）；T09 真实 dev shell 第 88 行及 T10 全部条目保持未勾选。Checklist 未因实际运行全量测试而越权替代 T10 acceptance。
- W05 范围内 P0/P1/P2 finding 已为 0；保留的仅是 P3/环境风险：真实 Electron dev/packaged 窗口的 dark/light、zh-CN/en、wide/narrow、keyboard-only/mouse、IME、100%/125%/150% zoom、reduced motion、dropdown overlap/flicker、横向 crop、真实 Provider 和人工 AskUser/Plan/Tool/Compact/Session/Key 矩阵未在本轮执行。
- `allow_other` 的两处命中位于冻结 CDP fixture，不是 W05 新生产链；不得为清零该命中修改 T10/CDP。Python full suite 的 3 skipped 由现有 suite 条件跳过，exit 仍为 0；本轮未将 skip 描述为通过的人工/Provider 验收。
- W05 未创建临时缓存、第二 harness、第二 state/runtime system 或额外抽象；可再生成构建产物由既有测试流程管理，未知文件未清理。

## UTF-8 guard

本 Feedback 与 Checklist 写回后运行：

`conda run --no-capture-output -n re-uthcode python C:\Users\93445\.codex\skills\uth-utf8-guard\scripts\check_utf8_docs.py "docs/work/F02-DesktopGUI交互与上下文缺陷修复/feedback/W05-gui-review-integration-feedback.md" "docs/work/F02-DesktopGUI交互与上下文缺陷修复/F02-DesktopGUI交互与上下文缺陷修复-checklist.md"`

结果将在本节 EOF 追加；Checklist 只保留有精确证据的勾选。

## 最终复核补充

- 在最后一轮 Renderer 门禁收敛后重新执行 `conda run --no-capture-output -n re-uthcode npm test`（cwd=`desktop`）：138 passed、0 failed、exit 0，耗时 106.91s。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q`：23 passed、0 failed、exit 0，耗时 8.57s。
- 上述补充后再次确认 `git diff --name-only -- docs/work/T10-DesktopGUI与TUI全量能力迁移` 与 `git diff --name-only -- desktop/src/main.ts desktop/src/preload.ts desktop/src/python-runtime.ts` 均为空；`git diff --check` exit 0（仅 LF/CRLF 转换提示）。
- Feedback/Checklist 的 UTF-8 guard 结果：`OK: 2 file(s) passed UTF-8 guard`。

## 返工轮次一：Reviewer P1 退回后的修复与复核（2026-09-01）

### 返工原因与边界

Reviewer 未批准上一轮，指出两个 W05 范围 P1：Bridge 的通用 `_safe_value`/denylist 允许 diagnostics、Session path、Provider/SDK response 等私有值穿过普通 status/event/snapshot；Session rename/move 在副作用 RPC 未完成或发生 generation 变化时缺少 single-flight，可能静默丢失旧成功。上一轮对应的两个关闭结论由本节实际证据 supersede。返工仍只修改 W05 的 GUI/Bridge/公共投影与对应回归测试；未修改 W01～W04 Feedback，也未代写其他 Worker 记录。

### P1-PRIV-01 关闭：公共 payload 显式 DTO/allowlist

- `src/uthcode/interfaces/desktop/bridge.py` 删除通用 `_safe_value` 生产投影及 denylist 依赖，按 payload 类型使用显式 `_public_*` DTO：Application status、configuration/provider/model、Run snapshot、AgentEvent、Pause/AskUser/Permission/Plan request、Session catalog/mutation/replay、Usage、command completion/outcome 和 UI action 均逐字段投影。
- 普通 `status.get` 的 runtime/application 结果只保留已冻结的用户安全字段；Application 的 `diagnostics`、`configuration_sources`（及其 Path）和 Runtime workdir 均不返回。Context source 也仅接受 `unavailable`、`context_compiler`、`provider_usage`，runtime state、replay status 等有限枚举同样显式约束。
- 未知 Mapping key、Path、native/provider/private object、exception、非有限数或不符合 DTO 形状的 event/snapshot/configuration 不被递归遍历、`str`/`repr` 或部分制造；event projection 失败只发布稳定 `runtime_state=failed`，不会把原始对象写入 outbox。专用 `settings.reveal_api_key` 窄路径保持原授权语义。
- `tests/test_desktop_bridge.py::test_secret_sentinel_stays_out_of_all_non_reveal_bridge_projections` 现在通过公开 `status.get`、event consume/outbox、Run snapshot、settings configuration 链验证 `api_key`、`diagnostics`、`session_path`、`provider_response`、`sdk_response`、`config_source`、`raw_provider_payload`、`arguments_delta`、`private_body`、`native_payload`、`exception` 共 11 类 sentinel；同时断言普通 Application status 不含 `diagnostics`/`configuration_sources`，unsafe snapshot 不产生 run payload。

### P1-COR-01 关闭：Session mutation single-flight 与权威收敛

- `desktop/src/renderer/App.tsx` 以一个 mutation token 覆盖 rename 与 move：RPC 之前取得 single-flight gate，记录 mutation/runtime generation，生命周期 owner 等待后再次核验；busy 时第二个 move、rename 只显示稳定 notice，不会触发第二次副作用 RPC。
- `desktop/src/renderer/Sidebar.tsx` 和 `state.ts` 增加 `sessionMutationBusy` 投影；Sidebar root 标记 `aria-busy`，rename/move menu item 与 rename input 在 mutation pending 时 disabled，并带有明确的 disabled reason/ARIA 文案。现有 active Turn/terminal gate 仍有效。
- 当前 generation 的成功结果先按 `session_mutated` 应用唯一 mutation projection，保留原 catalog 的 preview/checkpoint/transcript/pin 元数据；move 随后按需要刷新 source catalog authority。失败、迟到结果或 Runtime navigation generation 变化不重放副作用 RPC，并通过当前 source 项目的 authoritative catalog 收敛；失败不会乐观搬走原 UI 行，导航到其他 project 时不把旧 catalog 应用到新选中 project。
- `desktop/tests/renderer.test.tsx` 新增并通过：A pending 时 B/rename disabled 且 move RPC 恰好一次；A success 后 source/target/catalog/selection 一致；A failure 保留原行且只做一次 authority refresh；导航导致 generation 变化后迟到成功不写入新选中 project，且无重复副作用。既有 reducer mutation identity 测试继续通过。

### 返工后的唯一链与修改文件

返工复核的生产链仍为 `Renderer → DesktopApi → 既有 Main/Preload transport → DesktopBridge → Application → Core`，未新增 Desktop Core facade、第二 Runtime/state system、Manager/Store/EventBus/Registry/Protocol 或通用 streaming/modal/menu framework。实际修改文件为 `desktop/src/renderer/App.tsx`、`Sidebar.tsx`、`state.ts`、`desktop/tests/renderer.test.tsx`、`src/uthcode/interfaces/desktop/bridge.py`、`tests/test_desktop_bridge.py` 及既有 W05 GUI/API 文件；T10、Main/Preload/Python runtime、CDP、current-facts 和 W01～W04 Feedback 均未修改。

### 返工验证证据

- `conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_desktop_bridge.py`：57 passed、0 failed、exit 0。
- `conda run --no-capture-output -n re-uthcode npx tsx --test tests/renderer.test.tsx`（cwd=`desktop`）：104 passed、0 failed、exit 0。
- `conda run --no-capture-output -n re-uthcode npm run typecheck`（cwd=`desktop`）：exit 0。
- `conda run --no-capture-output -n re-uthcode python -m pytest -q`：1446 passed、3 skipped、0 failed、exit 0（332.18s）。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q`：23 passed、0 failed、exit 0（11.01s）。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests`：exit 0；`conda run --no-capture-output -n re-uthcode python -m pip check`：exit 0，`No broken requirements found.`
- 返工后执行 `conda run --no-capture-output -n re-uthcode npm test`（cwd=`desktop`）：共 141，140 passed、1 failed、0 skipped、exit 1。唯一失败为冻结 T10 `desktop/scripts/build-python-runtime.mjs` 驱动的 `T08 build command blocks on a real bundled Runtime smoke`；旧 smoke 仍读取 `status.result.application.diagnostics.context`，而本轮 P1 要求普通 status 移除 `diagnostics`，因此该断言与新冻结公共合同冲突。W05 未修改该 T10 build script/test，也未以恢复 diagnostics 的方式绕过隐私边界；需要由后续 T10/W06 按新安全 status 合同重新派发/调整其验收，不计作 W05 direct scope 的 P1 未关闭。
- 负向扫描：`waitForIdle|IdleWait`、旧 Manager/Store/EventBus/Registry/TransportFactory、`DEFAULT_CONTEXT_WINDOW|configuredContextWindow|renameModelRef|model-1` 在指定生产范围无命中；`allow_other` 仍仅命中冻结 `desktop/scripts/cdp-openai-fixture.mjs` 两处，按边界未修改。隐私扫描中 Bridge 的 diagnostics/Path 等仅为显式排除逻辑、错误保护注释或 sentinel 回归输入，无对应输出字段。
- `git diff --name-only -- docs/work/T10-DesktopGUI与TUI全量能力迁移` 与 `git diff --name-only -- desktop/src/main.ts desktop/src/preload.ts desktop/src/python-runtime.ts` 均为空；`git diff --check` exit 0（仅 LF/CRLF 转换提示）。

### Checklist、未关闭风险与 UTF-8

- Checklist 仅保留已有 W05/T08～T09 证据勾选；T09 真实 Desktop dev shell 与 T10 全部条目未勾选。返工没有修改 Checklist 文字、结构、编号或顺序，也没有把失败的冻结 T10 smoke 伪记为通过。
- W05 直接范围 P0/P1/P2 finding 为 0。剩余风险是 T10 冻结 smoke 合同需后续按安全 status 重验，以及真实 Electron dev/packaged 窗口、DPI/zoom、人工键鼠/IME、dark/light、zh/en、reduced-motion、真实 Provider 和 CDP 矩阵尚未在 W05 执行；这些不转化为 W05 新实现。
- 本节追加后重新执行 `conda run --no-capture-output -n re-uthcode python C:\Users\93445\.codex\skills\uth-utf8-guard\scripts\check_utf8_docs.py "docs/work/F02-DesktopGUI交互与上下文缺陷修复/feedback/W05-gui-review-integration-feedback.md" "docs/work/F02-DesktopGUI交互与上下文缺陷修复/F02-DesktopGUI交互与上下文缺陷修复-checklist.md"`：实际结果为 `OK: 2 file(s) passed UTF-8 guard`。
- 全程未执行 Git commit、push、merge、rebase、tag、release 或归档；未清理未知文件。

## 返工轮次二：第二轮复审 P1/P2 修复与复核（2026-09-01）

### 复审 finding、范围与处置

第二轮复审新增一个 W05 范围 P1 和一个 P2。P1 是正式 `package.json` `build:runtime` smoke 仍读取普通 status 的 `diagnostics.context`；P2 是上一轮 Bridge 显式投影虽然关闭了隐私问题，但仍重复声明过多深层 AgentEvent/Run/Permission/Config schema。两项均属于 W05 GUI/Bridge/公共投影范围；没有发现 W01～W04 产品缺陷，因此没有修改或代写其他 Worker Feedback。

### P1-PRIV-02 关闭：安全公开 status smoke 合同

- `desktop/scripts/build-python-runtime.mjs` 的正式 smoke 现在只断言 `status.result.application.context_status.available === true`、`context_status.source === "context_compiler"`，以及非空字符串 `application.stable_prefix_fingerprint`；没有恢复 `diagnostics`、`configuration_sources` 或任何 Path/diagnostic payload。
- `src/uthcode/interfaces/desktop/bridge.py` 的普通 `status.get` 继续显式构造窄 `application` 字段，删除 diagnostics/config source/workdir；`event`、`snapshot` 只输出冻结的用户字段。11 类 sentinel（api_key、diagnostics、session_path、provider_response、sdk_response、config_source、raw_provider_payload、arguments_delta、private_body、native_payload、exception）仍覆盖 status、event consume/outbox、snapshot 和 settings 链，未进入任何非 reveal 响应。
- 公开链对未知 Mapping key、Path/native/provider/private object 和 exception fail-closed；只有 `settings.reveal_api_key` 保留显式授权的秘密表达式返回语义。

### P2-MAINT-02 关闭：Bridge 投影收敛与未来字段兼容

- 删除上一轮 25 个 `_public_*` 深层 schema helper、通用 denylist/递归 `_safe_value` 依赖和重复的深层 Core/Application 校验。当前 Bridge 只保留职责相邻的私有边界函数：已知强类型 DTO 通过 `_dto_payload` 调用其既有 `to_dict()`，再做窄 top-level allowlist；普通 status 仍显式构造真实 Desktop 消费字段。
- typed AgentEvent/RunSnapshot/ApplicationStatus 允许其 DTO serializer 出现合法新增字段并忽略未纳入当前 Desktop 合同的字段；不可信 Mapping 只接受明确字段集合并拒绝未知字段。Message/TaskState/AskUser/Permission/Plan/Pause 等嵌套值沿既有 DTO serializer 进入，再只复制当前用户字段，因此不会因 Bridge 第二套深层 schema 拒绝合法新增 Core 字段，也不会把 raw/native/private/path/secret 带出。
- Bridge 保留在单文件的理由是它仍是唯一 Desktop/Application process-edge adapter；这些 helper 只服务该文件内的 request/result/event 生命周期，没有独立调用方或模块边界，拆文件会新增无真实职责的抽象。当前 `git diff --numstat -- src/uthcode/interfaces/desktop/bridge.py` 为 `675` added / `142` removed，`rg -n "_public_|_safe_value|_mapping_with_keys"` 在生产 Bridge 无命中。
- 11 类 sentinel 回归与现有前端合同保持不变；Session mutation single-flight、disabled/ARIA 和 generation/authoritative catalog 收敛沿用上一轮实现。

### 本轮修改与边界

- 修改：`desktop/scripts/build-python-runtime.mjs`、`src/uthcode/interfaces/desktop/bridge.py`；其余 GUI/Renderer 修改为上一轮 W05 已有工作树变更，本轮未重写。
- 未修改：W01～W04 Feedback、T10 工作包文件、Main/Preload/Python runtime、CDP harness/fixture、current-facts docs；构建脚本 smoke 调整是本轮复审明确允许的公开 status 合同同步，不恢复 T10/CDP 旧 diagnostics 依赖。
- 未执行 Git commit、push、merge、rebase、tag、release 或归档；未清理未知文件或构建以外的用户数据。

### 本轮精确验证

- `conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_desktop_bridge.py`：57 passed、0 failed、exit 0。
- `conda run --no-capture-output -n re-uthcode npx tsx --test tests/renderer.test.tsx`（cwd=`desktop`）：104 passed、0 failed、exit 0。
- `conda run --no-capture-output -n re-uthcode npm run typecheck`（cwd=`desktop`）：exit 0。
- `conda run --no-capture-output -n re-uthcode npm test`（cwd=`desktop`）：141 passed、0 failed、0 skipped、exit 0；包含正式 PyInstaller `build:runtime` smoke，`windows-packaging` 4/4，smoke 输出 `Bundled Runtime smoke passed: ready/status/shutdown JSONL and importlib.resources prompt asset`。
- `conda run --no-capture-output -n re-uthcode python -m pytest -q`：1446 passed、3 skipped、0 failed、exit 0（312.74s）。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q`：23 passed、0 failed、exit 0（9.32s）。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests`：exit 0；`conda run --no-capture-output -n re-uthcode python -m pip check`：exit 0，`No broken requirements found.`
- 负向扫描：`waitForIdle|IdleWait`、`DEFAULT_CONTEXT_WINDOW|configuredContextWindow|renameModelRef|model-1` 在指定生产/测试范围无命中；`allow_other` 仍只命中冻结 `desktop/scripts/cdp-openai-fixture.mjs` 两处；Bridge 无 `_public_*`、`_safe_value` 或旧 Mapping sanitizer。隐私扫描命中仅为显式排除注释、测试 sentinel 输入/断言与合法 `settings.reveal_api_key` 窄入口，无对应普通输出字段。
- `git diff --name-only -- docs/work/T10-DesktopGUI与TUI全量能力迁移`：空；`git diff --name-only -- desktop/src/main.ts desktop/src/preload.ts desktop/src/python-runtime.ts`：空；`git diff --check`：exit 0，仅有 Git LF/CRLF 转换提示，无 whitespace error。

### Checklist、未关闭风险与 UTF-8

- Checklist 本轮不改文字、结构、编号或越权范围；已有 T08 与 T09 自动/静态证据勾选保持不变，T09 真实 dev shell 和 T10 全部条目继续未勾选。141/141 的自动测试结果写入本 Feedback，不替代 T10 acceptance。
- 本轮 W05 范围 P0/P1/P2 finding 为 0。保留 P3/环境风险：真实 Electron dev/packaged 窗口的 dark/light、zh-CN/en、wide/narrow、keyboard-only/mouse、IME、100%/125%/150% zoom、reduced motion、dropdown overlap/flicker、横向 crop、真实 Provider 与人工 AskUser/Plan/Tool/Compact/Session/Key 矩阵仍未执行，交由 T10/W06。
- 追加后运行：`conda run --no-capture-output -n re-uthcode python C:\Users\93445\.codex\skills\uth-utf8-guard\scripts\check_utf8_docs.py "docs/work/F02-DesktopGUI交互与上下文缺陷修复/feedback/W05-gui-review-integration-feedback.md" "docs/work/F02-DesktopGUI交互与上下文缺陷修复/F02-DesktopGUI交互与上下文缺陷修复-checklist.md"`；结果为 `OK: 2 file(s) passed UTF-8 guard`。

## 返工轮次三：P2 Bridge 收敛纠正与复核（2026-09-01）

### 对上一轮描述的事实纠正

上一轮 Feedback 把 Bridge 描述为已经删除全部深层 AgentEvent/Run/Permission/Config 重复投影；该描述不准确：当时仍保留 `_EVENT_FIELDS`、逐事件分派以及 `_message`、`_task_state`、`_input_request`、`_permission_request`、`_plan_request`、`_pause` 等深层重校验。上一轮的 `675 added / 142 removed` 也不是本轮收敛后的统计，不能作为当前 P2 关闭证据。本节仅在 Feedback EOF 追加纠正，不改前文、不改 W01～W04 Feedback。

### P2-MAINT-03 关闭：权威 AgentEvent round-trip 与窄投影

- `src/uthcode/interfaces/desktop/bridge.py` 的 `_event` 现在只接受 `AgentEvent`，调用通过 Application 公共导出的同一 `uthcode.core.agent_events.agent_event_from_dict(value.to_dict())` 完成权威 round-trip，再对 canonical `to_dict()` 做单一 Desktop 顶层 allowlist；不再维护 `_EVENT_FIELDS`、逐类型字段/enum 分派或嵌套 AgentEvent schema。未知顶层字段被忽略，解析失败、unknown Mapping/object、Path/native/private/exception 不能进入 agent-event envelope。
- 为保持架构边界，`agent_event_from_dict` 由 `src/uthcode/application/__init__.py` 重新导出；Interface 仍只依赖 Application，Application→Core 的既有依赖方向不变。
- exact typed `RunSnapshot`、`PauseRequest`、`ApplicationStatus`、`UserConfigurationView`、`SessionMutation`、`SessionReplayRecord` 统一复用既有 `to_dict()`，只做当前 Desktop 顶层字段投影；snapshot 的 usage 仅保留当前 token 字段。普通 status 继续排除 diagnostics、configuration_sources、config path 与 workdir；非 DTO Mapping/object 直接拒绝。
- 删除重复 enum/value sets、`_message`、`_task_state`、`_input_request`、`_permission_request`、`_plan_request`、`_pause` 及事件逐类型重校验；保留的通用 JSON 边界只接受 JSON primitive/array/string-key mapping，unknown/native/Path/secret fail-closed。合法新增 typed DTO 顶层或嵌套字段不会因 Bridge 第二套深层表失败，未纳入 Desktop 合同的新增字段被窄投影忽略。
- `tests/test_desktop_bridge.py` 新增 parser spy 回归，证明事件投影确实调用 Core 权威 parser；permission snapshot fake 同步改为合法 `RunSnapshot`，不再以任意 Mapping 作为 typed Run 合同。既有 11 类 sentinel 覆盖仍通过。

### 本轮边界与精确验证

- 本轮修改：`src/uthcode/interfaces/desktop/bridge.py`、`src/uthcode/application/__init__.py`、`tests/test_desktop_bridge.py`；Feedback 仅追加本节。未修改 Checklist 结构/文字/编号、T10、Main/Preload/Python runtime、CDP/current-facts 或 W01～W04 Feedback；未执行任何 Git 写操作。
- `conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_desktop_bridge.py`：58 passed、0 failed、exit 0。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q`：23 passed、0 failed、exit 0。
- `conda run --no-capture-output -n re-uthcode python -m pytest -q`：1447 passed、3 skipped、0 failed、exit 0（169.23s）。
- `conda run --no-capture-output -n re-uthcode npm test`（cwd=`desktop`）重跑：141 passed、0 failed、0 skipped、exit 0（包含正式 `build:runtime` smoke 与 windows packaging）。第一次全量仅有既有同步时序测试瞬态失败，重跑稳定通过。
- 本轮静态边界：生产 Bridge 无 `_EVENT_FIELDS`、`_public_*`、`_safe_value`、`_message`、`_task_state`、`_input_request`、`_permission_request`、`_plan_request`、`_pause` 或重复 enum 集合命中；Architecture 23/23 通过。
- 仍未执行 Git commit、push、merge、rebase、tag、release 或归档；T09 真实 dev shell 与 T10 人工窗口验收仍按 Checklist 保持未勾选，剩余仅为既有 P3/环境矩阵风险。
