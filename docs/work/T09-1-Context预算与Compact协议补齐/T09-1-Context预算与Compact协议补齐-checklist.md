# T09-1：Context 预算与 Compact 协议补齐 Checklist

## T01：动态模型限制与确定性请求安全链

- [x] 执行 `python -m pytest tests/test_configuration.py tests/test_config_loader_integration.py tests/test_provider_model_limits.py tests/test_context_budget_gate.py tests/test_context_compiler.py tests/test_application_runtime.py tests/test_application_runs.py tests/test_agent_loop.py -q`，全部通过。
- [x] 用户配置 `context_window` 只接受 positive int；用户缺失且 Provider 无可靠 input metadata 时明确失败，生产代码无固定窗口或 bundled metadata fallback。
- [x] 项目层只能保留/收紧用户 `context_window`；项目补造缺失值或放大用户值均失败。
- [x] `max_input_tokens`、`max_output_tokens`、可选 `max_combined_tokens` 分维保存与校验；unknown 不伪造，larger Provider input 不扩大用户上限。
- [x] Pressure Estimate 与 Preflight Safety Count/Estimate 来源、allowance、用途可观察；测试不把近似 estimate 断言为数学精确。
- [x] final request accounting 覆盖 instruction、messages、tools、已知 framing 与 requested output reserve；每一维 Hard Gate 都发生在 Provider call 前。
- [x] 25K profile 自适应收缩、1M profile 绝对 cap；存在 `auto_pressure=true && hard_safe=true` 场景。
- [x] L1-L3 deterministic、protected/current/tool pair 完整；每次 reduce 后 rebuild/re-gate；required facts 超限时 Provider call count 为 0。
- [x] 正式 Application→Compiler→现有 awaitable preparer→AgentLoop→Provider path 可运行；`core/agent.py` 未新增重复 async protocol。

## T02：Transcript、Timeline 与 Session v2 一次性硬切

- [x] 执行 `python -m pytest tests/test_history_contract.py tests/test_timeline_contract.py tests/test_context_compiler.py tests/test_context_compaction.py tests/test_session_files.py tests/test_application_runtime.py tests/test_application_runs.py tests/test_w04_session_commands.py -q`，全部通过。
- [x] fresh Session 只创建 `transcript.jsonl`、`timeline.jsonl`、`runtime.jsonl`、`metadata.json`、`writer.lock`、`tool-results/`。
- [x] Transcript strict sequence、Session ownership、closed fact 与完整 ToolCall/ToolResult group 校验通过。
- [x] Timeline 只接受 Fine、Macro、Active checkpoint；模拟 checkpoint 前崩溃时 trailing transaction 不生效。
- [x] Context compiler、Application generation/history/session、Integration store 与生产测试在同一任务迁移到新 authority。
- [x] old v1 `history.jsonl` 明确 incompatible；无 migration、dual read/write、`CanonicalHistory`、`Projection` 或兼容 alias。
- [x] append/reload/半失败、identity reconciliation、unknown durability quarantine、close/reopen 回归通过。

## T03：生产 L4 与 bounded catch-up

- [x] 执行 `python -m pytest tests/test_context_compaction.py tests/test_context_budget_gate.py tests/test_application_runs.py tests/test_t09_1_context_protocol_e2e.py -q`，全部通过。
- [x] L4 使用 frozen provider/model/分维 limits，`tools=()`；Compact request 自身 Hard-gated 且不递归 Auto compact。
- [x] one entry per covered Turn、refs/coverage/summary 校验失败不 append；成功 transaction checkpoint-last。
- [x] one/multi-epoch 每批 commit 后 rebuild/re-gate；retained target 产生 headroom。
- [x] no-progress、repeated failure、no-safe-epoch、cancellation 有限停止且不产生伪 checkpoint。
- [x] Auto unresolved + Hard-safe 可发送并记录原因；Hard-unsafe Provider call count 为 0。
- [x] `rg -n "CompactState|CompactionJob|next_epoch_pointer|COMPACTING_BATCH" src tests` 不存在持久 Compact FSM/Job/pointer。

## T04：L5 Timeline Aging 与 HistoryRead

- [x] 执行 `python -m pytest tests/test_timeline_contract.py tests/test_context_compaction.py tests/test_history_read_tool.py tests/test_application_tools.py tests/test_tool_result_persistence.py -q`，全部通过。
- [x] Fine Timeline 超预算且普通请求低 pressure 时仍可独立触发 L5。
- [x] L5 只选 old complete epoch，证据来自 raw Transcript refs；不以 Fine/Macro 做 summary-of-summary。
- [x] macro 先写、checkpoint 最后写；logical supersede 不删除物理 Timeline。
- [x] 无 safe epoch 时 fail closed，不换模型、不递归、不生成伪 checkpoint。
- [x] HistoryRead 只允许 active Session exact opaque ref bounded page；malformed/cross-session/invalid boundary 均失败。
- [x] HistoryRead output 不递归 externalize，与 ToolResultRead 权限边界独立。

## T05：Application Compact 生命周期与 overflow recovery

