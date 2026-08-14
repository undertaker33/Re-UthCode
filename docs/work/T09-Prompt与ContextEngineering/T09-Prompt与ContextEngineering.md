# T09 Prompt 与 Context Engineering

## 0. 工作包状态

- 状态：`not_implemented`
- 当前阶段：任务包已返工，尚未显式派发任何 Worker Prompt，未冻结。
- 本工作包只定义 T09 的生产实现边界；本次返工不实施生产代码。
- 当前事实基线：`685d85d8ad97c733151e3cd54655cf848343753a`。

## 1. 背景与真实基线

T08 已提供进程内 `RunState`、`Turn`、`TaskState`、`PlanState`、Pause / Resume 与 AskUser，但当前仓库仍没有：

- Prompt Asset 与统一 Context Compiler；
- 持久化 Canonical Semantic History、Projection 与 `/resume`；
- 大 Tool Result 外置与受限读取；
- Runtime AGENTS / Project Instructions Loader；
- 可供 Compiler 使用的正式 Context Engine 工作预算。

AGENTS 需要区分两件事：仓库根 `AGENTS.md` 是开发代理约束；UthCode Runtime 当前并未加载它。旧 UthCode 的 Day7 工作包已经冻结并实现过用户级、项目级、目录级 AGENTS 与引用语义。T09 必须恢复这项正式产品需求，但按 Re-UthCode 当前模块化单体重建，不复制旧 LangGraph、旧工具或旧运行时结构。

当前 `ModelProfile` 只有 `max_output_tokens`，没有模型输入限制；ProviderPort 也没有统一 capability discovery。真实模型窗口发现、不同窗口适配和 258K Operating Profile 优化已正式后置为 T09-1，不在 T09 建立临时或猜测式 Model Limits 体系。

## 2. 目标

建立下列单向链路：

```text
Canonical Semantic History
        ↓ Projection（派生，不回写 History）
Context Sources + fixed 258K Operating Budget
        ↓ Context Compiler
Context Snapshot
        ↓ Provider Integration（仅协议映射）
```

交付目标：

1. Public Coding Prompt 迁入 package Prompt Asset，并与 Core Runtime Contract 分离；Core Runtime Contract 继续由 Core 权威维护。
2. 恢复既有 AGENTS / Project Instructions 产品语义，并通过明确 Source 进入 Compiler。
3. 完整 Session 语义历史与本轮 Working Context 分离；History 是事实源，Projection 是派生视图。
4. 建立固定 258K Context Operating Budget 下的 provider-independent Context Compiler。
5. 使用确定性 Working Set、受限 Tool Result 与有界 Compactor 构造可发送 Snapshot。
6. 持久化完整提交边界上的 History / Projection，提供 single-writer `/resume`。
7. 加入 Prompt / Context / Prefix Cache diagnostics 与可重复 Eval，提供机制和 baseline，不提前进行 T09-1 阈值优化。

## 3. 非目标

T09 不建设：Memory、长期记忆检索、Skill、MCP deferred loading、Subagent Context Isolation、Multi-Agent、Embedding Retriever、Vector DB、复杂 Artifact Store / GC、Provider-specific Prompt 套件、模型专用 Prompt Overlay、复杂 Progressive Compression Graph、后台上下文维护 Agent 的最终实现。

三种上下文维护方向如历史探索材料已有记录，可继续作为未来比较项；T09 不选定或实现其中的高级形态。

## 4. 权威模型与不变量

### 4.1 Canonical History

- History 是 append-only 的完整语义事实来源。
- Projection、Compaction、Working Set、Snapshot 均不得删除、改写或覆盖原事件。
- 每个 `ToolCall` 必须与对应 `ToolResult` 组成不可拆断的 semantic unit。
- Provider Integration 不拥有 History、Projection 或 Context policy。

### 4.2 权限不升级

```text
历史 User / Assistant / Tool 内容
        ↓ Projection / Compaction
仍属于历史上下文
```

