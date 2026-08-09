# W03：Slash Command 与 TUI 产品闭环

你在物理 worktree `D:\project\Re-UthCode-T08-W03`、分支 `T08-W03-slash-tui` 工作。只执行 T08 Task 8、Task 9。W01 是串行前置；W03 与 W02 在 W01 之后并行，不能读取或合并 W02 的未完成实现。

## 开工前核验与 W01 同步

1. 执行 `git rev-parse --show-toplevel`，输出必须是 `D:/project/Re-UthCode-T08-W03`。
2. 执行 `git branch --show-current`，输出必须是 `T08-W03-slash-tui`。
3. 执行 `git status --short`，必须为空。
4. 确认 `T08-W01-core-contracts` 与 W01 Feedback 存在。
5. 执行 `git merge --ff-only T08-W01-core-contracts`；无法 fast-forward 时停止，不得 rebase、强制移动或普通 merge。
6. 执行 `git merge-base --is-ancestor T08-W01-core-contracts HEAD`，退出码必须为 0。

## 必须完整读取

1. `AGENTS.md`
2. `SRe-AGENTS.md`
3. `docs/work/README.md`
4. `docs/Context-Index.md`
5. `docs/A04-Orchestration/Orchestration-Context.md`
6. `docs/TUI/README.md`
7. T08 原始需求、Spec、Tasks、Checklist
8. `docs/work/T08-任务规划与执行控制/feedback/W01-core-contracts-feedback.md`
9. 当前 Slash Command、TUI 与对应测试

## 严格工作范围

按顺序完成：

- Task 8：Slash Command 产品入口；
- Task 9：TUI Plan / Todo / Steering 产品闭环。

允许修改：

- `src/uthcode/application/commands/**`
- 为公开 Command Action 必需的 `src/uthcode/application/__init__.py`
- `src/uthcode/interfaces/tui/app.py`
- `src/uthcode/interfaces/tui/interaction.py`
- `src/uthcode/interfaces/tui/rendering.py`
- `src/uthcode/interfaces/tui/terminal.py`
- command tests、`tests/test_tui.py`
- `docs/TUI/README.md`
- Task 8、Task 9 Checklist 与 W03 Feedback

禁止修改 Core、`application/runs.py`、`generation.py`、`tools.py`、CLI、Agent/Application runtime tests 或 `tests/test_t08_e2e.py`。

## 已确认设计决策

- `/plan` 与 `/do` 是无参数 mode-selection；`/build` 只是 `/do` alias。删除旧 `/p` 和旧 Prompt `/do`，不增加第三种 Build mode。
- Command Registry 是 help/completion/alias 的唯一事实源；Action 只表达 BehaviorMode 选择，不直接保存业务状态。
- W02 将提供 `AgentRun.behavior_mode`、idle mode setter 和 `TurnHandle.steer(text)`；W03 用 fake Run/Handle 对该预期合同做分支级测试，真实接线由 W04 验证。
- idle 文本 start Turn；active 且无 typed interaction 的普通文本 steer；任何 AskUser、Permission、Retry 或 Plan Review pending 都优先消费输入。
- Plan revision 以完整 append-only block 显示，Plan Review UI 不拥有 PlanState。
- TaskStateChanged 只投影 Core 全量状态；Steering user message exactly once；CompletionBlocked 不展示 candidate final。
- status 分开显示 behavior mode 与 permission mode；PLAN separator/Plan block 使用专用可区分 palette，approve 后立即恢复 DEFAULT。
- 继续使用主缓冲区、原生 scrollback、非全屏、无鼠标、无 `CSI 3J`，不回写已提交历史。

## 实施与验证要求

1. 先补 command、renderer、interaction 和 TUI 失败测试；不为等待 W02 添加 placeholder Runtime、Interface-owned state 或兼容分支。
2. 当前真实测试集中在 `tests/test_tui.py`，不得再造重复 test suite/fixture。
3. 使用 `conda run --no-capture-output -n re-uthcode ...` 完成 Checklist Task 8、Task 9 与既有 TUI/command 回归。
4. 只勾选 Task 8、Task 9；若 `feedback/` 尚不存在，先创建该目录，再首次创建 `feedback/W03-slash-tui-feedback.md`。
5. Feedback 记录 Slash 最终定义、TUI 输入优先级、Plan/Todo/Steering 展示、测试、人工仍需复核项及 W04 接线边界。
6. 对 `docs/TUI/README.md`、Checklist、Feedback 执行 UTF-8 guard；执行 `git diff --check`。

## Git 边界与交付

- 本 Prompt 授权开工时对 W01 执行一次 `--ff-only` 同步，并授权在 W03 分支做窄范围本地 commit。
- 提交前核对 staged scope；禁止纳入 Core/Runtime、W02 文件或来源不明修改。
- 禁止 merge W02/W04、普通 merge W01、rebase、push、reset、worktree 操作、删分支或改远端。
- 提交后工作树必须干净，报告 commit hash 和验证摘要，然后等待 W04 合并。

如果实现需要 TUI 直接写 RunState/PlanState/TaskState、绕过 Application、改变 W01 事件协议、共享 W02 热点文件、回写 scrollback 或复制第二套 command registry，立即停止并在 Feedback 记录。
