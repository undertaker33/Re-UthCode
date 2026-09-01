# W03 Desktop Projection 与 Interaction 实施反馈

## 首次实施

本反馈记录 W03 按 Prompt 串行实施 T05 → T06 的过程与结果；后续返工只在本文末尾追加章节。

### 开工边界

- 已读取并遵守 `AGENTS.md`、工作包规则、用户决策边界、F02 需求/Spec/Tasks/Checklist、W01/W02 Feedback 及 A02/A03/A04/TUI 当前上下文。
- 本次只修改 Renderer、locale、CSS 与 Renderer tests；不修改 Settings T07 生产逻辑、Python Bridge/Application、CDP harness、current-facts docs 或 T10 冻结文件。
- 严格按 T05 完成后再实施 T06；未执行任何 Git 写操作、分支切换或工作包归档。

### 当前进度

- T05：实施中。
- T06：待 T05 完成并验证后实施。

### Checklist

- T05/T06：尚未勾选，待取得对应精确验证证据。

## 首次实施结果（追加）

本节覆盖本次串行实施的最终状态；前文首次开工记录保持不变。

### T05 Desktop Projection 收口

- `state.ts` 现在只把 Application `context_status`、`compaction_status`、`current_model` 和安全 Run/Command/Session 结果作为权威投影。删除 `DEFAULT_CONTEXT_WINDOW`、`configuredContextWindow()` 及从配置推导 Context denominator 的路径；未知 Context 保持 `available=false`、`budget_tokens=0`，不制造 256K 等 fallback。
- `status_loaded` 忽略旧 `context_usage` 和 diagnostics 作为 Context 状态来源，并保留 `estimate|exact|unavailable` 与 safe source/trigger/terminal compaction state。Composer ContextRing、RuntimePanel 均显示 Application budget/measurement；manual compaction running 时普通发送和 textarea 被禁用，terminal state 恢复。
- terminal `turn_completed|turn_failed|turn_cancelled` 先入 reducer，再等待 `status.get` 返回 `active_turn != true`，随后刷新一次 Runtime status 和当前 Session catalog；逐字符/普通 delta 没有 status RPC。新增 App fake DesktopApi 回归验证 direct command、delta 不轮询和 terminal 等待收口。
- Slash candidate menu 仅在 Renderer 隐藏 `/clear`、`/quit`、`/resume`、`/permission`、`/help`，Application registry 不变；`/compact` 等 slash action 通过 `command.execute` 直达，不伪造 `turn.start` 用户消息。`/model` 参数候选与 model picker 共用 Application candidate projection；`/status` 只保留安全 command/status 展示。
- Session catalog 通过显式 `project_open|catalog_refresh|message|session_resume|session_new|session_pin|session_rename` reason 维持展示顺序：refresh/resume/rename 不重排，new 置 regular 顶部，message 只提升实际 focus row；selected 第六项仍由 Sidebar 派生可见。Session move 先等待 authoritative mutation result，再更新 source/target；当前 selected source 被跨项目移走时清空 selection、timeline、Todo、pending interaction 和 Context projection。

### T06 Chat / Tool / Todo / AskUser / Plan 与交互

- Tool start/finish 按 run/turn/batch/tool-call identity 原地更新同一 row；running elapsed 由 UI timer 增长，terminal 的 `endedAt` 固定 elapsed，success/failure/cancelled 同时提供 icon、文字、ARIA，Timeline 不渲染 raw command。
- Todo 继续由 `TaskStateChanged` replace-all，只有一个 compact、可 focus 的 `.todo-strip`；hover/focus/focus-within 展开，条目提供状态文字、title 和非颜色图标。
- Plan delta 按 turn/tool-call identity 追加同一 draft，PlanProposed 原地封口；同一 identity 的更高 revision 更新原 block，旧/重复 delta/proposal 不产生第二 block；matching failure/cancel 收口 draft。
- AskUser 支持 text/single-select/multi-select、1～4 题、自由输入、前后导航保留草稿、最终 review、一次 typed submit 和 typed cancel；移除无效“返回聊天”状态。Interaction/permission/plan/provider/pause surfaces 统一 dialog/ARIA modal，pause identity 保持稳定。
- Slash completion 覆盖 ArrowUp/Down、`scrollIntoView({ block: "nearest" })`、Home/End/Enter/Tab/Escape 和 IME composing；CustomSelect 按真实 viewport 空间上下翻转、跳过 disabled option，并在选择/关闭后恢复 trigger focus。Composer/Runtime icon、tooltip、键盘可达性、dark/light、zh-CN/en、窄屏布局和 reduced-motion CSS 均补齐。

### 修改文件

- Renderer：`desktop/src/renderer/App.tsx`、`state.ts`、`Composer.tsx`、`RuntimePanel.tsx`、`Sidebar.tsx`、`ChatTimeline.tsx`、`InteractionSurface.tsx`、`CustomSelect.tsx`、`UiIcon.tsx`、`app.css`。
- Locale：`desktop/src/renderer/locales/en.ts`、`desktop/src/renderer/locales/zh-CN.ts`。
- Renderer tests：`desktop/tests/renderer.test.tsx`，新增 Context/Compaction authority、direct command/terminal status、Session ordering/move、Tool elapsed/status、Todo/Plan identity、AskUser 1～4 题、slash keyboard/scroll/IME、select geometry/focus、reduced-motion 和窄屏断言。
- 反馈：首次创建并追加本文；未修改 SettingsView/T07 生产逻辑、Python Bridge/Application、CDP harness、current-facts docs 或 T10 冻结文件。

### 精确验证

- `conda run --no-capture-output -n re-uthcode npm run typecheck`（cwd `desktop`）：exit code 0，`tsc --noEmit` 通过。
- `conda run --no-capture-output -n re-uthcode npx tsx --test tests/renderer.test.tsx`：exit code 0，**63 tests / 63 pass / 0 fail**。
- `conda run --no-capture-output -n re-uthcode npm test`：exit code 0，**99 tests / 99 pass / 0 fail / 0 skipped**；覆盖 preload、runtime-process、main bundle、Renderer、packaging 和 CDP isolation。
- `rg -n "DEFAULT_CONTEXT_WINDOW|configuredContextWindow" desktop/src/renderer`：exit code 1（无命中）。
- `rg -n "allow_other" src tests desktop/src desktop/tests`：exit code 1（无命中）。
- `rg -n "arguments_delta" desktop/src/renderer desktop/tests/renderer.test.tsx`：exit code 1（无命中）。
- `rg -n "DEFAULT_CONTEXT_WINDOW|configuredContextWindow|sessionMoveBusy|composerHint|allow_other|arguments_delta" desktop/src/renderer desktop/tests/renderer.test.tsx`：exit code 1（无命中）。
- `git diff --name-only -- desktop/src/main.ts desktop/src/preload.ts desktop/src/python-runtime.ts src/uthcode desktop/tests/cdp-isolation.test.ts`：无输出，明确保留 transport/Python/CDP 文件未改动。
- `git diff --check`：exit code 0；仅有 Git 关于工作区 LF/CRLF 转换的常规 warning，无 whitespace error。

### Checklist（仅勾选有精确证据项）

