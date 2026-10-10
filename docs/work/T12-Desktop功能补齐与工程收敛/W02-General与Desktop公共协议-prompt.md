# W02 General与Desktop公共协议 — Worker Prompt

## 派发与执行范围

只有用户明确指定执行本文件才开始本 Worker；本文件生成或另一 Worker 完成不授权自动继续。负责 T03 General 最小 Application 组合 → T04 Session 与 General Desktop 协议接入 → T05 过程回放与安全明细来源 → T06 变更摘要与当前只读 Diff 出口，严格依次完成。前置：W01 对应任务和 Feedback 已交付；先复核源码与受影响证据，不依赖未落地合同。

在当前仓库既有 `re-uthcode` Conda 环境工作，开始复核 HEAD/git diff，不 checkout/commit/push/merge/tag/归档。任务按长期 Worker 执行，不为每个 Task 新派 Worker。共享文件只有本 Worker 当前单写；下一组由用户另行显式派发。

## 必须完整读取

1. `AGENTS.md`、`docs/README.md`、`docs/Context-Index.md`、`docs/rules/WorkPackageRules.md`、`docs/rules/UserDecisionBoundary.md`。
2. `docs/work/T12-Desktop功能补齐与工程收敛/T12-Desktop功能补齐与工程收敛.md`、`T12-Desktop功能补齐与工程收敛-spec.md`、`T12-Desktop功能补齐与工程收敛-tasks.md`、`T12-Desktop功能补齐与工程收敛-checklist.md`（后三份亦位于同一 T12 目录）。
3. `docs/context/A03-State/State-Context.md`、`docs/context/A04-Orchestration/Orchestration-Context.md`、`docs/context/A01-AgentRuntime/AgentRuntime-Context.md`、`docs/context/GUI/GUI-Context.md`、`docs/Tools.md`；涉及实际欠账触发条件时读 `docs/OutstandingDebtList.md`。本包能力欠账为无，不为一般未来范围登记。
4. 同级 `W01-会话归档与检索-feedback.md`，以及 Tasks 依赖任务的相关原 Feedback；下列负责文件及其直接调用方/相应测试，依文档路由只读必要上下文：
   - `src/uthcode/application/bootstrap.py`
   - `src/uthcode/application/generation.py`
   - `src/uthcode/application/context.py`
   - `src/uthcode/application/instructions.py`
   - `src/uthcode/application/sessions.py`
   - `src/uthcode/core/prompt.py`
   - `src/uthcode/prompt_assets/__init__.py`
   - `tests/test_application_runtime.py`
   - `tests/test_system_prompt.py`
   - `tests/test_project_instructions.py`
   - `tests/test_session_authority.py`
   - `src/uthcode/application/configuration.py`
   - `src/uthcode/integrations/config/loader.py`
   - `tests/test_config_loader_integration.py`
   - `desktop/packaging/uthcode-runtime.spec`
   - `src/uthcode/interfaces/desktop/bridge.py`
   - `desktop/src/desktop-api.ts`
   - `desktop/src/main.ts`
   - `desktop/src/preload.ts`
   - `tests/test_desktop_bridge.py`
   - `desktop/tests/preload.test.ts`
   - `desktop/tests/runtime-process.test.ts`
   - `src/uthcode/integrations/session_files.py`
   - `tests/test_tool_result_persistence.py`
   - `tests/test_timeline_contract.py`
   - `tests/test_history_paging.py`
   - `src/uthcode/application/tools.py`
   - `src/uthcode/application/runs.py`
   - `src/uthcode/application/attachments.py`
   - `src/uthcode/integrations/tools/git_tools.py`
   - `tests/test_git_tools.py`
   - `tests/test_desktop_artifacts.py`
   - `src/uthcode/integrations/tools/file_tools.py`
   - `src/uthcode/integrations/tools/patch_tools.py`
   - `tests/test_builtin_file_tools.py`
   - `tests/test_patch_tool.py`
5. UI/视觉任务使用同级 `references/coding-reference.png`、`general-reference.png`、`settings-reference.png`、`UthCode-Desktop-V4.html`；明确行为优先，V4 假数据/模拟动作不是实现。

## 已确认决定

General 是用户级独立纯文本组合，复用同一 Agent Loop，创建/恢复/reload 无 Coding 指令与默认工具。归档只检查目标状态。工具观察、安全结果引用和真实写入元数据是投影来源；历史摘要与当前 Diff 分开。

用户“不新建文件夹”优先于工作包目录模板：不建 prompt/feedback/新任务目录，所有任务文档及反馈平放现有 T12。按需新增生产文件仅置于已有职责目录，不能为未来能力建目录/占位。公共约束遵守上述 AGENTS 与规则引用，本 Prompt 不另建平行规则。

## 修改范围与禁止范围

修改集合为 Tasks 中本 Worker 的文件/局部职责及对应必要测试；可选新增/删除按同编号“新增文件/删除范围”操作，实际证据记 Feedback。清理候选实施前复核引用，不能把候选当成已批准的大规模重构。

不修改 Renderer 页面/状态；不提前实施配置自动保存（W04）；不扩大模型工具权限、不写 Git、不造历史快照。

不得自行修改冻结原需求、Spec、Tasks、Prompt、Checklist 文字或编号。发现合同错误/冲突或必须扩范围，停止相关部分，在本 Worker Feedback 记录具体证据、影响和最多三个方案；其余已授权独立工作继续。既有任务书决定够用时不重复请求用户确认。

## 测试与验收

逐项执行 [Checklist](T12-Desktop功能补齐与工程收敛-checklist.md) 的 T03、T04、T05、T06；对应定向命令和收尾更大范围以 [Tasks](T12-Desktop功能补齐与工程收敛-tasks.md) 为准。涉及模块边界按规则跑架构测试；UI 公共行为覆盖成功、业务失败/RPC失败及迟到 owner。联通 Application/Bridge/Main/preload 精确协议和负例；General 真实 Provider 与 packaged 界面验证留给 W05，不能以 Mock 勾选 A08/A16/A23。

记录实际执行环境、源码/产物版本、精确命令与结果、有效证据路径和对应 R/A 项；未运行不写通过。必要验证满足后停止扩大测试；新修改/失败/具体疑点才补受影响检查。低风险清理不写复述实现的镜像测试。

## Feedback 与交接

首次实施创建同级 `W02-General与Desktop公共协议-feedback.md`；返工始终追加原文件并注明轮次/原因/修改/重验，不建 v2/retry，也不覆盖旧事实。遵守 WorkPackageRules §6，精简说明实际能力、关键机制、修改文件、命令及精确结果、Checklist 完成、差异/未完成/风险及遗留清理。

每个实际清理必须记录：路径/关键符号 → 真实调用者 → 冗余证据 → 具体删改 → 回归入口与结果 → 剩余风险。只勾本 Worker 已验证的现有复选框，不勾尚待后续 UI/真实 Provider/packaged/原生验证的条件。交接共享文件的实际公共合同与尚待后续验收，用户未另行派发不自动执行下一 Worker。
