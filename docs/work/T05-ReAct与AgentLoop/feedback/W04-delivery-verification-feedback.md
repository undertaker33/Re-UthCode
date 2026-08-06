# W04 delivery-verification Feedback

## 1. 执行范围与基线

本轮由用户明确派发 W04 Prompt，严格按 Task 7 → Task 8 → Task 9 执行。已完整读取 AGENTS、SRe-AGENTS、工作包规则、T05 任务书/Spec/Tasks/Checklist、W01–W03 Feedback、T04 最终 Feedback 以及 T02/T03 的既有调用边界。未执行 Git 写操作、真实 Provider 请求、网络请求或工作包归档。

实际 `HEAD` 为 `20fc83f7275d532465d7f88c78c3e3a7c8ba0fcf`，是 W01–W03 交接后的工作基线；与 T05 任务书记录的 T04 固定 SHA 不同，但与 W02/W03 Feedback 记录一致，未回退或改写此前交付。Task 1–Task 6 Checklist 在本轮开始时均已完成。

## 2. Task 7：[接入主流程]

最终普通 Agent 路径唯一收口为：

```text
Headless / CLI / TUI
→ UthCodeApplication.create_run()
→ AgentRun.start_turn()
→ Core AgentLoop / AgentTurnExecution
→ TurnHandle.events() / TurnHandle.result()
```

Application 在 Turn 开始时固定 Provider、Model Ref、有序 Tool Definitions、安全摘要函数和独立取消令牌；每次 iteration 仍由 Application 构建带 System Prompt 的请求。Core 继续独占 RunState、Provider 权威终态提交、Tool FIFO、限制、Usage、取消补偿和唯一终态。

低层 `start_generation()`、`stream_generation()`、`tool_definitions()`、`execute_tool_calls()` 均保留并回归通过。它们仍是单轮 Provider/手动 Tool API，不形成第二套自动 Loop。Application 公开 AgentRun、TurnHandle、AgentEvent、RunSnapshot 和 TurnResult，但不公开 RunState、ToolRegistry、ToolExecutor 或具体 Integration Tool。

Task 7 验证：

- `pytest -q tests/test_application_runs.py tests/test_cli.py tests/test_tui.py tests/test_architecture_boundaries.py tests/test_package.py`：`86 passed`。
- 低层 Application/Tool/Runtime 回归：`31 passed`。
- `ProviderEvent|GenerationHandle` 在 `src/uthcode/interfaces`：0 条；`uthcode.core|uthcode.integrations` 在 Interface：0 条。
- 正式 Headless、CLI、TUI 均只通过 Application 公共 API 进入 Run/Turn；没有 Interface 自动执行路径。

## 3. Task 8：[端到端验证]

按 Checklist 顺序执行的精确结果：

| 命令 | 结果 |
| --- | --- |
| `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests` | 退出码 0 |
| `pytest -q tests/test_agent_policy.py tests/test_agent_events.py tests/test_agent_loop.py tests/test_application_runs.py` | `77 passed` |
| `pytest -q tests/test_application.py tests/test_application_runtime.py tests/test_application_tools.py tests/test_cli.py tests/test_tui.py` | `74 passed` |
| `pytest -q tests/test_provider_contract.py tests/test_anthropic_integration.py tests/test_openai_responses_integration.py tests/test_openai_compat_integration.py` | `64 passed, 3 skipped` |
| `pytest -q tests/test_architecture_boundaries.py tests/test_package.py` | `27 passed` |
| `pytest -q` | `416 passed, 3 skipped` |
| `conda run --no-capture-output -n re-uthcode python -m pip check` | `No broken requirements found.` |
| `git diff --check` | 退出码 0；仅有既有 LF/CRLF 转换提示 |

未授权的 3 个 live Provider 用例继续 skip，未发起网络请求或产生费用。正式离线 E2E 探针（Headless 真实 ReadFile、CLI 正式模块入口、TUI 正式 Fake 流程及 TUI ToolResult 隐藏）为 `4 passed`，覆盖 reasoning/Tool activity/final/唯一 terminal 及结果正文隐藏。

## 4. Task 9：[遗留负担清理]

否定性扫描均无生产匹配：

- 旧 UthCode/MewCode、LangGraph/LangChain：0 条。
- `StateGraph|GraphState|checkpoint|ConversationManager`：0 条。
- Integration 对 Application/Interface 的导入：0 条。
- Interface 对 Core/Integration 的导入：0 条。
- Interface 中 `ProviderEvent`、TUI 中 `tool_result|ToolResultPart`：均为 0 条。
- Core Agent 中 `asyncio.gather|TaskGroup`：0 条。

