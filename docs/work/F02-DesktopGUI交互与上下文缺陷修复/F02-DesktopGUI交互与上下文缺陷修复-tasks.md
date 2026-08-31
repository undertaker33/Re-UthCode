# F02：Desktop GUI 交互与上下文缺陷修复 Tasks

## Worker 分组、顺序与依赖

| Worker | 执行任务 | 前置 | 写集与串行边界 |
| --- | --- | --- | --- |
| W01 | T01 → T02 | 无 | 独占 Core AskUser/Plan 协议、TUI 适配、公共事件与对应 Python tests |
| W02 | T03 → T04 | W01 | 独占 Application Context/Session、Python Desktop Bridge 与对应 Python tests |
| W03 | T05 → T06 | W02 | 独占 Desktop command/context/session/chat/interaction Renderer、共享 reducer/CSS 与 Renderer tests |
| W04 | T07 | W03 | 独占 Settings reveal 后端、Desktop Settings UI、配置/Bridge/Renderer tests；在 W03 后串行修改共享文件 |
| W05 | T08 → T09 | W04 | 独占 F02 GUI 审查、跨层接线、范围内清理与集成回归；不得提前引入新产品能力 |
| W06 | T10 → T11 | W05 | 独占现有 CDP/packaged acceptance 适配、真实验收、否定扫描、当前事实文档、Checklist 与最终 Feedback |

依赖固定为 `W01 → W02 → W03 → W04 → W05 → W06`。共享文件必须保持单写者；尤其 `bridge.py`、`App.tsx`、`state.ts`、`SettingsView.tsx`、`app.css` 与 Renderer tests 不允许多个 Worker 同时修改。

所有 Worker 必须由用户指定对应 Prompt 依次派发，不得自行开始实施。首次派发后，原始需求、Spec、Tasks、Prompt 和 Checklist 文字/结构冻结；Checklist 只允许把已有且有证据的 `[ ]` 改为 `[x]`。各 Task 的“逻辑交付边界”只用于控制 diff 范围，不授权 Git commit、push 或其他 Git 写操作。

需求提及的探索提示词在拆包时未于仓库中找到；正式实现不依赖该文件。现有源码、测试、当前上下文和 F02 原始需求已经足以确定边界。

## T01：AskUser Core 合同硬切

### 任务目标

统一 Core、TUI 与 Desktop 的选择题协议：结构化选项收敛为 2～3 项，所有选择题始终接受自然语言自由答案，并彻底删除 `allow_other`。

### 新增文件

- 无预设生产文件。

### 修改文件

- `src/uthcode/core/interaction.py`
- `src/uthcode/core/__init__.py`（仅公共导出确实受影响时）
- `src/uthcode/interfaces/tui/interaction.py`、`src/uthcode/interfaces/tui/app.py`（按实际旧分支命中）
- `desktop/src/renderer/InteractionSurface.tsx`
- `tests/test_agent_interaction.py`、`tests/test_tui.py`
- `desktop/tests/renderer.test.tsx` 或 W03/W06 最终确定的对应 Interaction suite
- `desktop/scripts/cdp-openai-fixture.mjs`、`desktop/scripts/cdp-driver.mjs` 由 W06 在真实验收阶段同步最终合同；W01 只在 Feedback 标记依赖，不跨写集修改。

### 删除文件

- 无预设整文件删除；删除 active source/tests 中所有仅服务于 `allow_other` 的字段、分支与 fixture。

### 文件职责及实施内容

- `UserQuestion`、JSON 合同和 AskUser Tool schema 只接受新硬切形状，不兼容读取旧字段。
- text 问题保持无结构化选项；single-select 恰好一个非空答案；multi-select 至少一个非空答案；任意非空答案不再受 option membership gate 限制。
- 保持现有 1～4 题、typed response identity、pause/resume/cancel 和 non-empty 校验。
- TUI 与 Desktop 每个选择题都提供自由输入，不创建 Interface 私有的合法性规则。

### 依赖任务

- 无。

### 参考资料定位

