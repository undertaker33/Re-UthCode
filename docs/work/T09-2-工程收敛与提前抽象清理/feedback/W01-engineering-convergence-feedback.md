# W01 Engineering Convergence Feedback

## 当前状态：Task 3 冻结任务书冲突，待用户决定

已完成并验证 Task 1、Task 2；Task 3 尚未修改源码。按 `WorkPackageRules.md` 的实施冻结规则，以下冲突范围已停止，未通过改写冻结文档或规避扫描继续实施。

### 已完成的实际改动

- Task 1：删除旧 Generation facade 与手工 Tool 路径；Application、TUI 和测试统一经 `create_application -> create_run -> start_turn`。
- Task 2：删除 `core/hooks.py`、Hook 注入与组合测试；PLAN 非 READ 控制固定在 preflight 后、Permission 前，DEFAULT 未完成 Task 的 completion gate 固定在 usage 记账后。

### 已验证结果

- Task 1 定向测试：`214 passed, 1 skipped in 25.44s`；架构测试：`23 passed in 4.48s`；旧 Generation 符号扫描为 0。
- Task 2：`tests/test_agent_loop.py` 为 `49 passed in 1.02s`；Permission/Planning 五文件为 `191 passed in 15.21s`；Application/Boundary/Package 三文件为 `75 passed in 12.16s`；Hook 符号扫描为 0。
- 已勾选 Checklist 中上述精确验证对应的 Task 1、Task 2 项；该 Checklist 修改后 UTF-8 guard 通过。

### 冲突证据与影响

`T09-2-工程收敛与提前抽象清理-tasks.md:89` 明确要求保留并改造 `DeterministicTokenEstimator`，使其使用 `__call__`。但 Checklist Task 3 要求执行包含 `TokenEstimator` 的普通 `rg` 扫描且结果为 0；该模式会匹配 `DeterministicTokenEstimator` 的名称本身。

因此不能同时保留任务书指定名称并如实勾选该扫描项。继续实施前需要由用户选择冻结工作包的修订方向：

1. 保留 `DeterministicTokenEstimator` 名称，并将 Checklist 的扫描目标改为只匹配独立的旧 Protocol/接口名；这是推荐方案，最符合 Task 3 对 callable 化该具体实现的明确要求。
2. 维持 Checklist 的零匹配要求，并将该 concrete fallback 类型重命名为不含 `TokenEstimator` 的名称；这会偏离 Tasks 对具体名称的要求。

未验证项、风险与遗留问题：Task 3 至 Task 9 均未开始；除上述冻结冲突外，尚未发现新的产品、架构或安全边界冲突。

## 返工轮次 1：用户选择 A 后重新派发

用户已明确选择保留 `DeterministicTokenEstimator` 名称，并将 Checklist Task 3 的否定扫描定点改为匹配独立旧 Protocol/接口名。该修订已由主协调方完成并通过 UTF-8/fence 校验；没有改变产品语义或实现范围。

本 Worker 从 Task 3 恢复串行实施，保留此前已验证的 Task 1、Task 2 代码、Checklist 状态和证据。

## 完成记录：Task 3～Task 9

### 实际改动与保留的正式链路

- 删除旧 Generation facade、Runtime Hook 组合、Context 身份包装/多形态入口、RuntimeLog/ApplicationHistory、未来命令占位/同步 Dispatcher 及三个空 capability Protocol；没有保留兼容别名或双轨入口。
- 正式执行链唯一为 `create_application -> create_run -> start_turn -> AgentLoop`。PLAN 非 `READ` Tool 在 trusted preflight 后、Permission 前由 Agent Loop 固定拒绝；DEFAULT unfinished Task 在 usage accounting 后、assistant final 提交前固定阻断。
- Session 硬切 v3：`metadata.json` schema 为 3，`transcript.jsonl`/`timeline.jsonl` record envelope 仍为 2；布局只包含 metadata、Transcript、Timeline、writer lock 和 Tool Result 目录。v1/v2 稳定抛 `SessionIncompatibleError`，不迁移、不双读。
- 命令 Registry 只保留有 handler 的现存命令，Dispatcher 只保留 async 入口；删除的 `/config`、`/login`、`/memory`、`/dream`、`/review` 统一返回 UNKNOWN_COMMAND。
- 已恢复并迁移原三份大型 Application 测试及 `tests/test_command_dispatcher.py` 的有效断言：Run/Turn、Provider/配置快照、Tool、Permission、Session、async 成功/unknown/usage/exception、Help/Completion 均继续覆盖，不以整文件删除替代验证。

