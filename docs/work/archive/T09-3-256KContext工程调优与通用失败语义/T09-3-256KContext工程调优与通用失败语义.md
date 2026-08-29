# UthCode T09-3：256K Context 工程调优与通用失败语义任务书

> 本任务书是 T09-3 的冻结上游需求与实施 authority。后续 Task Splitter 只能将本文向下拆分为 Spec / Tasks / Checklist / Worker Prompt，不得重新设计、删除、弱化或反向覆盖本文已经冻结的产品与架构语义。

---

## 1. 分析基线

### 1.1 目标仓库与唯一代码基线

```text
repository: https://github.com/undertaker33/Re-UthCode
commit:     958c699fa1cd58c49154928655a3e655e9388291
commit msg: refactor: 完成 T09-2 工程收敛与 Session v3 硬切
```

所有文件规划、调用链、产品行为与验收均以该 Commit 的真实 `src/ + tests/` 为代码事实基线。

编码代理开始实施前必须重新执行：

```bash
git rev-parse HEAD
```

如 HEAD 已变化，必须先确认变化是否仅为用户明确允许的后续文档/拆分提交；若生产代码基线发生实质变化，应重新核对本任务受影响的文件事实，不得机械按旧行号实施。

### 1.2 已读取并核对的项目约束

```text
AGENTS.md
docs/README.md
docs/Context-Index.md
docs/rules/WorkPackageRules.md
docs/rules/UserDecisionBoundary.md
docs/OutstandingDebtList.md
```

与本任务直接相关的冻结架构边界：

```text
interfaces -> application -> core
                |
                +-> integrations
```

- Core 只拥有 Provider-independent 的稳定产品语义，不依赖文件系统、网络、Provider SDK 或具体 Interface。
- Application 是正式组合与编排层，当前唯一正式运行链路为 `create_application -> create_run -> start_turn -> AgentLoop`。
- Integration 负责 Provider SDK / wire-format / Provider-specific 能力适配；第三方类型不得穿透到 Core。
- Interface 只负责输入与展示，不得拥有 Context、安全 Gate、失败分类等核心语义。
- 不重新引入 T09-2 已删除的无真实调用方 Manager / Registry / Protocol / facade / Hook 框架 / FSM。
- Tool Definition 继续由 Tool System 维护唯一权威定义；不得为了 Prefix Cache 在 Prompt 中复制一份 Tool Schema。

### 1.3 已读取并核对的前置工作包

```text
docs/work/T09-Prompt与ContextEngineering/
docs/work/T09-1-Context预算与Compact协议补齐/
docs/work/T09-2-工程收敛与提前抽象清理/
docs/work/B01-私有测试集v0/
```

重点恢复并保持：

- T09 已建立 Prompt Asset / Core Runtime Contract / typed Context Source / stable prefix fingerprint / instruction epoch / Provider-native request mapping / Session 与 Context Compiler 基础链路。
- T09-1 已建立 Context Budget、Pressure Gate、Hard Gate、Tool Result 外置、Transcript / Timeline、L4 Compact、L5 Timeline aging、manual compact、overflow recovery、HistoryRead 与 Context diagnostics。
- T09-1 已冻结：L4 一旦真正执行，必须朝 meaningful retained target / Low Water 收敛，不能只刚刚越过 Auto Gate。
- T09-2 已删除无真实调用方的提前抽象，并硬切 Session v3；T09-3 不得以“Context 工程化”为名恢复被删除的通用框架。
- B01 已提供可复用的 Eval runner、六维 metrics、compare、fingerprint 与离线 Fake 路径；T09-3 只扩展现有 Eval，不建设第二套 benchmark 系统。

### 1.4 已核对的关键源码

```text
src/uthcode/core/context.py
src/uthcode/core/compaction.py
src/uthcode/core/history.py
src/uthcode/core/prompt.py
src/uthcode/core/provider.py
src/uthcode/core/agent.py
src/uthcode/core/agent_events.py

src/uthcode/application/context.py
src/uthcode/application/generation.py
src/uthcode/application/configuration.py
src/uthcode/application/instructions.py
src/uthcode/application/provider_usage.py
src/uthcode/application/runs.py
src/uthcode/application/sessions.py

src/uthcode/integrations/providers/anthropic.py
src/uthcode/integrations/providers/openai_responses.py
src/uthcode/integrations/providers/openai_compat.py
src/uthcode/integrations/providers/config.py
```

### 1.5 已核对的关键测试

```text
tests/test_context_budget_gate.py
tests/test_context_compaction.py
tests/test_t09_1_context_protocol_e2e.py
tests/test_agent_events.py
tests/test_agent_loop.py
tests/test_application_runs.py
tests/test_anthropic_integration.py
tests/test_openai_responses_integration.py
tests/test_openai_compat_integration.py
tests/eval/
```

Task Splitter 可在不改变产品语义的前提下，将新增测试放入最匹配的现有测试文件，或在 `tests/` / `tests/eval/` 下创建职责单一的新文件；不得仅为“测试分层漂亮”新增生产抽象。

### 1.6 外部资料与工程参考

本任务实施时应以届时官方文档为准，当前探索使用：

- OpenAI Responses API / Prompt Caching：稳定前缀、`prompt_cache_key`、可用 cache options / cache metrics。
- Anthropic Prompt Caching：`cache_control`、自动/显式 breakpoint、cache read/create usage。
- Codex CLI 当前 Context Window / Auto Compaction 实现：物理 Hard Window 与 Auto Compaction threshold 分离，可作为 Operating Profile 分层参考。

外部 Agent 只是工程参考，不是 UthCode 产品 authority。

---

## 2. 当前实现基线

### 2.1 Context limit 仍只有 configured / Provider 两种 authority

当前 `ContextBudget` 要求：

```text
configured_input_limit
or
provider_max_input
```

至少一项存在；二者都不存在时抛出 `ContextBudgetError`。

当前还没有：

```text
UthCode default operating input limit = 256_000
```

也没有完整的：

```text
configured / provider / default
```

来源 provenance 投影。

### 2.2 当前预算公式仍属于历史默认，不是 256K 调优结果

当前已有：

```text
working_headroom
auto_gate_limit
fine_timeline_budget
retained_target
compaction_input_budget
compaction_output_reserve
safety allowance
```

但部分参数仍按通用比例 / clamp 历史公式产生，并未以 Coding Agent 256K 长任务 Eval 证明其工程效果。

当前 `ContextBudget` 还保留：

```text
active_evidence_budget
uncompressed_tail_budget
retained_hard_cap
```

当前生产 caller audit 未发现它们驱动实际行为；`fine_timeline_budget` 有 L5 消费者，`retained_target` 则有冻结产品语义但尚未真正接入 L4 stop condition。

### 2.3 Low Water 产品语义存在已确认的实施漂移

