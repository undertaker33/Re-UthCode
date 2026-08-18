# T09-1：Context 预算与 Compact 协议补齐 Checklist

## T01：模型窗口、Provider 能力与双 Gate 预算

- [ ] 执行 `python -m pytest tests/test_configuration.py tests/test_config_contract.py tests/test_provider_model_limits.py tests/test_context_budget_gate.py tests/test_anthropic_integration.py -q`，全部通过。
- [ ] 配置缺失、布尔值、零或负 `context_window` 时均 fail；positive int 可构造 runnable model，且生产代码不存在隐式固定窗口 fallback。
- [ ] fake Provider 证明 reliable input ceiling 只收紧 C、缺失 ceiling 时 E=C、larger ceiling 不扩大 C，OpenAI/Compat 不伪造 capability。
- [ ] Provider/local count 均带 source/kind 和非零有界 uncertainty；Hard Gate 基于 final request 的 input、output reserve 与 uncertainty。
- [ ] 25K profile 的 headroom/A/F/U/compact budget 自动收缩；1M profile 的 headroom 与 retained profile 有绝对 cap，不按固定百分比线性增长。
- [ ] 构造并断言 `auto_pressure=true` 且 `hard_safe=true` 的 proactive reduction 场景。

## T02：Transcript、Timeline 与 Session v2

- [ ] 执行 `python -m pytest tests/test_history_contract.py tests/test_timeline_contract.py tests/test_session_files.py -q`，全部通过。
- [ ] fresh Session 只创建 v2 布局：`transcript.jsonl`、`timeline.jsonl`、`runtime.jsonl`、`metadata.json`、`writer.lock`、`tool-results/`。
- [ ] Transcript strict sequence、current Session ownership 与完整 ToolCall/ToolResult semantic group 校验可观测通过。
- [ ] Timeline 只接受 `SemanticEntry`、`EpochMacroSummary`、`ActiveCheckpoint`；派生 records 后 checkpoint 最后提交。
- [ ] 模拟 entries 已落盘但 checkpoint 未提交，loader 忽略 trailing incomplete transaction 并恢复前一有效 logical view。
- [ ] old v1 `history.jsonl` Session 返回明确 incompatible；代码中不存在 migration、dual read、dual write 或旧 alias。
- [ ] append/reload/metadata 半失败、identity reconciliation、unknown durability quarantine 与 close/reopen recovery 回归通过。

## T03：最终请求计数与确定性 L1-L3

- [ ] 执行 `python -m pytest tests/test_context_compiler.py tests/test_context_budget_gate.py tests/test_tool_result_persistence.py -q`，全部通过。
- [ ] final request accounting 覆盖 system、messages、tools、requested output 与已知结构 overhead，且发生在 Provider call 之前。
- [ ] L1 复用 Tool Result externalization；L2 preview shrink/mask 可重复且 bounded；L3 只省略 inactive complete semantic unit。
- [ ] protected context、current Turn 和 ToolCall/ToolResult pair 在所有 reduction 中保持完整。
- [ ] L1-L3 后仍高于 Auto Gate 但 Hard-safe 时结果为 L4-required；清除 Auto pressure 且 Hard-safe 时不调用 L4。
- [ ] required protected/current facts 自身超过 E 时返回 unresolvable，fake Provider call count 为 0。

## T04：生产 L4 与 bounded catch-up

- [ ] 执行 `python -m pytest tests/test_agent_loop.py tests/test_context_compaction.py tests/test_context_budget_gate.py tests/test_application_runs.py tests/test_t09_1_context_protocol_e2e.py -q`，全部通过。
- [ ] fake Provider 断言 L4 使用 frozen main provider/model/C、`tools=()`，且 compact request 自身 Hard-gated、不递归 Auto compact。
- [ ] L4 output 必须 one entry per covered Turn、refs/coverage/summary 均合法；parse/coverage 失败不 append。
- [ ] one-epoch 与 multi-epoch B′ 都在每批 checkpoint-last commit 后 rebuild 并重做 Auto/Hard Gate。
- [ ] retained target 产生明显 headroom；no-progress、repeated failure、no-safe-epoch 在有限尝试内停止。
- [ ] cancellation 不提交 entries/checkpoint；Auto unresolved + Hard-safe 可发送并记录原因；Hard-unsafe call count 为 0。
- [ ] `rg -n "CompactState|CompactionJob|next_epoch_pointer|COMPACTING_BATCH" src tests` 不存在持久 Compact FSM/Job/pointer 实现。

## T05：L5 Timeline Aging 与 HistoryRead

- [ ] 执行 `python -m pytest tests/test_timeline_contract.py tests/test_context_compaction.py tests/test_history_read_tool.py tests/test_application_tools.py tests/test_tool_result_persistence.py -q`，全部通过。
- [ ] Fine Timeline > F 且普通请求低于 Auto Gate 时仍可独立触发 L5。
- [ ] L5 只选择 old complete compact epoch，prompt evidence 来自 raw Transcript refs；测试证明不以 Fine/Macro summary 做 summary-of-summary。
- [ ] L5 成功时 macro record 先写、checkpoint 最后写；logical view supersede old Fine coverage，物理 Timeline 不删除。
- [ ] raw evidence 无 safe epoch 时明确失败且不换模型、不递归 compact、不生成伪 checkpoint。
- [ ] HistoryRead 只允许 current Session exact opaque ref 的 bounded page；malformed、cross-session、invalid boundary 均 fail closed。
- [ ] HistoryRead output 不递归 externalize，且 ToolResultRead 与 HistoryRead 互不越权。

