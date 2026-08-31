# W05 GUI Review 与 Integration 实施提示词

请在 `D:\project\Re-UthCode` 严格串行完整实施 F02 的 T08 → T09。先完成范围内 GUI code review 并关闭 finding，再接入唯一 Desktop 生产链；不执行最终人工/CDP 验收和文档收尾。

## 开工前必须读取

1. `AGENTS.md`、`docs/README.md`、`docs/Context-Index.md`、`docs/rules/WorkPackageRules.md`、`docs/rules/UserDecisionBoundary.md`、`docs/OutstandingDebtList.md`。
2. F02 原始需求、Spec、Tasks、Checklist 和本 Prompt。
3. W01～W04 全部 Feedback 与实际 diff/tests。
4. `desktop/src/**`、`interfaces/desktop/**` 和 F02 新公共投影修改点。
5. `tests/test_architecture_boundaries.py` 与当前 Desktop/Python integration tests。

## 已确认决策

- review 限于 F02 直接触达生产链，不扩成全仓重构或通用安全审计。
- P0/P1/P2 范围内 finding 必须关闭；结果落实到代码/测试，不只写报告。
- 大文件不按行数机械拆分；只有独立当前职责、调用方和测试边界同时成立时才做私有局部拆分。
- 正式链固定为 Renderer → DesktopApi → 既有 transport → Bridge → Application → Core，无 Desktop Core facade 或第二 runtime/state system。

## 修改范围

- T08 可审查/修改 Tasks 指定范围；T09 只做跨层接线和 F02 回归修复。
- 不修改 T10 冻结文件、现有 Main/Preload/Python runtime（除非命中原始编码停止条件并先停止报告）、CDP harness 或 current-facts docs。
- 若 finding 属于 W01～W04 的产品实现缺陷，W05 停止对应范围并记录在 W05 Feedback，交由用户重新派发对应原 Prompt；被重新派发的 Worker 在自己的原 Feedback 追加返工记录，W05 不并发跨写或代写其他 Worker Feedback。
- 不新增 Manager/Store/EventBus/Registry/Protocol/通用 streaming/modal/menu framework。
- 未经用户明确要求，不执行任何 Git 写操作。

## 实施与验证

1. 按 correctness、architecture、maintainability、privacy 分级审查，记录文件/证据/severity。
2. 关闭所有范围内 P0/P1/P2，删除第二 authority、旧链路、无调用方与不可达代码；复查秘密安全。
3. T08 通过后再执行 T09 唯一生产链接线，覆盖 AskUser、Plan、Context/Compact、Session、command、Settings、Todo/Tool/Mode。
4. 执行 Python/Architecture tests、Desktop typecheck/tests、否定扫描与 `git diff --check`。
5. 首次执行创建 `feedback/W05-gui-review-integration-feedback.md`；只勾选 T08/T09 已验证 Checklist。

## Feedback 要求

按 severity 列出 finding 与关闭证据；说明保留/拆分大文件的真实职责、唯一生产链、删除内容、修改文件、精确测试、Checklist、未关闭 P3/风险与遗留清理。返工只追加。
