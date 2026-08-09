# W01 Core Contracts Feedback

## 1. 实际完成

- 完成 Task 1：新增不可变 Planning Domain、TodoWrite replace-all schema/解析、普通 Tool 的 Core-only 规划访问元数据、Plan Review 与 Steering 控制协议，以及六类 display-safe AgentEvent。
- 完成 Task 2：新增仅含 `before_tool_execution`、`before_completion` 的同步不可变 `RuntimeHookSet`，提供 PLAN 只读策略、Plan completion、Task completion 三个纯 Hook，并新增结构化 `RuntimePromptContext`。
- 未修改 `core/agent.py`、Application、Slash Command、TUI 或 `tests/test_agent_loop.py`；W01 只交付纯合同和策略函数，不预写 W02/W03 接线。

## 2. 冻结公共合同

### 2.1 Planning 与 Control Tool

- `BehaviorMode` 只有 `DEFAULT/default`、`PLAN/plan`。
- `TaskStatus` 只有 `PENDING/pending`、`IN_PROGRESS/in_progress`、`COMPLETED/completed`。
- `TaskItem(content, status)`、`TaskState(items)`、`PlanState(revision, text, approved)`、`RuntimeFeedback(kind, text)` 均为 frozen/slots 值并提供严格 JSON round-trip。
- `TaskState` 保持顺序、至多一个 `in_progress`；`has_unfinished`、`unfinished_count`、`is_empty` 是只读投影。
- `parse_todo_write_arguments({"todos": [...]})` 执行 replace-all 解析；`{"todos": []}` 返回空 `TaskState`。`TODO_WRITE_TOOL_DEFINITION` 只提供 Provider schema，后续必须由 Agent Core special control path 应用，不能注册到普通 `ToolRegistry`。

### 2.2 Tool planning access

- `ToolPlanningAccess` 只有 `HIDDEN`、`READ_ONLY`；普通 Tool 通过可选 `ToolPlanningMetadata.planning_access` 声明，未声明时 fail-closed 为 `HIDDEN`。
- `ToolRegistry` 在注册时快照元数据；`plan_definitions()` 返回稳定的 PLAN subset，`planning_access_for(name)` 返回快照值。元数据不进入 `ToolDefinition`、parameters 或 Provider wire JSON。
- Builtin 冻结矩阵：`ReadFile/Glob/Grep/Bash = READ_ONLY`，`WriteFile/EditFile = HIDDEN`。`Bash` 的可见性不代表调用获准；W02 必须在 trusted preflight 后以实际 `PermissionAction.effect is READ` 再判定。
- `AskUserQuestion` 继续是两种 Behavior Mode 都可见的 Core special definition；`TodoWrite` 只在 DEFAULT 可见；二者都不进入普通 Registry。

### 2.3 Plan Review 与 Steering

- typed pause 新成员：`PauseKind.PLAN_REVIEW_REQUIRED`、`PauseReason.PLAN_REVIEW_REQUIRED`。
- `PlanReviewRequest(revision, plan_text)`；`PlanReviewResponse(pause_id, run_id, turn_id, revision, choice, feedback)`。`REVISE` 必须有非空 feedback，`APPROVE` 禁止 feedback；`PauseRequest.validate_response()` 严格校验 pause/run/turn/revision。
- `SteeringRequest(steering_id, run_id, turn_id, text)` 是独立 immutable control request，不属于 `PauseKind` 或 `PauseResponse`。

### 2.4 AgentEvent

- `BehaviorModeChanged(previous_mode, behavior_mode)`。
- `TaskStateChanged(iteration, task_state)`，携带完整 replace-all `TaskState`。
- `PlanProposed(iteration, revision, plan_text)`，携带完整 Plan 正文。
- `CompletionBlocked(iteration, unfinished_count)`，不携带 candidate final。
- `UserSteeringRequested(steering_id)`、`UserSteeringApplied(steering_id)`，不携带原始 steering 文本或任意 payload。
- 六类事件均 frozen、strict JSON round-trip，并已加入 `AgentEventValue` 与公开 decoder。

### 2.5 Runtime Hook

