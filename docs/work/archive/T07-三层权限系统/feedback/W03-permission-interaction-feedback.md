# W03 permission-interaction Feedback

## 1. 完成结论

已严格按 W03 Prompt 串行完成 Task 6 → Task 7，并在 Task 7 完成后停止。Task 8～10 未提前实施；未修改原始需求、Spec、Tasks 或 Prompt 文字，Checklist 只更新了 Task 6、Task 7 的既有勾选状态。本轮未执行 Git add、commit、push，也未归档工作包。

## 2. Task 6：Permission Pause / Resume 与 Session Grant

### 交互协议

- 在现有 `PauseRequest → TurnHandle.pending_pause/resume()` 协议上增加 `PERMISSION_REQUIRED` pause kind，以及严格 JSON 的 `PermissionApprovalRequest`、`PermissionApprovalResponse`。
- Approval 请求携带独立 permission id、run/turn/tool_call id、trusted tool/action/effect/resource/scope、decision reason、授权开始时的 mode、choices 和 Guard 标记；resource 只来自 trusted Action，不携带 Tool 参数中的 secret value 或完整 credential-bearing command。
- ordinary choices 固定为 `once/session/reject`；Guard choices 固定为 `once/reject`。stale pause id、run/turn id、permission id、不可用 choice 和响应类型均在协议层拒绝。
- AskUserQuestion 仍走 T06 的 `UserInputRequest` 路径，不进入普通 Permission evaluator。

### Agent Loop 与状态变化

- 普通 Tool 仍按 registered → schema validation → trusted preflight 顺序运行；`ToolStarted` 之后、真实 `execute` 之前调用 Application 注入的 Permission resolver。
- Allow 执行 `PreparedToolCall`；Deny 生成标准 error `ToolResult` 和 `ToolFinished`；Ask 保存同一份 prepared call 后返回现有 `TurnPaused`，恢复时不重新 preflight、不重复副作用。
- Reject 与 Deny 都只结束当前 ToolCall，随后继续同一 Tool batch，保持 FIFO、每个 ToolCall 一个 ToolResult 和唯一 ToolFinished。
- Application `AgentRun` 保存当前 mode、Run-local `SessionGrant` 与 evaluator 快照。Session Grant 只按 tool/action/effect/bounded resource 精确匹配；新 Run 从 `default` 开始，Guard、Policy Deny 和不相同的动作/资源仍不能被覆盖。
- mode 在 pending Permission 上下文中通过 request 快照保留；暂停后切换 Run mode 不改写已有 request。取消在审批竞态中优先，Application waiter、pending pause 和 prepared call 均清理，未执行工具无副作用。

## 3. Task 7：`/permission`、TUI 与 CLI

- 在现有唯一 command Registry 新增 `/permission`，无参数返回三模式 picker action，参数 completion 来自同一 `CommandDefinition`；`/help` 自动展示该命令。
- `AgentRun.set_permission_mode()` 只改变当前 Run 的内存状态，不写 `config.toml`、`permissions.toml` 或其他持久化文件。`full_access` 通过 picker 或用户 slash 操作显示明确高风险提示；普通权限仍不绕过 Guard。
- TUI 增加临时 Permission picker 与 approval panel。ordinary 显示三项，Guard 显示两项；界面只消费 Application 导出的 DTO 和 `TurnHandle.resume()`，没有 Core evaluator、Integration loader 或第二 dispatcher 依赖。
- CLI 识别 Permission Pause 后输出安全诊断并取消当前 Turn，不自动 allow、不读取 stdin、不无限等待；继续消费同一事件流完成安全收口。

## 4. 实际修改文件

### 生产代码

- `src/uthcode/core/interaction.py`
- `src/uthcode/core/agent.py`
- `src/uthcode/core/agent_events.py`
- `src/uthcode/core/__init__.py`
- `src/uthcode/application/runs.py`
- `src/uthcode/application/__init__.py`
- `src/uthcode/application/commands/models.py`
- `src/uthcode/application/commands/builtins.py`
- `src/uthcode/application/commands/__init__.py`
- `src/uthcode/interfaces/tui/interaction.py`
- `src/uthcode/interfaces/tui/picker.py`
- `src/uthcode/interfaces/tui/app.py`
- `src/uthcode/interfaces/cli.py`

### 测试

- 新增 `tests/test_permission_integration.py`。
- 扩充 `tests/test_agent_interaction.py`、`tests/test_command_dispatcher.py`、`tests/test_command_completion.py`、`tests/test_tui.py`。
- 更新 `tests/test_cli.py`，将非交互 Tool Permission Pause 的验收固定为取消优先和无 secret 泄露。

## 5. 测试与验收证据

- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_agent_interaction.py tests/test_agent_loop.py tests/test_application_runs.py tests/test_permission_integration.py -q`：通过。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_command_dispatcher.py tests/test_command_completion.py tests/test_command_registry.py tests/test_command_parser.py tests/test_tui.py tests/test_cli.py -q`：通过。
- `conda run --no-capture-output -n re-uthcode python -m pytest -q`：`676 passed, 3 skipped`。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests`：通过。
- `conda run --no-capture-output -n re-uthcode python -m pip check`：输出 `No broken requirements found.`。
- `git diff --check`：退出码为 0；Git 输出的换行转换提示不属于空白错误。
- Core/Application/TUI/CLI 权限链未引入第二 waiter、queue、future、dispatcher、validator 或 persistent store；接口目录未发现直连 Core/Integration 的 import。

## 6. Checklist 状态

- Task 6：6/6 已勾选并通过，覆盖协议 choices、stale/wrong ID、same Turn prepared resume、Session Grant 生命周期、deny/reject FIFO 和 cancel/approval race。
- Task 7：7/7 已勾选并通过，覆盖 Registry/help/completion、Run mode picker、new Run default、full_access 警告、pending mode snapshot、TUI 两类 approval 和 CLI 非交互收口。
- Task 1～3 保持既有状态；Task 4、Task 5 的既有未完成项未提前勾选。
- Task 8～10 未实施并保持未勾选。

## 7. 偏差、风险与后续边界

- 按 W03 的完成边界，未修改 `application/bootstrap.py`、`generation.py` 或 `integrations/permissions.py` 的正式 Composition Root 接线。当前 `AgentRun` 支持注入稳定 `PermissionEvaluator`；默认空 RuleSet 的正式 user/project `permissions.toml` 加载仍属于 Task 8，不能在本轮提前完成。
- 本轮不提供 OS sandbox、操作系统权限提升或持久化 exact decision；Permission 仍是 Application 层审批机制。
- `TurnPaused` 直接携带 Permission approval payload，未新增独立事件或第二事件通道；这样保持 T06 单一事件流和单一 waiter。Provider adapter 没有权限分支。

## 8. 遗留清理与收尾

- 未新增兼容旧权限模型的 alias、wrapper、双轨执行路径或旧 API。
- 未写入真实用户目录的 mode/grant/permissions 文件；测试使用内存 Application/Run 与隔离的 fake Provider/Tool。
- 修改后的 Markdown 经过 UTF-8 guard 检查；工作包未归档，Git 未提交或推送。本轮在此停止，等待人工审查。
