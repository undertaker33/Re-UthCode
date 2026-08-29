# T09-1：Context 预算与 Compact 协议补齐 Tasks

## Worker 分组、顺序与依赖

| Worker | 执行任务 | 前置 | 并行边界 |
|---|---|---|---|
| W01 | T01 | 无 | 独占动态 limits、Gate、Compiler 与正式请求安全链 |
| W02 | T02 | T01 | 独占 History/Session v2 硬切；不得与 T01 并行修改 Context 调用链 |
| W03 | T03 | T02 | 独占生产 L4/bounded catch-up |
| W04 | T04 | T03 | 独占 L5 与 HistoryRead |
| W05 | T05 → T06 | T04 | 先完成 Application/Headless，再接命令/TUI/正式入口 |
| W06 | T07 → T08 | T06 | 先验收与文档，再做最终旧路径清理 |

任何 Worker 都必须先完整读取任务书、Spec、Tasks、Checklist 和自己的 Prompt。禁止提前勾选后续任务；失败结果写入本 Worker Feedback，不伪造通过。

## T01：动态模型限制与确定性请求安全链

### 任务目标

在一个可独立运行、测试、审查和回退的竖切任务中，完成配置权威、Provider 分维 limits、Pressure/Preflight 计数语义、Auto/Hard Gate、L1-L3 及正式请求链，彻底移除固定 258K runtime authority。

### 新增文件

- `tests/test_provider_model_limits.py`
- `tests/test_context_budget_gate.py`

### 修改文件

- `src/uthcode/core/context.py`、`src/uthcode/core/provider.py`、`src/uthcode/core/__init__.py`
- `src/uthcode/application/configuration.py`、`context.py`、`generation.py`、`bootstrap.py`
- `src/uthcode/integrations/config/loader.py`、`config/template.py`、`providers/config.py`、`providers/factory.py`
- 仅确有可靠 runtime metadata 的 Provider integration；Anthropic 使用可替换 fake client 测试，OpenAI/Compat 未知时保持 unknown
- `tests/test_configuration.py`、`test_config_loader_integration.py`、`test_context_compiler.py`、`test_application_runtime.py`、`test_application_runs.py`、`test_agent_loop.py` 及实际受影响 Provider tests

### 删除文件

- 无预设整文件删除；删除固定常量导出、硬校验和仅服务于固定预算的不可达分支。

### 文件职责及实施内容

- 用户配置 `context_window` 只接受 positive int；项目 overlay 只能在用户已有值时保持/收紧，补造或扩大硬失败。
- 不建立 bundled metadata、本地型号表、模型目录或硬编码 fallback。用户 input limit 与可靠 Provider input limit 至少一项存在，否则当前模型不可发送。
- UthCode-owned limits DTO 分开表达 configured input、provider max input、provider max output、optional combined；unknown 保持 unknown，Provider overflow 不反向学习。
- 集中 policy 生成 adaptive caps、Pressure Estimate、Preflight Safety Count/Estimate 和 allowance。近似 count 只能作为安全估计，不标称 exact。
- final candidate request accounting 覆盖 instruction、messages、tools、known framing、requested output reserve；input/output/combined 三个约束各自 Gate。
- 实现确定性 L1 ToolResult externalization、L2 bounded preview shrink/mask、L3 complete inactive semantic-unit omission；保护 current/protected/tool pair。
- 每次 reduction 后 rebuild/re-gate；unresolvable required facts fail closed，Provider call count 为 0。
- 正式接通 Application→Compiler→现有 request preparer→AgentLoop→ProviderPort。`core/agent.py` 已支持 sync/awaitable preparer/overflow；原则上不修改，只保留复用、取消、错误回归测试。

### 依赖任务

- 无。

### 参考资料定位

- 任务书第 4.1、4.4、7、10～12、15、16 节。
- 当前 `application/configuration.py`、`integrations/config/loader.py` 的 user/project merge。
- 当前 `core/context.py` 固定预算与 `application/generation.py::_prepare_request` 正式链。

### 完成边界

不依赖 Transcript/Timeline/L4 即可从正式 Application 路径完成 dynamic limit、final preflight、L1-L3 和 Provider call/fail-closed；不存在生产 258K 或 bundled metadata fallback。

## T02：Transcript、Timeline 与 Session v2 一次性硬切

### 任务目标

一次性替换 History authority、Session layout 及全部生产调用方，确保本任务结束时不存在“新模型已定义但 Compiler/Application 仍依赖旧 Projection”的半成品状态。

