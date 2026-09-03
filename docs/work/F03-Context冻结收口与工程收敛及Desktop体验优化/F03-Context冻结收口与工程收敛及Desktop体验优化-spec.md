# F03：Context 冻结收口、工程收敛与 Desktop 体验优化 Spec

## 背景

UthCode 已具备生产 Context 编译、L4/L5 Compaction、Session Timeline 和 Windows Desktop 完整链路，但 Context 冻结前仍存在真实请求缩减判定、oversized Turn、usage 口径与 manual Compact 的机制缺口。Desktop 也出现 Renderer 状态、运行生命周期、Settings、Markdown 和大型测试职责聚集，并缺少面板拖拽、Focus Mode、代码块复制等高频体验。

本包以 Commit `cf50c50c25b6739037f52f56fc14b96e8fa2ad8b` 为分析基线。当前事实仍以实施时的 `src/ + desktop/src/ + tests/ + desktop/tests/` 为准。

## 目标

- 以 prospective ordinary Working Context 的同源 before/after 计量决定 Compact candidate 是否可提交。
- 让 oversized complete Turn 通过 process-local bounded subpass 推进，同时保持 durable one-Turn-one-Fine。
- 对 multi-turn compaction 响应执行严格结构、顺序、identity、引用与 coverage 校验。
- 分离 Current Working Context 与 Last Provider Request Usage，并增加只用于观测的 Conversation projection change telemetry。
- 让 manual `/compact` 在一次 bounded invocation 内追赶 retained target。
- 在不复制 authority 的前提下收敛 Core/Application 与 Desktop Renderer 职责。
- 提供可拖拽双侧面板、瞬时 Focus Mode、Code Fence language/copy 和明确的回到底部入口。
- 删除无生产调用方的旧同步 compaction 路径和无语义 Application history wrapper。
- 形成 Python、Desktop、CDP/visual、packaged acceptance 与 Context measurement 的可审查证据。

## 能力清单

### T01：Core Compaction 冻结与旧路径清理

- 将 compaction policy、result、planner 与 structured parsing 收敛到一个 Core 模块。
- 删除旧同步 rolling-compaction 主路径及只服务它的代码和测试，同时保留生产 L4/L5 共享的 single-flight 能力。
- multi-turn 只接受与完整 Turn 集合严格匹配的结构化 entries；单 Turn 才保留已有有限兼容。
- 为 oversized Turn 提供 process-local bounded subpass 规划、结果验证和最终单 Fine candidate 合成，不持久化中间状态。

### T02：Application Working Context、manual Compact 与 usage 双投影

- 在 durable append 前构建 prospective ordinary request，并用相同 exact/local source 比较 before/after。
- 由 Application 驱动 oversized subpass 的 tool-free Provider 调用；任一失败或取消均不提交 candidate。
- 无 reduction candidate 不写 Timeline；有效提交后重建 current request。
- manual Compact 在既有 epoch 上限内继续，直到达到 retained target 或既有 bounded stop condition。
- Current Context 只表示当前普通请求；Last Provider Request Usage 覆盖普通 Agent 请求和 Compact/L5 请求。
- 普通请求 usage 由累计 `UsageUpdated` delta 得到；Compact/L5 由其 Provider terminal usage 得到，Core 累计事件语义不变。
- Conversation projection fingerprint/change 只进入安全 diagnostics，不持久化、不参与策略。
- 把已经独立成形的 request preparation 与 compaction Provider helper 从 Application 主门面中拆出一次。

### T03：Renderer state 与 App 生命周期收敛

- `state.ts` 保持唯一 reducer/state authority，只迁出纯 normalize、text 与 session snapshot/replay helper。
- `App.tsx` 把 runtime operation owner、generation/tail、stale guard 与 terminal convergence 交给唯一生产 hook。
- per-Session runtime state 继续只是 Interface 投影；AgentEvent 最终仍进入同一 reducer。
- 按 state、lifecycle、session 行为拆分测试，同时保留竞态、ARIA 与 Session authority 覆盖。

### T04：Settings 单 Modal 与 Markdown 高频交互

- Provider 与 Model 编辑共享一个 modal root、focus trap、return-focus owner 和 editor transaction。
- API Key reveal、replacement 与 save 继续走窄授权边界，不进入持久 Renderer state。
- 安全 Markdown 子集迁出 Timeline；Code Fence 显示 language 并复制原始代码。
- Session ID 与 Code Fence 共用窄 `copyText` Desktop clipboard adapter。
- 用户离开底部后新内容不抢滚动位置，并显示回到底部/新消息入口。

### T05：可拖拽布局、Focus Mode 与视觉层级

- Sidebar 与 docked Runtime 宽度作为 Desktop preference 持久化，并在宽屏支持 Pointer/键盘 resize。
- min/max、viewport 与 zoom clamp 保证 Conversation 可用；窄屏继续使用既有 Runtime overlay。
- Focus Mode 是 Renderer 瞬时状态，不写 preference，不改变持久 `panelMode`，退出恢复原布局。
- RuntimePanel 分组展示运行、环境与标识，并分开 Current Context 与 Last Provider Request Usage。
- 保持主题、语言、IME、键盘、ARIA、focus-visible、overlay 与 reduced-motion 语义。

### T06：非 Desktop/TUI 高置信瘦身与测试收口

- 删除无语义 Application history 转发层，让调用方使用已有 Core 转换函数。
- 清理因 T01/T02 迁移而失去调用方的 re-export、helper、import、fixture 和旧路径测试。
- 只合并真正重复且失去独立故障定位价值的测试。
- 保留 Agent Loop、Session writer、持久恢复、Provider composition、Permission、Secret、Hard Gate 与 legacy durable reader。

### T07：[接入主流程] Context 与 Desktop 生产链集成

