# UthCode F03：Context 冻结收口、工程复杂度收敛与 Desktop 体验优化任务书

## 1. 分析基线

### 1.1 仓库与 Commit

```text
仓库：D:\project\Re-UthCode
远端：https://github.com/undertaker33/Re-UthCode
分支：main
分析基线：cf50c50c25b6739037f52f56fc14b96e8fa2ad8b
```

本任务书只基于该 Commit 的真实源码、测试、current-context 与已冻结工作包结论生成；不得沿用更早 F03 草稿中的实现假设。

### 1.2 已读取的关键规则与资料

```text
AGENTS.md
docs/OutstandingDebtList.md
F03-Context冻结收口与工程瘦身及Desktop体验优化-探索与任务书生成提示词.md

docs/context/GUI/GUI-Context.md
docs/work/archive/T09-1-Context预算与Compact协议补齐/
docs/work/archive/T09-2-工程收敛与提前抽象清理/
docs/work/archive/T09-3-256KContext工程调优与通用失败语义/
docs/work/F02-DesktopGUI交互与上下文缺陷修复/
```

### 1.3 关键源码

```text
src/uthcode/core/context.py
src/uthcode/core/compaction.py
src/uthcode/core/history.py
src/uthcode/core/agent.py
src/uthcode/core/agent_events.py

src/uthcode/application/context.py
src/uthcode/application/generation.py
src/uthcode/application/runs.py
src/uthcode/application/provider_usage.py
src/uthcode/application/history.py
src/uthcode/application/sessions.py

src/uthcode/integrations/session_files.py
src/uthcode/integrations/providers/*

desktop/src/desktop-api.ts
desktop/src/desktop-preferences.ts
desktop/src/main.ts
desktop/src/preload.ts
desktop/src/renderer/App.tsx
desktop/src/renderer/state.ts
desktop/src/renderer/SettingsView.tsx
desktop/src/renderer/ChatTimeline.tsx
desktop/src/renderer/Composer.tsx
desktop/src/renderer/Sidebar.tsx
desktop/src/renderer/RuntimePanel.tsx
desktop/src/renderer/app.css
```

### 1.4 关键测试

```text
tests/test_context_compaction.py
tests/test_context_compiler.py
tests/test_t09_1_context_protocol_e2e.py
tests/test_w05_diagnostics.py
tests/test_agent_loop.py
tests/test_application_runs.py
tests/test_application_runtime.py
tests/test_history_contract.py
tests/test_session_authority.py

desktop/tests/renderer.test.tsx
desktop/tests/preload.test.ts
desktop/tests/runtime-process.test.ts
desktop/tests/cdp-isolation.test.ts
desktop/tests/settings-acceptance-isolation.test.ts
desktop/tests/*visual-fixture*
```

### 1.5 外部参考

本轮未使用外部 Agent 实现作为最终设计依据。F03 的核心问题均可由当前仓库真实调用链和已经冻结的 Provider/Context 语义确定，不为工程收敛额外引入竞品架构。

---

## 2. 当前实现基线

### 2.1 Context / Compaction

当前真实链路为：

```text
Transcript + Timeline + Prompt/Runtime/Tool sources
        ↓
ApplicationContextService.compile()/compose_generation_request()
        ↓
ContextCompiler
        ↓
ordinary GenerationRequest
        ↓
Provider count / local request accounting
        ↓
Auto/Hard Gate
        ↓
Provider
```

L4 Compact 当前已经具备：

```text
complete SemanticUnit
→ ContextCompactor.plan_epoch()
→ tool-free Provider summary request
→ parse_epoch_result()
→ build_epoch_candidate()
→ Application durable Timeline commit
→ optional should_continue()
```

但当前仍有以下已验证缺口：

1. `ApplicationContextService._non_reducing_result()` 仍使用 `candidate.output_tokens < candidate.input_tokens` 判断是否“压缩有效”，没有验证下一次 ordinary Working Context 是否真实变小。
2. `ContextCompactor.plan_epoch()` 遇到 oldest complete Turn 本身超过单次 compaction available input 时直接返回 `None`，导致后续历史无法推进。
3. `parse_compaction_result()` 对普通纯文本和只有 top-level `summary` 的响应仍可为多 Turn 自动复制同一摘要。
4. `ContextStatus` 仍可能在 compiler estimate 与上一轮 Provider usage exact 之间切换；`record_exact_usage()` 会把当前 ContextRing 的语义改写成上一请求的 usage。
5. manual `compact_session()` 当前明确传入 `max_epochs=1`，没有按 retained target 在一次 bounded invocation 中继续追赶。
6. Provider cache read/write 安全 diagnostics 已存在；当前缺口不是“已证明严重 cache miss”，而是 Conversation projection 本轮是否发生 rewrite 的最小观测。

### 2.2 Desktop Renderer

Desktop 仍保持：

```text
Renderer
  ↓ JSON-only Desktop API
preload/main/python runtime
  ↓
Desktop Bridge
  ↓
Application/Core
```

Renderer 不拥有 Agent 核心状态，这是必须保持的冻结边界。

当前复杂度集中点：

- `App.tsx` 约 74 KB，同时承担 runtime operation ownership、generation stale guard、Session 导航/变更、AgentEvent 路由、terminal convergence、settings rebootstrap 与页面 wiring。
- `state.ts` 同时承担 RendererState、DTO normalize、mojibake recovery、Session runtime snapshot、replay/hydration、事件/命令 reducer。
- `SettingsView.tsx` 同时维护 Provider/Model 双层 nested modal、两套 focus/snapshot 生命周期以及 API Key reveal/replace 状态。
- `ChatTimeline.tsx` 同时承担 Timeline UI 与手写安全 Markdown parser/render helper。
- `desktop/tests/renderer.test.tsx` 已达到约 300 KB，多个独立 UI contract 集中在一个测试文件。

已经存在且本轮只做回归、不重新实施的能力包括：

```text
ContextRing warning / critical
用户主动上滚时不被 streaming 强制拉回
Sidebar 普通 Session > 5 条的 show-more
窄屏 Runtime overlay 的 Escape / outside-click / focus restore
prefers-reduced-motion
Settings API Key 窄授权 reveal
zh-CN / en 与 dark / light / system
```

### 2.3 非 Desktop/TUI 工程结构

当前 `src/uthcode/` 中存在多个大文件，但不能按 LOC 机械拆分。

本轮确认的高价值收敛方向：

