# T09-1 Context 预算与 Compact 协议补齐 Tasks

## Worker 分组与执行顺序

| Worker | 严格顺序 | 前置 Worker |
| --- | --- | --- |
| W01 | Task 1 | 无 |
| W02 | Task 2 | W01 |
| W03 | Task 3 | W01、W02 |
| W04 | Task 4 | W01～W03 |
| W05 | Task 5 | W01～W04 |
| W06 | Task 6 | W01～W05 |
| W07 | Task 7 → Task 8 → Task 9 → Task 10 | W01～W06 |

Worker 必须按表串行派发；每个 Worker 首次执行时创建同名 Feedback。用户未显式指定 Prompt 文件前，不得开始对应实施。

## Task 1：Model Context Profile 与统一 Budget Resolver

- 任务目标：移除固定 258K 作为公共请求安全 invariant，建立 per-model operating window、request-level budget、small/large-window retained policy 与可靠物理上限 guard。
- 新增文件：`tests/test_context_budget_gate.py`、`tests/test_provider_model_limits.py`。
- 修改文件：`src/uthcode/application/configuration.py`、`src/uthcode/integrations/config/loader.py`、`src/uthcode/integrations/config/template.py`、`src/uthcode/core/context.py`、`src/uthcode/core/provider.py`、`src/uthcode/integrations/providers/anthropic.py`、`src/uthcode/application/bootstrap.py`、必要的 `src/uthcode/core/__init__.py` / `src/uthcode/application/__init__.py` export、`tests/test_configuration.py`、`tests/test_config_contract.py`。
- 删除内容：固定 `UTHCODE_CONTEXT_BUDGET_TOKENS` 作为唯一 runtime invariant，以及 `ContextUsage` / `ContextSnapshot` 对该常量的硬校验；若常量无剩余真实调用方则删除 export。
- 文件职责及实施内容：配置层要求每个可运行 Model profile 提供正整数 `context_window`；project overlay 只允许覆盖用户已定义 model 的非 Provider/credential 字段；Core 定义 SDK-neutral model-limit/count contract 与预算值；Application 解析 `C`、output reserve、safety margin、A/F/U、hard cap、compaction input/output budget；Anthropic adapter 把官方模型上限与 token count 转换为 Core DTO，OpenAI/compat 不伪造 metadata；composition root 只组装真实可选 capability。
- 依赖任务：无。
- 参考资料定位：原始需求第 6～8、10～12、15.1、16、18 节；`docs/context/A01-AgentRuntime/AgentRuntime-Context.md`；`docs/context/A03-State/State-Context.md`；Anthropic Models / Token Counting 官方 API；OpenAI Models 官方 API。
- 完成边界：配置与预算 contract 可独立工作，不依赖 Timeline 或真实 L4；覆盖 25K、128K、258K、1M，configured C 小于/大于可靠 ceiling、无 metadata 和 model switch next-Turn 边界。

## Task 2：Transcript / Timeline Contract 与 Session v2

- 任务目标：完成 `CanonicalHistory + Projection` 到 `Transcript + Timeline` 的硬切，并建立 checkpoint-last 的 crash-safe Timeline transaction。
- 新增文件：`tests/test_timeline_contract.py`。
- 修改文件：`src/uthcode/core/history.py`、`src/uthcode/core/prompt.py`、`src/uthcode/core/__init__.py`、`src/uthcode/application/history.py`、`src/uthcode/application/sessions.py`、`src/uthcode/integrations/session_files.py`、`tests/test_history_contract.py`、`tests/test_session_files.py`。
- 删除内容：Projection 作为 active Context authority 的产品语义、Session v1 `history.jsonl` 的新读写入口、旧 schema dual read/write 路径和失效 export。
- 文件职责及实施内容：Core 定义 raw Transcript、stable Transcript range/ref、Fine Semantic Entry、Epoch Macro Summary、Active Checkpoint 与 append-only Timeline；保留 strict sequence、完整 Tool semantic group 和 RuntimeLog 非权威语义；Session v2 分离 `transcript.jsonl` 与 `timeline.jsonl`；Timeline transaction 以 checkpoint 最后提交，loader 只采用 latest valid checkpoint 之前的记录；沿用 single-writer、append/fsync、identity reconciliation、durability unknown quarantine；旧 Session deterministic incompatible，不迁移。
- 依赖任务：Task 1 的配置/预算 contract 已稳定；本 Task 不依赖 L4 caller。
- 参考资料定位：原始需求第 4、6～7、9～13、15.2、16～18 节；`docs/context/A03-State/State-Context.md`；现有 `src/uthcode/integrations/session_files.py` durability contract。
- 完成边界：fresh Session 具备 metadata、writer lock、Transcript、Timeline、Runtime diagnostics、Tool Result 文件布局；partial JSON、incomplete semantic group、trailing timeline、checkpoint crash、single writer、unknown durability 和 old schema 均有测试。

