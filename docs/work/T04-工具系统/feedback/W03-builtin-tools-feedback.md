# W03 builtin-tools Feedback

## 1. 完成结论

已按 Task 3 → Task 4 → Task 5 完成内置工具实现，未开始 Task 6–Task 9，未执行任何 Git 写操作。

W01、W02 前置已核对并回归通过；本次只在 T04 W03 的 Integration Tool、测试、架构测试和 Checklist 范围内工作。Task 3–Task 5 的实现没有依赖 Application、Interface、Provider SDK、MewCode 或 Pydantic 运行时。

## 2. Task 3：工作区、文件状态与文件工具

### 实际机制

- `WorkspacePathResolver` 保存 Application workdir 的规范化物理根目录；既有路径严格解析，新路径只解析最近存在的父目录。
- 路径先做词法边界检查，再做物理路径检查；空字节、`..` 逃逸、工作区外绝对路径以及指向工作区外的文件/目录符号链接都会被拒绝。
- `FileReadTracker` 按物理路径保存 UTF-8 内容摘要、原始字节摘要、文件大小、mtime_ns 和可用的 stat 身份。检查时重新读取并联合比较这些证据，因此恢复 mtime 仍不能隐藏内容变化；删除、替换和不可读状态不会放行写入。
- `ReadFileTool` 使用 1-based `offset`/`limit` 分页并记录完整文件状态；`WriteFileTool` 只允许新文件直接创建，已有或曾被读取的文件必须通过 tracker 检查；`EditFileTool` 要求非空且唯一的 `old_string`，成功后刷新同一 tracker。
- 文件工具在实际写入前再次检查取消；文件输出不自行截断，统一交由 Core Executor 处理。

### 文件与测试

- 新增 `src/uthcode/integrations/tools/__init__.py`、`workspace.py`、`file_tools.py`。
- 新增 `tests/test_builtin_file_tools.py`，覆盖读取分页/空文件/目录/不存在/编码错误、新建与覆盖、未读/外改/替换/删除/mtime 恢复、编辑唯一性、路径和符号链接边界、取消及 Core 截断。
- 修改 `tests/test_architecture_boundaries.py`，固化 concrete Integration Tool 只能位于 Integration 边界下，且不能导入 Application、Interface 或 Provider SDK。

## 3. Task 4：安全 Glob 与 Grep

### 实际机制

- `GlobTool` 与 `GrepTool` 使用 Python `os.scandir`、glob 分段匹配和 `re`，没有调用系统搜索命令，也没有索引或监听状态。
- walker 不跟随目录符号链接；`.git`、`.venv`、`node_modules`、`__pycache__`、`.tox`、`.mypy_cache`、`.pytest_cache` 固定跳过。
- 每个候选文件同时通过词法和物理路径检查；工作区外文件符号链接被跳过，结果使用稳定的工作区相对 POSIX 路径排序。
- `GrepTool` 的 `include` 是相对文件模式，regex 使用 Python `re`；无匹配是非错误说明，非法 regex 是 error。搜索工具本身不截断结果，由 Core Executor 统一截断一次。

### 文件与测试

- 新增 `src/uthcode/integrations/tools/search_tools.py`。
- 新增 `tests/test_builtin_search_tools.py`，覆盖普通模式、include、空结果、非法 regex、固定跳过目录、parent pattern、外部文件/目录符号链接、稳定排序和 Core 截断。
- `rg -n "subprocess|shell=True|\brg\b|\bgrep\b|\bfind\b" src/uthcode/integrations/tools/search_tools.py` 无匹配。

## 4. Task 5：Bash 进程工具

### 实际机制

- `BashTool` 在 Application 提供的规范化 workdir 中使用当前操作系统 shell、当前用户权限执行命令；代码明确这是 unsandboxed process execution，不提供 OS Sandbox、黑名单或提权。
- schema 固定 `timeout_seconds` 默认 120、范围 1–600，并拒绝额外参数。
- stdout、stderr、无输出和非零退出分别可观察；非零退出返回 `is_error=True` 并保留退出码文本。超时与 Core cancellation 都会终止命令并等待进程及输出管道回收，无法确认收口时不会报告成功。
- Windows 使用独立进程组和 `taskkill /PID /T /F` 收口进程树；POSIX 使用独立 session/进程组并发送终止信号，必要时升级为强制终止。普通任务取消也会先收口子进程再重新抛出取消。
- Bash 输出不在 Integration 层截断，统一交由 Core Executor 处理。

