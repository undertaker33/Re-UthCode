# W01：交互运行时与 Turn 控制

你负责连续完成 T06 的 Task 1、Task 2、Task 3。三项任务共享同一运行语义，必须在同一工作上下文内依次完成；Task 2 完成后不得以中间状态交付，必须继续完成 Task 3 后再停止。

## 开工前必读

1. `AGENTS.md`
2. `SRe-AGENTS.md`
3. `docs/work/README.md`
4. `docs/work/T06-暂停恢复与询问用户/T06-暂停恢复与询问用户.md`
5. `docs/work/T06-暂停恢复与询问用户/T06-暂停恢复与询问用户-spec.md`
6. `docs/work/T06-暂停恢复与询问用户/T06-暂停恢复与询问用户-tasks.md`
7. `docs/work/T06-暂停恢复与询问用户/T06-暂停恢复与询问用户-checklist.md`
8. `docs/work/T04-工具系统/` 与 `docs/work/T05-ReAct与AgentLoop/` 中的最终 Spec、Tasks、Checklist 与 Feedback
9. Task 1～3 涉及的 Core、Application 源码和测试

若文档冲突，以需求原文、项目规则和本工作包 Spec 的约束为准；在 Feedback 中记录冲突与处理依据。

## 工作范围

按顺序完成：

- Task 1 — Core 交互协议与事件；
- Task 2 — Core 显式 Continuation 与暂停边界；
- Task 3 — Application Turn 协调与控制工具隔离。

允许修改的范围以 Tasks 中 Task 1～3 的文件级职责为准。若必须修改 Provider DTO、普通 Tool 公共协议、第三方集成协议或 Interface 行为，立即停止并在 Feedback 中说明，不得自行扩大边界。

## 不可变设计约束

- Core 以执行分段运行，每段在暂停边界或终态返回。
- Core 通过显式 continuation 事实描述如何继续，不等待用户回答。
- Core 的 T06 暂停路径不得保存响应等待用的 `Future`、`Event`、`Queue`、`Task`、`Lock`、等价等待器或暂停中的 Python 调用栈。
- Application 私有驱动器拥有分段驱动任务、事件队列、终态结果 Future 和暂停回答 waiter。
- 公共 API 只暴露稳定的 TurnHandle、事件、待处理交互和类型化恢复命令，不暴露私有异步对象。
- Ask 是 Application 注入的控制工具，不进入普通工具注册、Provider 工具实现或用户配置路径。
- 直接删除被新设计替代的旧入口、等待器、测试和不可达分支；不得添加适配器、别名、包装层、废弃入口或双轨逻辑。

## 实施与验证要求

1. 先补测试，再实现最小完整行为。
2. Task 1、Task 2、Task 3 的 Checklist 逐项验证并保留命令与结果证据。
3. 至少运行相关 Core/Application 测试、静态负向扫描、编译检查和 `git diff --check`。
4. 使用 `conda run --no-capture-output -n re-uthcode ...` 执行 Python、pytest 和项目工具；不得假设 `conda activate` 已生效。
5. 不执行 Git 写操作，不提交、不暂存、不推送。
6. 不修改需求原文，不勾选其他 Worker 的 Checklist。

## 交付

完成 Task 1～3 后：

- 勾选 Checklist 中 Task 1、Task 2、Task 3 的真实完成项；
- 写入 `docs/work/T06-暂停恢复与询问用户/feedback/W01-interaction-runtime-control-feedback.md`；
- Feedback 必须包含改动文件、关键设计结果、删除项、测试命令与输出摘要、负向扫描、未决风险和逐项验收证据；
- 若任一必需验收项未通过，明确标记未完成，不得宣称交付完成。
