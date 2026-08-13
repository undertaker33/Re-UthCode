# W02 Eval 单次执行实施提示词

请在 W01 验收完成后，完整实施 `B01-私有测试集v0` 的 Task 3。只负责通过公开 Application API 建立单次 Headless attempt 执行闭环及离线测试。

## 开工前必须读取

1. `AGENTS.md`
2. `docs/README.md`
3. `docs/Context-Index.md`
4. `docs/rules/WorkPackageRules.md`
5. `docs/work/B01-私有测试集v0/B01-私有测试集v0.md`
6. 本目录中的 Spec、Tasks、Checklist
7. `feedback/W01-eval-contract-workspace-feedback.md`
8. `docs/context/A01-AgentRuntime/AgentRuntime-Context.md`
9. `docs/context/A02-Control/Control-Context.md`
10. `docs/context/A03-State/State-Context.md`
11. `docs/context/A04-Orchestration/Orchestration-Context.md`
12. `src/uthcode/application/__init__.py`、`bootstrap.py`、`generation.py`、`runs.py` 以及相关 Application/Event/Permission/T08 测试

## 已确认设计决策

- Eval 只经 `uthcode.application` 公共入口工作，不读取 Core 私有 RunState，不直接执行 Tool 或调用 Provider。
- 每个 attempt 只有一个 AgentRun、一个 Turn、一个事件流消费者和一个稳定结果。
- Permission ASK 不批准、不建立 Session Grant；任务预声明的 AskUser/PlanReview 才可严格匹配并恢复同一 Turn。
- timeout 只取消一次；同一 workspace 不自动重试。
- Bash 是 unsandboxed process execution；外部 workspace 和 `auto` 不得描述为 Sandbox。
- 真实 Provider 必须有显式 live 开关和用户费用授权；本 Worker 只运行 Fake Provider 离线测试。

## 修改范围

- 新增 `eval/execution.py`
- 新增 `tests/eval/test_eval_execution.py`
- 必要时窄改 W01 新增的 `eval/models.py`、`eval/workspace.py` 以修复直接合同问题
- 完成后勾选 Task 3 Checklist，并创建/持续更新 `feedback/W02-eval-execution-feedback.md`

禁止修改 `src/uthcode/**`、正式 CLI/TUI、公共 Event、Permission/Agent Loop 语义、七题任务、metrics/reporting 和 runner。

## 实施约束

1. 使用 Conda 环境 `re-uthcode`，先写失败测试。
2. 事件只消费一次，`result()` 必须属于同一 Turn；不得通过双执行分别获得事件和结果。
3. typed response 严格匹配 pause/run/turn/tool/permission 标识与问题类型。
4. 已有副作用不确定时不重试；失败也尽力保留已有 artifact manifest。
5. 产物只保存公开、安全、可序列化投影，不保存秘密或 Provider 原生对象。
6. 触发任务书停止条件时，在 Feedback 记录证据并停止，不得修改生产公共协议绕过。

## 测试与验收

至少执行：

```powershell
conda run --no-capture-output -n re-uthcode python -m pytest tests/eval/test_eval_execution.py tests/test_application_runs.py tests/test_agent_events.py -q
conda run --no-capture-output -n re-uthcode python -m pytest tests/test_permission_delivery.py tests/test_t08_e2e.py -q
conda run --no-capture-output -n re-uthcode python -m compileall -q eval tests/eval
git diff --check
```

## Feedback 要求

Feedback 必须说明真实调用链、事件与结果 exactly-once 证据、交互/权限/超时分类、取消行为、脱敏边界、修改文件、精确测试结果、Checklist 证据、差异、风险和未验证项。