当前 Application 在每个 L4 epoch 后重建候选请求，但继续条件仍为：

```text
auto_pressure or not hard_safe
```

因此可能出现：

```text
High Water 触发 L4
    ↓
一个 epoch 后刚低于 High Water
    ↓
停止
```

而不是 T09-1 已冻结的：

```text
High Water 触发 L4
    ↓
持续 catch-up
    ↓
达到 Low Water / retained target
或 finite breaker / no-progress / failure / cancel
```

这是 T09-1 实施漂移，不是新的产品决策。

### 2.4 L4 / L5 / manual / overflow 已有生产能力

当前已有：

- Auto L4：Pressure / Hard unsafe 时有界 compact。
- L5：按 `fine_timeline_budget` 做独立 Timeline aging。
- Manual Compact：用户主动入口。
- Provider overflow recovery：Core one-retry guard + Application forced L4 recovery。
- 每次 compact 后可重新 compose / count request。

T09-3 只收敛真实重复的 L4 orchestration，不新增 CompactManager、CompactionJob、Scheduler、后台 worker 或 durable FSM。

### 2.5 Prefix 稳定性已经可观察，但 Provider cache hint 尚未主动工程化

当前已有：

```text
instruction_epoch
stable_prefix_fingerprint
prefix_changed
prefix_change_reason
tool_schema_fingerprint
cache_read_tokens
cache_write_tokens
Provider usage provenance
```

但 Provider Integration 当前还没有形成系统性的：

```text
稳定 prefix
+ Provider-specific cache hint
+ cache hit/write measurement
+ expected/unexpected invalidation Eval
```

OpenAI Responses 与 Anthropic 仍主要依赖 Provider 默认行为。

### 2.6 通用失败链在公共边界丢失了具体原因

当前 `AgentEvent` 已明确是 Provider-independent、display-safe、Headless 可序列化的公共事件边界。

但：

```text
TurnFailed
└── termination_reason
```

只有粗粒度终止原因；`TurnResult` 也只有 `termination_reason`。

Provider Integration 已经能区分部分认证、限流、网络、timeout、非法响应等 SDK 事实，但在 Core / Application 路径中会被折叠：

- network / rate-limit 主要进入现有 Pause/Retry 语义；
- invalid response / generic provider error 进入粗粒度 terminal reason；
- request preparation / Context resolver 的普通异常可能落为 `INTERNAL_ERROR`；
- Interface 因此无法只依赖稳定公共事实形成准确、统一、用户可理解的一句话。

---

## 3. 问题定义

当前 Context Engine 已具备较完整的 Context Compiler / Working Set / Gate / Compaction / Timeline / Tool Result 外置骨架，但还不能称为“针对 256K Operating Window 完成工程调优”，主要因为：

1. 256K 还不是缺省可运行的统一 Operating Profile；缺少 default limit source 与 provenance。
2. 当前预算参数不是通过 256K Coding Agent workload 调优得到，部分 profile 字段没有生产消费者。
3. 已冻结的 High Water -> Low Water 迟滞行为在生产 L4 中没有真正落地。
4. Prefix 稳定性已有 diagnostics，但 Provider prompt cache 仍未成为主动、可测、可回归的工程行为。
5. Context / Provider 失败在公共事件层过早折叠，TUI / CLI / Headless 无法共享一套稳定而具体的失败原因。
6. 已有 Eval 尚未形成专门针对 256K profile、post-compact working distance、cache reuse 与 failure projection 的比较证据。

T09-3 的目标不是扩张 Context 架构，而是让已经存在的 Context Engine **收敛、校正、调优并可测**。

---

## 4. 冻结决策清单

### D-T09-3-01：256K 是 UthCode 默认工程 Operating Window

```text
default operating window = 256_000 input tokens
```

它不是对模型物理上下文窗口的声明。

- 已知真实安全上限小于 256K：尊重更小上限。
- 模型真实上限大于 256K：UthCode 默认仍以 256K 作为本阶段工程 tuning target。
- 未来若需要新的 Operating Profile，另立任务，不在本任务建设多 Profile Registry。

### D-T09-3-02：Context Limit 有三类来源

支持且仅支持本任务所需的三类来源：

```text
1. user configured context_window
2. reliable Provider input limit / ceiling
3. UthCode default 256_000
```

解析原则：

- configured 与 reliable Provider 同时存在时，Provider ceiling 可以收紧安全上限，不得放大 configured 值。
- 二者都不存在时才由 default 256K 提供可运行 authority。
- 不把 default 伪装成 Provider metadata。
- diagnostics / status / Headless 必须能说明本次来源属于 configured / provider / default，以及哪些来源实际参与了收紧。
- Active Turn 冻结本 Turn 已解析的 model / provider limits / effective operating limit / provenance；model switch 与新 Turn 重新解析。

### D-T09-3-03：Hard Gate 保持分维 safety 语义

不得恢复“input + output 无条件都塞进同一窗口”的旧模型。

仅按真实已知维度判断：

```text
input + input allowance <= effective input limit
requested output <= provider max output      # 已知时
input + allowance + output <= combined limit # Provider 明确给 combined 时
```

未知维度保持 unknown，不伪造 combined limit。

### D-T09-3-04：不恢复 bundled model metadata

禁止：

```text
package 内 model-name -> context-window 表
型号 substring 猜窗口
基于模型名称的隐式 tuning table
```

限制只来自显式配置、可靠 Provider metadata、default 256K。

### D-T09-3-05：L4 必须形成 High Water -> Low Water 迟滞

L4 的**触发阈值**与**触发后的停止目标**必须分离。

一旦 Auto L4 真正启动：

```text
继续 compact
直到 retained target / Low Water 已达到
或 finite breaker
或 no safe epoch / no progress / failure / cancel
```

“刚好低于 Auto Gate”不是合法完成条件。

Low Water 不在 L4 尚未触发时主动制造 compact。

### D-T09-3-06：具体 Operating Profile 数值属于 Eval 调优参数

允许通过 Eval 调整：

```text
High Water / working headroom
Low Water / retained target
Fine Timeline budget
L4 input/output budget
L4 max epochs
count allowance
Tool Result preview / read-page 配比
```

不得将某次实验候选永久固化为 public API。

Task Splitter 必须保留至少三组有明显差异的候选用于粗筛，并可围绕优胜区域二次细调。候选可参考：

```text
High Water: 192K / 208K / 224K 等
Low Water:   64K /  96K / 128K 等
```

也允许加入约 `220K / 150K` 的工程候选进行比较，但不能在没有 Eval 证据的情况下把它写成最终永久参数。

### D-T09-3-07：通用失败语义采用最小混合方案 C

冻结为：

```text
Integration
    ↓ Provider/SDK 事实映射
Core
    ↓ stable provider-independent machine FailureReason
Application
    ↓ one-line user-facing message projection
Interface / Headless
```

