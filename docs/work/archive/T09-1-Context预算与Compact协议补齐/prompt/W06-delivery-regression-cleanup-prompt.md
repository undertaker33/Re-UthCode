# W06 Worker Prompt：端到端验收、文档同步与遗留清理

你负责按顺序执行 T09-1 的 T07、T08。T01～T06 必须全部完成并有 Feedback。先验收/文档 T07，再做 T08 清理；不做 Git 写入、工作包归档或虚假反馈。

## 实施起点与事实核对

以用户实际派发本 Prompt 时的当前仓库状态为实施起点，不要求 HEAD 等于任何固定 SHA，也不要求 checkout 历史 Commit。完整读取全部前置 Feedback 与下列文件后，必须重新核对当前真实 `src/ + tests/`；只有源码实质变化已经使冻结产品语义、架构边界或 T07/T08 完成范围失效时，才停止相关范围并按 Feedback 规则报告。普通后续 Commit、Feedback 追加或 Checklist 勾选不构成基线冲突。

## 开始前必须完整读取

- `AGENTS.md`、`docs/README.md`、`docs/Context-Index.md`、`docs/OutstandingDebtList.md`、`docs/rules/WorkPackageRules.md`。
- T09-1 任务书、Spec、Tasks、Checklist、全部 W01～W05 Feedback。
- `src/ + tests/` 相关最终实现、文档维护映射命中的 Tools、用户手册、Core Design、A03/A04、Eval。

## T07：验收与文档

- 从正式 Headless/Application/command 入口覆盖 ordinary、tool loop、L4/catch-up、L5、HistoryRead、manual no-op/success、overflow once、hard fail、resume。
- diagnostics/status 只含 configured/provider/effective input、provider output/combined、count source/allowance、Auto/Hard、Timeline id/coverage/reason/outcome；禁止 raw Transcript、summary、Tool Result、secret、异常正文。
- Eval 保持并列指标，不新增 total score，不把 tuning default 写成产品成功阈值。
- 按 `docs/README.md` 维护映射同步 `docs/Tools.md`、用户 config/commands、T09 Core Design、A03/A04 和 Context Index。
- 执行 Checklist T07 定向、架构、T05/T06/T08 回归与全量测试；未运行项明确写出。

## T08：最终清理

- 扫描并删除 production 固定 258K authority、Projection/CanonicalHistory、old history writer、sync-only Compact、`summarizer_unavailable`、重复入口/export/wrapper/alias。
- 确认 bundled official model metadata、本地 catalog、hardcoded official model window 路线在源码、测试、当前事实文档和 `OutstandingDebtList.md` 中持续不存在，且未重新登记为 future debt；不要重复删除已不存在的条目。
- 重新盘点所有被 T09-1 实际改变的欠账：`T02 Slash Command / TUI` 只移除已回补的 `/compact` 部分并保留仍成立的 `/memory`、`/dream`；`B01 私有测试集 v0` 中生产 Compaction 相关部分按真实结果删除或更新；三条 T09 Context 欠账只有实现完成、对应 Checklist 完成且 Feedback 有真实验收记录时才删除。
- 其它受影响条目统一按“完全回补则删除、部分改变则更新内容或触发条件、仍成立则保留、用户明确取消则删除且不得转登记”处理，禁止因一条记录部分完成而整条误删。
- 证明 Timeline 产品 records 只有三类；无持久 Compact FSM/Job/pointer、独立 compaction model、跨 Provider fallback、无调用方 Manager/Registry/Scheduler。
- 保护 Permission、Plan/Todo、Runtime Hook、其它 Slash Commands 和 TUI rendering。
- 清理后重跑最小受影响、架构、全量测试。

## 文档与状态规则

- 中文 Markdown 修改后运行 UTF-8 guard，检查 replacement character、常见乱码和 fence balance。
- T07、T08 始终写同一个与 Prompt 同名的 `feedback/W06-delivery-regression-cleanup-feedback.md`；首次创建，返工只在末尾追加章节。
- Feedback 分章节列 T07/T08 实际改动、精确命令、passed/failed/skipped、未验证项、风险、遗留问题。
- 只有全部任务完成且 Feedback 齐全，才把 Context Index 更新为 `implemented_unarchived`；工作包继续留在 `docs/work/`，等待用户手动归档。
