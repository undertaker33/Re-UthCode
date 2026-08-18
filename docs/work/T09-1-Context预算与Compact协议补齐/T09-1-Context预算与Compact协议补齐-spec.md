# T09-1：Context 预算与 Compact 协议补齐 Spec

## 背景

T09 已建立持久会话、确定性 Context Compiler、Tool Result 外置和有界 Compactor，但当前运行时仍以固定 Operating Budget 作为唯一预算权威，无法同时保护小窗口模型并利用大窗口模型。生产组合也未接通可用的语义压缩模型调用，原始会话事实与压缩视图仍共用单层历史协议，无法表达可恢复的多阶段压缩与 Timeline 老化。

本包在现有模块化单体、单 Agent ReAct Loop、Session single-writer 和安全配置边界内，完成动态模型窗口、双 Gate、Transcript/Timeline、确定性与语义 reduction、手动 Compact、一次 overflow retry、原始证据回读及包级文档收口。

## 目标

- 每个可运行模型都显式声明 Operating Context Window，并由可靠 Provider 限制只做收紧。
- 将 proactive Context pressure 与真实请求安全拆成两个独立判断；所有真实模型调用发送前都经过最终请求 Hard Gate。
- 以 Transcript 保存当前 Session 已闭合的原始语义事实，以 append-only Timeline 保存派生语义视图，并用最后提交的 checkpoint 确定有效状态。
- 建立不调用模型的确定性 reduction、使用当前冻结主模型的有界语义 reduction，以及不依赖持久 Compact 状态机的多 epoch catch-up。
- 让 Fine Timeline 可独立老化，并允许模型通过 current-Session opaque ref 有界读取原始 Transcript 证据。
- 让手动 Compact、自动治理、Provider overflow recovery、CLI/TUI/Headless 和安全 diagnostics 复用同一 Application 边界。
- 硬切新的 Session 持久化格式；不迁移、不双读写、不保留旧 Projection 兼容层。

## 能力清单

### T01：模型窗口、Provider 能力与双 Gate 预算

- 可运行模型显式提供正整数 Operating Context Window。
- 可靠 Provider input ceiling 只收紧有效限制；缺失能力时使用配置窗口，不虚构 metadata。
- Provider count 与确定性 local estimate 进入统一 estimate 语义，并由集中 policy 解析 uncertainty。
- Working headroom、保留预算和压缩预算对小窗口自适应收缩，对大窗口使用绝对上限，避免统一百分比规则。
- Auto Gate 与 Hard Gate 可独立观察，允许 proactive pressure 与 hard-safe 同时成立。

### T02：Transcript、Timeline 与 Session v2

- Transcript 成为当前 Session 的原始 durable closed semantic fact authority。
- Timeline 只允许 Fine semantic entry、Epoch macro summary 与 Active checkpoint 三类产品记录。
- 成功的语义派生 transaction 先写派生记录、最后写 checkpoint；loader 忽略 checkpoint 后未闭合尾部。
- fresh Session 使用分离的 Transcript、Timeline、Runtime Log 与 Tool Result 文件；旧 Session 明确不兼容。
- 保留 strict sequence、完整 Tool semantic group、single writer、fsync、reconciliation、quarantine 与 close/reopen recovery。

### T03：最终请求计数与确定性 L1-L3

- Context Compiler 继续作为唯一 model-view builder。
- 每次普通请求先形成最终候选 request，再对 system、messages、tools、输出预留和已知结构 overhead 做计数与 Gate 判断。
- L1 复用 Tool Result 外置，L2 确定性收缩 bounded preview，L3 按完整 inactive Turn/semantic unit 省略 raw view。
- protected context、当前 Turn 和 ToolCall/ToolResult 配对不可拆分。
- L1-L3 后重新组装并重做 Auto/Hard Gate；required facts 自身超限时 fail closed。

### T04：生产 L4 与 bounded catch-up

