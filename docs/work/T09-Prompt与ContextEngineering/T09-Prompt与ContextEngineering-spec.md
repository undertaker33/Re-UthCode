# T09 Prompt 与 Context Engineering Spec

## 1. 背景与目标

当前仓库已有进程内 Agent Runtime、Task/Plan、Pause/Resume 与 Provider/Tool 抽象，但没有 Runtime AGENTS Loader、持久 Session 或统一 Context Compiler；公共 Prompt、完整 working history 和永久 Tool Result 截断也尚未收口。旧 UthCode 已冻结 AGENTS 产品语义，T09 按当前模块化单体恢复语义，不继承旧运行时结构。模型真实窗口与不同窗口适配后置为 T09-1。

目标是建立 Canonical History → Projection → Context Compiler → Snapshot → Provider Integration 链路，以稳定权限前缀、固定 258K Operating Budget、有界 Working Set/Compaction、single-writer Session 和可观测 Eval 支持长任务。

## 2. Scope

本 Spec 是任务书的可实施收口。只覆盖 Prompt Asset、Project Instructions、Canonical History、Projection、固定 258K Budget、Context Compiler、Tool Result 外置、Compaction、Session persistence、Slash/TUI 与 Eval；不覆盖 T09-1 和任务书列出的后置能力。

## 3. 按 Task 划分的能力清单

1. Task 1：Prompt Asset、Context Source 与权限平面。
2. Task 2：AGENTS / Project Instructions Loader。
3. Task 3：Canonical History 与 Projection 基础。
4. Task 4：Context Compiler、258K Budget 与确定性 Working Set。
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

稳定指令前缀顺序：Public Prompt → Core Contract → 用户 AGENTS → 项目根 AGENTS → 当前作用域已生效的目录 AGENTS → 稳定工具/协议定义。该有序集合是 Instruction Plane，以 `instruction_epoch` 标识版本。

Conversation Plane 顺序：Projection → retained raw history → runtime facts/delta → environment facts/delta → current user turn。Projection 始终是历史权限；Runtime facts 不是 Instructions。

内部 authority 用于 Context policy、排序、校验和 Provider mapping，不能创造 Provider 不存在的权限 role。真正需要 instruction authority 的 Public Prompt/Core Contract/AGENTS 必须来自受信任 Source，经 Compiler 分类进入 Instruction Plane；普通 User/Tool 即使伪造标签也只在 Conversation Plane。目录 AGENTS 新 scope 或内容变化创建新 Instruction Epoch，而不是作为 history-tail 高权限消息。当前基线 DTO 的 `system_prompt + messages` 已可对应单一指令通道与会话通道；Task 7 负责正式化这两个 provider-independent 平面，只有真实需要时才扩展 DTO，Integration 不私拼 Context policy。

### 4.3 Project instructions

`InstructionLoader` 契约：

- session start 加载 user root 与 project root；路径访问惰性加载 project-root-to-target directory AGENTS；
- 只识别整行 `@include("relative/path")` / `@include('relative/path')`；代码围栏和 inline code 忽略；
- 引用相对当前文件，递归图最多 3 个额外文件；canonical physical identity 去重，Windows case-fold，循环/越界/超限/读取失败 fail closed；
- user 图限制在 user config root，project/directory 图限制在 project root；
- 返回有序、带 scope/source/reason 的 blocks、当前有效 instruction set 与显式 diagnostics；Application 维护 session instruction epoch 和已见 identity；新 scope 首次生效或已生效内容变化时创建新 epoch，未变化的重复访问不创建。

Integration 实现文件边界，Application 决定加载时机并生成 Source，Core 不读文件。

### 4.4 Fixed Context Operating Budget

T09 固定使用 258,000-token Context Operating Budget。它是 UthCode 工作档位，不是远端模型物理窗口声明。T09 不发现模型窗口、不建立 Model Limits contract、不修改 ModelProfile 输入字段、不查询 Provider/bundled metadata，也不做小/大窗口适配。相关能力及阈值优化由 T09-1 探索。

阶段限制：T09-1 完成前，不保证真实输入窗口小于 258K 的模型能安全运行到 T09 的长上下文规模。Provider overflow 最多触发一次受控 Compaction/重编译，不能用于反推窗口或动态修改 budget。

## 5. Compiler algorithm

