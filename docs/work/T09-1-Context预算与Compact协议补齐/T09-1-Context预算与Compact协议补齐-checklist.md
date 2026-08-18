# T09-1 Context 预算与 Compact 协议补齐 Checklist

## Task 1：Model Context Profile 与统一 Budget Resolver

- [ ] 执行 `python -m pytest tests/test_configuration.py tests/test_config_contract.py tests/test_context_budget_gate.py tests/test_provider_model_limits.py -q`，全部通过。
- [ ] 25K、128K、258K、1M model profile 均解析出正整数 `C`；25K 下 A/F/U/compact budget 会缩小，1M 下 retained target 不随 C 线性放大。
- [ ] configured C 小于 reliable ceiling 时使用 configured C；大于 ceiling 时 Provider request count 为 0 并产生安全失败；无 metadata 时不伪造 ceiling。
- [ ] `rg -n "UTHCODE_CONTEXT_BUDGET_TOKENS|budget_tokens != UTHCODE_CONTEXT_BUDGET_TOKENS" src/uthcode` 不再命中固定预算唯一 invariant。
- [ ] Anthropic SDK model/token-count fixture 只在 Integration 出现，Core/Application 断言只消费 UthCode-owned DTO。

## Task 2：Transcript / Timeline Contract 与 Session v2

- [ ] 执行 `python -m pytest tests/test_history_contract.py tests/test_timeline_contract.py tests/test_session_files.py -q`，全部通过。
- [ ] fresh Session 目录包含 `metadata.json`、`writer.lock`、`transcript.jsonl`、`timeline.jsonl`、`runtime.jsonl`、`tool-results/`，且不新建 `history.jsonl`。
- [ ] Timeline 只接受 SemanticEntry、EpochMacroSummary、ActiveCheckpoint 三种产品记录；非法 coverage/ref/record 顺序被拒绝。
- [ ] entries 已写但 checkpoint 未写、partial JSON line、semantic incomplete tool group 均不会进入 recovered logical view。
- [ ] old Session schema deterministic incompatible；代码中不存在 migration、dual read 或 dual write。
- [ ] single writer、append reconciliation、unknown durability quarantine 与 close/reopen recovery 测试通过。

## Task 3：ContextCompiler logical view 与确定性 L1-L3

- [ ] 执行 `python -m pytest tests/test_context_compiler.py tests/test_context_budget_gate.py tests/test_tool_result_persistence.py -q`，全部通过。
- [ ] L1 externalization、L2 bounded preview shrink、L3 inactive raw omission 的测试均断言没有额外模型调用。
- [ ] ToolCall/ToolResult pair、protected instruction block、current user turn 不会被拆分或错误省略。
- [ ] macro coverage 在 logical view 中 supersede old fine entries；追加物理无效/已覆盖 records 不改变 F 计算。
- [ ] protected required context + current turn 无法装入 C 时返回 `context_unresolvable`，Provider call count 为 0。
- [ ] diagnostics fixture 只含 ID/count/token/budget/reason，不含消息、summary 或 Tool result 正文。

## Task 4：Production L4 与 bounded catch-up

- [ ] 执行 `python -m pytest tests/test_context_compaction.py tests/test_context_budget_gate.py tests/test_application_runs.py tests/test_t09_1_context_protocol_e2e.py -q`，全部通过。
- [ ] 单 epoch 与 multi-epoch fixture 均使用当前 Turn 冻结的 provider/model/C，compact `GenerationRequest.tools` 为空。
- [ ] 每个成功 epoch 的 Timeline 最后一条是 ActiveCheckpoint；commit 后立即 rebuild + Gate。
- [ ] 800K raw / 1M C 场景不会因单 epoch cap 提前把主工作窗口降至小窗口，真实 pressure 后可由多个 bounded epoch 达到安全。
- [ ] invalid parse、coverage 不推进、token 无下降、repeated failure 和 finite-attempt breaker 均在有限调用次数内 fail closed。
- [ ] cancellation 与 checkpoint 前 crash 不提交伪 checkpoint；checkpoint 后 crash 可由 durable facts 推导下一 epoch。
- [ ] `rg -n "CompactionJob|BackgroundCompactor|CompactState|compaction_model" src tests` 不命中本任务新增的独立状态机/模型角色。

## Task 5：L5 Timeline Aging 与 HistoryRead

- [ ] 执行 `python -m pytest tests/test_timeline_contract.py tests/test_context_compaction.py tests/test_history_read_tool.py tests/test_application_tools.py tests/test_tool_result_persistence.py tests/test_context_budget_gate.py -q`，全部通过。
- [ ] L5 request evidence 来自 raw Transcript refs，fixture 证明不把 old SemanticEntry summary 作为权威输入。
- [ ] macro summary + final checkpoint 生效后旧 fine entries 物理仍存在、逻辑被 coverage 替代，Fine Timeline 回到 F。
- [ ] 当前模型无法安全读取任一 old epoch raw evidence 时无模型切换、无 checkpoint，并返回安全失败。
- [ ] HistoryRead current Session exact ref 正常分页；malformed ref、cross-session ref、任意路径和越界 range 均 fail closed。
- [ ] HistoryRead 输出有固定上限、只读、不搜索，且不会递归 externalize；ToolResultRead 行为不回退。

## Task 6：Incremental Transcript、Manual Compact 与 Overflow Retry

