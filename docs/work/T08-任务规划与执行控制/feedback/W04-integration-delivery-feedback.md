# W04 Integration Delivery Feedback

## 1. 实施边界

- 在最终物理 worktree `D:\project\Re-UthCode`、分支 `T08-任务规划与执行控制` 完成 Task 10、Task 11、Task 12。
- 开工核验通过：仓库根目录、分支、主工作树和 W01～W03 预期 worktree 均匹配；三个上游 worktree 均干净，Feedback 均存在，W02/W03 tip 均包含 W01 tip。
- 未修改冻结的原始需求、Spec、Tasks、Prompt 文字；只追加 W04 Feedback，并按证据勾选 Task 10～12 Checklist。

## 2. 分支整合

按 W01 → W02 → W03 顺序使用 `git merge --no-ff` 创建本地 merge commit：

1. `f154639` — `Merge W01 core contracts into T08`。
2. `39e4f6b` — `Merge W02 runtime application into T08`。
3. `ec211ea` — `Merge W03 slash tui into T08`。

三个合并均无冲突；W03 的 Checklist 变更与前两次合并自动合并。三个 Worker tip 均已通过 `git merge-base --is-ancestor` 祖先校验。合并后分别运行 W01 合同、W02 Runtime/Application、W03 Slash/TUI 定向测试，未发现需要重写冻结 Core 合同、W02 状态机或 W03 交互设计的集成缺陷。

## 3. 正式调用链

正式 Headless 路径由 `create_application` 组合配置、Fake/真实 Provider、真实 builtin Tool、唯一 `ToolRegistry`/`ToolExecutor`、固定 `RuntimeHookSet`、Permission loader 和 `ApplicationRuntimeContext`；随后由：

```text
create_application
  → create_run
  → start_turn
  → one Application _TurnDriver
  → one AgentLoop
  → public AgentEvent stream + TurnResult
```

当前请求捕获证明 PLAN 只暴露 `ReadFile, Glob, Grep, Bash, AskUserQuestion`；批准后 DEFAULT 使用完整内置 Tool View。调用顺序保持 `trusted preflight → before_tool_execution → Permission → execute`，完成顺序保持 usage accounting → completion hooks → authoritative assistant commit/terminal。

## 4. 跨层 E2E 证据

新增 `tests/test_t08_e2e.py`，使用正式 `create_application`、离线 Scripted Fake Provider、临时 workspace、真实 `ReadFile`/`WriteFile`/`EditFile`/`TodoWrite` 路径，覆盖：

- Plan v1 → REVISE → Plan v2 → APPROVE；全程同一 Run/Turn/Handle，批准自动切换 DEFAULT。
- PLAN request capture、DEFAULT full view、Todo replace-all、CompletionBlocked 和 one-shot feedback。
- active Turn Steering 作为真实 user message 写入；当前 gated Tool 完成，stale `WriteFile` 只产生 skipped result，不产生文件副作用。
- DEFAULT 阶段真实写入、精确编辑和 ReadFile 验证；最终只产生一个 `TurnCompleted`。
- 下一 Turn 保留 conversation 与最终 DEFAULT mode，同时重置 TaskState、PlanState 和 one-shot feedback。
- PLAN + `full_access` 仍在 Permission 前拒绝隐藏 WriteFile；敏感 `.env` 读取仍触发 Guard Ask；typed pause pending 时 Steering 被拒绝；Cancel 优先于 pending Steering/provider generation。

## 5. 验证记录

- 合并后 W01 合同/Hook/Prompt/架构定向集合：`251 passed`。
- 合并后 W02 Core/Application/Permission/架构定向集合：`198 passed`。
- 合并后 W03 Command/TUI/架构定向集合：`151 passed`。
- W04 composition/E2E/architecture/package 集合：`35 passed`；Hook 调用顺序集合：`4 passed`；Application 规划/Steering 集合：`15 passed`。
- 完成后的全量 pytest、compileall、pip check、diff check、否定性扫描和 UTF-8 guard 结果将在本 Feedback 末尾追加，以保留最终命令输出对应的收口证据。

## 6. 遗留负担与风险

