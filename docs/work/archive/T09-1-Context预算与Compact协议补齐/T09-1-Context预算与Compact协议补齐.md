# UthCode T09-1：Context预算与Compact协议补齐任务书

## 1. 分析基线

### 1.1 目标仓库与历史分析基线

目标仓库：

```text
https://github.com/undertaker33/Re-UthCode
```

本次 T09-1 设计与返工时用于核对源码事实的历史分析基线：

```text
40e9b2eaf984dbc266fa16e786f03de57435dfad
```

该 Commit 是形成当前设计时用于核对 `src/ + tests/` 事实的历史分析基线，用于说明原 T09-1 工作包从什么状态开始返工以及当前设计为何形成。它不是 Worker 必须 checkout、长期保持或按 HEAD 等值校验的实施 Commit。

```text
Merge pull request #24: T09-1 Context预算与Compact协议补齐工作包
```

该基线已经包含 T09-1 正式工作包，但尚未派发 Worker、没有实现提交、Checklist 全未勾选且 Feedback 为空。当前源码与测试状态已直接在该 merge tree 下重新核对；本次按用户批准的返工提示词原位修订，不继承任务书中与真实代码冲突的判断。

因此：

- 保留原工作包目录与四份主文档，原位返工，不创建 `v2`、`fix`、`retry` 平行包；
- Worker Prompt 仍为独立可派发文件，Feedback 目录保持空，直到真实实施发生；
- 本任务书中的“当前实现基线”记录 `40e9b2ea...` 当时的 `src/ + tests/` 事实；Worker 实施时必须以用户实际派发 Prompt 时的当前仓库状态为起点重新核对；
- 后续编码不得因早期方案而保留 fixed 258K、旧 Projection、bundled metadata 或兼容双轨。

### 1.2 已读取的全局约束与当前事实

本次实际读取并作为约束输入：

```text
AGENTS.md
docs/README.md
docs/rules/WorkPackageRules.md
docs/rules/UserDecisionBoundary.md
docs/Context-Index.md
docs/OutstandingDebtList.md
docs/context/A03-State/State-Context.md
docs/context/A04-Orchestration/Orchestration-Context.md
docs/core-design/T09-context-engineering.md
```

当前与本任务直接相关的冻结边界：

```text
interfaces -> application -> core
                  |
                  v
             integrations
```

并继续遵守：

- `core/` 不依赖 filesystem、network、Provider SDK、Application、Integration 或 Interface；
- 第三方 SDK 类型必须截止在 `integrations/`；
- Interface 只触发 Application use case，不拥有 Context 核心语义；
- Agent Loop 仍是行为 loop，不拥有 Session、Transcript、Timeline、Budget 或 Compact 编排状态；
- 不为未来 Memory、Skill、MCP、Subagent、Multi-Agent 预建 Manager / Registry / Job / FSM；
- 不为 Re:UthCode 早期实现保留迁移式兼容层。

### 1.3 实际核对的关键源码

```text
src/uthcode/core/context.py
src/uthcode/core/history.py
src/uthcode/core/prompt.py
src/uthcode/core/provider.py
src/uthcode/core/agent.py

src/uthcode/application/context.py
src/uthcode/application/configuration.py
src/uthcode/application/generation.py
src/uthcode/application/history.py
src/uthcode/application/sessions.py
src/uthcode/application/tools.py
src/uthcode/application/bootstrap.py
src/uthcode/application/commands/builtins.py
src/uthcode/application/commands/dispatcher.py
src/uthcode/application/commands/models.py

src/uthcode/integrations/config/loader.py
src/uthcode/integrations/config/data.py
src/uthcode/integrations/config/template.py
src/uthcode/integrations/session_files.py
src/uthcode/integrations/providers/config.py
src/uthcode/integrations/providers/anthropic.py
src/uthcode/integrations/tools/tool_result_read.py
```

### 1.4 实际核对的测试范围

当前 `tests/` 已存在与本任务直接相关的测试，包括：

```text
tests/test_agent_loop.py
tests/test_anthropic_integration.py
tests/test_application.py
tests/test_application_runtime.py
tests/test_application_runs.py
tests/test_application_tools.py
tests/test_architecture_boundaries.py
tests/test_command_dispatcher.py
tests/test_config_contract.py
tests/test_configuration.py
tests/test_context_compaction.py
tests/test_context_compiler.py
tests/test_history_contract.py
tests/test_session_files.py
tests/test_tool_result_persistence.py
tests/test_tui.py
tests/test_w04_session_commands.py
tests/test_w05_diagnostics.py
tests/test_w06_integration_delivery.py
```

后续新增测试文件见第 9、10、16 节。

### 1.5 本次外部参考

本次只围绕 T09-1 的预算与压缩问题核对以下当前资料：

| 来源 | 实际研究问题 |
| --- | --- |
| Pi Coding Agent 官方 Compaction 文档 | 自动压缩是否使用绝对 reserve；手动 `/compact` 是否独立于自动阈值 |
| OpenCode 当前 Compaction 文档 | 是否在 Provider call 前按最终 system/messages/tools 做 pressure accounting；buffer 与 output allowance 如何参与 |
| OpenAI Codex 当前 `context_window.rs` / Model metadata | proactive auto-compaction boundary 与 full model context hard cap 是否分层 |
| Anthropic Token Counting 官方文档 | Provider-side count 是否仍可能与实际 Messages input 有小幅差异 |
| Anthropic Models API 官方文档 / Release Notes | 是否能可靠取得 `max_input_tokens` / `max_tokens` |

---

## 2. 当前实现基线

T09 已完成第一版 Context Engineering；在历史分析基线 `40e9b2ea...` 下，正式源码仍处于以下阶段。该描述是设计证据，不是未来 Worker 的固定 HEAD 要求。

### 2.1 当前请求链路

```text
AgentLoop
   ↓ request_preparer（sync | awaitable，Core 已支持）
UthCodeApplication._start_agent_turn.prepare()
   ↓
ApplicationContextService.compose_generation_request()
   ↓
ContextCompiler
   ↓
ContextSnapshot
   ↓
GenerationRequest
   ↓
ProviderPort
```

`overflow_handler` 同样已经支持 sync | awaitable 和一次性 retry guard。T09-1 只复用、类型校准并回归取消/错误行为，不把 async hook 支持重复列为新增能力；当前 Application 的 `prepare()` 仍是同步 closure，真实 L4/L5 可在既有 awaitable 边界接入。

### 2.2 当前关键事实

1. `src/uthcode/core/context.py` 仍以：

```text
UTHCODE_CONTEXT_BUDGET_TOKENS = 258_000
```

作为唯一 Operating Budget。

`ContextUsage` 与 `ContextSnapshot` 仍对固定 258K 做硬校验。

2. `ModelProfile` 当前只有：

```text
model_ref
provider_profile_id
remote_id
display_name?
max_output_tokens?
reasoning_effort?
```

没有 `context_window`。

3. 当前 Context 原始事实与压缩视图是：

```text
CanonicalHistory
      ↓
Projection
      ↓
ContextCompiler
```

`Projection` 仍是单层派生历史视图。

4. `ContextCompactor` 已有：

- complete semantic unit；
- bounded input；
- output reserve；
- summary hard cap；
- rolling batch；
- single-flight；
- candidate validation。

但其生产 summarizer 仍是同步 `Callable[[str], str]`，而 Application 没有注入真实模型调用者。

因此：

```text
/compact
  -> compact_session()
  -> ContextCompactor.compact(summarize=None)
  -> summarizer_unavailable
```

Provider overflow 入口同样无法成功压缩。

5. 当前 Session schema 仍是 v1：

```text
metadata.json
writer.lock
history.jsonl
runtime.jsonl
tool-results/
```

History 与 Projection record 共存于 `history.jsonl`。

6. 当前 active Turn 已在 `_start_agent_turn()` 开始时冻结：

```text
Provider
model ref / remote model id
reasoning
max_output_tokens
Tool definitions
```

运行中的 `/model` 只影响下一 Turn。

7. `ToolResultRead` 已具备：

```text
current Session only
opaque ref
bounded page
read-only
```

可作为本任务 `HistoryRead` 的现有安全模式参考，但二者必须保持独立证据域。

8. `/status` 仍显示固定 258K，并明确打印 “before T09-1” 阶段限制。

9. Slash Command Dispatcher 与 Handler contract 当前是同步调用。真实 tool-free Compact 要调用异步 Provider，因此 `/compact` 生产可用后需要最小 async command 接入。

10. 当前 History 主要在 terminal Turn 边界 durable append；现有 durability reconciliation、unknown-outcome quarantine、single-writer 和 close/reopen recovery 已经稳定，本任务必须复用这些语义，而不是另造 Runtime checkpoint。

11. 当前 Anthropic Integration 尚未实现 Model Limits / token-count capability；OpenAI Responses / OpenAI-compatible 也没有可统一依赖的真实窗口发现合同。

---

## 3. 问题定义

本任务解决：

```text
让 UthCode 从：

固定 258K Operating Budget
+ 单层 Projection
+ 生产不可用的 Compact

升级为：

按当前模型 Operating Context Window 治理每一次真实 Provider 请求，
把 proactive Context Pressure 与 hard request safety 明确分离，
在 Transcript 原始事实不丢失的前提下，
通过确定性 L1-L3、bounded L4、B′ catch-up 和 L5 Timeline aging
形成可持久恢复、可重复推导、可实际运行的 Context reduction 协议。
```

当前已有能力不能完整解决，原因是：

1. 固定 258K 既不能保护小窗口模型，也不能充分使用大窗口模型。
2. “是否应该提前治理”与“当前请求是否绝对允许发送”尚未区分。
3. 本地 token estimate 与 Provider 最终 serialization/tokenization 存在误差，裸 estimate 低于某个 input limit 不能作为数学精确的硬安全依据。
4. Provider overflow 发生后再处理太晚，而且不能用 overflow 反推窗口。
5. 当前 `/compact` 与 overflow compact 没有生产 summarizer。
6. 单层 Projection 无法同时表达：
   - raw Transcript 的长期事实；
   - Fine semantic timeline；
   - 老化后的 epoch macro summary；
   - crash-safe checkpoint commit。
