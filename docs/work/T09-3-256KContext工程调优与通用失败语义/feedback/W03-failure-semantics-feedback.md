# W03 通用失败语义反馈

## 结论

W03/T04 已按冻结 Prompt 实施完成。实现保持最小混合方案 C：Integration 只把可靠的 SDK/HTTP 事实转换为 UthCode Provider error，Core 产生稳定 `FailureReason` 和保真的 `PauseReason`，Application 提供唯一的一行用户文案，CLI、TUI 和 Headless 消费同一结构化事实与投影。

本次没有修改原始需求、Spec、Tasks、Prompt、Context profile、Low Water、cache wire、Eval runner 或 Git 状态；没有执行 commit、push、merge、rebase、tag、release 或工作包归档。工作区中原有的文档删除和未跟踪文件保持不动。

## 最终语义

### FailureReason

最终枚举保持六项，值均为 Provider-independent、JSON-safe 的 machine semantic：

| 枚举 | 值 | 当前真实证据 |
| --- | --- | --- |
| `AUTHENTICATION` | `authentication` | Integration 的 SDK authentication/permission 事实及 HTTP 401/403 |
| `PROVIDER_REQUEST` | `provider_request` | Core 已有 `ProviderConfigurationError`/`MissingSecretError`，以及 Integration 可靠识别的 HTTP 400/422 request/configuration 事实 |
| `INVALID_PROVIDER_RESPONSE` | `invalid_provider_response` | Integration/Core 已有响应结构校验和 `InvalidProviderResponseError` |
| `CONTEXT_UNRESOLVABLE` | `context_unresolvable` | Context budget/compilation/safety 失败及一次受控 overflow recovery 失败 |
| `PERSISTENCE_UNAVAILABLE` | `persistence_unavailable` | Application 在下一次 Provider 请求前发现 closed Transcript cursor 未能持久化；该事实通过 Core-owned `PersistenceUnavailableError` 传递 |
| `INTERNAL` | `internal` | 未能可靠细分的 Provider/Core/Application 普通异常、Provider generic error 和 Provider error finish |

`FailureReason` 没有镜像 SDK exception、HTTP status、network、rate-limit 或 timeout。policy limit（例如 max iteration/tool/output）继续只由 `TerminationReason` 表达，不伪造具体 failure reason。

### TerminationReason 与 PauseReason

- `TerminationReason` 继续说明 Turn 为什么结束；例如 `PROVIDER_ERROR`、`INVALID_PROVIDER_RESPONSE`、`INTERNAL_ERROR` 的职责没有被 `FailureReason` 替代。
- failed `TurnFailed` 和 failed `TurnResult` 会保留同一 `failure_reason`；successful/cancelled `TurnResult` 明确保持 `None`。
- `NetworkError`、`RateLimitError` 继续产生 `PauseKind.PROVIDER_UNAVAILABLE` 和 Retry continuation。
- Integration 能可靠识别 SDK timeout 时，转换为 Core `ProviderTimeoutError`，Core 保持同一 Pause/Retry 路径并使用新增的 `PauseReason.TIMEOUT`；timeout 没有被 terminalize。
- pause response、continuation、stale response、cancel 和一次 retry 的既有边界未改变。

## 调用链与修改

### Core

- `src/uthcode/core/agent_events.py` 增加 `FailureReason`，并把 `failure_reason` 纳入 `TurnFailed` 的 JSON-safe event contract 和严格反序列化。
- `src/uthcode/core/agent.py` 为 `TurnResult` 增加同一字段和 round-trip；在 request preparation、Provider response、context overflow、generic internal 分支按稳定事实附加 reason；Core 不导入任何 SDK 类型。
- `src/uthcode/core/provider.py` 增加 Provider-independent `ProviderTimeoutError`；`src/uthcode/core/interaction.py` 增加 `PauseReason.TIMEOUT` 并保持 provider pause 的合法组合。
- `src/uthcode/core/__init__.py` 收口 `FailureReason`、`ProviderTimeoutError`、`PersistenceUnavailableError` 等公开导出。

### Integration

