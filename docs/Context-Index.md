# 当前项目上下文索引

```text
context_kind: current-code-context
context_file: docs/Context-Index.md
snapshot_date: 2026-09-04
document_language: zh-CN
target_reader: coding-agent
source_of_truth: src/ + desktop/src/ + tests/ + desktop/tests/
```

## Agent 读取协议

1. 先根据任务命中层级，只读下表对应的 `*-Context.md`。
2. 需要跨层修改时，再读取依赖层；不要默认遍历全部活跃工作包与 `docs/work/archive/`。
3. 本目录记录“当前代码事实”，不是需求、设计提案或兼容承诺。
4. 事实冲突时按以下优先级处理：`src/ + desktop/src/ + tests/ + desktop/tests/` > 本目录 > 根 `README.md` > `docs/work/TXX-*` 活跃工作包 > `docs/work/archive/`。
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
| `docs/context/GUI/` | 当前 Windows Desktop GUI 的长期实现上下文；不是工作包 | 修改 Desktop Renderer、Electron/Bridge、Project/Session 导航、Composer、Todo/Plan、Settings、Context/Compact 显示时读取 |
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
| 控制 | [`context/A02-Control/Control-Context.md`](context/A02-Control/Control-Context.md) | 权限、Sandbox、Ask User、暂停恢复、Steering | 已有权限、Ask User、暂停恢复、取消、固定控制检查；AskUser 为 1—4 题，选择题始终有自由输入且不再接受旧 `allow_other`/“Other”分支；无 OS Sandbox、动态控制 registry | Permission、审批、安全边界、暂停、恢复、询问用户、取消、Steering |
| 状态 | [`context/A03-State/State-Context.md`](context/A03-State/State-Context.md) | Context、Session History、Memory、Todo/Plan、任务进度、Steering | 已有进程内 Run/Turn、消息、事件、快照、Transcript/Timeline、PlanContentDelta/PlanProposed/typed review、动态 Context Budget/Gate（default 256K、effective 256K 使用 Eval 选定的 balanced-208k profile、configured/provider 收紧与 provenance）、Application `context_status`/`compaction_status` 安全投影、Session v3 metadata 与 Session `model_ref`、History append/reload/metadata touch 与 Instruction State 分阶段 persistence outcome、durable cursor；Desktop live delta 和 per-Session cache 只作显示投影；append 后异常先做结构化 identity reconciliation，未知 durability quarantine active Session writer，要求 close/reopen recovery 后才解除；真正 append 失败的 pending batch 保留原始 Session/Turn identity 并按 FIFO 重试；L4/L5、manual Compact、HistoryRead 与 overflow retry 已进入正式链路；无 Runtime checkpoint、Memory/retrieval | RunState、Turn、Event、Context、Snapshot、Usage、Session、Plan/Task、历史 |
| 编排 | [`context/A04-Orchestration/Orchestration-Context.md`](context/A04-Orchestration/Orchestration-Context.md) | Application、入口、CLI/TUI/Desktop、Session、Plan/Task、Steering、Slash Mode | 已有单 Agent 应用编排、CLI/TUI 适配、Windows Desktop Python Runtime/Bridge 适配，真实配置的 Desktop 按 Session 保存独立 Application/Run runtime，切换 Session/Project 不取消后台 Turn，Bridge 事件附 Session/Project identity；Bridge 暴露 Application `context_status`/`compaction_status` 与 typed interactions，真实 prompt/显式命令触发的惰性 Session、`/plan`、`/do`、`/new`、`/resume`、`/compact`；Compact、overflow、Timeline aging 和 HistoryRead 均复用 Application orchestrator；status/diagnostics 与 FailureReason/PauseReason 投影由 Application 提供；无 Subagent、任务拆分器、Multi-Agent | Application、入口、组装、命令、TUI、Desktop、CLI、Session、Plan/Task、Steering |

## current-status