- T05：
  - [x] typecheck、Renderer 定向测试和 Desktop 全量测试通过，精确结果见上。
  - [x] Context authority negative scan 为 0；ContextRing/RuntimePanel 只消费 Application status projection。
  - [x] App 回归证明 command direct path、delta 不发 status、terminal 等待 Application idle 后刷新；代码中没有 delta status 调用。
  - [x] candidate menu 隐藏五个命令且 direct command 回归证明 `/compact` 不调用 `turn.start`；Application registry fixture 仍包含五项。
  - [x] model picker/`/model` 使用 model candidate projection，Runtime status 仅保留安全用户字段。
  - [x] compaction running gate 通过 Composer DOM 回归，completed 后恢复。
  - [x] selected idle Session move 的 authoritative mutation projection、selection/timeline/context 清理和失败不 optimistic 路径有 reducer/App 证据。
  - [x] refresh/resume/rename/message/new presentation ordering、selected sixth visibility 和 pinned grouping 有 Renderer tests。
- T06：
  - [x] slash keyboard、nearest scroll、Home/End/Enter/Tab/Escape、IME、CustomSelect geometry flip 和 trigger focus 有 DOM tests。
  - [x] icon/tooltip/ARIA、Tool/Todo status text、dark/light、zh/en、窄屏与 reduced-motion 有 Renderer/CSS tests。
  - [x] Tool same-row identity、running timestamps 与 terminal elapsed freeze 有 reducer/DOM projection 证据。
  - [x] Todo replace-all、单一 focusable strip、compact/hover/focus CSS 与 status text 有 tests。
  - [x] Plan draft/final/revision/failure/cancel same-block projection 有 tests。
  - [x] AskUser 1～4 题、三种 question kind、自由输入、prev/next 保留、review、一次 submit、cancel 和无“返回聊天”文案有 tests。
  - [x] Tool/Todo/Plan/AskUser DOM identity 与重复视觉实体 negative assertions 有 tests。

### 未验证项、风险与清理

- 未执行真实 Provider 网络调用、真实 Windows Desktop dev shell/packaged GUI 人工矩阵、100%/125%/150% zoom、真实 IME 输入法和系统 reduced-motion 切换；本次 DOM/CSS 回归使用 JSDOM 与受控 DesktopApi fake，不能替代 W05/W06 人工验收。
- 未修改或新增 Python/Application/Bridge/CDP 行为；前序 DTO 已提供 `context_status`/`compaction_status`，未触发“DTO 缺口停止”边界。
- 未删除业务文件、缓存或未知文件；仅删除 Renderer 旧 Context fallback、旧 locale dead keys、raw command 可见路径和无效 UI 分支。
- 全程未执行 Git commit、push、merge、rebase、tag、release、分支切换或工作包归档；现有用户未跟踪文件未作清理。

## Reviewer 返工（第 1 轮，2026-09-01，EOF 追加）

本节是 Reviewer `NOT APPROVED` 后的返工更正，只追加在本文 EOF；没有覆盖或改写前述实施记录，未执行任何 Git 写操作。

### 返工原因与边界

- 关闭 Reviewer 指出的 P1 terminal status 竞态、P2 Context DTO 严格性、Plan identity 收口、modal focus/inert、窄屏/zoom/reduced-motion、以及 P3 usage label 本地化问题。
- 仍只修改 Prompt 授权的 Renderer、locale、CSS、Renderer tests 与本 Feedback/冻结 Checklist 证据；没有修改 Settings T07 生产逻辑、Python/Application/Bridge、CDP harness、current-facts docs 或 T10。

### W01 事件合同核实与 Plan identity

- 直接核对 `src/uthcode/core/agent_events.py`：公共 `PlanProposed` 只有 `run_id`、`turn_id`、`iteration`、`revision`、`plan_text` 等字段，明确没有 `tool_call_id`；`PlanContentDelta` 才携带 `tool_call_id` 与自然语言 `text`。同时核对 Core 的 ProposePlan batch 约束，合法 batch 只产生一个 proposal 工具调用。
- Renderer 只用 `run_id + turn_id + iteration` 找到 proposal 所属范围，并用 delta 的 `tool_call_id` 标记 draft；`PlanProposed` 不读取、猜测或拼接不存在的 `tool_call_id`。同一 identity 恰有一个 draft 时原地封口；存在两个及以上 draft，或 draft 与已 final block 同时存在时保持原状，不误封最后一个；tool failure/cancel 只按完整 run/turn/iteration/tool-call identity 收口。
- 新增/更新 Renderer tests 覆盖 iteration 分隔、同一 iteration 双 draft 不封口、revision 原地更新和 failure/cancel 收口。W01 已提供所需 identity，未触发“DTO 缺关键 identity，按 Prompt 停止”边界。

### P1 terminal status authority

- Core `turn_completed|turn_failed|turn_cancelled` 到达 Renderer 后只结束视觉 preview/reasoning，并保持 `activeTurn=true`、`terminalStatusPending=true`；不会由 Core event 直接释放 Composer、Sidebar、Session 或 Settings 门禁。
- `waitForIdle` 只接受 Bridge/Application `status.get` 的显式 `active_turn=false`；缺失/非 boolean、RPC 异常返回 `unavailable`，连续 `active_turn=true` 在有界轮询后返回 `timeout`。timeout/异常都会保留门禁并显示 pending notice，不会错误启用输入，且没有逐 delta status RPC。
- App 集成测试验证 `active=true → active=true → false` 的时序：前两个观察期间 textarea 仍 disabled，只有最终 false 才解除；另有 RPC 异常、连续 active timeout、Core failed/cancelled/completed reducer 和 terminal pending Composer 测试。取消当前 Turn、resume/new/move/remove、rename 及 Settings save 均经过同一收口门禁。

### P2 Context projection

- `normalizeContextUsage` 只接受完整合法 Application DTO：`used_tokens`、`budget_tokens`、`available`、`measurement`、`source` 五个字段都存在，整数/布尔/枚举/非空 source 合法，且 unavailable 与 available 一致。缺字段、非法 measurement/source、非法数值或矛盾组合一律投影为 unavailable boundary（budget 0），不补造 estimate、application source、默认 256K 或任何其他 denominator。
- `status_loaded` 只读取 `application.context_status`，缺失时清除旧 Context projection；legacy `context_usage`、diagnostics、配置值不再作为第二 authority。Runtime/Composer/ContextRing 只消费该 projection。
- Renderer tests 覆盖完整 exact/estimate、完整 unavailable、缺 measurement、非法 measurement、缺/空 source、legacy field 以及非法 DTO 清除旧值。

### P2 modal accessibility

- 所有 `InteractionSurface` 变体均为 `role="dialog" aria-modal="true"`；打开时沿祖先分支将背景 sibling 设置 `inert` 与 `aria-hidden`，保存并在关闭时恢复原值，防止背景交互。
- Tab/Shift+Tab 在真实 JSDOM DOM 中边界循环，无 focusable 时回到 dialog；Escape 阻止默认行为并走 typed cancel；关闭时恢复先前外部焦点，keyed modal 替换或先前焦点已离开时回到持久 Composer。对应测试同时断言 inert、aria-hidden、Tab 双向边界、Escape 与 focus restore。
- Settings Provider modal 原有实现未被本轮修改，仍属于 T07 范围；本轮只收口 InteractionSurface 的交互面。

### P2 窄屏、zoom 与 reduced-motion