- `core/context.py` 仍放置 `CompactionPolicy`、`CompactionResult`、`ContextCompactor` 等 compaction 执行主体，而结构化 compaction 协议已经位于 `core/compaction.py`；这是一个真实的同域职责分裂。
- `ContextCompactor.compact()` 的旧同步 rolling-compaction 主路径已无生产调用方；生产路径使用 `ApplicationContextService.compact_async()`，旧同步入口主要剩历史单测。
- `application/generation.py` 同时包含普通 Provider request preparation、Compact Provider request、Application 状态/Session/Run orchestration 与持久化处理，可把已经形成独立纯职责的 request/compaction helper 移出，但 `UthCodeApplication` 仍保持唯一 Application authority。
- `application/history.py` 当前只有一个参数原样转发 wrapper，可直接由真实调用方使用 `core.history.transcript_entries_from_message()`，无需维持平行 Application facade。

明确 KEEP：

```text
core/agent.py
application/sessions.py
integrations/session_files.py
Provider Port / provider factory / concrete provider adapters
```

原因：这些文件虽然大或存在单实现 seam，但分别承担 RunState 单写者、Session writer ownership/crash consistency、持久化恢复、第三方 SDK 隔离等真实架构边界；F03 不为“文件更小”拆散 authority。

---

## 3. 问题定义

F03 解决四个已经进入同一维护阶段的问题：

```text
Context 已具备生产 Compaction
但冻结前仍存在有效性、oversized Turn、usage 口径、manual compact 的机制缺口

Desktop 已具备完整业务链路
但 Renderer 生命周期、状态 normalize、Settings 与测试文件出现明显职责聚集

Desktop 基础交互已经可用
但固定面板宽度、缺少 Focus Mode、代码块复制等高频体验仍不完整

非 Desktop/TUI 主干经过多轮增量开发
仍保留少量无生产调用方旧路径、转发 wrapper 与已经形成真实职责边界的 God-file 混合
```

F03 的目标不是重新设计 UthCode，而是在当前架构上完成一次 **correctness freeze + authority-preserving convergence**。

---

## 4. 已冻结用户决定

以下决定直接进入实施，不再讨论候选方案。

### 4.1 Context 1A：按真实 ordinary Working Context 判断 Compact 有效

```text
before = Compact 前下一次普通 Provider request 的 Working Context
candidate = 尚未持久提交的 Timeline candidate
after  = 用 candidate 重新构建的下一次普通 Provider request

成功：after < before
```

计量来源必须一致：

```text
Provider count_input_tokens 可用
→ exact before vs exact after

Provider count 不可用
→ local final-request accounting before vs after
```

不得继续用 Fine Summary 自身 token 长度作为成功标准。

### 4.2 Context 2A：Oversized Turn 仍保持 one-Turn-one-Fine

允许 process-local bounded subpass/chunk，但所有子段完成前不得产生 durable Fine；最终只提交一个覆盖完整 Turn 的 `SemanticEntry`。

### 4.3 Context 3A：Current Working Context 与 Last Provider Request Usage 分离

```text
Current Working Context
→ 当前 ordinary request 的 compiler/local projection

Last Provider Request Usage
→ 最近一次实际完成的 Provider request usage
```

Core 的 `UsageUpdated` 继续保持 Run 累计 usage 语义，不改为 request usage。

### 4.4 Context 4A：manual `/compact` 在一次 bounded invocation 内继续追赶 retained_target

复用当前 retained target 与现有 bounded epoch limit，不重新调 208K/96K 等参数，不新增百分比压缩阈值。

### 4.5 Desktop 1A：可拖拽左右面板 + Focus Mode

- Sidebar 与 Runtime docked width 作为 Desktop UI preference 持久化；
- Renderer 提供明确 min/max；
- resize/zoom/narrow viewport 下保持安全；
- Focus Mode 是 Renderer 瞬时状态，不持久化，不进入 Application/Core；
- 退出 Focus Mode 恢复用户原布局。

### 4.6 Desktop 2A：Settings 改为单 Modal 分步编辑

Provider → Model 不再打开第二层 nested modal；共享一个 modal root、focus trap、return-focus owner 与 editor transaction。

### 4.7 Desktop 3A：Code Fence 只做 Language Label + Copy

本轮：

```text
语言标签
复制原始代码
```

明确不做：

```text
自动折叠
代码预览 Surface
文件预览
新 Markdown framework
```

当前 Markdown 渲染覆盖面保持不变：现有 User / Steering / Reasoning / Assistant / Plan / Status 等路径继续按当前 `ChatTimeline` 规则渲染；Tool 继续使用专用展示。

---

## 5. 任务目标

### 5.1 最终交付

F03 完成后必须形成：

1. Context Compaction 的真实 Working Context 有效性判定；
2. oversized complete Turn 不再永久阻塞 L4；
3. multi-turn summary 严格结构校验；
4. Current Working Context 与 Last Provider Request Usage 的稳定双投影；
5. manual `/compact` 可在单次 bounded invocation 内多 epoch 追赶 retained target；
6. Conversation projection rewrite 的最小 telemetry；
7. Desktop Renderer state/App/Settings/Markdown/测试按真实职责收敛，但保持唯一 Renderer authority；
8. 可拖拽左右面板、Focus Mode、Code Fence language/copy、回到底部提示等高频 UX；
9. RuntimePanel 清楚展示 Current Working Context 与 Last Provider Request Usage；
10. 删除无生产调用方的旧同步 compaction path 与无语义转发 wrapper；
11. 收敛 `core/context.py` / `core/compaction.py` 与 `application/generation.py` 的真实职责边界；
12. 全量测试、Desktop CDP/visual/packaged acceptance 与 Context measurement 证据通过。

### 5.2 最小完整链路

```text
ordinary request
    ↓
Context Compiler + Gate
    ↓
Working Context pressure
    ↓
L4 compaction candidate
    ↓
prospective ordinary request rebuild
    ↓
exact/local before-after comparison
    ├─ after >= before → reject, no durable commit
    └─ after < before  → commit Timeline
                            ↓
                      rebuild/recount
                            ↓
        manual: until retained_target / bounded stop
        auto:   existing pressure-driven continuation
```

Desktop：

```text
Application status / AgentEvent
          ↓
Desktop Bridge safe DTO
          ↓
Renderer single state authority
    ├─ App lifecycle coordinator
    ├─ Settings single editor modal
    ├─ Chat safe Markdown
    └─ Layout preferences + transient Focus Mode
```

---

## 6. 设计骨架

### 6.1 Context Core

