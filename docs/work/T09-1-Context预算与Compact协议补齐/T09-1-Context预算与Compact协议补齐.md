# UthCode T09-1：Context预算与Compact协议补齐任务书

## 1. 分析基线

### 1.1 目标仓库与基线

目标仓库：

```text
https://github.com/undertaker33/Re-UthCode
```

本任务唯一分析与实施基线：

```text
6b8dad8e38416de833e669fdb275aab824fe2845
```

该基线相对前一轮探索基线 `0c4e22024f4af385f495c0d27b7543d01a27cf09` 仅增加一个文档提交，源码未变化。本任务不得根据旧聊天或旧任务书推测源码状态，编码时仍须以该 Commit 实际文件为准。

### 1.2 已读取的项目约束与相关资料

已读取并作为本任务约束输入：

```text
AGENTS.md
docs/work/README.md
docs/rules/UserDecisionBoundary.md
docs/Context-Index.md
docs/OutstandingDebtList.md
docs/context/A01-AgentRuntime/AgentRuntime-Context.md
docs/context/A03-State/State-Context.md
docs/context/A04-Orchestration/Orchestration-Context.md
docs/core-design/T09-context-engineering.md
docs/work/T09-Prompt与ContextEngineering/
```

与本任务直接相关的当前源码：

```text
src/uthcode/core/history.py
src/uthcode/core/context.py
src/uthcode/core/prompt.py
src/uthcode/core/provider.py
src/uthcode/core/agent.py
src/uthcode/application/history.py
src/uthcode/application/context.py
src/uthcode/application/configuration.py
src/uthcode/application/generation.py
src/uthcode/application/sessions.py
src/uthcode/application/tools.py
src/uthcode/application/bootstrap.py
src/uthcode/application/commands/builtins.py
src/uthcode/application/commands/dispatcher.py
src/uthcode/integrations/config/loader.py
src/uthcode/integrations/config/template.py
src/uthcode/integrations/session_files.py
src/uthcode/integrations/providers/anthropic.py
src/uthcode/integrations/providers/openai_responses.py
src/uthcode/integrations/providers/openai_compat.py
src/uthcode/integrations/tools/tool_result_read.py
src/uthcode/integrations/tools/factory.py
```

与本任务直接相关的现有测试：

```text
tests/test_history_contract.py
tests/test_context_compiler.py
tests/test_context_compaction.py
tests/test_session_files.py
tests/test_configuration.py
tests/test_config_contract.py
tests/test_application_runtime.py
tests/test_application_runs.py
tests/test_application_tools.py
tests/test_tool_result_persistence.py
tests/test_command_dispatcher.py
tests/test_w04_session_commands.py
tests/test_w05_diagnostics.py
tests/test_w06_integration_delivery.py
tests/test_tui.py
tests/test_architecture_boundaries.py
```

### 1.3 官方资料与外部实现参考

本任务探索阶段实际使用的外部资料：

| 来源 | 实际研究问题 | 最终用途 |
| --- | --- | --- |
| Anthropic Models API / Token Counting 官方文档 | Provider 是否能可靠给出模型输入上限，以及是否能精确计算结构化请求 token | Anthropic Integration 可提供可靠 physical ceiling / token count；不得让 SDK 类型进入 Core |
| OpenAI Models API 官方文档 | 通用 Model 对象是否提供 context window | 不建立虚假的统一动态发现；OpenAI / OpenAI-compatible 默认以显式配置的 `context_window` 为 UthCode operating authority |
| Codex CLI 当前源码 | operating window、最大窗口、compaction model 绑定与 retained tail 如何表达 | 借鉴“运行预算与物理/最大能力分离”“Compaction 复用当前 Turn 模型/Provider”“绝对 retained budget” |
| OpenCode 当前源码 | Compaction 是否需要独立运行状态机 | 借鉴“Compaction 属于既有 Session loop 的操作，持久事实用于重建进度”；UthCode 额外补齐 bounded multi-epoch catch-up |
| Claude Code 官方文档 | 上下文清理、自动压缩与重复压缩保护 | 只借鉴 layered reduction 与 thrash breaker 语义，不假定其未公开内部实现 |

---

## 2. 当前实现基线

T09 已建立第一版 Context Engineering，但当前实现仍是固定 operating profile。

当前主链路：

```text
AgentLoop
   ↓ request_preparer
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

当前关键事实：

- `ContextCompiler` 使用固定 `258_000` token Operating Budget；这个数字明确不是远端模型物理 Context Window。
- `ContextUsage`、`ContextSnapshot` 对 258K 存在硬编码校验。
- `ModelProfile` 尚无 `context_window`。
- `CanonicalHistory` 是 append-only 语义历史；`Projection` 是当前压缩后的历史视图。
- `ContextCompactor` 已有 complete-semantic-unit、输入预算、输出 reserve、summary cap 和 single-flight，但依赖同步 `Callable[[str], str]`。
- 生产 `UthCodeApplication` 没有为 `/compact` 和 overflow path 提供真实 summarizer，因此两个入口都不能完成真实语义压缩。
- 当前 Session 实际存储为 `history.jsonl + runtime.jsonl`；History 与 Projection 记录共存于 `history.jsonl`。不存在独立 `projections.jsonl`。
- 当前 History 主要在 terminal Turn 边界提交；进程中断时不会恢复 active/paused Turn 的 Runtime continuation。
- 当前 active Turn 已在 `UthCodeApplication._start_agent_turn()` 开始时冻结 Provider、model、reasoning、max output 和 Tool definitions；运行中 `/model` 切换不改变该 Turn。
- `ToolResultRead` 已提供 current-Session、opaque-ref、bounded page 的大 Tool Result 回读路径。
- `/status` 仍显示固定 258K 及 “before T09-1” 限制。
- Application 是 Context 编排和 Provider composition 的权威层；AgentLoop 不应拥有 Session/Context 管理状态。

本任务允许替换上述 T09 阶段性实现，但不得借机引入 Memory、Persistent Runtime Recovery、后台 Context Agent 或 Multi-Agent。

---

## 3. 问题定义

当前任务解决：

```text
让 UthCode 从“固定 258K + 不可生产运行的单层 Projection compaction”
升级为：

按当前模型 operating context window C 进行每次请求前预算治理，
在 Transcript 原始事实不丢失的前提下，通过确定性 L1-L3、
bounded L4 semantic epoch 和 L5 timeline aging 形成可恢复、可重复推导的
Context reduction 协议，并让自动 / 手动 Compact 真正可用。
```

当前已有能力不能完整解决的原因：

1. 固定 258K 不能保证小窗口模型安全，也不能利用大窗口模型。
2. Provider overflow 发生后才压缩太晚，且 overflow 不能可靠反推出模型窗口。
3. 当前 Compactor 没有生产模型调用者，`/compact` 与 overflow compact 均不可用。
4. 单层 `Projection` 不能表达“原始证据压缩”和“长期 Fine Timeline 老化”两个维度。
5. 超大 `C` 下若一次等待到很晚再压缩，单个 Compact 输入可能超出未来可再次处理的安全范围。
6. terminal-only History persistence 不足以支持“只恢复已闭合语义事实”的 T09-1 崩溃边界。
7. 当前模型看见摘要后，没有独立于 `ToolResultRead` 的 current-Session 原始历史证据回读工具。

---

## 4. 任务目标

### 4.1 最终交付

完成后形成以下最小完整链路：

```text
                        ModelProfile.context_window = C
                                   │
                                   ▼
User / Tool / Resume ──► Application Context Orchestration
                                   │
                                   ▼
                              Per-call Hard Gate
                    ┌──────────────┼───────────────┐
                    │              │               │
                    ▼              ▼               ▼
                  L1-L3           L4              L5
               deterministic   bounded epoch   timeline aging
                    │              │               │
                    └──────────────┴───────────────┘
                                   │
                           rebuild ContextSnapshot
                                   │
                         safe? ─ no ─► fail closed
                           │
                          yes
                           ▼
                          AgentLoop
                           │
                           ▼
                       ProviderPort
