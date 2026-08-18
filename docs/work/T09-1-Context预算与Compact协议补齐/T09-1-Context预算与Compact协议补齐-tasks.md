# T09-1：Context 预算与 Compact 协议补齐 Tasks

## Worker 分组、顺序与依赖

| Worker | 严格顺序 | Prompt | 依赖 |
| --- | --- | --- | --- |
| W01 | T01 | `prompt/W01-model-budget-provider-prompt.md` | 无 |
| W02 | T02 | `prompt/W02-transcript-timeline-session-prompt.md` | 无；可在 W01 完成前独立实施，但合并后须重跑交叉测试 |
| W03 | T03 | `prompt/W03-request-compiler-reduction-prompt.md` | T01、T02 |
| W04 | T04 → T05 | `prompt/W04-semantic-compaction-aging-prompt.md` | T01～T03 |
| W05 | T06 | `prompt/W05-runtime-command-integration-prompt.md` | T01～T05 |
| W06 | T07 → T08 | `prompt/W06-delivery-regression-cleanup-prompt.md` | T01～T06 |

Worker 只能由用户显式派发对应 Prompt。每个 Worker 内部严格串行；不得跳过依赖或提前修改后续 Worker 的专属收口范围。W01/W02 即使分开实施，也必须在 W03 开始前集成到同一工作树并完成双方定向回归。

## T01：模型窗口、Provider 能力与双 Gate 预算

### 任务目标

用显式模型 Operating Context Window、可选可靠 Provider limits、统一 count estimate 与自适应预算 policy 替代固定 258K runtime invariant，建立可纯测试的 Auto/Hard Gate contract。

### 新增文件

- `tests/test_provider_model_limits.py`：验证 Provider limits/count optional capability、DTO 转换与缺失退化。
- `tests/test_context_budget_gate.py`：验证 C/E、headroom、retained profile、uncertainty、Auto/Hard Gate。

### 修改文件

- `src/uthcode/core/context.py`：定义动态预算、集中 policy、Gate decision 与 count uncertainty 纯逻辑；移除固定预算硬校验。
- `src/uthcode/core/provider.py`：增加 SDK-neutral limits 与 token count estimate contract；能力保持可选。
- `src/uthcode/core/__init__.py`：导出新 Core contract，删除失效固定预算导出。
- `src/uthcode/application/configuration.py`：让 runnable model profile 必须有正整数窗口，并纳入不可变配置。
- `src/uthcode/integrations/config/loader.py`：解析、合并和校验模型窗口；保持项目配置安全限制。
- `src/uthcode/integrations/config/template.py`：在首次配置模板中给出必填窗口与 operating 语义。
- `src/uthcode/integrations/providers/anthropic.py`：通过当前 SDK 提供可选 Models API limits 和 Messages count_tokens，转换为 Core DTO。
- `src/uthcode/application/bootstrap.py`：组合 Provider optional capability，不向 Application 泄露 SDK 类型。
- `tests/test_configuration.py`、`tests/test_config_contract.py`、`tests/test_anthropic_integration.py`：覆盖配置与 Anthropic adapter。

### 文件职责及实施内容

- `C` 来自 model profile；不存在 fallback。
- `E` 取 `C` 与可靠 input ceiling 的较小值；provider 无能力或受控失败时使用 `C`。
- output reserve 同时考虑配置、Provider reliable max output 与实际 request；具体优先级在一个 Application/Core policy 边界内集中定义。
- Provider count 与 local count 都返回带 source/kind 的 estimate；uncertainty 由 kind 单点解析。
- headroom 随 E 缓慢增长并有绝对 cap；active evidence、fine timeline、recent tail、retained target 与 compact input/output budget 对小窗口共同收缩，对大窗口不线性扩张。
- Anthropic 序列化 count request 时复用正式 Messages request 的 system/messages/tools/model 结构；测试使用 fake client。
- OpenAI Responses/Compat 不实现虚构 limits/count capability。

### 依赖任务

无。

### 参考资料定位

- 原始需求第 4.4、4.5、7、8、11.1～11.5、12.2、15/I01、16、18 节。
- `docs/context/A03-State/State-Context.md`、`docs/user-manual/configuration.md`。
- Anthropic Models API、Messages Token Counting 官方文档；Pi/OpenCode/Codex 仅作 policy 机制参考。

### 完成边界

动态 budget 与 Gate 可在不依赖 Timeline/L4 的纯测试中完整构造；现有请求链可暂时通过显式 default test config 适配，但不得保留生产 258K fallback。