## Task 3：ContextCompiler logical view 与确定性 L1-L3

- 任务目标：让 ContextCompiler 成为 Transcript + Timeline + current runtime facts 的唯一 model-view builder，并在 semantic model call 前完成确定性 reduction。
- 新增文件：无（复用 Task 1 新增预算测试）。
- 修改文件：`src/uthcode/core/context.py`、`src/uthcode/core/prompt.py`、`src/uthcode/application/context.py`、`tests/test_context_compiler.py`、`tests/test_context_budget_gate.py`、必要的 `tests/test_tool_result_persistence.py`。
- 删除内容：以 Projection revision 直接决定 active model view 的路径，以及绕过 Compiler 拼装模型消息的重复职责。
- 文件职责及实施内容：Core 编译 Instruction Plane、logical Timeline、protected blocks、active evidence、recent complete units 与 current turn；L1 复用 Tool Result externalization，L2 对旧 preview 做 bounded mask/shrink，L3 只按完整 Turn / semantic unit 省略 inactive raw；macro coverage 在 logical view 中 supersede 已覆盖 fine entries，physical Timeline 长度不进入 F；Application 只编排 plan/rebuild/Gate；diagnostics 只输出 ID、count、token、budget 与 reason。
- 依赖任务：Task 1、Task 2。
- 参考资料定位：原始需求第 4、6～7、10～12、15.3、16、18 节；`docs/core-design/T09-context-engineering.md`；现有 Tool Result externalization tests。
- 完成边界：无模型调用即可验证完整 Gate precheck、L1-L3、logical Timeline rebuild；protected required content + current turn 不可装入时返回 `context_unresolvable` 且 Provider call count 为零。

## Task 4：Production L4 与 bounded catch-up

- 任务目标：接通真实 tool-free L4 semantic compaction，并在同一次 Gate 调用栈中实现 1..N bounded epoch catch-up。
- 新增文件：`tests/test_t09_1_context_protocol_e2e.py`。
- 修改文件：`src/uthcode/core/agent.py`、`src/uthcode/application/context.py`、`src/uthcode/application/generation.py`、`src/uthcode/application/sessions.py`、`tests/test_context_compaction.py`、`tests/test_context_budget_gate.py`、`tests/test_application_runs.py`。
- 删除内容：生产同步 `summarize=None` path、旧 `compactor(summarize=None)` overflow path，以及任何 Projection candidate 生产提交路径。
- 文件职责及实施内容：AgentLoop 只 await request preparation，不接收 Transcript/Timeline/phase；Application 用 active Turn frozen provider/model/C 或 idle current selection 构造无 Agent Tools 的 bounded compact request；结构化解析为 one-SemanticEntry-per-Turn，校验 coverage、refs、size 与顺序；先 entries 后 checkpoint；每次 durable commit 后 rebuild+Gate；attempt/coverage/estimate/cancel 局限于当前调用栈；实现 no-progress、repeated-failure、finite-attempt breaker；compact request 自身也通过独立预算 gate。
- 依赖任务：Task 1～3。
- 参考资料定位：原始需求冻结决策 D1/D2、第 6～8、11～13、15.4、16～19 节；Codex 与 OpenCode 当前源代码/规格；Claude Code compaction thrash guard 文档。
- 完成边界：单 epoch、多 epoch、800K raw/1M C、crash after epoch N、checkpoint 前 crash、cancel、invalid result、no progress 与 active Turn snapshot 均有无网络 fake fixtures；不实现 L5、Job、background worker 或独立模型。

## Task 5：L5 Timeline Aging 与 HistoryRead

