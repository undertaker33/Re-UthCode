# T09 Prompt 与 Context Engineering Checklist

## Task 1 — Prompt Asset 与 Core Runtime Contract 分离

- [ ] 执行 `python -m pytest -q tests/test_system_prompt.py`，覆盖 asset 缺失/空文本、source/wheel package resource、确定顺序和 stable prefix，全部通过。
- [ ] 检查 `coding_agent.md` 不含 BehaviorMode、Plan/Task、RuntimeFeedback 和 Tool schema，修改 asset 不能删除 Core Runtime Contract。

## Task 2 — Semantic History / Projection Core Contract

- [ ] 执行 `python -m pytest -q tests/test_history_contract.py`，覆盖九类 Interaction、Projection round-trip、unknown schema/kind、sequence/id/ref 和 boundary 失败路径，全部通过。
- [ ] 构造 ToolCall/ToolResult 配对中间的 compact boundary，观察到受控拒绝且原 records 不变。

## Task 3 — JSONL Session Files 与 Runtime Log

- [ ] 执行 `python -m pytest -q tests/test_session_files.py`，覆盖 durable append、严格 sequence、尾部半写容错、中间损坏硬失败、unknown semantic kind 和 runtime log 非权威性，全部通过。
- [ ] 用两个 project key 和超过 10 个 Session 验证候选只返回当前项目，按 durable `last_used_at DESC` 排序，并能读取首条 User Message preview。
- [ ] 重建 Session service 后，观察到原 session id、完整 Interaction、最新合法 Projection 和 result namespace 保持，且测试只写入临时 root。

## Task 4 — 大 Tool Result 外置与 ToolResultRead

- [ ] 执行 `python -m pytest -q tests/test_tool_core.py tests/test_provider_contract.py tests/test_agent_loop.py tests/test_tool_result_persistence.py`，全部通过。
- [ ] 在外置阈值上下分别执行 Tool；大结果持久文件 hash 与原文相同，模型 working view 只含确定 preview/ref/size，小结果保持 inline。
- [ ] 对有效 range、伪造 ref、路径文本、跨 Session ref 和写入失败路径执行测试，观察到 fail closed，且 ToolCall ID、FIFO、is_error、Permission 与取消语义不变。

## Task 5 — Context Compiler、Budget 与 Working Set

- [ ] 执行 `python -m pytest -q tests/test_context_compiler.py`，覆盖相同输入确定性、固定 258K window、预算正好/超限、Tool schema 估算、output reserve 和 safety margin，全部通过。
- [ ] 构造超预算历史，观察到 current user、Runtime State、active Projection、Environment 必需事实与未闭合 Tool 语义单元被保留，recent tail 从完整安全边界开始。
- [ ] 检查 Context diagnostics 可 JSON/display-safe，不包含 API key、完整外置 Tool Result、Provider native payload 或未脱敏异常。

## Task 6 — 按需 Compactor 与 Projection Commit

- [ ] 执行 `python -m pytest -q tests/test_context_compaction.py`，覆盖 manual、auto、reactive overflow 单次 retry、第二次 overflow 硬失败、取消、ToolCall/invalid summary 拒绝和二次 compact，全部通过。
- [ ] 对每个失败路径比较 compact 前后 history，观察到无新 Projection 且 active Projection 不变；成功两次时观察到两条不可变 Projection 和正确 previous link。
- [ ] 检查 Compactor request 不携带 Tool、Permission、UI state、Runtime Log 或 AgentLoop，且取消沿现有 token 传播。

## Task 7 — 跨 Turn Runtime State 与正式 Request Composition

- [ ] 执行 `python -m pytest -q tests/test_agent_loop.py tests/test_application_runs.py tests/test_application_runtime.py`，覆盖多 Turn、completed reset、failed/cancelled unfinished continuation、approved Plan、one-shot feedback 清理和 compaction 前后，全部通过。
- [ ] 记录 Fake Provider 收到的正式 Agent requests，断言消费 Context Snapshot 而不是无条件全量 Run messages，同时 RunState 仍由 Agent Loop 唯一写入。
- [ ] 执行 T06/T08 Pause、AskUser、Permission、Plan Review、Steering 回归，观察到不重放 Tool、不创建第二 Turn，且 Task/Plan 不被 summary 替代。

