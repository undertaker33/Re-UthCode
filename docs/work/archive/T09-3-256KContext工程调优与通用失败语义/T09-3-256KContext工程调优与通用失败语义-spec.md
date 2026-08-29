# T09-3：256K Context 工程调优与通用失败语义 Spec

## 背景

T09、T09-1 与 T09-2 已建立并收敛 Prompt、Context Compiler、动态 Context Gate、Transcript/Timeline、Tool Result 外置、L4/L5、manual compact、overflow recovery、Session v3 与离线 Eval。当前剩余问题不是缺少新的 Context 架构，而是已有能力尚未以 256K 默认 Operating Window 形成统一可运行、可调优、可解释的工程闭环：缺少 default limit authority 与完整 provenance；Auto L4 在降到 High Water 以下后可能过早停止；Provider prompt cache 尚未主动使用稳定前缀；具体失败原因在公共事件和结果边界被折叠。

本包以冻结任务书和当前 `src/ + tests/` 为 authority，在既有模块化单体与唯一正式运行链内完成校正、调优、失败语义保真和离线验收，不恢复 T09-2 已删除的提前抽象。

## 目标

- 建立 configured、reliable Provider ceiling、UthCode default `256_000` 三来源 Context limit resolver，保留 provenance，并在 Active Turn 冻结解析结果。
- 保持 input、output、combined 三个真实维度的 Hard Gate；未知维度保持 unknown，不维护 bundled model metadata 或名称猜测表。
- 审计并删除没有生产消费者的 ContextBudget 字段；让 retained target 成为 Auto L4 启动后的 Low Water 停止目标。
- 保持 Auto、Manual、Overflow 的不同启动语义，同时收敛必要的 compact epoch、commit、rebuild、recount 和有界停止行为。
- 在 Provider Integration 内基于稳定 UthCode request facts 发送当前官方支持的缓存 hint/control，并延续 cache usage 的 availability 与 provenance 诊断。
- 在 Core 公共失败边界保留小而稳定的 `FailureReason`，由 Application 统一投影自然语言文案，Interface 只展示。
- 复用 B01 Eval，以至少三组明显不同的 256K profile candidate 完成离线粗筛与必要细调；六维指标并列展示，不生成总分。
- 同步当前事实文档、索引与 Feedback；默认不执行真实 Provider、费用调用或秘密读取。

## 能力清单

### T01：256K Context limit resolver 与分维安全合同

- UthCode default Operating Window 为 `256_000` input tokens，不声明模型物理窗口。
- configured、reliable Provider input ceiling 与 default 三来源按冻结规则解析；显式 configured 存在时 default 不参与收紧，configured 可高于 256K但仍受更小 Provider ceiling 约束；configured 缺失时 default 才作为 256K operating cap，Provider ceiling 只能收紧，default 不伪装成 Provider metadata。
- provenance 表达 configured/provider/default、effective input limit、active source 与实际收紧来源，并进入安全 diagnostics/status/Headless。
- Active Turn 冻结 model、Provider limits、effective limit 与 provenance；model switch 或下一 Turn 重新解析。
- Hard Gate 继续分别验证 input、known output 与 known combined limit；未知维度不补造。

### T02：ContextBudget 收敛与 High Water -> Low Water L4

- 快速审计 retained profile 字段；无生产行为消费者的字段从生产模型、序列化、diagnostics、测试与当前事实文档删除，不为其创造调用方。
- 保留并调优有真实消费者的 fine timeline budget、retained target、compaction input/output safety、finite epoch 与 count allowance。
- Auto L4 只由 High/Hard pressure 启动；一旦启动，即使一次 epoch 后已低于 High Water，只要仍高于 Low Water 就继续。
- 达到 retained target，或遇到 finite breaker、no-progress、no-safe-epoch、failure、cancel 时停止；Low Water 不在 L4 未启动时主动制造 compact。
- Manual compact 继续不依赖 High Water且允许成功 no-op；Overflow 继续 forced reduction，并保留 Core one-retry guard。

### T03：Provider Prefix Cache hints 与可观察 usage

- Core/Application 只提供稳定、Provider-independent 的请求事实；OpenAI/Anthropic wire 参数只存在于各自 Integration。
- OpenAI Responses 使用当前官方支持且由当前 SDK/fixture 证明可发送的稳定 cache routing/hint。
- Anthropic 使用当前官方支持且由请求 fixture 证明的 cache control 方案，不把 Tool Schema 复制进 system prompt。
- OpenAI-compatible 默认不发送 OpenAI 专有 cache 参数；只有现有明确 capability/config fact 才允许发送。
- instruction、AGENTS、runtime、tools 的 authority 与 stable/dynamic 划分不因缓存优化改变；真实 instruction/tool schema 变化形成 expected invalidation，普通 conversation growth/Timeline compact 不无故改变稳定前缀。
- Provider 未返回 cache metric 时继续为 `not_available`，不以零冒充观测值。

