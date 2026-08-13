# W03 Eval 任务集与交付反馈

## 交付结论

Task 4 → Task 5 → Task 6 → Task 7 → Task 8 → Task 9 已按冻结范围实施。当前 B01 已满足 `implemented_unarchived` 条件；工作包目录保留在 `docs/work/`，没有执行归档或任何 Git 写入。

真实 Provider baseline：`NOT VERIFIED (authorization required)`。本轮没有网络调用、费用调用或读取 API key 真实值。

## 实际实现

- 七个固定任务各有 `task.toml`、`instruction.md`、独立 fixture 和 deterministic `verify.py`。verifier 只读 workspace、只用标准库，输出 schema v1 的 hard/partial/forbidden checks；重复输入逐字段稳定，模型 final 不能覆盖 verifier 失败。
- `eval/metrics.py` 从公开事件投影、TurnResult、VerifierResult 和受控 diagnostics 生成 correctness、context、exploration、efficiency、stability、safety 六维；保留 raw、score、evidence_refs、status，缺少事实使用 `not_available`，安全 hard failure 单独保留。
- `eval/reporting.py` 生成逐次/均值/中位数报告和 JSON、Markdown、终端摘要；compare 校验代码、任务、模型、Provider、Prompt、配置、权限、运行参数、平台、运行时和 revision 指纹，以及任务集合、样本数和 schema。缺失或不一致时 `delta = null`。
- `eval/runner.py` 提供 `help`、`smoke`、`run`、`compare`、`clean`。Fake 通过公开 `uthcode.application` 运行 Application/Run/Turn；会执行证据 ReadFile、声明的 AskUser/PlanReview typed pause/resume，并在 permission-boundary 触发外部 ReadFile 的正式 Permission ASK。runner 不注入标准答案或完整 Patch。
- 运行态仅进入经物理路径校验的仓库外 Eval root；attempt artifact 包含 metadata、events、turn_result、verifier_result、diagnostics、workspace diff、output manifest 和 record。clean 只接受精确 manifest-owned attempt。
- `eval/README.md` 已说明安装、固定条件、网络/费用授权、外部目录、六维解释、Bash 是当前 OS 用户权限下的 unsandboxed process execution、精确清理和回滚边界。

## Checklist 证据

- Task 4：`tests/eval/test_eval_verifiers.py` 共 `15 passed`；覆盖七题 gold-like、partial、forbidden、重复输出、网络/模型依赖扫描。plan-only 写入变体失败，permission-boundary 不读取宿主敏感文件。
- Task 5：`tests/eval/test_eval_reporting.py` 通过；覆盖六维、不可用 Context、三次中位数、重复探索、secret scan、安全硬失败、完整指纹和缺失指纹拒绝。
- Task 6/7：`python -m eval.runner --help` 退出 0，列出 smoke/run/compare/clean；未授权 live 在执行前拒绝；runner 只通过 `uthcode.application` 公开导出创建 Application；没有修改正式 CLI、CI、生产源码或依赖。
- Task 8：真实入口 Fake 单题和 suite、compare incompatible、精确 clean、源码仓库 clean 拒绝均已执行；相关回归和全量验证结果如下。
- Task 9：没有仓库内 Eval artifacts、cache、临时 home/workspace；源码、测试和报告扫描未发现真实 secret、Provider 原生对象或未脱敏 ToolResult 正文；没有第二 Loop、第二 Permission、Benchmark Adapter、兼容层或无调用方通用抽象。

## 精确验证结果

使用环境：Conda `re-uthcode`；工作目录：`D:\project\Re-UthCode`。

1. `conda run --no-capture-output -n re-uthcode python -m pytest tests/eval -q`
   - 结果：`69 passed in 35.06s`。
2. `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_application_runs.py tests/test_agent_events.py tests/test_permission.py tests/test_permission_delivery.py tests/test_builtin_process_tool.py tests/test_t08_e2e.py -q`
   - 结果：`297 passed in 29.65s`。
