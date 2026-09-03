# W06 Cleanup 与主流程接入提示词

请在 `D:\project\Re-UthCode` 严格串行实施 F03 的 T06 → T07。等待 W01～W05 完成后，先做高置信清理，再完成唯一生产链集成验证。

## 开工前必须读取

1. AGENTS、docs 路由、WorkPackageRules、UserDecisionBoundary。
2. F03 冻结文件、本 Prompt、W01～W05 Feedback。
3. A03、A04、GUI 当前上下文及 T06/T07 列出的源码与 tests。

## 已确认决策与范围

- 删除 `application/history.py`，调用方直连已有 Core history 转换函数；不留 alias/facade。
- 删除旧同步 compaction 与迁移后无调用方内容，不为历史测试保留 production API。
- KEEP Agent Loop、Session writer/durability、Provider composition/fake、legacy reader、Permission/Secret/Hard Gate。
- 不重构 TUI，不做全仓安全审计，不新增兼容层或抽象。
- 主链必须覆盖 ordinary/manual/auto/overflow/L5、ordinary+Compact/L5 usage、Desktop status/state/lifecycle/settings/copy/layout。

## 实施与验证

1. 完成 T06 references 清理与高价值回归，只勾选 T06 有证据项。
2. 再执行 T07 跨层集成、identity、durability、secret、architecture 与否定扫描。
3. 运行相关 Python/Desktop 定向与完整集成测试、`git diff --check`。
4. 首次创建 `feedback/W06-cleanup-integration-feedback.md`，按 T06→T07 顺序记录与勾选。

## Feedback 要求

说明删除依据、KEEP 边界、唯一生产链、跨层验证、精确结果、Checklist、任务书差异、未完成项、风险及遗留负担；返工只追加。