7. 大窗口场景下一次 semantic compact 不能无限扩成超大模型调用，需要 bounded multi-epoch catch-up。
8. 当前 terminal-only durable semantic facts 不足以支撑“崩溃后从已闭合事实重新推导 compact 进度”。
9. 模型看见 Timeline summary 后，需要一个 exact-ref 的 current-Session 原始证据回读入口。

---

## 4. 任务目标

### 4.1 最终交付

完成后形成以下正式请求链：

```text
 user configured input? ───────┐
 reliable Provider max input? ─┼──► effective operating input limit
 Provider max output? ─────────┤
 Provider combined limit? ─────┘      （各维独立、unknown 不伪造）
                                   │
User / Tool / Resume ──► assemble final candidate request
                                   │
                                   ▼
                 Pressure / Preflight Resolver
                                   │
                      ┌────────────┴────────────┐
                      ▼                         ▼
                  Auto Gate                 Hard Gate
               proactive pressure        request safety
                      │                         │
                      └────────────┬────────────┘
                                   ▼
                              L1 → L2 → L3
                                   │
                         pressure still high?
                              │          │
                             no         yes
                              │          ▼
                              │         L4
                              │     bounded epoch
                              │          │
                              │    B′ 1..N catch-up
                              │          │
                              └────┬─────┘
                                   ▼
                              rebuild request
                                   │
                                   ▼
                              Hard Gate safe?
                               │          │
                              yes         no
                               │          │
                               ▼          ▼
                            Provider    fail closed
```

长期持久事实链改为：

```text
transcript.jsonl
  └─ raw durable closed semantic facts
             │
             ├────────────► HistoryRead
             │
             ▼
        L4 / L5 evidence

timeline.jsonl
  ├─ SemanticEntry
  ├─ EpochMacroSummary
  └─ ActiveCheckpoint   ← 每个成功 L4/L5 transaction 最后一条
             │
             ▼
        logical Timeline
             │
             ▼
       ContextCompiler
```

### 4.2 冻结决策 D1：Compact 复用当前主模型 / Provider

自动 L4/L5 发生在 active Turn 内时：

```text
使用该 Turn 已冻结的 Provider / model / 分维 limits snapshot
```

idle 状态手动 `/compact`：

```text
使用 Application 当前选中的 Provider / model / 分维 limits
```

Compact 请求：

```text
独立 Prompt
独立 GenerationRequest
独立 input/output budget
tools = ()
```

禁止：

```text
compaction_model
隐式切换大窗口模型
跨 Provider fallback
把 Compact 当普通 Agent Tool loop
```

### 4.3 冻结决策 D2：B′ bounded catch-up，无 Compact FSM

一次 Context reduction orchestration 可以执行：

```text
1..N 个 bounded complete raw L4 epoch
```

每批：

```text
derive bounded raw epoch
        ↓
tool-free L4 model call
        ↓
validate
        ↓
append SemanticEntry...
        ↓
append ActiveCheckpoint LAST
        ↓
rebuild
        ↓
Auto Gate + Hard Gate
```

只允许进程内局部变量：

```text
attempt_count
previous_estimate
previous_coverage
current_epoch
cancellation
```

禁止持久：

```text
CompactState
CompactionJob
next_epoch_pointer
COMPACTING_BATCH_N
compact coroutine position
后台 Compactor
```

Crash 后只依赖：

```text
Transcript + latest valid ActiveCheckpoint
```

重新推导下一未覆盖 epoch。

### 4.4 冻结决策 D3：Auto Gate 与 Hard Gate 分离

#### 4.4.1 模型限制来源与分维语义

模型限制只能来自：

```text
C_user?       = 用户显式配置的 operating input limit
P_input?      = 可靠 Provider runtime max input
P_output?     = 可靠 Provider runtime max output
P_combined?   = Provider 明确定义的 combined-context limit
O_request     = 本次最终 GenerationRequest 的 requested output reserve
```

当前调用的有效输入运行上限为所有已知 input 上限中的更紧者：

```text
C_effective = min(available C_user, P_input)
```

若 `C_user` 与 `P_input` 都缺失，则当前模型不能发送请求，必须明确 fail closed；不得回退到固定 258K、型号名推断、bundled table 或本地 catalog。

配置权威规则：

- 用户配置是可信项目上限来源；项目配置只有在用户已经配置 `context_window` 时才能保持或收紧，不能补造缺失值或放大用户值；
- Provider metadata 只能收紧已配置 limit，或在用户未提供时为当前运行建立可靠 input limit；
- `P_input`、`P_output`、`P_combined` 是不同物理维度，unknown 保持 unknown，不压扁为一个 `E`；
- Provider overflow 是最终外部裁决，不得反向学习、缓存或修改任何 limit；
- 取消 bundled official model metadata 路线，不登记为未来能力欠账。

#### 4.4.2 Hard Gate：请求安全边界

每一个真实 Provider Model Call 发送前必须经过 Hard Gate，包括：

```text
initial ordinary call
post-tool call
post-resume call
manual compact 内部 model call
L4 model call
L5 model call
overflow retry
```

Hard Gate 基于**最终将发送的完整 `GenerationRequest`**，由 Preflight Safety Count/Estimate 至少覆盖：

```text
instruction + messages + tools + known framing 的 input count/estimate
requested output reserve
集中定义的 counting / serialization safety allowance
```

按维度独立判断：

```text
input_estimate + allowance <= C_effective
O_request <= P_output                     （仅 P_output 已知时）
input_estimate + allowance + O_request <= P_combined
                                              （仅 P_combined 已知时）
```

任一已知维度不满足，或 `C_effective` 无法建立，则：

```text
Provider call count = 0
必须 reduction 或 fail closed
```

Hard Gate 是发送前的 fail-closed guard，但 local/Provider count 可能仍是估计值；不得把它宣传为数学精确，也不得实现为：

```text
used >= 90% * C_effective
```

也不得把：

```text
local estimate < C_effective
```

直接等价为 safe。

Provider-side token count 可作为更高可信度输入，但仍须记录来源并应用集中 safety allowance；Provider 实际 overflow 继续保持最终权威。

#### 4.4.3 Auto Gate：proactive Context Pressure

定义：

```text
AutoGate = C_effective - R

R = adaptive working headroom
```

`R` 的长期产品约束：

1. 小窗口时自动缩小；
2. 随 `C_effective` 增长可缓慢增大；
3. 大窗口有绝对上限；
4. 不按固定百分比无限线性增长；
5. 1M Context 不因统一 90% 规则固定损失约 100K；
6. 25K Context 不照搬 16K/20K 大窗口 reserve 把主工作区挤死。

具体公式和默认值属于**单点定义的内部 policy**，不是公共 API、用户配置子系统或长期协议。

测试验收产品不变量，不把某一个 tuning 数字变成长期契约。

#### 4.4.4 自动 Reduction 顺序

```text
assemble final candidate request
        ↓
resolve dimensioned limits / output reserve / allowance / R
        ↓
Auto Gate
        │
        ├─ below Auto Gate
        │      ↓
        │   Hard Gate
        │      ├─ safe   → send
        │      └─ unsafe → mandatory reduction / fail closed
        │
        └─ above Auto Gate
               ↓
             L1-L3
               ↓
             rebuild
               ↓
          Auto Gate again
               │
               ├─ pressure cleared
               │      ↓
               │   Hard Gate
               │      └─ safe → send
               │
               └─ still pressure
                      ↓
                     L4
                      ↓
               checkpoint commit
                      ↓
                   rebuild
                      ↓
               Auto + Hard Gate
                      ↓
                 B′ 1..N
```

必须满足：

```text
C_effective = 258K（仅为测试输入，不是默认值）
L1-L3: 259K → 257K
257K 仍高于 Auto Gate

=> 继续 L4
=> 不得因为已经低于 Hard Limit 就擦边发送
```

反之：

```text
L1-L3 已降到 Auto Gate 以下
且 Hard Gate safe

=> 不执行有损 L4
=> 直接发送
```

#### 4.4.5 Auto Pressure 无法完全清除时的最终行为

Auto Gate 是 proactive policy，不是第二个安全边界。

因此 finite L4/B′ 已触发 no-progress、no-safe-epoch 或 repeated-failure breaker 后：

```text
Auto pressure 仍存在
+
Hard Gate safe

=> 允许发送当前请求
=> diagnostics 记录 auto_pressure_unresolved + 原因
```

若：

```text
Hard Gate unsafe
```

则：

```text
绝不发送
=> context_unresolvable / fail closed
```

不得因为 Auto Gate 治理失败，把一个 Hard-safe 请求永久阻断；也不得因为 Hard-safe 就跳过原本应执行的 proactive L4 尝试。

### 4.5 L4 retained target

L4 一旦真正执行，不以“刚好低于 Auto Gate 几个 token”为目标。

继续使用 bounded retained profile：

```text
A = active evidence budget
F = fine timeline budget
U = uncompressed recent tail budget
retained target
retained hard cap
```

要求：

- 大窗口以绝对 retained budget 为主，不随 1M C 线性膨胀；
- 小窗口 A/F/U 与 compaction budget 联动收缩；
- bounded L4 epoch input 有绝对 cap；
- 一次 L4 后应形成可继续工作的明显 headroom；
- 具体 default 属于内部可 Eval 调优 policy。

### 4.6 Manual `/compact`

手动 `/compact`：

```text
不依赖 Auto Gate trigger
```

用户即使位于低 pressure 区也可主动请求 Compact。

但：

```text
无完整可压缩 epoch
或没有实际 reduction 价值

=> successful no-op
=> 不追加垃圾 Timeline record
=> 不追加无意义 ActiveCheckpoint
```

Manual 与 Auto 使用同一个 Application Context Orchestrator。

### 4.7 L5 Timeline Aging

L5 有独立 pressure source：

```text
Fine Timeline logical usage > F
=> 可独立触发 L5
```

L5 不要求普通请求先超过 Auto Gate。

L5 只能重新读取 raw Transcript evidence，禁止 summary-of-summary。

