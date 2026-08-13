# W01 权限分类与完全访问收口实施提示词

请完整实施 `T07-1-权限分类与完全访问收口`。本工作包是单 Worker 轻量任务，必须严格按 Task 1 -> Task 2 -> Task 3 -> Task 4 -> Task 5 串行完成。先用失败回归证明两个现存问题，再做最小修复；不得并行修改共享 Bash 事实和 PermissionEvaluator。

## 开工前必须读取

1. `AGENTS.md`
2. `docs/Context-Index.md`
3. `docs/work/README.md`
4. `docs/OutstandingDebtList.md`
5. `docs/work/T07-1-权限分类与完全访问收口/T07-1-权限分类与完全访问收口.md`
6. `docs/context/A01-AgentRuntime/AgentRuntime-Context.md`
7. `docs/context/A02-Control/Control-Context.md`
8. `docs/context/A04-Orchestration/Orchestration-Context.md`
9. `docs/context/TUI/README.md`
10. `docs/work/archive/T07-三层权限系统/` 中的 Spec、Tasks、Checklist，以及与 Permission evaluator、Bash Guard、pause/resume、Session Grant、交付返工有关的 Feedback
11. `docs/work/archive/T08-任务规划与执行控制/` 中与 `trusted preflight -> Hook -> Permission -> execute` 顺序有关的正式资料
12. 任务书列出的全部现有源码和测试；当前事实以 `src/ + tests/` 为准

## 已确认设计决策

- `full_access` 跳过内置普通 Guard、普通 Policy 与 Strategy。
- 用户和项目显式配置的 Guard ASK/DENY 在 `full_access` 下仍生效。
- 灾难性 circuit breaker 只覆盖根目录/Home 递归删除、磁盘/卷破坏和裸设备写入。
- circuit breaker 在三种模式均 ASK，只提供 ONCE/REJECT，不形成 Session Grant。
- 普通 ALLOW 规则不能覆盖 circuit breaker；用户/项目显式 DENY 可得到更严格的 DENY。
- fork bomb、关键进程终止、递归权限修改、工作区整体删除、Git destructive、提权、远程脚本管道、敏感读取、命令替换、嵌套 Shell、UNKNOWN 均不是 circuit breaker。
- `full_access` 仍不持久化；项目配置仍不能启用它。
- 当前文档实施后只保留新事实；归档 T07/T08/T08-1 保持冻结历史，不回写。

## 修改范围

按任务书实际需要修改：

- `src/uthcode/integrations/tools/process_tools.py`
- `src/uthcode/integrations/permissions.py`
- `src/uthcode/core/permission.py`
- 必要时窄改 `src/uthcode/core/agent.py`、`src/uthcode/application/runs.py`、`src/uthcode/application/tools.py` 与 TUI 权限投影
- `tests/test_builtin_process_tool.py`
- `tests/test_permission.py`
- `tests/test_permission_rules.py`
- `tests/test_permission_delivery.py`
- `tests/test_agent_interaction.py`
- `tests/test_application_runs.py`
- 新增 `tests/test_t07_1_e2e.py`
- 必要的架构、包导出与 TUI 测试
- Checklist checkbox、Feedback，以及实施完成后的当前事实文档

必须按当前代码事实更新：

- `AGENTS.md`
- `README.md`
- `docs/context/A02-Control/Control-Context.md`
- 若真实 effect/scope/调用链发生变化，同步 `docs/context/A01-AgentRuntime/AgentRuntime-Context.md`
- `docs/Context-Index.md`

禁止修改范围：

- 归档 T07、T08、T08-1 的冻结需求、Spec、Tasks、Prompt、Checklist 和 Feedback
- OS Sandbox、AI classifier、完整 Shell/CMD/PowerShell AST
- 新权限模式、full_access/Session Grant 持久化、持久 Session
- Skill、MCP、Subagent、动态 Tool/Hook Permission API
- 第二 PermissionEvaluator、Interface 权限判断、兼容开关或双轨旧语义
- 与本任务无关的 Provider、Plan/Todo、配置或 TUI 重构

## 实施约束

1. 使用 Conda 环境 `re-uthcode`。
2. 开始时记录 `git status --short`，保留用户已有修改；不得修改无关文件。
3. 先新增能在旧实现上失败的 `cd /d`、CMD 分组和 full_access Guard 矩阵回归，再修改生产代码。
4. circuit breaker 必须是 Rule 的可信、不可由权限 TOML设置的结构化属性；不得通过 rule ID 前缀、展示摘要或 source 字符串猜测。
5. circuit-breaker 事实由 Tool preflight 的段级解析器产生，测试只做 preflight/evaluator 或在 execute 前拒绝，禁止真实执行危险命令。
6. 普通 CMD 括号组要继续检查内部可见 effect；修复 `nested-execution` 误报不能把括号内写入或 destructive 命令降级为 READ。
7. `cd /d` 只接受一个静态字面目标；变量、通配符、缺失目标、额外参数和不确定控制流保持 UNKNOWN。
8. 保持 Tool FIFO、exactly-one ToolResult、取消优先、一次 preflight/execute 和 typed pause ID 校验。
9. 当前文档只能在代码与测试通过后按真实实现改写；删除旧事实口径，不写“旧语义仍存在但现已例外”的双轨叙述。
10. 未经用户明确要求，不执行 commit、push、merge、rebase、tag、归档或分支操作。

## 测试与验收

至少按风险递增执行：

```powershell
conda run --no-capture-output -n re-uthcode python -m pytest tests/test_builtin_process_tool.py tests/test_permission.py tests/test_permission_rules.py -q
conda run --no-capture-output -n re-uthcode python -m pytest tests/test_permission_delivery.py tests/test_agent_interaction.py tests/test_application_runs.py -q
conda run --no-capture-output -n re-uthcode python -m pytest tests/test_t07_1_e2e.py -q
conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py tests/test_package.py -q
conda run --no-capture-output -n re-uthcode python -m pytest -q
conda run --no-capture-output -n re-uthcode python -m compileall -q src tests
conda run --no-capture-output -n re-uthcode python -m pip check
git diff --check
```

必须增加参数化安全矩阵：四类 circuit breaker 的 POSIX/Windows 正例、每类相邻负例、三种 PermissionMode、用户/项目 Guard ASK/DENY、普通 Guard full_access 放行、外部配置强制等级拒绝。危险命令不得进入真实 subprocess。

至少进行一次正式 Application E2E，证明 `full_access` 的普通 Guard 场景没有 Permission pause，而 circuit breaker 与显式 Guard 仍产生正确 pause choices、拒绝无副作用并闭合 ToolCall。

## 文档与 Feedback

- 首次实施时创建并持续追加 `docs/work/T07-1-权限分类与完全访问收口/feedback/W01-权限分类与完全访问收口-feedback.md`。
- Feedback 记录：失败基线、实际行为、关键调用链、修改文件、测试命令与精确结果、Checklist 对应证据、与任务书差异、未验证项、风险和遗留负担清理。
- 首次派发后任务书与本 Prompt 冻结；只允许勾选现有 Checklist checkbox，不得改写其文字或顺序。
- 如任务书存在错误、必须扩大范围或无法满足冻结决策，停止相关范围，在 Feedback 记录并交由用户决定。
- 实施完成后按当前代码事实更新 `AGENTS.md`、`README.md`、`docs/Context-Index.md` 和命中的 `docs/context/**`；旧事实直接删除或改写。
- `docs/OutstandingDebtList.md` 本任务无变化；不要为缺陷修复制造能力欠账。
- 对所有修改 Markdown 执行 UTF-8、replacement character、常见乱码和 fence 平衡检查。
