# 当前项目上下文索引

```text
context_kind: current-code-context
context_file: docs/Context-Index.md
snapshot_date: 2026-08-27
document_language: zh-CN
target_reader: coding-agent
source_of_truth: src/ + tests/
```

## Agent 读取协议

1. 先根据任务命中层级，只读下表对应的 `*-Context.md`。
2. 需要跨层修改时，再读取依赖层；不要默认遍历全部活跃工作包与 `docs/work/archive/`。
3. 本目录记录“当前代码事实”，不是需求、设计提案或兼容承诺。
4. 事实冲突时按以下优先级处理：`src/ + tests/` > 本目录 > 根 `README.md` > `docs/work/TXX-*` 活跃工作包 > `docs/work/archive/`。
5. `docs/work/` 表达活跃需求或实施记录；存在工作包不等于对应能力已经进入源码。
6. 四层是理解与检索视图，不是新的 Python 顶层包；源码仍遵守 `interfaces -> application -> core`，并由 `application` 组合 `integrations`。

## docs/context 路由

| 路径 | 文档性质 | Agent 读取条件 |
| --- | --- | --- |
| `docs/Context-Index.md` | 全局上下文入口、目录路由、任务包状态快照 | 任意新开发窗口先读 |
| [`docs/OutstandingDebtList.md`](OutstandingDebtList.md) | 能力欠账清单；记录各 `TXX` 因后置能力未实现而刻意未继续设计或实施的部分 | 拆分或重新拆分工作包、任务命中欠账触发条件、准备回补后置能力时读取并按规则维护 |
| `docs/context/A01-AgentRuntime/` | 执行层当前代码上下文 | Provider、Prompt、Tool、ReAct、Agent Loop 任务 |
| `docs/context/A02-Control/` | 控制层当前代码上下文 | Permission、审批、暂停恢复、Ask User、取消、Sandbox、Hook 任务 |
| `docs/context/A03-State/` | 状态层当前代码上下文 | Run/Turn、Event、Context、Memory、Todo/Plan、进度任务 |
| `docs/context/A04-Orchestration/` | 编排层当前代码上下文 | Application、入口、CLI/TUI、Subagent、任务拆分、Multi-Agent 任务 |
| `docs/context/TUI/` | 当前 TUI 的长期实现上下文；不是工作包 | 修改 TUI 交互、终端渲染、输入、滚动、暂停界面时读取 |
| `docs/work/` | 工作包根目录；直接子目录 `TXX-*` 保存活跃正式工作包，`archive/` 保存历史记录 | 收到需求文件、拆分任务包或执行用户指定 Worker Prompt 时按需读取；工作包规则见 `docs/rules/WorkPackageRules.md` |
| `docs/work/archive/` | 用户手动归档的已完成工作包；历史证据，不代表当前代码结构 | 当前事实不足、需要追溯已确认需求或历史验收证据时按需读取；禁止默认全量扫描 |

```text
path_migration:
  old_archive_root: docs/archive/work/
  current_archive_root: docs/work/archive/
  rule: 冻结或已归档的历史文档可能保留 old_archive_root 字面量；路径解析时映射到 current_archive_root，不为替换历史字面量而修改冻结文件
```

## 四层路由