- 原始需求第 1.3、2.2、4.1、6、7、11.1、12.1、15/Task 1、16～21 节。
- `docs/context/A01-AgentRuntime/AgentRuntime-Context.md`、`A02-Control/Control-Context.md`、`TUI/README.md`。
- 当前 `core/interaction.py`、TUI/Desktop interaction 实现与对应 tests。

### 完成边界

Core、TUI、Desktop 的新 AskUser 合同一致；旧字段在 active source/tests 中为零；不实现 pending AskUser 跨进程恢复。

## T02：Plan 真流式公共事件

### 任务目标

从既有 Provider-independent 工具参数流中生成 display-safe Plan 文本增量，同时保持完整正式 Plan 与 Review 的最终权威不变。

### 新增文件

- 无预设生产文件；私有 decoder 仅在现有 planning 职责无法清晰承载时才可新增同目录私有模块。

### 修改文件

- `src/uthcode/core/planning.py`
- `src/uthcode/core/agent_events.py`
- `src/uthcode/core/agent.py`
- `src/uthcode/core/__init__.py`
- `src/uthcode/application/__init__.py`
- `tests/test_planning.py`、`tests/test_agent_events.py`、`tests/test_agent_loop.py`

### 删除文件

- 删除本任务触达范围内以完整最终文本伪造逐字 streaming 的旧帮助路径；不预设整文件删除。

### 文件职责及实施内容

- 新增 `PlanContentDelta`，携带 Run/Turn/iteration/tool-call identity 和已解码自然语言新增文本。
- 完成 AgentEvent JSON round-trip、union 和公共导出；payload 不含 raw `arguments_delta`、JSON key/quote/escape 或 SDK 类型。
- 私有 decoder 只绑定当前 `ProposePlan` 的单一 `plan` 字符串 schema，支持任意 chunk、escape、反斜杠、引号与 Unicode，不扩成通用 JSON streaming 框架。
- 只对匹配的 Plan 控制 Tool emit 新增 prefix；不同 tool call 不混流。
- Tool 完整结束时继续使用既有最终 parser；只有合法 complete 才写正式 PlanState 并 emit `PlanProposed`，malformed/cancelled 不产生伪正式 Plan。

### 依赖任务

- T01。

### 参考资料定位

- 原始需求第 1.3、2.3、4.2、6、7.1、11.2、12.2、15/Task 2、16～21 节。
- A01/A02/A03 当前上下文。
- 既有 Provider ToolCall stream、Plan final parser、Agent loop 与 AgentEvent tests。

### 完成边界

公开流只包含 Plan 自然语言增量，最终事件仍是 revision/Review 唯一权威；不持久化未完成 draft，不新增公共通用工具流框架。

## T03：Application Context / Compact 安全投影

### 任务目标

由 Application 提供足以驱动 Desktop 的 Context 与 Compaction 产品状态，保持现有 Context safety chain 为唯一权威。

### 新增文件

- 无预设生产文件。

### 修改文件

- `src/uthcode/application/context.py`
- `src/uthcode/application/generation.py`
- `src/uthcode/application/runs.py`（仅为权威 terminal/usage 收口时序提供必要投影时）
- `src/uthcode/application/__init__.py`
- `tests/test_application_runs.py`、`tests/test_w05_diagnostics.py` 与已有 Context 定向 tests

### 删除文件

- 无。

### 文件职责及实施内容

- 在 Application public status 中增加或收敛稳定 `ContextStatus` 与 `CompactionStatus`，不要求 Interface 解析 diagnostics。
- 有效预算复用现有 configured/provider/default 收紧与冻结 ContextBudget；不修改 T09-3 Gate、Low Water、Hard Gate 算法。
- 表达 current used tokens、budget、available、estimate/exact/unavailable 与安全短来源；Provider exact 只在仍对应当前 request boundary 时成立，后续 Transcript/Tool/Timeline/Compact 变化后回到 estimate。
- durable Session resume 复用既有 context refresh 重建 estimate，不伪造运行时 checkpoint。
- manual/auto/overflow 压缩共用既有 single-flight/orchestrator，并投影 running 与 completed/no-change/failed/cancelled terminal 事实。
- 明确 status refresh 应发生在 Application 已完成 Turn result、usage、persistence 与 active-turn 释放的权威边界之后；不得把 Core terminal event 到达本身误作全部 Application 收口完成。

