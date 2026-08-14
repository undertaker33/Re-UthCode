# T09 Prompt 与 Context Engineering Spec

## 1. 背景与目标

当前仓库已有进程内 Agent Runtime、Task/Plan、Pause/Resume 与 Provider/Tool 抽象，但没有 Runtime AGENTS Loader、持久 Session、统一 Context Compiler 或模型输入限制解析；公共 Prompt、完整 working history 和永久 Tool Result 截断也尚未收口。旧 UthCode 已冻结 AGENTS 产品语义，T09 按当前模块化单体恢复语义，不继承旧运行时结构。

目标是建立 Canonical History → Projection → Context Compiler → Snapshot → Provider Integration 链路，以稳定权限前缀、真实模型限制、有界 Working Set/Compaction、single-writer Session 和可观测 Eval 支持长任务。

## 2. Scope

本 Spec 是任务书的可实施收口。只覆盖 Prompt Asset、Project Instructions、Canonical History、Projection、Model Limits、Context Compiler、Tool Result 外置、Compaction、Session persistence、Slash/TUI 与 Eval；不覆盖任务书列出的后置能力。

## 3. 按 Task 划分的能力清单

1. Task 1：Prompt Asset、Context Source 与权限平面。
2. Task 2：AGENTS / Project Instructions Loader。
3. Task 3：Canonical History 与 Projection 基础。
4. Task 4：Model Limits、Context Compiler 与确定性 Working Set。
5. Task 5：Session Store、durable append 与 single writer。
6. Task 6：大 Tool Result 外置与资源上限。
7. Task 7：有界 Compaction 与 Runtime Request Composition。
8. Task 8：Session Slash Commands 与 TUI Context Status。
9. Task 9：Context Diagnostics 与 Eval。
10. Task 10：[接入主流程] 正式 Context Composition 收口。
11. Task 11：[端到端验证] Context / Session / Prefix。
12. Task 12：[遗留负担清理] 单历史 / 单 Context Path 收口。

## 4. Domain contracts

### 4.1 Semantic history

- `HistoryEntry` 具有 session id、strict sequence、turn id、kind、payload、created_at、commit boundary。
- `SemanticUnit` 是最小选择/压缩/恢复原子；ToolCall 与 ToolResult 必须闭合后成为一个 unit。
- `CanonicalHistory` 仅 append；Projection 只引用覆盖的 sequence 范围与 revision。
- 未完整提交的尾记录恢复时忽略，不伪造业务结果。

### 4.2 Context blocks and authority

每个 Source 产出统一 block：`source_kind`、`authority`、`stability`、`scope`、`provenance`、`content`、`estimated_tokens`、`semantic_unit_id`（若有）。Provider mapper 只能转换，不得提升 authority。

稳定指令前缀顺序：Public Prompt → Core Contract → 用户 AGENTS → 项目根 AGENTS → 稳定工具/协议定义。

上下文平面顺序：Projection → retained raw history → scoped instruction delta → runtime delta → environment delta → current user turn。只有真实 Project Instruction / Core Runtime block 保留相应权限；Projection 始终是历史权限。

### 4.3 Project instructions

`InstructionLoader` 契约：

- session start 加载 user root 与 project root；路径访问惰性加载 project-root-to-target directory AGENTS；
- 只识别整行 `@include("relative/path")` / `@include('relative/path')`；代码围栏和 inline code 忽略；
- 引用相对当前文件，递归图最多 3 个额外文件；canonical physical identity 去重，Windows case-fold，循环/越界/超限/读取失败 fail closed；
- user 图限制在 user config root，project/directory 图限制在 project root；
- 返回有序、带 scope/source/reason 的 blocks 与显式 diagnostics；Application 维护 session instruction epoch 和已见 identity。

Integration 实现文件边界，Application 决定加载时机并生成 Source，Core 不读文件。

### 4.4 Model limits

统一 `ResolvedModelLimits` 至少含正整数 `max_input_tokens`、`max_output_tokens`、`source`、精确模型身份与 provenance。

解析优先级：可靠 Provider metadata → 精确 bundled metadata → 用户级 ModelProfile 显式值。项目配置只允许收紧有效限制，不能提高或替换可信物理上限。未知且无显式输入上限时，在发送前明确失败并给出可操作配置诊断。

