# W01：动态模型限制与请求安全链 Feedback

## 交付结论

W01 已按 Prompt 实施。T01 的九项 Checklist 均有实现或测试证据；T02 及后续工作包未实施，原始 Prompt、Spec、Tasks 和 Checklist 文字结构均未修改。

## 实际完成

- 在 `core` 增加 UthCode-owned `ModelLimits`、`ContextCountEstimate`、`ContextBudget`、`RequestAccounting` 和 `GateDecision`。输入、输出、combined 三个限制维度独立保存；未知维度保持 `None`。
- `ModelProfile.context_window` 只接受正整数。项目配置只能在用户层已有值时保持或收紧该值；缺失用户值、项目补造值或项目放大值均明确失败。
- 删除 Context 生产路径的固定 258K authority。`FakeProvider` 不再提供默认窗口；正式 fake 工厂显式使用无 metadata，测试 double 必须显式提供 `ModelLimits`。
- 增加确定性 request accounting，覆盖 instruction、messages、tools、known framing；requested output reserve 进入 output/combined Hard Gate。Pressure Estimate 与 Preflight Safety Count/Estimate 使用不同来源和集中 allowance，并写入 bounded diagnostics/metadata。
- 接通正式 `Application -> Context Compiler -> awaitable request preparer -> AgentLoop -> Provider` 链。模型 limits 在 active Turn 内冻结；可选 Provider runtime resolver/count capability 只返回 Core DTO，Anthropic 通过 fake client 验证，无真实网络 metadata 请求。
- 请求发送前执行分维 Hard Gate。L1 externalize oversized tool-result preview，L2 shrink inactive previews，L3 由动态预算下的 compiler omission 完成；每轮 reduction 后重新 build/re-gate，current/protected fact 与 ToolCall/ToolResult pair 不拆分，required fact 超限时不调用 Provider。
- 同步更新动态 Context 使用状态展示，避免 UI、CLI 和 diagnostics 继续假定固定 258K。未新增 manual command、L4/L5 或 History/Session authority。

## 主要文件范围

- Core：`src/uthcode/core/provider.py`、`src/uthcode/core/context.py`、`src/uthcode/core/__init__.py`。
- Application：`src/uthcode/application/configuration.py`、`src/uthcode/application/context.py`、`src/uthcode/application/generation.py`。
- Integrations：`src/uthcode/integrations/config/loader.py`、`template.py`、`providers/anthropic.py`、`providers/fake.py`、`providers/factory.py`。
- Interface/status consumers：`src/uthcode/application/commands/builtins.py`、`src/uthcode/interfaces/tui/app.py`、`rendering.py`。
- 新增验收：`tests/test_provider_model_limits.py`、`tests/test_context_budget_gate.py`；其余受影响 Provider test doubles、CLI/TUI/session/eval fixtures 改为显式声明测试 limits。

## 正式调用流程

1. Application 从用户 ModelProfile 和可选 Provider runtime capability 得到冻结 limits。
2. ApplicationContextService 先编译 provider-visible request，供可选 Provider count endpoint 读取同一结构；随后以 ContextBudget 编译、计数并执行 L1-L3 与最终 Hard Gate。
3. 只有 `hard_safe` 且各 input/output/combined 维度通过时，现有 AgentLoop 才进入 ProviderPort；缺少可靠 input limit 或 required fact 超限均在 Provider call 前抛出受控错误。

## 验证证据

使用环境：Conda `re-uthcode`，Python 3.12.13。

```text
python -m pytest tests/test_configuration.py tests/test_config_loader_integration.py tests/test_provider_model_limits.py tests/test_context_budget_gate.py tests/test_context_compiler.py tests/test_application_runtime.py tests/test_application_runs.py tests/test_agent_loop.py -q
191 passed in 23.99s

python -m pytest tests/test_architecture_boundaries.py -q
23 passed in 11.98s

python -m pytest tests/test_provider_model_limits.py tests/test_context_budget_gate.py -q
15 passed in 12.03s

python -m pytest tests/test_application.py tests/test_application_runtime.py tests/test_application_runs.py tests/test_application_tools.py tests/test_cli.py tests/test_command_dispatcher.py tests/test_config_contract.py tests/test_package.py tests/test_w04_session_commands.py tests/test_w05_diagnostics.py tests/eval/test_eval_execution.py -q
209 passed in 55.87s

python -m pytest -q --deselect tests/test_tui.py::test_plan_revisions_and_task_state_append_as_distinct_permanent_blocks --deselect tests/test_tui.py::test_renderer_restores_roles_surfaces_markdown_and_code_colours --deselect tests/test_tui.py::test_tool_rows_keep_status_text_and_semantic_colour
1259 passed, 3 skipped, 3 deselected in 207.69s

python -m compileall -q src/uthcode tests/eval tests/test_package.py tests/test_tui.py
passed

git diff --check
passed; Git only emitted existing CRLF normalization warnings
```

