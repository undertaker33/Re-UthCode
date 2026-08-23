# W01 Engineering Convergence Prompt

请在 `D:\project\Re-UthCode` 完整实施 T09-2，严格按 Task 1 → Task 9 串行执行。

## 必读文件

1. `AGENTS.md`
2. `docs/README.md`
3. `docs/Context-Index.md`
4. `docs/rules/WorkPackageRules.md`
5. `docs/rules/UserDecisionBoundary.md`
6. `docs/work/T09-2-工程收敛与提前抽象清理/T09-2-工程收敛与提前抽象清理.md`
7. 同目录 Spec、Tasks、Checklist
8. `docs/OutstandingDebtList.md`
9. Tasks 命中的当前 Context、核心设计、源码和测试

## 已确认决策

- 唯一执行入口为 `create_application -> create_run -> start_turn -> AgentLoop`。
- 旧 Generation API 直接删除，无弃用或兼容层。
- Session v3 硬切，v1/v2 incompatible，无迁移或双读。
- 公共导出只定点清理，不扩大为全量 API 设计。
- 不新增未来能力，不修改冻结工作包，不执行 Git 写操作或归档。

## 执行要求

- 使用 Conda 环境 `re-uthcode`。
- 每个 Task 先读取对应实现与测试，再作最小修改；使用 `apply_patch` 编辑。
- 当前源码与测试是事实来源；历史工作包只用于解释，不得维护其旧 API。
- 删除旧测试时，必须把仍有业务价值的断言迁移到 Provider 或正式 Run/Turn 测试，不能以删测试代替验证。
- 任何 Tool 副作用、Permission、Context Hard Gate、Session durability 或 Secret 边界回退都必须立即停止相关范围并记录。
- 修改治理 Markdown 时使用 `uth-utf8-guard`；中文文档保持 UTF-8。
- 首次实施创建 `feedback/W01-engineering-convergence-feedback.md`；返工只在该文件追加。
- 只勾选已经用精确命令验证的 Checklist 项，不修改 Checklist 文字、顺序或编号。

## 验收与反馈

- 完成 Tasks 指定定向测试后，再执行架构、Eval、全量回归、compileall、pip check、diff check、否定扫描和 UTF-8 guard。
- Feedback 必须记录实际删除/保留内容、关键调用流、Session v3 格式、测试精确结果、未验证项和风险。
- 完成后把 `Context-Index.md` 的 T09-2 状态更新为 implemented_unarchived；不得移动到 archive。
