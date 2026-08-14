# W04 Session Commands / TUI Worker Prompt

## 执行范围

在 W03 完成后执行 Task 8。不修改 Eval，不执行 Task 9～12。

## 必须读取

1. `AGENTS.md`、`docs/rules/WorkPackageRules.md`，本工作包原始需求、Spec、Tasks、Checklist 和 W01～W03 Feedback。
2. `docs/context/A04-Orchestration/Orchestration-Context.md`、`docs/context/TUI/README.md`、Task 8 列出的 Application command、Session 和 TUI 源码/测试。

## 已确认决策

- `/compact` idle-only；`/new` 创建新 Session/Run；`/resume` 恢复原 Session identity 但从新 Turn 开始。
- `/resume` 使用独立 Picker，不复用 slash completion；仅当前 project key，last-used 倒序，每页 10 条。
- Picker 上下选择、左右翻页、Enter 确认、Esc 取消；Enter 前不改变当前 Session。
- `/status` 线性进度与输入区环形指示器使用同一 Application usage；TUI 不自行估算。

## 实施与禁止边界

- Interface 只依赖 Application 公共值；Session discovery/filter/sort/reconstruction 和 Context usage 业务语义不进 TUI。
- 保持 main-buffer scrollback、非 full-screen、无鼠标、已提交内容只追加、IME/focus 和现有最上层 Esc 消费规则。
- 不把 `/clear` 改成 new/compact，不实现跨项目 Browser 或 active Runtime recovery。
- 冻结文件规则与 Checklist 勾选规则同 W01。

## 测试与验收

执行 Checklist Task 8 全部项，包含至少 21 个 Session 的分页、窄终端省略/usage 降级、Esc 无副作用、same-session reconstruction 和原 TUI 回归；运行 architecture boundaries。

## Feedback

创建 `feedback/W04-session-commands-tui-feedback.md`。记录 Application action 与 TUI projection 边界、Picker 状态机、usage 同源证据、命令精确结果和回归。需要让 Interface 直连 Core/Integration 或改变已确认交互时停止并记录。