## T02：Transcript、Timeline 与 Session v2

### 任务目标

用分离的 raw Transcript 与 derived Timeline 硬切 Canonical History/Projection，并建立 checkpoint-last 的 crash-safe Session v2 contract。

### 新增文件

- `tests/test_timeline_contract.py`：验证三种 Timeline record、logical view、coverage 与 checkpoint transaction。

### 修改文件

- `src/uthcode/core/history.py`：定义 Transcript、TranscriptRef、SemanticEntry、EpochMacroSummary、ActiveCheckpoint、Timeline；移除 Projection 生产 authority。
- `src/uthcode/core/prompt.py`：把 Transcript/Timeline 作为 conversation/history authority，不把 summary 提升为 System。
- `src/uthcode/core/__init__.py`：更新 exports，不保留旧 alias。
- `src/uthcode/application/history.py`：把完整 Message semantic unit 转为 durable Transcript records；保持 Tool pair 原子性。
- `src/uthcode/application/sessions.py`：暴露 Transcript/Timeline snapshot 与 append/checkpoint outcome。
- `src/uthcode/integrations/session_files.py`：实现 Session v2 文件、严格读取、checkpoint-last transaction、reconciliation/quarantine 与 old v1 incompatible。
- `tests/test_history_contract.py`、`tests/test_session_files.py`：迁移到新 contract 并覆盖 crash/尾部/锁/恢复。

### 文件职责及实施内容

- fresh Session 创建 `metadata.json`、`writer.lock`、`transcript.jsonl`、`timeline.jsonl`、`runtime.jsonl`、`tool-results/`。
- Transcript 只接受已闭合 User、Assistant、完整 ToolCall/ToolResult group 等可判定事实，strict sequence 且带 current Session ownership。
- Timeline 物理 append-only，只接收三类产品 record；每次 L4/L5 transaction 先写 derived records，ActiveCheckpoint 最后 fsync。
- loader 只依据 latest valid checkpoint 构造 committed logical view；checkpoint 后 trailing incomplete records 不生效。
- old v1 `history.jsonl` Session 明确返回 incompatible，不 migration、dual read、dual write。
- 复用 single writer、append identity reconciliation、unknown durability quarantine、close/reopen recovery；RuntimeLog 仍非权威。

### 依赖任务

无。与 T01 合并后需重跑 configuration/context/session 交叉测试。

### 参考资料定位

- 原始需求第 4.1、4.3、6、7、11.6～11.11、12.4～12.6、15/I02、16～18 节。
- `docs/context/A03-State/State-Context.md`。
- 现有 `session_files.py` 的 lock/fsync/reconciliation/quarantine 实现和对应测试。

### 完成边界

无真实 summarizer/model call 时即可创建、append、load、resume Transcript/Timeline；旧 Session 稳定拒绝，且无 compatibility path。

## T03：最终请求计数与确定性 L1-L3

### 任务目标

让 Context Compiler 在 semantic compact 前完成最终 request assembly/count/Gate，并按完整语义边界执行确定性 L1-L3 后重新构建和 re-gate。

### 新增文件

无；扩展 T01 新增的 budget gate 测试。

### 修改文件

- `src/uthcode/core/context.py`：实现动态 Compiler working set、deterministic L2/L3 与 reduction outcome。
- `src/uthcode/core/prompt.py`：组合 protected instruction、Timeline、Transcript recent tail、runtime/environment facts。
- `src/uthcode/application/context.py`：统一 final request assembly、Provider/local count、Gate、L1-L3、rebuild 与 safe diagnostics。
- `tests/test_context_compiler.py`：覆盖 source authority、small/large budget、preview shrink、inactive unit omit、protected facts。
- `tests/test_context_budget_gate.py`：覆盖 L1-L3 re-gate、Auto/Hard 分叉与 unresolvable。
- `tests/test_tool_result_persistence.py`：确认 L1 外置及 bounded preview 不重复实现。

### 文件职责及实施内容

- final accounting 覆盖 Provider-visible system/messages/tools/model、requested output 和已知结构 overhead。
- L1 使用现有 Tool Result materialization；L2 可重复、bounded 地缩短 preview/mask；L3 只省略 inactive complete Turn/semantic unit。
- current Turn、protected instruction/runtime requirement 与完整 Tool semantic group不可拆。
- 每一步 reduction 后从权威 facts 重新组装 request 并重算 count/Gate，不通过差值猜测最终安全性。
- L1-L3 后仍 Auto pressure 时返回 L4-required，即使 Hard-safe；已清除且 Hard-safe 时直接发送候选。
- required protected/current facts 自身 Hard-unsafe 时直接 context-unresolvable，Provider call count 为零。
- diagnostics 仅含 token/count/source/id/reason 等安全字段。

