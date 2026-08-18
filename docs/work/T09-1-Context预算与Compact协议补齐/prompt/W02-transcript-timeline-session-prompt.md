# W02：Transcript、Timeline 与 Session v2 实施 Prompt

请完整读取并执行本文件。你负责 T02，严格完成 Transcript/Timeline Core contract 与 Session v2 hard cut，不提前接通 L1-L5、manual Compact 或命令生命周期。

## 必须先读

1. `AGENTS.md`
2. `docs/README.md`
3. `docs/Context-Index.md`
4. `docs/rules/WorkPackageRules.md`
5. 本工作包原始需求、Spec、Tasks、Checklist
6. `docs/context/A03-State/State-Context.md`
7. `src/uthcode/core/history.py`、`core/prompt.py`、`application/history.py`、`application/sessions.py`、`integrations/session_files.py`
8. `tests/test_history_contract.py`、`tests/test_session_files.py` 及所有直接使用 Canonical History/Projection 的测试。

使用 Conda 环境 `re-uthcode`。以当前 `src/ + tests/` 为事实，保留用户和 W01 已有改动；只解决必要交叉 typing/import。

## 冻结决策

- 新生产 authority 是 raw Transcript + derived append-only Timeline；不保留 Canonical History/Projection compatibility alias。
- Timeline 产品 record 只能是 `SemanticEntry`、`EpochMacroSummary`、`ActiveCheckpoint` 三类。
- 每个 L4/L5 transaction 必须 derived records first、checkpoint last；latest valid checkpoint 决定 committed logical view。
- fresh Session 使用 `transcript.jsonl` 与 `timeline.jsonl`；old v1 `history.jsonl` deterministic incompatible，无 migration、dual read、dual write。
- Transcript 只持久已闭合语义事实；ToolCall 与 matched ToolResult 是不可拆 semantic group。
- 复用现有 lock/fsync/identity reconciliation/quarantine/close-reopen recovery；不创建 Runtime checkpoint。

## 修改范围

只修改 T02 Tasks 列出的文件和必要的机械调用方/test fixture 跟随。不得实现 Provider model calls、L4/L5 prompt、HistoryRead、async command、overflow retry 或文档收口。

若大面积调用方因 hard cut 无法编译，可做最小 contract migration，但不能借此保留旧 wrapper；超出机械跟随时在 Feedback 记录并停止相关范围。

## 实施要求

- 先为 Transcript strict sequence/ownership/semantic unit 和 Timeline record/checkpoint/trailing transaction 写失败测试。
- Session schema bump 后，old v1 必须在明确入口稳定拒绝；测试 fixture 可以构造 old file，但生产路径不能读写它。
- Timeline physical append-only；loader 不删除 trailing records，只在 logical view 忽略未提交 transaction。
- checkpoint validation 必须能证明 refs/coverage/active set 属于当前 Session 与已存在 Transcript facts。
- unknown append durability 不得自动重试；现有 quarantine 对 Transcript、Timeline、Runtime、Tool Result 等新语义写入统一 fail closed。
- `core/` 只定义 immutable values/validation，不读写文件。

## 验证与交付

执行 T02 Checklist 的全部测试和操作性断言，并重跑 `tests/test_architecture_boundaries.py` 以及现有 Session command/application runs 定向测试中受 hard cut 影响的部分。

首次执行时创建：

`docs/work/T09-1-Context预算与Compact协议补齐/feedback/W02-transcript-timeline-session-feedback.md`

Feedback 说明文件格式、commit/recovery 流程、old v1 行为、durability 语义、实际迁移的调用方、精确测试结果与遗留风险。只勾选 T02 已验证 Checklist；不得修改冻结工作包文本。

未经用户明确要求，不执行 Git 写入或工作包归档。
