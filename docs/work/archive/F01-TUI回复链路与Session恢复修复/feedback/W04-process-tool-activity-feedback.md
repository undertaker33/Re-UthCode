# W04：进程输出与 Tool 活动 Feedback

## 执行范围与边界

本轮由用户显式派发 `prompt/W04-process-tool-activity-prompt.md`，严格按
T05 → T06 串行实施。只修改进程输出解码、Application Tool 安全摘要、对应
测试和本 Feedback；没有修改 Context、Provider、History、Session、TUI、Secret
配置边界、Core DTO 或其它 Worker 的 Feedback，也没有执行 Git 写操作。

## T05：Windows 进程输出解码

`src/uthcode/integrations/tools/process_tools.py` 现在通过单一
`_decode_process_output()` 收口 stdout/stderr 的 bytes 转文本：

1. 先用 UTF-8 strict；
2. Windows 再按当前 Console output code page、系统 OEM code page、ANSI code
   page 和 `locale.getencoding()` 返回的系统编码做有限 strict fallback；
3. 所有已知编码均无法解释时，最后才使用 UTF-8 replacement。

没有调用全局 `chcp`，没有增加编码探测依赖，也没有改变 shell、退出码、超时、
取消、输出上限或进程回收语义。stdout 和 stderr 分别经过同一解码入口。

新增测试覆盖：

- 合法 UTF-8 中文 stdout/stderr；
- Windows CP936（当前中文系统的 OEM/ANSI 事实）中文 stdout/stderr；
- 无法由已知编码解释的 bytes 最终使用 replacement；
- 既有空输出、非零退出、timeout、cancel、output limit 和进程回收回归。

真实 Windows 正式 Bash probe 使用临时目录和中文文件名 `中文文件.txt` 执行
`dir /b <probe-dir>`，结果为：

```text
STDOUT:
中文文件.txt
```

probe exit code 为 0，结果没有 `U+FFFD` 或 mojibake；临时目录已确认清理。

## T06：Tool 活动摘要与 FIFO 合同

`ApplicationToolService.describe_tool_call()` 现在只拥有安全参数/命令摘要，
`AgentEvent.tool_name` 独立拥有 Tool 名称。这样 CLI/TUI 组合 `name + command`
时不会产生 `Bash Bash ...`、`ReadFile ReadFile ...` 等重复名称。

默认 Tool 的摘要仅包含安全内容：命令摘要、工作区相对路径、Glob pattern/scope、
Grep scope/include、opaque ref 与边界数字；Write/Edit 正文、Grep pattern、
unknown/custom 参数和 ToolResult 正文不进入摘要。自定义 Tool 使用
`<arguments hidden>` 占位。原 T05 脱敏设计保持不变：配置秘密始终脱敏，所有非空
ambient 环境值按 token 边界脱敏，仅 `0`、`1` 保留为普通 feature flag；
`q7z`、`qz`、`q` 均在 ToolStarted/ToolFinished 事件发布前被替换。

新增/补充回归证明：

- Bash、ReadFile、WriteFile、EditFile、Glob、Grep、ToolResultRead、HistoryRead
  的名称与摘要组合中名称只出现一次；
- 同 batch 两个 ToolCall 的 ToolStarted 和 ToolFinished 均各一次，完成顺序与
  call FIFO 一致，状态文字为 `finished`；
- 既有 error、denied、cancelled、skipped 状态与 ToolStarted transient /
  ToolFinished permanent 语义继续通过；
- 构造的配置 secret、敏感 assignment/option、裸 key、Bearer/Basic、ambient
  短值均未进入事件或公开摘要。

## 修改文件

- `src/uthcode/integrations/tools/process_tools.py`
- `src/uthcode/application/tools.py`
- `tests/test_builtin_process_tool.py`
- `tests/test_application_runs.py`
- `tests/test_cli.py`（同步 Tool 摘要单一 owner 的既有消费方断言）
- `docs/work/F01-TUI回复链路与Session恢复修复/F01-TUI回复链路与Session恢复修复-checklist.md`
- 本 Feedback 文件

没有删除文件，没有引入第三方依赖，没有修改 ToolCall/ToolResult DTO，也没有
新增第二个 Tool Registry、摘要入口或进程执行器。

## 验证结果与 Checklist

| 命令 | 结果 |
| --- | --- |
| `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_builtin_process_tool.py -q` | `152 passed` |
| `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_application_tools.py tests/test_application_runs.py tests/test_agent_loop.py -q` | `108 passed` |
| `conda run --no-capture-output -n re-uthcode python -m pytest -q` | `1271 passed, 3 skipped`；3 个 live Provider 用例保持未授权 skip |
| `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q` | `23 passed` |
| `rg -n "chardet|charset_normalizer|EncodingManager|EncodingRegistry" src tests` | `0 matches` |
| `git diff --check` | 退出码 `0`；仅有既有 LF/CRLF 转换提示 |
| 真实 Windows 中文文件名 Bash probe | exit code `0`，输出 `中文文件.txt`，无 replacement/mojibake，临时目录已清理 |

