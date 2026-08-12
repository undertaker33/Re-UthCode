# W02：单 AgentLoop 与 Application 执行控制

你在物理 worktree `D:\project\Re-UthCode-T08-W02`、分支 `T08-W02-runtime-application` 工作。只执行 T08 Task 3～Task 7。W01 是串行前置；W02 与 W03 在 W01 之后并行。

## 开工前核验与 W01 同步

1. 执行 `git rev-parse --show-toplevel`，输出必须是 `D:/project/Re-UthCode-T08-W02`。
2. 执行 `git branch --show-current`，输出必须是 `T08-W02-runtime-application`。
3. 执行 `git status --short`，必须为空。
4. 确认本地分支 `T08-W01-core-contracts` 存在，且 W01 Feedback 可从该分支读取。
5. 执行 `git merge --ff-only T08-W01-core-contracts`。只允许 fast-forward；若失败立即停止，禁止 rebase、强制移动或普通 merge。
6. 执行 `git merge-base --is-ancestor T08-W01-core-contracts HEAD`，退出码必须为 0。

## 必须完整读取

1. `AGENTS.md`
2. `SRe-AGENTS.md`
3. `docs/work/README.md`
4. `docs/Context-Index.md`
5. `docs/A01-AgentRuntime/AgentRuntime-Context.md`
6. `docs/A02-Control/Control-Context.md`
7. `docs/A03-State/State-Context.md`
8. `docs/A04-Orchestration/Orchestration-Context.md`
9. T08 原始需求、Spec、Tasks、Checklist
10. `docs/work/T08-任务规划与执行控制/feedback/W01-core-contracts-feedback.md`
11. Task 3～Task 7 涉及的当前源码与测试

## 严格工作范围

按顺序完成：

- Task 3：Behavior Mode 与 Dynamic Tool View；
- Task 4：Plan Proposal / Review / Approve；
- Task 5：Todo / Execution Planning / Completion Control；
- Task 6：User Steering；
- Task 7：Application Run Mode 与 Steering Control。

你独占以下共享热点：

- `src/uthcode/core/agent.py`
- `src/uthcode/application/runs.py`
- `src/uthcode/application/generation.py`
- `src/uthcode/application/tools.py`
- `tests/test_agent_loop.py`
- `tests/test_application_runs.py`
- 相应 Application Runtime/Tool 测试

禁止修改 W01 冻结的 `planning.py`、`hooks.py`、`interaction.py`、`agent_events.py`、`prompt.py`、Tool access contract 及其合同测试；发现合同错误必须停止并记录，不得悄然重写。禁止修改 Slash、TUI、CLI 和 `docs/TUI/README.md`。

## 已确认设计决策

- 只有一个 AgentLoop、一个 RunState authority、一个 ToolRegistry/Executor 和一个 Application `_TurnDriver`。
- Provider、model 与 Tool universe 在 active Turn 内稳定；每次 iteration 依据当前 BehaviorMode 生成 visible Tool View。
- pre-tool 顺序严格为 trusted preflight → Hook → Permission → execute；PLAN 非 READ 在 Permission 前拒绝。
- candidate final 先验证与计 usage，再跑 completion Hook；只有 Continue 才写 ordinary assistant message/事件并完成 Turn。
- PLAN candidate 与 unfinished-task candidate 必须缓冲，不能先把 delta/完成正文写进不可回滚 UI。
- Plan proposal/revise/approve 保持同一 run、turn、handle；approve 自动 PLAN→DEFAULT 并在下一 iteration 使用 full Tool View。
- TodoWrite 是 Core control path，replace-all 写 TaskState；普通工具、Permission 和手工 Application Tool API 不执行它。
- Steering 使用专用 pending 请求：Provider attempt 可中断，当前 Tool 不强杀，stale remainder 逐 ID 闭合后把文本写为真实 user Message。
- typed pause pending 时 Steering 拒绝；Cancel > Steering > candidate completion。
- RunSnapshot 不暴露 Plan/Task 正文；TUI/Headless 通过安全事件和公开 Run mode API工作。

## 实施与验证要求

1. 对每个 Task 先补失败测试，保持单一顺序可读执行链；不要拆成 Manager、Scheduler 或第二 loop。
2. 复用现有 T06 pause/cancel safe boundary 和 T07 preflight/Permission，不复制 waiter、queue、evaluator 或 tool executor。
3. 使用 `conda run --no-capture-output -n re-uthcode ...`。
4. 完成 Checklist Task 3～Task 7 全部可执行项，并重跑 T04～T07 相关 Agent/Application/Permission 回归。
5. 只勾选 Task 3～Task 7；若 `feedback/` 尚不存在，先创建该目录，再首次创建 `feedback/W02-runtime-application-feedback.md`。
6. Feedback 必须给出实际 request Tool View capture、Hook 调用位置、Plan/Task/Steering 状态流、竞态与资源清理测试、修改文件、风险和 W03/W04 所需 API。
7. 对 Checklist 与 Feedback 执行 UTF-8 guard；执行 `git diff --check`。

## Git 边界与交付

- 本 Prompt 授权开工时对 W01 执行一次 `--ff-only` 同步，并授权在 W02 分支做窄范围本地 commit。
- 提交前核对 staged 文件，只包含 Task 3～Task 7、对应 Checklist 勾选和 W02 Feedback。
- 禁止 merge W03/W04、普通 merge W01、rebase、push、reset、worktree 操作、删分支或改远端。
- 提交后工作树必须干净，报告 commit hash 与验证摘要，然后等待 W04 合并。

如果动态 Tool View 只能通过重建 Turn、Steering 无法闭合 stale call ID、candidate 在 Hook 前已不可逆公开、必须新增 Hook point/第二 Runtime，或需要改 W01 冻结合同，立即停止相关范围并记录最小复现。
