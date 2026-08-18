# T09-1 Context 预算与 Compact 协议补齐 Spec

## 背景

T09 已建立持久语义历史、确定性 Context Compiler、固定 Operating Budget、Projection、Tool Result 外置和安全失败的 Compact 入口，但当前仍以单一固定预算治理所有模型，生产链路没有可执行的语义压缩模型调用，Session 也无法区分原始事实与压缩后的逻辑时间线。

本任务在不引入 Memory、持久 Runtime checkpoint 或后台调度器的前提下，完成按模型运行窗口治理、分层 Context reduction、可恢复的 Compact commit、原始证据回读和正式命令接入。

分析与实施基线为 `6b8dad8e38416de833e669fdb275aab824fe2845`。拆包核验时该提交与当前 `HEAD` 一致，源码事实与原始需求的关键前提一致。当前非交互 Windows 测试管道中，需求相关基线组合测试为 386 passed、3 个既有 TUI RGB ANSI 断言失败；该现象不改变本任务产品边界，实施完成时仍须复验并如实记录，不授权顺手重构无关 TUI renderer。

## 目标

- 每个可运行模型都有明确的 operating context window，并在每次 Provider 请求前执行统一 Hard Gate。
- 原始已闭合语义事实以 append-only Transcript 持久化；压缩事实以 append-only Timeline 持久化。
- Context reduction 按确定性 L1-L3、bounded L4 semantic epoch、L5 timeline aging 分层执行。
- 每个成功 L4/L5 事务以 ActiveCheckpoint 作为最后 durable commit；崩溃后只从持久事实重新推导进度。
- 自动与手动 Compact 使用相同 Application 编排，复用当前主模型与 Provider snapshot，并具备有限进展保护。
- 摘要后的模型可以通过 current-Session、exact-ref、bounded、read-only 的 HistoryRead 回读原始证据。
- CLI、TUI 与 Headless 共用同一 Application Context 权威链路；diagnostics 不泄露 Context 正文或秘密。

## 能力清单

### Task 1：Model Context Profile 与统一 Budget Resolver

建立按模型解析的运行窗口、输出预留、物理上限保护和 small/large-window retained policy，移除全局固定预算作为请求安全依据。

### Task 2：Transcript / Timeline Contract 与 Session v2

将原始历史与压缩视图硬切为 Transcript 和 Timeline，建立三种 Timeline 产品记录、checkpoint commit 与新 Session 文件布局；旧 Session 明确不兼容。

### Task 3：ContextCompiler logical view 与确定性 L1-L3

让唯一 Context model-view builder 从 Transcript、Timeline 和当前 Runtime facts 构造逻辑视图，并在模型压缩前完成完整语义边界上的确定性 reduction。

### Task 4：Production L4 与 bounded catch-up

接通 tool-free semantic compaction；一次 Gate 可执行有限个 bounded epoch，每批独立提交、重建和复判，不建立持久 Compact 状态机。

### Task 5：L5 Timeline Aging 与 HistoryRead

在 Fine Timeline 超预算时仅从 raw Transcript evidence 生成 macro summary，并提供 current-Session 原始历史的精确有界回读。

### Task 6：Incremental Transcript、Manual Compact 与 Overflow Retry

在每次下一 Provider call 前提交已闭合语义事实，把手动 Compact、single-flight、动态 status 和最多一次 overflow reduction retry 接入正式生命周期。

### Task 7：Diagnostics、Eval 与文档同步

将公开安全诊断、Eval 消费和用户/设计/当前事实文档切换到动态窗口、Transcript/Timeline 与 L1-L5 语义。

### Task 8：[接入主流程] 单一 Context Orchestration 收口

确认所有正式 Provider call、命令、Session 与工具路径只经过一个 Application Context 编排入口，并删除被替代的阶段性生产入口。

### Task 9：[端到端验证] Context / Compact / Recovery

从 Headless、CLI/TUI command adapter 和 Session resume 的真实入口验证正常路径、关键失败路径、崩溃边界与模型切换边界。

### Task 10：[遗留负担清理] 单 Transcript / Timeline 路径收口

删除本任务直接失效的固定预算、Projection authority、旧 Session 新写入路径、同步空 summarizer 和重复 Context 责任，不清理无关模块。

## 非功能要求

- Core 保持 Provider-independent，不依赖 filesystem、network、第三方 SDK、Application 或 Interface。
- 第三方 SDK 类型止于 Integration；Application 只消费 UthCode 自有 contract。
- Context Compiler 是唯一 model-view builder；Application 是 Context reduction 与持久提交的唯一编排者。
- Transcript 只保存 raw durable closed semantic facts；Timeline 只保存压缩产品事实；Runtime diagnostics 不成为 Context 或 Run authority。
- 每次 reduction 只在完整 Turn / semantic unit 边界发生，ToolCall 与对应 ToolResult 不得拆分。
- 大窗口 retained strategy 以绝对预算为主；小窗口必须同步收缩各子预算。
- Compact 调用必须有独立且有界的输入/输出预算、取消传播、结构化校验、no-progress 和 finite-attempt breaker。
- diagnostics、Event、日志、Eval artifact 不得包含 raw Transcript、summary 正文、Tool result 正文、API key 或其他秘密。
- 不新增第三方依赖，不创建无真实调用方的 Manager、Registry、Protocol、Event Bus、Job 或后台 worker。
- 中文 Markdown 使用 UTF-8；代码与文档事实一致。

## 设计骨架

### 权威数据

```text
Transcript = current Session raw durable closed semantic facts
Timeline   = append-only semantic reduction products
Checkpoint = L4/L5 transaction 的最后 durable commit
Snapshot   = 某次 Provider call 的逻辑工作集
RunState   = 当前进程 active Turn 的唯一 Runtime authority
```

