# W03 Permission Interaction Prompt

## 任务

严格串行执行：

1. Task 6 — Permission Pause / Resume 与 Session Grant
2. Task 7 — `/permission` Application Session Control 与 TUI

不得提前实施 Task 8～10。完成后停下，等待人工审查。

## 前置门槛

完整读取 W01、W02 Feedback，确认 Task 1～5 已完成且对应测试通过。若 Action/Rule/Strategy 公共边界未稳定，停止并报告。

## 必须完整读取

- `AGENTS.md`、`SRe-AGENTS.md`、`docs/work/README.md`
- T07 原始需求、Spec、Tasks、Checklist
- W01、W02 Prompt 与 Feedback
- T05 Agent Loop 与 T06 暂停恢复工作包的 Spec、Tasks、相关 Feedback
- 当前 `core/interaction.py`、`agent.py`、`agent_events.py`、`application/runs.py`
- 当前 Application command Registry/Dispatcher/Completion、TUI interaction/app 与 CLI，以及对应测试

## 已确认设计决策

- Permission Ask 扩展 T06 `PauseRequest → TurnHandle.pending_pause/resume()`，禁止第二 waiter、queue、future 或 UI 直连。
- ordinary Ask choices 为 once/session/reject；Guard Ask choices 为 once/reject。
- Session Grant 仅当前 AgentRun 有效，新 Run default；Grant 不能覆盖 Guard、Policy Deny 或不同动作/资源。
- 授权发生在 ToolStarted 后、execute 前；deny/reject 形成标准 error ToolResult，同 batch 继续。
- resume 使用 prepared 调用与授权开始时的 mode 快照，不重复副作用；cancel/approval race 取消优先。
- `/permission` 使用唯一 Registry，模式不持久化；full_access 只能由用户主动选择并显示风险提示。
- CLI 不自动批准、不读 stdin 等待；TUI 只调用 Application 公共 API；Headless 继续使用公共 pause/resume。

## 修改范围

只修改 Task 6、Task 7 明列的 Core、Application、command、TUI、CLI 文件及对应测试。只有现有组件真实职责要求时才调整现有 picker/state/rendering/completion；不得新建第二套 dispatcher、permission store 或 Interface→Core/Integration 依赖。

## 实施约束

- 使用 `conda run --no-capture-output -n re-uthcode ...`。
- 扩展现有严格 JSON 联合类型和 ID 校验，不伪装成 AskUserQuestion Tool。
- Pause/Event 只包含脱敏 action/resource/reason，不携带 secret 内容或完整带凭据命令。
- Agent Loop 仍是 RunState 唯一写入者，保持 FIFO、每 ToolCall 一个结果与唯一事件顺序。
- 不修改规则格式、Provider adapter，不新增输入线程、后台等待器或持久 mode/grant。
- 不执行 Git 写，不归档工作包。

## 测试与验收

- 完成 Task 6 后执行 interaction、agent loop、application runs、permission integration 测试和 T05/T06 回归。
- 完成 Task 7 后执行 command/registry/completion、TUI、CLI、Headless 测试。
- 明确覆盖 stale/wrong ID、same Turn resume、session grant 下一 Turn、新 Run、deny 后继续、cancel race、pending mode 快照。
- 执行 `compileall`、`pip check`、`git diff --check` 和 Feedback UTF-8 guard。
- 逐项核对 Checklist Task 6、Task 7，只勾选实际通过项。

## Feedback

创建并持续维护：

`docs/work/T07-三层权限系统/feedback/W03-permission-interaction-feedback.md`

记录暂停恢复状态变化、Run session 生命周期、界面边界、修改文件、测试证据、Checklist、偏差、竞态风险和遗留清理。返工只追加。
