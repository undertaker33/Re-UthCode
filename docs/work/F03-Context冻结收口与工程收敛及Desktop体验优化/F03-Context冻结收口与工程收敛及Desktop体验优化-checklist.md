# F03：Context 冻结收口、工程收敛与 Desktop 体验优化 Checklist

## T01：Core Compaction 冻结与旧路径清理

- [x] 执行 `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_context_compaction.py tests/test_context_compiler.py tests/test_t09_1_context_protocol_e2e.py -q`，全部用例通过。
- [x] multi-turn plain text、top-level summary、string entry、缺 refs、缺 coverage、数量/顺序/`turn_id` 不匹配均被拒绝；合法显式 entries 可继续。
- [x] oversized oldest complete Turn 能形成 bounded subpass plan，最终 candidate 只有一个 Fine、使用原 Turn identity 且 refs 覆盖完整 Turn。
- [x] oversized subpass 的 failure、cancel、invalid result 均不返回最终 candidate，不产生 durable ID/Timeline record。
- [x] 执行对 `ContextCompactor.compact`、`_compact_locked` 及旧 rolling helper 的 active source/test 引用扫描，返回 0 条；production L4/L5 single-flight 仍存在并有测试。
- [x] `core/context.py` 不再拥有 compaction 执行主体，`core/compaction.py` 为唯一 Core compaction 模块；公共导出无 legacy alias。

## T02：Application Working Context、manual Compact 与 usage 双投影

- [ ] 执行 `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_application_runs.py tests/test_application_runtime.py tests/test_t09_1_context_protocol_e2e.py tests/test_w05_diagnostics.py tests/test_desktop_bridge.py -q`，全部用例通过。
- [ ] exact capability 可用时 before/after 均为 exact；缺失或受控失败时两者均为 local，不出现 source 混用。
- [ ] 构造 summary token 变短但 prospective ordinary request 不变或变大的场景，确认 candidate 返回 `no_reduction` 等价结果且 Timeline append 为 0。
- [ ] oversized subpass 通过同一 tool-free、Hard-gated Provider path 执行；中途失败/取消/invalid 时 durable write 为 0，成功时只提交一个完整 Turn Fine。
- [ ] manual `/compact` 在一次调用内继续到 retained target 或既有 epoch limit；无 eligible history 为 `no_change`，已有有效 commit 后 bounded stop 仍为 completed/partial-success 且原因只在 diagnostics。
- [ ] Compact commit 后重建 ordinary request；Current Working Context 显示新请求的 exact/local projection，不再被上一请求 usage 覆盖。
- [ ] 同一 Turn 连续累计 `UsageUpdated` 产生正确的非负 request delta；新 Turn 从零基线开始，pause/resume 不丢边界。
- [ ] ordinary request 与 Compact/L5 terminal usage 都能更新同一个 Last Provider Request Usage；无法证明字段存在时为 `not_available`，Bridge 不包含 raw details。
- [ ] Conversation projection full→reduced 与 reduced→full 可观察 fingerprint/change；该值不持久化、不改变 compaction policy。
- [ ] `request_preparation.py`、`application/compaction.py` 均有多个真实调用方且不拥有 Application/Session/Timeline state；`generation.py` 仍是唯一 `UthCodeApplication` authority。

## T03：Renderer state 与 App 生命周期收敛

- [ ] 在 `desktop` 执行 `npm run typecheck` 与 `npm test`，新增 state/lifecycle/session 测试由正式脚本执行且全部通过。
- [ ] `state.ts` 仍是唯一 RendererState/reducer authority；normalize/text/session helper 均为纯函数，不持 store、reducer 或持久状态。
- [ ] `useRuntimeLifecycle` 是 runtime generation/owner/tail、AbortController、stale guard 与 terminal convergence 的唯一 owner，App 未保留重复 refs。
- [ ] Session A/B background events、visible owner switch、stale operation、terminal event/result race 与 Settings rebootstrap 回归通过。
- [ ] 从 `renderer.test.tsx` 迁出的高价值竞态、ARIA、Session identity/ordering 覆盖在新测试中可定位且没有被删除。
- [ ] 执行重复 store、EventBus、RuntimeManager 和第二 reducer 的否定扫描，无 F03 新增生产命中。

