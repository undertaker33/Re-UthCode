# W01 Eval 合同与 Workspace 实施提示词

请完整实施 `B01-私有测试集v0` 的 Task 1 -> Task 2，严格按顺序执行。只负责数据合同、仓库外 workspace 和对应离线测试，不提前实现 Agent 执行、任务集、报告或 runner。

## 开工前必须读取

1. `AGENTS.md`
2. `docs/README.md`
3. `docs/Context-Index.md`
4. `docs/rules/WorkPackageRules.md`
5. `docs/rules/UserDecisionBoundary.md`
6. `docs/work/B01-私有测试集v0/B01-私有测试集v0.md`
7. 本目录中的 Spec、Tasks、Checklist
8. `docs/context/A02-Control/Control-Context.md`
9. `docs/context/A03-State/State-Context.md`
10. Task 1～2 命中的现有源码和测试；事实冲突时以 `src/ + tests/` 为准

## 已确认设计决策

- Eval 是仓库级私有开发工具，运行态全部写入仓库外专用目录。
- 使用严格版本化合同；未知字段和危险/宽泛值硬失败；不可用不等于零。
- fixture 只复制不回写；clean 只能作用于经过 manifest 证明的具体目标。
- 不新增第三方依赖、公共 Benchmark 协议、数据库或通用删除工具。
- 不修改 `src/uthcode/**`、`pyproject.toml`、`.gitignore`、`tests/conftest.py`。

## 修改范围

- 新增 `eval/models.py`
- 新增 `eval/workspace.py`
- 新增 `tests/eval/test_eval_reporting.py` 的合同测试
- 新增 `tests/eval/test_eval_workspace.py`
- 完成后勾选 Task 1～2 Checklist，并创建/持续更新 `feedback/W01-eval-contract-workspace-feedback.md`

禁止实现或修改 Agent execution、七题 fixture/verifier、metrics/reporting、runner、正式产品入口、Core/Application/Permission 协议。

## 实施约束

1. 使用 Conda 环境 `re-uthcode`。
2. 先写失败测试，再做最小实现。
3. 开始时记录 `git status --short` 和源码仓库物理路径；保留所有用户已有改动。
4. 所有删除目标先物理解析并验证类型、边界、manifest 和目标数量；遇到链接、锁定或不明确路径立即停止，不升级删除手段。
5. 错误信息只暴露字段定位所需信息，不回显秘密或文件正文。
6. 首次派发后 Spec、Tasks、Prompt 与 Checklist 文案冻结，仅可勾选现有 checkbox。

## 测试与验收

至少执行：

```powershell
conda run --no-capture-output -n re-uthcode python -m pytest tests/eval/test_eval_reporting.py tests/eval/test_eval_workspace.py -q
conda run --no-capture-output -n re-uthcode python -m compileall -q eval tests/eval
git diff --check
```

## Feedback 要求

Feedback 必须记录实际合同、路径防线、清理边界、修改文件、精确测试结果、Checklist 证据、与任务书差异、未验证项、风险和遗留负担。涉及停止条件时记录证据并停止相关范围，不得扩大公共边界。
