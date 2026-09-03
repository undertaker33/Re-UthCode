# F03：Context 冻结收口、工程收敛与 Desktop 体验优化 Tasks

## Worker 分组、顺序与依赖

| Worker | 严格串行 Tasks | 前置依赖 | 独占写域 |
| --- | --- | --- | --- |
| W01 `core-compaction` | T01 | 无 | `core/context.py`、`core/compaction.py`、Core compaction tests |
| W02 `application-context-usage` | T02 | W01 | Application Context/generation/run/status、Desktop Bridge status |
| W03 `renderer-authority` | T03 | W02 | Renderer state/App lifecycle 与对应测试 |
| W04 `settings-markdown` | T04 | W03 | Settings、ChatTimeline、clipboard、相关 CSS/locale/CDP fixture |
| W05 `layout-focus-visual` | T05 | W04 | preferences、layout/state/App/CSS/locale、visual fixture |
| W06 `cleanup-integration` | T06 → T07 | W02、W05 | 非 Desktop/TUI 清理与跨层接入检查 |
| W07 `acceptance-closeout` | T08 → T09 | W06 | acceptance/measurement、当前事实文档、Checklist 收口 |

W04 与 W05 在当前代码中共享 `desktop-api.ts`、`App.tsx`、`app.css` 和 locale，固定串行，不并行写。原始需求中的“提交边界”只表示逻辑审查边界；未经用户明确要求，任何 Worker 均不得执行 Git commit、push、merge、rebase、tag、release 或归档。

## T01：Core Compaction 冻结与旧路径清理

### 任务目标

归一 Core compaction 职责，严格校验 multi-turn，提供 oversized Turn 的纯 Core 规划/合成能力，并删除无生产调用方的同步旧路径。

### 新增文件

- 无；若实现中确需 Core 私有测试 fixture，优先放入现有测试文件。

### 修改文件

- `src/uthcode/core/context.py`
- `src/uthcode/core/compaction.py`
- `src/uthcode/core/__init__.py`
- `src/uthcode/core/history.py`（仅完整 Turn 引用边界确需时）
- `tests/test_context_compaction.py`
- `tests/test_context_compiler.py`
- `tests/test_t09_1_context_protocol_e2e.py`

### 删除文件

- 无；删除的是 `ContextCompactor.compact()`、`_compact_locked()` 及只服务旧入口的 helper/test。

### 文件职责及实施内容

- 将 `CompactionPolicy`、`CompactionResult`、`ContextCompactor` 与 compaction-only helper 移入 `core/compaction.py`，`core/context.py` 只保留 budget/compiler/accounting/gate。
- 保留仍被 production L4/L5 使用的 single-flight 协调，不得随旧同步入口删除。
- multi-turn 必须显式提供数量、顺序、`turn_id`、refs 和 coverage 完全匹配的 entries；拒绝 plain text、top-level summary、string entry 以及缺失 refs/coverage 的自动补全。单 Turn 仅保留真实调用方仍需要的 bounded compatibility。
- 定义 oversized complete Turn 的安全 part/text 边界、bounded subpass plan、中间结果校验与最终一个完整 Turn Fine candidate 的合成；Core 不调用 Provider、不持久化 chunk。
- 任一 subpass 失败、取消或无效时不产生最终 candidate；最终 refs 精确覆盖原 Turn。

### 依赖任务

- 无。

### 参考资料定位

- F03 原始需求第 4.2、6.1～6.3、7/W01、11、12、19 节。
- `docs/context/A03-State/State-Context.md`。
- 当前 `ContextCompactor.plan_epoch()`、`parse_compaction_result()` 与 `ApplicationContextService.compact_async()` 调用链。

### 完成边界

- Core 已具备 W02 可调用的 oversized 纯规划/合成合同；Provider subpass orchestration 留给 T02。
- 无第二 compaction 主路径，无 durable chunk，无公共兼容 alias；定向测试与架构导入测试通过。

## T02：Application Working Context、manual Compact 与 usage 双投影

### 任务目标

在 Application 单一权威内完成 prospective ordinary request 验证、oversized Provider subpass、manual multi-epoch、usage 双投影、projection telemetry 与 `generation.py` 一次性职责拆分。

### 新增文件

- `src/uthcode/application/request_preparation.py`
- `src/uthcode/application/compaction.py`

### 修改文件