```

同时形成持久事实链：

```text
transcript.jsonl
  └─ raw durable closed semantic facts
             │
             ├─────────────► HistoryRead
             │
             ▼
        L4 / L5 evidence

timeline.jsonl
  ├─ SemanticEntry
  ├─ EpochMacroSummary
  └─ ActiveCheckpoint  ← 每个成功 L4/L5 事务最后提交
             │
             ▼
      ContextCompiler logical view
```

### 4.2 本任务冻结决策

#### D1：Compact 模型绑定

L4 / L5 使用当前主模型，不增加独立 `compaction_model` 配置或模型角色。

- 自动压缩发生在 active Turn 内时，使用该 Turn 已冻结的 Provider / model snapshot。
- idle 状态手动 `/compact` 使用 Application 当前选中的 Provider / model。
- Compact 使用独立 Prompt、独立 `GenerationRequest`、独立 input/output budget。
- Compact 请求没有 Agent Tools，不进入普通 Tool loop。
- 不隐式切换到第二个大窗口模型，不做跨 Provider fallback。

#### D2：B′ bounded catch-up

大窗口模型尊重 `C`，不因为 L4 单次输入上限而提前把主上下文强制压到小窗口。

触发 Compact 后允许执行 `1..N` 个 bounded L4 Epoch：

```text
Gate unsafe / manual force
      ↓
pick next bounded raw epoch
      ↓
L4 model call
      ↓
validate
      ↓
append SemanticEntry...
      ↓
append ActiveCheckpoint  ← commit
      ↓
rebuild + Gate
      ↓
safe? yes -> exit
      │
      no
      └── next bounded epoch
```

B′ **不得新增独立或持久 Compact 状态机**。`attempt_count`、`last_coverage`、`last_estimate` 等只属于单次 Application reduction loop 的进程内变量。

Crash 后：

```text
Transcript + latest valid ActiveCheckpoint
                   ↓
          derive next uncovered epoch
```

不得恢复：

```text
COMPACTING_BATCH_3
next_epoch_pointer
compact coroutine position
```

每批必须有 no-progress / repeated-failure breaker，禁止无限 compact loop。

### 4.3 明确不交付

本任务不交付：

- Persistent Run / active Turn checkpoint；
- Pending Tool / Permission / AskUser 跨进程恢复；
- Memory；
- semantic retrieval / vector DB / embedding；
- 跨 Session History Retrieval；
- Artifact Store 生命周期与 GC；
- Timeline rotation / GC / self-compaction；
- 后台 Context Agent；
- 独立 compaction model；
- Subagent / Multi-Agent；
- Provider 全量模型目录或模型能力自动发现 UI；
- Provider-specific server-side context editing 作为 Core 语义；
- 为旧 T09 Session 做迁移、dual read、dual write 或兼容层。

---

## 5. 能力欠账

### 5.1 本任务新增能力欠账

无。

### 5.2 本任务命中的既有能力欠账

T09-1 实施完成后，应由**任务包拆分阶段**根据届时的 `docs/OutstandingDebtList.md` 同步处理以下既有 T09-1 欠账：

- 真实 Context Window / max input 与统一 Budget Resolver；
- 正式 tool-free Compaction model use case；
- small-window / large-window adaptation。

本任务不会回补 T05 / T06 的 Persistent Runtime Recovery，也不会把 Transcript + Timeline 变成 RunState checkpoint。

任务书生成与编码实施阶段均不得自行修改 `docs/OutstandingDebtList.md`；清单同步由后续任务包拆分流程负责。

---

## 6. 核心产品行为

| 场景 | 输入 / 前置状态 | 预期行为 | 状态变化 | 对外结果 |
| --- | --- | --- | --- | --- |
| 普通请求，预算安全 | assembled request + reserve < `C` | Gate 放行，不触发 semantic compact | 无 Timeline 变化 | 请求正常发送 |
| L1 可解决 | 旧 Tool Result 正文仍占模型视图 | 使用现有 externalized ref / bounded preview | Transcript 不变 | 重新组装后 Gate |
| L2 可解决 | 旧 Tool preview 仍过大 | 确定性 mask / shrink 为更小 bounded preview + ref | Transcript 不变 | 重新组装后 Gate |
| L3 可解决 | inactive raw turns 占用预算 | 只在完整语义边界从 active raw view 省略 | Transcript 不变 | 重新组装后 Gate |
| L4 单 Epoch 足够 | L1-L3 后仍不安全 | 选择一个 bounded complete raw epoch，tool-free model 生成每 Turn `SemanticEntry` | Timeline 追加 entries，最后追加 `ActiveCheckpoint` | rebuild 后安全则发送 |
| B′ 多 Epoch catch-up | 大 `C` 会话首次压缩时存在大量 uncovered raw history | 顺序执行多个 bounded L4，每批成功即 commit，再 Gate | 每批独立提交 Timeline checkpoint | 达到 retained target / 请求安全后结束 |
| L4 无进展 | summary 失败、coverage 未推进、token 不降或重复同一候选 | breaker 停止 | 不提交伪 checkpoint | fail closed，Provider 不发送超预算请求 |
| L5 aging | Fine Timeline 超过 `F` | 选择旧 complete Compact Epoch，重新读原始 Transcript refs，生成一个 `EpochMacroSummary` | 追加 macro summary + 最终 checkpoint；旧 Fine entries 物理保留、逻辑被 coverage 取代 | Timeline logical view 回到预算 |
| L5 证据过大 | 当前模型无法安全读取一个历史 epoch 的 raw evidence | 不做 summary-of-summary，不切模型 | 无新 checkpoint | 返回明确 `no_safe_epoch` / `context_unresolvable` |
| 小窗口模型 | `C` 明显小于默认 retained profile | Budget Resolver 同步收缩 A/F/U 和 Compact request budget | 仅 policy 变化 | 不出现 48K evidence 塞入 25K window |
| 大窗口模型 | `C` 为数百 K / 1M | 主上下文可继续使用大 C；L4 epoch cap 不线性扩到 C | 无提前强制 compact | 真正 pressure 时才做 B′ |
| reliable physical ceiling 小于 C | Provider Integration 能可靠证明 max input < configured C | fail safe，不按更大的 C 发送 | 诊断记录 ceiling source | 配置/请求明确失败，不猜测 |
| Provider 无 window metadata | OpenAI / compat 等无法可靠给出物理上限 | 显式 `ModelProfile.context_window` 为 operating authority | 无 | 不伪造 discovery |
| 手动 `/compact` 有候选 | current Session 存在完整可压缩历史 | 进入与 auto 相同的 orchestrator，force reduction | 同一 Session；不新建 Run/Turn | 返回 compact success + bounded diagnostics |
| 手动 `/compact` 无候选 | 没有 complete compressible epoch | 安全 no-op | 不写 Timeline，不造 checkpoint | 返回 no-op，不作为错误 |
| Provider 首次 overflow | Gate 曾判断安全，但远端仍报告 context overflow | 最多一次 forced reduction + rebuild + retry | 可产生正常 Timeline checkpoint | 第二次仍 overflow 则失败 |
| Crash 发生在 L4 model call 前/中 | 本批尚无最终 checkpoint | 重启只读取已 committed checkpoint | 不恢复 batch runtime state | 本批从 raw Transcript 重新推导 |
| Crash 发生在 Timeline entries 后、checkpoint 前 | trailing `SemanticEntry` / `EpochMacroSummary` 已落盘但事务未闭合 | loader 仅采用 latest valid checkpoint 之前的逻辑状态 | trailing records 视为 incomplete transaction | 不需要 rollback |
| Resume | Session v2 有有效 Transcript + Timeline | 恢复 durable closed facts 和 latest valid checkpoint，创建 fresh process-local Run | 不恢复 old active Turn | 现有 T05/T06 边界保持 |
| Resume 旧 T09 Session | 检测到旧 schema / `history.jsonl` layout | 明确拒绝兼容恢复 | 不迁移、不 dual write | deterministic incompatible-session error |
| HistoryRead | 模型持有 current Session Transcript ref | bounded 读取 ref 对应 raw evidence 页 | 无写入 | 只返回当前 Session 原始证据 |
| HistoryRead 跨 Session / 伪 ref | ref 不属于 active Session | fail closed | 无 | 不泄露其他 Session 或任意路径 |

---

## 7. 架构归属

| 能力 | 所属模块 | 状态所有者 | 调用方 | 依赖方向 | 原因 |
| --- | --- | --- | --- | --- | --- |
| Transcript / Timeline value contracts | Core | 不拥有持久化；只定义不可变语义 | Application / Integration | Application/Integration → Core | Core 定义 Provider-independent 稳定产品语义 |
| Model operating context profile | Application configuration | `EffectiveConfig / ModelProfile` | Application Context orchestration | Integration config → Application model | 属于 UthCode 模型运行配置，不是 Provider SDK 对象 |
| reliable physical model ceiling | Core optional capability contract + Integration implementation | Integration cache / Provider adapter | Application Budget Resolver | Application → Core contract；Integration → Core | SDK/network 截止在 Integration |
| Context Budget Resolver | Application Context | 当前 request / Turn snapshot | request preparation | Application → Core Context Compiler | 需要合并 C、output reserve、Provider evidence 和 runtime request |
| Context Compiler | Core | 无可变业务状态 | Application Context | Application → Core | 只负责把 typed sources 编译成 model view |
| L1-L3 reduction | Core policy + Application orchestration | 当前 compile attempt | Application Gate | Application → Core | 规则确定、无 Provider 调用 |
| L4 / L5 model orchestration | Application Context | 单次 reduction loop | Hard Gate / `/compact` | Application → ProviderPort | 需要异步模型调用、取消、持久提交；不能放入 Core |
| B′ catch-up | Application Context | 只在单次调用栈中的局部变量 | Hard Gate | Application | 不存在持久 Compact FSM |
| Transcript / Timeline durable files | Integration Session store | Session writer | Application Session service | Application → Integration → Core models | fsync/lock/recovery 属于 Integration |
| closed semantic fact commit cadence | Application | process-local durable cursor + Session writer outcome | request preparation / terminal tail | AgentRun → Application → Session writer | 是编排时机，不是 Core runtime checkpoint |
| HistoryRead | Integration Tool + Application Tool composition | active Session Transcript | Agent Tool call | AgentLoop → Tool runtime → active Session | 复用现有 Tool 权限/执行链，但不变成 Memory |
| `/compact` 命令 | Application Command | 无独立状态 | Interface | Interface → Application | Interface 只触发 use case，不实现 Context |
| `/status` Context diagnostics | Application | bounded diagnostic projection | Interface / Eval | Application → Interface | 不暴露原始 Context 内容 |

### 7.1 新增协议约束

只允许新增当前任务确有真实调用方的最小协议：

```text
ModelLimits
  - max_input_tokens?
  - max_output_tokens?
  - source

