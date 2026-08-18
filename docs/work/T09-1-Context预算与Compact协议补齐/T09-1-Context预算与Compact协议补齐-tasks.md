# T09-1 Context 预算与 Compact 协议补齐 Tasks

## Worker 分组与执行顺序

| Worker | 严格顺序 | 前置 Worker |
| --- | --- | --- |
| W01 | Task 1 | 无 |
| W02 | Task 2 | W01 |
| W03 | Task 3 | W01、W02 |
| W04 | Task 4 | W01～W03 |
| W05 | Task 5 | W01～W04 |
| W06 | Task 6 → Task 7 → Task 8 → Task 9 | W01～W05 |

用户未显式指定 Prompt 文件前不得实施。Worker内部严格串行；首次执行创建同名Feedback。

## Task 1：模型窗口、计数能力与双 Gate 预算契约

- 任务目标：建立per-model `C`、optional ceiling `E`、output reserve、count source、uncertainty、adaptive capped `R`、Auto/Hard Gate纯值和Provider capability。
- 新增文件：`tests/test_provider_model_limits.py`、`tests/test_context_budget_gate.py`。
- 修改文件：`src/uthcode/application/configuration.py`、`src/uthcode/integrations/config/loader.py`、`src/uthcode/integrations/config/template.py`、`src/uthcode/core/context.py`、`src/uthcode/core/provider.py`、`src/uthcode/integrations/providers/anthropic.py`、`src/uthcode/application/bootstrap.py`、必要exports、`tests/test_configuration.py`、`tests/test_config_contract.py`。
- 删除内容：固定258K作为唯一invariant及无调用方export。
- 文件职责及实施内容：每个可运行model要求正整数`context_window`；`E=min(C,reliable ceiling)`；Anthropic Models/count API只在Integration；final-request count contract保持SDK-neutral；headroom default单点定义为`clamp(ceil(E*0.08),2048,32768)`；uncertainty policy集中且provider count allowance小于local estimate allowance；Auto/Hard结果分离。
- 依赖任务：无。
- 参考资料：Taskbook第6、8节；A01/A03 Context；Anthropic Models/Token Counting；Pi/OpenCode/Codex一手来源。
- 完成边界：25K、128K、258K、1M；configured C与ceiling；provider/local count和fallback；不依赖Timeline/L4。

## Task 2：Transcript / Timeline 与 Session v2 持久事实

- 任务目标：硬切History/Projection，建立raw Transcript、三类Timeline产品record和checkpoint-last恢复。
- 新增文件：`tests/test_timeline_contract.py`。
- 修改文件：`src/uthcode/core/history.py`、`src/uthcode/core/prompt.py`、`src/uthcode/core/__init__.py`、`src/uthcode/application/history.py`、`src/uthcode/application/sessions.py`、`src/uthcode/integrations/session_files.py`、`tests/test_history_contract.py`、`tests/test_session_files.py`。
- 删除内容：Projection authority、Session v1 `history.jsonl`新读写与compatibility export。
- 文件职责及实施内容：Transcript strict sequence与complete tool group；Timeline只接受SemanticEntry/EpochMacroSummary/ActiveCheckpoint；Compact Epoch由checkpoint边界推导；fresh Session为`metadata.json/writer.lock/transcript.jsonl/timeline.jsonl/runtime.jsonl/tool-results/`；复用single writer、fsync、reconcile、unknown durability quarantine；old schema deterministic incompatible。
- 依赖任务：Task 1 contract稳定；不依赖model compaction。
- 参考资料：Taskbook第7、11、12节；A03 Context；现有Session writer safety tests。
- 完成边界：partial line、trailing transaction、checkpoint crash、single writer、old schema均有测试。

## Task 3：最终请求组装、Auto/Hard Gate 与确定性 L1-L3

