# W02 Application Context 与 Session 实施反馈

## 首次实施

本反馈记录 W02 按 Prompt 串行实施 T03 → T04 的结果；后续返工只在本文末尾追加章节。

### 当前进度

- T03：实施中。
- T04：待 T03 完成后实施。

### Checklist

- T03：尚未勾选，待取得对应定向验证证据。
- T04：尚未勾选，待取得对应定向验证证据。

## T03/T04 完成记录

### Context / Compaction

- Application 新增 `ContextStatus` 与 `CompactionStatus` 两个不可变、可序列化的安全 DTO；Desktop 可直接消费 `ApplicationStatus`，不需要解析 diagnostics。Context 状态字段固定为已用量、有效预算、可用性、`estimate|exact|unavailable` 测量性质和短来源。
- `budget_tokens` 复用当前 Application 已解析的 `ContextBudget`：配置窗口、已冻结的 Provider ceiling 或默认值按既有收紧规则决定。Session resume 会从 durable Transcript/Timeline 重建 estimate；只有对应 terminal `Usage.input_tokens` 才标 `exact`，随后 compile/Transcript/Tool/Timeline/Compact mutation 会回到 `estimate`。
- L4 `manual|auto|overflow` 与 L5 aging 均通过 `ApplicationContextService` 的生命周期包装进入同一既有 Core single-flight；状态从 `running` 收口到 `completed|no_change|failed|cancelled`，并保留安全 trigger/changed 字段。并发触发被既有 single-flight 拒绝时不会覆盖 owner 的 running 状态。
- Turn 收口顺序为 durable persistence 完成 → active-turn ownership 释放 → Provider usage 投影；Core terminal event 到达本身不直接制造最终 status。

### Session move / Plan replay

- 当前 open idle Session 在原 writer lock 内同步 close-time instruction state，成功更新 project membership 后才释放 writer 与 source Application ownership；失败时保留 source writer、membership 和可继续使用状态。Bridge 继续以 active Turn gate 拒绝 move，不隐式 cancel。
- replay 仅遍历 durable 完整 semantic unit；`ProposePlan` 必须通过既有 parser 且有成功 ToolResult，才投影 `kind=plan`、合法 plan 文本和 tool identity。malformed、unfinished、失败/取消 Plan，以及 raw arguments、ToolResult private body 均被抑制；普通 tool replay 语义不变。
- Bridge safe allowlist 增加两个状态 DTO和 `plan` replay kind，未引入第二 Application、跨项目文件扫描或 Desktop Context/Session facade。

### 修改文件

- 生产：`src/uthcode/application/context.py`、`src/uthcode/application/generation.py`、`src/uthcode/application/runs.py`、`src/uthcode/application/sessions.py`、`src/uthcode/application/__init__.py`、`src/uthcode/interfaces/desktop/bridge.py`。
- Python tests（实际修改）：`tests/test_application_runs.py`、`tests/test_w05_diagnostics.py`、`tests/test_context_compaction.py`、`tests/test_context_budget_gate.py`、`tests/test_session_authority.py`；`tests/test_context_compiler.py`、`tests/test_desktop_bridge.py` 仅作为未修改的受影响回归运行。
- 工作包记录：首次创建本 Feedback；F02 Checklist 仅将取得证据的 T03/T04 复选框由 `[ ]` 改为 `[x]`。

### 精确验证

- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_application_runs.py tests/test_w05_diagnostics.py -q`：61 passed，exit code 0。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_session_authority.py tests/test_desktop_bridge.py -q`：69 passed，exit code 0。
- 受影响 Context/Session/Bridge 定向集合：`conda run --no-capture-output -n re-uthcode python -m pytest tests/test_application_runs.py tests/test_w05_diagnostics.py tests/test_context_compiler.py tests/test_context_compaction.py tests/test_context_budget_gate.py tests/test_session_authority.py tests/test_desktop_bridge.py -q`：201 passed，exit code 0。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q`：23 passed，exit code 0。
- `conda run --no-capture-output -n re-uthcode python -m pytest -q`：1427 passed、3 skipped，exit code 0。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests`：exit code 0。
- `git diff --check`：exit code 0；仅有 Git 关于修改文件 LF/CRLF 的常规提示，无 whitespace error。

