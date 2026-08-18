# W06 Runtime Persistence / Manual Compact / Overflow Worker Prompt

## 任务范围与顺序

在 W01～W05 完成后，只执行 Task 6：Incremental Transcript、Manual Compact 与 Overflow Retry。完成 Feedback 后停止，最终 diagnostics/docs/E2E/cleanup 由 W07 负责。

## 必须读取

1. `AGENTS.md`、`docs/README.md`、`docs/Context-Index.md`
2. `docs/rules/WorkPackageRules.md`
3. 本工作包原始需求、Spec、Tasks、Checklist
4. `docs/context/A01-AgentRuntime/AgentRuntime-Context.md`
5. `docs/context/A03-State/State-Context.md`
6. `docs/context/A04-Orchestration/Orchestration-Context.md`
7. W01～W05 Feedback
8. Task 6 列出的源码与测试，特别是现有 terminal persistence outcome、Command dispatcher 与 TUI adapter

使用 Conda 环境 `re-uthcode`。冻结文档不得改写；只勾选 Task 6 已满足复选框并创建/追加 Feedback。

## 已确认决策

- 在每个下一 Provider call 前提交已闭合 semantic facts；terminal tail 继续提交。
- durable identity/cursor、reconciliation、unknown quarantine 与 FIFO retry 保持现有安全语义；不把更频繁 Transcript 写入变成 Runtime checkpoint。
- manual `/compact` await 同一 Application orchestrator；有候选压缩，无候选 success no-op；不创建 Session/Run/Turn。
- same Session compaction single-flight，不创建第二套 job。
- Provider overflow 只是最后保护，最多一次 forced reduction + rebuild + retry；不修改/学习 C。
- active Turn 内 `/model` 不改变 frozen provider/model/C。

## 修改范围

仅修改 Tasks Task 6 列出的文件。`commands/models.py` 与 `interfaces/tui/app.py` 只有真实 async typing/dispatch 接入需要时才修改，不得重构 rendering。

## 必须交付

- first call user fact、post-tool complete group、terminal tail 的 incremental durable persistence；open fragment/continuation 不写。
- `/compact` async command success/no-op/failure、same Session、single-flight、no Run/Turn creation。
- 最多一次 overflow retry 与 normalized second failure。
- dynamic `/status` safe diagnostics，展示 C/Gate/A/F/U/L1-L5/checkpoint/epoch，不泄露正文。
- initial/post-tool/post-resume、manual、overflow、model switch 与 Headless tests。

## 禁止

- 不实现 persistent Runtime recovery、Pending Tool/Permission/AskUser resume、background job、独立 compaction model。
- 不让 Command/TUI 持有 Context state；不重构无关 Palette/renderer/Plan/Todo/Hook。
- 不为旧 Session 增加兼容层，不执行 Git 写入或归档。

## 验证

逐项执行 Task 6 Checklist。拆包基线在当前非交互 Windows 管道中已有 3 个 TUI RGB ANSI 断言失败；先判断是否为本 Worker 改动导致。不得为消除无关基线失败擅自扩大实现，必须在 Feedback 记录原始/复验命令、精确结果和验收影响。

## Feedback

首次创建 `feedback/W06-runtime-compact-overflow-feedback.md`。说明持久时机、manual compact、single-flight、overflow retry、status secrecy、修改文件、精确测试、Checklist 状态、差异、风险和清理。