## Task 8 — `/compact`、`/new`、`/resume` 与 TUI 产品闭环

- [ ] 执行 `python -m pytest -q tests/test_command_registry.py tests/test_command_completion.py tests/test_command_dispatcher.py tests/test_tui.py`，三个命令不再返回 NOT_IMPLEMENTED，全部用例通过。
- [ ] 验证 idle `/compact` 成功或明确无需压缩，active Turn 返回 unavailable 且不暂停/截断原 Turn；`/new` 创建新 session id 且旧 Session 文件字节不变。
- [ ] 以至少 21 个当前项目 Session 验证 Picker：`last_used_at DESC`、每页 10 条、上下选择、左右翻页、单行首 User Message 省略、Enter 恢复、Esc 不切换 Session。
- [ ] 重启式恢复后观察到原 session id、完整 transcript、最新 Projection 和 result ref 可用，同时没有恢复旧 active/paused Turn、waiter 或 Provider continuation。
- [ ] `/status` 显示线性进度、used/258K 和百分比；输入区显示环形状态与同一百分比；unavailable 和窄终端降级有测试，`/clear` 仍不更换 Session。

## Task 9 — B01 Context Diagnostics 与 Before/After Eval

- [ ] 执行 `python -m pytest -q tests/eval/test_eval_reporting.py tests/eval/test_eval_execution.py`，覆盖 compact count、estimated/actual input、selected/omitted interactions、evidence retention/rediscovery、repeated exploration、externalized count/bytes 和 read hits，全部通过。
- [ ] 对没有 Context facts 的 attempt 断言对应维度为 `not_available`，不由 Eval 估算或猜测；安全字段不包含完整 Tool Result 或秘密。
- [ ] 用相同模型、任务和运行参数的 fixture 验证 pre/post report 可 compare，且概率性质量不作为 pytest 成败断言。

## Task 10 — [接入主流程] 正式 Composition 收口

- [ ] 从 `create_application` 创建 Headless Run，执行多 Turn、大 Tool Result、ToolResultRead、manual/auto compact、重建 Application 后 resume 与 final，整条 Fake Provider 用例通过。
- [ ] 执行 `rg -n "RunState\.messages|_DEFAULT_MAX_RESULT_CHARS|Output truncated to 10000|NOT_IMPLEMENTED" src/uthcode`，所有命中均能被证明不再是正式 Agent Context 直通、永久 Tool Result 截断或三命令占位。
- [ ] 执行 `python -m pytest -q tests/test_architecture_boundaries.py`，Core 不依赖 filesystem/SDK/Interface，Interface 不直连 Core/Integration Session Store，全部通过。

## Task 11 — [端到端验证] Context / Compaction / Evidence

- [ ] 执行 T09 端到端用例，覆盖多 Turn、new/resume/picker/status、大结果重读、manual/auto/reactive compact、二次 Projection、Task/Plan 独立、失败不破坏和 diagnostics，全部通过。
- [ ] 执行 `python -m pytest -q`，记录 passed/failed/skipped 精确数量和耗时。
- [ ] 执行 `python -m compileall -q src tests eval` 和 `python -m pip check`，两者均退出 0。

## Task 12 — [遗留负担清理] 单历史 / 单 Context Path 收口

- [ ] 扫描 `src tests docs eval`，确认不存在永久 10k Tool Result 截断、Interface history authority、Context Compiler 写 Task/Plan、AgentEvent 全量持久化、Prompt Tool schema 副本、fake user compact summary 和 mutable history rewrite。
- [ ] 扫描并确认未引入 Context Worker/Scheduler/第二 Loop、SQLite checkpoint、Context Source Registry、无调用方 Artifact Repository、Provider-specific Context 分支或旧行为兼容层。
- [ ] 根据 `docs/README.md` 维护映射核对 `docs/Tools.md`、命令手册、相关 Core Design、A01/A03/A04/TUI 当前事实和索引，与当前 `src/ + tests/` 一致。
- [ ] 对所有改动 Markdown 执行 UTF-8 decoding、replacement character、mojibake 和 fence balance 检查，全部通过；内链有效，示例不含真实秘密。
- [ ] 执行 `git diff --check` 和 `git status --short`，无 whitespace error，变更只包含 T09 授权范围，且未执行 commit、push、merge、rebase、tag、release 或工作包归档。