完成后 Core 结构应收敛为：

```text
core/context.py
  ├─ Context budget / accounting / gate
  ├─ Context Compiler / source selection
  └─ Working Context projection primitives

core/compaction.py
  ├─ CompactionPolicy / CompactionResult
  ├─ CompactionEpoch / structured result contracts
  ├─ ContextCompactor bounded planning
  ├─ oversized Turn process-local subpass
  ├─ L4 strict parsing
  └─ L5 aging contracts
```

不得保留两套 compaction 主执行路径。

### 6.2 Compact candidate 有效性

`ContextCompactor` 只负责产生 provider-independent candidate；**真实 ordinary request 是否缩小由 Application 判断**，因为只有 Application 掌握：

```text
Provider count capability
最终普通 request compose
L1/L2 request projection
当前 model/output reserve
```

候选验证必须发生在 durable Timeline append 之前。

建议内部链路：

```text
ApplicationContextService.compact_async()
    ↓ candidate
Application supplied validate_candidate(candidate_timeline)
    ↓
compose prospective ordinary request
    ↓
count with same source as baseline
    ↓
reduced ? commit : reject
```

该 callback 是 Application 内部协作，不新增公共 Agent 协议。

### 6.3 Oversized Turn

```text
one complete SemanticUnit > available compaction input
        ↓
按当前 raw Turn 的安全 part/text 边界生成 process-local chunks
        ↓
每个 chunk 使用同一 tool-free/hard-gated compaction Provider path
        ↓
得到 bounded intermediate summaries
        ↓
若中间结果仍超预算，继续 bounded fold
        ↓
最终得到一个 Turn summary
        ↓
SemanticEntry(turn_id = original Turn, refs = full Turn ref)
```

约束：

- chunk/subpass 不写 Timeline；
- chunk 不获得 durable ID；
- 任一 subpass 失败/取消/结构无效 → 整 Turn 不提交；
- L5/HistoryRead 仍只认识完整 Turn Fine；
- 不实现长期 Summary Graph。

### 6.4 Context status 双投影

新增 Application-owned、display-safe 的最近请求 usage 投影；现有 `ContextStatus` 只保留 Current Working Context 语义。

建议：

```text
ApplicationContextService.context_status
    = current Working Context estimate/current live delta

UthCodeApplication.last_provider_request_usage
    = derived from consecutive cumulative UsageUpdated boundaries
```

`UsageUpdated` 不改协议。Application Run driver 对同一 Turn 保存上一累计 `Usage`，对下一 `UsageUpdated` 做非负 delta，得到最近 request 的 input/output/cache counters；Turn 切换时以零基线重新开始。

若某 Provider 字段无法可靠区分“0”与“未提供”，保持 `not_available`，不得伪造 exact cache measurement。

### 6.5 Prefix Cache telemetry

只新增最小观测：

```text
conversation_projection_fingerprint / changed
```

该值基于本轮最终 ordinary request 的 Conversation Plane 投影产生，不持久化、不参与业务决策、不变成 sticky reduction state。

现有 `provider_usage.cache_read/cache_write` diagnostics 继续作为 Provider 侧证据。

### 6.6 Renderer authority

```text
state.ts
  = RendererState + reducer 唯一写入口

state-normalization.ts
  = DTO/replay/unsafe JSON → typed projection 的纯函数

state-session.ts
  = per-session runtime snapshot / catalog order 等纯函数

text-normalization.ts
  = mojibake/string recovery
```

这些文件不得各自拥有 store/reducer。

### 6.7 App lifecycle

把已形成独立生命周期的 runtime operation owner/generation/tail 与 terminal convergence 移入一个当前真实调用方使用的 hook，例如：

```text
useRuntimeLifecycle.ts
```

该 hook **接管原 App refs**，不是复制 refs。App 只消费其 API 完成 navigation/rebootstrap/terminal convergence wiring。

AgentEvent 最终仍 dispatch 到同一 Renderer reducer。

### 6.8 Settings 单 Modal

```text
SettingsView
    ↓ open provider editor
SettingsEditorModal
  state: provider | model
    ├─ Provider form
    └─ Model form
```

仅一个 modal root/focus trap/background inert/return focus owner。

API Key：

```text
普通态不持有明文
→ 用户显式 reveal 才走现有窄 Bridge 授权
→ revealed value 仍只在 renderer-local editor lifecycle 内存在
→ replacement 仅在显式编辑后进入 settings.save request
```

不得创建 Secret store/cache authority。

### 6.9 Markdown / Code Fence

手写安全 Markdown 子集保留，只把纯解析/渲染职责移出 `ChatTimeline.tsx`。

```text
safe-markdown.tsx
  ├─ renderInline
  ├─ block parser/render
  └─ CodeFence
```

CodeFence：

- 显示 fence language；
- copy 复制原始代码，不修改文本；
- 使用 Desktop 已存在的 Electron clipboard 边界扩展为通用 `copyText`，让 Session ID copy 与 Code Fence 共用一个真实 clipboard adapter；
- copy 成功/失败只做局部 UI feedback；
- 不折叠。

---

## 7. 按实施 Task 划分的工作范围

### W01：Core Compaction 冻结与旧路径清理

**任务目标**

一次完成 Core compaction 的结构收敛、strict multi-turn、oversized Turn 和旧同步路径删除。

**涉及文件**

```text
src/uthcode/core/context.py
src/uthcode/core/compaction.py
src/uthcode/core/__init__.py
src/uthcode/core/history.py（仅必要边界）
tests/test_context_compaction.py
tests/test_context_compiler.py
tests/test_t09_1_context_protocol_e2e.py
```

**实现要求**

- 将 `CompactionPolicy`、`CompactionResult`、`ContextCompactor` 及其仅服务于 compaction 的 helper 收敛到 `core/compaction.py`；
- `core/context.py` 不再拥有 compactor 执行实现；
- 删除无生产调用方的 `ContextCompactor.compact()` / `_compact_locked()` rolling legacy path 及只验证该旧入口的测试；
- `parse_compaction_result()`：multi-turn 必须显式 entries 且数量/顺序/turn_id/refs/coverage 完全匹配；纯文本或 top-level summary 自动复制仅允许单 Turn compatibility；
- oversized complete Turn 走 process-local bounded subpass，最终只返回一个完整 Turn Fine candidate；
- subpass failure/cancel/invalid result 不产生任何 durable candidate；
- 不改变 `SemanticEntry`、`TranscriptRef`、L5 durable granularity。

