# UthCode F02：DesktopGUI交互与上下文缺陷修复任务书

## 1. 分析基线

### 1.1 目标仓库与固定基线

```text
仓库：https://github.com/undertaker33/Re-UthCode
Commit：d0359f352c3d0a78fd03f08839c4a3d7df62ecb1
```

所有文件规划、公共协议变化、测试和验收均以该 Commit 为唯一代码基线。不得在实施时把 T10 后续提交、旧任务书中的预期结构或历史聊天记忆当作既成事实。

### 1.2 本任务需求来源

- `F02-DesktopGUI交互与上下文缺陷修复.md`
- `F02-DesktopGUI交互与上下文缺陷修复-探索提示词.md`
- `docs/work/T10-DesktopGUI与TUI全量能力迁移/uthcode-desktop-ui-prototype-v5.html`：仅作为既定 GUI 视觉/交互参考，不作为运行时权威。
- 用户本轮追加的 F02 强制范围：
  1. GUI 越界检查；
  2. GUI 冗余代码和不可达代码清理；
  3. GUI 提前抽象和过度抽象清理；
  4. GUI 相关代码审查。

### 1.3 用户最终拍板

以下决定已冻结，实施阶段不得重新讨论：

1. **AskUserQuestion 的所有选择题都天然允许自然语言“自行输入”。**
   - 这是 Core 公共交互协议变化，不是 Desktop 特例。
   - `single_select` / `multi_select` 均允许答案值不命中结构化 option。
   - 结构化 option 数量由当前 `2..6` 收敛为 `2..3`。
   - 既然所有选择题都允许自由输入，现有 `allow_other` 不再具有产品语义；本任务删除该字段及其分支，而不是保留一个永远为真的兼容开关。

2. **正式 Plan 必须是真实流式展示。**
   - 允许增加一个最小、Provider-independent、display-safe 的公共 AgentEvent：`PlanContentDelta`。
   - `PlanContentDelta` 只传递已从 `ProposePlan.plan` 参数中解码出的自然语言增量；禁止把 Provider 原生事件、raw JSON arguments、SDK payload 传给 Application/Desktop。
   - `PlanProposed` 继续是完整正式计划、revision 和 Plan Review 的唯一权威边界。

### 1.4 已读取的全局约束与相关已完成任务

- `AGENTS.md`
- `docs/rules/WorkPackageRules.md`
- `docs/rules/UserDecisionBoundary.md`
- `docs/OutstandingDebtList.md`
- `docs/work/archive/T08-任务规划与执行控制/`
- `docs/work/archive/T09-Prompt与ContextEngineering/`
- `docs/work/archive/T09-1-Context预算与Compact协议补齐/`
- `docs/work/archive/T09-2-工程收敛与提前抽象清理/`
- `docs/work/archive/T09-3-256KContext工程调优与通用失败语义/`
- `docs/work/archive/F01-TUI回复链路与Session恢复修复/`
- 当前活动 T10 Desktop 工作包仅用于核对既有实现和冻结边界；**F02 不修改 T10 已冻结的 spec/task/checklist/prompt/feedback。**

### 1.5 实际读取的关键源码

```text
src/uthcode/core/interaction.py
src/uthcode/core/provider.py
src/uthcode/core/planning.py
src/uthcode/core/agent_events.py
src/uthcode/core/agent.py
src/uthcode/application/configuration.py
src/uthcode/application/context.py
src/uthcode/application/generation.py
src/uthcode/application/sessions.py
src/uthcode/interfaces/desktop/bridge.py
src/uthcode/interfaces/tui/interaction.py

desktop/src/renderer/App.tsx
desktop/src/renderer/state.ts
desktop/src/renderer/Composer.tsx
desktop/src/renderer/ChatTimeline.tsx
desktop/src/renderer/InteractionSurface.tsx
desktop/src/renderer/RuntimePanel.tsx
desktop/src/renderer/SettingsView.tsx
desktop/src/renderer/Sidebar.tsx
desktop/src/renderer/CustomSelect.tsx
desktop/src/renderer/app.css
desktop/package.json
```

### 1.6 关键测试基线

```text
tests/test_agent_interaction.py
tests/test_agent_events.py
tests/test_agent_loop.py
tests/test_planning.py
tests/test_application_runs.py
tests/test_session_authority.py
tests/test_desktop_bridge.py
tests/test_w05_diagnostics.py
tests/test_tui.py

desktop/tests/renderer.test.tsx
desktop/tests/preload.test.ts
desktop/tests/runtime-process.test.ts
desktop/tests/cdp-isolation.test.ts
```

### 1.7 外部资料

本任务最终设计不依赖新的第三方协议或外部 Agent 机制。当前真实 Core/Application/Desktop 链路已经足以确定 F02 的实现边界，因此**不引入外部项目作为产品权威，也无新增外部参考结论需要固化。**

---

## 2. 当前实现基线

### 2.1 Desktop 的正确架构边界已经存在

当前主链是：

```text
React Renderer
    ↓ JSON-safe DesktopApi
Preload / Electron Main
    ↓ JSONL child-process transport
Python DesktopBridge
    ↓ Application public API / AgentEvent
UthCodeApplication / AgentRun
    ↓
Agent Core
    ↓
Integrations / Provider / Session files
```

`DesktopBridge` 已明确定位为“小型 Application adapter，而不是第二套 runtime”。Renderer 可以维护展示态、菜单开合、当前 hover/focus、局部草稿和计时器，但不能拥有 Session、Context、Permission、Task、Plan、Provider、Command 的第二套业务事实。

### 2.2 AskUserQuestion 当前 Core 合同与本次拍板冲突

当前 `UserQuestion`：

```text
kind = text | single_select | multi_select
options = 2..6（select）
allow_other = bool，默认 false
```

`UserInputRequest.validate_answers()` 当前在 `allow_other=false` 时拒绝不在 option label 集合中的答案。因此仅在 Desktop 永远显示“自行输入”会形成 Interface 宣称可用、Core 实际拒绝的越界。

本任务必须从 Core 改成：

```text
select question
├─ options: 2..3
└─ arbitrary natural-language answer: always allowed
```

`allow_other` 因此成为无效分支，必须随协议更新删除。

### 2.3 Plan 已有完整提交事件，但没有正式内容增量事件

当前 Provider Port 已经拥有：

```text
ToolCallStarted
ToolCallArgumentsDelta
ToolCallCompleted
```

`ProposePlan` 的 schema 又固定为：

```json
{"plan": "..."}
```

但公共 AgentEvent 只有：

```text
PlanProposed(iteration, revision, plan_text)
```

所以现状只能在完整 `ProposePlan` 参数解析后显示整块计划。Renderer 如果自行打字机播放 `PlanProposed.plan_text`，只是伪流式。

本任务直接利用已经存在的 Core-owned `ToolCallArgumentsDelta`，在 Agent Core 内仅对 `ProposePlan` 的 `plan` 字符串进行增量解码，再映射成新的 `PlanContentDelta`。不增加通用 Tool JSON streaming 框架。

### 2.4 Context 当前存在 Renderer 二次判定

`desktop/src/renderer/state.ts` 当前存在：

```text
DEFAULT_CONTEXT_WINDOW = 256_000
configuredContextWindow(...)
normalizeContextUsage(...)
```

且 `normalizeContextUsage()` 有意忽略 Application 返回的 `budget_tokens`，改用 Renderer 自己从 model config 推导 denominator。

这已经突破 Context 权威边界：

```text
Application / ContextBudget
       ↓ 应为唯一安全预算
Renderer
       ↓ 当前又推一次
第二套 Context window 语义
```

F02 必须删除 Renderer 的权威预算推导。256K 默认、model 配置、Provider ceiling、output reserve、安全余量、Auto/Hard Gate 的结果统一在 Application/Context 层形成 display-safe 投影。

### 2.5 Session move 的真实失败链已定位

当前 Desktop 已经调用：

```text
session.move
→ DesktopBridge._session_move()
→ application.move_session(...)
→ ApplicationSessionService.move_session(...)
```

但 `ApplicationSessionService.move_session()` 对当前 active Session 直接返回 `busy`。Desktop 侧即使当前没有 active Turn，用户正在看的 Session 仍由 Application 持有 writer，因此最常见的“移动当前 Session”会失败。

本任务不另建 Desktop Session mover。应在 Application Session authority 中支持“**无 active Turn 时移动当前已打开 Session**”：在既有 writer lock 下完成 close-time state sync → 原子更新 project membership → release writer；失败时保留旧 Session/旧 project 所有权。

移动成功后当前 source Application 不再拥有该 Session；Desktop 清除该 source 下的 selected Session/timeline，不自动伪装成仍可继续写入，也不创建第二 Application。目标项目 catalog 在可见/展开时刷新即可。

### 2.6 Settings 当前泄漏内部引用概念

Application 的长期配置合同已经明确区分：

```text
ProviderProfile.provider_profile_id
ModelProfile.model_ref
ModelProfile.remote_id
ModelProfile.display_name
```

其中 `model_ref` 是稳定内部引用，不等于用户输入的 remote model ID。

当前 `SettingsView.tsx` 却：

- 允许用户直接 rename `model_ref`；
- 空配置时制造 `provider` / `model`；
- 新建时继续生成 `provider-1` / `model-1`；
- 让内部引用成为可见配置概念。

本任务不改 `ProviderProfile` / `ModelProfile` 的长期配置语义；只把稳定引用收回实现内部。新增 model 使用 Renderer 内部生成的稳定、不可见唯一 key，UI 只展示/编辑当前真实用户概念：协议、Base URL、API Key、remote model ID、display name、context window、max output tokens、reasoning effort。