- `src/uthcode/application/context.py`
- `src/uthcode/application/generation.py`
- `src/uthcode/application/runs.py`
- `src/uthcode/application/provider_usage.py`
- `src/uthcode/application/__init__.py`
- `src/uthcode/interfaces/desktop/bridge.py`
- `eval/workloads.py`（仅受 request/helper 边界影响时）
- `tests/test_t09_1_context_protocol_e2e.py`
- `tests/test_w05_diagnostics.py`
- `tests/test_application_runs.py`
- `tests/test_application_runtime.py`
- `tests/test_desktop_bridge.py`

### 删除文件

- 无。

### 文件职责及实施内容

- `request_preparation.py` 持有 model limit、output reserve、token count 与 final ordinary request preparation 纯 helper；不持 Application state。
- `application/compaction.py` 持有 L4/L5 prompt、payload、tool-free request、Provider run 和 terminal usage 提取；不拥有 durable Timeline。
- baseline 与 candidate 均从同一个 ordinary request 构建路径计量，并固定为 exact/exact 或 local/local；prospective 构建不得把临时 snapshot/status/diagnostics 发布为当前状态。
- `after >= before` 时返回稳定 `no_reduction` 等价结果且不 append；有效 candidate append 后重新构建并统计 Current Working Context。
- 使用 T01 Core plan 驱动 oversized subpass/fold；全部子阶段成功后才形成一个 candidate，失败/取消/invalid 时零 durable write。
- manual `/compact` 复用 retained target 与既有 epoch limit；无 eligible epoch 为 `no_change`，有效提交后的 bounded stop 保留 completed/partial-success 语义并只在 diagnostics 记录原因。
- 删除或改造 `record_exact_usage()` 的旧 current-context 覆盖路径。普通 Agent 请求从同一 Turn 的累计 `UsageUpdated` 非负 delta 派生 last request usage；Compact/L5 从各自 terminal usage 更新同一个 Application-owned display-safe projection。
- Provider 字段无法区分未提供与零时保持 `not_available`；Bridge 只 allowlist 新 DTO，不暴露 raw details。
- 记录 Conversation projection fingerprint/change，仅作 process-local telemetry。
- `UthCodeApplication`、Session、Run 与 durable commit authority 留在 `generation.py`。

### 依赖任务

- T01。

### 参考资料定位

- F03 原始需求第 4.1、4.3、4.4、6.2～6.5、7/W02、10.1～10.2、11 节。
- `docs/context/A03-State/State-Context.md`、`docs/context/A04-Orchestration/Orchestration-Context.md`。
- 用户追加决定：方案 A，Last Provider Request Usage 覆盖 ordinary 与 Compact/L5。

### 完成边界

- Current Context 与 Last Provider Request Usage 的来源和生命周期完全分离；所有 Compact candidate 在 durable append 前完成真实 ordinary request reduction 验证。
- `generation.py` 只拆一次且保留唯一 Application authority；Context 定向、run usage、Bridge 与 diagnostics tests 通过。

## T03：Renderer state 与 App 生命周期收敛

### 任务目标

迁出已经独立成形的纯 helper 和 runtime lifecycle owner，同时保持唯一 Renderer reducer、per-Session 投影与现有事件/导航语义。

### 新增文件

- `desktop/src/renderer/state-normalization.ts`
- `desktop/src/renderer/state-session.ts`
- `desktop/src/renderer/text-normalization.ts`
- `desktop/src/renderer/useRuntimeLifecycle.ts`
- `desktop/tests/renderer-state.test.ts`
- `desktop/tests/renderer-runtime-lifecycle.test.tsx`
- `desktop/tests/renderer-session.test.tsx`

### 修改文件

- `desktop/src/renderer/state.ts`
- `desktop/src/renderer/App.tsx`
- `desktop/tests/renderer.test.tsx`
- `desktop/package.json`（仅将新增测试纳入正式 `npm test`）

### 删除文件

- 无。

### 文件职责及实施内容

- `state.ts` 继续定义 RendererState、action 与唯一 reducer；新 helper 文件只做 DTO/replay normalize、mojibake recovery、per-Session snapshot/catalog order 等纯计算，不持 store/reducer。
- `useRuntimeLifecycle.ts` 接管而非复制 runtime generation/owner/tail、pending operation、AbortController、stale guard 与 terminal convergence refs；只有 App 一个生产调用方。
- AgentEvent subscription 仍 dispatch 到同一 reducer；Session A/B background event、navigation、busy/ownership 与 settings rebootstrap 语义不变。
- 从 giant renderer test 迁移相应 contract，并确保新增文件真实进入 `npm test`。