- 将 T01～T06 接入唯一普通请求、Compact、Application status、Desktop Bridge、Renderer reducer 与 Electron clipboard/preferences 生产链。
- 删除被替代入口，确认没有第二 compaction、Application、store、runtime lifecycle 或 Settings modal authority。
- 保持 Headless、CLI、TUI、Desktop 与 Session durability 的既有公共语义。

### T08：[端到端验证] 全量回归、measurement 与 Desktop 验收

- 执行 Python 全量测试、Desktop typecheck/tests、CDP/visual 和 packaged Electron acceptance。
- 生成 exact/local Compact before/after、无 reduction、oversized、malformed multi-turn、projection changed 与 cache diagnostics 证据。
- 覆盖 Desktop wide/narrow、dark/light、zh/en、zoom、reduced-motion、resize persistence、Focus、Settings secret/focus、Code Fence copy 与 user-scroll preservation。

### T09：[遗留负担清理] 否定扫描、文档与冻结收口

- 检查旧同步 compaction、history facade、重复 authority、无调用方 public surface、循环依赖与 SDK 穿透均已消失。
- 同步受影响的用户手册、核心设计、当前事实和 Context Index；不修改其他冻结工作包。
- 运行 UTF-8、Markdown fence、diff 与工作树范围检查，记录未验证项、风险和文件职责变化。

## 非功能要求

- 保持 `interfaces -> application -> core`，由 Application 组合 Integrations；Core 不依赖 UI、存储或 SDK。
- Agent Loop、RunState、durable Transcript/Timeline、Session writer 与 Renderer reducer 各自保持唯一 authority。
- Tool Batch FIFO、Permission、Secret、Hard Gate、crash consistency 与受支持 legacy reader 不退化。
- 不修改 Session 持久格式，不创建 Summary Graph、checkpoint、第二 store 或 secret cache。
- 不新增第三方依赖，不引入 Markdown/UI/state/animation framework、EventBus、Manager、Registry 或未来占位协议。
- 测试与真实风险匹配，不以 LOC 下降为 KPI；结构拆分必须有真实调用方和职责边界。
- 中文 Markdown 使用 UTF-8，文档与最终代码事实一致。

## 设计骨架

```text
ordinary request baseline
  -> same-source exact/local count
  -> Core candidate / Application oversized subpass orchestration
  -> prospective ordinary request rebuild
  -> same-source count
     -> not smaller: discard without durable append
     -> smaller: append Timeline, rebuild current request
```

```text
ordinary Agent request -> cumulative UsageUpdated delta
Compact/L5 request     -> compaction terminal usage
                      \-> Application Last Provider Request Usage

current compiler/accounting -> Current Working Context
```

```text
Desktop Bridge safe DTO
  -> one Renderer reducer authority
     -> runtime lifecycle hook
     -> single Settings editor modal
     -> safe Markdown + narrow copyText
     -> durable widths + transient Focus Mode
```

## 能力欠账

无。

F03 不触发现有 Memory/Evidence Retrieval、Persistent Runtime Recovery、Skill/MCP 动态 Tool、OS Sandbox、Artifact Store 或高级 Summary Graph 欠账的回补条件；`docs/OutstandingDebtList.md` 保持不变。

## Out of Scope

- 文件/代码预览、Workspace 文件浏览器、文件解析 Tool、PDF/Office、多模态或 WebSearch。
- Git/Git Diff/Worktree、Skill、MCP、Memory、Subagent、Multi-Agent 或后台 Context Maintainer。
- Persistent Runtime Recovery、OS Sandbox、Artifact Store、完整 Eval/Benchmark 平台或高级 Summary Graph。
- Desktop 之外的新 GUI、TUI 视觉/结构重构、代码折叠深化或新 Markdown framework。
- Context profile 参数重新调优、Checkpoint View、dual-path 或 Backfill。
- 为未来能力预留公共抽象、长期兼容层或新的持久格式。

## 验收标准

1. Compact 只有在 prospective ordinary request 以同源计量真实缩小时才 durable commit；无效 candidate 从未 append。
2. oversized complete Turn 可推进且 durable one-Turn-one-Fine、完整 refs 与 L5 语义不变；失败或取消不留下 durable candidate。
3. multi-turn 非结构化、数量/顺序/identity/coverage 不匹配的响应被拒绝并按既有重试/失败边界收口。
4. manual `/compact` 在一次有界调用中追赶 retained target；无 eligible history 为 `no_change`，已有有效提交不因后续 bounded stop 被伪装为失败。
5. Current Working Context 与 Last Provider Request Usage 口径、生命周期和 DTO 明确分离；后者覆盖 ordinary 与 Compact/L5，cache/projection 只作 telemetry。
6. Core/Application 只保留一套 compaction production path；旧同步入口与 Application history wrapper 被删除。
7. Renderer 只有一个 reducer authority，App 只有一个 runtime lifecycle owner，Settings 只有一个 modal lifecycle，Markdown parser 不属于 Timeline 主体。
8. panel resize/persistence、Focus Mode、Code Fence language/copy、新消息入口及 Runtime 双 usage 展示通过自动与真实 Desktop 验收。
9. wide/narrow、dark/light、zh/en、100%/125%/150% zoom、reduced-motion、keyboard、IME、focus 与 ARIA 回归有精确证据。
10. Python、Desktop、architecture、CDP/visual、packaged acceptance、Context measurement、否定扫描和 UTF-8 检查结果均被如实记录。
11. 未新增第三方依赖、第二 authority、循环依赖、Interface→Core 越权、SDK 类型穿透、未来占位或无调用方 public surface。
12. Feedback、Checklist、当前事实文档和代码一致；Agent 不自动归档，不执行未经用户明确要求的 Git 写操作。
