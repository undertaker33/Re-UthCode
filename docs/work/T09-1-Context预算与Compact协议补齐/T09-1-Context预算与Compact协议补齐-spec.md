# T09-1 Context 预算与 Compact 协议补齐 Spec

## 背景

T09 已提供固定 258K Context Compiler、Canonical History、Projection、Tool Result 外置、Session persistence 与 Compact 安全失败入口，但没有 per-model window、发送前双 Gate、可靠 Provider count/ceiling、production summarizer 或长期 Timeline aging。

本工作包以 `1887361d7a929b5aa493c8783cdc5c35f623a041` 为唯一基线，从零替代旧 T09-1 规划。重写前已确认没有 Worker 派发、Feedback 或 Checklist 勾选，源码也未实施 T09-1。

## 目标

- 每个可运行模型提供 operating `context_window = C`；可靠 Provider ceiling 只收紧为 `E`。
- 每个最终结构化 Provider request 在发送前计入 input count、output reserve 与 counting uncertainty。
- Auto Gate 负责提前治理，Hard Gate 独占发送许可；二者不再混为统一阈值。
- Working Headroom 随小窗口缩小、随 E 缓慢增长并在大窗口绝对封顶，不使用统一 90%。
- L1-L3 清除 Auto pressure 后直接发送；仍高于 Auto Gate 时即使低于 E 也继续 L4。
- Transcript 保存 raw durable closed facts；Timeline 保存 Fine、Macro 与 ActiveCheckpoint 三类 append-only reduction facts。
- L4 使用当前主模型完成 bounded epoch 与 `1..N` catch-up；L5 可由 Fine Timeline pressure 独立触发并重读 raw evidence。
- manual `/compact`、自动治理和 overflow forced reduction 复用同一 Application Context Orchestrator。
- Provider overflow 最多触发一次 reduction/rebuild/retry，不学习窗口。
- CLI、TUI、Headless、diagnostics、Eval 与文档使用同一事实与安全边界。

## 按 Task 划分的能力清单

### Task 1：模型窗口、计数能力与双 Gate 预算契约

建立 `C/E`、output reserve、count source、uncertainty、adaptive capped headroom、Auto/Hard Gate纯值；接入模型配置和 Anthropic limits/count capability。

### Task 2：Transcript / Timeline 与 Session v2 持久事实

硬切 `CanonicalHistory + Projection`，建立 raw Transcript、三类 Timeline record、checkpoint-last transaction、fresh Session v2 与 old Session rejection。

### Task 3：最终请求组装、Auto/Hard Gate 与确定性 L1-L3

在已有 awaitable request-preparer 内组装、计数、双 Gate与确定性 L1-L3；Hard unsafe时零Provider call。

### Task 4：L4 proactive semantic compaction 与 B′

接通 tool-free L4、bounded raw epoch、retained target、checkpoint/rebuild/re-gate和有限 catch-up；区分 Auto pressure未清除与Hard unsafe。

### Task 5：L5独立老化与 HistoryRead

由 Fine Timeline pressure独立触发 raw-evidence L5，生成Macro coverage；提供 current-Session exact-ref raw evidence读取。

### Task 6：运行生命周期、手动 Compact、Overflow、Diagnostics 与文档

接入 request-boundary closed-fact persistence、manual compact/no-op、single-flight、一次 overflow retry、status、safe diagnostics、Eval和文档。

### Task 7：[接入主流程] 单一 Context Request Orchestration

收口全部正式 model call与命令/Session入口，删除被替代生产路径。

### Task 8：[端到端验证] Dual Gate / Compact / Recovery

从正式入口验证 small/large window、L1-L5、manual、overflow、crash/resume、model switch与Headless/TUI。

### Task 9：[遗留负担清理] 动态预算与单 Timeline 路径收口

删除固定预算、Projection authority、Session v1新写入、空 summarizer、旧 overflow path、兼容层和无调用方抽象。

## 非功能要求

