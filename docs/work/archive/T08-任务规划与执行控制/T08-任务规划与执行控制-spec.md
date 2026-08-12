# T08 任务规划与执行控制 Spec

## 1. 背景

T05 已建立单一、显式、顺序执行的 Agent Loop，T06 已建立同一 Turn 内的暂停、恢复、询问用户与取消链路，T07 已把普通工具收口到可信预检、权限决策和实际执行的唯一生产路径。当前系统仍无法表达规划模式、自然语言 Plan 审阅、结构化执行任务、执行中用户追加要求，以及“已知工作未完成时禁止提前结束”等产品语义。

T08 在既有单 Agent Loop 上增加任务规划与执行控制。它不是新的工作流引擎、调度器或第二 Runtime；所有状态变更、工具调用、暂停恢复和完成判定继续由当前权威执行链闭合。

## 2. 目标

- 建立默认与规划两种一等行为模式，并与权限模式保持正交。
- 在规划模式中提供只读探索、完整 Plan 提案、用户修订与批准后同 Turn 自动实施的闭环。
- 在执行模式中提供结构化 Todo、持续执行规划、自主重规划和完成拦截。
- 允许用户在 active Turn 中追加、修改或收缩目标，并在 Provider 或工具安全边界继续原 Turn。
- 建立仅包含真实生产调用点的工具执行前与完成前 Hook。
- 通过正式 Application、Slash Command、Headless 与 TUI 路径交付统一行为。
- 保持单 Agent Loop、单 RunState authority、ToolCall ID 闭合、取消优先和 Interface 只投影等既有不变量。

## 3. 能力清单

### Task 1 — Planning Domain、Tool 可见性与控制协议

建立行为模式、结构化任务、Plan、一次性运行反馈、Plan Review、Steering 请求及工具规划可见性的不可变 Core 合同，并提供严格校验、序列化和安全默认边界。

### Task 2 — Runtime Hook 与 Runtime Prompt Facts

建立同步、不可变、按固定顺序组合的两类 Runtime Hook 合同，以及默认模式、规划模式、任务状态、已批准 Plan 和一次性反馈所需的最小 Prompt facts。

### Task 3 — Behavior Mode 与 Dynamic Tool View

让行为模式进入当前 Turn 的权威执行状态；保持 Provider、模型和工具全集稳定，同时按当前模式为每次请求生成动态可见工具集合，并在运行时对规划模式的非只读动作 fail-closed。

### Task 4 — Plan Proposal / Review / Approve

把规划模式的候选 final 转换为可审阅 Plan，支持同一 Turn 内多轮完整替换修订，并在批准后自动切换到默认模式继续实施。

### Task 5 — Todo / Execution Planning / Completion Control

提供 replace-all 的结构化 Todo 控制路径，使任务状态反映真实执行计划；在默认模式中允许模型持续推进和重规划，并阻止仍有未完成任务时提交普通完成结果。

### Task 6 — User Steering

允许 active Turn 中的用户文本成为真实用户事实；Provider attempt 可合作式中断，正在执行的工具到安全边界结束，当前批次未启动的 stale ToolCall 得到受控闭合后再继续同一 Turn。

### Task 7 — Application Run Mode 与 Steering Control

让每个 Run 持有下一 Turn 的行为模式，限制 idle 状态下的外部模式切换，并由 Application 独占 Steering 信号、typed pause 互斥、异步 waiter 与 active Turn 生命周期协调。

### Task 8 — Slash Command 产品入口

提供无参数的规划与执行模式命令，并将构建命令作为执行命令别名；命令只产生界面无关的模式选择意图，不增加第三种行为模式或第二套命令状态。

### Task 9 — TUI Plan / Todo / Steering 产品闭环

投影行为模式、Plan revision、Plan Review、Todo、Steering 和完成拦截；规划视觉与默认视觉可区分，typed interaction 优先于普通 Steering，界面不保存第二份业务状态。

### Task 10 [接入主流程] — 正式 Composition 与分支整合

把各 Worker 交付合并到唯一保留分支，统一共享合同和冲突热点，并证明所有新增能力只通过正式 Application、AgentRun 与单 Agent Loop 主链生效。

### Task 11 [端到端验证] — Plan + Execution Planning + Steering

从正式入口以离线 Provider、真实内置工具和临时工作区验证规划、修订、批准、实施、Todo、Steering、完成拦截、取消竞态和下一 Turn 重置的完整闭环。

### Task 12 [遗留负担清理] — 单 Runtime 收口与 Worktree 回收

删除被替代的旧命令语义、重复状态、旁路和不可达代码，完成全量回归；确认短期分支已合入后回收物理 worktree 与短期本地分支，只保留最终 T08 分支。

## 4. 非功能要求