F01 Checklist 已仅将 T05、T06 的已验证项目从 `[ ]` 改为 `[x]`；其它 Task
保持原状态。

## 偏差、风险与遗留负担

- 当前 shell 为 UTF-8 code page 时，合法 UTF-8 仍由 strict 首选路径处理；CP936
  用例证明系统编码 fallback 可恢复中文。没有覆盖未经当前 Windows API/locale
  报告的任意编码，也没有引入猜测框架。
- Tool 名称 owner 的调整要求消费方使用事件中的 `tool_name` 与摘要 `command`
  组合；本轮按任务书不修改 TUI，现有 CLI/TUI 的组合已由摘要不含名称解决重复。
- 全量回归首次暴露 `tests/test_cli.py` 中一个旧的 `Reveal (Reveal)` 断言；该测试
  已同步为 `Reveal (<arguments hidden>)`，随后定向回归与全量测试均通过。
- 没有发现需要修改 TUI、Provider、History、Session 或公共 DTO 的阻断问题。
- 本轮未执行 Git commit、push、merge、PR 或工作包归档。
- 未引入兼容层、第二状态仓库、重复 Tool 活动路径、编码探测框架或临时生产
  产物；probe 产物已清理。

UTF-8 guard:
- files checked: 本 Feedback、F01 Checklist
- result: UTF-8 解码、replacement/mojibake 检查和 Markdown fence parity 通过
- repaired encoding issues: 无

## 首审返工 R1：Tool event 投影与 Windows 测试确定性

首审指出两个 UI-neutral 投影问题和一个 Windows 测试假设问题。本节追加记录，
不覆盖前轮事实：

- `src/uthcode/core/agent.py` 的 `AgentTurnExecution._safe_command()` 不再把
  `AskUserQuestion`、`TodoWrite`、`ProposePlan` 或无 describer 的已知 Tool 名称
 作为 `command` fallback；它们现在分别发布不含 Tool 名称的安全占位。CLI/TUI
  继续分别消费 `tool_name` 和 `command`，因此不会组合出重复名称。
- Permission resolver 返回 `Decision.DENY`，以及用户在 Permission Approval 中
  选择 `REJECT`，现在都发布 `ToolFinished.status == "denied"`，并保持
  `is_error=True`。普通错误仍为 `failed`，取消仍为 `cancelled`，steering 跳过仍
  为 `skipped`。
- 新增 Core 状态与摘要回归，覆盖三个控制类和无 describer fallback；新增真实
  `ToolStarted`/`ToolFinished` event 到 CLI `_tool_diagnostic()`、TUI
  `AgentEventRenderer` 和 terminal row 的消费组合回归，分别断言名称只出现一次、
  status 透传和 `denied` 颜色语义。只改了消费测试，未改 TUI 生产代码。
- Windows 中文输出用例改为读取当前 `_windows_output_encodings()`，只在当前报告
  的非 UTF-8 编码能够表示中文时运行；replacement 单测 monkeypatch 当前平台为
  Windows 并把报告编码固定为 `ascii`，使用 `0xff`，不再假定 CP936 或任意字节在
  所有码页都非法。

## R1 验证结果

| 命令/证据 | 结果 |
| --- | --- |
| 首次运行新增 R1 失败测试（实现前） | 5 failed：四个控制/fallback 摘要和一个 DENY status；其余 9 passed |
| `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_builtin_process_tool.py -q` | `152 passed` |
| `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_application_tools.py tests/test_application_runs.py tests/test_agent_loop.py -q` | `113 passed` |
| `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_cli.py tests/test_tui.py -q` | `105 passed` |
| `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q` | `23 passed` |
| `conda run --no-capture-output -n re-uthcode python -m pytest -q` | `1284 passed, 3 skipped`；3 个 live Provider 用例保持未授权 skip |
| 真实 Windows 中文文件名 Bash probe | 当前报告编码 `('cp65001', 'cp936', 'cp936', 'cp936')`，选择可表示中文的 `cp65001`；`dir /b` 输出 `中文文件.txt`，`is_error=False`，无 replacement/mojibake，`probe_cleanup=True` |

R1 新增/调整文件为 `src/uthcode/core/agent.py`、
`tests/test_agent_loop.py`、`tests/test_builtin_process_tool.py`、
`tests/test_cli.py`、`tests/test_tui.py` 和本 Feedback；TUI 生产源码保持未修改。
没有执行 Git commit、push、merge、PR 或工作包归档。