### 4.8 Overflow fallback

Provider-side count 仍可能与实际生成请求存在小幅误差。

普通 Agent 请求首次收到规范化 `ContextOverflowError` 时：

```text
forced reduction
→ rebuild final request
→ Hard Gate
→ 最多 retry 1 次
```

第二次仍 overflow：

```text
直接失败
不继续探测
不修改任何 limit facts
不动态猜测或反向学习窗口
```

Compact 内部模型请求不得递归启动另一套 Compact。若其 bounded request 仍 overflow，应作为当前 L4/L5 attempt 的受控失败或重新选择更小 safe epoch；禁止形成递归 compaction loop。

---

## 5. 能力欠账

### 5.1 本任务回补的既有能力欠账

当前 `docs/OutstandingDebtList.md` 已把尚未实现的 T09 Context 能力列为欠账。本任务自然回补：

| 来源 | 本任务回补内容 |
| --- | --- |
| T09 Prompt / Context Engineering | 用户显式 Context Window、可靠 Provider runtime limits、分维 input/output/combined contract 与自适应 Working Budget |
| T09 Prompt / Context Engineering | 正式 tool-free Compaction model use case、复用既有 awaitable hook、取消、失败与一次 overflow retry |
| T09 Prompt / Context Engineering | small-window / large-window adaptation、Operating Profile、Working Set、trigger、recent tail 与 safety headroom |

### 5.2 本任务新增能力欠账

无。

以下内容属于明确 Out of Scope 或独立后续能力，不登记为 T09-1 新欠账：

```text
Persistent Runtime Recovery
Memory / Evidence Retrieval
Artifact Store GC
Timeline physical GC
后台 Context Agent
独立 compaction model
```

“维护 bundled official model metadata”路线已由用户取消，并已从滚动欠账中移除；T08 只需确认该路线在源码、测试、当前事实文档和欠账清单中继续不存在，且未重新登记为 future debt。

T08 必须重新盘点所有被 T09-1 实际改变的现有欠账，至少包括 `T02 Slash Command / TUI`、`B01 私有测试集 v0` 与上表三条 T09 Context 欠账。统一按真实验收结果处理：已完全回补则删除；部分改变则只更新内容或触发条件；仍成立则保留；用户明确取消则删除且不得转登记。三条 T09 Context 欠账只有在实现完成、对应 Checklist 完成且 Feedback 有真实验收记录后才允许删除。

---

## 6. 核心产品行为

| 场景 | 输入 / 前置状态 | 预期行为 | 状态变化 | 对外结果 |
| --- | --- | --- | --- | --- |
| 普通请求低于 Auto Gate | final request 已组装，Auto safe | 直接进入 Hard Gate | 无 Timeline 变化 | Hard safe 后发送 |
| Auto pressure，但 L1-L3 足够 | deterministic reduction 后低于 Auto Gate | 不执行 L4 | Transcript 不变 | Hard safe 后发送 |
| L1-L3 只降到 Hard Limit 以下 | 仍高于 Auto Gate | 继续 L4 | 可产生 Timeline transaction | 不擦边发送 |
| Hard Gate unsafe | 任一已知 input/output/combined 维度失败或 input limit 无法建立 | Provider 不得调用 | 可先 reduction；无法解决则无语义提交 | fail closed |
| local estimate 与 Provider count 不同 | Provider 提供 count | 优先 provider estimate，并加对应 uncertainty | 诊断记录 count source | 再做 Auto/Hard 判断 |
| Provider count 不可用 | capability 缺失或受控失败 | 用 deterministic conservative estimate + 更保守 uncertainty | 无 | 不伪造 exact count |
| reliable input < user limit | Provider 能证明较小 max input | effective input 收紧 | Turn limits snapshot 固定 | 不按更大用户值发送 |
| 用户与 Provider input 都未知 | 无可证 input limit | 不组装可发送请求 | 无 | 明确 fail closed |
| Provider output/combined 未知 | 无可靠 metadata | 只跳过未知维度，不伪造值 | diagnostics 标记 unknown | 仍执行已知 input Gate |
| 小窗口模型 | C≈25K | R、A/F/U、Compact input/output budget 同步收缩 | policy 变化 | 不被大窗口 reserve 挤死 |
| 大窗口模型 | C≈1M | R 有绝对 cap；retained profile 不线性放大 | 无提前强压缩 | 可真正使用大窗口 |
| L4 单 Epoch 足够 | Auto pressure 经 L1-L3 未清除 | bounded raw epoch → SemanticEntry → checkpoint | Timeline append | rebuild 后继续 |
| B′ 多 Epoch | 一个 epoch 仍未达到治理目标 | 连续 1..N bounded epoch，每批 commit 后 re-gate | 多个独立 committed epoch | 达到 retained target 或 breaker |
| Auto pressure unresolved 但 Hard safe | finite breaker 已触发 | 不继续无限 compact | diagnostics 记录 unresolved | 允许发送 |
| Auto pressure unresolved 且 Hard unsafe | 无 safe reduction | 不发送 | 无伪 checkpoint | `context_unresolvable` |
| L4 model call 取消 | cancellation | 不提交 candidate/checkpoint | 无 | cancelled / compact failure |
| L4 parse/coverage 失败 | summary 不满足 schema | candidate 无效 | 不提交 | 受控失败 |
| L5 Fine pressure | Fine Timeline > F | 选旧 complete epoch，重读 raw refs | macro + checkpoint | logical Fine 回到预算 |
| L5 raw evidence 本身放不下 | 无 safe epoch | 不做 summary-of-summary、不换模型 | 无 | `no_safe_epoch` |
| 手动 `/compact` 有价值 | 即使低于 Auto Gate | 同一 orchestrator force reduction | 正常 Timeline commit | success |
| 手动 `/compact` 无候选 | 无完整 epoch或无 reduction value | safe no-op | 不写 Timeline | success no-op |
| 首次 Provider overflow | preflight 曾认为安全 | forced reduction + rebuild + Hard Gate + retry 1 次 | 可正常产生 Timeline commit | 成功或二次 overflow |
| 第二次 Provider overflow | retry 仍 overflow | 停止 | 不学习或修改任何 limit facts | 规范化失败 |
| Crash 在 L4/L5 model call 中 | checkpoint 未提交 | 重启只认旧 checkpoint | 本批无效 | 从 raw evidence 重推 |
| Crash 在 entries 后 checkpoint 前 | trailing records 已落盘 | loader 忽略未闭合 transaction | 旧 checkpoint 仍 authority | 无 rollback FSM |
| Resume v2 | Transcript + Timeline valid | 恢复 durable closed facts，创建 fresh Run | 不恢复 old active Turn | 继续 Session |
| Resume v1 | 旧 `history.jsonl` schema | deterministic incompatible | 不迁移 | 明确拒绝 |
| HistoryRead 成功 | active Session opaque TranscriptRef | bounded exact raw read | 无 | 返回 bounded page |
| HistoryRead 伪 ref / 跨 Session | ref ownership 不匹配 | fail closed | 无 | 不泄露数据 |
| Fine Timeline 低于 F、普通请求低 pressure | 无治理需要 | 不调用 L4/L5 | 无 | 零额外 model call |

---

## 7. 架构归属

| 能力 | 所属模块 | 状态所有者 | 调用方 | 依赖方向 | 原因 |
| --- | --- | --- | --- | --- | --- |
| Transcript / Timeline value contract | Core | 无持久 IO；只定义 immutable semantic values | Application / Session Integration | Application/Integration → Core | Provider-independent 产品语义 |
| configured operating input limit | Application configuration | `ModelProfile` | Application budget resolver | Integration config → Application | 用户可显式配置；项目只能保持/收紧 |
| Provider reliable limits | Core capability contract + Integration implementation | Provider adapter/cache | Application | Application → Core contract；Integration → Core | SDK/network 截止在 Integration |
| Provider token count | Core capability contract + Integration implementation | 无长期状态 | Application Hard Gate | Application → Core contract；Integration → Core | 对最终 Provider request 做高可信度 estimate |
| Working Headroom policy | Core Context pure policy | 无业务状态 | Application Context Orchestrator | Application → Core | 纯确定性 Provider-independent 预算数学 |
| Auto Gate / Hard Gate decision | Core value/pure calculation + Application orchestration | 单次 request preparation | Application | Application → Core | Core 表达稳定 gate 语义，Application 决定何时执行 reduction |
| ContextCompiler | Core | 无可变业务状态 | ApplicationContextService | Application → Core | 唯一 model-view builder |
| L1-L3 | Core deterministic policy + Application loop | 单次 prepare | Application | Application → Core | 不需要 Provider |
| L4/L5 orchestration | Application Context | 单次 reduction loop | Auto Gate / manual compact / aging | Application → ProviderPort | 需要 async model call、cancel、persistence |
| B′ catch-up | Application Context | 仅局部变量 | L4 orchestrator | Application | 明确禁止持久 FSM |
| Transcript / Timeline files | Integration Session Store | Session writer | Application Session Service | Application → Integration → Core models | fsync/lock/recovery 属于 Integration |
| closed semantic fact commit cadence | Application | process-local durable cursor | request preparation / terminal tail | Run/Application → Session writer | 这是编排时机，不是 Core checkpoint |
| HistoryRead | Integration Tool + Application Tool composition | active Session Transcript | Agent Tool runtime | AgentLoop → Tool → active Session | exact evidence read，不是 Memory |
| `/compact` | Application Command | 无独立 Compact state | Interface | Interface → Application | Interface 不拥有 Context |
| diagnostics | Application | bounded safe projection | Interface / Eval | Application → Interface/Eval | 不泄露正文 |

### 7.1 允许新增的最小 Provider contracts

现有 `ProviderPort` 不足以表达“可选 reliable limits”和“可选 structured token count”，允许在 `core/provider.py` 增加有当前真实调用方的 UthCode-owned contract，例如：

```text
ModelLimits
  max_input_tokens?
  max_output_tokens?
  max_combined_tokens?
  source

ContextCountEstimate
  input_tokens
  source
  kind = pressure_estimate | preflight_provider_count | preflight_local_estimate
  safety_allowance

SupportsModelLimits
  resolve_model_limits(model) -> ModelLimits?

SupportsInputTokenCount
  count_input_tokens(request) -> TokenCountEstimate
```

