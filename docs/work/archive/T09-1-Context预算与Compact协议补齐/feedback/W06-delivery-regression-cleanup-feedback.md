# W06 Delivery Regression Cleanup Feedback

执行日期：2026-08-21
工作包：T09-1：Context 预算与 Compact 协议补齐
状态：完成，工作包仍保留在 `docs/work/`，等待用户手动归档。

## 1. 执行边界与初始状态

- 已完整读取 W06 Prompt、`AGENTS.md`、`docs/README.md`、`docs/Context-Index.md`、`docs/OutstandingDebtList.md`、`docs/rules/WorkPackageRules.md`、T09-1 Requirement/Spec/Tasks/Checklist，以及 W01～W05 Feedback。
- 初始工作树无未提交改动；当前分支为 `T09-1-Context预算与Compact协议补齐`。本轮未执行 commit、push、merge、rebase、tag、archive 或其他 Git 写操作。
- 遵守工作包冻结边界：未修改 Requirement、Spec、Tasks、Prompt 内容；Checklist 仅把已验证条目的 checkbox 从 `[ ]` 改为 `[x]`。
- 使用 Conda 环境 `re-uthcode` 执行验证。

## 2. T07：端到端交付验收、Diagnostics、Eval 与文档

### 2.1 代码与验证结果

T01～T06 已提供动态 limits、Transcript/Timeline、L4/L5、HistoryRead、manual Compact、overflow recovery、Application/Headless/TUI/CLI 正式链路。本轮发现并修复一个 T06 精确回归阻断：`NO_COLOR=1` 时，TUI capture 使用的 Rich Console 仍把强制 truecolor 降为无色输出，导致三个既有语义颜色断言失败；`src/uthcode/interfaces/tui/terminal.py` 的 capture Console 显式设置 `no_color=False`。该修正只恢复既有 TUI rendering contract，不改变命令、权限、Plan/Todo、Runtime Hook 或 Context 语义。

T07 的 Headless/Application e2e 覆盖 ordinary、tool loop、L4/catch-up、L5、HistoryRead、manual no-op/success、overflow once 与 hard-fail；diagnostics/status 只暴露分维 limits、count source、allowance、Pressure/Preflight、Auto/Hard、Timeline 与受控 Compact/persistence outcome，不把 Transcript、summary、Tool Result、API key 或异常正文写入安全输出。Eval README 保持并列指标，不引入总分或产品成功阈值。

### 2.2 文档同步

已按文档维护映射同步：

- `docs/Tools.md`：补齐 HistoryRead、当前 Session opaque ref bounded page、默认/Plan 工具集合。
- `docs/user-manual/configuration.md`、`commands.md`、`getting-started.md`：补齐 dynamic Context Window/Provider limits、正式 `/compact`、`/status`、`/resume` 与 Transcript/Timeline 语义。
- `docs/core-design/T09-context-engineering.md`、`docs/core-design/README.md`、`docs/core-design/A04-Orchestration/02-可替换交互层.md`：统一 Context Budget/Gate、L1～L5、Compact、Timeline 与 no-fallback 边界。
- `docs/context/A01-AgentRuntime/AgentRuntime-Context.md`、`A03-State/State-Context.md`、`A04-Orchestration/Orchestration-Context.md`、`TUI/README.md`：同步当前事实、命令编排和状态/诊断边界。
- `eval/README.md`：同步动态诊断和并列指标口径。
- `docs/Context-Index.md`：在实现、Checklist 与本 Feedback 齐全后标记 T09-1 为 `implemented_unarchived`。

## 3. T08：阶段性与兼容逻辑清理

### 3.1 清理结论

- 当前 `src/`、`tests/`、`eval/` 和当前事实文档不再使用固定 258K authority、`UTHCODE_CONTEXT_BUDGET_TOKENS`、`before T09-1`、`summarizer_unavailable` 或旧阶段 `/status` 文案；精确扫描中的命中仅来自冻结工作包/历史/归档证据，未修改这些冻结文件。
- Session v2 生产路径只写 `transcript.jsonl`、`timeline.jsonl`、`runtime.jsonl` 和 `metadata.json`。`src/uthcode/integrations/session_files.py` 中保留的 `history.jsonl` 仅用于发现旧 v1 目录并抛出明确 `SessionIncompatibleError`；测试只断言 fresh/persisted Session 不创建旧文件。没有旧 writer、旧 contract 或兼容 alias。
- Timeline 产品 record 仍只有 Fine、Macro、ActiveCheckpoint 三类；无持久 Compact FSM/Job/pointer、独立 compaction model、跨 Provider fallback 或无调用方 Manager/Registry/Scheduler。
- `/compact` 与 automatic L4/L5 复用同一 Application orchestrator，支持低 pressure no-op；无 sync-only Compact、重复入口或重复 async protocol。
- Permission、Plan/Todo、Runtime Hook、其它 Slash Commands 和 TUI rendering 未发生范围外重构；本轮 TUI 改动仅修复既有颜色输出测试在 `NO_COLOR` 环境下的 capture 行为。