- L4 使用 active Turn 冻结的主 Provider、model 与窗口；idle manual 场景使用当前选择。
- Compact request 独立、tool-free、bounded，并在调用模型前执行 Hard Gate。
- 结构化输出按 covered Turn 形成 Fine semantic entries；校验通过后 checkpoint 最后提交。
- 一次编排允许多个有界 epoch，每次提交后重新构建并重做 Gate。
- no-progress、repeated failure、no-safe-epoch 与 cancellation 都有有限、可观测且不产生伪提交的结果。
- Auto pressure 在有限治理后仍未解决但 Hard-safe 时允许发送并记录原因；Hard-unsafe 始终 fail closed。

### T05：L5 Timeline Aging 与 HistoryRead

- Fine Timeline 超预算可独立触发 L5，不依赖普通请求先达到 Auto pressure。
- L5 只选择旧的完整 compact epoch，并重新读取 raw Transcript evidence，禁止 summary-of-summary。
- 成功 L5 追加 epoch macro summary 与最后 checkpoint，在 logical view 中 supersede 旧 Fine entries，不删除物理记录。
- HistoryRead 只读取 active Session 的精确 opaque Transcript ref，结果有界、只读，不支持搜索或跨 Session。
- HistoryRead 输出不会递归外置。

### T06：[接入主流程] 生命周期、命令与 overflow recovery

- Application 在每次下一普通 Provider call 前 durable append 已闭合事实，并在 terminal tail 提交余下事实；不持久化 open continuation。
- active Turn 冻结 Provider、model、窗口、output 与 tools；运行中切换模型只影响下一 Turn。
- 手动 Compact 进入与自动治理相同的异步 Application orchestrator，低 pressure 也可执行；无候选时 success no-op。
- 普通 Provider overflow 最多强制 reduction 后 retry 一次；二次 overflow 失败且不修改窗口事实。
- 同步命令保持兼容，Compact 命令可 await；TUI 只做异步命令适配，不拥有 Context 语义。
- CLI、TUI 与 Headless 的所有真实模型调用都经过相同 Hard Gate。

### T07：[端到端验证] Diagnostics、Eval、文档与回归

- status 与公开 diagnostics 展示动态窗口、有效限制、Gate、count source、Timeline 与 pressure 结果，但不泄露正文、摘要、Tool Result 或秘密。
- Eval 只消费公开安全 diagnostics，按既有并列维度比较，不新增总分，不把 tuning 默认值定义为产品成败阈值。
- 用户手册、Core Design、Tool 清单、当前事实文档和索引与代码事实同步。
- 从正式 Application/command/headless 入口覆盖普通、自动、手动、overflow、resume、HistoryRead 和失败路径。
- T05/T06/T08、架构边界与全量测试回归通过。

### T08：[遗留负担清理] 删除阶段性与兼容逻辑

- 删除固定预算作为 runtime safety authority、Projection 生产语义、旧 Session 新写入路径和同步-only Compact 路径。
- 删除不可达分支、重复 Context 编排、旧文案、旧导出与只为早期实现存在的 alias/wrapper。
- 确认未新增第四种 Timeline 产品记录、持久 Compact FSM、独立 compaction model、跨 Provider fallback 或无调用方的系统级抽象。
- 保留 Permission、Plan/Todo、Runtime Hook、其它 Slash Command 与 TUI rendering 的既有语义。

## 非功能要求

- Core 不依赖 filesystem、network、Provider SDK、Application、Integration 或 Interface。
- Provider SDK 类型截止在 Integration，Application/Core 只消费 UthCode-owned DTO。
- Interface 只调用 Application；Headless 不依赖 TUI。
- 所有 reduction 与 persistence 都按完整语义边界工作，ToolCall 与匹配 ToolResult 不可拆。
- 未知 durability 继续 fail closed；无法确认副作用时不盲目重试。
- Context、diagnostics、Event、Journal、Snapshot 与 Eval artifact 不得泄露 API key、秘密或 raw evidence 正文。
- 无真实 Provider 网络调用也能完成必过测试；Provider capability 使用 fake SDK/client fixture。
- 不新增第三方依赖。

## 设计骨架

```text
Configured operating window
        + optional reliable Provider ceiling
        ↓
Effective limit + adaptive capped profile
        ↓
final candidate request assembly
        ↓
count estimate + uncertainty
        ↓
Auto Gate / Hard Gate
        ↓
L1 -> L2 -> L3 -> optional L4 catch-up
        ↓
rebuild + re-gate
        ↓
Hard-safe Provider call or fail closed
```