具体职责：

- Core：在现有 display-safe public failure boundary 中保存小而稳定的机器可读失败分类；`TerminationReason` 继续表示“Turn 为什么终止”，`FailureReason` 表示“失败的具体类型”。
- Application：唯一拥有用户自然语言错误文案映射；同一稳定 reason 在 TUI、CLI、Headless 形成一致语义。
- Interface：只展示，不重新分类 Provider / Context 错误。
- Integration：只映射自己能可靠判断的 SDK / HTTP / Provider 事实；不得猜测“模型不可用”等无法可靠区分的细分类。
- 内部 diagnostics 可更细，但不得把 traceback、SDK exception、secret、未经脱敏的 Provider body 塞入 public event/message。
- 保持现有 Pause / Retry 行为；不能为了显示 timeout / network 文案把本来可恢复的 pause 强行改成 terminal failure。
- 不建设 ErrorManager、ErrorRegistry、异常平台或完整 i18n 系统。

FailureReason 的最终枚举必须小而证据驱动；至少应能够准确表达当前真实调用链中可可靠辨识的：

```text
authentication
provider_request/configuration（仅能可靠区分时）
invalid_provider_response
context_unresolvable
persistence_unavailable（如当前 Application 失败链有稳定事实）
internal
```

网络、限流、timeout 如继续属于 Pause/Retry，则优先通过现有 PauseReason 的稳定扩展/投影表达；只有在当前公开终止链确实需要且 Integration 能可靠区分时才增加 terminal FailureReason。

### D-T09-3-08：任务书是后续拆分 authority

本文经用户确认后：

```text
Decision -> Spec -> Task -> Worker Prompt -> Checklist
```

必须形成可追踪覆盖。

Splitter 不得：

- 删除任一冻结 Decision；
- 把 MUST 改成 SHOULD；
- 把 Low Water 弱化为“产生 headroom”；
- 把 failure semantic 下放成 TUI 私有映射；
- 恢复 bundled model catalog；
- 恢复 T09-2 已删除的提前抽象。

---

## 5. 任务目标

本任务必须完成以下七项闭环。

### G1. 建立 256K default limit resolver

形成：

```text
Configured limit ───────┐
Reliable Provider limit ├──> resolved safe input limit
Default 256K ───────────┘
                               ↓
                    effective operating limit
```

要求：

- 小窗口模型永不因 default 256K 被放大；
- 大窗口模型默认仍工作在 256K Operating Profile；
- configured/provider/default provenance 可观察；
- model switch / 新 Turn 重新解析；Active Turn 不被中途 limit 变化破坏。

### G2. 收敛 ContextBudget 并建立少量真实 256K profile 参数

逐项 caller audit：

```text
active_evidence_budget
fine_timeline_budget
uncompressed_tail_budget
retained_target
retained_hard_cap
compaction_input_budget
compaction_output_reserve
```

规则：

```text
有生产行为消费者 -> 保留并调优
无真实消费者 -> 删除字段、序列化、diagnostics、测试与文档残留
```

当前基线已确认：

- `fine_timeline_budget` 有 L5 真实消费者；
- `retained_target` 应成为 L4 Low Water 的真实输入；
- `active_evidence_budget`、`uncompressed_tail_budget`、`retained_hard_cap` 当前未发现生产行为消费者，实施时再次快速审计后优先删除，不得为了 profile “完整”创造新调用方。

### G3. 修复并收敛 L4 High Water -> Low Water orchestration

Auto / Manual / Overflow 保留各自不同的启动语义，但共享必要的 epoch/rebuild/commit/stop 行为。

```text
AUTO
- High / Hard pressure 触发
- 启动后追 Low Water

MANUAL
- 不依赖 High Water
- no candidate / no reduction 可为成功 no-op

OVERFLOW
- forced reduction
- 保留 Core one-retry guard
```

共享：

```text
epoch derive
compact Provider request
validation
commit
candidate rebuild
count / gate
Low Water or breaker stop
active Turn exclusion
frozen model / limits
```

禁止为此新增通用 Manager / FSM。

### G4. 完成 Provider Prefix Cache 工程调优

UthCode 只负责：

```text
稳定请求前缀
+ Provider-specific cache hint
+ cache usage diagnostics
+ Eval
```

Provider 负责实际 KV Cache 生命周期。

要求：

1. 不改变 Prompt / Tool Schema authority 顺序只为追求 cache hit。
2. instruction / AGENTS / runtime / tools 的 stable/dynamic 划分必须保持现有 Context authority 语义。
3. OpenAI Responses：在 Integration 中使用当前官方支持、经测试可稳定发送的 cache routing/hint；`prompt_cache_key` 等字段的生成只能依赖稳定 UthCode request facts，不把 Provider 类型带入 Core。
4. Anthropic：在 Integration 中使用当前官方支持的 `cache_control` / 自动或显式 caching 机制；选择方案必须通过请求 fixture + cache usage Eval 证明，不复制 Tool Schema 到 system prompt。
5. OpenAI-compatible：默认不得假设所有兼容端都支持 OpenAI 专有缓存参数；仅在已有明确配置/能力事实时发送，否则保持兼容行为。
6. AGENTS / instruction / tool schema 真变化必须形成 expected invalidation；普通 conversation growth / Timeline compact 不应无故改动真正稳定的 instruction/tool prefix。
7. Provider 不返回 cache metric 时继续 `not_available`，不得用 0 冒充实测。

### G5. 建立通用 FailureReason -> 用户文案链

最小完整链：

```text
Provider SDK / Context / persistence fact
        ↓
Integration / Application mapping boundary
        ↓
Core stable FailureReason / existing PauseReason
        ↓
AgentEvent + TurnResult / Run result
        ↓
Application user-facing projection
        ↓
TUI / CLI / Headless
```

必须做到：

- 分类准确；
- 一句自然语言；
- 有必要时给下一步；
- 跨 Interface 一致；
- 不泄露内部术语、SDK 类型、raw traceback、secret；
- 不冻结每一个中文字面字符串，允许普通文案调整。

### G6. 扩展现有 Eval 完成 256K profile / cache / failure tuning

Deterministic acceptance 与概率性 tuning 证据必须分开。

#### deterministic tests 证明

- 256K default source 生效；
- configured/provider/default provenance 正确；
- 小于 256K 的可靠 Provider ceiling 能收紧；
- 大于 256K 的模型默认仍按 256K Operating Window 工作；
- Hard Gate 分维语义保持；
- High Water 触发后，即使一个 epoch 已低于 High Water，只要仍高于 Low Water 就继续；
- 达到 Low Water 或 finite breaker 后停止；
- manual / overflow 语义不回归；
- prefix fingerprint expected/unexpected change 可判断；
- cache hint 只在正确 Provider Integration 出现；
- no metric -> `not_available`；
- failure reason 可跨 public event/result 序列化；
- TUI / CLI / Headless 消费同一 Application projection；
- raw SDK exception / secret 不进入 public projection。

