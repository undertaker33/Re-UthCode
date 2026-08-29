# W03 通用失败语义实施提示词

请在 W02 已完成并通过审查后，完整实施 T09-3 的 T04；落实 Core `FailureReason`、Integration事实映射、Application统一用户文案和 TUI/CLI/Headless展示消费，同时保持现有 Pause/Retry。

## 开工前必须读取

1. `AGENTS.md`
2. `docs/README.md`、`docs/Context-Index.md`
3. `docs/rules/WorkPackageRules.md`、`docs/rules/UserDecisionBoundary.md`
4. `docs/OutstandingDebtList.md`
5. T09-3 原始任务书、Spec、Tasks、Checklist
6. W01、W02 Feedback
7. `docs/context/A01-AgentRuntime/AgentRuntime-Context.md`、A02 Control、A03 State、A04 Orchestration 中命中的当前事实
8. Tasks T04 定位的 Provider errors、Agent Loop/Event/TurnResult、Application Run/Context/persistence、CLI/TUI 与相关 tests

## 已确认决策

- 采用最小混合方案 C：Integration可靠映射 SDK事实 -> Core稳定 Provider-independent `FailureReason` -> Application唯一 one-line message projection -> Interface/Headless消费。
- `TerminationReason` 继续说明 Turn为什么终止；`FailureReason`说明具体失败类型，不互相替代。
- 枚举必须小而证据驱动，不镜像异常类/HTTP status；只表达当前真实调用链可靠辨识的 authentication、provider request/configuration、invalid response、context unresolvable、稳定 persistence unavailable 和 internal。
- network/rate-limit/timeout 如现有语义可恢复，继续走 `PauseReason`/Retry；当前 timeout 若被折叠为 network且 SDK事实可可靠区分，使用最小 Provider-independent error/PauseReason扩展保真，不能为了文案改成 terminal failure。
- successful/cancelled result不携带虚假 failure reason；third-party exception止于 Integration。
- public event/result/message不得泄露 traceback、SDK class、raw Provider body、secret、endpoint credential或内部异常正文。
- 不新增 ErrorManager/Registry、完整 i18n、每个 HTTP status错误类、兼容层或新的事件系统。

## 修改范围

- T04 Tasks 列出的 Core Provider/Agent/Event、Application Runs/Generation/public exports、三个 Provider Integrations、CLI/TUI展示与对应 tests。
- 只有当前文件职责无法清晰承载统一文案时才新增一个职责单一的 Application projection文件；不得新增通用错误子系统。
- 首次实施创建 `feedback/W03-failure-semantics-feedback.md`；返工只追加。
- 只勾选 T04 已验证 Checklist。

禁止修改 Context profile/Low Water、cache wire方案（除非修复 W02直接回归并记录）、Eval runner、冻结工作包或 Git状态。

## 实施约束

1. 使用 Conda环境 `re-uthcode`，先写 public JSON round-trip、provider mapping、context/persistence和cross-interface失败测试。
2. 审计每个现有 `TerminationReason.PROVIDER_ERROR`、`INVALID_PROVIDER_RESPONSE`、`INTERNAL_ERROR` 分支；只在有稳定事实的边界附加 FailureReason，不从异常字符串猜测。
3. Context resolver/safety失败在 Application事实边界映射为 context unresolvable；persistence仅在现有稳定失败事实足够时映射 unavailable，否则保持 internal并记录原因。
4. Provider Integration映射必须基于 SDK type/HTTP fact且不把 native对象向上传递；generic error不得假装成更细分类。
5. 统一文案允许普通措辞调整，但同一 reason跨 Interface语义一致，有必要时给可行动下一步。
6. Pause事件/response/continuation、stale response、cancel和一次 retry全部回归；不得新增 terminal timeout分类来绕过 pause。
7. 假 secret/raw body/traceback只可用于测试注入，不得出现在 Feedback大型日志或 public artifact。
8. 修改治理 Markdown时使用 `uth-utf8-guard`；本 Worker原则上只写 Feedback和勾选 Checklist。

## 测试与验收

至少执行：

```powershell
conda run --no-capture-output -n re-uthcode python -m pytest tests/test_agent_events.py tests/test_agent_loop.py tests/test_application_runs.py tests/test_cli.py tests/test_tui.py tests/test_openai_responses_integration.py tests/test_anthropic_integration.py tests/test_openai_compat_integration.py -q
conda run --no-capture-output -n re-uthcode python -m pytest tests/test_agent_interaction.py tests/test_architecture_boundaries.py -q
git diff --check
```

必须覆盖 authentication、reliable configuration/request、invalid response、context unresolved、稳定 persistence、generic internal、network/rate-limit/timeout pause、successful/cancel invariants、JSON round-trip、same projection与 secret/native exception leak guards。

## Feedback 要求

Feedback 必须说明最终枚举及每项真实证据、Termination/Failure/Pause职责、Integration到Interface调用流、Application文案owner、删除的重复分类、修改文件、精确测试结果、未能可靠细分的错误及原因、任务书差异、风险和否定扫描。不得复制 raw exception/body或 secret。

## 冻结决策覆盖

- 必须在 W03 Feedback逐项映射 D-T09-3-07、08，并证明未弱化现有 Pause/Retry、Hard Gate、Secret和架构边界。
