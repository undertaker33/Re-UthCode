# W01 Prompt / History / Session Foundation Worker Prompt

## 执行范围

严格串行执行 Task 1 → Task 2 → Task 3。不执行 Task 4～12，不实现 Tool Result externalization、Context Compiler、Compaction、Slash/TUI 或 Eval。

## 必须读取

1. `AGENTS.md`、`docs/README.md`、`docs/Context-Index.md`、`docs/rules/WorkPackageRules.md`。
2. 本工作包原始需求、Spec、Tasks 和 Checklist。
3. `docs/context/A01-AgentRuntime/AgentRuntime-Context.md`、`docs/context/A03-State/State-Context.md`。
4. Task 1～3 列出的当前 `src/ + tests/`，以及 T03/T06 归档 Spec/Feedback 中命中的 Prompt、Session 和 restart 边界。

## 已确认决策

- 唯一 package Coding Prompt asset；不建 Registry/Profile/Overlay/用户 Prompt loader。
- Core Runtime Contract 不得被可编辑 asset 弱化。
- Session identity 与 Run/Turn 分离；history append-only，runtime log 非语义权威。
- 第一版只有 compact Projection；未知 schema/kind 和中间损坏 fail closed，只容忍最后半写 fragment。
- project key 来自物理 Git root，非 Git 则来自物理 launch workdir；`last_used_at` 不以 mtime 为产品真值。

## 实施与禁止边界

- 只修改 Tasks 1～3 列出的文件及为实现同一职责必需的最小包内导出/测试。
- Core 不依赖 filesystem、Application、Integration、Interface 或 SDK；Integration 不拥有语义 policy。
- 不恢复 active/paused Turn、waiter、Tool side effect 或 Provider continuation；不新增第三方运行时依赖。
- 不修改冻结的原始需求、Spec、Tasks、Prompt 或 Checklist 文字；Checklist 只勾选已有项。

## 测试与验收

执行 Checklist Task 1～3 全部项，并运行 `tests/test_architecture_boundaries.py`。使用 `conda run --no-capture-output -n re-uthcode ...`，测试仅写临时 Session root。

## Feedback

首次执行创建 `feedback/W01-prompt-history-session-foundation-feedback.md`。记录实际实现、关键机制、文件、命令与精确结果、Checklist 状态、偏差、风险和遗留项。返工只在原 Feedback 末尾追加轮次。遇到需要扩大公共边界或与任务书关键前提冲突时，写入 Feedback 并停止相关范围。