### 文件与测试

- 新增 `src/uthcode/integrations/tools/process_tools.py`。
- 新增 `tests/test_builtin_process_tool.py`，覆盖 cwd、stdout/stderr、空输出、非零退出、默认/上下界 timeout schema、timeout、cancellation、回收时限及 Core 截断。

## 5. 验证结果

开发环境：`conda run --no-capture-output -n re-uthcode ...`。

- 前置回归：`tests/test_config_loader_integration.py tests/test_configuration.py tests/test_tool_core.py tests/test_provider_contract.py tests/test_package.py tests/test_architecture_boundaries.py`：`98 passed`。
- Task 3 文件与架构定向回归：`16 passed`；Task 4 搜索定向回归：`8 passed`；Task 5 进程定向回归：`7 passed`。
- 三组内置工具合并回归：`31 passed`。
- Core/Provider/package 回归：`36 passed`。
- 架构门禁：`21 passed`。
- `python -m compileall -q src tests`：通过。
- `python -m pip check`：`No broken requirements found.`
- `pytest -q`：`313 passed, 3 skipped`。3 个 live Provider 门禁继续保持 skip。
- `git diff --check`：退出码 0；仅报告工作区既有的 LF/CRLF 转换提示，无 diff 错误。
- UTF-8 guard：Checklist 和本 Feedback 均需通过最终检查；当前 Checklist 已通过写入前检查，Feedback 创建后再执行最终检查。

## 6. Checklist 与范围差异

- Task 3：7/7 已勾选。
- Task 4：7/7 已勾选。
- Task 5：6/7 已勾选。
- Task 5 最后一项要求同时修改 README，明确当前 OS shell 和 unsandboxed process execution；但 W03 Prompt 明确 Task 5 只能新增进程实现与测试，且 README 属于后续 W04/Application delivery 范围。因此未修改 README，也未勾选该复合项；代码中的 `BashTool` 定义和 docstring 已完成对应语义，剩余 README 证据交由 W04 处理。
- 未修改原始需求、Spec、Tasks、Prompt 或 Checklist 的文字、编号和顺序；Checklist 只把已验证项从未完成改为完成。

## 7. 遗留负担清理与风险

- 未新增 factory、Application Tool API、Agent Loop、Permission、审批、Sandbox、shell 黑名单、索引、文件历史或兼容层。
- 未新增第二套 ToolCall、ToolResult、ToolDefinition 或 CancellationToken；所有工具只实现现有 Core `Tool` Protocol。
- `src/uthcode/integrations/tools` 不导入 `uthcode.application`、`uthcode.interfaces`、`mewcode`、LangGraph/LangChain 或 Pydantic；搜索实现也没有系统搜索命令调用。
- 符号链接测试在当前 Windows 环境可执行并通过；若其他平台不支持创建符号链接，相关测试应按 Prompt 约束显式 skip，而不能放宽路径边界。
- Bash 终止依赖当前 OS 的进程组/进程树能力；实现只有在进程和管道均可确认回收时才返回超时/取消结果，不会把无法确认的状态报告为成功。

## 8. 返工第 1 轮

### 返工原因与复现场景

本轮针对审查问题 [P1] 返工：原实现看到直接 shell 的 `process.returncode is not None` 后会直接报告进程树已收口，但 shell 可能已经退出，后代仍在运行并继续持有 stdout/stderr 管道。复现场景是 Bash 启动 Python 父进程，父进程创建一个子进程后立即退出，子进程等待约 2 秒再写入唯一标记文件，Bash timeout 为 1 秒；原实现最终返回 timeout error，但调用约 2.17 秒才返回且标记文件存在，证明后代只是自然结束而没有被终止。

### 平台进程树生命周期机制

