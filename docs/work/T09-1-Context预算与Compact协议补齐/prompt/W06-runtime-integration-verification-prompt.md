# W06 Runtime / Integration / Verification Worker Prompt

## 任务范围与严格顺序

W01～W05全部完成后严格串行执行：

1. Task 6：运行生命周期、手动 Compact、Overflow、Diagnostics 与文档；
2. Task 7：[接入主流程] 单一 Context Request Orchestration；
3. Task 8：[端到端验证] Dual Gate / Compact / Recovery；
4. Task 9：[遗留负担清理] 动态预算与单 Timeline 路径收口。

完成Feedback后停止；不得归档或Git写入。

## 必须读取

`AGENTS.md`、docs路由/Context Index/WorkPackageRules、本工作包四文件、W01～W05全部Feedback、A01/A03/A04 Context、T09 Core Design、Task 6～9全部源码/tests/Eval/用户文档。使用`re-uthcode`；修改governed Markdown前后使用`uth-utf8-guard`。

必须逐一读取：`application/generation.py`、`application/sessions.py`、`application/context.py`、`application/commands/builtins.py`、`dispatcher.py`、`models.py`、`interfaces/tui/app.py`、`eval/metrics.py`，以及`test_application_runtime.py`、`test_application_runs.py`、`test_session_files.py`、`test_command_dispatcher.py`、`test_w04_session_commands.py`、`test_tui.py`、`test_w05_diagnostics.py`、`test_w06_integration_delivery.py`、`test_t09_1_context_protocol_e2e.py`、`test_architecture_boundaries.py`和目标树全部长期文档。

工作包已冻结，只能勾选已满足复选框并创建/追加同一Feedback。

## 冻结决策

- D1：L4/L5复用当前主模型；active Turn frozen snapshot，idle manual current selection；无independent model。
- D2：bounded `1..N` catch-up、checkpoint/rebuild/re-gate；无持久Compact FSM。
- D3：Auto proactive与Hard send safety分离；adaptive capped headroom；final count含output reserve与uncertainty；L1-L3仍pressure继续L4。
- breaker后Hard safe为`auto_pressure_unresolved`并允许发送；Hard unsafe拒绝。
- manual不受Auto trigger限制；L5 Fine pressure独立；overflow最多一次retry且不改C。

## 修改范围与交付

Task 6只改列出runtime/command/diagnostics/Eval/docs；Task 7～9仅修复既定范围的接入缺陷、fixtures、机械exports和直接失效实现。

必须交付incremental closed facts、manual success/no-op/single-flight、overflow once/twice、dynamic safe status、全部call Hard Gate、真实E2E、包级docs同步与遗留清理。

## 禁止

不实现Memory/Retrieval、Persistent Runtime Recovery、Timeline/Artifact GC、background agent、Subagent/Multi-Agent、全量catalog、旧Session compatibility；不重构无关TUI/Permission/Plan/Todo/Hook；不修改冻结文字；不执行commit/push/merge/rebase/tag/release/archive。

## 验证

逐项执行Task 6～9 Checklist，至少运行：

```powershell
python -m pytest tests/test_t09_1_context_protocol_e2e.py -q
python -m pytest tests/test_architecture_boundaries.py -q
python -m pytest -q
```

再执行cleanup `rg`与UTF-8 guard。所有命令记录精确passed/failed/skipped和耗时，失败不得描述为通过。

## Feedback

创建`feedback/W06-runtime-integration-verification-feedback.md`。说明实际调用链与状态变化、修改文件、逐条命令结果、Checklist、任务书差异、未完成项/风险、cleanup与UTF-8 guard。返工只在同一文件末尾追加。
