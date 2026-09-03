# W02 Application Context 与 Usage 实施提示词

请在 `D:\project\Re-UthCode` 严格实施 F03 的 T02。W01 完成后，完成 prospective ordinary request 验证、oversized Provider subpass、manual multi-epoch、usage 双投影、telemetry 与 `generation.py` 一次性职责拆分。

## 开工前必须读取

1. `AGENTS.md`、`docs/README.md`、`docs/Context-Index.md`、WorkPackageRules 与 UserDecisionBoundary。
2. F03 原始需求、Spec、Tasks、Checklist、本 Prompt 和 W01 Feedback。
3. A03、A04、GUI 当前上下文。
4. T02 列出的 Application/Core/Bridge 源码与测试。

首次派发后遵守实施冻结；Checklist 只勾选精确验证项。

## 已确认决策

- candidate commit 前构建 prospective ordinary request；before/after 固定 exact/exact 或 local/local。
- prospective 构建不得发布临时 Context status/diagnostics；无 reduction 不 append。
- oversized Provider subpass 由 Application 使用同一 tool-free、Hard-gated 路径驱动，最终只提交一个完整 Turn Fine。
- manual Compact 在现有 epoch 上限内追赶 retained target，不调 profile 参数。
- 方案 A：Last Provider Request Usage 覆盖 ordinary 与 Compact/L5。ordinary 用累计 `UsageUpdated` delta；Compact/L5 用 terminal usage；Core 事件语义不变。
- Current Working Context 在 Compact 后重新构建/计数，不接受上一请求 usage 覆盖。

## 修改与禁止范围

- 只修改 T02 文件及其必要直接测试；不修改 Desktop Renderer、不删除 history wrapper（留给 W06）。
- helper 不持 Application/Session/Timeline state；`UthCodeApplication` 保持唯一 authority。
- 不暴露 Provider raw details，不新增公共 Agent 协议、持久 telemetry 或第二 Application facade。

## 实施与验证

按 request helper → compaction helper → candidate lifecycle → manual continuation → usage projection → Bridge/telemetry 顺序实施。运行 Checklist T02 定向 tests、架构与 diff 检查。首次创建 `feedback/W02-application-context-usage-feedback.md`，只勾选 T02。

## Feedback 要求

说明同源计量、无副作用 prospective 构建、oversized orchestration、manual stop、双 usage 来源、DTO/telemetry、文件拆分及精确验证。记录任何任务书不一致或未验证项；返工只追加。