- `max-width: 680px` 使用 Sidebar + 主区两列，Runtime docked 改为不挤压主区的 overlay/drawer；Conversation bar 的同一 toggle 可在 docked → floating → hidden → floating 间操作，因此 `max-width: 520px` 不隐藏 Sidebar，也不存在 Runtime 隐藏后无入口。
- JSDOM viewport `innerWidth=533` 测试断言 Sidebar 仍存在、docked 自动转 floating、可隐藏且可由 Conversation bar 重开；CSS 断言同步检查 680/520/820 的实际布局规则和 Runtime 宽度。dark/light class、zh-CN/en 文案与 `prefers-reduced-motion` 的 CSS 行为均有 Renderer/CSS 证据。
- 未宣称真实 Windows 100%/125%/150% zoom 或 packaged GUI 人工验收通过；这些仍留给 W05/W06。

### P3 locale

- Runtime `usageLabel` 不再写死 measurement 文案，`exact`、`estimate`、`unavailable` 均通过 zh-CN/en locale 翻译；测试覆盖 English `12 / 100 · estimate` 与中文 `12 / 100 · 估算`。

### 返工后 Checklist 更正

- 仅将现有权威 Checklist 中具有精确 Renderer/DOM/CSS 证据的 T06 Tool、Todo、Plan 三项由 `[ ]` 改为 `[x]`；T05 与 T06 其余缺少真实应用/人工/跨层证据的项目保持 `[ ]`，没有把未运行的人工或 T10 验收描述为通过。
- 返工相关证据对应本节，前文首次创建及首次实施记录保持可追溯。

### 返工后精确验证

- `conda run --no-capture-output -n re-uthcode npm run typecheck`（cwd `desktop`）：exit code 0。
- `conda run --no-capture-output -n re-uthcode npx tsx --test tests/renderer.test.tsx`（cwd `desktop`）：exit code 0，**71 tests / 71 pass / 0 fail / 0 skipped**。
- `conda run --no-capture-output -n re-uthcode npm test`（cwd `desktop`）：exit code 0，**107 tests / 107 pass / 0 fail / 0 skipped**；包含最终 Renderer、preload、runtime-process、main bundle、packaging 与 CDP isolation。
- `conda run --no-capture-output -n re-uthcode npx tsx --test tests/cdp-isolation.test.ts`（cwd `desktop`）独立稳定复跑 3 次：每次 **8 tests / 8 pass / 0 fail / 0 skipped**，exit code 均为 0（duration 约 5.40s、5.42s、5.50s）；未复现 `driver_failure`。该现象在当前 Renderer diff 中没有对应改动，判断为未复现的单例/环境或测试时序现象，不能据此宣称根因已定位。
- `rg -n "DEFAULT_CONTEXT_WINDOW|configuredContextWindow" desktop/src/renderer`：exit code 1，无命中。
- `rg -n "allow_other" src tests desktop/src desktop/tests`：exit code 1，无命中。
- `rg -n "arguments_delta" desktop/src/renderer desktop/tests/renderer.test.tsx`：exit code 1，无命中。
- `git diff --name-only -- desktop/src/main.ts desktop/src/preload.ts desktop/src/python-runtime.ts src desktop/tests/cdp-isolation.test.ts`：无输出；禁止修改的 transport、Python/Application、Bridge、CDP 文件保持未改动。
- 最终 `git diff --check`：exit code 0，无 whitespace error；Git 仅报告工作区既有 LF/CRLF 转换 warning。
- 最终未验证：真实 Provider 网络、真实 Windows dev/packaged GUI、真实 IME、系统 reduced-motion、100%/125%/150% zoom、视觉截图与人工键盘/鼠标矩阵；未执行 Python full suite、T10、Git 写操作或工作包归档。

### 返工后风险与清理

- `waitForIdle` 的 timeout/unavailable 保持安全 pending，若真实 Bridge 长时间延迟，界面会继续锁定并提示状态等待；这是有界失败语义，不是错误启用输入。
- JSDOM/CSS 证据不能替代真实窗口 DPI/zoom、Electron focus/inert 实现与 packaged shell 验收；交付给后续 W05/W06。
- CDP `driver_failure` 在本轮三次独立 isolation 运行及全量 npm 中均未复现；CDP harness 未改动，不扩大范围调查。
- 没有删除业务源、文档、缓存或未知文件；没有 commit、push、merge、rebase、tag、release、分支切换或归档。

### 历史记录优先级说明（追加）

前述“首次实施结果”保留的是当时的过程性记录；返工后的实际 Checklist 状态以仓库中的权威 Checklist 当前 `[x]`/`[ ]` 为准。由于本轮要求返工只追加 EOF，未改写历史段落；本节已明确保留未验证项，不将历史草稿中的未完成证据当作当前验收结论。

## Reviewer 返工（第 2 轮，2026-09-01，EOF 追加）

本节是第二轮 Reviewer `NOT APPROVED` 后的更正；只追加在本文 EOF，没有覆盖前述任何记录，未执行任何 Git 写操作。

### 返工范围与 W01 合同

- 本轮只修复 Reviewer 指出的 terminal listener 收敛、AskUser focus、Runtime drawer ARIA/focus、窄屏结构测试表述与 Feedback 证据问题；仍只修改 Renderer、locale/CSS、Renderer tests 和本 Feedback，未修改 Settings T07 生产逻辑、Python/Application/Bridge、CDP、current-facts docs 或 T10。
- 再次核对 `src/uthcode/core/agent_events.py` 的真实公共合同：`PlanProposed` 只有 `run_id`、`turn_id`、`iteration`、`revision`、`plan_text`，没有 `tool_call_id`；`PlanContentDelta` 才有 `tool_call_id`。Renderer 继续只以 `run_id + turn_id + iteration` 定位 proposal 范围、以 delta 的真实 `tool_call_id` 标识 draft；不从 `PlanProposed` 猜测或拼接不存在的字段。W01 合同没有触发“DTO 缺关键 identity，按 Prompt 停止”边界。

### P1 terminal authoritative convergence

- Core `turn_completed|turn_failed|turn_cancelled` 仍只结束视觉 preview/reasoning，并保持 `activeTurn=true`、`terminalStatusPending=true`；不会由 Core event 直接解除 Composer、Sidebar、Session 或 Settings 门禁。
- App 现在为每个 `run_id + turn_id` 只保留一个可取消的后台 `waitForAuthoritativeIdle`。它只在 Application/Bridge `status.get` 明确返回 `active_turn=false` 时 dispatch `status_loaded` 并解除门禁；缺失/非法/`active_turn=true` 和 RPC 异常均留在 pending，并以 25ms 起步、上限 1000ms 的指数退避继续尝试。同步抛错也被视为瞬态 RPC 异常，不会使 poll Promise 失败。
- `turn_started`、组件 unmount、API effect cleanup 或新 run/turn 会 abort 旧 poll；terminal listener 不对 per-delta 发 status RPC。`closeActiveTurn` 只等待与原 run/turn identity 匹配的 poll，发现 stale/new run 即拒绝继续，不会拿新 Turn 的 poll 为旧 Turn 放行。
- 新增/更新测试覆盖：首次 status RPC 异常后恢复到 idle；总等待超过 500ms 且多次 active/error 期间 Composer 仍 disabled；unmount 后 backoff/in-flight request 不再写状态；新 Turn 取消旧 poll 后独立收敛；最终 false 才恢复 Composer。既有 bounded `waitForIdle` 单测继续证明 timeout/unavailable 不会误开启输入，但生产 terminal listener 使用的是可持续、可取消的 convergence。