API Key 不再是“只在本次编辑中临时输入、保存后不可回看”的字段。**只要该 Provider 已配置 API Key，Settings 中的 eye 按钮就必须始终可用，用户显式点击后可以查看当前已保存的 Key。** 普通 `settings.get` 仍只返回 `api_key_configured` 等安全投影；明文只允许通过专用 `settings.reveal_api_key` 请求按 Provider 单次读取。若用户配置保存的是 `env:VARIABLE_NAME`，reveal 返回该已配置引用本身，不解析并暴露环境变量中的实际 secret。点击 reveal 只表示查看，不得把该 Key 标记为 changed，也不得在未编辑时随 `settings.save` 回写。

### 2.7 GUI 工程收敛基线

当前 Renderer 已有明显高风险热点：

- `state.ts` 约 49KB，集中 Session、Timeline、Context、Todo、Run、Command、Settings 多类投影；
- `App.tsx` 约 30KB，同时承担 bootstrap、preferences、Project、Session、Command、Settings、Turn orchestration 和页面组装；
- `SettingsView.tsx` 约 26KB，混合配置 DTO 变换、ID 管理、API Key reveal/替换临时状态、modal 行为和页面渲染；
- `renderer.test.tsx` 超过 100KB。

F02 的目标不是机械按行数拆文件，而是对本次直接触达的 GUI 链做一次收敛：删除无用分支、重复 authority、伪兼容和无调用方 helper；只有当当前真实职责已经形成独立调用/测试边界时才拆文件。不得趁机创建 `DesktopManager`、`ContextManager`、`SessionStore`、`EventBus`、通用 modal framework、通用 command framework 等新抽象。

---

## 3. 问题定义

F02 解决的是：

> T10 已经打通 Desktop GUI 的生产链路，但实际人工使用暴露出多项“交互可用性 + 状态权威 + 上下文安全投影 + GUI 工程收敛”缺陷；其中 AskUser 和 Plan streaming 还需要补齐 Core 稳定产品语义，不能靠 Renderer 伪造。

当前已有能力不能完整解决，主要因为：

1. AskUser 的自由输入仍受 `allow_other` 控制，与最终产品行为不一致；
2. `ProposePlan` 原始 Provider 参数虽流式到达，但没有 display-safe Plan 内容增量事件；
3. Renderer 自己计算 Context window，形成第二权威；
4. active Session writer 使当前 Session move 永远容易命中 `busy`；
5. Slash、Settings、Session 排序、Tool/Todo/AskUser/Plan 表现仍混有 T10 原型期实现；
6. GUI 代码中已经出现重复语义、内部概念泄漏和大文件职责堆积，需要在 F02 触达范围内收敛。

---

## 4. 任务目标

F02 完成后必须形成以下最小完整链路。

### 4.1 AskUser

```text
Model → AskUserQuestion tool call
        ↓
Core UserInputRequest
  select options = 2..3
  arbitrary answer always valid
        ↓
Application pause/resume
        ↓
Desktop / TUI render structured options + 自行输入
        ↓
UserInputResponse
        ↓
Core authoritative validation
        ↓
同一 Turn 恢复
```

### 4.2 Plan streaming

```text
Provider ToolCallArgumentsDelta(ProposePlan)
        ↓
Agent Core 私有 plan 字符串增量解码
        ↓
PlanContentDelta（仅自然语言文本）
        ↓
Application / DesktopBridge 原样转发稳定 AgentEvent
        ↓
Renderer 同一 Plan block 增量更新
        ↓
ToolCallCompleted + parse_propose_plan_arguments
        ↓
PlanState / PlanProposed
        ↓
正式 Plan Review
```

### 4.3 Context

```text
Transcript / Timeline / current Turn / model config / provider limits
        ↓
Application Context Compiler + ContextBudget
        ↓
Application display-safe ContextStatus
  used / budget / measurement kind
        ↓
DesktopBridge status.get
        ↓
Renderer Context ring / RuntimePanel
```

Renderer 只显示，不再计算安全预算。

### 4.4 Session move

```text
Desktop session.move
        ↓
DesktopBridge path/trust validation
        ↓
ApplicationSessionService
        ↓
writer lock 下同步并改变 project membership
        ↓
SessionMutation
        ↓
source catalog refresh + target catalog refresh
```

### 4.5 本次最终交付

- Core AskUser 最终协议；
- Core/AgentEvent 最小 Plan streaming 协议；
- Application-owned Context / Compaction 用户安全投影；
- 当前 Session 可移动的 Application 语义；
- F02 所列 Slash、Session、Composer、Settings、Tool、Todo、AskUser、Plan、动画与布局修复；
- GUI 越界检查和对应修复；
- GUI 冗余/不可达/提前抽象清理；
- GUI Code Review 结论落实到代码和测试；
- 全量回归与真实 Desktop 验收。

---

## 5. 能力欠账

无。

本任务**不触发** `docs/OutstandingDebtList.md` 中 T05/T06/T09 的 Persistent Runtime Recovery 欠账。F02 只要求在重启/恢复一个**已经安全落盘的 durable Session** 后，基于 Transcript/Timeline/Context Compiler 重建可用 Context 投影；不恢复进程退出时仍 active/paused 的 Turn、AskUser waiter、Permission waiter、Plan Review waiter、Provider coroutine 或 pending Tool。

已有 Persistent Runtime Recovery 欠账保持原样，不在本任务书生成阶段修改 `docs/OutstandingDebtList.md`。

---

## 6. 核心产品行为

| 场景 | 输入 / 前置状态 | 预期行为 | 状态变化 | 对外结果 |
| --- | --- | --- | --- | --- |
| AskUser 单选 | 2~3 个结构化 option | 始终显示“自行输入” | 选 option 或输入自由文本 | 任一非空答案可进入 typed resume |
| AskUser 多选 | 2~3 个结构化 option | 允许结构化选项与自由文本答案 | 保留本题草稿 | 至少一个答案后可继续 |
| AskUser 多题 | 1~4 题 | 上一题/下一题可切换，答案不丢 | 只维护 Renderer 草稿 | 最后进入统一 review 再提交 |
| AskUser 取消 | pending user input | 使用已有 typed cancel/resume 边界 | Turn 取消/恢复按 Core 规则 | 不出现“返回聊天”伪状态 |
| Plan 生成 | PLAN 模式且模型调用 ProposePlan | 正式计划文本真实逐段出现 | 同一 draft block 增量更新 | 不等完整结果后打字机伪装 |
| Plan 完成 | ProposePlan 参数完整合法 | `PlanProposed` 覆盖/封口 draft | PlanState revision 成为权威 | 展示 Review 控件 |
| Plan 参数失败 | raw tool args 无法形成合法最终 payload | 不产生 `PlanProposed` | draft 标记失败/随 Turn 失败收口 | 不泄漏 raw arguments |
| Plan 取消 | Turn/tool cancelled | 停止增量 | draft 标记 cancelled | 不残留“仍生成中” |
| Context cold resume | durable Session 被 resume | Application 用 durable state 重编译安全投影 | usage kind 为 estimate/unavailable，不伪造 exact | Context ring 恢复可用值或明确 unknown |
| Context running | message/tool/timeline/request 变化 | Application 更新 ContextStatus | Renderer 拉取/消费新投影 | ring 随真实权威变化 |
| Provider exact usage | Provider terminal usage 可用 | Application 标明 exact measurement | exact 只对应该已测请求 | UI 可区分 estimate / exact |
| Manual compact | idle Session | 同一 Application compaction authority 执行 | idle→running→completed/no_change/failed/cancelled | Composer 禁止普通发送，活动状态可见 |
| Auto/overflow compact | Context gate 触发 | 继续走既有 single-flight / recovery | 同一 CompactionStatus | Desktop 不创建第二 FSM |
| Session move inactive | 无 active Turn | Application 原子修改 project membership | source→target | source 消失，target 可见 |
| Session move current open | 当前 Session 已打开但无 active Turn | 在当前 writer lock 下同步、移动并 release | source Application 不再持有该 Session | selected Session/timeline 清空，不自动假装仍可写 |
| Session move active Turn | 有 active Turn | 拒绝 | 无变化 | 稳定 `turn_active/session_busy` 错误 |
| Session rename/resume/refresh | existing Session | 不改变导航顺序 | metadata 更新 | 行位置不跳动 |
| New Session | session.new 成功 | 新 Session 置于 regular list 顶部 | presentation order 更新 | 立即可见 |
| 新消息提交 | 当前 Session 获得新的 durable Turn 内容 | 该 Session 按既定 recent 规则更新 | presentation order 允许变化 | 这是普通 Session 唯一自动重排原因之一 |
| Slash candidate | 输入 `/` | 隐藏 clear/quit/resume/permission/help | 仅 candidate projection 变化 | Application registry 本体不删 |
| Slash direct action | 选择 compact/new/plan/do | 直接执行 Application/GUI action | 对应权威状态变化 | 不把 slash 文本作为用户消息发给模型 |
| `/model` | 选择 `/model` | 使用 Application completion/model authority | ModelSelected | 与 Composer model picker 同一 catalog |
| `/status` | 执行 status | 只展示用户可理解、安全信息 | 无核心状态变化 | diagnostics/private payload 不进入聊天 UI |
| Settings 新 Model | 用户填写 remote model 等 | 内部生成不可见稳定 model_ref | config draft 更新 | 不出现 `model` / `model-1` 可见概念 |
| Tool running | ToolStarted | 同一行显示活动态与真实经过时间 | ephemeral timer | 完成后原地变 success/failure/cancelled |
| Todo | TaskStateChanged | replace-all 更新浮层 | Renderer 投影替换 | 不维护第二 Todo Store |
| reduced motion | OS prefers-reduced-motion | 禁用/缩短非必要动画 | 无业务变化 | 功能和焦点行为保持 |

