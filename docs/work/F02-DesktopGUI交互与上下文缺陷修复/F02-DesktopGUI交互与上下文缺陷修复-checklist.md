# F02：Desktop GUI 交互与上下文缺陷修复 Checklist

## T01：AskUser Core 合同硬切

- [x] 执行 `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_agent_interaction.py tests/test_tui.py -q`，全部用例通过。
- [x] 构造 text、single-select、multi-select 与 1～4 题请求，确认 text 无 options、select 只接受 2～3 个结构化 options，第 4 个 option 被拒绝。
- [x] 对 single-select 与 multi-select 提交不命中 option label 的非空答案，确认 Core typed response 校验通过；空答案、重复 question id、缺失 question id 仍被拒绝。
- [x] 对旧 JSON/tool payload 注入 `allow_other`，确认新合同拒绝；执行 `rg -n "allow_other" src tests desktop/src desktop/tests`，active source/tests 返回 0 条。
- [x] TUI 与 Desktop Renderer 测试确认每个选择题始终出现自由输入路径，提交后恢复原 Turn，cancel 仍走 typed cancel。

## T02：Plan 真流式公共事件

- [x] 执行 `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_planning.py tests/test_agent_events.py tests/test_agent_loop.py -q`，全部用例通过。
- [x] `PlanContentDelta` 完成 dict/JSON round-trip，字段含 Run/Turn/iteration/tool-call identity 与自然语言 text，payload 不含 `arguments_delta`、raw JSON 或 Provider SDK 类型。
- [x] 以单 chunk、多 chunk、逐字符、key/value 边界、换行、引号、反斜杠和 Unicode escape 输入 Plan 参数流，确认输出只追加新解码文本且最终拼接正确。
- [x] 同一 Turn 中混入不同 tool-call identity 与非 `ProposePlan` 工具，确认不会串流或产生 Plan delta。
- [x] 合法完成顺序为 delta → `PlanProposed` → Plan Review；malformed、失败与取消只终止 draft，不写正式 PlanState、不产生伪 `PlanProposed`。
- [x] 执行否定扫描，确认 Renderer 与公共 AgentEvent 不解析/携带 raw tool argument JSON，生产代码中没有通用 Tool JSON streaming framework。

## T03：Application Context / Compact 安全投影

- [x] 执行 `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_application_runs.py tests/test_w05_diagnostics.py -q` 及受影响的现有 Context 定向 tests，全部通过。
- [x] 在无更具体限制、显式大窗口配置和可靠 Provider ceiling 三类场景读取 Application status，确认 `budget_tokens` 与实际 ContextBudget/effective limit 同源且 Provider ceiling 可收紧。
- [x] resume 已提交 durable Session 后，status 可重建 current estimate；没有对应 Provider 请求 usage 时 measurement 不标 exact。
- [x] Provider terminal exact usage 可标 exact；随后追加 Transcript、Tool、Timeline 或 Compact mutation 后再次读取，measurement 回到 estimate。
- [ ] manual、auto、overflow compact 都经过同一 Application single-flight，并可观察 `running` 到 `completed|no_change|failed|cancelled` 的 terminal 状态。
- [ ] 在 Core terminal event 已入队但 Application 尚未完成 result/persistence/active-turn 释放的时序测试中，Desktop 不提前把旧 status 当成最终状态。
- [x] 现有 Low Water、Auto Gate、Hard Gate 与 overflow retry 回归通过，证明本任务没有改写 T09-3 safety semantics。

## T04：Session move 与 Plan replay

- [x] 执行 `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_session_authority.py tests/test_desktop_bridge.py -q`，全部用例通过。
- [x] 移动未打开 Session 与当前 open idle Session 均成功；后者同步 close-time state、更新项目归属、释放 writer，并清除 source Application ownership。
- [x] active Turn 移动返回稳定 busy/turn-active 结果且不隐式 cancel；invalid target、corrupt、storage 结果不包含路径或异常正文。
- [x] 在 project membership 更新前和更新时注入失败，确认源 project membership、writer 与可继续使用状态保持完整，没有 optimistic Renderer mutation。
- [x] durable 完整 `ProposePlan` replay 投影为 `kind=plan` 且正文仅为合法 plan 文本；普通 tool replay 保持原语义。
- [x] unfinished/malformed Plan、raw arguments、ToolResult private body、Session path 与 secret 不进入 replay 或 Desktop response。
- [ ] 当前单 Runtime move 后只用 mutation 更新可见 target，目标项目下一次激活再读 authoritative catalog；测试确认没有第二 Application 或跨项目文件扫描。