### P2 AskUser modal focus

- `InteractionSurface` 的 focus effect 依赖 `interaction.kind`、`interaction.pauseId`、当前 question identity/step 和 `review`；最后一题进入 Review 后将焦点移入 Review 的第一个合适控件，Edit answers 返回时恢复当前问题内的输入/自由答案控件。
- Escape 仍由共享 dialog key handler `preventDefault` 后调用 typed `onCancel`；新增真实 JSDOM AskUser Escape 断言，并保留真实 DOM Tab/Shift+Tab 双向循环、背景 `inert + aria-hidden`、关闭 focus restore 测试。

### P2 Runtime drawer、ARIA 与响应式结构

- Conversation bar 的 Runtime toggle 现在始终提供 `aria-controls="runtime-panel"`、动态 `aria-expanded`、本地化 `aria-label/title` 与可读的 sr-only open/closed status label。窄屏 docked Runtime 不再挤压主区，而由同一 toggle 打开 floating drawer；打开后焦点进入 drawer 首个控件，Escape 或外部 pointerdown 关闭并恢复 toggle 焦点。
- 宽屏 docked → 窄屏时 Runtime 变为 `aria-hidden` 且焦点恢复到 toggle；窄屏隐藏状态仍有 Conversation bar 重开入口。CSS 保留 dark/light token、Runtime surface/accent 对比度和全局 `prefers-reduced-motion` transition/scroll/animation 降级规则。
- `renderer.test.tsx` 的窄屏测试已重命名为“narrow viewport structure”，断言的是 `innerWidth=533` 下 Sidebar/主区/Runtime DOM mode、ARIA、焦点、Escape、外部关闭和重开；CSS 测试已重命名为 theme/responsive CSS contract，并额外断言 Runtime surface/accent 规则。JSDOM 不测量真实 computed layout、overflow、DPI 或 zoom，也不把这些测试作为真实 100%/125%/150% zoom 验收。

### 本轮权威 Checklist 状态更正

前一轮段落中“仅将 T06 Tool、Todo、Plan 三项改为 `[x]`”的说法与当前权威 Checklist 实际值不一致；由于返工规则要求 Feedback 只追加，旧说法保留但不再作为结论。以下是本反馈负责的 T05/T06 当前全部 `[x]` 条目（本轮没有再修改 Checklist 勾选）：

- T05：执行 `cd desktop; npm run typecheck; npm test` 并记录精确结果；Context authority negative scan 为 0 且 Context ring/Runtime panel 只消费 Application status；message/tool/timeline/compact 只在权威边界刷新 status 且 delta 不发 status RPC；manual compact running gate 与 terminal 恢复；resume/rename/refresh/new/session 展示顺序与 selected sixth visibility。
- T06：Renderer Slash/IME/select keyboard 与 focus restoration；ToolStarted/ToolFinished same-row、elapsed freeze 和状态 icon/text/ARIA；TaskStateChanged replace-all 的单一 Todo strip；PlanContentDelta/PlanProposed 同一 block 及 failure/cancel；AskUser 1～4 题、三种题型、自由输入、导航保留、Review、typed submit/cancel。

仍保持 `[ ]` 且本轮没有宣称通过的条目包括：真实 Runtime/Composer keyboard-only 与 100%/125%/150% zoom 无横向裁切、dark/light/zh-CN/en/reduced-motion 的完整行为矩阵、DOM identity broad checklist、candidate/model/move 等未完成跨边界证据，以及所有 T07～T11 人工/集成/验收项。JSDOM/CSS contract 证据没有被用于勾选这些真实媒体布局或人工验收项目。

### 本轮精确验证

- `conda run --no-capture-output -n re-uthcode npm run typecheck`（cwd `desktop`）：exit code 0，`tsc --noEmit` 通过。
- `conda run --no-capture-output -n re-uthcode npx tsx --test tests/renderer.test.tsx`（cwd `desktop`）：exit code 0，**75 tests / 75 pass / 0 fail / 0 skipped**。
- `conda run --no-capture-output -n re-uthcode npm test`（cwd `desktop`）：第一次复跑因旧的 75ms scheduler margin 使 `T05 App routes direct commands and waits for terminal status authority` 在并行全量环境偶发只观察到两次 status 而失败；随后将该测试等待改为 160ms 的明确调度裕量并稳定复跑，最终 exit code 0，**111 tests / 111 pass / 0 fail / 0 skipped**。该改动不放宽业务门禁，只稳定测试观察窗口。
- `git diff --check`：exit code 0，无 whitespace error；仅有工作区既有 LF/CRLF 转换 warning。
- 禁止范围检查：`git diff --name-only -- desktop/src/main.ts desktop/src/preload.ts desktop/src/python-runtime.ts src desktop/tests/cdp-isolation.test.ts` 无输出；无 Python/Application/Bridge/CDP/T10 生产改动。
- 负向扫描：`rg -n "DEFAULT_CONTEXT_WINDOW|configuredContextWindow" desktop/src/renderer`、`rg -n "allow_other" src tests desktop/src desktop/tests`、`rg -n "arguments_delta" desktop/src/renderer desktop/tests/renderer.test.tsx` 均 exit code 1、0 matches。
- 前一轮已对 `tests/cdp-isolation.test.ts` 独立稳定复跑 3 次，每次 **8 tests / 8 pass / 0 fail / 0 skipped**，且本轮全量 `npm test`（111/111）亦未复现 `driver_failure`；当前 diff 不包含 CDP 文件，故将该单例判断为未复现的环境/测试时序现象，不能据此声称根因已定位或扩大 CDP 范围。
- 依据已读取的 `uth-utf8-guard` 规则，本轮 Feedback 追加后需对 Checklist 与 W03 Feedback 一并运行 guard；本节不把 guard 尚未运行前的结果描述为通过。

### 未验证项与清理边界

- 未验证真实 Windows/Electron packaged GUI、真实 computed media layout/overflow、DPI/100%/125%/150% zoom、真实 IME、系统 reduced-motion、真实 Provider 网络或人工键盘/鼠标矩阵；这些仍由 W05/W06 负责。
- 未删除业务文件、缓存或未知文件；未执行 commit、push、merge、rebase、tag、release、分支切换或工作包归档。

### 本轮追加后的 UTF-8 guard completion（EOF 追加）

- `conda run --no-capture-output -n re-uthcode python C:\Users\93445\.codex\skills\uth-utf8-guard\scripts\check_utf8_docs.py "docs/work/F02-DesktopGUI交互与上下文缺陷修复/F02-DesktopGUI交互与上下文缺陷修复-checklist.md" "docs/work/F02-DesktopGUI交互与上下文缺陷修复/feedback/W03-desktop-projection-interaction-feedback.md"`：exit code 0，`OK: 2 file(s) passed UTF-8 guard`；无 replacement character、常见乱码或不平衡 Markdown fence。

## Reviewer 返工（第 4 轮，2026-09-01，EOF 追加）

本节是第四轮 Reviewer `NOT APPROVED` 后的更正；只追加在本文 EOF，没有覆盖前述记录，未执行任何 Git 写操作。

### Bridge DTO 合同与 accepted identity

