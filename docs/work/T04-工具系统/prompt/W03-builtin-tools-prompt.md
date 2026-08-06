# W03 builtin-tools Prompt

请在 `D:\project\Re-UthCode` 中严格按 Task 3 → Task 4 → Task 5 的顺序实现 T04 内置工具，完成后写入 `docs/work/T04-工具系统/feedback/W03-builtin-tools-feedback.md`。开始前确认 W01、W02 已完成并通过；不得开始 Task 6–Task 9，不执行 Git 写操作。

## 必读资料

1. `AGENTS.md`、`SRe-AGENTS.md`、`docs/work/README.md`。
2. T04 原始需求、Spec、Tasks、Checklist，以及 W01、W02 Feedback。
3. 已实现的 Core Tool 契约和测试、Application runtime context。
4. 原 UthCode 固定提交的 `src/uthcode/tools/`、Day3 工作包及 `2001d10a...` 安全修复。
5. `D:\project\MewCode\mewcode\tools\` 中 base、file state、read/write/edit、glob、grep、bash，仅提取用户可见行为和缺陷教训。

## 已确认决策

- 文件与搜索能力限制在规范化工作区；既有路径严格解析，新路径校验最近存在父目录；候选文件同时做词法与物理路径检查。
- 三个文件工具共享一个 Application 局部 tracker；已有文件 Write/Edit 必须先 Read，并通过内容摘要和 stat 复核。
- Glob/Grep 不跟随目录符号链接，固定跳过依赖与缓存目录，使用稳定相对路径和排序；Grep 使用 Python regex。
- Bash 使用当前 OS shell、当前用户权限和 Application workdir，不是 Sandbox；超时/取消必须终止并 await 回收进程树或进程组。
- 所有输出截断只由 Core Executor 负责。

## 修改范围与顺序

1. Task 3：只修改其 workspace、file tools、包入口和对应测试/架构测试。
2. Task 4：只新增搜索实现与测试；workspace 仅可补通用安全 helper。
3. Task 5：只新增进程实现与测试；若 Core 取消接口确实无法表达等待，必须遵守原始需求停止条件。

不得实现 factory、Application Tool API、Agent Loop、Permission、审批、Sandbox、shell 黑名单、索引或文件历史；不得保留 MewCode/Pydantic 运行时依赖。

## 实施与验证

- 使用 `conda run --no-capture-output -n re-uthcode ...`。
- 每个 Task 完成后先运行自己的定向测试和已完成部分回归，再进入下一 Task。
- 符号链接和进程树测试按平台能力显式 skip，不得弱化核心边界。
- 完成 Task 3、4、5 Checklist，只勾选现有复选框；最后运行三组内置工具测试、Core 回归、架构测试和 `git diff --check`。

## Feedback

创建 `feedback/W03-builtin-tools-feedback.md`，按 Task 3–5 说明实际安全机制、状态变化、平台差异、文件、测试、Checklist 和风险。无法确认文件副作用或进程收口时停止，不得盲目重试或报告成功。

