# T09-3：256K Context 工程调优与通用失败语义 Tasks

## Worker 分组、顺序与依赖

| Worker | 执行任务 | 前置 | 写集合与并行边界 |
| --- | --- | --- | --- |
| W01 | T01 -> T02 | 无 | 独占 Core/Application ContextBudget、limit freeze、L4 orchestration 与相关测试 |
| W02 | T03 | W01 | 独占 Provider cache request mapping、usage 投影与 Provider integration tests |
| W03 | T04 | W02 | 独占 Provider error mapping、Core event/result failure contract、Application presentation 与 Interface 消费；Provider files 与 W02 串行 |
| W04 | T05 | W03 | 独占 `eval/`、`tests/eval/` 与离线 tuning artifacts；只消费已完成生产事实 |
| W05 | T06 -> T07 -> T08 | W04 | 独占正式入口收口、跨层验收、当前事实文档、Checklist 与最终清理 |

所有 Worker 严格按依赖顺序由用户显式派发；不得自行提前实施。每个 Worker 必须先完整读取原始任务书、Spec、Tasks、Checklist 和自己的 Prompt，并核对前序 Feedback。首次派发后冻结原始需求、Spec、Tasks、Prompt 和 Checklist 文案；Checklist 只允许把已验证项由 `[ ]` 改为 `[x]`。

## T01：256K Context limit resolver 与分维安全合同

### 任务目标

在现有 ContextBudget/Application request preparation 上补齐 configured/provider/default 三来源解析、provenance 与 Active Turn freeze，使无显式 limit 的 runnable model 能以 256K default 工作，同时保持所有已知小窗口和分维 Hard Gate 安全语义。

### 新增文件

- 无预设；只有现有文件无法承载职责时才新增职责单一的测试文件。

### 修改文件

- `src/uthcode/core/context.py`、`src/uthcode/core/__init__.py`
- `src/uthcode/application/context.py`、`generation.py`、`runs.py`、`configuration.py`（仅真实配置/provenance 调用需要时）
- `src/uthcode/application/commands/builtins.py`（仅 status 消费字段变化需要时）
- `tests/test_context_budget_gate.py`、`test_application_runs.py`、`test_w05_diagnostics.py`、`test_t09_1_context_protocol_e2e.py`
- 其它被真实 public serialization 或 status 调用命中的定向测试

### 删除文件

- 无预设整文件删除；删除“configured/provider 至少一个”硬失败假设及其不可达分支/测试。

### 文件职责及实施内容

- Core value 以最小扩展表达 configured value、provider value、default `256_000`、effective input、active/selected source 和实际收紧来源；default 与 Provider metadata 严格区分。
- 解析规则不得放大任何可靠小 ceiling；无 configured 时 Provider 小于 256K取 Provider、Provider 大于 256K仍取 256K、二者都无时取 default；configured 与 Provider 同时存在时取不扩大任何已知 authority 的安全结果并保留 provenance。
- Application 在 start Turn 所需快照边界冻结 model、Provider limits、effective operating limit 与 provenance；活动期间外部 model/config/metadata 变化只影响下一 Turn。
- 保持现有 input + allowance、known max output、known combined limit 的分维验证；unknown output/combined 继续 unknown。
- diagnostics/status/Headless 投影 provenance，不泄露 secret、Provider native object 或正文。
- 不增加 bundled catalog、model-name substring、Profile Registry 或 Provider metadata 获取逻辑到 Core。

### 依赖任务

- 无。

### 参考资料定位

- 原始任务书 D-T09-3-01～04、G1、7、8、9.1、10～12、15 Task 1、16、19。
- `docs/context/A03-State/State-Context.md`、`A04-Orchestration/Orchestration-Context.md`。
- 当前 `core/context.py`、`application/context.py`、`generation.py`、`runs.py` 与对应 tests。

### 完成边界

从正式 Application/Headless 路径可离线证明 default-only、configured-only、provider-only、configured+provider、小/大 ceiling、unknown dimensions 与 next-Turn re-resolution；不存在固定模型表或 default-as-provider 伪 provenance。

### 冻结决策覆盖

- D-T09-3-01、D-T09-3-02、D-T09-3-03、D-T09-3-04、D-T09-3-08。

## T02：ContextBudget 收敛与 High Water -> Low Water L4

### 任务目标