最终私有函数/协议名可遵循现有命名风格微调，但语义必须保持。

禁止把这些能力强行塞成所有 Provider 必须实现的方法；没有可靠 metadata 时保留 unknown。只有用户已显式配置 input limit 时才能配合 local estimate 继续，否则 fail closed。

---

## 8. 外部参考结论

| 来源 | 研究问题 | 可借鉴机制 | UthCode 处理 |
| --- | --- | --- | --- |
| Pi Coding Agent 官方 Compaction 文档 | 自动 compact 是否保留 absolute reserve | `contextTokens > contextWindow - reserveTokens`；manual `/compact` 独立可触发 | 只借鉴“绝对 working reserve”和 manual 独立语义；不照搬 16K/20K 默认值 |
| OpenCode 当前 Compaction 文档 | pre-send pressure 如何算 | 在 model call 前估 final system/messages/tools，并以 context limit 减 output/buffer 判断；compact 后重建请求；overflow recovery 单步有限 | 简化后采用“最终请求 preflight + absolute buffer + rebuild”；UthCode 使用独立 Auto/Hard Gate |
| Codex 当前 Context Window 源码 | auto compact 与 hard context 是否分层 | 源码明确把 full model context 作为 hard cap，独立于 auto-compaction scope/limit | 采用分层语义；不采用其 90% 派生规则 |
| Anthropic Token Counting | Provider count 是否绝对精确 | endpoint 接受与 Messages 创建相同的结构化 inputs，但官方仍称 token count 为 estimate，实际 input tokens 可能小幅不同 | 采用 Provider count 作为高可信度 estimate，仍保留 uncertainty |
| Anthropic Models API | 是否能可靠取得模型限制 | 当前 API 返回 `max_input_tokens`、`max_tokens` | Anthropic Integration 可提供 reliable physical ceiling；转换为 Core DTO 后再给 Application |

额外约束：

- UthCode 不因为 Anthropic 能动态查询，就要求 OpenAI / OpenAI-compatible 伪造相同能力；
- 用户显式 `ModelProfile.context_window` 与可靠 Provider runtime input metadata 至少一项存在，才能建立 operating input limit；
- Provider metadata 是可验证的运行时安全证据，input/output/combined 三维不互相替代；
- 本任务取消 bundled official metadata，不建立 Model Catalog、型号表、自动联网枚举 UI 或模型注册中心。

---

## 9. 目标目录树

以下只列当前任务真实需要修改、增加或明确纳入验收的文件。

```text
src/uthcode/
├─ core/
│  ├─ __init__.py                                  [修改]
│  ├─ agent.py                                     [验收，原则上不修改]
│  ├─ context.py                                   [修改]
│  ├─ history.py                                   [修改]
│  ├─ prompt.py                                    [修改]
│  └─ provider.py                                  [修改]
│
├─ application/
│  ├─ bootstrap.py                                 [修改]
│  ├─ configuration.py                             [修改]
│  ├─ context.py                                   [修改]
│  ├─ generation.py                                [修改]
│  ├─ history.py                                   [修改]
│  ├─ sessions.py                                  [修改]
│  ├─ tools.py                                     [修改]
│  └─ commands/
│     ├─ builtins.py                               [修改]
│     ├─ dispatcher.py                             [修改]
│     └─ models.py                                 [修改]
│
├─ integrations/
│  ├─ config/
│  │  ├─ loader.py                                 [修改]
│  │  └─ template.py                               [修改]
│  ├─ providers/
│  │  └─ anthropic.py                              [修改]
│  ├─ session_files.py                             [修改]
│  └─ tools/
│     └─ history_read.py                           [新增]
│
└─ interfaces/
   └─ tui/
      └─ app.py                                     [修改，仅 async command adaptation]

eval/
└─ metrics.py                                      [修改]

tests/
├─ test_agent_loop.py                              [修改]
├─ test_anthropic_integration.py                   [修改]
├─ test_application_runtime.py                     [修改]
├─ test_application_runs.py                        [修改]
├─ test_application_tools.py                       [修改]
├─ test_architecture_boundaries.py                 [修改]
├─ test_command_dispatcher.py                      [修改]
├─ test_config_contract.py                         [修改]
├─ test_configuration.py                           [修改]
├─ test_context_budget_gate.py                     [新增]
├─ test_context_compaction.py                      [修改]
├─ test_context_compiler.py                        [修改]
├─ test_history_contract.py                        [修改]
├─ test_history_read_tool.py                       [新增]
├─ test_provider_model_limits.py                   [新增]
├─ test_session_files.py                           [修改]
├─ test_t09_1_context_protocol_e2e.py              [新增]
├─ test_timeline_contract.py                       [新增]
├─ test_tool_result_persistence.py                 [修改]
├─ test_tui.py                                     [修改]
├─ test_w04_session_commands.py                    [修改]
├─ test_w05_diagnostics.py                         [修改]
└─ test_w06_integration_delivery.py                [修改]

docs/
├─ Context-Index.md                                [修改]
├─ Tools.md                                        [修改]
├─ core-design/
│  └─ T09-context-engineering.md                   [修改]
├─ context/
│  ├─ A03-State/
│  │  └─ State-Context.md                          [修改]
│  └─ A04-Orchestration/
│     └─ Orchestration-Context.md                  [修改]
└─ user-manual/
   ├─ commands.md                                  [修改]
   └─ configuration.md                             [修改]
```

默认保持不动：

```text
src/uthcode/integrations/providers/openai_responses.py
src/uthcode/integrations/providers/openai_compat.py
src/uthcode/integrations/config/data.py
```

它们不得为了“接口统一”伪造可靠 window metadata。只有编码时出现纯机械 typing/conformance 必要，且不改变产品语义时，才允许随调用链做最小修改。

---

## 10. 文件级任务清单

| 文件路径 | 操作 | 文件职责 | 核心改动 | 输入 | 输出 | 禁止事项 | 对应测试 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `core/history.py` | 修改 | raw Transcript 与 derived Timeline Core contract | `TranscriptEntry/Transcript/TranscriptRef/SemanticEntry/EpochMacroSummary/ActiveCheckpoint/Timeline`；删除 Projection 生产 authority | closed semantic facts | immutable values | fs、SDK、兼容 alias | history/timeline |
| `core/context.py` | 修改 | dynamic budget、Gate、deterministic reduction、Compiler | 去除固定 258K invariant；定义分维 limits、R/A/F/U、Pressure/Preflight、Auto/Hard、L1-L3 | typed sources + budget | snapshot / gate / reduction plan | Provider SDK/network | compiler/budget |
| `core/prompt.py` | 修改 | Context source authority | Transcript/Timeline source kinds；保持 summary 为 conversation/history authority | typed sources | ContextBlock | 将 summary 升级为 System | compiler |
| `core/provider.py` | 修改 | SDK-neutral Provider contracts | `ModelLimits`、token-count estimate、可选 capability contract | model/request | UthCode DTO | SDK type | provider limits/architecture |
| `core/agent.py` | 验收，原则上不修改 | ReAct behavior loop | 复用现有 sync/awaitable request preparer 与 overflow hook；只回归 typing/cancel/error | messages/tools | provider request | 重复 async protocol、Timeline/Budget ownership | agent/application runs |
| `core/__init__.py` | 修改 | Core exports | 新 contract export，移除失效 Projection export | - | imports | legacy alias | import/architecture |
| `application/history.py` | 修改 | Message → durable Transcript | 只生成完整 closed semantic unit；保持 ToolCall/Result 原子性 | Message | TranscriptEntry | open fragment | history/runs |
| `application/context.py` | 修改 | Context 总编排 | resolve configured/provider/effective input、output/combined、count/allowance/R；Auto/Hard；L1-L5；B′ | frozen Turn limits + Session facts + Provider capability | safe request / compact result | SDK、持久 FSM | gate/compaction/e2e |
| `application/configuration.py` | 修改 | operating model profile | optional positive `context_window`；user authority 与 project tighten-only contract | config | configured input limit? | fixed/bundled fallback | configuration |
| `application/generation.py` | 修改 | Turn snapshot 与正式 Provider path | 冻结分维 limits；复用 awaitable prepare；closed Transcript；manual compact；一次 overflow retry；status | Run/Turn | Agent execution/diagnostics | Context state 下放 AgentLoop | runtime/runs/e2e |
| `application/sessions.py` | 修改 | Session use-case | Transcript/Timeline snapshot、append、checkpoint transaction outcome | Core records | durable outcome | runtime checkpoint | session/e2e |
| `application/tools.py` | 修改 | Tool composition | reserved `HistoryRead`；active Session reader；自身 bounded output 不递归外置 | TranscriptRef | ToolResult | cross-session/search | tool/history-read |
| `application/bootstrap.py` | 修改 | composition root | Provider optional capabilities、Session、HistoryRead wiring | EffectiveConfig | Application | SDK 泄露到 Application type | runtime |
| `commands/builtins.py` | 修改 | `/compact` `/status` | async compact；success/no-op/failure；分维 limits/Auto/Hard diagnostics | Application | outcome text | fixed 258K 文案 | commands |
| `commands/dispatcher.py` | 修改 | command execution | 增加最小 awaitable handler dispatch；保留 sync handler | handler | CommandOutcome | Context orchestration | dispatcher/tui |
| `commands/models.py` | 修改 | command typing | handler 支持 sync/awaitable result | handler | type contract | Context logic | dispatcher |
| `config/loader.py` | 修改 | TOML validation/overlay | optional positive `context_window`；项目只能保持/收紧用户已有值，不能补造 | TOML | LoadedConfigData | provider redirect/limit enlargement | config |
| `config/template.py` | 修改 | first-run template | 明确用户 `context_window` 显式配置与 Provider reliable fallback 语义 | - | template | bundled/default window | config |
| `providers/anthropic.py` | 修改 | Anthropic adapter | Models API limits + Messages count_tokens；转换为 Core DTO | remote model / GenerationRequest | limits/count estimate | SDK type 越界 | anthropic/provider limits |
| `session_files.py` | 修改 | Session v2 durable files | `transcript.jsonl` + `timeline.jsonl`；checkpoint recovery；old schema reject | Core records | snapshot | dual read/write/migration | session |
| `tools/history_read.py` | 新增 | raw Transcript exact-ref reader | opaque ref validation、current Session ownership、bounded page | ref/offset/limit | bounded page | arbitrary path/search | history-read |
| `interfaces/tui/app.py` | 修改 | async command adaptation | await Application dispatcher；不新增 Context 语义 | command outcome | UI projection | Budget/Timeline ownership | tui |
| `eval/metrics.py` | 修改 | Eval safe diagnostics consumer | 消费 Gate/Timeline/pressure 字段，不依赖 Projection/258K | public diagnostics | existing metrics | raw context text/new total score | diagnostics fixture |
| `docs/**` | 修改 | 用户与开发者文档 | 同步分维 limits、Pressure/Preflight、Auto/Hard、Transcript/Timeline、HistoryRead、config、commands | implemented facts | docs | 把规划写成现状 | doc checks |