3. `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q`
   - 结果：`23 passed in 9.27s`。
4. `conda run --no-capture-output -n re-uthcode python -m pytest -q`
   - 结果：`1076 passed, 3 skipped in 106.11s`。
5. `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests eval`
   - 结果：退出码 `0`。
6. `conda run --no-capture-output -n re-uthcode python -m pip check`
   - 结果：`No broken requirements found.`
7. `git diff --check`
   - 结果：退出码 `0`；仅有既存 Markdown 文件的 LF/CRLF 转换 warning，没有 whitespace error。
8. `C:\Users\93445\.codex\skills\uth-utf8-guard\scripts\check_utf8_docs.py` 检查 11 个相关 Markdown 文件
   - 结果：`OK: 11 file(s) passed UTF-8 guard`；无 replacement character、常见乱码或不平衡 fence。

## 真实入口 E2E 结果

- `python -m eval.runner --help`：退出 0，公开四个手动子命令；未访问网络。
- Fake `plan-only` smoke：`finish_categories = {success: 1}`，报告写入仓库外 root。
- Fake 七题 suite：`sample_count = 7`，六维均存在且无 `overall`；`finish_categories = {agent_failure: 5, blocked_by_permission: 1, success: 1}`。这表示 Fake 没有伪造模型修改，五题 verifier 失败被如实记录；不是 baseline 分数。
- Fake compare（prompt salt 不同）：`compatible = false`，`delta = null`，原因包含 `fingerprints.prompt`。
- 精确 clean：删除一个 attempt 的 workspace/home/artifacts 共 3 个路径；再次确认 workspace 已不存在。
- `clean --eval-root D:\project\Re-UthCode`：拒绝，错误包含 `dedicated`；未删除源码仓库。
- suite E2E 后 `D:\project\Re-UthCode\artifacts` 不存在；仓库运行前后没有新增 Eval 污染。

## 任务书差异、风险与遗留负担

- Fake 入口没有保存标准完整 Patch，也没有隐藏 gold 变更。除 plan-only 的只读成功路径外，Fake smoke 的失败是预期的链路验收结果；七题 verifier 的 gold-like/partial/forbidden 正确性由独立测试覆盖。真实模型成功率仍未验证。
- `Context` 当前只能利用 evidence discovery、Usage 和 Tool 轨迹；没有 Context Compiler、Compaction、Working Set、Memory 结构化事实。B01 欠账保留在 `docs/OutstandingDebtList.md`，没有提前建设未来能力。
- `docs/Context-Index.md` 已将 B01 更新为 `implemented_unarchived`；`docs/context/A04-Orchestration/Orchestration-Context.md` 已同步私有 Eval 手动链路事实；未修改用户手册、核心产品能力或正式 CLI 文档。
- 任务开始前已有的 `docs/Context-Index.md`、`docs/OutstandingDebtList.md` 及 T07-1 删除/新增变更均保留；本轮没有执行 `git add`、commit、push、merge、rebase、tag、release 或工作包归档。

## UTF-8 guard

- files checked: `docs/Context-Index.md`、`docs/OutstandingDebtList.md`、`docs/context/A04-Orchestration/Orchestration-Context.md`、`eval/README.md`、B01 Spec/Tasks/Checklist/Prompt、W01/W02 Feedback。
- result: `OK: 11 file(s) passed UTF-8 guard`。
- repaired encoding issues: none。

## 收尾复核

- 初次反馈记录后，按 UTF-8 Guard 重新检查包含本反馈文件在内的 12 个受影响 Markdown/文本文件：`OK: 12 file(s) passed UTF-8 guard`；无 replacement character、常见乱码或未闭合 Markdown fence。
- 按明确范围执行 `git clean -ndX -- eval tests/eval` 后再执行同范围 `git clean -fdX -- eval tests/eval`，仅移除该 Eval 工具范围内可再生成的 23 个 `__pycache__` 目录；复查 `eval` 与 `tests/eval` 后无残留缓存。
- Checklist 最终为 31 项完成、0 项未完成；未执行 Git stage、commit、push 或归档，既有工作区变更保持不动。

