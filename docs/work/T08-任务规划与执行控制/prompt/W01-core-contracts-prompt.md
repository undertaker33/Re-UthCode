# W01：Core 合同与策略基础

你在物理 worktree `D:\project\Re-UthCode-T08-W01`、分支 `T08-W01-core-contracts` 工作。只执行 T08 Task 1、Task 2；完成后提交本分支，供 W02、W03 fast-forward 和 W04 最终合并。

## 开工前核验

1. 执行 `git rev-parse --show-toplevel`，输出必须是 `D:/project/Re-UthCode-T08-W01`。
2. 执行 `git branch --show-current`，输出必须是 `T08-W01-core-contracts`。
3. 执行 `git status --short --branch`，除任务包基线外不得有来源不明的修改。
4. 任一条件不满足立即停止，不得切换、重置或修复别的 worktree。

## 必须完整读取

1. `AGENTS.md`
2. `SRe-AGENTS.md`
3. `docs/work/README.md`
4. `docs/Context-Index.md`
5. `docs/A01-AgentRuntime/AgentRuntime-Context.md`
6. `docs/A02-Control/Control-Context.md`
7. `docs/A03-State/State-Context.md`
8. `docs/work/T08-任务规划与执行控制/T08-任务规划与执行控制.md`
9. `docs/work/T08-任务规划与执行控制/T08-任务规划与执行控制-spec.md`
10. `docs/work/T08-任务规划与执行控制/T08-任务规划与执行控制-tasks.md`
11. `docs/work/T08-任务规划与执行控制/T08-任务规划与执行控制-checklist.md`
12. Task 1、Task 2 涉及的当前源码与测试

## 严格工作范围

按顺序完成：

- Task 1：Planning Domain、Tool 可见性与控制协议；
- Task 2：Runtime Hook 与 Runtime Prompt Facts。

允许修改范围以 Tasks 中 Task 1、Task 2 的文件清单为准。特别禁止修改：

- `src/uthcode/core/agent.py`
- `src/uthcode/application/**`
- `src/uthcode/interfaces/**`
- `tests/test_agent_loop.py`
- `tests/test_application*.py`
- `tests/test_tui.py`

## 已确认设计决策

- BehaviorMode 只有 DEFAULT/PLAN，与 PermissionMode 正交。
- TaskState 使用三态、不可变、保持顺序、replace-all、至多一个进行中项；`todos=[]` 是显式清空。
- PlanState 与 TaskState 分离，不自动转换。
- Steering 是专用 immutable control request，不是 PauseKind、PauseResponse 或新 Turn。
- Plan Review 是现有 typed pause union 的正式成员，REVISE 需要非空反馈并严格校验 revision 与关联 ID。
- 普通 Tool 的规划可见性属于 Core Tool contract，不进入 Provider wire schema。ReadFile/Glob/Grep 可见，Bash 预检可读，WriteFile/EditFile 不可见；未声明的 Tool 不得默认可见。
- AskUserQuestion 在 PLAN/DEFAULT 均可见；TodoWrite 只在 DEFAULT，是 Core control tool，不进入普通 Registry。
- Hook 只有 `before_tool_execution` 与 `before_completion`；同步、不可变、有序、无动态注册、无全局 registry、无 Agent/Tool 调度。
- Completion Hook 顺序固定为 Plan completion → Task completion。
- Runtime Prompt Context 只携带 mode、TaskState、PlanState、one-shot feedback，不接受整个 RunState 或 UI/Application 对象。
- 新事件 display-safe；PlanProposed 携带完整 Plan，TaskStateChanged 携带完整结构化状态，Steering 事件不泄露任意原始 payload。

## 实施与验证要求

1. 先写能够失败的合同/序列化/架构测试，再实现最小生产代码。
2. 不为 W02 预写 AgentLoop glue，不创建空方法、future protocol、兼容层或分支专用 adapter。
3. 不改变 T03～T07 已有公共语义，除非 T08 原始需求明确替换。
4. 使用 `conda run --no-capture-output -n re-uthcode ...` 执行 Python、pytest 和检查工具。
5. 至少执行 Checklist Task 1、Task 2 的全部命令，并重跑所有受影响既有测试。
6. 只勾选 Task 1、Task 2 中有真实输出支持的复选框，不改 Checklist 文字、编号或其他 Task。
7. 若 `feedback/` 尚不存在，先创建该目录；首次创建 `docs/work/T08-任务规划与执行控制/feedback/W01-core-contracts-feedback.md`，说明合同、文件、测试、与需求差异、风险和 W02/W03 必须遵守的冻结 API。
8. 对 Checklist 与 Feedback 执行 UTF-8 guard，结果必须为 `OK`。

## Git 边界与交付

- 本 Prompt 明确授权在当前 W01 分支执行窄范围 `git add` 与本地 commit。
- 提交前核对 `git diff --check`、`git diff --cached --name-only` 和 `git diff --cached`，只能包含 Task 1、Task 2、对应 Checklist 勾选与 W01 Feedback。
- 使用清晰的 T08/W01 commit message；提交后 `git status --short` 必须为空。
- 禁止 push、merge、rebase、cherry-pick、reset、worktree add/remove、删除分支或修改远端。
- 完成后报告 commit hash 和验证摘要；等待用户派发 W02/W03，不自行继续实施。

遇到需要修改 `agent.py`、Application/TUI、增加第三个 Hook point、把 Tool metadata 写入 Provider schema、把 Steering 建成 pause，或需求与现有冻结语义冲突时，停止相关范围并在 W01 Feedback 记录。