完整 `tests/test_tui.py` 当前为 `69 passed, 3 failed`。失败项均是未改动的 `src/uthcode/interfaces/tui/terminal.py` 与当前 Rich 输出之间的 ANSI truecolor 背景/前景码断言：`test_plan_revisions_and_task_state_append_as_distinct_permanent_blocks`、`test_renderer_restores_roles_surfaces_markdown_and_code_colours`、`test_tool_rows_keep_status_text_and_semantic_colour`。排除这三项后的全量结果如上；未将其描述为通过，也未扩大 W01 范围修改 TUI terminal renderer。

## 偏差、风险与边界

- Provider runtime metadata 与 input count 是可选 capability；没有可靠 input limit 时正式 Application fail closed，不猜测型号窗口。
- Anthropic metadata/count 使用 fake client 验证；OpenAI/compat 无可靠来源时保持 unknown。
- 既有工作树中的 `AGENTS.md` 非 W01 修改，保留原状。
- 未执行 Git commit、push、merge、rebase、tag 或工作包归档；Checklist 仅将 T01 既有复选框改为完成，T02+保持不变。

## 遗留负担清理

已移除固定 258K runtime authority、fake adapter 默认窗口和固定预算 UI 文案；未新增兼容 alias、重复 async protocol、持久 Compact FSM、bundled model metadata 或未来 L4/L5/manual command 实现。

## W01 第一次验收返工

### 返工原因

第一次验收发现 W01 的最终请求安全检查没有把 Provider count、预算裁剪后的请求、Hard Gate 元数据和实际发送对象绑定在同一条请求准备链上；Provider count 受控失败也会直接使 request preparer 进入 internal failure；`ContextBudget` 还允许在没有任何 configured/provider input limit 时由调用方直接构造 effective input limit。本轮仅修复这三个 W01 问题，没有扩大到 T02～T08 或重新设计 Context Budget / Compact 架构。

### 三个问题的根因

1. 原 request preparation 先对 `context_budget=None` 的未裁剪请求执行 Provider count，再把该 count 传给预算编译、L3 omission 以及后续 L1/L2 reduction 产生的另一份请求。于是 reduction 前 count（复现为 `46408`）与最终请求本地 accounting（复现为 `367`）不对应，可能在 effective input limit 为 `10000` 时错误触发 Hard Gate。此前流程还没有对最终 metadata 稳定后的对象做一次明确的 count/send 对齐。
2. `count_input_tokens()` 的异常原先直接向上冒泡，未区分 capability 缺失、Provider count endpoint 的受控运行时失败、取消、配置/类型错误和 limit authority 错误，因此已有可信 input limit 与可用本地 estimator 时仍会以 internal failure 结束，或者存在误吞安全错误的风险。
3. `ContextBudget.__post_init__` 原先只校验 effective 数值及其与已知 limit 的关系，没有先强制要求至少一个 input authority，导致 `ContextBudget(effective_input_limit=10_000)` 在 configured/provider 均为 `None` 时能够成功构造，绕过了唯一 limit authority。

### 实际修改文件

本轮返工实际修改了：

- `src/uthcode/application/generation.py`
- `src/uthcode/application/context.py`
- `src/uthcode/core/context.py`
- `tests/test_context_budget_gate.py`
- 本 Feedback 文件（仅在原文件末尾追加本章节）

本轮未修改 Requirement、Spec、Tasks、W01～W06 Prompt、Checklist 的文字/结构/编号/顺序，也未修改 TUI terminal renderer。Checklist 不在本轮范围内。

### 修正后的 final request count / reduction / re-gate 流程

1. Application 先解析并冻结 configured input limit 与可靠 Provider max input，形成 `ContextBudget`；再以该预算编译候选请求，使 L3 omission 已经体现在候选的 Provider-visible messages 中，并暂缓 Hard Gate。
2. Provider count 针对这份候选 `GenerationRequest` 执行。若 Provider count 带来的 Gate/编译结果改变了 request，则对改变后的同一候选重新 count；不再复用未裁剪请求的 count。
3. 若 L1 或 L2 改变消息，Application 为改变后的 request 重新计算 accounting、重新 count、重新执行 Auto/Hard Gate。随后用同一组候选 messages、reduction levels 和 provider count 禁用再次 reduction，重建最终 metadata 并 re-gate；metadata/accounting 的变化也会触发重新 count。
4. 该过程循环到最终 request 与最近一次 Provider count 收到的不可变 `GenerationRequest` 完全相等，并直接返回刚被 count 的对象给 Provider。这样 final count、count source、gate、accounting、metadata 和实际发送 request 对应同一份请求；异常不稳定时 fail closed。
5. 为避免同一进程内重复重建时 wall-clock history timestamp 改变 block id/diagnostics，process-local history projection 使用确定性的序列 timestamp，保证同一输入的 rebuild 不会仅因诊断字段变化而破坏上述稳定性检查。

### Provider count fallback 与 cancellation 边界