---

## 7. 架构归属

| 能力 | 所属模块 | 状态所有者 | 调用方 | 依赖方向 | 原因 |
| --- | --- | --- | --- | --- | --- |
| AskUser 问题/答案语义 | `core/interaction.py` | Core immutable request / active Turn | Agent Loop / Application | Application → Core | 选择题是否接受自由文本是稳定产品协议 |
| Plan draft 增量语义 | `core/agent_events.py` + `core/agent.py` | active Agent Turn | Application / Interfaces | Application → Core | 需要 Provider-independent、display-safe 公共事件 |
| ProposePlan raw 参数解码 | Core 私有实现 | 当前 Tool call | Agent Loop | Core ProviderEvent → private decoder | raw ProviderEvent 已被 UthCode Core 统一，不需要 Interface 参与 |
| 正式 Plan | `PlanState` / `PlanProposed` | RunState / Agent Loop | Application / Interfaces | Application → Core | 保持 T08 既有权威 |
| Context budget / usage | Application Context + Core Context | Application / Context service | Desktop/TUI/Headless | Interface → Application → Core | Renderer 不得自行决定安全窗口 |
| Compaction lifecycle | Application | Application Context service / command use case | Desktop status projection | Interface → Application | manual/auto/overflow 必须共用已有 single-flight |
| Session move | Application Session service | Application + Session writer | Desktop/TUI command/use case | Interface → Application → Integration | Session 文件/锁不能由 Renderer 操作 |
| Session 导航顺序 | Renderer presentation projection | Renderer | Sidebar | UI-only | 排序是展示行为，不改变 durable Session truth |
| Slash candidate visibility | Renderer presentation filter | Renderer | Composer | UI-only | Application registry 仍是唯一命令目录 |
| Model/Permission/Todo/Plan 展示 | Renderer projection | Core/Application 为事实所有者 | Renderer | 单向投影 | 禁止第二业务状态机 |
| API Key reveal / 替换草稿 | Application user-config read + Settings local UI state | Application 持有配置读取权威；Renderer 仅持按需明文与编辑草稿 | Settings | UI → `settings.reveal_api_key` / `settings.save` → Application | 普通配置投影不带明文；显式 reveal 才下发当前已配置值；明文仅驻留 Renderer 临时内存，不进 preference/event/log/diagnostics |

### 7.1 新公共协议说明：`PlanContentDelta`

现有 `AssistantMessageDelta` 不能复用，因为正式 Plan 不是普通 assistant message；`PlanProposed` 又只允许完整、可 review 的最终计划。因此新增：

```text
PlanContentDelta
  run_id: str
  turn_id: str
  iteration: int
  tool_call_id: str
  text: str
```

约束：

- `text` 是**已解码的 plan 自然语言增量**；
- 不包含 JSON key、引号、escape、Provider SDK 类型或 native payload；
- `tool_call_id` 只用于在同一 Turn 内把 draft 与最终 `PlanProposed`/Tool terminal 关联；
- 不持久化“正在生成”的 draft；
- Session replay 只从 durable 完整 `ProposePlan` tool call 投影最终 plan block；
- 不新增 Plan Event Bus、Plan Registry、Plan Manager。

### 7.2 API Key 显式 reveal 合同

F02 新增一个**窄、用户主动触发**的 Settings secret-read 路径，目的只有一个：让已经保存的 API Key 在任何时候都能通过 eye 按钮查看，而不是只有刚输入尚未保存时可见。

```text
Settings 普通加载
  → settings.get
  → UserConfigurationView
  → 只含 api_key_configured
  → 不含 API Key 明文

用户点击 eye
  → settings.reveal_api_key(provider_profile_id)
  → Application 读取用户级 config 中该 Provider 的 api_key 配置值
  → DesktopBridge 返回本次 reveal result
  → Renderer 临时内存显示

用户仅查看/再次隐藏
  → 不产生 settings.save
  → 不标记 touched

用户实际修改输入框
  → replacement/touched = true
  → settings.save 显式写入新值
```

冻结约束：

- reveal 只读取**用户级配置**中该 Provider 当前保存的 `api_key` 配置表示；项目配置无权提供或覆盖 secret；
- literal Key 返回 literal；`env:VARIABLE_NAME` 返回该配置引用字符串，不解析环境变量实际值；
- 不允许为了 reveal 调用 `SecretValue.reveal()` 从已解析运行时 Provider 状态反向取 secret；读取必须沿 Application → Integration 的用户配置读取边界完成；
- `settings.get`、Application status、Run snapshot、AgentEvent、Session replay、diagnostics 继续保持 secret-free；
- `settings.reveal_api_key` 是唯一允许携带该配置值的 Desktop JSON response；错误响应不得包含 Key；
- Renderer 的 revealed cache 与 replacement draft 必须分离；reveal 不改变 dirty/touched；
- 明文不写入 `DesktopPreferences`、local/session storage、日志、错误、测试快照或持久 reducer state；只保留完成当前显示所需的组件内临时状态；
- 关闭 Provider 编辑面、离开 Settings、切换 Project/runtime、组件卸载时清除 revealed cache；
- 不建设通用 Secret Manager、Credential Vault、secret event 或 secret registry。

---

## 8. 外部参考结论

无。本任务没有新增外部参考依赖。

---

## 9. 目标目录树

仅列 F02 实际涉及范围。

```text
src/uthcode/
├─ core/
│  ├─ interaction.py                         [修改]
│  ├─ planning.py                            [修改]
│  ├─ agent_events.py                        [修改]
│  ├─ agent.py                               [修改]
│  └─ __init__.py                            [修改]
├─ application/
│  ├─ bootstrap.py                           [修改]
│  ├─ generation.py                          [修改]
│  ├─ context.py                             [修改]
│  ├─ sessions.py                            [修改]
│  └─ __init__.py                            [修改]
├─ integrations/
│  └─ config/
│     └─ loader.py                           [修改]
└─ interfaces/
   ├─ desktop/
   │  └─ bridge.py                           [修改]
   └─ tui/
      └─ interaction.py                      [修改]

desktop/
├─ src/
│  ├─ desktop-api.ts                         [修改]
│  └─ renderer/
│     ├─ App.tsx                             [修改]
│     ├─ state.ts                            [修改]
│     ├─ Composer.tsx                        [修改]
│     ├─ ChatTimeline.tsx                    [修改]
│     ├─ InteractionSurface.tsx              [修改]
│     ├─ RuntimePanel.tsx                    [修改]
│     ├─ SettingsView.tsx                    [修改]
│     ├─ Sidebar.tsx                         [修改]
│     ├─ CustomSelect.tsx                    [修改]
│     ├─ app.css                             [修改]
│     └─ locales/
│        ├─ zh-CN.ts                         [修改]
│        └─ en.ts                            [修改]
└─ tests/
   ├─ preload.test.ts                         [修改]
   └─ renderer.test.tsx                      [修改]

tests/
├─ test_agent_interaction.py                 [修改]
├─ test_agent_events.py                      [修改]
├─ test_agent_loop.py                        [修改]
├─ test_planning.py                          [修改]
├─ test_application_runs.py                  [修改]
├─ test_session_authority.py                 [修改]
├─ test_desktop_bridge.py                    [修改]
├─ test_configuration.py                     [修改]
├─ test_w05_diagnostics.py                   [修改]
└─ test_tui.py                               [修改]

docs/
├─ Tools.md                                  [修改]
├─ Context-Index.md                          [修改]
└─ context/
   ├─ A02-Control/Control-Context.md          [修改]
   └─ A03-State/State-Context.md              [修改]
```

### 9.1 明确保留不动

```text
docs/work/T10-DesktopGUI与TUI全量能力迁移/**
desktop/src/main.ts
desktop/src/preload.ts
desktop/src/python-runtime.ts
src/uthcode/integrations/providers/**
src/uthcode/integrations/session_files.py
```

只有编码阶段发现上述“保留不动”文件存在与本任务关键假设直接冲突，且不修改就无法完成冻结产品行为时，才触发“编码停止条件”，不得私自扩大范围。

---

## 10. 文件级任务清单

