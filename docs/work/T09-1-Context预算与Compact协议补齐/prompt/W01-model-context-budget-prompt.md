# W01 Model Context Profile / Budget Resolver Worker Prompt

## 任务范围与顺序

只执行 Task 1：Model Context Profile 与统一 Budget Resolver。完成并记录 Feedback 后停止，不提前实施 Transcript、Timeline、L1-L5、命令或文档收口。

## 必须读取

1. `AGENTS.md`
2. `docs/README.md`
3. `docs/Context-Index.md`
4. `docs/rules/WorkPackageRules.md`
5. 本工作包原始需求、Spec、Tasks、Checklist
6. `docs/context/A01-AgentRuntime/AgentRuntime-Context.md`
7. `docs/context/A03-State/State-Context.md`
8. Task 1 列出的现有源码与测试

以 `src/ + tests/` 为当前事实。使用 Conda 环境 `re-uthcode`。首次实施后本工作包已冻结：不得修改原始需求、Spec、Tasks、Prompt 或 Checklist 文字，只能勾选本 Worker 已满足的既有复选框并创建/追加 Feedback。

## 已确认决策

- `context_window` 是每个 Model profile 的 UthCode operating window，不是 UI 猜测的物理值。
- reliable Provider ceiling 只作为安全上限，不覆盖更小的 configured C；无可靠 metadata 时不伪造 discovery。
- 大窗口 retained strategy 使用绝对预算，不按 C 线性扩张；小窗口同步收缩 A/F/U 与 compact budget。
- Anthropic 可通过现有 SDK optional capability 提供可靠 model limits/token count；OpenAI/compat 不为统一外观伪造能力。
- Core/Application 只接收 UthCode-owned DTO，第三方 SDK 类型止于 Integration。

## 修改范围

仅修改 Tasks Task 1 列出的文件及必要 public export。新增 `tests/test_context_budget_gate.py`、`tests/test_provider_model_limits.py`。局部私有 helper/fixture 可按现有风格组织。

## 必须交付

- 每个真实 request path model 有正整数 C，配置 merge 与 project overlay 保持安全边界。
- request-level budget 合并 output reserve、safety margin、A/F/U、hard cap 和 compact input/output budgets。
- 25K、128K、258K、1M 与 provider ceiling/no-metadata 测试。
- active Turn snapshot 所需 contract 可供后续 Worker 使用，但本 Worker 不接入 Timeline 或 L4。
- 删除固定 258K 作为唯一 invariant；不得保留无调用方兼容 export。

## 禁止

- 不创建 ModelCatalogManager、ContextManager、动态模型浏览 UI 或启动时全量网络枚举。
- 不修改 OpenAI adapter 伪造 context metadata。
- 不实现 Transcript/Timeline、Compaction、Memory、Runtime recovery、Timeline GC、后台任务。
- 不执行 Git 写入或工作包归档。

## 验证

逐项执行 Task 1 Checklist；至少运行配置、budget、provider limits 与 architecture tests。外部真实 Provider 网络调用不得成为 CI 必过条件。记录精确 passed/failed/skipped；未运行不得声称通过。

## Feedback

首次创建 `feedback/W01-model-context-budget-feedback.md`。说明实际 contract、small/large policy、Provider capability 截止位置、修改文件、测试结果、Checklist 勾选、与任务书差异、风险和清理结果。若发现必须改变冻结产品/架构/安全边界，停止相关范围并在 Feedback 记录。
