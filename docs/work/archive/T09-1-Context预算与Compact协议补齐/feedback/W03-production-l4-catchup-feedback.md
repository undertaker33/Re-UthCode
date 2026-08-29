# W03：生产 L4 与 bounded catch-up Feedback

## 交付结论

W03 已完成。正式 Agent Turn 现在可以在冻结的主 Provider、model 和分维 limits 下执行 tool-free L4；L4 只在当前调用栈内做有界 epoch catch-up，每次成功后先提交 Timeline，再重建并重新执行 Pressure/Hard Gate。T04～T08、Git 写入和工作包归档均未执行。

## 实际完成

- 新增 `src/uthcode/core/compaction.py`，定义进程内 `CompactionEpoch`、结构化结果、Fine entry 与 `TranscriptRef`/coverage/summary 校验。epoch 只从完整 semantic unit 推导，遇到未闭合 unit 会停止，不跳过它去覆盖后续 Turn。
- `src/uthcode/core/context.py` 增加 bounded epoch 推导、结构化结果解析和 Timeline candidate 构造；成功结果按 covered complete Turn 生成一个 Fine entry，derived records 先于 `ActiveCheckpoint` 写入。旧的 `summarizer_unavailable` 生产/测试路径改为受控的 `summary_function_required`。
- `src/uthcode/application/context.py` 增加 `compact_async`：每次调用最多 4 个 epoch；每个 epoch 的 parse/coverage 失败最多重试一次，no-progress、repeated failure、no-safe-epoch、commit failure 和 cancellation 均有限停止；不写持久 FSM、Job 或 pointer。诊断只记录计数、阶段、attempt、coverage count、预算和失败原因，不写 raw transcript/summary。
- `src/uthcode/application/generation.py` 接通正式 L4：Compact request 使用当前 Turn 冻结的 Provider/model/limits，`tools=()`，独立 Hard Gate，不递归 Auto compact，不切换 model/provider。新增 Provider 精确 count 后的 catch-up hook；当本地预估安全但精确 count 触发 Pressure/Hard 时，先执行一次 bounded L4，再从最新 Timeline 重建、重新 count 和 re-gate。
- 保留现有 `ApplicationSession`/`SessionWriter` 的 Timeline append authority；generation 通过已有 candidate commit 边界提交，因此未重复建设 Session writer 或第二套 persistence protocol。
- 新增 `tests/test_t09_1_context_protocol_e2e.py`，覆盖冻结 request、tool-free compact、精确 count 触发 L4、one Fine per covered Turn、checkpoint-last、多 epoch、headroom、invalid coverage、no-progress、no-safe-epoch、incomplete boundary、cancellation、Auto unresolved + Hard-safe 继续发送，以及 Hard-unsafe 不进入 Provider stream。

## 正式调用边界

1. Active Turn 首次准备时解析并冻结主 Provider、remote model、configured/provider input/output/combined limits，形成 `ContextBudget`。
2. Application 先编译 ordinary request，执行本地 Pressure/Hard Gate；若需要，`compact_async` 从当前 Timeline checkpoint 后推导完整 raw epoch。
3. Compact request 使用相同 Provider/model 和冻结预算，去掉所有 tools，并在 Provider stream 前独立 Hard-gate。响应必须覆盖 epoch 的全部 Turn，refs 只能是 Core 根据 Transcript 生成的 opaque refs。
4. candidate 通过校验后才 append；Timeline transaction 的 checkpoint 始终最后写入。提交后重新编译 ordinary request，并继续到 headroom 足够或达到 epoch breaker。
5. 若 Auto 仍 unresolved 但 ordinary request Hard-safe，继续发送并在 `context_compaction` bounded note 记录原因；若 Hard-unsafe，最终 request preparation 在 Provider stream 前失败，测试确认 Provider stream 次数为零。

## 与任务书起点的实际差异

任务书要求读取 `core/compaction.py`，但本次实际起点的当前源码中该文件尚不存在；因此按当前 `src/` 事实新增该 Core contract 模块，并从现有 `core/context.py` 保留统一的 `ContextCompactor` 对外入口，没有创建重复 compactor。`application/sessions.py` 已经具备 transaction append 和 writer durability 边界，本轮没有无必要修改它。上述差异没有扩大到 T04～T08，也没有改变冻结产品语义。

## Checklist T03 证据

T03 七项均已取得实现或测试证据并在 Checklist 中勾选：