- [ ] 执行 `python -m pytest tests/test_application_runtime.py tests/test_application_runs.py tests/test_session_files.py tests/test_t09_1_context_protocol_e2e.py -q`，全部通过。
- [ ] first call 前、complete tool batch 后/next call 前、terminal tail 三边界 durable append closed facts；不写 open continuation。
- [ ] durable cursor 不重复 append；确定失败保持 identity/FIFO retry；unknown durability quarantine 新语义写入。
- [ ] active Turn 冻结 provider/model/input/output/combined limits/tools；切换模型只影响下一 Turn。
- [ ] direct Application/Headless manual compact 在低 pressure 可执行；无候选 success no-op 且 Timeline 无垃圾。
- [ ] ordinary overflow 只执行一次 reduce→rebuild→re-gate→retry；二次 overflow 停止且不修改 limits。
- [ ] ordinary、post-tool、post-resume、manual、L4、L5、retry 每次真实 model call 前均有 Hard Gate 证据。

## T06：[接入主流程] 命令、TUI 与正式入口收口

- [ ] 执行 `python -m pytest tests/test_command_dispatcher.py tests/test_w04_session_commands.py tests/test_cli.py tests/test_tui.py tests/test_application_runtime.py tests/test_t09_1_context_protocol_e2e.py -q`，全部通过。
- [ ] `/compact` await T05 同一 Application orchestrator；`/status` 使用分维 limits/Auto/Hard/Timeline diagnostics。
- [ ] sync commands 不回退，TUI 只 await command outcome；CLI/TUI/Headless 不包含独立 Context 编排。
- [ ] 现有 request preparer 与 overflow handler sync/awaitable 行为、取消和错误测试继续通过；没有第二套 protocol。
- [ ] bootstrap/正式 generation 入口全部接通，旧 synchronous-only compact 和重复入口在本任务删除。

## T07：[端到端验证] Diagnostics、Eval、文档与回归

- [ ] 执行 `python -m pytest tests/test_w05_diagnostics.py tests/test_w06_integration_delivery.py tests/test_t09_1_context_protocol_e2e.py tests/test_architecture_boundaries.py -q`，全部通过。
- [ ] 正式 Headless Application 完成 ordinary、tool loop、L4/catch-up、L5、HistoryRead、manual no-op/success、overflow once 与 hard-fail e2e。
- [ ] diagnostics/status 只含分维 limits、count source、allowance、Auto/Hard、Timeline id/coverage/reason/outcome，不含 Transcript/summary/Tool Result/API key/异常正文。
- [ ] Eval 保持并列指标，不新增总分，不把 tuning default 写成产品成功阈值。
- [ ] `docs/Tools.md`、用户手册、Core Design、A03/A04、`docs/Context-Index.md` 与 `src/ + tests/` 一致。
- [ ] 执行任务书列出的 T05/T06/T08 回归集合与 `python -m pytest -q`；精确命令、passed/failed/skipped 写入 Feedback，真实网络不作为必过条件。

## T08：[遗留负担清理] 删除阶段性与兼容逻辑

- [ ] `rg -n "UTHCODE_CONTEXT_BUDGET_TOKENS|fixed 258K|固定 258K|before T09-1|summarizer_unavailable" src tests eval docs` 只剩冻结历史/归档证据；生产代码与当前事实文档旧 authority 为 0。
- [ ] `rg -n "\bProjection\b|\bCanonicalHistory\b|history\.jsonl" src/uthcode tests` 不存在生产 contract、旧 writer 或兼容 alias；old-v1 fixture 的唯一保留原因写入 Feedback。
- [ ] `rg -n "bundled.*model|model.*catalog|hard.?coded.*context" src/uthcode tests docs` 确认 bundled metadata / model catalog / hardcoded official model window 路线在源码、测试、当前事实文档和 `docs/OutstandingDebtList.md` 中均保持不存在，且未重新登记为 future debt。
- [ ] Timeline 产品 record 仍只有三类；无持久 FSM/Job/pointer、独立 compaction model、跨 Provider fallback、无调用方 Manager/Registry/Scheduler。
- [ ] Permission、Plan/Todo、Runtime Hook、其它 Slash Commands 与 TUI rendering 无范围外重构。
- [ ] 清理后重跑最小定向、`tests/test_architecture_boundaries.py` 与全量测试，精确结果写入 `feedback/W06-delivery-regression-cleanup-feedback.md`。
- [ ] 逐条复核 `docs/OutstandingDebtList.md` 中所有被 T09-1 实际改变的条目：`T02 Slash Command / TUI` 只移除已回补的 `/compact` 部分并保留 `/memory`、`/dream`；`B01 私有测试集 v0` 按真实 Compaction 结果删除或更新相关部分；三条 T09 Context 欠账只有实现、Checklist、Feedback 证据齐全才删除；其它条目按“完全回补删除、部分改变更新、仍成立保留、用户取消删除且不转登记”处理。
- [ ] `docs/Context-Index.md` 在全部实现与反馈完成后更新为 `implemented_unarchived`；工作包留在 `docs/work/` 等待用户手动归档。
