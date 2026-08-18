# UthCode T09-1：Context预算与Compact协议补齐任务书

## 1. 分析基线

### 1.1 唯一基线

本任务的唯一事实基线为：

```text
1887361d7a929b5aa493c8783cdc5c35f623a041
```

该提交是 `6b8dad8... + 21d6804...` 的 merge commit。重写时已从远端取回该对象，并验证当前分支 `21d6804d5a4742a56525610d7219a63ade4755c2` 与该 merge commit 的工作树完全一致；因此无需切换分支或改写 Git 历史即可锁定同一份 `src/ + tests/` 事实。

### 1.2 冻结状态核验

重写前已核对：

- T09-1 已存在 Taskbook、Spec、Tasks、Checklist 与 W01～W07 Prompt；
- `feedback/` 不存在实施记录；
- Checklist 没有已勾选项；
- 当前源码仍是 T09 的固定 258K、`CanonicalHistory + Projection`、生产 `summarizer_unavailable` 基线；
- 没有证据表明用户曾显式派发任一旧 Worker Prompt。

因此旧规划尚未进入实施冻结，本次按用户授权原地废弃并重写，不创建平行版本。

### 1.3 已读取约束与当前事实

已完整读取 `AGENTS.md`、文档路由、工作包规则、用户决策边界、能力欠账、A01/A03/A04 Context、T09 Core Design，以及旧 T09-1 全部文件；并重新核对 Context、History、Provider、Application、Session、配置、命令和相关测试。

基线定向测试命令：

```powershell
conda run --no-capture-output -n re-uthcode python -m pytest tests/test_context_compiler.py tests/test_context_compaction.py tests/test_history_contract.py tests/test_session_files.py tests/test_configuration.py tests/test_config_contract.py tests/test_application_runtime.py tests/test_application_runs.py tests/test_command_dispatcher.py tests/test_w04_session_commands.py tests/test_w05_diagnostics.py tests/test_architecture_boundaries.py -q
```

精确结果：`264 passed in 17.94s`。

---

## 2. 当前实现基线

当前真实调用链为：

```text
AgentLoop
  -> awaitable request_preparer（已实现）
  -> UthCodeApplication._start_agent_turn.prepare
  -> ApplicationContextService.compose_generation_request
  -> ContextCompiler(fixed 258K)
  -> GenerationRequest
  -> validated_provider_stream
  -> ProviderPort
```

当前关键事实：

- `ContextCompiler`、`ContextSnapshot` 与 `ContextUsage` 把 `258_000` 写成固定 invariant；它只是 operating budget，不是模型物理窗口。
- `ModelProfile` 没有 `context_window`，配置层也不解析该字段。
- `GenerationRequest` 已包含最终结构化 `system_prompt`、`messages`、`tools`、model 与 output 参数，但发送前没有统一的请求级 Auto Gate / Hard Gate。
- Core `AgentLoop` 的 `RequestPreparer` 已接受 sync 或 awaitable 返回值，不需要再改造该公共边界。
- Core overflow handler 已接受 sync 或 awaitable 返回值，并通过 `_overflow_retry_used` 保证每个 Turn 最多一次 retry；本任务只替换 Application 侧无可用 summarizer 的 handler。
- `CanonicalHistory` 与 `Projection` 共存于 Session `history.jsonl`；`runtime.jsonl` 只保存非权威诊断。
- `ContextCompactor` 已有 complete semantic unit、bounded input、output reserve、summary cap 与 single-flight，但生产组合传 `summarize=None`，所以 `/compact` 与 overflow 只能返回 `summarizer_unavailable`。
- History 主要在 terminal Turn 后提交；request-boundary closed facts 尚未增量持久化。
- active Turn 已冻结 Provider、remote model、reasoning、max output 与 tools；后续应把 `C`、Provider capability 与预算 policy 一起冻结。
- `/status` 仍展示固定 258K 与 Projection 语义。
- `ToolResultRead` 已提供 current-Session opaque ref 有界回读；不要重复实现该能力。

---

## 3. 问题定义

T09-1 要把“固定 258K + 发送后才知道 overflow + 不可生产运行的 Projection compaction”替换为一套请求发送前可验证的 Context 协议：

