# T09-2 工程收敛与提前抽象清理 Checklist

## Task 1 — 正式 Run/Turn 入口收敛

- [x] 执行 Application/Run、Provider Adapter、Context Gate 定向测试，全部通过。
- [x] 执行 `rg -n "GenerationHandle|start_generation|stream_generation|execute_tool_calls|def compile_context" src tests eval`，确认生产与活动测试中均为 0 条。
- [x] 从 `create_application -> create_run -> start_turn` 验证正常完成、取消、Provider 失败和模型快照。

## Task 2 — 固定 Runtime 控制收敛

- [x] 执行 AgentLoop/Permission/Planning 定向测试，PLAN READ 放行、非 READ 在 Permission 前拒绝、`full_access` 不绕过。
- [x] 执行 unfinished-task 测试，确认 usage 已计入、candidate 未提交、`CompletionBlocked` 后继续。
- [x] 执行 `rg -n "RuntimeHookSet|BeforeToolExecutionHook|BeforeCompletionHook|compose_runtime_hooks|runtime_hooks" src tests`，结果为 0 条。

## Task 3 — Context 合同单轨化

- [x] 执行 Context Compiler、Budget Gate、Compaction 与 T09-1 E2E 定向测试，全部通过。
- [x] 验证 Compiler 只接受 Bundle，非法 source 在边界稳定拒绝，instruction authority/plane 不回退。
- [x] 执行 `rg -n "PromptAssetSource|CoreRuntimeContractSource|TimelineSource|RuntimeStateSource|EnvironmentSource|\bTokenEstimator\b|to_context_block" src tests`，结果为 0 条。

## Task 4 — Session v3 硬切

- [x] 新建 Session，断言 metadata schema 为 3，目录不存在 `runtime.jsonl`。
- [x] v1、v2 fixtures 均抛 `SessionIncompatibleError`，无迁移、双读或 fallback。
- [x] 执行 Session、HistoryRead、Tool Result、Compact、`/new`、`/resume` 定向测试，全部通过。
- [x] 执行 `rg -n "RuntimeLog|RuntimeLogEntry|append_runtime|runtime_log|runtime\.jsonl" src tests`，结果为 0 条。

## Task 5 — 命令系统收敛

- [x] 执行 Registry、Parser、Dispatcher、Completion 和 TUI 命令测试，全部经 async Dispatcher 通过。
- [x] `/config`、`/login`、`/memory`、`/dream`、`/review` 返回 UNKNOWN_COMMAND，Help/Completion 不展示它们。
- [x] `/compact -- focus` 返回 usage error；不存在 Prompt/query Outcome。
- [x] 执行 `rg -n "CommandAvailability|NOT_IMPLEMENTED|CommandKind\.PROMPT|success_prompt|dispatch_text\(|def dispatch\(" src tests`，结果为 0 条。

## Task 6 — 定点公共边界清理

- [x] 执行 package tests，确认 Interfaces/Eval 现用 Application facade 可导入，被删符号不可导入。
- [x] 执行 `rg -n "SupportsModelLimits|SupportsInputTokenCount|ToolPreflight" src tests`，结果为 0 条。
- [x] 人工核对未重排或删除本任务范围外公共导出。

## Task 7 `[接入主流程]` — 正式组合与文档同步

- [x] 执行 `tests/test_architecture_boundaries.py tests/test_package.py`，全部通过。
- [x] 验证 CLI、TUI、Eval 均只调用 `create_application/create_run/start_turn`，无 Interface 到 Core internal/Integration 的新依赖。
- [x] 当前事实文档只描述固定控制、Session v3、异步命令和唯一 Run/Turn 链路；归档工作包无改动。

## Task 8 `[端到端验证]` — Headless、Session 与 TUI 验收

- [x] 使用 Fake Provider 从正式 Headless 入口完成包含 Tool、PLAN、Todo block 与最终回答的 Run。
- [x] 完成 v3 Session create/turn/compact/close/reopen/resume，Transcript、Timeline、Tool Result ref 与 Instruction State 一致。
- [x] 执行 CLI/TUI 离线 E2E，异步命令、帮助、补全、取消和清理均通过。

## Task 9 `[遗留负担清理]` — 否定扫描与全量回归

- [x] 执行 `conda run --no-capture-output -n re-uthcode python -m pytest -q`，全量测试全部通过，记录精确 passed/skipped 数。
- [x] 执行 `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests eval`，退出码为 0。
- [x] 执行 `conda run --no-capture-output -n re-uthcode python -m pip check`，无损坏依赖。
- [x] 执行 `git diff --check`，无 whitespace error；执行 `git status --short`，只有 T09-2 范围改动。
- [x] 更新 `OutstandingDebtList.md` 与 `Context-Index.md`，T09-2 标记 implemented_unarchived 且未归档。
- [x] 对全部修改 Markdown 执行 UTF-8 guard，确认无 replacement character、mojibake 或 fence 不平衡。
- [x] W01 Feedback 列出实际改动、命令精确结果、未验证项、风险和遗留问题；Checklist 全部完成。
