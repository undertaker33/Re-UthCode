# W05 工程收敛与联合验收 — Worker Prompt

## 派发与执行范围

只有用户明确指定执行本文件才开始本 Worker；本文件生成或另一 Worker 完成不授权自动继续。负责 T13 全仓调用证据与定点工程收敛 → T14 [接入主流程] → T15 [端到端验证] → T16 [遗留负担清理]，严格依次完成。前置：W04 对应任务和 Feedback 已交付；先复核源码与受影响证据，不依赖未落地合同。

在当前仓库既有 `re-uthcode` Conda 环境工作，开始复核 HEAD/git diff，不 checkout/commit/push/merge/tag/归档。任务按长期 Worker 执行，不为每个 Task 新派 Worker。共享文件只有本 Worker 当前单写；下一组由用户另行显式派发。

## 必须完整读取

1. `AGENTS.md`、`docs/README.md`、`docs/Context-Index.md`、`docs/rules/WorkPackageRules.md`、`docs/rules/UserDecisionBoundary.md`。
2. `docs/work/T12-Desktop功能补齐与工程收敛/T12-Desktop功能补齐与工程收敛.md`、`T12-Desktop功能补齐与工程收敛-spec.md`、`T12-Desktop功能补齐与工程收敛-tasks.md`、`T12-Desktop功能补齐与工程收敛-checklist.md`（后三份亦位于同一 T12 目录）。
3. `docs/README.md`、`docs/Context-Index.md`、`docs/OutstandingDebtList.md`、`docs/context/GUI/GUI-Context.md`、`docs/context/A03-State/State-Context.md`、`docs/context/A04-Orchestration/Orchestration-Context.md`；涉及实际欠账触发条件时读 `docs/OutstandingDebtList.md`。本包能力欠账为无，不为一般未来范围登记。
4. 同级 `W04-配置自动保存与设置-feedback.md`，以及 Tasks 依赖任务的相关原 Feedback；下列负责文件及其直接调用方/相应测试，依文档路由只读必要上下文：
   - `src/uthcode/**（仅有当前证据的定点删改）`
   - `desktop/src/**（仅有当前证据的定点删改）`
   - `tests/**、desktop/tests/**（相应失效或重复覆盖）`
   - `pyproject.toml`
   - `desktop/package.json`
   - `desktop/package-lock.json`
   - `desktop/scripts/build-python-runtime.mjs`
   - `desktop/packaging/uthcode-runtime.spec`
   - `desktop/forge.config.ts`
   - `src/uthcode/interfaces/desktop/bridge.py`
   - `desktop/src/renderer/App.tsx`
   - `desktop/src/renderer/state.ts`
   - `desktop/src/main.ts`
   - `desktop/src/preload.ts`
   - `tests/test_desktop_bridge.py`
   - `desktop/tests/renderer-session.test.tsx`
   - `desktop/tests/renderer-settings.test.tsx`
   - `desktop/tests/renderer-chat.test.tsx`
   - `tests/test_architecture_boundaries.py`
   - `desktop/scripts/cdp-driver.mjs`
   - `desktop/scripts/cdp-packaged-visual-acceptance.mjs`
   - `desktop/tests/renderer.test.tsx`
   - `desktop/tests/cdp-isolation.test.ts`
   - `desktop/tests/windows-packaging.test.ts`
   - `docs/context/GUI/GUI-Context.md`
   - `docs/context/A03-State/State-Context.md`
   - `docs/context/A04-Orchestration/Orchestration-Context.md`
   - `docs/context/A01-AgentRuntime/AgentRuntime-Context.md`
   - `docs/user-manual/getting-started.md`
   - `docs/user-manual/configuration.md`
   - `docs/user-manual/commands.md`
   - `docs/Tools.md`
   - `docs/core-design/A04-Orchestration/02-可替换交互层.md`
   - `README.md`
   - `docs/Context-Index.md`
   - `docs/OutstandingDebtList.md`
   - `本包 W05 Feedback`
5. UI/视觉任务使用同级 `references/coding-reference.png`、`general-reference.png`、`settings-reference.png`、`UthCode-Desktop-V4.html`；明确行为优先，V4 假数据/模拟动作不是实现。

## 已确认决定

瘦身需真实调用证据，工作区全覆盖盘点不等于无边界重构。正式 R/A 证据映射和相关文档必须收口；真实 Provider、真实 Git、packaged/Windows原生视觉分别验，不用Mock/HTML替代。

用户“不新建文件夹”优先于工作包目录模板：不建 prompt/feedback/新任务目录，所有任务文档及反馈平放现有 T12。按需新增生产文件仅置于已有职责目录，不能为未来能力建目录/占位。公共约束遵守上述 AGENTS 与规则引用，本 Prompt 不另建平行规则。

## 修改范围与禁止范围

修改集合为 Tasks 中本 Worker 的文件/局部职责及对应必要测试；可选新增/删除按同编号“新增文件/删除范围”操作，实际证据记 Feedback。清理候选实施前复核引用，不能把候选当成已批准的大规模重构。

不改冻结任务书/Spec/Tasks/Prompt/Checklist文字，不处理独立未来能力，不自行commit/push/归档；不以已有旧包测试结果冒称T12通过。

不得自行修改冻结原需求、Spec、Tasks、Prompt、Checklist 文字或编号。发现合同错误/冲突或必须扩范围，停止相关部分，在本 Worker Feedback 记录具体证据、影响和最多三个方案；其余已授权独立工作继续。既有任务书决定够用时不重复请求用户确认。

## 测试与验收

逐项执行 [Checklist](T12-Desktop功能补齐与工程收敛-checklist.md) 的 T13、T14、T15、T16；对应定向命令和收尾更大范围以 [Tasks](T12-Desktop功能补齐与工程收敛-tasks.md) 为准。涉及模块边界按规则跑架构测试；UI 公共行为覆盖成功、业务失败/RPC失败及迟到 owner。T14/T15/T16 可复用仍有效证据。真实条件不足保留对应未勾选并说明，继续可独立的文档/清理；有新代码改动才补受影响回归。

记录实际执行环境、源码/产物版本、精确命令与结果、有效证据路径和对应 R/A 项；未运行不写通过。必要验证满足后停止扩大测试；新修改/失败/具体疑点才补受影响检查。低风险清理不写复述实现的镜像测试。

## Feedback 与交接

首次实施创建同级 `W05-工程收敛与联合验收-feedback.md`；返工始终追加原文件并注明轮次/原因/修改/重验，不建 v2/retry，也不覆盖旧事实。遵守 WorkPackageRules §6，精简说明实际能力、关键机制、修改文件、命令及精确结果、Checklist 完成、差异/未完成/风险及遗留清理。

每个实际清理必须记录：路径/关键符号 → 真实调用者 → 冗余证据 → 具体删改 → 回归入口与结果 → 剩余风险。只勾本 Worker 已验证的现有复选框，不勾尚待后续 UI/真实 Provider/packaged/原生验证的条件。按 T16 做包级文档/索引与欠账核对；未满足真实验收不能标记整包完成。
