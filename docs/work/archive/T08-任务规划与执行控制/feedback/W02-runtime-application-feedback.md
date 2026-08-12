# W02 Runtime / Application Feedback

## 1. 实际完成

- 完成 Task 3～7：在现有单一 `AgentLoop`、`RunState`、Tool batch 与 Application driver 上接入 Behavior Mode、动态 Tool View、Plan Review、Todo/TaskState、Completion Control 与 User Steering。
- 开工前从 W02 基线 `dbb50c734387d422f8a2e623da2be303b79a35eb` 以唯一授权命令 `git merge --ff-only T08-W01-core-contracts` 快进到已验收 W01 tip `cec8220fb35dbfdccb73eea3fcd111fccaece59d`；祖先检查退出码为 0。
- 未修改 W01 冻结合同文件，未修改 Slash Command、TUI、CLI 或公共聚合导出；未创建第二 Runtime、第二 Tool executor、Todo Manager 或 Plan→Todo 编译器。

## 2. Request Tool View 与 Hook 接线

- Turn 开始时把 idle `BehaviorMode` 快照进 `RunState`；每次 Provider request 都从同一 Turn 捕获的 Tool universe 动态计算 view，不重建 Run、Turn、handle、Registry 或 Loop。
- 正式 Application request capture：PLAN 严格为 `ReadFile, Glob, Grep, Bash, AskUserQuestion`；DEFAULT 严格为 `ReadFile, WriteFile, EditFile, Glob, Grep, Bash, AskUserQuestion, TodoWrite`。
- `RequestPreparer` 接收当前 visible definitions 与 `RuntimePromptContext`；Application 用当前 mode、TaskState、PlanState 与一次性 feedback 构建 System Prompt。一次性 feedback 只进入下一次成功构造的 request，不伪造成 conversation message。
- 普通 Tool 唯一顺序为：`ToolExecutor.prepare_call`（schema + trusted preflight）→ `RuntimeHookSet.run_before_tool_execution` → Run-local Permission resolver → `execute_prepared`。PLAN 中实际 Action 非 READ 时在 Permission/execute 前受控拒绝，`full_access` 不能绕过。
- Candidate final 先完成 Provider 校验与 usage 计账，再执行 `run_before_completion`；只有 `BeforeCompletionContinue` 才提交 ordinary assistant message、`AssistantMessageCompleted(FINAL)` 与 `TurnCompleted`。PLAN 与 unfinished-task candidate 的 text delta 在 Hook 判定前缓冲。

## 3. Plan / Task / Steering 权威状态流

### 3.1 Plan

- PLAN candidate 写入或完整替换 `PlanState(revision, text, approved=False)`，发布 `PlanProposed`，进入 `PLAN_REVIEW_REQUIRED` typed pause；candidate 不进入 ordinary assistant message/event。
- REVISE 由现有 `PauseRequest.validate_response()` 校验 pause/run/turn/revision，把非空 feedback 作为同 Turn 真实 `role=user` Message，并设置一次性 `plan_revision` feedback；下一 candidate 是完整 Plan 新 revision。
- APPROVE 在同一 run、turn、`TurnHandle` 内把当前 Plan 标记 approved，切换 PLAN→DEFAULT 并发布 `BehaviorModeChanged`；下一 iteration 自动获得完整 Tool View，无需 `/do` 或新 Turn。

### 3.2 Task / Completion

- `TodoWrite` 是 Core special control path，不进入普通 Registry、Permission 或手工 Application Tool API。合法参数 replace-all 写 `TaskState` 并发布完整 `TaskStateChanged`；非法参数返回同 call ID 的受控错误；`todos=[]` 显式清空。
- DEFAULT candidate final 遇到 unfinished Task 时保留真实 usage，发布 `CompletionBlocked`，设置一次性 `completion_blocked` feedback，并进入下一 iteration；candidate 正文不进入 messages、普通 assistant event 或 terminal final。
- TaskState 在同 Turn typed pause/resume 中保留；Steering 不自动修改；模型可通过下一次 TodoWrite 保持、推进或整体重写。新 Turn 重置 TaskState、PlanState 与 feedback。

### 3.3 Steering

