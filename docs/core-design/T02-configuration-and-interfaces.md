# T02：从入口走向核心

同一个 Agent Core 可以服务于不同交互方式。UthCode 提供 TUI、一次性 `exec` 和可嵌入的 Application，它们的差异只在系统边缘：如何收集输入、如何展示事件、如何返回最终结果。

## 启动时先确定运行环境

用户执行 `uthcode` 后，Application 会完成三件事：确定工作目录、加载有效配置、构造所选 Provider。随后它才创建 Agent Run。

```text
CLI 参数 + 用户配置 + 项目配置
  → EffectiveConfig
  → Provider + Tools + Permission Rules
  → UthCodeApplication
  → AgentRun
```

用户配置是可信 Provider 的来源。项目配置可以选择其中已有的 Provider 和模型，却不能重新指定端点或密钥来源。这个边界防止仅仅进入某个项目目录，就把请求悄悄转发到另一个服务。

## Interface 观察事件，不接管执行

用户输入最终都会变成 `AgentRun.start_turn(...)`。从这里开始，Interface 不再驱动内部步骤，而是消费 Agent 事件：模型增量、工具开始与结束、暂停请求以及最终结果。

TUI 将事件渲染为连续会话，并能回应选择器和审批；`exec` 把最终回答写入 stdout，把进度和错误写入 stderr。两者没有各自实现一套 Agent Loop。

## Slash Command 是控制面

普通文本进入模型，Slash Command 则由 Application 的统一 Registry 解析。例如 `/model` 改变后续请求使用的模型，`/plan` 改变行为模式，`/status` 读取安全状态投影。

把命令放在控制面，而不是伪装成 Prompt，可以让这些行为具有明确参数、可测试结果和一致补全。下一章将进入一次模型请求内部，看看 Application 为模型准备了哪些信息。