| 文件路径 | 操作 | 文件职责 | 核心类型 / 函数 | 输入 | 输出 | 允许依赖 | 禁止依赖 | 对应测试 | 验收条件 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `src/uthcode/core/interaction.py` | 修改 | AskUser 稳定协议 | `UserQuestion`, `UserInputRequest.validate_answers`, `ASK_USER_TOOL_DEFINITION` | Tool args / typed answers | immutable request / validated answers | Core provider DTO | Interface/Application | `test_agent_interaction.py` | select=2..3；任意非空自由文本合法；`allow_other` 删除 |
| `src/uthcode/core/planning.py` | 修改 | ProposePlan 最终解析 + 私有增量文本解码 | `PROPOSE_PLAN_TOOL_DEFINITION`, `parse_propose_plan_arguments`, 私有 plan delta decoder | `ToolCallArgumentsDelta.arguments_delta` | decoded natural-language delta | Core provider types | Renderer/SDK | `test_planning.py`, `test_agent_loop.py` | 跨 chunk/escape/unicode 正确；最终 parser 仍权威 |
| `src/uthcode/core/agent_events.py` | 修改 | display-safe Agent events | `PlanContentDelta`, serializer/parser union | decoded plan text | public AgentEvent | Core DTO | Provider SDK/native payload | `test_agent_events.py` | JSON round-trip；无 raw arguments |
| `src/uthcode/core/agent.py` | 修改 | Agent Loop event mapping | Provider tool argument deltas → PlanContentDelta；final → PlanProposed | ProviderEvent | AgentEvent stream | Core provider/planning | Interface | `test_agent_loop.py` | 只对 ProposePlan 产生 plan delta；失败/取消不伪造 proposed |
| `src/uthcode/core/__init__.py` | 修改 | Core public export | `PlanContentDelta` | Core symbol | export | Core | - | import tests | 新事件可由 Application 正常导入 |
| `src/uthcode/application/context.py` | 修改 | Context 安全投影来源 | context status / compaction lifecycle 的现有 service 状态 | Context snapshot/budget/accounting | safe status data | Core context | Renderer | `test_application_runs.py`, `test_w05_diagnostics.py` | 能表达 current estimate、effective budget、measurement kind、compaction state |
| `src/uthcode/application/generation.py` | 修改 | Application status / Run composition / Session boundary context refresh | `ApplicationStatus`, `status()`, `_refresh_context_for_session`, compaction use cases | current model/session/provider facts | display-safe status | Core + Application | Interface internals | `test_application_runs.py`, `test_w05_diagnostics.py` | cold resume 可重建；running 状态更新；不把 diagnostics 当 UI contract |
| `src/uthcode/application/sessions.py` | 修改 | Session authority / replay | `move_session`, `SessionReplayRecord`, `_project_replay` | session id + target project | `SessionMutation`, safe replay | session file Integration | Desktop file I/O | `test_session_authority.py` | 当前 idle open Session 可原子移动；replay 识别完整 Plan block |
| `src/uthcode/application/__init__.py` | 修改 | Application public export | 新/扩展 safe DTO/Event export | Application types | public surface | Application/Core | Interface concrete types | import/application tests | Desktop 无需绕过 Application |
| `src/uthcode/application/bootstrap.py` | 修改 | 用户配置 Application 边界 | 专用 API Key configured-value reveal use case | provider profile id | `str | None` configured key representation | Integration config reader | Runtime Provider/SecretValue 反向 reveal | `test_configuration.py` | literal/env reference 可按需读取；未知 Provider 安全失败；不改变普通 `UserConfigurationView` |
| `src/uthcode/integrations/config/loader.py` | 修改 | 用户配置文件读取适配 | 最小 raw configured API Key 读取 helper | user config path + provider id | configured `api_key` representation | TOML/config data | Desktop/Renderer | config tests | 不解析 env secret；不返回其他 provider secret；无通用 Secret Store |
| `src/uthcode/interfaces/desktop/bridge.py` | 修改 | Desktop/Application adapter | `_status_result`, `_session_move`, `_replay_values`, `settings.reveal_api_key`, command projection | JSON request | JSON-safe result/event；专用 reveal response 可含本次配置值 | Application public exports | SDK/Session files/Runtime SecretValue 反向读取 | `test_desktop_bridge.py` | storage/busy 等稳定映射；plan replay；context/compact safe status；API Key 仅专用 reveal 路径过线 |
| `src/uthcode/interfaces/tui/interaction.py` | 修改 | TUI AskUser 适配 | select answer UI | `UserInputRequest` | `UserInputResponse` | Application/Core contract | Desktop | `test_tui.py` | TUI 与 Core 新“始终可自行输入”语义一致 |
| `desktop/src/desktop-api.ts` | 修改 | Renderer/Main 公开 Desktop RPC 类型 | `settings.reveal_api_key` runtime method | provider profile id | JSON reveal result | Electron IPC JSON contract | secret persistence | preload/main/renderer tests | 专用 method 可调用；不把 Key 加入 preference 类型 |
| `desktop/src/renderer/state.ts` | 修改 | Renderer 单一投影 reducer | context/session/timeline/todo/plan actions | JSON-safe Application facts | UI state | Desktop types | Core safety算法/文件系统 | `renderer.test.tsx` | 删除 Context 二次权威；plan draft in-place；session 排序稳定 |
| `desktop/src/renderer/App.tsx` | 修改 | Desktop workflow orchestration | status refresh、direct Slash、session move/catalog refresh、settings | DesktopApi | reducer actions | DesktopApi | Core/Integration direct import | `renderer.test.tsx` | 无用户文本伪 command；Context 从 status；move 事务结果驱动 UI |
| `desktop/src/renderer/Composer.tsx` | 修改 | 输入、slash/model/permission/context 控件 | menu keyboard/autoscroll/select placement | Renderer projection | user action | React | Application semantics复制 | `renderer.test.tsx` | hidden candidates、direct action、upward select、toolbar 样式/可达性 |
| `desktop/src/renderer/ChatTimeline.tsx` | 修改 | Chat/tool/plan/todo 展示 | tool in-place/elapsed、plan stream block | TimelineEntry | DOM | React | raw Provider | `renderer.test.tsx` | 同 tool 不重复；Plan 同 block 更新；状态非仅靠颜色 |
| `desktop/src/renderer/InteractionSurface.tsx` | 修改 | AskUser/Permission/Plan Review 输入面 | AskUser multi-question/review，自由输入；Plan review | PendingInteraction | typed resume request | DesktopApi contract | 自定义核心状态机 | `renderer.test.tsx` | 1~4题、前后切换、review、cancel、焦点/滚动正确 |
| `desktop/src/renderer/RuntimePanel.tsx` | 修改 | user-facing runtime/context info | ContextStatus/CompactionStatus render | Renderer state | DOM | renderer state | diagnostics raw dump | `renderer.test.tsx` | `/status` 与 panel 均只展示安全、可理解字段 |
| `desktop/src/renderer/SettingsView.tsx` | 修改 | Settings 分类页 + provider/model modal | config draft + reveal cache + replacement draft | `UserConfigurationView` projection / 显式 reveal result | `settings.reveal_api_key` / `settings.save` | React/Desktop API | secret 持久化到 preference/state snapshot、内部 ref UI | `renderer.test.tsx` | 已配置 Key 随时可 eye reveal/hide；查看不等于修改；无 visible model_ref/model-1；多 model |
| `desktop/src/renderer/Sidebar.tsx` | 修改 | Project/Session 导航 | collapse/order/context menu/move | ProjectState | user action | React | Session storage | `renderer.test.tsx` | new 顶部；existing 不乱序；>5 折叠；selected 仍可见；菜单碰撞处理 |
| `desktop/src/renderer/CustomSelect.tsx` | 修改 | 统一当前 select 的定位/键盘行为 | placement + collision flip | options/value | selection | React | business authority | `renderer.test.tsx` | 默认向上、空间不足翻转、键盘/IME 不回退 |
| `desktop/src/renderer/app.css` | 修改 | F02 视觉/动画 | reduced motion、settings group、tool/plan/todo/toolbar/menu | classes | styling | CSS | - | renderer/CDP visual | dark/light、zoom、narrow 无裁切/闪烁 |
| locale files | 修改 | 中英文本 | 新/删除 UI label | translation key | string | i18n | diagnostics | renderer tests | zh/en 无缺 key；术语“协议”等一致 |
| Python/Renderer 测试文件 | 修改 | 行为证明 | 见测试矩阵 | fixture | assertions | 测试依赖 | 真实网络模型 | all | 关键行为红绿闭环 |
| current facts docs | 修改 | 同步公开协议事实 | AskUser/Plan/Context/Session boundary | final code | docs | current facts | 冻结 T10 文档修改 | doc checks | 文档与最终代码一致 |

---

## 11. 关键数据结构与状态

### 11.1 AskUser：删除 `allow_other`

最终 `UserQuestion`：

```text
UserQuestion
├─ question_id
├─ header
├─ question
├─ kind
└─ options
    ├─ TEXT          → 0 option
    ├─ SINGLE_SELECT → 2..3 options + arbitrary one answer
    └─ MULTI_SELECT  → 2..3 options + arbitrary answer values
```

生命周期：

- 由 Core 从 AskUser tool args 创建；
- active Turn pause 期间存在；
- 通过 `UserInputResponse` 恢复；
- 不因 F02 增加新的 durable runtime checkpoint；
- 不跨进程恢复 pending AskUser。

### 11.2 Plan draft 与正式 Plan 分离

```text
Provider raw argument delta
        ↓
private decoder buffer（active tool call 内）
        ↓
PlanContentDelta
        ↓
Renderer TimelineEntry(kind=plan, streaming=true)
        ↓
PlanProposed
        ↓
PlanState(revision,text,approved)
```

状态所有权：

- raw incremental decoder：Agent Turn 私有、随 tool call 销毁；
- draft Plan UI：Renderer 仅展示投影，随当前 Turn/draft tool call 生命周期存在；
- 正式 PlanState：RunState/Agent Loop 唯一所有者；
- Session replay：只投影 durable 完整计划，不恢复未完成 draft/review waiter。

### 11.3 Application `ContextStatus`

在现有 `ApplicationStatus` 中提供稳定、安全、非 diagnostics 的 Context 投影。最终至少表达：

```text
ContextStatus
├─ used_tokens: int
├─ budget_tokens: int
├─ available: bool
├─ measurement: estimate | exact | unavailable
└─ source: stable short enum/string
```