可选 Provider capability:
  - resolve_model_limits(...)
  - count_input_tokens(...)   # 仅 Provider 确实提供可靠结构化计数时实现
```

具体类型名可在不改变语义的前提下按现有命名规范调整。

禁止：

```text
ContextManager
CompactManager
TimelineRegistry
ModelCatalogManager
CompactionJob
BackgroundCompactor
```

这类无必要的系统级抽象。

---

## 8. 外部参考结论

| 来源 | 研究问题 | 可借鉴机制 | UthCode 处理 |
| --- | --- | --- | --- |
| Codex CLI | operating context 与最大窗口是否应是同一概念 | operating budget 与更大物理/能力窗口分离；absolute recent retention | 简化后采用；UthCode 以 `C` + retained profile 表达 |
| Codex CLI | Compaction 是否需要独立模型 | 复用当前 Turn model/provider | 采用，冻结为 D1 |
| OpenCode | Compaction 进度是否必须有独立 FSM | compaction 作为现有 Session loop 操作，持久记录可重建 active view | 采用其状态边界思想；UthCode 增加 B′ multi-epoch |
| OpenCode | compact 输入自身过大时如何处理 | 当前实现会停止 | 不采用；UthCode 使用 bounded epoch catch-up |
| Claude Code | 如何避免只靠一次 summary | layered cleanup + compact + repeated-compaction protection | 只借鉴语义；不复制内部架构 |
| Anthropic 官方 API | 是否有可靠 model max input / token count | 可提供 max input 与请求 token 计数 | Integration 有能力时采用 |
| OpenAI 官方 API | generic model endpoint 是否统一暴露 context window | 不保证提供 | 不建立伪统一 discovery；显式 C 为 authority |

---

## 9. 目标目录树

以下只列本任务实际需要涉及的文件。文件内旧类型的删除不代表物理文件删除。

```text
src/uthcode/
├─ core/
│  ├─ history.py                         [修改]
│  ├─ context.py                         [修改]
│  ├─ prompt.py                          [修改]
│  ├─ provider.py                        [修改]
│  ├─ agent.py                           [修改]
│  └─ __init__.py                        [修改]
│
├─ application/
│  ├─ history.py                         [修改]
│  ├─ context.py                         [修改]
│  ├─ configuration.py                   [修改]
│  ├─ generation.py                      [修改]
│  ├─ sessions.py                        [修改]
│  ├─ tools.py                           [修改]
│  ├─ bootstrap.py                       [修改]
│  └─ commands/
│     ├─ builtins.py                     [修改]
│     ├─ dispatcher.py                   [修改]
│     └─ models.py                       [修改，仅若 awaitable handler 类型需要]
│
├─ integrations/
│  ├─ config/
│  │  ├─ loader.py                       [修改]
│  │  └─ template.py                     [修改]
│  ├─ session_files.py                   [修改]
│  ├─ providers/
│  │  └─ anthropic.py                    [修改]
│  └─ tools/
│     └─ history_read.py                 [新增]
│
eval/
└─ metrics.py                            [修改]
│
tests/
├─ test_history_contract.py              [修改]
├─ test_timeline_contract.py             [新增]
├─ test_context_compiler.py              [修改]
├─ test_context_compaction.py            [修改]
├─ test_context_budget_gate.py           [新增]
├─ test_session_files.py                 [修改]
├─ test_history_read_tool.py             [新增]
├─ test_provider_model_limits.py          [新增]
├─ test_configuration.py                 [修改]
├─ test_config_contract.py               [修改]
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
│
docs/
├─ Context-Index.md                      [修改]
├─ core-design/
│  └─ T09-context-engineering.md         [修改]
├─ context/
│  ├─ A03-State/State-Context.md         [修改]
│  └─ A04-Orchestration/Orchestration-Context.md [修改]
└─ user-manual/
   └─ commands.md                        [修改]