## 返工轮次 1：W03 验收阻断项

### 返工原因

W03 验收不通过，暂不能将 B01 标记为 `implemented_unarchived`，不建议归档。验收指出两个 P1：真实 Provider 没有真实模型选择入口，Compare 只校验任务集合与总样本数，未校验逐任务样本分布。

### 实际修改

- `eval/runner.py` 为 Fake/live 运行增加 `--model` 入口；非 Fake 运行在创建 attempt 前要求显式非空模型标识，Fake 默认仍使用 `eval-model` 以保持离线入口兼容。
- `eval/execution.py` 将配置中的实际远端模型 ID 写入 `model_id` 指纹；该值进入 attempt record、聚合报告和 Compare 必需指纹集合，不能再用固定字面量替代真实模型选择。
- `eval/reporting.py` 新增 `task_sample_counts`，保存每个任务的实际样本数；Compare 对缺失、非法或映射不完全一致的计数返回不兼容并将 `delta` 置为 `null`。
- `eval/README.md`、`docs/context/A04-Orchestration/Orchestration-Context.md` 补充真实模型参数、模型指纹和逐任务计数约束；未修改生产源码、正式 CLI、依赖、CI 或冻结工作包文件。

### 新增离线回归

- `tests/eval/test_eval_runner.py`：验证显式模型 ID 被写入 attempt/report 指纹，以及授权 live 缺少 `--model` 时在创建 attempt 前拒绝。
- `tests/eval/test_eval_reporting.py`：验证 `a×2+b×1` 与 `a×1+b×2` 被判定不兼容且不生成 delta，并验证缺失/非法计数映射被拒绝。

### 当前状态

- 本轮修复后需重新执行 W03 要求的 Eval、定向回归、架构、全量、compileall、pip check、`git diff --check`、UTF-8 Guard 以及真实入口 E2E。
- 在复验完成前，`docs/Context-Index.md` 将 B01 保持为 `not_implemented`，明确记录“W03 验收未通过、返工中”；Checklist 冻结文本未改，原有复选框状态未回退。

## 返工轮次 1：复验结果

- 阻断项 1 已关闭：Fake/live 均支持 `--model`；非 Fake 运行缺少显式模型标识时在创建 attempt 前拒绝；实际远端模型 ID 以 `model_id` 写入 attempt 与聚合报告指纹，并纳入 Compare 必需指纹。
- 阻断项 2 已关闭：聚合报告保存 `task_sample_counts`；Compare 对缺失、非法或不一致映射返回 `compatible=false`、`delta=null`。离线回归实测 `a×2+b×1` 与 `a×1+b×2` 被拒绝。
- 新增/修订回归：`tests/eval` 为 `74 passed`，覆盖模型参数、live 缺参拒绝、模型指纹、逐任务样本计数和 Compare 兼容性。
- 完整复验：定向回归 `297 passed`；架构边界 `23 passed`；全量 `1081 passed, 3 skipped`；`compileall` 退出码 0；`pip check` 为 `No broken requirements found.`；`git diff --check` 退出码 0（仅 LF/CRLF warning，无 whitespace error）。
- 真实入口 E2E：`--help` 退出 0；未授权 live 与已授权但缺少 `--model` 均在网络前拒绝；Fake smoke 写入 `model_id=offline-model-v2`；Fake suite `sample_count=7` 且每题计数为 1；prompt 不同的 compare 不兼容且无 delta；精确 clean 删除 3 个 manifest-owned 路径；源码仓库 clean 被拒绝；无仓库内 artifacts。
- UTF-8 Guard：受影响的 12 个 Markdown/文本文件全部通过，无 replacement character、常见乱码或不平衡 fence；未修复编码问题。
- 复验后 `docs/Context-Index.md` 已恢复 B01 为 `implemented_unarchived`；工作包仍保留在 `docs/work/`，不建议归档，未执行 Git 写入或真实 baseline。Checklist 冻结文字和复选框状态未修改。