```text
status_snapshot: 2026-09-04
status_scope: docs/work 直接任务包子目录 + docs/work/archive 直接子目录
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
| B01 | 私有测试集 v0 | `docs/work/archive/B01-私有测试集v0/` |
| T09 | Prompt 与 Context Engineering | `docs/work/archive/T09-Prompt与ContextEngineering/` |
| T09-1 | Context 预算与 Compact 协议补齐 | `docs/work/archive/T09-1-Context预算与Compact协议补齐/` |
| T09-2 | 工程收敛与提前抽象清理 | `docs/work/archive/T09-2-工程收敛与提前抽象清理/` |
| T09-3 | 256K Context 工程调优与通用失败语义 | `docs/work/archive/T09-3-256KContext工程调优与通用失败语义/` |
| F01 | TUI 回复链路与 Session 恢复修复 | `docs/work/archive/F01-TUI回复链路与Session恢复修复/` |

### `implemented_unarchived`

| Task | 任务包 | 当前路径 | 当前证据 |
| --- | --- | --- | --- |

### `not_implemented`

| Task | 任务包 | 当前路径 | 当前证据 |
| --- | --- | --- | --- |
| T10 | Desktop GUI 与 TUI 全量能力迁移 | `docs/work/T10-DesktopGUI与TUI全量能力迁移/` | W01～W06 Feedback 齐全，自动回归、Runtime/PyInstaller smoke、package/make、Installer 自动测试和 packaged Electron 中英文 CDP 视觉验收已有证据；冻结 Checklist 共 86 项，仍有 20 项未完成，覆盖 Project/Session、Composer/Slash、AskUser/Plan、Settings/主题、真实 Desktop/Installer/Feature Parity 与最终状态收口，其中部分旧验收语义已被 F02 新需求取代但不得回写冻结文件，保持 `not_implemented` |
| F02 | Desktop GUI 交互与上下文缺陷修复 | `docs/work/F02-DesktopGUI交互与上下文缺陷修复/` | W01～W05 已实施；W06 的既有 `w06-rework-*` 16 份 packaged/CDP 报告记录完整交互矩阵历史证据，P3 收紧 ResizeObserver stderr allowlist 后另有定向报告；在合入 W03/W05 返工后又从当前源码重建 SHA-256 `6cf2fd8e9e79074554aeb072de713f8edf7696679a5b656f12ae25a0c7c32849` 的 packaged app，并以 `commands` flow 分别通过 en/zh-CN canonical Slash、typed `/compact` 与 typed `/status` 当前包集成验收，报告均无 console/renderer exception/unexplained stderr。完整 16 场未使用当前包重跑，W06 Checklist 仍保留人工、真实 Provider、干净 Windows 与视觉/可访问性未验证项，因此仍为 `not_implemented` |
| F03 | Context 冻结收口、工程收敛与 Desktop 体验优化 | `docs/work/F03-Context冻结收口与工程收敛及Desktop体验优化/` | W01～W07 Feedback 已齐全；W07 fixture 修复、全量 Python/Context measurement、Desktop typecheck 与 `npm test`（183 passed）已有证据；当前标准 `npm run package` 与 `npm run make` 均 exit 0，标准包为 `desktop/out/UthCode-win32-x64/UthCode.exe`（244440576 bytes），安装器为 `desktop/out/make/squirrel.windows/x64/UthCode Setup.exe`（175683072 bytes）。当前标准包 en/zh-CN CDP visual restore 报告均通过，覆盖 dark/light、docked/floating/hidden、wide/narrow、CSS page scale 1/1.25/1.5 与 reduced-motion，且无 unexplained console/renderer/stderr；Settings acceptance、Renderer DOM/keyboard/scroll/copy（92 tests）也有证据。返工 3 已用 Electron Forge dev shell 验证真实 `Renderer → DesktopApi → Main/Preload → DesktopBridge → Application → Core` identity/event/terminal 链，报告为 `[probe-report.json](../desktop/out/f03-w07-dev-renderer-probe/probe-report.json)`，HTTP webpack Renderer target、7 类事件同一 identity、fixture response 与 `completed/final_answer` 均有证据；当前标准包 wrapper stream 的 en/zh 报告分别为 `[en stream](../desktop/out/f03-w07-cdp-round3-en-stream-locale-dom/acceptance-report.json)` 与 `[zh stream](../desktop/out/f03-w07-cdp-round3-zh-stream-locale-dom/acceptance-report.json)`，各 1 个 fixture request、driver/electron exit 0，显示 Model `CDP fixture` 与安全 wire `fixture/fixture-model` 分离断言；对应 en/zh visual 报告分别为 `[en visual](../desktop/out/f03-w07-cdp-round3-en-visual-locale-dom/acceptance-report.json)` 与 `[zh visual](../desktop/out/f03-w07-cdp-round3-zh-visual-locale-dom/acceptance-report.json)`，各 6 张截图且当前 preference 与可见 UI locale 一致。仍未验证真实 Provider、native pointer/Windows zoom、干净 Windows 与人工视觉；stream probe 的 reload 前 listener 证据不用于归因。Checklist 仍有未勾项，保持 `not_implemented` |

## 跨层最短链路

```text
interfaces/cli.py 或 interfaces/tui/app.py
  -> application/bootstrap.py:create_application
  -> application/generation.py:UthCodeApplication.create_run
  -> (真实 prompt/显式命令时) UthCodeApplication.ensure_session / resume_session_for_command
  -> application/runs.py:AgentRun.start_turn
  -> core/agent.py:AgentLoop / AgentTurnExecution
  -> core/provider.py:ProviderPort
  -> core/tool.py:ToolExecutor
  -> core/permission.py:PermissionEvaluator
  -> application/runs.py:_TurnDriver
  -> AgentEvent 流 / TurnResult

