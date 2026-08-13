# W01 权限分类与完全访问收口 Feedback

## 2026-08-13 初始交付记录

### 实际完成

- Windows Bash 分类支持 `cd`/`chdir /d <literal>`，并沿复合命令顺序计算物理范围；缺失、动态、通配符或多目标仍为 UNKNOWN。
- CMD 普通括号组不再自动产生 `nested-execution`，组内可见 READ/WRITE/DESTRUCTIVE 继续参与最高 effect 聚合；命令替换、反引号和间接执行仍保守分类。
- Core `Rule` 新增结构化 `RuleAuthority`，`PermissionAction` 新增可信 `CircuitBreaker` 事实。权限 TOML 不接受这两个字段，外部规则不能伪造强制等级。
- 唯一 `PermissionEvaluator` 现在先处理 circuit breaker 与更严格显式 DENY，再处理显式 Guard；`full_access` 跳过内置普通 Guard、普通 Policy 与 Strategy。
- circuit breaker 仅覆盖根目录/Home 递归删除、磁盘/卷破坏和裸设备写入，三模式均 ASK，choices 为 ONCE/REJECT；普通 ALLOW 不能覆盖。
- 正式 Application E2E 使用离线 Scripted Provider、真实 Bash preflight/evaluator 和不可执行 Bash stub，证明普通 Guard 在 `full_access` 无 pause，breaker/显式 Guard 在 execute 前 pause，拒绝无副作用并闭合原 call ID。

### 失败基线

生产修复前新增 Task 1 回归：

```text
python -m pytest tests/test_builtin_process_tool.py -k "cmd_cd_d or cmd_groups" -q
5 failed, 3 passed, 82 deselected
```

失败覆盖 `cd /d` 静态范围、缺失目标误判、CMD 组 READ 退化为 UNKNOWN，以及 WRITE/DESTRUCTIVE 组仍带 `nested-execution`。

Task 2 权限结构红测在生产实现前因 `CircuitBreaker` 尚不存在而 collection error；实现后对应矩阵为 `6 passed, 100 deselected`。完整旧回归首次运行的 30 个失败均为已冻结的旧 `full_access` Guard 语义或旧 rule-id 断言，已按本工作包确认的新语义替换。

### 关键调用链与修改文件

正式顺序保持：

```text
Tool prepare / trusted Bash segment facts
  -> fixed Runtime Hook
  -> one PermissionEvaluator
  -> typed Permission pause or execute_prepared once
  -> exactly-one ToolResult
```

生产文件：

- `src/uthcode/integrations/tools/process_tools.py`
- `src/uthcode/core/permission.py`
- `src/uthcode/integrations/permissions.py`
- `src/uthcode/application/commands/builtins.py`

测试文件：

- `tests/test_builtin_process_tool.py`
- `tests/test_permission.py`
- `tests/test_permission_rules.py`
- `tests/test_permission_delivery.py`
- `tests/test_t07_1_e2e.py`

当前事实文档：

- `AGENTS.md`
- `README.md`
- `docs/Context-Index.md`
- `docs/context/A01-AgentRuntime/AgentRuntime-Context.md`
- `docs/context/A02-Control/Control-Context.md`

### 验证结果

- 分类/权限定向：`221 passed`。
- Permission delivery/interaction/Application：`151 passed`。
- T07-1 E2E：`6 passed`。
- architecture/package：`32 passed`。
- command/TUI：`97 passed`。
- 全量 pytest：`971 passed, 3 skipped`；3 个 skip 为既有环境门禁。
- `python -m compileall -q src tests`：退出码 0。
- `python -m pip check`：`No broken requirements found.`。
- `git diff --check`：退出码 0，仅有 Git 的 LF/CRLF 转换提示，无 whitespace error。
- 生产扫描未发现通过 rule ID、source 或展示摘要猜测 circuit-breaker 的逻辑；非归档当前文档未发现旧 `full_access` 口径。

Checklist 23 项已全部勾选，证据对应上述定向、E2E、架构、全量和静态检查。

### 差异、未验证项与风险

