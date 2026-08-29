# W05 交付回归、主链收口与清理反馈

## 结论

W05/T06→T07→T08 已按冻结 Prompt 执行完成。当前源码不需要新增生产代码或扩大架构范围：正式入口已经收敛为 `create_application -> create_run -> start_turn -> AgentLoop`，Application 统一组合 Context Budget、Request Safety、Provider Usage、FailureReason/PauseReason 和 diagnostics；CLI、TUI、Headless 只消费 Application 的结构化事件与文案投影。

T09-3 的 T01～T08 Checklist 已有真实测试、入口、负面扫描、文档和本 Feedback 证据。`docs/Context-Index.md` 已将 T09-3 更新为 `implemented_unarchived`；工作包仍保留在 `docs/work/`，没有执行归档或任何 Git 写操作。

真实 Provider 的 cache 命中、远端 tokenizer、latency、billing 和 live 长上下文质量仍为 `NOT VERIFIED (authorization required)`。本轮没有读取真实 API key、没有发送网络请求、没有执行 `--live`。

## 主链与实现审计

- `create_application` 仍是唯一 composition root；`create_run` 创建隔离的 `AgentRun`；`start_turn` 只通过 Application 的 `_start_agent_turn` 建立正式 `AgentLoop` 和 `_TurnDriver`。
- Active Turn 在第一次请求准备时解析并冻结 Provider limits、Model Profile、ContextBudget、ToolDefinition 顺序和 request preparer；同一 Turn 的普通请求、Tool continuation、resume、manual Compact、L4/L5 和 overflow recovery 都复用同一 Application Context/Hard Gate 路径，下一 Turn 才重新解析 limits。
- 没有 configured `context_window` 时，`ContextBudget` 使用 `256_000` default input Operating Window；可靠 Provider `max_input_tokens` 只能收紧它。`max_output_tokens`、combined limit、input allowance 分维进入 Hard Gate，diagnostics 保留 configured/provider/default/effective、provenance 和 tightened sources。
- `FailureReason` 保持六个稳定的 Provider-independent machine semantics：`authentication`、`provider_request`、`invalid_provider_response`、`context_unresolvable`、`persistence_unavailable`、`internal`。Application 的 `failure_message()` 与 `pause_message()` 是唯一安全文案投影；CLI/TUI 未建立 exception classifier。
- Provider-specific `prompt_cache_key`/`cache_control` 只存在于对应 Integration；Application diagnostics 只在明确的 Usage 字段存在时标记 cache read/write 为 available，否则保留 `not_available`，不把缺测写成数值零。
- 审计未发现当前范围内的真实生产缺陷，因此没有修改 `src/`、`tests/` 或新增 resolver/manager/registry/FSM/wrapper。普通测试失败修复边界没有被触发。

## 文档同步

按 `docs/README.md` 维护映射，更新了以下当前事实与使用文档：

- `README.md`：补充默认 256K Operating Window、收紧规则和 Application diagnostics 入口。
- `docs/Context-Index.md`：更新状态快照为 2026-08-27，将 T09-3 移至 `implemented_unarchived`，补充默认预算、provenance、缓存与失败投影事实。
- `docs/context/A01-AgentRuntime/AgentRuntime-Context.md`：补充 ContextBudget/Provider limits 的 Turn freeze、256K default、FailureReason/Application 投影事实。
- `docs/context/A02-Control/Control-Context.md`：更正 typed pause kind 与 network/rate-limit/timeout PauseReason 的当前事实。
- `docs/context/A03-State/State-Context.md`：补充 FailureReason JSON 投影、预算 provenance、Active Turn freeze 和 cache availability 事实。
- `docs/context/A04-Orchestration/Orchestration-Context.md`：补充统一 budget/request 入口、Eval diagnostics 和 CLI 文案投影事实。
- `docs/user-manual/configuration.md`、`docs/user-manual/commands.md`、`docs/user-manual/getting-started.md`：同步默认预算、`/status` 可观察字段及使用说明。

未恢复或覆盖开工前已有的 dirty files：

```text
 D docs/core-design/T09-context-engineering.md
?? docs/core-design/A01-AgentRuntime/03-系统指令权威链路.md
?? docs/core-design/A01-AgentRuntime/assets/03-系统指令权威链路-编译流.png
?? 临时目录/
```

