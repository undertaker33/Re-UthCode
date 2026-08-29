# W02 Eval 单次执行 Feedback

## 执行范围

- Worker：`W02-eval-execution`
- 执行日期：2026-08-13
- Conda 环境：`re-uthcode`
- 负责范围：B01 Task 3；只新增 `eval/execution.py`、`tests/eval/test_eval_execution.py`，并勾选 Task 3 Checklist。
- 没有修改 `src/uthcode/**`、正式 CLI/TUI、公共 Event、Permission/Agent Loop、Task 1～2 合同实现或其他冻结任务书。
- 开始时已存在 `docs/Context-Index.md`、`docs/OutstandingDebtList.md`、B01 工作包及一组与本任务无关的 T07-1 工作树删除/新增变更；本 Worker 未覆盖、清理或改写这些既有变更。

## 实际完成内容

`eval/execution.py` 提供 `run_attempt` 和 `AttemptExecution`，将一次 Eval attempt 组合为以下闭环：

```text
TaskDefinition + AttemptPaths
  -> 外部 workspace/home/artifacts 合同校验
  -> ApplicationRuntimeContext(workspace)
  -> uthcode.application.create_application(...)
  -> Application.create_run(run_id)
  -> Run-local permission=auto、任务 behavior mode
  -> 同一 Run.start_turn(instruction)
  -> 唯一 TurnHandle.events() 消费者
       -> 预声明 AskUser/PlanReview 的 typed resume
       -> Permission ASK / 未声明交互的单次 cancel
       -> timeout 的单次 cancel
  -> 同一 TurnHandle.result()
  -> verifier 单次调用
  -> 外部 artifact 投影和 AttemptRecord
```

实现不导入 `uthcode.core`、`uthcode.integrations` 或 Provider SDK；只从 `uthcode.application` 取得 Application、Run、Turn、公开 Event、TurnResult 和 typed interaction 合同。Application 内部仍是既有唯一 Agent Loop、Tool Registry 和 Permission Evaluator，Eval 没有创建第二套实现，也没有使用手工 Tool 执行入口。

## 关键行为证据

### Exactly-once

- 每次调用只创建一个 Application、一个 `AgentRun` 和一个 Turn。
- `events()` 只在一个任务中调用一次；`result()` 只等待该同一 Turn。
- provider 请求数、run/turn ID、`turn_started` 和 `turn_resumed` 事件在测试中均有断言。
- `cancel_once` 统一收口 Permission、未声明交互和 timeout 的取消请求；重复取消不会产生第二次请求。
- verifier 在 Turn 结束后最多调用一次，包括 Permission block，以便保留已有副作用证据。
- 现有 `TurnHandle.result()` 的稳定终态复用由 Application 测试回归覆盖，W02 只消费其公开合同，不复制结果状态。

### 交互、权限和超时分类

- `AskUser`：只按 `InteractionSpec(kind=ask_user)` 查找预设答案，并先调用公开 `UserInputRequest.validate_answers`；问题 ID、问题类型、工具调用、run/turn/pause 标识不匹配时不会编造答案。
- `PlanReview`：只按声明的 `plan_review` response 构造 approve/revise typed response，并使用待审 revision；恢复继续使用同一个 Run/Turn。
- 未声明 AskUser/PlanReview：`undeclared_interaction`，记录请求类型并单次取消。
- Permission ASK：不调用 `resume`，不提供 ONCE/SESSION，不建立 Session Grant，标记 `blocked_by_permission` 并单次取消。
- timeout：等待同一 Turn 到截止时间后标记 `timeout`、取消一次、等待稳定终态，不在同一 workspace 重试。
- Provider failure 与 Runtime/runner/verifier failure 分别保留可解析分类；Provider 失败映射为 `agent_failure` + `failure_class=provider`，verifier 异常映射为 `verifier_error`，组装或输入边界异常映射为 `runner_error`。
- 非 Fake Provider 在没有同时提供 `live=True` 和 `live_authorized=True` 时，在 Application factory 之前拒绝；本 Worker 未发起网络或费用调用。

### 脱敏与 artifact

每次 attempt 在外部专用 root 的 manifest 目录写入：

- `metadata.json`
- `events.jsonl`
- `turn_result.json`
- `verifier_result.json`
- `diagnostics.json`
- `workspace-diff.json`
- `output-manifest.json`（stdout/stderr 当前明确标为 unavailable）