| 层级 | 目录 | 图中职责 | 当前代码事实 | 首选任务关键词 |
| --- | --- | --- | --- | --- |
| 执行 | [`context/A01-AgentRuntime/AgentRuntime-Context.md`](context/A01-AgentRuntime/AgentRuntime-Context.md) | Provider、Tool、ReAct、Agent Loop、固定控制检查 | 已有单 Agent、显式串行 ReAct Runtime、固定 PLAN 非 READ 与 unfinished-task 控制检查 | Provider、Prompt、Tool、模型流、Agent Loop、工具调用、控制边界 |
| 控制 | [`context/A02-Control/Control-Context.md`](context/A02-Control/Control-Context.md) | 权限、Sandbox、Ask User、暂停恢复、Steering | 已有权限、Ask User、暂停恢复、取消、固定控制检查；无 OS Sandbox、动态控制 registry | Permission、审批、安全边界、暂停、恢复、询问用户、取消、Steering |
| 状态 | [`context/A03-State/State-Context.md`](context/A03-State/State-Context.md) | Context、Session History、Memory、Todo/Plan、任务进度、Steering | 已有进程内 Run/Turn、消息、事件、快照、Transcript/Timeline、动态 Context Budget/Gate（default 256K、configured/provider 收紧与 provenance）、Session v3 metadata、History append/reload/metadata touch 与 Instruction State 分阶段 persistence outcome、durable cursor；append 后异常先做结构化 identity reconciliation，未知 durability quarantine active Session writer，要求 close/reopen recovery 后才解除；真正 append 失败的 pending batch 保留原始 Session/Turn identity 并按 FIFO 重试；L4/L5、manual Compact、HistoryRead 与 overflow retry 已进入正式链路；无 Runtime checkpoint、Memory/retrieval | RunState、Turn、Event、Context、Snapshot、Usage、Session、Plan/Task、历史 |
| 编排 | [`context/A04-Orchestration/Orchestration-Context.md`](context/A04-Orchestration/Orchestration-Context.md) | Application、入口、CLI/TUI、Session、Plan/Task、Steering、Slash Mode | 已有单 Agent 应用编排、CLI/TUI 适配、Session ensure/close、`/plan`、`/do`、`/new`、`/resume`、`/compact`；Compact、overflow、Timeline aging 和 HistoryRead 均复用 Application orchestrator；status/diagnostics 与 FailureReason/PauseReason 投影由 Application 提供；无 Subagent、任务拆分器、Multi-Agent | Application、入口、组装、命令、TUI、CLI、Session、Plan/Task、Steering |

## current-status

```text
status_snapshot: 2026-08-27
status_scope: docs/work/TXX-* + docs/work/archive/
status_values:
  archived: 工作包已由用户移动至 docs/work/archive/
  implemented_unarchived: 当前源码已有实现，Checklist 全部完成且 Feedback 已记录，但目录仍在 docs/work/
  not_implemented: 需求或工作包仍在 docs/work/，且不满足 implemented_unarchived；未开始和部分实施统一归入此状态
```

### `archived`

| Task | 任务包 | 当前路径 |
| --- | --- | --- |
| T01 | 项目骨架与 Provider 抽象 | `docs/work/archive/T01-项目骨架与Provider抽象/` |
| T01-2 | 移除 pydantic，改用原生 SDK | `docs/work/archive/T01-2-移除pydantic改用原生SDK/` |
| T02 | Slash Command 与默认 TUI | `docs/work/archive/T02-SlashCommand与默认TUI/` |
| T03 | System Prompt 设计 | `docs/work/archive/T03-SystemPrompt设计/` |
| T04 | 工具系统 | `docs/work/archive/T04-工具系统/` |
| T05 | ReAct 与 Agent Loop | `docs/work/archive/T05-ReAct与AgentLoop/` |
| T06 | 暂停恢复与询问用户 | `docs/work/archive/T06-暂停恢复与询问用户/` |
| T07 | 三层权限系统 | `docs/work/archive/T07-三层权限系统/` |
| T07-1 | 权限分类与完全访问收口 | `docs/work/archive/T07-1-权限分类与完全访问收口/` |
| T08 | 任务规划与执行控制 | `docs/work/archive/T08-任务规划与执行控制/` |
| T08-1 | 阶段一扫尾 | `docs/work/archive/T08-1-阶段一扫尾/` |

### `implemented_unarchived`

| Task | 任务包 | 当前路径 | 当前证据 |
| --- | --- | --- | --- |
| B01 | 私有测试集 v0 | `docs/work/B01-私有测试集v0/` | W03 第二轮已关闭报告级 `task_sample_counts` 内部一致性阻断；Task 1～9 Checklist 已完成；Eval 77、定向 297、架构 23、全量 1084 passed/3 skipped；真实 baseline 仍需单独授权，工作包未归档 |
| T09 | Prompt 与 Context Engineering | `docs/work/T09-Prompt与ContextEngineering/` | W06 及定点返工接入 Session closed-fact persistence、Tool Result ref、Instruction State resume、分阶段 persistence outcome 与 Eval diagnostics；T09-1 在独立工作包中补齐 dynamic limits、Transcript/Timeline、生产 L4/L5、manual Compact、HistoryRead 与 overflow retry；T09 工作包未归档 |
| T09-1 | Context 预算与 Compact 协议补齐 | `docs/work/T09-1-Context预算与Compact协议补齐/` | T01～T08 Checklist 全部完成；W01～W06 Feedback 齐全；定向、架构和全量回归结果记录于 W06 Feedback；工作包未归档 |
| T09-2 | 工程收敛与提前抽象清理 | `docs/work/T09-2-工程收敛与提前抽象清理/` | W01 Task 1～9 Checklist 已完成；全量 `1189 passed, 3 skipped`、compileall/pip check/diff check/UTF-8 guard 均通过。用户已确认 `AGENTS.md` 的 57 行规则为本次交付基线，后续 T09-2 提交/推送一并纳入；工作包未归档 |
| T09-3 | 256K Context 工程调优与通用失败语义 | `docs/work/T09-3-256KContext工程调优与通用失败语义/` | W01～W05 Feedback 齐全，T01～T08 Checklist 已完成；Application 唯一主链已收口 default 256K/provenance、High→Low/L4/L5/overflow、Provider cache usage、FailureReason/PauseReason 与安全 diagnostics；定向、Eval、架构、全量、compileall、pip check、diff check 与 UTF-8 guard 结果记录于 W05 Feedback；工作包未归档 |