### 依赖任务

- T02。

### 参考资料定位

- 原始需求第 2.4、4.3、6、7、11.3～11.4、12.3、15/Task 3、16～21 节。
- A03/A04 当前上下文与 T09-3 已冻结 Context 语义。
- 当前 Application Context service、status、Run completion 和 diagnostics tests。

### 完成边界

Application 能安全、稳定地表达当前 Context/Compaction 状态，恢复和 mutation 后 measurement 正确降级；没有新的 Context 算法或 Desktop FSM。

## T04：Session move 与 Plan replay

### 任务目标

在 Application authority 内支持当前 open idle Session 的事务移动，并把 durable 完整 Plan 安全投影为 replay record。

### 新增文件

- 无预设生产文件。

### 修改文件

- `src/uthcode/application/sessions.py`
- `src/uthcode/application/__init__.py`（仅公共 DTO 导出受影响时）
- `src/uthcode/interfaces/desktop/bridge.py`
- `tests/test_session_authority.py`、`tests/test_desktop_bridge.py`

### 删除文件

- 删除 Desktop/Application 中被新 idle-move 权威替代的预拒绝或重复判断；不删除 Session store。

### 文件职责及实施内容

- active Session 无 active Turn 时，在既有 writer lock 下完成 close-time state sync、project membership 更新、成功释放与 active ownership 清除。
- 更新失败时保持旧 writer/source membership 可用，不 optimistic move；active Turn 仍由 Bridge gate 拒绝，不隐式 cancel。
- 对 invalid target、busy、corrupt、storage 等返回稳定安全映射，不透出路径或异常正文。
- 扩展 safe replay kind 以表达 Plan；只从 durable、完整、可解析的 `ProposePlan` ToolCall part 读取 plan 文本，不把 raw arguments 或普通 tool private body暴露为 replay。
- 当前单 Application 不能同时查询两个项目 catalog：move result 立即驱动 source projection，target 在已可见时使用 mutation 更新，或在目标项目下一次激活/展开时由权威 catalog 刷新；不得为同步刷新创建第二 runtime/跨项目 reader。

### 依赖任务

- T03。

### 参考资料定位

- 原始需求第 2.5、4.4、6、7、11.5、12.4、15/Task 4、16～21 节。
- A03/A04 当前上下文、现有 ApplicationSession writer/update_project_key 和 Bridge tests。

### 完成边界

open idle Session 成功移动后 source Application 不再持有它；失败保持源状态完整；完整 Plan replay 保持视觉身份且无 raw tool 泄漏。

## T05：Desktop 命令、Context 与 Session 投影收口

### 任务目标

删除 Renderer 的 Context/Command/Session 第二语义，让 Desktop 按 Application 结果完成命令、压缩和 Session 导航。

### 新增文件

- 仅当现有职责形成独立当前调用与测试边界时，可新增 Renderer 私有 projection helper/test suite；必须删除原入口。

### 修改文件

- `desktop/src/renderer/App.tsx`
- `desktop/src/renderer/state.ts`
- `desktop/src/renderer/Composer.tsx`
- `desktop/src/renderer/RuntimePanel.tsx`
- `desktop/src/renderer/Sidebar.tsx`
- `desktop/src/renderer/app.css` 与 locale files（仅本 Task 文案）
- `desktop/tests/renderer.test.tsx` 或拆出的共享 fixture + feature suites

### 删除文件

- 删除 `DEFAULT_CONTEXT_WINDOW` 业务 authority、`configuredContextWindow()` 和忽略 Application budget 的 normalize 路径。
- 删除 selected current Session 的 Renderer 预拒绝 move 分支及被权威结果替代的旧 action/helper。

### 文件职责及实施内容