### Checklist 状态

- T03 已勾选：定向回归、default/configured/provider budget、durable resume estimate、Provider exact 与 mutation downgrade、Low Water/Auto Gate/Hard Gate/overflow retry 均有测试证据。
- T03 未勾选：manual/auto/overflow 三种 trigger 的完整 terminal 观测矩阵、Core terminal event 竞态专测；本次未把部分证据扩写为全部通过。
- T04 已勾选：定向回归、open idle move、active Turn gate、invalid/corrupt/storage 安全结果、失败不变量和 complete Plan replay/raw body 隔离均有测试证据。
- T04 未勾选：单 Runtime move 后“无第二 Application/无跨项目扫描”的独立验收断言尚未单独补充。

### 偏差、未完成项与风险

- 未修改 Renderer、Settings、CDP harness、T10 冻结文件或 Persistent Runtime Recovery；未新增 Context 算法、后台 Agent、第二 store/runtime 或兼容层。
- 未执行真实 Provider 网络调用、packaged Desktop 或人工 GUI 矩阵；这些需要后续 W03～W06 的环境与职责。未运行项没有在 Checklist 中勾选，也没有描述为通过。
- 本次为已有 Python Context 定向 tests 增加了状态生命周期和手动 no-change 断言；未修改 `tests/test_context_compiler.py`、`tests/test_desktop_bridge.py`，它们仅作为受影响回归运行。

### 清理与 Git 边界

- 未删除业务文件、缓存或未知文件；未执行任何 Git commit、push、merge、rebase、tag、release、分支切换或工作包归档。
- 未新增能力欠账，`docs/OutstandingDebtList.md` 保持不变；未触发 Persistent Runtime Recovery。

## 评审返工记录（第 1 轮）

### 返工原因

- 评审指出 `TurnResult.usage` 是跨 Provider 迭代累计值，不能在工具续接或同一迭代网络重试后直接标记当前 request 为 exact。
- durable Session 的合法 `kind=plan` replay 已由 Application 产生，但 TUI hydration allowlist 仍拒绝该 kind，导致 `/resume` 在合法 Plan 上失败。
- 同步 Session refresh 未消费 async Provider 的 `resolve_model_limits`，冷 resume 可能继续显示默认 `256000`，而实际首个 request 使用 Provider ceiling `12000`。

### 实际返工

- `generation.py` 为每个 `(run_id, turn_id)` 记录成功完成的 request preparation boundary；`runs.py` 只有 completed、无 Tool continuation 且计数精确为 1 时才允许把 `Usage.input_tokens` 提升为 `exact`，否则保留 Context compiler 的 `estimate`。原有累计 Usage diagnostics 仍完整保留。
- 同步 Session Context refresh 复用正式 request 使用的 `_resolve_model_limits_async` 适配器；原生 async resolver 在已有 event loop 时通过专用短生命周期 loop 完成，避免在当前 loop 上嵌套 `asyncio.run` 或遗留未消费 coroutine，并缓存同一 Provider ceiling 后编译 `ContextBudget`。
- TUI 仅补齐既有 `plan` replay 的安全适配：allowlist 接受 `plan`，正文仍只取 Application safe `record.text`，按 replay 顺序使用既有 `plan_message` 生成 `Plan vN` identity；未修改 Renderer。

### 新增/调整回归

- `tests/test_w05_diagnostics.py` 增加两个 Provider request 的 `input_tokens=5/7` 累计回归，断言累计结果为 `12` 但 Context measurement 不会成为 `exact=12`；增加 async ceiling `12000` 的冷 resume 回归，并在 event loop 运行时调用同步 Session boundary，随后确认实际 `GenerationRequest` 的 effective input limit 仍为 `12000`。
- `tests/test_application_runs.py` 的网络重试回归确认同一 Core iteration 的两次 Provider request 仍为 `estimate`。
- `tests/test_tui.py` 的 `/resume` replay 回归加入合法 Plan，确认 Plan 正文与 `UthCode · Plan v1` 保留、工具 identity 不泄漏且无 live stream。

