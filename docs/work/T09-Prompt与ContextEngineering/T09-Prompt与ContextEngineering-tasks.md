# T09 Prompt 与 Context Engineering Tasks

## Worker 分组与执行顺序

| Worker | 严格串行 Task | 依赖 |
| --- | --- | --- |
| W01 Prompt / History / Session Foundation | Task 1 → 2 → 3 | 无 |
| W02 Tool Result / Context Compiler | Task 4 → 5 | W01 |
| W03 Compaction / Runtime Composition | Task 6 → 7 | W01、W02 |
| W04 Session Commands / TUI | Task 8 | W03 |
| W05 Eval Diagnostics | Task 9 | W03 |
| W06 Integration / Delivery | Task 10 → 11 → 12 | W04、W05 |

Worker 必须在同一组内严格按 Task 顺序执行。W04 与 W05 在 W03 完成后可分别开始，但两者的写入范围不得交叉；W06 必须等待两者全部完成。

## Task 1 — Prompt Asset 与 Core Runtime Contract 分离

**任务目标**

将可编辑的公共 Coding Prompt 迁入 package asset，保留 Core 强制 Runtime Contract 和动态 facts 的权威组装。

**新增、修改和删除的文件**

- 新增 `src/uthcode/prompt_assets/__init__.py`、`src/uthcode/prompt_assets/coding_agent.md`。
- 修改 `src/uthcode/core/prompt.py`、`pyproject.toml`、`tests/test_system_prompt.py`。
- 删除 Core 中已迁入 asset 的重复公共 Prompt 长文本，不删除 Runtime Contract。

**文件职责及实施内容**

- asset 包只提供唯一稳定读取入口，Markdown 只包含通用 Coding Agent 定位、工程、安全、沟通和真实性原则。
- Core 继续渲染 BehaviorMode、PLAN 边界、Plan/Task、RuntimeFeedback、Tool 真实能力与完成约束。
- 保证 stable prefix 和 package data 可在 source/wheel 中读取，不创建 Registry、Profile、Overlay 或用户目录加载器。

**依赖任务**

无。

**参考资料定位**

`docs/work/T09-Prompt与ContextEngineering/T09-Prompt与ContextEngineering.md` 第八、十四、十八节；`docs/context/A01-AgentRuntime/AgentRuntime-Context.md`；T03 归档 Spec/Feedback。

**完成边界**

Prompt asset 与 Runtime Contract 可独立测试，尚不引入 History/Context 持久化。

## Task 2 — Semantic History / Projection Core Contract

**任务目标**

建立 Provider-independent 的不可变语义交互与 Compact Projection 领域合同。

**新增、修改和删除的文件**

- 新增 `src/uthcode/core/history.py`、`tests/test_history_contract.py`。
- 按需修改 `src/uthcode/core/__init__.py`或相关包内导出，不扩张 Application 公共 API。

**文件职责及实施内容**

- 定义 strict versioned envelope、Session created、九类 Interaction 与 compact Projection。
- 验证 sequence、stable id、previous projection、covered/tail 边界和 ToolCall/ToolResult 完整语义单元。
- 排除 streaming delta、UI event、Provider SDK object、Exception、Future/Task 与 Todo 内部变化。

**依赖任务**

Task 1。

**参考资料定位**

T09 第六、十一、十二节；`src/uthcode/core/provider.py`、`src/uthcode/core/agent.py`及对应 JSON contract tests。

**完成边界**

只交付可 JSON round-trip 的 Core 领域值与边界验证，不读写文件系统。

## Task 3 — JSONL Session Files 与 Runtime Log

**任务目标**

实现 Session 级 durable append storage、Tool Result namespace 与当前项目 Session 发现/重建。

**新增、修改和删除的文件**

- 新增 `src/uthcode/integrations/session_files.py`、`src/uthcode/application/session_history.py`、`tests/test_session_files.py`。
- 按最小需要修改 `src/uthcode/application/__init__.py`、`src/uthcode/application/bootstrap.py`与相关 runtime tests。

**文件职责及实施内容**

- Integration 负责 history/runtime JSONL durable append、最后半写 fragment 容错、中间损坏硬失败和 result file 原子持久。
- Application 负责 Session identity、project key、语义提交、active projection、last-used 排序、首条 User Message preview 和 reconstruction。
- 以临时 root 测试并列 Session、跨 Session ref、跨进程式重建和 runtime log 非权威性。