## T06：[接入主流程] 生命周期、命令与 overflow recovery

- [ ] 执行 `python -m pytest tests/test_application_runtime.py tests/test_application_runs.py tests/test_command_dispatcher.py tests/test_w04_session_commands.py tests/test_tui.py tests/test_t09_1_context_protocol_e2e.py -q`，全部通过。
- [ ] before first Provider call、after complete Tool batch/before next call、terminal tail 三个边界均 durable append closed Transcript facts；不写 open continuation。
- [ ] durable cursor 不重复 append；真实 append failure 保留原 Session/Turn identity FIFO retry；unknown durability quarantine 新语义写入。
- [ ] active Turn 切换 `/model` 后 frozen provider/model/C 不变，下一 Turn 使用新 model profile C。
- [ ] `/compact` 可 await 同一 Application orchestrator；低于 Auto Gate 仍可有价值压缩，无候选时 success no-op 且 Timeline 无新增。
- [ ] ordinary overflow 第一次执行 forced reduction、rebuild、Hard Gate 后只 retry 一次；第二次 overflow 失败且 C/E 不变。
- [ ] sync commands 行为不回退，TUI 只 await command outcome；CLI/TUI/Headless 不包含独立 Context 编排。
- [ ] fake Provider 证明 ordinary、post-tool、post-resume、manual、L4、L5、retry 每次真实 model call 前均通过 Hard Gate。

## T07：[端到端验证] Diagnostics、Eval、文档与回归

- [ ] 执行 `python -m pytest tests/test_w05_diagnostics.py tests/test_w06_integration_delivery.py tests/test_t09_1_context_protocol_e2e.py tests/test_architecture_boundaries.py -q`，全部通过。
- [ ] 从正式 Headless Application 完成普通请求、tool loop、自动 L4/B′、L5、HistoryRead、manual no-op/success、overflow once 与 hard-fail e2e。
- [ ] diagnostics/status 只含 C/E、count source、Auto/Hard、Timeline coverage/id/reason、pressure/compaction outcome，不含 Transcript、summary、Tool Result、API key 或异常正文。
- [ ] Eval 继续并列比较 success/token/tool calls/compaction/pressure 等维度，不新增总分，不把内部 tuning default 写成产品成功阈值。
- [ ] `docs/Tools.md`、用户手册、Core Design、A03/A04 当前事实和 `docs/Context-Index.md` 均与 `src/ + tests/` 一致，明确 C/E、双 Gate、L1-L5、B′、manual、HistoryRead、overflow once、resume 边界与 v1 incompatible。
- [ ] 执行 `python -m pytest tests/test_application_runs.py tests/test_agent_interaction.py tests/test_permission.py tests/test_planning.py tests/test_runtime_hooks.py -q`（若实际文件名不同，使用仓库中对应 T05/T06/T08 定向集合），全部通过并在 Feedback 记录精确命令。
- [ ] 执行 `python -m pytest -q`，全量通过；真实 Provider 网络调用未作为必过条件。

## T08：[遗留负担清理] 删除阶段性与兼容逻辑

- [ ] `rg -n "UTHCODE_CONTEXT_BUDGET_TOKENS|fixed 258K|固定 258K|before T09-1|summarizer_unavailable" src tests eval docs` 只剩冻结历史需求/归档证据或明确不属于当前事实的引用；生产代码和当前文档为 0 条旧 authority/旧阶段文案。
- [ ] `rg -n "\bProjection\b|history\.jsonl" src/uthcode tests` 不存在 Projection 生产 contract、旧 Session 新写入或 compatibility alias；若测试构造 old v1 incompatible fixture，Feedback 列出唯一保留原因。
- [ ] `rg -n "dual[_ -]?(read|write)|migration|compat(ibility)?" src/uthcode` 不存在为旧 T09 Session 新增的迁移或双轨逻辑。
- [ ] 代码审查确认 Timeline 产品 record 仍只有三类，B′ 无持久 FSM/Job/pointer，Compact 无独立 model/跨 Provider fallback，无新增无调用方 Manager/Registry/Scheduler/Event Bus。
- [ ] 代码审查确认 Permission、Plan/Todo、Runtime Hook、其它 Slash Commands 与 TUI rendering 未发生范围外重构。
- [ ] 清理后重跑最小受影响定向测试、`tests/test_architecture_boundaries.py` 与 `python -m pytest -q`，精确结果追加到 `feedback/W06-delivery-regression-cleanup-feedback.md`。
- [ ] `docs/OutstandingDebtList.md` 仅在 T01～T08 全部完成且 Feedback 已记录后删除本包已回补的三项 T09 欠账；没有新增一般 Out of Scope 欠账。
- [ ] `docs/Context-Index.md` 在 Checklist 全部完成且 Feedback 已记录后把 T09-1 更新为 `implemented_unarchived`；工作包保持在 `docs/work/`，等待用户手动归档。