### 返工后精确验证

- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_application_runs.py tests/test_w05_diagnostics.py -q`：**62 passed**，exit code 0。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_session_authority.py tests/test_desktop_bridge.py -q`：**69 passed**，exit code 0。
- 受影响集合（含 Context、Session、Bridge、TUI）：`conda run --no-capture-output -n re-uthcode python -m pytest tests/test_application_runs.py tests/test_w05_diagnostics.py tests/test_context_compiler.py tests/test_context_compaction.py tests/test_context_budget_gate.py tests/test_session_authority.py tests/test_desktop_bridge.py tests/test_tui.py -q`：**298 passed**，exit code 0。
- Python 全量：`conda run --no-capture-output -n re-uthcode python -m pytest -q`：**1428 passed, 3 skipped**，exit code 0。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q`：**23 passed**，exit code 0。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests`：exit code 0。

### Checklist、边界与未验证项

- Checklist 既有已勾选项保持不回退；T03 Provider exact 项现在以 request-boundary 计数为精确前提，`5+7` 累计和网络重试证据均为 estimate。T03 的完整 compact terminal 矩阵、terminal event 竞态项及 T04 的单 Runtime move 独立验收项仍保持 `[ ]`，没有用部分证据扩勾。
- 本轮只增加 TUI Application replay consumer 的必要配套；Renderer、Settings、CDP harness、T10 冻结文件、Persistent Runtime Recovery、`docs/OutstandingDebtList.md` 均未修改。
- 未验证真实 Anthropic 网络/SDK、packaged Desktop 和人工 GUI 矩阵；async provider 回归使用受控 test double。上述未验证项未记为通过。
- 本轮仍未执行任何 Git commit、push、merge、rebase、tag、release、分支切换或工作包归档。

### 返工验证补充

- `conda run --no-capture-output -n re-uthcode python C:\Users\93445\.codex\skills\uth-utf8-guard\scripts\check_utf8_docs.py "docs/work/F02-DesktopGUI交互与上下文缺陷修复/F02-DesktopGUI交互与上下文缺陷修复-checklist.md" "docs/work/F02-DesktopGUI交互与上下文缺陷修复/feedback/W02-application-context-session-feedback.md"`：**OK: 2 file(s) passed UTF-8 guard**。
- `git diff --check`：exit code 0；输出仅为 Git 关于工作区 LF/CRLF 转换的常规 warning，无 whitespace error。

## 评审返工记录（第 3 轮补充）

### 复审纠正与最终实现

- 第三轮复审指出 `/model` 在 event loop 中仍会落入同步 `select_model`，导致 Provider、配置、model identity 与 active Context 发生部分提交。最终实现由 built-in `/model` 走 `select_model_async`：候选 Provider 只在 staging 阶段构造，目标 `resolve_model_limits` 必须先在当前 event loop 完成并校验，随后一次无 await 的 commit 才写用户默认模型、发布 Provider/model identity、更新 limits cache，并以同一 `ContextBudget` 刷新 active Session。resolver failure 或 cancellation 均发生在 commit 前，旧模型、旧配置、旧 budget、旧 active Session 保持不变。
- 第三轮复审另指出 `new_session_for_command_async`/`resume_session_for_command_async` 在 resolver 完成前已经提交 Session。最终实现保留单一 Application Context/Session authority，并把 async budget preflight 前置到 SessionService create/resume；Desktop Bridge 还在关闭 active Turn、切换 active Run 之前调用同一 preflight，并把已解析的 `ContextBudget` 传入 commit，取消时不会释放 source writer、取消旧 Run 或留下新 Session。`turn.start`、TUI、CLI 和 built-in command 均优先使用既有 async boundary。
- 第二轮关于 loop affinity 的错误结论在本轮明确保持纠正：running loop 内的同步入口不创建新线程、新 event loop，也不阻塞当前 loop 调同一 Provider resolver；无 running loop 的正式同步调用方才使用短生命周期 `asyncio.run`。loop-affine Provider 回归断言 resolver 的 observed loop 与调用方当前 loop 相同。
- TUI replay 不按 record 顺序合成 Plan revision；`SessionReplayRecord` 无权威 revision 时只展示安全正文和 `UthCode · Plan` 类型，不显示伪造的 `Plan vN`。跨 Run、跨 turn 的多个 durable Plan 回归均确认没有合成 revision。