### 新增文件

- `tests/test_timeline_contract.py`

### 修改文件

- `src/uthcode/core/history.py`、`context.py`、`prompt.py`、`core/__init__.py`
- `src/uthcode/application/history.py`、`context.py`、`generation.py`、`sessions.py` 及真实调用方
- `src/uthcode/integrations/session_files.py`
- `tests/test_history_contract.py`、`test_context_compiler.py`、`test_context_compaction.py`、`test_session_files.py`、`test_application_runtime.py`、`test_application_runs.py`、`test_w04_session_commands.py` 及旧 history consumers

### 删除文件

- 无预设整文件删除；删除 `CanonicalHistory`、`Projection` 导出、旧 `history.jsonl` 新写入和为其服务的生产路径。

### 文件职责及实施内容

- Transcript 只保存 current Session closed raw semantic facts；ref opaque、顺序严格、ToolCall/ToolResult 组完整。
- Timeline 只允许 Fine、Epoch Macro、Active Checkpoint；checkpoint-last 决定 logical view，trailing transaction 不生效。
- Session v2 fresh layout 分离 transcript/timeline/runtime/tool-results；old v1 明确 incompatible，不迁移、不双读写。
- 同任务迁移 Context source/compiler、Application generation/history/session、store reconciliation、diagnostics fixture 与正式测试。
- 保持 single writer、append+fsync、metadata-last、unknown durability quarantine、identity reconciliation 和 close/reopen recovery。

### 依赖任务

- T01。

### 参考资料定位

- 任务书第 4.1、7、9～13、15、16 节。
- 当前 `core/history.py`、`application/context.py`、`integrations/session_files.py`。

### 完成边界

fresh Session 可完整 create/run/persist/resume；所有生产 callers 都以 Transcript/Timeline 为 authority；old v1 只得到明确 incompatible，旧 Projection/CanonicalHistory 不再可达。

## T03：生产 L4 与 bounded catch-up

### 任务目标

把现有 Compactor 提升为正式 tool-free L4，并在同一 Application 调用栈实现有限多 epoch catch-up、checkpoint-last commit 和每批 rebuild/re-gate。

### 新增文件

- `tests/test_t09_1_context_protocol_e2e.py`（建立 L4 场景骨架，后续任务继续扩展）

### 修改文件

- `src/uthcode/core/compaction.py`、`src/uthcode/core/context.py`
- `src/uthcode/application/context.py`、`generation.py`、`sessions.py`
- `tests/test_context_compaction.py`、`test_context_budget_gate.py`、`test_application_runs.py`、`test_t09_1_context_protocol_e2e.py`

### 删除文件

- 删除 `summarizer_unavailable` 等仅代表旧未接线阶段的路径和测试。

### 文件职责及实施内容

- active Turn 使用冻结 main provider/model/limits；idle manual 使用当前选择，不引入 compaction model/fallback。
- L4 request 独立、tool-free、bounded，发送前只做 Hard Gate，不递归 Auto compact。
- 结构化结果必须覆盖所选完整 Turns，refs/coverage/summary 校验通过才 append Fine entries，checkpoint 最后落盘。
- 一个 orchestration 可处理多个 safe epoch；每次 commit 后 rebuild 并重做 Pressure/Hard Gate。
- retained target 留出有效 headroom；no progress/repeated failure/no safe epoch/cancel 有 finite breaker 和安全 diagnostics。
- Auto unresolved 但 Hard-safe 可继续普通调用并记录原因；Hard-unsafe 不调用 Provider。

### 依赖任务

- T02。

### 参考资料定位

- 任务书第 4.2、4.3、4.5、7.1、11.9～12.5、15、16 节。

### 完成边界

正式 Application 可完成单/多 epoch L4，失败与取消无伪提交，无持久 Compact FSM/Job/pointer。

## T04：L5 Timeline Aging 与 HistoryRead

### 任务目标

完成 Fine Timeline 独立老化和 current-Session raw evidence 精确回读，使长期 compact 视图可控但原始证据仍按需可得。

### 新增文件

- `src/uthcode/integrations/tools/history_read.py`
- `tests/test_history_read_tool.py`

### 修改文件

- `src/uthcode/core/compaction.py`、`context.py`
- `src/uthcode/application/context.py`、`generation.py`、`tools.py`、`sessions.py`
- `src/uthcode/integrations/tools/__init__.py`
- `tests/test_timeline_contract.py`、`test_context_compaction.py`、`test_application_tools.py`、`test_tool_result_persistence.py`