#### Eval tuning 比较

至少覆盖：

```text
多轮代码探索 + 修改 + 回归
大 Tool Result 外置与回读
长历史保持用户约束/决策
触发一次与多次 compact
compact 后继续真实 coding work
AGENTS scope / tool schema expected invalidation
稳定 prefix 下多轮 cache reuse
```

观测至少包括：

```text
task success / verifier
input/output tokens
compact_count
pre/post compact usage
post_compact headroom
work distance until next pressure
rediscovery / repeated exploration
externalization / HistoryRead
cache_read_tokens
cache_write_tokens
cached-input ratio（可计算时）
prefix change rate / reason
failure reason correctness
```

真实 Provider cache / latency / billing Eval 只有用户明确授权后才能执行；默认任务验收必须可完全离线完成。

### G7. 文档与滚动索引收尾

编码完成后同步当前事实：

```text
docs/Context-Index.md
docs/context/A03-State/State-Context.md        # 若 ContextBudget / Session state fact 受影响
docs/context/A04-Orchestration/Orchestration-Context.md  # 若 orchestration / Eval fact 受影响
docs/OutstandingDebtList.md                    # 由 Task Splitter 按工作包规则决定是否需要同步
```

不得回写或篡改 T09 / T09-1 / T09-2 已冻结的历史正文、Spec、Tasks、Prompt、Checklist；T09-1 的实施漂移应在 T09-3 Feedback 中记录新的最终事实。

---

## 6. 能力欠账

无。

说明：Memory / Evidence Retrieval、Persistent Runtime Recovery、跨 Session Artifact 生命周期、Subagent / Multi-Agent、OS Sandbox、后台 Context Agent 等都是独立未来能力或已有独立触发条件，不是 T09-3 因缺少后置能力而被迫留下的未完成边界。

---

## 7. 核心产品行为

| 场景 | 输入 / 前置状态 | 预期行为 | 状态变化 | 对外结果 |
| --- | --- | --- | --- | --- |
| 无 configured / Provider limit | runnable model，无可靠 limit metadata | 使用 UthCode default 256K | Turn 冻结 default provenance | 正常生成，不因缺少显式 `context_window` 失败 |
| Provider 小窗口 | Provider 可靠 ceiling < 256K | effective input 不超过 ceiling | provenance 记录 provider 收紧 | Hard Gate 以较小安全上限工作 |
| configured + Provider | 二者均存在 | effective 取不扩大任何已知安全 authority 的值 | provenance 同时保留参与来源 | `/status` / Headless 可解释来源 |
| 高压 Auto L4 | candidate >= High Water | 启动 L4 | Timeline 逐 epoch commit | 不直接把超压请求发给 Provider |
| 已低于 High 但高于 Low | L4 已启动 | 继续 compact | 继续 rebuild/count | 不发生“刚低于 High 就停”的漂移 |
| 达到 Low | L4 已启动且 candidate <= target | 停止 catch-up | 保存最终 Timeline | 获得可继续一段工作的 post-compact headroom |
| L4 无进展/失败 | finite breaker / no-progress / unsafe / cancel | 有界停止 | diagnostics 记录原因 | 不无限 compact；最终 request 继续受 Hard Gate 保护 |
| Manual compact | 用户主动触发 | 不依赖 High Water；无可压内容为可控 no-op | 仅在 changed 时 commit | 命令语义稳定 |
| Provider overflow | Provider 明确 overflow | 仅一次 forced recovery | 保留 Core one-retry guard | 成功则重试，失败则稳定失败 |
| stable prefix 连续请求 | instructions/tools 未变 | 不无故改变 stable prefix；发送正确 Provider cache hint | usage 收集 read/write | cache reuse 可观察 |
| expected prefix change | AGENTS / tool schema /稳定 instruction 真变化 | 更新 epoch/fingerprint | 记录 change reason | cache invalidation 被解释为预期 |
| Provider 无 cache metric | 正常响应但不返回指标 | 保持 unavailable | 不伪造 0 | diagnostics 明确 not_available |
| 认证失败 | Integration 可可靠识别 | stable failure classification | terminal / pause 依既有语义 | 用户看到一句可理解的认证提示 |
| 网络/限流/timeout | 现有语义可恢复 | 保持 Pause/Retry；投影具体原因 | continuation 保持现有规则 | 用户得到具体、可行动提示 |
| Context 无法安全收敛 | Hard Gate / compact 最终无法安全发送 | stable context failure | 不发送 unsafe request | 用户看到“当前会话内容过多……”类自然语言 |
| Headless | 无 TUI | 消费同一 structured reason / Application projection | 无 UI 私有状态 | 能获得机器分类与一致用户文案 |

---

## 8. 架构归属

| 能力 | 所属模块 | 状态所有者 | 调用方 | 依赖方向 | 原因 |
| --- | --- | --- | --- | --- | --- |
| `ContextBudget` / Gate contract | Core | Core value object | Application Context service | Application -> Core | Provider-independent safety/product semantics |
| 256K default / limit resolution orchestration | Core policy + Application freeze | Active Turn 的 frozen budget 由 Application 组合 | `generation.prepare` | Application -> Core / Integration | default 是 UthCode policy；Provider metadata 获取仍在 Integration |
| Context Source / Compiler | Core | Transcript / Timeline / Context snapshots 既有 owner | Application | Application -> Core | 保持 T09/T09-1 边界 |
| L4 orchestration | Application | active Session Timeline | Formal Run / Turn | Application -> Core + Provider | 需要 session、provider、commit、rebuild 组合；不应塞入 Core loop |
| L4 epoch / validation contract | Core | value objects | Application | Application -> Core | provider-independent compact semantics |
| Prefix fingerprint | Core/Application 既有边界 | instruction/context snapshot | Application | existing | 已有稳定事实，不新增 cache subsystem |
| OpenAI cache hint | Integration | 无 UthCode durable cache state | Application request adapter | Core/Application -> Integration | Provider-specific wire capability |
| Anthropic cache control | Integration | 无 UthCode durable cache state | Application request adapter | Core/Application -> Integration | Provider-specific wire capability |
| cache usage projection | Application | diagnostics snapshot | status / Eval / Headless | Integration usage -> Application | 统一 provider-independent observation |
| `FailureReason` | Core public contract | terminal Turn result/event | Application / Headless | Core -> Application | 稳定机器语义应跨 Interface |
| 用户失败文案 | Application | 无长期状态 | TUI / CLI / Headless | Interface -> Application | Interface 不拥有分类规则 |
| Provider SDK error mapping | Integration | 无 | Core ProviderPort consumer | Integration -> Core error classes | SDK 类型截止于 Integration |
| tuning / comparison | `eval/` | attempt artifact | 人工 runner | Public Application API | 复用 B01，不进入生产 runtime |

