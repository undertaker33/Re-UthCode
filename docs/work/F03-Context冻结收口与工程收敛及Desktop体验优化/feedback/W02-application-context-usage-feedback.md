# W02 Application Context 与 Usage Feedback

## 状态

T02 已完成本轮 Application 实施与定向验收；未执行 Git commit、push、PR、merge、rebase、tag 或 release。未触碰用户已有 `.workbuddy/` 与 `临时目录/`。

## 实际改动

- 新增 `src/uthcode/application/request_preparation.py`，集中承载 Provider model-limit/count 解析、controlled count fallback、普通 request 的 counted/final preparation，以及 prospective ordinary request 的 `exact` / `local` 同源标识。helper 只接收 immutable request builder/Core 值，不持有 Application、Session 或 Timeline state。
- 新增 `src/uthcode/application/compaction.py`，承载 Application-owned 的 tool-free Provider request envelope、L4/L5/oversized subpass/fold payload、Hard Gate、validated stream 与 terminal Usage 提取；durable Timeline candidate 仍由 Core 构造、由 `UthCodeApplication` 提交。
- `src/uthcode/application/context.py` 迁移 compaction 类型到 `core.compaction`，接入 oversized subpass/fold candidate 生命周期、candidate validator、manual multi-epoch continuation，并为 prospective compose 增加不发布 Context status/diagnostics 的路径。summary 变短但 ordinary request 未收敛时在 durable append 前以 `no_reduction` 收口。
- `src/uthcode/application/generation.py` 将 ordinary、manual、overflow 与 L5 接入同一 Application/Core compaction 链；candidate commit 后重新构建 ordinary Context。ordinary 的 Last Provider Request Usage 取同一 Turn 内累计 `UsageUpdated` 的非负 delta；Compact/L5 取 terminal Usage。Context status 不再被上一 Provider request usage 直接覆盖。
- `src/uthcode/application/runs.py` 为每个 `_TurnDriver` 维护累计 Usage baseline，保证同一 Turn 的连续 UsageUpdated、tool continuation 与 pause/resume 按请求边界计算；新 Turn 从零基线开始。
- `src/uthcode/application/provider_usage.py` 新增安全的累计 Usage delta projection；`interfaces/desktop/bridge.py` 将 `last_provider_request_usage` 纳入 typed status 字段，仍不暴露 Provider raw details。
- 直接测试补充：prospective exact/local source contract、publish-free conversation projection，以及 full→reduced→full fingerprint/change；manual multi-epoch/terminal compaction Usage；L5/ordinary、non-negative Usage delta 与 Hard Gate unsafe ordinary 边界。

## 关键数据流与边界

`Application request builder → Provider count 或 controlled local fallback → 同源 prospective before/after → Core candidate validation → durable Timeline commit → Context rebuild`。prospective 构建使用 `publish=False`，不会把候选状态写进 Application 的当前 diagnostics；只有最终 ordinary request 才发布 projection。oversized subpass/fold 请求均无 tools 且先经过同一 Hard Gate，成功后只形成一个完整原 Turn Fine；中途 failure、cancel 或 invalid 不产生 durable write。

Last Provider Request Usage 与 Current Working Context 是两条独立投影：前者记录最近一次可证明的 ordinary delta 或 Compact/L5 terminal Usage，后者在 commit 后从新的 Timeline/Transcript 重新编译并按 exact/local 计量。

## 精确验证

- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_application_runs.py tests/test_application_runtime.py tests/test_t09_1_context_protocol_e2e.py tests/test_w05_diagnostics.py tests/test_desktop_bridge.py -q`：`181 passed`，`0 failed`，exit code `0`，`17.43s`（新增 projection/source/terminal Usage 测试后需再执行最新命令并以最新计数为准）。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q`：`23 passed`，`0 failed`，exit code `0`，`4.74s`。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_w05_diagnostics.py::test_cumulative_usage_delta_clamps_regressions_and_keeps_current_details tests/test_w05_diagnostics.py::test_context_projection_fingerprint_only_publishes_final_request tests/test_w05_diagnostics.py::test_prospective_request_keeps_exact_or_local_count_source tests/test_t09_1_context_protocol_e2e.py::test_l5_ages_fine_timeline_before_ordinary_request_at_low_pressure tests/test_t09_1_context_protocol_e2e.py::test_w02_manual_compact_continues_within_epoch_limit_until_retained_target tests/test_t09_1_context_protocol_e2e.py::test_w02_manual_compact_projects_terminal_provider_usage tests/test_t09_1_context_protocol_e2e.py::test_hard_unsafe_ordinary_request_never_streams_to_provider -q`：`7 passed`，`0 failed`，exit code `0`；新增 exact/local projection test 后另有 `2 passed`，`0 failed`，exit code `0`。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests`：exit code `0`。
- 已执行 source scan：`request_preparation.py` 与 `application/compaction.py` 均由多个 generation/compaction 调用点使用，helper 未持有 Application/Session/Timeline state；`UthCodeApplication` 仍是唯一 Application authority。

## 任务书偏差与风险

