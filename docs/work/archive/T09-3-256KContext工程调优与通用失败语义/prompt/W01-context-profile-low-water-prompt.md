# W01 Context Profile 与 Low Water 实施提示词

请在 `D:\project\Re-UthCode` 完整实施 T09-3 的 T01 -> T02，严格串行完成 256K limit resolver、provenance、Active Turn freeze、ContextBudget 清理和 High Water -> Low Water L4；不得实施 T03 之后内容。

## 开工前必须读取

1. `AGENTS.md`
2. `docs/README.md`
3. `docs/Context-Index.md`
4. `docs/rules/WorkPackageRules.md`
5. `docs/rules/UserDecisionBoundary.md`
6. `docs/OutstandingDebtList.md`
7. `docs/work/T09-3-256KContext工程调优与通用失败语义/T09-3-256KContext工程调优与通用失败语义.md`
8. 同目录 Spec、Tasks、Checklist
9. `docs/context/A03-State/State-Context.md`、`A04-Orchestration/Orchestration-Context.md`
10. Tasks T01/T02 定位的源码、测试，以及 T09-1 相关 Feedback

## 已确认决策

- default 256K 是 UthCode Operating Window，不是模型物理窗口，也不是 Provider metadata。
- configured 存在时，effective 取 configured 与已知可靠 Provider ceiling 的更小值；显式 configured 可以大于 256K，default 不参与收紧。
- configured 缺失时：Provider ceiling 小于 256K 则收紧 default；Provider ceiling 大于 256K 时 effective 仍为 256K；二者都缺失时 effective 为 256K。
- provenance 必须区分 observed source、active/effective source 与 actually tightened source。
- Hard Gate 继续按 input、known output、known combined 分维验证，unknown 不补造。
- Auto L4 由 High/Hard pressure 启动，启动后追 retained target/Low Water；刚低于 High Water 不是完成。
- Manual 不依赖 High且允许 no-op；Overflow 保持 forced reduction和 Core one-retry；L5 保持独立 fine budget。
- 不新增 model catalog、Context policy/manager、Compact manager/FSM/job、兼容层或新的公共框架。

## 修改范围

- T01/T02 Tasks 列出的 `core/context.py`、按需 `compaction.py`、Application Context/generation/runs/config/status 与对应 tests。
- 首次实施创建 `feedback/W01-context-profile-low-water-feedback.md`；返工只在同文件末尾追加。
- 只勾选 T01/T02 已用精确命令验证的 Checklist；不得修改 Checklist 文字、顺序或其它任务状态。

禁止修改 Provider cache hints、FailureReason 公共合同、Eval runner/reporting、Interface 失败展示、冻结工作包正文或执行 Git 写操作/归档。

## 实施约束

1. 使用 Conda 环境 `re-uthcode`，先补失败测试再作最小生产修改。
2. active Turn、idle manual 和 Context service individual-limits fallback 三个真实 caller 必须统一使用同一 resolver；不能只修普通生成。
3. 同一 Turn 的 provider limits/budget/provenance只解析并冻结一次；下一 Turn重新解析。model switch只影响下一 Turn。
4. `active_evidence_budget`、`uncompressed_tail_budget`、`retained_hard_cap` 再次 caller audit 后无生产消费者则连同派生、序列化、diagnostics/tests/current docs 残留删除；若发现新生产 caller，停止删除该字段并在 Feedback记录事实。
5. Low Water 判定使用每次 rebuild 后真实 preflight input usage 与 frozen retained target；未触发 Auto 时不得主动追 Low。
6. 复用现有 bounded compact epoch/commit/rebuild机制，只允许窄私有 helper 收敛真实重复；不恢复 T09-2 删除的抽象。
7. 保持 Session single-writer、checkpoint-last、active Turn exclusion、Hard Gate、cancel、unknown durability和 overflow exactly-one retry。
8. 修改治理 Markdown 时使用 `uth-utf8-guard`；本 Worker原则上只写 Feedback和勾选 Checklist。

## 测试与验收

至少执行：

```powershell
conda run --no-capture-output -n re-uthcode python -m pytest tests/test_context_budget_gate.py tests/test_application_runs.py tests/test_w05_diagnostics.py tests/test_t09_1_context_protocol_e2e.py -q
conda run --no-capture-output -n re-uthcode python -m pytest tests/test_context_budget_gate.py tests/test_context_compaction.py tests/test_t09_1_context_protocol_e2e.py tests/test_application_runs.py -q
conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q
git diff --check
```

显式包含：configured >256K 不被 default 限制；provider-only >256K 仍为 256K；同 Turn多 iteration只解析一次、下一 Turn刷新；epoch 1 低于 High但高于 Low继续、epoch 2 到 Low停止；manual/overflow/L5 和 finite breakers 回归。

## Feedback 要求

Feedback 必须说明 resolver 真值表与 provenance、三类 caller、Active Turn freeze、删除/保留字段的 caller证据、High->Low 调用流、Auto/Manual/Overflow差异、修改文件、测试精确结果、Checklist证据、任务书差异、未完成项和风险。不得把未运行测试或 T05 尚未完成的 profile tuning 写成通过。

## 冻结决策覆盖

- 必须在 W01 Feedback逐项映射 D-T09-3-01、02、03、04、05、06、08。