### 依赖任务

- T02。

### 参考资料定位

- F03 原始需求第 6.6～6.7、7/W03、11、12 节。
- `docs/context/GUI/GUI-Context.md`。

### 完成边界

- App 主要负责页面组合与 action wiring；runtime operation 只有一个 owner，Renderer state 只有一个 authority。
- stale operation、terminal race、Session isolation 与 reducer baseline tests 通过。

## T04：Settings 单 Modal 与 Markdown 高频交互

### 任务目标

统一 Settings 编辑生命周期，拆出安全 Markdown，并以窄 clipboard API 提供代码复制和不抢滚动的新消息入口。

### 新增文件

- `desktop/src/renderer/SettingsEditorModal.tsx`
- `desktop/src/renderer/settings-draft.ts`
- `desktop/src/renderer/safe-markdown.tsx`
- `desktop/tests/renderer-settings.test.tsx`
- `desktop/tests/renderer-chat.test.tsx`

### 修改文件

- `desktop/src/renderer/SettingsView.tsx`
- `desktop/src/renderer/ChatTimeline.tsx`
- `desktop/src/renderer/App.tsx`
- `desktop/src/renderer/app.css`
- `desktop/src/renderer/locales/zh-CN.ts`
- `desktop/src/renderer/locales/en.ts`
- `desktop/src/desktop-api.ts`
- `desktop/src/preload.ts`
- `desktop/src/main.ts`
- `desktop/tests/preload.test.ts`
- `desktop/tests/renderer.test.tsx`
- `desktop/tests/render-settings-interactions-visual-fixture.tsx`
- `desktop/scripts/build-settings-acceptance.mjs`
- `desktop/scripts/cdp-settings-acceptance.mjs`
- `desktop/package.json`（纳入新增测试）

### 删除文件

- 无；删除 nested modal 分支和旧 `copySessionId` 专用入口。

### 文件职责及实施内容

- Provider→Model 使用同一个 modal root、focus trap、inert background、return focus 与 transaction；Back、Cancel、Save 行为符合冻结语义。
- draft helper 不读 API/DOM；API Key 明文只存在于用户显式 reveal 后的 editor-local 生命周期，取消/关闭/卸载清除。
- `safe-markdown.tsx` 保持现有安全子集、覆盖面、safe URL 与 no raw HTML；Code Fence 显示 language 并通过传入的 `copyText` 复制原文。
- 将 main/preload/API 的 Session 专用 clipboard IPC 收敛为经 sender/frame/origin 校验的 `copyText(text)`，Renderer 不取得 Electron 对象。
- ChatTimeline 保持 near-bottom follow；用户离底后 streaming 不抢回，新内容显示明确入口，点击后滚底并恢复 follow-tail。
- 更新 Settings CDP fixture/selector 与中英文、CSS；不得让 `safe-markdown` 直接读取全局 Electron API。

### 依赖任务

- T03。

### 参考资料定位

- F03 原始需求第 4.6～4.7、6.8～6.9、7/W04、11 节。
- `docs/context/GUI/GUI-Context.md` 与既有 Settings acceptance scripts。

### 完成边界

- Settings 只有一个 modal lifecycle；Session ID 与 Code Fence 使用同一个窄 clipboard adapter。
- Settings focus/rollback/secret、Markdown safety/language/copy、scroll preservation tests 与现有 CDP Settings flow 通过。

## T05：可拖拽布局、Focus Mode 与视觉层级

### 任务目标

实现可持久化面板宽度、瞬时 Focus Mode、Runtime 双 usage 展示与一致视觉层级，并保持所有响应式和无障碍回归。

### 新增文件

- 无；仅在现有 visual fixture 无法清晰承载新交互时新增一个有真实 runner 调用的专用 fixture。

### 修改文件

- `desktop/src/desktop-api.ts`
- `desktop/src/desktop-preferences.ts`
- `desktop/src/renderer/state.ts`
- `desktop/src/renderer/App.tsx`
- `desktop/src/renderer/Sidebar.tsx`
- `desktop/src/renderer/RuntimePanel.tsx`
- `desktop/src/renderer/Composer.tsx`
- `desktop/src/renderer/app.css`
- `desktop/src/renderer/locales/zh-CN.ts`
- `desktop/src/renderer/locales/en.ts`
- `desktop/tests/preload.test.ts`
- `desktop/tests/runtime-process.test.ts`
- `desktop/tests/renderer.test.tsx` 及 T03 拆出的相关测试
- `desktop/tests/render-populated-visual-fixture.tsx`
- `desktop/scripts/cdp-driver.mjs`
- `desktop/scripts/cdp-packaged-visual-acceptance.mjs`