---

## 11. 关键数据结构与状态

### 11.1 ModelProfile

```text
ModelProfile
  model_ref
  provider_profile_id
  remote_id
  display_name?
  context_window: positive int?  # 用户显式 operating input limit
  max_output_tokens?
  reasoning_effort?
```

`context_window` 若存在，只能来自用户显式配置；项目配置只能保持/收紧用户值。用户值可缺省，但只有可靠 Provider input metadata 能补足本次运行 limit；两者皆无时模型不可发送，不得回退到 258K 或型号表。

### 11.2 ModelLimits

```text
ModelLimits
  max_input_tokens?
  max_output_tokens?
  max_combined_tokens?
  source
```

语义：

- 来自 Provider 可验证 metadata；
- 三个字段分别保持 Provider 声明的 input、output、combined 语义；
- `max_input_tokens` 只能收紧更小的用户值，不能扩大它；
- `max_output_tokens` 校验/收紧本次 output reserve；`max_combined_tokens` 只在 Provider 明确定义 combined 语义时参与；
- 不存在可靠值时返回 absent，而不是猜值。

### 11.3 Pressure Estimate 与 Preflight Safety Count/Estimate

```text
ContextCountEstimate
  input_tokens
  source
  kind:
    pressure_estimate
    preflight_provider_count
    preflight_local_estimate
  safety_allowance
```

Pressure Estimate 服务 Auto Gate，不是发送安全证明。Preflight count/estimate 基于最终 request 服务 Hard Gate；即便来自 Provider count API，也只记录更高可信来源而不宣称数学精确。Application 根据来源在单点 policy 选择 safety allowance。

### 11.4 ContextBudget

建议最终 Core contract 表达：

```text
ContextBudget
  configured_input_limit?
  provider_max_input?
  effective_input_limit
  provider_max_output?
  provider_combined_limit?

  requested_output_reserve
  safety_allowance

  working_headroom = R
  auto_gate_limit = effective_input_limit - R

  active_evidence_budget = A
  fine_timeline_budget = F
  uncompressed_tail_budget = U

  retained_target
  retained_hard_cap

  compaction_input_budget
  compaction_output_reserve
```

约束：

```text
effective_input_limit 来自至少一个已知 input limit
若 user/provider input 同时存在，effective_input_limit <= 两者
0 < R < effective_input_limit
auto_gate_limit < effective_input_limit
known output/combined limit 按各自维度独立成立
A/F/U/compact budget 均必须能在小窗口中退化
retained profile 对大 C 以 absolute cap 为主
```

第一版大窗口可以继续采用 T09 探索中验证过的“约 48K active evidence + 约 16K Fine Timeline + bounded recent tail”作为内部 tuning 起点，但这些具体数字不是公开协议；编码时必须集中在一个 policy 定义点。

### 11.5 GateDecision

```text
GateDecision
  input_tokens
  count_source
  requested_output_reserve
  safety_allowance
  preflight_input_usage

  auto_pressure: bool
  hard_safe: bool

  auto_gate_limit
  effective_input_limit
  provider_output_limit?
  provider_combined_limit?
  input_safe
  output_safe
  combined_safe
  reason
```

关系必须可直接测试：

```text
auto_pressure = input-side working usage > auto_gate_limit
hard_safe = input_safe && output_safe && combined_safe
```

Auto 与 Hard 可以出现：

```text
auto_pressure = true
hard_safe = true
```

这正是 proactive reduction 场景。

### 11.6 Transcript

```text
TranscriptEntry
  schema_version
  session_id
  sequence
  turn_id
  kind
  payload
  created_at
  semantic_unit_id?
  commit_boundary
```

Transcript 是当前 Session 的 raw durable semantic fact authority。

只允许持久：

- 已闭合 User message；
- 完整 Assistant text/final；
- 完整 ToolCall + matched ToolResult semantic group；
- 其它当前已有且可判定闭合的语义事实。

禁止持久：

- streaming fragment；
- unmatched ToolCall；
- pending Provider coroutine；
- Permission/AskUser waiter；
- active Turn continuation。

### 11.7 TranscriptRef

```text
TranscriptRef
  session ownership
  sequence_start
  sequence_end
```

对模型暴露 opaque ref。

Integration 解析后必须再次校验：

```text
active Session
range validity
complete semantic boundary
```

### 11.8 Timeline

Timeline 物理 append-only，产品 record 只允许三类：

```text
SemanticEntry
  turn_id
  summary
  refs

EpochMacroSummary
  turn_id
  summary
  refs
  coverage

ActiveCheckpoint
  turn_id
  active_turns
```

不得增加第四种：

```text
CompactEpochRecord
CompactionJobRecord
```

### 11.9 Compact Epoch

Compact Epoch 是逻辑概念：

```text
previous ActiveCheckpoint
        ↓
SemanticEntry A
SemanticEntry B
SemanticEntry C
        ↓
new ActiveCheckpoint
```

两 checkpoint 之间本批新增的 Fine entries 构成一个 complete epoch。

### 11.10 ActiveCheckpoint：唯一 durable Compact commit

一次成功 L4/L5 transaction：

```text
derived records
...
ActiveCheckpoint   # 必须最后写
```

loader：

```text
physical timeline
      ↓
latest valid ActiveCheckpoint
      ↓
committed logical view
```

checkpoint 后不存在的 trailing records：

```text
incomplete transaction
=> 不生效
```

### 11.11 B′ 无持久状态

以下只存在于当前 Application 调用栈：

```text
attempts
previous_estimate
previous_coverage
current_epoch
cancellation
```

不进入：

```text
RunState
Transcript
Timeline
runtime.jsonl
```

---

## 12. 依赖与数据流

### 12.1 普通 Provider Call

```text
AgentLoop
   │
   │ await request_preparer(...)
   ▼
Application Context Orchestrator
   │
   ├─ frozen Turn model / dimensioned limits
   ├─ current Transcript / Timeline
   ├─ optional Provider ModelLimits
   ├─ final GenerationRequest assembly
   ├─ Pressure Estimate / Preflight provider count or local estimate
   ├─ resolve effective input / output / combined / R / A / F / U / allowance
   ├─ Auto Gate
   ├─ L1-L3
   ├─ L4/B′ if proactive pressure remains
   └─ Hard Gate
           │
           ▼
      safe GenerationRequest
           │
           ▼
        AgentLoop
           │
           ▼
       ProviderPort
           │
           ▼
  Integration SDK adapter
```

Provider SDK 类型不得越过 Integration。

### 12.2 Hard Gate 的 count 位置

必须对**最终 Provider-visible request**计数：

```text
GenerationRequest
├─ system_prompt
├─ messages
├─ tools
├─ model
├─ reasoning / other known request params
└─ requested max output
```

Provider 支持 `count_input_tokens` 时：

```text
Application
  -> Core capability
  -> Integration serializes according to provider protocol
  -> remote/provider count
  -> UthCode TokenCountEstimate
```

Provider 不支持时：

```text
Application
  -> deterministic canonical representation
  -> local estimator
  -> larger uncertainty allowance
```

不得在 ContextCompiler 尚未形成最终 request 前拿“历史正文 token”冒充最终 Provider request count。

### 12.3 Auto Gate 与内部 Compact call

Auto Gate 只驱动普通 Context 治理。

L4/L5 自己的 tool-free model request：

```text
bounded compact request
      ↓
Hard Gate
      ↓
Provider
```

不得让 Compact request 再进入 Auto Gate 后递归触发 L4。

### 12.4 closed semantic fact persistence

复用“每次下一 Provider call 都经过 Application prepare”这一事实：

```text
before first Provider call
  └─ current user message 已闭合
       → append Transcript if not durable

after Tool batch, before next Provider call
  └─ Assistant ToolCall + matched ToolResult group 已闭合
       → append Transcript

terminal Turn
  └─ final Assistant tail
       → append remaining closed facts
```

Application 保持 process-local durable cursor / identity reconciliation。

这不是 Runtime checkpoint。

### 12.5 L4

```text
Auto pressure remains
        ↓
derive next uncovered bounded raw epoch
        ↓
read raw Transcript evidence
        ↓
build tool-free request
        ↓
Hard Gate(compact request)
        ↓
same frozen provider/model/dimensioned limits
        ↓
parse + validate
  - contiguous coverage
  - refs exist
  - one SemanticEntry per covered Turn
  - bounded summary
        ↓
append SemanticEntry...
        ↓
append ActiveCheckpoint LAST
        ↓
rebuild ordinary request
        ↓
Auto Gate + Hard Gate
```

### 12.6 L5

```text
logical Fine Timeline > F
        ↓
select old complete Compact Epoch
        ↓
resolve Transcript refs
        ↓
read RAW evidence
        ↓
tool-free L5 request
        ↓
Hard Gate(compact request)
        ↓
EpochMacroSummary
        ↓
ActiveCheckpoint LAST
        ↓
logical coverage supersedes old Fine entries
```

禁止：

```text
SemanticEntry summaries
   ↓
summary of summary
   ↓
summary of summary...
```

