# W07 Diagnostics / Integration / Verification Worker Prompt

## 任务范围与严格顺序

在 W01～W06 全部完成后，严格串行执行：

1. Task 7：Diagnostics、Eval 与文档同步
2. Task 8：[接入主流程] 单一 Context Orchestration 收口
3. Task 9：[端到端验证] Context / Compact / Recovery
4. Task 10：[遗留负担清理] 单 Transcript / Timeline 路径收口

不得跳过前项直接勾选后项。完成 Feedback 后停止；不得归档或执行 Git 写入。

## 必须读取

1. `AGENTS.md`
2. `docs/README.md`
3. `docs/Context-Index.md`
4. `docs/rules/WorkPackageRules.md`
5. 本工作包原始需求、Spec、Tasks、Checklist
6. W01～W06 全部 Feedback
7. `docs/context/A01-AgentRuntime/AgentRuntime-Context.md`
8. `docs/context/A03-State/State-Context.md`
9. `docs/context/A04-Orchestration/Orchestration-Context.md`
10. `docs/core-design/T09-context-engineering.md`
11. Task 7～10 列出的源码、tests、Eval 与用户文档

使用 Conda 环境 `re-uthcode`。工作包已冻结：不得修改原始需求、Spec、Tasks、Prompt 或 Checklist 文字，只能勾选已满足复选框并创建/追加本 Worker Feedback。修改 governed Markdown 前后必须使用 `uth-utf8-guard`。

## 已确认决策

- D1：L4/L5 复用当前主模型；active Turn 使用 frozen snapshot，idle manual compact 使用 Application current selection；无独立 compaction model。
- D2：大窗口尊重 C；真实 pressure 后执行有限 1..N bounded epoch catch-up；无独立/持久 Compact FSM。
- Transcript 是 raw durable closed facts，Timeline 是 append-only reduction products，ActiveCheckpoint 是唯一 durable Compact commit。
- L1-L3 deterministic；L4/L5 tool-free、bounded、checkpoint-last；L5 只读 raw Transcript evidence。
- resume 不恢复 active/paused Runtime；old Session 不迁移；HistoryRead 不构成 Memory/retrieval。
- Application 独占 Context orchestration；Core Provider-independent；SDK 截止 Integration；Interface 只适配 Application。

## 修改范围

Task 7 只修改列出的 diagnostics/Eval/tests/docs。Task 8～10 仅允许修复 Task 1～7 范围内的接入缺陷、测试 fixture、机械 import/export 和直接失效实现；不得新增范围外产品能力。

## 必须交付

- safe public diagnostics 与 Eval mapping，无 Context/summary/Tool result/secret 正文。
- 配置、命令、核心设计、当前事实、索引与实际代码一致。
- 所有正式 Provider call 经过单一 Application Hard Gate；L4/L5 自身也受预算 gate。
- 真实 E2E 覆盖 25K/1M、L1-L5、manual compact/no-op、HistoryRead、overflow、incremental facts、crash、resume、old schema、model switch、Headless/TUI adapter。
- 删除固定 258K/Projection/old history/unavailable summarizer/old overflow 等直接失效路径；无 compatibility、Manager/Registry/Job/FSM 或未来占位。

## 禁止

- 不实现 Memory/retrieval、Persistent Runtime Recovery、Timeline GC、Artifact lifecycle、background agent、Subagent/Multi-Agent、全量 model catalog。
- 不修改冻结工作包文字，不创建额外 retry/v2 Feedback。
- 不为既有无关测试失败擅自重构 TUI renderer、Permission、Plan、Todo 或 Hook。
- 不执行 commit、push、merge、rebase、tag、release，不移动工作包到 archive。

## 验证

逐项执行 Task 7～10 Checklist，至少包括：

```powershell
python -m pytest tests/test_t09_1_context_protocol_e2e.py -q
python -m pytest tests/test_architecture_boundaries.py -q
python -m pytest -q
```

再执行 cleanup `rg` 与 UTF-8 guard。所有命令记录精确 passed/failed/skipped 和耗时。当前拆包基线有 3 个既有 TUI RGB ANSI 断言在非交互 Windows 管道失败；最终仍失败时不得宣称全量通过，也不得把无关修复混入 T09-1，必须提供可复现证据并保持对应 Checklist 未勾选。

## Feedback

首次创建 `feedback/W07-integration-docs-verification-feedback.md`。内容需让人工审查者理解：实际能力与调用链、关键数据/状态变化、采用原因、修改文件、每条验证命令及精确结果、Checklist 状态、任务书差异、未完成项/风险、遗留清理与 UTF-8 guard。返工只在同一文件末尾追加新章节。
