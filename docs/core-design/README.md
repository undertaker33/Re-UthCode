# UthCode Core Design

如果你让 UthCode 修改一个项目，它表面上做的事情并不复杂：理解需求，读取代码，调用模型，执行工具，最后给出结果。

但只要任务稍微长一点，问题就会接连出现：模型准备执行一个危险命令时，谁来拦住它？工具执行到一半需要询问用户时，当前任务怎么暂停？用户回答之后，系统又凭什么知道应该从哪里继续？当对话越来越长，哪些历史应该继续交给模型，哪些内容可以压缩？Plan、Todo、Session 又分别属于哪里？

这些问题很难只靠一个 Agent Loop 解决。一个真正能够长期运行的 Coding Agent，除了“让模型调用工具”，还需要同时处理执行、控制、状态和编排。

UthCode 用四层来理解这些问题：

```text
A01 Agent Runtime
执行：Agent 如何完成一次推理与行动

A02 Control
控制：哪些行动可以继续，什么时候需要停下来

A03 State
状态：Agent 当前知道什么、做到哪里、留下了什么

A04 Orchestration
编排：如何把前三层组合成完整的用户任务
```

这四层构成了 `core-design/` 的主线。

> **阅读提示**：这里不是源码索引，也不是任务包归档。`core-design/` 更像 UthCode 的设计教材：每篇文档选择一个值得长期解释的机制，从它解决的问题出发，再进入实际运行流程和设计边界。如果第一次阅读，建议先建立四层的整体印象，不必一开始记住所有类型和调用链。

---

## 为什么是四层

先看一次最普通的 Coding Agent 任务。

用户提出：

```text
帮我修改权限系统，并运行测试确认没有回归。
```

UthCode 首先要把这句话变成一次真正的 Agent 运行。模型读取上下文，决定搜索哪些文件、调用哪些工具，并根据工具结果继续推理。这是 **Agent Runtime** 要解决的问题。

但模型并不能想做什么就做什么。假如它准备执行一个需要用户确认的操作，系统必须在真正执行之前做权限判断；如果信息不足，还可能暂停当前 Turn，向用户提问。这些属于 **Control**。

与此同时，系统还要知道当前处在哪个 Run、哪个 Turn，模型已经看到过什么，Todo 做到了哪一步，哪些历史已经持久化，下一次模型调用应该重新装配哪些上下文。这些属于 **State**。

最后，CLI、TUI、Session、Slash Command、Plan Mode 等能力还要把这些底层机制组合起来，让用户看到的是一次完整任务，而不是一堆彼此独立的组件。这是 **Orchestration**。

于是一次任务可以粗略地画成：

```text
用户
 │
 ▼
A04 Orchestration
创建并组织一次任务
 │
 ▼
A03 State
建立 Run / Turn / Context
 │
 ▼
A01 Agent Runtime
模型推理并选择行动
 │
 ├───────────────┐
 ▼               │
A02 Control       │
检查 / 暂停 / 审批 │
 │               │
 └───────┬───────┘
         ▼
A01 Agent Runtime
执行工具并观察结果
         │
         ▼
A03 State
记录新的事实与进度
         │
         ▼
       ……循环……
         │
         ▼
A04 Orchestration
向用户交付结果
```

四层不是四条互不相干的流水线。一次真实运行会不断在它们之间往返。

---

## A01 Agent Runtime：让 Agent 真正运行起来

如果把 Coding Agent 想成一台机器，Agent Runtime 是最接近发动机的部分。

模型本身只能根据输入生成输出。要让它成为 Agent，还需要有人不断做这样一件事：

```text
准备上下文
   ↓
调用模型
   ↓
模型决定调用工具
   ↓
执行工具
   ↓
把结果交还模型
   ↓
再次决策
```

这个循环让一次模型调用变成了持续运行的 Agent。

因此，执行层关注的不是某一个具体 Provider 或某一个具体 Tool，而是它们进入 Agent Loop 后共同遵守的运行协议：模型请求如何构造，Tool Call 如何闭合，工具结果如何回填，什么时候进入下一轮推理，什么时候才算一次 Turn 真正完成。

在这一层，你会逐步看到 Provider、System Prompt、Tool、ReAct Agent Loop、Runtime Hook 等机制如何组合起来。

可以把它记成一句话：

> **Agent Runtime 决定“下一步怎么执行”。**

目录：

```text
A01-AgentRuntime/
```

如果需要核对当前代码事实，可查看：

[`../context/A01-AgentRuntime/AgentRuntime-Context.md`](../context/A01-AgentRuntime/AgentRuntime-Context.md)

---

## A02 Control：让能力处在可控边界内

Agent 一旦能够调用文件、Shell、外部服务，它就不再只是一个聊天程序。

比如模型生成：

```text
Bash("rm ...")
```

真正重要的问题并不是“模型会不会调用 Bash”，而是：

```text
这个操作允许执行吗？
需要用户确认吗？
如果用户还没有回答，当前 Turn 怎么办？
用户拒绝以后，Agent 是失败还是继续寻找别的办法？
```

这些问题不能交给 Provider 决定，也不能散落在每个 Tool 里各写一套逻辑。它们需要一层独立的运行控制语义。

UthCode 的 Control 层负责的正是这件事。Permission、Ask User、Pause / Resume、Cancellation、Approval 以及固定 Runtime Hook 都属于这一类能力。

它们有一个共同特征：**不负责替 Agent 做任务，而是决定当前执行能不能继续、应该以什么方式继续。**

因此可以把这一层记成：

> **Control 决定“现在能不能继续”。**