```text
per-model operating authority C
  + optional reliable Provider ceiling
  + final structured request counting
  + adaptive capped working headroom
  + deterministic L1-L3
  + bounded semantic L4 / L5
  + crash-safe Transcript / Timeline
  + manual compact / one-shot overflow fallback
```

上一版把“是否应该提前治理”和“是否允许发送”混成一个 Hard Gate，导致 L1-L3 只要擦回 Hard Limit 下方就可能停止，无法保持真正的工作余量；同时裸本地 estimate 可能小于 Provider 实际序列化/tokenized 输入，不能作为绝对安全事实。

---

## 4. 任务目标

完成后必须形成：

```text
assemble final candidate GenerationRequest
  -> resolve C and optional reliable ceiling => E
  -> count exact final structure with best available counter
  -> add requested output reserve + counting uncertainty
  -> Auto Gate(E - adaptive capped R)
       -> deterministic L1-L3
       -> still pressured: bounded L4 1..N
  -> independent Fine Timeline pressure may trigger L5
  -> rebuild final request
  -> Hard Gate(E)
       -> safe: send
       -> unsafe: mandatory reduction or fail closed
```

同时完成 raw durable facts 与 derived context state 分离、production tool-free L4/L5、manual compact、一次 overflow fallback，以及 diagnostics、Eval、CLI/TUI/Headless 和文档同步。

---

## 5. 能力欠账

### 5.1 本任务新增欠账

无。

### 5.2 本任务承接的既有欠账

本任务完整承接 `docs/OutstandingDebtList.md` 中三项 T09-1 欠账：

1. per-model Context Window、可靠 Provider max-input metadata、统一 Budget Resolver；
2. production tool-free Compaction use case 与 async Provider 调用；
3. small-window / large-window adaptation 与可比较 Eval。

在 T09-1 Checklist、Feedback 和源码全部完成前，这些条目仍保留在滚动清单，并按新 Task 编号标注承接关系。Persistent Runtime Recovery、Memory/Retrieval、Artifact 生命周期与 Timeline GC 不因本任务自动形成新欠账。

---

## 6. 核心产品行为

### 6.1 Effective Context Limit

```text
C = ModelProfile.context_window
E = min(C, reliable_provider_ceiling)  # ceiling 存在时
E = C                                  # ceiling 不存在时
```

- `C` 是 UthCode operating authority；
- reliable Provider ceiling 只能收紧，不能扩大 `C`；
- Provider 不提供 metadata 时不得虚构物理窗口；
- active Turn 冻结 `C` 与 capability snapshot，模型切换只影响下一 Turn。

### 6.2 统一投影量

对最终将发送的完整结构化请求计算：

```text
projected_hard_usage
  = best_available_input_count
  + requested_output_reserve
  + counting_uncertainty
```

计数优先使用 Provider 对同一最终结构的官方 preflight/token-count；不可用时使用 UthCode 对 Provider-independent DTO 的 serialization-aware deterministic estimate。Provider count 仍附加较小 uncertainty；本地 estimate 使用更保守 uncertainty。计数失败若可安全退回本地估算则降级并记录 source；无法形成保守估算时 fail closed。

### 6.3 Auto Gate 与 Hard Gate

```text
AutoGate = E - R
R = adaptive working headroom with absolute cap
```

Auto Gate 判断是否进入 proactive reduction，比较 `projected_hard_usage > AutoGate`，不是发送许可边界。

Hard Gate 判断当前请求是否允许发送，比较 `projected_hard_usage > E`。unsafe 时 Provider call count 必须为 0，除非先完成有效 reduction 并重新构建、重新计数、重新通过 Hard Gate。

每个真实 Provider model call 都必须经过 Hard Gate，包括 initial、post-tool、post-resume、manual compact 内部调用、L4、L5 与 overflow retry。

### 6.4 Working Headroom 初始内部 policy

冻结的长期行为是：小窗口自动缩小、随 E 缓慢增长、大窗口绝对封顶；不是固定百分比协议。

第一版内部默认集中为一个可替换 policy：

```text
R = clamp(ceil(E * 0.08), 2_048, 32_768)
```

- 25K 窗口约保留 2K，不套用 16K/20K 大窗口 reserve；
- 1M 窗口最多保留 32K，不因统一 90% 规则浪费约 100K；
- 数值是单点内部 default，可由 Eval 比较后替换，不是长期公共 API 或用户配置；
- 产品测试证明“adaptive + cap”的性质，Eval 不把当前默认值胜负当成产品通过阈值。