```

`src/uthcode/integrations/providers/openai_responses.py` 与 `openai_compat.py` 默认保持不动：二者不应为了“统一能力”伪造不存在的 reliable context-window metadata。若编码时仅因已有公共 Provider capability typing 需要做机械式无行为调整，可修改，但不得增加虚假窗口发现。

---

## 10. 文件级任务清单

| 文件路径 | 操作 | 文件职责 | 核心类型 / 函数 | 输入 | 输出 | 允许依赖 | 禁止依赖 | 对应测试 | 验收条件 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `src/uthcode/core/history.py` | 修改 | 定义 raw Transcript 与 append-only Timeline 语义 | `TranscriptEntry`, `Transcript`, `TranscriptRef`, `SemanticEntry`, `EpochMacroSummary`, `ActiveCheckpoint`, `Timeline`；保留 `RuntimeLog` 非权威语义 | Session/Turn semantic facts | 不可变 Core values | stdlib、Core provider/prompt values | fs、SDK、Application | history/timeline tests | 无 `Projection` 作为 active Context authority；三种 Timeline record type 完整校验 |
| `src/uthcode/core/context.py` | 修改 | dynamic compiler / budget policy / deterministic reduction contracts | `ContextBudget`, retained profile、Gate/reduction result、ContextCompiler | Transcript + Timeline + runtime facts + C | `ContextSnapshot` / typed reduction plan | Core values | Provider SDK、fs、network | compiler/budget/compaction tests | 移除固定 258K invariant；支持 small/large C |
| `src/uthcode/core/prompt.py` | 修改 | Context source authority 与 Plane | Transcript/Timeline source kinds | typed context sources | ContextBlock | Core | Application/SDK | compiler tests | Timeline summary 仍只能是 Conversation/History authority，不能升级成 System |
| `src/uthcode/core/provider.py` | 修改 | SDK-neutral Provider contracts | `ModelLimits`、可选 limits/token-count capability；现有 `ProviderPort` | model/request | provider-independent limits/count | stdlib | SDK types | provider limits + architecture | Application 可选调用；无 SDK 泄漏 |
| `src/uthcode/core/agent.py` | 修改 | Agent behavior loop | awaitable request-preparer 边界 | messages/tool defs/runtime facts | final `GenerationRequest` | Core contracts | Transcript/Timeline store、Application | application runs | AgentLoop 不知道 L1-L5/Timeline，只 await prepare |
| `src/uthcode/core/__init__.py` | 修改 | 公共 Core export | 新 contracts | - | exports | Core | - | import/architecture | 无失效 Projection export |
| `src/uthcode/application/history.py` | 修改 | Core Message → durable Transcript entries | transcript conversion helpers | closed Messages/tool groups | Transcript entries | Core | fs/SDK | history/application runs | 不提交 open fragment；ToolCall/Result 不拆分 |
| `src/uthcode/application/context.py` | 修改 | T09-1 Context 总编排 | Budget Resolver、Hard Gate、L1-L5、B′ catch-up、L4/L5 request/parse/validate | Turn model snapshot + Transcript/Timeline + provider capability | safe GenerationRequest / Compact result | Core ProviderPort/contracts | SDK、Interface | gate/compaction/e2e | 每个 provider call 过 Gate；无 Compact FSM |
| `src/uthcode/application/configuration.py` | 修改 | 模型 operating profile | `ModelProfile.context_window` | config mapping | positive `C` | stdlib/Core permission | Provider SDK | configuration tests | 每个可运行 model 有正整数 C |
| `src/uthcode/application/generation.py` | 修改 | Application generation、Turn snapshot、Session persistence | `_start_agent_turn`, gated async prepare, manual compact, overflow retry, status | Run/Turn/provider/model | AgentTurnExecution / diagnostics | Application/Core | Interface/SDK types | runtime/runs/e2e | active Turn 固定 C；每次调用 Gate；最多一次 overflow retry |
| `src/uthcode/application/sessions.py` | 修改 | Session use-case surface | Transcript/Timeline snapshot、append outcomes | Core values | durable outcome | Integration Session store + Core | Provider SDK | session/e2e | append checkpoint 事务结果明确；resume 不恢复 runtime |
| `src/uthcode/application/tools.py` | 修改 | Tool registry/composition | reserved `HistoryRead`, read callback, safe summary/materialization | active Session ref | bounded ToolResult | Core Tool + Integration HistoryRead | cross-session search | application tools/history read | 与 ToolResultRead 独立；无递归 externalization |
| `src/uthcode/application/bootstrap.py` | 修改 | composition root | Context/Session/Provider capability wiring | EffectiveConfig | UthCodeApplication | Integration implementations | Interface | application/runtime | optional capability 只在 composition root 组装 |
| `src/uthcode/application/commands/builtins.py` | 修改 | `/compact` 与 `/status` | async compact handler、dynamic usage text | Application | command outcome | Application API | Context internals/SDK | command tests | `/compact` success/no-op/failure 可区分；status 显示 C |
| `src/uthcode/application/commands/dispatcher.py` | 修改 | Application command dispatch | 最小 async dispatch path | awaitable/sync handler | `CommandOutcome` | Application command models | Interface-specific await loop | dispatcher/TUI | `/compact` 可 await；现有 sync command 不被迫后台化 |
| `src/uthcode/application/commands/models.py` | 修改 | handler typing（如需要） | awaitable handler type | handler | typing contract | stdlib | Context logic | dispatcher | 只做真实 `/compact` 调用所需 typing |
| `src/uthcode/integrations/config/loader.py` | 修改 | TOML validation/merge | `context_window` model field；project overlay rules | user/project TOML | config data | tomlkit/Application DTO boundary | Provider runtime | config tests | positive int；project 只能 overlay existing model，不可定义 Provider/credential |
| `src/uthcode/integrations/config/template.py` | 修改 | first-run template | `context_window` example | - | user template | stdlib | - | config tests | 新用户可明确填写 C |
| `src/uthcode/integrations/session_files.py` | 修改 | Session v2 bytes/lock/fsync/recovery | `transcript.jsonl`, `timeline.jsonl`, timeline transaction, schema v2 loader | Transcript/Timeline records | recovered snapshot | Core values、fs | Application policy/SDK | session files | 不读写 v1 history layout；checkpoint recovery 正确 |
| `src/uthcode/integrations/providers/anthropic.py` | 修改 | Anthropic SDK adapter | reliable model limits / token-count optional capability | remote model/request | Core `ModelLimits` / count | Anthropic SDK + Core | Application | provider model limits | SDK 类型截止在 adapter；失败不伪造值 |
| `src/uthcode/integrations/tools/history_read.py` | 新增 | current-Session raw Transcript bounded reader | `HistoryReadTool`, read policy/ref validation | opaque Transcript ref + offset/limit | bounded page | Core Tool + Session value access | arbitrary path、cross-session、vector DB | history read | ref 不可逃逸 Session；bounded output |
| `eval/metrics.py` | 修改 | 私有 Eval 消费安全 diagnostics | Timeline/Gate diagnostics mapping | public diagnostics | existing multi-dimension metrics | public Application data | raw Context text | diagnostics/eval unit fixture | 移除 Projection-only 假设；不建立新总分 |
| `docs/**` 上表文件 | 修改 | 同步已实现真实边界 | T09-1 final semantics | implementation facts | docs | 当前源码 | 未来设想 | 文档检查 | 不再写固定 258K / Projection 为现行架构 |

---

## 11. 关键数据结构与状态

### 11.1 Model operating budget

```text
ModelProfile
  ├─ model_ref
  ├─ provider_profile_id
  ├─ remote_id
  ├─ ...
  └─ context_window: positive int   # C
```

`context_window` 表示 UthCode 当前对该模型采用的 **Operating Context Window**，不是由 UI 猜出的 Provider 物理值。

运行请求必须先解析：

```text
C
+ configured / effective max_output_tokens
+ reliable Provider physical ceiling?   # optional
+ exact provider input count?            # optional
+ deterministic fallback estimate
        ↓
ContextBudget
```

建议内部结构：

```text
ContextBudget
  context_window = C
  output_reserve
  safety_margin
  active_evidence_budget = A
  fine_timeline_budget = F
  uncompressed_tail_budget = U
  retained_hard_cap
  compaction_input_budget
  compaction_output_reserve
```

大窗口初始 operating profile：

```text
A ≈ 48K
F ≈ 16K
retained target ≈ 64K
retained hard cap ≈ 96K
```

这些是默认 operating policy，不是模型物理声明，也不是不可调整的公开 API 常量。

`U` 必须包含在 active-evidence 工作集中；小窗口时 A/F/U 必须共同缩减。

禁止：

```text
A = C * 0.2
F = C * 0.1
```

作为大窗口的主策略。对 1M C 不应线性放大 retained context。

### 11.2 Transcript

Transcript 是当前 Session 的 raw durable fact authority。

建议 envelope：

```text
TranscriptEntry
  schema_version
  session_id
  sequence
  turn_id
  kind
  payload
  created_at
  commit_boundary
  semantic_unit_id?
```

现有 HistoryEntry 中已验证的 strict sequence、ToolCall/ToolResult semantic-unit 完整性与 JSONL safety 可重用，但命名和职责必须硬切为 Transcript。

稳定证据引用：

```text
TranscriptRef
  session_id ownership   # 不直接暴露为任意可编辑路径
  sequence_start
  sequence_end
```

对模型暴露时使用 opaque ref；Integration 解析后必须再次校验 active Session 与完整范围。

### 11.3 Timeline

Timeline 物理上 append-only，记录类型仅允许：

```text
SemanticEntry
  turn_id
  summary
  refs

ActiveCheckpoint
  turn_id
  active_turns

EpochMacroSummary
  turn_id
  summary
  refs
  coverage
```

文件 envelope 可附加 schema/record sequence/created_at 等持久化元数据，但不得增加第四种产品 record type。

第一阶段每个被 L4 覆盖的 Turn 生成一个 `SemanticEntry`，不创建 topic graph。

### 11.4 Compact Epoch

`Compact Epoch` 是**由 Timeline commit 边界推导出的逻辑概念**，不是另一个持久 record type。

一次 L4：

```text
SemanticEntry(turn A)
SemanticEntry(turn B)
SemanticEntry(turn C)
ActiveCheckpoint(...)
```

从上一个有效 checkpoint 到本次 checkpoint 之间新增的 L4 entries 构成一个 complete epoch。

L5 选择一个旧 complete epoch，通过其 `refs` 回到 raw Transcript，不能拿旧 summary 当唯一证据。

### 11.5 ActiveCheckpoint 是唯一 durable Compact commit

每次成功 L4 / L5 transaction 最后一条必须是 `ActiveCheckpoint`。

有效逻辑 Timeline：

```text
physical Timeline records
        ↓
find latest valid ActiveCheckpoint
        ↓
only records committed through that checkpoint are effective
```

尾部：

```text
SemanticEntry
EpochMacroSummary
```

若没有随后 checkpoint，只是 incomplete transaction，不进入 active logical view。

### 11.6 B′ 不存在持久状态

只允许：

```text
local reduction loop:
  attempts
  previous_estimate
  previous_coverage
  current_epoch
  cancellation
```

这些值：

- 不写入 Core RunState；
- 不写入 Transcript；
- 不写入 Timeline；
- 不写入 `runtime.jsonl` 作为恢复依据；
- 进程结束即消失。

---

## 12. 依赖与数据流

### 12.1 普通 Provider Call

```text
AgentLoop
   │
   │ await request_preparer(...)
   ▼
Application Context Gate
   │
   ├─ read current Turn model snapshot / C
   ├─ read active Session Transcript / Timeline
   ├─ resolve optional Provider limits/count
   ├─ deterministic L1-L3
   ├─ L4 / L5 if required
   └─ ContextCompiler rebuild
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

第三方类型必须在 Integration 截止。

### 12.2 closed semantic fact persistence

不得把“更频繁保存 Transcript”实现成 Runtime checkpoint。

建议复用现有每次 request preparation 都会经过 Application 的事实：

```text
before first provider call
  └─ current user message 已闭合
      → append durable Transcript if not already durable

after Tool batch, before next provider call
  └─ assistant ToolCall + matched ToolResult group 已闭合
      → append durable Transcript

terminal Turn
  └─ final assistant tail 已闭合
      → append remaining durable Transcript
```

Application 必须维护 process-local durable cursor / identity reconciliation，保证已经可判定 durable 的消息不重复追加。

禁止写入：

- 尚在 streaming 的 assistant fragment；
- unmatched ToolCall；
- provider coroutine position；
- pending permission / AskUser continuation。

### 12.3 L4

```text
Gate still unsafe after L1-L3
        ↓
derive next uncovered bounded raw epoch
        ↓
read exact Transcript evidence
        ↓
build tool-free compact request
        ↓
same Turn provider/model snapshot
        ↓
ProviderPort
        ↓
parse + validate:
  - coverage contiguous
  - refs exist
  - one SemanticEntry per covered Turn
  - bounded summary
        ↓
SessionWriter append Timeline entries
        ↓
append ActiveCheckpoint LAST
        ↓
fsync / reconcile
        ↓
rebuild + Gate
```

### 12.4 L5

```text
Fine Timeline > F
        ↓
select old complete Compact Epoch
        ↓
resolve its Transcript refs
        ↓
read RAW Transcript evidence
        ↓
tool-free model request
        ↓
EpochMacroSummary
        ↓
ActiveCheckpoint LAST
        ↓
logical view hides covered fine SemanticEntries
```

禁止：

```text
old SemanticEntry summaries
      ↓
summary of summaries
      ↓
summary of summary...
```

### 12.5 HistoryRead

```text
Agent Tool Call
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

HistoryRead 不是 Memory，也不做相关性搜索。

### 12.6 错误与取消

- cancellation 从 Turn / manual compact use case 传入每个 L4/L5 model call。
- 被取消的 model call 不提交 checkpoint。
- parse/validation 失败不提交 candidate。
- Timeline append durability unknown 时沿用 Session writer quarantine 思路；不能假装“没写”后自动重复写。
- Provider model-limit discovery/counting 失败时，只有明确可安全 fallback 到 configured C + deterministic estimate 的场景才继续；不得使用猜测出来的物理窗口。
- physical ceiling 明确小于 configured C 时 fail safe。
- Provider context overflow 最多触发一次 forced reduction/rebuild retry；第二次直接上抛规范化 overflow。

---

## 13. 对现有能力的影响

| 现有能力 / 文件 | 当前状态 | 本次如何使用 | 是否修改 | 原因 | 回归测试 |
| --- | --- | --- | --- | --- | --- |
| AgentLoop | sync request preparer + overflow handler | 继续负责 behavior/tool loop | 修改 | request preparation 需要 await L4/L5 | application runs / agent tests |
| RunState / Pause | in-memory Runtime authority | 保持原边界 | 原则上保持不动 | T09-1 不做 runtime checkpoint | T05/T06 regressions |
| Model selection | active Turn snapshot 已冻结 | C 与 Provider/model 一起冻结 | 修改 Application snapshot 参数 | 保证 mid-turn model switch 不改变 C | application runtime |
| CanonicalHistory | raw fact store | 语义升级为 Transcript | 修改并硬切命名 | 明确 raw truth 与 Context state 分离 | history contract |
| Projection | 单层历史压缩 view | 被 Timeline 取代 | 删除旧语义 | 无法表达 L4+L5 与 checkpoint | timeline/context tests |
| Session single writer | durable append + reconciliation/quarantine | 直接复用 | 修改 layout / append primitive | transcript/timeline 分文件 | session tests |
| `runtime.jsonl` | 非权威 diagnostics | 保留非权威性质 | 最小调整 | 不允许演化成 Compact/Run recovery state | session tests |
| ToolResult externalization | 已存在 | 作为 L1 基础 | 保持机制，只接 Gate policy | 避免重复实现 | tool result tests |
| ToolResultRead | current Session result ref read | 保持独立 | 不改变产品语义 | HistoryRead 是不同证据域 | application tools |
| `/compact` | registered but summarizer unavailable | 接真实 async orchestrator | 修改 | 本任务正式补齐 | command/TUI/e2e |
| `/status` | fixed 258K | 展示 current C / gate diagnostics | 修改 | 消除旧阶段说明 | command/status |
| `/resume` | fresh Run + durable Session semantic history | 读取 Transcript + valid Timeline checkpoint | 修改 Session data source，保持 Runtime 语义 | 不回补 T05/T06 | session/e2e |
| Eval diagnostics | Projection/258K 字段 | 消费 Timeline/Gate safe projection | 修改 | 避免旧指标失真 | diagnostics fixture |
| OpenAI Responses / Compat | 无可靠统一 runtime window metadata | 继续用 configured C | 保持不动 | 不伪造 capability | config + provider conformance |

---

## 14. 第三方依赖

**无新增第三方依赖。**

现有 Provider SDK 继续只在 `integrations/providers/` 内使用。

Anthropic adapter 如实现官方 Model limits / token count，必须复用当前已安装 Anthropic SDK，不额外引入 tokenizer/model-catalog 包。

不新增：

- vector database；
- embedding package；
- tokenizer package 作为强依赖；
- background scheduler；
- persistence framework。

Provider exact token count 不可用时，使用现有 deterministic estimator 的保守版本作为 operating estimate，并在 diagnostics 标明 estimator source。

---

## 15. 实施任务拆分

### W01：Model Context Profile 与统一 Budget Resolver

**任务目标**

把固定 258K 从公共 Context invariant 中移除，建立 per-model `C` 与 small/large-window retained profile。

**前置条件**

当前配置与 ContextCompiler 测试全部通过。

**涉及文件**

```text
src/uthcode/application/configuration.py
src/uthcode/integrations/config/loader.py
src/uthcode/integrations/config/template.py
src/uthcode/core/context.py
src/uthcode/core/provider.py
src/uthcode/integrations/providers/anthropic.py
src/uthcode/application/bootstrap.py
tests/test_configuration.py
tests/test_config_contract.py
tests/test_context_budget_gate.py
tests/test_provider_model_limits.py
```

**允许修改的已有文件**

仅上表与必要 export。

**实现要求**

- `ModelProfile` 具备正整数 `context_window`。
- 配置支持 user 定义；project 只能 overlay 已存在 model 的非 Provider/credential 字段。
- 每个进入真实 request path 的 model 必须解析出 C；不得默默使用一个可能大于真实小窗口的全局 258K。
- Anthropic 的 reliable ceiling 只作为 physical guard，不覆盖用户选择的更小 operating C。
- OpenAI / compat 不伪造 generic model-window discovery。
- 建立 A/F/U/hard cap resolver；大窗口采用 absolute retained profile，小窗口自动收缩。
- output reserve、safety margin 与 request input 共同进入 Gate 预算。

**完成结果**

无固定 258K 的 ContextSnapshot invariant；同一 Application 切换 model 后，下一 Turn 使用新 C。

**测试**

至少覆盖 25K、128K、258K、1M profile；configured C 小于/大于 reliable ceiling；无 reliable metadata。

**明确不做**

全量模型 catalog、网络启动时枚举所有模型、UI model capability browser。

**提交边界**

配置 + budget contracts + Provider optional capability 完整且不依赖后续 Timeline。

---

### W02：Transcript / Timeline Core Contract 与 Session v2 Storage

**任务目标**

完成 `CanonicalHistory + Projection` 到 `Transcript + Timeline` 的硬切，并建立 crash-safe checkpoint transaction。

**前置条件**

W01 可提供 C，但 W02 不依赖 L4 model caller。

**涉及文件**

```text
src/uthcode/core/history.py
src/uthcode/core/prompt.py
src/uthcode/core/__init__.py
src/uthcode/application/history.py
src/uthcode/application/sessions.py
src/uthcode/integrations/session_files.py
tests/test_history_contract.py
tests/test_timeline_contract.py
tests/test_session_files.py
```

**实现要求**

- `transcript.jsonl` 只保存 raw semantic facts。
- `timeline.jsonl` 只保存三类产品 record。
- `runtime.jsonl` 可保留，但明确非 Context/Run authority。
- Session schema bump；旧 `history.jsonl` layout 不迁移、不 dual read/write。
- Transcript strict sequence 与 ToolCall/ToolResult complete unit safety 保留。
- Timeline append transaction 必须以 ActiveCheckpoint 最后提交。
- loader 只采用 latest valid checkpoint 之前的 records；尾部未闭合事务无效。
- stable Transcript refs 不能变成任意路径。
- Session writer 的 durability unknown / quarantine 语义继续成立。

**完成结果**

fresh Session 文件布局：

```text
metadata.json
writer.lock
transcript.jsonl
timeline.jsonl
runtime.jsonl
tool-results/
```

**测试**

partial JSON line、semantic incomplete tool group、Timeline trailing entries、checkpoint crash boundary、single writer、old schema incompatibility。

**明确不做**

旧 Session migration、Timeline GC、runtime checkpoint。

**提交边界**

不需要真实 L4 model call，也能创建/读写/恢复 Transcript+Timeline。

---

### W03：ContextCompiler logical view 与确定性 L1-L3

**任务目标**

让 ContextCompiler 从 Transcript + Timeline 生成模型逻辑视图，并在 semantic model call 前尽可能做确定性 reduction。

**前置条件**

W01 + W02。

**涉及文件**

```text
src/uthcode/core/context.py
src/uthcode/core/prompt.py
src/uthcode/application/context.py
tests/test_context_compiler.py
tests/test_context_budget_gate.py
```

**实现要求**

- ContextCompiler 是唯一 model-view builder。
- Instruction Plane / Conversation Plane authority 不变。
- L1 externalization、L2 bounded preview masking、L3 inactive raw turn omission 必须 deterministic。
- reduction 只按完整 semantic unit / Turn 边界。
- required protected context + current turn 本身若无法装入 C，直接 `context_unresolvable`，不得调用 L4 掩盖必需内容。
- Timeline logical view能处理：
  - Fine `SemanticEntry`；
  - `EpochMacroSummary.coverage` 对旧 fine entries 的逻辑替代；
  - latest checkpoint active-turn set。
- physical Timeline 增长不得改变 logical F budget。
- diagnostics 只输出 ID/count/token/budget/reason，不输出 Context 正文。

**完成结果**

无模型调用时可测试的完整 Gate precheck + L1-L3 + rebuild。

**测试**

protected block、tool pair、active/inactive raw turn、macro coverage、small C impossible request、large C no premature compact。

**明确不做**

embedding relevance、Memory retrieval、topic graph。

**提交边界**

semantic compaction 尚可用 Fake plan/result fixture，但 ContextCompiler 逻辑已完整。

---

### W04：Production L4 + B′ bounded catch-up

**任务目标**

接通真实 tool-free semantic compaction，并实现无独立 FSM 的 bounded catch-up。

**前置条件**

W01-W03。

**涉及文件**

```text
src/uthcode/core/agent.py
src/uthcode/application/context.py
src/uthcode/application/generation.py
src/uthcode/application/sessions.py
tests/test_context_compaction.py
tests/test_context_budget_gate.py
tests/test_application_runs.py
tests/test_t09_1_context_protocol_e2e.py
```

**实现要求**

- AgentLoop request preparer 可以 await。
- AgentLoop 不接受 Timeline/Transcript/phase 参数。
- L4 使用 frozen Turn model/provider；manual idle compact 使用 current Application model/provider。
- 每个 L4 request 无 Agent Tools。
- 每个 epoch input 有独立 cap；不随 1M C 线性放大。
- L4 输出必须结构化解析/校验成 one-SemanticEntry-per-Turn。
- 成功 epoch：先 entries，最后 checkpoint。
- 每个 commit 后 rebuild + Gate。
- one Gate 可执行 1..N epochs。
- no-progress/repeated-failure/finite-attempt breaker。
- attempts/coverage 只在当前调用栈，不持久化。
- cancellation 不提交伪 checkpoint。
- compact request 自身也必须经过自己的 input/output budget gate。

**完成结果**

800K raw history 在 1M operating model 中可以等真实 pressure 后，以多个 bounded epochs catch-up，而不是单次超大 compact 或提前把 C 降成 128K/258K。

**测试**

单 epoch、多 epoch、crash after epoch N、crash before checkpoint、no progress、cancel、same Turn model snapshot、1M C 不提前 compact。

**明确不做**

CompactionJob、background worker、dedicated compaction model。

**提交边界**

L4 + checkpoint + B′ 完整；L5 可后接。

---

### W05：L5 Timeline Aging 与 HistoryRead

**任务目标**

把长期 Fine Timeline 限制在 F，并为摘要后的模型提供显式原始证据回读能力。

**前置条件**

W04 已能产生 complete Compact Epoch。

**涉及文件**

```text
src/uthcode/application/context.py
src/uthcode/application/tools.py
src/uthcode/integrations/tools/history_read.py
src/uthcode/application/bootstrap.py
tests/test_timeline_contract.py
tests/test_history_read_tool.py
tests/test_application_tools.py
tests/test_tool_result_persistence.py
tests/test_context_budget_gate.py
```

**实现要求**

- F 超预算时选旧 complete epoch。
- L5 只从 raw Transcript refs 取证。
- 输出一个 `EpochMacroSummary`，随后 checkpoint。
- `coverage` 足以确定旧 Fine entries 在 logical view 中被 supersede。
- 不删除旧 Timeline 记录。
- 不允许 summary-of-summary input。
- 当前模型不足以安全处理 old epoch raw evidence 时明确失败，不静默切模型。
- `HistoryRead` 独立于 `ToolResultRead`：
  - current Session only；
  - opaque ref；
  - bounded page；
  - read-only；
  - no index/search；
  - 不递归 externalize 自己的 bounded output。

**完成结果**

Fine Timeline 可在不破坏 raw evidence 的情况下 aging；模型能按 refs 找回原始证据。

**测试**

L5 raw-evidence provenance、coverage、cross-session denial、malformed ref、bounded page、small-model no-safe-epoch。

**明确不做**

semantic search、Memory、cross-session history。

**提交边界**

L5 + HistoryRead 可独立审查。

---

### W06：Incremental Closed-Transcript Persistence、Manual Compact 与 Overflow Retry

**任务目标**

把 Context 协议接入正式 Run/Command 生命周期，补齐 crash facts 和用户入口。

**前置条件**

W01-W05。

**涉及文件**

```text
src/uthcode/application/generation.py
src/uthcode/application/sessions.py
src/uthcode/application/commands/builtins.py
src/uthcode/application/commands/dispatcher.py
src/uthcode/application/commands/models.py   # 仅真实 typing 需要时
src/uthcode/interfaces/tui/app.py            # 仅 async dispatch 接入需要时
tests/test_application_runtime.py
tests/test_application_runs.py
tests/test_command_dispatcher.py
tests/test_w04_session_commands.py
tests/test_tui.py
tests/test_t09_1_context_protocol_e2e.py
```

**实现要求**

- 在每次下一 Provider call 前提交已经闭合的 semantic facts。
- terminal tail 继续提交。
- 已 durable 内容不重复 append。
- 不持久化 open streaming fragments / continuation。
- `/compact` await 同一 Application Context orchestrator。
- no candidate 返回成功 no-op，不写 checkpoint。
- manual compact 不创建 Session/Run/Turn。
- 同 Session已有 compaction single-flight 时 fail safe，不创建第二套 job。
- Provider overflow 仅最后保护：最多一次 forced compact + rebuild + retry。
- overflow 不修改/学习 C。
- `/status` 展示 `used/C`、estimator、reserve、A/F/U、last Gate action、L1-L5 counters、checkpoint/epoch safe diagnostics。
- active Turn 内 `/model` 仍不改变 frozen C。

**完成结果**

正式 CLI/TUI/Headless 通过真实 Context Gate 工作，manual compact 可用。

**测试**

initial call、post-tool、pause/resume 后 call、manual compact、no-op、overflow once/twice、incremental crash fact、model switch。

**明确不做**

让 Command/TUI 拥有 Context 状态；后台异步 job。

**提交边界**

用户可感知链路闭合。

---

### W07：Diagnostics、Eval、文档与回归收口

**任务目标**

删除 T09 阶段性固定 258K / Projection 对外描述，证明架构边界与现有能力不回退。

**前置条件**

W01-W06。

**涉及文件**

```text
eval/metrics.py
tests/test_w05_diagnostics.py
tests/test_w06_integration_delivery.py
tests/test_architecture_boundaries.py
docs/Context-Index.md
docs/core-design/T09-context-engineering.md
docs/context/A03-State/State-Context.md
docs/context/A04-Orchestration/Orchestration-Context.md
docs/user-manual/commands.md
```

**实现要求**

- diagnostics 不泄露 raw Transcript、summary 正文、Tool result、secret。
- Eval 只消费公开安全字段，不把某个 threshold 写成 pytest 产品验收标准。
- 删除旧 “fixed 258K / Projection revision = current compaction state / summarizer_unavailable” 描述。
- 文档明确：
  - Transcript vs Timeline；
  - C vs physical ceiling；
  - L1-L5；
  - B′ 无 Compact FSM；
  - resume 不恢复 Runtime；
  - old Session incompatible。
- architecture test 保证 Core 无 SDK/fs/network，Interface 不拥有 Context orchestration。
- 全量现有 tests 通过。

**完成结果**

代码、测试、诊断和文档互相一致。

**明确不做**

公开 Benchmark leaderboard、Memory eval、Timeline GC。

**提交边界**

最终 integration / cleanup commit。

---

## 16. 测试矩阵

| 场景 | 主要测试文件 | 必须证明 |
| --- | --- | --- |
| `C` 配置与 model switch | `test_configuration.py`, `test_config_contract.py`, `test_application_runtime.py` | positive C；project overlay 边界；下一 Turn 换 C、active Turn 不变 |
| 25K small-window | `test_context_budget_gate.py` | A/F/U/compact budget 自动缩减，不出现 48K 固定保留 |
| 1M large-window | `test_context_budget_gate.py`, `test_t09_1_context_protocol_e2e.py` | 不因 L4 cap 过早压缩；真实 pressure 后 B′ |
| reliable physical ceiling | `test_provider_model_limits.py` | configured C 超 ceiling fail safe；SDK value 已转成 Core DTO |
| Provider 无 ceiling | `test_provider_model_limits.py` | 不伪造数据，explicit C 仍可工作 |
| Transcript strict sequence | `test_history_contract.py` | append-only、stable range、同 Session ownership |
| closed Tool semantic group | `test_history_contract.py`, `test_application_runs.py` | ToolCall/Result 不拆分 |
| Timeline record validation | `test_timeline_contract.py` | 只有三种 product record；refs/coverage/checkpoint 合法 |
| crash before checkpoint | `test_session_files.py` | trailing L4/L5 records 不生效 |
| old Session v1 | `test_session_files.py` | 明确 incompatible，不迁移 |
| L1 externalization | `test_tool_result_persistence.py`, `test_context_compiler.py` | full raw result 不进入工作上下文 |
| L2 preview shrink | `test_context_compiler.py` | deterministic bounded preview |
| L3 omit inactive raw | `test_context_compiler.py` | 完整 Turn 边界，不拆 tool pair |
| L4 one epoch | `test_context_compaction.py` | raw evidence → per-turn SemanticEntry + checkpoint |
| L4 multi epoch B′ | `test_context_compaction.py`, `test_t09_1_context_protocol_e2e.py` | 1..N commit/re-gate，最终安全 |
| L4 no-progress breaker | `test_context_compaction.py` | finite failure，无无限模型调用 |
| L4 cancel | `test_context_compaction.py` | 无 checkpoint commit |
| L5 aging | `test_timeline_contract.py`, `test_context_compaction.py` | raw Transcript input；macro coverage 替代 fine view |
| no summary-of-summary | `test_context_compaction.py` | L5 prompt evidence 不含旧 summary 作为权威来源 |
| HistoryRead success | `test_history_read_tool.py` | current Session opaque ref bounded read |
| HistoryRead cross-session | `test_history_read_tool.py` | fail closed |
| every Provider call gated | `test_application_runs.py`, `test_t09_1_context_protocol_e2e.py` | initial/post-tool/post-resume/L4/L5 均有 Gate |
| protected context impossible | `test_context_budget_gate.py` | provider call count = 0，明确失败 |
| manual `/compact` | `test_w04_session_commands.py`, `test_command_dispatcher.py`, `test_tui.py` | async use case、same Session、no new Run/Turn |
| manual no candidate | 同上 | success no-op，无 Timeline record |
| overflow first retry | `test_t09_1_context_protocol_e2e.py` | forced reduction 后最多重试一次 |
| overflow second failure | 同上 | 不循环、不改 C |
| incremental persistence | `test_application_runs.py`, `test_session_files.py` | user/tool closed facts crash 后存在；open continuation 不存在 |
| diagnostics secrecy | `test_w05_diagnostics.py` | 无 Context/summary/tool result/secret 正文 |
| Headless | `test_w06_integration_delivery.py` | 不依赖 TUI |
| module boundaries | `test_architecture_boundaries.py` | Core 无 SDK/fs/network；Interface 不拥有 Context |
| T05/T06 regression | `test_application_runs.py` + pause/resume tests | resume 仍 fresh Run，不恢复 pending runtime |

测试不得把外部真实 Provider 网络调用作为必过 CI 条件。Provider limits/count 使用 fake SDK/client fixtures 验证 adapter conversion；真实 Eval 用于后续效果比较，不是红绿功能验收替代品。

---

## 17. 删除与清理

本任务无额外无关历史清理，但必须删除/替代以下**当前任务直接失效**的阶段性逻辑：

```text
固定 UTHCODE_CONTEXT_BUDGET_TOKENS = 258_000 作为唯一 runtime invariant
ContextUsage / ContextSnapshot 对固定 258K 的硬校验
Projection 作为当前 Context 压缩权威
Projection append/revision 作为生产 compaction 状态
ContextCompactor 的生产同步 summarize=None 路径
旧 overflow -> compactor(summarize=None) -> retry 逻辑
Session v1 history.jsonl 中 History + Projection 的新写入路径
/status 中 “before T09-1 / fixed 258K limitation” 文本
```

允许保留经过重新命名后仍有真实价值的：

- strict sequence；
- SemanticUnit complete-boundary 校验；
- deterministic token estimator；
- single-flight；
- Session writer lock/fsync/reconciliation/quarantine；
- Tool Result externalization；
- RuntimeLog 非权威 diagnostics。

不得为了代码“干净”顺手重构 Permission、Plan、Todo、Hook、TUI rendering 等无关模块。

---

## 18. 验收标准

编码完成必须同时满足：

1. `ModelProfile` 的每个真实可运行模型都有明确 operating `context_window = C`，不再以全局固定 258K 作为请求安全依据。
2. small-window 与 large-window profile 均有测试，且 large-window retained strategy 以 absolute budgets 为主。
3. 每一次正式 Provider model call 在发送前都经过同一 Application Hard Gate。
4. AgentLoop 只 await request preparation，不拥有 Transcript、Timeline、L1-L5 或 Compact 状态。
5. L1-L3 是 deterministic reduction，不调用模型。
6. L4 是 bounded raw epoch semantic compaction；每个成功 transaction 最后提交 ActiveCheckpoint。
7. B′ 支持 1..N bounded L4 catch-up；不存在独立 `CompactState` / `CompactionJob` / persisted FSM。
8. crash 后能仅凭 Transcript + latest valid ActiveCheckpoint 重新推导下一未覆盖 epoch。
9. L5 重新读取 raw Transcript evidence，不能递归 summary-of-summary。
10. physical Timeline append-only；logical Fine Timeline 被 F 限制；本任务不实现 Timeline GC。
11. `HistoryRead` 只读 current Session raw Transcript，不能跨 Session、不能任意路径、不能做 semantic search。
12. storage hard cut 为 `transcript.jsonl + timeline.jsonl`；旧 T09 Session 不迁移、不 dual write。
13. Transcript 只持久化 closed semantic facts；active/paused Turn Runtime continuation 仍不持久。
14. `/compact` 使用同一 orchestrator；有候选真实压缩，无候选安全 no-op。
15. L4/L5 使用当前主模型/Provider snapshot，不存在独立 compaction model role。
16. Provider overflow 只作为最后保护，最多一次 forced reduction retry，不学习 C。
17. reliable Provider physical ceiling 只作为安全上限；Provider 无可靠 metadata 时不伪造 discovery。
18. Core 不依赖 filesystem、network、Provider SDK 或 Interface。
19. Anthropic SDK 类型只存在于 Integration；Core/Application 只消费 UthCode-owned contract。
20. `/status` 与 public diagnostics 使用动态 C、Gate/Timeline 语义且不泄露 Context 内容。
21. Headless Application 可完整运行，不依赖 TUI。
22. T05/T06 persistent runtime recovery 边界保持，不通过 Transcript/Timeline 偷跑。
23. 不新增无真实调用方的 Manager/Registry/Protocol/Event Bus。
24. 本任务相关单测、架构测试与全量回归通过。
25. 实施完成后的代码可作为后续 Memory/Evidence Retrieval 的真实基线，但本任务没有为其预制索引或协议。

---

## 19. 编码停止条件

编码代理仅在以下情况停止并报告用户：

- 基线 `6b8dad8e38416de833e669fdb275aab824fe2845` 的真实源码与本任务书关键假设不一致；
- `AGENTS.md` 或其引用规则与本任务书冻结决策实质冲突；
- 必须改变“Application 负责编排、Core Provider-independent、Integration 截止 SDK”的冻结公共边界才能继续；
- 实际发现 `ModelProfile.context_window` 无法在不引入新的用户产品语义的前提下接入当前配置层；
- Transcript/Timeline 三 record 设计无法表达 crash-safe checkpoint，必须增加第四种持久产品 record；
- B′ 必须依赖跨进程 Compact 状态机才能正确实现；
- L4/L5 必须引入独立 compaction model 才能成立；
- 第三方官方 API 事实与探索结论发生变化，并会改变 Provider capability 公共语义；
- 任务必须扩大到 Persistent Runtime Recovery、Memory、Artifact GC 或另一个独立能力；
- 实际文件修改范围明显超过本任务书且不是机械性 import/test/doc 跟随；
- 出现未计划的安全边界变化；
- 需要为旧 Session 建迁移/兼容层；
- 需要创建无当前调用方的系统级抽象；
- 两项冻结决定发生实质冲突。

以下情况不得停止等待用户，应由编码代理自行解决：

```text
普通编译错误
类型错误
lint / formatting
fixture 调整
私有 helper 拆分
普通数据结构选择
测试失败
局部实现 bug
不改变产品语义的文件内重构
```

---

## 20. 明确不做

本任务明确不包含：

```text
Memory
Embedding / Vector Retrieval
跨 Session History Retrieval
Persistent Run / Turn checkpoint
Pending Tool / Permission / AskUser restart recovery
独立 Compaction Model
Background Context Agent
Compaction Job Scheduler
Timeline GC / rotation / self-compaction
Artifact Store 生命周期
Subagent / Multi-Agent
全量 Provider Model Catalog
动态模型能力发现 UI
Provider-specific server context editing 进入 Core
旧 Session migration / dual read / dual write
```

其中：

```text
Persistent Runtime Recovery
```

继续保留为 T05/T06/T09 既有能力欠账，不得在 T09-1 中以“更频繁写 Transcript”为名实现。

```text
Memory / Evidence Retrieval
```

仍是独立后续能力；`HistoryRead` 只是 exact ref-based current-Session raw evidence read，不构成 Memory 或 retrieval engine。

```text
Timeline GC
```

是本阶段明确不做的存储生命周期能力；当前设计允许 Timeline 物理增长，只约束 logical Fine Timeline，不为未来 GC 提前创建接口或占位抽象。
