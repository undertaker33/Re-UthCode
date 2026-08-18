# T09-1 Context 预算与 Compact 协议补齐 Checklist

## Task 1：模型窗口、计数能力与双 Gate 预算契约

- [ ] 执行`python -m pytest tests/test_configuration.py tests/test_config_contract.py tests/test_provider_model_limits.py tests/test_context_budget_gate.py -q`全部通过。
- [ ] Auto Gate与Hard Gate对同一projection可产生不同结果；不存在统一`0.9 * C`规则。
- [ ] 25K headroom小于大窗口16K/20K reserve；1M headroom受32K初始default cap约束，不浪费100K级空间。
- [ ] `E=min(C,reliable ceiling)`；无metadata不伪造ceiling；configured C更小时不被扩大。
- [ ] provider count与local estimate有不同、正且有上限的uncertainty；裸local estimate小于E不直接视为Hard safe。
- [ ] Anthropic SDK类型只在Integration；Core/Application只消费UthCode-owned DTO。

## Task 2：Transcript / Timeline 与 Session v2 持久事实

- [ ] 执行`python -m pytest tests/test_history_contract.py tests/test_timeline_contract.py tests/test_session_files.py -q`全部通过。
- [ ] fresh Session包含`metadata.json`、`writer.lock`、`transcript.jsonl`、`timeline.jsonl`、`runtime.jsonl`、`tool-results/`，不新建`history.jsonl`。
- [ ] Timeline只接受SemanticEntry、EpochMacroSummary、ActiveCheckpoint；Compact Epoch不成为第四种record。
- [ ] entries已写但checkpoint未写、partial JSON、incomplete Tool group均不进入logical committed view。
- [ ] old schema deterministic incompatible；无migration/dual read/dual write。
- [ ] single writer、reconciliation、unknown durability quarantine与close/reopen recovery通过。

## Task 3：最终请求组装、Auto/Hard Gate 与确定性 L1-L3

- [ ] 执行`python -m pytest tests/test_context_compiler.py tests/test_context_budget_gate.py tests/test_tool_result_persistence.py tests/test_application_runs.py -q`全部通过。
- [ ] input count基于最终`system_prompt + messages + tools + request parameters`结构，requested output reserve和uncertainty进入Hard projection。
- [ ] L1-L3均无模型调用且不拆ToolCall/ToolResult、protected blocks或current turn。
- [ ] L1-L3从259K降至257K但仍高于Auto Gate时返回L4-required，而不是因低于258K放行。
- [ ] L1-L3已清除Auto pressure且Hard safe时不执行L4。
- [ ] Hard unsafe时Provider call count为0；diagnostics无正文。

## Task 4：L4 proactive semantic compaction 与 B′

- [ ] 执行`python -m pytest tests/test_context_compaction.py tests/test_context_budget_gate.py tests/test_application_runs.py tests/test_t09_1_context_protocol_e2e.py -q`全部通过。
- [ ] L4使用active Turn冻结provider/model/C，request tools为空且自身通过Hard Gate。
- [ ] 每个epoch先Fine entries后ActiveCheckpoint；每批后立即rebuild/recount/Auto+Hard re-gate。
- [ ] 1M场景只在真实pressure后执行多个bounded epoch，并回到retained target。
- [ ] no-progress/repeated-failure/finite breaker有限结束；cancel/checkpoint前crash不提交伪checkpoint。
- [ ] Auto pressure无法清除但Hard safe时发送并记录`auto_pressure_unresolved`；Hard unsafe仍不发送。
- [ ] `rg -n "CompactionJob|BackgroundCompactor|CompactState|compaction_model" src tests`无本任务新增命中。

## Task 5：L5独立老化与 HistoryRead

