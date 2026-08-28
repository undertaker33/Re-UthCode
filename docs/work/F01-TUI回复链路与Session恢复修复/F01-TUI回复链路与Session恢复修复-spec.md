# F01：TUI 回复链路与 Session 恢复修复 Spec

## 背景

UthCode 已具备 Provider-independent Agent Loop、Context Compiler、durable Session、公开 AgentEvent 与 prompt_toolkit TUI，但真实多轮会话暴露出跨层语义没有闭合：上下文来源和当前用户输入在 Provider 边界被拼接；reasoning、正式回复和 Tool 活动的事件顺序在 TUI 被重新分组；历史 reasoning 在跨模型映射中可能变成正式正文；`/resume` 只恢复模型上下文而不恢复用户可见聊天；Windows 进程输出和 Session 生命周期还存在乱码、存储放大与空壳积累。

本包修复既有链路，不建立第二套 Prompt、History、Session、事件或 UI 状态体系。

## 目标

- 保持冻结的 Instruction Plane 与 Conversation Plane 权限边界，同时让 Runtime、Environment、历史 assistant 和当前用户输入具有不可混淆的结构来源。
- 保留 reasoning 实时流式体验，按事件语义严格隔离 reasoning 与正式回复，并使用不同竖线颜色。
- 保证 reasoning 永远保持 typed reasoning；不同 Provider/model identity 不得把它降级为正式 assistant 文本。
- 只有非空正式文本才能完成普通 final；reasoning 加 ToolCall 仍可作为合法 progress。
- 让 Transcript 以每个 part 的单一事实保存和重建，不再重复嵌入完整 Message。
- 让 `/resume` 完整、安全、原子地回放用户、reasoning、正式回复和 Tool 终态摘要。
- 延迟创建持久 Session，消除空启动和先 resume 产生的空壳。
- 在 Windows 正确恢复常见 UTF-8 与系统 shell 编码输出。
- 按原设计保留 Tool 摘要秘密与 ambient 环境值脱敏，同时消除名称重复并验证多 Tool FIFO。

## 能力清单

### T01：Prompt、Context 与当前用户消息边界

- 只保留一条正式 Prompt/Context 组合路径。
- Instruction Plane、Conversation Plane、runtime/environment source authority 与稳定前缀语义保持不变。
- Runtime、Environment 和当前用户输入使用明确来源与边界；当前用户正文逐字保持并位于会话尾部。
- Provider mapper 不再无分隔拼接独立语义 part；普通历史不能伪造 system authority。

### T02：Provider reasoning 与正式终态合同

- Reasoning delta、part 和 native carrier 保持 typed，顺序可验证。
- 同 identity 的合法 reasoning continuity 保留；跨 identity reasoning 不得转成普通 assistant content。
- 同一 chunk 或交错 chunk 中的 reasoning/content 都生成可判定的独立事件序列。
- reasoning-only stop 和空文本 stop 不得形成成功 final；reasoning 加 ToolCall 继续合法。

### T03：Transcript 逻辑消息与 reasoning 持久化

- 每个 Transcript entry 只保存自身 part、角色、消息身份和必要 native carrier，不重复完整 Message。
- 按稳定身份和 part 顺序聚合重建唯一逻辑 Message，保留 ToolCall/ToolResult 配对与 FIFO。
- Reasoning 作为独立 typed display/history record 持久化和恢复，不进入正式文本。
- 旧 Session 可读取但不原地改写；跨 identity Provider projection 遵守 T02。

### T04：Session 安全回放与惰性生命周期

- Application 提供 interface-neutral、display-safe、按 durable sequence 排序的回放记录。
- 完整回放 user、steering、reasoning、正式 assistant 和安全 Tool 终态；过滤原始结果、native payload、秘密和未提交状态。
- TUI/CLI 冷启动、帮助、状态和 Picker 不创建 Session；普通输入、`/new`、`/resume` 分别遵守已确认生命周期。
- Session 切换失败保持当前 Session、界面和锁状态不变。