把 frozen retained target 接入已启动 Auto L4 的真实停止条件，并在同一任务删除经再次 caller audit 确认没有生产行为消费者的 profile 字段及全部残留。

### 新增文件

- 无。

### 修改文件

- `src/uthcode/core/context.py`、`compaction.py`（仅共享 epoch/validation contract 确有需要时）
- `src/uthcode/application/context.py`、`generation.py`
- `tests/test_context_budget_gate.py`、`test_context_compaction.py`、`test_t09_1_context_protocol_e2e.py`、`test_application_runs.py`
- 被 profile diagnostics/serialization 命中的其它定向测试

### 删除文件

- 无预设整文件删除。
- caller audit 后删除无生产消费者的 `active_evidence_budget`、`uncompressed_tail_budget`、`retained_hard_cap` 及其 constructor 派生、validation、serialization、diagnostics、fixtures、tests 和当前事实残留；若最新 HEAD 出现真实生产消费者，按任务书停止删除并在 W01 Feedback 记录该 caller 和产品行为。

### 文件职责及实施内容

- 明确 High Water 只负责触发；Low Water/retained target 只负责已启动 Auto L4 的 catch-up stop condition。
- 使用可控 estimator/fake provider 固化关键回归：初始高于 High；epoch 1 后低于 High 但高于 Low，必须继续；epoch 2 达到或低于 Low，停止。
- 每个 epoch 继续沿用 derive、tool-free Provider request、Hard Gate、validation、checkpoint-last commit、candidate rebuild、recount/re-gate；不引入持久指针或新状态机。
- max epochs、no progress、no safe epoch、failure、cancel 有界停止且无伪 checkpoint；最终 ordinary request 仍受 Hard Gate。
- Manual 不依赖 High，no candidate/no reduction 仍为成功 no-op；Overflow forced reduction 与 exactly-one retry 不改变；L5 继续消费 fine timeline budget。
- 只保留有真实行为消费者的少量 profile 参数；初始具体数值在 T05 Eval 后才能定案。

### 依赖任务

- T01。

### 参考资料定位

- 原始任务书 D-T09-3-05～06、G2～G3、7、9.1、10～11、15 Task 2、16.1、18～20。
- T09-1 T03/T05 Feedback 与当前 `application/generation.py` L4 loop。

### 完成边界

生产 Auto L4 形成真实 High->Low 迟滞，并在有限条件下停止；manual/overflow/L5 回归通过；无消费者字段及其非冻结当前态残留为零，且没有新增第二 policy engine。

### 冻结决策覆盖

- D-T09-3-05、D-T09-3-06、D-T09-3-08。

## T03：Provider Prefix Cache hints 与可观察 usage

### 任务目标

在不污染 Core、不改变 Prompt/Tool authority 的前提下，为 OpenAI Responses 和 Anthropic 接入当前官方支持、当前 SDK 可验证发送的 Provider cache hint/control，并完整回归 OpenAI-compatible 的默认兼容行为和 cache metrics availability。

### 新增文件

- 无预设；必要的 Provider request fixture 放入现有 integration test 文件。

### 修改文件

- `src/uthcode/integrations/providers/openai_responses.py`、`anthropic.py`
- `src/uthcode/integrations/providers/openai_compat.py`、`config.py`（只在已有明确 capability/config fact 确有调用方时修改）
- `src/uthcode/application/provider_usage.py`（只补齐真实 availability/provenance/ratio 需要）
- `tests/test_openai_responses_integration.py`、`test_anthropic_integration.py`、`test_openai_compat_integration.py`
- `tests/test_w05_diagnostics.py`、现有 instruction/context fingerprint tests 与必要 Eval fixtures
- `pyproject.toml` 仅当当前锁定范围内 SDK 确实不支持冻结需求、官方资料证明必须升级且不形成新依赖时修改；升级必须连同三个 Integration 回归。

### 删除文件

- 删除实施过程中被淘汰的 cache experiment 分支、无调用方 capability 开关或重复 request builder；不删除 Tool System authority。

### 文件职责及实施内容

