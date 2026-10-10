# UthCode 可用 Tool

正式 Application 当前共实现 **17 个基础 Tool 名称**：12 个 Integration 执行工具、2 个当前 Session 作用域的证据读取工具和 3 个由 Core 处理的控制工具。用户级搜索配置有效且启用时，再增加可选的 `WebSearch`，总数为 18 个。实际向模型提供哪些 Tool，取决于当前行为模式。

## 默认执行工具

| Tool | 用途 |
| --- | --- |
| `ReadFile` | 读取 UTF-8 文本文件，文件路径仍按权限判断 |
| `WriteFile` | 创建或覆盖文件 |
| `EditFile` | 对已读取文件进行精确替换 |
| `Glob` | 按路径模式查找文件 |
| `Grep` | 搜索文件内容 |
| `Bash` | 以当前操作系统用户权限执行命令 |
| `ReadDocument` | 有界读取 PDF、DOCX、XLSX、PPTX 的结构化内容，可读取当前 Session 附件 |
| `ViewImage` | 读取图片或把 PDF 指定页渲染为模型可见的图片资产，可读取当前 Session 附件 |
| `Process` | 查询或控制当前 Session 所属的 Bash 进程 |
| `ApplyPatch` | 按 Codex patch 方言预检，按文件原子提交增删改和移动 |
| `GitWorkspace` | 以只读、无外部 diff 的方式查询 Git 工作区 |
| `WebFetch` | 对公开 HTTP(S) 地址逐跳授权并有界抓取正文或 PDF |

这 12 个 Tool 进入普通 Tool Registry，执行前会完成参数准备、路径或命令分析以及权限判断。`ReadDocument`、`ViewImage`、`Process`、`GitWorkspace` 和 `WebFetch` 的只读定义在 Plan Mode 可见；`Process` 的 `write`、`resize`、`stop` 操作仍分别进入输入、写入或破坏性权限判断，`ApplyPatch` 在 Plan Mode 隐藏。

`ReadFile` 按路径读取 UTF-8 文本，不接受附件 `asset_ref`，不解析 PDF、Office 文档或图片；文档使用 `ReadDocument`，图片使用 `ViewImage`。路径读取仍经过既有权限判断，外部路径需要相应授权。已经随当前用户消息提交的图片可直接观察，无需把显示文件名猜成路径。

启用可信用户级搜索配置后，`WebSearch` 也进入普通 Tool Registry。它只调用固定 Tavily endpoint，使用 `search_depth=basic` 和 `include_answer=false`；结果中的来源和用量可继续读取，凭据不会出现在 Tool Result、事件或历史中。

注册 `WebSearch` 需要用户级搜索启用且已配置 API key；仅勾选启用而缺少 key 时，模型不会收到此工具。普通设置保存保留未编辑的搜索凭据，显式清空才删除；`WebFetch` 仍独立可用，其抓取网页不消耗 Tavily 搜索额度。

`WebFetch` 对公开正文中的登录链接或登录教程不再按关键词拒绝；HTML 中存在密码表单时，先剔除表单并用既有正文提取器检查剩余可读内容。纯登录表单、明确的登录密码提示以及没有可读正文的动态页仍返回受控错误；逐跳权限、公开地址校验、字节预算和取消边界不变。

### `EditFile`

`EditFile` 要求先读取文件并确认读取后的版本没有变化，`old_string` 必须非空且唯一匹配。匹配沿用文本读取的换行归一化视图；写回只替换命中的原始文本区间，未命中的 LF、CRLF 或 CR 换行保持原样。替换文本的换行采用命中区间的首个换行样式，没有时使用原文件的首个样式。文件没有换行时使用当前平台样式，避免 Windows 局部编辑使整份文件产生行尾差异。

### `ReadDocument`

`ReadDocument` 每次调用必须只提供 `path` 或 `asset_ref` 之一。路径读取仍经过既有权限判断，包含已获准的外部路径；附件读取必须逐字复制当前 Session 提供的完整 `asset_ref`，包括 `attachment:` 前缀及 Session/ref 部分。不要用附件显示文件名替代 `asset_ref`，也不要猜测、补全或修补引用。工具按格式返回带定位的结构化内容：PDF 按页，DOCX 按顺序段落/表格，XLSX 按 sheet/range，PPTX 按 slide/shape/table。结果有页、字符和字节预算；损坏、加密、不支持格式、超限和取消都会返回受控错误。XLSX 的公式文本与已有缓存值分别保留，工具不执行公式重算。该工具只提取文档文字和结构，不返回文档内图片像素。PDFium 的文本解析在短生命周期私有 PDF 宿主内执行；取消会终止该宿主，不依赖等待仍在 native 调用中的线程。开发运行时直接启动 `uthcode.integrations.pdf_worker` 私有模块，frozen 运行时使用打包的 `--uthcode-pdf-worker` 入口。

### `ViewImage`

`ViewImage` 每次调用必须只提供 `path` 或 `asset_ref` 之一。路径读取仍经过既有权限判断，外部路径需要相应授权。附件引用必须逐字复制完整 `asset_ref`，包括 `attachment:` 前缀；不使用显示文件名替代，也不猜测或修补引用。已经随当前用户消息提交的图片可以直接观察，无需再次调用本工具。其他受当前 Session 所有的图片可按路径或附件引用读取；PDF 可按指定页渲染成 PNG 图片资产。PDF 页渲染与文本解析共用短生命周期私有宿主，取消会终止正在执行的宿主。渲染结果通过既有 Session 附件物化路径进入模型，并保留文件/页来源定位；图片尺寸、像素和字节有界。没有视觉能力的模型仍会收到明确的不可用能力结果，不会把文本描述伪装成图像输入。