## T05：Desktop 命令、Context 与 Session 投影收口

- [x] 执行 `cd desktop; npm run typecheck; npm test`，记录命令、exit code 与精确 passed/failed 数量。
- [x] 执行 `rg -n "DEFAULT_CONTEXT_WINDOW|configuredContextWindow" desktop/src/renderer`，Renderer 业务 authority 命中为 0；Context ring 与 Runtime panel 只消费 Application status。
- [x] message/tool/timeline/compact 变化后只在权威收口边界刷新 status；逐字符 delta 不调用 status RPC，Turn terminal/result 竞态测试不读取陈旧最终状态。
- [ ] 输入 `/` 时 clear/quit/resume/permission/help 不出现在 Desktop candidate menu，但 Application command registry 仍保留；compact/new/plan/do 选择后直接执行且不调用 `turn.start` 发送 Slash 文本。
- [ ] `/model` 与 Composer model picker 使用同一 Application catalog；`/status` 只渲染安全用户字段，不输出 diagnostics/private payload。
- [x] manual compact running 时普通 send 被禁用，terminal 后恢复；界面 activity 仅来自 Application CompactionStatus。
- [ ] 当前 selected Session move 成功后 selection/timeline 清空，source/target 导航按 mutation/后续 authoritative catalog 收敛；失败时 UI 不移动。
- [x] resume/rename/refresh 不改变现有 Session 行顺序；new 置于 regular 顶部，只有新 durable message/pin 允许重排；超过五项时 selected 第六项仍可见且前五不乱。

## T06：Chat、Tool、Todo、AskUser、Plan 交互完成

- [x] Renderer tests 覆盖 Slash ArrowUp/Down `scrollIntoView(nearest)`、Home/End/Enter/Tab/Escape、IME composing、menu/select collision flip 与 focus restoration。
- [ ] Composer/Runtime 控件在 keyboard-only 下可达，icon、tooltip、ARIA 和非颜色状态齐全；窄屏、100%/125%/150% zoom 无横向裁切。
- [x] ToolStarted/ToolFinished 使用同一 DOM row；running elapsed 持续增长，success/failure/cancelled 时冻结，状态同时有 icon/text/ARIA。
- [x] 连续 TaskStateChanged 只 replace-all 更新一个 Todo 浮层；默认 compact，hover/focus expand，不出现第二 Todo store 或冗长状态 label。
- [x] 连续 `PlanContentDelta` 只追加同一 turn/tool-call draft block；`PlanProposed` 原地封口，Plan Review 独立显示；failure/cancel 不残留 running 或新增第二 block。
- [x] AskUser tests 覆盖 1～4 题、text/single/multi、自由输入、prev/next 答案保留、最终 review、一次 typed submit 与 cancel；界面不存在“返回聊天”伪状态。
- [ ] dark/light、zh-CN/en 与 `prefers-reduced-motion` 测试通过；关闭非必要动画后业务行为、键盘路径和焦点不变。
- [ ] 执行 DOM identity/重复行否定断言，确认同一 Tool、Todo、AskUser、Plan 事实均只对应一个视觉实体。

## T07：Settings 语义、API Key reveal 与页面结构修复

