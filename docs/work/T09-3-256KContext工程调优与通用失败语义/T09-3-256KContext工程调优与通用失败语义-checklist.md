# T09-3：256K Context 工程调优与通用失败语义 Checklist

## T01：256K Context limit resolver 与分维安全合同

- [x] 执行 `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_context_budget_gate.py tests/test_application_runs.py tests/test_w05_diagnostics.py tests/test_t09_1_context_protocol_e2e.py -q`，全部通过。
- [x] default-only 场景 effective input 为 `256_000` 且 source/provenance 为 default；该值不出现在 Provider metadata 字段。
- [x] configured-only、provider-only、configured+provider 的有效值与 provenance 符合收紧规则；可靠 Provider ceiling 小于 256K 时不被放大，大于 256K 且无 configured 时仍以 256K Operating Window 工作。
- [x] model/config/provider limits 在 Active Turn 内冻结；同 Turn 中途变化不改变 budget，下一 Turn 重新解析并可观察新 provenance。
- [x] input + allowance、known max output、known combined limit 分别产生通过/拒绝测试；unknown output/combined 保持 unknown，不被 default 伪造。
- [x] status/diagnostics/Headless 可观察 configured/provider/default、effective 与 tightened sources，且不包含秘密、正文或 Provider native object。
- [x] `rg -n "model.?name.*context|context.*model.?name|bundled.*model|model.*catalog" src/uthcode tests` 不存在型号猜测或 bundled model limit authority；命中普通说明时在 Feedback 逐条解释。
- [x] D-T09-3-01、02、03、04 在 T01 实现、测试与 W01 Feedback 中均有证据。

## T02：ContextBudget 收敛与 High Water -> Low Water L4

- [x] 执行 `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_context_budget_gate.py tests/test_context_compaction.py tests/test_t09_1_context_protocol_e2e.py tests/test_application_runs.py -q`，全部通过。
- [x] caller audit 证明 `fine_timeline_budget` 仍驱动 L5、`retained_target` 驱动已启动 Auto L4，保留的其它 profile 字段均有真实生产行为消费者。
- [x] 可控 estimator/fake provider 场景中：初始高于 High；epoch 1 后低于 High 但高于 Low 时继续；epoch 2 达到 Low 后停止，并断言 epoch/provider call/commit 次数。
- [x] Low Water 不在 Auto L4 未触发时主动 compact；High Water trigger 与 Low Water stop target 是两个独立可观察条件。
- [x] max epochs、no progress、no safe epoch、failure、cancel 均有限停止，无伪 checkpoint 或无限循环，最终 ordinary request 继续受 Hard Gate。
- [x] manual compact 低 pressure 可执行且 no candidate/no reduction 为成功 no-op；overflow 仍 exactly one recovery retry；L5 独立 aging 不回归。
- [x] `rg -n "active_evidence_budget|uncompressed_tail_budget|retained_hard_cap" src tests eval docs/context docs/Context-Index.md` 返回 0 条；冻结任务书/历史工作包不属于扫描范围。
- [x] `rg -n "ContextPolicyRegistry|ContextManager|CompactManager|CompactionJob|CompactionScheduler|next_epoch_pointer|COMPACTING_BATCH" src tests` 不存在第二 policy engine、Manager 或持久 compact FSM/job/pointer。
- [x] D-T09-3-05、06 在 T02 实现、显式 High->Low 回归与 W01 Feedback 中均有证据。

## T03：Provider Prefix Cache hints 与可观察 usage

- [ ] W02 Feedback 记录实施时核对的 OpenAI/Anthropic官方文档、当前 SDK 版本/signature 与选择的 wire 参数；无法可靠确认的参数没有发送。
- [ ] 执行 `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_openai_responses_integration.py tests/test_anthropic_integration.py tests/test_openai_compat_integration.py tests/test_w05_diagnostics.py -q`，全部通过。
- [ ] OpenAI Responses request fixture 证明 cache routing/hint 只由稳定 UthCode request facts 派生；相同 stable facts 得到稳定值，真实 instruction/tool change 产生预期变化。
- [ ] Anthropic request fixture 证明 cache control/breakpoint 位于正确 Integration wire boundary，且 system prompt 未复制 Tool Schema。
- [ ] OpenAI-compatible 默认请求未发送 OpenAI Responses 专有缓存字段；如发送任何 cache 字段，测试能指出现有显式 capability/config authority。
- [ ] ordinary conversation growth 与 Timeline compact 不改变 stable instruction/tool prefix；AGENTS/instruction/tool schema 真变化产生 expected invalidation reason。
- [ ] Provider 报告 cache read/write 时 value 与 provenance 为 available；未报告时 status 为 `not_available` 且不是数值 0，派生 ratio 同样不可用。
- [ ] `rg -n "prompt_cache_key|cache_control" src/uthcode/core src/uthcode/interfaces` 返回 0 条；Provider-specific cache wire type 不穿透 Core/Application public contract 或 Interface。
- [ ] tests 使用 fake client/request fixture，执行期间未访问网络、未读取真实 API key。
- [ ] D-T09-3-04、06 在 T03 request shape、架构边界与 W02 Feedback 中均有证据。