Summary 不因由模型生成而升级为 Core/System authority。Compiler 的 typed source/authority 必须保留来源语义；Provider 角色映射必须证明 Projection 仍位于历史/上下文平面。包含 instruction-like 文本的用户或工具内容在压缩后也不得成为系统指令。

### 4.3 Session 与 Runtime State

- 同进程失败或取消 Turn 后，`TaskState` / `PlanState` 继续遵守 T08 现有进程内规则。
- 跨进程 `/resume` 只恢复最后完整提交边界的 Canonical History、Projection 与 Session 元数据，并开始一个新 Turn。
- T09 不持久化或恢复旧进程内存中的 active/paused Turn、TaskState、PlanState、Pending Tool、Permission、AskUser waiter、Provider 请求或协程位置。
- Agent 可以依据恢复后的语义历史重新建立 Task/Plan，但这不是 checkpoint 恢复保证。

### 4.4 Session single writer

- 一个 Session 同一时刻只允许一个进程持有写权。
- `/resume` 必须先取得进程生命周期内持有的排他 OS 文件锁，再重建并 append；第二个进程 fail closed 为 `session busy`。
- 锁随进程/文件描述符释放，避免崩溃留下永久逻辑锁；不得用仅靠先检查后创建的竞态协议。
- `sequence` 严格单调、append durable，恢复只接受完整事务/记录边界；并发恢复不得产生双 sequence。

## 5. Prompt 与 Context 平面

### 5.1 Stable Instruction Prefix

稳定、长期不变且具有真实指令权限的内容形成稳定前缀：

```text
Stable Instruction Prefix
├─ Public Coding Prompt
├─ Core Runtime Contract
├─ Session 启动时加载的稳定用户级 AGENTS
├─ Session 启动时加载的项目根 AGENTS
└─ 其他稳定工具/协议定义
```

### 5.2 Conversation / Contextual Plane

```text
Conversation / Contextual Plane
├─ Projection / Compaction Summary（历史权限）
├─ retained raw semantic history
├─ 目录级 Project Instruction update / delta（按其真实权限）
├─ TaskState / PlanState runtime update / delta
├─ Environment update（必要时）
└─ current user turn
```

具体 Provider message role 由 Integration 根据协议映射，但不得改变 typed authority。高频变化的 TaskState、PlanState、one-shot feedback、Projection revision、环境变化不得插入稳定前缀与长历史之间。目录级 AGENTS 在路径首次命中时作为带 scope 的 instruction delta 追加；同 Session 内文件变化也产生新 epoch/delta，而不是回写旧前缀。

### 5.3 Authority transport contract

Python 内部 `authority` 字段不会自动被模型理解。Core Runtime Contract 必须预先声明：UthCode Runtime 可以在 Contextual Plane 注入由受信任 Runtime 构造边界产生的强类型更新；其权限来自 typed source、Compiler 构造与 Provider mapping contract，而不是块内 Markdown 标签。

```text
typed source / authority
        ↓
Context Compiler semantic item
        ↓
GenerationRequest 可表达的权限与顺序
        ↓
Provider Integration 最小 wire mapping
```

正式约束：

1. `ProjectInstructionUpdate`、`RuntimeStateUpdate`、`EnvironmentUpdate` 必须保留各自语义和尾部顺序。
2. 普通 User/Tool 历史即使伪造 `[RuntimeStateUpdate]` 等标签，也只能保持原 history authority。
3. Projection 不能映射成 System/Core instruction。
4. 动态 Runtime/Project update 不能全部重建到 system prompt 前部，也不能降级成普通 User history 裸文本。
5. Worker 根据当前正式 Provider 协议选择最小映射，并用 Integration contract tests 证明 ordinary history 不能伪造 Runtime/Project authority；Integration 不拥有 Context policy。
6. 若现有统一 `GenerationRequest` 无法表达该边界，必须在 Core/Application 的 provider-independent contract 收口，不采用 Provider-specific Prompt hack。