- 任务目标：把 logical Fine Timeline 限制在 F，并让模型通过 current Session opaque ref 有界回读摘要覆盖的 raw Transcript evidence。
- 新增文件：`src/uthcode/integrations/tools/history_read.py`、`tests/test_history_read_tool.py`。
- 修改文件：`src/uthcode/application/context.py`、`src/uthcode/application/tools.py`、`src/uthcode/application/bootstrap.py`、必要的 `src/uthcode/integrations/tools/factory.py`、`tests/test_timeline_contract.py`、`tests/test_application_tools.py`、`tests/test_tool_result_persistence.py`、`tests/test_context_budget_gate.py`、`tests/test_context_compaction.py`。
- 删除内容：无独立历史读取旧入口；如现有重复 path reader 因本 Task 直接失效则删除。
- 文件职责及实施内容：L5 只选择旧 complete compact epoch，解析其 refs 并读取 raw Transcript evidence；生成一个 bounded macro summary 后最后提交 checkpoint；coverage 在 logical view 中替代旧 fine entries但不物理删除；禁止 summary-of-summary input；无法安全读取任何 epoch 时明确 fail closed；HistoryRead 与 ToolResultRead 分离，current Session only、opaque ref、bounded page、read-only、no index/search、输出不递归 externalize。
- 依赖任务：Task 1～4。
- 参考资料定位：原始需求第 4、6～7、10～13、15.5、16、18～20 节；现有 ToolResultRead 与 tool composition contract。
- 完成边界：L5 raw provenance、coverage supersede、no-safe-epoch、malformed/cross-session ref、bounded pagination 和独立 Tool 注册均有测试；不实现 Memory、semantic search、cross-session history 或 Timeline GC。

## Task 6：Incremental Transcript、Manual Compact 与 Overflow Retry

- 任务目标：把 Context 协议接入正式 Run/Command 生命周期，补齐 closed semantic facts 的 request-boundary persistence、手动 Compact、动态 status 和最后保护型 overflow retry。
- 新增文件：无（扩展 E2E 测试）。
- 修改文件：`src/uthcode/application/generation.py`、`src/uthcode/application/sessions.py`、`src/uthcode/application/commands/builtins.py`、`src/uthcode/application/commands/dispatcher.py`、仅真实 awaitable typing 需要时修改 `src/uthcode/application/commands/models.py`、仅 async dispatch adapter 需要时修改 `src/uthcode/interfaces/tui/app.py`、`tests/test_application_runtime.py`、`tests/test_application_runs.py`、`tests/test_command_dispatcher.py`、`tests/test_w04_session_commands.py`、`tests/test_tui.py`、`tests/test_t09_1_context_protocol_e2e.py`、`tests/test_session_files.py`。
- 删除内容：`/compact` 固定 `summarizer_unavailable` 生产结果、`/status` 的 fixed-258K limitation 文本、旧 overflow → unavailable compactor → retry 路径。
- 文件职责及实施内容：在 first provider call 前提交 current user closed fact，在 post-tool next call 前提交完整 assistant ToolCall + matched ToolResult group，terminal 提交 final tail；复用 durable cursor/reconciliation/quarantine 保证不重复 append，禁止 open fragments/continuation；`/compact` await 同一 Application orchestrator，不创建 Run/Turn，无候选成功 no-op，不写 checkpoint；同 Session compaction single-flight；overflow 最多一次 forced reduction/rebuild/retry，不修改 C；status 展示 used/C、estimator、reserve、A/F/U、last Gate action、L1-L5 counters 与 checkpoint/epoch safe diagnostics；mid-turn model switch 不改变 frozen C。
- 依赖任务：Task 1～5。
- 参考资料定位：原始需求第 6～7、10～13、15.6、16、18 节；`docs/context/A04-Orchestration/Orchestration-Context.md`；现有 terminal History persistence outcomes。
- 完成边界：initial/post-tool/post-resume/terminal persistence、manual success/no-op/failure、single-flight、overflow once/twice、model switch 和 Headless path 均有测试；不实现后台 job 或 Runtime recovery。

## Task 7：Diagnostics、Eval 与文档同步

- 任务目标：让公开 diagnostics、Eval 与长期文档反映动态 C、Gate、Transcript/Timeline、L1-L5 与旧 Session incompatible 的真实实现。
- 新增文件：无。
- 修改文件：`eval/metrics.py`、`tests/test_w05_diagnostics.py`、`tests/test_w06_integration_delivery.py`、`tests/test_architecture_boundaries.py`、`docs/Context-Index.md`、`docs/core-design/T09-context-engineering.md`、`docs/context/A01-AgentRuntime/AgentRuntime-Context.md`、`docs/context/A03-State/State-Context.md`、`docs/context/A04-Orchestration/Orchestration-Context.md`、`docs/user-manual/configuration.md`、`docs/user-manual/commands.md`、必要时 `README.md` 与 `docs/user-manual/getting-started.md`。
- 删除内容：文档和 Eval 中 fixed 258K、Projection revision=current compaction state、生产 `summarizer_unavailable` 的现行能力描述。
- 文件职责及实施内容：safe diagnostics 不含 raw Transcript、summary、Tool result 或 secret 正文；Eval 只消费公开字段，不将效果阈值写成产品 pytest；用户文档说明 `context_window` 配置、`/compact`、`/status`、旧 Session incompatibility；核心设计/当前事实说明 C vs physical ceiling、Transcript vs Timeline、L1-L5、B′ 无 Compact FSM、resume 不恢复 Runtime；architecture tests 固化 Core 无 SDK/fs/network、Interface 不拥有 Context orchestration。
- 依赖任务：Task 1～6。
- 参考资料定位：`docs/README.md` 文档维护映射；原始需求第 13、15.7、16～18 节；实际实现与公开 tests。
- 完成边界：文档只描述已实现事实；UTF-8、乱码、fence、链接和 secret 示例检查通过；Eval 不新增总分或网络 CI。