- `status_loaded` 只消费 Application ContextStatus/CompactionStatus；Renderer 不从 model config 推算 denominator，也不解析 diagnostics 作为产品状态。
- 在 message/tool/timeline/compact 等有意义的权威收口边界适度刷新 status；等待 Bridge/Application 已清除 active Turn 后刷新一次，不在每字符 delta 上发 RPC。
- 只从 Desktop candidate menu 隐藏冻结的五个命令，不修改 Application registry；compact/new/plan/do 走 direct command/action，Slash 字符串不进入 `turn.start`。
- Model picker 与 `/model` 使用同一 Application catalog；`/status` 只显示用户安全字段。
- manual compact running 时禁止普通发送，结束后恢复；状态只来自 Application。
- move 成功后按 mutation 更新 source/target 可见投影，当前 source selected 被移走时清空 selection/timeline，不自动创建第二 Application。
- 保留 refresh/resume/rename 的既有行位置；new 显式置于 regular 顶部；只有新 durable message 或显式 pin 可触发相应重排。普通 catalog refresh 不按 timestamp 偷偷重排。
- regular Session 超过五个时折叠，selected 第六项以后仍可见且不篡改前五顺序。

### 依赖任务

- T04。

### 参考资料定位

- 原始需求第 2.4～2.5、6、7、15/Task 5、16～21 节。
- A04 当前上下文与当前 App/state/Composer/Sidebar tests。

### 完成边界

Desktop command/context/session 只投影 Application authority；不存在每-delta status 风暴、terminal 刷新竞态或隐式多 runtime。

## T06：Chat、Tool、Todo、AskUser、Plan 交互完成

### 任务目标

完成聊天页交互和可访问性，让每个业务事实在原位更新一个视觉实体，并正确收口 streaming、失败与取消。

### 新增文件

- 仅在当前真实职责和测试边界明确时，可拆出 Renderer 私有 interaction/projection 模块或 feature test suite；不得复制 fixture truth。

### 修改文件

- `desktop/src/renderer/ChatTimeline.tsx`
- `desktop/src/renderer/InteractionSurface.tsx`
- `desktop/src/renderer/Composer.tsx`
- `desktop/src/renderer/CustomSelect.tsx`
- `desktop/src/renderer/state.ts`
- `desktop/src/renderer/app.css`
- `desktop/src/renderer/locales/zh-CN.ts`、`en.ts`
- `desktop/tests/renderer.test.tsx` 或拆出的 feature suites

### 删除文件

- 删除旧 `allow_other` Renderer 分支、最终 Plan 伪 typewriter/重复 block、重复 action/locale/CSS/fixture；不删除现有正确的 Tool in-place 与 Todo replace-all 主链。

### 文件职责及实施内容

- Slash menu 键盘移动后把 active item 滚入视区；Home/End/Enter/Tab/Escape 与 IME composing 正确。
- select 默认向上并按实际空间翻转，不覆盖 active input；modal/menu 关闭后恢复合理焦点。
- Composer/Runtime 控件按原始需求完成布局、icon、tooltip、ARIA 和 reduced-motion；颜色不是唯一状态线索。
- 保持现有 Tool start/finish 同一 row 主链，补齐真实 elapsed running/freeze、failure/cancel 状态与可访问性，禁止退化为双行。
- TaskStateChanged 保持 replace-all；Todo 浮层 compact/hover/focus 行为只属于 UI。
- `PlanContentDelta` 按 turn/tool-call identity 首次创建并追加同一 draft；`PlanProposed` 封口同一 block；matching failure/cancel 收口 draft，不产生第二 plan 或 raw JSON。
- AskUser 支持 1～4 题、前后导航、答案保留、选择题自由输入、最终 review 与一次 typed submit；删除无效“返回聊天”，保留 typed cancel。

### 依赖任务

- T05。

### 参考资料定位

- 原始需求第 4.1～4.2、6、7、11.2/11.6、15/Task 6、16～21 节。
- TUI typed interaction/Plan 当前事实仅作产品边界参考，不复制 TUI 实现。

### 完成边界