- Windows 使用标准 Win32 Job Object 作为独立的后代生命周期控制对象。shell 以 `CREATE_SUSPENDED` 创建，在恢复主线程前先通过 `AssignProcessToJobObject` 放入 Job Object；终止时调用 `TerminateJobObject`，并通过 `QueryInformationJobObject` 等待 Job 的活动进程数归零。该机制不依赖管理员权限、Sandbox、黑名单或外部进程管理框架。
- POSIX 继续使用 `start_new_session=True` 创建独立 session/process group，并保存原始进程组 ID。终止时即使直接 shell 已经退出，仍向该原始进程组发送 `SIGTERM`，必要时升级为 `SIGKILL`，再通过 `killpg(group_id, 0)` 轮询确认进程组已经消失。

直接 shell 退出不再等同于命令树结束：生命周期控制对象独立于直接进程的 returncode 保存。Windows 的 Job Object 句柄仍覆盖已派生的后代，POSIX 的原始进程组 ID 仍可用于向同一进程组发信号；因此后代仍持有管道时也会在 timeout/cancel 收口中被主动处理。

### timeout、Core cancellation 与 asyncio task cancellation 收口

三条路径现在都执行相同的收口顺序：先请求平台进程树/进程组终止，再 await 直接进程回收和生命周期控制对象的空状态，随后继续 await `communicate()` 完成 stdout/stderr 管道收口。未完成确认前不会返回成功；不会取消 `communicate()`、关闭父侧管道或用缩短等待伪造回收。

- timeout 在确认进程与管道均已回收后返回原有的 `Error: command timed out after Ns`。
- Core `CancellationToken` 在确认进程与管道均已回收后返回原有的 `Error: command cancelled`。
- 外层 asyncio task cancellation 在完成同一收口后重新抛出 `asyncio.CancelledError`，保持调用方取消语义；若平台收口或管道回收无法确认，则抛出明确失败，不会把该状态报告为成功。

### 新增真实后代副作用测试

`tests/test_builtin_process_tool.py` 新增三个真实回归场景：

- `test_bash_timeout_terminates_descendant_after_shell_exit`：父进程立即退出，后代延迟写标记文件，timeout 先发生；返回不等待到后代自然结束，且延迟窗口后标记文件不存在。
- `test_bash_cancellation_terminates_descendant_after_shell_exit`：同一父子结构触发 `CancellationToken.cancel()`；返回 cancellation error，且延迟窗口后标记文件不存在。
- `test_bash_task_cancellation_terminates_descendant_after_shell_exit`：同一父子结构取消执行 task；task 保持 `CancelledError` 语义，且延迟窗口后标记文件不存在。

三项均在当前 Windows 环境真实运行通过。

### 验证结果

- `conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_builtin_process_tool.py`：`10 passed`，包含上述三个后代收口场景。
- `conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_builtin_file_tools.py tests/test_builtin_search_tools.py tests/test_builtin_process_tool.py tests/test_architecture_boundaries.py`：`55 passed`。
- `conda run --no-capture-output -n re-uthcode python -m pytest -q`：`316 passed, 3 skipped`；3 个 live Provider 测试继续按既有规则 skip。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests`：通过。
- `conda run --no-capture-output -n re-uthcode python -m pip check`：`No broken requirements found.`
- `git diff --check`：退出码 0；仅有既有 LF/CRLF 转换提示，无 diff 错误。

### 平台差异、风险与遗留负担检查

当前工作区为 Windows，Windows Job Object、挂起后分配再恢复和三个真实后代副作用测试均已验证。POSIX 分支保留独立 session/process group、原始组信号和组退出确认结构；本轮未在 Windows 工作区模拟 POSIX 内核，但该分支不依赖 Windows API。两种机制都面向当前用户权限下的普通后代；若命令显式创建脱离 Job/session 的进程，操作系统不提供无特权的通用树归属保证，收口确认会失败而不会报告成功。

本轮没有引入兼容层、别名、第二套 Tool DTO、Sandbox、黑名单或无关进程管理框架；没有修改 Core Tool/Provider DTO、文件/搜索工具、Application、Interface、Provider Integration、README、原始需求/Spec/Tasks/Prompt 或 Checklist，也没有开始 Task 6—Task 9，未执行 Git 写操作。公开 `BashTool` 名称、参数 schema、默认/范围 timeout、当前 shell/current user 和 unsandboxed process execution 契约保持不变。