counting uncertainty 同样集中定义。实现必须区分 local estimate 与 provider count 的可信度，禁止把 allowance 分散成 magic number；产品测试要求 provider-count allowance 小于 local-estimate allowance，且二者均为正、有上限。

### 6.5 自动治理顺序

```text
final candidate
  -> Auto Gate below?
       yes -> Hard Gate -> safe send / unsafe mandatory reduction
       no  -> L1-L3 -> rebuild -> Auto Gate
                below -> Hard Gate -> safe send
                above -> L4 epoch -> checkpoint -> rebuild -> Auto + Hard
                           -> bounded B' next epoch when needed
```

关键断言：

- `E=258K`，L1-L3 将 259K 降到 257K，但 257K 仍高于 Auto Gate：继续 L4，不能仅因低于 Hard Limit 就发送；
- L1-L3 已清除 Auto pressure 且 Hard Gate safe：直接发送，不做有损 L4；
- Auto reduction 因 no-safe-epoch/no-progress/repeated-failure 达到 breaker，若最终请求仍通过 Hard Gate，则记录 `auto_pressure_unresolved` 并允许当前请求发送；Hard Gate unsafe 时必须 fail closed。这一行为来自“Auto Gate 只决定提前治理、Hard Gate 才决定发送许可”的职责分离。

### 6.6 L4 与 B′

保留 D1/D2：active Turn 使用冻结的主 Provider/model/C；idle manual compact 使用 Application 当前选择。Compact request 使用独立 prompt/budget、无 Agent Tools、不跨 Provider fallback。

L4 选择 bounded complete raw epoch，每个被覆盖 Turn 生成一个 Fine `SemanticEntry`；成功 epoch 先 append products，最后 append `ActiveCheckpoint`。每批 commit 后 rebuild + Auto/Hard re-gate；同一调用栈最多 `1..N` epoch，有 finite-attempt、no-progress、repeated-failure breaker。attempt/coverage/estimate 只在调用栈，不持久化 Compact FSM。Crash 后从 Transcript + latest valid checkpoint 推导下一 epoch。L4 一旦执行，目标是回到 retained profile，不是只压到 Auto Gate 下几个 token。

### 6.7 Manual `/compact`

- 用户可在低于 Auto Gate 时手动触发；
- 复用同一 Application Context Orchestrator；
- 不创建新 Session/Run/Turn；
- 无完整可压缩 epoch或没有实际 reduction 价值时返回 successful no-op；
- no-op 不写垃圾 Timeline 或 checkpoint；
- compact 内部 Provider call 自身必须通过 Hard Gate。

### 6.8 L5 Timeline Aging

- `Fine Timeline > F` 可独立触发 L5，不依赖 Auto/Hard pressure；
- 只选择旧 complete Compact Epoch，并按 refs 重新读取 raw Transcript evidence；
- 不做 summary-of-summary；
- 成功结果是 bounded `EpochMacroSummary`，随后最后提交 checkpoint；
- 旧 Fine records 物理保留，logical view 被 coverage supersede；
- 当前模型无法安全读取任何 epoch 时返回 `no_safe_epoch`，不静默切模型。

### 6.9 Overflow fallback

- Provider overflow 是最后异常保护，不是窗口发现；
- 首次 overflow 且尚无 durable assistant/tool side effect 时，执行一次 forced reduction、rebuild、重新计数与 Hard Gate，再 retry；
- 第二次 overflow 终止；
- 不修改 `C`，不通过循环重试探测窗口；
- Core 已有 one-retry guard，Application 只需提供新的 async forced-reduction handler。

---

## 7. 架构归属