- [ ] 执行 `python -m pytest tests/test_application_runtime.py tests/test_application_runs.py tests/test_session_files.py tests/test_command_dispatcher.py tests/test_w04_session_commands.py tests/test_tui.py tests/test_t09_1_context_protocol_e2e.py -q`，全部通过或对与本任务无关的既有失败提供可复现证据并明确保持未验收状态。
- [ ] first call 前 user fact、post-tool next call 前完整 Tool group、terminal final tail 均 durable；open streaming fragment、unmatched ToolCall、continuation 不持久化。
- [ ] 已 durable message identity 不重复 append；unknown durability 后 active Session 新 Run/语义写入 fail closed，close/reopen 后按既有 contract 恢复。
- [ ] `/compact` 有候选时使用同一 Session/orchestrator 且不创建 Run/Turn；无候选 success no-op 且 Timeline record count 不变。
- [ ] 同 Session并发 compact 只有一个进入模型调用，其余 fail safe；未创建 background job 或持久 attempt state。
- [ ] 首次 overflow 最多执行一次 forced reduction + rebuild + retry；第二次 overflow 终止，C 保持不变。
- [ ] `/status` 展示 used/C、estimator、reserve、A/F/U、last Gate action、L1-L5 counters、checkpoint/epoch diagnostics，且不含 Context 正文。
- [ ] active Turn 内 `/model` 后该 Turn 的 provider/model/C 不变，下一 Turn 使用新 profile。

## Task 7：Diagnostics、Eval 与文档同步

- [ ] 执行 `python -m pytest tests/test_w05_diagnostics.py tests/test_w06_integration_delivery.py tests/test_architecture_boundaries.py -q`，全部通过。
- [ ] Eval fixture 只消费公开 Timeline/Gate diagnostics；不读取 raw Transcript/summary/Tool result/secret，不新增总分或效果阈值产品断言。
- [ ] `docs/user-manual/configuration.md` 说明 model `context_window` 的 operating 语义和安全边界；`docs/user-manual/commands.md` 说明可用 `/compact` 与动态 `/status`。
- [ ] 核心设计与当前事实文档明确 Transcript vs Timeline、C vs physical ceiling、L1-L5、B′ 无 Compact FSM、resume 不恢复 Runtime、old Session incompatible。
- [ ] `rg -n "fixed 258K|固定 258K|before T09-1|summarizer_unavailable|Projection revision" README.md docs eval` 不再把已替代阶段性语义描述为当前能力。
- [ ] 对全部本 Worker 修改的 Markdown 运行 UTF-8 guard，UTF-8 解码、replacement character、常见乱码和 fence balance 均通过。

## Task 8：[接入主流程] 单一 Context Orchestration 收口

- [ ] 从 `create_application -> ensure_session/create_run -> AgentRun -> request preparation -> Application Context Gate -> ProviderPort` 追踪所有正式 model call，均无绕过 Hard Gate 的入口。
- [ ] L4/L5 model call 经过独立 input/output Gate、无 Agent Tools，并复用 frozen/current provider/model 选择规则。
- [ ] Interface 只调用 Application command/use case；Core 无 filesystem/network/SDK/Application/Interface import；Integration 无 Application/Interface import。
- [ ] `rg -n "history\.jsonl|class Projection|summarizer_unavailable" src/uthcode` 不存在旧 Session 新写入、Projection authority 或 unavailable summarizer 生产路径。
- [ ] 执行 `python -m pytest tests/test_architecture_boundaries.py tests/test_application_runtime.py tests/test_application_runs.py -q`，全部通过。

## Task 9：[端到端验证] Context / Compact / Recovery

- [ ] 执行 `python -m pytest tests/test_t09_1_context_protocol_e2e.py -q`，从真实 Application/Session/Run/Command adapter 入口覆盖正常请求、manual compact、HistoryRead、overflow、resume 与 crash boundary，全部通过。
- [ ] E2E 明确覆盖 initial、post-tool、post-resume、L4、L5 每类 Provider call 的 Gate evidence，以及 impossible request 的 provider call count = 0。
- [ ] E2E 明确覆盖旧 Session reject、checkpoint 前后 crash、incremental closed facts、1M multi-epoch 与 25K no-safe-epoch。
- [ ] 执行任务相关定向集合与 `python -m pytest tests/test_architecture_boundaries.py -q`，记录 passed/failed/skipped 和耗时。
- [ ] 执行 `python -m pytest -q` 全量回归并在 Feedback 记录精确结果；任何失败均不得描述为通过。
- [ ] Headless 路径不导入 TUI，TUI `/compact` 只作为 async command adapter，不拥有 Context 状态。

## Task 10：[遗留负担清理] 单 Transcript / Timeline 路径收口

- [ ] `rg -n "UTHCODE_CONTEXT_BUDGET_TOKENS|CanonicalHistory|class Projection|ProjectionAppend|summarize=None|before T09-1" src tests eval docs` 的剩余命中逐项证明有真实职责，否则删除。
- [ ] `rg -n "ContextManager|CompactManager|TimelineRegistry|ModelCatalogManager|CompactionJob|BackgroundCompactor|compaction_model" src tests` 返回 0 条本任务新增系统级抽象。
- [ ] `rg -n "memory|embedding|vector|runtime checkpoint|pending tool recovery|timeline gc" src/uthcode` 的本任务新增命中为 0，或仅为明确的错误/边界文案且已审查。
- [ ] 没有旧 Session migration/dual read/dual write、兼容 alias、废弃 export、不可达 branch、重复 Context compiler 或 Interface-owned orchestration。
- [ ] W07 Feedback 列出实际改动、机制、文件、精确测试结果、Checklist 状态、与任务书差异、未完成项/风险及清理结果。
- [ ] 不执行 Git commit、push、merge、rebase、tag、release，不移动工作包到 `docs/work/archive/`。