- 开工时以官方 OpenAI/Anthropic文档和当前安装 SDK signature/wire fixture 双重确认参数；无法可靠确认就不得猜测发送，并按 Coding 停止条件记录。
- OpenAI cache routing key/hint 只能从稳定 UthCode request facts 派生；相同 stable instruction/tool facts 得到稳定 hint，真实 instruction/tool schema变化产生 expected invalidation。
- Anthropic cache control 只在 Integration 的 system/tools/messages wire boundary设置官方支持的 breakpoint/automatic control；不得把 tools schema 复制入 system prompt。
- OpenAI-compatible 默认请求 shape不新增 Responses 专有字段；只有现有显式支持事实才发送。
- 普通 conversation growth、Timeline compact 不应改变真正稳定的 instruction/tool prefix；AGENTS/instruction/tool schema 真变化更新 fingerprint/reason。
- `cache_read`/`cache_write` 只有 Provider 实际报告时为 available；缺失保持 `not_available`，派生 ratio 也保持 unavailable。
- 所有测试使用 fake client/request fixture，不访问网络、不读取真实 key。

### 依赖任务

- T02。T01 是缓存稳定 request facts 的直接前置；与 T02 完成后的最终 request shape 一起验收。

### 参考资料定位

- 原始任务书 D-T09-3-06、G4、7、9.2、10～14、15 Task 3、16～17、19～20。
- 当前 `pyproject.toml`、三个 Provider Integration 与 tests、`application/provider_usage.py`。
- 实施时最新官方 OpenAI Responses Prompt Caching 和 Anthropic Prompt Caching 文档。

### 完成边界

OpenAI/Anthropic request fixture 可确定性观察正确 cache hint/control；Compat 默认无专有字段；stable/expected invalidation 与 usage unavailable/available 全部可测；Core 无 Provider cache wire type。

### 冻结决策覆盖

- D-T09-3-06、D-T09-3-08；并保持 D-T09-3-04 的无型号猜测边界。

## T04：稳定 FailureReason 与 PauseReason 保真

### 任务目标

以最小混合方案 C 在现有 Provider error、AgentEvent、TurnResult、Application projection 和 Interface 消费链上保留稳定具体失败原因；不建设错误平台，不改变可恢复 Pause/Retry 产品语义。

### 新增文件

- 无预设；Application 用户文案应放入现有职责文件，只有现有结构无法清晰承载时才新增单一 projection 模块。

### 修改文件

- `src/uthcode/core/provider.py`（仅补可靠、Provider-independent error fact 所需）
- `src/uthcode/core/agent.py`、`agent_events.py`、`core/__init__.py`
- `src/uthcode/application/runs.py`、`generation.py`、`application/__init__.py`
- `src/uthcode/integrations/providers/openai_responses.py`、`anthropic.py`、`openai_compat.py`（只补可靠 SDK/HTTP mapping）
- `src/uthcode/interfaces/cli.py`、`interfaces/tui/**`（只改展示消费，按真实调用方最小修改）
- `tests/test_agent_events.py`、`test_agent_loop.py`、`test_application_runs.py`、`test_cli.py`、`test_tui.py`
- 三个 Provider integration tests 及 Context/persistence failure 的现有定向测试

### 删除文件

- 删除 Interface 内重复 exception classifier、重复用户文案 switch 或旧 opaque failure fallback；不得删除既有 Pause/Retry continuation。

### 文件职责及实施内容

- 定义小而证据驱动的 `FailureReason`，不镜像异常类或 HTTP status；至少覆盖当前可靠事实的 authentication、provider request/configuration、invalid provider response、context unresolvable、稳定 persistence unavailable 与 internal。
- `TurnFailed`、failed `TurnResult` 与 public JSON round-trip 保留 failure reason；successful/cancelled result 不伪造 failure reason，termination reason 不改变原职责。
- Provider SDK 事实在 Integration 转为 UthCode error/fact；Core 不导入 SDK 类型。Context resolver/safety 和 Application persistence 的普通异常在其事实边界映射，不一律折叠为 opaque internal。
- Network/rate-limit/timeout 如当前为 recoverable，继续输出 typed Pause/Retry，并由 Application形成一致可行动文案；timeout 若被折叠为 network且 Integration能从 SDK事实可靠区分，则补最小 Provider-independent error/PauseReason 保真；不得为了展示而 terminalize。
- Application 只有一处稳定 reason -> one-line user-facing message projection；TUI/CLI/Headless 只消费投影与 structured reason。
- public event/result/message不得包含 SDK class、traceback、raw body、secret、endpoint credential 或未经脱敏异常字符串。