- 只读核对 `src/uthcode/interfaces/desktop/bridge.py`：`_turn_start` 返回 flat `{run_id, turn_id, status}`；`_turn_steer` 返回 `{accepted: true, run: snapshot}`。Renderer 不修改 Bridge，也不把两种返回形状混为一谈。
- `App.tsx` 现在按调用方法分别解析：`turn.start` 直接读取 flat response，`turn.steer` 只读取 nested `response.run`；两者均要求非空 `run_id` 与 `turn_id` 才能建立 accepted `latestTurnRef` 和取消旧 poll。缺少任一 identity 时只写入失败 notice，不猜测或以旧 Run 作为新 ownership。
- accepted boundary 建立后，Core `turn_started` 必须匹配当前 accepted/current identity 才能 dispatch 和取得 poll ownership；run/turn 不匹配的 stale event 在 listener 入口 return，不改变 reducer、timeline 或当前 terminal poll。

### 连续 Turn 与 stale poll 证据

- race mock 已改为真实 Bridge flat shape：第一次 `turn.start` 返回 `run-new/turn-one`，第一次 terminal 经 `active_turn=true → false` 收敛后，第二次 `turn.start` 返回同一 `run-new` 的新 `turn-two`。测试断言 accepted Run 投影、两条 user timeline、两次独立 terminal poll，以及最终两次 Composer 解锁，证明同一 Run 连续 Turn 不锁死。
- 第二次 terminal poll 活跃期间注入旧 `run-old/turn-old` `turn_started`，断言旧事件不写 timeline、不替换 Run、不取消第二次 poll；最终仍由第二次 authoritative `active_turn=false` 释放门禁。
- 新增 nested `turn.steer` 回归使用真实 `{accepted, run}` shape，断言 active Composer 不调用 `turn.start`，且 nested Run 的下一事件可被正确接受。Plan/Tool 公共 identity 未新增字段，也未猜测不存在的 `tool_call_id`。

### 本轮权威 Checklist 记录

- 本轮未新增或修改 Checklist 勾选；W03 负责范围当前实际为 `[x]` 的全部条目仍为：
  - T05：`cd desktop; npm run typecheck; npm test` 精确验证；Context authority negative scan 为 0 且 Context ring/Runtime panel 只消费 Application status；message/tool/timeline/compact 仅在权威边界刷新 status 且 delta 不发 status RPC；manual compact running gate 与 terminal 恢复；resume/rename/refresh/new/session 展示顺序与 selected sixth visibility。
  - T06：Renderer Slash/IME/select keyboard 与 focus restoration；ToolStarted/ToolFinished same-row、elapsed freeze 和状态 icon/text/ARIA；TaskStateChanged replace-all 的单一 Todo strip；PlanContentDelta/PlanProposed 同一 block 及 failure/cancel；AskUser 1～4 题、三种题型、自由输入、导航保留、Review、typed submit/cancel。
- Composer/Runtime keyboard-only 与 100%/125%/150% zoom 无横向裁切、dark/light/zh-CN/en/reduced-motion 完整矩阵、DOM identity broad negative assertions及真实人工/集成/T07～T11 条目仍为 `[ ]`；本轮没有把 JSDOM contract 当作真实窗口测量或人工验收。

### 本轮精确验证

- `conda run --no-capture-output -n re-uthcode npm run typecheck`（cwd `desktop`）：exit code 0，`tsc --noEmit` 通过。
- `conda run --no-capture-output -n re-uthcode npx tsx --test tests/renderer.test.tsx`（cwd `desktop`）：exit code 0，**77 tests / 77 pass / 0 fail / 0 skipped**。
- `conda run --no-capture-output -n re-uthcode npm test`（cwd `desktop`）：exit code 0，**113 tests / 113 pass / 0 fail / 0 skipped**；包含 8 个 CDP isolation、packaging 与 T08 bundled Runtime smoke，未复现 `driver_failure`。
- `git diff --check`：本轮代码/测试修改后无 whitespace error；仅有工作区既有 LF/CRLF 转换 warning。
- 禁止范围检查 `git diff --name-only -- desktop/src/main.ts desktop/src/preload.ts desktop/src/python-runtime.ts src desktop/tests/cdp-isolation.test.ts`：无输出；没有修改 Python/Application、Bridge、CDP、Settings T07 生产逻辑、current-facts docs 或 T10 冻结文件。未执行 commit、push、merge、rebase、tag、release、分支切换或归档。

### 本轮未验证项与风险

- 仍未验证真实 Windows/Electron dev/packaged GUI、真实 computed media layout/overflow、DPI/100%/125%/150% zoom、真实 IME、系统 reduced-motion、真实 Provider 网络及人工 keyboard/mouse 矩阵；533/1100 JSDOM 只验证 DOM 状态/ARIA/focus 与结构 contract。
- malformed `turn.start` accepted response 不建立新 ownership并显示失败 notice；真实 Bridge 合同提供完整 identity，因此未触发 DTO 缺口停止边界。terminal convergence 在长时间 status 异常或持续 active 时继续安全保持 pending，瞬态 RPC error 后退避重试，不错误启用输入。
- 未删除业务源、文档、缓存或未知文件；第四轮仅在 Feedback EOF 追加，Checklist 勾选保持不变。

### 第 4 轮 UTF-8 guard completion（EOF 追加）

- 待本轮 Feedback 追加后执行并记录：`conda run --no-capture-output -n re-uthcode python C:\Users\93445\.codex\skills\uth-utf8-guard\scripts\check_utf8_docs.py "docs/work/F02-DesktopGUI交互与上下文缺陷修复/F02-DesktopGUI交互与上下文缺陷修复-checklist.md" "docs/work/F02-DesktopGUI交互与上下文缺陷修复/feedback/W03-desktop-projection-interaction-feedback.md"`。

### 第 4 轮 UTF-8 guard 实际结果（EOF 追加）

- 上述命令实际 exit code 0，输出 `OK: 2 file(s) passed UTF-8 guard`；Checklist 与 Feedback 均无 replacement character、常见乱码或不平衡 Markdown fence。

### 第 2 轮 stale-event 补充更正（仍为 EOF 追加）

- 在上述验证后又收紧了 listener identity：`turn_started` 在 React 重渲染前同步更新当前 `run_id + turn_id`，late old terminal event 在 dispatch 前被丢弃；新 Turn terminal 仍可启动自己的 authoritative poll。idle 写回前再次核对该即时 identity，旧 false 不会覆盖新 Run。新增回归覆盖“新 Turn 后再到达旧 terminal event”和已取消的 in-flight status response。
- 该补充仍未改变 T05/T06 Checklist 勾选；本反馈负责范围内实际 `[x]` 仍仅为上一节列出的 5 条 T05 与 5 条 T06，Composer/Runtime 完整 zoom、真实媒体布局和其他 `[ ]` 项仍未勾选。
- 补充后的 `conda run --no-capture-output -n re-uthcode npm run typecheck`（cwd `desktop`）exit code 0；`conda run --no-capture-output -n re-uthcode npx tsx --test tests/renderer.test.tsx` exit code 0，**75 tests / 75 pass / 0 fail / 0 skipped**；最终 `conda run --no-capture-output -n re-uthcode npm test` exit code 0，**111 tests / 111 pass / 0 fail / 0 skipped**。

## Reviewer 返工（第 3 轮，2026-09-01，EOF 追加）

本节是第三轮 Reviewer `NOT APPROVED` 后的更正；只追加在本文 EOF，没有覆盖前述记录，未执行任何 Git 写操作。