## Task 8：[接入主流程] 单一 Context Orchestration 收口

- 任务目标：把 Task 1～7 的能力接入唯一正式 Headless/TUI/CLI/Application/Session 调用链，并删除被替代生产入口。
- 新增文件：无。
- 修改文件：仅 Task 1～7 已列文件及必要机械 import/export；不得借本 Task 新增产品能力。
- 删除内容：绕过 Application Hard Gate 的 Provider call、重复模型消息拼装、旧 History/Projection 新写入入口、同步空 summarizer、旧 overflow path 和失效 public export。
- 文件职责及实施内容：沿 `create_application -> ensure_session/create_run -> AgentRun -> awaited request preparation -> Application Context Gate -> ProviderPort` 检查每个 call site；L4/L5 也经过自身预算 gate但不进入 Agent Tool loop；Command/TUI 只触发 Application use case；Session writer 只提交 Core values。
- 依赖任务：Task 1～7。
- 参考资料定位：`docs/Context-Index.md` 跨层最短链路；原始需求第 4、7、12、13、18 节。
- 完成边界：代码检索与 architecture tests 证明单一路径；没有 Interface-owned Context、Provider-name Runtime branch、SDK type leak 或第二套 compaction state。

## Task 9：[端到端验证] Context / Compact / Recovery

- 任务目标：从真实入口验证动态预算、分层 reduction、durable checkpoint、手动 Compact、overflow retry、resume 与 Headless 行为。
- 新增文件：无（优先完善 `tests/test_t09_1_context_protocol_e2e.py`）。
- 修改文件：仅测试、fixture 与因真实 E2E 暴露的 Task 1～8 范围内实现缺陷。
- 删除内容：无。
- 文件职责及实施内容：覆盖 small/large C、normal gate、protected impossible、L1-L5、multi-epoch、crash before/after checkpoint、incremental closed facts、manual compact/no-op、HistoryRead、overflow once/twice、mid-turn model freeze、old Session reject、Headless 与 TUI command adapter；外部真实 Provider 网络调用不作为 CI 必过条件。
- 依赖任务：Task 8。
- 参考资料定位：原始需求第 16、18 节完整矩阵；`docs/README.md` 包级验收要求。
- 完成边界：定向、架构和全量 pytest 命令及精确结果记录到 W07 Feedback；基线 3 个 TUI RGB 断言若仍失败，不得伪报通过或擅自扩大 T09-1 范围，必须记录环境/复现证据和对验收的影响。

## Task 10：[遗留负担清理] 单 Transcript / Timeline 路径收口

- 任务目标：证明本任务未保留兼容层、废弃实现、不可达代码、重复职责或为未来能力预制的抽象。
- 新增文件：无。
- 修改文件：仅 Task 1～9 范围内因删除失效实现而必要的代码、测试和文档。
- 删除内容：固定预算唯一 invariant、Projection authority/生产 revision、Session v1 history 新写入、同步 unavailable summarizer、旧 overflow compactor、过时 status/docs、无调用方 manager/registry/job/protocol；保留仍有真实价值的 strict sequence、complete-unit validation、token estimator、single-flight、writer lock/fsync/reconciliation/quarantine、Tool Result externalization 与非权威 Runtime diagnostics。
- 文件职责及实施内容：使用 `rg`、import/architecture tests 和 dead-code review 核对旧符号、旧路径和重复调用链；确认没有 Memory、Runtime checkpoint、Timeline GC、background worker、independent compaction model、Subagent/Multi-Agent 或旧 Session compatibility。
- 依赖任务：Task 9。
- 参考资料定位：原始需求第 17、19、20 节；`AGENTS.md` 增量开发与旧实现删除原则。
- 完成边界：清理检索结果、最终测试、UTF-8 guard 与未完成风险写入 W07 Feedback；不执行 Git commit/push/merge/tag/release，不归档工作包。