### 3.2 bundled model 扫描的精确解释

没有 bundled official model metadata、本地官方型号表或 hardcoded official model window 路线，也没有将其重新登记为 future debt。任务要求的宽 regex 会命中现有 `model_catalog` 符号，但这些符号只读取用户配置中的 Model Profile，供 `/model` 选择和命令补全使用，不包含随包官方 metadata、官方窗口推断或 Provider fallback；该既有用户配置能力不应被误删或改名。

### 3.3 OutstandingDebtList 复核

- `T02 Slash Command / TUI` 只移除已回补的 `/compact` 欠账，继续保留 `/memory`、`/dream`。
- `B01 私有测试集 v0` 删除生产 Compaction 不可运行和安全 diagnostics 相关欠账，只保留 Memory injection 命中指标欠账。
- T09 的三条 Context 欠账已在实现、Checklist、Feedback 证据齐全后删除；仍成立的 Persistent Runtime Recovery、Memory/Retrieval、Artifact GC、层级 Summary Graph 等欠账继续保留。
- bundled model metadata 路线未重新登记为未来欠账。

## 4. 精确验证记录

以下命令均在 `D:\project\Re-UthCode` 执行：

| 范围 | 命令 | 结果 |
| --- | --- | --- |
| T05 regression | `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_application_runtime.py tests/test_application_runs.py tests/test_session_files.py tests/test_t09_1_context_protocol_e2e.py -q` | `104 passed in 15.81s`；failed 0；skipped 0 |
| T06 exact | `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_command_dispatcher.py tests/test_w04_session_commands.py tests/test_cli.py tests/test_tui.py tests/test_application_runtime.py tests/test_t09_1_context_protocol_e2e.py -q` | `164 passed in 34.39s`；failed 0；skipped 0 |
| T07 target | `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_w05_diagnostics.py tests/test_w06_integration_delivery.py tests/test_t09_1_context_protocol_e2e.py tests/test_architecture_boundaries.py -q` | `60 passed in 11.35s`；failed 0；skipped 0 |
| T08 regression | `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_t08_e2e.py tests/test_agent_loop.py tests/test_planning.py tests/test_runtime_hooks.py -q` | `104 passed in 3.82s`；failed 0；skipped 0 |
| 全量 pytest | `conda run --no-capture-output -n re-uthcode python -m pytest -q` | `1253 passed, 3 skipped in 150.48s (0:02:30)`；failed 0 |
| 编译 | `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests eval` | exit code 0；无输出；通过 |
| diff 检查 | `git diff --check` | exit code 0；仅报告工作树 LF/CRLF 转换提示；无 whitespace error |

静态清理核验：

- `rg -n "UTHCODE_CONTEXT_BUDGET_TOKENS|fixed 258K|固定 258K|before T09-1|summarizer_unavailable" src tests eval docs` 的命中仅在冻结 T09/T09-1 工作包、历史 Feedback 或归档证据中；生产代码、测试、eval 和当前事实文档没有旧 authority。
- `rg -n "\bProjection\b|\bCanonicalHistory\b|history\.jsonl" src/uthcode tests` 仅命中 v1 incompatible guard 和“不创建 history.jsonl”的测试，不存在生产 contract、旧 writer 或兼容 alias。
- `rg -n "bundled.*model|model.*catalog|hard.?coded.*context" src/uthcode tests docs` 的当前源码命中仅为用户配置 Model Profile catalog；bundled official metadata、官方模型窗口和硬编码窗口路线不存在。其余命中来自冻结任务/历史文本。

真实 Provider 网络调用未作为必过条件执行；本反馈以本地 fake/provider doubles 和正式 Headless/Application 测试为验收依据。全量测试的 3 个 skipped 保持现有测试套件语义，未被改写为通过。

## 5. 交付结论

T07/T08 验收、T06 精确回归修复、文档同步、遗留欠账复核和验证均完成。T09-1 Checklist 已全部勾选；`docs/Context-Index.md` 已记录 `implemented_unarchived`。未执行 Git 写操作，工作包和 Feedback 均保留在 `docs/work/`，等待用户后续手动归档。

## W06 第一次验收返工