- 任务目标：在已有awaitable request-preparer中组装、计数、双Gate与L1-L3。
- 新增文件：无。
- 修改文件：`src/uthcode/core/context.py`、`src/uthcode/core/prompt.py`、`src/uthcode/application/context.py`、`src/uthcode/application/generation.py`、`tests/test_context_compiler.py`、`tests/test_context_budget_gate.py`、必要的`tests/test_tool_result_persistence.py`、`tests/test_application_runs.py`。
- 删除内容：固定budget compile path、Projection直接决定view和绕过final request count的入口。
- 文件职责及实施内容：Compiler从Transcript/latest committed Timeline/runtime facts生成唯一logical view；L1 externalization、L2 preview shrink、L3 inactive raw omission均deterministic且完整语义边界；每次rebuild后对同一final request重计数；Auto pressure与Hard safe分别表达；required/current不可装入时fail closed且provider count为0。
- 依赖任务：Task 1、Task 2。
- 参考资料：Taskbook第6.2～6.5、11～12节；T09 Core Design；Tool Result tests。
- 完成边界：L1-L3后仍高于Auto Gate产生L4-required结果；清除pressure直接Hard Gate；不执行真实L4。

## Task 4：L4 proactive semantic compaction 与 B′

- 任务目标：接通tool-free async L4和无持久FSM的bounded catch-up。
- 新增文件：`tests/test_t09_1_context_protocol_e2e.py`（L4初始范围）。
- 修改文件：`src/uthcode/core/context.py`、`src/uthcode/application/context.py`、`src/uthcode/application/generation.py`、`src/uthcode/application/sessions.py`、`tests/test_context_compaction.py`、`tests/test_context_budget_gate.py`、`tests/test_application_runs.py`。
- 删除内容：同步`summarize=None`生产路径和旧Projection candidate/overflow compactor路径。
- 文件职责及实施内容：复用AgentLoop现有awaitable preparer；active Turn使用冻结provider/model/C，idle入口预留同一orchestrator调用；compact request无Tools且自身Hard-Gated；bounded raw epoch→per-Turn Fine entries→checkpoint last；commit后rebuild/recount/re-gate；1..N、retained target、cancel、finite/no-progress/repeated-failure breaker；Auto unresolved但Hard safe时诊断后发送，Hard unsafe fail closed。
- 依赖任务：Task 1～3。
- 参考资料：D1/D2/D3；Taskbook第6.5～6.6、12节。
- 完成边界：单/多epoch、1M、257K still pressure、crash/cancel/invalid/no-progress都有fake tests；不修改`core/agent.py`除非发现局部既有缺陷并在Feedback证明。

## Task 5：L5独立老化与 HistoryRead

- 任务目标：让Fine Timeline pressure独立触发raw-evidence L5，并提供current-Session exact-ref回读。
- 新增文件：`src/uthcode/integrations/tools/history_read.py`、`tests/test_history_read_tool.py`。
- 修改文件：`src/uthcode/application/context.py`、`src/uthcode/application/tools.py`、`src/uthcode/application/bootstrap.py`、`src/uthcode/integrations/tools/factory.py`、`tests/test_timeline_contract.py`、`tests/test_context_compaction.py`、`tests/test_application_tools.py`、`tests/test_tool_result_persistence.py`、`tests/test_context_budget_gate.py`。
- 删除内容：无真实职责的重复history/path reader（若存在）。
- 文件职责及实施内容：选old complete epoch；按refs读raw Transcript；L5 request自身Hard-Gated；macro + checkpoint last；coverage逻辑替代Fine但不物理删除；禁止summary-of-summary；HistoryRead current Session only、opaque、bounded、read-only、no search/path、输出不递归externalize。
- 依赖任务：Task 1～4。
- 参考资料：Taskbook第6.8、7、11～12节；ToolResultRead contract。
- 完成边界：Fine-only pressure、raw provenance、no-safe-epoch、cross-session/path denial与ToolResultRead回归有测试。

## Task 6：运行生命周期、手动 Compact、Overflow、Diagnostics 与文档