### 依赖任务

T01、T02。

### 参考资料定位

- 原始需求第 4.4、6、7、10、11.4～11.5、12.1～12.3、15/I03、16、18 节。
- `docs/core-design/T09-context-engineering.md` 与现有 Tool Result externalization contract。

### 完成边界

不调用模型即可证明所有 ordinary candidate 都先形成最终请求、执行双 Gate，并正确选择直接发送、L4-required 或 fail closed。

## T04：生产 L4 与 bounded catch-up

### 任务目标

接通当前主模型的 tool-free L4，用结构化 Fine entries 和 checkpoint-last transaction 实现 1..N bounded epoch catch-up。

### 新增文件

- `tests/test_t09_1_context_protocol_e2e.py`：先建立 L4/Hard Gate/Application fake-provider 骨架，后续 Task 扩展。

### 修改文件

- `src/uthcode/application/context.py`：实现 async L4 orchestrator、epoch selection、tool-free request、Hard Gate、parse/validate、commit/re-gate 与 finite breaker。
- `src/uthcode/application/generation.py`：向 Context orchestrator 提供 frozen Turn provider/model/C/cancellation；不下放状态给 AgentLoop。
- `src/uthcode/application/sessions.py`：提交 SemanticEntry batch 与 final checkpoint outcome。
- `src/uthcode/core/agent.py`：复用并收紧现有 awaitable request preparer/overflow hook contract；只做必要 typing/cancellation/error boundary 调整。
- `tests/test_context_compaction.py`、`tests/test_context_budget_gate.py`、`tests/test_agent_loop.py`、`tests/test_application_runs.py`：覆盖 L4 与编排。

### 文件职责及实施内容

- active Turn 使用已冻结 provider/model/C；manual idle 由后续 T06 使用 current selection。
- L4 request 使用独立 compact prompt、`tools=()`、bounded raw Transcript epoch、bounded output；自身只经过 Hard Gate，不递归 Auto Gate。
- parser 必须验证 one entry per covered Turn、contiguous/完整 coverage、refs 存在、summary bounded；失败或取消不 append。
- commit 顺序为 entries first、checkpoint last；每个 committed epoch 后从 Transcript/Timeline rebuild ordinary request 并重新 Auto/Hard Gate。
- retained target 提供明显工作 headroom，不只越过 Auto Gate 数 token；最多有限 epoch/attempt，并检测 previous estimate/coverage 无进展、repeated failure、no-safe-epoch。
- breaker 后 Auto unresolved + Hard-safe 返回可发送 request 与安全 reason；Hard-unsafe fail closed。
- 不创建持久 Compact state/job/next pointer，不修改 RunState ownership。

### 依赖任务

T01～T03。

### 参考资料定位

- 原始需求第 4.2～4.5、6、7、11.8～11.11、12.3、12.5、12.8、15/I04、16、18～20 节。
- Core 已有 awaitable request preparer/overflow hook 测试；不要重复建设第二套协议。

### 完成边界

fake Provider 下可完成 one-epoch 与 multi-epoch L4、checkpoint recovery、no-progress、cancel、parse failure、Auto unresolved 和 Hard unsafe；尚不要求命令/TUI 已接入。

## T05：L5 Timeline Aging 与 HistoryRead

### 任务目标

让 Fine Timeline pressure 可独立触发 raw-evidence L5，并提供 current-Session exact Transcript ref 的 bounded read-only Tool。

### 新增文件

- `src/uthcode/integrations/tools/history_read.py`：opaque TranscriptRef 解码、ownership/boundary 校验与 bounded page read。
- `tests/test_history_read_tool.py`：覆盖成功、分页、malformed/cross-session/invalid-boundary denial。

### 修改文件

- `src/uthcode/application/context.py`：选择 old complete compact epoch、从 raw Transcript 组装 L5、Hard Gate、macro/checkpoint commit 与 logical supersede。
- `src/uthcode/application/tools.py`：保留 HistoryRead 名称、参数、权限和 output materialization 特例；与 ToolResultRead 分域。
- `src/uthcode/application/bootstrap.py`：按 active Session 组合 HistoryRead reader。
- `tests/test_timeline_contract.py`、`tests/test_context_compaction.py`：覆盖 Fine budget、epoch selection、raw provenance、no summary-of-summary 与 no-safe-epoch。
- `tests/test_application_tools.py`、`tests/test_tool_result_persistence.py`：覆盖正式 Tool composition 与不递归外置。

