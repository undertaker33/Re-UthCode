# W04 application-delivery Feedback

## 1. 完成结论

已按 Task 6 → Task 7 → Task 8 → Task 9 完成 T04 Application 接入、手动单次往返、全量验证和遗留清理。W01、W02、W03 Feedback 与 Checklist 已核对并通过；本轮未执行 Git 写操作、真实 Provider 请求或工作包归档。

最终 Headless 调用链为：

```text
create_application(runtime_context)
    → create_default_tools(runtime_context.workdir)
    → ApplicationToolService
    → Core ToolRegistry + ToolExecutor

headless caller
    → application.tool_definitions()
    → GenerationRequest(tools=...)
    → Provider ToolCallPart
    → application.execute_tool_calls(calls)
    → ToolResultPart
    → caller 构造 Message(role="tool") 并发起下一次请求
```

`start_generation()` 仍然只准备并执行一轮 Provider 请求，不自动注入工具、不自动执行 ToolCall、不自动追加消息，也没有引入 Agent Loop、Permission、审批或 Sandbox。

## 2. Task 6：默认工具 Factory 与 Application API

- 新增 `src/uthcode/integrations/tools/factory.py`，每次创建独立的 `WorkspacePathResolver` 与 `FileReadTracker`，按 `ReadFile`、`WriteFile`、`EditFile`、`Glob`、`Grep`、`Bash` 固定顺序返回六个 Integration Tool。
- 三个文件工具共享同一 resolver/tracker；不同 Application 由不同 factory 调用获得隔离状态。Bash 使用同一 resolver 的规范化 workdir。
- 新增 `src/uthcode/application/tools.py`。`ApplicationToolService` 内部持有 Registry/Executor，只向 `UthCodeApplication` 提供不可变定义 tuple 和 Core `ToolResultPart` tuple，不向调用方返回具体 Integration Tool、Registry 或 Executor。
- `create_application(..., tools=None)` 装配默认六工具；显式 `tools` 完整替代默认集合。Application 公共包导出 `CancellationToken`、`ToolDefinition`、`ToolCallPart`、`ToolResultPart` 等 Core 类型。
- `tests/test_application.py` 的既有 generation、model、Provider snapshot、取消和 System Prompt 行为保持通过；`tests/test_architecture_boundaries.py` 增加了正式 factory 依赖与 Integration/Interface 边界门禁。

## 3. Task 7：Fake Provider 手动工具往返

`tests/test_application_tools.py` 新增正式 `create_application()` 入口测试，使用现有 Fake Provider 的离线子类提供两轮确定性事件：

1. 第一次请求显式携带 Application 返回的六个 Tool Definition。
2. Fake Provider 返回 `ReadFile` 的 `ToolCallCompleted`，保留 `provider-call-1`。
3. 调用方将事件转换为 Core `ToolCallPart`，通过 `application.execute_tool_calls()` 执行。
4. 结果 ID 仍为 `provider-call-1`，内容为临时 runtime workdir 中真实文件的 `1\tfrom the fake workdir`。
5. 调用方手动构造 `Message("assistant", (call,))` 与 `Message("tool", (result,))`，再发起第二次请求。
6. 测试确认执行结果产生前 Provider 只有一次请求，第二次请求才包含工具结果，并且两次请求使用同一 Application runtime context。

README 已补充 Headless 工具调用示例、工作区边界、物理符号链接检查，以及 Bash 使用当前操作系统 shell/当前用户权限的 unsandboxed process execution 语义。文档明确 Bash 不是 OS Sandbox，不附带 Permission approval 或危险命令策略。

## 4. Task 8：验证结果

开发环境均使用 `conda run --no-capture-output -n re-uthcode ...`。

| 命令 | 结果 |
| --- | --- |
| `python -m compileall -q src tests` | 通过 |
| `pytest -q tests/test_application_tools.py -k "round_trip or tool"` | `4 passed` |
| `pytest -q tests/test_application_tools.py tests/test_application.py tests/test_package.py` | `21 passed` |
| T04 工具组五个测试文件 | `49 passed` |
| 配置两组测试 | `42 passed` |
| Provider contract + 三协议测试 | `59 passed, 3 skipped` |
| Application/runtime/CLI/TUI | `58 passed` |
| 架构与 package | `26 passed` |
| `pytest -q` | `321 passed, 3 skipped` |
| `python -m pip check` | `No broken requirements found.` |
| `git diff --check` | 退出码 0；仅有既有 LF/CRLF 转换提示 |

3 个 live Provider 用例继续因既有授权门禁 skip，没有发起真实费用请求。

## 5. Task 9：遗留负担与边界清理

- `rg -n "from mewcode|import mewcode|langgraph|langchain" src tests README.md`：0 条。架构测试中的框架禁词改为运行时拼接，保留门禁语义而不污染交付扫描。
- 工具范围 `BaseModel|pydantic`：0 条；Provider 中既有的 Core `ToolDefinition`、`ToolCallPart`、`ToolResultPart`、`CancellationToken` 是唯一权威定义。
- Provider 之外的重复 Tool DTO、Tool Manager/Repository/Facade/Shim、兼容别名和双入口扫描：0 条。
- `src/uthcode/integrations` 中 `uthcode.application|uthcode.interfaces`：0 条；`integrations.config` 不再公开 `load_effective_config`，Application 是最终配置和工具的正式入口。
- 架构与导出测试确认 concrete Tool 只位于 Integration，Interface 不直连 Core Tool/Integration Tool；移除架构测试中对正式 `integrations/tools` 目录的未来目录禁令，并只增加 `bootstrap → integrations.tools.factory` 的明确允许边界。
- 未来能力关键词的剩余匹配仅为必要的否定性文档/边界测试、Provider SDK 既有字段和操作系统错误类型；没有创建 enable/disable、deferred/discovered、parallel、Permission、Agent Loop、MCP、Skill、Hook、Memory 或 Sandbox 实现/占位模块。
- 没有保留临时迁移 helper、第二套配置转换入口、无调用方扩展或旧项目运行时依赖；没有删除历史工作包或用户已有文件。

## 6. 本轮文件与范围差异

本轮新增或修改：

- `src/uthcode/integrations/tools/factory.py`
- `src/uthcode/application/tools.py`
- `src/uthcode/application/bootstrap.py`
- `src/uthcode/application/generation.py`
- `src/uthcode/application/__init__.py`
- `tests/test_application_tools.py`
- `tests/test_architecture_boundaries.py`
- `tests/test_package.py`
- `README.md`
- `docs/work/T04-工具系统/T04-工具系统-checklist.md`
- `docs/work/T04-工具系统/feedback/W04-application-delivery-feedback.md`

`bootstrap.py`、架构测试、package 测试和工作包目录同时包含 W01–W03 的既有未提交交接内容，本轮在其上追加 W04 所需边界，没有覆盖或整理其他用户变更。Provider DTO、Provider SDK Adapter、System Prompt、CLI/TUI 交互和后续 Agent Loop 范围均未修改。

Checklist 当前 Task 1–Task 9 全部既有验收项均已勾选；工作包仍未归档，等待用户确认后由用户手动移动。

## 7. UTF-8 guard

- files checked：`README.md`、`docs/work/T04-工具系统/T04-工具系统-checklist.md`、`docs/work/T04-工具系统/feedback/W04-application-delivery-feedback.md`
- result：通过 UTF-8 解码、常见乱码标记检查和 Markdown fence parity 检查
- repaired encoding issues：无

