# W01 阶段一扫尾 Feedback

## 实际交付

- 新增 Provider 无关的 Core 控制 Tool `ProposePlan`：仅在 PLAN request 可见，只接受一个非空 `plan`；普通 PLAN final 直接完成 Turn。
- 合法独占调用创建 Core 权威 revision、`PlanState`、`PlanProposed` 与 typed Plan Review；REVISE/APPROVE/CANCEL 保持同一 Run/Turn/Handle，控制 call 通过原 ID 的 `ToolResult` 闭合。包含 `ProposePlan` 的混合 batch 整批拒绝，同批普通 Tool 不进入 preflight、Permission 或 execute。
- 用户配置新增 `default_permission_mode = default|auto`。项目配置声明该字段硬失败；安全模式采用 TOMLKit 同目录临时文件加 `os.replace` 原子写回，成功后更新 Application 默认值，再由命令结构化结果更新当前 Run；失败时三者不分叉。
- `full_access` 保持当前 Run 临时态。TUI picker 与直接 Slash 参数统一走 `/permission <mode>`，仅 `permission: full_access` 状态片段使用 `status.warning = PALETTE.error`，原高风险正文保留。
- 正式链路为 `load_effective_config -> create_application -> create_run -> start_turn -> AgentLoop`；未新增第二 Agent Loop、动态 Hook registry、控制 Tool registry、Session/Plan 持久化或 Interface 业务状态。

## 关键调用链

```text
PLAN ordinary final -> before-completion unfinished-task gate -> TurnCompleted
PLAN ProposePlan-only batch -> strict parse -> Core revision/PlanState -> typed review
  REVISE -> close call -> user feedback -> PLAN -> next ProposePlan
  APPROVE -> close call -> DEFAULT before TurnResumed -> same Turn implementation

/permission default|auto -> atomic user write -> Application default -> current Run action
/permission full_access -> no write/default change -> current Run only
```

## 修改范围

- Core：`planning.py`、`agent.py`、`hooks.py`、`prompt.py`、公共导出。
- Config/Application：配置 data/loader/template/writer、configuration/bootstrap/generation/runs、permission command、Application Tool 保留名。
- Interface：`interfaces/tui/app.py`。
- 测试：planning、prompt、hooks、Agent Loop、配置、Command、Application Run、TUI、T08 E2E。
- 文档：本工作包 Checklist、当前 Context/索引与能力欠账清单。

## 验证结果

- `pytest tests/test_planning.py tests/test_runtime_hooks.py tests/test_system_prompt.py -q`：`59 passed`。
- `pytest tests/test_agent_loop.py tests/test_agent_interaction.py tests/test_agent_events.py -q`：`130 passed`。
- `pytest tests/test_configuration.py tests/test_config_loader_integration.py tests/test_command_dispatcher.py -q`：`69 passed`。
- `pytest tests/test_application_runs.py tests/test_tui.py tests/test_t08_e2e.py -q`：`121 passed`。
- `pytest tests/test_architecture_boundaries.py tests/test_package.py -q`：`32 passed`。
- `pytest -q`：`924 passed, 3 skipped in 49.77s`。
- `python -m compileall -q src tests`：退出码 0。
- `python -m pip check`：`No broken requirements found.`。
- `git diff --check`：退出码 0，无 whitespace error。
- 负向扫描：`plan_completion_hook`、`default_behavior_mode`、通用 ControlTool/Hook registry 无生产命中；`AgentLoop` 与 `AgentTurnExecution` 各一个定义；TUI 生产代码无 picker 直接权限修改旁路。

## Checklist、差异与未验证项

- Task 1–7 全部现有复选框已按上述证据勾选；未修改冻结文字、结构、编号或顺序。
- 实施与冻结任务书一致；没有需要用户拍板的扩大范围或任务书冲突。
- Windows Terminal 的实际色差未做人工视觉验收，标记为 `NOT VERIFIED`；自动测试已精确断言 `permission: full_access` 唯一使用 `class:status.warning`，且该样式颜色映射为 `PALETTE.error`。
- 全量测试的 3 个 skip 为既有环境门禁，本任务未新增 skip/xfail。

## 风险、回退与遗留负担

- 风险集中在 Provider 对新控制 Tool 的选择质量；Core 对 DEFAULT、非法参数、混合 batch、重复/错误响应与取消均 fail-closed。
- 回退应整体撤销本任务源码、测试与当前事实文档；不得仅恢复旧 completion Hook，否则会重新把所有 PLAN final 强制转为 Review。
- 已删除 `T08 Plan Mode / Plan Review` 显式提交协议欠账；其余 Persistent Session、跨 Turn Plan/Todo、Context Compaction 等欠账保持不变。未新增能力欠账。
- 未执行 commit、push、merge、rebase、tag、release、分支操作或工作包归档。