- 未新增第二 AgentLoop、第二 planning loop、Todo Manager、Plan→Todo compiler、complexity detector、动态 Hook registry、Interface-owned Plan/Task state、旧 `/p` 或第三 Build mode。
- 未新增兼容层、旧 API 别名、旁路 Tool executor 或 TUI 对 Core/Integration 的直接依赖。
- W02 已记录的普通 DEFAULT streaming delta 在 Steering 到达前可能作为非权威 delta event 发出的既有风险保持不变；本 W04 E2E 对 PLAN/unfinished completion 的不可回写窗口和最终权威事件进行了验证。W03 记录的 Windows Terminal 人工色差、键盘和 scrollback 复核仍属于人工验收，不由离线自动化替代。

## 7. Worktree 回收

最终清理将仅在三个 tip 已合入、路径精确核验通过且全部验证完成后执行：

- `D:\project\Re-UthCode-T08-W01` / `T08-W01-core-contracts`
- `D:\project\Re-UthCode-T08-W02` / `T08-W02-runtime-application`
- `D:\project\Re-UthCode-T08-W03` / `T08-W03-slash-tui`

使用逐一的精确 `git worktree remove` 和安全的 `git branch -d` 回收；不修改远端，不删除 main、T05 或最终 T08 分支。

## 8. 最终验证证据

- 最终全量 pytest：`846 passed, 3 skipped`。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests`：退出码 0。
- `conda run --no-capture-output -n re-uthcode python -m pip check`：`No broken requirements found.`。
- `git diff --check`：退出码 0，无 whitespace error。
- UTF-8 guard：T08 工作包 Markdown、`docs/Context-Index.md`、`docs/TUI/README.md` 共 14 个文件全部 `OK`，无 replacement character、mojibake 或 fence 不平衡。
- 旧入口、重复 Runtime/AgentLoop、重复规划职责、动态 Hook registry 与 Interface 反向依赖扫描：无命中。
- W04 新增 E2E：`4 passed`；W04 composition/architecture/package：`35 passed`；Hook 顺序：`4 passed`；Application 规划/Steering：`15 passed`。

上述命令均在最终 T08 分支、`conda` 环境 `re-uthcode` 中执行；未改变远端引用。

## 9. 实际回收结果

- 三个 worker tip 在回收前均为干净 worktree，且祖先校验退出码均为 0。
- 已按精确绝对路径移除 `D:\project\Re-UthCode-T08-W01`、`D:\project\Re-UthCode-T08-W02`、`D:\project\Re-UthCode-T08-W03`；三个路径均已不存在。
- 已删除 `T08-W01-core-contracts`、`T08-W02-runtime-application`、`T08-W03-slash-tui`；删除安全，因为对应 tip 已合入最终 T08。
- 最终 `git worktree list` 仅显示 `D:\project\Re-UthCode`；本地分支仅保留 `main`、`T05-ReAct与AgentLoop`、`T08-任务规划与执行控制`；`origin` URL 未改变。
- 本次 W04 未启动 T08 包级审查，保留任务上下文供独立 W04 reviewer 反馈后继续返工。

## 10. 返工第 1 轮

### 原因

W04 独立验收指出原正式 E2E 只验证了文件副作用和部分公开事件，未充分证明后续 Provider request 中的 `role=tool` 消息、`ToolResultPart` 的正文/错误标记/顺序及每个原始 call ID 的唯一闭合；同时 A01–A04 Context 与当前 Hook、Plan、Todo、Steering、`/plan`、`/do` 实现事实不一致。

### 实际修改

- `tests/test_t08_e2e.py` 新增正式 ToolResult 证据收集：只读取每个后续 Provider request 相对前一 request 新增的 `role=tool` 消息，严格断言 8 个原始 call ID 各出现一次、ToolResult 的 `is_error`/正文/顺序、`plan-read` 与 `verify-read` 成功及 `verify-read` 正文为 `1\tseed + steered`。
- E2E 新增每个 `ToolBatchFinished` 的 call ID 顺序/集合、batch status、ToolFinished 状态与唯一错误断言；`gate` 与 `stale-write` 均闭合，只有 `stale-write` 为错误且没有文件副作用。
- E2E 新增故障反例：测试专用 ReadFile wrapper 让真实 `verify-read` 返回 `is_error=True`，严格主流程证据校验随之失败，防止错误结果被误判为成功。
- 同步 `docs/Context-Index.md` 与 A01–A04 Context：固定 `RuntimeHookSet`、PlanState/TaskState、同一 Turn Steering、`/plan`/`/do` 标为当前事实；动态 Hook registry/plugin、持久 Session/Memory、Context Compiler、Subagent/Multi-Agent 等真实未实现边界继续保留。
- 未修改冻结的 T08 原始需求、Spec、Tasks、Prompt 或 Checklist；未启动 T08 包级审查。

### 重新验证结果

- W04 E2E：`5 passed`。
- architecture/package：`32 passed`。
- T04–T08 定向回归（工具、ReAct、交互、权限、规划/Hook、命令/TUI、W04 E2E）：`788 passed, 3 skipped`。
- 全量 pytest：`847 passed, 3 skipped`。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests`：退出码 0。
- `conda run --no-capture-output -n re-uthcode python -m pip check`：`No broken requirements found.`。
- `git diff --check`：退出码 0，无 whitespace error。
- UTF-8 guard：本轮改动的 6 个 Markdown 文件全部 `OK`，无 replacement character、mojibake 或 fence 不平衡。
- 负向扫描：无旧 `/p`/Prompt `/do`/第三 Build mode、重复 Runtime/规划职责、动态 Hook registry、Interface Core/Integration 反向依赖或 Interface-owned Plan/Task state；`AgentLoop` 与 `AgentTurnExecution` 定义各 1 个。

