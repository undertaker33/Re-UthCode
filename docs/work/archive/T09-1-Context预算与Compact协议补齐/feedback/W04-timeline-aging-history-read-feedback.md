# W04：Timeline Aging 与 HistoryRead Feedback

## 1. 状态

- T04 已完成并保持在 `docs/work/`，未归档。
- 本反馈只覆盖 Fine Timeline aging、逻辑 supersede、HistoryRead 和对应验证；没有实施 T05–T08 的命令、手动 compact、诊断交付或清理范围。
- 没有执行 Git commit、push、merge、rebase、tag 或工作包归档。

## 2. 实施结果

### 2.1 Fine Timeline aging / L5

- `Timeline` 新增逻辑视图：已提交 `EpochMacroSummary.coverage` 覆盖的 Fine 不再进入当前逻辑 Context，但原始 Fine 仍保留在物理 append-only Timeline 中。
- `EpochMacroSummary` 的 coverage 现在要求非空、Turn ID 唯一且为有效字符串；Timeline 物理产品记录仍只有 `SemanticEntry`、`EpochMacroSummary`、`ActiveCheckpoint` 三类。
- `ContextCompactor.plan_timeline_aging_epoch()` 只从最旧的已提交 Fine transaction 选择候选，要求所有 raw refs 属于当前 Session，并能由 `Transcript.select(..., complete_only=True)` 精确解析为完整 semantic unit。最旧候选不安全或超预算时返回 `no_safe_epoch`，不会跳过到后续 epoch。
- L5 input 由 raw `SemanticUnit.to_dict()` 生成，并重新读取/校验 Transcript boundary；没有把 Fine summary、Macro summary 或 summary-of-summary 放入模型证据。
- `build_timeline_aging_candidate()` 只生成一个 `EpochMacroSummary`，通过 `append_transaction()` 先追加 Macro、最后追加 `ActiveCheckpoint`；物理 Timeline 不删除记录。
- `ApplicationContextService.age_timeline_async()` 每次最多执行一个 aging epoch，使用同一 Session 单飞锁、最多一次重试、取消传播和提交失败 fail closed；不写 durable cursor/FSM/job/pointer。
- 正式 Agent Turn 在同一冻结 Provider/model/ContextBudget 下，先根据 `fine_timeline_budget` 独立触发无工具 L5，再重新编译普通请求；L5 可以在普通请求低 pressure 时触发。L5 使用独立 metadata level、Tool-free request 和独立 bounded diagnostics。

### 2.2 HistoryRead

- 新增独立 `integrations.tools.history_read` namespace、schema、错误码和 `HistoryReadPolicy/Page`，不复用 ToolResultRead 的 ref、文件存储、异常或权限资源。
- ref 只接受 Core `TranscriptRef.to_token()` 的 canonical opaque token；不接受路径、搜索条件或跨 Session ref。
- 读取只针对当前 active Session 的 exact Transcript ref，要求完整 semantic boundary，并按 entry offset/limit 返回 bounded page；malformed、cross-session、split/incomplete/out-of-range boundary 和 envelope 超出 output limit 均受控失败。
- 权限 Action 使用 `tool=HistoryRead`、`action=read`、`effect=READ`、`resource=session-transcript:<ref>`、`scope=INSIDE`，与 ToolResultRead 的 `session-result:<ref>` 保持独立。
- HistoryRead 的成功输出在 Application materialization 层保持 inline，不会递归 externalize，也不会把 HistoryRead 交给 ToolResultFileStore。

## 3. Raw evidence provenance / no summary-of-summary

L5 候选来源链为：已提交 Timeline 的 Fine `SemanticEntry.refs` → 当前 Session 的 `Transcript` → `Transcript.select(..., complete_only=True)` → 完整 raw `SemanticUnit` → bounded L5 input。候选 builder 再次用同一 raw ref 校验边界后才创建 Macro。测试明确验证 L5 input 含 raw fact、且不含 Fine summary；没有从 Fine/Macro 的 summary 再生成 Macro。

## 4. HistoryRead permission / failure matrix

| 场景 | 结果 | 是否产生读取权限 |
|---|---|---|
| canonical ref、active Session、完整 boundary、bounded page | 成功返回 raw page | 产生独立 `HistoryRead/read/READ/INSIDE` Action |
| token malformed 或非 canonical | `invalid_history_ref` | 不产生 Action，preflight fail closed |
| ref 属于其他 Session、无 active Session | `history_session_mismatch` | 不允许跨 Session 读取 |
| ref 越界、切分 semantic unit、包含 incomplete unit、offset 越界 | `invalid_history_boundary` | 不读取、不修复、不回退 |
| JSON envelope 无法放入配置 output limit | `history_read_output_limit_exceeded` | 不递归 externalize，不扩大 page |
| ToolResultRead ref 传给 HistoryRead，或反向使用 | 分别按各自 namespace 拒绝 | 两套 resource/validation 不互通 |

## 5. 验证

所有命令均在 `conda run --no-capture-output -n re-uthcode` 下执行。

| 命令 | 精确结果 |
|---|---|
| `python -m pytest tests/test_timeline_contract.py tests/test_context_compaction.py tests/test_history_read_tool.py tests/test_application_tools.py tests/test_tool_result_persistence.py -q` | **56 passed** |
| `python -m pytest tests/test_context_budget_gate.py tests/test_application_runs.py tests/test_t09_1_context_protocol_e2e.py tests/test_architecture_boundaries.py -q` | **94 passed** |
| `python -m pytest tests/test_history_contract.py tests/test_application_runtime.py tests/test_session_files.py -q` | **42 passed** |
| `python -m compileall -q src/uthcode tests/test_history_read_tool.py tests/test_context_compaction.py tests/test_t09_1_context_protocol_e2e.py` | exit 0 |
| `git diff --check` | exit 0 |