没有修改 T09/T09-1/T09-2 冻结正文、Spec、Tasks、Prompt 或 Checklist 文字；没有修改 `docs/OutstandingDebtList.md`。核对结果仍为 T09-3 能力欠账无。

## 定向与全量验证

全部命令均在 `re-uthcode` Conda 环境执行：

```text
conda run --no-capture-output -n re-uthcode python -m pytest tests/test_context_budget_gate.py tests/test_context_compaction.py tests/test_t09_1_context_protocol_e2e.py tests/test_application_runs.py tests/test_w05_diagnostics.py -q
135 passed in 18.70s

conda run --no-capture-output -n re-uthcode python -m pytest tests/test_openai_responses_integration.py tests/test_anthropic_integration.py tests/test_openai_compat_integration.py tests/test_agent_events.py tests/test_agent_loop.py tests/test_cli.py tests/test_tui.py -q
217 passed, 3 skipped in 22.92s

conda run --no-capture-output -n re-uthcode python -m pytest tests/eval -q
87 passed in 85.68s

conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q
23 passed in 4.98s

conda run --no-capture-output -n re-uthcode python -m pytest -q
1247 passed, 3 skipped in 159.97s (0:02:39)

conda run --no-capture-output -n re-uthcode python -m compileall -q src tests eval
exit 0

conda run --no-capture-output -n re-uthcode python -m pip check
No broken requirements found.

git diff --check
exit 0
```

定向组覆盖 default-only/small-large ceiling、configured/provider provenance、Active Turn freeze、High→Low、finite L4、manual no-op、L5、overflow、cache usage、terminal failure、recoverable pause、Session persistence 和 cross-interface projection。全量结果包含上述路径的回归。

## 正式 Headless/Application 与 Eval 入口

应用级离线 E2E 由 `tests/test_application_runs.py`、`tests/test_w05_diagnostics.py`、`tests/test_t09_1_context_protocol_e2e.py`、`tests/test_cli.py` 和 `tests/test_tui.py` 通过正式 Application/Run/Turn 入口执行；没有绕过 Application 直接拼 Provider 请求。

另外执行了当前 `eval.runner` 入口：

- `python -m eval.runner --help` 返回 0，展示 `smoke/run/profile/compare/clean`；`profile --help` 返回 0，展示 `production-default`、`balanced-208k`、`compact-224k` 和完整 profile 参数。
- `profile --candidate balanced-208k --experiment t09-3-w05-e2e-balanced --eval-root D:\project\Re-UthCode-Eval-T09-3 --attempts 1 --prompt-salt t09-3-w05-e2e --model eval-model` 返回 0。外部报告为 `reports/t09-3-w05-e2e-balanced/report.json`，`sample_count=1`、`finish_categories={"success":1}`、`compact_count=1`、`pre_compact_usage=268192`、`post_compact_usage=90632`、`post_compact_headroom=165368`、`candidate=balanced-208k`；cache 为 `not_available`，原因是 offline Fake Provider 没有 cache telemetry。
- `smoke --task single-file-control --experiment t09-3-w05-smoke ... --model eval-model` 返回 0 并产生预期的 `agent_failure`（Fake smoke 未注入标准答案）；随后通过 manifest-owned `clean` 精确清理该 attempt，报告保留在外部 reports 目录。
- 对已有 compatible 的 `t09-3-w04-v5-balanced` 与 `t09-3-w04-v5-repeat-balanced` 执行 `compare`：`compatible=true`、`incompatibilities=[]`、delta 非空，candidate axis 和六维结果保留，cache/HistoryRead 缺测原因保留。
- 对仓库根执行 `clean --eval-root D:\project\Re-UthCode ...` 被拒绝，当前命令返回 exit 1，错误为 `eval runner error: clean requires a dedicated Eval root`；没有触碰仓库。W05 新增的两个外部 attempt 的 workspace/home/artifacts 内容已清理，reports 保留。

## 最终否定扫描

以下扫描均在当前 `src`、`tests`、`eval` 和命中范围执行：

- `active_evidence_budget|uncompressed_tail_budget|retained_hard_cap`：0 条。
- `ContextPolicyRegistry|ContextManager|CompactManager|CompactionJob|CompactionScheduler|CacheManager|CacheRegistry|ErrorManager|ErrorRegistry`：0 条。
- `prompt_cache_key|cache_control` 在 `src/uthcode/core` 与 `src/uthcode/interfaces`：0 条。
- `ErrorManager|ErrorRegistry|FailureManager|FailureRegistry`：0 条。
- Interface/Application SDK exception classifier 扫描：0 条。
- `bundled.*model|model.*catalog|model.?name.*context|context.*model.?name` 只有配置模型候选目录的普通命中：`configuration.py`/`generation.py` 提供已配置 `ModelProfile`，`commands/builtins.py` 和 TUI 只用于模型 Picker/命令 completion，相关测试验证候选读取；没有 bundled model metadata、型号名称推断或 Context limit authority。