### 删除文件

- 无预设整文件删除。

### 文件职责及实施内容

- Fine budget 独立评估，即使普通 request 不处于 Auto pressure 也可触发 L5。
- 只选择 old complete epoch；按 Transcript refs 重新读取 raw evidence，禁止 summary-of-summary。
- macro-first/checkpoint-last；logical supersede 不删除物理 Fine records。
- HistoryRead 参数只接受 active Session opaque exact ref 和 bounded paging；不搜索、不跨 Session、不递归外置。
- HistoryRead 与 ToolResultRead 的 ref namespace、授权和错误边界清晰分离。

### 依赖任务

- T03。

### 参考资料定位

- 任务书第 4.7、7、11.10、12.6～12.8、15、16 节。

### 完成边界

L5 与 HistoryRead 可通过 Application/ToolService 独立运行和测试；没有后台任务、GC、retrieval index 或第四种 Timeline record。

## T05：Application Compact 生命周期与 overflow recovery

### 任务目标

把 closed-fact persistence、Turn limit snapshot、manual compact 和一次 overflow recovery 收到可独立使用的 Application/Headless 边界；不等待命令/TUI 才形成可运行能力。

### 新增文件

- 无。

### 修改文件

- `src/uthcode/application/generation.py`、`context.py`、`sessions.py`、`history.py`、`tools.py`
- `src/uthcode/application/bootstrap.py`（只接 Application 组合所需依赖）
- `tests/test_application_runtime.py`、`test_application_runs.py`、`test_session_files.py`、`test_t09_1_context_protocol_e2e.py`

### 删除文件

- 删除旧 application compact placeholder 或重复 overflow composition path。

### 文件职责及实施内容

- first Provider call 前、complete tool batch 后/next call 前、terminal tail 增量持久化 closed facts；不写 open continuation。
- durable cursor 防重复；确定失败保持 identity/FIFO retry；unknown durability quarantine 后续语义写入。
- active Turn 冻结 provider/model/configured/effective/provider limits/output/tools；模型切换只影响下一 Turn。
- 公开 async Application compact API 复用 T03/T04 orchestrator；低 pressure 仍允许有价值 compact，无候选 success no-op。
- ordinary ContextOverflow 只允许一次 forced reduction→rebuild→Hard Gate→retry；第二次失败，不修改 limit facts。
- 复用 `AgentLoop` 已存在的 awaitable hook；不把 async support 作为新增 Core 能力。

### 依赖任务

- T04。

### 参考资料定位

- 任务书第 4.6、4.8、6、12、13、15、16 节。
- 当前 `core/agent.py` awaitable preparer/overflow 实现与相关测试。

### 完成边界

Headless/Application 正式入口可覆盖 ordinary/post-tool/resume/manual/overflow；命令和 TUI 尚未接入也不影响本任务独立验收。

## T06：[接入主流程] 命令、TUI 与正式入口收口

### 任务目标

把 T05 能力接入 slash command、CLI、TUI 和最终 bootstrap 组合，删除旧同步-only Compact 入口；Interface 不复制 Context 语义。

### 新增文件

- 无。

### 修改文件

- `src/uthcode/application/commands/dispatcher.py`、`commands/builtins.py`、`commands/registry.py`（按真实结构最小修改）
- `src/uthcode/application/bootstrap.py`、`generation.py`
- `src/uthcode/interfaces/cli.py`、`src/uthcode/interfaces/tui/app.py`（按实际文件名）
- `tests/test_command_dispatcher.py`、`test_w04_session_commands.py`、`test_cli.py`、`test_tui.py`、`test_application_runtime.py`、`test_t09_1_context_protocol_e2e.py`

### 删除文件

- 删除旧 `/compact` placeholder、同步-only handler 路径及重复正式入口。

### 文件职责及实施内容

- dispatcher 只为必要 handler 支持 awaitable outcome，同步命令行为保持。
- `/compact` 调用 T05 Application API；`/status` 只显示安全的分维 limits/Gate/Timeline/outcome。
- TUI 只 await Application command；CLI/TUI/Headless 全部复用同一生成和 Hard Gate 入口。
- bootstrap 注入完整依赖，不在 Interface 构造 Provider、Store 或 compactor。
- 回归现有 request preparer/overflow awaitable、cancel/error tests，证明没有重复协议。

### 依赖任务

- T05。

### 参考资料定位

- 任务书第 6、7、9、10、12、13、15、16 节。