### T04：稳定 FailureReason 与 PauseReason 保真

- Core 公共事件与 terminal result 增加小而稳定、JSON-safe 的失败机器分类；`TerminationReason` 继续表达终止原因，`FailureReason` 表达具体失败类型。
- 当前真实链路至少准确覆盖 authentication、能可靠判断的 provider request/configuration、invalid provider response、context unresolvable、当前已有稳定事实时的 persistence unavailable 与 internal。
- Integration 只映射可靠 SDK/HTTP/Provider 事实，第三方异常对象止于 Integration；不按每个 HTTP status 建类或猜测模型不可用。
- Network、rate limit、timeout 的可恢复行为继续使用 Pause/Retry 语义；当前 timeout 若在 Integration 被折叠为 network且 SDK fact 可可靠区分，则以最小 Provider-independent error/PauseReason扩展保真，不把可恢复暂停改成 terminal failure。
- Public event/result/message 不包含 traceback、native SDK exception、raw Provider body、secret 或内部实现术语。

### T05：256K profile、cache 与 failure Eval 调优

- 在现有 B01 runner、任务、六维 metrics、reporting、compare 与 fingerprint 机制上扩展，不建立第二套 benchmark runtime。
- deterministic contract tests 与概率性 tuning evidence 分离。
- 至少比较三组 High/Low、Timeline、L4 budget/epoch、allowance 等有明显差异的候选；允许围绕优胜区域二次细调。
- 观测 task verifier、tokens、compact count、pre/post usage、post-compact headroom、到下一次 pressure 的工作距离、rediscovery/repeated exploration、externalization/HistoryRead、cache usage、prefix change 和 failure correctness。
- 固定代码、Prompt、model/provider/config 等控制变量仍按 B01 compatibility fingerprint 严格相等；profile id 与完整参数作为受控 candidate variant axis 单独记录，不得把候选差异误判为不兼容，也不得放宽其它 fingerprint。只对控制变量兼容且各候选样本分布一致的报告生成正式 delta；不产生加权 overall score。
- 选出一组 T09-3 初始工程默认并保留可解释报告；参数不是 public API 承诺。

### T06：[接入主流程] Application 统一投影与正式入口收口

- Context resolver、Low Water、Provider cache、FailureReason 进入唯一 `create_application -> create_run -> start_turn -> AgentLoop` 正式链。
- Application 是用户失败文案的唯一 owner；TUI、CLI、Headless 消费同一 structured reason 与 message projection，不保留独立 exception classifier。
- status/diagnostics/Headless 暴露安全的 limit provenance、profile、cache availability/provenance 与失败事实，不泄露正文或秘密。
- 删除被替代的重复 Context/compact/failure/cache 入口；不新增 Manager、Registry、FSM、后台 worker 或第二 Agent Loop。

### T07：[端到端验证] 离线验收、调优报告与文档同步

- 从正式 Headless/Application、CLI/TUI 展示消费和 Provider fake fixture 覆盖 default-only、小/大 ceiling、Active Turn freeze、High->Low、manual、overflow、cache hint/invalidation、FailureReason/PauseReason 与 secret-safe projection。
- 执行定向、Eval、架构、全量、compileall、pip check、diff check 与 UTF-8 guard，记录精确结果。
- 同步 `docs/Context-Index.md`、A03/A04 当前事实以及 `docs/README.md` 维护映射命中的用户手册、Core Design 或 Tool 文档；尊重开工时用户已有未提交改动，不擅自恢复被用户删除的文件。
- 真实 Provider cache/latency/billing Eval 保持 `NOT VERIFIED (authorization required)`，除非用户另行明确授权。

### T08：[遗留负担清理] 单一路径与取消路线确认

- 确认无生产 caller 的 retained profile 字段及其序列化、diagnostics、fixture、当前事实残留为零。
- 确认 bundled model metadata、model-name guessing、第二 Context policy、持久 compact FSM/job、独立 compaction model、Provider cache 类型穿透 Core、Interface 私有失败分类为零。
- 清理本包产生但最终未使用的 profile 参数、cache experiment 分支、重复导出/包装、不可达分支与临时运行产物。
- 重新核对能力欠账；本包没有因后置能力未实现而留下的新欠账，滚动清单保持真实。
- 全部 Checklist 与 Feedback 有证据后将 T09-3 更新为 `implemented_unarchived`；不得自动归档或执行 Git 写操作。

## 非功能要求