当前事实代码中的 `GenerationRequest` 只有单一 `system_prompt` 与普通 `messages`，尚不能显式区分尾部的 runtime-authenticated Project/Runtime update 和 ordinary history；这是 T09 必须收口的真实 Core/Application DTO 缺口，不得退回“全塞 system prompt”或“伪装成 User history”。

### 5.4 Context Source contract

至少包含：

- `PromptAssetSource`
- `ProjectInstructionSource`
- `HistoryProjectionSource`
- `RuntimeStateSource`
- `EnvironmentSource`
- `ToolDefinitionSource`

Source 提供 typed block、authority、stability、scope、provenance 与估算信息；Compiler 只消费统一 Source，不直接读 Provider SDK、文件系统或 TOML。

## 6. AGENTS / Project Instructions

### 6.1 冻结产品语义

T09 必须按历史已冻结定义实现：

1. 新 Session 先加载用户配置目录 `AGENTS.md`，再加载项目根 `AGENTS.md`。
2. Read/Edit 等路径访问首次进入子目录时，按项目根到目标目录顺序惰性发现目录级 `AGENTS.md`，只发出新命中范围。
3. 广域到窄域按加载顺序组合，不做隐式覆盖；保留 source、scope、load order 与 reason。
4. 历史实际语法是整行 `@include("path")` 或单引号形式，不是任意裸 `@file`。围栏代码与行内代码中的 `@` 不解析。
5. 引用相对包含它的文件解析，递归展开；整个加载图最多额外加载 3 个被引用文件，第 4 个明确失败。
6. 以规范化物理路径/文件身份去重；Windows 路径大小写不敏感；检测直接和间接循环。
7. 用户级引用受用户配置根约束，项目/目录级引用受项目根约束；越界、读取失败、循环和超限均显式诊断并 fail closed。
8. 用户级 AGENTS 只能通过明确授权修改；项目级 AGENTS 遵守普通 workspace 权限。未来 Memory/Dream 不得修改 AGENTS。

### 6.2 当前架构落点

- Integration 负责文件发现、规范路径、物理身份、读取和 OS 边界。
- Application 负责加载时机、Session/路径 scope、去重状态与 Source 组合。
- Core 只接收 provider-independent 的 instruction block / authority，不读取文件。
- Interface 不直接调用 Loader，只通过 Application。

## 7. 固定 258K Context Operating Budget

```text
UTHCODE_CONTEXT_BUDGET_TOKENS = 258_000
```

258K 是 T09 Context Engine 的固定工作预算 / Operating Budget，不是所有远端模型真实物理 Context Window 的声明。T09 不发现 model window，不计算 `min(model_window, 258K)`，不改 `ModelProfile` 输入限制，不查询 Provider metadata，不维护 bundled context metadata，也不按模型改变 TUI denominator。

真实模型窗口、统一 Model Limits contract、小/大窗口适配和 258K 专项阈值优化由 T09-1 探索。Provider overflow 在 T09 仍只是最后保护，可触发一次受控 Compaction/重编译；它不是窗口发现机制，也不能无限重试。

## 8. Context Compiler 与 Working Set

### 8.1 Snapshot

Compiler 输入为 Sources、固定 258K Operating Budget 与 token estimator，输出不可变 `ContextSnapshot`，至少记录 selected/omitted blocks、token estimate、固定 budget、Projection revision、instruction epoch、stable-prefix diagnostics 与原因。

### 8.2 确定性 Working Set

T09 没有 retriever、embedding、relevance scorer、evidence graph、Memory 或后台 context agent，因此禁止实现“任务相关性算法”、关键词匹配或 embedding。

按以下确定性顺序选择：

