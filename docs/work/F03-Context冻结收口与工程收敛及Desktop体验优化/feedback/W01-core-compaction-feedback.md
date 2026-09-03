# W01 Core Compaction Feedback

## 状态

T01 已完成 Core-only 实施与定向验收；未执行 Git commit、push、PR、merge、rebase、tag 或 release。

## 实际改动

- `src/uthcode/core/compaction.py` 现在承载 `CompactionPolicy`、`CompactionResult`、`ContextCompactor`、L4/L5 planner/parser/candidate builder 以及 single-flight。`ContextCompactor.compact()`、`_compact_locked()` 和只服务旧同步入口的 rolling 失败路径已删除。
- `parse_compaction_result()` 对 multi-turn 强制显式 `entries`、数量/顺序/`turn_id`/逐项 `refs`/`coverage` 与 Core epoch 完全一致；纯文本、top-level `summary`、字符串 entry 和缺失 refs/coverage 只在 single-turn 保留有限兼容。
- 新增 process-local `OversizedCompactionPlan`、`CompactionSubpass` 和结果验证：按完整 TranscriptEntry 或可拆分 text part 形成 bounded 输入；subpass 只保留原序列覆盖，不生成 durable ID/Timeline record。所有 subpass 成功后才合成一个原 Turn identity、完整范围 ref 的 `SemanticEntry`；failure、cancel 或 invalid result 返回 unchanged/无 candidate。
- `src/uthcode/core/context.py` 仅保留 Context budget/compiler/accounting/gate 实现；`src/uthcode/core/__init__.py` 从 `core.compaction` 直接导出 compaction 公共类型和 parser，未增加 legacy alias。为保证 W01→W02 过渡期间现有 Application 可运行，`context.py` 仍保留显式内部导入供旧调用方解析，但不再加入其 `__all__`；W02 应将 Application 调用方迁移到 `core.compaction`。
- 更新 Core compaction/compiler/e2e 测试：固定 strict multi-turn、合法 refs、oversized success/full refs、failure/cancel/invalid no-candidate 和 single-flight；测试 Provider fake 的合法 multi-turn 响应从请求合同复制 refs。

## 关键数据流

`Transcript`/已提交 `Timeline` → Core `plan_epoch()` 或 `plan_oversized_turn()` → Provider-independent 结构验证 → `build_epoch_candidate()` / `build_oversized_candidate()` → prospective candidate。oversized 的中间 subpass 只存在于本次调用的内存对象中，只有最终完整 Turn Fine 与 checkpoint 进入候选 Timeline；Application 仍负责 Provider 调用和后续 durable commit。

## 精确验证

- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_context_compaction.py tests/test_context_compiler.py tests/test_t09_1_context_protocol_e2e.py -q`：`57 passed`，exit code `0`。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_context_compaction.py tests/test_context_compiler.py tests/test_t09_1_context_protocol_e2e.py tests/test_architecture_boundaries.py -q`：`80 passed`，exit code `0`。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src`：exit code `0`。
- `rg -n "ContextCompactor\.compact|_compact_locked" src tests eval desktop/src desktop/tests`：`0 matches`。
- Core import smoke check确认 `ContextCompactor.__module__` 与 `CompactionPolicy.__module__` 均为 `uthcode.core.compaction`，新 oversized 类型和 parser 可由 `uthcode.core` 导入。
- `git diff --check`：exit code `0`；仅有 Git 关于 LF→CRLF 的环境提示，无 whitespace error。

## Checklist

T01 六项均已勾选；T02～T09 未勾选，留给后续 Worker。

## 偏差、未完成项与风险

- W01 未修改 Application/Desktop。当前 `generation.py` 的旧 Provider prompt 仍未要求模型回传 refs，W02 在迁移 oversized/provider orchestration 时必须同步更新为显式 refs 合同；本反馈中的 e2e fake 已按新合同修正。
- `build_oversized_candidate()` 可直接接收调用方提供的最终 `final_summary`；未提供时会合并各 subpass summary 并继续执行 hard-cap 校验，过长时拒绝 candidate。W02 应在 Provider fold/orchestration 中提供受 cap 约束的最终摘要。
- 未新增依赖，未修改 `core/history.py`、Application、Desktop、用户原有 `.workbuddy/` 或 `临时目录/`。

## 遗留负担清理

旧同步入口、`_compact_locked`、`SummaryFunction` 和仅服务旧入口的 Core 实现/测试已移除；生产 single-flight 及其测试保留。Application 的旧导入路径是 W02 的迁移范围，不在本 Worker 越权修改。

## 返工第 1 轮

### Reviewer findings

- P1：`build_oversized_candidate()` 原先允许调用方用任意 `final_summary` 绕过 aggregate summary 的预算与结果链；缺少 aggregate 超 available 时的 bounded fold、多轮 fold 及 fold failure/cancel/invalid 收口。
- P2：`_compaction_input_text()` 返回后残留不可达的 top-level `result.summary` 校验，`CompactionStructuredResult.summary` 未执行 hard-cap 校验。

### 实际修复

- 删除 `final_summary` 参数，新增 process-local `OversizedFold`、`OversizedFoldPlan`、`OversizedFoldResult` 和 `plan_oversized_fold_round()`。Core 将已验证的 subpass summaries 以不超过 available input 的 fold 输入分组；每轮成功输出可再次规划下一轮，最多 bounded 轮次，缺失/多余 round、不可规划或 fold 失败均不形成最终 Fine。
- 新增 `parse_oversized_fold_result()`，fold 输出只能是受 hard-cap 约束的 summary 或明确 failure/cancel 状态，不得携带 entries、refs、coverage 等 durable 语义。`build_oversized_candidate()` 只有完整 fold 链结束且最终聚合 summary 再次通过 cap 校验时才 append 一个完整 Turn Fine；聚合超预算时没有 fold 结果会返回 `oversized_fold_required`。
- 将 top-level summary 的 token 校验恢复到 `_validate_summary_limits()`，删除 `_compaction_input_text()` 后的不可达代码，并新增 typed structured result 与 JSON payload 两条超 cap 回归。
- 扩展 Core compaction 测试覆盖 aggregate summaries 超 available、多轮 fold、missing fold、fold failure/cancel/invalid，以及 bounded fold input tokens。

### 返工验证

- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_context_compaction.py tests/test_context_compiler.py tests/test_t09_1_context_protocol_e2e.py -q`：返工前后当前最新结果为 `58 passed`，exit code `0`。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests`：exit code `0`。
- Reviewer 关注的 `final_summary` 与不可达校验扫描：`final_summary` active source/test 命中为 `0`；top-level 校验仅位于 `_validate_summary_limits()`，`_compaction_input_text()` 后无残留语句。
- 原 T01 架构验证仍为 `23 passed`（与定向测试合并运行时 `80 passed`）；旧入口扫描仍为 `0 matches`；UTF-8 guard 与 `git diff --check` 在返工文档写回后重新执行并通过。

### Checklist / 未完成项

T01 六项继续保持勾选；未勾选 T02～T09。未修改 Application/Desktop、`core/history.py`、用户原有 `.workbuddy/` 或 `临时目录/`，未执行 Git 写操作。W02 仍需接入 fold Provider orchestration，并继续迁移 Application 的旧 `core.context` compaction imports。

### 返工第 2 轮验证收口

此前标记为待执行的文档收口验证现已完成：`conda run --no-capture-output -n re-uthcode python -m compileall -q src tests` exit code `0`；UTF-8 guard 输出 `OK: 2 file(s) passed UTF-8 guard`；`git diff --check` exit code `0`，仅有 LF→CRLF 环境提示；独立 wildcard smoke 输出 `core __all__ wildcard exports ok`，exit code `0`。

### 返工第 1 轮验证计数更正

上述返工验证段中的合并计数为早先快照；最新命令 `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_context_compaction.py tests/test_context_compiler.py tests/test_t09_1_context_protocol_e2e.py tests/test_architecture_boundaries.py -q` 实际结果为 `81 passed in 17.42s`，exit code `0`。单独 W01 定向测试最新结果为 `58 passed in 12.62s`，exit code `0`；其余验证结论不变。

## 返工第 2 轮

### Reviewer finding

- P2：`core.__all__` 声明了已迁移至 `core.compaction` 的 `DeterministicTokenEstimator`，但 `uthcode.core` 未导入该名称，导致 `from uthcode.core import *` 在解析导出名时抛出 `AttributeError`。

### 实际修复

- 从 `uthcode.core.compaction` 正常导入 `DeterministicTokenEstimator`，不增加兼容别名或重复实现。
- 新增 `from uthcode.core import *` smoke test，逐一断言 `core.__all__` 中的所有名称均可解析且与包属性一致。

### 返工验证

- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_context_compaction.py tests/test_context_compiler.py tests/test_t09_1_context_protocol_e2e.py tests/test_architecture_boundaries.py -q`：`82 passed in 17.30s`，exit code `0`。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests`：待文档收口前执行。
- `core.__all__` 全量 wildcard smoke test：已纳入定向测试并通过。

### Checklist / 未完成项

T01 六项继续保持勾选；未勾选 T02～T09。未修改 Application/Desktop、`core/history.py`、用户原有 `.workbuddy/` 或 `临时目录/`，未执行 Git 写操作。W02 仍需接入 fold Provider orchestration，并继续迁移 Application 的旧 `core.context` compaction imports。
