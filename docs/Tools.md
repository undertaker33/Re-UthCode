# UthCode 可用 Tool

UthCode 当前共实现 **10 个 Tool 名称**：6 个默认执行工具、1 个当前 Session 作用域的结果读取工具和 3 个由 Core 处理的控制工具。实际向模型提供哪些 Tool，取决于当前行为模式。

## 默认执行工具

| Tool | 用途 |
| --- | --- |
| `ReadFile` | 读取工作目录内的文件 |
| `WriteFile` | 创建或覆盖文件 |
| `EditFile` | 对已读取文件进行精确替换 |
| `Glob` | 按路径模式查找文件 |
| `Grep` | 搜索文件内容 |
| `Bash` | 以当前操作系统用户权限执行命令 |

这 6 个 Tool 进入普通 Tool Registry，执行前会完成参数准备、路径或命令分析以及权限判断。

## Session 结果工具

| Tool | 用途 |
| --- | --- |
| `ToolResultRead` | 使用当前 Session 的 opaque ref 读取大 Tool Result 的有界页 |

`ToolResultRead` 只接受当前 Session 发出的 ref、offset 和 limit；它不能读取任意文件路径，也不会把上一 Session 的 ref 带入当前 Session。大结果仍保留完整内容，模型先收到 bounded preview，再按需调用该 Tool。

## Core 控制工具

| Tool | 用途 |
| --- | --- |
| `AskUserQuestion` | 暂停当前 Turn 并向用户提出结构化问题 |
| `TodoWrite` | 更新当前 Turn 的任务状态 |
| `ProposePlan` | 在 Plan Mode 中提交计划并进入用户审阅 |

这些 Tool 不走普通 Tool Registry 的执行路径，而是由 Agent Core 识别并更新运行状态。

## 不同模式下的可见数量

| 模式 | 向模型提供的 Tool | 数量 |
| --- | --- | ---: |
| 默认执行模式 | 6 个默认执行工具、`ToolResultRead`、`AskUserQuestion`、`TodoWrite` | 9 |
| Plan Mode | `ReadFile`、`Glob`、`Grep`、`Bash`、`ToolResultRead`、`AskUserQuestion`、`ProposePlan` | 7 |

Plan Mode 中的 `Bash` 仅允许通过只读检查的命令；写入类操作会在执行前被 Runtime Hook 阻止。

> `Bash` 不是 OS Sandbox。即使工具对模型可见，具体调用仍需经过参数校验、运行模式限制和权限判断。