- `BeforeToolExecutionContext(run_id, turn_id, behavior_mode, prepared_call)`；结果仅 `BeforeToolExecutionContinue` 或 `BeforeToolExecutionReject(error_text, reason)`。
- `BeforeCompletionContext(run_id, turn_id, behavior_mode, candidate_text, task_state, plan_state)`；结果仅 `BeforeCompletionContinue`、`BeforeCompletionBlock(feedback, reason)`、`BeforeCompletionRequestPause(kind, request, reason)`。
- `create_default_runtime_hooks()` 的顺序固定为：pre-tool 仅 `plan_tool_policy`；completion 为 `plan_completion_hook` → `task_completion_hook`。
- Hook 同步执行、按 tuple 顺序短路，不捕获意外异常；调用方必须将异常 fail-closed 为 Turn failure。Hook 不生成 ID、不写状态、不调 Provider/Tool、不持有异步协调对象。

### 2.6 Runtime Prompt Facts

- `RuntimePromptContext(behavior_mode, task_state, plan_state, one_shot_feedback)` 是 Prompt 唯一新增结构化输入，不接受整个 RunState、Registry、Application 或 UI。
- `build_runtime_prompt_section()` 生成独立的 `当前行为与执行状态` section；PLAN 与 DEFAULT 行为文本不同，并安全转义 Task、Plan、feedback 动态内容。
- `build_system_prompt(..., runtime_context=...)` 组合该 section；省略时使用 DEFAULT/空状态，供 W02 接线前的既有调用方继续得到合法当前语义。

## 3. 修改文件

- Core：`src/uthcode/core/planning.py`、`hooks.py`、`tool.py`、`interaction.py`、`agent_events.py`、`prompt.py`、`__init__.py`。
- Builtin Tool metadata：`src/uthcode/integrations/tools/file_tools.py`、`search_tools.py`、`process_tools.py`、`factory.py`。
- 测试：新增 `tests/test_planning.py`、`tests/test_runtime_hooks.py`；修改 Task 1/2 对应合同、builtin、Prompt 与 architecture 测试。
- 文档：仅勾选 Checklist Task 1/2 已验证项并创建本 Feedback。

## 4. 测试与检查证据

- 开工前相关基线：`189 passed in 17.49s`。
- 测试先行红测：新增模块/符号尚不存在时出现预期的 6 个 collection errors，随后实现生产合同。
- Task 1：`test_planning.py` 为 `23 passed`；Interaction/Event 为 `72 passed`；Tool/builtin 为 `102 passed`。
- Task 2：Hook/Prompt 为 `22 passed`；Architecture 为 `23 passed`。
- W01 受影响定向集合：`242 passed in 16.97s`。
- 最终全量回归：`777 passed, 3 skipped in 56.05s`；skip 数与基线环境门禁一致。
- Package smoke：`8 passed in 1.59s`；`compileall -q src tests` 退出码为 0；`pip check` 输出 `No broken requirements found.`。
- 公开导出核对：基线 108 个 `core.__all__` 导出零遗失，当前 148 个导出均可解析、无重复，40 个新增名称与 W01 合同一致。
- 两条否定性 `rg` 均为 0 条匹配；`git diff --check` 无 whitespace error。
- 当前 conda 环境的 editable install 指向主 worktree；所有 Python/pytest 验证均在命令前把 `D:\project\Re-UthCode-T08-W01\src` 置于 `PYTHONPATH`，并用 `uthcode.__file__`/测试收集路径确认实际命中 W01 物理树。

## 5. 与任务书差异、风险和后续接线约束

- 无需求差异、无越界实现、无冻结任务包错误。
- W01 只提供合同；BehaviorMode、Plan/Task state、Hook、Steering 和事件尚未接入 `AgentLoop`/Application，属于 W02 的明确工作范围，不能把 W01 的合同测试误判为端到端能力已完成。
- W02 必须复用上述公开类型与 `create_default_runtime_hooks()`，不得另建同义枚举、Todo Manager、字符串 Hook dispatch、动态 registry 或第二执行器；pre-tool 顺序必须是 trusted preflight → Hook → Permission → execute。
- W02 必须由 AgentLoop 生成 event、Plan revision、Pause/Steering ID 并写权威状态；Hook 结果只是纯控制建议。
- W03 应只依赖公开 Interaction/Event 字段做投影；不得把 Steering 事件当作用户正文来源，真实文本由 Application/Core 正式用户消息链提供。

## 6. 遗留负担检查

- 未增加兼容别名、废弃入口、旧结构适配器、第二 Runtime、Plan→Todo 编译器、complexity detector、Hook package/plugin/global registry 或未使用 Hook point。
- Planning metadata 只存在于 Core Tool contract，Provider `ToolDefinition` 未变化；Steering 未进入 PauseKind；Hook 文件无 asyncio、Provider/Tool 执行和 RunState 持有。
- 未归档工作包、未修改远端、未 push/merge/rebase/cherry-pick/reset，也未操作其他 worktree。
