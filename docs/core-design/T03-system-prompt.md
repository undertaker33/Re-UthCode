# T03：构造 Agent 的工作上下文

模型不会自动知道自己正在一个 Coding Agent 中运行。每次决策前，Harness 必须告诉它“你是谁、环境是什么、能够做什么”，再附上当前对话轨迹。

可以把 UthCode 的模型上下文理解为：

```text
Context = System Prompt + Tool Definitions + Conversation Trajectory
```

## System Prompt 是运行说明书

UthCode 根据当前运行上下文构造 System Prompt，其中包括 Agent 身份、工作目录、操作系统、行为要求和可用能力。它描述的是当前真实环境，而不是一份与运行脱节的通用模板。

Tool Definitions 则定义模型可以选择的行动空间：工具叫什么、接收哪些参数、能完成什么。如果某项能力没有进入工具定义，模型即使知道如何做，也只能在文本中提出建议。

## 轨迹让 Agent 看到行动后果

用户消息、Assistant Message 和 Tool Result 会依次进入对话轨迹。模型下一次被调用时，不只看到最初目标，也看到自己之前选择了什么工具，以及环境返回了什么结果。

例如：

```text
用户：找出失败测试
Assistant：调用 Grep
Tool：找到 3 处相关断言
Assistant：调用 ReadFile
Tool：返回目标文件内容
```

这条不断增长的轨迹，是 ReAct 能连续工作的基础。

## Prompt 不是安全边界

System Prompt 可以要求模型遵守规则，但模型输出仍是不可信输入。路径限制、参数校验和权限判断必须由 Runtime 与工具执行。工程上应把 Prompt 视为行为引导，把代码检查视为真正约束。

上下文解决了“模型知道什么”，下一章解决“模型能够做什么”。