### 文件职责及实施内容

- L5 trigger 只依赖 logical Fine Timeline usage 与 F，可在 ordinary request 低 pressure 时发生。
- 只选择由 checkpoint 闭合的旧 complete L4 epoch；evidence 必须由 refs 回读 raw Transcript，不使用 Fine/Macro summary 作为唯一输入。
- L5 request tool-free、bounded、Hard-gated；成功 append one macro summary then checkpoint，logical view supersede coverage，物理记录不删除。
- raw epoch 无法安全放入请求时返回 no-safe-epoch，不换模型、不递归 compact、不做 summary-of-summary。
- HistoryRead 只接受 active Session opaque ref 与 bounded offset/limit；拒绝任意路径、搜索、跨 Session 和不完整 semantic boundary。
- HistoryRead 的返回不再被 Tool Result externalization 替换为另一个 ref。

### 依赖任务

T01～T04。

### 参考资料定位

- 原始需求第 4.7、6、7、11.7～11.10、12.6～12.7、15/I05、16、18、20 节。
- `src/uthcode/integrations/tools/tool_result_read.py` 作为安全模式参考，不复用其证据域。

### 完成边界

fake Provider 与临时 Session 下可证明 L5 独立触发、raw provenance、checkpoint commit、logical aging，以及 HistoryRead current-session bounded safety。

## T06：[接入主流程] 生命周期、命令与 overflow recovery

### 任务目标

把 T01～T05 接入正式 Run、Session、command、TUI 与 Headless 路径，保证每个真实模型调用共享 Hard Gate，并完成手动 Compact 与一次 overflow recovery。

### 新增文件

无；扩展协议 e2e 测试。

### 修改文件

- `src/uthcode/application/generation.py`：冻结 Turn budget snapshot、async prepare、incremental closed Transcript persistence、manual compact、forced overflow reduction、status diagnostics。
- `src/uthcode/application/sessions.py`：request-boundary 与 terminal-tail durable cursor/outcome；不写 open continuation。
- `src/uthcode/application/commands/builtins.py`：异步 Compact success/no-op/failure 与动态 status。
- `src/uthcode/application/commands/dispatcher.py`、`models.py`：最小 sync-or-awaitable handler contract，保留同步命令行为。
- `src/uthcode/interfaces/tui/app.py`：await command outcome；不新增 Context 编排。
- `src/uthcode/application/bootstrap.py`：完成 Context/Provider/Session/HistoryRead 正式组合。
- `tests/test_application_runtime.py`、`tests/test_application_runs.py`：覆盖 frozen C、incremental persistence、normal/tool/resume call Gate。
- `tests/test_command_dispatcher.py`、`tests/test_w04_session_commands.py`、`tests/test_tui.py`：覆盖 async command 与 UI/headless compatibility。
- `tests/test_t09_1_context_protocol_e2e.py`：覆盖 manual、overflow retry 与正式入口。

### 文件职责及实施内容

- before first call 提交已闭合 user fact；after tool batch/before next call 提交完整 assistant ToolCall + matched ToolResult；terminal 提交 final tail。
- durable cursor 只对可判定落盘的 identity 前进；真正 append failure 的 pending batch 保留原 Session/Turn identity FIFO retry；unknown outcome quarantine。
- active/paused continuation、waiter、coroutine、pending permission/AskUser 不持久化。
- active Turn 冻结 provider/model/C/output/tools；运行中 `/model` 只影响下一 Turn。
- `/compact` await Application orchestrator，低于 Auto 也强制寻找有价值 epoch；无候选 success no-op，不建 Session/Run/Turn、不写垃圾 Timeline。
- ordinary provider overflow 只允许一次 forced L1-L4 reduction、rebuild、Hard Gate 与 retry；第二次失败，不修改 C/E。Compact 内部 overflow 作为当前 attempt 失败或缩小 safe epoch，禁止递归。
- 所有普通、post-tool、post-resume、manual、L4、L5、retry model call 都在 Provider 前执行 Hard Gate。
- `/status` 与 TUI usage projection 使用动态安全 diagnostics，不泄露正文。

### 依赖任务

T01～T05。

### 参考资料定位

- 原始需求第 4.6、4.8、6、7、12.1、12.4、12.8、13、15/I06、16、18～20 节。
- `docs/context/A04-Orchestration/Orchestration-Context.md`、`docs/context/TUI/README.md`。