### 依赖任务

- T03。T01 提供 Context failure 的稳定事实；T03 与本任务串行修改 Provider Integration，避免重叠写集合。

### 参考资料定位

- 原始任务书 D-T09-3-07、G5、7、8、9.3、10～13、15 Task 4、16、19～20。
- `core/provider.py` error hierarchy、`core/agent.py` Provider exception branches、`agent_events.py` terminal events、`application/runs.py`、CLI/TUI projections。

### 完成边界

认证、可靠 configuration/request、invalid response、Context unresolvable、稳定 persistence 与 internal failure 能跨 Integration/Core/Application/public event/result 保真；Network/rate-limit/timeout 的既有 pause/retry 不回归；所有 Interface 共享 Application 文案且无敏感细节。

### 冻结决策覆盖

- D-T09-3-07、D-T09-3-08。

## T05：256K profile、cache 与 failure Eval 调优

### 任务目标

复用 B01 的任务、runner、fingerprint、六维 metrics、reporting 和 compare，建立完全离线可重复的 256K profile/cache/failure 调优证据，并选出一组 T09-3 初始工程默认。

### 新增文件

- `eval/` 现有布局下职责单一的 T09-3 profile candidate/fixture/report artifact 定义（具体文件名按现有合同选择）
- `tests/eval/` 下对应 deterministic runner/reporting tests
- T09-3 离线 Eval 结果 Markdown/JSON；产物位置必须符合 B01 仓库外运行边界，仓库内只保留版本化、可审查的汇总报告与候选定义。

### 修改文件

- `eval/models.py`、`runner.py`、`execution.py`（仅 candidate metadata/fingerprint/安全运行需要）
- `eval/metrics.py`、`reporting.py`、`README.md`
- 现有 `eval/tasks/` 中最匹配的 long-context/long-task fixture，或新增最小 256K workload fixture
- `tests/eval/test_eval_execution.py`、`test_eval_reporting.py`、`test_eval_runner.py`、`test_eval_verifiers.py`
- T01/T02 的 profile 默认生产值只在完成候选比较后按证据定点修改，并重跑其 contract tests

### 删除文件

- 删除未入选且不属于版本化候选/报告证据的临时参数、重复 runner、一次性脚本和仓库内 attempt/cache/home/workspace。

### 文件职责及实施内容

- 固定代码、Prompt、model/provider/config/task sample counts 等共同控制变量继续使用严格 compatibility fingerprint；profile id 与完整参数作为受控 candidate variant axis 单独记录并验证，不把候选差异本身视为不兼容，也不放宽其它指纹。
- 至少三组有明显差异的候选覆盖 High Water、Low Water、fine timeline、L4 input/output、max epochs、count allowance 及任务书允许的相关配比；先粗筛，必要时围绕优胜区细调。
- deterministic fixture 明确证明 High->Low、cache stable/expected invalidation、failure reason correctness；概率性/模拟 workload 报告与 deterministic acceptance 分栏。
- 逐维报告 correctness、context、exploration、efficiency、stability、safety；附 compact count、pre/post usage、post-compact headroom、work distance、rediscovery/repeated exploration、externalization/HistoryRead、cache read/write/ratio availability、prefix change、failure correctness。
- 每个候选必须使用相同任务与逐任务样本分布；选择不得只按 token 最少。任务成功、约束保留、compact thrash、连续工作空间、重复探索和 cache reuse 共同解释，且不生成 overall score。
- candidate 注入使用 Eval 私有、可替换 seam，不把 tuning参数加入产品 config 或公共 `create_application` API；若只能通过扩大公共 API 实现，按任务书停止并报告。
- 真实 Provider cache/latency/billing 默认拒绝；未授权时报告 unavailable/`NOT VERIFIED (authorization required)`，不请求 secret。

### 依赖任务

- T04；生产链 T01～T04 全部完成。

### 参考资料定位

- 原始任务书 D-T09-3-01、06～08、G6、15 Task 5、16～17、19.2。
- `docs/work/B01-私有测试集v0/` Spec/Tasks/Prompt/Feedback 与当前 `eval/`、`tests/eval/`。

### 完成边界

可通过现有 Eval 正式手动入口完全离线重放至少三组 compatible candidate，产出逐维比较并选定一组初始工程默认；不存在第二 benchmark runtime、总分或未经授权的 live call。