- [ ] 执行`python -m pytest tests/test_timeline_contract.py tests/test_context_compaction.py tests/test_history_read_tool.py tests/test_application_tools.py tests/test_tool_result_persistence.py tests/test_context_budget_gate.py -q`全部通过。
- [ ] Fine Timeline超过F时即使Auto/Hard无pressure也触发L5。
- [ ] L5 input来自raw Transcript refs，不以old summary为权威；macro后checkpoint last。
- [ ] 当前模型无safe epoch时无model switch、无checkpoint并返回安全失败。
- [ ] HistoryRead current Session exact ref正常分页；malformed/cross-session/path/range逃逸fail closed。
- [ ] HistoryRead bounded、read-only、no search且不递归externalize；ToolResultRead不回退。

## Task 6：运行生命周期、手动 Compact、Overflow、Diagnostics 与文档

- [ ] 执行Task 6列出的runtime/session/command/TUI/diagnostics/architecture测试全部通过，或明确记录真实未验收失败。
- [ ] first call前user fact、post-tool前complete group、terminal tail durable；open fragment/continuation不持久化。
- [ ] manual `/compact`低于Auto Gate仍可执行；无候选successful no-op且Timeline count不变。
- [ ] same Session并发compact只有一个进入model call，无background job/persisted attempt。
- [ ] 首次overflow最多一次forced reduction/rebuild/Hard Gate/retry；第二次终止且C不变。
- [ ] initial、post-tool、post-resume、manual、L4、L5、retry每类call均有Hard Gate evidence。
- [ ] `/status`展示C/E/R/Auto/Hard/count source/L1-L5/checkpoint，且无Context/summary/Tool/secret正文。
- [ ] active Turn内切模型不改变provider/model/C/capability，下一Turn使用新profile。
- [ ] docs与Eval同步实际事实；修改Markdown通过UTF-8 guard。

## Task 7：[接入主流程] 单一 Context Request Orchestration

- [ ] 追踪`create_application -> create_run/direct generation -> awaited request preparation -> Application Context Orchestrator -> ProviderPort`，无绕过入口。
- [ ] L4/L5/manual/retry均复用同一orchestrator；Interface只调用Application。
- [ ] Core无filesystem/network/SDK/Application/Interface import；Integration无Application/Interface import。
- [ ] `rg -n "history\.jsonl|class Projection|summarizer_unavailable" src/uthcode`无旧生产职责命中。
- [ ] 执行architecture、application runtime/runs测试全部通过。

## Task 8：[端到端验证] Dual Gate / Compact / Recovery

- [ ] 执行`python -m pytest tests/test_t09_1_context_protocol_e2e.py -q`，从正式入口覆盖完整协议并全部通过。
- [ ] E2E覆盖25K/1M、Auto vs Hard、provider/local count mismatch、L1-L5、auto unresolved与provider call count=0。
- [ ] E2E覆盖manual/no-op、HistoryRead、overflow once/twice、checkpoint前后crash、resume、old schema与model switch。
- [ ] 执行任务相关定向集合与`tests/test_architecture_boundaries.py`，记录passed/failed/skipped和耗时。
- [ ] 执行`python -m pytest -q`全量回归并记录精确结果；任何失败不得描述为通过。
- [ ] Headless不导入TUI；TUI只做command adapter。

## Task 9：[遗留负担清理] 动态预算与单 Timeline 路径收口

- [ ] `rg -n "UTHCODE_CONTEXT_BUDGET_TOKENS|CanonicalHistory|class Projection|ProjectionAppend|summarize=None|before T09-1" src tests eval docs`剩余命中逐项有真实职责，否则删除。
- [ ] `rg -n "ContextManager|CompactManager|TimelineRegistry|ModelCatalogManager|CompactionJob|BackgroundCompactor|compaction_model" src tests`无本任务新增系统级抽象。
- [ ] 无旧Session compatibility、废弃export、不可达branch、重复compiler或Interface-owned orchestration。
- [ ] 无Memory/Retrieval、Runtime checkpoint、Timeline GC、background agent、Subagent/Multi-Agent占位。
- [ ] W06 Feedback列出实际改动、机制、文件、精确测试、Checklist、差异、风险、cleanup与UTF-8结果。
- [ ] 不执行commit/push/merge/rebase/tag/release，不移动工作包到archive。