本次返工严格限定为三项验收问题：A01 当前事实残留、Context Index 快照日期滞后、`NO_COLOR` 回归测试未显式建立环境条件。未重新探索或调整 Context Budget / Compact 架构，未修改 Checklist、冻结工作包或历史 Feedback，未执行 Git 写操作和归档。

### 1. 根因与实际修改

- A01 的 `[DEFER]` 行是在 T09-1 已完成生产接线后遗留的旧当前事实，把生产 tool-free summarizer 与仍未实现的 Memory/retrieval、真实模型窗口解析混写在同一条延后描述中。已将其拆为当前事实：Application 正式链路中的 tool-free L4/L5 summarizer、manual `/compact`、dynamic limits 与 fail-closed/no-fallback 边界；只保留 Memory、retrieval 等真实后置能力为 `[DEFER]`。修改文件：`docs/context/A01-AgentRuntime/AgentRuntime-Context.md`。
- Context Index 的 `snapshot_date` 已为 `2026-08-21`，但 `status_snapshot` 仍为 `2026-08-19`，属于快照元数据不同步。已将 `status_snapshot` 更新为 `2026-08-21`，并保持 T09-1 为 `implemented_unarchived`、工作包位于 `docs/work/`、不归档。修改文件：`docs/Context-Index.md`。
- 原有实现已在 `RichTerminalRenderer._capture()` 显式设置 `no_color=False`，但没有测试强制建立 `NO_COLOR` 环境条件，因此测试可能依赖 pytest 启动环境。已在 `tests/test_tui.py` 新增最小回归测试，使用 pytest `monkeypatch.setenv("NO_COLOR", "1")` 后构造 `RichTerminalRenderer`，分别调用 user、agent、tool 渲染，并断言既有 truecolor ANSI 背景/前景/语义颜色仍存在。没有修改 TUI palette、renderer 产品样式或其它交互行为。

为确认回归测试确实守住修复边界，曾临时移除 `no_color=False` 做一次可恢复验证：新增测试以 `1 failed in 1.07s` 失败，失败断言为 user truecolor 背景 ANSI 缺失；随后立即恢复该行，`tests/test_tui.py` 重新通过 `73 passed`。

### 2. 当前事实残留扫描

已扫描 `docs/context/`、`docs/core-design/`、`docs/user-manual/`、`docs/Tools.md`、`docs/Context-Index.md` 和 `eval/README.md`。除真实边界外，没有发现其它把生产 tool-free L4/L5 summarizer、dynamic limits、Transcript/Timeline 或正式 `/compact` 写成未实现的当前事实。

扫描保留且语义正确的未实现/后置描述只有：`/memory`、`/dream` 等未实现命令，Memory/retrieval，Persistent Runtime checkpoint，以及 Web/Desktop/IDE、Subagent/Multi-Agent 等尚未进入当前范围的能力。没有修改冻结工作包或历史 Feedback。

### 3. 精确测试与验证结果

以下命令均在 `D:\project\Re-UthCode`、Conda 环境 `re-uthcode` 中执行：

| 范围 | 命令 | 结果 |
| --- | --- | --- |
| TUI | `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_tui.py -q` | `73 passed in 8.76s`；failed 0；skipped 0 |
| T06 精确回归（首次并行尝试） | `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_command_dispatcher.py tests/test_w04_session_commands.py tests/test_cli.py tests/test_tui.py tests/test_application_runtime.py tests/test_t09_1_context_protocol_e2e.py -q` | `1 failed, 164 passed in 23.46s`；`test_tui_double_escape_pauses_and_resume_keeps_the_turn_alive` 时序超时；未作为验收结果采纳 |
| T06 失败用例隔离复现 | `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_tui.py::test_tui_double_escape_pauses_and_resume_keeps_the_turn_alive -q` | `1 passed in 1.56s` |
| T06 精确回归（串行重跑） | `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_command_dispatcher.py tests/test_w04_session_commands.py tests/test_cli.py tests/test_tui.py tests/test_application_runtime.py tests/test_t09_1_context_protocol_e2e.py -q` | `165 passed in 24.15s`；failed 0；skipped 0 |
| T07 target | `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_w05_diagnostics.py tests/test_w06_integration_delivery.py tests/test_t09_1_context_protocol_e2e.py tests/test_architecture_boundaries.py -q` | `60 passed in 9.93s`；failed 0；skipped 0 |
| 全量 pytest | `conda run --no-capture-output -n re-uthcode python -m pytest -q` | `1254 passed, 3 skipped in 100.00s (0:01:39)`；failed 0 |
| 编译 | `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests eval` | exit code 0；无输出；通过 |
| diff 检查 | `git diff --check` | exit code 0；仅有工作树 LF/CRLF 转换提示；无 whitespace error |

