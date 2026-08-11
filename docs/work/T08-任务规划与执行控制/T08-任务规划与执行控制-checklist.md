# T08 任务规划与执行控制 Checklist

## Task 1 — Planning Domain、Tool 可见性与控制协议

- [x] 在 `D:\project\Re-UthCode-T08-W01` 执行 `git branch --show-current`，输出为 `T08-W01-core-contracts`。
- [x] 执行 `conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_planning.py`，合法、非法、清空、replace-all、顺序和至多一个 `in_progress` 用例全部通过。
- [x] 执行 `conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_agent_interaction.py tests/test_agent_events.py`，Plan Review、Steering 与六类新增事件的严格 JSON round-trip 全部通过。
- [x] 执行 `conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_tool_core.py tests/test_builtin_file_tools.py tests/test_builtin_search_tools.py tests/test_builtin_process_tool.py`，全部内置普通 Tool 都有明确规划可见性且 Provider schema 不包含该内部元数据。
- [x] 执行 `rg -n "PauseKind.*STEER|Steering.*PauseKind|ToolDefinition.*plan" src/uthcode/core src/uthcode/integrations`，确认没有把 Steering 建成 PauseKind，也没有把规划元数据写入 Provider wire definition。

## Task 2 — Runtime Hook 与 Runtime Prompt Facts

- [x] 执行 `conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_runtime_hooks.py tests/test_system_prompt.py`，两类 Hook 结果、固定顺序、异常输入和 PLAN/DEFAULT Prompt facts 全部通过。
- [x] 执行 `conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_architecture_boundaries.py`，只放行 `core/hooks.py`，并继续拒绝 Hook package、动态 registry、Integration/Interface 依赖。
- [x] 执行 `rg -n "async def|create_task|ToolExecutor|ProviderPort|RunState" src/uthcode/core/hooks.py`，确认 Hook 不异步调度、不执行 Tool/Provider、不直接持有或写 RunState。
- [x] 检查 W01 Feedback，确认列出 Behavior/Task/Plan、Tool access、Hook、Prompt、Plan Review、Steering 和事件的冻结公共合同及定向测试结果。

## Task 3 — Behavior Mode 与 Dynamic Tool View

- [x] 在 `D:\project\Re-UthCode-T08-W02` 执行 `git merge-base --is-ancestor T08-W01-core-contracts HEAD`，退出码为 0；当前分支为 `T08-W02-runtime-application`。
- [x] 执行 T08 mode/tool-view 定向测试，断言 PLAN request 的 Tool 名称严格为 `ReadFile, Glob, Grep, Bash, AskUserQuestion`，DEFAULT 额外包含 `WriteFile, EditFile, TodoWrite`。
- [x] 执行 pre-tool 顺序测试，证明 trusted preflight 后先调用 Hook、再调用 Permission、最后执行；PLAN 非 READ 不进入 Permission/execute。
- [x] 执行 full_access、隐藏 Write/Edit、PLAN TodoWrite、未知工具与非法参数测试，确认每个原始 call ID 恰好一个受控 ToolResult。
- [x] 执行 `conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_agent_loop.py tests/test_application.py tests/test_application_runtime.py tests/test_application_tools.py`，全部通过。

## Task 4 — Plan Proposal / Review / Approve

- [x] 执行 Plan v1 → REVISE → Plan v2 → APPROVE 测试，前后 `run_id`、`turn_id` 与同一 `TurnHandle` 均不变。
- [x] 捕获事件与 RunState，确认两个 Plan candidate 都没有 ordinary assistant commit、`AssistantMessageCompleted(FINAL)` 或 `TurnCompleted`，但 usage 已计入。
- [x] 执行 stale/wrong pause ID、run ID、turn ID、revision、空 revision feedback 测试，全部稳定拒绝且状态不变。
- [x] 执行 approve 测试，确认立即出现 PLAN→DEFAULT 状态变化，下一 request 使用完整 Tool View，且无需 `/do`。
- [x] 执行 proposal/review/approve 与 cancel race 测试，确认只产生一次 `TurnCancelled`，无后续 Tool 副作用或 `TurnCompleted`。

## Task 5 — Todo / Execution Planning / Completion Control