- 任务目标：接入closed-fact persistence、manual compact、overflow fallback、dynamic status、安全diagnostics、Eval和文档。
- 新增文件：无。
- 修改文件：`src/uthcode/application/generation.py`、`src/uthcode/application/sessions.py`、`src/uthcode/application/commands/builtins.py`、`src/uthcode/application/commands/dispatcher.py`、仅真实typing需要时的`src/uthcode/application/commands/models.py`、仅async adapter需要时的`src/uthcode/interfaces/tui/app.py`、`eval/metrics.py`、`tests/test_application_runtime.py`、`tests/test_application_runs.py`、`tests/test_session_files.py`、`tests/test_command_dispatcher.py`、`tests/test_w04_session_commands.py`、`tests/test_tui.py`、`tests/test_w05_diagnostics.py`、`tests/test_w06_integration_delivery.py`、`tests/test_t09_1_context_protocol_e2e.py`、`tests/test_architecture_boundaries.py`、`docs/Context-Index.md`、`docs/OutstandingDebtList.md`、`docs/core-design/T09-context-engineering.md`、A01/A03/A04 Context文档、`docs/user-manual/configuration.md`、`docs/user-manual/commands.md`。
- 删除内容：`summarizer_unavailable`命令结果、fixed-258K/Projection status和旧docs/Eval假设。
- 文件职责及实施内容：initial前user fact、post-tool前complete group、terminal tail durable；manual低于Auto Gate可执行，无候选no-op；same Session single-flight；Core one-retry guard绑定async forced reduction/rebuild/Hard Gate；第二次overflow终止且C不变；status公开C/E/R/Auto/Hard/count source/L1-L5/checkpoint，不泄露正文；实现验收时同步长期文档。
- 依赖任务：Task 1～5。
- 参考资料：Taskbook第6.7～6.9、13、16节；A04 Context；docs维护映射。
- 完成边界：initial/post-tool/post-resume/manual/overflow/model switch/Headless tests闭合。

## Task 7：[接入主流程] 单一 Context Request Orchestration

- 任务目标：收口全部正式model call与入口。
- 新增文件：无。
- 修改文件：仅Task 1～6已列文件及机械import/export。
- 删除内容：绕过Application dual-gate/final count的Provider call、旧History/Projection写入、空summarizer与旧overflow入口。
- 文件职责及实施内容：逐一追踪direct generation、initial/post-tool/post-resume、manual、L4、L5、retry；每次Hard Gate；Command/TUI只调用Application；Session writer只接Core values。
- 依赖任务：Task 1～6。
- 参考资料：Context-Index跨层链路；Taskbook第7、12节。
- 完成边界：检索与architecture tests证明单一编排；不新增产品行为。

## Task 8：[端到端验证] Dual Gate / Compact / Recovery

- 任务目标：从真实Application/Session/Run/Command adapter验证完整协议。
- 新增文件：无。
- 修改文件：测试、fixture及Task 1～7范围内被E2E暴露的实现缺陷。
- 删除内容：无。
- 文件职责及实施内容：覆盖25K/1M、Auto vs Hard、count mismatch、L1-L5、multi-epoch、auto unresolved、manual/no-op、HistoryRead、overflow once/twice、incremental facts、crash、resume、old schema、model switch、Headless/TUI。
- 依赖任务：Task 7。
- 参考资料：Taskbook第16、18节；docs包级验收。
- 完成边界：定向、E2E、架构和全量pytest结果进入W06 Feedback；真实网络不作为CI必过。

## Task 9：[遗留负担清理] 动态预算与单 Timeline 路径收口

- 任务目标：确认无兼容层、废弃实现、不可达代码、重复职责或未来占位。
- 新增文件：无。
- 修改文件：仅Task 1～8范围内直接失效内容、测试与文档。
- 删除内容：固定258K invariant、Projection authority、Session v1新写入、sync unavailable summarizer、旧overflow path、过时status/docs、无调用方Manager/Registry/Job/Protocol。
- 文件职责及实施内容：用`rg`、imports、architecture tests与dead-code review核对；保留strict sequence、estimator、single-flight、writer safety、Tool externalization与runtime diagnostics。
- 依赖任务：Task 8。
- 参考资料：Taskbook第17、19、20节；AGENTS增量原则。
- 完成边界：cleanup、最终tests、UTF-8 guard与风险写入W06 Feedback；不执行Git写入或归档。
