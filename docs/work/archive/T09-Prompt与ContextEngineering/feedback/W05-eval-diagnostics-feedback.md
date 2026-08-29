# W05 Context Diagnostics 与 Eval Feedback

## 1. 执行范围

本轮只执行 W05 / Task 9：安全 Context diagnostics、Provider Usage cache availability/provenance、baseline/candidate Eval facts 与回归验证。没有实施 Memory injection、embedding/retriever、生产上下文策略重写、动态模型窗口或 Git 写入，也没有修改冻结的 Prompt、Spec、Tasks 正文。

## 2. 实际实现

- `ApplicationContextService.public_diagnostics()` 输出 JSON-safe Context 投影：固定 budget、used/token estimate、selected/omitted block ID 与计数、omitted reason、Projection revision、instruction epoch、stable prefix token estimate/fingerprint、prefix changed/reason、Tool Schema fingerprint/estimate 和 over-budget。没有复制 selected block content 或 Tool Definition payload。
- Context Service 记录 bounded compaction count、last/event status、input/output token estimate、batch count 和受控 failure code；不保存 summary 文本或异常正文。恢复已有 Projection 时，public count 仍反映 durable Projection revision。
- `UthCodeApplication.diagnostics()` 汇总 Context、compaction、Tool-result externalization、Session recovery/busy 和 Provider Usage；`ApplicationStatus` 同步暴露该安全 projection。Tool externalization 只记录 attempts、inline/externalized/failed counts、bytes 和受控 error code，不复制结果、ref、hash 或路径。
- `ApplicationSessionService.public_diagnostics()` 记录 active session、recovery diagnostics、最近一次 create/resume 的稳定状态和 busy kind，不复制 storage path、History 或 Tool Result。执行与 persistence 的真假继续分离，失败不触发 Tool retry。
- 新增 `application/provider_usage.py`。它只读取现有 Integration 已转换的 `Usage` 字段和安全字段路径，返回 input/output/total 与 cache read/write 的 `status`、tokens、provenance；Provider 未提供 cache 字段时为 `not_available`，Usage 默认 `0` 不作为实测值，显式报告的 `0` 保持 `available`。Anthropic mapper 只在原始 cache 字段实际出现时写入对应 details key；Responses/Chat 复用现有 nested Usage mapping。
- Eval 增加 `diagnostic_facts`：`success`、`tokens`、`tool_calls`、`compact_count`、`rediscovery`、`repeated_exploration`、`externalization`、`prefix_stability`、`cache_reuse`。报告新增 `facts` 聚合和 `delta.facts`，保留原六维报告，不生成 overall，也不把 candidate 必须优于 baseline 作为 pytest 或 compare 通过条件。
- 新增 `tests/test_w05_diagnostics.py`，覆盖 diagnostics JSON 序列化/内容隔离、cache 缺测与显式零、ordinary history authority spoof、Runtime/Projection 稳定、目录 AGENTS scope/内容变化、未变化 resume 与离线删除 reason、Session busy、externalization failure 和 baseline/candidate facts compare。
- 更新 `eval/README.md` 说明 facts、NA 语义、cache provenance、固定 258K Operating Budget 边界；仅把现有 Task 9 Checklist 四项从 `[ ]` 勾为 `[x]`。

## 3. 字段来源与 NA 语义

| 公共事实 | 来源 | 缺失处理 |
| --- | --- | --- |
| selected/omitted、budget、Projection、epoch、prefix | `ContextSnapshot` 的安全 ID/计数/摘要字段 | 无 snapshot 为 `status=not_available` |
| compact | Application Context Service 的 attempt/event projection 与 durable Projection revision | 没有 Application diagnostics 时 fact 为 `not_available` |
| externalization | Application Tool Service materialization counters | 没有投影时为 `not_available`；不复制内容/ref/hash |
| recovery/busy | Application Session Service 的 recovery codes 和最后一次命令状态 | 无 durable Session 时保持 `not_available` / `busy=false` |
| cache read/write | 现有 Anthropic/Responses/Chat Usage mapping 的字段路径 | 未提供字段为 `not_available`；默认 0 不冒充测量，明确字段 0 为 available |