1. Protected Context：稳定指令、current user turn、当前未闭合 semantic unit 与必要协议定义。
2. Projection / prior summary。
3. recent complete turns：从新到旧按预算选择完整 semantic units。
4. Tool Result preview/ref 只跟随被保留的 semantic unit；不得单独漂移。
5. runtime/environment/instruction delta 位于当前 Turn 附近。

80 Turn 前仍重要的证据检索属于未来 Evidence Retrieval / Memory，不在 T09 偷加启发式。

### 8.3 Prefix Cache diagnostics

至少记录：

- `stable_prefix_estimated_tokens`
- `stable_prefix_fingerprint`
- `prefix_changed`
- `prefix_change_reason`
- 可选 `tool_schema_fingerprint`

fingerprint 基于 Compiler 实际稳定语义序列的确定性规范化表示，只保存不可逆摘要和安全元数据，不复制原始 Context 文本；这不要求通用 secret scanner。仅 TaskState / Runtime State 更新时，稳定前缀 fingerprint 不变，历史公共前缀可继续复用。Provider 若返回 `cache_read_input_tokens`、`cache_creation/write_input_tokens` 或 `cached_input_tokens`，Integration 可继续映射现有 Usage token 计数，同时提供可选的 metrics availability/provenance；不支持时 diagnostics 为 `not_available`，不得把现有数值默认 0 解释成“Provider 明确报告 0”。不要求所有 Provider 支持同一指标。

T09 只保证 prefix 结构和可观测机制正确，不冻结最佳 compact threshold、headroom、Working Set 比例、recent-tail 大小、不同模型档位或按物理窗口百分比 trigger；这些属于 T09-1 Eval/优化。

## 9. 大 Tool Result 外置

- Tool 执行返回完整领域 `ToolResult`，Application 在写入 History 前决定内联或外置。
- 外置采用 temp + flush/fsync + atomic rename，成功后 History 只保存 bounded preview、opaque session-scoped ref、大小/hash/截断元数据。
- `ToolResultRead` 只解析 opaque ref，校验 Session ownership，并以 offset/limit 有界读取；不得接受任意路径。
- 实施前用代表性输出和文件系统边界测试确定并记录：单 Result 持久化 hard cap、单 Session Result quota、preview/read limit。不能无依据拍常数。
- 超过单项或 Session quota 返回明确 `result_too_large` / `session_result_quota_exceeded` 受控 ToolResult，不留下部分文件或可用 ref。
- T09 不实现通用 Artifact GC。

### 9.1 Tool execution 与 materialization 是不同事实

Tool 是否执行成功，与结果是否成功 materialize/persist 必须分别表达。若 Edit、Bash、网络请求等副作用已经发生，后续结果过大、quota 或持久化失败不得伪造为“Tool 未执行”，不得因此自动重试可能有副作用的 Tool。

最小 contract 必须让模型、History 与 Runtime diagnostics 区分 execution outcome 和 result persistence outcome，同时保持原 ToolCall ID、FIFO、Permission、cancel 与既有 `is_error` 语义。具体数据模型由 Worker 根据当前 Core Tool contract 收口，不提前建设复杂状态机。

## 10. Compaction

### 10.1 触发与语义

支持手动 `/compact` 与自动阈值触发。第一版没有 focus 参数。Compactor 是 tool-free、provider-independent 的专用请求；输出 Projection revision，不删除 History，不获得更高权限。

### 10.2 Compactor 自身预算

每次压缩请求必须有独立硬预算：

```text
CompactionInputBudget
CompactionOutputReserve
SummaryHardCap
```

`prior projection + candidate semantic history` 必须位于 effective compactor input limit 内。候选过大时，只能在完整 semantic boundary 上切分，按时间顺序进行简单的有界滚动批次；每批输入和输出分别受限。不得拆断 ToolCall/ToolResult，不得绕过 Compiler，也不建设 summary graph。

自动阈值、手动触发、Provider overflow 保护共用 single-flight：同一 Session 同时只有一个 Compaction；失败保留旧 Projection 和完整 History。