要求：

- `budget_tokens` 是**当前有效输入预算**，由 Application 根据现有 ContextBudget 决定；
- 有最近已解析 Provider ceiling 时必须包含其收紧结果；
- 尚无 Provider runtime ceiling 时按现有配置/default 规则形成安全投影；
- 默认 256K 只在不存在更具体有效窗口时生效；
- exact 只在 Provider 确实给出对应请求 usage 时成立；
- Transcript/Timeline/Tool/Compact 后若 exact 已不再描述当前请求边界，应回到 estimate，而不是延用过期 exact；
- Renderer 不再读取 config 重新算 denominator。

### 11.4 Application `CompactionStatus`

不创建 Desktop FSM。Application 的已有 compaction 执行链增加/整理一个用户安全生命周期投影：

```text
CompactionStatus
├─ state: idle | running | completed | no_change | failed | cancelled
├─ trigger: manual | auto | overflow | null
└─ changed: bool | null
```

仅表示当前 Application 生命周期事实；不跨进程恢复。

### 11.5 Session move

当前 open idle Session 的 move 生命周期：

```text
active ApplicationSession writer held
        ↓
validate target canonical project
        ↓
_prepare_close() / instruction-state sync
        ↓
writer.update_project_key(target)
        ↓ success
release writer + Application active_session=None
        ↓
SessionMutation
```

如果 update 前/中失败：

```text
旧 writer / source membership 保持有效
→ 不返回成功
→ Renderer 不做 optimistic move
```

### 11.6 Renderer UI-only ephemeral state

允许存在：

- command menu active index/open state；
- AskUser 当前题 index、未提交草稿；
- Settings 编辑 draft、API Key 按需 reveal 明文缓存与 replacement draft（两者必须分离）；
- context menu anchor；
- tool elapsed timer start/end；
- Todo hover/focus expand；
- panel/modal/select animation state。

禁止把这些提升为 Core/Application 第二事实。

---

## 12. 依赖与数据流

### 12.1 AskUser

```text
Provider
  ↓ UthCode ProviderEvent
Agent Core
  ↓ UserInputRequested / PauseRequest
Application Run
  ↓ AgentEvent
DesktopBridge
  ↓ JSON-safe event
Renderer
  ↓ UserInputResponse JSON
DesktopBridge
  ↓ Application typed response
Core PauseRequest.validate_response
```

错误：自由文本合法性最终在 Core；Renderer 只做非空、步骤完整等 UX 校验。

### 12.2 Plan

```text
Provider Integration
  ↓ ToolCallArgumentsDelta（UthCode-owned ProviderEvent）
AgentLoop
  ↓ private incremental plan decoder
PlanContentDelta
  ↓
Application AgentEvent stream
  ↓
DesktopBridge envelope
  ↓
Renderer plan timeline block

ToolCallCompleted
  ↓ parse_propose_plan_arguments
PlanState update
  ↓ PlanProposed
Plan Review pause
```

SDK 类型截止在 Integration；raw tool arguments 截止在 Agent Core。

### 12.3 Context / Compact

```text
Model config + Provider limits + Context Compiler + Transcript/Timeline
        ↓
ContextBudget / ContextStatus
        ↓
UthCodeApplication.status()
        ↓
DesktopBridge.status.get
        ↓
Renderer
```

Manual/Auto/Overflow compact 全部更新同一 Application `CompactionStatus`。Renderer 只能通过现有命令/API 发起并读回状态。

### 12.4 Session

```text
Sidebar action
  ↓ session.move
DesktopBridge
  ↓ target path validation
ApplicationSessionService
  ↓ SessionFileStore writer
SessionMutation
  ↓
Renderer catalog reconciliation
```

Session 文件和 writer lock 不跨 Application 边界。

---

## 13. 对现有能力的影响

| 现有能力 / 文件 | 当前状态 | 本次如何使用 | 是否修改 | 原因 | 回归测试 |
| --- | --- | --- | --- | --- | --- |
| Provider unified stream | 已稳定 | 复用 ToolCallArgumentsDelta | 保持协议，Core 消费方式修改 | Plan streaming 已有原始增量 | provider + agent tests |
| `ProposePlan` final parser | 已稳定 | 保持最终合法性权威 | 小改/复用 | draft 不能替代 final | planning/agent tests |
| `PlanProposed` | 已稳定 | 继续作为正式 Review 边界 | 保持语义 | 用户拍板 2A 不改变 final authority | agent/t08 tests |
| AskUser `allow_other` | 当前公共字段 | 被新冻结语义替代 | 删除 | 所有 select 永远允许自由文本，旧 flag 成为死语义 | interaction/tui/desktop |
| `UserInputRequest` 最多 4 题 | 已稳定 | 直接复用 | 保持 | F02 未要求改变问题数 | interaction |
| Context Compiler/Budget/Gates | 已稳定 | 作为唯一 Context authority | 只补安全投影，不重写算法 | 修 Renderer 越界，不另建算法 | context/application/eval |
| Persistent Runtime Recovery | 明确欠账 | 不触发 | 保持不动 | durable Session context 重建不等于 active Turn 恢复 | session/F01 regressions |
| Application Session storage | 已稳定 | 继续唯一 move authority | 修改 active-idle move 边界 | 当前 selected Session move 真实失败 | session authority |
| Slash registry/dispatcher | 已稳定 | 继续唯一命令目录/执行器 | Application 保持 | GUI 只隐藏/映射入口 | command + desktop |
| Permission | 已稳定 | GUI 继续投影 | 保持 | F02 不重设权限语义 | permission regressions |
| TodoWrite / TaskStateChanged | 已稳定 | Todo UI replace-all | Core 保持 | 只修展示 | T08 + renderer |
| Config Secret / API Key | 普通配置投影已脱敏 | 保持安全写入，并新增用户显式 reveal 当前已保存 Key 的窄路径 | `ProviderProfile`/`ModelProfile` 保持；Application/Integration 配置读取与 Desktop bridge 最小扩展 | 满足 Settings 始终可通过 eye 查看已配置 Key，同时不把明文塞进普通状态投影 | config + bridge + renderer |
| TUI | 默认旧 Interface | 适配 AskUser 公共协议变化 | 最小修改 | Core contract 改变后必须保持可替换 Interface | test_tui |
| T10 冻结工作包 | 已完成/冻结 | 只作事实来源 | 保持不动 | F02 独立修复包 | negative scan |

---

## 14. 第三方依赖

**无新增第三方依赖。**

- 不引入 React Router；Settings 分类页使用当前应用内轻量 view/section state即可。
- 不引入新的 state manager；继续使用 React state/reducer。
- 不引入 animation library；使用现有 CSS transition / `prefers-reduced-motion`。
- 不引入 JSON streaming 库；`ProposePlan` 只有当前单一 `plan:string` schema，使用私有、目的明确的增量解码即可。

---

## 15. 实施任务拆分

### Task 1 — AskUser Core 合同硬切

**任务目标**

把所有 select 问题统一改成“2~3 个 option + 永远允许自由文本”，删除 `allow_other`。

**前置条件**

固定基线和用户拍板 1B。

**涉及文件**

```text
src/uthcode/core/interaction.py
src/uthcode/core/__init__.py（如导出受影响）
src/uthcode/interfaces/tui/interaction.py
tests/test_agent_interaction.py
tests/test_tui.py
desktop/src/renderer/InteractionSurface.tsx
desktop/tests/renderer.test.tsx
```

**实现要求**

- `UserQuestion` 删除 `allow_other` 字段；
- select `options` 验证改为 `2 <= len <= 3`；
- `ASK_USER_TOOL_DEFINITION` 同步删除 `allow_other`，`maxItems=3`；
- JSON `to_dict/from_dict` 只接受新硬切合同，不保留旧字段兼容读取；
- `validate_answers()` 不再做“必须命中 option label”的 membership gate；
- SINGLE_SELECT 仍必须恰好 1 个非空答案；MULTI_SELECT 仍至少 1 个；
- Desktop/TUI 每个 select 均提供“自行输入”；
- 删除 active source/test 中依赖 `allow_other` 的条件分支和 fixture。

**完成结果**

Core、TUI、Desktop 对自由输入语义一致。

**测试**

结构化 option、自由文本、multi、重复/空/缺失 question id、4 questions 上限、旧 `allow_other` payload 被拒绝。

**明确不做**

不做 pending AskUser 跨进程恢复；不改变最多 4 questions。

**提交边界**

AskUser Core contract + 两个 Interface 适配 + tests 独立提交。

---

### Task 2 — Plan 真流式公共事件

**任务目标**

从现有 Provider tool argument stream 生成 display-safe `PlanContentDelta`，保持 `PlanProposed` 最终权威。

**涉及文件**

```text
src/uthcode/core/planning.py
src/uthcode/core/agent_events.py
src/uthcode/core/agent.py
src/uthcode/core/__init__.py
src/uthcode/application/__init__.py
tests/test_planning.py
tests/test_agent_events.py
tests/test_agent_loop.py
```

**实现要求**

- 新增 `PlanContentDelta(run_id, turn_id, iteration, tool_call_id, text)`；
- 加入 AgentEvent JSON serialize/deserialize 和 TypeAlias/export；
- 私有 decoder 仅绑定 `ProposePlan` 当前 schema；
- 支持任意 chunk 切分、JSON string escape、反斜杠、引号和 unicode escape；
- 每次仅 emit 新增的**已解码自然语言字符**；不得重复旧 prefix；
- 不向 public event 暴露 `arguments_delta`；
- ToolCallCompleted 时仍调用现有完整 `parse_propose_plan_arguments()`；
- final 合法后才写 PlanState / emit `PlanProposed`；
- malformed/cancelled 不制造 formal plan。