- [x] 执行 `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_configuration.py tests/test_desktop_bridge.py -q` 与 Desktop preload/Settings tests，全部通过。
- [x] 普通 `settings.get`、status、events、diagnostics、errors、preferences、logs 和 snapshots 均不含 API Key；只有用户显式调用 `settings.reveal_api_key(provider_profile_id)` 的成功 response 可携带当前配置表示。
- [x] literal Key reveal 返回 literal；`env:VARIABLE_NAME` reveal 只返回引用字符串且不解析环境变量；unknown provider 与读取失败返回稳定无秘密错误。
- [x] 点击 eye/reveal/hide 不标记 touched/dirty、不触发 save；未编辑 Key 的保存请求不含旧明文且保留现有配置。
- [x] 用户实际编辑 Key 后 replacement/touched=true；保存失败保留 replacement 草稿，保存成功按既有配置写入边界收敛。
- [x] 关闭 Provider modal、离开 Settings、runtime rebootstrap 与组件卸载后 revealed cache 被清除，明文不进入 reducer 持久 state 或 DesktopPreferences。
- [x] 空配置、新 Provider、一个 Provider 多 Models、Model 增删/默认选择、display-name fallback 均通过；DOM/文案中不出现可编辑 `model_ref`、`model`/`model-1` placeholder、清除 Key或“已配置”旧交互。
- [x] Settings 复用全局 sidebar 宽度并按分类独立 page/section；Provider/Model modal 的 keyboard/focus/tooltip/ARIA、zh/en 与 dark/light 均通过。
- [x] 执行 `rg -n "renameModelRef|model-1|clearKey" desktop/src/renderer desktop/tests`，生产旧路径为 0，测试中的否定断言逐条可解释。

## T08：GUI 越界、冗余、不可达与过度抽象审查

- [ ] 对 `desktop/src/**`、`src/uthcode/interfaces/desktop/**` 与 F02 新公共投影修改点完成按 P0/P1/P2/P3 分级审查，finding、证据、处置和验证写入 W05 Feedback。
- [ ] F02 范围内 P0/P1/P2 finding 全部关闭；未关闭项为 0 后才进入 T09。
- [ ] stale RPC、project/session 切换污染、Plan tool-call 混流、duplicate/out-of-order event、compact input gate、Settings rollback 与 focus restoration 均有测试或可复核证据。
- [ ] Renderer 不计算 Context safety、不修改 durable Session、不复制 Permission/Mode/Todo/Plan authority、不把 Slash 伪装用户消息；Bridge 不绕 Application 访问 Core mutable state/Session files。
- [ ] API Key、raw Provider/tool private body、internal diagnostics、Session path 与 native exception 不穿过非授权 Interface payload。
- [ ] 执行无调用方 export/helper、重复 normalize/project、旧 action/locale/CSS/fixture、catch 后不可达 fallback 的扫描并删除真实遗留。
- [ ] `App.tsx`、`state.ts`、`SettingsView.tsx` 的保留/拆分理由记录在 Feedback；新增私有模块均有当前调用方与测试，旧入口已删除。
- [ ] 执行 `rg -n "DesktopManager|SessionManager|SessionStore|ContextManager|ContextEngine|PlanManager|TodoManager|EventBus|PluginRegistry|TransportFactory" src/uthcode desktop/src tests desktop/tests`，无 F02 新增生产抽象命中。
- [ ] 执行 Python architecture tests、Desktop typecheck/tests 与 `git diff --check`，全部通过。

## T09：[接入主流程] Desktop 生产链集成

- [ ] 从真实 Desktop dev shell 验证 `Renderer → DesktopApi → Main/Preload → DesktopBridge → Application → Core`，请求/Run/Turn/pause/tool-call identity 和事件顺序一致。
- [ ] AskUser request → typed response → 同一 Turn continue 通过；Plan delta → final → Review → approve/revise/cancel 通过且没有 raw JSON。
- [ ] Context/Compact status、open idle Session move/Plan replay、direct Slash/model/status、Settings reveal/save/rebootstrap、Todo/Tool/BehaviorMode 均走唯一生产链。
- [ ] active Turn、pending interaction、compact running 与 stale response 门禁均从现有权威收敛，不创建第二 Turn/Run/Application。
- [ ] 执行否定扫描，确认被替代的 candidate 特判、伪 command user message、Context/Plan/Session/Settings 双入口为 0。
- [ ] `git diff --name-only -- docs/work/T10-DesktopGUI与TUI全量能力迁移` 返回空；`git diff --name-only -- desktop/src/main.ts desktop/src/preload.ts desktop/src/python-runtime.ts` 也返回空，证明冻结工作包和明确保留 transport 文件没有无授权修改。
- [ ] T08 的所有已关闭 finding 在集成后复查仍为关闭，无新增 F02 范围 P0/P1/P2。