## 11. Session 持久化与命令

Session identity 与 Run / Turn identity 分离。Git 工作目录以规范化物理 repository root 作为 `project_key`；非 Git 目录以规范化物理 launch workdir 作为 `project_key`。`/resume` 默认只发现相同 `project_key` 的 Session，不跨项目兜底。

Session 目录至少包含：

```text
sessions/<session-id>/
├─ metadata.json              # schema、project_key、created/last_used
├─ history.jsonl              # InteractionRecord + ProjectionRecord
├─ runtime.jsonl              # 非语义权威 lifecycle/diagnostics/Eval facts
├─ writer.lock
└─ tool-results/              # session-scoped 完整结果
```

`runtime.jsonl` 丢失不得改变语义恢复；Stream delta、ToolProgress、UsageUpdated、UI lifecycle 不进入 Canonical History。active Projection 由 history 中最后一个合法、完整提交的 ProjectionRecord 推导，不增加可变 current pointer。所有 envelope/version/kind/sequence/turn/call/ref 字段严格校验，未知 schema/kind 和中段损坏 fail closed。

UthCode Runtime 自身持有的 Provider Credential、API Key、配置秘密、内部敏感构造信息和可能含秘密的原始异常，不得因 Context/Session 基础设施被主动注入 Prompt、History、Runtime Log 或 diagnostics。用户显式提供或经正常 Permission/Tool 语义产生的内容按既有 Session 语义处理；T09 不实现通用 Secret Detection、DLP 或自动脱敏系统。Diagnostics 仍不得额外复制 credential、完整大型 Tool Result、Provider native payload 或未脱敏内部异常。

- `/compact`：触发有界压缩，成功后使用新 Projection。
- `/new`：结束当前 Session 持有权，创建空 History 新 Session，保留用户/项目配置。
- `/resume [session_id]`：获取 single-writer lock，恢复最后完整提交边界的 History/Projection，开始新 Turn；无 id 时使用现有选择契约。
- `/status`：显示 `used_tokens / 258K`、固定 Operating Budget 说明、compact count、Projection revision 与可选 prefix/cache diagnostics。

TUI context ring 按固定 258K Operating Budget 计算；颜色阈值保持语义一致。Headless Application 路径必须独立工作。

### 11.1 `/resume` Session Picker

`/resume` 使用独立 Picker，不复用 slash completion：候选按 durable `last_used_at DESC` 排序，每页固定 10 条；`↑/↓` 选择、`←/→` 翻页、Enter 恢复、Esc 无状态变化返回。每条显示 durable last-used time 与第一条 User Message 的单行 bounded preview，按终端宽度省略；不得用文件 mtime 作为产品真值。Picker 只持有页码/选择索引等 UI 临时状态，发现、排序、重建和 lock 均由 Application 提供。至少 21 个 Session 的测试覆盖分页边界。

Context usage 只读 projection 由 Application/Context Engine 提供，至少含 `used_tokens`、固定 `budget_tokens=258_000`、ratio 与 availability。`/status` 线性条和输入区终端环形指示器使用同一 projection，并明确该分母是 UthCode T09 Operating Budget，不是远端物理窗口；草稿不计入，稳定边界后刷新，active Turn 可显示最近稳定值，未知时显示 unavailable 而非 0%。窄终端优先保留 ring/百分比且不影响输入。

## 12. Eval 与可观测性

Eval 用于比较策略效果，不把上下文策略写成 pytest 红绿门槛。至少比较 baseline / candidate 的：success、input/output tokens、tool calls、compact count、rediscovery、repeated exploration、externalization、stable prefix、provider cache reuse（可获得时）。

必须包含场景：