**测试**

- 单 chunk、多 chunk、1-char chunk；
- key/value 边界拆分；
- `\n`、`\"`、`\\`、unicode；
- 非 ProposePlan tool 无 PlanContentDelta；
- malformed final；
- cancelled Turn；
- delta→proposed 顺序。

**明确不做**

不建设通用 Tool arguments streaming API；不持久未完成 draft。

**提交边界**

Core Plan streaming 协议和测试独立提交。

---

### Task 3 — Application Context / Compact 安全投影

**任务目标**

让 Desktop 获得足够的 Context/Compaction 产品事实，从而删除 Renderer 自行算窗口和解析 diagnostics 的行为。

**涉及文件**

```text
src/uthcode/application/context.py
src/uthcode/application/generation.py
src/uthcode/application/__init__.py
tests/test_application_runs.py
tests/test_w05_diagnostics.py
```

**实现要求**

- 在 Application public status 增加/收敛 `ContextStatus`；
- budget 来自现有 `ContextBudget`/model config/provider ceiling/default 规则；
- durable Session resume 后调用既有 `_refresh_context_for_session()` 重建 estimate；
- status 明确 `estimate/exact/unavailable`，不伪造 provider exact usage；
- Provider exact usage 与当前 request boundary 失配后不得继续标 exact；
- manual/auto/overflow 使用同一 `CompactionStatus`；
- compaction 状态至少覆盖 running/completed/no_change/failed/cancelled；
- public status 不要求 GUI 读取 `diagnostics` 才能判断产品状态；
- 不改变 T09-3 的 Gate、Low Water、Hard Gate 算法，若测试证明实际链路有早溢出/auto gate bug，只修既有 Application/Core Context 链中的真实缺陷。

**测试**

- default 256K；
- model config 1M；
- Provider ceiling 收紧；
- cold resume estimate；
- terminal exact；
- transcript/tool/compact 后 exact→estimate；
- manual/auto/overflow compaction lifecycle；
- Hard Gate/Low Water 回归。

**明确不做**

不新增 background context agent；不新增 persistent runtime state。

**提交边界**

Application safe status 和 Context tests 独立提交。

---

### Task 4 — Session move 与 Plan replay

**任务目标**

修复当前打开但无 active Turn 的 Session 无法移动，并让 durable 完整 Plan 在 Desktop resume 后保持 plan 视觉身份。

**涉及文件**

```text
src/uthcode/application/sessions.py
src/uthcode/interfaces/desktop/bridge.py
tests/test_session_authority.py
tests/test_desktop_bridge.py
```

**实现要求**

- `ApplicationSessionService.move_session()` 支持 active idle Session；
- 在已有 writer lock 下同步 instruction state、更新 project_key、成功后 release；
- 更新失败时保持旧 writer/source ownership；
- active Turn 仍由 DesktopBridge gate 拒绝，不隐式 cancel；
- `storage` 映射成稳定 Desktop 错误，不把异常文本透出；
- `SessionReplayRecord` 允许 `kind="plan"`；
- `_project_replay` 只从 durable 完整 `ProposePlan` ToolCallPart 提取 `plan` 文本，不能把 raw tool arguments 作为 replay body；
- pending/unfinished plan draft 不进入 replay；
- bridge `_replay_values` 放行 `plan` safe record。

**测试**

- inactive move；
- current open idle move；
- active Turn reject；
- target invalid；
- busy/corrupt/storage；
- move failure transactional；
- plan replay；
- 普通 tool replay 不变。

**提交边界**

Session authority 与 bridge adapter 独立提交。

---

### Task 5 — Desktop 命令、Context 与 Session 投影收口

**任务目标**

把 Renderer 重新变成纯 Application projection，打通 F02 command/context/session 工作流。

**涉及文件**

```text
desktop/src/renderer/App.tsx
desktop/src/renderer/state.ts
desktop/src/renderer/Composer.tsx
desktop/src/renderer/RuntimePanel.tsx
desktop/src/renderer/Sidebar.tsx
desktop/tests/renderer.test.tsx
```

**实现要求**

- 删除 `DEFAULT_CONTEXT_WINDOW` 作为 Renderer authority；
- 删除 `configuredContextWindow()` 和“忽略 Application budget”逻辑；
- `status_loaded` 只消费 Application ContextStatus/CompactionStatus；
- agent event 中对 Context 有意义的边界触发适度 `status.get` refresh，禁止每字符 delta 发一次 RPC；
- `/clear` `/quit` `/resume` `/permission` `/help` 仅从 Desktop candidate menu 过滤，不改 registry；
- `/compact` `/new` `/plan` `/do` 选中后直接调用 command/application action；
- `/model` 和 Composer model picker 使用同一 Application completion/catalog；
- `/status` 渲染用户安全字段，不把 `diagnostics` dump 到 timeline；
- Plan/Default 模式指示器来自 Run/Application projection；
- manual compact 期间禁普通 send，结束自动恢复；
- compact activity 只展示 Application CompactionStatus；
- Session move 成功后按 authoritative result 更新两侧 catalog；当前 source selected session 被移走时清空选择/timeline，不自动建立第二 runtime；
- Session refresh/resume/rename 保持旧 row 顺序；`session.new` 放 regular 顶部；仅新 durable 消息/显式 pin 允许其他重排；
- >5 regular Sessions 折叠，selected 第 6+ 项必须仍可见但不篡改 top5。

**测试**

命令过滤/直接执行/model/status/context/session ordering/move/compact。

**提交边界**

Desktop application projection 收口独立提交。

---

### Task 6 — Chat、Tool、Todo、AskUser、Plan 交互完成

**任务目标**

完成核心聊天页交互，保证同一权威事实只更新同一个 UI block。

**涉及文件**

```text
desktop/src/renderer/ChatTimeline.tsx
desktop/src/renderer/InteractionSurface.tsx
desktop/src/renderer/Composer.tsx
desktop/src/renderer/CustomSelect.tsx
desktop/src/renderer/state.ts
desktop/src/renderer/app.css
locales/*
desktop/tests/renderer.test.tsx
```

**实现要求**

- Slash menu ArrowUp/Down 后 active item `scrollIntoView({block:"nearest"})`；
- Home/End/Enter/Tab/Escape 与 IME composing 正确；
- select 默认向上，空间不足可翻转，不能盖住 active input；
- Composer 底栏删除分隔线、hint、plus/mic；permission/model idle 无边框，hover/active 短动画；send 与 permission/model/context ring 底部对齐；
- Runtime panel 控件使用真实 icon + tooltip + aria；
- ToolStarted 建立一条 running row，ToolFinished 原地更新同一 row；
- elapsed timer 为 UI ephemeral，running 时持续更新，结束冻结；
- tool 左线 running=yellow/success=green/failure=red，同时必须有 icon/text/ARIA 非颜色提示；
- TaskStateChanged replace-all；Todo 浮在 composer 上方，默认 compact，hover/focus expand；
- Todo 状态不显示冗长文本 label，但 tooltip/aria 完整；
- PlanContentDelta 首次创建 draft block，后续 append；PlanProposed 对同一 draft 封口而不是再插一块；
- matching tool/turn fail/cancel 能结束 draft running；
- Plan review 状态与 timeline plan block 分离，review 不覆盖 composer/timeline；
- AskUser 1~4 题 prev/next 保留答案；select 永远有“自行输入”；最终 review 后一次提交；
- 移除无效“返回聊天”；保留 typed cancel；
- AskUser/Plan 面板焦点、滚动、窄屏不横向裁切。

**测试**

DOM identity、keyboard/IME、focus、elapsed、Todo replace-all、AskUser multi-step、Plan stream/review/cancel。

**提交边界**

聊天交互 UI 独立提交。

---

### Task 7 — Settings 语义、API Key reveal 与页面结构修复

**任务目标**

让 Settings 只展示用户概念，不暴露内部 model_ref；已保存 API Key 在任何时候都可通过 eye 按钮显式 reveal/hide，并按 F02 分类页/编辑 modal 行为完成。

**涉及文件**

```text
src/uthcode/integrations/config/loader.py
src/uthcode/application/bootstrap.py
src/uthcode/application/__init__.py
src/uthcode/interfaces/desktop/bridge.py
desktop/src/desktop-api.ts
desktop/src/renderer/App.tsx
desktop/src/renderer/SettingsView.tsx
desktop/src/renderer/app.css
desktop/src/renderer/locales/zh-CN.ts
desktop/src/renderer/locales/en.ts
tests/test_configuration.py
tests/test_desktop_bridge.py
desktop/tests/preload.test.ts
desktop/tests/renderer.test.tsx
```

**实现要求**