Provider capability resolver 是 Integration 的可选实现：Anthropic 可映射 Models API；OpenAI Models API 不作为 Context Window 来源；OpenAI-compatible 要求显式配置。当前不增加 Gemini Provider，只保留可映射独立 input/output limit 的通用 contract 测试。

```text
POLICY_CAP = 258_000
effective_input_limit = min(POLICY_CAP, limits.max_input_tokens)
```

`max_output_tokens` 独立验证；Provider 如只发布 combined window，由 resolver 依据真实协议和输出 reserve 归一化。overflow 是受控最后保护，不是 discovery。

## 5. Compiler algorithm

1. 验证 resolved limits 与 Source contract。
2. 构造稳定指令序列并计算规范化 fingerprint、token estimate、change reason；工具 schema 可单独 fingerprint。
3. 放入 Protected Context：稳定指令、current user、未闭合 unit、必要协议。
4. 加入当前 Projection。
5. 从新到旧选择 recent complete semantic units，ref/preview 跟随 unit；无 relevance scorer。
6. 在尾部加入 instruction/runtime/environment deltas。
7. 若超过 effective limit，在合法 unit boundary 裁剪；需要时请求 Compaction 后重新编译一次。
8. 产出不可变 Snapshot 和 selected/omitted reasons。

`ContextSnapshot` 至少记录：effective/policy/model limits、token estimate、selected/omitted block ids、Projection revision、instruction epoch、stable prefix estimated tokens/fingerprint/changed/reason、可选 tool schema fingerprint。

仅 runtime delta 改变时，stable prefix fingerprint 必须保持不变；不得把动态 state 插入稳定前缀与 retained history 之间。

## 6. Token estimation

- estimator 是 provider-independent port；Provider-specific tokenizer 可由 Integration 注入，稳定 fallback 只用于估算，不充当模型限制发现。
- 所有消息、工具 schema、结构开销和外置 preview 都计入；诊断显示 estimate，不声称等于 Provider billing。
- effective input limit 不以 258K 或 overflow 回填未知物理限制。

## 7. Tool Result persistence

- `ToolResultPolicy` 包含基于证据确定的 inline threshold、preview limit、single-result hard cap、session quota、read page limit。
- 外置写入先检查声明/流式累计大小与 session quota，使用同 Session 临时文件、fsync、atomic rename，再写 History ref。
- 失败删除临时文件，产生受控 error result；没有 dangling ref。
- ref 为不可猜路径语义的 opaque id，解析后验证 session ownership、hash/size，read 只接受 ref + bounded offset/limit。
- 无通用路径读取，无跨 Session 读取，无 GC。

## 8. Session store and locking

### 8.1 Layout

```text
sessions/<session-id>/
├─ metadata.json
├─ history.jsonl
├─ runtime.jsonl
├─ writer.lock
└─ tool-results/
```

metadata 和 record envelope 版本化；history append-only，active Projection 由最后一个合法 ProjectionRecord 推导，不维护可变 pointer 文件。`runtime.jsonl` 只保存非权威 lifecycle/diagnostics/Eval facts，删除它不改变语义恢复；stream delta、ToolProgress、UsageUpdated 与 UI lifecycle 不写入 history。写入 sequence 前持有 writer lock。实现使用进程持有的跨平台 OS advisory/exclusive lock（Windows/POSIX 适配），不是可残留的纯存在性锁；busy 明确失败。

### 8.2 Commit and recovery

- append 采用完整 JSONL record + flush/fsync；关联 metadata/projection 采用 temp + atomic replace。
- 只恢复连续 strict sequence 和最后完整 commit boundary；损坏中段 fail closed，尾部不完整记录可诊断并忽略。
- resume 先 lock，后读取/重建，再允许新 Turn append。
- release 在 `/new`、Session close 或进程退出时发生。

### 8.3 Runtime boundary

Session store 不序列化 T08 内存 TaskState/PlanState checkpoint。跨进程恢复得到新 Run/Turn；同进程 continuation 继续由现有 Application 规则负责。

## 9. Compaction

`CompactionPolicy` 至少含 input budget、output reserve、summary hard cap、auto trigger threshold。每次请求使用 compactor 自身 resolved limits 与 policy cap；`prior projection + selected units` 必须在预算内。

超大候选按完整 semantic units 形成按时间顺序的有界滚动批次，每批以先前 summary 作为输入并受 hard cap；不拆 ToolCall/ToolResult，不调用工具，不生成层级图。single-flight 保证每 Session 一次；失败保留旧 revision。