### 删除文件

- 无。

### 文件职责及实施内容

- 新增 `sidebarWidth`、`runtimePanelWidth` preference default/migration/validation；Pointer move 只改 visual state，稳定边界才写 IPC。
- wide mode separator 支持 Pointer 与键盘、ARIA、min/max；按 viewport/CSS pixel 在 resize/zoom 后 clamp，并保证 Chat 最小可用宽度；narrow mode 禁用 resize且保留 overlay。
- `focusMode` 只属于 Renderer transient state；进入隐藏左右面板，退出恢复持久 panel mode/width，不写 preference。
- RuntimePanel 分组且分别显示 T02 的 Current Context 与 Last Provider Request Usage，不重算 authority。
- 收敛真实 design token 与 monospace 标识；新增 motion 轻量且在 reduced-motion 下关闭。
- 扩展 CDP/fixture 覆盖 drag persistence、reload、Focus transient/restore、keyboard resize 和双 usage 显示。

### 依赖任务

- T04。

### 参考资料定位

- F03 原始需求第 4.5、6.4、7/W05、9.3、10.3、11 节。
- `docs/context/GUI/GUI-Context.md`。

### 完成边界

- 两侧宽度可操作、可恢复且不会挤毁 Conversation；Focus Mode 不改变 durable preference。
- wide/narrow、zoom、主题、语言、IME、keyboard、focus、ARIA、overlay、reduced-motion tests/acceptance 通过。

## T06：非 Desktop/TUI 高置信瘦身与测试收口

### 任务目标

删除确认无语义的 Application wrapper 与迁移遗留，只合并失去独立价值的重复测试。

### 新增文件

- 无。

### 修改文件

- `src/uthcode/application/context.py`
- `src/uthcode/application/generation.py`
- `eval/workloads.py`
- 引用 `uthcode.application.history` 或旧 compaction path 的相关 tests。

### 删除文件

- `src/uthcode/application/history.py`
- 仅服务已删除同步 compaction 入口且无独立 contract 的 fixture/test。

### 文件职责及实施内容

- 所有真实调用方直接使用 `core.history.transcript_entries_from_message()`，不保留 alias/facade。
- 扫描 T01/T02 迁移后的 re-export、helper、import、fixture 与 unreachable branch，确认无调用方后删除。
- 保留 `core/agent.py`、`application/sessions.py`、`integrations/session_files.py`、Provider factory/fake、权限/秘密/持久化/Hard Gate 与 legacy durable reader。
- 不重构 TUI；共享 contract 变化只做最小适配和回归。

### 依赖任务

- T02、T05。

### 参考资料定位

- F03 原始需求第 2.3、7/W06、12～13 节。
- `docs/context/A04-Orchestration/Orchestration-Context.md`。

### 完成边界

- history wrapper 和旧同步 compaction references 为零；没有为测试保留 production facade。
- 高价值安全、Session、Provider、Context 与 TUI/CLI regressions 保持。

## T07：[接入主流程] Context 与 Desktop 生产链集成

### 任务目标

确认 T01～T06 只形成一条正式调用链并删除所有被替代入口。

### 新增文件

- 无。

### 修改文件

- `src/uthcode/core/compaction.py`
- `src/uthcode/application/context.py`
- `src/uthcode/application/generation.py`
- `src/uthcode/application/runs.py`
- `src/uthcode/interfaces/desktop/bridge.py`
- `desktop/src/desktop-api.ts`
- `desktop/src/main.ts`
- `desktop/src/preload.ts`
- `desktop/src/renderer/state.ts`
- `desktop/src/renderer/App.tsx`
- `desktop/src/renderer/SettingsView.tsx`
- `desktop/src/renderer/ChatTimeline.tsx`
- `desktop/src/renderer/RuntimePanel.tsx`
- T01～T06 已列的跨层集成测试文件；只处理接入缺口，不重新组织已完成职责。

### 删除文件

- 接入后确认无调用方的旧入口、旧测试适配或重复投影。

### 文件职责及实施内容