**完成结果**

Core 只保留一套 production compaction derivation path，one-Turn-one-Fine 语义不变。

**测试**

- multi-turn plain text rejected；
- multi-turn summary-only JSON rejected；
- malformed first attempt + valid retry 可继续；
- repeated invalid no commit；
- oversized first Turn 可推进；
- oversized subpass 中途 cancel/failure 无 candidate；
- full Turn refs 精确；
- L5/Fine 现有回归通过。

**明确不做**

Summary Graph、持久 chunk、Memory、参数调优。

**提交边界**

一个 Core-only commit；不得同时修改 Desktop。

---

### W02：Application Working Context 有效性、manual Compact 与 usage 双投影

**前置条件**

W01 完成。

**涉及文件**

```text
src/uthcode/application/context.py
src/uthcode/application/generation.py
src/uthcode/application/runs.py
src/uthcode/application/provider_usage.py
src/uthcode/application/__init__.py
[新增] src/uthcode/application/request_preparation.py
[新增] src/uthcode/application/compaction.py
src/uthcode/interfaces/desktop/bridge.py（仅共享 status DTO）
TUI/CLI 相关状态测试（仅最小兼容）
tests/test_t09_1_context_protocol_e2e.py
tests/test_w05_diagnostics.py
tests/test_application_runtime.py
```

**实现要求**

1. 从 `generation.py` 移出已有独立纯职责：
   - model limit / token count / final request count-rebuild helper → `request_preparation.py`；
   - L4/L5 compaction system prompt、payload、tool-free Provider request/run helper → `application/compaction.py`；
   - `UthCodeApplication`、Session/Run ownership 留在 `generation.py`。
2. Compact 前先得到 ordinary request baseline；candidate durable commit 前构建 prospective ordinary request；before/after 使用相同 exact/local source。
3. `after >= before`：候选无效，不 append Timeline；记录稳定 `no_reduction`/等价既有失败语义。
4. 有效 candidate append 后重新构建 current request；manual `/compact` 使用 `should_continue` 继续，直到 `<= retained_target` 或既有 bounded stop condition。
5. manual 无 eligible epoch 保持 `no_change`；已有有效 epoch 后遇 epoch limit/no-safe-epoch，可沿现有 partial-success → completed 语义返回，详细原因只留 diagnostics。
6. `ContextStatus` 不再被上一 Provider usage 写成 exact；`record_exact_usage()` 若不再有真实 current-context caller，应删除或收敛为 last-request usage 路径，不能继续混口径。
7. `UsageUpdated` Core 事件保持累计语义；Application Run 层由累计 usage delta 得到 `last_provider_request_usage`。
8. Application status/Bridge 增加显式、安全的 last request usage DTO；不暴露 Provider 原始 details。
9. 新增 Conversation projection fingerprint/change telemetry；只观测，不持久化、不影响 reduction policy。

**完成结果**

```text
Current Working Context = 当前 request
Last Provider Request Usage = 最近 request
Compact completed = 已验证下一 ordinary request 真实下降
```

**测试 / measurement**

Tests：协议、状态、no-commit、manual stop rule、exact/local source consistency、usage state separation。

Eval/measurement：构造当前确实会出现“summary 变短但 ordinary request 变大/不变”的场景，证明旧判定会误报、新判定拒绝；记录 projection rewrite 与 cache read/write observation。该 measurement 不成为 pytest 式固定产品阈值平台。

**提交边界**

Application/Context commit。由于 `generation.py` 的结构拆分与本任务修改同一职责，必须在本提交一次完成，后续 Part D 不再二次大搬迁该文件。

---

### W03：Renderer state 与 App 生命周期收敛

**前置条件**

W02 已稳定 Application status contract。

**涉及文件**

```text
desktop/src/renderer/state.ts
[新增] desktop/src/renderer/state-normalization.ts
[新增] desktop/src/renderer/state-session.ts
[新增] desktop/src/renderer/text-normalization.ts

desktop/src/renderer/App.tsx
[新增] desktop/src/renderer/useRuntimeLifecycle.ts

desktop/tests/renderer.test.tsx
[新增] desktop/tests/renderer-state.test.ts
[新增] desktop/tests/renderer-runtime-lifecycle.test.tsx
[新增] desktop/tests/renderer-session.test.tsx
```

**实现要求**

- `state.ts` 保持唯一 Renderer reducer/state authority；
- 仅把纯 normalize/replay/string/session snapshot helper 物理移出；
- `sessionRuntime` 仍只是 Interface projection，不变成第二持久状态；
- runtime operation generation/owner/tail、stale guard、terminal convergence 的 refs/AbortController 从 `App.tsx` 移入单一 hook；
- hook 只有 App 一个生产调用方，不建设通用 runtime manager；
- AgentEvent subscription 最终仍 dispatch 到同一 reducer；
- Settings、Composer、Session mutation 的现有 busy/ownership 语义不变；
- 把 `renderer.test.tsx` 中对应 state/lifecycle/session 合同迁到行为级测试文件，不删除高价值竞态/ARIA/Session authority coverage。

**完成结果**

App 主要负责页面组合和用户操作 wiring；state reducer 仍只有一个权威入口。

**明确不做**

Redux/Zustand/EventBus/第二 store/general manager。

---

### W04：Settings 单 Modal 与 Markdown 高频交互

**前置条件**

W03 完成。

**涉及文件**

```text
desktop/src/renderer/SettingsView.tsx
[新增] desktop/src/renderer/SettingsEditorModal.tsx
[新增] desktop/src/renderer/settings-draft.ts

desktop/src/renderer/ChatTimeline.tsx
[新增] desktop/src/renderer/safe-markdown.tsx

desktop/src/desktop-api.ts
desktop/src/preload.ts
desktop/src/main.ts

desktop/tests/renderer-settings.test.tsx
desktop/tests/renderer-chat.test.tsx
desktop/tests/preload.test.ts
相关 settings/CDP visual fixture
```

**实现要求**

Settings：

- Provider 与 Model 使用同一 Modal 分步；
- 只有一个 modal root/focus trap/inert background/return focus；
- Back：Model → Provider；Cancel：回滚当前 editor transaction；Save：沿现有 Configuration write；
- API Key reveal/replace/save 语义和窄 Bridge 授权不变；
- 不创建 generic Modal Framework。

Markdown：