真实 Provider 网络调用未执行；本次返工只验证本地正式 Application/TUI/test-double 链路。工作包仍位于 `docs/work/`，等待用户手动归档。

## W06 第二次验收返工：T09-1 P1 Hard Gate 与 direct async limits

执行日期：2026-08-22

本轮只处理独立包级验收发现的 P1-1、P1-2，以及冻结 Tasks 的文档路径偏差记录；未重新设计 Context Budget/Compact 主体架构，未扩大 T09-1 范围，未修改 Checklist 文字/结构/编号/顺序，也未执行任何 Git 写入或工作包归档。

### 1. 冻结路径偏差（P2）

冻结 Tasks 的 T07 文件清单（`T09-1-Context预算与Compact协议补齐-tasks.md` 第 286～288 行）写入了不存在的 `docs/current/A03-agent-runtime.md` 与 `docs/current/A04-infrastructure.md`。当前实际维护路径是 `docs/context/A03-State/State-Context.md` 与 `docs/context/A04-Orchestration/Orchestration-Context.md`，并已由此前 W06 文档同步覆盖。影响仅是验收/维护路由指向错误，不改变源码、架构或运行行为。

Tasks 已因首次 Worker Prompt 派发而冻结；本轮没有直接修改 Tasks，而是在本 Feedback 末尾记录偏差、实际路径、影响和不修改冻结文件的原因。

### 2. P1-1 根因、修复语义与文件

根因是 Application 在 direct `_prepare_request`、formal Turn `prepare`（以及手动 compact 的预算基线）中把未填写的 `max_output_tokens` 转成 `requested_output_reserve=0`。Anthropic、OpenAI-compatible Chat Completions 和 OpenAI Responses Integration 在 request 未显式带该字段时都会实际发送 4096 的默认 output 参数，因此已知 Provider output 或 combined limit 可能被错误放行。

修复为单一 Provider-independent `DEFAULT_OUTPUT_RESERVE = 4096` 事实：Application 以“本次 request 显式值 → ModelProfile 配置值 → 4096”顺序解析 effective output reserve，并在预算解析、Hard Gate 和最终 `GenerationRequest.max_output_tokens` 中复用同一值；三个 Provider Integration 的 SDK fallback 也改为引用该共享事实。没有按 Provider 名称分支、没有伪造未知 limit。已知 output/combined 维度不安全时，Hard Gate 在 Provider stream 前 fail closed，调用次数为 0；已配置 output 值仍优先于默认值。

本轮 P1-1 修改文件：

- `src/uthcode/core/provider.py`
- `src/uthcode/application/generation.py`
- `src/uthcode/integrations/providers/anthropic.py`
- `src/uthcode/integrations/providers/openai_compat.py`
- `src/uthcode/integrations/providers/openai_responses.py`
- `tests/test_context_budget_gate.py`

新增/加强回归覆盖未配置 output 的 direct output-limit、direct combined-limit 和 formal Turn；均断言不安全时 Provider call/stream 为 0。

### 3. P1-2 根因、修复语义与文件

根因是公开 `start_generation` 使用同步 limits resolver。遇到 Anthropic-style async `resolve_model_limits` 时，旧代码关闭 awaitable 并返回 `None`；用户未配置 `context_window` 时，可靠 Provider input metadata 因而丢失，direct Headless 路径错误地 fail closed。

修复为 direct request preparation 的可 await 边界：`start_generation` 保留同步 Provider 的立即准备；若 runtime limits resolver 返回 awaitable，则生成一个延迟准备的 `GenerationHandle`。公开 `stream_generation` 的 `events()`，以及显式 `await application.start_generation(...)`，会先 await limits、再解析 ContextBudget、执行最终 request Hard Gate，只有 Gate 通过后才进入 Provider stream。awaitable 不再被静默关闭或当作 unknown；正式 Agent Turn 原有的 async limits 路径保持并复用同一 effective output reserve 语义。

本轮 P1-2 生产修改文件：`src/uthcode/application/generation.py`；Anthropic-style fake Models API 与 direct Application 回归位于 `tests/test_anthropic_integration.py`。安全分支证明 metadata retrieve 已被 await、Gate 通过后才发生一次 stream；已知 output limit 不安全分支证明 metadata 已被 await 且 Provider stream 为 0。

### 4. 本轮实际验证结果

以下命令均在 `D:\project\Re-UthCode`、Conda `re-uthcode` 环境执行，Provider limits/count/stream 均使用 fake/test double，无真实网络调用：

