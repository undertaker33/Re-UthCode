# W04：语义 Compaction、B′ 与 Timeline Aging 实施 Prompt

请完整读取并执行本文件。你负责 T04 → T05，必须严格按顺序：先完成生产 L4 与 bounded catch-up，再实现 L5 Timeline Aging 与 HistoryRead。

## 必须先读

1. `AGENTS.md`、`docs/README.md`、`docs/Context-Index.md`、`docs/rules/WorkPackageRules.md`
2. 本工作包原始需求、Spec、Tasks、Checklist
3. W01～W03 Feedback；确认 T01～T03 Checklist 已完成，否则停止并报告依赖。
4. `docs/context/A03-State/State-Context.md`、`docs/context/A04-Orchestration/Orchestration-Context.md`
5. T04/T05 Tasks 列出的全部源码和测试；完整读取现有 Core awaitable preparer/overflow 测试与 `tool_result_read.py`。

使用 Conda 环境 `re-uthcode`，保留前序 Worker 改动。

## 冻结决策

- L4/L5 复用当前主 Provider/model/C；active Turn 使用 frozen snapshot，idle manual 由 W05 接 current selection。
- Compact request 独立、tool-free、bounded，只执行 Hard Gate，不递归 Auto compact。
- B′ 一次 orchestration 支持 1..N bounded complete raw epochs，每批 commit 后 rebuild + Auto/Hard re-gate。
- 只允许调用栈局部 attempts/coverage/previous estimate/current epoch/cancellation；不得持久 Compact FSM/Job/pointer。
- 每个 transaction derived records first、ActiveCheckpoint last；cancel/parse/coverage/durability failure 不生成伪 commit。
- finite breaker 后 Auto unresolved + Hard-safe 可发送并记录原因；Hard-unsafe fail closed。
- L5 由 Fine Timeline pressure 独立触发，只重读 raw Transcript，禁止 summary-of-summary。
- HistoryRead 只允许 current Session exact opaque raw Transcript ref bounded read，不搜索、不跨 Session。

## T04 实施要求

- 复用 Core 已有 sync-or-awaitable request preparer/overflow hook；只做必要 contract 收紧，不建立第二套 async loop。
- 构造独立 compact prompt/request，`tools=()`；output schema 必须 one SemanticEntry per covered Turn。
- 校验 contiguous complete coverage、refs existence/ownership、summary bound；任何 invalid candidate 都不 append。
- L4 epoch input 使用 raw Transcript，bounded input/output 适应 T01 profile；retained target 要形成明显 headroom。
- one epoch 与 multi-epoch 每批 checkpoint-last，之后从 authority rebuild ordinary request；测试 no-progress/repeated failure/no-safe-epoch/cancel。
- Compact request overflow 不递归 compact；可在当前 attempt 内选择更小 safe epoch，仍失败则受控返回。

完成并验证 T04 后，才进入 T05。

## T05 实施要求

- Fine Timeline logical usage > F 可独立触发 L5；只选 old complete L4 epoch。
- L5 evidence 从 refs 回读 raw Transcript，不能只把已有 summary 再总结。
- 成功写 EpochMacroSummary 后最后写 checkpoint；logical view supersede coverage，physical records 不删除。
- raw epoch 自身无 safe bounded request 时返回 no-safe-epoch，不换模型。
- 新 HistoryRead Integration 参照 ToolResultRead 的 opaque ref/ownership/bounded/page 模式，但保持不同 ref 域与存储入口。
- Application 注册 reserved read-only Tool；HistoryRead output 不递归 externalize，权限/Tool batch 仍走现有链路。

## 修改范围

只修改 T04/T05 Tasks 文件及必要 import/export/test fixture。不得接 `/compact` command/TUI、ordinary overflow retry、增量 request-boundary persistence 或包级文档；这些属于 W05/W06。

## 验证与交付

先执行并记录 T04 Checklist，再执行 T05 Checklist；之后联合运行 compaction/timeline/history-read/application-tools/e2e/architecture tests。不要用真实网络 Provider 作为必过条件。

首次执行时创建：

`docs/work/T09-1-Context预算与Compact协议补齐/feedback/W04-semantic-compaction-aging-feedback.md`

Feedback 分 T04、T05 两节记录调用流、transaction、breaker、raw provenance、HistoryRead 安全边界、精确测试结果和风险。只勾选已证明的 T04/T05 Checklist；不改冻结文本。

未经用户明确要求，不执行 Git 写入或归档。
