# W04 256K Eval 调优实施提示词

请在 W01～W03 全部完成并通过审查后，完整实施 T09-3 的 T05；复用 B01 Eval完成至少三组 256K profile候选的离线粗筛/必要细调、cache/failure观测和初始工程默认选择。

## 开工前必须读取

1. `AGENTS.md`
2. `docs/README.md`、`docs/Context-Index.md`
3. `docs/rules/WorkPackageRules.md`、`docs/rules/UserDecisionBoundary.md`
4. `docs/OutstandingDebtList.md`
5. T09-3 原始任务书、Spec、Tasks、Checklist
6. W01、W02、W03 Feedback
7. `docs/work/B01-私有测试集v0/` 的 Spec、Tasks、W01～W03 Prompt与 Feedback
8. `docs/context/A04-Orchestration/Orchestration-Context.md` 的私有 Eval手动链路
9. 当前 `eval/`、`tests/eval/`、long-context/long-task fixtures和生产 diagnostics public facts

## 已确认决策

- 只扩展现有 B01 runner/models/execution/metrics/reporting/compare/fingerprint，不建第二套 benchmark runtime、不注册正式 CLI、不接 CI。
- 至少三组明显不同候选；High/Low可覆盖任务书参考区域，并可围绕优胜区二次细调。具体数值只有 Eval后才能成为 T09-3初始工程默认，且不是 public API。
- deterministic acceptance与 tuning evidence分开；六维 correctness/context/exploration/efficiency/stability/safety并列，不生成总分或加权排名。
- 选择不能只看 token最少，必须综合任务成功、约束保留、compact thrash、post-compact工作空间、rediscovery/repeated exploration、cache reuse与成本。
- code/prompt/model/provider/config/task-sample等共同控制变量继续按 B01 compatibility fingerprint严格相等；profile id与完整参数是受控 candidate variant axis，不把候选差异误判为不兼容，也不放宽其它 fingerprint。
- 真实 Provider cache/latency/billing、网络和费用默认拒绝；没有单独授权时保持 `NOT VERIFIED (authorization required)`，不读取 secret。
- Eval产物运行在物理校验过的仓库外专用根；仓库内只保留版本化 fixture/candidate与可审查汇总。

## 修改范围

- T05 Tasks列出的 `eval/`、`tests/eval/`、必要 long-context/long-task fixture和版本化汇总报告。
- 选出优胜候选后，允许定点修改 T01/T02 的生产 profile默认及其 contract tests；不得重构 Context架构。
- 首次实施创建 `feedback/W04-256k-eval-tuning-feedback.md`；返工只追加。
- 只勾选 T05已验证 Checklist。

禁止修改 FailureReason公共语义、Provider cache wire owner、Interface展示、冻结文档、CI、正式 `uthcode` CLI、第三方依赖或 Git状态。

## 实施约束

1. 使用 Conda环境 `re-uthcode`，先扩展严格合同/fingerprint/tests，再运行离线候选。
2. 候选必须真实驱动当前生产参数；通过 Eval私有、可替换 seam注入，不加入产品 config或公共 `create_application` API，也不通过无消费者字段、测试私有捷径或第二 policy engine模拟。若只能扩大公共 API，停止并在 Feedback报告。
3. 报告至少收集 verifier/success、input/output、compact count、pre/post usage、post-compact headroom、work distance、rediscovery/repeated exploration、externalization/HistoryRead、cache read/write/ratio availability、prefix change/reason和 failure correctness。
4. unavailable保持 unavailable；不得用0、final文本或猜测补齐缺失 diagnostics。
5. long workload必须覆盖多轮探索/修改/回归、大 Tool Result外置回读、长期约束、一次/多次 compact、compact后继续工作、expected prefix invalidation和 stable prefix reuse；现有小型 long-context fixture与固定 usage不足以作为 256K tuning evidence，必须增加可控离线长工作负载/usage。
6. 不保存标准完整 Patch、不规定唯一 ToolCall序列；verifier保持离线确定性。
7. 清理只走 B01 manifest专用边界，不删除用户文件；不得在仓库生成 home/cache/attempt。
8. 修改治理 Markdown时使用 `uth-utf8-guard`。

## 测试与验收

至少执行：

```powershell
conda run --no-capture-output -n re-uthcode python -m pytest tests/eval -q
conda run --no-capture-output -n re-uthcode python -m pytest tests/test_context_budget_gate.py tests/test_context_compaction.py tests/test_t09_1_context_protocol_e2e.py tests/test_w05_diagnostics.py -q
conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q
git diff --check
```

另从真实 `python -m eval.runner` 入口执行离线 help/smoke/candidate runs/compare/clean拒绝，记录精确命令、外部路径、fingerprint和结果。没有用户授权时禁止任何 live开关。

## Feedback 要求

Feedback 必须说明候选表、fingerprint、workload/verifier、逐维结果、High/Low最终取舍、post-compact工作距离、compact/rediscovery/cache/prefix/failure指标、unavailable原因、生产默认回写、修改文件、精确测试与 runner结果、live未验证状态、风险和临时产物清理。不得声称某候选“总分第一”。

## 冻结决策覆盖

- 必须在 W04 Feedback逐项映射 D-T09-3-01、05、06、07、08。