Tool、Todo、AskUser、Plan 各自只有一个视觉实体；键盘、IME、焦点、窄屏与动画偏好有自动证据，不改变 Core 权威。

## T07：Settings 语义、API Key reveal 与页面结构修复

### 任务目标

提供用户可理解的 Settings 分类与 Provider/Model 编辑，并以专用窄路径安全 reveal 当前已保存 API Key。

### 新增文件

- 无预设公共模块；可在 Settings 已形成独立当前职责时新增私有局部组件/test suite，旧入口必须删除。

### 修改文件

- `src/uthcode/integrations/config/loader.py`
- `src/uthcode/application/bootstrap.py`
- `src/uthcode/application/__init__.py`
- `src/uthcode/interfaces/desktop/bridge.py`
- `desktop/src/desktop-api.ts`
- `desktop/src/renderer/App.tsx`
- `desktop/src/renderer/SettingsView.tsx`
- `desktop/src/renderer/app.css`
- `desktop/src/renderer/locales/zh-CN.ts`、`en.ts`
- `tests/test_configuration.py`、`tests/test_desktop_bridge.py`
- `desktop/tests/preload.test.ts`、`desktop/tests/renderer.test.tsx` 或拆出的 Settings suites

### 删除文件

- 删除可见 `model_ref` rename、`model`/`model-1` placeholder、清除 Key/已配置旧交互、无调用方的整 API prop 和相关 helper/fixture。

### 文件职责及实施内容

- Integration 只按 user config path + provider profile identity 读取当前保存的 `api_key` 配置表示；literal 原样返回，`env:` 只返回引用，不解析环境变量 secret。
- Application 暴露窄 use case；Bridge 新增只接收 provider identity 的 `settings.reveal_api_key`。普通 `settings.get`、status、event、diagnostics 和 error 继续无明文。
- 不从 Runtime Provider 或 `SecretValue` 反向 reveal，不建通用秘密系统。
- Renderer 通过窄 `onRevealApiKey(providerId)` 调用，不把整个 Desktop API 作为无边界组件依赖。
- revealed cache 与 replacement/touched draft 分离；eye/reveal/hide 不标 dirty、不触发 save、不自动把旧值拼入 write request。关闭 Provider modal、离开 Settings、runtime rebootstrap、组件卸载时清除 reveal cache。
- 保存失败保留真实 replacement 草稿；未触碰 Key 时保留已有配置。
- Settings 复用全局 sidebar 宽度，按分类独立 section/page，使用轻量 group background；Provider 行进入 modal，一个 Provider 支持多个 Models。
- UI 使用“协议”等用户术语，只展示 remote model/display name/limits 等真实概念；内部稳定 ref 自动生成且不可见，不改变公共配置模型。
- model 增删/配置、modal 键盘、焦点、tooltip、ARIA、zh/en 均有测试。

### 依赖任务

- T06。

### 参考资料定位

- 原始需求第 2.6、6、7.2、11.6、13、15/Task 7、16～21 节。
- 当前 configuration/bootstrap/loader/bridge 边界与 Settings 实现/tests。

### 完成边界

已保存 Key 只能通过用户显式专用请求短暂显示，查看与修改无耦合；Settings 不暴露内部引用且支持真实多 Model 编辑。

## T08：GUI 越界、冗余、不可达与过度抽象审查

### 任务目标

对 F02 直接相关 GUI 生产链做工程收敛，按 severity 关闭范围内 finding，并把结论落实为代码删除、合并或局部私有拆分。

### 新增文件

- 仅允许新增已有独立调用/测试边界的私有局部模块或按 feature 拆分的 tests；不得新增公共抽象层。

### 修改文件

- `desktop/src/**`
- `src/uthcode/interfaces/desktop/**`
- T01～T07 直接修改的 Application/Core 公共投影点
- 对应 Python/Desktop tests

### 删除文件

- 删除范围内第二 authority、重复生产链、无调用方 export/helper/action、旧 locale/CSS/test fixture、不可达 fallback 和仅为旧行为存在的兼容分支。

### 文件职责及实施内容