- 从 ChatTimeline 移出安全 Markdown parser/render helper；
- 保留当前支持的 inline/code/emphasis/link/fence/heading/table/quote/list/paragraph 子集；
- 保留当前各 Timeline kind 的 Markdown 覆盖面；
- Code Fence 显示语言标签 + Copy；
- 不引入第三方 Markdown renderer；
- 不允许 raw HTML；safe URL 白名单保持；
- 不折叠代码。

Clipboard：

- 将当前只服务 Session ID 的 Electron clipboard IPC 收敛为真实有两个调用方的 `copyText(text)` Desktop API；
- Session ID copy 与 Code Fence copy 共用；
- 仍由 main process 调用 Electron clipboard，Renderer 不直接取得 Node/Electron 能力。

Chat scroll：

- 保留 near-bottom auto-follow；
- 用户离开底部后新内容到达时显示“回到底部/新消息”入口；
- 点击后滚到底并重新启用 follow-tail；
- streaming 不抢回用户滚动位置。

---

### W05：可拖拽布局、Focus Mode 与视觉层级

**前置条件**

W03 完成；可与 W04 在无共享文件冲突时并行，但 `app.css`、`App.tsx` 如存在共享修改必须单写者串行。

**涉及文件**

```text
desktop/src/desktop-api.ts
desktop/src/desktop-preferences.ts
desktop/src/renderer/state.ts
desktop/src/renderer/App.tsx
desktop/src/renderer/Sidebar.tsx
desktop/src/renderer/RuntimePanel.tsx
desktop/src/renderer/Composer.tsx
desktop/src/renderer/app.css
locales/zh-CN.ts
locales/en.ts
相关 renderer/CDP/visual tests
```

**实现要求**

布局：

- 新增 `sidebarWidth`、`runtimePanelWidth` Desktop preference；
- preference migration/default 对旧用户无破坏；
- desktop wide mode 提供可键盘/Pointer 操作的 resize separator；
- 设置明确 min/max，并结合 viewport 防止 Chat 被挤成不可用宽度；
- pointer move 只更新 Renderer visual state，持久写入在稳定边界执行，避免高频 preference IPC；
- narrow viewport 停用 resize，继续现有 Runtime overlay；
- zoom 后仍按 CSS pixel/viewport 约束重新 clamp。

Focus Mode：

- `focusMode` 为 Renderer transient state；
- 隐藏 Sidebar + Runtime，仅保留 Conversation/Composer；
- 提供明确进入/退出按钮和键盘 focus；
- 不写 Desktop preference；
- 不改变 `panelMode` 持久值；退出恢复之前 panelMode/width。

视觉：

- 收敛 surface/raised/accent/line 等已有 token 使用，减少无语义的近似 `color-mix`；
- 技术标识（run/session/path/command/code）统一 monospace；
- RuntimePanel 视觉分组为“运行状态 / 环境 / 标识”，但不隐藏现有事实；
- 增加 `Last Provider Request Usage` 展示，与 `Current Context` 分开；
- 新消息/按钮/modal 只使用轻量 transition；
- `prefers-reduced-motion` 下关闭非必要位移/动画；
- 不增加 skeleton，除非现有 acceptance 能稳定复现真实加载空白并证明必要。

回归保持：

```text
Sidebar show-more
selected/catalog order
Runtime overlay focus/escape/outside click
IME
focus-visible
aria/live region
dark/light/system
zh-CN/en
```

---

### W06：非 Desktop/TUI 高置信瘦身与测试收口

**前置条件**

W01/W02 完成，避免重复修改 Context/God files。

**涉及文件**

```text
[删除] src/uthcode/application/history.py
src/uthcode/application/context.py
src/uthcode/application/generation.py
eval/workloads.py
相关 tests imports

非 Desktop/TUI tests 中因 W01/W02/W06 已失效的旧-path 测试
```

**实现要求**

- 删除 `application/history.py` 转发 wrapper；真实调用方直接使用 Core 已有 `transcript_entries_from_message()`；
- 删除 W01 已淘汰的同步 compaction legacy tests/fixture，不为测试保留 production facade；
- 检查迁移后无调用方的 re-export/helper/import，确认后删除；
- 对重复测试只在“同一产品 contract 已有等价覆盖且失去独立故障定位价值”时合并；
- 不删除安全、权限、持久化、Context Hard Gate、Session authority、Provider protocol、pause/resume/cancel regression；
- 不重构 TUI；共享 contract 变化仅做最小兼容测试。

**明确 KEEP**

```text
core/agent.py：RunState/AgentLoop 单写者集中优先于拆文件
application/sessions.py：Session writer lifecycle/transaction ownership
integrations/session_files.py：durability/recovery 边界
integrations/providers/factory.py：多个真实 Provider 实现的 composition seam
integrations/providers/fake.py：当前 Headless/Eval/测试真实调用方
持久 Session legacy reader：仍用于读取受支持旧 Session 数据，不删除
```

---

### W07：全量回归、measurement 与冻结验收

**前置条件**

W01-W06 完成。

**执行内容**

```text
Python full pytest
Desktop npm test
Desktop CDP/visual acceptance
真实 Electron packaged acceptance（按现有脚本）
Context before/after measurement
静态 import/reference 检查
文件职责与新增 public surface 审查
```

必须生成可审查结果：

- Compact ordinary Working Context before/after；
- exact 与 local fallback 各一组；
- oversized Turn 一组；
- multi-turn malformed response 一组；
- Conversation projection changed + cache diagnostics observation；
- Desktop wide/narrow、light/dark、zh/en、zoom、reduced-motion；
- draggable layout persistence + Focus Mode transient；
- Settings focus/secret path；
- Code Fence copy；
- user-scroll preservation；
- 结构收敛前后主要职责/file size 变化作为辅助证据，不设 LOC KPI。

---

## 8. 文件级改动矩阵