| 范围 | 命令 | 精确结果 |
| --- | --- | --- |
| P1 定向 | `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_context_budget_gate.py tests/test_anthropic_integration.py -q` | `37 passed, 1 skipped in 2.43s`；failed 0 |
| T01 | `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_configuration.py tests/test_config_loader_integration.py tests/test_provider_model_limits.py tests/test_context_budget_gate.py tests/test_context_compiler.py tests/test_application_runtime.py tests/test_application_runs.py tests/test_agent_loop.py -q` | `189 passed in 8.24s`；failed 0；skipped 0 |
| T05 | `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_application_runtime.py tests/test_application_runs.py tests/test_session_files.py tests/test_t09_1_context_protocol_e2e.py -q` | `104 passed in 9.28s`；failed 0；skipped 0 |
| T06 | `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_command_dispatcher.py tests/test_w04_session_commands.py tests/test_cli.py tests/test_tui.py tests/test_application_runtime.py tests/test_t09_1_context_protocol_e2e.py -q` | `165 passed in 23.99s`；failed 0；skipped 0 |
| T07 target | `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_w05_diagnostics.py tests/test_w06_integration_delivery.py tests/test_t09_1_context_protocol_e2e.py tests/test_architecture_boundaries.py -q` | `60 passed in 7.89s`；failed 0；skipped 0 |
| 架构 | `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q` | `23 passed in 4.73s`；failed 0；skipped 0 |
| 全量 pytest | `conda run --no-capture-output -n re-uthcode python -m pytest -q` | `1259 passed, 3 skipped in 102.62s`；failed 0 |
| 编译 | `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests eval` | exit code 0；无输出；通过 |
| diff 检查 | `git diff --check` | exit code 0；仅有 LF/CRLF 转换提示；无 whitespace error |

未验证项：未执行真实 Provider 网络调用，未验证外部 Anthropic/OpenAI 服务在当前环境下的实际 metadata/API 响应；本轮只验证 SDK adapter 与 Application 的离线 fake 链路。未发现需要用户拍板的产品、架构或范围决策。

### 5. 本轮 UTF-8 guard 与 Git 边界

本轮 Feedback 追加前原文件已通过 UTF-8 guard；追加后将再次检查本文件的 UTF-8 解码、replacement character、常见乱码标记和 Markdown fence parity。未执行 `git add`、commit、push、merge、rebase、tag、release、分支操作或工作包归档。

## 第二次包级验收返工：异步 limits Handle 快照与延迟准备

执行日期：2026-08-22

本轮只处理独立包级验收提出的异步 limits Handle P1/P2：冻结 direct Handle 的 Provider/model/config snapshot，并将 async limits resolver 延迟到 Handle 真正消费时执行。未重新设计 Context Budget/Compact 主体架构，未扩大 T09-1 范围，未修改冻结 Requirement、Spec、Tasks、Checklist、Prompt，也未执行任何 Git 写入或工作包归档。

### 1. P1 根因与修复

根因是上一轮 direct async preparation 虽然捕获了旧 Provider 和旧 remote model id，但 deferred `_prepare_request` 没有传入冻结的 `model_ref`。Handle 创建后切换模型再消费时，`_prepare_request` 从 Application 当前配置读取新 profile，导致旧 Provider 可能收到新模型的 request model、模型选择和环境身份。

修复在 `start_generation` 创建 Handle 时冻结当前 `model_ref`、selected ModelProfile、Provider 和 remote model id；延迟准备始终把冻结 `model_ref` 传入 `_prepare_request`，并只针对该冻结 remote id 解析一次 runtime limits，再把结果用于该 request。因此 request model、Application-owned system/environment identity、Context config snapshot 与创建时 Provider 一致；runtime limits 虽在消费时获取，但不会改用切换后的模型。模型切换只影响之后新建的 Handle。正式同步/异步 Provider、Headless stream 和 Handle await 均复用同一快照边界。

P1 生产修改文件：

- `src/uthcode/application/generation.py`

新增 `test_async_limits_handle_binds_model_snapshot_across_model_switch` 回归：旧 Handle 在切换到第二模型后消费，断言旧 Provider 只解析 `remote-one`、只收到 `remote-one` request，且新 Provider 没有 limits/stream 调用。

### 2. P2 根因与修复

根因是 `start_generation` 在同步调用阶段立即调用 async `resolve_model_limits`，生成并保存 coroutine。未消费 Handle 被回收时产生 `coroutine was never awaited`；已取消 Handle 首次 await 时，旧 `_ensure_prepared` 仍先 await metadata，再在之后检查取消。

