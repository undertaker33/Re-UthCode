# B01 私有测试集 v0 Checklist

## Task 1：任务与产物合同

- [x] 执行合同 round-trip、未知字段、非法版本/路径/交互/规则、重复 ID、分数边界测试，全部通过。
- [x] 断言不可用指标与数值 `0` 序列化结果不同，错误信息不包含测试秘密值。

## Task 2：仓库外 workspace 与安全清理

- [x] 执行 `tests/eval/test_eval_workspace.py`，覆盖 repo、子目录、链接回 repo、盘符根、filesystem root、home 根、重复 attempt、部分创建失败与清理拒绝，全部通过。
- [x] 在已有 dirty/untracked fixture 下比较运行前后基线，原有改动不被覆盖、清理或计为新增污染。
- [x] 执行精确 clean 测试，只删除 manifest 对应且位于专用 external root 的目标。

## Task 3：单次 Headless attempt 执行

- [x] 执行 `tests/eval/test_eval_execution.py`，证明每个 attempt 只有一个 Run/Turn、一条事件流、一个稳定 TurnResult 和一个 verifier 调用。
- [x] 覆盖正常、Permission ASK、未声明交互、typed response、timeout、Provider failure、取消 exactly-once 与脱敏产物，全部通过。
- [x] 静态检查 Eval 执行代码只导入 `uthcode.application` 公共入口，不直接导入 Provider SDK、Tool Registry 或 Core 私有状态。

## Task 4：七个私有任务与 deterministic verifier

- [x] 执行 `tests/eval/test_eval_verifiers.py`，七题各自的 gold-like、partial、forbidden 用例全部通过。
- [x] 对每个 verifier 重复运行相同输入，输出逐字段一致且无网络访问。
- [x] 对 plan-only fixture 执行写入变体，确定失败；对 permission-boundary 证明无需访问宿主敏感文件即可完成安全路径。

## Task 5：六维指标、报告与 compare

- [x] 执行 `tests/eval/test_eval_reporting.py`，覆盖聚合、中位数、三次波动、partial score、missing diagnostics、重复探索、secret scan 和安全硬失败，全部通过。
- [x] 同指纹 baseline/candidate 输出逐次、绝对值、中位数和 delta；任一关键指纹不同则拒绝正式 A/B delta。
- [x] 检查 JSON、Markdown、终端报告均并列展示六维信息且不存在单一综合排名。

## Task 6：手动入口与开发者文档

- [x] 执行 `python -m eval.runner --help`，退出成功且不访问网络。
- [x] 在未提供 live 授权时执行真实 Provider 路径，必须在网络调用前拒绝。
- [x] `eval/README.md` 明确安装、固定条件、成本、Bash 非 Sandbox、外部目录、结果解释、精确清理、回滚和 Context 指标限制。
- [x] 验证 `pyproject.toml`、`.gitignore`、`tests/conftest.py` 相对任务开始基线未变化。

## Task 7：[接入主流程]

- [x] 从 `python -m eval.runner` 的 Fake smoke 入口完成 task load -> external attempt -> Application Run -> verifier -> report 全链路。
- [x] 执行 `python -m pytest tests/test_architecture_boundaries.py -q`，全部通过，并确认 `src/uthcode/**` 与正式 CLI/TUI 无 B01 改动。
- [x] 搜索并确认不存在第二 Agent Loop、手工 Tool 执行入口、第二 Permission 系统或重复 attempt 执行链。

## Task 8：[端到端验证]

- [x] 执行 `python -m pytest tests/eval -q`，全部通过且无真实网络或费用。
- [x] 执行 Fake 单题 smoke 和全 suite 聚合，生成仓库外 artifacts 与报告，源码仓库相对运行前无新增污染。
- [x] 执行相关 Application、Permission、Event、T08 定向回归，精确命令和结果记录在 Feedback。
- [x] 执行 `python -m pytest -q`、`python -m compileall -q src tests eval`、`python -m pip check` 和 `git diff --check`，结果全部记录。
- [x] 仅在用户明确授权真实模型网络与费用后执行固定模型七题 baseline；记录命令、实验 ID、指纹、逐题与聚合结果，否则在 Feedback 标记 `NOT VERIFIED (authorization required)`。
- [x] 按 `docs/README.md` 维护映射同步 B01 相关开发者文档、当前事实、索引、欠账和 Feedback，并对修改 Markdown 执行 UTF-8 guard。

## Task 9：[遗留负担清理]

- [x] 盘点并删除本任务误生成的仓库内 Eval artifacts、cache、临时 home/workspace，且不触碰任务开始前用户已有改动。
- [x] 搜索确认不存在无调用方的 Benchmark/Adapter/Registry/Manager、兼容层、废弃入口、不可达代码和重复职责。
- [x] 搜索确认源码、测试、文档和 artifacts 中无 API key、token、临时 endpoint、自动授权逻辑或未脱敏 ToolResult 正文。
- [x] 最终 `git status --short` 中仅包含 B01 授权范围及其必须同步的工作包/当前事实文档改动。
