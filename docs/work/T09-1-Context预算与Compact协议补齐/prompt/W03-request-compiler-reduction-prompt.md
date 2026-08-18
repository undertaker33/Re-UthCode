# W03：最终请求与确定性 Reduction 实施 Prompt

请完整读取并执行本文件。你负责 T03，在 W01/W02 已集成并通过各自验收后，实现 final request accounting、Context Compiler 动态 working set 与 L1-L3；不要接通生产 L4/L5。

## 必须先读

1. `AGENTS.md`、`docs/README.md`、`docs/Context-Index.md`、`docs/rules/WorkPackageRules.md`
2. 本工作包原始需求、Spec、Tasks、Checklist
3. W01、W02 Feedback 和已勾选 Checklist；若缺失或失败，停止并报告依赖未满足。
4. `docs/core-design/T09-context-engineering.md`、`docs/context/A03-State/State-Context.md`
5. T03 Tasks 列出的源码/测试及 Tool Result externalization 实现。

使用 Conda 环境 `re-uthcode`。不得覆盖前序 Worker 改动。

## 冻结决策

- Context Compiler 是唯一 model-view builder；Integration 不重新编译 Context。
- count/Gate 基于最终 Provider-visible `GenerationRequest`，覆盖 system/messages/tools、requested output 和已知结构 overhead。
- 自动顺序是 assemble/count/Gate → L1-L3 → rebuild/recount/re-Gate → 必要时 L4-required。
- L1 复用 Tool Result externalization；L2 deterministic bounded preview shrink/mask；L3 只省略 inactive complete Turn/semantic unit。
- protected context、current Turn、ToolCall/ToolResult pair 不可拆。
- L1-L3 后仍 Auto pressure 即使 Hard-safe 也必须返回 L4-required；清除 Auto 且 Hard-safe 不执行 L4。
- required facts 自身 Hard-unsafe 时 fail closed，Provider call count 为 0。

## 修改范围

只修改 T03 Tasks 文件及必要的机械 test helper。不得写 fake production summarizer、Timeline checkpoint、L5、HistoryRead、manual command、TUI 或 overflow retry。

## 实施要求

- 以测试驱动 259K→257K 仍 Auto pressure、L1-L3 clear Auto、hard unsafe、25K/1M、Tool pair boundary 等场景；具体 tuning 数字来自 T01 单点 policy。
- local canonical estimator 和 Provider count 都针对最终 request shape；不可用“历史正文 token”代替 final request count。
- 每次 reduction 从权威 Transcript/Timeline/runtime facts rebuild，不用预估差值声明安全。
- L2/L3 必须 deterministic、idempotent 或具有明确的单调边界；重复 prepare 不得产生无界漂移。
- diagnostics 只输出 count/token/source/id/reason，不包含 raw context、summary 或 Tool Result。
- 不重复实现 Tool Result artifact 存储或 read Tool。

## 验证与交付

完成 T03 Checklist，并重跑 W01 budget tests、W02 history/timeline tests 和架构测试，确认新 Compiler 对 dynamic C/E 与 Session v2 同时成立。

首次执行时创建：

`docs/work/T09-1-Context预算与Compact协议补齐/feedback/W03-request-compiler-reduction-feedback.md`

Feedback 以请求构建/Gate/reduction 状态流说明实现，记录精确测试结果、未验证项、任务书差异与遗留负担。只勾选 T03 有证据的 Checklist，不改冻结文本。

未经用户明确要求，不执行 Git 写入或归档。