- 依赖方向保持 `interfaces → application → core`，Application 可组合 Integrations；Core 不依赖 UI、第三方 SDK、文件存储或进程实现。
- 继续只有一个 Agent Loop 和一个 RunState authority；不得增加 Scheduler、DAG、通用工作流或第二条 planning loop。
- Tool Batch 严格 FIFO，每个原始 ToolCall 都恰好得到一个 ToolResult；Steering 不强杀已经开始的普通工具。
- 规划模式的静态工具缩减与运行时动作效果检查同时存在；完全访问权限不能绕过规划模式只读边界。
- Hook 只读取不可变上下文并返回结构化控制结果，不调 Provider、不执行 Tool、不直接写状态、不动态注册。
- 被 Plan Review 或未完成任务拦截的候选文本不得进入权威消息、普通 assistant 完成事件或不可回写的终端 scrollback；用量仍按真实调用计入。
- Plan、TaskState、一次性反馈和 Steering 不通过伪造 system、user 或 tool 消息表达；只有真实用户修订与 Steering 写入用户消息历史。
- 公开事件和界面投影保持 display-safe，不携带秘密工具参数、原始结果或未脱敏命令。
- 原则上不新增运行时依赖；测试使用现有离线 Fake Provider 和临时目录。
- 不兼容旧类、旧 API、旧命令行为或 Re:UthCode 早期实现；被新语义替代的入口直接删除。

## 5. 设计骨架

```text
idle Run behavior mode
        ↓ start Turn
authoritative Turn behavior mode
        ↓
request composition
  ├─ runtime prompt facts
  └─ mode-specific Tool View
        ↓
single Agent Loop
  ├─ ToolCall
  │    → schema + trusted preflight
  │    → before-tool Hook
  │    → permission
  │    → execute / controlled result
  └─ candidate final
       → usage accounting
       → before-completion Hooks
       ├─ PLAN: Plan proposal + review pause
       ├─ DEFAULT + unfinished task: block + next iteration
       └─ accept: authoritative assistant commit + Turn completion
```

```text
active Turn user update
  → dedicated Steering request
  → interrupt Provider attempt OR wait for current Tool safe boundary
  → close stale remaining ToolCall IDs
  → append real user message
  → one-shot steering feedback
  → same Turn next iteration
```

Plan 是用户批准的自然语言实施依据，TaskState 是当前执行中的结构化工作事实；二者不自动编译或互相替代。工具规划可见性属于 Core Tool contract，不进入 Provider wire schema；未显式声明可用于规划的普通工具不进入规划视图，实际调用仍由可信预检得到的只读效果二次确认。

## 6. Out of Scope

- LangGraph、LangChain Agent、通用 Workflow Engine、DAG、任务 Scheduler 或第二 Agent Loop。
- 自动复杂度检测、基于工具数/文件数/token 数的任务分级，以及 Plan 到 Todo 的自动编译器。
- 动态 Hook 注册、Hook 插件系统、全局 Hook registry、配置化 Hook、未有生产调用方的 Hook point。
- Context Compiler、Context Budget、压缩、Memory、Dream、持久 Session、Journal 或跨进程恢复。
- Subagent、Multi-Agent、应用内 Worktree 产品能力；本工作包使用 Git worktree 仅作为开发隔离手段。
- OS Sandbox、权限提升或替代现有 Permission 体系。
- Web、Desktop、IDE、Diff Viewer、完整会话浏览或正式全屏 TUI。
- 兼容旧 `/plan`、旧 `/do` 查询语义、旧 `/p` 别名、第三种 Build mode 或任何旧规划状态模型。

## 7. 验收标准

1. 默认与规划模式是同一 Run/Turn Runtime 中的权威状态，且与权限模式组合无歧义。
2. 规划请求只暴露允许的探索工具；异常构造的非只读动作在权限前被拒绝，完全访问模式不能绕过。
3. Plan v1、修订后的完整 Plan v2 与批准全部保持同一 run、turn 和 handle；批准后无需额外执行命令即可进入实施。
4. Todo 使用严格三态和 replace-all 语义，至多一个进行中项；清空、重写、暂停恢复和新 Turn 重置均有自动测试。
5. 未完成任务存在时，候选 final 不进入消息或普通完成事件；任务全部完成或显式清空后只产生一次 Turn completion。
6. Steering 文本成为当前 Turn 的真实用户消息；Provider 中断、工具安全边界、stale ToolCall 闭合和取消优先均有竞态测试。
7. Hook 只有工具执行前与完成前两个生命周期点，顺序固定、异常 fail-closed，且不存在动态注册或第二执行器。
8. 规划与默认 Prompt facts、Tool View 和完成语义均不同；一次性反馈只影响下一次成功请求。
9. 规划、执行和构建 Slash Command 的参数、别名、帮助与补全符合最终定义；旧 `/p` 与旧 Prompt `/do` 不再存在。
10. TUI 能区分 mode 与 permission，追加显示 Plan revision 和 Todo，并在 typed interaction、Steering、批准自动切模之间保持正确优先级。
11. Headless 入口不依赖 TUI，也能完成 Plan Review、Steering 与 Completion Control；正式端到端场景使用真实 Application 组合链。
12. 定向测试、全量测试、编译、依赖、差异、架构、UTF-8 与 Markdown 围栏检查全部通过，且无兼容层、重复职责、不可达分支或未合并短期 worktree。