- 未修改 `core/agent.py`、`application/runs.py`、`application/tools.py` 或 TUI 权限投影；现有 Guard ASK 投影已满足 ONCE/REJECT，正式回归证明无需窄改。
- 未修改 `docs/OutstandingDebtList.md`；本任务没有能力欠账变化。
- 未修改归档 T07/T08/T08-1，也未执行归档、commit、push、merge、rebase、tag 或分支操作。
- Bash 仍是保守段级扫描器，不是完整 Shell/CMD/PowerShell AST，也不提供 OS Sandbox。危险命令测试均停在 preflight/evaluator 或使用不可执行 stub，未真实执行。

## 返工第 1 轮

### 返工原因

独立验收发现两个阻塞缺陷：circuit breaker 只检查顶层程序，导致灾难操作可藏在 Shell/CMD/PowerShell 包装、命令替换或 `diskpart` 管道中并在 `full_access` 放行；CMD 括号组在去除括号前已按组内连接符切成残片，导致只读组退化为 UNKNOWN。

### 修复前失败证据

先新增 R01/R02 回归，再运行：

```text
python -m pytest tests/test_builtin_process_tool.py -k "recursively_classify_internal_connectors or inspect_supported_nested_execution" -q
13 failed, 2 passed, 115 deselected
```

失败覆盖 `sh/bash -c`、`cmd /c`、PowerShell `-Command`、`$()`、反引号、`clean | diskpart`、`${HOME}`、`$env:USERPROFILE`，以及带 `&&`/`&`/管道/嵌套组的 READ 分类。组内 WRITE 与 DESTRUCTIVE 两个既有安全聚合断言当时仍通过。

### 实际修复

- `_scan_bash_command()` 增加可见 CMD group depth；组内连接符不再被当作顶层 separator。
- 完整平衡组通过 `_outer_command_group()` 递归进入既有分类链，READ/WRITE/DESTRUCTIVE 与嵌套管道按最高 effect 聚合；不把删除括号后的整段直接交给 `shlex`。
- circuit breaker 对已声明支持的 `sh/bash/zsh -c`、`cmd /c`、`pwsh/powershell -Command`、`$()`、反引号进行最多四层的有限 payload 递归；单引号或转义后的非执行文本保持 inert。
- Home 目标补齐 `${HOME}` 与 `$env:USERPROFILE`；明确的 `echo/Write-Output/printf clean | diskpart` 进入磁盘/卷破坏 breaker。
- 正式 Application E2E 把 CMD 组场景升级为组内 `&&`，并在同一 FIFO batch 中验证六种嵌套灾难调用在 `full_access` 逐一 pause、ONCE/REJECT、execute=0 和全部 call ID 闭合。

### 重新验证

- R01/R02 聚焦回归：`15 passed, 115 deselected`。
- 分类/权限完整定向：`236 passed`。
- T07-1 正式 E2E：`7 passed`。
- Permission delivery/interaction/Application：`151 passed`。
- architecture/package：`32 passed`。
- 全量 pytest：`988 passed, 3 skipped`。
- `python -m compileall -q src tests`：退出码 0。
- `python -m pip check`：`No broken requirements found.`。
- `git diff --check`：退出码 0，仅有 LF/CRLF 转换提示，无 whitespace error。

### 状态、差异与剩余风险

- R01、R02 已修复，Checklist 23 项经重新验证继续全部成立；`Context-Index` 的 `implemented_unarchived` 状态恢复成立。
- 首轮 Feedback 的测试数字和完成结论是当时记录，按追加规则保留；本节的返工结果取代其当前有效性。
- 未修改冻结的任务书文字、结构或顺序，只保留既有 checkbox 状态；未修改归档 T07/T08/T08-1 或 `docs/OutstandingDebtList.md`。
- 有限递归只覆盖工作包和返工明确要求的包装/替换形式，仍不宣称完整 Shell/CMD/PowerShell AST；危险命令未真实执行。

## 返工第 2 轮

### 返工原因

人工验收发现只读 Windows 调查命令 `dir *.py /s /b 2>nul | find /c ".py"` 在 `auto` 下仍进入普通权限确认。根因是 Bash segment 分类看到任意 `<`/`>` 就直接返回 WRITE，没有区分真实文件输出、输入重定向、文件描述符复制与平台空设备；`2>nul` 因此把整条 `cd /d ... && ...` 链污染为 WRITE/UNKNOWN。