| 能力 | 归属 | 权威状态 | 约束 |
| --- | --- | --- | --- |
| Transcript/Timeline value contract | Core | 不可变 Provider-independent values | 无 fs/network/SDK |
| `ModelProfile.context_window` | Application configuration | Effective config / Turn snapshot | 项目配置不得改 Provider/端点/凭据 |
| Model limits / input count capability | Core-owned optional contract + Integration implementation | Provider adapter/cache | SDK 类型止于 Integration |
| Headroom/uncertainty/budget policy | Core纯值与 Application resolver | 单次请求 snapshot | 单点 default，无新配置系统 |
| ContextCompiler | Core | 无可变业务状态 | 唯一 model-view builder |
| Auto/Hard Gate 与 L1-L5 orchestration | Application Context | 单次 prepare/reduction 调用栈 | AgentLoop 不拥有 Context state |
| Transcript/Timeline files | Integration Session store | Session single writer | checkpoint-last、fsync、reconcile、quarantine |
| closed-fact commit cadence | Application Run/Session orchestration | process-local durable cursor | 不成为 Runtime checkpoint |
| HistoryRead | Integration Tool，由 Application 绑定 active Session | current Session | exact ref、bounded、read-only |
| `/compact`、`/status` | Application Command use case | 无独立 Context state | Interface 只适配结果 |

新增公共类型必须有直接调用方。禁止引入 `ContextManager`、`CompactManager`、`CompactionJob`、`TimelineRegistry`、后台 worker 或通用 FSM。

---

## 8. 外部参考结论