### 冻结决策覆盖

- D-T09-3-01、D-T09-3-05、D-T09-3-06、D-T09-3-07、D-T09-3-08。

## T06：[接入主流程] Application 统一投影与正式入口收口

### 任务目标

将 T01～T05 的 resolver、profile、Low Water、cache usage 与 failure projection 收口到唯一 Application/Run/Turn 调用链及全部 Interface 消费边界，删除任何被替代的重复入口。

### 新增文件

- 无预设。

### 修改文件

- `src/uthcode/application/generation.py`、`context.py`、`runs.py`、`bootstrap.py`、`provider_usage.py`、`application/__init__.py`
- `src/uthcode/application/commands/builtins.py` 与 status/command tests
- `src/uthcode/interfaces/cli.py`、`interfaces/tui/**` 及其 tests（只做展示消费）
- `tests/test_application_runs.py`、`test_w05_diagnostics.py`、`test_cli.py`、`test_tui.py`、`test_t09_1_context_protocol_e2e.py`

### 删除文件

- 删除重复 Context resolver、旧 L4 stop branch、Interface exception switch、重复 cache hint/presentation helper、无调用方导出和过渡 wrapper。

### 文件职责及实施内容

- 证明 ordinary、post-tool、post-resume、manual、L4/L5 与 overflow 仍使用同一 frozen request safety/Provider chain。
- status/Headless diagnostics 同时安全表达 configured/provider/default provenance、effective limit、High/Low profile、cache availability/provenance、prefix reason 与 public failure fact。
- TUI/CLI/Headless 对同一 failure/pause reason得到同一 Application projection；Interface 不导入 Core/Integration/SDK做分类。
- bootstrap 只组合现有具体依赖；不新增 Cache/Error/Context Manager、Registry、FSM 或 hook layer。
- 取消/异常/未知 durability 继续释放 active Turn并遵守 Session/Hard Gate 边界。

### 依赖任务

- T05。

### 参考资料定位

- 原始任务书 G1～G7、7～13、15 Task 6、19。
- A03/A04 当前正式调用链与相关 Application/Interface tests。

### 完成边界

唯一正式入口完整消费所有新事实，Interface 只有展示职责，旧入口和双轨逻辑为零。

### 冻结决策覆盖

- D-T09-3-02、D-T09-3-07、D-T09-3-08，并验证 D-T09-3-01～06 的正式接线。

## T07：[端到端验证] 离线验收、调优报告与文档同步

### 任务目标

从真实 Application/Headless 与 Interface 展示入口完成 deterministic、Eval、架构和全量验收，并按当前代码事实同步全部命中文档。

### 新增文件

- `docs/work/T09-3-256KContext工程调优与通用失败语义/feedback/W05-delivery-regression-cleanup-feedback.md`（由 W05 首次实施创建）。

### 修改文件

- `docs/Context-Index.md`
- `docs/context/A03-State/State-Context.md`、`A04-Orchestration/Orchestration-Context.md`
- `docs/README.md` 维护映射实际命中的用户手册、Core Design、Tools 或根 README；只按当前存在文件与用户开工时改动处理，不擅自恢复用户删除文件
- `eval/README.md` 与 T09-3 版本化汇总报告
- `tests/`、`eval/` 与生产文件只允许验收发现的当前范围内必要修正
- T09-3 Checklist 只勾选已验证项；W01～W04 Feedback 只读取，不覆盖

### 删除文件

- 删除当前事实文档中的旧两来源-only、High-only stop、opaque failure 或 Provider-default-only cache 描述；不修改冻结工作包正文。

### 文件职责及实施内容

- 运行 default-only、小/大 ceiling、provenance/freeze、分维 Hard Gate、High->Low、finite breakers、manual/overflow/L5、cache hints/metrics/invalidation、FailureReason/PauseReason、cross-interface、secret-safe projection 的最小定向集合。
- 运行 `tests/eval`、离线 profile compare、架构测试、全量 pytest、compileall、pip check、git diff check 与 UTF-8 guard。
- 核对所有任务包 Checklist 和 W01～W05 Feedback；记录每条实际命令、精确 passed/failed/skipped、未运行项、风险与任务书差异。
- 更新 A03/A04 与索引为当前实现事实；只有 T08 清理后所有 Checklist 与 Feedback 完整才把 T09-3 从 `not_implemented` 改为 `implemented_unarchived`。
- live Provider 项没有授权时明确记为未验证，不阻断离线 acceptance，也不读取环境 secret。