### 实际修复

- 分类器复用段级重定向解析结果：输出到普通文件保持 WRITE；输入重定向不提升底层命令 effect；`2>&1`、`>&2` 等描述符复制以及 `NUL`、`NUL:`、`/dev/null` 丢弃不再视为文件写入。
- 无目标的残缺重定向保持 UNKNOWN，引号内普通 `>` 文本不被当作重定向。
- 新增截图命令的真实 Bash preflight + PermissionEvaluator 回归，确认其在 `auto` 下为 READ/INSIDE/ALLOW；真实 `>`、`>>` 文件输出仍为 WRITE。
- 既有敏感路径 Guard、裸设备 circuit breaker 和多层嵌套灾难命令识别保持不变。

### 红绿验证与完整回归

- 修复前聚焦回归：`6 failed, 2 passed`；失败均为错误的 WRITE 分类与截图链路的 WRITE/UNKNOWN。
- 修复后聚焦回归：`11 passed, 138 deselected`。
- 权限与 T07-1 组合定向：`308 passed`。
- 全量 pytest：`1007 passed, 3 skipped`；3 个 skip 为既有环境门禁。
- `python -m compileall -q src tests`：退出码 0。
- `python -m pip check`：`No broken requirements found.`。
- `git diff --check`：退出码 0；仅有 LF/CRLF 转换提示，无 whitespace error。

### 状态与边界

- 本轮只修改 `process_tools.py`、对应分类测试和本 Feedback；未扩大为完整 Shell/CMD/PowerShell AST。
- 未修改冻结任务书、Checklist 文字或归档工作包；未执行 Git 操作。

## 返工第 3 轮

### 返工原因

复查确认 R02 已闭合，但 R01 仍有双层包装旁路。`_nested_command_payloads()` 使用 `strip('"\'')` 从两端连续删除单双引号；例如 `"sh -c 'rm -rf /'"` 会丢失外层开头双引号和内层结尾单引号，下一层解析因引号不平衡停止，导致 `full_access` ALLOW。这与上一轮“最多四层有限递归”的事实声明不一致。

### 修复前失败证据

新增双层、混合、四层和 inert 负例后运行：

```text
python -m pytest tests/test_builtin_process_tool.py -k "preserve_nested_wrapper_quotes or nested_wrapper_inert_text" -q
4 failed, 4 passed, 130 deselected
```

失败覆盖双层 Shell、双层 PowerShell、Shell→PowerShell→CMD 混合包装和四层 Shell；双层 CMD及单引号/转义 inert 负例通过。

### 实际修复

- 新增 `_remove_matching_outer_quotes()`，只在首尾为同一种引号时移除一对外层引号，不再按字符集合连续剥离。
- 移除该外层引号时只解码同一种外层引号的反斜线转义，使更深一层能恢复自己的配对边界；内部异种引号完整保留。
- 正式 Application E2E 的嵌套 breaker FIFO batch 新增 `bash -c "sh -c 'rm -rf /'"`，继续验证每条调用均在 `full_access` pause、choices 为 ONCE/REJECT、execute=0、call ID 全部闭合。

### 重新验证

- R01.1 聚焦回归：`8 passed, 130 deselected`。
- 分类/权限完整定向：`244 passed`。
- T07-1 正式 E2E：`7 passed`；嵌套 breaker batch 从 6 条扩为 7 条。
- Permission delivery/interaction/Application：`151 passed`。
- architecture/package：`32 passed`。
- 全量 pytest：`996 passed, 3 skipped`。
- `python -m compileall -q src tests`：退出码 0。
- `python -m pip check`：`No broken requirements found.`。
- `git diff --check`：退出码 0，仅有 LF/CRLF 转换提示，无 whitespace error。

### 当前状态与风险

- R01.1 已闭合；双层 Shell/PowerShell、双层 CMD、混合包装、四层 Shell 均有正例，单引号及转义命令替换仍有负例。
- Checklist、`implemented_unarchived` 与当前事实文档在本轮验证后重新成立；不改写首轮或返工第 1 轮历史记录。
- 有限解析仍只覆盖已声明的包装器和最多四层递归，不等同完整 AST；危险命令只经过 preflight/evaluator 或不可执行 stub。
