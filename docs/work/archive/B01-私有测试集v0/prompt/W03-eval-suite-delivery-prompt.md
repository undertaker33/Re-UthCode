# W03 Eval 任务集与交付实施提示词

请在 W01、W02 验收完成后，完整实施 `B01-私有测试集v0` 的 Task 4 -> Task 5 -> Task 6 -> Task 7 -> Task 8 -> Task 9，严格串行完成任务集、报告、手动入口、主链接入、端到端验证和遗留负担清理。

## 开工前必须读取

1. `AGENTS.md`
2. `docs/README.md`
3. `docs/Context-Index.md`
4. `docs/rules/WorkPackageRules.md`
5. `docs/rules/UserDecisionBoundary.md`
6. `docs/OutstandingDebtList.md`
7. `docs/work/B01-私有测试集v0/B01-私有测试集v0.md`
8. 本目录中的 Spec、Tasks、Checklist
9. W01、W02 Feedback
10. 四个 `docs/context/A0*-*/` 当前事实文档
11. 原始需求和 Tasks 为 Task 4～9 定位的源码、测试及已完成 W01/W02 实现

## 已确认设计决策

- 固定七题，不接第三方 Benchmark，不保存标准完整 Patch，不规定唯一 ToolCall 序列。
- verifier 离线、确定性、只读 workspace，以 hard/partial/forbidden checks 为权威；模型 final 不能覆盖失败。
- 六维指标并列展示，保留原始值、证据、可用性、逐次和中位数；安全硬失败不可平均抵消；无单一总分。
- compare 必须校验全部实验指纹；不兼容结果不生成正式 delta。
- runner 是手动仓库级工具，不注册正式 `uthcode` CLI，不新增 CI、第三方依赖或仓库内运行产物。
- 真实 baseline 只有在用户另行明确授权网络与费用后才能执行；默认三次只是建议条件，不构成授权。
- 生产 `src/uthcode/**`、`pyproject.toml`、`.gitignore`、`tests/conftest.py` 保持不动。

## 修改范围

- 新增 `eval/tasks/` 七个任务四件套
- 新增 `eval/metrics.py`、`eval/reporting.py`、`eval/__init__.py`、`eval/runner.py`、`eval/README.md`
- 新增/补全 `tests/eval/test_eval_verifiers.py`、`tests/eval/test_eval_reporting.py` 及必要 E2E 测试
- 必要时窄改 W01/W02 新增 Eval 文件以完成正式链路
- 实施完成后按 `docs/README.md` 同步当前事实、索引、欠账和相关开发者文档
- 勾选 Task 4～9 Checklist，并创建/持续更新 `feedback/W03-eval-suite-delivery-feedback.md`

禁止修改正式产品 CLI/TUI、公共 Event/Core/Application/Permission 协议、CI、公共 Benchmark、Context/Memory/Session 实现和未来扩展占位。

## 实施约束

1. 使用 Conda 环境 `re-uthcode`，按 Task 顺序先写失败测试。
2. fixture 版本化且不可回写；verifier 不访问网络、模型或宿主敏感文件。
3. exploration/context 只统计公开结构化事实；事实不足时使用不可用，不从 final 或重复读取猜测。
4. 真实运行产物只写经 W01 校验的仓库外路径；任何 clean 都必须走精确 manifest 边界。
5. 包级验收必须检查与 B01 能力相关的开发者文档和当前事实，不得只写 Feedback。
6. 首次派发后冻结 Spec、Tasks、Prompt 与 Checklist 文案，只勾选 checkbox。
7. 遇到真实 baseline 授权缺失时继续完成全部离线范围，将该项标为 `NOT VERIFIED (authorization required)`，不要请求或读取秘密值。

## 测试与验收

至少按风险递增执行：

```powershell
conda run --no-capture-output -n re-uthcode python -m pytest tests/eval -q
conda run --no-capture-output -n re-uthcode python -m pytest tests/test_application_runs.py tests/test_agent_events.py tests/test_permission.py tests/test_permission_delivery.py tests/test_builtin_process_tool.py tests/test_t08_e2e.py -q
conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q
conda run --no-capture-output -n re-uthcode python -m pytest -q
conda run --no-capture-output -n re-uthcode python -m compileall -q src tests eval
conda run --no-capture-output -n re-uthcode python -m pip check
git diff --check
```

另外从真实 `python -m eval.runner` 入口运行离线 help、Fake smoke、Fake suite、compare 和 clean 拒绝场景。只有收到用户明确的真实网络与费用授权后，才按固定模型和次数执行七题 baseline。

## Feedback 要求

Feedback 必须面向人工审查说明七题、verifier、六维指标、比较兼容性、真实手动调用链、安全边界、修改文件、所有命令与精确结果、Checklist 证据、真实 baseline 授权/执行状态、与任务书差异、未验证项、风险、文档同步和遗留负担清理结果。不得复制秘密或大型日志。