## 返工轮次 2：逐任务样本报告内部一致性

### 返工原因

W03 验收再次发现 P1：原校验只确认 `task_sample_counts` 是字符串到正整数的映射，未确认映射非空、键集合等于 `task_ids`，也未确认计数总和等于 `sample_count`。因此外部 Compare 对两份相同的畸形 JSON 报告仍可能生成 delta。

### 实际修改

- `eval/reporting.py` 将样本计数校验改为接收完整 report，同时校验 `task_ids` 为非空且无重复的字符串列表、`task_sample_counts` 为非空正整数映射、键集合完全一致，以及计数总和等于 `sample_count`。
- `compare_experiments` 在比较两边映射前分别验证 baseline 和 candidate；任一报告缺失或违反内部一致性时返回 `compatible=false`、`delta=null`。
- `tests/eval/test_eval_reporting.py` 新增空映射、总和不足、键集合不一致和同一畸形报告自比较回归；外部 `python -m eval.runner compare` 已用 JSON 文件实测空映射与总和不足均拒绝。
- `eval/README.md`、`docs/context/A04-Orchestration/Orchestration-Context.md` 补充报告级一致性约束；未修改冻结 Prompt/Task/Spec/Checklist、生产源码、正式 CLI、依赖、CI 或既有 T07-1 变更。

### 复验结果

- `tests/eval`：`77 passed`。
- 定向回归：`297 passed`；架构边界：`23 passed`；全量：`1084 passed, 3 skipped`。
- `compileall` 退出码 `0`；`pip check` 为 `No broken requirements found.`；`git diff --check` 退出码 `0`，仅 LF/CRLF warning，无 whitespace error。
- 外部 Compare：`task_ids=[a,b]`、`sample_count=3` 配空映射，及配 `a=1,b=1`，均返回 `compatible=false`、`delta=null`；同一畸形报告自比较也同时报告 baseline/candidate 内部不一致。
- 当前 B01 仍保持 `not_implemented`，待本轮文档、UTF-8、入口 E2E 和缓存收尾完成后再更新索引；工作包不归档，未执行 Git 写入或真实 baseline。

## 返工轮次 2：最终收尾

- 第二轮新增报告级一致性校验后，`tests/eval` 为 `77 passed`；定向回归 `297 passed`；架构边界 `23 passed`；全量 `1084 passed, 3 skipped`。
- `compileall` 退出码为 `0`；`pip check` 为 `No broken requirements found.`；`git diff --check` 退出码为 `0`，仅有 LF/CRLF 转换 warning，没有 whitespace error。
- 真实入口复验：`--help` 退出 `0`；Fake smoke 将 `offline-model-v3` 写入 `model_id`；Fake suite 为 7 个样本且每题 `task_sample_counts=1`；prompt 不同的 compare 返回 `compatible=false`、`delta=null`；缺少 `--model` 的已授权 live 在网络前退出 `2`；源码仓库 clean 拒绝并退出 `2`；仓库内无 `artifacts`。
- 外部 JSON Compare 复验：`task_ids=[a,b]`、`sample_count=3` 配空映射，及配 `a=1,b=1`，均返回 `compatible=false`、`delta=null`；同一畸形报告自比较也同时拒绝 baseline/candidate 内部一致性。
- UTF-8 Guard 最终检查 12 个受影响 Markdown/文本文件全部通过；`eval` 与 `tests/eval` 的可再生成 `__pycache__` 已按显式范围清理，复查为 0；Checklist 为 31 完成、0 未完成。
- 第二轮阻断已关闭。`docs/Context-Index.md` 恢复 B01 为 `implemented_unarchived`；工作包仍保留在 `docs/work/`，不建议归档；未执行 Git stage、commit、push 或其他 Git 写入，也未执行真实 baseline。