1. 验证 Source contract，并加载固定 258K Operating Budget。
2. 从当前 Instruction State 构造 Instruction Plane，并计算 `instruction_epoch`、规范化 fingerprint、token estimate、change reason；工具 schema 可单独 fingerprint。
3. 放入 Protected Context：稳定指令、current user、未闭合 unit、必要协议。
4. 加入当前 Projection。
5. 从新到旧选择 recent complete semantic units，ref/preview 跟随 unit；无 relevance scorer。
6. 在尾部加入 runtime/environment deltas。
7. 若超过固定 budget，在合法 unit boundary 裁剪；需要时请求 Compaction 后重新编译一次。
8. 产出不可变 Snapshot 和 selected/omitted reasons。

`ContextSnapshot` 至少记录：固定 budget、token estimate、selected/omitted block ids、Projection revision、instruction epoch、stable prefix estimated tokens/fingerprint/changed/reason、可选 tool schema fingerprint。

仅 runtime/environment 或 Projection/Compaction revision 改变时，instruction epoch 与 stable prefix fingerprint 必须保持不变；不得把动态 state 插入稳定前缀与 retained history 之间。新目录 AGENTS 首次生效或已生效内容变化时创建新 epoch，允许 fingerprint 改变并记录 `instruction_scope_added` / `instruction_content_changed` 等原因；未变化的已生效 AGENTS 保持复用。

## 6. Token estimation

- estimator 是 provider-independent port；Provider-specific tokenizer 可由 Integration 注入，稳定 fallback 只用于固定预算下的估算。
- 所有消息、工具 schema、结构开销和外置 preview 都计入；诊断显示 estimate，不声称等于 Provider billing。
- 258K 与估算结果不解释为远端模型物理窗口；overflow 只作一次最后保护，不作窗口发现。

## 7. Tool Result persistence

- `ToolResultPolicy` 包含基于证据确定的 inline threshold、preview limit、single-result hard cap、session quota、read page limit。
- 外置写入先检查声明/流式累计大小与 session quota，使用同 Session 临时文件、fsync、atomic rename，再写 History ref。
- 失败删除临时文件，产生受控 error result；没有 dangling ref。
- ref 为不可猜路径语义的 opaque id，解析后验证 session ownership、hash/size，read 只接受 ref + bounded offset/limit。
- 无通用路径读取，无跨 Session 读取，无 GC。

Tool execution outcome 与 result materialization/persistence outcome 是两个事实。副作用已经发生后，quota 或持久化失败不能伪造成 Tool 未执行，不能触发自动副作用重试；模型、History 和 Runtime diagnostics 必须得到不误导执行真值的受控表达，同时保持 call id、FIFO、Permission、cancel 与既有 `is_error` 语义。

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

`CompactionPolicy` 至少含 input budget、output reserve、summary hard cap、auto trigger threshold。每次请求受固定 T09 Operating Budget 和 Compactor 自身硬预算约束；`prior projection + selected units` 必须在预算内。

超大候选按完整 semantic units 形成按时间顺序的有界滚动批次，每批以先前 summary 作为输入并受 hard cap；不拆 ToolCall/ToolResult，不调用工具，不生成层级图。single-flight 保证每 Session 一次；失败保留旧 revision。

Projection schema 至少保留目标/约束/决策/已做工作/未完成项/关键证据 ref/覆盖范围，明确其 authority=`history_projection`。

## 10. Runtime and provider integration

- Application 在每次 Provider request 前调用 Compiler，使用固定 258K Budget；RunState 仍是唯一写入者。
- 统一 request contract 表达 Instruction Plane、Conversation Plane 与 Tool Definitions；Provider mapper 仅映射到原生 `system`/`instructions`/system message 和会话协议，并将 ToolCall/ToolResult 转为合法形状。Core 不按 Provider 名称分支，ordinary history 伪造标签不能进入 Instruction Plane。
- Provider 返回 cache metrics 时继续映射现有 Usage 计数，并在 Context diagnostics 中记录 availability/provenance；现有 Usage 默认 0 可保留以避免破坏累计语义，但 Provider 不支持时必须报告 `not_available`，不能把默认 0 冒充 Provider 实测值。
- overflow 归一为受控 error；最多触发一次预算重编译/压缩保护，仍失败则停止。

## 11. Commands and UI