### P2-1 Runtime drawer 与宽屏 floating

- `RuntimePanel` 新增明确的 `drawer` prop；App 仅在 `innerWidth <= 680` 且 Runtime 为 `floating` 时传入 `true`。Escape、外部 `pointerdown`、打开后首控件 focus 只在该 narrow drawer 状态注册/执行；宽屏 `floating` 保持三态布局，不再被工作区点击或全局 Escape 隐藏。隐藏可见面板时仍恢复 toggle focus，避免焦点落入 `aria-hidden` 面板。
- 既有 533 CSS px DOM 测试继续验证 narrow drawer 的打开、首控件 focus、Escape/外部点击关闭、focus restore 与同一 toggle 重开；新增 1100 CSS px 测试验证 wide floating 初始不抢焦点，工作区 Escape 不被消费、pointerdown 不关闭、`aria-expanded` 保持 `true`、Runtime 仍可见。

### P2-2 accepted Run 边界与 terminal poll ownership

- `turn.start` 返回的真实 `{ run: { run_id, turn_id } }` DTO 在 `turn_accepted` dispatch 前同步建立 `latestTurnRef`，并仅在该 accepted boundary 取消旧 terminal poll。`turn_started` 不再自行创造边界：listener 先确认已有 accepted/current Run identity，再允许更新 ownership；run/turn 不匹配时立即 return，不 dispatch、不取消当前 poll。
- terminal 事件同样必须匹配当前 accepted identity；authoritative status poll 仍按 `run_id + turn_id` 单实例、可取消、退避收敛，旧事件不能写入新 Run 或用旧 false 解除新 Run 门禁。没有新增公共 DTO 字段，也没有猜测 Plan/tool identity。
- race test 先通过真实 `turn.start` accepted response 建立 `run-new/turn-new`，断言 Runtime 显示新 Run、Composer accepted draft 清空、accepted `turn_started` 写入新 user timeline；随后新 terminal 启动唯一 poll，再发 `run-old/turn-old` stale `turn_started`，断言 Run/timeline/poll 归属不变且最终仍由 `active_turn=false` 解锁。该测试覆盖 stale start 无影响，而非凭空 dispatch 一个未被 Application 接受的 Run。

### 本轮权威 Checklist 记录

- 本轮没有新增或修改任何 Checklist 勾选；以下是本轮完成后 W03 负责范围内实际为 `[x]` 的全部条目（逐项列出，未把新增 DOM contract 当成真实 zoom/人工验收）：
  - T05：执行 `cd desktop; npm run typecheck; npm test` 并记录精确结果；Context authority negative scan 为 0 且 Context ring/Runtime panel 只消费 Application status；message/tool/timeline/compact 只在权威边界刷新 status 且 delta 不发 status RPC；manual compact running gate 与 terminal 恢复；resume/rename/refresh/new/session 展示顺序与 selected sixth visibility。
  - T06：Renderer Slash/IME/select keyboard 与 focus restoration；ToolStarted/ToolFinished same-row、elapsed freeze 和状态 icon/text/ARIA；TaskStateChanged replace-all 的单一 Todo strip；PlanContentDelta/PlanProposed 同一 block 及 failure/cancel；AskUser 1～4 题、三种题型、自由输入、导航保留、Review、typed submit/cancel。
- T06 的 Composer/Runtime keyboard-only 与 100%/125%/150% zoom 无横向裁切、dark/light/zh-CN/en/reduced-motion 完整矩阵、DOM identity broad negative assertions，以及所有人工/集成/T07～T11 条目仍为 `[ ]`；本轮没有将 JSDOM/CSS contract 误记为真实 media layout 或 packaged GUI 验收。

### 本轮精确验证

- `conda run --no-capture-output -n re-uthcode npm run typecheck`（cwd `desktop`）：exit code 0，`tsc --noEmit` 通过。
- `conda run --no-capture-output -n re-uthcode npx tsx --test tests/renderer.test.tsx`（cwd `desktop`）：exit code 0，**76 tests / 76 pass / 0 fail / 0 skipped**。
- `conda run --no-capture-output -n re-uthcode npm test`（cwd `desktop`）：exit code 0，**112 tests / 112 pass / 0 fail / 0 skipped**；本轮全量包含 CDP isolation、packaging 与 T08 bundled Runtime smoke，未复现 `driver_failure`。
- `conda run --no-capture-output -n re-uthcode npx tsx --test tests/cdp-isolation.test.ts`（cwd `desktop`）：exit code 0，**8 tests / 8 pass / 0 fail / 0 skipped**；第二轮已记录的 3 次独立稳定复跑（每次 8/8）仍是当前差异下的历史证据，本轮独立复跑与全量同样未复现该单例。
- `git diff --check`：exit code 0，无 whitespace error；仅有工作区既有 LF/CRLF 转换 warning。
- 禁止范围检查 `git diff --name-only -- desktop/src/main.ts desktop/src/preload.ts desktop/src/python-runtime.ts src desktop/tests/cdp-isolation.test.ts`：无输出；未修改 Python/Application、Bridge、CDP、Settings T07 生产逻辑、current-facts docs 或 T10 冻结文件。全程未执行 commit、push、merge、rebase、tag、release、分支切换或归档。

### 本轮未验证项与风险

- 仍未验证真实 Windows/Electron dev/packaged GUI 的 computed media layout、overflow、DPI/100%/125%/150% zoom、真实 IME、系统 reduced-motion、真实 Provider 网络及人工 keyboard/mouse 矩阵；533/1100 JSDOM 只验证 DOM 状态/ARIA/focus 与结构 contract，不替代真实窗口测量。
- terminal convergence 在真实 Bridge 长时间异常或持续 `active_turn=true` 时继续安全保持 pending，瞬态 RPC error 后退避重试；不会错误启用输入，但可能保持门禁直到权威 false 或组件卸载取消。
- 未删除业务源、文档、缓存或未知文件；Checklist 未新增勾选，旧 Feedback 内容保持可追溯，仅在 EOF 追加本轮更正。

### 第 3 轮 UTF-8 guard completion（EOF 追加）

- `conda run --no-capture-output -n re-uthcode python C:\Users\93445\.codex\skills\uth-utf8-guard\scripts\check_utf8_docs.py "docs/work/F02-DesktopGUI交互与上下文缺陷修复/F02-DesktopGUI交互与上下文缺陷修复-checklist.md" "docs/work/F02-DesktopGUI交互与上下文缺陷修复/feedback/W03-desktop-projection-interaction-feedback.md"`：exit code 0，`OK: 2 file(s) passed UTF-8 guard`；无 replacement character、常见乱码或不平衡 Markdown fence。

## Reviewer 返工（第 5 轮，2026-09-01，真实 EOF 追加）

本节是第五轮 Reviewer `NOT APPROVED` 后的最终审计与更正。仅在文件当前真实 EOF 追加，未移动、删除或改写任何历史章节；全程未执行 Git 写操作。

### P1 pending `turn.start` stdout 收口

