# W01 阶段一扫尾实施提示词

请完整实施 `T08-1-阶段一扫尾`。本工作包是单 Worker 轻量任务，必须严格按 Task 1 -> Task 2 -> Task 3 -> Task 4 -> Task 5 -> Task 6 -> Task 7 串行完成，不得拆出第二套并行 Agent Loop、配置状态或 Interface 业务逻辑。

## 开工前必须读取

1. `AGENTS.md`
2. `docs/Context-Index.md`
3. `docs/work/README.md`
4. `docs/OutstandingDebtList.md`
5. `docs/work/T08-1-阶段一扫尾/T08-1-阶段一扫尾.md`
6. `docs/context/A01-AgentRuntime/AgentRuntime-Context.md`
7. `docs/context/A02-Control/Control-Context.md`
8. `docs/context/A03-State/State-Context.md`
9. `docs/context/A04-Orchestration/Orchestration-Context.md`
10. `docs/context/TUI/README.md`
11. `docs/work/archive/T08-任务规划与执行控制/` 中的 Spec、Tasks、Checklist，以及与 Plan Review、Application、TUI 有关的 Feedback
12. 任务书列出的全部现有源码和测试；当前事实以 `src/ + tests/` 为准

## 已确认设计决策

- `/new` 不做。
- PLAN 普通 final 正常完成；只有 `ProposePlan` 才进入 Plan Review。
- `ProposePlan` 只用于“用户批准后准备在同一 Turn 继续实施”的正式方案；纯问答、调查、解释、定位和只交付 Plan 文本均使用普通 final。
- `ProposePlan` 是 Provider 可见的 Core 控制 Tool，不是普通执行 Tool，不经过 Permission、Integration 或 OS 进程。
- `ProposePlan` 必须是 Provider 响应中唯一 ToolCall；混合 batch 整批受控拒绝，不执行同批普通 Tool，不创建 Plan。
- revision 由 Core 计算；REVISE 保持 PLAN，APPROVE 在公开恢复前把当前活动 Run/Turn 切到 DEFAULT，CANCEL 服从取消优先。
- 用户配置顶层 `default_permission_mode` 只允许 `default|auto`；省略为 `default`；项目配置声明该字段硬失败。
- `/permission default|auto` 先原子写回并更新 Application 默认值，成功后才更新当前 Run；失败时全部保持旧值。
- `/permission full_access` 仅当前 Run，不写配置、不改 Application 默认值；底部状态栏的 `permission: full_access` 使用 `PALETTE.error` 警告色。
- Behavior Mode 不持久化。当前没有 Session 恢复，不设计重启后 Plan/批准事实恢复。

## 修改范围

按任务书实际需要修改：

- `src/uthcode/core/planning.py`
- `src/uthcode/core/agent.py`
- `src/uthcode/core/hooks.py`
- `src/uthcode/core/prompt.py`
- 必要时窄改 `core/interaction.py`、`agent_events.py` 与 Core 公共导出
- `src/uthcode/integrations/config/data.py`
- `src/uthcode/integrations/config/loader.py`
- `src/uthcode/integrations/config/template.py`
- `src/uthcode/integrations/config/writer.py`
- `src/uthcode/application/configuration.py`
- `src/uthcode/application/bootstrap.py`
- `src/uthcode/application/generation.py`
- `src/uthcode/application/runs.py`
- `src/uthcode/application/commands/` 与必要公共导出
- `src/uthcode/interfaces/tui/app.py`
- 任务书指定的测试文件、Checklist checkbox、Feedback 和实施完成后的当前事实文档

禁止修改范围：

- `/new`、`/resume` 与其他未实现 Slash Command
- Persistent Session、Context、Memory、Skill、MCP、Sandbox、Subagent、Multi-Agent
- Behavior Mode 持久化、项目级 Permission 默认值、full_access 持久化
- 动态 Hook registry、新 Hook 生命周期点、通用 ControlTool registry、工作流/DAG
- Provider SDK 适配器语义，除非现有自有 `ToolDefinition/ToolCallPart/ToolResultPart` 转换存在由本任务直接触发的确定缺陷
- 已归档 T08 工作包的冻结文档

## 实施约束

1. 使用 Conda 环境 `re-uthcode`。
2. 先写能证明旧行为失败的回归测试，再做最小实现。
3. 保持唯一 Agent Loop、FIFO、每个 ToolCall exactly-one ToolResult、取消优先和 typed pause 校验。
4. 普通 PLAN final 不再经过 Plan Review，但 PLAN 非只读 Tool 的强制 Hook 不得减弱。
5. 不保留 `plan_completion_hook` 旧语义的兼容入口；若函数已无调用方，删除实现、导出和旧测试。
6. ProposePlan pause 必须保留原 call ID，批准、修订、取消、错误和重复恢复均有明确闭合证据。
7. 配置 writer 必须窄化、强类型、按允许字段写回；不得提供调用方可任意修改 TOML 的字典接口。
8. 项目配置的拒绝必须发生在正式配置校验层，不依赖 Interface。
9. TUI picker 不得直接绕过 Application 写回语义；Interface 只应用结构化结果并投影状态。
10. 用户已有未提交修改必须保留。开始时记录 `git status --short`，不要修改无关文件。
11. 未经用户明确要求，不执行 commit、push、merge、rebase、tag、归档或分支操作。

## 测试与验收

至少按风险递增执行：

```powershell
conda run --no-capture-output -n re-uthcode python -m pytest tests/test_planning.py tests/test_runtime_hooks.py tests/test_system_prompt.py -q
conda run --no-capture-output -n re-uthcode python -m pytest tests/test_agent_loop.py tests/test_agent_interaction.py tests/test_agent_events.py -q
conda run --no-capture-output -n re-uthcode python -m pytest tests/test_configuration.py tests/test_config_loader_integration.py tests/test_command_dispatcher.py -q
conda run --no-capture-output -n re-uthcode python -m pytest tests/test_application_runs.py tests/test_tui.py tests/test_t08_e2e.py -q
conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py tests/test_package.py -q
conda run --no-capture-output -n re-uthcode python -m pytest -q
conda run --no-capture-output -n re-uthcode python -m compileall -q src tests
conda run --no-capture-output -n re-uthcode python -m pip check
git diff --check
```

Checklist 中的行为断言必须逐项有测试或真实入口证据。Windows Terminal 颜色若无法人工验证，自动断言 fragment style，并在 Feedback 中将人工视觉验收标为 `NOT VERIFIED`，不得写成通过。

## 文档与 Feedback

- 首次实施时创建并持续追加 `docs/work/T08-1-阶段一扫尾/feedback/W01-阶段一扫尾-feedback.md`。
- Feedback 记录：实际行为、关键调用链、修改文件、测试命令与精确结果、Checklist 对应证据、与任务书差异、未验证项、风险和遗留负担清理。
- 首次派发后任务书与本 Prompt 冻结；只允许勾选现有 Checklist checkbox，不得改写其文字或顺序。
- 如任务书存在错误、必须扩大范围或无法满足冻结决策，停止相关范围，在 Feedback 记录并交由用户决定。
- 实施完成后按当前代码事实更新 `docs/Context-Index.md`、命中的 `docs/context/**` 和 `docs/OutstandingDebtList.md`；不得自行归档工作包。
- 对所有修改 Markdown 执行 UTF-8、replacement character、常见乱码和 fence 平衡检查。