事件和结果只使用公开 `to_dict()` 投影；通用 JSON 投影拒绝原生对象并将未知对象变为 `<redacted>`。`api_key`、token、Bearer、`sk-...` 形状以及显式传入/配置环境中的 secret value 不进入 artifact。运行前后的 workspace 文件哈希差异和 Git status delta 只记录可确认事实；Eval 自动生成的隔离 `.uthcode/permissions.toml` 不计作任务副作用。

`AttemptPaths` 在执行前重新检查 Eval root marker、attempt manifest identity、三个物理 component 与外部 root 的关系；不接受链接、伪造 manifest、跨 root 路径或 task/attempt ID 不一致。

## 修改文件

- `eval/execution.py`
- `tests/eval/test_eval_execution.py`
- `docs/work/B01-私有测试集v0/B01-私有测试集v0-checklist.md`：仅将 Task 3 三个既有复选框从 `[ ]` 改为 `[x]`
- `docs/work/B01-私有测试集v0/feedback/W02-eval-execution-feedback.md`

没有修改 W01 的 `eval/models.py` 或 `eval/workspace.py`；没有修改生产源码、公共协议、配置 loader、权限规则实现、正式入口、metrics/reporting/runner 或七题任务。

## Checklist 证据

- Task 3 第 1 项：已完成。`tests/eval/test_eval_execution.py` 覆盖正常 attempt、单 Run/Turn、单事件流、同一 Turn 结果、单 verifier，且包含 AskUser 与 PlanReview 的同 Turn resume。
- Task 3 第 2 项：已完成。覆盖正常、Permission ASK、未声明交互、typed response、timeout、Provider failure、verifier/runner error、取消 exactly-once、Session Grant 为零和 artifact 脱敏。
- Task 3 第 3 项：已完成。静态 AST 测试确认 `eval/execution.py` 没有 `uthcode.core`、`uthcode.integrations` 或 SDK import；实际调用只经过 `uthcode.application`。

## 精确验证结果

1. `conda run --no-capture-output -n re-uthcode python -m pytest tests/eval/test_eval_execution.py tests/test_application_runs.py tests/test_agent_events.py -q`
   - 结果：`74 passed in 7.02s`。
2. `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_permission_delivery.py tests/test_t08_e2e.py -q`
   - 结果：`54 passed in 9.12s`。
3. `conda run --no-capture-output -n re-uthcode python -m pytest tests/eval -q`
   - 结果：`35 passed in 7.04s`。
4. `conda run --no-capture-output -n re-uthcode python -m compileall -q eval tests/eval`
   - 结果：退出码 `0`。
5. `git diff --check`
   - 结果：退出码 `0`；仅显示开始时已存在文档的 LF/CRLF 转换警告，无 whitespace error。
6. `python C:\Users\93445\.codex\skills\uth-utf8-guard\scripts\check_utf8_docs.py docs/work/B01-私有测试集v0/B01-私有测试集v0-checklist.md docs/work/B01-私有测试集v0/feedback/W01-eval-contract-workspace-feedback.md`
   - 结果：W02 文档写回前检查用例通过；W02 Feedback 写回后还需对新文件和 Checklist 重新执行一次 guard，见交付前复核。

## 与任务书的差异

- Task 3 任务书写明“修改文件：无”；本次实际只新增 Prompt 明确允许的 `eval/execution.py`、`tests/eval/test_eval_execution.py`，并按工作包规则更新 Checklist/Feedback，没有修改 W01 合同文件。
- 本 Worker 没有实现 verifier 子进程、metrics/reporting、runner、七题 fixture、真实 baseline 或产品 CLI；这些属于后续 Task，未提前建设。
- `AttemptRecord` 的 context metric 在本 Worker 保持 `not_available`，没有伪造 Context Compiler、Compaction、Working Set 或 Memory 事实。
- stdout/stderr 当前通过 `output-manifest.json` 明确记录为 unavailable，未把不存在的输出流伪造成已采集内容。

## 风险与未验证项

