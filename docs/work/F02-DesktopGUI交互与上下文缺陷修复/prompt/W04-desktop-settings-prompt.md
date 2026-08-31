# W04 Desktop Settings 实施提示词

请在 `D:\project\Re-UthCode` 完整实施 F02 的 T07。完成 API Key 专用 reveal 后端与 Settings UI 闭环，不提前执行 GUI 全面审查、CDP 验收或文档收尾。

## 开工前必须读取

1. `AGENTS.md`、`docs/README.md`、`docs/Context-Index.md`、`docs/rules/WorkPackageRules.md`、`docs/rules/UserDecisionBoundary.md`、`docs/OutstandingDebtList.md`。
2. F02 原始需求、Spec、Tasks、Checklist 和本 Prompt。
3. A04 当前上下文及配置/Secret 相关当前文档。
4. W01～W03 Feedback，尤其 Bridge/Application 与 Renderer 当前实际边界。
5. T07 定位的 config loader、bootstrap、Bridge、Desktop API、Settings source/tests。

## 已确认决策

- 用户提供的 F02 需求明确批准窄、主动触发的 `settings.reveal_api_key`：普通 `settings.get`/status/event/diagnostics 永不携带明文。
- reveal 读取用户配置中保存的表达；`env:` 不解析环境变量 secret，不从 Runtime Provider/`SecretValue` 反向读取。
- revealed 与 replacement/touched 分离；查看/隐藏不写入、不标 dirty，离开生命周期即清除明文。
- Settings 不显示内部 `model_ref` 或 placeholder，一个 Provider 支持多个 Model；不改变公共配置模型。

## 修改范围

- 独占 Tasks T07 列出的 Python config/Application/Bridge、Desktop API/Settings/共享 Renderer files 与 tests。
- W04 在 W03 后串行修改共享 `App.tsx`、CSS、locale/tests；不得恢复 W03 已删除的第二 authority。
- 不修改 Main/Preload/Python runtime、T10 冻结文件、CDP harness 或 current-facts docs。
- 不创建通用 Secret Manager/Vault/Event/Registry，不把整个 DesktopApi 作为无边界 Settings 依赖。
- 未经用户明确要求，不执行任何 Git 写操作。

## 实施与验证

1. 先以 Python tests 固化 configured-expression reader、Application use case、Bridge allowlist/error/secret safety。
2. 再以 Renderer tests 固化 reveal/hide/untouched/replacement/failed save/cache clear 生命周期。
3. 完成分类页、Provider/Model modal、多 Model、内部 ref 隐藏、键盘/focus/ARIA、zh/en/dark/light。
4. 执行 Python config/Bridge tests、Desktop typecheck/preload/Settings tests、秘密否定扫描与 `git diff --check`。
5. 首次执行创建 `feedback/W04-desktop-settings-feedback.md`；只勾选 T07 已验证 Checklist。

## Feedback 要求

说明 secret 从用户配置到专用 response 的唯一数据流、临时明文生命周期、replacement 写回、内部 ref 生成/隐藏、页面/modal 结构、修改文件、精确测试、Checklist、风险与清理结果。不得在 Feedback 写入真实 Key。返工只追加。