**依赖任务**

Task 2。

**参考资料定位**

T09 第六、十一、十二、十三节；`docs/context/A03-State/State-Context.md`；T06 跨进程不恢复 active Turn 边界。

**完成边界**

完成存储与 Application reconstruction，不在本 Task 实现 TUI Picker 或 Runtime crash recovery。

## Task 4 — 大 Tool Result 外置与 ToolResultRead

**任务目标**

消除大结果永久截断，并在不扩大文件读取权限的前提下提供完整内容重读。

**新增、修改和删除的文件**

- 新增 `src/uthcode/integrations/tools/tool_result_read.py`、`tests/test_tool_result_persistence.py`。
- 修改 `src/uthcode/core/provider.py`、`src/uthcode/core/tool.py`、`src/uthcode/core/agent.py`、`src/uthcode/application/tools.py`、`src/uthcode/integrations/tools/factory.py`。
- 修改 `tests/test_provider_contract.py`、`tests/test_tool_core.py`、`tests/test_agent_loop.py` 及已绑定 Core 截断的 builtin Tool tests。

**文件职责及实施内容**

- ToolExecutor 交付完整结果；Application materializer 根据阈值选择 inline 或原子外置后的 bounded preview/ref。
- Provider-independent ToolResult metadata 不暴露磁盘路径；wire adapter 仍只发送模型需要的正文。
- ToolResultRead 为 PLAN 可见 READ_ONLY Tool，只接受当前 Session resolver 能解析的 opaque ref 与有界 range。

**依赖任务**

Task 3。

**参考资料定位**