- `App.tsx` 在发出非 steering 的 `turn.start` 前建立单一 pending-start ownership。Listener 在该请求窗口内暂存带 `run_id + turn_id` 的 AgentEvent，不让 Python Runtime 同一同步调用栈中“先 resolve flat response、再连发 stdout”落入旧 identity 过滤；暂存事件保持到 accepted boundary 建立后再处理。
- `turn.start` 严格读取真实 Bridge flat `{run_id, turn_id, status}`；`turn.steer` 仍严格读取 nested `{accepted, run: {...}}`。仅完整、非空的 `run_id + turn_id` 可以建立 `latestTurnRef`、取消旧 terminal poll、dispatch `turn_accepted`，不存在 TS 猜测的公共 `tool_call_id` 或第二 authority。
- accepted 后只按完整 identity 原顺序重放匹配事件，因此同步 `turn_started → assistant_message_delta → turn_completed` 不重复、不丢失，其他 Run 事件被丢弃；rejection、异常、取消、组件 unmount 和 duplicate/new request 清理 pending buffer，不能污染 timeline 或 poll ownership。terminal 仍等待 Application `status.get.active_turn=false`，不会因 Core terminal event 立即解锁。
- 新增 `T05 buffers synchronous turn.start stdout until the flat accepted identity and replays once`：mock 在 response resolve 前于同一栈连发 accepted Run 的 started/delta/terminal 及另一 Run delta，断言一条 user、一条 assistant、无 other Run、只发一条 terminal poll，并由 `true → false` authority 解锁 Composer。新增 pending single-flight/unmount 回归，断言第二次发送不发请求、未 accepted 不渲染、unmount 后 response 不启动 poll。
- 第四轮已修复的 accepted Run boundary、stale `turn_started` 过滤、同一 Run 连续两 Turn 的独立 terminal poll 与 nested steering DTO 测试继续保留；本轮用真实 flat start shape 验证 pending replay 不改变该收口。

### 历史 Feedback 与 Checklist 审计

- 本轮严格只向真实 EOF 追加。现有文件历史顺序保留原状：第四轮标题/内容位于此前记录中，随后才有第三轮追加，因此第四轮章节在最终文件中并非 EOF；未为此移动或修改旧记录。以后返工只追加实际文件 EOF，不再前插。
- 冻结 Checklist 未新增、删除、移动或改写条目。本轮没有新增勾选；W03 负责范围实际已勾选仍为 T05 的 5 条与 T06 的 5 条：T05 typecheck/full Desktop evidence、Application Context authority 与 delta 无 status RPC、manual compact/terminal gate、Session presentation ordering、以及 T06 Slash/IME/select/focus、Tool same-row/elapsed/ARIA、Todo replace-all、Plan draft/final/failure/cancel、AskUser multi-step/review/typed response。
- 真实 Windows/Electron GUI、computed media layout/overflow、DPI/100%/125%/150% zoom、真实 IME、系统 reduced-motion、人工 keyboard/mouse 矩阵及其他冻结 `[ ]` 条目仍未勾选；JSDOM 只作为 DOM/CSS/ARIA contract 证据，不声称完成真实窗口测量。

### 第五轮精确验证

- `conda run --no-capture-output -n re-uthcode npm run typecheck`（cwd `desktop`）：exit code 0，`tsc --noEmit` 通过。
- `conda run --no-capture-output -n re-uthcode npx tsx --test tests/renderer.test.tsx`（cwd `desktop`）：exit code 0，**79 tests / 79 pass / 0 fail / 0 skipped**。
- `conda run --no-capture-output -n re-uthcode npx tsx --test tests/cdp-isolation.test.ts`（cwd `desktop`）：exit code 0，**8 tests / 8 pass / 0 fail / 0 skipped**；driver `driver_failure` 是该测试对无可用 CDP target 的预期失败输出，独立复跑与本轮全量均稳定通过，未见当前 Renderer diff 影响。
- `conda run --no-capture-output -n re-uthcode npm test`（cwd `desktop`）：exit code 0，**115 tests / 115 pass / 0 fail / 0 skipped**；包含 Renderer、Main/Preload、Runtime process、CDP isolation、packaging 与 T08 smoke。
- 本轮追加后执行 `git diff --check` 与禁止范围 diff 检查；UTF-8 guard 结果将在本节末尾追加。未执行 commit、push、merge、rebase、tag、release、分支切换或归档。

### 本轮风险与未验证项

- pending buffer 只收集带完整事件 identity 的 stdout；Application/Bridge 当前 AgentEvent 合同提供 `run_id + turn_id`，没有为缺失 identity 的事件猜测归属。持续 status RPC 异常或 `active_turn=true` 时 Composer 安全保持 pending，直至 authoritative false 或卸载取消，可能延迟解锁。
- 仍未验证真实 Windows/Electron packaged GUI 的 computed overflow、DPI/zoom、IME、系统 reduced-motion 及人工输入矩阵；533/1100 JSDOM 回归只证明窄 drawer/宽 floating 的可观测 DOM、ARIA、focus 和结构 contract。
- 未删除业务源、文档、缓存或未知文件；禁止范围源码与 CDP/Application/Python 文件保持未修改。

### 第 5 轮 UTF-8 guard 实际结果（真实 EOF 追加）

- `conda run --no-capture-output -n re-uthcode python C:\Users\93445\.codex\skills\uth-utf8-guard\scripts\check_utf8_docs.py "docs/work/F02-DesktopGUI交互与上下文缺陷修复/F02-DesktopGUI交互与上下文缺陷修复-checklist.md" "docs/work/F02-DesktopGUI交互与上下文缺陷修复/feedback/W03-desktop-projection-interaction-feedback.md"`：exit code 0，输出 `OK: 2 file(s) passed UTF-8 guard`；Checklist 与 Feedback 均无 replacement character、常见乱码或不平衡 Markdown fence。

## W06 视觉复审返工（第 6 轮，2026-09-01，真实 EOF 追加）

本轮仅修复 W06 最终视觉复审发现的 Runtime 错误告警布局/重复实体问题；未修改 W05/W06 Feedback、冻结 Checklist 或任何 Git 状态。

### 实际修复

- Runtime 错误改为单一可访问视觉实体：可见的 RuntimePanel（docked/floating）负责渲染 `runtime-panel__error`；hidden 或窄屏 docked（RuntimePanel 不可见）由 Timeline 内联 `timeline-runtime-error` 负责渲染。App 将同一 `runtimeError` 传给 Timeline 仅用于 owner 判定与相同 notice 去重，不创建第二 store；旧 fixed bottom `configuration-banner` 已删除。
- Timeline 告警位于主区滚动容器顶部，使用 opaque surface、danger 边界、`overflow:auto`、最大高度与 sticky top，不再 fixed 到窗口底部；Composer 继续由现有底部安全 padding 与独立布局承载，RuntimePanel 告警则在其自身滚动面板内，不覆盖 Send/Settings 或主操作。配置错误仍保留可聚焦、按当前 locale 翻译的 Open Settings 按钮。
- 响应式 CSS 保持 760px docked 主区与 <=680/<=520 窄屏边界，<=520 告警允许换行；dark/light 使用现有 text/surface/danger token，错误文本在两主题 opaque surface 上保持可读，既有 reduced-motion 全局规则继续生效且告警不引入动画。Renderer/locale/CSS 边界外的 Main、Preload、Python、Bridge、CDP 未修改。

### 本轮实际验证与 Checklist

