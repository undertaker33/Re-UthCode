# W06 Acceptance 与 Cleanup 实施提示词

请在 `D:\project\Re-UthCode` 严格串行完整实施 F02 的 T10 → T11。复用现有 CDP/packaged harness 完成自动与真实 Desktop 验收，再执行遗留清理、文档同步和全量回归；不得自动归档。

## 开工前必须读取

1. `AGENTS.md`、`docs/README.md`、`docs/Context-Index.md`、`docs/rules/WorkPackageRules.md`、`docs/rules/UserDecisionBoundary.md`、`docs/OutstandingDebtList.md`。
2. F02 原始需求、Spec、Tasks、Checklist 和本 Prompt。
3. W01～W05 全部 Feedback、实际代码和 tests。
4. T10 W06 Feedback 中现有 packaged/CDP isolation、launcher、deadline 证据；只作 harness 使用参考，不修改 T10 冻结文件。
5. `desktop/package.json`、现有 CDP fixture/driver/packaged runner/acceptance tests 与 docs 维护映射命中的当前事实文档。

## 已确认决策

- 必须复用现有 packaged/CDP acceptance 链，不创建第二 harness；AskUser 硬切后旧 `allow_other` fixture 必须删除。
- 自动与人工矩阵逐项记录；未运行、缺真实 Provider或缺干净机条件的项目不得描述为通过。
- F02 能力欠账为无，OutstandingDebtList 保持不变；T10 冻结 Checklist/Feedback 不修改且仍按其真实未完成项分类。
- 文档只描述最终代码事实；Agent 不自动归档、不执行未经授权的 Git 写。

## 修改范围

- 独占 Tasks T10/T11 列出的现有 CDP/packaged scripts/tests、current-facts docs、F02 Checklist 与本 Worker Feedback。
- 验收发现生产缺陷时，停止该场景并记录在 W06 Feedback，交由用户重新派发对应 W01～W05 原 Prompt；被重新派发的 Worker 在自己的原 Feedback 追加返工记录，W06 不静默跨域重写或代写其他 Worker Feedback。
- 不修改 T10 原始需求/spec/tasks/checklist/prompt/feedback，不新建 E2E framework、产品能力或未来抽象。
- 保持用户已有未跟踪 `desktop/.runtime`、`.webpack`、`node_modules`、`out`、`packaging/.build` 等构建内容；只使用，不擅自清理。

## 实施与验证

1. 更新现有 CDP fixture/driver/runner，使正式脚本实际覆盖 F02 新合同和主要交互，不只跑不足的 visual 子流。
2. 运行 full pytest、Desktop typecheck/tests、现有 packaged/CDP acceptance；记录精确命令、exit code、passed/failed/skipped。
3. 执行原始需求真实 Desktop 矩阵；对不可执行项保留未勾选并说明原因。
4. 执行旧符号/第二 authority/内部 ref/raw arguments/过度抽象否定扫描、architecture/compile/pip/diff checks。
5. 按 `docs/README.md` 更新 Tools/A02/A03/Context Index 及其他真实命中文档；核对 OutstandingDebtList 不变。
6. 对所有修改 Markdown 执行 `uth-utf8-guard` 检查。
7. 首次执行创建 `feedback/W06-acceptance-cleanup-feedback.md`；只勾选 T10/T11 及最终已有证据的 Checklist。

## Feedback 要求

说明 CDP/packaged harness 变更与覆盖、真实人工矩阵、所有精确自动结果、否定扫描、文档同步、UTF-8 guard、工作包状态、未验证项和风险。不得伪造人工结果或写入真实 API Key。返工只追加。