- 验证 ordinary/auto/manual/overflow/L5 共用 Application/Core compaction 主链，oversized 与 no-reduction 均在 durable append 前收口。
- 验证 ordinary 与 Compact/L5 usage 更新同一 Last Provider Request Usage，Current Context 只来自重新构建的普通请求。
- 验证 Desktop status→Bridge→reducer、runtime hook、single Settings modal、copyText、width/focus/scroll 均只有一个 owner。
- 执行跨层 identity、stale response、Session background、secret 与 persistence 检查；删除被替代入口。

### 依赖任务

- T01～T06。

### 参考资料定位

- F03 原始需求第 5.2、10、13、17 节。
- A03、A04 与 GUI 当前上下文。

### 完成边界

- Headless、CLI/TUI、Desktop 均通过同一 Application 边界；无第二 authority、兼容双轨、Interface→Core 越权或 SDK 穿透。

## T08：[端到端验证] 全量回归、measurement 与 Desktop 验收

### 任务目标

从真实入口生成 F03 所有自动、measurement、CDP/visual 与 packaged acceptance 证据。

### 新增文件

- 仅允许新增当前 acceptance runner 实际引用的报告或 fixture；生成报告放入既有忽略的验收输出目录，不纳入业务源码。

### 修改文件

- `desktop/scripts/cdp-driver.mjs`
- `desktop/scripts/cdp-packaged-visual-acceptance.mjs`
- 对应 visual/settings fixture 与 tests（仅补齐缺失验收能力）
- `eval/workloads.py` 或既有 Context measurement 入口（仅当前测量需要）

### 删除文件

- 无；清理仅限本次明确生成且可再生成的临时验收产物。

### 文件职责及实施内容

- 执行 Python full pytest、architecture、compileall、pip check；执行 Desktop typecheck、正式 npm test、package 与适用 make/packaged smoke。
- 运行 exact/local before-after、summary 更短但 ordinary 不缩小、oversized、malformed multi-turn、projection changed/cache diagnostics measurement。
- 运行 wide/narrow、dark/light、zh/en、100/125/150% zoom、reduced-motion、drag persistence、Focus transient、Settings focus/secret、Code Fence copy、scroll preservation、keyboard/IME/ARIA acceptance。
- 每个未运行的真实 Provider、干净 Windows 或人工视觉场景必须写明环境、原因与风险，不得标记通过。

### 依赖任务

- T07。

### 参考资料定位

- F03 原始需求第 7/W07、11、17 节。
- `desktop/package.json` 与 `desktop/scripts/cdp-*.mjs`。

### 完成边界

- 所有可用自动和真实入口证据有命令、exit code、精确计数与报告路径；关键矩阵无未解释异常、console error 或 stderr。

## T09：[遗留负担清理] 否定扫描、文档与冻结收口

### 任务目标

完成否定扫描、文档同步、Checklist/Feedback 收口和 UTF-8 验证，不自行归档或执行 Git 写操作。

### 新增文件

- 无；只更新本 Worker 的既有 Feedback。

### 修改文件

- `docs/Context-Index.md`
- 与实际改动对应的 `docs/context/**`、`docs/user-manual/**`、`docs/core-design/**`、`docs/Tools.md`（按维护映射实际需要）
- 本 Checklist（只允许勾选已有项）
- `feedback/W07-acceptance-closeout-feedback.md`

### 删除文件

- 无；不得移动或归档 F03、F02、T10 或任何历史工作包。

### 文件职责及实施内容

- 扫描旧 compaction path、history facade、重复 store/runtime/modal、无调用方 export/helper、循环依赖、Interface→Core、SDK import 与未来占位抽象。
- 按最终 `src/ + tests/` 同步当前事实；全量盘点 `docs/work/` 与 archive 后更新 Context Index 状态。
- 核对 `docs/OutstandingDebtList.md`，无真实触发变化时保持不变。
- 执行 UTF-8/mojibake/fence、内部链接、秘密示例、`git diff --check` 与 diff scope 检查。
- 汇总结构收敛前后主要职责/file size 作为辅助证据，不设 LOC KPI。

### 依赖任务

- T08。

### 参考资料定位

- `docs/README.md`、`docs/rules/WorkPackageRules.md`、`docs/OutstandingDebtList.md`。
- F03 原始需求第 12、15、17、19～20 节。

### 完成边界

- Feedback 与 Checklist 精确反映已验证和未验证项，当前事实文档一致，UTF-8 检查通过。
- 未自动归档，未执行未经用户明确要求的 commit/push/merge/rebase/tag/release。
