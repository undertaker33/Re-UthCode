# T03：构造 Agent 的工作上下文

模型不会自动知道自己正在一个 Coding Agent 中运行。每次决策前，Harness 必须告诉它“你是谁、环境是什么、能够做什么”，再附上当前对话轨迹。

可以把 UthCode 当前生成请求的上下文理解为：

```text
Context Snapshot
├─ Instruction Plane
│  ├─ Public Prompt
│  ├─ Core Runtime Contract
│  └─ effective AGENTS / instruction epoch
├─ Conversation Plane
│  ├─ Projection
│  ├─ retained Canonical History
│  ├─ current process/runtime delta
│  └─ current user turn
└─ Tool Definitions
   └─ GenerationRequest.tools
```

Application Context Compiler 以固定的 `258K Operating Budget` 编排这个 Snapshot。258K 是当前 UthCode 的运行预算，不是对远端模型物理输入窗口的声明；真实 Provider 的协议映射不会改变这条 Application/Core 边界。

## Instruction Plane 是运行说明书

UthCode 根据当前运行上下文构造 Instruction Plane，其中包括 Public Prompt、Core Runtime Contract、Agent 身份、工作目录、操作系统、行为要求和当前 effective AGENTS。Instruction epoch 用于标识当前指令事实及其稳定前缀；Projection 的变化不会提升 Instruction authority，也不会改变 instruction epoch。

Tool Definitions 定义模型可以选择的行动空间：工具叫什么、接收哪些参数、能完成什么。Tool Schema 的唯一来源是 Tool System，最终进入 `GenerationRequest.tools`；它不会复制进 Public Prompt、Core Runtime Contract 或 AGENTS。Provider Integration 只负责把这个结构化请求映射成原生 wire format，不重新拥有 Context policy。

## Conversation Plane 让 Agent 看到行动后果

Canonical History 是 append-only 的语义事实；Projection 是从已提交 History 派生的历史视图，不升级 authority。每次生成还会组合当前进程中尚未提交的 runtime delta 和 current user turn，因此模型下一次被调用时，不只看到最初目标，也看到自己之前选择了什么工具，以及环境返回了什么结果。

例如：

```text
用户：找出失败测试
Assistant：调用 Grep
Tool：找到 3 处相关断言
Assistant：调用 ReadFile
Tool：返回目标文件内容
```

这条不断增长的轨迹，是 ReAct 能连续工作的基础。

terminal Turn 在 Application 边界把新增 Message 通过 active Session 的 single writer 提交到 History，并分别记录 JSONL append+fsync、reload、last-used/metadata touch 与 Instruction State metadata sync 的 outcome。只有可判定 `durability=durable` 的 History append 才推进 process cursor；append 后的 metadata/reload 半失败保留 durable 事实并进入 partial diagnostics，不会把同一批消息再次作为 delta。无法通过结构化 History identity reconciliation 判定时 active Session writer 进入 quarantine，新的 Run 与 History/Projection 等语义写入 fail closed；必须显式 close 后由 fresh writer 重新打开并验证/恢复，才可继续。真正 History append 失败则不推进 cursor，未提交批次在进程内保留原始 Session/Turn identity 并按 FIFO 重试，也不伪造已提交。

`/resume` 恢复已提交的 History、Projection、Tool Result ref 和 Instruction State，并从新的 Run/Turn 开始。它不跨进程恢复 `TaskState`、`PlanState`、Pending Tool、Permission、AskUser waiter 或 Provider 协程位置。

长期 Session 的 Working Set、持久化、Tool Result 外置和 Compaction 边界见 [T09：让长期会话拥有可治理的上下文](T09-context-engineering.md)。

## Prompt 不是安全边界

System Prompt 可以要求模型遵守规则，但模型输出仍是不可信输入。路径限制、参数校验和权限判断必须由 Runtime 与工具执行。工程上应把 Prompt 视为行为引导，把代码检查视为真正约束。

上下文解决了“模型知道什么”，下一章解决“模型能够做什么”。