### 12.7 HistoryRead

```text
Agent Tool Call: HistoryRead
        ↓
ApplicationToolService
        ↓
HistoryReadTool
        ↓
active Session
        ↓
opaque TranscriptRef validation
        ↓
bounded raw page
        ↓
ToolResult
```

HistoryRead 不做：

```text
semantic search
keyword search
cross-session retrieval
vector DB
```

### 12.8 错误与取消

- cancellation 传入每次 L4/L5 model call；
- 被取消的 candidate 不 commit；
- parse/validation failure 不 commit；
- append durability unknown 沿用 Session quarantine；
- unknown durability 不得自动重复写；
- Provider count failure 只有存在安全 local fallback 时才继续；
- reliable Provider input 明确小于 configured input 时 effective input 收紧；
- 普通请求 context overflow 最多 forced reduction + rebuild + re-gate + retry 一次。

---

## 13. 对现有能力的影响

| 现有能力 / 文件 | 当前状态 | 本次处理 | 是否修改 | 回归要求 |
| --- | --- | --- | --- | --- |
| AgentLoop | request preparer 与 overflow handler 已支持 sync/awaitable | 复用并回归，不新增协议 | 原则上不修改 | ReAct/tool/pause/cancel 行为不变 |
| RunState | in-memory runtime authority | 保持原所有权 | 保持语义 | T05/T06/T08 回归 |
| active Turn model snapshot | 已冻结 Provider/model/output/tools | 把分维 limits capability 一并纳入 frozen snapshot | 修改 Application | mid-turn `/model` 不影响当前 limits |
| CanonicalHistory | raw durable facts | 硬切为 Transcript | 替换 | strict sequence/semantic unit 保留 |
| Projection | 单层 compact view | 被 Timeline 取代 | 删除生产语义 | 无 compatibility alias |
| Session single writer | lock/fsync/reconcile/quarantine | 复用到 v2 files | 修改 | durability 语义不退化 |
| RuntimeLog | 非权威 diagnostics | 保持 | 最小修改 | 不变成 Run checkpoint |
| ToolResult externalization | 已正式可用 | 继续作为 L1 基础 | 只调用 | 不重复实现 |
| ToolResultRead | current Session result ref | 保持独立 | 不改变语义 | 与 HistoryRead 互不越权 |
| `/compact` | 已注册但生产失败 | 接真实 async orchestrator | 修改 | success/no-op/failure |
| `/status` | fixed 258K | 分维 limits、Pressure/Preflight、Auto/Hard/Timeline | 修改 | 无正文泄露 |
| `/resume` | durable history + fresh Run | 恢复 Transcript + committed Timeline | 修改数据源 | 不恢复 active Turn |
| Eval diagnostics | Projection/258K | Gate/Timeline safe projection | 修改 | 不新增总分 |
| OpenAI Responses/Compat | 无可靠统一 window discovery | 用户配置可用；若用户也缺失 input limit 则 fail closed | 默认不动 | 不伪造 capability |
| Anthropic | 无 limits/count | 增加官方 capability adapter | 修改 | SDK 截止 Integration |

---

## 14. 第三方依赖

**无新增第三方依赖。**

继续复用现有：

```text
Anthropic SDK
OpenAI SDK
tomlkit / 当前配置依赖
pytest
```

Anthropic 的 Models API 与 Token Counting 通过当前已安装 SDK / client adapter 接入，不引入新 tokenizer package。

不新增：

```text
tiktoken 作为 Core 强依赖
vector DB
embedding library
background scheduler
persistence framework
model catalog package
```

local fallback 使用现有 deterministic estimator 的保守演化版本。

---

## 15. 实施任务拆分

> 本节与正式 Tasks 保持同一原子边界。T01～T08 均须独立可运行、可测试、可审查、可回退；不得把关键生产调用方留给后续任务。正式工作包、Checklist 与 6 份独立 Worker Prompt 已在本目录原位同步。

### I01 / T01：动态模型限制与确定性请求安全链

**任务目标**

移除固定 258K runtime invariant，并在同一任务接通正式请求链，建立：

```text
configured/provider/effective input limits
provider output/combined limits
adaptive capped R
Auto Gate
Hard Gate
Pressure Estimate / Preflight Safety Count/Estimate + allowance
A/F/U retained profile
final request accounting + L1-L3 + rebuild/re-gate
```

**涉及文件**

```text
core/context.py
core/provider.py
application/configuration.py
integrations/config/loader.py
integrations/config/template.py
integrations/providers/anthropic.py
application/bootstrap.py
application/context.py
application/generation.py
tests/test_configuration.py
tests/test_config_contract.py
tests/test_provider_model_limits.py
tests/test_context_budget_gate.py
tests/test_anthropic_integration.py
```

**实现要求**

- 用户 `ModelProfile.context_window` 为 optional positive int；项目只能保持/收紧用户已有值；
- 不存在隐式 258K fallback；
- 不存在 bundled metadata/catalog/hardcoded window；用户 input 与可靠 Provider input 两者皆无时 fail closed；
- input/output/combined limits 分维表达，unknown 不伪造；
- Pressure Estimate 与 Preflight Count/Estimate 分层；allowance 根据 count source 由单点 policy 解析；
- R 满足 adaptive + absolute cap；
- small-window A/F/U/compact budgets 自动退化；
- large-window retained profile 不线性增长；
- Anthropic 使用当前官方 `max_input_tokens` / `max_tokens` 与 count endpoint；
- OpenAI/compat 不伪造 capability。
- final request accounting 覆盖 instruction/messages/tools/framing/output reserve；
- L1-L3 每步后 rebuild/re-gate，required facts 超限时 Provider call count 为 0；
- 正式 Application→Compiler→既有 awaitable preparer→AgentLoop→ProviderPort 在本任务闭环。

**完成结果**

不依赖 Timeline/L4 即可从正式 Application 路径测试 dynamic limits、Budget/Gate、L1-L3 和 Provider call/fail-closed。

**明确不做**

Model Catalog UI、自动联网枚举全部 Provider 模型。

---

#### I01-b：Final Request Accounting、ContextCompiler 与确定性 L1-L3

该部分属于 T01 同一提交、同一验收边界，不得拆成独立 Worker 或推迟到 T03。

```text
final request assembly
→ Pressure/Preflight count
→ Auto Gate
→ L1-L3
→ rebuild
→ Auto/Hard recheck
```

涉及 `core/context.py`、`core/prompt.py`、`application/context.py`、`application/generation.py` 及 compiler/gate/tool-result/application tests。ContextCompiler 仍是唯一 model-view builder；L1 复用 Tool Result externalization，L2 deterministic bounded preview shrink/mask，L3 只省略 complete inactive semantic unit。protected/current/tool pair 不可拆；final accounting 覆盖 instruction/messages/tools/framing/output reserve；每步 rebuild/re-gate；required facts 自身超过已知 input/combined limit 时 unresolvable，Provider call count 为 0。

---

### I02 / T02：Transcript / Timeline Core Contract 与 Session v2 Hard Cut

**任务目标**

完成：

```text
CanonicalHistory + Projection
        ↓
Transcript + Timeline
```

硬切，并建立 crash-safe checkpoint commit。

**涉及文件**

```text
core/history.py
core/context.py
core/prompt.py
core/__init__.py
application/history.py
application/context.py
application/generation.py
application/sessions.py
integrations/session_files.py
tests/test_history_contract.py
tests/test_timeline_contract.py
tests/test_session_files.py
tests/test_context_compiler.py
tests/test_context_compaction.py
tests/test_application_runtime.py
tests/test_application_runs.py
tests/test_w04_session_commands.py
所有实际 CanonicalHistory / Projection / history.jsonl production caller 及对应 tests
```

**实现要求**

fresh Session：

```text
metadata.json
writer.lock
transcript.jsonl
timeline.jsonl
runtime.jsonl
tool-results/
```

- Session schema bump；
- old v1 deterministic incompatible；
- 不 migration / dual read / dual write；
- Timeline 只有 3 种产品 record；
- `ActiveCheckpoint` 最后提交；
- loader 忽略 checkpoint 后 trailing incomplete transaction；
- Transcript strict sequence 与 complete Tool semantic unit 保留；
- existing reconciliation/quarantine 保留；
- 同一任务迁移 Context source/compiler、Application generation/history/session、Integration store 与全部生产调用方，不允许留下“新 DTO/Store 已存在但正式 Compiler/Application 仍依赖旧 Projection”的半成品状态。

**完成结果**

无真实 L4 模型调用也能完整创建、运行、持久化并恢复 Transcript/Timeline；所有生产 caller 已切到新 authority，old v1 只保留明确 incompatible 行为。

---

### I03 / T03：Production L4 与 B′ Bounded Catch-up

**任务目标**

接通正式 tool-free semantic compaction，并实现 bounded multi-epoch catch-up。

**涉及文件**

```text
application/context.py
application/generation.py
application/sessions.py
tests/test_agent_loop.py
tests/test_context_compaction.py
tests/test_context_budget_gate.py
tests/test_application_runs.py
tests/test_t09_1_context_protocol_e2e.py
```

**实现要求**

- 复用现有 request preparer/overflow handler sync|awaitable contract，不重复改造 `core/agent.py`；
- L4 使用 frozen Turn provider/model/分维 limits；
- manual idle later 使用 current model；
- L4 tools=()；
- Compact request 自身 Hard-gated；
- L4 output 结构化解析成 one SemanticEntry per covered Turn；
- entries first，checkpoint last；
- 每 epoch commit 后 rebuild + Auto/Hard re-gate；
- one orchestration 支持 1..N；
- meaningful retained target；
- no-progress/repeated-failure/finite breaker；
- Auto unresolved + Hard safe => send + diagnostics；
- Hard unsafe => fail closed；
- cancellation 不 commit；
- 不存在持久 Compact FSM。

**完成结果**

大窗口可以在真实 pressure 到来后再通过多个 bounded epoch catch-up，而不是提前把 1M 模型人为降成小窗口。

---

### I04 / T04：L5 Timeline Aging 与 HistoryRead