## T04：Settings 单 Modal 与 Markdown 高频交互

- [ ] 在 `desktop` 执行 `npm run typecheck`、`npm test`、`node scripts/build-settings-acceptance.mjs` 和 `node scripts/cdp-settings-acceptance.mjs`，全部成功并记录报告。
- [ ] Provider→Model→Back 使用同一个 modal root/focus trap/return-focus owner；Cancel 回滚 transaction，Save 只走现有 Configuration write。
- [ ] reveal/hide 不标记 Key touched；replacement 失败保留草稿、成功按既有写入收敛；关闭/取消/卸载后明文不在 reducer、preferences、日志或 snapshot 中。
- [ ] Markdown 现有 inline/code/emphasis/link/fence/heading/table/quote/list/paragraph 子集和各 Timeline kind 覆盖保持，raw HTML 与 unsafe URL 仍被拒绝。
- [ ] fenced code 显示正确 language label；Copy 经 `copyText` 复制逐字一致的原始代码，并有成功/失败局部反馈。
- [ ] Session ID copy 与 Code Fence copy 共用 `copyText`；main process sender/frame/origin 校验仍生效，Renderer 无 Electron/clipboard 对象。
- [ ] 用户离开底部后 streaming 不改变 scroll position并显示新消息入口；点击后滚到底并恢复 near-bottom follow-tail。
- [ ] zh-CN/en、keyboard、focus、ARIA、dark/light 下 Settings、Code Fence 与新消息入口无缺文案或不可达控件。

## T05：可拖拽布局、Focus Mode 与视觉层级

- [ ] 在 `desktop` 执行 `npm run typecheck` 与 `npm test`，preference migration、layout reducer、Pointer/keyboard resize、Focus 与 RuntimePanel tests 全部通过。
- [ ] 旧 preference 文档无 width 字段时加载默认值；合法宽度可写回/重载，非法或越界值按明确规则恢复或 clamp。
- [ ] wide mode 左右 separator 支持 Pointer 与 keyboard，具有正确 role/value/label；拖动期间不高频写 preference，只在稳定边界写一次。
- [ ] resize、窗口变化及 100%/125%/150% zoom 后宽度按 viewport 重新 clamp，Conversation 保持最小可用宽度；narrow mode 禁用 resize 且 Runtime overlay 回归通过。
- [ ] Focus Mode 隐藏 Sidebar/Runtime；退出后恢复进入前的 `panelMode` 与宽度，整个过程没有 preference write。
- [ ] RuntimePanel 分组展示运行状态、环境、标识，Current Context 与 Last Provider Request Usage 数值和 unavailable 状态分离。
- [ ] Sidebar show-more、catalog order、overlay Escape/outside-click/focus restore、IME、focus-visible、ARIA/live region 回归通过。
- [ ] dark/light/system、zh-CN/en 与 reduced-motion 下新增视觉/transition 无横向裁切、乱码、缺文案或非必要动画。

## T06：非 Desktop/TUI 高置信瘦身与测试收口

- [ ] 执行 `rg -n "uthcode\.application\.history|application/history|ContextCompactor\.compact|_compact_locked" src tests eval desktop/src desktop/tests`，active 旧入口命中为 0 或逐条证明是合法否定测试。
- [ ] `src/uthcode/application/history.py` 已删除，所有真实调用方直接使用 Core 现有转换函数，且无 re-export/alias。
- [ ] 迁移后无调用方 helper/import/fixture 已删除；没有仅为历史测试保留 production facade。
- [ ] `core/agent.py`、`application/sessions.py`、`integrations/session_files.py`、Provider factory/fake、legacy durable reader 未被无关拆分或删除。
- [ ] Permission、Secret、Hard Gate、Session authority/durability、Provider protocol、pause/resume/cancel 与 TUI/CLI 定向回归通过。
- [ ] 合并的重复测试均有等价 contract 覆盖和清晰故障定位证据；高价值安全/持久化回归数量未下降。

