# T09 Prompt 与 Context Engineering Tasks

## Worker 分组与执行顺序

| Worker | 严格顺序 | 前置 Worker |
| --- | --- | --- |
| W01 | Task 1 → Task 2 → Task 3 | 无 |
| W02 | Task 4 → Task 5 | W01 |
| W03 | Task 6 → Task 7 | W01、W02 |
| W04 | Task 8 | W01～W03 |
| W05 | Task 9 | W01～W04 的公开 diagnostics contract；可与 W04 后半段只读核验，但不得交叉写文件 |
| W06 | Task 10 → Task 11 → Task 12 | W01～W05 |

Worker 内严格串行。每个 Worker 首次执行时创建同名 Feedback；未显式派发不得实施。

## Task 1：Prompt Asset、Context Source 与权限平面

- 任务目标：拆分 Public Prompt/Core Contract，定义稳定指令与上下文平面的统一强类型输入。
- 新增：`src/uthcode/prompt_assets/coding_agent.md`、`src/uthcode/prompt_assets/__init__.py`、必要的 Context block/source models 与 `tests/test_system_prompt.py`、Context contract tests。
- 修改：`src/uthcode/core/prompt.py` 及 package resource 配置。
- 删除：被 asset 替代的公共 Prompt 硬编码副本；不删除 Core Runtime Contract。
- 文件职责：Core 定义 provider-independent authority/stability/scope/provenance；asset 只拥有可编辑公共 Prompt；Tool schema 仍由 Tool System 唯一维护。
- 依赖：无。
- 参考：T03 归档包、`core/prompt.py`、`core/provider.py`、任务书第 5 节。
- 完成边界：稳定前缀与 Contextual Plane 顺序可测试；Projection/User/Tool 内容不能升级权限；未实现 Loader/History/Compiler。

## Task 2：AGENTS / Project Instructions Loader