- 未运行真实 Provider、网络或费用；固定模型 baseline 仍是 `NOT VERIFIED (authorization required)`。
- 尚未实现 Task 4～9，因此 `python -m eval.runner`、七题 deterministic verifier、六维报告、compare 和 Fake smoke 总入口不属于本次已验证范围。
- 当前任务级 permission rules 文件使用既有 Integration loader 的项目规则格式；规则仍由正式 Permission Evaluator 判定，Eval 不提供 allow bypass。Bash 仍是当前 OS 用户权限下的 unsandboxed process execution，外部 workspace 和 `auto` 都不描述为 Sandbox。
- 当前 artifact 使用公开事件/TurnResult 的 JSON 投影；完整 ToolResult 正文和 Provider 原生对象不会进入该边界，但完整安全扫描、报告聚合和跨实验 compare 留给后续 Worker。

## 遗留负担清理

- 未引入 Benchmark Adapter、Registry、Manager、第二 Agent Loop、第二 Permission 系统、兼容层或正式 CLI 入口。
- 未创建仓库内运行态 artifact、临时 home 或 workspace；测试使用 pytest 临时目录并由 fixture 生命周期管理。
- 未执行 Git add、commit、push、merge、rebase、tag、release 或工作包归档。
- 开始时已存在的 T07-1 删除/新增变更未触碰；最终 Git 状态仍需由用户在整体工作树范围复核。

## UTF-8 guard

- files checked: W02 Checklist、W01 Feedback、W02 Feedback
- result: UTF-8 解码、replacement character、常见乱码和 Markdown fence 检查通过。
- repaired encoding issues: none

## 返工记录：P1 repo-child Eval root 安全边界

### 返工轮次与原因

- 返工轮次：W02 验收后 P1 返工。
- 原因：验收发现 `eval/execution.py` 原执行前校验只拒绝 `eval_root == repo_root`，没有拒绝物理路径上位于 `repo_root` 下的 Eval root。公开构造 `AttemptPaths` 并伪造匹配 marker/manifest 后，`repo/forged-eval` 会被接受，存在在源码仓库内写入任务权限文件和 artifact 的风险。
- 本轮没有修改原始需求、Spec、Tasks、Prompt 或 Checklist 文本；仅在本 Feedback 末尾追加记录，并修改实现及回归测试。

### 实际修复

- `eval/execution.py` 的 `_validate_attempt_paths` 现在先将 `repo_root` 和 `eval_root` 解析为物理路径。
- 执行前通过 `git rev-parse --show-toplevel` 和仓库状态读取确认 `repo_root` 是真实、可访问且物理上等于 Git worktree 根；普通目录、伪造 `.git` 或仓库子目录均拒绝。
- 使用物理路径 containment 检查，同时拒绝 `eval_root == repo_root` 和 `eval_root` 位于 `repo_root` 下的情况；该检查发生在 `_task_permission_file`、Application 创建、Run/Turn 启动以及执行 artifact 写入之前。

### 新增对抗回归

- `tests/eval/test_eval_execution.py` 新增伪造 repo-child marker/manifest 用例：构造 `repo/forged-eval` 的公开 `AttemptPaths` 后，断言在任何权限文件或新 artifact 写入前失败，Application factory 不被调用。
- 新增非 Git `repo_root` 用例，断言同样在写入前失败。
- 测试 fixture 使用真实临时 Git 仓库；伪造目录只存在于 pytest 临时目录，不进入源码仓库。

### 返工后精确验证结果

1. `conda run --no-capture-output -n re-uthcode python -m pytest tests/eval/test_eval_execution.py -q`
   - 结果：`12 passed in 8.85s`。
2. `conda run --no-capture-output -n re-uthcode python -m pytest tests/eval/test_eval_workspace.py -q`
   - 结果：`9 passed in 2.09s`。
3. `conda run --no-capture-output -n re-uthcode python -m pytest tests/eval/test_eval_execution.py tests/test_application_runs.py tests/test_agent_events.py -q`
   - 结果：`76 passed in 11.53s`。
4. `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_permission_delivery.py tests/test_t08_e2e.py -q`
   - 结果：`54 passed in 11.08s`。
5. `conda run --no-capture-output -n re-uthcode python -m pytest tests/eval -q`
   - 结果：`37 passed in 10.58s`。
6. `conda run --no-capture-output -n re-uthcode python -m compileall -q eval tests/eval`
   - 结果：退出码 `0`。
7. `git diff --check`
   - 结果：退出码 `0`；仅保留既有 `Context-Index.md`、`OutstandingDebtList.md` 的 LF/CRLF 转换警告，无 whitespace error。

本轮未执行 Git add、commit、push、merge、rebase、tag、release 或工作包归档。P1 修复已具备上述回归证据；在验收方复核前，仍不建议进入 W03。