| 来源 | 当前一手事实 | 对 UthCode 的影响 |
| --- | --- | --- |
| [Pi Compaction](https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/docs/compaction.md) | auto compaction 使用 `contextTokens > contextWindow - reserveTokens`；reserve 是为模型响应留空间的绝对 token 数 | 借鉴绝对 headroom 的形状，不照搬 16,384 默认值 |
| [OpenCode Session Spec](https://github.com/anomalyco/opencode/blob/dev/specs/v2/session.md) | 每个 Provider turn 前估算完整 model-visible request，并从 context window 中减去绝对 reserved headroom；overflow 后最多一次 compaction retry | 支持 pre-send accounting、绝对 reserve、一次 fallback；不复制其 durable attempt record |
| [Codex model metadata](https://github.com/openai/codex/blob/main/codex-rs/protocol/src/openai_models.rs) 与 [context window status](https://github.com/openai/codex/blob/main/codex-rs/core/src/session/context_window.rs) | context window、effective window、auto-compact limit 与 full-window reached 是分层概念；full window 是独立 hard cap | 借鉴 proactive boundary 与 hard boundary 分离，不照搬默认 90% |
| [Anthropic Token Counting](https://platform.claude.com/docs/en/build-with-claude/token-counting) | count endpoint 接受结构化 messages/system/tools，但官方明确其结果仍是 estimate，实际 message input 可能小幅不同 | Provider count 提高可信度但不取消 uncertainty allowance |
| [Anthropic Models API](https://platform.claude.com/docs/en/api/models/list) | 当前正式 API 返回 `max_input_tokens`、`max_tokens` 与 capabilities | Anthropic adapter 可提供可靠 ceiling；返回前转换为 UthCode-owned DTO |

---

## 9. 目标目录树

```text
src/uthcode/
├─ core/
│  ├─ context.py                         [修改]
│  ├─ history.py                         [修改]
│  ├─ prompt.py                          [修改]
│  ├─ provider.py                        [修改]
│  └─ __init__.py                        [修改]
├─ application/
│  ├─ context.py                         [修改]
│  ├─ history.py                         [修改]
│  ├─ configuration.py                   [修改]
│  ├─ generation.py                      [修改]
│  ├─ sessions.py                        [修改]
│  ├─ tools.py                           [修改]
│  ├─ bootstrap.py                       [修改]
│  ├─ __init__.py                        [修改]
│  └─ commands/
│     ├─ builtins.py                     [修改]
│     ├─ dispatcher.py                   [修改]
│     └─ models.py                       [仅 awaitable command typing 真实需要时修改]
├─ integrations/
│  ├─ config/
│  │  ├─ loader.py                       [修改]
│  │  └─ template.py                     [修改]
│  ├─ session_files.py                   [修改]
│  ├─ providers/anthropic.py             [修改]
│  └─ tools/
│     ├─ factory.py                      [修改]
│     └─ history_read.py                 [新增]
eval/metrics.py                           [修改]
tests/
├─ test_configuration.py                 [修改]
├─ test_config_contract.py               [修改]
├─ test_provider_model_limits.py          [新增]
├─ test_context_budget_gate.py           [新增]
├─ test_history_contract.py              [修改]
├─ test_timeline_contract.py             [新增]
├─ test_session_files.py                 [修改]
├─ test_context_compiler.py              [修改]
├─ test_context_compaction.py            [修改]
├─ test_history_read_tool.py             [新增]
├─ test_application_runtime.py           [修改]
├─ test_application_runs.py              [修改]
├─ test_application_tools.py             [修改]
├─ test_tool_result_persistence.py       [修改]
├─ test_command_dispatcher.py            [修改]
├─ test_w04_session_commands.py          [修改]
├─ test_w05_diagnostics.py               [修改]
├─ test_w06_integration_delivery.py      [修改]
├─ test_t09_1_context_protocol_e2e.py    [新增]
├─ test_tui.py                           [修改]
└─ test_architecture_boundaries.py       [修改]
docs/
├─ Context-Index.md                      [实现验收时修改]
├─ OutstandingDebtList.md                [实现验收时修改]
├─ core-design/T09-context-engineering.md [修改]
├─ context/A01-AgentRuntime/AgentRuntime-Context.md [修改]
├─ context/A03-State/State-Context.md     [修改]
├─ context/A04-Orchestration/Orchestration-Context.md [修改]
└─ user-manual/
   ├─ configuration.md                   [修改]
   └─ commands.md                        [修改]
```

`src/uthcode/core/agent.py` 不在目标树中：awaitable request preparation 与 one-retry overflow guard 已存在。只有真实实现发现该既有合同存在局部缺陷，且不改变公共语义时，才允许最小修复并在 Feedback 说明。

OpenAI Responses / OpenAI-compatible adapter 默认不改：没有可靠通用 metadata 时继续使用 configured `C`，不得为统一外观伪造 ceiling/count capability。

---

## 10. 文件级任务清单

| 文件 | 操作与职责 | 对应 Task | 验收证据 |
| --- | --- | --- | --- |
| `core/context.py` | 动态 budget、headroom、uncertainty、dual-gate纯值、Compiler与 L1-L5 contracts；删除固定 258K invariant | 1、3、4、5 | budget/compiler/compaction tests |
| `core/history.py` | `Transcript`、stable ref、三类 Timeline product与 logical checkpoint validation；删除 Projection authority | 2 | history/timeline tests |
| `core/prompt.py` | Transcript/Timeline summary 保持 Conversation/History authority | 2、3 | compiler tests |
| `core/provider.py` | SDK-neutral `ModelLimits`、count result/source/capability contract | 1 | provider limits + architecture |
| `core/__init__.py` | 新 exports，删除失效固定预算/Projection export | 1、2、9 | import/cleanup |
| `application/__init__.py` | 新 Application DTO/export 跟随，删除失效export | 1、2、9 | import/cleanup |
| `application/configuration.py` | `ModelProfile.context_window` 正整数 operating authority | 1 | configuration tests |
| `integrations/config/loader.py`、`template.py` | TOML `context_window` validation/merge与模板 | 1 | config contract |
| `integrations/providers/anthropic.py` | Models ceiling 与 Messages count-token 转 UthCode DTO | 1 | fake SDK tests |
| `application/context.py` | final request、count、Auto/Hard Gate、L1-L5、B′、manual/forced reduction总编排 | 1、3、4、5、6 | gate/compaction/E2E |
| `application/history.py` | closed Message到raw Transcript entries | 2、6 | history/run tests |
| `application/sessions.py` | Transcript/Timeline snapshot、append outcomes、active Session证据读取 | 2、4、5、6 | session/E2E |
| `integrations/session_files.py` | Session v2、checkpoint-last、recovery/quarantine | 2 | session files |
| `application/generation.py` | Turn budget/capability snapshot、async prepare、incremental persistence、manual/overflow/status | 3、4、6 | runtime/runs/E2E |
| `application/tools.py`、`bootstrap.py`、`integrations/tools/factory.py` | 绑定 current-Session HistoryRead | 5 | tool tests |
| `integrations/tools/history_read.py` | exact opaque Transcript ref有界只读实现 | 5 | security tests |
| `application/commands/builtins.py`、`dispatcher.py`、按真实typing需要的`models.py` | awaitable `/compact` 与 dynamic `/status` | 6 | command/TUI tests |
| `eval/metrics.py` | 消费安全 dual-gate/Timeline diagnostics | 6 | diagnostics fixtures |
| `tests/test_configuration.py`、`test_config_contract.py`、`test_provider_model_limits.py`、`test_context_budget_gate.py` | 模型配置、limits/count与dual-gate性质 | 1、3、4 | pytest |
| `tests/test_history_contract.py`、`test_timeline_contract.py`、`test_session_files.py` | Transcript/Timeline/Session v2与crash recovery | 2、5、6 | pytest |
| `tests/test_context_compiler.py`、`test_context_compaction.py` | logical view、L1-L5、B′与breaker | 3～5 | pytest |
| `tests/test_history_read_tool.py`、`test_application_tools.py`、`test_tool_result_persistence.py` | HistoryRead与Tool Result回归 | 3、5 | pytest |
| `tests/test_application_runtime.py`、`test_application_runs.py` | Turn snapshot、request-boundary persistence与全部call Gate | 3、4、6～8 | pytest |
| `tests/test_command_dispatcher.py`、`test_w04_session_commands.py`、`test_tui.py` | manual `/compact`、`/status`与Interface adapter | 6、8 | pytest |
| `tests/test_w05_diagnostics.py`、`test_w06_integration_delivery.py` | safe diagnostics、Eval与Headless交付 | 6～8 | pytest |
| `tests/test_t09_1_context_protocol_e2e.py`、`test_architecture_boundaries.py` | 真实E2E和模块依赖边界 | 4、6～9 | pytest |
| `docs/Context-Index.md`、`docs/OutstandingDebtList.md` | 实现验收时同步状态与已承接欠账 | 6、9 | current-status/debt审计 |
| `docs/core-design/T09-context-engineering.md`、A01/A03/A04 Context | 同步实现后的长期设计与当前事实 | 6、9 | UTF-8/事实检查 |
| `docs/user-manual/configuration.md`、`docs/user-manual/commands.md` | 说明`context_window`、`/compact`、`/status`与旧Session边界 | 6 | UTF-8/用户行为检查 |

---

## 11. 关键数据结构与状态

### 11.1 Budget snapshot

```text
ContextBudgetSnapshot
  configured_context_window: C
  provider_ceiling?: int
  effective_context_limit: E
  requested_output_reserve: int
  input_count: int
  count_source: provider | local_estimate
  counting_uncertainty: int
  projected_hard_usage: int
  working_headroom: R
  auto_gate_limit: E - R
  hard_gate_limit: E
  retained_profile: A/F/U + bounded L4 input/output limits
```

该值属于单次 Turn/request snapshot，不持久化为新的 Runtime authority。

### 11.2 Gate result

```text
ContextGateResult
  auto_pressure: bool
  hard_safe: bool
  reason
  count_source
  before/after projected usage
  reduction counters
  diagnostic status
```

不得携带 request正文、summary、Tool result或秘密。

### 11.3 Transcript / Timeline

```text
TranscriptEntry
  session_id + sequence + turn_id + kind + payload + semantic_unit_id

TimelineRecord = SemanticEntry | EpochMacroSummary | ActiveCheckpoint
```

Compact Epoch 由相邻有效 checkpoint 之间的 records 推导，不增加第四种产品 record。

### 11.4 B′ 局部状态

`attempt_count`、`last_coverage`、`last_projected_usage`、`last_candidate_identity` 与 `cancellation` 只存在于一次 Application 调用栈；不写 RunState、Transcript、Timeline、runtime log。

---

## 12. 依赖与数据流

### 12.1 普通请求

```text
AgentLoop awaits request_preparer
  -> Application persists newly closed Transcript facts
  -> ContextCompiler builds final candidate
  -> Provider counter or local estimator counts same structure
  -> Auto Gate
       -> L1-L3 -> rebuild/recount
       -> L4 1..N -> checkpoint/rebuild/recount
  -> independent L5 aging when Fine Timeline > F
  -> Hard Gate
  -> ProviderPort.stream
```

### 12.2 L4 / L5

L4：bounded uncovered raw epoch → tool-free request → Hard Gate → same model/provider → validate Fine entries → append checkpoint last → rebuild/re-gate。

L5：Fine Timeline pressure → old complete epoch → raw Transcript refs → tool-free Hard-Gated request → macro summary → checkpoint last → logical supersession。

### 12.3 closed facts

```text
before initial Provider call: current user fact
before post-tool Provider call: assistant ToolCall + matched ToolResult group
terminal boundary: final assistant tail
```

streaming fragment、unmatched ToolCall、Pause continuation与Provider coroutine位置不持久化。

---

## 13. 对现有能力的影响

| 现有能力 | 处理 |
| --- | --- |
| AgentLoop awaitable preparer | 直接复用，不重复改造 |
| AgentLoop one-retry overflow guard | 直接复用，替换 Application handler |
| fixed 258K Compiler | 替换为 request-specific budget snapshot |
| CanonicalHistory + Projection | 硬切为 Transcript + Timeline，不兼容旧 Session |
| Session writer safety | 保留 safety semantics，改文件布局与 product append |
| Tool Result externalization / ToolResultRead | 作为 L1并保持独立 |
| `/compact` | 改为 async use case + no-op |
| `/status` | 展示 C/E/Auto/Hard/headroom/count source/L1-L5/checkpoint安全投影 |
| `/resume` | 恢复 durable facts后创建 fresh Run，不恢复 Runtime continuation |
| Eval | 比较效果与安全 diagnostics，不固定 tuning 胜负阈值 |

---

## 14. 第三方依赖

不新增第三方依赖。Anthropic limits/count复用现有SDK；不新增 tokenizer、model catalog package、数据库、scheduler或persistence framework。没有官方 count时使用保守deterministic estimator；外部真实Provider网络调用不作为CI必过条件。

---

## 15. 实施任务拆分

### Task 1：模型窗口、计数能力与双 Gate 预算契约

建立 `C/E`、output reserve、count source、uncertainty、adaptive capped `R`、Auto/Hard Gate纯值与 Provider limits/count capability；接入配置与 Anthropic adapter。不得触碰 Timeline 或 model compaction。

### Task 2：Transcript / Timeline 与 Session v2 持久事实

完成 History/Projection 到 Transcript/Timeline 的硬切，建立三 record、checkpoint-last transaction、fresh Session布局与旧 Session deterministic incompatibility。

### Task 3：最终请求组装、Auto/Hard Gate 与确定性 L1-L3

让 Application 在已有 awaitable request-preparer 内组装最终 request、计数、执行 dual gate；ContextCompiler 从 Transcript/Timeline 构造 logical view，完成 L1-L3 和 rebuild/recount。Hard unsafe 时 Provider call count为零。

### Task 4：L4 proactive semantic compaction 与 B′

接通 tool-free async L4、bounded raw epoch、checkpoint commit、retained target、每批 re-gate 与有限 `1..N` catch-up；实现 Auto pressure未清除与 Hard unsafe的不同终止语义。

### Task 5：L5独立老化与 HistoryRead

让 Fine Timeline pressure独立触发 raw-evidence L5，生成 macro coverage；新增 current-Session exact-ref HistoryRead。

### Task 6：运行生命周期、手动 Compact、Overflow、Diagnostics 与文档

接入 request-boundary closed Transcript persistence、manual `/compact`、single-flight、一次 overflow retry、dynamic status、安全 diagnostics、Eval和包级文档同步。

### Task 7：[接入主流程] 单一 Context Request Orchestration

核对 direct generation、initial/post-tool/post-resume、L4、L5、manual、overflow retry都经过同一 Application编排与每次 Hard Gate；删除被替代入口。

### Task 8：[端到端验证] Dual Gate / Compact / Recovery

从正式 Application/Session/Run/Command adapter入口验证正常、失败、crash、resume、model switch与 Headless/TUI适配。

### Task 9：[遗留负担清理] 动态预算与单 Timeline 路径收口

删除固定 258K、Projection authority、Session v1新写入、空 summarizer生产路径、旧 overflow path与无调用方抽象；确认无兼容层、重复责任或未来占位。

---

## 16. 测试矩阵

| 场景 | 必须证明 |
| --- | --- |
| Auto vs Hard | 同一request可处于Auto pressure但仍Hard safe；判断和诊断不同 |
| 25K | headroom收缩，不使用大窗口16K/20K reserve |
| 1M | headroom绝对cap，不因90%浪费约100K |
| L1-L3 still pressured | 即使低于E仍进入L4 |
| L1-L3 clears pressure | Hard safe后直接发送，不执行L4 |
| Hard unsafe | Provider call count = 0 |
| count mismatch | 裸local estimate不作为硬事实；provider count仍有allowance |
| every call gated | initial/post-tool/post-resume/manual/L4/L5/retry均有Hard Gate evidence |
| L4 B′ | 1..N epochs、每批checkpoint/rebuild/re-gate、finite breaker |
| unresolved Auto pressure | breaker后Hard safe发送并诊断；Hard unsafe拒绝 |
| manual | 低于Auto Gate仍可执行；无候选no-op且无Timeline垃圾 |
| L5 | Fine Timeline pressure单独触发，raw Transcript provenance |
| overflow | 最多一次forced reduction+retry；第二次终止且C不变 |
| crash | checkpoint前尾部无效；checkpoint后重算下一epoch |
| old Session | incompatible，无migration/dual path |
| HistoryRead | current Session、opaque exact ref、bounded、cross-session/path denial |
| diagnostics/architecture | 无正文/秘密泄漏；模块依赖边界保持 |

---

## 17. 删除与清理

必须删除或替代固定 `UTHCODE_CONTEXT_BUDGET_TOKENS` invariant、固定 258K校验、Projection authority、`history.jsonl` 新写入、生产 `summarize=None`、旧 unavailable overflow handler、旧 status wording及失效 exports/tests/docs。

保留有真实职责的 strict sequence、complete semantic unit、deterministic estimator、single-flight、writer lock/fsync/reconciliation/quarantine、Tool Result externalization与non-authoritative runtime diagnostics。

---

## 18. 验收标准

1. 每个可运行model有正整数`C`，`E`只被可靠ceiling收紧。
2. Auto Gate与Hard Gate有不同结果/诊断，且没有统一90%规则。
3. headroom small-window收缩、large-window绝对封顶。
4. 每个真实Provider call基于最终结构化request通过Hard Gate。
5. output reserve与count uncertainty进入hard projection。
6. provider count是高可信estimate而非绝对事实。
7. L1-L3后仍在Auto pressure时继续L4；已清除时不做L4。
8. L4回到retained target并支持有限B′；无持久Compact FSM。
9. Auto治理无法清除但Hard safe时发送并诊断；Hard unsafe时零Provider call。
10. Transcript/Timeline分离，Timeline三record，checkpoint-last恢复正确。
11. L5可由Fine Timeline pressure独立触发并重读raw evidence。
12. manual `/compact`不依赖Auto Gate；无候选successful no-op。
13. overflow最多一次forced reduction/retry，不学习C。
14. HistoryRead不能跨Session或退化成路径/搜索。
15. request-boundary只持久化closed facts，不实现Runtime checkpoint。
16. active Turn冻结Provider/model/C/capability，模型切换只影响下一Turn。
17. CLI/TUI/Headless共用Application，架构边界通过。
18. diagnostics/Eval/docs与实际实现一致且不泄露正文/秘密。
19. 定向、E2E、架构和全量测试记录精确结果。
20. 失效实现已删除，无兼容层、后台job、未来占位或重复职责。

---

## 19. 编码停止条件

出现以下情况停止相关实施并写入Feedback：真实源码关键前提冲突且需改变产品/公共边界/范围；D1/D2/D3冲突；必须新增第四种Timeline产品record、持久Compact FSM或独立compaction model；必须扩大到Persistent Runtime Recovery、Memory、Artifact/Timeline GC；Provider官方API变化会改变公共语义；必须让SDK越过Integration或Interface拥有Context；必须为旧Session建立compatibility；出现新的安全边界或无法形成安全计数fallback；修改范围明显超出目标树且不是机械跟随。

普通编译错误、fixture、私有helper、局部类型与测试失败由Worker在既定范围内解决。

---

## 20. 明确不做

```text
Memory / embedding / vector or semantic retrieval
cross-Session History Retrieval
Persistent Run/Turn checkpoint
Pending Tool/Permission/AskUser/Provider coroutine restart recovery
Artifact Store lifecycle / GC
Timeline physical GC / rotation / self-compaction
background Context Agent / Compaction Job / Scheduler / FSM
independent compaction model / cross-Provider fallback
Subagent / Multi-Agent
full Provider model catalog UI
Provider-specific server context editing as Core semantics
old Session migration / dual read / dual write / compatibility
new user configuration subsystem for headroom tuning
unrelated Permission/Plan/Todo/Hook/TUI renderer refactor
```