目录：

```text
A02-Control/
```

当前代码事实：

[`../context/A02-Control/Control-Context.md`](../context/A02-Control/Control-Context.md)

---

## A03 State：让 Agent 拥有连续的任务世界

模型没有天然的“刚才”。

每一次请求到来时，它真正能使用的，只是这次请求里重新提供给它的信息。如果系统没有保存状态，那么上一轮读过哪些文件、工具返回过什么、任务做到哪一步，对下一次模型调用来说都可能不存在。

因此 Coding Agent 必须自己维护一个任务世界。

最短的一次运行里，可能只有：

```text
User Message
Assistant Message
Tool Call
Tool Result
```

但任务一旦变长，很快就会出现更多状态：

```text
Run
Turn
Event
Session History
Context
Todo
Plan
Projection
Compact
```

这些东西看起来差别很大，实际都在回答同一个问题：

> **下一步决策之前，系统需要保留哪些事实？**

例如 Todo 记录当前任务进度，History 保存已经发生的语义事实，Context 决定其中哪些内容真正进入下一次模型请求，Compact 则在历史不断增长后重新组织有效工作集。

以后 Memory 出现时，它也不会取代这些运行状态，而是继续扩展 Agent 能够跨更长时间保留和重新获取的信息。

所以这一层可以记成：

> **State 决定“Agent 现在处于什么状态、还能看到什么”。**

目录：

```text
A03-State/
```

当前代码事实：

[`../context/A03-State/State-Context.md`](../context/A03-State/State-Context.md)

---

## A04 Orchestration：把机制组合成一次完整任务

执行层能跑模型，控制层能拦住危险动作，状态层能保存任务事实，但用户并不会直接面对这些模块。

用户看到的是：

```text
uthcode
```

然后输入一个需求，进入 Plan Mode，切换模型，回答 Ask User，暂停或恢复任务，最后得到结果。

这中间还有一层负责把底层能力组织成真正的用例。

例如 `/resume` 并不是“读取一个文件”这么简单。它需要找到 Session，恢复允许恢复的历史和状态，创建新的 Run / Turn，再重新进入 Agent Runtime。TUI 也不应该自己实现一套 Agent Loop，而只是把用户操作投影到 Application 已经提供的能力上。

这些“谁先调用谁、一次用户动作应该组合哪些能力”的问题，就是 Orchestration 的职责。

今天它主要连接 Application、CLI、TUI、Session 和各种命令；未来如果出现 Subagent、任务拆分和 Multi-Agent，更复杂的任务组织也会自然落到这一层。

可以把它记成：

> **Orchestration 决定“这些能力怎样组成一个完整任务”。**

目录：

```text
A04-Orchestration/
```

当前代码事实：

[`../context/A04-Orchestration/Orchestration-Context.md`](../context/A04-Orchestration/Orchestration-Context.md)

---

## 四层之间真正的关系

把四层放在一起，可以得到一个更完整的理解：

| 层 | 核心问题 | 典型机制 |
| --- | --- | --- |
| **A01 Agent Runtime** | 下一步怎么执行？ | Provider、Prompt、Tool、ReAct、Agent Loop |
| **A02 Control** | 现在能不能继续？ | Permission、Ask User、Pause / Resume、Cancellation、Hook |
| **A03 State** | Agent 现在知道什么、做到哪里？ | Run、Turn、Event、History、Context、Todo、Plan、Compact |
| **A04 Orchestration** | 怎样组成一次完整用户任务？ | Application、Session、CLI/TUI、Slash Command、任务编排 |

这里最容易产生的误解，是把四层理解成一次单向调用：

```text
A04 → A03 → A02 → A01
```

实际并不是这样。四层定义的是**职责边界**，而不是一条固定调用顺序。

Agent Runtime 在一次 Turn 中可能多次读取 State；每次工具执行之前可能进入 Control；Ask User 暂停后又需要由 Orchestration 接收用户输入，并重新驱动当前任务。真正的运行过程更像几个职责明确的系统共同维持一个循环。

这也是后续阅读各个机制时最重要的参照系。

---

## 从哪里开始读

如果你第一次接触 UthCode，可以从 A01 开始。先理解模型、上下文和工具怎样形成 Agent Loop，再去看权限和暂停如何控制这个循环，随后理解长任务为什么需要独立的状态系统，最后再看 CLI、TUI 和 Session 如何把它们组合起来。

```text
A01 Agent Runtime
执行循环
    ↓
A02 Control
控制循环
    ↓
A03 State
维持连续性
    ↓
A04 Orchestration
组成完整应用
```

也可以直接从自己关心的问题进入：

| 如果你想知道…… | 建议阅读 |
| --- | --- |
| 为什么模型可以连续搜索、修改、测试，而不是调用一次就结束？ | A01 Agent Runtime |
| 为什么 Permission 不是 Sandbox？Agent 怎么停下来等用户？ | A02 Control |
| 长对话为什么需要 Context Compiler 和 Compact？Todo、Plan 放在哪里？ | A03 State |
| `/resume`、Plan Mode、CLI/TUI 怎么复用同一套底层能力？ | A04 Orchestration |

`core-design/` 后续不会机械地收录每一个任务包。只有那些真正形成了长期 Agent 机制、值得单独讲清楚的设计，才会成为这里的一篇文章。

任务包更像 UthCode 的开发记录，`docs/context/` 更像当前代码的事实地图，而 `core-design/` 希望回答另一个问题：

> **一个工程化 Coding Agent，为什么需要这些机制，它们又是怎样协同工作的？**