## 第一轮验收返工

### 返工原因与修复结果

- 返工原因：Confirmed Defect `T08-1-R01`（P1）。REVISE 原实现先把修订反馈追加为真实 `role=user`，随后才在 `_close_tool_batch` 中写入 `ProposePlan` 的 `role=tool` 结果，违反 ToolCall 必须先闭合的公共消息顺序。
- 修复前顺序：`user(original request) -> assistant(ProposePlan ToolCall) -> user(revision feedback) -> tool(ProposePlan ToolResult) -> assistant(next response)`。
- 修复后权威顺序：`user(original request) -> assistant(ProposePlan ToolCall) -> tool(ProposePlan ToolResult: revise) -> user(revision feedback) -> assistant(next ProposePlan ToolCall)`。
- 最小修复位于现有 `AgentTurnExecution._apply_response`：REVISE 使用原 `tool_call_id` 创建一次结果，依次发出 `ToolFinished`、通过现有 `_close_tool_batch` 写入 `role=tool` Message 并发出 `ToolBatchFinished`，随后才追加真实用户修订反馈与 one-shot `PLAN_REVISION` feedback。没有新增队列、第二 Agent Loop、Provider-specific Core 分支或兼容路径。
- `BehaviorMode.PLAN`、当前 `PlanState.revision`、同一 `AgentRun`/`TurnHandle`/`turn_id`/`AgentTurnExecution` 均保持不变；下一次合法 `ProposePlan` 才把 revision 从 1 递增为 2。APPROVE、CANCEL、错误 revision、重复 response 与混合 batch 的既有语义通过定向及全量套件复验。

### 实际修改文件与测试

- Core：`src/uthcode/core/agent.py`。
- Core/Application 回归：`tests/test_agent_loop.py`、`tests/test_application_runs.py`；修正旧的错误消息顺序断言，并覆盖 call ID exactly-once、`ToolFinished < ToolBatchFinished <` 下一 iteration/Provider request、PLAN one-shot feedback、ProposePlan 可见性、revision 递增及同 Turn 状态。
- Provider 正式转换回归：`tests/test_anthropic_integration.py`、`tests/test_openai_responses_integration.py`、`tests/test_openai_compat_integration.py`。三项测试均调用对应 Provider 的正式 `stream` 消息转换入口：Anthropic 验证 `tool_result` 在修订文本之前，OpenAI Responses 验证 `function_call_output` 在后续 user input 之前，OpenAI-compatible Chat 验证 tool message 在后续 user message 之前。
- 当前事实文档：`README.md`、`docs/context/A02-Control/Control-Context.md`；本章节追加到原 Feedback，未覆盖旧记录，未修改冻结任务书、Prompt 或 Checklist。
- 先行失败证据：仅运行修订后的 Core 顺序用例时，旧实现得到索引 2 为 `user` 而预期为 `tool`，结果 `1 failed`；实施最小修复后 Core/Application/三 Provider 新增用例合计 `5 passed`。

### 重新验证结果

- `python -m pytest tests/test_agent_loop.py tests/test_application_runs.py tests/test_t08_e2e.py -q`：`101 passed in 4.22s`。
- `python -m pytest tests/test_anthropic_integration.py tests/test_openai_responses_integration.py tests/test_openai_compat_integration.py -q`：`41 passed, 3 skipped in 3.21s`；三种 Provider 顺序回归全部通过，skip 为既有环境门禁。
- `python -m pytest tests/test_planning.py tests/test_runtime_hooks.py tests/test_system_prompt.py tests/test_agent_interaction.py tests/test_agent_events.py tests/test_configuration.py tests/test_config_loader_integration.py tests/test_command_dispatcher.py tests/test_tui.py tests/test_architecture_boundaries.py tests/test_package.py -q`：`310 passed in 14.80s`。
- `python -m pytest -q`：`927 passed, 3 skipped in 48.74s`。
- `python -m compileall -q src tests`：退出码 0。
- `python -m pip check`：`No broken requirements found.`。
- `git diff --check`：退出码 0，无 whitespace error；仅有既有 Windows 行尾提示。
- 负向扫描：`plan_completion_hook`、`BeforeCompletionRequestPause`、Session/Plan persistence、动态 Hook/Control Tool registry 均为 0 命中；`AgentLoop` 与 `AgentTurnExecution` 各仅一个定义；Core 无 Anthropic/OpenAI 名称分支。

### 未验证项与阻塞问题

- 未调用真实 Anthropic/OpenAI 网络 API；Provider 顺序通过各自 SDK 客户端 mock 的正式消息转换入口验证。本返工不涉及终端视觉变化。
- 当前无阻塞问题，等待主审代理复验。未执行 Git commit、push、merge、rebase、tag、分支操作或工作包归档。