### 本轮新增回归证据

- active Session + async Provider 的 `/model` success、failure、cancel 回归：成功预算为 `12000`；failure/cancel 均保持旧 Provider、旧 model ref、旧配置 writer、旧 active Session 和旧 Context budget，并确认 resolver 在当前 event loop。
- blocked async resolver 的 Desktop `/resume` cancellation 回归：source active Session、source writer、旧 Bridge Run/active handle 均保持，未执行隐式 cancel；target writer 仍可打开。blocked async resolver 的 `/new` cancellation 回归确认没有 active Session 或 durable metadata。
- cold resume 的 async Provider ceiling 回归确认 status 与后续实际 `GenerationRequest` 同为 `12000`；正式无 running loop 的同步 resume 仍可解析 async ceiling。两个 request `input_tokens=5/7` 的累计值不会被伪标为当前 request 的 `exact=12`。

### 最终精确验证

- T03 定向：`conda run --no-capture-output -n re-uthcode python -m pytest tests/test_application_runs.py tests/test_w05_diagnostics.py -q`：**68 passed**，exit code 0。
- T04 定向：`conda run --no-capture-output -n re-uthcode python -m pytest tests/test_session_authority.py tests/test_desktop_bridge.py -q`：**69 passed**，exit code 0。
- 受影响集合（Application、Context、Session、Bridge、命令、CLI、TUI）：`conda run --no-capture-output -n re-uthcode python -m pytest tests/test_application_runs.py tests/test_w05_diagnostics.py tests/test_context_compiler.py tests/test_context_compaction.py tests/test_context_budget_gate.py tests/test_session_authority.py tests/test_desktop_bridge.py tests/test_w04_session_commands.py tests/test_cli.py tests/test_tui.py tests/test_command_dispatcher.py tests/test_application_runtime.py -q`：**367 passed**，exit code 0。
- Python 全量：`conda run --no-capture-output -n re-uthcode python -m pytest -q`：**1435 passed, 3 skipped**，exit code 0。
- 架构：`conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q`：**23 passed**，exit code 0。
- 编译：`conda run --no-capture-output -n re-uthcode python -m compileall -q src tests`：exit code 0。
- 文档编码：`conda run --no-capture-output -n re-uthcode python C:\Users\93445\.codex\skills\uth-utf8-guard\scripts\check_utf8_docs.py "docs/work/F02-DesktopGUI交互与上下文缺陷修复/F02-DesktopGUI交互与上下文缺陷修复-checklist.md" "docs/work/F02-DesktopGUI交互与上下文缺陷修复/feedback/W02-application-context-session-feedback.md"`：追加本节后重跑，**OK: 2 file(s) passed UTF-8 guard**。
- 完整性：`git diff --check`：exit code 0；仅有 LF/CRLF 转换提示，无 whitespace error。
- 静态边界：generation.py 不再命中 `ThreadPoolExecutor`/`resolve_in_worker`；TUI replay hydration 不命中 `Plan v`；T10 目录和明确保留的 Desktop transport 文件均无 diff。

### Checklist、文件边界与未验证项

- Checklist 只保留既有精确证据的 `[x]`，本轮没有新增或回退任何复选框；T03 完整 compact terminal 矩阵、Core terminal event 竞态和 T04 单 Runtime move 独立验收仍保持 `[ ]`。
- 本轮最终修改文件为 Application Context/Session/generation、既有 async consumer 配套（builtins、CLI、Desktop Bridge、TUI）和 Python 回归 tests；未修改 Renderer、Settings、CDP harness、T10 冻结文件、Persistent Runtime Recovery 或 `docs/OutstandingDebtList.md`。
- 未验证真实 Anthropic SDK/network、packaged Desktop 和人工 GUI 矩阵；async provider 证据使用 loop-affine test double，这些环境风险留待后续集成验收。
- 未执行任何 Git commit、push、merge、rebase、tag、release、分支切换或工作包归档。