### 新增的正式 E2E 覆盖

- `tests/test_application_runs.py::test_t09_2_formal_headless_run_turn_keeps_tool_plan_todo_gate_and_final_answer`：真实 `create_application -> create_run -> start_turn`、离线脚本 Fake Provider、`ReadFile`、PLAN 审批、Todo completion block 与最终回答。
- `tests/test_w06_integration_delivery.py::test_t09_2_v3_session_formal_turn_compact_close_reopen_resume_preserves_facts`：v3 Session 实际 Turn、大 Tool Result ref、compact、close、reopen/resume，以及 Transcript、Timeline、Instruction State 一致性。

### 精确验证结果

- Task 3 Context Compiler/Budget/Compaction：`30 passed in 3.95s`；T09-1 Context E2E：`23 passed in 3.75s`。
- Task 4 History/Session：`28 passed in 1.59s`；Session、HistoryRead、Tool Result、Compact、命令集：`43 passed in 9.99s`。
- Task 5 Command Registry/Parser/Completion/Dispatcher：`51 passed in 1.18s`；W04 Session commands 与 TUI：`83 passed in 16.02s`。
- Task 6 package/architecture：`33 passed in 8.32s`。
- Task 7 architecture/package：`33 passed in 6.94s`；CLI/TUI/ApplicationRuns/Eval execution+runner：`165 passed in 59.81s`；9 份当前事实文档通过 UTF-8 guard。
- Task 8 Headless/Tool/PLAN/Todo/cancel：`3 passed in 0.82s`；v3 Session/compact/reopen/resume：`31 passed in 7.10s`；CLI/TUI/async commands/Completion/cancel cleanup：`116 passed in 19.81s`。
- Task 9 最终全量：`1189 passed, 3 skipped in 96.56s`；`python -m compileall -q src tests eval` 退出码 0；`python -m pip check` 输出 `No broken requirements found.`；`git diff --check` 无 whitespace error。
- 六组旧符号否定扫描均为 0：Generation facade、Runtime Hook、Context wrappers/old estimator contract、RuntimeLog、旧命令协议、capability Protocol。

### 文档、欠账与边界

- 已同步 A01～A04、T09 核心设计、命令手册、Tools、TUI Context 与 Context Index；文档只描述固定控制、Session v3、async Dispatcher 和唯一 Run/Turn 链。
- 已删除 OutstandingDebtList 中 T02 占位命令与 T08 假设性 Hook 扩展欠账，新增 T09-2“暂无明确能力欠账”；因未获 W01 授权的 `AGENTS.md` 用户改动尚待基线分类确认，Context Index 暂保持 T09-2 为 `not_implemented`（部分实施），未归档。
- 未修改 T02/T05/T08/T09/T09-1 的冻结正文、Spec、Tasks、Prompt 或 Checklist；未处理 258K 默认窗口问题；未执行任何 Git 写操作、提交、推送、合并、rebase、tag、release 或归档。

### 未验证项、风险与遗留

- 产品行为未留未验证项；除工作树范围确认外，Checklist 所列实现和验收命令均已执行。
- 工作树存在一项不属于 W01 的既有/并发 `AGENTS.md` 修改（新增“工程收敛与反过度设计”规则），本 Worker 未改写或覆盖；其是否属于授权基线需要主协调方确认。除此以外，工作树改动均在 T09-2 实施、当前事实文档或其 Feedback/Checklist 范围内。

## 返工轮次 2：用户确认 AGENTS 基线后的文档收口

用户已明确确认：`AGENTS.md` 新增的 57 行规则由用户本人修改，必须保留，并在下一次 T09-2 相关提交、推送时一并纳入。本轮没有修改 `AGENTS.md`，也没有执行 commit、push、merge、rebase、tag、release 或归档。

该决定解除上一轮记录的工作树范围阻塞。此次只完成 Checklist 勾选、Feedback 追加和 Context Index 状态收口；没有代码或测试改动，未重跑测试。沿用上一轮已取得的证据：最终全量 `1189 passed, 3 skipped in 96.56s`、`compileall -q src tests eval` 退出码 0、`pip check` 无损坏依赖、`git diff --check` 无 whitespace error，以及全部修改 Markdown 的 UTF-8 guard 通过。

因此 T09-2 已在 Context Index 标记为 `implemented_unarchived`，仍保留在 `docs/work/`，不归档。
