# T09-2 工程收敛与提前抽象清理 Tasks

## 1. Worker 与依赖

本工作包使用一个长期 Worker，在当前工作树严格串行执行全部任务；不创建分支、worktree、提交或归档。

| Worker | 严格串行 Task | 依赖 |
| --- | --- | --- |
| W01 `engineering-convergence` | Task 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 | 用户显式派发 W01 Prompt |

首次派发后，原始任务书、Spec、Tasks、Prompt 和 Checklist 文字冻结；Worker 只勾选 Checklist，并在 `feedback/W01-engineering-convergence-feedback.md` 追加实施记录。

## Task 1 — 正式 Run/Turn 入口收敛

### 任务目标

删除没有仓库内生产调用方的原始 generation facade，让 Application 只有正式 Run/Turn 生命周期。

### 新增、修改和删除的文件

- 修改 `src/uthcode/application/generation.py`、`application/__init__.py` 及直接依赖测试。
- 修改 Provider Adapter、Context Gate 和架构测试中仍调用旧 facade 的用例。
- 不修改 ProviderPort、AgentRun/TurnHandle/AgentEvent 合同。

### 文件职责及实施内容

- 删除 `GenerationHandle`、`start_generation`、`stream_generation`、`execute_tool_calls`、`compile_context`。
- 按调用图删除仅供上述 API 使用的同步 request preparation、stream/cancellation 包装与辅助分支。
- Provider 线协议测试直接调用相应 Provider；Application 行为测试改走 `create_run/start_turn`。
- 用架构测试断言旧方法与应用层导出不存在，不保留恒失败方法或弃用别名。

### 依赖任务

无。

### 参考资料定位

任务书决策 1～2；当前 `application/generation.py`、`application/runs.py`、CLI/TUI 与相关测试。

### 完成边界

旧 facade 生产与测试调用均为零；正式 Run/Turn 正常、取消、Provider 错误和模型快照行为通过。

## Task 2 — 固定 Runtime 控制收敛

### 任务目标

保留两个现实控制行为，删除无生产扩展者的通用 Hook 组合框架。

### 新增、修改和删除的文件

- 删除 `src/uthcode/core/hooks.py`。
- 修改 `core/agent.py`、`core/__init__.py`、`application/tools.py` 及 Hook/AgentLoop 测试。

### 文件职责及实施内容

- 删除 Hook Protocol、Context/Result、Reason、HookSet、默认/自定义组合与 callable 校验。
- 删除 AgentLoop `runtime_hooks` 参数、Application 私有空 HookSet 和 Hook failure 专用分支。
- 在 trusted preflight 后、Permission 前直接检查 `PLAN && effect != READ`，保持当前受控 ToolResult 文本。
- 在 candidate final 的 usage accounting 后直接检查 DEFAULT unfinished Task，保持 RuntimeFeedback、CompletionBlocked 和继续迭代语义。

### 依赖任务

Task 1。

### 参考资料定位

当前 `core/hooks.py` 与 `core/agent.py` 两个调用点；T08 只作为历史证据，不修改归档文件。

### 完成边界

没有 Hook 注入或动态组合符号；PLAN/full_access 与 completion control 回归通过。

## Task 3 — Context 合同单轨化

### 任务目标

让 Context 来源和编译入口与正式 Application 组装方式一致。

### 新增、修改和删除的文件

- 修改 `core/prompt.py`、`core/context.py`、`core/__init__.py`、`application/context.py`、`application/generation.py` 及 Context 测试。

### 文件职责及实施内容

- 删除 `_TextContextSource` 和五个身份包装；直接构造 `ContextBlock`。
- 保留 `ProjectInstructionSource`、`ToolDefinitionSource` 和 ContextBlock authority/plane 校验。
- Bundle 强类型化；Compiler 只接受 Bundle 与 previous snapshot，删除独立参数和任意 `to_context_block`。
- estimator 统一为 callable，`DeterministicTokenEstimator` 使用 `__call__`。
- Compactor 构造只保留 `CompactionPolicy` 和 callable estimator；删除 Application 同步 compact facade，保留 async 生产链。

### 依赖任务

Task 2。

### 参考资料定位

当前 `application/context.py` 正式 Bundle 组装、`core/context.py` Compiler/Compactor、T09/T09-1 当前事实文档。

### 完成边界

Context 安全、预算、Hard Gate、异步 Compact 与 Provider count 行为不变；多形态入口扫描为零。

## Task 4 — Session v3 硬切

### 任务目标

删除无生产事实的 RuntimeLog，并让持久布局准确反映当前可恢复状态。

### 新增、修改和删除的文件

- 修改 `core/history.py`、`application/history.py`、`application/sessions.py`、`integrations/session_files.py`、相关导出和 Session 测试。

### 文件职责及实施内容

- 删除 ApplicationHistory、RuntimeLog/Entry 及 runtime 属性、追加、序列、tail 修复与诊断。
- 保留生产消息到 Transcript 的转换函数并改为内部辅助。
- 将 Session metadata schema 升为 3；record envelope 仍为 2。
- v3 不创建、不要求、不读取 `runtime.jsonl`；v1/v2 明确 `SessionIncompatibleError`，未知损坏继续 fail closed。
- 保持 Transcript/Timeline append、reconciliation、quarantine、Instruction State 和 Tool Result 不变。