### 第三轮补充：commit 异常回滚

- 进一步收紧 `/model` commit：候选 Provider limit 解析成功后才调用原子配置 writer；active Context compile 或无 Session budget 投影发生同步异常时，Application identity、limits cache 和 Context 状态恢复旧值，并对已成功的默认模型写入执行旧 ref 的补偿写入。无 active Session 的成功切换也会立即收敛 Context budget，不等待下一次 Session。
- 该补充未改变 resolver failure/cancel 的前置不变式；两者仍不会调用配置 writer。受影响 T03/T04 定向、367 项受影响集合和 Python 全量均在补充后重新运行并通过。

### 补充后的精确验证

- T03 定向：**68 passed**，exit code 0。
- T04 定向：**69 passed**，exit code 0。
- 受影响集合：**367 passed**，exit code 0。
- Python 全量：**1435 passed, 3 skipped**，exit code 0。
- `tests/test_architecture_boundaries.py`：**23 passed**，exit code 0；`python -m compileall -q src tests`：exit code 0。
- UTF-8 guard（Checklist + 本 Feedback）：**OK: 2 file(s) passed UTF-8 guard**；`git diff --check`：exit code 0，仅 LF/CRLF 转换提示、无 whitespace error。
- Checklist 复选框仍未新增或回退；真实 Provider 网络、packaged Desktop 和人工 GUI 仍未验证。全程无 Git 写操作。

## 评审返工记录（第 3 轮）

### 返工原因与实际修复

- `/model` 不再由 built-in handler 同步调用 `select_model`。Application 先构造并验证目标 Provider，沿当前 event loop await 目标 `resolve_model_limits`，计算目标 `ContextBudget`，随后才调用原子用户默认模型 writer 并提交 Provider、model identity、limits cache 和 active Session Context；resolver failure/cancel 均发生在提交前，旧模型、旧配置、旧 budget 保持不变。无 running loop 的正式同步 `select_model` 也先完成同步/async resolver 预检后再提交。
- `new_session_for_command_async` 与 `resume_session_for_command_async` 现在先 await Context budget 预检，再调用 `SessionService` 的 create/resume commit，并把已解析 budget 传给 refresh，避免 resolver cancellation 留下已切换 active Session 或 ghost Session。Bridge 的 `turn.start` 也改为优先 await `ensure_session_async`，清理剩余 async 调用方的同步入口。
- Application 仍只有一套 SessionService、ContextService、ContextBudget compiler 和 model commit authority；async 方法是同一 authority 的 async boundary，不新增第二 runtime/store/facade。

### 新增回归

- `tests/test_w05_diagnostics.py` 增加 active Session + async resolver 的 `/model` success、failure、cancel 三个回归：success 得到目标 `12000` budget；failure/cancel 均保持旧 Provider/model/config/writer/Context budget，并验证 resolver 在当前 loop。
- 同文件增加 resume cancellation 回归：blocked resolver 被 cancel 后 source active Session、writer lock 和 Desktop Bridge 原有 Run 保持不变，target writer 仍可打开；new cancellation 回归确认没有 active Session 或 durable metadata。
- async provider fixture 记录 `expected_loop`、observed loop 和 `same_loop`，覆盖本轮所有 blocked/success resolver 边界。

### 第三轮精确验证

- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_application_runs.py tests/test_w05_diagnostics.py -q`：**68 passed**，exit code 0。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_session_authority.py tests/test_desktop_bridge.py -q`：**69 passed**，exit code 0。
- 受影响集合（含 Application、Context、Session、Bridge、命令、CLI、TUI）：`conda run --no-capture-output -n re-uthcode python -m pytest tests/test_application_runs.py tests/test_w05_diagnostics.py tests/test_context_compiler.py tests/test_context_compaction.py tests/test_context_budget_gate.py tests/test_session_authority.py tests/test_desktop_bridge.py tests/test_w04_session_commands.py tests/test_cli.py tests/test_tui.py tests/test_command_dispatcher.py tests/test_application_runtime.py -q`：**367 passed**，exit code 0。
- Python 全量：`conda run --no-capture-output -n re-uthcode python -m pytest -q`：**1435 passed, 3 skipped**，exit code 0。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q`：**23 passed**，exit code 0。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests`：exit code 0。

### Checklist、边界与未验证项

- Checklist 仅保持既有 `[x]` 证据，不新增未经精确验证的勾选，也未回退既有勾选；T03 完整 compact terminal 矩阵、terminal event 竞态和 T04 单 Runtime move 独立验收仍为 `[ ]`。
- 本轮修改限于 Application、既有 async consumers（builtins/CLI/Bridge/TUI）和 Python tests；Renderer、Settings、CDP harness、T10 冻结文件、Persistent Runtime Recovery、`docs/OutstandingDebtList.md` 未修改。
- 未验证真实 Anthropic SDK/network、packaged Desktop 和人工 GUI 矩阵；本轮 async Provider 证据使用 loop-affine test double。真实 SDK client 的运行环境绑定仍需后续集成环境验证。
- 未执行任何 Git commit、push、merge、rebase、tag、release、分支切换或工作包归档。

### 第三轮文档完整性验证

- 追加本轮记录后重新执行 UTH UTF-8 guard，要求 checklist 与本 Feedback 均通过。
- 追加本轮记录后重新执行 `git diff --check`，仅接受工作区 LF/CRLF 转换提示，不接受 whitespace error。

### 本轮实际修改文件清单

- Application：`src/uthcode/application/__init__.py`、`src/uthcode/application/context.py`、`src/uthcode/application/generation.py`、`src/uthcode/application/runs.py`、`src/uthcode/application/sessions.py`。
- Async consumer 配套：`src/uthcode/application/commands/builtins.py`、`src/uthcode/interfaces/cli.py`、`src/uthcode/interfaces/desktop/bridge.py`、`src/uthcode/interfaces/tui/app.py`。
- Python 回归：`tests/test_application_runs.py`、`tests/test_context_budget_gate.py`、`tests/test_context_compaction.py`、`tests/test_session_authority.py`、`tests/test_tui.py`、`tests/test_w05_diagnostics.py`。
- 工作包记录：Checklist 仅保留既有 `[x]` 状态；本 Feedback 仅在 EOF 追加本轮章节。

## 评审返工记录（第 2 轮）

### 复审纠正

- 第二轮复审指出第一轮采用 `ThreadPoolExecutor`、新 `asyncio.run` 并同步 `result()` 的方案不满足 Provider loop affinity。该方案结论已明确纠正并移除：running loop 中不再跨线程、创建第二 event loop 或阻塞当前 loop 调用同一 Provider resolver。
- Application 新增的 async Session adapter 复用既有 `SessionService`、`ContextService`、replay builder 与 `ContextBudget` compiler；Bridge、命令 dispatcher、TUI 和 CLI 的现有 async 调用边界优先 await 该 adapter。它们不是第二套 Session/Context authority。正式同步 API 仍保留给无 running loop 的调用方；遇到 native async resolver 且当前 loop 已运行时显式要求 async boundary，不再静默阻塞或跨 loop。
- async Session refresh 先在调用方当前 loop await `_resolve_model_limits_async`，再用同一 provider ceiling 编译 Context projection；因此 cold resume 的 status 与后续正式 request 共用 `12000` ceiling。
- TUI replay 不再按 record 顺序合成 revision；`SessionReplayRecord` 没有权威 plan revision 时，只输出既有安全正文和 `UthCode · Plan` 角色，不显示伪造的 `Plan vN`。live Core Plan event 的既有权威 revision 路径未修改。

### 新增/调整回归