- capability 缺失、count 返回 `None`、同步路径遇到 async-only capability，或受控 Provider operational failure（包括 typed Provider/network/timeout 类失败）时，在已有可信 input limit 的前提下使用最终 request 的 deterministic local estimate。
- local fallback 的 source 明确为 `local.preflight_estimate`，fallback 原因写入 `context_count_fallback`，并使用集中定义的 `safety_allowance_for(..., kind="preflight_local_estimate")`；该近似值不会伪造 Provider count，也不会反向学习或推断模型窗口。
- `GenerationCancelled` 与 `asyncio.CancelledError` 继续传播到 Agent Loop 的 cancelled 结果，绝不进入 local fallback。`ProviderConfigurationError`、类型/值错误、invalid Provider response、ContextBudget/overflow/limit authority 错误也不作为普通 count outage 吞掉。
- configured input 与可靠 Provider input 都缺失时，`resolve_context_budget` 在任何 Provider count 前 fail closed，因此 Provider count 调用次数为 `0`。

### ContextBudget authority invariant

`ContextBudget` 现在无论是否显式传入 `effective_input_limit`，都必须至少有一个已知 input source：用户 configured input 或可靠 Provider max input。effective input limit 不得超过任一已知 input limit；两者都缺失时抛出明确 `ContextBudgetError`。没有新增固定窗口、bundled metadata、型号推断或默认 fallback。

### 新增/加强的测试场景

- budget-aware/L3 候选与未裁剪请求不同；Provider counter 捕获其实际 request，最终发送对象与最近一次 count 对象相同，并覆盖 reduction 前 count 大于 limit、L3 后安全且不再误拒绝的回归。
- L1、L2 分别改变 request 后重新 count/rebuild/re-gate；最终 metadata/accounting 与发送 request 一致。
- protected/current facts 保留，ToolCall/ToolResult pair 保持配对。
- Provider count capability 缺失时使用 local preflight estimate，并验证 source、fallback 原因与 allowance。
- 受控 Provider count failure 在可信 input limit 下回退 local estimate，ordinary Provider request 仍执行且不以 INTERNAL_ERROR 结束。
- cancellation 不进入 local fallback；配置错误不被当作 count outage。
- configured/provider input 都缺失时 Provider call count 为 0 并 fail closed；直接构造 `ContextBudget(effective_input_limit=10000)` 且无 authority source 时失败。
- 既有 25K、1M adaptive policy，以及 input/output/combined 分维 Gate 测试继续覆盖。

### 本轮实际验证命令与结果

以下命令均使用 `conda run --no-capture-output -n re-uthcode`，且 Provider limits/count/failure/cancellation 均为 fake client 或 test double：

```text
conda run --no-capture-output -n re-uthcode python -m pytest tests/test_configuration.py tests/test_config_loader_integration.py tests/test_provider_model_limits.py tests/test_context_budget_gate.py tests/test_context_compiler.py tests/test_application_runtime.py tests/test_application_runs.py tests/test_agent_loop.py -q
199 passed in 9.85s

conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q
23 passed in 9.43s

conda run --no-capture-output -n re-uthcode python -m pytest tests/test_provider_model_limits.py tests/test_context_budget_gate.py -q
23 passed in 2.99s

conda run --no-capture-output -n re-uthcode python -m pytest -q --deselect tests/test_tui.py::test_plan_revisions_and_task_state_append_as_distinct_permanent_blocks --deselect tests/test_tui.py::test_renderer_restores_roles_surfaces_markdown_and_code_colours --deselect tests/test_tui.py::test_tool_rows_keep_status_text_and_semantic_colour
1267 passed, 3 skipped, 3 deselected in 114.20s (0:01:54)

conda run --no-capture-output -n re-uthcode python -m pytest tests/test_tui.py -q
69 passed, 3 failed in 8.99s

git diff --check
passed; only existing CRLF normalization warnings, no whitespace error
```

完整 `tests/test_tui.py` 的三条失败仍为既有 ANSI truecolor 断言：`test_plan_revisions_and_task_state_append_as_distinct_permanent_blocks`、`test_renderer_restores_roles_surfaces_markdown_and_code_colours`、`test_tool_rows_keep_status_text_and_semantic_colour`。本轮未修改 `src/uthcode/interfaces/tui/terminal.py`，也未把这三条失败描述为通过。除这三条既有 TUI 失败外，本轮要求的 W01 定向、架构边界和排除已知失败的全量回归均通过；未使用真实网络属于本轮测试约束，不是未验证的网络行为声明。

### 范围与 Git 边界

未实施 T02～T08，也未实施 T02+ 的 History/Session v2 hard cut、Transcript/Timeline、L4/L5、manual compact、新 Compact FSM/Job/Manager、bundled model metadata/catalog、独立 compaction model 或 Permission/Plan/Todo/Runtime Hook 范围外修改。

未执行任何 Git commit、push、merge、rebase、tag、release、工作包归档或其它 Git 写操作；完成本轮返工后停止，等待重新验收。
