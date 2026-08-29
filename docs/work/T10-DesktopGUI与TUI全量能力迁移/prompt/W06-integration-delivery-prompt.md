# W06 Desktop 全链路验收与交付收口提示词

请在 `D:\project\Re-UthCode` 严格串行完整实施 T10 的 T09 -> T10 -> T11，完成主链接入、Windows Feature Parity E2E、全量回归、文档与遗留负担清理。

## 开工前必须读取

1. `AGENTS.md`、`docs/README.md`、`docs/Context-Index.md`
2. `docs/rules/WorkPackageRules.md`、`docs/rules/UserDecisionBoundary.md`、`docs/OutstandingDebtList.md`
3. T10 原始需求、Spec、Tasks、Checklist 和本 Prompt
4. W01～W05 全部 Feedback
5. A02/A03/A04/TUI 命中的当前上下文、用户手册与根 README 维护映射
6. T01～T08 全部生产代码/tests 与当前构建产物配置

## 已确认决策

- 只接入当前已实现 UthCode 能力，不得从原型/外部产品增加未来入口。
- Desktop 唯一主链是 Renderer -> Preload -> Main -> Bridge -> Application -> Core -> AgentEvent，不允许任何第二 authority。
- Windows 11 x64 是 Installer/真实 E2E 平台；无签名时只标 dev/RC。
- 产品无卡片矩阵、设计说明文案、fake state、account/usage 或浏览器 alert/prompt/confirm。
- 能力欠账为无；Persistent Runtime Recovery 继续是既有欠账，本包不实施。

## 修改范围

- 仅修改 Tasks T09～T11 列出的接入缺口、tests、当前事实/用户文档、Context Index、Checklist 和本 Worker Feedback。
- 首次实施创建 `feedback/W06-integration-delivery-feedback.md`；返工只追加。
- 只勾选已验证 T09～T11 和未由前序勾选但本轮重新取得精确证据的项。
- 禁止修改冻结文字、自动归档或执行 commit/push/merge/rebase/tag/release。

## 实施与验证

1. 先完成真实主链离线 E2E，删除 fake/stub/dead IPC，再进行 Windows Installer E2E，不在验收阶段新建架构机制。
2. 逐条执行 Checklist T09/T10 Feature Parity/失败路径/人工清单；未有真实环境的项标记未验证并不得勾选。
3. 执行 Python 定向、架构、全量、compileall、pip check、diff check；Desktop `npm ci`/typecheck/tests/E2E/build/package/make；PyInstaller 和 packaged Runtime/Installer smoke。
4. 按 Checklist 做重复 authority、卡片/文案、未来占位、兼容/dead code 静态检查，删除 T10 可再生成临时产物。
5. 按 `docs/README.md` 同步根 README、用户手册、A04 与实际命中的 A02/A03/TUI 当前事实；最后更新 Context Index 为 implemented_unarchived。
6. 对所有改动 Markdown 执行 UTF-8、replacement/mojibake、fence 平衡检查，保留用户手动归档 dirty changes。

## Feedback 要求

Feedback 必须面向人工审查说明最终链路/状态所有权、Windows 环境与 Installer 结果、Feature Parity 与失败路径、人工验收、修改/删除文件、所有精确命令与结果、Checklist 证据、未验证项、风险、文档同步、能力欠账与遗留负担清理。不得将未运行的真实 Windows 验收写成通过。
