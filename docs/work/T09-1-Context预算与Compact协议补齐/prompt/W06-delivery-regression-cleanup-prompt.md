# W06：端到端交付、文档与遗留清理 Prompt

请完整读取并执行本文件。你负责 T07 `[端到端验证]` → T08 `[遗留负担清理]`，严格先完成正式 e2e、diagnostics、Eval 与文档同步，再删除阶段性/兼容负担并做最终全量回归。

## 必须先读

1. `AGENTS.md`
2. `docs/README.md`、`docs/Context-Index.md`、`docs/OutstandingDebtList.md`
3. `docs/rules/WorkPackageRules.md`
4. 本工作包原始需求、Spec、Tasks、Checklist
5. W01～W05 全部 Feedback；确认 T01～T06 Checklist 已完成，否则停止并报告依赖。
6. `docs/Tools.md`、`docs/core-design/T09-context-engineering.md`、A03/A04 当前事实、用户手册 commands/configuration，以及 `docs/README.md` 维护映射命中的其它文档。
7. T07/T08 Tasks 列出的源码、eval 与测试。

使用 Conda 环境 `re-uthcode`。修改 governed Markdown 前后必须使用 `uth-utf8-guard`，保持 UTF-8、无 replacement/mojibake、fence 平衡，不重写无关内容。

## 冻结决策

- diagnostics/Eval 只消费安全投影，不含 Transcript、summary、Tool Result、secret 或未脱敏异常正文。
- Eval 保持并列维度，不建立总分，不把 tuning default 变成产品成败阈值。
- 文档只能描述已经由 `src/ + tests/` 证明的当前事实。
- old v1 Session incompatible；无 migration/dual path/compat alias。
- Timeline 只有三类产品 records；无持久 Compact FSM、独立 compaction model、跨 Provider fallback。
- Persistent Runtime Recovery、Memory/retrieval、GC、Subagent/Multi-Agent 仍为 Out of Scope。
- 未经用户确认不归档、不执行 Git 写入。

## T07 实施要求

- 完成正式 Headless/Application/command e2e：ordinary、tool loop、L1-L5、B′、manual success/no-op、HistoryRead、overflow once、hard unsafe、resume fresh Run、model switch frozen C。
- fake Provider 明确记录 call count/request shape；真实网络调用不作为 CI gate。
- public status/diagnostics 与 Eval 使用动态 C/E/count/Auto/Hard/Timeline/pressure 字段，并通过 secrecy test。
- 按 `docs/README.md` 维护映射同步用户手册、Core Design、Tools、A03/A04、Context Index，以及所有仍把 fixed 258K/Projection/summarizer unavailable 当当前事实的非冻结文档。
- 运行 Checklist 指定定向、架构、T05/T06/T08 回归和全量 pytest；精确记录结果。

完成 T07 并有证据后，才进入 T08。

## T08 实施要求

- 用 `rg` 盘点 fixed 258K constant/文案、Projection、history.jsonl、summarizer_unavailable、old exports、migration/dual path、Compact FSM/Job/pointer。
- 删除生产旧 authority、旧 Session 新写入、同步-only compact、不可达分支、重复 request builder、旧 tests/fixtures 和 compatibility alias；冻结原始需求/Spec/Tasks/Prompt 里的历史字面量不修改。
- 测试构造 old v1 incompatible 可以保留 `history.jsonl` 字面量，但必须在 Feedback 明确列出。
- 复核没有第四种 Timeline record、独立 compact model、cross-provider fallback、Manager/Registry/Scheduler/Event Bus 或范围外 Permission/Plan/Hook/TUI 重构。
- 清理后重跑受影响定向、architecture 和全量 pytest。

## 工作包外部状态维护

- 只有 T01～T08 Checklist 全部完成且 W01～W06 Feedback 齐全后，才把本包回补的三项 T09 Context 欠账从 `docs/OutstandingDebtList.md` 删除；不要新增一般 Out of Scope 欠账。
- 同样只在全部完成后把 `docs/Context-Index.md` 中 T09-1 从 `not_implemented` 更新为 `implemented_unarchived`，写明精确验收证据。
- 工作包仍留在 `docs/work/`，等待用户手动归档。

## Feedback 与 Closeout

首次执行时创建：

`docs/work/T09-1-Context预算与Compact协议补齐/feedback/W06-delivery-regression-cleanup-feedback.md`

Feedback 分 T07/T08，说明实际 e2e、diagnostics/Eval、文档同步、删除项、`rg` 证据、精确测试命令与结果、未验证项、风险和遗留问题。只勾选有证据完成的 T07/T08 Checklist，不修改其它冻结文字。

运行 UTF-8 guard 并在 Feedback/交付报告记录：files checked、result、repaired encoding issues。若 guard 或全量回归失败，不得声称包级交付完成。

未经用户明确要求，不执行 Git commit/push/merge/rebase/tag/release，不移动或归档工作包。