- 保持 `interfaces -> application -> core`，由 Application 组合 Integration；Core 不依赖 SDK、filesystem、network、Application 或 Interface。
- Tool Definition 继续只有 Tool System 一份 authority；缓存优化不得复制 Tool Schema 或改变 Prompt authority 顺序。
- Agent Loop 继续显式、集中、串行；Context 与 failure 工作不引入通用 Manager/Registry/FSM/Hook 平台。
- Session single-writer、unknown durability quarantine、Hard Gate、Permission、Secret 与 unsandboxed Bash 边界不得回归。
- 生产修改与测试风险匹配；不新增第三方依赖。若当前 SDK 无法可靠支持官方 cache 参数，停止该 Provider 猜测发送并在 Feedback 报告。
- 中文治理 Markdown 使用 UTF-8；不修改 T09、T09-1、T09-2 已冻结正文、Spec、Tasks、Prompt 或 Checklist。

## 设计骨架

```text
configured input? ─────────┐
reliable provider ceiling? ├─> resolved effective input limit + provenance
default 256K ──────────────┘                    │
                                                v
                                      Active Turn frozen budget
                                                │
                           candidate -> High Water trigger
                                                │
                                           L4 started
                                                │
                       rebuild/recount until Low Water or breaker
                                                │
                                           final Hard Gate
```

```text
stable instructions/tools facts
          -> GenerationRequest
          -> Provider Integration cache hint/control
          -> Provider-managed cache
          -> usage availability/provenance
          -> Application diagnostics / Eval
```

```text
SDK/Context/persistence fact
          -> Integration/Application factual mapping
          -> Core FailureReason or existing PauseReason
          -> AgentEvent + TurnResult
          -> Application one-line presentation
          -> TUI / CLI / Headless display
```

## 能力欠账

无。

Memory / Evidence Retrieval、Persistent Runtime Recovery、跨 Session Artifact 生命周期、Subagent/Multi-Agent、OS Sandbox、后台 Context Agent 等属于独立未来能力或已有独立触发条件，不是本包因后置能力缺失而刻意留下的未完成部分；`docs/OutstandingDebtList.md` 保持不变。

## Out of Scope

- Memory、cross-session retrieval、RAG、Subagent、Multi-Agent、Worktree。
- background Context Agent、hierarchical Summary Graph、independent compaction model、Provider fallback、durable compaction FSM/job。
- bundled model catalog、型号 substring 猜测、模型特定 tuning table 或 Prompt Overlay。
- Provider KV Cache 本地持久化、Cache DB/WAL/migration/replication。
- 完整 Error subsystem、ErrorManager/ErrorRegistry、复杂 i18n、所有 HTTP status 的分类。
- OS Sandbox、权限系统大改、Persistent Runtime Recovery、跨 Session Artifact Store/GC。
- 大型 TUI redesign、动态 Skill/MCP Tool 系统、真实 Provider 调用或费用 baseline（未获单独授权时）。

## 验收标准

1. 无 configured/Provider input limit 时使用 default 256K；可靠小 ceiling 永不被放大，大 ceiling 默认仍以 256K Operating Window 工作。
2. limit provenance 在 Application status/diagnostics/Headless 可观察，Active Turn 冻结且下一 Turn 重新解析。
3. input/output/combined 分维 Hard Gate 保持，unknown 不伪造。
4. Auto L4 启动后真正追到 Low Water 或有限停止；刚低于 High Water不是完成条件，manual/overflow/L5 不回归。
5. 无消费者 ContextBudget 字段及残留删除，没有为保留字段创造伪调用方。
6. OpenAI/Anthropic cache hint 只存在于 Integration，Compat 默认不盲发，Tool Schema authority 唯一，缺失 metric 为 `not_available`。
7. `FailureReason` 可在 public event/result JSON round-trip；Pause/Retry 保持；Application 统一文案，TUI/CLI/Headless 不重复分类且不泄露秘密或 native exception。
8. 现有 Eval 比较至少三组 256K profile，保留逐维证据、兼容 fingerprint 和初始默认选择理由，不生成总分。
9. deterministic、Eval、architecture、全量与文档 guard 通过；未运行的 live Provider 项明确标记未验证。
10. 没有 model catalog、第二 Context policy、缓存子系统、错误平台、兼容层或冻结文档回写；T09-3 保持未归档直到用户手动归档。

## 冻结决策追踪

| 冻结决策 | Spec 覆盖 |
| --- | --- |
| D-T09-3-01 | T01、T05、验收 1/8 |
| D-T09-3-02 | T01、T06、验收 1/2 |
| D-T09-3-03 | T01、验收 3 |
| D-T09-3-04 | T01、T08、验收 10 |
| D-T09-3-05 | T02、验收 4 |
| D-T09-3-06 | T05、验收 8 |
| D-T09-3-07 | T04、T06、验收 7 |
| D-T09-3-08 | T01～T08、本追踪表 |
