# T09：让长期会话拥有可治理的上下文

长期 Coding Session 同时需要保存已经发生的事实、选择下一次请求的工作集，并在上下文变长时安全地减少派生视图。UthCode 将这三件事分开：`Transcript` 保存当前 Session 的闭合原始事实，`Timeline` 保存可重建的派生语义视图，`ContextCompiler` 为每一次 Provider 请求建立最终工作集。

```text
Transcript（raw closed facts）
        ├─ HistoryRead（当前 Session、精确 ref、有界页）
        └─ L4/L5 raw evidence
                 ↓
Timeline（Fine / Macro / ActiveCheckpoint）
                 ↓
ContextCompiler
                 ↓
final GenerationRequest
                 ↓
Provider Integration
```

## Context authority 与请求工作集

`Transcript` 是 append-only 的 Session authority，只接受已经闭合的 User、Assistant 和完整 ToolCall/ToolResult 语义单元。它不保存 streaming fragment、未匹配 ToolCall、Permission/AskUser waiter、Provider coroutine 或 active Turn continuation。

`Timeline` 是派生的 append-only context state，产品记录只有三类：`SemanticEntry`（Fine）、`EpochMacroSummary`（Macro）和 `ActiveCheckpoint`。一次成功的 L4/L5 transaction 先追加派生记录，最后追加 checkpoint；加载时只有最后一个有效 checkpoint 之前的完整 transaction 进入 logical view，checkpoint 后的 trailing records 不生效但仍保留物理审计事实。

Context Compiler 组合结构化的 Instruction Plane、Conversation Plane 和 Tool Schema：

```text
GenerationRequest
├─ Instruction Plane：Prompt Asset、Core Contract、有效 AGENTS
├─ Conversation Plane：Timeline logical view、Transcript recent facts、runtime facts、current user
└─ tools：Application 提供的 Tool definitions
```

普通 User/Tool 文本即使包含 instruction-like 标签，也不会升级为 Core 或 System instruction。Working Set 只在完整 semantic boundary 上选择，不能拆开 ToolCall 与对应 ToolResult；当前没有 Memory、semantic retrieval 或后台 Context Agent。

## 动态模型限制与两层 Gate

模型输入限制只来自用户配置的 `context_window` 和可靠 Provider runtime metadata。有效输入上限取已知 configured/provider input 中更紧者；两者都未知时，Application 在 Provider call 前 fail closed，不使用固定窗口、型号名称推断、bundled metadata 或本地官方型号表。Provider `max_output_tokens` 与可选 `max_combined_tokens` 保持独立维度，未知值不伪造。

每个最终 Provider-visible request 都经过两层判断：

```text
final request
  ├─ Pressure Estimate + allowance ──> Auto Gate（proactive policy）
  └─ Preflight Safety Count/Estimate ─> Hard Gate（fail closed）
```

Hard Gate 覆盖 instruction、messages、tools、已知 framing、requested output reserve 及集中 safety allowance，并分别验证 input、output、combined 维度。Provider count 是高可信度 estimate，不宣称 tokenizer 数学精确；Provider 实际 overflow 仍是最终外部裁决。

Working headroom、active evidence、Fine Timeline、recent tail 和 Compact budget 是集中定义的自适应 policy：小窗口会联动收缩，大窗口使用绝对 cap，不采用统一百分比或固定丢弃一段窗口的规则。Auto pressure 可以与 Hard-safe 同时成立；这表示应尝试 proactive reduction，但不阻断一个已经安全的普通请求。

确定性 reduction 按 `L1 → L2 → L3` 执行：大 Tool Result 先使用已有外置/ref 机制，随后收缩非活动 preview，最后只省略完整的非保护 semantic unit。每一步都重新组装最终 request、计数并 re-gate；current facts、protected blocks 和 Tool pair 不能拆分。

## Compact、Timeline aging 与 overflow

L4 发生在 active Turn 内时复用该 Turn 冻结的 Provider、remote model 和分维 limits；idle 手动 `/compact` 使用当前选择。L4/L5 请求有独立 prompt、独立预算、`tools=()`，发送前只执行 Hard Gate，不递归触发另一轮 Compact，也不切换 Provider/model。

一次 Application orchestration 可以执行有限的 bounded raw epoch catch-up。每个 epoch 都经历：

```text
derive raw Transcript epoch
  → tool-free model call
  → validate refs / coverage / bounded summary
  → append Fine 或 Macro
  → append ActiveCheckpoint last
  → rebuild ordinary request and re-gate
```

attempt、coverage、previous estimate、epoch 和 cancellation 只存在于当前调用栈，不写入 RuntimeLog 或 Session state。无 progress、无 safe epoch、解析失败、取消和持久化未知都 fail closed，不产生伪 checkpoint。

当 Fine Timeline 独立超过其预算时，L5 可以在普通请求低 pressure 时触发。L5 只根据 Fine refs 回读当前 Session 的 raw Transcript，不能用 Fine/Macro summary-of-summary 作为证据；Macro 逻辑上 supersede 旧 Fine，但不删除物理 Timeline。

手动 `/compact` 不依赖 Auto Gate。没有完整候选或没有实际 reduction 价值时返回成功 no-op，不创建垃圾 Timeline record。普通请求首次收到规范化 `ContextOverflowError` 时最多执行一次 `reduce → rebuild → Hard Gate → retry`；第二次仍 overflow 就停止，不学习或修改任何 limit facts。

## Session persistence 与恢复边界

Session v2 的持久文件为：

```text
transcript.jsonl
timeline.jsonl
runtime.jsonl
metadata.json
writer.lock
tool-results/
```

Application 在首次 Provider call 前、完整 Tool batch 后/下一次 call 前和 terminal tail 边界增量提交闭合 Transcript facts。single writer、append+fsync、identity reconciliation、unknown durability quarantine 与 close/reopen recovery 继续有效；无法确认副作用时不盲目重试。旧 v1 layout 明确 incompatible，不迁移、不双读写、不保留兼容入口。

`/resume` 只加载已 durable 的 Transcript、committed Timeline、Tool Result ref 和 Instruction State，并创建新的 Run/Turn；它不恢复退出时仍 active/paused 的 Turn、pending Tool、Permission、AskUser waiter、Provider request 或 coroutine 位置。这不是 Persistent Runtime Recovery。

## Tool、diagnostics 与 Eval

`ToolResultRead` 读取当前 Session 的大 Tool Result ref；`HistoryRead` 读取当前 Session 的精确 Transcript ref。二者 namespace、权限资源和 failure boundary 独立；HistoryRead 不搜索、不跨 Session、不递归 externalize。

`/status` 和 Application public diagnostics 只投影安全的 limits、count source/allowance、request accounting、Pressure、Auto/Hard、Timeline checkpoint/coverage、Compact reason/outcome、Session persistence 和 Provider usage facts，不复制 raw Transcript、summary、Tool Result、Provider native payload、secret 或异常正文。Eval 继续报告 success、tokens、tool calls、compaction、pressure 等并列指标，不新增 total score，也不把 tuning default 写成产品成功阈值。

## 当前边界

- Headless、CLI 和 TUI 共用 Application Context/Compact orchestrator；Interface 不拥有 Budget、Timeline、Session 或 Compact state。
- Timeline 只有三类产品 record；不存在持久 Compact FSM/Job/pointer、独立 compaction model、跨 Provider fallback 或无调用方 Manager/Registry/Scheduler。
- 不提供 Memory、Evidence Retrieval、Timeline physical GC、Artifact Store lifecycle、Persistent Runtime Recovery、Subagent 或 Multi-Agent。
