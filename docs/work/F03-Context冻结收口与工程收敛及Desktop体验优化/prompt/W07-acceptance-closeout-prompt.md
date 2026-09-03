# W07 Acceptance 与冻结收口提示词

请在 `D:\project\Re-UthCode` 严格串行实施 F03 的 T08 → T09。W06 完成后执行全量回归、measurement、真实 Desktop 验收、否定扫描和文档收口；不要新增产品能力。

## 开工前必须读取

1. AGENTS、`docs/README.md`、Context Index、WorkPackageRules、UserDecisionBoundary、OutstandingDebtList。
2. F03 全部冻结文件、本 Prompt、W01～W06 Feedback 与 Checklist 当前状态。
3. A03、A04、GUI 当前上下文、所有受影响用户手册/核心设计/Tools。
4. `desktop/package.json`、CDP/visual/packaged scripts 与 Context measurement 入口。

## 已确认决策与范围

- 只补齐当前 F03 验收能力；不建立第二 harness、完整 Eval 平台或固定产品阈值。
- 必须如实区分自动、CDP、packaged、真实 Provider、人工视觉与未验证场景。
- 文档以最终 `src/ + tests/` 为准；只修改受影响当前事实，不改其他冻结工作包。
- F03 无能力欠账变化时保持 OutstandingDebtList 不变。
- 不自动归档，不执行未经明确要求的任何 Git 写操作。

## 验收顺序

1. 运行 T08 Python full/architecture/compileall/pip check 与 Desktop typecheck/npm test/package/适用 make。
2. 运行 Context exact/local/no-reduction/oversized/malformed/projection/cache measurement。
3. 运行 Desktop wide/narrow、theme/language/zoom/reduced-motion、drag/Focus、Settings、copy、scroll、keyboard/IME/ARIA 的 CDP/visual/packaged acceptance。
4. 对不可用环境保留未勾选项并写明原因/风险。
5. 完成 T09 否定扫描、文档维护映射、Context Index 全量状态、UTF-8/fence/link/secret/diff scope 检查。
6. 首次创建 `feedback/W07-acceptance-closeout-feedback.md`；按 T08→T09 记录，只勾选有证据项。

## Feedback 要求

列出全部命令、exit code、精确计数、报告/截图路径、measurement before/after、结构职责/file size 变化、Checklist、未验证项、风险与清理结论。返工只在同一 Feedback 末尾追加，禁止覆盖旧事实。