- 任务目标：恢复历史冻结的 Runtime AGENTS 产品语义，并成为 ProjectInstructionSource。
- 新增：`src/uthcode/application/instructions.py`、`src/uthcode/integrations/instruction_files.py`、`tests/test_project_instructions.py`（具体稳定职责命名可按现有布局调整）。
- 修改：Application tool/run composition 中 session-start 与 Read/Edit 路径命中通知；架构测试。
- 删除：无；不得创建第二套裸 `@file` Loader。
- 文件职责：Integration 负责物理路径/文件读取；Application 负责 user/root/directory scope、惰性发现、epoch/去重；Core 只接收 instruction blocks。
- 依赖：Task 1。
- 参考：旧 `D:\project\UthCode\docs\work\Day7-记忆系统\` 的冻结语义与 `src/uthcode/instructions/` 实现证据；当前仓库 AGENTS.md 只作为开发约束。
- 完成边界：用户/项目/目录、整行 `@include(...)`、递归最多 3 个额外文件、物理身份去重、Windows case-fold、循环/越界/代码块忽略全部有失败路径；不复制旧 LangGraph 结构。

## Task 3：Canonical History 与 Projection 基础

- 任务目标：定义 append-only 语义历史、不可变 Projection、semantic unit 与 Runtime Log 非权威边界。
- 新增：`src/uthcode/core/history.py`、Application history value/orchestration 骨架、`tests/test_history_contract.py`。
- 修改：`core/provider.py` / `core/agent.py` 中形成完整 Interaction 所需的 provider-independent value 边界；不接文件存储。
- 删除：无。
- 文件职责：Core 定义 strict envelope/schema/kind/sequence/turn/call/ref 和原子 unit；Application 后续负责持久提交/active view。
- 依赖：Task 1。
- 参考：T04/T05/T08 当前事实、任务书第 4/11/13 节。
- 完成边界：ToolCall/ToolResult 不可拆；Projection 不回写 History、不提升权限；同进程 Runtime State 与跨进程 Session resume 合同明确。

## Task 4：Model Limits、Context Compiler 与确定性 Working Set

- 任务目标：解析真实模型限制，以 258K policy cap 编译确定性 Snapshot，并保护 prefix cache。
- 新增：`src/uthcode/application/model_limits.py`、`src/uthcode/application/context.py`、`src/uthcode/core/context.py`、精确 bundled model metadata 资源（若确有当前官方模型调用方）、`tests/test_model_limits.py`、`tests/test_context_compiler.py`。
- 修改：`application/configuration.py`、`integrations/config/loader.py`、`integrations/config/template.py`、bootstrap/provider composition 和必要 Provider resolver；配置与架构测试。
- 删除：固定 258K 作为物理窗口、overflow discovery、model-name substring 推断与“任务相关性”占位逻辑。
- 文件职责：Integration 只解析可靠 metadata；Application 统一来源/限制；Core Compiler 只消费 resolved limits 和 typed sources。
- 依赖：Task 1～3。
- 参考：现有 ModelProfile/config security、Provider integrations、Usage cache fields、任务书第 7/8 节。
- 完成边界：small/large/unknown model、project 不能提高可信上限、Protected Context、recent complete units、ref 跟随 unit、stable-prefix fingerprint 全部通过；无 retriever/embedding。

## Task 5：Session Store、durable append 与 single writer

- 任务目标：持久化完整提交边界的 History/Projection/Runtime Log，并保证每 Session 单写者。
- 新增：`src/uthcode/integrations/session_files.py`、完整 Application Session service、`tests/test_session_files.py`。
- 修改：`application/bootstrap.py` 与可注入 storage root/config；必要的 lifecycle close/new/resume 接口。
- 删除：可变 Projection pointer、mtime 产品排序、仅检查 lock 文件存在性的竞态实现。
- 文件职责：Integration 实现 history/runtime/result bytes、OS lock、fsync/atomic replace；Application 实现 project_key/catalog/reconstruction。
- 依赖：Task 3、Task 4 的 model/session metadata contract。
- 参考：任务书第 4.4/11 节、T06/T08 resume 边界。
- 完成边界：strict sequence、中段损坏、尾部半写、Runtime Log 丢失、跨项目隔离、并发子进程 resume 和 session busy 均有测试；不恢复 Task/Plan checkpoint。

## Task 6：大 Tool Result 外置与资源上限

- 任务目标：移除永久截断，以 bounded preview/ref 保留完整结果，并加入最薄磁盘资源上限。
- 新增：`src/uthcode/integrations/tools/tool_result_read.py`、`tests/test_tool_result_persistence.py`。
- 修改：`core/tool.py`、`core/provider.py`、`application/tools.py`、`application/runs.py`、`integrations/session_files.py`、tool factory 与既有 tool/provider tests。
- 删除：永久 10K 数据丢失路径和接受任意路径的读取可能性。
- 文件职责：Tool 仍返回完整领域结果；Application materialize；Integration durable write/read；ToolResultRead 只接受当前 Session opaque ref。
- 依赖：Task 3、Task 5。
- 参考：T04 Tool FIFO/Permission/call-id 合同、任务书第 9 节。
- 完成边界：用代表性输出/文件系统边界选择并在 Feedback 记录 inline/preview/single-result/session quota/read limit；quota 失败无 partial/dangling ref；不做 Artifact GC。

## Task 7：有界 Compaction 与 Runtime Request Composition

- 任务目标：让 Compactor 自身受预算约束，并使正式 Provider request 只消费 ContextSnapshot。
- 新增：`tests/test_context_compaction.py` 及必要 request composition tests。
- 修改：`application/context.py`、`application/generation.py`、`application/runs.py`、`core/agent.py` 与 Provider mapper tests。
- 删除：全量 `RunState.messages` 直通 Provider、无界压缩输入、动态 state 插入稳定前缀和无限 overflow retry。
- 文件职责：Application 组装 Sources、Compaction single-flight 与一次 overflow 保护；Core 保持唯一 RunState writer；Integration 仅 wire mapping。
- 依赖：Task 4、Task 6。
- 参考：T05 Agent Loop、T06/T08 lifecycle、任务书第 5/10 节。
- 完成边界：CompactionInputBudget/OutputReserve/SummaryHardCap、完整 unit 滚动分批、tool-free、失败不切 Projection、summary authority 和 provider-independent path 通过。

## Task 8：Session Slash Commands 与 TUI Context Status

- 任务目标：完成 `/compact`、`/new`、`/resume`、`/status` 和 Picker/ring 产品闭环。
- 新增：必要 Session Picker view/widget tests；不新增 Session 业务层。
- 修改：`application/commands/builtins.py`、command result models/dispatcher、`interfaces/tui/app.py`、TUI 状态/渲染与 command/TUI tests。
- 删除：三个命令的 NOT_IMPLEMENTED 占位；不改变 `/clear` 语义。
- 文件职责：Application 提供 UI-neutral action/catalog/usage；TUI 只持有页码/选择等临时状态并渲染。
- 依赖：Task 5、Task 7。
- 参考：T02 Slash/TUI、TUI Context docs、任务书第 11.1 节。
- 完成边界：同 project key、durable last-used、10 条/页、首 User preview、21 条分页、键盘/Esc、busy/recovery、same usage projection、窄终端与 Headless 全覆盖。

## Task 9：Context Diagnostics 与 Eval

- 任务目标：提供安全 Context/Prefix/Cache 事实和可重复 baseline/candidate Eval。
- 新增：必要 Eval fixture/case 与 diagnostics tests。
- 修改：`eval/metrics.py`、`eval/execution.py`、报告 schema/README、Application public diagnostics projection、Provider usage mapping tests。
- 删除：以字符/消息数猜测 Context、把缺失 cache metric 当实测 0、概率性质量 pytest 阈值。
- 文件职责：Application 暴露 JSON-safe/脱敏 facts；Eval 只消费公开投影。
- 依赖：Task 4、Task 7、Task 8 的公开 diagnostics contract。
- 参考：B01 Spec/Feedback、现有 Usage cache fields、任务书第 8.3/12 节。
- 完成边界：selected/omitted、compact、rediscovery、externalization、stable prefix、cache availability/provenance 和 runtime-only prefix 回归可比较；真实远程 baseline 仍需另行授权。

## Task 10：[接入主流程] 正式 Context Composition 收口

- 任务目标：把 Task 1～9 接入唯一正式 Headless/TUI 调用链并删除被替代入口。
- 新增：集成测试与 `feedback/W06-integration-delivery-feedback.md`。
- 修改：composition root、Generation/Application Run、tool/session/context/command 接线和相关当前事实文档。
- 删除：正式路径上的全量 messages 直通、永久 Tool 截断和命令占位。
- 文件职责：保持 `interfaces -> application -> core`，Application 组合 integrations。
- 依赖：Task 1～9。
- 参考：`docs/README.md` 维护映射、A01～A04/TUI current context。
- 完成边界：从 `create_application` 可完成多 Turn、外置/read、compact、重建 resume、final；架构测试通过。

## Task 11：[端到端验证] Context / Session / Prefix

- 任务目标：从真实入口验证正常和关键失败路径并执行全量回归。
- 新增/修改：T09 E2E fixtures/tests；只修复 T09 范围缺陷。
- 删除：无。
- 文件职责：E2E 证明产品行为，不复制单元实现。
- 依赖：Task 10。
- 参考：任务书第 12 节与 Checklist。
- 完成边界：prefix/authority/model limits/AGENTS/compactor overflow/concurrent resume/runtime boundary/quota/Picker 全通过；全量 pytest、compileall、pip check 记录精确结果。

## Task 12：[遗留负担清理] 单历史 / 单 Context Path 收口

- 任务目标：清理旧入口并完成任务包、代码、文档和欠账一致性。
- 新增：无。
- 修改：`docs/context/A01-AgentRuntime/`、`A03-State/`、`A04-Orchestration/`、`docs/context/TUI/`、`docs/UserManual.md`、`docs/Tools.md`、`docs/Context-Index.md`、`docs/OutstandingDebtList.md`、Tasks/Checklist/Feedback 状态。
- 删除：T09 替代的兼容壳、重复职责、不可达代码/测试和误导文案；不删无关历史。
- 文件职责：当前事实以最终 `src/ + tests/` 为准。
- 依赖：Task 11。
- 参考：WorkPackageRules、UTF-8 guard、任务书第 14/15 节。
- 完成边界：静态扫描、UTF-8/fence、链接、`git diff --check`、scope 审查通过；不归档、不执行 Git 写入。