- `TurnHandle.steer(text) -> bool` 创建 immutable `SteeringRequest` 并交给当前 `AgentTurnExecution`；非字符串/空文本稳定拒绝，terminal、single-pending、typed pause 与重复 pending 返回 false。
- Provider generation 中 accepted Steering 合作式中断当前 attempt；未提交 candidate 不进入权威 message/completion，Steering 文本作为同 Turn 真实 user Message 写入 history，并产生一次性 `user_steering` feedback 后进入下一 iteration。
- 普通 Tool 正在执行时不强杀；当前 Tool 到安全边界后，余下未启动 call ID 各自产生 `Error: tool call skipped after user steering` 的受控 ToolResult，`ToolBatchFinished(status="steered")` 闭合 batch，再应用 Steering。
- Steering 在 PLAN generation 中可用且保持 PLAN；AskUser、Permission、Provider retry、Plan Review 等 typed pause pending 时拒绝普通 Steering。优先级为 Cancel > Steering > candidate completion。

## 4. W03 / W04 可用 API 与事件

- W03 可只通过 `AgentRun.behavior_mode` 读取 active/idle 权威 mode，通过 idle-only `AgentRun.set_behavior_mode(mode)` 选择下一 Turn；该 API 与 `PermissionMode` 独立。
- W03 可通过当前 `TurnHandle.steer(text)` 提交 active-Turn 自然语言更新；typed interaction pending 时返回 false，Interface 不应直接写 messages、TaskState 或 PlanState。
- Plan/Task/Steering UI 投影使用 W01 冻结事件：`BehaviorModeChanged`、`PlanProposed`、`TaskStateChanged`、`CompletionBlocked`、`UserSteeringRequested`、`UserSteeringApplied`。真实 Steering 正文来自正式 user message/history，不从 display-safe Steering event 反推。
- `RunSnapshot` 新增安全的 `behavior_mode`，仍不暴露 Plan/Task 正文。Plan Review 继续使用 `TurnHandle.pending_pause` 与 `TurnHandle.resume(PlanReviewResponse)`。
- W04 合并后无需额外 Runtime composition；`ApplicationToolService` 已持有唯一 `ToolRegistry`、`ToolExecutor` 与默认 `RuntimeHookSet`，每个 Turn 只创建一个现有 `AgentLoop`。

## 5. 修改文件

- Runtime/Core：`src/uthcode/core/agent.py`。
- Application：`src/uthcode/application/generation.py`、`runs.py`、`tools.py`。
- 测试：`tests/test_agent_loop.py`、`test_application_runs.py`、`test_application_tools.py`、`test_permission_delivery.py`。
- 文档：仅勾选 Checklist Task 3～7 并首次创建本 Feedback。

## 6. 测试与检查证据

- W01 同步前 W02 基线定向测试：`87 passed in 9.17s`。
- Task 3 测试先行：新增 mode/view/pre-tool/Application 场景为 `5 failed, 54 deselected`，实现后 `5 passed, 54 deselected`。
- Task 4 测试先行：Plan/Core/Application/cancel 场景为 `3 failed, 59 deselected`，实现后 `3 passed, 59 deselected`。
- Task 5 测试先行：Todo/completion 场景为 `3 failed, 62 deselected`，实现并校正既有 display-safe event 断言后 `3 passed, 62 deselected`；另补 Hook exception、max-iteration、显式清空与 new-Turn reset。
- Task 6/7 测试先行：Provider Steering、Tool batch、Cancel、typed pause 与 public API 场景为 `5 failed, 64 deselected`，实现后 `5 passed, 64 deselected`；另补 PLAN Steering、mode persistence、approved Plan + Todo pause/resume 与 Steering 保留 TaskState。
- Checklist Task 3 定向集合：`74 passed in 5.06s`。
- Checklist Task 7 定向集合：`96 passed in 6.30s`。
- 最终全量回归：`809 passed, 3 skipped in 45.59s`；skip 数与既有环境门禁一致。
- `compileall -q src tests` 退出码为 0；`pip check` 输出 `No broken requirements found.`；`git diff --check` 退出码为 0。
- 所有 Python/pytest 命令均显式设置 `PYTHONPATH=D:\project\Re-UthCode-T08-W02\src;D:\project\Re-UthCode-T08-W02`；`uthcode.__file__` 确认为 `D:\project\Re-UthCode-T08-W02\src\uthcode\__init__.py`，未误用主 worktree editable install。

## 7. 竞态、资源清理与风险