- Core 不依赖 filesystem、network、Application、Integration、Interface 或第三方 SDK。
- Provider SDK 类型止于 Integration；Application 只消费 UthCode-owned values。
- ContextCompiler 是唯一 model-view builder；Application 是 Gate/reduction/persistence 的唯一编排者。
- AgentLoop 继续只拥有行为 loop；直接复用其现有 awaitable preparer 与 one-retry guard。
- reduction 只在完整 Turn/semantic unit 边界发生，ToolCall/ToolResult 不拆分。
- compact model call 无 Agent Tools，有独立且有界 input/output budget、取消、parse validation和finite breaker。
- diagnostics/Event/log/Eval artifact 不包含 raw Transcript、summary、Tool result、API key或秘密。
- 不新增第三方依赖、用户 headroom配置系统、Manager/Registry/Job/FSM或未来占位。
- 中文 Markdown 使用 UTF-8。

## 设计骨架

```text
final GenerationRequest
  -> count + output reserve + uncertainty
  -> Auto Gate(E - R)
       -> L1-L3
       -> L4 1..N when still pressured
  -> L5 when Fine Timeline > F
  -> rebuild/recount
  -> Hard Gate(E)
  -> ProviderPort

Transcript(raw facts) -> Timeline(derived products) -> ContextCompiler -> request
```

`R` 的冻结性质是 adaptive + absolute cap；初始内部 default 为 `clamp(ceil(E * 0.08), 2_048, 32_768)`。具体数值可由 Eval 后续替换，不是长期公共协议。

Auto治理达到breaker但当前request仍Hard safe时，记录`auto_pressure_unresolved`并允许发送；Hard unsafe必须fail closed。这保持Auto policy与Hard safety职责分离。

冻结决策：

1. D1：L4/L5复用当前主Provider/model；active Turn使用冻结snapshot，idle manual使用Application当前选择；无独立compaction model或cross-Provider fallback。
2. D2：L4执行`1..N` bounded catch-up，每批checkpoint/rebuild/re-gate；无持久Compact FSM。
3. D3：Auto Gate与Hard Gate分离；Working Headroom自适应且绝对封顶；Provider count仍保留uncertainty。

## 能力欠账

无新增欠账。

本任务承接既有三项T09-1欠账：Model Limits/Budget Resolver、production tool-free Compaction、small/large-window adaptation。实现完成且Checklist/Feedback闭合前仍保留滚动清单项。

## Out of Scope

- Memory、embedding、vector/semantic retrieval、cross-Session History Retrieval。
- Persistent Run/Turn checkpoint和Pending Tool/Permission/AskUser/Provider coroutine恢复。
- Artifact Store生命周期、Timeline物理GC/rotation/self-compaction。
- independent compaction model、cross-Provider fallback、background Context Agent、Job/Scheduler/FSM。
- Subagent/Multi-Agent、全量Provider model catalog/UI。
- Provider server-side context editing作为Core语义。
- 旧Session migration/dual read/dual write/compatibility。
- 与本任务无关的Permission/Plan/Todo/Hook/TUI renderer重构。

## 验收标准

1. Auto Gate与Hard Gate分别可观测，没有统一90%规则。
2. 25K headroom收缩；1M headroom绝对封顶且不浪费100K级空间。
3. final request计入output reserve与count uncertainty；provider count不被当绝对事实。
4. L1-L3后仍高于Auto Gate时继续L4；清除pressure时不执行L4。
5. Hard unsafe时Provider call count为0；每类真实model call均有Hard Gate证据。
6. L4 retained target、bounded B′、checkpoint-last与finite breaker成立，无Compact FSM。
7. L5可由Fine Timeline pressure独立触发，并只读raw Transcript evidence。
8. manual compact不依赖Auto Gate；无候选successful no-op且不写垃圾Timeline。
9. overflow最多一次forced reduction/retry，不修改C。
10. Transcript/Timeline hard cut、old Session reject和crash recovery成立。
11. HistoryRead current-Session、exact-ref、bounded、read-only，不能跨Session或读路径。
12. closed facts在下一Provider call前durable，open Runtime continuation不持久化。
13. active Turn冻结Provider/model/C/capability；切模型只影响下一Turn。
14. diagnostics/Eval/docs安全且与实现一致。
15. 定向、E2E、架构与全量测试记录精确结果；直接失效路径已清理。