### T05：Windows 进程输出解码

- UTF-8 合法输出保持原样。
- Windows shell 的真实 OEM/ANSI 编码使用当前平台事实做有限 fallback，最后才 replacement。
- stdout、stderr、非零退出和取消语义不改变；不引入编码猜测依赖或第二进程执行器。

### T06：Tool 活动摘要与 FIFO 展示合同

- Tool 名只显示一次，名称与安全参数摘要具有单一展示所有权。
- ToolStarted 继续只用于当前 activity；ToolFinished 每个 call 恰好永久显示一次。
- 多 Tool batch 的完成记录严格按 FIFO，各状态不能只靠颜色区分。
- 原 T05 脱敏边界完整保留，不展示 ToolResult 正文或 unknown/custom 参数正文。

### T07：TUI 时序化流式投影与 reasoning 视觉

- 流式投影使用单一事件时间线，不按消息类型字典分组 flush。
- Reasoning 安全 Markdown 块继续实时进入 scrollback，未完成尾部实时进入带 reasoning 标题和颜色的 preview。
- 正式回复 delta 持续更新独立 preview，权威消息完成后永久提交一次，确保晚到 reasoning 不要求重排 scrollback。
- Reasoning segment、正式回复、Tool 边界和修正消息均有明确块边界；reasoning 与 final 的竖线颜色不同。

### T08：TUI `/resume` hydrate

- TUI 只消费 Application 回放 DTO，不读取 Session 文件或 Core History 类型。
- 回放按原顺序、有界批次写入主缓冲区并让出事件循环，不伪造 AgentEvent、Turn 或 Provider 调用。
- 回放结束后的新 Turn 继续使用已恢复历史，既不重复显示也不重复持久化。

### T09：[接入主流程] 唯一请求、历史、Session 与 TUI 链路

- T01～T08 进入唯一正式 Application Run/Turn、Session command 和 TUI 路径。
- 删除被替代的 Prompt 双轨、reasoning 降级、重复 Message payload、提前 Session 创建和重复 Tool 标题入口。
- CLI、Headless 与 TUI 继续消费同一公共语义，不在 Interface 复制 Provider、History 或 Secret 规则。

### T10：[端到端验证] 四现象、九类问题与真实入口验收

- 从真实 TUI 启动、普通输入、reasoning、工具、final、退出、重启、`/resume` 和继续对话覆盖完整链路。
- 覆盖 OpenAI-compatible 交错 reasoning/content、跨 identity、Windows 中文输出、多个 ToolCall、长 Session 回放和空启动。
- 执行定向、架构、全量、compileall、pip check、diff check 与文档 UTF-8 校验，并记录精确结果。

### T11：[遗留负担清理] 单一路径与历史负担收口

- 删除无生产调用方的 Prompt/renderer helper、旧 reasoning fallback、完整 Message 重复载荷和失效 fixture。
- 不保留旧行为兼容入口、第二 replay store、Session migration framework、UI 历史副本或编码探测框架。
- 核对 F01 能力欠账、当前事实文档、Checklist 与 Feedback 后保持工作包未归档。

## 非功能要求

- 保持 `interfaces -> application -> core`，并由 Application 组合 Integration；Interface 不直接读取 Provider、Core History 或 Session 文件。
- Agent Loop 继续显式、集中、串行；Tool batch 继续 FIFO，RunState 继续是唯一写入者。
- 保持 append-only scrollback；已永久输出的内容不得回写、删除或重排。
- Reasoning 与正式回复均保持生成期间可观察；不得通过等待 Turn terminal 才一次性输出全部内容来伪造正确顺序。
- Session replay 对长历史采用有界批次并让出事件循环，不引入分页、虚拟列表或第二历史状态。
- SecretValue、敏感参数、ambient 环境值和 ToolResult 正文不得进入公开摘要、回放或诊断。
- 中文 Markdown 使用 UTF-8；不修改已冻结 T03、T05、T09 等历史工作包正文。
- 不新增运行时第三方依赖。