- [x] 执行 TodoWrite control-path 测试，确认它不进入普通 Registry、Permission 或手工 Tool API，且合法/非法调用都闭合原 call ID。
- [x] 执行 TaskState 暂停恢复、Plan approve 后建立、replace-all 重规划、显式清空和新 Turn reset 测试，状态与实际执行事实一致。
- [x] 执行 unfinished Todo candidate final 测试，确认 usage 增加、`CompletionBlocked` 出现，candidate text 不进入 messages、普通 assistant 事件或 TUI final。
- [x] 执行全部 completed 与 `todos=[]` 两种完成测试，分别只产生一次 `TurnCompleted`。
- [x] 执行连续 completion block 与 `max_iterations`、Hook exception 测试，确认受现有硬上限控制且异常 fail Turn。

## Task 6 — User Steering

- [x] 执行 Provider generation 中 Steering 测试，确认 partial attempt 未提交，Steering 是同一 Turn 的真实 user Message，下一 request 同时看到原目标和更新目标。
- [x] 执行 Tool batch 中 Steering 测试，确认当前 Tool 完成，剩余 stale Tool 未启动、每个 call ID 有受控结果且 batch 正常闭合。
- [x] 执行 TaskState 测试，确认 Steering 不自动改写 Todo，模型可在下一 iteration 保持、更新或整体重写。
- [x] 执行 PLAN generation Steering、重复 pending Steering、terminal 后 Steering 和 typed pause pending Steering 测试，结果符合各自边界。
- [x] 执行 Cancel > Steering > candidate completion 竞态测试，确认取消 exactly once、无残留 pending request、无副作用和完成事件。

## Task 7 — Application Run Mode 与 Steering Control

- [x] 执行 `AgentRun` mode 测试，确认新 Run 为 DEFAULT，idle 切模幂等，active Turn 外部切模稳定拒绝，PermissionMode 不变化。
- [x] 执行 Plan approve mode sync 和 Turn 结束测试，确认 TUI 可立即读到 DEFAULT，下一 Turn 继承最终 mode但重置 Task/Plan/feedback。
- [x] 执行 `TurnHandle.steer` 非空、active-only、single-pending、typed-pause 互斥和 terminal rejection 测试。
- [x] 执行 driver 资源清理测试，确认 terminal/cancel/failure 后无残留 asyncio task、queue waiter、pause signal 或 steering coordination。
- [x] 执行 `conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_agent_loop.py tests/test_application_runs.py tests/test_application_runtime.py tests/test_application_tools.py`，全部通过。
- [x] 检查 W02 Feedback，确认记录 request capture、Hook 位置、Plan/Task/Steering 状态流、竞态测试及未决风险。

## Task 8 — Slash Command 产品入口

- [x] 在 `D:\project\Re-UthCode-T08-W03` 执行 `git merge-base --is-ancestor T08-W01-core-contracts HEAD`，退出码为 0；当前分支为 `T08-W03-slash-tui`。
- [x] 执行 command dispatcher/registry/completion 测试，确认 `/plan` 选择 PLAN、`/do` 选择 DEFAULT、`/build` 解析为 `/do` alias，三者均已实现且无参数。
- [x] 执行 `/plan extra`、`/do extra`、`/build extra` 测试，全部返回 usage error，不产生 Prompt。
- [x] 执行 `rg -n -e "aliases=.*p" -e "canonical=.*build" -e "CommandKind\.PROMPT" src/uthcode/application/commands/builtins.py`，人工核对无旧 `/p`、无第三个 canonical Build mode、`/do` 不再是 Prompt 命令。
- [x] 执行 `/help` 与 completion 快照测试，确认最终命令、alias、说明和实现状态只来自同一 Registry。

## Task 9 — TUI Plan / Todo / Steering 产品闭环

- [x] 执行 TUI 输入测试，确认 idle 普通文本 start Turn，active 且无 typed interaction 时 steer，Plan Review/AskUser/Permission/Retry pending 时普通输入不能旁路。
- [x] 执行 mode UI 测试，确认 DEFAULT 与 PLAN separator 不同，status 同时显示 behavior mode 与 permission mode，approve 后立即恢复默认色。
- [x] 执行 Plan rendering 测试，确认 `UthCode · Plan v1`、完整替代 `Plan v2` 分别 append，均使用 plan background 且不覆盖旧 scrollback。
- [x] 执行 Plan Review picker/revision、TaskState checklist、Steering user message exactly-once 与 CompletionBlocked 不显示 candidate final 的测试。
- [x] 执行 `conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_command_dispatcher.py tests/test_command_registry.py tests/test_command_completion.py tests/test_tui.py`，全部通过。
- [x] 执行 UTF-8 guard 检查 `docs/TUI/README.md`，结果为 `OK`；检查 W03 Feedback 已记录命令/TUI 结果和跨层待集成边界。