## Traceability 与边界

- D-T09-3-01：`ContextBudget` 的 256K default、configured/provider 收紧、provenance、Active Turn freeze；对应 T01/W01，T06 定向测试与本 Feedback。
- D-T09-3-02：Provider/config/default 来源和唯一 Application 请求链；对应 T01/T06 主链审计与 Application E2E。
- D-T09-3-03：input/output/combined 分维 Hard Gate；对应 T01/T02 定向测试和全量回归。
- D-T09-3-04：无 model catalog/型号猜测 authority；对应 T01、T05 Eval candidate axis、T08 扫描与本 Feedback 解释。
- D-T09-3-05：High→Low、finite L4/L5、manual/overflow；对应 T02、T06/T07 正式入口和 compaction E2E。
- D-T09-3-06：Eval profile candidate、兼容 compare、cache/prefix 与 unavailable facts；对应 T05/W04、T07 runner/compare 入口和 reports。
- D-T09-3-07：六类 FailureReason、PauseReason、Application 文案、cross-interface 安全投影；对应 T04/W03、T06 定向测试和负面扫描。
- D-T09-3-08：Spec → Tasks → W01～W05 Prompt → Checklist → Feedback → tests/eval/docs 的最终追踪；T09-3 状态已写入 Context-Index，但未归档。

## UTF-8 guard

本轮使用 `uth-utf8-guard` 检查 T09-3 工作包、`docs/Context-Index.md`、A01～A04 当前 Context、TUI Context、用户手册、根 README 以及本 Feedback；最终命令与结果见交付汇总。检查内容包括 UTF-8 解码、replacement character、常见 mojibake 和 Markdown fence parity。

## 清理后复跑追加记录（2026-08-27）

按 Checklist 要求，在 W05 外部 Eval attempt 的 workspace/home/artifacts 清理完成后重新执行 T01～T07 最小定向、Eval、架构、全量和工具链检查：

```text
conda run --no-capture-output -n re-uthcode python -m pytest tests/test_context_budget_gate.py tests/test_context_compaction.py tests/test_t09_1_context_protocol_e2e.py tests/test_application_runs.py tests/test_w05_diagnostics.py -q
135 passed in 18.03s

conda run --no-capture-output -n re-uthcode python -m pytest tests/test_openai_responses_integration.py tests/test_anthropic_integration.py tests/test_openai_compat_integration.py tests/test_agent_events.py tests/test_agent_loop.py tests/test_cli.py tests/test_tui.py -q
217 passed, 3 skipped in 28.05s

conda run --no-capture-output -n re-uthcode python -m pytest tests/eval -q
87 passed in 156.85s (0:02:36)

conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q
23 passed in 8.14s

conda run --no-capture-output -n re-uthcode python -m pytest -q
1247 passed, 3 skipped in 273.82s (0:04:33)

conda run --no-capture-output -n re-uthcode python -m compileall -q src tests eval
exit 0

conda run --no-capture-output -n re-uthcode python -m pip check
No broken requirements found.

git diff --check
exit 0
```

复跑期间未修改生产源码；结果确认清理步骤没有引入回归。最终 UTF-8 guard、Checklist 勾选后的差异和工作区状态在本反馈之后的交付核验中记录。

## 最终文档与状态核验追加记录（2026-08-27）

- `uth-utf8-guard` 最终检查 27 个文件，结果为 `OK: 27 file(s) passed UTF-8 guard`；UTF-8、replacement character、常见 mojibake 和 Markdown fence parity 全部通过。
- Checklist 最终为 `checked=77`、`unchecked=0`；仅把 T06～T08 的 checkbox 从 `[ ]` 改为 `[x]`，没有改写条目文字或顺序。
- 最终 `git diff --check` 返回 exit 0。Windows `core.autocrlf` 对原有 LF 风格 Checklist 输出换行提示，但不存在 whitespace error。
- 最终 `git status --short` 只包含本 Feedback、Checklist、已映射文档修改，以及开工前已有的 `docs/core-design/T09-context-engineering.md` 删除、A01 新文档/图片和 `临时目录/`；`src/`、`tests/` 没有本轮变更。

