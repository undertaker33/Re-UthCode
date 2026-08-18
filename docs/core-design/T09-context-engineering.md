# T09：让长期会话拥有可治理的上下文

一次模型请求只需要一份 Prompt，但长期 Coding Session 需要回答更多问题：哪些事实必须永久保留，哪些内容只属于本轮工作集，工具返回过大时如何处理，进程退出后又能恢复到什么程度。UthCode 因此把“完整会话事实”和“本轮发送给模型的上下文”分开管理。

```text
Canonical History
        ↓
Projection
        ↓
Context Compiler
        ↓
Context Snapshot
        ↓
GenerationRequest
        ↓
Provider Integration
```

## History 是事实，Snapshot 是工作集

`CanonicalHistory` 以 append-only 方式保存已经提交的 User、Assistant、ToolCall 和 ToolResult 语义事实。它不会因为模型窗口有限而被重写或删除。

`Projection` 是从完整 History 派生的历史视图。它可以用摘要替代较早的原始单元，但仍然只有 history authority：用户或 Tool 返回中的 instruction-like 文本即使被总结，也不会升级为 Core 或 System instruction。

`ContextSnapshot` 是某一次 Provider 请求真正使用的内容。当前 Compiler 使用确定性 Working Set：

```text
Protected Context
+ active Projection
+ recent complete semantic units
+ current Turn runtime/environment facts
+ current user turn
```

选择只在完整 semantic unit 边界发生，不能拆开 ToolCall 与对应 ToolResult。当前没有 embedding、关键词相关性评分、Memory retrieval 或后台 Context Agent，因此不能声称会自动找回很久以前但“相关”的证据。

## Instruction Plane 与 Conversation Plane

Context Compiler 把请求分成三个结构化部分：

```text
GenerationRequest
├─ Instruction Plane
│  ├─ Public Coding Prompt
│  ├─ Core Runtime Contract
│  └─ effective AGENTS
├─ Conversation Plane
│  ├─ Projection
│  ├─ retained History
│  ├─ Runtime / Environment facts
│  └─ current user turn
└─ tools
   └─ Tool System 提供的唯一 Tool Schema
```

只有受信任的 Prompt、Core Contract 和 AGENTS 来源进入 Instruction Plane。普通 User/Tool 文本即使伪造标签，也只属于 Conversation Plane。Tool Schema 通过 `GenerationRequest.tools` 交给 Provider，不复制成 Prompt 文本。

AGENTS 的有效集合发生变化时会创建新的 instruction epoch。首次激活目录级 AGENTS 或已激活文件内容变化，允许 stable instruction prefix fingerprint 改变；TaskState、PlanState、Projection、Compaction revision 和普通环境增量不会创建 instruction epoch。这样既保持权限正确，也避免高频运行状态无意义地破坏稳定前缀。

## 固定 258K 是 Operating Budget

当前 `ContextCompiler` 按固定 `258_000` token Operating Budget 工作。这个数字是 UthCode 当前阶段的工作档位，不是远端模型物理 Context Window 的声明。

UthCode 目前没有统一 Model Limits、Provider window discovery 或不同窗口 Budget Resolver。因此，当真实模型窗口小于 258K 时，Compiler 可能认为请求仍在预算内，而 Provider 已经拒绝输入。Provider overflow 只是一层最后保护，不能用来推断模型窗口。

## Session 持久化与恢复

每个 Session 只有一个 writer。History 使用 strict sequence 和 durable append；同一个 Session 被另一进程持有时，第二个 resume 会 fail closed，避免两个进程从同一 sequence 同时追加。

terminal Turn 会分别记录 History append、reload、metadata touch 和 Instruction State sync 的结果。已确认落盘的消息只推进一次 durable cursor；无法判断 durability 时 writer 进入 quarantine，后续语义写入停止，必须 close 后由 fresh writer 重新打开和验证。

`/resume` 恢复已提交的 History、Projection、Tool Result ref 和已激活 instruction scopes。AGENTS 内容不作为权威副本写入 Session；恢复时会根据保存的 scopes 重新读取当前文件系统，文件变化会创建新的 instruction epoch。

Session resume 不等于 Runtime checkpoint。它不会恢复退出前仍 active/paused 的 Turn、TaskState、PlanState、Pending Tool、Permission、AskUser waiter、Provider 请求或协程位置，而是根据已提交语义历史开始新的 Run/Turn。

## 大 Tool Result 不直接塞回上下文

大 Tool Result 由 Application 做 materialization：小结果 inline，超过阈值的完整结果写入当前 Session 的受限存储，模型只收到 bounded preview 和 opaque ref。`ToolResultRead` 可以按页重新读取，但 ref 只在当前 Session 有效，不能演化成任意路径读取接口。

Tool 是否已经执行成功与结果是否成功持久化是两个事实。持久化失败不能把已经发生的文件修改或命令执行伪装成“Tool 执行失败”，也不能因此自动重试有副作用的 Tool。

## Compaction 机制已存在，生产 summarizer 尚未接通

`ContextCompactor` 已实现完整 semantic unit 的有界滚动分批、prior summary 合并、输入预算、输出 reserve、summary hard cap、single-flight 和 Projection candidate 校验。失败不会推进 Projection，也不会修改 Canonical History。

但当前生产组合没有向它提供 summarizer：

```text
/compact
  -> UthCodeApplication.compact_session()
  -> ApplicationContextService.compact()
  -> ContextCompactor.compact(summarize=None)
  -> summarizer_unavailable
```

Provider overflow 的自动压缩路径也使用同一个缺失的 summarizer，因此当前不能完成真实压缩或通过压缩重试。`/compact` 已有命令、Session 和安全失败链路，但不是可用的压缩能力。这个缺口与真实模型窗口解析、不同窗口适配和 258K 阈值调优一起由 T09-1 收口；不能把 overflow 当成能力发现，也不能用普通 Agent Tool 流程冒充 tool-free summarizer。

## 当前可依赖的边界

- 可依赖：Canonical History、Projection 数据模型、Context Compiler、固定 258K Working Set、Instruction Epoch、Session single writer、Tool Result 外置、prefix/usage diagnostics。
- 不可依赖：生产 `/compact` 成功、overflow 后自动恢复、小窗口模型安全适配、跨进程 Runtime checkpoint、Memory/retrieval、高级层级压缩。

这一区分很重要：安全失败说明系统没有破坏历史，但不代表用户能力已经完成。