扫描首次发现 `tests/test_architecture_boundaries.py` 的否定性门禁自身含有字面量 `checkpoint`。按 W04 Prompt 要求改为运行时字符串拼接，保留原有禁止断言语义；这是本轮唯一的源码测试门禁修改。修改后架构/package 为 `27 passed`，全量测试仍为 `416 passed, 3 skipped`。

复核确认只有一套 Core AgentLoop、一套 AgentEvent/RunState/Tool DTO 和一条正式 Run/Turn 路径；没有旧 ProviderEvent renderer、无调用方旧单轮 state、ToolResult 展开入口、Interface 原始参数摘要、兼容 alias、Facade、Shim、第二套自动 Loop、后置能力占位或 SDK 越界。`README.md` 与 Bash 实现均明确当前用户权限下的 `unsandboxed process execution`，没有把它描述为 OS Sandbox。

## 5. 本轮文件与差异

本轮实际新增或修改：

- 新增 `docs/work/T05-ReAct与AgentLoop/feedback/W04-delivery-verification-feedback.md`。
- 修改 `docs/work/T05-ReAct与AgentLoop/T05-ReAct与AgentLoop-checklist.md`：只将 Task 7、Task 8、Task 9 的现有复选框改为 `[x]`。
- 修改 `tests/test_architecture_boundaries.py`：仅修复否定性测试门禁的 `checkpoint` 自命中。

本轮没有删除文件，没有修改 Provider Adapter/DTO、Core Agent 业务语义、Application Run/Turn、CLI/TUI、README、配置、Slash Command、System Prompt 或 T04 Tool 实现。当前工作树中其他 W01–W03 源码、测试、README 和 Feedback 改动均保留原状，未整理或覆盖。

## 6. Checklist、风险与收口

- Task 1–Task 9：全部现有验收项已勾选。
- 3 个 live Provider 测试未授权，因此保持 skip；这不影响离线交付验证。
- 未进行真实终端人工验收或真实 Provider 请求；TUI 证据来自 Textual Pilot 和正式 Fake Application 入口。
- T04/T05 工作包仍位于 `docs/work/`，未由 Agent 归档，等待用户确认后手动移动。
- 未执行 commit、push、merge、rebase、tag、分支写入或工作树清理。

## 7. UTF-8 guard

- files checked：`README.md`、`docs/work/T05-ReAct与AgentLoop/T05-ReAct与AgentLoop-checklist.md`、`docs/work/T05-ReAct与AgentLoop/feedback/W04-delivery-verification-feedback.md`
- result：写入前后均通过 UTF-8 解码、常见乱码标记和 Markdown fence parity 检查
- repaired encoding issues：无

## W04-R1 包级返工与 README 重写

独立包级验收指出 README 仍保留旧的单轮 TUI 和 Text delta stdout 描述。
本轮将根 README 完整改写为中文、面向 GitHub 用户的产品说明，删除嵌入式
开发 API 教程，改为介绍功能、安装、首次配置、Provider、TUI、`exec`、
配置作用范围、内置工具、安全边界、常见问题和当前状态。

README 现明确：

- 同一次 TUI 使用连续对话，`/clear` 只清显示；
- `exec` 仅把最终回答写 stdout，活动与诊断写 stderr；
- Bash 是当前用户权限下的未沙箱化进程执行；
- API Key 只从环境变量读取；
- 当前没有 OS Sandbox、持久 Session、Memory 等后置能力。

本轮同时收口 W02-R3 的短环境值脱敏和 W03-R2 的 ReasoningPart 投影问题。
重新执行 Application/Run、CLI、TUI 定向测试与全量测试，结果分别为
`53 passed`、`17 passed`、`26 passed` 和 `416 passed, 3 skipped`。
Checklist 未修改；未运行 live Provider、未访问网络、未执行 Git 写操作。

## W04-R2 短环境值边界补充

返工复查发现 W02-R3 的三字符阈值仍会遗漏两字符 ambient 值。本轮继续完成
W02-R4：`q7z`、`qz`、`q` 均在 Tool 生命周期事件发布前脱敏，普通
`echo 2026-08-06` 保持可读。

重新执行 Application/Run 定向测试与全量测试，结果为 `53 passed` 和
`416 passed, 3 skipped`。README 与 W03-R2 未发生语义回退；Checklist 未修改，
未运行 live Provider、未访问网络、未执行 Git 写操作。