- `tests/test_w05_diagnostics.py` 用 loop-affine async Provider double 记录 `expected_loop`、observed loop 和 `same_loop`；cold resume 在当前 event loop 中断言 `same_loop is True`、只观察到当前 loop，并验证 status 与实际 `GenerationRequest` 的 effective input limit 都是 `12000`。
- 同文件增加正式同步调用方回归：普通（无 running loop）同步 `resume_session_for_command` 可在调用线程建立短生命周期 loop 完成 async resolver，status 得到 `12000`，且 resolver 只执行一次。
- `tests/test_tui.py` 增加跨 Run、跨 turn 的两个 Plan replay 回归，断言两个安全正文均保留、Plan 角色各出现一次且输出完全不含 `Plan v`；既有 `/resume` hydration 断言同步更新为无合成 revision。

### 第二轮精确验证

- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_application_runs.py tests/test_w05_diagnostics.py -q`：**63 passed**，exit code 0。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_session_authority.py tests/test_desktop_bridge.py -q`：**69 passed**，exit code 0。
- 受影响集合（含 Context、Session、Bridge、命令、CLI、TUI）：`conda run --no-capture-output -n re-uthcode python -m pytest tests/test_application_runs.py tests/test_w05_diagnostics.py tests/test_context_compiler.py tests/test_context_compaction.py tests/test_context_budget_gate.py tests/test_session_authority.py tests/test_desktop_bridge.py tests/test_w04_session_commands.py tests/test_cli.py tests/test_tui.py -q`：**344 passed**，exit code 0。
- Python 全量：`conda run --no-capture-output -n re-uthcode python -m pytest -q`：**1430 passed, 3 skipped**，exit code 0。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q`：**23 passed**，exit code 0。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests`：exit code 0。

### Checklist、边界与未验证项

- Checklist 仅保留既有证据状态，未把本轮定向回归扩大解释为完整 terminal 观测矩阵、Core terminal event 竞态或单 Runtime move 的独立验收；既有 `[x]` 未回退，未新增没有精确证据的勾选。
- 本轮必要配套仅触及 Application async Session boundary、既有命令/CLI/TUI consumers 及 Python regression tests；Renderer、Settings、CDP harness、T10 冻结文件、Persistent Runtime Recovery 和 `docs/OutstandingDebtList.md` 均未修改。
- 未验证真实 Anthropic SDK/network、packaged Desktop 和人工 GUI 矩阵；async provider 证据使用 loop-affine test double。真实 SDK 的 client loop 绑定仍是交付风险，但当前代码路径没有主动跨线程或跨 loop 调用。
- 第二轮仍未执行任何 Git commit、push、merge、rebase、tag、release、分支切换或工作包归档。

### 返工后完整性验证

- Feedback 追加后将重新执行 UTH UTF-8 guard，要求 checklist 与本 Feedback 均通过且无 replacement character/mojibake/fence 问题。
- 将重新执行 `git diff --check`；预期仍仅有工作区 LF/CRLF 转换提示，不应有 whitespace error。

### 返工验证补充（本轮已完成）

- `conda run --no-capture-output -n re-uthcode python C:\Users\93445\.codex\skills\uth-utf8-guard\scripts\check_utf8_docs.py "docs/work/F02-DesktopGUI交互与上下文缺陷修复/F02-DesktopGUI交互与上下文缺陷修复-checklist.md" "docs/work/F02-DesktopGUI交互与上下文缺陷修复/feedback/W02-application-context-session-feedback.md"`：**OK: 2 file(s) passed UTF-8 guard**。
- `git diff --check`：exit code 0；输出仅为 Git 关于工作区 LF/CRLF 转换的常规 warning，无 whitespace error。

## 评审返工审计澄清（第 4 轮）

### 真实返工顺序

