# UthCode 可用 Tool

正式 Application 当前共实现 **14 个 Tool 名称**：9 个 Integration 执行工具、2 个当前 Session 作用域的证据读取工具和 3 个由 Core 处理的控制工具。实际向模型提供哪些 Tool，取决于当前行为模式。

## 默认执行工具

| Tool | 用途 |
| --- | --- |
| `ReadFile` | 读取工作目录内的文件 |
| `WriteFile` | 创建或覆盖文件 |
| `EditFile` | 对已读取文件进行精确替换 |
| `Glob` | 按路径模式查找文件 |
| `Grep` | 搜索文件内容 |
| `Bash` | 以当前操作系统用户权限执行命令 |
| `ReadDocument` | 有界读取 PDF、DOCX、XLSX、PPTX 的结构化内容 |
| `ViewImage` | 读取图片或把 PDF 指定页渲染为模型可见的图片资产 |
| `Process` | 查询或控制当前 Session 所属的 Bash 进程 |

这 9 个 Tool 进入普通 Tool Registry，执行前会完成参数准备、路径或命令分析以及权限判断。`ReadDocument`、`ViewImage` 和 `Process` 的只读定义在 Plan Mode 可见；`Process` 的 `write`、`resize`、`stop` 操作仍分别进入输入、写入或破坏性权限判断。

### `ReadDocument`

`ReadDocument` 接受工作目录内路径或当前 Session 已拥有的 `asset_ref`，并按格式返回带定位的结构化内容：PDF 按页，DOCX 按顺序段落/表格，XLSX 按 sheet/range，PPTX 按 slide/shape/table。结果有页、字符和字节预算；损坏、加密、不支持格式、超限和取消都会返回受控错误。XLSX 的公式文本与已有缓存值分别保留，工具不执行公式重算。PDFium 的文本解析在短生命周期私有 PDF 宿主内执行；取消会终止该宿主，不依赖等待仍在 native 调用中的线程。开发运行时直接启动 `uthcode.integrations.pdf_worker` 私有模块，frozen 运行时使用打包的 `--uthcode-pdf-worker` 入口。

### `ViewImage`

`ViewImage` 可读取受当前 Session 所有的图片，或把 PDF 指定页渲染成 PNG 图片资产。PDF 页渲染与文本解析共用短生命周期私有宿主，取消会终止正在执行的宿主。渲染结果通过既有 Session 附件物化路径进入模型，并保留文件/页来源定位；图片尺寸、像素和字节有界。没有视觉能力的模型仍会收到明确的不可用能力结果，不会把文本描述伪装成图像输入。

### `Bash` 与 `Process`

`Bash` 是唯一的进程启动入口。`yield_time_ms` 只控制本次 ToolCall 等待多久；`timeout_seconds` 是可选的进程总寿命上限，默认没有总寿命。短等待可返回仍在运行的 `process_id`，之后用 `Process` 的 `list`/`read` 获取有界增量和退出码。pipe 模式继续区分 stdout/stderr，PTY 模式提供单一 terminal 流及原生 stdin、EOF 和 resize。

进程句柄绑定当前 Application/Session 和启动 Turn。成功 Turn 后服务进程继续存活，新的 Turn 可以续读或显式停止；取消、失败和异常只清理本 Turn 新建的进程，Session 关闭才清理全部进程。每个 Session 默认最多保留 32 个正常终态和 128 个过期事实，单进程 UTF-8 输出环默认 2 MiB；淘汰会保留 `expired`、最早游标和原因，避免短命令长期累积。`Process read` 使用单调游标，输出环超出容量时报告最早游标和过期状态；输出事件仍由 Application 统一做跨 chunk Secret 脱敏后路由到 Desktop，不能把后台日志当作新的 Turn 或 History 内容。stdin 是独立的执行输入授权，不能因启动命令已获批而自动获得后续输入权限。

## Session 结果工具

| Tool | 用途 |
| --- | --- |
| `ToolResultRead` | 使用当前 Session 的 opaque ref 读取大 Tool Result 的有界页 |
| `HistoryRead` | 使用当前 Session 的 opaque Transcript ref 读取原始历史的有界页 |

`ToolResultRead` 只接受当前 Session 发出的 ref、offset 和 limit；它不能读取任意文件路径，也不会把上一 Session 的 ref 带入当前 Session。大结果仍保留完整内容，模型先收到 bounded preview，再按需调用该 Tool。

## Core 控制工具

| Tool | 用途 |
| --- | --- |
| `AskUserQuestion` | 暂停当前 Turn 并向用户提出结构化问题 |
| `TodoWrite` | 更新当前 Turn 的任务状态 |
| `ProposePlan` | 在 Plan Mode 中提交计划并进入用户审阅 |

这些 Tool 不走普通 Tool Registry 的执行路径，而是由 Agent Core 识别并更新运行状态。

### `AskUserQuestion` 合同

`AskUserQuestion` 一次请求包含 1—4 个问题。`text` 问题不携带 options；`single-select` 与 `multi-select` 必须各自提供 2—3 个结构化选项。Renderer 对选择题始终提供自由文本输入，非空自由文本可以与选项答案一起按正常 typed response 提交。当前合同不再包含旧的 `allow_other` 字段或 “Other” 选项分支。

### Plan 流式事件

Plan 草稿通过公开的 `PlanContentDelta` 事件增量投影自然语言文本，并在完成后产生 `PlanProposed`，随后进入 typed Plan Review。Renderer 不消费 Provider 原始 JSON 或 `arguments_delta`；事件携带 Run、Turn、iteration 和 tool-call identity，保证同一草稿按调用边界追加。

## 不同模式下的可见数量

| 模式 | 向模型提供的 Tool | 数量 |
| --- | --- | ---: |
| 默认执行模式 | 9 个 Integration 执行工具、`ToolResultRead`、`HistoryRead`、`AskUserQuestion`、`TodoWrite` | 13 |
| Plan Mode | 9 个只读 Integration 定义、`ToolResultRead`、`HistoryRead`、`AskUserQuestion`、`ProposePlan` | 13 |

Plan Mode 中的 `Bash` 以及 `Process` 的只读查询可以准备；写入、停止、resize 或其他非 `READ` 操作会在 trusted preflight 后、Permission 前由 Agent Loop 的固定检查受控拒绝。`ReadDocument`/`ViewImage` 仅在当前模型声明支持所需输入且 Session 资源可用时形成有效请求。

`HistoryRead` 只接受当前 Session 的精确 opaque Transcript ref 和有界分页参数；它不搜索、不跨 Session，也不把原始历史递归外置。它与 `ToolResultRead` 使用独立的 ref namespace、权限资源和错误边界。

> `Bash` 不是 OS Sandbox。即使工具对模型可见，具体调用仍需经过参数校验、运行模式限制和权限判断。