1. 长历史不变，仅 TaskState 更新，稳定前缀 fingerprint 不变且历史 prefix 不被无意义打碎。
2. User/Tool instruction-like 文本经 summary 后仍为历史权限。
3. 普通 User/Tool 历史伪造 Runtime/Project update 标签时，仍不能获得对应 authority。
4. 固定 258K Budget 下 Working Set、Compaction 与 status/ring 口径一致。
5. AGENTS 用户/项目/目录 scope、`@include` 递归、去重、循环、3 文件限制、越界和代码块忽略。
6. Compactor 候选超过其输入预算时按完整 semantic boundary 分批。
7. 两进程 resume 同 Session 时只有一个 writer，无双 sequence 或 corruption。
8. 同进程 Turn continuation 与跨进程 Session resume 符合边界。
9. 单 Result hard cap、Session quota 与 ref 越权读取失败。
10. Tool 已成功执行但 persistence 失败时，不伪造 Tool 未执行，也不自动重试副作用。

## 13. 实施顺序与 Worker

1. Prompt / Context Source / AGENTS contract。
2. Canonical History / Projection。
3. Context Compiler / fixed 258K Budget / deterministic Working Set。
4. Session single-writer persistence。
5. Tool Result externalization。
6. bounded Compaction / runtime composition。
7. Slash / TUI。
8. Eval / diagnostics。
9. integration、E2E、cleanup。

Worker 数保持 W01～W06，不因问题数量机械扩张；精确 Task 分配见 Tasks 与 Prompt。

## 13.1 现有产品闭环不得丢失

- `/compact` 只在 idle 安全边界手动执行；active Turn 返回 unavailable，不暗中暂停。
- `/new` 创建新 Session/Run 并保持旧 Session 文件不变；`/clear` 不等于 `/new`。
- Tool Result 外置不得改变 call id、FIFO、Permission、`is_error`、取消或普通错误语义。
- completed Turn 收口 active Task/Plan；failed/cancelled 且仍有 unfinished Task 的同进程下一 Turn 按 T08 规则 reconcile；one-shot feedback 不自动延续。
- 保持 Interaction History、Projection、Context Snapshot、Runtime State、Runtime Log 五类事实分离，不重新塞回一个 `messages`、Snapshot 文件或通用 Event 流。
- 不新增动态 Context Source Registry、SQLite checkpoint、第二 Agent Loop、scheduler 或 workflow。

## 14. 验收与文档同步

- 定向测试覆盖所有第 12 节场景，架构变化运行 `tests/test_architecture_boundaries.py`，最终运行全量测试。
- 任务书、Spec、Tasks、Checklist、W01～W06 Prompt 的 Task 名称、顺序、依赖和范围必须一致。
- 包级验收同步 `docs/context/A03-State/State-Context.md`、`docs/context/A04-Interface/Interface-Context.md`、`docs/UserManual.md`、`docs/Context-Index.md`、`docs/OutstandingDebtList.md` 与代码事实。
- Feedback 仅在 Worker 被实际派发并执行后创建；本次返工不创建。

## 15. 能力欠账

T09 完成后仍明确后置：

- T09-1：真实 Context Window / max input discovery、Provider metadata、bundled metadata、自定义模型显式配置、统一 Model Limits、不同窗口 Budget Resolver、小/大窗口适配、258K Operating Profile、Working Set/Compaction/headroom 阈值与 Prefix Cache/token/success Eval 调优；
- active/paused Turn、TaskState、PlanState、Pending Tool、Permission、AskUser waiter、Provider 请求与协程位置的跨进程 checkpoint / recovery；
- Memory / Evidence Retrieval 对久远但重要证据的选择；
- 通用 Artifact 生命周期与 GC；
- 高级 progressive/hierarchical compression、后台 Context Agent；
- Skill、MCP deferred loading、Subagent/Multi-Agent context isolation。

AGENTS / Project Instructions、Context Compiler、固定 258K Operating Budget、Session single writer、Compactor hard budget 和 Tool Result 最薄资源上限均属于 T09 正式范围。Model Limits 与不同窗口适配属于 T09-1，不得在 T09 Worker 中实施。
