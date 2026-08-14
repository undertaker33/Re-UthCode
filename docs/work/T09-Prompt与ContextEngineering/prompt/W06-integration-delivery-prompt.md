# W06 Integration / Delivery Worker Prompt

## 执行范围

在 W04、W05 全部完成后，严格串行执行 Task 10 → Task 11 → Task 12。允许修复 T09 范围内的集成缺陷，不扩大到 Out of Scope。

## 必须读取

1. `AGENTS.md`、`docs/README.md`、`docs/Context-Index.md`、`docs/rules/WorkPackageRules.md`，本工作包原始需求、Spec、Tasks、Checklist 和 W01～W05 全部 Feedback。
2. A01/A02/A03/A04/TUI current context，`docs/Tools.md`、命令手册、命中 Context/Runtime 的 Core Design，以及所有 T09 改动的 `src/ + tests/ + eval/`。
3. T09 与现有 T03/T04/T05/T06/T08/B01 边界相关的归档证据，只在当前事实不足时继续向历史深入。

## 已确认决策

- 交互历史、Projection、Context Snapshot、Runtime State 和 Runtime Log 是五类不同事实，不得重新合并为一个 messages/Snapshot/Event 流。
- 正式 Agent 路径必须唯一；Headless 不依赖 TUI；低层单次 generation 不冒充 Session Context path。
- 不引入后台 Worker、第二 Loop、Registry、SQLite、Provider-specific Context 分支、任意文件读取或兼容层。
- 未经用户明确要求，不执行 Git commit/push/merge/rebase/tag/release 或工作包归档。

## 实施与禁止边界

- 先执行只读集成审查，再修复可归属于 T09 的局部缺陷；发现需改冻结设计或扩展独立能力时，记录并停止相关范围。
- 依 `docs/README.md` 维护映射同步所有受影响文档，以最终 `src/ + tests/` 为事实，不把 active Runtime recovery 等 Out of Scope 写成已实现。
- 原始需求、Spec、Tasks、Prompt 和 Checklist 文字冻结；Checklist 只勾选有实际证据的现有项。

## 测试与验收

完整执行 Checklist Task 10～12，包括正式 Headless E2E、TUI Picker/usage、Eval diagnostics、定向测试、全量 pytest、compileall、pip check、architecture boundaries、UTF-8/fence、静态清理扫描和 `git diff --check`。精确记录 passed/failed/skipped 与未验证项，不把未运行命令写成通过。

## Feedback

创建 `feedback/W06-integration-delivery-feedback.md`。Feedback 需让人工审查者理解唯一正式路径、Session/Projection/Context/Runtime 边界、大结果安全模型、产品交互、文档同步、所有命令精确结果、风险与遗留项。返工只在原文件末尾追加。完成后等待用户审查和手动归档。