Projection schema 至少保留目标/约束/决策/已做工作/未完成项/关键证据 ref/覆盖范围，明确其 authority=`history_projection`。

## 10. Runtime and provider integration

- Application 在每次 Provider request 前调用 Compiler，传入 resolved limits；RunState 仍是唯一写入者。
- Provider mapper 保留 semantic order/authority，并将 ToolCall/ToolResult 转为合法协议形状。
- Provider 返回 cache metrics 时继续映射现有 Usage 计数，并在 Context diagnostics 中记录 availability/provenance；现有 Usage 默认 0 可保留以避免破坏累计语义，但 Provider 不支持时必须报告 `not_available`，不能把默认 0 冒充 Provider 实测值。
- overflow 归一为受控 error；最多触发一次预算重编译/压缩保护，仍失败则停止。

## 11. Commands and UI

- `/compact [focus]`：Application compaction use case。
- `/new`：关闭旧 Session/lock，创建新 Session。
- `/resume [id]`：获取 lock、恢复 History/Projection、创建新 Turn；busy/损坏显式失败。
- `/status`：used/effective limit、258K cap、model limit source、projection revision、compact count、prefix/cache diagnostics。
- TUI ring 使用 `used/effective_input_limit`；Headless 无 TUI 依赖。

`project_key` 为规范物理 Git root；非 Git 目录使用规范物理 launch workdir。Picker 只显示同 project key Session，按 durable last_used_at 倒序，每页 10 条；上下选择、左右翻页、Enter 恢复、Esc 无副作用返回。条目显示 last-used time 与第一条 User Message 单行 bounded preview，不使用 mtime。至少 21 个候选覆盖分页。`/status` 与输入区 ring 使用 Application 同一 usage projection；草稿不计入、不可用显示 unavailable、窄终端不破坏输入。

## 12. Diagnostics and Eval

新增事件/快照 diagnostics：selected/omitted、externalized、compact start/end/fail、session busy/recovery、stable prefix fields、optional provider cache read/write tokens。不得记录秘密或完整敏感 Tool Result。

Eval 以 baseline/candidate 报告比较 success、tokens、tool calls、compact count、rediscovery、repeated exploration、externalization、prefix stability 与可用 cache reuse；不以策略优劣作为 pytest 必须红绿。

## 13. 非功能要求

- 架构：Core provider-independent、无 filesystem/SDK/UI；Interface 只通过 Application。
- 确定性：相同 Sources/limits/policy 产生相同 Snapshot/fingerprint/reasons。
- 安全：秘密不进入 Prompt、History、Log、diagnostics；ref 不是路径读取接口；未知限制 fail closed。
- 可靠性：append durable、single writer、partial-tail 可恢复、中段损坏硬失败；Tool 副作用未知时不重试。
- 性能：稳定前缀尽量复用；动态 delta 不无意义打碎长历史；Compactor/Tool Result 均有硬上限。
- 可移植性：Windows/POSIX 锁与路径身份语义有测试；不新增运行时第三方依赖。

## 14. 能力欠账

T09 后置：active/paused Runtime checkpoint；Task/Plan/Pending Tool/Permission/AskUser/Provider continuation 的跨进程恢复；久远证据 Retrieval/Memory；Artifact GC；高级层级压缩/后台 Context Agent；Skill/MCP/Subagent/Multi-Agent context。AGENTS、Model Limits、single writer、Compactor budget 和 Result quota 不属于欠账。

## 15. Out of Scope

不实施 Memory、长期记忆、Skill、MCP deferred loading、Subagent/Multi-Agent、Embedding/Vector DB、复杂 Artifact Store/GC、Provider-specific Prompt/Overlay、模型专用 Context policy、复杂 Progressive Compression Graph、后台上下文 Agent、OS Sandbox 或旧行为兼容层。

## 16. 验收标准

必须覆盖：prefix stability、authority non-escalation、small/large-window、unknown compatible model、完整 AGENTS frozen semantics、compactor overflow、concurrent resume、runtime recovery boundary、result hard cap/quota/ref isolation、strict sequence/durable append，以及 Provider mapper/Usage 可选 cache metrics。

最终执行定向、架构和全量测试，并同步任务书指定文档。未运行项必须明确记录。