## 返工追加：关闭包级 P1，将 selected profile 接入正式生产链（2026-08-27）

### 原因与实际变更

包级审核发现 W04 选定的 `balanced-208k` 尚未成为生产 256K 默认：生产 resolver 仍生成历史的 High `243200`、Low `72000`、working headroom `12800`、compaction output `4000`、count allowance `0`。本轮只处理该实施遗漏，不改变冻结 Spec/Tasks/Prompt/Checklist，不新增产品配置字段、公共 `create_application` API、Manager/Registry/兼容层，不扩大 Provider/cache/failure 语义，也没有触碰用户既有 `docs/core-design/**` 删除/新增文件或 `临时目录/**`。

- `src/uthcode/core/context.py` 的正式 `ContextBudget` resolver 在 effective input `256_000` 时采用 `balanced-208k`：High `208_000`、retained/Low `96_000`、working headroom `48_000`、fine timeline `16_000`、compaction input/output `64_000/4_096`、count allowance `8_192`；Application L4 的既有 epoch 上限 `4` 与该 profile 一致。
- 对 effective input 小于或大于 `256_000` 的 configured/provider 窗口，保留原有有界自适应派生；不会把 256K profile 参数写入更小 effective window。Provider `max_output_tokens`、combined limit、input/output/combined Hard Gate、Active Turn freeze、manual/L4/L5/overflow 均未改写。
- `tests/test_context_budget_gate.py` 新增 Core 精确默认、正式 Application Turn request/diagnostics 精确默认及收紧窗口合法性覆盖；`tests/test_t09_1_context_protocol_e2e.py` 只调整 High→Low fake provider 的低水位计数以计入新的 budget safety allowance，仍验证 epoch 1 低于 High 但高于 Low 时继续、epoch 2 到 Low 后停止。
- `eval/t09-3-256k-profile-tuning-summary.md` 与 `eval/README.md` 已把旧 `production-default` 说明限定为历史比较 baseline，并记录 balanced 已接入生产；A01/A03/A04 与 `docs/Context-Index.md` 已同步当前事实。W04/W05 Feedback 均按规则在原文件末尾追加本返工记录。

### 返工验证

- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_context_budget_gate.py tests/test_context_compaction.py tests/test_t09_1_context_protocol_e2e.py tests/test_application_runs.py tests/test_w05_diagnostics.py -q`：`139 passed`。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/eval -q`：`87 passed in 121.82s`。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q`：`23 passed`。
- `conda run --no-capture-output -n re-uthcode python -m pytest -q`：`1251 passed, 3 skipped in 232.37s`。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests eval`：exit `0`、无输出。
- `conda run --no-capture-output -n re-uthcode python -m pip check`：`No broken requirements found.`
- `git diff --check`：exit `0`；仅有 Windows `core.autocrlf` LF→CRLF 提示，无 diff error。
- `uth-utf8-guard`：待本轮所有 Markdown 修改完成后，对本轮修改 Markdown 统一执行；结果记录在本 Feedback 后续交付检查中。

真实 Provider/cache/latency/billing、远端 tokenizer、远端长上下文和费用仍未授权验证；本轮未读取 API key、未联网、未执行 Git commit/push/merge/rebase/tag/release 或工作包归档。用户既有 dirty files 保持原样。

## 返工验证补充：文档编码检查（2026-08-27）

执行：`conda run --no-capture-output -n re-uthcode python C:\Users\93445\.codex\skills\uth-utf8-guard\scripts\check_utf8_docs.py eval\README.md eval\t09-3-256k-profile-tuning-summary.md docs\Context-Index.md docs\context\A01-AgentRuntime\AgentRuntime-Context.md docs\context\A03-State\State-Context.md docs\context\A04-Orchestration\Orchestration-Context.md docs\work\T09-3-256KContext工程调优与通用失败语义\feedback\W04-256k-eval-tuning-feedback.md docs\work\T09-3-256KContext工程调优与通用失败语义\feedback\W05-delivery-regression-cleanup-feedback.md`

结果：`OK: 8 file(s) passed UTF-8 guard`；UTF-8、replacement character、常见 mojibake 与 Markdown fence parity 全部通过。此前“待检查”记录对应本节最终结果。