| 文件路径 | 操作 | 文件职责 / 改动 | 核心类型 / 函数 | 禁止事项 | 对应验证 |
| --- | --- | --- | --- | --- | --- |
| `src/uthcode/core/context.py` | 修改 | 只保留 Context budget/compiler/accounting；移出 Compactor 执行 | ContextBudget, ContextCompiler, gates | 不再保留第二 compaction 主路径 | Context compiler/gate tests |
| `src/uthcode/core/compaction.py` | 修改 | 成为 L4/L5 compaction 单一 Core 模块；strict parse；oversized subpass | CompactionPolicy/Result/Epoch, ContextCompactor | chunk 不持久化 | compaction tests |
| `src/uthcode/core/__init__.py` | 修改 | 从新模块继续导出真实公共 compaction 类型 | exports | 不增加 legacy alias | import/architecture tests |
| `src/uthcode/application/context.py` | 修改 | candidate lifecycle、current context status、telemetry | ApplicationContextService, ContextStatus | 不再用上一 request usage 覆盖 current context | context e2e |
| `src/uthcode/application/generation.py` | 修改 | 保留 UthCodeApplication authority，移出 request/compaction pure helper | UthCodeApplication | 不建第二 Application facade | runtime tests |
| `src/uthcode/application/request_preparation.py` | 新增 | ordinary/compaction 共用的 Provider count + final-request preparation helper | internal functions | 不持有 Application state | exact/local gate tests |
| `src/uthcode/application/compaction.py` | 新增 | tool-free L4/L5 Provider request/payload helper | internal compaction request functions | 不拥有 durable Timeline | compact e2e |
| `src/uthcode/application/runs.py` | 修改 | 从累计 UsageUpdated 边界派生 last-request usage | AgentRun/Turn driver | 不改 Core UsageUpdated 协议 | run usage tests |
| `src/uthcode/application/provider_usage.py` | 修改 | 新增/收敛 display-safe last request usage projection | safe usage helpers | 不返回 Provider raw details | diagnostics tests |
| `src/uthcode/application/history.py` | 删除 | 删除无语义 pass-through wrapper | — | 不保留 alias | reference search |
| `src/uthcode/interfaces/desktop/bridge.py` | 修改 | 投影 last request usage；不重算 authority | status DTO | 不解释 Provider details | bridge tests |
| `desktop/src/renderer/state.ts` | 修改 | 保持 reducer/store 唯一 authority；接入 layout/usage state | RendererState, reducer | 不拆第二 store | state tests |
| `desktop/src/renderer/state-normalization.ts` | 新增 | DTO/replay normalize 纯函数 | normalize* | 不持 state | unit tests |
| `desktop/src/renderer/state-session.ts` | 新增 | Session runtime snapshot/catalog order 纯函数 | sessionRuntime* | 不持久化 | session tests |
| `desktop/src/renderer/text-normalization.ts` | 新增 | mojibake/string recovery | text helpers | 不成为通用 domain util | text tests |
| `desktop/src/renderer/App.tsx` | 修改 | 页面组合、操作 wiring；移出 runtime lifecycle refs | App | 不复制 owner refs | app lifecycle tests |
| `desktop/src/renderer/useRuntimeLifecycle.ts` | 新增 | 唯一 runtime operation owner/tail/terminal convergence | hook | 不建 Manager/EventBus | lifecycle tests |
| `desktop/src/renderer/SettingsView.tsx` | 修改 | 分类页面与 editor entry，移除 nested modal lifecycle | SettingsView | 不持第二 secret authority | settings tests |
| `desktop/src/renderer/SettingsEditorModal.tsx` | 新增 | Provider/Model 单 modal 分步 editor | editor state | 不泛化为 Modal framework | focus/CDP |
| `desktop/src/renderer/settings-draft.ts` | 新增 | Settings draft/normalize/save request 纯函数 | settingsSaveRequest 等 | 不读 API/DOM | unit tests |
| `desktop/src/renderer/ChatTimeline.tsx` | 修改 | Timeline scroll/render orchestration | ChatTimeline | 不再内嵌 Markdown parser | chat tests |
| `desktop/src/renderer/safe-markdown.tsx` | 新增 | 当前安全 Markdown 子集 + language/copy fence | renderMarkdown, CodeFence | no raw HTML / no new framework | markdown tests |
| `desktop/src/desktop-api.ts` | 修改 | `copyText` 与 layout preference schema | DesktopApi, DesktopPreferences | Renderer 不直连 Electron | preload tests |
| `desktop/src/preload.ts` | 修改 | 暴露窄 `copyText` | preload bridge | 不暴露 clipboard object | preload tests |
| `desktop/src/main.ts` | 修改 | main process clipboard adapter | IPC handler | 不扩大 Node surface | main/preload tests |
| `desktop/src/desktop-preferences.ts` | 修改 | width preference default/migration/clamp | preference schema | 不持久 Focus Mode | preference tests |
| `desktop/src/renderer/RuntimePanel.tsx` | 修改 | 分组 + current/last request usage 双展示 | RuntimePanel | 不计算 Context authority | renderer/CDP |
| `desktop/src/renderer/app.css` | 修改 | resize/focus/layout/visual/motion token | CSS | 不引入 framework | visual acceptance |
| `desktop/tests/renderer.test.tsx` | 修改 | 保留跨组件 smoke，迁出独立 contract | — | 不一次删除回归 | npm test |
| `desktop/tests/renderer-*.test.*` | 新增 | 按 state/lifecycle/settings/chat/session 行为拆测试 | — | 不测试私有文件结构 | npm test |

---

## 9. 关键状态与数据结构

### 9.1 Context

```text
ApplicationContextService
├─ owns → ContextStatus(current working context)
├─ owns → CompactionStatus
├─ owns → latest compile/count diagnostics
└─ does NOT own → durable Transcript/Timeline
```

```text
UthCodeApplication / AgentRun driver
└─ owns → last_provider_request_usage projection
      source: delta between consecutive cumulative UsageUpdated facts
      lifecycle: current process/application diagnostics
      durable: no
      enters model context: no
```

### 9.2 Oversized compaction

```text
Oversized subpass state
- process-local only
- created for one complete Turn
- destroyed after final candidate/failure/cancel
- no Session metadata
- no Timeline records
- no public ID
```

### 9.3 Desktop layout

```text
DesktopPreferences
├─ sidebarWidth          durable UI preference
└─ runtimePanelWidth     durable UI preference

RendererState
└─ focusMode             transient, not persisted
```

宽度不是 Application/Session 状态，不随 Session 切换改变。

---

## 10. 调用链 / 状态流

### 10.1 Compact

```text
manual / auto / overflow trigger
        ↓
Application resolves ContextBudget
        ↓
build ordinary baseline request
        ↓ exact/local count
ContextCompactor plans candidate
        ↓
Provider produces structured summary
        ↓
Core validates structure/coverage
        ↓
Application builds prospective ordinary request(candidate Timeline)
        ↓ same-source count
        ├─ not smaller → discard candidate, no append
        └─ smaller
             ↓
        Session writer append Timeline
             ↓
        current Context recompile
             ↓
        manual should_continue?
             ├─ > retained_target → next bounded epoch
             └─ stop
```

### 10.2 Last request usage