禁止新增：

```text
ContextManager
ContextPolicyRegistry
CompactManager
CompactionJob
CompactionScheduler
CacheManager
CacheRegistry
ErrorManager
ErrorRegistry
后台 Context Agent
新的通用 runtime hook
```

除非编码过程中发现当前生产调用链**无法在不新增长期公共协议的情况下实现冻结行为**；此时必须停止并请求重新打开设计，不得自行突破。

---

## 9. 完成后的最小完整调用链

### 9.1 普通生成与 Context safety

```text
Interface / Headless
      ↓
Application Run / Turn
      ↓
resolve reliable Provider limits
      ↓
resolve ContextBudget
(configured / provider / default 256K)
      ↓
compose final candidate
      ↓
count / estimate
      ↓
High Water Pressure Gate
      │
      ├─ no pressure ───────────────────────┐
      │                                    │
      └─ pressure -> L4 catch-up            │
                     ↓                     │
              rebuild + recount            │
                     ↓                     │
              target reached / breaker     │
                     └──────────────────────┤
                                            ↓
                                    final Hard Gate
                                            ↓
                                      ProviderPort
                                            ↓
                                      Integration
```

### 9.2 Prefix cache

```text
stable UthCode instructions/tools facts
            ↓
existing fingerprint / epoch
            ↓
GenerationRequest
            ↓
Provider Integration
   ├─ OpenAI-specific cache hint
   ├─ Anthropic-specific cache control
   └─ Compat: only supported configured behavior
            ↓
Provider-managed KV cache
            ↓
Usage cache read/write
            ↓
Application diagnostics / Eval
```

### 9.3 用户失败语义

```text
SDK / Provider / Context / persistence failure fact
             ↓
Integration / Application factual mapping
             ↓
Core FailureReason / existing PauseReason
             ↓
AgentEvent + TurnResult
             ↓
Application failure presentation
             ↓
TUI / CLI / Headless
```

---

## 10. 目标目录树与文件级变更规划

> 下列是基于分析基线的目标写集合。Task Splitter 可因最新 HEAD 的局部文件组织变化做等价调整，但不得改变架构 owner 或扩大范围。

```text
src/uthcode/
├── core/
│   ├── context.py                         [修改]
│   ├── agent.py                           [修改]
│   ├── agent_events.py                    [修改]
│   ├── provider.py                        [按实际分类需要修改]
│   └── compaction.py                      [仅当共享 stop/contract 需要最小修改]
├── application/
│   ├── context.py                         [修改]
│   ├── generation.py                      [修改]
│   ├── provider_usage.py                  [修改/补测]
│   ├── runs.py                            [修改]
│   └── configuration.py                   [仅 provenance/config 解析确有需要时修改]
├── integrations/providers/
│   ├── anthropic.py                       [修改]
│   ├── openai_responses.py                [修改]
│   ├── openai_compat.py                   [原则上保持；仅支持能力配置确有调用方时修改]
│   └── config.py                          [仅 Provider cache capability 需要已有配置入口时修改]
└── interfaces/
    └── ...                                [只修改展示消费；不得新增分类规则]

eval/
├── metrics.py                             [修改]
├── reporting.py                           [按新增可观察指标需要修改]
├── runner.py                              [仅需要 profile candidate 参数/metadata 时修改]
└── tasks/...                              [新增/修改 256K 长任务 fixture，按 B01 现有布局]

tests/
├── test_context_budget_gate.py            [修改]
├── test_context_compaction.py             [修改]
├── test_t09_1_context_protocol_e2e.py     [修改]
├── test_agent_events.py                   [修改]
├── test_agent_loop.py                     [修改]
├── test_application_runs.py               [修改]
├── test_anthropic_integration.py          [修改]
├── test_openai_responses_integration.py   [修改]
├── test_openai_compat_integration.py      [回归/按需修改]
└── eval/...                               [修改/新增]

docs/
├── Context-Index.md                       [实施收尾按事实修改]
├── OutstandingDebtList.md                 [由拆分阶段按规则决定是否变化]
└── context/
    ├── A03-State/State-Context.md          [按事实修改]
    └── A04-Orchestration/Orchestration-Context.md [按事实修改]
```

### 10.1 文件级任务说明

| 文件 / 区域 | 变更目的 | 不允许顺带做 |
| --- | --- | --- |
| `core/context.py` | default source、profile 收敛、Low/High contract、provenance value | model catalog、动态 policy registry |
| `application/generation.py` | frozen budget、L4 Low Water catch-up、shared orchestration | 第二 Agent Loop、后台 compactor |
| `application/context.py` | 复用现有 compact/rebuild 服务，必要时收敛最小重复 | ContextManager facade |
| `core/agent_events.py` | public `FailureReason` 序列化 | 用户中文字面文案 |
| `core/agent.py` | 已知错误到稳定 reason 的保真 | SDK 类型判断、Application 文案 |
| `application/runs.py` | Application-owned failure presentation / persistence failure projection | TUI-specific branch |
| `provider.py` | 仅在现有 error hierarchy 无法表达可靠事实时补最小稳定错误类型 | 每个 HTTP status 一个 class |
| `openai_responses.py` | OpenAI cache hint、timeout/auth 等可靠 mapping | Core cache contract |
| `anthropic.py` | Anthropic cache control、usage / error mapping | Anthropic 类型泄露 |
| `openai_compat.py` | 保持协议兼容，默认不盲发 Responses 专有字段 | 假定所有 compat 支持 prompt cache |
| `provider_usage.py` | cache metric availability/provenance 与新增比率所需原始事实 | 把 unavailable 写成 0 |
| `eval/` | 256K profile、cache、failure 对比 | 新 benchmark runtime / CI 强制 live Provider |
| Interface | 展示 Application 统一 projection | 自己判断异常类型 |

---

## 11. 关键数据与状态

### 11.1 Context limit provenance

最终必须有一个**现有模型上的最小扩展**能表达：

```text
configured value: optional
provider value: optional
default value: 256_000
effective input limit
selected/active source
which sources tightened the result
```

具体私有字段名由实施决定；不新增无调用方 protocol。

必须满足：

```text
default != Provider metadata
```

### 11.2 Operating Profile

最终 profile 只保留真实驱动行为的参数。

至少需要能够驱动：

```text
effective_input_limit
High Water / auto gate
Low Water / retained target
fine timeline budget
compaction input/output safety
finite max epochs
count safety allowance
```

若字段没有行为消费者，删除而不是人为创造消费者。

### 11.3 FailureReason

`FailureReason` 是稳定 public machine semantic，不是异常类镜像，也不是 HTTP status 镜像。

要求：

