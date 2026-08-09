# 当前项目上下文索引

```text
context_kind: current-code-context
context_file: docs/Context-Index.md
snapshot_date: 2026-08-09
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

## docs 根目录路由

| 路径 | 文档性质 | Agent 读取条件 |
| --- | --- | --- |
| `docs/Context-Index.md` | 全局上下文入口、目录路由、任务包状态快照 | 任意新开发窗口先读 |
| `docs/A01-AgentRuntime/` | 执行层当前代码上下文 | Provider、Prompt、Tool、ReAct、Agent Loop 任务 |
| `docs/A02-Control/` | 控制层当前代码上下文 | Permission、审批、暂停恢复、Ask User、取消、Sandbox、Hook 任务 |
| `docs/A03-State/` | 状态层当前代码上下文 | Run/Turn、Event、Context、Memory、Todo/Plan、进度任务 |
| `docs/A04-Orchestration/` | 编排层当前代码上下文 | Application、入口、CLI/TUI、Subagent、任务拆分、Multi-Agent 任务 |
| `docs/TUI/` | 当前 TUI 的长期实现上下文；不是工作包 | 修改 TUI 交互、终端渲染、输入、滚动、暂停界面时读取 |
| `docs/work/` | 工作包根目录；`README.md` 保存规则，直接子目录 `TXX-*` 保存活跃正式工作包 | 收到需求文件、拆分任务包或执行用户指定 Worker Prompt 时读取；先读 `docs/work/README.md` |
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
| 执行 | [`A01-AgentRuntime/AgentRuntime-Context.md`](A01-AgentRuntime/AgentRuntime-Context.md) | Provider、Tool、ReAct、Agent Loop | 已有单 Agent、显式串行 ReAct Runtime | Provider、Prompt、Tool、模型流、Agent Loop、工具调用 |
| 控制 | [`A02-Control/Control-Context.md`](A02-Control/Control-Context.md) | 权限、Sandbox、Hook、Ask User、暂停恢复 | 已有权限、Ask User、暂停恢复、取消；无 OS Sandbox、无 Hook | Permission、审批、安全边界、暂停、恢复、询问用户、取消 |
| 状态 | [`A03-State/State-Context.md`](A03-State/State-Context.md) | Context、Memory、Todo/Plan、任务进度 | 已有进程内 Run/Turn、消息、事件、快照；无持久 Session、Memory、Todo/Plan | RunState、Turn、Event、Context、Snapshot、Usage、历史 |
| 编排 | [`A04-Orchestration/Orchestration-Context.md`](A04-Orchestration/Orchestration-Context.md) | Subagent、任务拆分、Multi-Agent | 已有单 Agent 应用编排和 CLI/TUI 适配；无 Subagent、任务拆分器、Multi-Agent | Application、入口、组装、命令、TUI、CLI、并发 Agent |

## current-status

```text
status_snapshot: 2026-08-09
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

### `implemented_unarchived`

| Task | 任务包 | 当前路径 | 当前证据 |
| --- | --- | --- | --- |
| T04 | 工具系统 | `docs/work/T04-工具系统/` | Checklist `62/62`；4 份 Feedback；`src/uthcode/core/tool.py` 与 `src/uthcode/integrations/tools/` 已接入 |
| T05 | ReAct 与 Agent Loop | `docs/work/T05-ReAct与AgentLoop/` | Checklist `91/91`；4 份 Feedback；`src/uthcode/core/agent.py` 与 `src/uthcode/application/runs.py` 已接入 |
| T06 | 暂停恢复与询问用户 | `docs/work/T06-暂停恢复与询问用户/` | Checklist `42/42`；3 份 Feedback；`src/uthcode/core/interaction.py` 与暂停恢复链已接入 |
| T07 | 三层权限系统 | `docs/work/T07-三层权限系统/` | Checklist `56/56`；4 份 Feedback；`src/uthcode/core/permission.py` 与 `src/uthcode/integrations/permissions.py` 已接入 |

### `not_implemented`

| Task | 任务包 | 当前路径 | 当前证据 |
| --- | --- | --- | --- |
| T08 | 任务规划与执行控制 | `docs/work/T08-任务规划与执行控制/` | 正式工作包已生成；Checklist 尚未完成且尚无 Worker Feedback；当前源码仍无 BehaviorMode、PlanState、TaskState 与 Runtime Hook |

## 跨层最短链路

```text
interfaces/cli.py 或 interfaces/tui/app.py
  -> application/bootstrap.py:create_application
  -> application/generation.py:UthCodeApplication.create_run
  -> application/runs.py:AgentRun.start_turn
  -> core/agent.py:AgentLoop / AgentTurnExecution
  -> core/provider.py:ProviderPort
  -> core/tool.py:ToolExecutor
  -> core/permission.py:PermissionEvaluator
  -> application/runs.py:_TurnDriver
  -> AgentEvent 流 / TurnResult
```

## 全局禁止推断

- `[ABSENT]` LangGraph、LangChain Agent、图/DAG/工作流 DSL。
- `[ABSENT]` OS Sandbox；`Bash` 是当前用户权限下的未沙箱化进程执行。
- `[ABSENT]` 持久 Session、Journal 存储、Memory、Dream、Context Compiler、Context Budget、结构化压缩。
- `[ABSENT]` Hook、Skill、MCP、Worktree、Subagent、Multi-Agent、通用任务调度器。
- `[ABSENT]` 旧 API、旧数据结构、旧行为的兼容层；新增兼容入口默认不允许。