`compare_experiments()` 仍要求指纹、任务集合、样本数、per-task sample counts、schema 和 fingerprint variants 兼容；兼容后 facts 只做观察值 delta。不可获得的事实不会被填充为 0，也不会影响 candidate/baseline 的兼容性判断。

## 4. 验证记录

- `conda run --no-capture-output -n re-uthcode python -m pytest -q tests/eval/test_eval_reporting.py tests/eval/test_eval_execution.py tests/test_w05_diagnostics.py`：**44 passed**，8.95s。
- `conda run --no-capture-output -n re-uthcode python -c "import os,pytest; os.environ.pop('NO_COLOR',None); os.environ['TERM']='xterm-truecolor'; raise SystemExit(pytest.main(['-q']))"`：**1198 passed, 3 skipped**，108.21s。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests eval`：退出码 **0**。
- `conda run --no-capture-output -n re-uthcode python -m pip check`：**No broken requirements found.**
- `conda run --no-capture-output -n re-uthcode python C:\Users\93445\.codex\skills\uth-utf8-guard\scripts\check_utf8_docs.py "docs/work/T09-Prompt与ContextEngineering/T09-Prompt与ContextEngineering-checklist.md" eval/README.md "docs/work/T09-Prompt与ContextEngineering/feedback/W05-eval-diagnostics-feedback.md"`：**3 file(s) passed UTF-8 guard**。
- `git diff --check`：无 whitespace error；仅报告 Windows 工作树既有的 LF→CRLF 提示。

默认环境直接执行 `pytest -q` 时出现 3 个既有 TUI ANSI 颜色断言失败（`NO_COLOR`/`TERM=dumb`）；清除 `NO_COLOR` 并设置 truecolor 后同一全量套件通过，当前实现的最终全量结果以上述 **1198 passed, 3 skipped** 为准。

## 5. 工作包边界、未执行项与安全说明

- 按 `WorkPackageRules.md`，首次 Worker Prompt 后没有改写冻结的 Prompt、Spec、Tasks 或 Checklist 正文结构；“同步 Tasks/Checklist”与冻结规则冲突时只勾选已有 Task 9 Checklist 项，并在此记录。
- 没有执行真实 Provider baseline、网络调用、API key 读取或费用实验；B01/W03 的真实 baseline 仍为 `NOT VERIFIED (authorization required)`。本轮只执行离线 Fake/contract Eval。
- 没有实现 128K/1M/unknown-model window Eval、258K 阈值专项优化、Memory、retriever 或生产策略改写。`rediscovery` 和 Provider cache reuse 在没有公开结构化证据时保持 `not_available`。
- 未执行 commit、push、merge、rebase、tag、release 或工作包归档；没有发现需要删除的本轮临时文件、日志或业务外缓存。

## 6. Checklist

- [x] Context diagnostics schema/序列化与安全字段投影。
- [x] Provider cache availability/provenance 与缺测 NA 语义。
- [x] baseline/candidate facts、报告聚合与 compare delta。
- [x] epoch/prefix/resume/authority spoof/execution-persistence 回归。

## 7. Cleanup

保留本轮源代码、测试、`eval/README.md`、Task 9 Checklist 勾选和本 Feedback；未执行任何 Git 写入或删除用户既有文件。

## 第一轮定点返工

### 1. 正式 AgentRun Usage 已进入 Application diagnostics

- 正式路径 `create_application → create_run → start_turn → AgentLoop → TurnResult` 现在在 Application `_TurnDriver` 完成终止 `TurnResult` 的生命周期边界投影 Usage；Eval 和 Interface 不读取 Provider SDK/native payload，也不直接写 diagnostics。
- `AgentRun` 的终止结果携带当前 Turn 内所有 Provider iteration / Tool continuation 已累计的 `TurnResult.usage`，由 Application-owned `_record_formal_run_usage()` 转换为安全 public diagnostics。该投影只读取已有 UthCode `Usage`，不执行第二次 Provider request。
- Contract 固定为：`application.diagnostics()["provider_usage"]` 表示最近一次正式 AgentRun 中“实际观测到 Provider Usage”的终止 Turn 的累计 Usage；同一 Turn 内跨 iteration 累计，后续没有任何实际 Usage 的 pause/cancel/failure 不用空默认 `Usage` 覆盖已有投影。若终止路径确实已收到 Provider Usage，则只投影已发生的部分。
- 原有 `stream_generation() → _stream_with_token() → GenerationCompleted` 更新路径保持不变；新增正式 AgentRun 测试锁定 input/output/total、cache availability/provenance、单次 request 和不包含 native payload 的边界。

### 2. Eval token fallback 与 cache 语义

- `eval.metrics._efficiency()` 现在对 input、output、total 分别执行：Provider public diagnostics 中该字段是有效非负整数时优先使用；该字段缺失或不可用时独立回退到 `TurnResult.usage`；两边都缺失才为 `not_available`。因此一个 Provider 字段缺失不会丢弃另外两个 token fact，`provider_usage.status=not_available` 也不会遮蔽有效的 TurnResult Usage。
- cache read/write 与普通 token 独立：只接受 Provider diagnostics 中对应 cache projection 为 `available` 的值；TurnResult Usage 中默认的 cache `0` 不会被当作 Provider cache metric。Provider 没有明确 cache 报告时保持 `not_available` / `tokens=None`。
- cache availability 和 provenance 仍由 Provider mapper 实际报告的安全 details 字段路径证明；cache token 数值统一来自累计后的规范化 `Usage.cache_read_tokens` / `Usage.cache_write_tokens`。Core Usage 聚合现在递归保留多轮 details evidence，避免后续没有字段时抹掉首轮报告。
- 最终语义已锁定：未报告字段且默认值为 `0` → `not_available`；明确报告 `0` → `available, tokens=0`；多轮 read `5+0` → `available, tokens=5`；多轮 write `3+2` → `available, tokens=5`；首轮报告、后续轮未报告时 availability/provenance 仍保留首轮证据。公共 diagnostics 不复制完整 `Usage.details` 或 Provider native payload。

### 3. 新增测试与精确验证

- `tests/test_w05_diagnostics.py` 新增正式 FakeProvider AgentRun → `result()` → `application.diagnostics()` 测试；新增未知 Tool continuation 的两次 Provider iteration 累计 read/write cache 测试；新增 Provider diagnostics 缺测时的 total/input/output fallback 及逐字段部分 fallback 测试，并验证 cache 不从 TurnResult 默认零值伪造。
- `conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_w05_diagnostics.py tests/eval/test_eval_reporting.py tests/eval/test_eval_execution.py tests/test_application_runs.py tests/test_application_runtime.py tests/test_anthropic_integration.py tests/test_openai_responses_integration.py tests/test_openai_compat_integration.py`：**147 passed, 3 skipped**。
- `conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_architecture_boundaries.py`：**23 passed**。
- 默认 `conda run --no-capture-output -n re-uthcode python -m pytest -q`：**1198 passed, 3 skipped, 3 failed**；3 个失败均为既有 TUI ANSI 颜色断言，原因是 `NO_COLOR/TERM=dumb`，未触及本轮 diagnostics 代码。
- 清除当前测试进程的 `NO_COLOR` 并设置 `TERM=xterm-truecolor` 后重跑全量：**1201 passed, 3 skipped**。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests eval`：退出码 **0**。
- `conda run --no-capture-output -n re-uthcode python -m pip check`：**No broken requirements found.**
- `git diff --check`：退出码 **0**，无 whitespace error；仅有工作树既有的 LF→CRLF 提示。
- W05 原有 Checklist 复选框、冻结任务书正文、Spec、Tasks、Prompt 均未在本轮返工中修改。

### 4. 未执行项与范围边界

- 未执行真实远程/付费 Provider Eval、网络调用或 API key 读取/输出；本轮证据来自离线 Fake/contract 测试。
- 未实施 W06、T09-1 Model Limits、动态模型窗口、生产 Context policy 调整、Memory/retriever 或其他范围外能力。
- 未执行 Git commit、push、PR、merge、rebase、tag、release 或工作包 archive；未修改无关 Checklist。

### 5. UTF-8 guard

- files checked: `T09-Prompt与ContextEngineering-checklist.md`、`eval/README.md`、`W05-eval-diagnostics-feedback.md`。
- result: `check_utf8_docs.py` 输出 **OK: 3 file(s) passed UTF-8 guard**；未发现 replacement character、常见乱码或 Markdown fence 不平衡。
- repaired encoding issues: 无。