## 11. 返工第 2 轮

### 原因

独立 reviewer 发现 `_run_formal_application_e2e()` 与正式成功测试各自保留完整 workspace、十轮 Provider script、Application/Run/Turn 组装和事件 driver，形成约 300 行双轨 fixture，增加成功路径与故障反例漂移风险。

### 实际修改

- 删除正式成功测试中的重复 workspace、Provider script、Application/Run/Turn 组装和事件 driver；成功测试现在唯一调用 `_run_formal_application_e2e(tmp_path)`。
- verify-read 故障反例继续调用同一个 runner，仅通过 `fail_verify_read=True` 注入第二次 ReadFile 的 `is_error=True` 结果，并由同一严格 Tool evidence validator 证明主 E2E 验收失败。
- 保留成功路径全部严格断言：8 个 ToolResult 的顺序/唯一闭合/正文/`is_error`，5 个 ToolBatch 的 ID 集合/状态，`plan-read`/`verify-read`，gate/stale-write，文件副作用，Plan/Todo/Steering/reset 和唯一 terminal。
- 未创建第二套 helper/fixture，未降低断言强度；仅修改 `tests/test_t08_e2e.py` 与本 Feedback 追加章节。

### 重新验证结果

- W04 E2E：`5 passed`。
- architecture/package：`32 passed`。
- T04–T08 定向回归：`788 passed, 3 skipped`。
- 全量 pytest：`847 passed, 3 skipped`。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests`：退出码 0。
- `conda run --no-capture-output -n re-uthcode python -m pip check`：`No broken requirements found.`。
- `git diff --check`：退出码 0，无 whitespace error。
- UTF-8 guard：W04 Feedback 共 1 个改动 Markdown 文件，结果 `OK`；无 replacement character、mojibake 或 fence 不平衡。
- 负向扫描：无旧 Slash 入口、重复 Runtime/规划职责、动态 Hook registry、Interface 越界依赖；`AgentLoop` 与 `AgentTurnExecution` 定义各 1 个。

## 包级返工第 1 轮

### 包级审查的四项原因

1. `AgentLoop` 在 omitted、显式空和 custom-only `RuntimeHookSet` 下可能没有强制 PLAN 只读与 completion Hook，`PLAN + WRITE + FULL_ACCESS` 可执行工具并普通完成。
2. one-shot completion、steering、revision feedback 在 async request preparer 返回后过早清除；被 pause、cancel 或 steering 丢弃的 prepared request 仍会消费 feedback。
3. Application 对 Plan Review REVISE 先发布 `TurnResumed`，Core 的真实 user Message 与 revision feedback 在下一 segment 才应用；APPROVE/REVISE 未走统一的 Core response application path。
4. A01、A02、A04 当前事实未同步实际的 Tool/候选 final 路径、五类 typed pause/Plan Review 转移与输入优先级、`start_turn`/`steer` 编排边界。

### 红测证据

- 先加入 omitted/empty/custom-only HookSet、PLAN candidate final、PLAN WRITE fail-closed、async preparer 下 completion/steering/revision feedback、cancel 竞态以及 Application `TurnResumed` 精确时点断言。
- 旧顺序下 Application 断言在消费 `TurnResumed` 时失败：`state.runtime_feedback is None`；这直接证明 REVISE feedback 尚未在恢复事件发布前保持。
- 强制 completion Hook 接入后，原有显式 PLAN tool-only Hook 测试继续把 candidate final 断言为普通完成；已修正为 `PLAN_REVIEW_REQUIRED`，删除该反向固化。

### 实际实现选择

- `AgentLoop` 通过 `compose_runtime_hooks()` 固定先组合 `plan_tool_policy`、`plan_completion_hook`、`task_completion_hook`，再按调用者给定顺序执行可选 Hook；内建 Hook 去重，避免 Application 与 Core 重复执行。Application 默认只提供空的可选 `RuntimeHookSet`。
- feedback 清除点从 request preparer 返回后移动到 cancel、steering、pause 边界之后、真实 Provider attempt 之前，因此被丢弃的 prepared request 不消费 feedback，首个真实 attempt 只携带一次。
- Core 增加统一 `apply_pause_response()`；`TurnHandle.resume()` 对 APPROVE、REVISE 及其他 typed response 都先调用 Core 应用路径，再由 driver 发布唯一 `TurnResumed`。恢复事件发布后让出一次调度机会，保持消费者可观察到恢复时的权威状态。
- 仅同步 A01/A02/A04 当前事实；未修改冻结的 T08 原始需求、Spec、Tasks、Prompt 或 Checklist，也未新增 Context-Index 变更。

### 修改文件

- `src/uthcode/core/agent.py`
- `src/uthcode/core/hooks.py`
- `src/uthcode/core/__init__.py`
- `src/uthcode/application/tools.py`
- `src/uthcode/application/runs.py`
- `tests/test_agent_loop.py`
- `tests/test_application_runs.py`
- `docs/A01-AgentRuntime/AgentRuntime-Context.md`
- `docs/A02-Control/Control-Context.md`
- `docs/A04-Orchestration/Orchestration-Context.md`
- 本文件（仅追加本章节）

### 定向及全量测试

- 四项独立反例与新增生命周期回归：`tests/test_agent_loop.py`、`tests/test_application_runs.py`、`tests/test_runtime_hooks.py` 定向集合通过；包括 omitted/empty/custom-only HookSet、Tool 不执行/权限 resolver 不调用/单一受控 ToolResult、candidate final Plan Review、completion/steering/revision feedback pause/cancel/steering 边界和一次性消费。
- T08 Task 1–12 相关定向集合：`339 passed`。
- Runtime Hook、AgentLoop、Application Run、Permission、TUI、architecture/package 与正式 T08 E2E：`114 passed`（运行时核心集合）；扩大 T04–T08 回归：`608 passed`。
- 全量：`conda run --no-capture-output -n re-uthcode python -m pytest -q`，`857 passed, 3 skipped`。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests`：通过。
- `conda run --no-capture-output -n re-uthcode python -m pip check`：`No broken requirements found.`。
- T08 正式 E2E 单独复验：`5 passed`。
- 所有 Python 验证显式设置 `PYTHONPATH=D:\project\Re-UthCode\src`；实际 `uthcode.__file__` 为 `D:\project\Re-UthCode\src\uthcode\__init__.py`。

### UTF-8 guard、未完成项与风险

- 本轮追加后已执行 `uth-utf8-guard`：18 个受管 Markdown 文件全部 `OK`，检查 UTF-8、BOM、replacement character、mojibake 与 Markdown fence 均通过。
- 未引入动态 Hook registry、第二 Runtime、Manager/Scheduler、兼容层、第二 AgentLoop 或第二 RunState authority；仍保留动态 registry、持久 Session/Memory、Subagent/Multi-Agent、第二 Runtime/Scheduler、Context Compression 等未实现边界。
- 当前未发现与四项 findings 相关的未完成实现；原有 Windows Terminal 人工色差、键盘与 scrollback 风险仍需人工验收，不由本轮自动化替代。