```text
Transcript (raw closed facts) ──► HistoryRead
            │
            └──► L4/L5 evidence
                         │
                         ▼
Timeline: Fine entries / Macro summaries / Active checkpoint
                         │
                         ▼
                 logical model view
```

Compact 编排只在当前 Application 调用栈保存 attempt、coverage、previous estimate、current epoch 与 cancellation；持久状态只由 Transcript 与 latest valid checkpoint 推导。

## 能力欠账

无新增能力欠账。

本包计划回补 `docs/OutstandingDebtList.md` 中 T09 的三项 Context 欠账：真实模型窗口与 Provider limits、生产 tool-free Compaction、small/large-window adaptation。工作包创建时只更新其回补触发状态；只有本包实现完成、Checklist 全部完成且 Feedback 已记录后才能从滚动清单删除。

Persistent Runtime Recovery、Memory/Evidence Retrieval、Artifact Store GC、Timeline physical GC、后台 Context Agent 和独立 compaction model 属于 Out of Scope，不登记为本包新增欠账。

## Out of Scope

- Memory、Embedding、Vector/semantic retrieval、跨 Session History retrieval。
- active/paused Run/Turn、Pending Tool、Permission、AskUser、Provider coroutine 的跨进程恢复。
- 独立 Compaction Model、跨 Provider fallback、后台 Context Agent、Job Scheduler、持久 Compact FSM。
- Timeline physical GC、rotation/self-compaction、Artifact Store 生命周期与 GC。
- Subagent、Multi-Agent、Worktree。
- Provider 全量 Model Catalog、自动模型发现 UI、新的 headroom 用户配置子系统。
- Provider-specific server-side context editing 进入 Core。
- 旧 T09 Session migration、dual read、dual write、compatibility alias。
- Permission、Plan/Todo、Runtime Hook、TUI rendering 与其它 Slash Command 的非必要重构。

## 验收标准

1. 所有 runnable model 有明确正整数 Operating Context Window；没有固定窗口 fallback。
2. 可靠 Provider ceiling 只收紧有效限制，缺失时不伪造；Provider overflow 不反向学习窗口。
3. Auto Gate 与 Hard Gate 独立，headroom 对小窗口收缩且对大窗口封顶。
4. 每个普通、L4、L5、manual 与 retry 模型调用都基于最终 request 通过 Hard Gate。
5. Provider count 与 local estimate 都带来源和有界 uncertainty。
6. L1-L3 确定性工作；仍处于 Auto pressure 时尝试 L4，已清除时不做无意义 L4。
7. L4/L5 tool-free、bounded、复用当前主模型，并且自身只做 Hard Gate、不递归 Auto compact。
8. bounded catch-up 支持多个 epoch，每批 checkpoint 最后提交并重新 Gate，没有持久 Compact FSM。
9. finite reduction 后 Auto unresolved + Hard-safe 可发送并记录原因；Hard-unsafe Provider call count 为零。
10. Transcript 与 Timeline 职责分离，Timeline 只有三类产品记录，trailing incomplete transaction 不生效。
11. L5 从 raw Transcript 取证且不做 summary-of-summary；HistoryRead 只允许 current Session exact bounded read。
12. fresh Session 使用 v2 文件布局；old v1 明确不兼容，无迁移或双轨逻辑。
13. closed facts 在 request preparation 与 terminal 边界增量 durable；不持久化 open runtime continuation。
14. 手动 Compact 可在低 pressure 执行，无候选时 success no-op 且无 Timeline garbage。
15. ordinary overflow 最多 reduction + retry 一次，二次 overflow 停止且不修改窗口。
16. status、diagnostics 与 Eval 不泄露正文或秘密，且不建立总分。
17. CLI、TUI、Headless、Session resume、Permission、Plan/Todo 与固定 Hook 行为回归通过。
18. 架构测试、相关定向测试与全量回归通过；文档与当前 `src/ + tests/` 一致。
19. 没有旧 Projection/固定预算生产 authority、compatibility layer、第四种 Timeline record 或无调用方系统抽象。
