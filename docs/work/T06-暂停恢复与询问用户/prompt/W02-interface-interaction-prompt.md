# W02：CLI 与 TUI 交互接入

你负责连续完成 T06 的 Task 4、Task 5。必须在 W01 完成并存在有效 Feedback 后开工。

## 开工前必读

1. `AGENTS.md`
2. `SRe-AGENTS.md`
3. `docs/work/README.md`
4. `docs/work/T06-暂停恢复与询问用户.md`
5. `docs/work/T06-暂停恢复与询问用户/T06-暂停恢复与询问用户-spec.md`
6. `docs/work/T06-暂停恢复与询问用户/T06-暂停恢复与询问用户-tasks.md`
7. `docs/work/T06-暂停恢复与询问用户/T06-暂停恢复与询问用户-checklist.md`
8. `docs/work/T06-暂停恢复与询问用户/feedback/W01-interaction-runtime-control-feedback.md`
9. Task 4～5 涉及的 CLI、TUI 源码和测试

若 W01 Feedback 缺失、标记未完成，或公共 Application API 无法满足本任务，立即停止并写明阻塞，不得绕过公共边界。

## 工作范围

按顺序完成：

- Task 4 — 非交互 CLI 暂停收口；
- Task 5 — 默认 TUI 暂停与结构化问答。

允许修改的范围以 Tasks 中 Task 4～5 的文件级职责为准。Interface 只能通过 Application 使用 Agent Core，不得直接访问 Core continuation 或 Application 私有协调对象。

## 不可变设计约束

- CLI `exec` 是非交互入口，遇到暂停必须取消 Turn、消费至取消终态并返回可识别的非零结果；不得读取 stdin、自动回答或构造恢复命令。
- TUI 将用户输入转换为类型化恢复命令，通过公共 TurnHandle 恢复同一 Turn。
- TUI 的自由文本、单选、多选、确认四类交互必须具有一致语义。
- TUI 必须处理焦点、重复提交、取消、退出和恢复后的消息流，不遗留后台任务。
- 不复制 Core/Application 状态机，不创建 Interface 私有的第二套交互协议。
- 直接删除被替代的 Interface 入口与测试；不得添加兼容层、别名或双轨逻辑。

## 实施与验证要求

1. 先补测试，再实现最小完整行为。
2. Task 4、Task 5 的 Checklist 逐项验证并保留命令与结果证据。
3. 至少运行 CLI/TUI 相关测试、取消与清理测试、编译检查和 `git diff --check`。
4. 使用 `conda run --no-capture-output -n re-uthcode ...` 执行 Python、pytest 和项目工具。
5. 不执行 Git 写操作，不提交、不暂存、不推送。
6. 不修改需求原文，不勾选其他 Worker 的 Checklist。

## 交付

完成 Task 4～5 后：

- 勾选 Checklist 中 Task 4、Task 5 的真实完成项；
- 写入 `docs/work/T06-暂停恢复与询问用户/feedback/W02-interface-interaction-feedback.md`；
- Feedback 必须包含改动文件、交互行为、删除项、测试命令与输出摘要、资源清理证据、未决风险和逐项验收证据；
- 若任一必需验收项未通过，明确标记未完成，不得宣称交付完成。