**任务目标**

限制 logical Fine Timeline，并让模型可按 exact ref 回到 raw evidence。

**涉及文件**

```text
application/context.py
application/tools.py
application/bootstrap.py
integrations/tools/history_read.py
tests/test_timeline_contract.py
tests/test_context_compaction.py
tests/test_history_read_tool.py
tests/test_application_tools.py
tests/test_tool_result_persistence.py
```

**实现要求**

- Fine Timeline > F 可独立触发 L5；
- 只选 old complete Compact Epoch；
- L5 input 来自 raw Transcript refs；
- 生成 `EpochMacroSummary` + checkpoint；
- coverage supersede old fine logical view；
- old Timeline physical records 不删除；
- no summary-of-summary；
- no safe raw epoch => explicit failure；
- HistoryRead current Session only / opaque ref / bounded / read-only；
- HistoryRead output 不递归 externalize。

**完成结果**

Timeline 可以老化，但 raw evidence 永久仍以 Transcript 为 authority。

---

### I05 / T05：Application Compact 生命周期与 Overflow Recovery

**任务目标**

先把新 Context 协议接入真实 Run 与 Application/Headless 生命周期，形成不依赖命令/TUI 的完整能力。

**涉及文件**

```text
application/generation.py
application/sessions.py
tests/test_application_runtime.py
tests/test_application_runs.py
tests/test_t09_1_context_protocol_e2e.py
```

**实现要求**

- 每次下一 ordinary Provider call 前提交已闭合 Transcript facts；
- terminal tail 继续提交；
- durable cursor 不重复 append；
- 不写 open continuation；
- Application manual compact API await 同一个 orchestrator；
- manual compact 不依赖 Auto Gate；
- no candidate = success no-op；
- 不创建新 Session/Run/Turn；
- compact single-flight 保留；
- Provider overflow 普通 request 最多一次 forced reduction + retry；
- second overflow fail；
- 不修改任何 limit facts；
- active Turn `/model` 不改变 frozen limits snapshot。

**完成结果**

Application/Headless 正式链路经过相同 Context safety boundary，可独立验收。

---

### I06 / T06：[接入主流程] 命令、TUI 与正式入口收口

**任务目标**

在 T05 已通过后，把 manual compact、status 和正式生成入口接到 Command、CLI、TUI；删除旧同步-only 路径，不让 Interface 拥有 Context 语义。

**涉及文件**

```text
application/bootstrap.py
application/commands/builtins.py
application/commands/dispatcher.py
application/commands/models.py
interfaces/cli.py
interfaces/tui/app.py
tests/test_command_dispatcher.py
tests/test_w04_session_commands.py
tests/test_cli.py
tests/test_tui.py
```

**实现要求**

- `/compact` await T05 同一 Application API，`/status` 展示安全的分维 limits/Gate/Timeline diagnostics；
- dispatcher 最小支持 awaitable handler，所有 sync commands 保持；
- TUI 只 await outcome，CLI/TUI/Headless 不复制 Context orchestration；
- bootstrap 完成正式组合，删除 placeholder/重复入口；
- 回归既有 preparer/overflow awaitable、cancel/error tests，不新增第二套协议。

**完成结果**

CLI/TUI/Headless 全部复用同一 Application safety boundary，旧入口为零。

---

### I07 / T07：[端到端验证] Diagnostics、Eval、文档与回归收口

**任务目标**

删除 T09 阶段性固定 258K / Projection 对外语义，完成包级一致性。

**涉及文件**

```text
eval/metrics.py
tests/test_w05_diagnostics.py
tests/test_w06_integration_delivery.py
tests/test_architecture_boundaries.py

docs/Context-Index.md
docs/Tools.md
docs/core-design/T09-context-engineering.md
docs/context/A03-State/State-Context.md
docs/context/A04-Orchestration/Orchestration-Context.md
docs/user-manual/commands.md
docs/user-manual/configuration.md
```

**实现要求**

文档明确：

```text
configured/provider/effective input 与 provider output/combined
Pressure Estimate vs Preflight Safety Count/Estimate
Auto Gate vs Hard Gate
adaptive capped working headroom
Transcript vs Timeline
L1-L5
B′ no FSM
manual compact
HistoryRead
overflow retry once
resume != Runtime Recovery
old v1 Session incompatible
```

Eval：

- 只消费 public safe diagnostics；
- 对比 success/token/tool calls/compaction/pressure 等维度；
- 不建立总分；
- 不把某个 R 默认值写成产品成功阈值；
- tuning default 的优劣交由 Eval 比较。

**完成结果**

代码、测试、用户手册、Core Design、Context docs 与 diagnostics 一致。

---

### I08 / T08：[遗留负担清理] 删除阶段性与兼容逻辑

**任务目标**

在 T07 验收后删除 fixed 258K、Projection/CanonicalHistory、old writer、sync-only compact、旧阶段文案和重复入口，并确认已取消的 bundled metadata 路线持续不存在。

**实现要求**

- 以调用图和 `rg` 证明旧 production authority 为零；old-v1 fixture 只用于 incompatible 测试；
- 确认 bundled official metadata/catalog/hardcoded official window 路线在源码、测试、当前事实文档和 `OutstandingDebtList.md` 中均不存在，且未重新登记为 future debt；
- 重新盘点所有被 T09-1 实际改变的欠账：`T02 Slash Command / TUI` 仅删除已回补的 `/compact` 部分并保留仍成立的 `/memory`、`/dream`；`B01 私有测试集 v0` 按真实 Compaction 结果删除或更新对应部分；三条 T09 Context 欠账仅在实现、Checklist、Feedback 三项证据齐全后删除；
- 对其它受影响条目同样执行“完全回补则删除、部分改变则更新、仍成立则保留、用户取消则删除且不转登记”，禁止因一条记录部分完成而整条误删；
- Timeline record 恰为三类，B′ 无持久 FSM，Compact 无独立 model/provider fallback；
- 保护 Permission、Plan/Todo、Runtime Hook、其它命令与 TUI rendering；
- 清理后重跑最小定向、架构与全量测试，并写真实 Feedback；
- 全部任务和 Feedback 完成后将索引更新为 `implemented_unarchived`，不自动归档。

**完成结果**

仓库只剩一条生产 Context/Session/Compact 路径，取消路线和无调用方抽象为零。

---

## 16. 测试矩阵

| 场景 | 主要测试 | 必须证明 |
| --- | --- | --- |
| limit source | `test_configuration.py`, `test_config_loader_integration.py` | user positive 可用；user 与 reliable Provider input 都缺失时 fail |
| project authority | 同上 | project 只能保持/收紧 user `context_window`，不能补造/扩大 |
| model switch | `test_application_runtime.py` | 下一 Turn 换 limits，active Turn snapshot 不变 |
| input resolution | `test_provider_model_limits.py` | Provider input 只收紧 user；user 缺失可用 reliable Provider；双方缺失 fail |
| output/combined | `test_provider_model_limits.py` | 分维校验，unknown 不伪造、不折叠 |
| Anthropic limits | `test_anthropic_integration.py` | SDK metadata → Core ModelLimits，无 SDK leak |
| Provider count | `test_provider_model_limits.py` | structured request count 返回 estimate source |
| count allowance | `test_context_budget_gate.py` | Pressure 与 Preflight 分层；provider/local count 都不是数学精确 hard fact |
| Auto vs Hard | `test_context_budget_gate.py` | 可出现 Auto pressure=true、Hard safe=true |
| 禁止统一 90% | `test_context_budget_gate.py` | 1M R 有 absolute cap；不固定丢 100K |
| 25K small-window | `test_context_budget_gate.py` | R/A/F/U/compact budget 收缩，不套大窗口 reserve |
| large-window retained | `test_context_budget_gate.py` | A/F/U 不随 1M 线性放大 |
| L1 externalization | `test_tool_result_persistence.py` | large raw Tool Result 不进入工作请求 |
| L2 preview shrink | `test_context_compiler.py` | deterministic bounded |
| L3 omit inactive | `test_context_compiler.py` | complete semantic boundary |
| L1-L3 synthetic 259K→257K | `test_context_budget_gate.py` | 258K 仅测试输入；若仍高于 Auto，必须 L4-required |
| L1-L3 clear Auto | 同上 | 不调用 L4 |
| Hard unsafe | 同上 / e2e | Provider call count=0 |
| Transcript sequence | `test_history_contract.py` | strict append-only/current Session |
| Tool semantic group | history/runs | ToolCall/Result 不拆 |
| Timeline types | `test_timeline_contract.py` | 仅三种 record |
| crash before checkpoint | `test_session_files.py` | trailing records 不生效 |
| old Session v1 | `test_session_files.py` | explicit incompatible，无 migration |
| L4 one epoch | `test_context_compaction.py` | raw evidence → fine entries + checkpoint |
| L4 B′ | compaction/e2e | 1..N、每批 re-gate |
| L4 retained target | compaction | 不只跨 Auto 几 token |
| L4 no progress | compaction | finite breaker |
| Auto unresolved Hard safe | compaction/e2e | send + `auto_pressure_unresolved` |
| Auto unresolved Hard unsafe | e2e | no provider call |
| L4 cancel | compaction | no checkpoint |
| 1M pressure | e2e | 不因 bounded L4 cap 提前 compact；真正 pressure 后 catch-up |
| L5 independent trigger | compaction/timeline | Fine>F 即可 aging |
| L5 provenance | compaction | prompt evidence 来自 raw Transcript |
| no summary-of-summary | compaction | 不以旧 summary 为唯一证据 |
| HistoryRead | `test_history_read_tool.py` | current Session exact ref bounded page |
| HistoryRead denial | 同上 | cross-session/malformed ref fail closed |
| every model call hard-gated | runs/e2e | ordinary、L4、L5、manual、retry 均覆盖 |
| manual `/compact` below Auto | commands/e2e | 仍可压缩 |
| manual no-op | commands | success no-op，无 Timeline garbage |
| overflow first retry | e2e | forced reduction 后只 retry 一次 |
| overflow second fail | e2e | 不循环、不修改任何 limit facts |
| incremental persistence | runs/session | user/tool closed facts crash 后存在 |
| open continuation | runs/session | 未闭合事实不持久 |
| existing awaitable hooks | `test_agent_loop.py` | preparer/overflow sync|awaitable、cancel/error 无重复协议 |
| async command | dispatcher/tui | sync commands 不回退，`/compact` 可 await |
| diagnostics secrecy | `test_w05_diagnostics.py` | 无 Transcript/summary/tool/secret 正文 |
| Headless | `test_w06_integration_delivery.py` | 不依赖 TUI |
| architecture | `test_architecture_boundaries.py` | Core 无 SDK/fs/network；Interface 无 Context orchestration |
| T05/T06 regression | application runs + pause tests | resume 仍 fresh Run，不恢复 pending Runtime |
| T08 regression | agent loop/planning tests | Plan/Todo/Hook 行为不受 Context 改造破坏 |