## T07：[接入主流程] Context 与 Desktop 生产链集成

- [ ] 从 ordinary、manual、auto、overflow 与 L5 真实入口验证只有一条 Application/Core compaction 链，Provider request 均 tool-free 且先 Hard Gate。
- [ ] no-reduction、malformed、oversized failure/cancel 都在 durable append 前收口；有效 commit 后 Timeline、Current Context 与 Last Provider Request Usage 按各自权威更新。
- [ ] 从真实 Desktop dev shell 验证 `Renderer → DesktopApi → Main/Preload → DesktopBridge → Application → Core` identity、事件顺序与 terminal convergence 一致。
- [ ] Session background runtime、Settings rebootstrap、clipboard、layout preference、Focus、scroll 与 status 均使用唯一 owner，无第二 Run/Application/store/modal。
- [ ] Headless、CLI、TUI、Desktop、Permission、Session persistence/recovery、Context Gate 与配置安全回归通过。
- [ ] 执行架构和 import 扫描，确认无循环依赖、Interface→Core/Integration 越权或 Provider SDK 类型穿透。

## T08：[端到端验证] 全量回归、measurement 与 Desktop 验收

- [ ] 执行 `conda run --no-capture-output -n re-uthcode python -m pytest -q`，记录 exit code 与精确 passed/failed/skipped 数量。
- [ ] 执行 `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q`、`python -m compileall -q src tests` 与 `python -m pip check`，全部退出码 0。
- [ ] 在 `desktop` 执行 `npm run typecheck`、`npm test`、`npm run package`，记录 exit code、精确测试数量和 packaged executable 路径；`npm run make` 若当前环境可用也记录结果，否则明确未验证原因。
- [ ] measurement 报告包含 exact 与 local before/after、无 reduction 拒绝、oversized、multi-turn malformed、projection changed 和 cache read/write availability，且不建立固定产品阈值平台。
- [ ] CDP/visual 与 packaged acceptance 覆盖 wide/narrow、dark/light、zh-CN/en、100/125/150% zoom、reduced-motion，无 unexplained console/renderer exception/stderr。
- [ ] acceptance 覆盖 drag persistence/reload、Focus transient/restore、Settings Provider→Model→Back 与 secret、Code Fence language/copy、user-scroll/new-message/button、keyboard/IME/ARIA。
- [ ] 真实 Provider、干净 Windows、人工视觉或其他当前不可用场景在 Feedback 中列出环境、原因和风险；未运行项未勾选、未描述为通过。

## T09：[遗留负担清理] 否定扫描、文档与冻结收口

- [ ] 执行旧 compaction/history、重复 authority、Manager/EventBus/Registry、无调用方 public surface、SDK import 与未来占位扫描，所有命中为 0 或逐条解释。
- [ ] 按 `docs/README.md` 维护映射同步所有受影响用户手册、核心设计、Tools 与 A03/A04/GUI 当前事实文档，内容与最终代码一致。
- [ ] 全量盘点 `docs/work/` 与 `docs/work/archive/` 后更新 `docs/Context-Index.md`；只有 Checklist 全部完成且 Feedback 齐全时才将 F03 标为 `implemented_unarchived`。
- [ ] 核对 `docs/OutstandingDebtList.md`；F03 仍无新增、变更或回补欠账时保持其内容不变。
- [ ] 对 F03 工作包和所有实际修改 Markdown 运行 UTF-8 guard，确认可解码、无 replacement/常见乱码且 fenced code block 成对。
- [ ] 执行文档内部链接、秘密示例、`git diff --check` 与 diff scope 检查；其他冻结工作包无修改。
- [ ] W01～W07 Feedback 齐全并记录改动、机制、文件、精确测试、Checklist、偏差、未完成项、风险与清理结果；返工只在原文件末尾追加。
- [ ] 记录结构收敛前后主要职责/file size 变化，不设置或声称 LOC KPI。
- [ ] 未自动归档 F03/F02/T10，未执行未经用户明确要求的 commit、push、merge、rebase、tag 或 release。