```text
Core Provider request N completed
       ↓
RunState cumulative Usage N
       ↓ UsageUpdated(cumulative N)
Application Run driver
       ↓ delta(cumulative N - cumulative N-1)
last_provider_request_usage
       ↓
ApplicationStatus / Desktop Bridge
       ↓
RuntimePanel
```

### 10.3 Desktop layout

```text
pointer/keyboard resize
      ↓
Renderer width state
      ↓ CSS variables
      ↓
layout updates
      ↓ stable end
Desktop preference write
```

Focus Mode：

```text
user toggle
  ↓
RendererState.focusMode
  ↓
hide sidebar/runtime visually
  ↓
exit
  ↓
restore persisted panelMode + widths
```

---

## 11. 测试矩阵

| 场景 | 预期 | 测试位置 |
| --- | --- | --- |
| Summary token 变短但 ordinary request 不变/变大 | Compact 不提交 | Context e2e |
| exact count available | before/after 都 exact | Context e2e |
| count capability missing | before/after 都 local | Context e2e |
| oldest Turn > compaction budget | bounded subpass 后仍产生一个 Fine | compaction tests |
| oversized subpass cancel/fail | 无 durable candidate | compaction tests |
| multi-turn plain text | validation fail → retry/no-commit | compaction tests |
| multi-turn top-level summary only | validation fail | compaction tests |
| single-turn compatible text | 保留现有 bounded compatibility（若仍有真实调用） | compaction tests |
| manual compact 多 epoch | 一次 invocation 追赶 retained_target | e2e |
| manual 无 eligible history | no_change | e2e |
| epoch limit after effective commit | durable success 保留，状态 completed，diagnostic 有 bounded reason | e2e |
| Current Context after terminal usage | 仍表示 current request，不跳为上一 request exact | application tests |
| Last request usage | 与最近一次 Provider request 一致，不是 Run cumulative | run/diagnostics tests |
| Conversation projection full→reduced/reduced→full | telemetry 能观察 changed，但不改变 policy | measurement |
| Renderer state split | reducer 输出与基线一致 | renderer-state tests |
| Session A/B background event | 状态隔离不变 | renderer-session/CDP |
| runtime stale operation | 旧 operation 不发布状态 | lifecycle tests |
| Settings Provider→Model→Back | 单 modal，focus 正确 | settings tests/CDP |
| Settings cancel | draft/replacement 回滚 | settings tests |
| API Key reveal | 仍走窄 Bridge，不持久 Renderer secret | settings/preload |
| fenced code language | label 正确 | markdown tests |
| fenced code Copy | 原文完整复制 | renderer/preload |
| unsafe/raw HTML/link | 保持安全子集 | markdown tests |
| 用户上滚 + streaming | 不拉回底部，出现新消息入口 | chat tests |
| 回到底部按钮 | 滚到底并恢复 follow-tail | chat tests |
| resize sidebar/runtime | min/max、persist、reload 恢复 | renderer/CDP |
| narrow viewport | resize disabled，Runtime overlay 保持 | visual/CDP |
| Focus Mode | 两栏隐藏，退出恢复 | renderer/CDP |
| reduced-motion | 新增动画被抑制 | CSS/visual |
| zh/en + dark/light + zoom | 关键 UI 无溢出/缺文案 | visual acceptance |
| Python public architecture | interfaces→application→core/integrations 不反向 | architecture/full pytest |

---

## 12. 工程瘦身边界

### DELETE

1. `ContextCompactor.compact()` 旧同步 rolling-compaction 主路径及只服务它的 `_compact_locked()`/旧 helper；生产已经由 `compact_async()` 驱动。
2. `src/uthcode/application/history.py` 无语义转发 facade；更新所有真实调用方后删除。
3. 因上述两项删除而变成无调用方的旧 test fixture、re-export、import。

### MERGE / CONSOLIDATE

1. `CompactionPolicy/Result/ContextCompactor` 与已经存在的 `core/compaction.py` 结构化契约归并为一个 compaction Core 模块。
2. Desktop Session ID copy 与 Code Fence copy 归并为一个有两个真实调用方的 Desktop clipboard adapter。
3. Settings 两套 modal focus/snapshot 生命周期归并为一个 editor modal lifecycle。

### SPLIT

1. `application/generation.py`：只拆已经独立成形的 request preparation 与 compaction Provider helper；UthCodeApplication authority 不拆。
2. `desktop/renderer/state.ts`：拆纯 normalize/session/text helper；reducer authority 不拆。
3. `desktop/renderer/App.tsx`：拆 runtime lifecycle owner hook；页面 orchestration authority 不复制。
4. `ChatTimeline.tsx`：拆安全 Markdown parser/render；Timeline 组件继续拥有 scroll/UI orchestration。
5. `renderer.test.tsx`：按真实产品 contract 拆测试文件，不按组件数量机械拆。

### KEEP

```text
core/agent.py
application/sessions.py
integrations/session_files.py
provider factory/ports/adapters
Session legacy durable reader
现有 Permission/Secret/Hard Gate/crash consistency 防线
```

F03 不以总代码量下降为硬验收；新增少量职责明确文件是允许的，前提是减少同一文件内的独立状态机/纯 helper/UI orchestration 混杂，且没有增加新的 authority。

---

## 13. 对现有能力的影响

| 能力 | 当前状态 | F03 处理 | 产品语义 |
| --- | --- | --- | --- |
| Agent Loop / RunState | 稳定 | KEEP；仅 Application 读取累计 Usage 形成 request delta | 不变 |
| Tool / FIFO / Permission | 稳定 | 回归 | 不变 |
| Session Transcript/Timeline | 稳定 | Compact candidate 提交前增强验证 | durable 语义不变 |
| L4 Fine | one Turn one Fine | oversized 内部 subpass | 不变 |
| L5 aging | raw Transcript evidence | 回归 | 不变 |
| Provider adapters | 稳定 | 复用 count/cache usage；不按 Provider 分支 | 不变 |
| Desktop Session background runtime | 已实现 | refactor 后回归 | 不变 |
| Settings Secret | 已实现窄授权 | UI 生命周期收敛 | 安全语义不变 |
| Markdown | 手写安全子集 | helper 拆分 + language/copy | 覆盖面不变 |
| Sidebar show-more | 已实现 | 回归 | 不变 |
| Runtime overlay | 已实现 | 回归 | 不变 |
| Desktop layout | 固定宽度 | 新增拖拽 + Focus | 新增已拍板 UX |

---