### 依赖任务

- T06。

### 参考资料定位

- 原始任务书 G6～G7、15 Task 6、16～19、23；`docs/README.md` 文档维护映射。

### 完成边界

离线 deterministic 与 tuning 证据、正式入口、文档和全量回归均可复审；任何未运行 live 项被准确标注，不伪造通过。

### 冻结决策覆盖

- D-T09-3-01～D-T09-3-08 全部端到端验收。

## T08：[遗留负担清理] 单一路径与取消路线确认

### 任务目标

在 T07 验收基础上清除本包范围内所有旧字段、重复职责、提前抽象、兼容层和临时产物，完成索引与欠账最终核对。

### 新增文件

- 无。

### 修改文件

- 按调用图与否定扫描定点修改/删除 `src/`、`tests/`、`eval/` 和当前事实 `docs/` 中已确认的遗留负担。
- `docs/OutstandingDebtList.md` 只有发现真实新增/变更/回补时才修改；按本包冻结结论应保持不变。
- `docs/Context-Index.md` 在全部证据齐全后更新 T09-3 状态与日期；不得移动工作包。
- 完成并最终收敛 `feedback/W05-delivery-regression-cleanup-feedback.md`。

### 删除文件

- 删除 T01～T07 范围内确认无调用方的旧字段、实验分支、重复 helper/export/wrapper、不可达测试和仓库内 Eval 运行产物；不预设删除用户文件或整份当前文档。

### 文件职责及实施内容

- 扫描并证明 `active_evidence_budget`、`uncompressed_tail_budget`、`retained_hard_cap` 在生产、测试、Eval 与当前事实文档无残留；冻结历史正文允许作为历史证据存在。
- 证明不存在 bundled model catalog/name guessing、ContextPolicyRegistry/Manager、CompactManager/Job/Scheduler、CacheManager/Registry、ErrorManager/Registry、Provider cache wire type进入 Core。
- 证明 Interface 无 exception/provider classifier，Tool Schema未复制，Compat 默认无专有 cache hint，Pause/Retry 语义仍在。
- 删除本包产生但未使用的 profile candidates runtime branch、临时脚本、缓存、attempt、home/workspace、重复 helper/export/wrapper 与不可达测试。
- 保护用户开工前已有 dirty worktree；不清理 `临时目录/` 或恢复用户删除的文档。
- 清理后重跑最小定向、Eval、架构、全量、compileall、pip check、diff check、UTF-8 guard；精确结果写入 Feedback。

### 依赖任务

- T07。

### 参考资料定位

- 原始任务书 18～23；AGENTS.md 工程收敛与缓存边界；`docs/OutstandingDebtList.md`。

### 完成边界

仓库只保留当前需求的单一生产路径和版本化 Eval 证据；无兼容层、未来占位、冻结文档回写或仓库内运行产物；索引为 `implemented_unarchived`，等待用户手动归档。

### 冻结决策覆盖

- D-T09-3-04、D-T09-3-08，并对 D-T09-3-01～07 做取消路线与遗留负担否定验证。

## 冻结决策下游覆盖矩阵

| Frozen Decision | Spec | Tasks | Worker Prompt | Checklist |
| --- | --- | --- | --- | --- |
| D-T09-3-01 | T01/T05 | T01/T05/T07 | W01/W04/W05 | T01/T05/T07 |
| D-T09-3-02 | T01/T06 | T01/T06/T07 | W01/W05 | T01/T06/T07 |
| D-T09-3-03 | T01 | T01/T07/T08 | W01/W05 | T01/T07/T08 |
| D-T09-3-04 | T01/T08 | T01/T03/T08 | W01/W02/W05 | T01/T03/T08 |
| D-T09-3-05 | T02 | T02/T07 | W01/W05 | T02/T07 |
| D-T09-3-06 | T05 | T02/T03/T05/T07 | W01/W02/W04/W05 | T02/T03/T05/T07 |
| D-T09-3-07 | T04/T06 | T04/T06/T07 | W03/W05 | T04/T06/T07 |
| D-T09-3-08 | T01～T08 | T01～T08/本矩阵 | W01～W05 | T01～T08/追踪检查 |