- JSON-safe / round-trip；
- 可存在于 `TurnFailed` 与 terminal `TurnResult` 的稳定 public projection；
- successful / cancelled result 不得伪造 failure reason；
- PauseReason 继续承担可恢复暂停的真实语义；
- native exception details 仅进入内部 diagnostics，不能进入 public reason/message。

### 11.4 Cache diagnostics

必须继续保留：

```text
available / not_available
value
provenance
```

如新增 `cached_input_ratio` 等派生指标，只能在底层 read/input 数值真实 available 时计算；缺失时保持 unavailable。

---

## 12. 依赖与数据流约束

### 12.1 Context limit

```text
Configuration ------------------┐
                                │
Provider Integration -> ModelLimits
                                │
                                v
                       Application Turn freeze
                                ↓
                           Core ContextBudget
                                ↓
                        Compiler / Gate / L4
```

- Provider metadata 获取逻辑不得进入 Core。
- UthCode default policy 不得伪造成 Integration metadata。
- Active Turn 内已冻结 budget 不因外部配置变化被中途替换。

### 12.2 Prefix cache

```text
Core/Application stable request facts
                ↓
            Integration
                ↓
        Provider cache controls
```

禁止反向：

```text
Core -> Anthropic cache_control
Core -> OpenAI prompt_cache_key SDK type
```

### 12.3 Failure

```text
SDK error
  ↓
Integration UthCode error
  ↓
Core failure/pause semantic
  ↓
Application user projection
  ↓
Interface
```

第三方异常对象截止于 Integration。

---

## 13. 对现有能力的影响

| 现有能力 / 文件 | 当前状态 | 本次如何使用 | 是否修改 | 原因 | 回归重点 |
| --- | --- | --- | --- | --- | --- |
| Prompt Asset / Core Runtime Contract | 稳定 | 作为 stable prefix | 原则上不改内容 | cache 优化不能改变 authority | prompt snapshot / fingerprint |
| Tool System | Tool schema 唯一 authority | 继续作为 `GenerationRequest.tools` | 不改 owner | 禁止复制 schema | tool fingerprint / provider request |
| Transcript / Timeline Session v3 | 已生产化 | L4/L5 的 durable semantic history | 最小修改 | Low Water orchestration | resume / compact refs |
| Tool Result 外置 | 已生产化 | 作为 256K long-task baseline | 原则上不改架构 | 避免 T09-3 扩成 Artifact Store | externalization / HistoryRead |
| Manual Compact | 已存在 | 共享最小 compact orchestration | 修改测试/必要实现 | 保持独立 trigger | manual no-op / changed |
| Overflow Recovery | 已存在 | 保留 one-retry | 最小修改 | 统一 stop/rebuild | exactly one retry |
| L5 Timeline aging | 已存在 | 保留 `fine_timeline_budget` | 调参/测试 | 真实消费者 | aging budget |
| Provider usage | 已有 cache read/write | 扩展 tuning | 修改 | Prefix Cache 可测 | availability / provenance |
| AgentEvent | display-safe public contract | 增加 stable FailureReason | 修改 | Headless / Interface 共享 | JSON round-trip |
| TurnResult | terminal public result | 同步 failure reason | 修改 | Headless 机器消费 | success/fail/cancel invariants |
| TUI / CLI | 展示层 | 只显示 Application projection | 最小修改 | 消除私有分类 | same reason -> same message |
| B01 Eval | 已有六维 runner | 扩展 Context 实验 | 修改 | 不建第二套 | compare compatibility |

---

## 14. 第三方依赖

**无新增第三方依赖。**

本任务只使用当前已有 OpenAI / Anthropic SDK 能力与现有项目依赖。

若当前 SDK 版本不支持需要的官方 cache 参数：

1. 先确认当前官方 SDK 版本与 wire API；
2. 如必须升级现有 SDK，Task Splitter 应把版本兼容与三个 Provider Integration 回归列为同一可审查任务；
3. 不得为单个缓存字段引入额外 Prompt/Cache 框架。

---

## 15. 实施任务拆分建议

> 本节给 Task Splitter 定义依赖顺序和提交边界；Splitter 仍需生成正式 Spec / Tasks / Checklist / Worker Prompt。

### Task 1：收敛 Context limit resolver 与 256K Operating Profile contract

**目标**

补齐 default 256K source、provenance 与 active Turn freeze；保持 Hard Gate 分维语义。

**前置条件**

无。

**主要文件**

```text
src/uthcode/core/context.py
src/uthcode/application/generation.py
src/uthcode/application/configuration.py      # 按需
tests/test_context_budget_gate.py
tests/test_application_runs.py
```

**实现要求**

- configured/provider/default 三来源；
- effective 不放大更小的可靠限制；
- default 与 Provider provenance 严格区分；
- Active Turn freeze；
- 不恢复 model catalog；
- 不改变 input/output/combined 分维 Gate。

**完成结果**

无显式 `context_window`、无 Provider limit 的 model 也能以 UthCode 256K default 建立安全 budget；小窗口仍被收紧。

**测试**

离线 Fake / contract tests。

**明确不做**

多 profile registry、按模型名称 tuning、Provider SDK catalog。

**推荐提交边界**

```text
t09-3-01: resolve 256k operating limits with provenance
```

### Task 2：修复 Low Water 并清理无消费者 ContextBudget 字段

**目标**

让 frozen `retained_target` 真正控制已启动 Auto L4 catch-up，并删除半落地字段。

**前置条件**

Task 1。

**主要文件**

```text
src/uthcode/core/context.py
src/uthcode/application/context.py
src/uthcode/application/generation.py
tests/test_context_compaction.py
tests/test_t09_1_context_protocol_e2e.py
tests/test_context_budget_gate.py
```

**实现要求**

- 一个 epoch 后低于 High 但高于 Low -> 继续；
- target reached -> 停；
- breaker/no-progress/failure/cancel -> 有界停；
- manual/overflow 保持真实差异；
- audit 后删除无生产消费者字段及所有残留；
- 不新增第二 policy engine。

**推荐提交边界**

```text
t09-3-02: restore low-water compaction semantics
```

### Task 3：建立 Provider Prefix Cache hints 与确定性请求回归

**目标**

让 OpenAI Responses / Anthropic 在不污染 Core 的情况下主动利用 Provider 缓存能力。

**前置条件**

Task 1；Task 2 可并行后的稳定 request shape 需要在最终合并前确认。

**主要文件**

```text
src/uthcode/integrations/providers/openai_responses.py
src/uthcode/integrations/providers/anthropic.py
src/uthcode/integrations/providers/openai_compat.py   # 回归为主
src/uthcode/application/provider_usage.py
tests/test_openai_responses_integration.py
tests/test_anthropic_integration.py
tests/test_openai_compat_integration.py
```

**实现要求**