## T04：稳定 FailureReason 与 PauseReason 保真

- [ ] 执行 `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_agent_events.py tests/test_agent_loop.py tests/test_application_runs.py tests/test_cli.py tests/test_tui.py tests/test_openai_responses_integration.py tests/test_anthropic_integration.py tests/test_openai_compat_integration.py -q`，全部通过。
- [ ] `FailureReason` 是小而稳定、Provider-independent、JSON-safe 的 machine semantic；认证、可靠 provider request/configuration、invalid response、context unresolvable、稳定 persistence unavailable 与 internal 的现有可辨识链路各有定向测试。
- [ ] `TurnFailed` 与 failed `TurnResult` JSON round-trip 保留 failure reason；successful/cancelled result 没有伪造 failure reason，`TerminationReason` 不被具体错误分类替代。
- [ ] native SDK exception 在 Integration 内转换；Core/Application public contract 与 Interface 不导入 SDK exception 类型或按 HTTP status 猜测。
- [ ] network、rate limit、timeout 的 recoverable 场景仍产生 typed Pause/Retry，不被改成 terminal failure；可可靠区分的 timeout 不再被错误投影为普通 network，取消/恢复与 stale response 回归通过。
- [ ] Application 对同一 FailureReason/PauseReason只生成一套 one-line projection；CLI、TUI、Headless 测试观察到一致语义，Interface 不维护 exception classifier。
- [ ] 注入含假 secret、SDK class name、traceback 和 raw body 的异常后，public event/result/message 均不包含这些内容。
- [ ] `rg -n "isinstance\(.*(OpenAI|Anthropic)|APIStatusError|AuthenticationError|RateLimitError" src/uthcode/interfaces src/uthcode/application` 的命中均不构成 Interface SDK 分类或 Application Provider-native 分类；结果在 Feedback 逐条说明。
- [ ] `rg -n "ErrorManager|ErrorRegistry|FailureManager|FailureRegistry" src tests` 返回 0 条。
- [ ] D-T09-3-07 在 T04 Core contract、Application projection、cross-interface tests 与 W03 Feedback 中均有证据。

## T05：256K profile、cache 与 failure Eval 调优

- [ ] 执行 `conda run --no-capture-output -n re-uthcode python -m pytest tests/eval -q`，全部通过。
- [ ] 从现有 `python -m eval.runner` 手动入口运行离线 T09-3 smoke/profile compare；精确命令、外部 attempt 根与结果写入 W04 Feedback，未访问真实 Provider。
- [ ] 至少三组明显不同的候选进入同一 compatible fingerprint 比较，覆盖 High/Low、fine timeline、L4 budget/epoch、count allowance 等实际参数；报告保留候选配置与 task sample counts。
- [ ] 报告分别标明 deterministic acceptance 与 tuning evidence，且并列输出 correctness、context、exploration、efficiency、stability、safety，不存在 overall/weighted score。
- [ ] 每组可观察 task verifier、tokens、compact count、pre/post usage、post-compact headroom、work distance、rediscovery/repeated exploration、externalization/HistoryRead、cache usage/availability、prefix change/reason 与 failure correctness。
- [ ] compare 对不兼容 code/prompt/model/provider/config/task sample 等共同控制变量拒绝正式 delta；profile id/完整参数作为受控 candidate axis 单独记录，各候选逐任务样本分布一致，未放宽其它 fingerprint；compatible 报告重复生成结果稳定。
- [ ] profile candidate 通过 Eval 私有 seam 注入，没有新增产品 config 字段或扩大公共 `create_application` API。
- [ ] 最终初始工程默认有逐维取舍说明：任务成功与约束不明显退化、compact 不 thrash、post-compact 工作空间充分、重复探索与 cache invalidation 无明显恶化；未把该数值声明为 public API。
- [ ] live Provider cache/latency/billing 未获授权时报告 `NOT VERIFIED (authorization required)` / unavailable；没有读取真实 secret 或发起网络请求。
- [ ] 仓库内只保留版本化 candidate/fixture/汇总证据，不存在 attempt、cache、临时 home/workspace 或第二 benchmark runner。
- [ ] D-T09-3-01、05、06、07 在 T05候选、报告、选择理由与 W04 Feedback 中均有证据。

## T06：[接入主流程] Application 统一投影与正式入口收口

