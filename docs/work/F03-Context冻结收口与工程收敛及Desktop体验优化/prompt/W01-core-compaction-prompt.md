# W01 Core Compaction 实施提示词

请在 `D:\project\Re-UthCode` 严格实施 F03 的 T01。只完成 Core compaction 归一、strict multi-turn、oversized 纯 Core 规划/合成与旧同步路径删除，不进入 Application 或 Desktop。

## 开工前必须读取

1. `AGENTS.md`、`docs/README.md`、`docs/Context-Index.md`。
2. `docs/rules/WorkPackageRules.md`、`docs/rules/UserDecisionBoundary.md`。
3. F03 原始需求、Spec、Tasks、Checklist 和本 Prompt。
4. `docs/context/A03-State/State-Context.md`。
5. T01 列出的 Core 源码与测试；核对当前 HEAD 与任务书关键事实。

首次派发后，原始需求、Spec、Tasks、Prompt 和 Checklist 文字/结构冻结；Checklist 只允许勾选已有且有精确证据的条目。

## 已确认决策与范围

- durable one-Turn-one-Fine、完整 refs、L5 granularity 不变；oversized 中间状态只存在于进程内。
- multi-turn 必须显式 entries，数量/顺序/turn_id/refs/coverage 完全匹配；单 Turn 仅保留有真实调用方的有限兼容。
- 删除 `compact()`/`_compact_locked()`，但 production L4/L5 共用的 single-flight 不能删除。
- W01 只提供 Core subpass planning/validation/final synthesis；Provider subpass orchestration 属于 W02。
- 不新增 Summary Graph、Memory、持久 chunk、兼容 alias 或参数调优。

## 实施与验证

1. 先用 strict parsing、oversized success/failure/cancel/full-refs tests 固定合同。
2. 收敛 Core 模块与公共导出，删除旧同步路径及仅服务它的测试。
3. 运行 Checklist T01 的定向 pytest、reference/import/architecture 检查和 `git diff --check`。
4. 首次执行创建 `feedback/W01-core-compaction-feedback.md`；仅勾选 T01 已验证项。

## Feedback 要求

说明 Core 模块边界、strict multi-turn、oversized 数据流、删除内容、修改文件、精确测试/扫描结果、Checklist、偏差、未完成项、风险和遗留负担。返工只在同一文件末尾追加。