- 新增真实 React DOM contract 测试覆盖 docked/floating/hidden、760/680/608/533/520/507/500 CSS viewport、dark/light、en/zh-CN；断言同一 Runtime 错误恰有一个 owner 与一个 `role=alert`，相同 generic notice 不重复，Runtime error 不禁用 Composer，窄屏 Timeline 告警的设置按钮可聚焦。
- 测试通过显式 `getBoundingClientRect()` contract 断言 Timeline 告警在 Composer 之上且处于 main 内、RuntimePanel 告警与 Composer 矩形不相交，并补充 CSS sticky/scroll/opaque surface、<=520 wrap、旧 fixed banner 删除、reduced-motion 与颜色对比断言。JSDOM 不计算真实 media/zoom layout，因此这些是 DOM/CSS/矩形 contract，不是 packaged 窗口测量。
- 本轮没有修改冻结 Checklist，也没有新增勾选。当前 W03 负责范围中原有已勾选项保持不变：T05 的 Desktop typecheck/full evidence、Application Context authority 与 delta 无 status RPC、manual compact/terminal gate、Session presentation ordering；T06 的 Slash/IME/select/focus、Tool same-row/elapsed/ARIA、Todo replace-all、Plan draft/final/failure/cancel、AskUser multi-step/review/typed response。真实 Windows/Electron packaged visual、100/125/150% 实际 DPI/zoom、真实 IME、系统 reduced-motion 与人工 keyboard/mouse 仍未因本轮 JSDOM contract 而勾选。

### 本轮精确验证

- `conda run --no-capture-output -n re-uthcode npm run typecheck`（cwd `desktop`）：exit code 0，`tsc --noEmit` 通过。
- `conda run --no-capture-output -n re-uthcode npx tsx --test tests/renderer.test.tsx`（cwd `desktop`）：exit code 0，**107 tests / 107 pass / 0 fail / 0 skipped**。
- `conda run --no-capture-output -n re-uthcode npx tsx --test tests/cdp-isolation.test.ts`（cwd `desktop`）：exit code 0，**8 tests / 8 pass / 0 fail / 0 skipped**；未复现 `driver_failure`。
- `conda run --no-capture-output -n re-uthcode npm test`（cwd `desktop`）：exit code 0，**146 tests / 146 pass / 0 fail / 0 skipped**；包含 Renderer、Main/Preload、Runtime process、CDP isolation、packaging 与 T08 smoke。该全量结果在本轮最终代码/测试变更后重新执行。
- `git diff --check`：exit code 0，无 whitespace error，仅工作区既有 LF/CRLF 转换 warning；禁止范围 `desktop/src/main.ts`、`desktop/src/preload.ts`、`desktop/src/python-runtime.ts`、`src`、`desktop/tests/cdp-isolation.test.ts` 无 diff。全程未执行 commit、push、merge、rebase、tag、release、分支切换或归档。

### 本轮未验证项与风险

- 未能在本轮使用真实 packaged Electron 窗口对 760px 截图、100/125/150% DPI/zoom、computed overflow、安全区及系统 reduced-motion 做人工测量；本轮测试明确只证明真实 React DOM 的 owner/ARIA/focus/矩形 contract。W06 既有 packaged/build smoke 仍由全量 `npm test` 覆盖，但不等同于此项视觉人工验收。
- Runtime 错误实体仍由 Renderer 的现有 `runtimeError` state 单一承载；RuntimePanel 可见性变化时由 owner prop 切换，hidden/narrow docked 不保留可访问 error 子树。没有新增第二 authority/store、兼容层或范围外代码。

### 第 6 轮 UTF-8 guard 实际结果（真实 EOF 追加）

- `conda run --no-capture-output -n re-uthcode python C:\Users\93445\.codex\skills\uth-utf8-guard\scripts\check_utf8_docs.py "docs/work/F02-DesktopGUI交互与上下文缺陷修复/F02-DesktopGUI交互与上下文缺陷修复-checklist.md" "docs/work/F02-DesktopGUI交互与上下文缺陷修复/feedback/W03-desktop-projection-interaction-feedback.md"`：exit code 0，输出 `OK: 2 file(s) passed UTF-8 guard`；Checklist 与本 Feedback 均无 replacement character、常见乱码或不平衡 Markdown fence。

## 第 7 轮复审更正与响应式焦点收口（2026-09-01，真实 EOF 追加）

本轮按复审要求删除了 Runtime 错误测试中所有手工覆盖 `getBoundingClientRect()` 的预设矩形、矩形相交断言及其“safe area/不覆盖 Composer”描述；生产 CSS 未回退。保留的自动证据是实际 React DOM 的单一错误 owner、`role="alert"`、可达设置控件、Composer 未禁用、docked/floating/hidden 模式、680/608/533/520/507/500/760 等 CSS viewport 结构、dark/light 与 en/zh-CN，以及独立 CSS contract 检查。

- 当前自动测试不声称测得真实 computed rect、真实 overflow/安全区、DPI/zoom（100/125/150%）或 packaged 窗口中告警与 Composer 的实际覆盖关系；这些视觉/几何证据保留给 W06 Chromium/CDP。相关 Checklist 未修改、未因 JSDOM/CSS contract 误勾真实 visual/zoom/geometry 项。
- 补充修复了真实 `window.resize` 的 owner 迁移：窄屏 docked Runtime 隐藏时，Timeline 的 Open Settings 按钮若持有焦点，切到宽屏后 Timeline 错误实体卸载、RuntimePanel 成为唯一 owner，并把焦点迁移到稳定的 Runtime toggle；既有宽→窄 panel focus restore、窄 drawer Escape/外部点击恢复保持不变。新增测试不 remount App，直接派发 680→760 resize 并验证 owner、ARIA、焦点与 Composer 可操作性。
- W05/W06 Feedback、冻结 Checklist 与范围外源码均未修改；未执行 Git 写操作。

### 第 7 轮精确验证

- `conda run --no-capture-output -n re-uthcode npm run typecheck`（cwd `desktop`）：exit code 0，`tsc --noEmit` 通过。
- `conda run --no-capture-output -n re-uthcode npx tsx --test tests/renderer.test.tsx`（cwd `desktop`）：exit code 0，**108 tests / 108 pass / 0 fail / 0 skipped**；包括新增真实 resize owner handoff 测试。
- `conda run --no-capture-output -n re-uthcode npx tsx --test --test-name-pattern="buffers synchronous turn.start" tests/renderer.test.tsx`（cwd `desktop`）：exit code 0，**1 test / 1 pass / 0 fail**。
- `conda run --no-capture-output -n re-uthcode npm test`（cwd `desktop`）：首次全量在同步 `turn.start` buffer 用例出现一次退避计数时序失败（`statusCalls` 实际 3、断言 2），随后同一代码立即重跑通过；最终 **147 tests / 147 pass / 0 fail / 0 skipped**，包含 Renderer、Main/Preload、Runtime process、CDP isolation、packaging 与 T08 smoke。
- `conda run --no-capture-output -n re-uthcode python C:\Users\93445\.codex\skills\uth-utf8-guard\scripts\check_utf8_docs.py "docs/work/F02-DesktopGUI交互与上下文缺陷修复/F02-DesktopGUI交互与上下文缺陷修复-checklist.md" "docs/work/F02-DesktopGUI交互与上下文缺陷修复/feedback/W03-desktop-projection-interaction-feedback.md"`：exit code 0，输出 `OK: 2 file(s) passed UTF-8 guard`；最终 Checklist 与本 Feedback 均无 replacement character、常见乱码或不平衡 Markdown fence。