## Task 10 [接入主流程] — 正式 Composition 与分支整合

- [x] 在 `D:\project\Re-UthCode` 执行 `git branch --show-current`，输出为 `T08-任务规划与执行控制`；W01、W02、W03 各自工作树均已提交且 Feedback 存在。
- [x] 按 W01 → W02 → W03 顺序创建本地 merge commit；逐个执行 `git merge-base --is-ancestor <worker-branch> HEAD`，退出码均为 0。
- [x] 执行正式 composition 测试，确认 `create_application → create_run → start_turn` 使用唯一 HookSet、Tool universe、AgentLoop、Permission 链和 Application driver。
- [x] 执行调用顺序测试，确认 pre-tool Hook 位于 preflight 与 Permission 之间，completion Hook 位于 usage accounting 与 authoritative assistant commit 之间。
- [x] 执行 Headless 测试，确认无 TUI 也能 Plan Review、Steering、Todo、Completion Block；Interface 未导入 Core internal Hook 或 Integration。
- [x] 执行 `conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_architecture_boundaries.py tests/test_package.py`，全部通过。

## Task 11 [端到端验证] — Plan + Execution Planning + Steering

- [x] 执行 `conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_t08_e2e.py`，正式 Application + Fake Provider + 真实 builtin Tool + 临时 workspace 的核心 E2E 全部通过。
- [x] E2E request capture 证明首个 PLAN view、approve 后 full view、TodoWrite、真实 user Steering message 和一次性反馈按顺序出现。
- [x] E2E 文件证据证明 PLAN 阶段无写入，DEFAULT 阶段真实 Read/Write/Edit/验证发生，stale Tool 未执行。
- [x] E2E 事件证据证明 Plan v1/revise/v2/approve 同 Turn、CompletionBlocked 后继续、最终 exactly one `TurnCompleted`、无额外 terminal。
- [x] 执行 PLAN + full_access、敏感只读 Permission Ask、Plan Review pending Steering rejection、stale response 和 Cancel race 额外场景，全部通过。
- [x] 启动下一 Turn，断言 TaskState、PlanState 和 one-shot feedback 已重置，Run 的最终 BehaviorMode 与 conversation 保留规则符合 Spec。

## Task 12 [遗留负担清理] — 单 Runtime 收口与 Worktree 回收

- [x] 执行否定性扫描，确认无旧 `/p`、旧 Prompt `/do`、第三 Build mode、第二 AgentLoop/planning loop、Todo Manager、Plan→Todo compiler、complexity detector、动态 Hook registry 和 Interface-owned Plan/Task state。
- [x] 执行 `conda run --no-capture-output -n re-uthcode python -m pytest -q`，全量测试全部通过，除既有环境门禁外无新增 skip/xfail。
- [x] 执行 `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests`，退出码为 0。
- [x] 执行 `conda run --no-capture-output -n re-uthcode python -m pip check`，输出 `No broken requirements found.`。
- [x] 执行 `git diff --check`，退出码为 0 且无 whitespace error。
- [x] 对 T08 工作包、`docs/Context-Index.md` 与 `docs/TUI/README.md` 执行 UTF-8 guard，全部输出 `OK`，无 replacement character、mojibake 或 fence 不平衡。
- [x] Checklist 12 个 Task 全部完成，W01～W04 四份 Feedback 齐全；`docs/Context-Index.md` 将 T08 标记为 `implemented_unarchived`，工作包未被 Agent 归档。
- [x] 对 W01、W02、W03 tip 逐一执行祖先验证为 0 后，以精确绝对路径移除三个 worktree，再用 `git branch -d` 删除三个本地短期分支。
- [x] 最终 `git worktree list` 只显示 `D:\project\Re-UthCode`；本地保留 `main`、`T05-ReAct与AgentLoop`、`T08-任务规划与执行控制`，远端引用未改变。
- [x] 最终工作树干净，W04 Feedback 记录合并顺序、冲突处理、测试结果、删除项、worktree 回收和未决风险。