Timeline 产品记录固定为 Fine Semantic Entry、Epoch Macro Summary 和 Active Checkpoint 三类。Compact Epoch 由相邻有效 checkpoint 之间的事务事实推导，不增加第四种持久产品记录。

### 预算与 Gate

每个 Turn 冻结当前模型 operating window、Provider/model、输出预算和 Tool definitions。Application 在每次模型调用前合并该窗口、输出预留、安全余量、可选可靠物理上限、可选精确计数与确定性估算，形成请求级预算并执行 Hard Gate。

可靠物理上限只用于 fail-safe guard，不覆盖用户选择的更小 operating window；没有可靠 Provider metadata 时不伪造 discovery。

### 分层 reduction

```text
L1 复用外置 Tool Result ref
L2 缩小旧 preview
L3 省略 inactive raw turns
L4 从 bounded raw epoch 生成 per-Turn fine entries
L5 从 raw Transcript evidence 生成 old complete epoch 的 macro summary
```

L1-L3 完全确定性。必要保护块与当前 Turn 本身无法装入时直接 fail closed，不使用 L4 隐藏不可丢内容。L4/L5 使用当前主模型：active Turn 内使用冻结 snapshot，idle 手动 Compact 使用 Application 当前选择；不增加独立压缩模型或跨 Provider fallback。

### bounded catch-up 与恢复

一次 Gate 可以串行执行一个或多个有界 L4 epoch。每批成功后先追加产品记录、最后追加 checkpoint，再重新构建并复判。attempt、coverage、estimate 与 cancellation 只存在于当前调用栈；重启后由 Transcript 与 latest valid checkpoint 推导下一未覆盖 epoch。

### Session 与原始证据

新 Session 使用分离的 Transcript、Timeline、Runtime diagnostics 和 Tool Result 存储。旧 T09 Session 不迁移、不 dual read/write。HistoryRead 只接受 active Session 所属 opaque Transcript ref，提供 bounded page，不接受路径、不跨 Session、不搜索、不递归外置其自身有界结果。

### 冻结决策

1. L4/L5 复用当前主模型和 Provider snapshot，不新增独立 compaction model。
2. 大窗口尊重真实 operating window；压力出现后使用 1..N bounded epoch catch-up，不建立独立或持久 Compact FSM。

## 能力欠账

无新增能力欠账。

本任务回补既有清单中的三项 T09-1 欠账：真实 Context Window / Model Limits 与统一 Budget Resolver、正式 tool-free Compaction use case、small-window / large-window adaptation。工作包尚未实施完成前清单项继续保留，并标注已由本工作包承接；全部验收完成后再删除对应已回补条目。

Persistent Runtime Recovery、Memory / Evidence Retrieval、跨 Session Artifact 生命周期和更高级压缩仍按既有欠账或独立未来能力处理，不属于本任务新增欠账。

## Out of Scope

- Memory、embedding、vector retrieval、semantic search 或跨 Session History Retrieval。
- Persistent Run / Turn checkpoint，以及 Pending Tool、Permission、AskUser、Provider coroutine 的跨进程恢复。
- 独立 compaction model、跨 Provider fallback、后台 Context Agent、Compaction Job/Scheduler。
- Timeline GC、rotation、self-compaction 或 Artifact Store 生命周期。
- Subagent、Multi-Agent、任务调度器。
- 全量 Provider model catalog、动态能力发现 UI、Provider-specific server context editing 进入 Core。
- 旧 Session migration、dual read、dual write 或兼容层。
- 与本任务无关的 Permission、Plan、Todo、Hook 或 TUI rendering 重构。

## 验收标准

1. 每个真实可运行模型都解析出正整数 operating context window；small/large-window 与物理上限边界有测试。
2. 每一次正式 Provider call 在发送前通过同一 Application Hard Gate；不可解析或不可安全装入时 Provider call count 为零。
3. Agent Loop 只等待请求准备，不拥有 Transcript、Timeline、reduction phase 或 Compact 状态。
4. Transcript 与 Timeline 文件及语义分离；旧 Session 明确不兼容；resume 不恢复 Runtime continuation。
5. Timeline 只有三种产品记录；每个成功 L4/L5 transaction 最后提交 ActiveCheckpoint；尾部未闭合事务不生效。
6. L1-L3 确定性且只在完整语义边界 reduction。
7. L4 从 raw Transcript 生成 bounded per-Turn fine entries，支持有限 multi-epoch catch-up、取消和 no-progress breaker。
8. L5 只从 raw Transcript evidence 生成 macro summary，不使用 summary-of-summary 作为权威来源。
9. HistoryRead 只读 current Session exact refs，bounded 且不能逃逸为路径或跨 Session 读取。
10. Transcript 在下一 Provider call 前增量提交闭合事实，不持久化 open streaming fragment 或 Runtime continuation。
11. `/compact` 复用相同 orchestrator；有候选真实压缩，无候选成功 no-op；同 Session compaction single-flight。
12. Provider overflow 最多触发一次 forced reduction/rebuild/retry，不学习或修改 operating window。
13. `/status`、public diagnostics 与 Eval 使用动态窗口和 Timeline/Gate 语义，不泄露 Context 内容或秘密。
14. CLI、TUI command adapter 与 Headless 共用 Application API；Interface 不拥有 Context 状态。
15. Core/Integration/Application/Interface 架构测试通过，第三方 SDK 类型不越界。
16. 定向测试、真实端到端测试、架构测试与全量回归均执行并记录精确结果；未通过项不得描述为通过。
17. 本任务直接失效的固定预算、Projection authority、旧 Session 新写入路径和空 summarizer 生产路径已删除，且未新增兼容层、重复责任或未来占位抽象。