- Settings 复用全局左侧区域和同一 sidebar width；
- 分类导航切成独立 section/page，不把所有配置堆成一张长页；
- 使用轻量 group background，不堆 dashboard card；
- Provider 每行进入 modal；
- 增加专用 `settings.reveal_api_key` Desktop request：只接收 `provider_profile_id`，通过 Application → Integration 读取该用户配置中当前保存的 `api_key` 表示；普通 `settings.get` 不得因此携带明文；
- 已保存 Key 的 eye 点击后才发 reveal；重复 show/hide 可复用当前 modal 生命周期内的临时 revealed cache；关闭/离开 Settings 后必须丢弃；
- `env:VARIABLE_NAME` 只显示该配置引用，不解析环境变量 secret；不得从 Provider runtime/`SecretValue` 反向读取；
- UI “提供商”字段改为“协议”；
- Base URL 下方紧接 API Key；Key 的 eye show/hide **始终存在**：对已保存 Provider，即使本轮没有编辑 Key，也可以显式 reveal 当前已配置值；
- 删除“清除 Key”“已配置”文案；未触碰 Key 时不得清空已有 secret；**点击 eye/reveal 本身不算触碰/修改**；
- 一个 Provider 支持多 Models；
- model 增删/配置按钮有 tooltip/aria；
- Model 字段从 Provider advanced 中移入 Model modal；
- `display_name` 是 chat 显示名，空时由 Application 现有 fallback 到 remote_id；
- `model_ref` 不再成为用户可编辑/可见字段；
- 新 model 内部 ref 使用不可见稳定唯一 key，不生成可见 `model`、`model-1`；
- 不修改 `ModelProfile` / `ProviderProfile` 公共配置语义；
- API Key 必须拆成 `revealed` 与 `replacement/touched` 两套局部状态：reveal 只负责显示当前值，只有用户实际编辑 Key 才形成 replacement；
- hide 不写入任何持久状态；关闭 Provider modal、离开 Settings、runtime rebootstrap 或组件卸载时清除已 reveal 的明文缓存；
- 保存失败保留真正的 replacement 编辑草稿；已 reveal 的旧 Key 不得因为保存流程被自动拼进 write request。

**测试**

空配置、新 Provider、多 Model、删除/默认 model、API Key 已配置时随时 reveal/hide、reveal 不触发 touched/writeback、literal 与 `env:VARIABLE_NAME` reveal、replacement、modal close/Settings leave 清理 reveal cache、modal keyboard/focus、zh/en。

**提交边界**

Settings 配置读取/专用 reveal/Renderer UI 作为一个闭环提交；不得把 secret reveal 扩成通用凭据系统。

---

### Task 8 — GUI 越界、冗余、不可达与过度抽象审查

**任务目标**

对 F02 直接相关 GUI 生产代码做一次工程收敛，并把发现落实为删除/合并/局部拆分，而不是只输出审查报告。

**强制审查范围**

```text
desktop/src/**
src/uthcode/interfaces/desktop/**
与 Desktop 新公共投影直接相关的 application/core 修改点
```

不扩成全仓瘦身。

**越界检查清单**

- Renderer 是否重新实现 Context budget/gate/compact 语义；
- Renderer 是否直接构造/修改 durable Session truth；
- Renderer 是否把 Slash string 伪装成用户消息；
- Renderer 是否维护第二套 Permission/BehaviorMode/Todo/Plan authority；
- DesktopBridge 是否绕过 Application 直接使用 Session files/Core mutable state；
- raw Provider payload/tool private body/internal diagnostics 是否穿过 Interface 边界；
- API Key/Secret 是否进入 preference/log/event/diagnostics，或除专用 `settings.reveal_api_key` response 外的普通 Desktop payload；
- GUI 是否新增反向依赖。

**冗余/不可达检查清单**

- `allow_other` 旧字段、branch、fixture；
- Renderer Context 256K/budget fallback 旧算法；
- visible `model_ref` rename 和 `model/model-1` placeholder 路径；
- Plan typewriter/整块重复插入逻辑；
- Tool started/finished 双行遗留路径；
- 已被 native GUI 入口替代但仍在 Renderer candidate 特判的重复分支；
- 无调用方 helper、旧 action、旧 locale key、旧 CSS class、失效测试 fixture；
- catch 后永不可达的 fallback、重复 normalize/project helper。

**提前/过度抽象检查清单**

删除或拒绝新增：

```text
DesktopManager
SessionManager / SessionStore（第二业务 store）
ContextManager / ContextEngine（Renderer 侧）
PlanManager / TodoManager
通用 EventBus
为未来插件准备的 Registry/Protocol
通用 JSON streaming framework
无第二当前调用方的 modal/menu framework
纯转发 facade / compatibility adapter
```

**God/巨型文件处理规则**

- 不以行数阈值机械拆分；
- `App.tsx`、`state.ts`、`SettingsView.tsx` 必须做职责审查；
- 如果 F02 修改后某段已形成“独立当前产品职责 + 独立真实调用方/测试边界”，允许抽成**私有局部模块**；
- 抽出后旧代码必须删除，不保留双入口；
- 不新增公共层级或未来扩展协议；
- 测试巨型文件允许按当前已有 feature suite 拆分，但不得复制 fixture truth。

**完成结果**

- 代码中不留本任务替代掉的第二链路；
- 无新增无调用方抽象；
- 所有保留的大文件均能说明剩余职责为何仍应共置。

**测试**

`npm run typecheck`、Desktop tests、Python architecture tests、全量 pytest；必要的源代码否定扫描。

**提交边界**

工程收敛单独提交，禁止混入新产品能力。

---

### Task 9 `[接入主流程]` — Desktop 生产链集成

**任务目标**

把 Task 1~8 通过唯一生产链连接起来。

**要求**

```text
Renderer
→ DesktopApi
→ Main/Preload transport（保持）
→ DesktopBridge
→ Application
→ Agent Core
```

验证：

- AskUser typed resume；
- PlanContentDelta → PlanProposed → PlanReview；
- context/compact status；
- session move；
- direct Slash；
- settings save/rebootstrap；
- Todo/Tool/BehaviorMode projection。

**明确不做**

不创建 Desktop 专用 Core facade；不改 T10 冻结文件。

**提交边界**

只做跨层接线和回归修复。

---

### Task 10 `[端到端验证]` — Desktop 人工与自动验收

**自动验证**

```text
pytest -q
cd desktop && npm run typecheck
cd desktop && npm test
```

需要使用项目现有 packaged/CDP acceptance 脚本验证的场景，继续走既有脚本，不创建第二套视觉测试 harness。

**真实 Desktop 人工矩阵**

- Windows packaged/Desktop dev shell；
- dark/light；
- zh-CN/en；
- wide/narrow window；
- keyboard-only / mouse；
- IME composing；
- 100%/125%/150% zoom；
- reduced motion；
- Session >5；
- AskUser 1题/4题；
- Plan stream/review/change/cancel；
- Tool success/fail/cancel；
- manual compact/no_change/fail；
- restart+resume durable Session context；
- settings API Key always-reveal / hide / untouched / replacement。

**通过条件**

无 dropdown flicker/overlap、无横向 crop、无 focus loss、无 duplicate timeline row、无乱码、无错误的 Session reorder。

---

### Task 11 `[遗留负担清理]` — 否定扫描、文档与全量回归

**任务目标**

删除被 F02 替代的遗留路径，同步当前事实文档。

**必须扫描**

```text
allow_other                  → active src/tests 中应为 0
DEFAULT_CONTEXT_WINDOW       → Renderer authority 路径应为 0
configuredContextWindow      → 应删除
renameModelRef               → 用户可见重命名路径应删除
"model-1" / visible model ref placeholder → UI 路径为 0
raw arguments_delta in Renderer → 0
T10 frozen files modified    → 0
```

**文档同步**

- `docs/Tools.md`：AskUser 新合同、Plan streaming 最终公共语义；
- `docs/Context-Index.md`：Desktop 仍为 Interface，Context status authority 在 Application；
- `docs/context/A02-Control/Control-Context.md`：AskUser/Plan pause/review 当前事实；
- `docs/context/A03-State/State-Context.md`：Context status、Session replay/Plan replay 当前事实；
- `docs/OutstandingDebtList.md`：本任务无新增欠账，且未触发 Persistent Runtime Recovery，后续任务包拆分阶段应保持相关条目不变。

**提交边界**

只允许删除/文档/测试收尾，不新增新能力。

---

## 16. 测试矩阵

| 产品行为 | 测试文件 | 关键断言 |
| --- | --- | --- |
| select 2..3 | `tests/test_agent_interaction.py` | 4th option 构造失败 |
| arbitrary answer always allowed | `tests/test_agent_interaction.py` | single/multi 非 option 文本合法 |
| old allow_other hard cut | `tests/test_agent_interaction.py` | 带旧字段 payload 拒绝 |
| TUI other input | `tests/test_tui.py` | 所有 select 有自由输入路径 |
| Plan delta JSON roundtrip | `tests/test_agent_events.py` | public event fields 完整，无 raw args |
| Plan chunk decode | `tests/test_planning.py` / `test_agent_loop.py` | arbitrary chunks/escapes/unicode |
| Plan delta only for ProposePlan | `tests/test_agent_loop.py` | other tool 不 emit |
| Plan final authority | `tests/test_agent_loop.py` | delta 后只有合法 complete 才 proposed |
| Plan cancel/fail | `tests/test_agent_loop.py` + renderer | draft terminal，无假 proposed |
| Context default 256K | Application/Context existing tests | 无更具体 limit 时 256K |
| 1M config | `tests/test_application_runs.py` | status budget 1M 或被 provider ceiling 收紧 |
| provider ceiling | `tests/test_application_runs.py` | effective budget 与 gate 同源 |
| cold Session resume | application/desktop tests | estimate restored，exact 不伪造 |
| Context mutation updates | application/renderer | tool/timeline/compact 后新 projection |
| compact lifecycle | application/renderer | running→terminal；manual/auto/overflow 同权威 |
| current idle Session move | `tests/test_session_authority.py` | success + active release + metadata target |
| move failure transaction | `tests/test_session_authority.py` | source/writer 保持 |
| Desktop move error mapping | `tests/test_desktop_bridge.py` | busy/storage/corrupt/invalid target safe |
| Plan replay | session/bridge/renderer tests | resume 后 kind=plan，不暴露 raw tool body |
| hidden Slash candidates | renderer | 五个 command 不显示但 backend 仍可用 |
| direct Slash | renderer | 不调用 `turn.start` 发送 slash text |
| `/model` catalog | renderer/bridge | completion 与 composer 同 source |
| `/status` safe | bridge/renderer | diagnostics/private payload 不显示 |
| Session ordering | renderer | resume/rename/refresh 不动；new/message/pin 才动 |
| Session >5 collapse | renderer | selected 6+ 可见且 top5 不乱 |
| Tool in-place | renderer | started/finished 只有一个 DOM row |
| Tool elapsed | renderer | running 增长、terminal 冻结 |
| Todo replace-all | renderer | TaskStateChanged 完整替换 |
| AskUser multi-step | renderer | prev/next answers 保留 + review |
| Settings internal ref hidden | renderer | DOM 无 model_ref / model-1 概念 |
| API Key reveal safety | config + bridge + renderer | 已保存 Key 可显式 eye reveal；普通 `settings.get` 不带明文；reveal 不标 touched、不自动回写；明文不进 preference/event/log/diagnostics |
| reduced motion | renderer/CDP | 动画禁用后功能/焦点不变 |
| architecture boundary | `tests/test_architecture_boundaries.py` | 无反向依赖/Interface→Core bypass |
| full regressions | `pytest -q`, `npm test` | TUI/CLI/Headless/Context/Permission 无回退 |