desktop/src/renderer/App.tsx
  -> desktop/src/preload.ts -> desktop/src/main.ts -> desktop/src/python-runtime.ts
  -> src/uthcode/interfaces/desktop/bridge.py
  -> 同一 Application/Run/Turn/Core/AgentEvent 链
  -> Desktop background event 附 `session_id`/`project_key`，由 Renderer 作 per-Session 显示缓存
```

配置 contract 当前事实：用户级 `config.toml` 使用 `default_model`、Provider `api_key`（literal 或 `env:VARIABLE_NAME`）/可选 `display_name`、Model `remote_id`/`display_name`/可选 `reasoning_effort`；Provider 显示名不参与稳定引用，项目配置不得定义 Provider、端点或凭据等价字段。逻辑 Model Profile ID 仅用于界面和状态，AgentRun 与 direct generation 都把快照的 `remote_id` 写入 `GenerationRequest.model`；`/model` 原子写回只修改用户级 `default_model`。输入运行上限由 configured/provider/default 三类来源按收紧规则解析，未配置时 default 为 `256_000`；effective 为 `256_000` 时，正式 resolver/Turn 使用 Eval 选定的 `balanced-208k` profile，其它窗口按有界自适应派生，并在 Active Turn 内冻结。

## 全局禁止推断

- `[ABSENT]` LangGraph、LangChain Agent、图/DAG/工作流 DSL。
- `[ABSENT]` OS Sandbox；`Bash` 是当前用户权限下的未沙箱化进程执行。
- `[FACT]` 持久 Session Transcript/Timeline、Tool Result ref、Instruction State metadata、Context Compiler、dynamic Context Budget/Gate、bounded L4/L5 与 Runtime AGENTS / Project Instructions Loader 已进入正式链路；输入预算包含 `256_000` default、effective 256K 时采用 Eval 选定的 `balanced-208k` profile、configured/provider 收紧及来源诊断，并在 Active Turn 内冻结；terminal Transcript 的 append/reload/last-used metadata touch 与 Instruction State sync 分开诊断，只有可判定 durable 的 message append 才推进 cursor，metadata 半失败不会回退；失败 Turn 同批持久化已公开 reasoning/partial assistant 与稳定失败 marker，replay 可恢复但不会回灌 Provider；append 后无法 reconciliation 的未知批次会 quarantine active Session writer，新的 Run/语义写入均 fail closed，只有 close 后 fresh writer 验证/恢复才解除；真正 append 失败时才保留进程内 pending batch，按原始 Session/Turn identity FIFO 重试，不引入 Runtime checkpoint。Provider cache usage 与 terminal FailureReason/PauseReason 只以安全 Application 投影暴露，不把 native payload 或正文带入 diagnostics。
- `[ABSENT]` Persistent Runtime checkpoint、Memory、Dream、retrieval、Timeline physical GC、Artifact lifecycle、独立 compaction model、跨 Provider fallback、持久 Compact FSM/Job/pointer、Provider 能力自动发现 UI。
- `[FACT]` Agent Loop 的固定顺序已接入 PLAN 非 READ Tool 边界与 unfinished-task 完成阻断；普通 PLAN final 正常完成，正式 Plan Review 仅由 `ProposePlan` 控制 ToolCall 触发；不提供动态注册。
- `[ABSENT]` 动态 Hook registry、第三方 Hook plugin 生命周期、Skill、MCP、Worktree、Subagent、Multi-Agent、通用任务调度器。
- `[ABSENT]` 旧 API、旧数据结构、旧行为的兼容层；新增兼容入口默认不允许。