- 当前官方参数；
- stable request facts 派生 cache hint；
- Tool Schema 不复制；
- compat 不盲发专有字段；
- cache metrics unavailable 不伪造；
- expected invalidation fixture。

**推荐提交边界**

```text
t09-3-03: tune provider prompt cache integration
```

### Task 4：补齐 Core FailureReason 与 Application 用户失败投影

**目标**

落实决策 C。

**前置条件**

Task 1（Context failure reason 需要稳定分类）。

**主要文件**

```text
src/uthcode/core/provider.py                  # 按需
src/uthcode/core/agent.py
src/uthcode/core/agent_events.py
src/uthcode/application/runs.py
src/uthcode/application/generation.py         # Context prepare error preservation
src/uthcode/integrations/providers/*.py       # 只补可靠 mapping
src/uthcode/interfaces/...                    # 展示消费
tests/test_agent_events.py
tests/test_agent_loop.py
tests/test_application_runs.py
Provider integration tests
```

**实现要求**

- `FailureReason` 小而稳定；
- public JSON round-trip；
- preserve existing Pause / Retry；
- Application 一处形成 user-facing message；
- Headless structured reason；
- Interface 无重复 exception switch；
- no secret/native exception leak。

**推荐提交边界**

```text
t09-3-04: expose stable failure reasons across interfaces
```

### Task 5：扩展 Eval 并完成 256K profile 粗筛/细调

**目标**

基于 B01 对 Profile、Low Water、cache 与 compact 频率做可重复比较。

**前置条件**

Task 1-4 生产链完成。

**主要文件**

```text
eval/
tests/eval/
```

**实现要求**

- 固定代码、Prompt、model/provider/config fingerprint；
- >=3 组明显不同 profile candidate；
- 输出逐维 metrics，不造 overall score；
- 将 deterministic contract 与 tuning result 分离；
- remote Provider run 默认拒绝，只有显式授权才运行。

**完成结果**

选出一组 **T09-3 初始工程默认**，并保留实验报告证明它相对候选的取舍；数值不是 public API 承诺。

**推荐提交边界**

```text
t09-3-05: tune 256k context profile with eval evidence
```

### Task 6：全链路验收、清理与文档同步

**目标**

确认没有旧字段、重复失败映射、cache 越界、第二 Context policy 或冻结文档回写。

**前置条件**

Task 1-5。

**主要文件**

```text
tests/
docs/Context-Index.md
docs/context/A03-State/State-Context.md
docs/context/A04-Orchestration/Orchestration-Context.md
T09-3 feedback
```

**要求**

- 全量 pytest；
- architecture boundaries；
- compileall；
- pip check；
- git diff --check；
- UTF-8 docs guard；
- no real network / paid provider unless authorized；
- 无被删除字段残留；
- 无 TUI 私有 failure classification；
- 无 Provider cache type 穿透 Core。

**推荐提交边界**

```text
t09-3-06: close 256k context tuning and failure semantics
```

---

## 16. 测试矩阵

| 场景 | 主要测试文件 | 必须证明 |
| --- | --- | --- |
| default-only 256K | `test_context_budget_gate.py` | 无 config/provider limit 也有 safe budget，source=default |
| configured < 256K | `test_context_budget_gate.py` | 不能被 default 放大 |
| Provider < configured/default | `test_context_budget_gate.py` | Provider ceiling 收紧 |
| Provider > 256K | `test_context_budget_gate.py` / Application | 默认 operating cap 仍 256K |
| combined/output unknown | `test_context_budget_gate.py` | 不伪造物理 combined window |
| active Turn freeze | `test_application_runs.py` | 中途 model/config 变化不改 active budget |
| High -> Low | `test_t09_1_context_protocol_e2e.py` | 低于 High、高于 Low 继续 compact |
| target reached | 同上 | 达到 Low 后停止 |
| max epochs / no progress | `test_context_compaction.py` + e2e | finite termination |
| manual compact | context command/e2e existing tests | 不依赖 High；no-op 稳定 |
| overflow | `test_agent_loop.py` + e2e | exactly one recovery retry |
| L5 | context compaction tests | fine budget 仍有效 |
| deleted ContextBudget fields | budget tests / grep guard | 无 serialization/docs/test 残留 |
| OpenAI cache hint | `test_openai_responses_integration.py` | wire args 正确、稳定 key、无 Core type |
| Anthropic cache control | `test_anthropic_integration.py` | wire args/breakpoint 正确 |
| Compat cache | `test_openai_compat_integration.py` | 默认不盲发专有参数 |
| cache metric available | provider/application usage tests | read/write + provenance 正确 |
| cache metric missing | 同上 | `not_available`，不是 0 |
| prefix unchanged | instruction/context tests | ordinary turn growth 不改 stable instruction fingerprint |
| expected invalidation | instruction/provider fixture | AGENTS/tool schema 真变化有 reason |
| FailureReason round-trip | `test_agent_events.py` | TurnFailed / TurnResult JSON 稳定 |
| auth failure | Provider integration + AgentLoop | 分类不丢失，用户文案可理解 |
| invalid response | integration + agent | stable reason |
| Context unresolved | application e2e | 不变成 opaque internal error |
| network/rate limit/timeout | AgentLoop + integration | preserve Pause/Retry + 具体投影 |
| Headless | `test_application_runs.py` / exec tests | structured reason + same message semantics |
| TUI/CLI | existing interface tests | 不自己做异常分类 |
| secret/native exception | integration/application tests | public event/message 不泄露 |
| Eval compare | `tests/eval/` | fingerprint compatible 才产生 delta |
| 256K long task | `tests/eval/` + fixtures | compact/cache/rediscovery metrics 可观察 |
| architecture | `test_architecture_boundaries.py` | Integration SDK 类型不越界，无新反向依赖 |

### 16.1 关键 Low Water 回归必须显式包含

使用可控 token estimator / fake provider 构造至少一条类似：

```text
初始 candidate ≈ 225K
High Water      < 225K
Low Water       ≈ target

L4 epoch 1 -> ≈ 210K
# 已低于 High，但仍高于 Low
=> MUST continue

L4 epoch 2 -> <= Low
=> stop
```

具体 candidate 数值应按最终 Eval profile 调整，但测试结构不能退化成只断言 `headroom > 0`。

---

## 17. Eval 调优协议

### 17.1 不产生“总分”

沿用 B01 六维输出：

```text
correctness
context
exploration
efficiency
stability
safety
```

不得为了选 profile 再造一个加权 overall score。

### 17.2 候选选择规则

候选优劣不能只看 token 最少。

需要综合人工/逐维证据：

```text
任务成功率不能明显退化
compact 不能 thrash
post-compact 要有足够连续工作空间
关键约束/决策不能丢失
重复探索不能明显增加
Provider cache reuse 不能因无意义 prefix invalidation 明显变差
总 token / cache write 成本合理
```

### 17.3 远端实验

默认：