### 完成边界

正式 CLI/TUI/Headless 均已接通；同步命令无回退；旧入口删除且 Interface 无 Context ownership。

## T07：[端到端验证] Diagnostics、Eval、文档与回归

### 任务目标

从正式入口完成跨层验收，收敛安全 diagnostics、Eval consumer 和所有相关当前事实文档。

### 新增文件

- 无预设新增。

### 修改文件

- `src/uthcode/application/context.py`、`generation.py`、`sessions.py` 中 diagnostics projection（仅验收发现的必要修正）
- `eval/metrics.py` 与现有 Eval fixtures
- `docs/Tools.md`、`docs/user-manual/configuration.md`、`docs/user-manual/commands.md`
- `docs/core-design/T09-context-engineering.md`、`docs/current/A03-agent-runtime.md`、`docs/current/A04-infrastructure.md`、`docs/Context-Index.md`
- `tests/test_w05_diagnostics.py`、`test_w06_integration_delivery.py`、`test_t09_1_context_protocol_e2e.py`、`test_architecture_boundaries.py`

### 删除文件

- 删除当前事实文档中的旧 authority/阶段性描述；不改冻结历史需求和归档证据。

### 文件职责及实施内容

- public diagnostics 只包含分维 limits、source/allowance、Gate、Timeline id/coverage、reason/outcome；不含 raw/summary/tool result/secret/exception body。
- Eval 延续 success/token/tool calls/compaction/pressure 等并列指标，不新增 total score。
- E2E 从正式 headless/command 路径覆盖 ordinary、tool loop、L4/catch-up、L5、HistoryRead、manual、overflow once、hard fail、resume。
- 按 `docs/README.md` 维护映射同步 Tools、用户手册、Core Design、A03/A04 与索引。
- 执行定向、架构、T05/T06/T08 回归和全量测试，Feedback 记录精确命令与统计。

### 依赖任务

- T06。

### 参考资料定位

- 任务书第 1、8、13、16、18 节；`docs/README.md` 文档维护映射。

### 完成边界

正式入口和失败路径有可复现测试结果；所有当前事实文档与实现一致；未运行项明确记录，不把网络测试描述为通过。

## T08：[遗留负担清理] 删除阶段性与兼容逻辑

### 任务目标

只在 T07 验收基础上删除旧 authority、兼容残留、取消路线和无调用方抽象，确认最终仓库只有一条生产路径。

### 新增文件

- 无。

### 修改和删除文件

- 按 `rg` 与调用图结果修改/删除 `src/`、`tests/`、`eval/`、当前事实 `docs/` 中确认无调用方的旧路径。
- `docs/OutstandingDebtList.md`：确认已取消的 bundled official metadata 路线持续不存在；重新盘点所有被 T09-1 实际改变的条目，按完全回补、部分改变、仍成立或用户取消分别删除、更新、保留或删除且不转登记。
- `docs/Context-Index.md`：全部完成后更新为 `implemented_unarchived`，不自动归档。

### 文件职责及实施内容

- 证明 production 固定 258K、Projection/CanonicalHistory、old history writer、sync-only compact、`summarizer_unavailable` 为零。
- 证明 bundled metadata/catalog/hardcoded official model window 路线在源码、测试、当前事实文档和欠账清单中为零，且未转登记为 future debt。
- 逐条复核 `T02 Slash Command / TUI`：只移除已回补的 `/compact` 部分，继续保留仍成立的 `/memory`、`/dream`；复核 `B01 私有测试集 v0` 中“生产 Compaction 不可运行/无可比较结果”的部分，按真实验收删除或更新。
- 三条 T09 Context 回补欠账仅在实现完成、对应 Checklist 完成且 Feedback 有真实验收记录时删除；其它受影响条目部分改变时只改内容或触发条件，禁止因部分完成整条误删。
- 证明 Timeline record 恰为三类，catch-up 无持久 FSM，Compact 无独立 model/provider fallback。
- 删除重复 export/wrapper/alias/unreachable branch；保护 Permission、Plan/Todo、Hook、其它命令和 TUI rendering。
- 清理后重跑定向、架构和全量测试；精确结果写入 W06 Feedback。

### 依赖任务

- T07。

### 参考资料定位

- 任务书第 5、17～20 节；Checklist T08；`docs/OutstandingDebtList.md`。

### 完成边界

旧路径与取消路线扫描满足 Checklist，回归通过并有 Feedback；索引为 `implemented_unarchived`，工作包保留等待用户手动归档。