- Correctness：审查 stale closure、旧 RPC 污染、Plan tool-call 混流、重复/乱序 event、compact/turn input gate、Settings save/rebootstrap rollback、menu/modal focus。
- Architecture：确认 Renderer 不重做 Context/Session/Permission/Mode/Todo/Plan authority，Bridge 不绕 Application，raw Provider/tool/diagnostics 不穿界。
- Privacy：确认 Key 明文只在专用 response 与当前组件临时内存；错误、日志、preference、event、Session、Timeline、snapshot 均无明文。
- Maintainability：清除重复 normalize/project、无调用方 export、不可达分支与临时 workaround；说明保留 App/state/Settings 大文件职责仍需共置的原因。
- 禁止新增 Desktop/Session/Context/Plan/Todo Manager、EventBus、未来 Registry/Protocol、通用 JSON streaming 或无第二调用方的 modal/menu framework。
- 记录所有 finding severity、证据、处置和验证；F02 范围内 P0/P1/P2 未关闭则不进入 T09。

### 依赖任务

- T07。

### 参考资料定位

- 原始需求第 2.7、15/Task 8、17～21 节。
- `tests/test_architecture_boundaries.py` 与当前 Desktop source/tests。

### 完成边界

范围内 finding 已关闭，无第二生产链、无新增无调用方抽象；审查不扩成全仓瘦身或新安全项目。

## T09：[接入主流程] Desktop 生产链集成

### 任务目标

把 T01～T08 通过唯一正式链连接并删除被替代入口，验证跨层 identity、状态与错误映射。

### 新增文件

- 无预设生产文件。

### 修改文件

- `desktop/src/desktop-api.ts`（仅跨层类型确有缺口时）
- `desktop/src/renderer/App.tsx`、`state.ts` 及 T01～T08 实际命中的 Renderer 组件
- `src/uthcode/interfaces/desktop/bridge.py`
- T01～T08 实际命中的 Application/Core 接线点
- `tests/test_desktop_bridge.py`、`desktop/tests/renderer.test.tsx` 或已拆出的对应 integration suites

以上只处理真实接线/回归缺陷，不扩大产品范围。

### 删除文件

- 删除已由正式链取代的 Desktop candidate 特判、伪 command/message、Plan/Context/Session/Settings 双入口。

### 文件职责及实施内容

- 验证 Renderer → DesktopApi → 既有 Main/Preload transport → DesktopBridge → Application → Agent Core 唯一生产链。
- 完成 AskUser typed resume、Plan delta/final/review、Context/Compact status、Session move/replay、direct Slash、Settings reveal/save/rebootstrap、Todo/Tool/BehaviorMode 接线。
- Main/Preload/Python runtime 保持既有通用 transport；除非真实固定假设冲突触发停止条件，不修改原始需求明确保留文件。
- 集成修复不得创建 Desktop Core facade、新 runtime 或额外 event/state system。

### 依赖任务

- T08。

### 参考资料定位

- 原始需求第 7、12、15/Task 9、19～22 节。
- A04 Windows Desktop production chain 与前序 Feedback。

### 完成边界

所有 F02 能力从真实 Desktop 入口到权威层只有一条生产链，前序范围内审查 finding 仍保持关闭。

## T10：[端到端验证] Desktop 人工与自动验收

### 任务目标

复用现有自动、CDP 和 packaged acceptance 链完成 F02 端到端验证，并精确记录真实人工矩阵。

### 新增文件

- 不创建第二套视觉/E2E harness；仅在现有 runner 无法表达当前场景时为其增加最小 fixture/flow。

### 修改文件

- `desktop/package.json`（确保实际 acceptance tests 被正式脚本覆盖，按现有脚本结构最小调整）
- `desktop/scripts/cdp-openai-fixture.mjs`
- `desktop/scripts/cdp-driver.mjs`
- `desktop/scripts/cdp-packaged-visual-acceptance.mjs`
- `desktop/tests/cdp-isolation.test.ts`、`settings-acceptance-isolation.test.ts` 及相关现有 acceptance tests（按真实命中）
- 验收暴露前序生产缺陷时，W06 停止对应场景并记录在 W06 Feedback，交由用户重新派发对应 W01～W05 Prompt；被重新派发的 Worker 在自己的原 Feedback 追加返工记录，W06 不跨写集或代写其他 Worker Feedback。