```text
NOT RUN / authorization required
```

任何真实 API 调用、费用调用或真实 secret 读取都必须由用户显式授权。

离线 acceptance 不得依赖远端 Provider。

---

## 18. 删除与清理

实施时确认无生产 caller 后，优先删除当前半落地字段：

```text
active_evidence_budget
uncompressed_tail_budget
retained_hard_cap
```

并同步删除：

- constructor / `__post_init__` 派生逻辑；
- `to_dict()`；
- diagnostics；
- tests fixture；
- 文档中的当前态描述。

如果实施时发现某字段已有新的真实生产 caller：

```text
停止删除
→ 在对应 Task feedback 中记录 caller 与真实产品行为
→ 纳入 256K Eval
```

这属于基线变化下的事实核对，不需要重新讨论产品方向。

同时清理：

- Interface 重复失败分类；
- 无用 cache experiment 分支；
- T09-3 实施中产生但最终未使用的临时 profile 参数；
- 旧的“configured/provider 必须至少一个”假设测试；
- 任何为了兼容过渡保留的双轨 API。

---

## 19. 验收标准

### 19.1 Deterministic correctness acceptance

必须全部满足：

1. 缺少显式 model context_window 与 Provider limit 时可由 default 256K 正常运行。
2. 任何可靠小窗口 ceiling 都不会被 default 256K 放大。
3. Context limit provenance 可在 Application status/diagnostics/Headless 中观察。
4. Hard Gate 分维 safety 语义不回归。
5. Auto L4 真正满足 High Water -> Low Water 迟滞。
6. finite breaker / no-progress / failure / cancel 不会形成无限 compaction。
7. Manual / overflow / L5 不因 Low Water 修复退化。
8. 无生产 caller 的 retained profile 字段已经删除，不新增伪调用方。
9. stable instruction/tool prefix 不因普通 conversation growth 无意义改变。
10. OpenAI / Anthropic cache hint 只出现在 Integration；Tool Schema 仍只有 Tool System 一份 authority。
11. Provider cache metrics 缺失仍为 `not_available`。
12. Core public failure contract 能稳定表达具体失败类型；Application 统一映射用户文案。
13. TUI、CLI、Headless 不再各自维护独立 exception classifier。
14. native SDK exception / raw Provider body / secret 不进入 public event/result/message。
15. 全量测试与 architecture boundary 通过。

### 19.2 Eval tuning evidence

必须交付一份 T09-3 Eval 结果，至少能够回答：

- 最终选定的 256K High Water / Low Water 初始默认为什么优于其它候选；
- compact 后能继续多少真实 coding work 才再次 pressure；
- compact 次数、rediscovery、repeated exploration 的变化；
- cache read/write / prefix stability 的变化（可观察时）；
- 是否出现质量下降或 false early compaction；
- 哪些指标 unavailable，为什么 unavailable。

候选不需要在所有指标上“全胜”；任务要求是形成可解释的工程取舍，而不是伪造确定性的冠军。

---

## 20. Coding 停止条件

出现以下任一情况，编码代理必须停止当前设计扩张并报告：

1. 为完成 256K profile 必须新增一套长期 Context Policy Registry / Manager / background Agent。
2. 必须让 Core 感知 OpenAI / Anthropic SDK 类型或 cache-specific wire object。
3. 必须复制 Tool Schema 到 system/public prompt 才能实现缓存。
4. 必须通过 model name substring / package model catalog 才能保证安全 limit。
5. 必须修改 T09/T09-1/T09-2 冻结历史文档才能让新测试通过。
6. FailureReason 无法在现有 public event/result 边界上以小扩展实现，必须引入新的系统级错误子系统。
7. 某 Provider 的 cache 参数无法由当前官方 SDK / API 可靠确认，却需要靠猜测发送。
8. Eval 结果表明简单有界 L4 + 256K profile 无法满足真实任务，必须进入后台 Context Agent / hierarchical summary graph 等独立能力。
9. 发现新的产品/公共协议决策会形成两种明显不同的长期 UthCode 行为。

普通私有函数拆分、测试组织、字段命名、fixture、局部错误处理不得借此停止并向用户甩普通工程决策。

---

## 21. 明确不做 / Out of Scope

T09-3 不做：

```text
Memory / cross-session retrieval
Evidence Retrieval / RAG
Subagent / Multi-Agent
Worktree
background Context Agent
hierarchical Summary Graph（除非未来 Eval 另立任务证明需要）
independent compaction model
compaction provider fallback
durable compaction FSM / job manager
OS Sandbox
权限系统大改
完整 Error subsystem / ErrorManager / ErrorRegistry
复杂 i18n 系统
bundled model catalog / local official metadata database
按模型名称的 tuning table
模型特定 Prompt Overlay
Provider KV Cache 本地持久化
Cache DB / WAL / migration / replication
大型 TUI redesign
所有 Provider HTTP status 的完整错误分类
跨 Session Artifact Store / GC
Persistent Runtime Recovery
Skill / MCP 动态 Tool 系统
```

这些不属于本任务的隐藏验收项。

---

## 22. 对后续 Task Splitter 的强制覆盖矩阵

Splitter 必须最终证明至少以下映射存在：

| Frozen Decision | 必须覆盖的下游主题 |
| --- | --- |
| D-T09-3-01 | 256K default Operating Window + tests + Eval |
| D-T09-3-02 | 三来源 resolver + provenance + active Turn freeze |
| D-T09-3-03 | 分维 Hard Gate regression |
| D-T09-3-04 | 无 model catalog / guessing architecture checks |
| D-T09-3-05 | High -> Low production L4 + explicit e2e |
| D-T09-3-06 | >=3 profile candidates + Eval evidence |
| D-T09-3-07 | Core FailureReason + Application message + cross-interface tests |
| D-T09-3-08 | Spec/Task/Worker/Checklist traceability |

任何 Decision 没有 Spec、Task、Worker Prompt 和 Checklist 覆盖都视为拆分失败。

---

## 23. 最终完成定义

T09-3 完成后，UthCode 应具备这样一条可验证事实：

> 在用户没有手动声明模型窗口时，UthCode 仍可按 256K 默认 Operating Window 工作；可靠的小窗口 Provider ceiling 会安全收紧该值。Context Engine 使用经 Eval 选择的 High/Low profile，在压力触发后真正 compact 到 Low Water，而不是刚越过触发线即停止。稳定 instructions/tools 前缀可由 Provider Integration 主动利用 prompt cache，并通过真实 usage diagnostics 观察收益。生成失败时，Core 保留稳定机器 FailureReason，Application 形成统一自然语言提示，TUI、CLI 与 Headless 不再各自猜测失败原因。

同时：

> 这一结果不依赖 Memory、后台 Context Agent、model catalog、Provider KV Cache 本地持久化、复杂错误平台或新的通用框架。