真实 Provider 网络调用不得作为必过 CI 条件。Anthropic limits/count 使用 fake SDK/client fixture 验证 adapter conversion。

---

## 17. 删除与清理

本任务必须删除或替代以下已失效阶段性逻辑：

```text
UTHCODE_CONTEXT_BUDGET_TOKENS = 258_000 作为唯一 runtime invariant
ContextUsage / ContextSnapshot 固定 258K 硬校验
Projection 作为生产 Context compact authority
Projection revision 作为 active compaction state
生产 ContextCompactor summarize=None 路径
旧 overflow -> summarize=None -> retry 路径
Session v1 对 History + Projection 的新写入路径
/status 中 before T09-1 / fixed 258K 文案
同步-only /compact handler path
bundled official model metadata / 本地型号表 / 硬编码窗口路线及其欠账
```

可以重新设计后保留的现有机制：

```text
strict sequence
complete semantic-unit validation
deterministic token estimator
single-flight
Session lock/fsync/reconciliation/quarantine
Tool Result externalization
ToolResultRead
RuntimeLog 非权威 diagnostics
Instruction Epoch / stable prefix semantics
```

不得借机清理：

```text
Permission
Plan/Todo
Runtime Hook
TUI rendering
其它 Slash Commands
```

---

## 18. 验收标准

编码完成必须同时满足：

1. 用户显式配置与可靠 Provider runtime metadata 是唯一 limit 来源；用户 input 与 Provider input 都缺失时 fail closed，固定 258K/bundled table 不再是 authority。
2. 项目配置只能保持/收紧用户 `context_window`，不能补造或扩大；Provider input 也只能收紧更小用户值。
3. configured/provider/effective input、provider output、optional combined limit 分维表达和校验，unknown 不伪造、不折叠为单一 `E`。
4. Pressure Estimate 与 Preflight Safety Count/Estimate 是不同语义，Auto Gate 与 Hard Gate 是两个不同产品判断。
5. Auto Gate 使用 adaptive + absolute capped working headroom，不存在统一 90% 规则。
6. 25K 等小窗口不会被大窗口 reserve 挤死；1M 窗口不会固定浪费约 100K。
7. 每个真实 Provider model call 前都经过 Hard Gate。
8. Hard Gate 基于最终结构化 request，分别覆盖 input、requested output、known combined 与集中 safety allowance。
9. Provider-side count 被视为高可信度 estimate，而非绝对无误差事实；Provider overflow 仍是最终裁决。
10. L1-L3 都是 deterministic，不调用模型，并与 dynamic limits/正式请求链在 T01 同一任务闭环。
11. L1-L3 后仍处于 Auto pressure 时，即使 Hard-safe，也会尝试 L4；已清除时不做无意义 L4。
12. L4 使用当前 frozen main model/provider/分维 limits，tools 为空，不存在独立 compaction model。
13. L4 request 自身 Hard-gated，且不会递归 Auto compact。
14. B′ 支持 1..N bounded epoch；每批 commit 后 rebuild + re-gate。
15. B′ 没有 persistent Compact FSM/Job/next pointer。
16. Auto pressure finite reduction 后仍 unresolved 但 Hard-safe 时允许发送并记录安全 diagnostics。
17. Hard unsafe 且无法 reduction 时 Provider call count=0。
18. Transcript 是 raw durable closed semantic fact authority；Timeline 是 derived append-only context state。
19. Timeline 产品 record 只有 `SemanticEntry`、`EpochMacroSummary`、`ActiveCheckpoint`。
20. `ActiveCheckpoint` 是每个成功 L4/L5 transaction 的最后 durable commit。
21. crash 后可仅凭 Transcript + latest valid checkpoint 重新推导下一 epoch。
22. L5 由 Fine Timeline pressure 独立触发，并重新读取 raw Transcript，禁止 summary-of-summary。
23. HistoryRead 只允许 current Session exact raw Transcript bounded read。
24. fresh Session hard cut 为 `transcript.jsonl + timeline.jsonl`；old v1 不迁移、不 dual read/write。
25. closed semantic facts 在 request preparation 边界增量 durable；active/paused Runtime continuation 仍不持久。
26. `/compact` 走同一 Application orchestrator，低于 Auto Gate 也能手动触发。
27. `/compact` 无候选是 success no-op，不制造 Timeline garbage。
28. ordinary Provider overflow 最多 forced reduction + rebuild + re-gate + retry 一次；第二次失败，不学习或修改任何 limit facts。
29. Anthropic SDK 类型仅存在 Integration；Application/Core 只消费 UthCode-owned DTO。
30. OpenAI Responses / Compat 不为了统一接口伪造 window discovery。
31. `/status` 与 diagnostics 使用分维 limits、Pressure/Preflight、Auto/Hard/Timeline 语义且不泄露 Context 正文。
32. Eval 继续作为改进效果测量器，不把 tuning default 变成固定产品成败标准。
33. Headless Application 完整可运行，不依赖 TUI。
34. T05/T06 Persistent Runtime Recovery 边界保持。
35. 没有新增无真实调用方的 Manager / Registry / Scheduler / Event Bus。
36. 没有旧 T09 Session compatibility layer。
37. 相关单测、架构测试和全量回归通过。
38. 既有 request preparer 与 overflow handler sync|awaitable contract 仅被复用和回归，没有重复 async protocol 或无必要 AgentLoop 改造。
39. bundled official model metadata 路线已取消并从欠账删除，不转登记 future debt。
40. 实施后的 Context 边界可作为后续 Memory/Evidence Retrieval 的真实基线，但本任务没有预建 retrieval index/protocol。

---

## 19. 编码停止条件

Worker 开始实施时，以用户实际派发对应 Prompt 时的当前仓库状态为起点。开始编码前必须重新核对当前 `src/ + tests/`、前置 Worker Feedback 与任务书关键事实；普通后续 Commit、任务包修订、文档更新、Feedback 追加和 Checklist 勾选不构成基线冲突，不得仅因当前 HEAD SHA 与历史分析 SHA 不同而停止。

编码代理只在以下情况停止相关范围并通过 Feedback 报告用户：

- 当前源码已经发生会使本任务书产品语义、架构边界、任务依赖或完成范围失效的实质变化；
- AGENTS / UserDecisionBoundary 与 D1/D2/D3 发生实质冲突；
- 必须改变 `interfaces -> application -> core` / Integration 截止 SDK 的冻结边界；
- 必须新增第四种 Timeline 产品 record 才能完成 crash-safe commit；
- B′ 必须依赖跨进程 Compact FSM 才能正确工作；
- 必须引入独立 compaction model 或跨 Provider fallback；
- 用户显式配置与可靠 Provider metadata 无法在现有配置体系中形成唯一 limit authority；
- 第三方官方 API 当前事实变化，导致已规划 Provider capability 公共语义不成立；
- 必须扩大到 Persistent Runtime Recovery、Memory、Artifact GC、Timeline GC 等独立能力；
- 实际修改范围显著超出任务书且不是机械 import/test/doc 跟随；
- 需要旧 Session migration / compatibility；
- 出现未计划的安全边界变化；
- 已冻结决策发生真实冲突。

以下情况不得停止等待用户，应由编码代理在当前范围自行处理：

```text
普通编译错误
类型错误
lint / formatting
fixture 调整
私有 helper 拆分
局部数据结构选择
单元测试失败
普通实现 bug
不改变产品语义的文件内重构
```

---

## 20. 明确不做

本任务明确不包含：

```text
Memory
Embedding / Vector Retrieval
semantic retrieval
跨 Session History Retrieval

Persistent Run / Turn checkpoint
Pending Tool / Permission / AskUser restart recovery

独立 Compaction Model
跨 Provider Compaction fallback
Background Context Agent
Compaction Job Scheduler
持久 Compact FSM

Timeline physical GC / rotation / self-compaction
Artifact Store 生命周期 / GC

Subagent
Multi-Agent
Worktree

Provider 全量 Model Catalog UI
bundled official model metadata / 本地型号表 / 硬编码模型窗口
自动模型能力发现 UI
为了 Headroom 建独立用户配置子系统

Provider-specific server-side context editing 进入 Core

旧 T09 Session migration
dual read
dual write
compatibility alias
```

其中：

### Persistent Runtime Recovery

继续属于 T05/T06/T09 的独立后续边界。

本任务的：

```text
incremental closed Transcript persistence
```

只保存已经闭合的语义事实，不保存：

```text
active Turn continuation
waiter
coroutine
pending permission
pending AskUser
provider request position
```

### Memory / Evidence Retrieval

`HistoryRead` 只是：

```text
exact ref-based
current Session
raw Transcript
bounded read
```

不是 Memory、search 或 retrieval engine。

### Timeline GC

当前设计：

```text
physical Timeline 可增长
logical Fine Timeline 受 F 约束
```

本阶段不为未来 GC 创建占位协议。

---

> 本任务书最初基于历史分析基线 `40e9b2ea...` 形成，并与同目录 Spec、Tasks、Checklist、6 份独立 Worker Prompt 同步。当前仍为 `not_implemented`；Worker 以实际派发时的当前仓库状态起步并重新核对真实 `src/ + tests/`，不得把历史 SHA 当作固定实施前置，也不得恢复返工前的横向拆分或伪造 Feedback。