## 设计骨架

```text
trusted instruction sources ───────────────> Instruction Plane
durable typed history ─┐
runtime facts ─────────┼─> Conversation Plane ─> current user exact tail
environment facts ─────┘
                                      │
                                      v
                         one GenerationRequest path
```

```text
Provider typed stream
  -> chronological AgentEvent timeline
  -> reasoning stream: live preview + safe incremental scrollback
  -> final stream: live preview + one authoritative permanent commit
  -> ToolFinished FIFO records
```

```text
durable Transcript
  -> Application display-safe replay projection
  -> bounded ordered replay batches
  -> TUI scrollback
  -> fresh Run continues from the same restored history
```

## 能力欠账

无。

F01 不因后置能力尚未实现而停止任何当前修复。跨进程恢复 active/paused Turn、Pending Tool、Permission、AskUser waiter、Provider continuation、Memory/Retrieval 和跨 Session Artifact 生命周期仍是已有独立未来边界，不是本包新增欠账；`docs/OutstandingDebtList.md` 保持不变。

## Out of Scope

- Persistent Runtime checkpoint、active/paused Turn 跨进程恢复。
- Pending Tool、Permission、AskUser、Plan/Task continuation 恢复。
- Memory、Retrieval、Artifact Store/GC、Provider fallback。
- 新 Provider 协议、Provider 专用 Prompt policy、模型名称猜测。
- 通用 Secret/DLP 系统，或放宽 T05 已冻结的环境值脱敏设计。
- alternate screen、应用内滚动条、历史分页、虚拟列表、大型 TUI redesign。
- Session schema migration service、旧 UthCode 兼容层或第二套持久化格式。

## 验收标准

1. 输入 `？` 时，最后一个当前 user 语义正文精确为 `？`，不包含模型、Provider、工作目录或 Runtime 尾巴。
2. Instruction、Runtime、Environment、历史 user/assistant/tool 和当前 user 在三种 Provider mapping 中保持正确来源、角色和顺序。
3. reasoning 实时可见，reasoning 与 final 永不共用标题、缓冲区或竖线颜色；永久 scrollback 始终 reasoning 在前、权威 final 只出现一次。
4. 跨 Provider/model identity 时 reasoning 不成为 assistant content；同 identity 合法 continuity 与 ToolCall 不回归。
5. reasoning-only stop、空文本 stop 被受控拒绝；非空 final 和 reasoning+ToolCall 正常。
6. 新旧 Transcript 均可重建唯一逻辑消息；不再出现 parts 数量乘完整 Message 的存储放大。
7. `/resume` 完整回放 user、reasoning、final 和安全 Tool 终态，不显示原始 ToolResult/native/secret，且不产生新 Turn、Provider call 或 Transcript entry。
8. 启动即退出、只用帮助/状态/Picker、先 `/resume` 均不新增空 Session；首条普通输入与 `/new` 各只创建一个 Session。
9. Windows UTF-8 和真实 shell 编码中文 stdout/stderr 无 replacement mojibake，错误、取消和退出码语义不变。
10. Tool 名不重复，多 Tool FIFO 每个终态恰好显示一次；原 T05 环境值与秘密脱敏测试继续通过。
11. 定向、架构和全量测试通过，真实 Windows Terminal 人工验收有记录，所有治理文档通过 UTF-8 guard。
12. 无 Prompt/History/Session/TUI 双轨、兼容层、第二状态仓库、迁移框架或范围外能力。

## 决策追踪

| 决策 | 覆盖任务 |
| --- | --- |
| D-F01-01 | T02、T03、T07～T10 |
| D-F01-02 | T03、T04、T08～T10 |
| D-F01-03 | T04、T08～T10 |
| D-F01-04 | T06、T09～T11 |
