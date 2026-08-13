# 理解 UthCode Agent Core

一个 Coding Agent 不只是“能调用工具的聊天模型”。在 UthCode 中，可以先用下面这条公式建立整体认识：

```text
Agent Core = Model + Context + Tools + Runtime Control
```

Model 决定下一步做什么，Context 提供判断所需的信息，Tools 让决定作用于真实项目，Runtime Control 则让整个过程可约束、可暂停、可恢复、可验证。

这组文档结合 UthCode 的实际设计，从一次请求如何进入系统讲起，逐步走完 Agent Core 的运行闭环。章节按项目能力形成的阶段划分，但不是任务书摘要；即使不阅读源码，也可以把它当作一份简短的 Agent 工程教程。

| 回答的问题 | 文档 |
| --- | --- |
| 一个 Agent Core 应如何划分边界，模型又应放在哪一层？ | [T01：搭起 Agent Core 的骨架](T01-foundation-and-provider.md) |
| 不同模型 API 差异很大，如何把它们接入同一套运行时？ | [T01-2：把模型协议翻译成统一语言](T01-2-native-sdk-provider.md) |
| 用户输入如何穿过配置、CLI 和 TUI，到达同一个 Core？ | [T02：从入口走向核心](T02-configuration-and-interfaces.md) |
| 模型每次决策前究竟看到了什么？ | [T03：构造 Agent 的工作上下文](T03-system-prompt.md) |
| 模型如何安全地读取代码、修改文件和执行命令？ | [T04：工具是 Agent 的行动接口](T04-tool-system.md) |
| Agent 为什么能够观察结果并连续采取下一步行动？ | [T05：用 ReAct Loop 闭合感知与行动](T05-react-agent-loop.md) |
| 长任务如何暂停、询问用户、恢复和取消？ | [T06：让运行过程可以被控制](T06-interaction-control.md) |
| 如何限制 Agent 的行动，而不把权限误认为沙箱？ | [T07：把权限判断放进执行链](T07-permission-system.md) |
| 计划、Todo 和运行中补充指令如何进入同一个循环？ | [T08：在同一运行时中加入规划](T08-planning-and-task-control.md) |

建议按顺序阅读。前四章介绍 Agent 的组成，T05 将它们闭合成循环，后三章解释一个工程化 Agent 如何接受用户控制。