新增测试覆盖：L5 低 pressure 独立触发、raw-only input、Macro/checkpoint 顺序、物理保留/逻辑 supersede、unsafe oldest epoch fail closed、HistoryRead canonical/cross-session/boundary/page/output-limit/permission/materialization 边界。

## 6. 风险、未验证项与遗留范围

- 未执行真实 Provider 网络调用；Provider 端只用受控测试 double 验证 request metadata、tool-free、冻结 model 和返回协议。
- 未执行全量 `python -m pytest -q` 和 `tests/test_tui.py`；W01–W03 已记录的 TUI renderer 已知失败未在本包重复验证。
- T05–T08 的命令入口、manual compact、overflow/diagnostics delivery、全量清理和工作包归档仍保持未实施状态，不作为 T04 完成条件被提前吸收。
- 当前工作区原有的 `docs/core-design/A04-Orchestration/` 未跟随本任务修改、暂存或删除。

## W04 第一次验收返工

### 根因

W04 已将 `HistoryRead` 注册进正式 Application Tool 集合，并保持其位于 `ToolResultRead` 之后；T08 正式端到端测试的三处精确工具顺序断言仍是旧清单，直接期待 `AskUserQuestion` 出现在 `ToolResultRead` 后，因此出现两条 T08 失败。第一处 Plan 断言失败遮挡了同一测试后续 Default 清单的缺口。根因是测试事实未同步，不是生产 Tool 注册顺序或 HistoryRead 设计错误。

### 实际修复的精确断言

仅修改 `tests/test_t08_e2e.py`，并完成全文件扫描：

- `test_t08_formal_application_e2e_plan_execution_steering_and_reset` 的 `provider[0]` Plan 工具清单（当前断言起始于第 532 行）；
- 同一测试的 `provider[3]` Default 工具清单（当前断言起始于第 542 行）；`provider[6]` 继续复用该完整 Default 清单；
- `test_t08_plan_full_access_rejects_hidden_write_before_permission` 的 `provider[0]` full_access Plan 工具清单（当前断言起始于第 706 行）。

三处都只在原有 `ToolResultRead` 后插入 `HistoryRead`，没有删除精确断言、放宽为子集/集合比较、修改数量语义或跳过测试。全文件扫描未发现其它受正式 Application 注册影响的硬编码工具名称或数量断言。

### HistoryRead 的真实注册顺序

`ApplicationToolService` 的正式注册顺序保持为：

```text
ToolResultRead → HistoryRead
```

对应的正式端到端工具顺序为：

```text
Plan：ReadFile, Glob, Grep, Bash, ToolResultRead, HistoryRead,
      AskUserQuestion, ProposePlan

Default：ReadFile, WriteFile, EditFile, Glob, Grep, Bash,
         WaitForSteering, ToolResultRead, HistoryRead,
         AskUserQuestion, TodoWrite

full_access Plan：ReadFile, Glob, Grep, Bash, ToolResultRead,
                  HistoryRead, AskUserQuestion, ProposePlan
```

### 本轮验证结果

以下命令均使用 Conda 环境 `re-uthcode`：

| 命令 | 精确结果 |
|---|---|
| `python -m pytest tests/test_t08_e2e.py -q` | **5 passed in 1.44s** |
| `python -m pytest tests/test_timeline_contract.py tests/test_context_compaction.py tests/test_history_read_tool.py tests/test_application_tools.py tests/test_tool_result_persistence.py -q` | **56 passed in 5.59s** |
| `python -m pytest tests/test_context_budget_gate.py tests/test_application_runs.py tests/test_t09_1_context_protocol_e2e.py tests/test_architecture_boundaries.py -q` | **94 passed in 12.60s** |
| `python -m pytest tests/test_history_contract.py tests/test_application_runtime.py tests/test_session_files.py -q` | **42 passed in 4.18s** |
| `python -m pytest -q --deselect tests/test_tui.py::test_plan_revisions_and_task_state_append_as_distinct_permanent_blocks --deselect tests/test_tui.py::test_renderer_restores_roles_surfaces_markdown_and_code_colours --deselect tests/test_tui.py::test_tool_rows_keep_status_text_and_semantic_colour` | **1237 passed, 3 skipped, 3 deselected in 97.99s** |
| `python -m compileall -q src tests` | exit 0 |
| `git diff --check` | exit 0；仅有工作区既有 LF/CRLF 转换提示，无 whitespace error |

### 实际修改文件与边界

- 本轮实际修改：`tests/test_t08_e2e.py`、本 Feedback 文件；未修改任何生产源码、T04 Checklist、T09-1 主文档或 `docs/core-design/A04-Orchestration/` 用户文件。
- W04 指定测试、T08 正式端到端测试和全量回归均已通过；全量仅排除用户指定的三条既有 TUI ANSI 断言，未排除本轮 T08 测试。
- 未验证真实 Provider 网络调用；本轮仅使用现有 fake/test double。T05～T08 主体、L5/HistoryRead 设计和 Application Tool 注册语义未重新实施或重探索。
- 未执行任何 Git 写操作：没有 commit、push、merge、rebase、tag、release、归档、暂存或清理；工作区其它用户改动均保留。