- [ ] 执行 `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_application_runs.py tests/test_w05_diagnostics.py tests/test_t09_1_context_protocol_e2e.py tests/test_cli.py tests/test_tui.py -q`，全部通过。
- [ ] default resolver、frozen profile、High->Low、Provider cache usage 与 FailureReason 都通过 `create_application -> create_run -> start_turn -> AgentLoop` 唯一正式链工作。
- [ ] ordinary、post-tool、post-resume、manual、L4/L5、overflow 的每次真实 model call 均使用同一 frozen request safety/Provider chain，且最终 Hard Gate 证据存在。
- [ ] `/status`、Headless diagnostics 安全表达 limit provenance、effective、High/Low、cache availability/provenance、prefix reason 与 failure fact，不包含 Transcript/summary/Tool Result/secret/native exception。
- [ ] CLI、TUI、Headless 只消费 Application structured reason/message projection；没有独立 Context、cache、failure 编排或 Provider exception switch。
- [ ] bootstrap 只组合现有依赖；`rg -n "ContextManager|CacheManager|ErrorManager|Registry|CompactionJob|CompactionScheduler" src/uthcode/application src/uthcode/interfaces` 的命中不包含本包新增通用机制。
- [ ] 被替代的旧 resolver、High-only stop、重复 presentation/cache helper、过渡 wrapper/export 已删除，且 active Turn 异常/取消后仍释放独占槽位。
- [ ] D-T09-3-02、07 以及 D-T09-3-01～06 的主链接线在 T06 tests 与 W05 Feedback 中有证据。

## T07：[端到端验证] 离线验收、调优报告与文档同步

- [ ] 从正式 Headless/Application 入口完成 default-only、小/大 ceiling、Active Turn freeze、High->Low、finite breaker、manual、overflow、cache hint/invalidation、terminal failure 与 recoverable pause 的离线 E2E。
- [ ] 执行 `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q`，全部通过。
- [ ] 执行 `conda run --no-capture-output -n re-uthcode python -m pytest -q`，精确 passed/failed/skipped 写入 W05 Feedback。
- [ ] 执行 `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests eval`，退出码为 0。
- [ ] 执行 `conda run --no-capture-output -n re-uthcode python -m pip check`，结果为 `No broken requirements found.`。
- [ ] 执行 `git diff --check`，退出码为 0；`git status --short` 中用户开工前已有的 `docs/core-design/T09-context-engineering.md` 删除与 `临时目录/` 未被覆盖、恢复或纳入本包。
- [ ] 使用 `uth-utf8-guard` 检查 T09-3 工作包、`docs/Context-Index.md`、A03/A04 及本包实际修改的其它 Markdown，UTF-8、replacement character、mojibake 和 fence parity 全部通过。
- [ ] `docs/Context-Index.md`、A03/A04 及 `docs/README.md` 维护映射命中的当前文档与最终 `src/ + tests/` 一致；没有修改 T09/T09-1/T09-2 冻结正文、Spec、Tasks、Prompt 或 Checklist。
- [ ] T09-3 Eval 汇总能够回答最终 High/Low 选择、post-compact工作距离、compact/rediscovery/repeated exploration、cache/prefix、质量退化与 unavailable 指标原因。
- [ ] 无授权 live Provider 项明确为未验证；没有把它写成通过或隐藏验收。
- [ ] D-T09-3-01～08 在 Spec、Tasks、W01～W05 Prompt、Checklist 与 Feedback 中逐项可追踪。

## T08：[遗留负担清理] 单一路径与取消路线确认

- [ ] `rg -n "active_evidence_budget|uncompressed_tail_budget|retained_hard_cap" src tests eval docs/context docs/Context-Index.md` 返回 0 条。
- [ ] `rg -n "bundled.*model|model.*catalog|model.?name.*context|context.*model.?name" src/uthcode tests eval docs/context docs/Context-Index.md` 不存在 bundled model metadata、型号猜测或隐式 tuning table；普通文本命中在 Feedback 说明。
- [ ] `rg -n "ContextPolicyRegistry|ContextManager|CompactManager|CompactionJob|CompactionScheduler|CacheManager|CacheRegistry|ErrorManager|ErrorRegistry" src tests eval` 返回 0 条或只有明确非生产文本且逐条解释。
- [ ] `rg -n "prompt_cache_key|cache_control" src/uthcode/core src/uthcode/interfaces` 返回 0 条；Tool Schema仍只有 Tool System authority，Compat 默认不盲发专有参数。
- [ ] Interface 无 Provider/SDK exception classifier；Network/rate-limit/timeout Pause/Retry、Session quarantine、Hard Gate、Permission、Secret 与 unsandboxed Bash 语义无范围外改变。
- [ ] 本包产生但未使用的 profile branch、cache experiment、一次性脚本、重复 helper/export/wrapper、不可达代码和仓库内 Eval 运行产物已删除；用户既有 dirty files 保留。
- [ ] `docs/OutstandingDebtList.md` 已按“能力欠账：无”核对并保持不变；没有把 Out of Scope、未来能力或未授权 live Eval 登记为欠账。
- [ ] 清理后重新执行 T01～T07 的最小定向、`tests/eval`、架构、全量、compileall、pip check、diff check 与 UTF-8 guard，精确结果写入 W05 Feedback。
- [ ] 全部 Checklist 已有真实证据、W01～W05 Feedback 齐全后，`docs/Context-Index.md` 将 T09-3 标为 `implemented_unarchived`；工作包仍留在 `docs/work/`，未执行归档、commit、push、merge、rebase、tag 或 release。
- [ ] D-T09-3-01～08 的最终否定扫描和取消路线验证完整，未弱化任何冻结 MUST。