- exact T03 pytest 命令：`72 passed`；
- frozen Provider/model/分维 limits、`tools=()`、Compact Hard Gate/no recursive Auto：端到端 fake Provider 断言通过；
- one Fine/ref/coverage/summary 与 checkpoint-last：端到端和 invalid coverage 测试通过；
- one/multi epoch commit/rebuild/re-gate 与 measurable headroom：端到端 headroom 断言及 multi-epoch 测试通过；
- no-progress、repeated failure、no-safe-epoch、cancellation：对应测试均通过且无伪 checkpoint；
- Auto unresolved + Hard-safe 与 Hard-unsafe zero Provider stream：对应测试通过；
- `src tests` 中持久 FSM/Job/pointer 扫描无命中。

## 验证结果

全部命令均使用 Conda 环境 `re-uthcode`：

```text
conda run --no-capture-output -n re-uthcode python -m pytest tests/test_context_compaction.py tests/test_context_budget_gate.py tests/test_application_runs.py tests/test_t09_1_context_protocol_e2e.py -q
72 passed in 7.91s

conda run --no-capture-output -n re-uthcode python -m pytest tests/test_provider_model_limits.py tests/test_history_contract.py tests/test_timeline_contract.py tests/test_session_files.py -q
39 passed in 8.49s

conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q
23 passed in 7.59s

conda run --no-capture-output -n re-uthcode python -m pytest -q --deselect tests/test_tui.py::test_plan_revisions_and_task_state_append_as_distinct_permanent_blocks --deselect tests/test_tui.py::test_renderer_restores_roles_surfaces_markdown_and_code_colours --deselect tests/test_tui.py::test_tool_rows_keep_status_text_and_semantic_colour
1226 passed, 3 skipped, 3 deselected in 140.64s (0:02:20)

conda run --no-capture-output -n re-uthcode python -m compileall -q src/uthcode tests/test_t09_1_context_protocol_e2e.py
passed

rg -n "CompactState|CompactionJob|next_epoch_pointer|COMPACTING_BATCH" src tests
no matches

git diff --check
passed; only existing LF/CRLF normalization warnings, no whitespace error

conda run --no-capture-output -n re-uthcode python C:\Users\93445\.codex\skills\uth-utf8-guard\scripts\check_utf8_docs.py docs/work/T09-1-Context预算与Compact协议补齐/feedback/W03-production-l4-catchup-feedback.md docs/work/T09-1-Context预算与Compact协议补齐/T09-1-Context预算与Compact协议补齐-checklist.md
OK: 2 file(s) passed UTF-8 guard
```

完整 `tests/test_tui.py` 仍为 `69 passed, 3 failed`。失败仍是 W01/W02 已记录、未触及的 Rich ANSI truecolor 断言：

- `test_plan_revisions_and_task_state_append_as_distinct_permanent_blocks`
- `test_renderer_restores_roles_surfaces_markdown_and_code_colours`
- `test_tool_rows_keep_status_text_and_semantic_colour`

本轮未修改 TUI renderer；真实 Provider 网络调用也未执行，验证使用 fake Provider/test doubles。

## 遗留负担与 Git 边界

- `src/` 与 `tests/` 已不再包含 `summarizer_unavailable`；冻结工作包历史文档中的旧术语未修改，T08 扫描与清理不属于本轮。
- 未新增 L5、HistoryRead、manual compact command、独立 compaction model、跨 Provider fallback、持久 Compact FSM/Job/pointer 或 Permission/Plan/Todo/Runtime Hook 范围外逻辑。
- 未执行 commit、push、merge、rebase、tag、release、归档或其它 Git 写操作；工作区原有 `docs/core-design/A04-Orchestration/` 用户文件保持不变。

## W03 第一次验收返工

### 根因与最小修复

验收复现的根因是 `src/uthcode/application/context.py` 的
`ApplicationContextService.compact_async` 用 `except Exception` 同时包住了
`summarize(epoch)`、awaitable 执行、结构化解析和 candidate 构造。`GenerationCancelled`
继承自 `Exception`，Provider 在调用途中直接抛出它且共享 `CancellationToken` 尚未置位时，
因此被误判为可重试的结构化结果错误，导致第二次 summarizer 调用和最终
`repeated_failure`。

本轮仅在该重试边界前显式区分 `GenerationCancelled` 与
`asyncio.CancelledError`，两者均立即向上层传播，不进入有限重试分支。parse、coverage、
refs、summary 等校验异常仍保持原有“最多重试一次”。现有
`generation.py` 的 `GenerationCancelled` 到 `asyncio.CancelledError` 转换，以及
`AgentRun` 的取消出口继续生效；未改变 Context Budget、Compact epoch/checkpoint-last、
bounded catch-up 或其它 T04～T08 范围。