### 依赖任务

Task 3。

### 参考资料定位

任务书决策 3；当前 Session v2 实现与 `docs/core-design/T09-context-engineering.md`。

### 完成边界

v3 新建、恢复、尾部修复和 `/resume` 通过；v2 不迁移且稳定拒绝。

## Task 5 — 命令系统收敛

### 任务目标

让 Registry、Parser、Dispatcher、Help 和 Completion 只表达已实现命令。

### 新增、修改和删除的文件

- 修改 `application/commands/**`、TUI 命令消费与命令/TUI 测试。

### 文件职责及实施内容

- 删除五个占位命令、CommandAvailability、NOT_IMPLEMENTED、PROMPT、query/separator 与 Prompt Outcome。
- 所有 CommandDefinition 必须有 handler；CompletionCandidate 不再携带实现状态。
- 删除同步 dispatch/dispatch_text，只保留 async 入口；现有同步测试改为 await。
- TUI 删除 outcome.prompt 分支；被删命令返回普通 UNKNOWN_COMMAND。

### 依赖任务

Task 4。

### 参考资料定位

当前 command models/parser/dispatcher/builtins/completion 与 `docs/user-manual/commands.md`。

### 完成边界

Help/Completion 不显示未来能力；所有现存命令正常，额外参数仍受控 usage error。

## Task 6 — 定点公共边界清理

### 任务目标

只删除已确认冗余设计产生的公共符号，不扩大为全量 API 重构。

### 新增、修改和删除的文件

- 修改 Core、Application、Commands 包导出和 `tests/test_package.py`。
- 修改 Provider/Tool capability 定义处及对应测试。

### 文件职责及实施内容

- 删除三个未被引用的 capability Protocol，保留现有 `getattr` 能力探测。
- 从导出表移除 Tasks 1～5 删除的 facade、Hook、RuntimeLog、Context 包装和命令类型。
- 其他现有导出名称与顺序不主动重排。

### 依赖任务

Task 5。

### 参考资料定位

当前 `core/__init__.py`、`application/__init__.py`、`commands/__init__.py` 与 package tests。

### 完成边界

删除项无法从包根导入；Interfaces/Eval 所需现有 Application facade 全部保留。

## Task 7 `[接入主流程]` — 正式组合与文档同步

### 任务目标

把六项收敛接回唯一正式入口，并同步所有当前事实文档。

### 新增、修改和删除的文件

- 修改 composition/architecture tests 和命中的 `docs/context/**`、核心设计、命令手册、Context Index。
- 不修改 T02/T05/T08/T09/T09-1 冻结任务包正文、Spec、Tasks、Prompt 或 Checklist。

### 文件职责及实施内容

- 验证 CLI/TUI/Eval 均只走 Run/Turn，Interface 不依赖 Core internal 或 Integration。
- 文档把 RuntimeHookSet 改为固定控制检查，把 Session layout 改为 v3，删除手工 Tool API 墓碑和未来命令文案。
- 保持当前配置、Provider、Tool、Permission、Compact 与 Eval 事实不变。

### 依赖任务

Task 6。

### 参考资料定位

`docs/README.md` 维护映射、Context Index、A01～A04 Context、T09 核心设计和命令手册。

### 完成边界

代码和活动文档描述一致，正式路径无旧符号。

## Task 8 `[端到端验证]` — Headless、Session 与 TUI 验收

### 任务目标

从真实组合入口验证删除抽象后产品行为完整。

### 新增、修改和删除的文件

- 修改或新增最小正式 E2E 测试；不新增测试专用生产接口。

### 文件职责及实施内容

- Fake Provider + 临时工作区验证 Run/Turn、Tool、PLAN、Task completion、cancel 与 terminal。
- 新建 v3 Session 后完成 Turn、Compact、关闭、重新打开并 `/resume`；确认 Transcript/Timeline/Tool Result 与 Instruction State 正确。
- TUI 验证异步命令、帮助、补全和被删命令 unknown。

### 依赖任务

Task 7。

### 参考资料定位

现有 T08、T09、T09-1 E2E 与 CLI/TUI 测试模式。

### 完成边界

离线真实入口全部通过，无第二状态或测试旁路。

## Task 9 `[遗留负担清理]` — 否定扫描与全量回归

### 任务目标

完成旧测试/文案清理、能力欠账维护和全仓验收。

### 新增、修改和删除的文件

- 修改 Checklist、W01 Feedback、`docs/OutstandingDebtList.md` 和 `docs/Context-Index.md`。
- 删除只验证被删扩展面的测试；保留并迁移实际行为测试。

### 文件职责及实施内容

- 删除 T02 占位命令债务与 T08 假设性 Hook 扩展债务；T09-2 能力欠账保持“无”。
- 将 T09-2 状态更新为 implemented_unarchived；不得归档。
- 运行否定扫描、架构、定向、Eval、全量、compileall、pip check、diff check 与 UTF-8 guard。

### 依赖任务

Task 8。

### 参考资料定位

本工作包 Checklist、WorkPackageRules、OutstandingDebtList 与 Context Index。

### 完成边界

所有验收有精确结果，工作树仅包含本任务改动，无 Git 写操作或未声明遗留问题。