修复为真正的 deferred preparation factory：`start_generation` 只完成 request 参数校验、Provider/model snapshot 捕获和 Handle 创建，不调用 limits resolver，也不创建 coroutine。`GenerationHandle._ensure_prepared` 在创建 preparation task 前先检查 `CancellationToken`；factory 内才调用 resolver，并对同步返回值和 awaitable 返回值统一校验/await。准备 task 被 Handle 缓存，支持并发 await 共享同一次 resolver；成功后缓存最终 immutable request，`events()` 仍保持单次消费。取消、resolver/prepare 错误均不会进入 Provider stream；未消费 Handle 不持有待 await coroutine。

本轮 P2 生产修改文件：

- `src/uthcode/application/generation.py`

新增/调整回归文件：

- `tests/test_application_runtime.py`：async model snapshot、未消费 Handle GC 无 warning、取消不解析/不 stream、并发 await 与单次 resolver。
- `tests/test_context_budget_gate.py`：async output/combined unsafe Hard Gate 零 stream，并将 direct preparation 错误断言移到 Handle 消费边界。
- `tests/test_application.py`：prompt build failure 断言移到 Handle 消费边界。

### 3. 本轮复现与验证结果

回退修复前新增回归精确复现：`test_async_limits_handle_binds_model_snapshot_across_model_switch` 收到 `remote-two` 而非 `remote-one`；未消费 async Handle 产生 `never awaited` warning；取消后 limits resolver 调用次数为 1。修复后以下命令均在 `D:\project\Re-UthCode`、Conda `re-uthcode` 环境执行，Provider limits/count/stream 使用 fake/test double，无真实网络调用：

| 范围 | 命令 | 精确结果 |
| --- | --- | --- |
| 新增定向 | `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_application_runtime.py::test_async_limits_handle_binds_model_snapshot_across_model_switch tests/test_application_runtime.py::test_unconsumed_async_limits_handle_does_not_leak_coroutine tests/test_application_runtime.py::test_cancelled_async_limits_handle_does_not_resolve_or_stream tests/test_application_runtime.py::test_async_limits_handle_resolves_once_when_prepared_then_streamed tests/test_context_budget_gate.py::test_async_limits_output_or_combined_gate_blocks_before_stream tests/test_anthropic_integration.py::test_anthropic_async_limits_are_awaited_before_direct_application_stream -q` | `8 passed in 2.15s`; failed 0 |
| 受影响 direct/context/integration | `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_application_runtime.py tests/test_context_budget_gate.py tests/test_anthropic_integration.py -q` | `58 passed, 1 skipped in 4.07s`; failed 0 |
| T01 | `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_configuration.py tests/test_config_loader_integration.py tests/test_provider_model_limits.py tests/test_context_budget_gate.py tests/test_context_compiler.py tests/test_application_runtime.py tests/test_application_runs.py tests/test_agent_loop.py -q` | `195 passed in 8.05s`; failed 0 |
| T05 | `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_application_runtime.py tests/test_application_runs.py tests/test_session_files.py tests/test_t09_1_context_protocol_e2e.py -q` | `108 passed in 9.11s`; failed 0 |
| T06 | `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_command_dispatcher.py tests/test_w04_session_commands.py tests/test_cli.py tests/test_tui.py tests/test_application_runtime.py tests/test_t09_1_context_protocol_e2e.py -q` | `169 passed in 23.47s`; failed 0 |
| T07 target | `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_w05_diagnostics.py tests/test_w06_integration_delivery.py tests/test_t09_1_context_protocol_e2e.py tests/test_architecture_boundaries.py -q` | `60 passed in 8.06s`; failed 0 |
| 架构 | `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q` | `23 passed in 4.85s`; failed 0 |
| 全量 pytest | `conda run --no-capture-output -n re-uthcode python -m pytest -q` | `1265 passed, 3 skipped in 136.66s (0:02:16)`; failed 0 |

附加验证：

- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests eval`：exit code 0，无输出。
- `git diff --check`：exit code 0；仅有工作树 LF/CRLF 转换提示，无 whitespace error。
- `python C:\Users\93445\.codex\skills\uth-utf8-guard\scripts\check_utf8_docs.py docs/work/T09-1-Context预算与Compact协议补齐/feedback/W06-delivery-regression-cleanup-feedback.md`：`OK: 1 file(s) passed UTF-8 guard`。

未验证项：未执行真实 Provider 网络调用，未验证外部 Anthropic/OpenAI 服务在当前环境下的实际 metadata/API 响应；本轮验证限于本地 Provider adapter、fake/test-double 与正式 Application/Headless/TUI regression。未发现需要用户拍板的产品、架构或范围决策。

本轮未执行 `git add`、commit、push、merge、rebase、tag、release、分支操作或工作包归档；冻结 Requirement、Spec、Tasks、Checklist、Prompt 均保持未修改，工作包仍位于 `docs/work/`，等待用户手动归档。

## 第三次包级验收返工：Instruction/Session 快照与 preparation task 取消所有权

执行日期：2026-08-22

本轮只处理第三轮独立包级验收发现的两个 P1：异步 limits Handle 的 Instruction/Session 身份快照不完整，以及 preparation task 的取消所有权错误。上一轮“Handle 已冻结完整 snapshot”和“延迟准备的 task 引用/异常已完成收口”的结论被本轮可复现反例推翻；本节追加纠正，不改写前两段历史记录。未重新设计 Context Budget/Compact 主体架构，未扩大 T09-1 范围，未修改冻结 Requirement、Spec、Tasks、Checklist、Prompt，也未执行任何 Git 写入或工作包归档。

### 1. P1-1 反例、根因与修复语义

反例是：Handle 创建时 Instruction epoch 为旧值，随后公开 `InstructionLoader.adopt_session_state()` 切换到新 Session/Instruction State；消费旧 Handle 时，旧 Provider/model 虽然仍正确，但 deferred `_prepare_request` 重新读取了 Application 当前的可变 `InstructionLoader`，请求 prompt blocks、epoch 和 fingerprint 已变成新状态。上一轮只冻结 Provider、remote model 和 model reference，未冻结 Instruction/Session Context source，因此“完整 snapshot”结论不成立。

修复在 Handle 创建边界生成不可变 `ProjectInstructionSource` 快照，冻结 effective prompt blocks、instruction epoch、stable prefix fingerprint 与 change reason；异步 limits 仍延迟到真正消费时解析，但 request preparation 始终使用该 source，并继续使用创建时 Provider、model reference、remote model 与 limits/config 语义。`ApplicationContextService.compile()` 与 `compose_generation_request()` 现在接受该不可变 source；生成 request metadata 的 `prefix_change_reason` 也来自创建时 source。direct GenerationHandle 当前没有从 Session service late-read Transcript/Timeline；其 conversation facts 来自创建时传入的 immutable `GenerationRequest`，因此本轮没有扩大到其它 Session 架构。

实际修改文件：

- `src/uthcode/application/generation.py`：创建时冻结 `ProjectInstructionSource`，并在 deferred preparation 中传入；
- `src/uthcode/application/context.py`：接入不可变 source，并保留创建时 instruction change reason；
- `tests/test_application_runtime.py`：新增公开 `adopt_session_state()` 后消费旧 Handle 的 prompt/epoch/fingerprint/change-reason/provider/model 回归。

回退修复时，`test_async_limits_handle_binds_instruction_snapshot_across_adopt_session_state` 精确失败：旧 Handle 的 `system_prompt` 包含 `new instruction epoch`，不包含创建时的 `old instruction epoch`。修复后该测试通过，并断言旧 Provider 只解析/stream 旧 remote model，旧 request 的完整 Instruction 身份保持一致。

### 2. P1-2 反例、根因与修复语义

反例一是 `handle.cancel()` 在 async limits resolver 阻塞期间只设置了 Handle token，没有取消 Handle 所拥有的 preparation task；调用方会等待到超时。反例二是两个 waiter 共享同一个 preparation task 时，普通 waiter 的 `Task.cancel()` 直接沿未 shield 的 await 链取消了共享 task，另一个 `events()` waiter 随后收到 `asyncio.CancelledError`，即使 Handle token 没有被取消也无法完成。上一轮的 deferred factory 虽避免了未消费 coroutine，但没有建立这两个取消所有权边界，故“task 收口已完成”的结论被纠正。

修复后的语义为：

- `GenerationHandle` 显式拥有 preparation task；`handle.cancel()` 在 token 转换成功时同时取消仍在运行的 preparation task，resolver 收到取消，公开调用方稳定收到 `GenerationCancelled`，Provider stream 次数为零；
- 普通 asyncio waiter 通过 `asyncio.shield()` 等待共享 preparation task，单个 waiter 的取消只结束该 waiter，不改变 Handle token、不取消其它 waiter 或共享 resolver；
- preparation task 的成功、普通异常和底层 `asyncio.CancelledError` 均由 Handle 的 done callback 收口，缓存终态 request/error、清除 task/factory 引用，并消费 task exception，避免 pending/unretrieved task；resolver 的 raw `asyncio.CancelledError` 映射为 `GenerationCancelled`；
- pre-cancel 仍在创建 preparation task 前 fail fast；未消费 Handle 不创建 coroutine；并发正常 await 只 resolve 一次；`events()` 仍是单次消费，`await Handle` 与 `events()` 可交错但不会互相误杀。

实际修改文件：

- `src/uthcode/application/generation.py`：preparation task ownership、shielded shared wait、cancel/error cleanup 与取消映射；
- `tests/test_application_runtime.py`：新增阻塞 resolver 的 Handle cancel、waiter/events 交错取消，以及 resolver exception/`CancelledError` 回归；保留并回归 pre-cancel、未消费 GC、正常并发 await、async output/combined unsafe 零 stream。

回退修复时，阻塞 resolver 的 `test_handle_cancel_cancels_owned_async_limits_preparation` 以 `TimeoutError` 失败；加入 waiter 已进入共享 await 的调度屏障后，`test_waiter_cancellation_does_not_cancel_shared_preparation_or_events` 以共享 resolver 的 `CancelledError` 失败。修复后两项均通过：resolver cancellation 次数为 1、stream 为 0 或 1（分别对应 Handle cancel/正常另一 waiter），无 pending preparation task。

### 3. 本轮精确验证

以下命令均在 `D:\project\Re-UthCode`、Conda 环境 `re-uthcode` 执行；Provider limits/count/stream 均使用 fake/test double，未发起真实 Provider 网络调用：

| 范围 | 命令 | 精确结果 |
| --- | --- | --- |
| 新增 P1 定向 | `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_application_runtime.py::test_async_limits_handle_binds_instruction_snapshot_across_adopt_session_state tests/test_application_runtime.py::test_handle_cancel_cancels_owned_async_limits_preparation tests/test_application_runtime.py::test_waiter_cancellation_does_not_cancel_shared_preparation_or_events tests/test_application_runtime.py::test_async_limits_handle_resolves_once_when_prepared_then_streamed tests/test_application_runtime.py::test_cancelled_async_limits_handle_does_not_resolve_or_stream -q` | `5 passed`；failed 0 |
| resolver failure 定向 | `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_application_runtime.py::test_async_limits_preparation_closes_resolver_failures -q` | `2 passed`；failed 0 |
| Application runtime | `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_application_runtime.py -q` | `24 passed`；failed 0 |
| direct/context/integration | `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_application_runtime.py tests/test_context_budget_gate.py tests/test_anthropic_integration.py -q` | `63 passed, 1 skipped`；failed 0 |
| T01 | `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_configuration.py tests/test_config_loader_integration.py tests/test_provider_model_limits.py tests/test_context_budget_gate.py tests/test_context_compiler.py tests/test_application_runtime.py tests/test_application_runs.py tests/test_agent_loop.py -q` | `200 passed`；failed 0；skipped 0 |
| T05 | `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_application_runtime.py tests/test_application_runs.py tests/test_session_files.py tests/test_t09_1_context_protocol_e2e.py -q` | `113 passed`；failed 0；skipped 0 |
| T06 | `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_command_dispatcher.py tests/test_w04_session_commands.py tests/test_cli.py tests/test_tui.py tests/test_application_runtime.py tests/test_t09_1_context_protocol_e2e.py -q` | `174 passed`；failed 0；skipped 0 |
| T07 | `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_w05_diagnostics.py tests/test_w06_integration_delivery.py tests/test_t09_1_context_protocol_e2e.py tests/test_architecture_boundaries.py -q` | `60 passed`；failed 0；skipped 0 |
| 架构 | `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q` | `23 passed`；failed 0；skipped 0 |
| 全量 pytest | `conda run --no-capture-output -n re-uthcode python -m pytest -q` | `1270 passed, 3 skipped`；failed 0 |
| 编译 | `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests eval` | exit code 0；无输出 |
| diff 检查 | `git diff --check` | exit code 0；仅有 LF/CRLF 转换提示，无 whitespace error |

### 4. 未验证项与边界

未执行真实 Anthropic/OpenAI Provider 网络调用，未验证外部服务在当前环境下实际返回的 metadata/API 响应；本轮只验证本地 Integration adapter、fake/test-double 与正式 Application/Headless 路径。未发现需要产品、架构、范围或安全决策的冲突。已运行 UTF-8 guard：追加前与追加后均检查本 Feedback 的 UTF-8 解码、replacement character、常见乱码和 Markdown fence parity；追加后结果为 `OK: 1 file(s) passed UTF-8 guard`。

未执行 `git add`、commit、push、merge、rebase、tag、release、分支操作或工作包归档；冻结 Requirement、Spec、Tasks、Checklist、Prompt 保持未修改，W06 Feedback 仅在末尾追加本章，工作包仍位于 `docs/work/`。