### 新增回归与实际语义

- `tests/test_t09_1_context_protocol_e2e.py` 新增 `GenerationCancelled` 和
  `asyncio.CancelledError` 两个 `compact_async` 直接取消测试：token 初始均未取消，
  summarizer 各只调用 1 次；异常向上层传播；commit candidate、`should_continue`、
  Fine、Timeline、`ActiveCheckpoint` 均为零，Transcript 保持不变。
- 同文件新增正式 Application/AgentRun 链路测试：fake L4 Provider 在第一次 compact
  stream 已进入、token 仍为未取消时抛出 `GenerationCancelled`。compact Provider
  尝试恰为 1 次，ordinary Provider 为 0 次；Run 状态走现有 `CANCELLED` 出口；
  `Timeline.records`、Fine entries、`ActiveCheckpoint` 均保持零伪提交，不继续
  bounded catch-up。
- `src/uthcode/application/context.py` 是本轮唯一生产代码修改；本轮未修改 Checklist，
  T03 cancellation 项在修复和真实测试通过后继续保持完成状态。

### 本轮验证命令与准确结果

以下命令均使用 Conda 环境 `re-uthcode`：

```text
conda run --no-capture-output -n re-uthcode python -m pytest tests/test_t09_1_context_protocol_e2e.py::test_generation_cancelled_during_l4_summarize_is_propagated_once tests/test_t09_1_context_protocol_e2e.py::test_asyncio_cancelled_error_during_l4_summarize_is_propagated_once tests/test_t09_1_context_protocol_e2e.py::test_mid_call_l4_generation_cancelled_uses_agent_run_cancel_exit_without_ordinary_request -q
3 passed in 1.12s

conda run --no-capture-output -n re-uthcode python -m pytest tests/test_context_compaction.py tests/test_context_budget_gate.py tests/test_application_runs.py tests/test_t09_1_context_protocol_e2e.py -q
75 passed in 4.66s

conda run --no-capture-output -n re-uthcode python -m pytest tests/test_provider_model_limits.py tests/test_history_contract.py tests/test_timeline_contract.py tests/test_session_files.py -q
39 passed in 2.88s

conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q
23 passed in 4.82s

conda run --no-capture-output -n re-uthcode python -m pytest tests/test_application_runtime.py -q
15 passed in 3.16s

conda run --no-capture-output -n re-uthcode python -m pytest tests/test_agent_loop.py -k "request_preparer or cancel" -q
9 passed, 43 deselected in 0.47s

conda run --no-capture-output -n re-uthcode python -m pytest tests/test_application_runs.py -k "cancel or provider_terminal_path or turn_can_start" -q
12 passed, 32 deselected in 0.98s

conda run --no-capture-output -n re-uthcode python -m pytest -q --deselect tests/test_tui.py::test_plan_revisions_and_task_state_append_as_distinct_permanent_blocks --deselect tests/test_tui.py::test_renderer_restores_roles_surfaces_markdown_and_code_colours --deselect tests/test_tui.py::test_tool_rows_keep_status_text_and_semantic_colour
1229 passed, 3 skipped, 3 deselected in 93.30s (0:01:33)

conda run --no-capture-output -n re-uthcode python -m compileall -q src tests
passed

rg -n "CompactState|CompactionJob|next_epoch_pointer|COMPACTING_BATCH" src tests
no matches

git diff --check
passed; only LF/CRLF normalization warnings, no whitespace error
```

### 未验证项、遗留问题与实际修改文件

- 未执行真实 Provider 网络调用；本轮使用 fake Provider/test doubles 验证取消传播。
- 完整 `tests/test_tui.py` 未作为本轮必过项重跑；此前已知的 3 个 Rich ANSI truecolor
  断言仍属于 W01/W02 既有问题，本轮没有触碰 TUI。
- 本轮实际修改文件：
  - `src/uthcode/application/context.py`
  - `tests/test_t09_1_context_protocol_e2e.py`
  - `docs/work/T09-1-Context预算与Compact协议补齐/feedback/W03-production-l4-catchup-feedback.md`
- `docs/work/T09-1-Context预算与Compact协议补齐/T09-1-Context预算与Compact协议补齐-checklist.md`
  本轮未改动；其 T03 cancellation 项仅在上述测试通过后保持 `[x]`。
- 未执行 commit、push、merge、rebase、tag、release、归档或其它 Git 写操作；工作区中
  不属于 W03 的 `docs/core-design/A04-Orchestration/` 用户改动未覆盖、未删除。