## 14. 第三方依赖

**无新增第三方依赖。**

- 不引入 Markdown framework；
- 不引入 UI component library；
- 不引入状态库；
- 不引入动画库；
- Provider 与 Electron 继续使用当前依赖。

---

## 15. 能力欠账

本轮检查 `docs/OutstandingDebtList.md` 后，F03 不触发以下后置条件：

```text
Memory / Evidence Retrieval
Persistent Runtime Recovery
Skill / MCP 动态 Tool
OS Sandbox
Artifact Store
高级 Summary Graph
```

F03 已经把当前阶段应完成的 Context freeze 缺口全部纳入正文，没有因为某个尚未实现的后置能力而刻意保留一个“本应在 F03 解决”的边界。

**无新增能力欠账。**

任务包拆分阶段不得因为本节为“无”而修改 `docs/OutstandingDebtList.md`；只有届时真实发现已有欠账触发条件变化时才按工作包规则处理。

---

## 16. Out of Scope

F03 明确不包含：

```text
文件预览 / Preview Surface
Workspace 文件浏览器
代码/文件深度预览体系
代码折叠策略深化
Git / Git Diff / Worktree
文件解析 Tool
PDF / Office 解析
多模态
WebSearch
MCP
Skill
Memory / 长期记忆
Subagent / Multi-Agent
Persistent Runtime Recovery
OS Sandbox
Desktop 之外的新 GUI
TUI 视觉/结构重构
208K / 96K / 48K 参数重新调优
Checkpoint View / dual-path / Backfill
后台 Context Maintainer Agent
完整 Eval / Benchmark 平台
```

后续“文件/代码预览”阶段再重新评估 Markdown 深度能力、Code preview、文件解析与相关 Desktop API，不在 F03 提前占位。

---

## 17. 验收标准

F03 只有同时满足以下条件才算完成：

### Context correctness

- Compact 成功判定基于 prospective ordinary Working Context；
- exact/local before-after 计量来源一致；
- 无效 candidate 从未 durable append；
- oversized first Turn 不再阻塞后续 L4；
- durable one-Turn-one-Fine 不变；
- multi-turn 无结构摘要无法静默复制；
- manual compact 在 bounded invocation 内多 epoch 追赶 retained target；
- Current Context 与 Last Provider Request Usage 完全分离；
- cache projection 只有 telemetry，没有 sticky state。

### Desktop engineering

- `state.ts` 只有一个 reducer authority；
- `App.tsx` 不再直接维护完整 runtime operation state machine；
- Settings 只有一个 modal lifecycle；
- Markdown parser 不再属于 ChatTimeline 组件主体；
- giant renderer test 已按行为边界拆分但 regression 不下降；
- 没有 Redux/Zustand/EventBus/通用 UI framework。

### Desktop UX

- 左右面板可拖拽并持久化；
- Focus Mode 瞬时、可恢复；
- Code Fence language/copy 可用且不改原文；
- 用户上滚不被抢回；有显式回到底部入口；
- RuntimePanel 分开展示 current context 与 last request usage；
- wide/narrow、dark/light、zh/en、zoom、reduced-motion、keyboard、IME、focus、ARIA 均通过现有 acceptance 体系。

### Project convergence

- 旧同步 compaction 主路径删除；
- application history pass-through wrapper 删除；
- compaction Core 边界归一；
- `generation.py` 的 request/compaction helper 有真实调用方且只拆一次；
- `core/agent.py`、Session persistence/recovery 等必要 authority 未因瘦身被拆散；
- 无新循环依赖、无 Interface→Core 越权、无 SDK 类型穿透；
- 无新增长期兼容层、未来占位抽象或无调用方 public surface。

---

## 18. 风险与实施顺序

### 高风险共享文件

```text
src/uthcode/core/context.py
src/uthcode/core/compaction.py
src/uthcode/application/context.py
src/uthcode/application/generation.py
desktop/src/renderer/state.ts
desktop/src/renderer/App.tsx
desktop/src/renderer/app.css
```

同一时间只允许一个 Worker 修改同一高风险区域。

建议依赖：

```text
W01 Core compaction
  ↓
W02 Application Context/status + generation structural split
  ↓
W03 Renderer authority split
  ├─→ W04 Settings/Markdown
  └─→ W05 Layout/visual
        ↓
W06 remaining non-Desktop/TUI cleanup
        ↓
W07 full regression
```

W04/W05 只有在写集合不重叠时并行；若都修改 `App.tsx`/`app.css`，必须串行。

---

## 19. 编码停止条件

编码代理仅在以下情况停止并报告用户：

- 当前实际 HEAD 与本任务书基线关键事实不一致；
- 1A/2A/3A/4A 或 Desktop 1A/2A/3A 无法在现有公共边界内实现；
- prospective ordinary request 验证必须先 durable commit 才能计算，且找不到无副作用构建路径；
- oversized Turn 只有改变 durable one-Turn-one-Fine 才能推进；
- last provider request usage 无法在不改变 Core 累计 Usage 公共语义的情况下可靠获得；
- 删除旧 compaction path 后发现真实生产调用方；
- 删除 `application/history.py` 后发现其承担未识别的 Application 产品语义；
- Desktop refactor 必须引入第二 store/runtime authority 才能继续；
- copy/resize 实现必须突破 Electron sandbox/CSP 安全边界；
- 实际需要新增第三方状态/Markdown/UI/animation framework；
- 需要修改 Session 持久格式或删除仍受支持 legacy reader；
- 任务实际扩展到 Preview/Git/Memory/MCP/Skill/Subagent 等独立能力。

以下情况由编码代理自行解决，不得停下等待用户：

```text
pytest/npm test 失败
类型错误
lint
fixture 调整
私有函数/文件名调整
CSS token 命名
局部 hook/reducer 组织
不改变产品语义的测试拆分
```

---

## 20. 最终冻结结论

F03 完成后，Context 阶段进入当前版本冻结：

```text
正确性缺口已收口
简单 bounded L4/L5 继续作为当前生产方案
高级 Context/Memory 能力必须由未来真实需求或 Eval 重新触发
```

Desktop 进入下一阶段的稳定基础：

```text
Renderer authority 更集中
文件职责更清楚
Settings/Markdown/布局具备可继续演进的真实边界
但不提前建立 Preview/Git/文件能力框架
```

工程瘦身的最终标准不是“代码最少”，而是：

```text
同样的产品与安全语义
由更少的执行路径、更少的重复 authority、更清楚的职责边界表达。
```