以下三个适配器均使用相同的可靠事实映射，native SDK object、SDK exception、traceback 和 raw body 不向上穿透：

- `src/uthcode/integrations/providers/openai_responses.py`
- `src/uthcode/integrations/providers/anthropic.py`
- `src/uthcode/integrations/providers/openai_compat.py`

三者均覆盖 SDK authentication/permission、rate limit、connection、timeout，以及 HTTP 401/403、429、408/504、413、400/422；未能可靠细分的 status/generic error 仍保持 generic Provider error，不假装成更细分类。

### Application

- `src/uthcode/application/generation.py` 在既有职责文件内承载唯一的 `failure_message` / `pause_message` projection；没有新增 ErrorManager、Registry、i18n 平台或第二事件系统。
- 下一次 Provider 请求前的持久化 cursor 失败改为稳定 `PersistenceUnavailableError`，由 Core 映射到 `PERSISTENCE_UNAVAILABLE`；Context compiler/budget/safety facts 映射到 `CONTEXT_UNRESOLVABLE`。
- `src/uthcode/application/__init__.py` 公开统一 projection 和 `FailureReason`。

### Interface / Headless

- `src/uthcode/interfaces/cli.py` 的 Turn failure 和 pause diagnostic 均消费 Application projection；删除了 per-Turn `ProviderError` fallback 和 `TerminationReason` 文案 switch。
- `src/uthcode/interfaces/tui/rendering.py` 将同一 Application failure projection 放入 `RenderBatch`，`src/uthcode/interfaces/tui/app.py` 只展示；TUI pause action 也消费同一 `pause_message`。
- TUI 删除了按异常类名生成的 public message；CLI 启动阶段保留的 ProviderError 处理只负责进程级启动退出边界，不参与 FailureReason 分类，也不读取异常正文。

## 测试与验收证据

以下命令均在 Conda 环境 `re-uthcode` 中执行，fixture 使用 fake/scripted Provider，不访问真实网络或 API key；带 `live` 标记的用例按仓库规则跳过。

### Prompt 要求的最终命令

```text
conda run --no-capture-output -n re-uthcode python -m pytest tests/test_agent_events.py tests/test_agent_loop.py tests/test_application_runs.py tests/test_cli.py tests/test_tui.py tests/test_openai_responses_integration.py tests/test_anthropic_integration.py tests/test_openai_compat_integration.py -q
262 passed, 3 skipped in 28.19s

conda run --no-capture-output -n re-uthcode python -m pytest tests/test_agent_interaction.py tests/test_architecture_boundaries.py -q
81 passed in 5.84s

git diff --check
exit code 0
```

### 补充定向验证

- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_t09_1_context_protocol_e2e.py -q`：`29 passed`。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_agent_policy.py tests/test_package.py tests/test_context_budget_gate.py tests/test_context_compiler.py tests/test_provider_model_limits.py -q`：`94 passed`。
- 三个 Provider integration 定向集合：`46 passed, 3 skipped`。
- `conda run --no-capture-output -n re-uthcode python -m pytest -q`：`1236 passed, 3 skipped in 123.90s`。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests`：通过。
- `rg -n "ErrorManager|ErrorRegistry|FailureManager|FailureRegistry" src tests`：0 条。
- `rg -n "isinstance\(.*(OpenAI|Anthropic)|APIStatusError|AuthenticationError|RateLimitError" src/uthcode/interfaces src/uthcode/application`：0 条；没有 Interface SDK classifier 或 Application Provider-native classifier 命中。

定向测试覆盖了 public event/result JSON round-trip、success/cancel invariant、authentication、configuration/request、invalid response、context compilation、persistence cursor、generic internal、network/rate-limit/timeout Pause/Retry、cancel/resume/stale response、CLI/TUI/Headless projection 以及 SDK class/traceback/raw body/secret leak guard。

## 冻结决策与差异

- D-T09-3-07：已在 Core `FailureReason`、Application 唯一 projection、三类 Interface/Headless 消费和本 Feedback 中形成完整证据链；Integration → Core → Application → Interface 的边界保持不变。
- D-T09-3-08：本 Feedback 与 T04 Checklist 记录了 Prompt、Tasks、源码、测试和扫描之间的追踪；未修改冻结文件。
- 相对冻结任务书没有产品、架构、范围或安全语义差异。为保真 timeout 增加了最小 `ProviderTimeoutError` / `PauseReason.TIMEOUT`；这是 Prompt 已确认的 Pause 扩展，不是新的 terminal failure。
- 没有可靠事实的 generic Provider error 没有被细分；policy limit 没有被强行包装成 `INTERNAL`。
- Hard Gate、ContextBudget/Low Water、Secret boundary、Permission 与 Core/Integration/Interface 架构边界均未弱化；本次只接入既有异常事实到公共失败投影。

## 风险与未验证项

- 未执行真实 Provider/live 网络测试；这符合本 Worker 的离线 fixture 边界，live 用例明确标记为 skipped。
- 未执行 T05 Eval、T06/T07/T08 后续 Worker 的验收；这些不属于 W03 范围。
- 当前工作包仍等待后续 Worker 和用户手动归档；没有更新 `Context-Index.md` 或自行归档。
- 现有工作区在 W03 开始前已有与本任务无关的 `docs/core-design` 变更/未跟踪文档；本次未清理、覆盖或纳入 Git 操作。

## 返工第一轮

- 返工原因：验收发现 `PauseRequest` 已允许 `PauseKind.PROVIDER_UNAVAILABLE` 与 `PauseReason.TIMEOUT`，但 `TurnPausing` 的对应合法 reason 矩阵仍缺少 `TIMEOUT`，导致公共事件构造和 JSON round-trip 被错误拒绝。
- 实际修改文件：
  - `src/uthcode/core/agent_events.py`
  - `tests/test_agent_events.py`
  - 本 Feedback 文件仅在末尾追加本章节。
- 公共事件合同修复：`TurnPausing` 的 provider-unavailable 合法 reason 增加 `PauseReason.TIMEOUT`；新增公共事件测试验证 timeout 事件可构造，`to_dict()` 稳定输出 `provider_unavailable` 与 `timeout`，`to_json()` 经 `agent_event_from_json()` 精确 round-trip，并验证非法 kind/reason 组合仍抛出 `ValueError`。
- 精确验证结果：
  - `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_agent_events.py -q`：`22 passed in 0.82s`。
  - `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_agent_events.py tests/test_agent_loop.py tests/test_application_runs.py tests/test_cli.py tests/test_tui.py tests/test_openai_responses_integration.py tests/test_anthropic_integration.py tests/test_openai_compat_integration.py -q`：`263 passed, 3 skipped in 27.79s`。
  - `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_agent_interaction.py tests/test_architecture_boundaries.py -q`：`81 passed in 5.78s`。
  - `conda run --no-capture-output -n re-uthcode python -m pytest -q`：`1237 passed, 3 skipped in 124.91s (0:02:04)`。
  - `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests`：退出码 `0`，无输出。
  - `git diff --check`：退出码 `0`，无 whitespace error；Git 仅输出工作区 LF/CRLF advisory warnings。
  - `rg -n "ErrorManager|ErrorRegistry|FailureManager|FailureRegistry" src tests`：无命中（rg 原始退出码 `1`）。
  - `rg -n "isinstance\(.*(OpenAI|Anthropic)|APIStatusError|AuthenticationError|RateLimitError" src/uthcode/interfaces src/uthcode/application`：无命中（rg 原始退出码 `1`）。
- 范围确认：`PauseRequest`、`TurnPaused`、continuation、Retry 和既有 timeout Pause/Retry 语义未改动；未修改六项 `FailureReason`、Provider 映射、Application 文案或 Interface 行为；未新增 timeout `FailureReason`，未将 timeout 转为 terminal failure。未实施 T05+，未修改 Eval、Context profile、Low Water、cache wire 或其它冻结内容；未修改 Checklist；未执行 Git commit、push、PR、merge、rebase、tag、release 或归档；`docs/core-design/**` 与 `临时目录/**` 保持原有工作区状态。