### `ApplyPatch`

`ApplyPatch` 使用严格的 Codex patch 格式，而不是普通 unified diff。补丁必须以 `*** Begin Patch` 开始、以 `*** End Patch` 结束，中间使用 `*** Add File:`、`*** Update File:` 或 `*** Delete File:` 文件头。例如：

```text
*** Begin Patch
*** Update File: notes.txt
@@
-status=pending
+status=verified
*** End Patch
```

格式错误或上下文不匹配时，按工具返回的原因修正补丁；不要为凑出旧上下文而先覆盖原文件。工具不会猜测修补非法格式。多个文件的实际成功、失败和未应用结果分别报告，重试前先核对已产生的副作用。

### `Bash` 与 `Process`

`Bash` 是唯一的进程启动入口。`yield_time_ms` 只控制本次 ToolCall 等待多久；`timeout_seconds` 是可选的进程总寿命上限，默认没有总寿命。短等待可返回仍在运行的进程。`Bash` 和 `Process read` 的结果正文以有界状态摘要开头，包含真实 `process_id`、`state`、`next_cursor`，退出码已知时附带 `exit_code`；模型按这个句柄继续操作，并把返回的游标用于下一次增量读取，不依赖仅供界面使用的 metadata。之后用 `Process` 的 `list`/`read` 获取有界增量和退出码。pipe 模式继续区分 stdout/stderr，PTY 模式提供单一 terminal 流及原生 stdin、EOF 和 resize。

`Process write` 接受文字输入，在 POSIX PTY 适配边界编码为 UTF-8 字节，Windows PTY 使用原生文本接口；EOF 也按对应平台的底层接口送出。输入只发送本次提供的内容，不自动补回车，也不在等待、续读或恢复时自动重放。Windows CMD 的交互输入需要实际的 CR（U+000D）或 CRLF 才提交一行；只有 LF 或字面量反斜线字符不能替代回车。工具接受了输入，不代表目标程序已经消费，应读取目标程序的输出确认。

停止结果只报告已确认的事实；无法确认树终止或读取收尾时保留 `unknown`，不能把父进程退出或等待超时当成停止成功。pipe 与 Windows PTY 的具体收尾边界见 [Bash 中止收口](core-design/A01-AgentRuntime/06-Bash中止收口.md)。

进程句柄绑定当前 Application/Session 和启动 Turn。成功 Turn 后服务进程继续存活，新的 Turn 可以续读或显式停止；取消、失败和异常只清理本 Turn 新建的进程，Session 关闭才清理全部进程。每个 Session 默认最多保留 32 个正常终态和 128 个过期事实，单进程 UTF-8 输出环默认 2 MiB；淘汰会保留 `expired`、最早游标和原因，避免短命令长期累积。`Process read` 使用单调游标，`wait_ms` 只能在 50—60000 毫秒内取值，默认 1000 毫秒；运行中无新输出时实际等待到新输出、终态或超时，不能用 `0` 绕过有界等待，取消会及时解除等待。输出环超出容量时报告最早游标和过期状态；输出事件仍由 Application 统一做跨 chunk Secret 脱敏后路由到 Desktop，不能把后台日志当作新的 Turn 或 History 内容。stdin 是独立的执行输入授权，不能因启动命令已获批而自动获得后续输入权限。

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
| 默认执行模式 | 12 个 Integration 执行工具、`ToolResultRead`、`HistoryRead`、`AskUserQuestion`、`TodoWrite` | 17 |
| 默认执行模式（搜索已配置） | 上述工具加 `WebSearch` | 18 |
| Plan Mode | 9 个只读 Integration 定义、`ToolResultRead`、`HistoryRead`、`AskUserQuestion`、`ProposePlan` | 13 |
| Plan Mode（搜索已配置） | 上述工具加只读 `WebSearch` | 14 |

Plan Mode 中的 `Bash` 以及 `Process` 的只读查询可以准备；写入、停止、resize 或其他非 `READ` 操作会在 trusted preflight 后、Permission 前由 Agent Loop 的固定检查受控拒绝。`ReadDocument`/`ViewImage` 仅在当前模型声明支持所需输入且 Session 资源可用时形成有效请求。

`HistoryRead` 只接受当前 Session 的精确 opaque Transcript ref 和有界分页参数；它不搜索、不跨 Session，也不把原始历史递归外置。它与 `ToolResultRead` 使用独立的 ref namespace、权限资源和错误边界。

> `Bash` 不是 OS Sandbox。即使工具对模型可见，具体调用仍需经过参数校验、运行模式限制和权限判断。

## 仓库级 Eval 边界

`eval/swebench.py` 是仓库级手动评测适配器，不是 `uthcode` Tool，也不会进入 Tool Registry、模型 Tool 列表或 Desktop 运行链。它要求外部 Git 实例根在运行前 clean，只把外部工作目录、题面和模型引用接到正式 Headless Application，并用真实 Git 生成实际差异预测 JSONL；官方评分器仍属于外部评测环境。
