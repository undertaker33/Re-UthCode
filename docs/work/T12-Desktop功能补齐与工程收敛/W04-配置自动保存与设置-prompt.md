# W04 配置自动保存与设置 — Worker Prompt

## 派发与执行范围

只有用户明确指定执行本文件才开始本 Worker；本文件生成或另一 Worker 完成不授权自动继续。负责 T11 配置单项持久化与安全边界应用 → T12 Settings 自动保存与归档管理，严格依次完成。前置：W03 对应任务和 Feedback 已交付；先复核源码与受影响证据，不依赖未落地合同。

在当前仓库既有 `re-uthcode` Conda 环境工作，开始复核 HEAD/git diff，不 checkout/commit/push/merge/tag/归档。任务按长期 Worker 执行，不为每个 Task 新派 Worker。共享文件只有本 Worker 当前单写；下一组由用户另行显式派发。

## 必须完整读取

1. `AGENTS.md`、`docs/README.md`、`docs/Context-Index.md`、`docs/rules/WorkPackageRules.md`、`docs/rules/UserDecisionBoundary.md`。
2. `docs/work/T12-Desktop功能补齐与工程收敛/T12-Desktop功能补齐与工程收敛.md`、`T12-Desktop功能补齐与工程收敛-spec.md`、`T12-Desktop功能补齐与工程收敛-tasks.md`、`T12-Desktop功能补齐与工程收敛-checklist.md`（后三份亦位于同一 T12 目录）。
3. `docs/context/GUI/GUI-Context.md`、`docs/context/A04-Orchestration/Orchestration-Context.md`、`docs/user-manual/configuration.md`；涉及实际欠账触发条件时读 `docs/OutstandingDebtList.md`。本包能力欠账为无，不为一般未来范围登记。
4. 同级 `W03-Renderer导航与审阅-feedback.md`，以及 Tasks 依赖任务的相关原 Feedback；下列负责文件及其直接调用方/相应测试，依文档路由只读必要上下文：
   - `src/uthcode/application/configuration.py`
   - `src/uthcode/application/bootstrap.py`
   - `src/uthcode/application/generation.py`
   - `src/uthcode/integrations/config/writer.py`
   - `src/uthcode/integrations/config/loader.py`
   - `src/uthcode/interfaces/desktop/bridge.py`
   - `desktop/src/desktop-api.ts`
   - `desktop/src/main.ts`
   - `desktop/src/preload.ts`
   - `tests/test_configuration.py`
   - `tests/test_application_runtime.py`
   - `tests/test_desktop_bridge.py`
   - `tests/test_config_contract.py`
   - `tests/test_config_loader_integration.py`
   - `tests/test_w04_review_fixes.py`
   - `desktop/src/renderer/App.tsx`
   - `desktop/src/renderer/SettingsView.tsx`
   - `desktop/src/renderer/SettingsEditorModal.tsx`
   - `desktop/src/renderer/settings-draft.ts`
   - `desktop/src/renderer/state.ts`
   - `desktop/src/renderer/i18n.tsx`
   - `desktop/src/renderer/locales/zh-CN.ts`
   - `desktop/src/renderer/locales/en.ts`
   - `desktop/tests/renderer-settings.test.tsx`
   - `desktop/tests/renderer-runtime-lifecycle.test.tsx`
   - `desktop/src/renderer/useRuntimeLifecycle.ts`
   - `desktop/src/renderer/app.css`
   - `desktop/tests/renderer.test.tsx`
5. UI/视觉任务使用同级 `references/coding-reference.png`、`general-reference.png`、`settings-reference.png`、`UthCode-Desktop-V4.html`；明确行为优先，V4 假数据/模拟动作不是实现。

## 已确认决定

有效字段/合法关联组自动持久化，无全局 Save；保存和生效分离，活动 Turn/Compact/已启动进程快照保留。唯一用户配置 writer、可信 Provider、项目收紧和 Secret 生命周期保持。归档页按原 Coding 项目/General 分组。

用户“不新建文件夹”优先于工作包目录模板：不建 prompt/feedback/新任务目录，所有任务文档及反馈平放现有 T12。按需新增生产文件仅置于已有职责目录，不能为未来能力建目录/占位。公共约束遵守上述 AGENTS 与规则引用，本 Prompt 不另建平行规则。

## 修改范围与禁止范围

修改集合为 Tasks 中本 Worker 的文件/局部职责及对应必要测试；可选新增/删除按同编号“新增文件/删除范围”操作，实际证据记 Feedback。清理候选实施前复核引用，不能把候选当成已批准的大规模重构。

不重写 General Runtime、Session存储或过程/Diff语义；不按字段重启 child，不改变公共权限/Secret合同，不删失败重试局部草稿。

不得自行修改冻结原需求、Spec、Tasks、Prompt、Checklist 文字或编号。发现合同错误/冲突或必须扩范围，停止相关部分，在本 Worker Feedback 记录具体证据、影响和最多三个方案；其余已授权独立工作继续。既有任务书决定够用时不重复请求用户确认。

## 测试与验收

逐项执行 [Checklist](T12-Desktop功能补齐与工程收敛-checklist.md) 的 T11、T12；对应定向命令和收尾更大范围以 [Tasks](T12-Desktop功能补齐与工程收敛-tasks.md) 为准。涉及模块边界按规则跑架构测试；UI 公共行为覆盖成功、业务失败/RPC失败及迟到 owner。重点写后 reload 失败、快速连续编辑、跨项目后台 active/compact/process、literal/env Key保留、General refresh无工具。可调整旧全局 Save测试为新公开行为，但保留关键失败/owner/Secret覆盖。

记录实际执行环境、源码/产物版本、精确命令与结果、有效证据路径和对应 R/A 项；未运行不写通过。必要验证满足后停止扩大测试；新修改/失败/具体疑点才补受影响检查。低风险清理不写复述实现的镜像测试。

## Feedback 与交接

首次实施创建同级 `W04-配置自动保存与设置-feedback.md`；返工始终追加原文件并注明轮次/原因/修改/重验，不建 v2/retry，也不覆盖旧事实。遵守 WorkPackageRules §6，精简说明实际能力、关键机制、修改文件、命令及精确结果、Checklist 完成、差异/未完成/风险及遗留清理。

每个实际清理必须记录：路径/关键符号 → 真实调用者 → 冗余证据 → 具体删改 → 回归入口与结果 → 剩余风险。只勾本 Worker 已验证的现有复选框，不勾尚待后续 UI/真实 Provider/packaged/原生验证的条件。交接共享文件的实际公共合同与尚待后续验收，用户未另行派发不自动执行下一 Worker。