T09 第六、十一、十二、十三节；T04/T05 归档资料；`tests/test_permission.py`中 workspace 外 READ 边界；Claude Agent SDK [large tool output issue](https://github.com/anthropics/claude-agent-sdk-typescript/issues/175) 仅作外置行为参考。

**完成边界**

先证明 full content 与 working view 分离，不建通用 Artifact Store、GC 或任意路径读取。

## Task 5 — Context Compiler、Budget 与 Working Set

**任务目标**

建立纯、确定、Provider-independent 的 Context Snapshot 编译链。

**新增、修改和删除的文件**

- 新增 `src/uthcode/core/context.py`、`tests/test_context_compiler.py`。
- 按最小需要修改 `src/uthcode/core/prompt.py`、`src/uthcode/core/provider.py` 的 Core 值组合边界。

**文件职责及实施内容**

- 固定五类 Source，不建动态 Registry 或万能 ContextItem。
- 在 258K 总窗口中纳入 Prompt、Contract、Projection、Runtime、Environment、History、ToolDefinition 估算、output reserve 和 safety margin。
- 实现保护项、recent raw tail、完整语义单元和被 Projection 覆盖 head 的选择规则，输出 JSON/display-safe diagnostics。

**依赖任务**

Task 4。

**参考资料定位**

T09 第八、九、十一节；OpenAI Codex [`compact.rs`](https://github.com/openai/codex/blob/main/codex-rs/core/src/compact.rs)；OpenCode [`session/compaction.ts`](https://github.com/sst/opencode/blob/dev/packages/opencode/src/session/compaction.ts)，仅作机制参考。

**完成边界**

相同输入产生相同预算内 Snapshot，但本 Task 不发起 Compactor 模型请求。

## Task 6 — 按需 Compactor 与 Projection Commit

**任务目标**

实现 manual/auto/reactive 的一次性模型 Compaction 和不可变 Projection 提交。

**新增、修改和删除的文件**

- 新增 `src/uthcode/application/context.py`、`tests/test_context_compaction.py`。
- 修改 `src/uthcode/application/generation.py`、`src/uthcode/application/runs.py`及相关 Application tests。

**文件职责及实施内容**

- Coordinator 冻结可压缩语义 head，以 prior summary + new stable records 发起 tool-free 单 Provider request，验证后才 append Projection。
- manual 仅 idle；auto 仅在正常请求前安全边界；Provider 明确 context overflow 时同一逻辑请求最多一次 compact/recompile/retry。
- 保留 recent raw tail；取消、失败、不完整流、ToolCall 或无效 summary 不改变旧 Projection。

**依赖任务**

Task 5。

**参考资料定位**

T09 第十、十三节；OpenAI Codex manual/auto compaction 当前源码；不复制其 Session 模型。

**完成边界**

不创建后台 Worker、Scheduler、Context Agent 或第二 Agent Loop。

## Task 7 — 跨 Turn Runtime State 与正式 Request Composition

**任务目标**

使 AgentLoop 的正式请求消费 ContextSnapshot，并收口 Task/Plan 跨 Turn 与 Compaction 语义。

**新增、修改和删除的文件**

- 修改 `src/uthcode/core/agent.py`、`src/uthcode/application/generation.py`、`src/uthcode/application/runs.py`。
- 修改 `tests/test_agent_loop.py`、`tests/test_application_runs.py`、`tests/test_application_runtime.py`及 T06/T08 相关回归测试。
- 删除正式 Agent Turn 的全量 `RunState.messages` 直通路径。

**文件职责及实施内容**

- RunState 仍为当前 Runtime authority 和唯一写入对象；Session History 在 Application 边界持续提交语义 Interaction。
- completed Turn 清理 active Task/Plan；failed/cancelled + unfinished Task 在同 Session 下一 Turn 延续，已批准计划按规则保留；one-shot feedback 不延续。
- 压缩只影响 History Projection，每次 Provider request 重新注入当前结构化 Runtime State。

**依赖任务**

Task 6。

**参考资料定位**

T09 第六、十一、十三节；`docs/context/A01-AgentRuntime/AgentRuntime-Context.md`、`docs/context/A03-State/State-Context.md`；T06/T08 归档边界。

**完成边界**

形成单一正式 request composition，不实现 Runtime State 跨进程 checkpoint。

## Task 8 — `/compact`、`/new`、`/resume` 与 TUI 产品闭环

**任务目标**

从 Application 命令到 TUI 完成已确认的 Session/Context 交互。

**新增、修改和删除的文件**

- 修改 `src/uthcode/application/commands/models.py`、`src/uthcode/application/commands/builtins.py`、`src/uthcode/application/session_history.py`、`src/uthcode/interfaces/tui/app.py`。
- 按现有 TUI 职责新增或修改一个最小 Session Picker 状态模块，不复制 Application 业务规则。
- 修改 `tests/test_command_dispatcher.py`、`tests/test_command_registry.py`、`tests/test_command_completion.py`、`tests/test_tui.py` 及 Session/Application tests。

**文件职责及实施内容**

- `/compact` idle-only；`/new` 创建新 Session/Run 且不改旧文件；`/resume` 获得当前 project key 候选并在 Enter 后才切换。
- Picker 每页 10 条，展示 last-used + 首条 User Message 单行摘要，按时间倒序，支持上下选择、左右翻页、Enter 恢复和 Esc 无副作用取消。
- `/status` 线性进度与输入区环形指示器使用同一 Application usage；unavailable 不伪造为零。`/clear` 仍只清界面投影。

**依赖任务**

Task 7。

**参考资料定位**

T09 第六点四、第十八节 Task 8；`docs/context/TUI/README.md`；`docs/context/A04-Orchestration/Orchestration-Context.md`。

**完成边界**

TUI 只投影结构化 Application result，不拥有 Session discovery、sort、reconstruction 或 Context estimator。

## Task 9 — B01 Context Diagnostics 与 Before/After Eval

**任务目标**

让 B01 可测量 Context 机制对长任务的收益或退化。

**新增、修改和删除的文件**

- 修改 `eval/metrics.py`、`eval/execution.py`、`tests/eval/test_eval_reporting.py`、`tests/eval/test_eval_execution.py`。
- 按需修改少量已有代表性 Eval fixture 和 `eval/README.md`，不改正式 CLI 或 CI。

**文件职责及实施内容**

- 从 Application 公开安全投影读取 compact count、estimated/actual input、selected/omitted interactions、evidence retention/rediscovery、repeated exploration、externalized count/bytes 和 read hits。
- 缺少事实时继续输出 `not_available`；确定性 diagnostics 进 pytest，概率性效果只进同实验指纹 compare。
- 保留 pre-context baseline 的可比较约束，不引入综合分、LLM Judge 或 CI gate。

**依赖任务**

Task 7。

**参考资料定位**

T09 第十八节 Task 9 和第十九节；B01 Spec/Tasks/Feedback；`docs/context/A04-Orchestration/Orchestration-Context.md`。

**完成边界**

不运行需远程模型的真实 baseline，除非用户另行授权并提供运行条件。

## Task 10 — [接入主流程] 正式 Composition 收口

**任务目标**

打通 Bootstrap → AgentRun → Context → AgentLoop → Provider 唯一正式路径。

**新增、修改和删除的文件**

- 修改 `src/uthcode/application/__init__.py`、`src/uthcode/application/bootstrap.py`、`src/uthcode/application/generation.py`、`src/uthcode/application/runs.py`、`src/uthcode/application/tools.py` 及相关 integration tests。
- 按各 Worker 实际接入结果修复最小集成缺口，删除被替代的旧入口和重复组合。

**文件职责及实施内容**

- 每个正式 Agent Turn 都绑定 Session History、Context Coordinator 和 run-local ToolResultRead/materializer。
- `/compact`/`/new`/`/resume` 仅经 Application；低层单次 generation 可保留，但不冒充 Session Agent 路径。
- 确认 Provider/model/tool/rule 的 Turn 快照语义、FIFO、Permission、Pause/Steering 和唯一 RunState writer 无回归。

**依赖任务**

Task 8、Task 9。

**参考资料定位**

T09 第十三、十四、十八节 Task 10；A01/A03/A04 current context。

**完成边界**

正式路径唯一，Headless 不依赖 TUI，不引入第二 Runtime。

## Task 11 — [端到端验证] Context / Compaction / Evidence

**任务目标**

用真实 Application/Fake Provider 路径验证 T09 完整产品行为与关键失败路径。

**新增、修改和删除的文件**

- 新增或修改一个按正式入口组织的 T09 E2E test，并修改已列单元/集成测试中的必要失败路径。
- 不为测试建立第二产品入口或真实用户目录副作用。

**文件职责及实施内容**

- 覆盖多 Turn、`/new`隔离、重建 Application 后当前项目 `/resume`、Picker 交互、same session id/history/projection/ref 和新 Turn。
- 覆盖 usage 同源、大结果完整持久/preview/ref/read，manual/auto/reactive 压缩，两次 Projection 追加，Task/Plan 独立与压缩失败不破坏。
- 执行定向测试、全量 pytest、compileall、pip check 和 architecture boundaries，记录精确结果。

**依赖任务**

Task 10。

**参考资料定位**

T09 第十八节 Task 11、第十九节和第二十一节。

**完成边界**

所有正面声明有实际执行证据；未授权的真实远程 Eval 明确列为未验证项。

## Task 12 — [遗留负担清理] 单历史 / 单 Context Path 收口

**任务目标**

清理旧职责、重复链路和误导文档，完成包级验收记录。

**新增、修改和删除的文件**

- 修改 `docs/Tools.md`、`docs/user-manual/commands.md`、命中 Context/Runtime 的 `docs/core-design/**`、`docs/context/A01-AgentRuntime/AgentRuntime-Context.md`、`docs/context/A03-State/State-Context.md`、`docs/context/A04-Orchestration/Orchestration-Context.md`、`docs/context/TUI/README.md`。
- 按 `docs/README.md` 维护映射检查根 `README.md`、相关用户手册与当前事实；只修改真正受影响文档。
- 修改本工作包 Checklist 中现有复选框状态，创建/append `feedback/W06-integration-delivery-feedback.md`。

**文件职责及实施内容**

- 扫描并删除 10k 永久截断、全量 messages 直通、Prompt 硬编码副本、三命令占位和无调用方抽象。
- 确认不存在 Interface history authority、Context 写 Task/Plan、AgentEvent 全量持久化、fake user compact summary、mutable history rewrite、SQLite、Scheduler、第二 Loop 或兼容层。
- 执行 UTF-8/replacement/mojibake/fence、内链、秘密示例、`git diff --check` 和 Git scope 检查；不执行 commit/push/archive。

**依赖任务**

Task 11。

**参考资料定位**

`docs/README.md` 文档维护映射；T09 第二十、二十一、二十三节；AGENTS.md 验证与交付约束。

**完成边界**

Checklist 只勾选有实际证据的现有项；Feedback 记录改动、命令、精确结果、未验证项、风险和遗留问题；等待用户手动归档。