- 原有 `test_hard_unsafe_ordinary_request_never_streams_to_provider` 曾把“Provider requests 必须为空”作为断言；在 T02 冻结 oversized 语义下，oversized oldest Turn 必须允许 tool-free compaction subpass，但 Hard Gate unsafe ordinary request 仍绝不能发送。因此测试已收窄为 `ordinary == []` 且所有已记录请求均为 compaction request，没有放松 ordinary 安全边界。
- 原有 manual fixture 使用固定的 safe count，无法证明 prospective summary 前后同源计量；测试 fixture 已改为真实 local accounting（`pressure_extra=0`），未改变产品配置或 profile 参数。
- 本轮未运行仓库全量 `pytest -q`、`python -m pip check`、真实 Provider、干净 Windows 环境或 Desktop `npm run typecheck`/`npm test`/`npm run package`；这些属于后续包级验收，不能由本反馈描述为通过。
- 由于普通 Provider 的空 Usage 只能投影为 `not_available`，若 Compact/L5 后紧接着一个无 Usage 的 ordinary request，Last Provider Request Usage 按“最近请求”语义会回到 `not_available`；Compact/L5 terminal projection 已在无后续 ordinary 的 manual contract 中验证。

## Checklist

T02 项已按本轮实际测试与 source scan 勾选；T03～T09 未勾选，留给后续 Worker。冻结 Spec、Tasks、Prompt 文字未修改。

## 收口复核（首次 Feedback 写回后的追加）

- 在补充 exact/local source 与 full→reduced→full projection contract 后，重新执行指定定向集：`182 passed`，`0 failed`，exit code `0`，`17.77s`。
- 重新执行 `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q`：`23 passed`，`0 failed`，exit code `0`，`4.96s`；重新执行 `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests`：exit code `0`。
- L5 terminal-usage recording contract 补强后再次执行同一指定定向集：`182 passed`，`0 failed`，exit code `0`，`18.70s`；该结果为本 Feedback 的最终定向计数。

## 返工第 1 轮（Reviewer REQUEST CHANGES）

### Findings 与修复

- overflow `compact_async` 与 L5 `age_timeline_async` 均接入 `_start_agent_turn` 构建的同一 prospective candidate validator；validator 在 durable append 前比较完整 ordinary request 的 before/after。新增 exact count 恒定 `100` 的 overflow 等大回归与 L5 等大回归，均确认 `no_reduction` 不产生 Timeline append；overflow 不再把未收敛请求伪报为 completed。
- manual candidate 校验在同一次 before/after invocation 中，只要任一侧 count 退化为 local，就对两侧 immutable request 统一使用 local accounting。新增 Provider count 成功→失败、失败→成功两种切换回归，并用故意偏离的 exact 值证明不会混用来源。
- 删除 `_record_formal_run_usage` 到 `context.record_exact_usage` 的旧覆盖路径及 `provider_usage` Context measurement；`AgentRun._complete_turn` 在 terminal flush 后重新从普通 conversation 组合 Current Context，terminal assistant 内容进入 accounting，Provider Usage 仅更新独立的 Usage diagnostics。新增单请求 terminal assistant accounting 回归。
- Hard-unsafe 端到端回归保留 `ordinary == []`，并新增所有已允许的 compaction request 均 `tools == ()`、`context_gate.hard_safe is True` 的断言。

### 返工验证

- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_application_runs.py tests/test_application_runtime.py tests/test_t09_1_context_protocol_e2e.py tests/test_w05_diagnostics.py tests/test_desktop_bridge.py -q`：`185 passed`，`0 failed`，exit code `0`，`18.46s`。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q`：`23 passed`，`0 failed`，exit code `0`，`5.02s`。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests`：exit code `0`。
- `git diff --check`：exit code `0`；仅报告仓库既有 LF→CRLF warning，无 whitespace error。
- 返工后未执行仓库全量 `pytest -q`、`python -m pip check`、真实 Provider、干净 Windows 或 Desktop `npm` 验收；这些仍未验证，不能描述为通过。未执行 Git 写操作，未触碰 `.workbuddy/`、`临时目录/`，未修改冻结 Spec/Tasks/Prompt 文字。

## 返工第 2 轮（Reviewer 剩余 P1）

### Finding 与修复

- 删除 `generation.py` candidate validator 中 `saturated_boundary` 将 exact count 降级为 local 的条件。现在只有 Provider capability 缺失或受控 count failure 才会把 before/after 两侧统一改用 local accounting；exact count 等于 effective input limit 不再被无依据地降级。
- 新增 `ordinary count=6000`、`compaction` 使用真实 accounting、`context_window=6000`、单个 seed Turn 的窗口边界回归，确认 equal before/after 返回 `no_reduction`，Timeline append 为 0；同步更新 partial hard-unsafe 回归以确认 exact 等大不提交。

### 返工验证

- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_application_runs.py tests/test_application_runtime.py tests/test_t09_1_context_protocol_e2e.py tests/test_w05_diagnostics.py tests/test_desktop_bridge.py -q`：`186 passed`，`0 failed`，exit code `0`，`18.37s`。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q`：`23 passed`，`0 failed`，exit code `0`，`5.51s`。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests`：exit code `0`。
- `conda run --no-capture-output -n re-uthcode python C:\Users\93445\.codex\skills\uth-utf8-guard\scripts\check_utf8_docs.py "docs/work/F03-Context冻结收口与工程收敛及Desktop体验优化/feedback/W02-application-context-usage-feedback.md" "docs/work/F03-Context冻结收口与工程收敛及Desktop体验优化/F03-Context冻结收口与工程收敛及Desktop体验优化-checklist.md"`：`OK: 2 file(s) passed UTF-8 guard`，exit code `0`。
- 追加文档后再次执行 `git diff --check`：exit code `0`；仅有 LF→CRLF warning，无 whitespace error。全量 pytest、pip check、真实 Provider、干净 Windows 与 Desktop npm 验收仍未执行。