### 完成边界

CLI/TUI/Headless 正式路径共享 Context safety boundary；manual no-op/success/failure、一次 overflow retry、incremental persistence、resume fresh Run 与 model switch frozen snapshot 都可测试观察。

## T07：[端到端验证] Diagnostics、Eval、文档与回归

### 任务目标

从正式入口证明完整协议并同步所有受影响文档与安全 diagnostics，完成包级一致性和回归证据。

### 新增文件

无。

### 修改文件

- `eval/metrics.py`：消费 public Gate/Timeline/count/pressure diagnostics；保持并列维度、无总分。
- `tests/test_w05_diagnostics.py`、`tests/test_w06_integration_delivery.py`：覆盖安全字段、Headless、Session/Context 整合。
- `tests/test_architecture_boundaries.py`：覆盖 Core/Integration/Application/Interface 与 SDK 截止边界。
- `tests/test_t09_1_context_protocol_e2e.py`：完成测试矩阵中的正式 e2e。
- `docs/Context-Index.md`、`docs/Tools.md`、`docs/core-design/T09-context-engineering.md`、`docs/context/A03-State/State-Context.md`、`docs/context/A04-Orchestration/Orchestration-Context.md`、`docs/user-manual/commands.md`、`docs/user-manual/configuration.md`：同步已实现事实。
- 按 `docs/README.md` 维护映射检查并按事实更新其它受影响文档，尤其根/核心设计索引和 TUI 当前事实中残留的固定预算或 Projection 文案。

### 文件职责及实施内容

- public diagnostics 只记录窗口、limit、estimate、count source、Gate result、coverage/id/reason、compaction/pressure outcome；禁止 Transcript/summary/Tool/secret 正文。
- Eval 对比 success、token、tool calls、compaction、pressure 与既有维度，不增加总分，不将内部 tuning default 写成产品阈值。
- 文档明确 C/E、Auto/Hard、adaptive capped profile、Transcript/Timeline、L1-L5、B′ no FSM、manual compact、HistoryRead、overflow retry once、resume != Runtime Recovery、old v1 incompatible。
- 执行工作包测试矩阵、T05/T06/T08 定向回归、架构测试与全量 pytest；真实 Provider 网络调用不作为必过条件。
- 更新 Checklist 完成框和 Feedback；未经用户确认不归档、不提交 Git。

### 依赖任务

T01～T06。

### 参考资料定位

- 原始需求第 8、9、15/I07、16、18 节。
- `docs/README.md` 文档维护映射与当前 Context docs。

### 完成边界

正式入口正常/失败路径和全量回归有精确结果，文档不再把固定 258K、Projection 或 `summarizer_unavailable` 写成当前生产事实；未运行项明确记录。

## T08：[遗留负担清理] 删除阶段性与兼容逻辑

### 任务目标

在全部能力和验证完成后删除被替代的阶段性实现、重复路径与兼容负担，并证明未扩大到 Out of Scope。

### 新增文件

无。

### 修改和删除文件

- 检查 `src/uthcode/core/context.py`、`core/history.py`、`core/__init__.py`、`application/context.py`、`application/generation.py`、`integrations/session_files.py`、commands、TUI usage rendering、tests/eval/docs 中的旧固定预算、Projection、Session v1、同步-only Compact 与旧文案。
- 删除所有失效导出、旧测试夹具、不可达分支、重复 request builder、compatibility alias/wrapper；只修改实际命中的文件。

### 文件职责及实施内容

- `rg` 证明生产源码、测试和当前事实文档不再把固定 258K 作为 authority，不再存在 Projection 生产 contract 或 old history.jsonl 新写入路径。
- 确认 Timeline 产品 record 只有三类，B′ 没有持久 state/job/pointer，compact 没有独立模型或跨 Provider fallback。
- 确认 Permission、Plan/Todo、Runtime Hook、其它 Slash Commands 和 TUI rendering 未被顺手重构。
- 确认无 Manager/Registry/Scheduler/Event Bus 等无真实调用方抽象，无 migration/dual read/write。
- 清理后重跑最小受影响测试、架构测试与全量回归；结果追加到 W06 Feedback。

### 依赖任务

T01～T07。

### 参考资料定位

- 原始需求第 17、18、20 节。
- `AGENTS.md` 增量开发、无兼容层与架构边界要求。

### 完成边界

旧阶段性逻辑与文本被彻底替代且无兼容层；清理不改变已验收产品语义，最终工作树仍由用户决定是否提交或归档。