- `/compact`：无参数的 Application compaction use case。
- `/new`：关闭旧 Session/lock，创建新 Session。
- `/resume [id]`：获取 lock、恢复 History/Projection、创建新 Turn；busy/损坏显式失败。
- `/status`：used/258K Operating Budget、projection revision、compact count、prefix/cache diagnostics。
- TUI ring 使用 `used_tokens/258_000`，并说明分母不是远端模型物理窗口；Headless 无 TUI 依赖。

`project_key` 为规范物理 Git root；非 Git 目录使用规范物理 launch workdir。Picker 只显示同 project key Session，按 durable last_used_at 倒序，每页 10 条；上下选择、左右翻页、Enter 恢复、Esc 无副作用返回。条目显示 last-used time 与第一条 User Message 单行 bounded preview，不使用 mtime。至少 21 个候选覆盖分页。`/status` 与输入区 ring 使用 Application 同一 usage projection；草稿不计入、不可用显示 unavailable、窄终端不破坏输入。

## 12. Diagnostics and Eval

新增事件/快照 diagnostics：selected/omitted、externalized、compact start/end/fail、session busy/recovery、`instruction_epoch`、stable prefix fields/change reason、optional provider cache read/write tokens。Diagnostics 不得额外复制 Runtime credential/API key、完整大型 Tool Result、Provider native payload 或未脱敏内部异常。

Eval 以 baseline/candidate 报告比较 success、tokens、tool calls、compact count、rediscovery、repeated exploration、externalization、prefix stability 与可用 cache reuse；不以策略优劣作为 pytest 必须红绿。

## 13. 非功能要求

- 架构：Core provider-independent、无 filesystem/SDK/UI；Interface 只通过 Application。
- 确定性：相同 Sources/固定 Budget 产生相同 Snapshot/fingerprint/reasons。
- 安全：Runtime 自身 credential、配置秘密和内部敏感构造信息不得被基础设施主动注入 Prompt/History/Log/diagnostics；用户显式或经正常 Tool/Permission 产生的语义内容照常进入 Session。T09 不实现通用 Secret/DLP。ref 不是路径读取接口。
- 可靠性：append durable、single writer、partial-tail 可恢复、中段损坏硬失败；Tool 副作用未知时不重试。
- 性能：Runtime/Projection 动态变化不扰动 Instruction Plane；AGENTS 权限集合真实变化允许创建可解释的新 prefix epoch；Compactor/Tool Result 均有硬上限。
- 可移植性：Windows/POSIX 锁与路径身份语义有测试；不新增运行时第三方依赖。

## 14. 能力欠账

T09-1 后置：真实 Context Window/max input discovery、Provider/bundled metadata、自定义模型显式配置、统一 Model Limits、不同窗口 Budget Resolver、小/大窗口适配、258K Operating Profile 与 Working Set/Compaction/headroom/Prefix Cache Eval 调优。该欠账正式解决 T09 固定预算阶段对真实窗口小于 258K 模型不保证长上下文安全的问题。

其他后置：active/paused Runtime checkpoint；Task/Plan/Pending Tool/Permission/AskUser/Provider continuation 的跨进程恢复；久远证据 Retrieval/Memory；Artifact GC；高级层级压缩/后台 Context Agent；Skill/MCP/Subagent/Multi-Agent context。AGENTS、固定 258K Budget、single writer、Compactor budget 和 Result quota 不属于欠账。

## 15. Out of Scope

不实施 T09-1 Model Limits/不同窗口适配/Operating Profile 优化、Memory、长期记忆、Skill、MCP deferred loading、Subagent/Multi-Agent、Embedding/Vector DB、复杂 Artifact Store/GC、Provider-specific Prompt/Overlay、模型专用 Context policy、复杂 Progressive Compression Graph、后台上下文 Agent、OS Sandbox 或旧行为兼容层。

## 16. 验收标准

必须覆盖：runtime/projection prefix stability、directory AGENTS epoch change 与 stable reuse、ordinary history authority spoof rejection、Projection authority non-escalation、固定 258K Budget及小窗口阶段边界、完整 AGENTS frozen semantics、compactor overflow、concurrent resume、runtime recovery boundary、result hard cap/quota/ref isolation、execution/persistence outcome 区分、strict sequence/durable append，以及 Provider mapper/Usage 可选 cache metrics。

最终执行定向、架构和全量测试，并同步任务书指定文档。未运行项必须明确记录。