### 删除文件

- 删除失效的 `allow_other`/Other CDP fixture 和只覆盖旧视觉流程的重复分支；不删除现有 harness。

### 文件职责及实施内容

- 更新现有 fixture/driver 以匹配 2～3 options + 始终自由输入、Plan delta、Tool/Todo/Compact/Session/Settings reveal 新合同。
- packaged runner 不得固定只跑不足以覆盖 F02 的 visual 子流；复用既有 isolated launcher、bounded deadline 和 no-second-harness 规则。
- 执行全量 Python tests、Desktop typecheck/tests，以及现有 packaged/CDP acceptance scripts。
- 真实 Desktop 覆盖 dev/packaged、dark/light、zh/en、wide/narrow、keyboard/mouse、IME、zoom、reduced motion、Session >5、AskUser、Plan、Tool、Compact、restart/resume 与 API Key reveal/hide/untouched/replacement。
- 对需要真实 Provider 或干净机条件而无法执行的场景，记录环境、未验证原因和风险，不伪称通过。

### 依赖任务

- T09。

### 参考资料定位

- 原始需求第 15/Task 10、16、18～21 节。
- T10 W06 已有 packaged/CDP runner、fixture、deadline 和 isolation 经验；只作机制证据，不修改冻结文件。

### 完成边界

自动结果和人工矩阵均有精确证据；现有 E2E harness 覆盖新合同且没有第二套测试框架。

## T11：[遗留负担清理] 否定扫描、文档与全量回归

### 任务目标

删除 F02 替代的遗留路径，更新当前事实文档，完成最终回归、UTF-8 与工作包状态核对。

### 新增文件

- `feedback/W06-acceptance-cleanup-feedback.md` 由执行 Worker 首次实施时创建；返工只追加。

### 修改文件

- `docs/Tools.md`
- `docs/Context-Index.md`
- `docs/context/A02-Control/Control-Context.md`
- `docs/context/A03-State/State-Context.md`
- 仅在最终代码事实确实变化时按 `docs/README.md` 维护映射更新其他 current-facts 文档
- 本 F02 Checklist 只勾选已验证项；W01～W06 各自 Feedback 只按规则创建/追加

### 删除文件

- 删除旧 AskUser 字段、Renderer Context authority、可见 model ref/placeholder、Plan 伪 streaming、重复 Tool row、raw arguments Renderer 路径及其失效测试/locale/CSS。
- 不修改或删除 T10 冻结正文/Feedback，不自动归档任何工作包。

### 文件职责及实施内容

- 对原始需求列出的旧符号/路径执行否定扫描，并逐条解释任何合法非生产命中。
- 运行 Python architecture/full tests、Desktop typecheck/tests、compile/pip/diff checks 与必要 acceptance 回归。
- 按最终代码同步 AskUser、Plan、Context/Compact、Session move/replay、Desktop Interface 与 Settings secret reveal 当前事实。
- `docs/OutstandingDebtList.md` 只核对不改写：F02 能力欠账为无，未触发 Persistent Runtime Recovery。
- 对全部新增/修改 Markdown 执行 UTF-8、replacement/mojibake 和 fence 平衡检查。
- 盘点 `docs/work/` 与 archive，更新 Context Index 快照：T10 仍按冻结 Checklist 保持 `not_implemented`，F02 仅在 Checklist 全部完成且 Feedback 齐全时才可标 `implemented_unarchived`；否则保持 `not_implemented`。

### 依赖任务

- T10。

### 参考资料定位

- 原始需求第 5、15/Task 11、16～22 节。
- `docs/README.md`、WorkPackageRules、OutstandingDebtList 与 current facts docs。

### 完成边界

否定扫描、文档、全量回归与 UTF-8 检查闭合；未验证项明确；不自动归档、不执行未经授权的 Git 写。