- 覆盖 Provider cooperative interruption、Provider 不提交 partial assistant、当前 Tool 完成后 stale call closure、重复/stale Steering、terminal rejection、PLAN Steering、typed pause 互斥、Plan Review cancel 与 Tool Steering cancel；取消只产生一个 `TurnCancelled`，无 `TurnCompleted` 或后续副作用。
- `_TurnDriver` 继续独占 asyncio task、event queue、typed response waiter 与 pause signal；terminal/cancel/failure 后 waiter、signal、pending pause、pending Steering 全部清理。Steering 不创建第二 task/queue/Turn。
- 保留的实现风险：普通 DEFAULT streaming delta 在 Steering 到达前可能已作为非权威 delta event 发出，但不会提交 `AssistantMessageCompleted` 或写入 messages；现有事件合同没有 rollback/retract event，W03 应继续以 completed/terminal 事实区分权威提交。PLAN 与 unfinished completion candidate 已在 Core 缓冲，不存在该不可回滚正文窗口。
- 无已知阻断项；W04 仍需在 W01→W02→W03 合并后运行正式 composition、T08 E2E、architecture、package 与全量回归，确认 W03 未持有第二份 Plan/Task 状态。

## 8. 遗留负担检查

- 未修改 `planning.py`、`hooks.py`、`interaction.py`、`agent_events.py`、`prompt.py`、`tool.py` 等 W01 冻结合同文件。
- 未增加旧 API 适配器、别名、双轨行为、第二 planning/runtime loop、Todo Manager、complexity detector、Plan→Todo compiler、动态 Hook registry 或 Interface-owned 状态。
- 未 push、普通 merge、rebase、reset、cherry-pick、远端修改、分支删除或 worktree 操作；仅执行授权的 W01 fast-forward 与后续窄范围本地提交。

## 返工第 1 轮

### 返工原因

首轮独立审查发现四处执行控制边界不够严格：pre-tool Hook 异常没有闭合原始 Tool batch；Provider generation 中 Steering 与紧随其后的 pause 会出现 `pause() == True` 但暂停信号被更新后继续运行；idle mode 通过替换 `RunState` 保存；Plan APPROVE 的 `TurnResumed` 早于 Core 应用批准状态。

### 实际修改

- pre-tool Hook 异常现在 fail-closed：当前及剩余原始 ToolCall ID 均写入 `Error: pre-tool hook failed` 的受控结果，发布配对的 `ToolStarted` / `ToolFinished(status="failed")`，以唯一 `ToolBatchFinished(status="failed")` 闭合 tool message 后，再以唯一 `TurnFailed(INTERNAL_ERROR)` 终止。异常后不进入 Permission，不执行当前或剩余 Tool。
- Steering 与 pause 采用审查允许的明确拒绝语义：Core 尚有 pending Steering 时，Application `pause()` 返回 `False`，不会声称已接受一个可能被 Steering signal renewal 吞掉的请求；Steering 应用后 pending 清空，后续 pause 仍可正常请求。
- `AgentRun` 新增 Run-local idle behavior mode 字段。`set_behavior_mode()` 只修改该字段，不替换或直接改写 `RunState`；start Turn 时把 idle mode 快照给 Core，active 期间读取 Core mode，终态再把 Core 最终 mode 同步回 idle 字段。idle `RunSnapshot` 只做安全投影，不改写业务状态。
- Plan APPROVE 由 Core 在 `TurnHandle.resume()` 返回前同步校验并应用 approved Plan 与 `PLAN → DEFAULT`，先发布 `BehaviorModeChanged`，Application driver 随后才发布唯一 `TurnResumed`。若批准后立即 cancel，取消仍赢得 terminal，且不发布 `TurnResumed`。

### 重新验证

- reviewer 反例先行为 `9 failed`；最终修复后同一集合为 `9 passed in 1.10s`。
- Runtime / Application / Permission 热点回归：`140 passed in 24.20s`。
- T04～T07 / Permission 扩展回归：`409 passed in 20.91s`。
- architecture / package：`31 passed in 6.14s`。
- 最终全量回归：`818 passed, 3 skipped in 67.19s`；`uthcode.__file__` 为 `D:\project\Re-UthCode-T08-W02\src\uthcode\__init__.py`。
- 新增回归精确覆盖 Hook exception 的 call ID、事件、tool message、Permission/execute 副作用；Provider cancelled/error/completed 三种 Steering 竞态；Tool safe boundary；idle mode 不替换 `RunState`；APPROVE 的即时 DEFAULT、事件顺序、exactly-one resume 与 cancel wins。

### 范围与风险

- 返工只修改 `src/uthcode/core/agent.py`、`src/uthcode/application/runs.py`、对应 Core/Application 测试及本 Feedback；Checklist 证据仍成立，未修改其文字或勾选状态。
- 未修改 W01 冻结合同、Slash、TUI、CLI、Spec、Tasks、Prompt 或 Checklist；未启动 W04。
- 首轮记录的 DEFAULT streaming delta 风险未改变；本轮没有新增阻断项，等待原 reviewer 复验。