---

## 17. 删除与清理

本任务明确删除以下**被最终行为替代**的内容：

1. Core `UserQuestion.allow_other` 字段、JSON 字段、tool schema 字段及所有 active conditional branch；
2. Renderer 对 `allow_other` 的展示条件；
3. Renderer `DEFAULT_CONTEXT_WINDOW` 作为业务 authority 的路径；
4. Renderer `configuredContextWindow()` 及忽略 Application budget 的二次计算；
5. 用户可见 `model_ref` 编辑/rename 逻辑；
6. 用户可见 `model` / `model-1` placeholder 生成逻辑；
7. 如现有 Plan 使用最终整块文本再人为逐字播放的伪 streaming 路径，删除；
8. Tool started/finished 重复 timeline row 路径；
9. F02 修改触达范围内失去调用方的 helper/action/locale/CSS/test fixture；
10. 为被替代逻辑保留的兼容分支、双读/双写和 fallback。

不得借此删除与 F02 无关的历史模块。

---

## 18. GUI Code Review 必过项

编码代理完成实现后，必须按 severity 输出并处理代码审查发现；**P0/P1/P2 属于 F02 范围的 finding 未关闭则任务不通过。**

审查至少覆盖：

### Correctness

- stale closure / async race；
- Session/Project 切换后旧 RPC 回包污染新视图；
- Plan delta 与不同 tool_call_id 混流；
- duplicate/out-of-order AgentEvent；
- compact/turn active input gate；
- settings save/rebootstrap 失败回滚；
- menu/modal focus restoration。

### Architecture

- Renderer 第二 authority；
- Bridge 绕 Application；
- raw Provider/internal diagnostics leak；
- 当前真实调用方不足却新增公共抽象；
- 同一功能存在两条生产链。

### Maintainability

- 重复 normalize/project helper；
- 一个函数同时改变多个不相关业务域；
- 已无调用方 export；
- unreachable branch；
- 临时 workaround 变长期路径；
- 巨型文件中本任务新增职责是否可在当前真实边界内收敛。

### Security / Privacy

- API Key 明文只允许出现在用户显式触发的专用 reveal response 与当前 Renderer 临时内存；永不进入 preference/event/log/error/diagnostics/Session/Timeline；
- Session path/Provider exception/private tool result 不因新 status/replay 泄漏；
- Desktop error 继续使用 stable safe message。

---

## 19. 验收标准

F02 只有同时满足以下条件才完成：

1. Core select AskUser 只允许 2~3 个结构化 option，且所有 select 永远接受自然语言自由答案；active code 中不存在 `allow_other` 产品分支。
2. 正式 Plan 在 Provider 真正产生 `ProposePlan` 参数流时通过 `PlanContentDelta` 实时显示；Renderer 不解析 raw JSON、不做 final typewriter 伪流式。
3. `PlanProposed` 仍是正式 revision/Review 的唯一权威；失败/取消不产生伪正式 Plan。
4. Renderer 不再计算 Context 安全窗口；Context ring/RuntimePanel 使用 Application safe ContextStatus。
5. default 256K、1M config、Provider ceiling、Auto/Overflow/Low Water/Hard Gate 的显示和实际安全链一致。
6. durable Session restart/resume 后可重建 Context estimate；无法证明 exact 时明确不是 exact。
7. Manual/Auto/Overflow compact 共用 Application single-flight/lifecycle；Desktop 没有第二 compaction FSM。
8. 当前 open idle Session 可移动；active Turn 不可移动；失败事务不损坏 source Session。
9. Slash candidate/menu/direct action/model/status 行为全部按 F02 固定要求完成，Slash action 不进入模型 user message。
10. Session new/refresh/resume/rename/message/pin 的排序行为符合矩阵，>5 collapse 正确。
11. Settings 不再暴露 model_ref 和 `model/model-1` placeholder；已配置 API Key 无论是否处于编辑阶段都可通过 eye 显式 reveal/hide；普通配置读取仍不返回明文，reveal 不等于修改且不会自动写回。
12. Tool、Todo、AskUser、Plan 只更新各自同一个视觉实体，不产生重复 timeline。
13. dark/light、zh/en、wide/narrow、keyboard/mouse/IME/zoom/reduced-motion 人工验收通过。
14. GUI 越界检查无未处理边界突破；无 Renderer→Core/Integration 反向越界。
15. F02 触达范围的冗余、不可达代码、旧分支、无调用方抽象已删除；无新增未来 placeholder。
16. `npm run typecheck`、`npm test`、`pytest -q` 全部通过。
17. TUI、CLI、Headless、Permission、Session durability、Context Gate、Config security 回归通过。
18. T10 冻结工作包文件无修改。
19. 无新增第三方依赖，无旧 UthCode/MewCode runtime 依赖。
20. 当前实现可作为 F02 后下一任务的真实代码基线。

---

## 20. 编码停止条件

编码代理仅在以下情况停止并报告：

- 固定 Commit 的真实代码与本任务书关键假设发生实质不一致；
- 必须推翻用户本轮 1B / 2A 决定才能继续；
- 需要把 `PlanContentDelta` 扩成通用 Tool/Provider streaming 公共框架才能实现；
- 需要新增独立 Desktop Runtime、Event Bus、Session/Context Manager 等系统级层；
- 需要实现 Persistent Runtime Recovery 才能满足一个已列验收项；
- 必须修改 T10 冻结工作包正文才能成立；
- 实际 Session move 无法在 Application authority 内事务实现，必须改变 Session durable schema；
- 新 Context status 必须改变 T09-3 已冻结 Gate/Low Water/Hard Gate 产品语义，而不是修真实 bug；
- 必须新增长期兼容层处理 `allow_other` 旧 payload；
- API Key 需要扩大到本任务已明确的“专用按需 reveal”之外的新的秘密传播边界，或出现未计划的权限/文件系统安全边界变化；
- 文件范围明显扩展到 F02 之外的独立能力。

以下问题编码代理自行解决，不得停下等待用户：

- TypeScript/Python 类型错误；
- lint/format；
- 单元测试失败；
- fixture 调整；
- 私有函数命名/拆分；
- CSS 局部实现；
- 普通 async race 修复；
- 不改变产品语义的局部重构。

---

## 21. 明确不做 / Out of Scope

F02 不包含：

- Persistent Runtime checkpoint；
- active/paused Turn 跨进程恢复；
- pending AskUser/Permission/Plan Review waiter 跨进程恢复；
- Memory / Dream / Review Prompt；
- Skill / MCP / Plugin / Subagent / Multi-Agent；
- Worktree / Git 新能力；
- Voice / TTS / STT；
- 登录、云同步、远端设备；
- 新 Provider 协议；
- 新 Context 压缩算法或后台压缩 Agent；
- TUI/CLI 替换或删除；
- 全仓 God file/巨型文件瘦身；
- 与 F02 无关的 Core/Application 历史重构；
- 修改 T10 冻结任务书、spec、checklist、prompt、feedback；
- 为未来 Desktop 功能预制 Manager/Registry/EventBus/Protocol。

---

## 22. 实施顺序总览

```text
Task 1  AskUser Core 硬切
    ↓
Task 2  PlanContentDelta 真流式
    ↓
Task 3  Application Context/Compact 安全投影
    ↓
Task 4  Session move + Plan durable replay
    ↓
Task 5  Desktop command/context/session 投影收口
    ↓
Task 6  Chat/Tool/Todo/AskUser/Plan UI
    ↓
Task 7  Settings 修复
    ↓
Task 8  GUI 越界/冗余/提前抽象/Code Review
    ↓
Task 9  [接入主流程]
    ↓
Task 10 [端到端验证]
    ↓
Task 11 [遗留负担清理]
```

实施原则只有一条：

> **Core/Application 负责稳定产品语义和唯一事实，Desktop 只消费安全投影并提供交互；凡 F02 新实现替代的旧 GUI/Core 分支，在同一任务中删除，不留第二链路。**