### `not_implemented`

| Task | 任务包 | 当前路径 | 当前证据 |
| --- | --- | --- | --- |

## 跨层最短链路

```text
interfaces/cli.py 或 interfaces/tui/app.py
  -> application/bootstrap.py:create_application
  -> application/generation.py:UthCodeApplication.ensure_session / create_run
  -> application/runs.py:AgentRun.start_turn
  -> core/agent.py:AgentLoop / AgentTurnExecution
  -> core/provider.py:ProviderPort
  -> core/tool.py:ToolExecutor
  -> core/permission.py:PermissionEvaluator
  -> application/runs.py:_TurnDriver
  -> AgentEvent 流 / TurnResult
```

配置 contract 当前事实：用户级 `config.toml` 使用 `default_model`、Provider `api_key`（literal 或 `env:VARIABLE_NAME`）、Model `remote_id`/`display_name`/可选 `reasoning_effort`；项目配置不得定义 Provider、端点或凭据等价字段。逻辑 Model Profile ID 仅用于界面和状态，AgentRun 与 direct generation 都把快照的 `remote_id` 写入 `GenerationRequest.model`；`/model` 原子写回只修改用户级 `default_model`。输入运行上限由 configured/provider/default 三类来源按收紧规则解析，未配置时 default 为 `256_000`，并在 Active Turn 内冻结。

## 全局禁止推断

- `[ABSENT]` LangGraph、LangChain Agent、图/DAG/工作流 DSL。
- `[ABSENT]` OS Sandbox；`Bash` 是当前用户权限下的未沙箱化进程执行。
- `[FACT]` 持久 Session Transcript/Timeline、Tool Result ref、Instruction State metadata、Context Compiler、dynamic Context Budget/Gate、bounded L4/L5 与 Runtime AGENTS / Project Instructions Loader 已进入正式链路；输入预算包含 `256_000` default、configured/provider 收紧及来源诊断，并在 Active Turn 内冻结；terminal Transcript 的 append/reload/last-used metadata touch 与 Instruction State sync 分开诊断，只有可判定 durable 的 message append 才推进 cursor，metadata 半失败不会回退；append 后无法 reconciliation 的未知批次会 quarantine active Session writer，新的 Run/语义写入均 fail closed，只有 close 后 fresh writer 验证/恢复才解除；真正 append 失败时才保留进程内 pending batch，按原始 Session/Turn identity FIFO 重试，不引入 Runtime checkpoint。Provider cache usage 与 terminal FailureReason/PauseReason 只以安全 Application 投影暴露，不把 native payload 或正文带入 diagnostics。
- `[ABSENT]` Persistent Runtime checkpoint、Memory、Dream、retrieval、Timeline physical GC、Artifact lifecycle、独立 compaction model、跨 Provider fallback、持久 Compact FSM/Job/pointer、Provider 能力自动发现 UI。
- `[FACT]` Agent Loop 的固定顺序已接入 PLAN 非 READ Tool 边界与 unfinished-task 完成阻断；普通 PLAN final 正常完成，正式 Plan Review 仅由 `ProposePlan` 控制 ToolCall 触发；不提供动态注册。
- `[ABSENT]` 动态 Hook registry、第三方 Hook plugin 生命周期、Skill、MCP、Worktree、Subagent、Multi-Agent、通用任务调度器。
- `[ABSENT]` 旧 API、旧数据结构、旧行为的兼容层；新增兼容入口默认不允许。