- 初次 T03/T04 实施先创建本文件并记录 Context/Compaction、Session move、Plan replay、Checklist 与验证证据。
- 第 1 轮复审后，补充 request boundary exact 判定、TUI `plan` replay allowlist 和 async Provider ceiling 证据。
- 第 2 轮复审后，移除 running loop 内跨线程/新 loop/同步阻塞 resolver 路径，改为当前 loop 的 async Session boundary；同时修正 TUI replay 不合成 `Plan vN`，并补 loop-affine、跨 Run/多 Plan 回归。
- 第 3 轮复审后，补充 `/model` async Provider limit preflight 与 active Session success/failure/cancel 事务，补 async `/new`/`/resume` preflight、Desktop Bridge active-Turn 前置保护；随后又补充 model commit 异常补偿回滚、无 active Session 的预算收敛，以及本轮 old-provider blocked→new-model success 并发回归。
- 第 4 轮复审针对 preflight await 期间 model/provider 切换的竞态，加入 generation/identity snapshot、await 后匹配校验和 stale budget 重新 preflight；本次新增跨任务回归确认 old ceiling 不会覆盖 `new/ref` 的 `12000` ContextStatus，Session commit 使用当前 model 语义。

### Feedback 位置审计与后续规则

- 本文件早期追加操作中，两个第三轮补充段落使用了文件内重复的验证尾行作为 patch 锚点，导致新写入的“第 3 轮补充”及其 commit 回滚补充在物理顺序上位于原有“第 3 轮”和“第 2 轮”章节之前。这是追加定位错误，不是对旧章节的移动、删除或覆盖；既有章节正文与历史验证记录均保持原样。
- 本次审计段落明确记录该事实；从本段之后，所有返工、验证和审计内容只在文件真实 EOF 追加，不再使用会命中旧记录的重复锚点，也不新建 v2/retry/fix Feedback 文件。
- Checklist 仍只保留已有精确证据的复选框状态，本轮未新增或回退任何勾选；无 Git 写操作、无工作包归档。

## 评审返工记录（第 5 轮）

### 复审原因与修复

- 第五轮复审指出同步 `select_model` 复用 Session status 所需的 lenient `_resolve_model_limits_sync`，会把 resolver 异常、非法 limits 或 `asyncio.run` 失败吞成 `None` 后继续提交，和 async model selection 的严格失败语义分裂。
- 新增最小 `_resolve_model_limits_sync_strict`，只供同步模型选择使用；无 resolver 或 resolver 明确返回 `None` 仍表示无 Provider ceiling、可以成功，resolver 异常、非法返回、asyncio.run 失败则在 writer/provider/model/limits/Context commit 前原样失败。既有 lenient 路径继续仅服务 Context status refresh，不改变 Session 容错语义。

### 新增回归与验证

- 无 running loop 的同步 `select_model` + async resolver 抛错：确认旧 Provider、model ref、配置、active Session、Context budget 和 writer 均不变。
- 无 running loop 的同步 `select_model` + async resolver 返回非法 limits：确认严格失败且无部分提交。
- 无 running loop 的同步 `select_model` + async resolver 明确返回 `None`：确认目标 model/provider、配置 writer、active Session Context 成功收敛，预算采用 configured limit `64000`。
- T03 定向：`conda run --no-capture-output -n re-uthcode python -m pytest tests/test_application_runs.py tests/test_w05_diagnostics.py -q`：**72 passed**，exit code 0。
- T04 定向：`conda run --no-capture-output -n re-uthcode python -m pytest tests/test_session_authority.py tests/test_desktop_bridge.py -q`：**69 passed**，exit code 0。
- 受影响集合：**371 passed**，exit code 0；Python 全量：**1439 passed, 3 skipped**，exit code 0。
- Architecture：**23 passed**，exit code 0；`conda run --no-capture-output -n re-uthcode python -m compileall -q src tests`：exit code 0。
- Checklist + 本 Feedback 的 UTF-8 guard：**OK: 2 file(s) passed UTF-8 guard**；`git diff --check`：exit code 0，仅 LF/CRLF 转换提示，无 whitespace error。

### 边界与未验证项

- Checklist 未新增或回退任何复选框；Renderer、Settings、CDP、T10、Persistent Runtime Recovery 未修改。
- 真实 Anthropic SDK/network、packaged Desktop、人工 GUI 矩阵仍未验证；未执行任何 Git 写操作或工作包归档。