## T10：[端到端验证] Desktop 人工与自动验收

- [ ] 执行 `conda run --no-capture-output -n re-uthcode python -m pytest -q`，记录精确 passed/failed/skipped 和 exit code。
- [ ] 在 `desktop` 执行 `npm run typecheck` 与 `npm test`，记录精确结果；确认 Settings acceptance isolation 测试实际被正式脚本覆盖或单独明确执行。
- [ ] 更新并运行现有 CDP fixture/driver，AskUser 新合同、Plan stream/review、Tool/Todo、Compact、Session >5 与 Settings reveal 场景均不依赖旧 `allow_other` fixture。
- [ ] 运行现有 packaged/CDP acceptance runner，确认不再只固定覆盖不足的 visual 子流；沿用 isolated launcher、bounded deadline，不创建第二 harness。
- [ ] 在 Windows Desktop dev shell 与 packaged app 分别验证 dark/light、zh-CN/en、wide/narrow、keyboard-only/mouse、IME、100%/125%/150% zoom、reduced motion。
- [ ] 人工验证 AskUser 1题/4题、Plan stream/review/change/cancel、Tool success/fail/cancel、manual compact no-change/fail、Session >5/move/restart+resume 和 API Key reveal/hide/untouched/replacement。
- [ ] 检查无 dropdown flicker/overlap、横向 crop、focus loss、duplicate timeline row、乱码或错误 Session reorder。
- [ ] 需要真实 Provider、干净 Windows 或其他当前不可用条件的场景均在 W06 Feedback 写明环境、未验证原因和风险；未运行项没有被勾选或描述为通过。

## T11：[遗留负担清理] 否定扫描、文档与全量回归

- [ ] 执行 `rg -n "allow_other" src tests desktop/src desktop/tests desktop/scripts`，active 旧合同命中为 0；历史冻结文件命中不修改并在 Feedback 解释。
- [ ] 执行 `rg -n "DEFAULT_CONTEXT_WINDOW|configuredContextWindow|renameModelRef|model-1|arguments_delta" desktop/src desktop/tests desktop/scripts`，被替代 Renderer/UI/raw 路径命中为 0或逐条证明是合法否定测试。
- [ ] 执行 `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q`、`python -m compileall -q src tests`、`python -m pip check` 与 `git diff --check`，全部退出码 0。
- [ ] 重新执行 Python full suite、Desktop typecheck/tests 与必要 CDP/packaged 回归，精确结果写入 W06 Feedback。
- [ ] `docs/Tools.md`、A02、A03、A04/TUI（仅实际事实受影响时）和 `docs/Context-Index.md` 与最终代码一致；T10 冻结文件无修改。
- [ ] `docs/OutstandingDebtList.md` 已核对且保持原内容，F02 Spec/Feedback 明确“能力欠账：无”且未触发 Persistent Runtime Recovery。
- [ ] W01～W06 Feedback 齐全，分别说明实际改动、机制、文件、精确测试、Checklist、偏差、未完成项、风险和清理结果；返工只追加。
- [ ] 对 F02 工作包和所有实际修改 Markdown 运行 UTF-8 guard，确认可解码、无 replacement/常见乱码、fenced code block 成对。
- [ ] 全量盘点 `docs/work/` 与 archive 后更新 Context Index：T10 仍按冻结 Checklist 事实分类；F02 只有本 Checklist 全部完成且 Feedback 齐全时才标 `implemented_unarchived`，否则为 `not_implemented`。
- [ ] 未自动归档 F02/T10，未执行未经用户明确要求的 Git commit、push、merge、rebase、tag 或 release，且用户原有未跟踪构建缓存保持不动。
