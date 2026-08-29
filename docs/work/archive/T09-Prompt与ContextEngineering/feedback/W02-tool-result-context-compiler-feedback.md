# W02 Context Compiler / Session Store Feedback

## 执行结论

W02 已按 Prompt 的严格顺序完成 Task 4 的 Context Compiler 基础和 Task 5 的 Session Store 基础。没有实施 Task 6～Task 12、T09-1 Model Limits、Tool Result 外置、Compaction、Slash/TUI、Eval 或 Git 写入。

Tasks、Spec、Prompt 正文保持冻结；只更新了本 Feedback 和 Checklist 中已有的验收复选框。工作包未归档，未执行 commit、push、merge、rebase、tag、release。

## 固定预算与 Context Compiler

- `src/uthcode/core/context.py` 新增 provider-independent `ContextCompiler`、不可变 `ContextSnapshot`、`ContextSourceBundle`、固定 `CONTEXT_OPERATING_BUDGET_TOKENS = 258_000` 和稳定 fallback token estimator。
- Instruction Plane 从 W01 的 Public Prompt、Core Contract、`ProjectInstructionSource` 有序构造；snapshot 记录 instruction epoch、stable-prefix estimated tokens/fingerprint、changed/reason 和 Projection revision。
- Working Set 严格按 protected context/current turn/未闭合 unit、Projection、最新到最旧的完整 semantic unit、current-turn/runtime/environment delta 选择；ToolCall/ToolResult 作为同一 SemanticUnit，ref/preview 不会单独漂移。没有加入关键词、embedding、retriever 或相关性排序。
- `ToolDefinitionSource` 保持 Tool System 唯一来源。Tool schema 计入固定预算并形成 fingerprint，但只以结构化 definitions 保留，不渲染进 Instruction Plane 文本。
- 仅 Runtime、Projection 或当前上下文变化时，stable prefix fingerprint 和 instruction epoch 保持稳定；W01 loader 提供的 scope/content change reason 会在 AGENTS 变化时进入 snapshot diagnostics。
- `src/uthcode/application/context.py` 和 `UthCodeApplication.compile_context()` 负责组合当前 Application sources；已有 Provider 两平面正式 request mapper 仍留给 Task 7，当前 Worker 没有改写 `GenerationRequest` 或 Agent Loop 的既有调用路径。

## Session Store 与恢复

- `src/uthcode/integrations/session_files.py` 实现版本化 Session layout：`metadata.json`、`history.jsonl`、`runtime.jsonl`、`writer.lock`、`tool-results/`。
- History 使用严格 envelope/kind/sequence 校验；append 采用 UTF-8 JSONL、flush/fsync；metadata 使用 temp + fsync + atomic replace。Projection 记录只追加，恢复由最后一个合法 ProjectionRecord 推导，不维护可变 pointer。
- 恢复只接受连续完整记录和完整 semantic boundary；尾部半写或未闭合 semantic tail 可诊断并忽略，中段损坏、未知 schema/kind、序列缺口和不匹配 Projection fail closed。
- writer 使用进程持有的 Windows/POSIX 排他 OS 锁；Application resume 取得锁后才读取 metadata、History 和当前 Instruction State，第二个进程得到 `session busy`。
- `runtime.jsonl` 只保存非语义 runtime facts；文件删除不影响 History/Projection 恢复，Stream/UI lifecycle 没有写入 History。
- `src/uthcode/application/sessions.py` 提供 Application Session create/resume/catalog；project key 由当前 Instruction Loader 的规范化 project root 得到，catalog 按 durable `last_used_at` 倒序并按 project key 隔离。
- metadata 只保存 activated directory scopes、epoch、prefix fingerprint 和 source fingerprints，不保存 AGENTS 正文。resume 使用 W01 同一 Loader 重读当前文件系统；未变化保持 epoch/fingerprint，修改/删除/重新出现产生明确 change reason，同时保留已激活目录 scope 标识。Session Store 不恢复 TaskState/PlanState checkpoint。
- 新增 `InstructionLoader.reset_for_new_session()`，避免同一进程新 Session 继承旧 Session 的 directory scopes；Application Session close 在释放锁前同步当前 Instruction State。

## 实际修改文件

- `src/uthcode/core/context.py`
- `src/uthcode/core/__init__.py`
- `src/uthcode/application/context.py`
- `src/uthcode/application/sessions.py`
- `src/uthcode/application/__init__.py`
- `src/uthcode/application/bootstrap.py`
- `src/uthcode/application/generation.py`
- `src/uthcode/application/instructions.py`
- `src/uthcode/integrations/session_files.py`
- `tests/test_context_compiler.py`
- `tests/test_session_files.py`
- `tests/test_architecture_boundaries.py`
- `docs/work/T09-Prompt与ContextEngineering/T09-Prompt与ContextEngineering-checklist.md`
- 本 Feedback 文件

架构测试的既有“未来模块缺失”白名单已按 W02 的正式 `core/context.py`、`application/context.py` 边界调整，并允许 Application Session service 使用 Session Integration；没有放宽 Core→Integration 或 Integration→Application 反向依赖。

## 精确验证结果

- `conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_context_compiler.py tests/test_session_files.py`：`11 passed in 8.49s`。
- `conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_context_compiler.py tests/test_provider_contract.py tests/test_application_runtime.py tests/test_architecture_boundaries.py`：`69 passed in 11.46s`。
- `conda run --no-capture-output -n re-uthcode python -m pytest -q`（`NO_COLOR` 清除、`TERM=xterm-truecolor`）：`1113 passed, 3 skipped in 141.70s (0:02:21)`。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests eval`：退出码 `0`。
- `conda run --no-capture-output -n re-uthcode python -m pip check`：退出码 `0`，`No broken requirements found.`。
- `git diff --check`：退出码 `0`；仅有既有 LF/CRLF 转换提示，没有 whitespace error。

## Checklist 状态

- Task 1～Task 3：沿用 W01 已有证据和勾选状态。
- Task 4：本 Worker 已勾选固定预算、无 Model Limits、阶段边界、deterministic Working Set 及定向测试证据；`/status`/TUI ring 的正式接入仍属于 Task 8，因此对应复合验收项保留未勾选。
- Task 5：本 Worker 已勾选 durable append、尾部/中段恢复、跨进程 busy、runtime 删除、project key/last-used、Instruction State metadata 与 AGENTS 离线变化证据；跨进程新 Run/Turn 的正式入口接线留给 Task 10，因此该复合验收项保留未勾选。
- Task 6～Task 12：未实施、未勾选。

## 未完成项与边界

- 当前 Provider 仍接收既有 `GenerationRequest.system_prompt + messages`；W02 只提供 Context Snapshot 和 Application composition，不提前实施 Task 7 的两平面 request mapper，也没有移除 Task 10 才收口的 `RunState.messages` 正式路径。
- Session Store 能恢复 canonical History、Projection、Runtime Log 和 Instruction State metadata，但不恢复旧进程的 Run/Turn、Task/Plan、Pending Tool、Permission waiter、Provider request 或协程位置；这些不是 checkpoint 保证。
- 固定 258K 仍不是远端模型窗口声明；没有 `ModelProfile.max_input_tokens`、Provider/bundled window metadata、dynamic budget resolver 或 T09-1 阈值优化。真实输入窗口小于 258K 的模型长上下文安全性未在 T09 阶段承诺。
- Tool Result externalization、Compaction、Slash/TUI、Eval、完整 Headless 多 Turn→resume→final 主流程和包级用户文档同步留给后续 Worker；本次没有把它们标记为已实现。

## UTF-8 guard

- files checked: `T09-Prompt与ContextEngineering-checklist.md`、`W02-tool-result-context-compiler-feedback.md`。
- result: 写入前 Checklist 已通过 `OK: 1 file(s) passed UTF-8 guard`；写入后需对上述两份 Markdown 再执行同一 checker，并确认 replacement character、常见乱码和 Markdown fence 均不存在。
- repaired encoding issues: none.

## 最终复核补充

- 写入后对上述两份 Markdown 执行同一 checker：`OK: 2 file(s) passed UTF-8 guard`。
- 写入 Checklist 后重新执行全量测试：`1113 passed, 3 skipped in 145.39s (0:02:25)`。
- 写入后重新执行 `compileall`、`pip check` 与 `git diff --check`：均退出码 `0`；`pip check` 输出 `No broken requirements found.`，`git diff --check` 仅有 LF/CRLF 转换提示，无 whitespace error。

## W02 验收返工记录（本轮定点返工）

本节为 W02 验收不通过后的追加返工记录，保留本文件此前全部内容。本轮只修复 Context Compiler、Session Store 及其直接测试、导出和最小清理；未修改任务书、Spec、Tasks、Prompt、Checklist 的文字、结构、编号或顺序，也未创建第二个 W02 Feedback，未执行 Git commit、push、merge、rebase、tag、release 或 archive。

### 1. 中段未闭合 semantic unit 的根因与最终判定

- 根因是恢复逻辑把遇到的第一个未闭合 semantic unit 直接视为可恢复尾部，并将其后所有记录一并丢弃，没有继续确认未闭合边界之后是否存在完整语义记录或 Projection。
- 现在恢复会扫描完整 History 的 semantic unit 边界。只有“完整 semantic units + 最后一个未闭合 unit”，且其后没有任何完整 User、Assistant、Tool、Projection 等语义记录时，才判定为真正尾部；该尾部可诊断忽略，并由 writer 在合法边界修复文件尾部。
- 未闭合 unit 后存在完整语义记录、Projection，或未闭合 unit 本身结构不合法时，判定为 middle corruption，`read_session`/`open_writer` fail closed，保留原文件字节，不返回静默丢失后的 History，也不执行自动 truncate。
- append 在写入前先校验已有 pending semantic unit 和本次候选 History：已有未闭合 ToolCall 后只允许能够匹配并闭合该 group 的 ToolResult；无关 User/Assistant/新 Turn/新 ToolCall、不匹配、重复或额外 ToolResult 均受控拒绝，拒绝路径不写入任何字节。合法的跨一次 append 的 ToolCall → ToolResult 仍可完成同一 semantic unit。
- Projection 不能引用未闭合 semantic boundary；未闭合 ToolCall 后出现 Projection 会被拒绝或在恢复时 fail closed，绝不作为可静默删除的尾部。

### 2. ContextSnapshot 的选择优先级与最终顺序

- 明确分离 `selection priority` 与 `composition order`。预算选择仍优先保护 Protected Context、current user、未闭合 semantic unit、必要协议、Projection，再按新到旧选择 recent complete units，最后选择 runtime/environment delta。
- 最终 Snapshot 不按上述预算选择顺序直接输出。Instruction Plane 先按 Public Prompt、Core Contract、User AGENTS、Project AGENTS、activated Directory AGENTS 组成；Conversation / Contextual Plane 再按 Projection、保留的完整 History、按合法 semantic 时间位置保留的 history unit（包括未闭合 unit）、runtime facts/delta、environment facts/delta、current user turn 输出。
- retained raw History 保持确定性的时间顺序；ToolCall/ToolResult 保持在同一 SemanticUnit 内；current user 即使因保护规则导致超预算也保留，并位于最终 Conversation Plane 尾部。`selected_blocks`、plane projections、diagnostics 及后续 snapshot 消费均共享这一确定性 composition contract；本轮未提前实现 Task 7 Provider mapper。

### 3. Bundle 与独立 compiler inputs 的互斥 contract

- `ContextCompiler.compile()` 使用 sentinel 区分“未传入”和“显式传入空值”。当 `sources` 为 `ContextSourceBundle` 时，只要显式提供任意独立 input——包括 `protected_context`、`protocol_blocks`、`current_turn`、`current_turn_deltas`、`runtime_sources`、`environment_sources`、`tool_source`、`history` 或 `projection`——立即抛出 `TypeError`。
- 因此 bundle 不会再静默丢失 Protected Context 或 current user，也不会隐式合并部分字段；只传 bundle 和只传独立 inputs 均保持可用。

### 4. 多活动 Session 的 Instruction State 边界

- 采用当前阶段最小边界：一个 `ApplicationSessionService` 同一时刻只允许一个活动 Session。已有活动 Session 时，`create_session`/`resume_session` 明确抛出 `SessionActiveError`，不重置或改写活动 Session 的 scopes、epoch、fingerprint 或 metadata。
- `close()` 只关闭并同步当前活动 Session，异常和 resume 失败路径都会释放 writer lock；关闭后才能 create/resume 下一 Session。没有引入 per-session Loader registry、Multi-Agent 或复杂多 Session Runtime，也没有保留共享可变 Loader 的串写行为。

### 5. 无依据兼容别名清理

通过真实调用方核对，删除了 W02 新增的独立兼容别名 `ContextSources`、`SessionStore`、`SessionService` 及其导出；删除 `CONTEXT_OPERATING_BUDGET_TOKENS`，统一保留工作包最终正式名称 `UTHCODE_CONTEXT_BUDGET_TOKENS`。未重命名无关既有公共 API，未为未来 Worker 保留包装入口、重复导出或双轨 API。

### 6. 新增或修改的测试

- `tests/test_session_files.py`：中段未闭合 unit + 后续 User fail closed 且字节不变；真正尾部恢复与诊断；未闭合 ToolCall 后追加无关消息提前拒绝；跨 append 的匹配 ToolResult 成功；不匹配 ToolResult 拒绝且字节不变；未闭合 ToolCall 后 Projection fail closed；既有合法跨 append ToolCall → ToolResult 回归保留。
- `tests/test_context_compiler.py`：selection priority 与 composition order 分离；Projection/history/runtime/environment/current user 最终顺序；current user 受保护且位于尾部；recent units 新到旧选择但按时间顺序输出；未闭合 ToolCall 不拆且 current user 为最终当前轮；bundle 与各类独立 input 互斥；single-active Session、resume 失败释放 lock、Application close 释放活动 lock。

### 7. 精确验证结果

- `conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_context_compiler.py`：`18 passed in 5.29s`。
- `conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_session_files.py`：`11 passed in 4.01s`。
- `conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_architecture_boundaries.py`：`23 passed in 6.28s`。
- `conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_history_contract.py tests/test_project_instructions.py tests/test_application_runtime.py tests/test_application_runs.py tests/test_application_tools.py tests/test_provider_contract.py`：`126 passed in 13.23s`。
- 定向合并回归 `conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_context_compiler.py tests/test_session_files.py`：`29 passed in 9.26s`。
- 全量命令（`NO_COLOR` 清除、`TERM=xterm-truecolor`）：`conda run --no-capture-output -n re-uthcode python -m pytest -q`，`1131 passed, 3 skipped in 155.76s (0:02:35)`。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests eval`：退出码 `0`。
- `conda run --no-capture-output -n re-uthcode python -m pip check`：退出码 `0`，`No broken requirements found.`。
- `git diff --check`：退出码 `0`，无 whitespace error；仅报告既有 LF/CRLF 转换提示。
- W02 Feedback 写入后 UTF-8 guard：`OK: 1 file(s) passed UTF-8 guard`。未发现 replacement character、常见乱码或不平衡 Markdown fence。

### 8. 本轮实际修改、风险与遗留

本轮直接修改文件为：`src/uthcode/integrations/session_files.py`、`src/uthcode/core/context.py`、`src/uthcode/application/sessions.py`、`src/uthcode/application/__init__.py`、`src/uthcode/core/__init__.py`、`tests/test_session_files.py`、`tests/test_context_compiler.py` 及本 Feedback 文件。工作树中原有 W02 改动均予以保留，无关变更未覆盖。

主要风险是恢复器现在会对中段损坏严格拒绝（这是本轮要求的 fail-closed 行为），以及 single-active Session 暂不允许同一服务并行持有两个活动 Session；两者均已由定向失败路径测试覆盖。遗留项仍包括 Task 6～Task 12、T09-1 Model Limits、Provider request mapper、Compaction、Slash/TUI、Eval、完整 Integration/E2E/cleanup，以及复杂多 Session Runtime；本轮明确未实施这些内容，也未修改冻结工作包正文或 Checklist。

## W02 第二轮定点返工记录（Context composition）

本轮只修复 W02 复查发现的 current user 组合顺序问题，追加到原 Feedback 末尾；未修改任务书、Spec、Tasks、Prompt 或 Checklist，未创建第二份 Feedback，未执行任何 Git 写入。

### 1. 根因与统一顺序

根因是 Core 的独立参数入口和 Application 的 Context 组装入口都把 `current_user` 前置为 `(current_user, *current_turn)`。因此同时提供 `current_user="current-user"` 与 `current_turn=("other-current-turn",)` 时，Snapshot 尾部错误地变成 current user、other current turn。

两处现统一为：先保留 `current_turn` 的全部 block 及其相对顺序，再在 `current_user is not None` 时追加 current user，即 `(*current_turn, current_user)`。因此最终 Conversation Plane 保持 `Projection → retained history → runtime facts/delta → environment facts/delta → current turn blocks → current user`；没有通过 Provider mapper 事后重排，也没有改变 Instruction Plane、Projection、History、Working Set 或 Session Store 语义。

### 2. 保护与空值行为

current user 仍作为 required/protected block 参与编译。即使其估算 token 使 Snapshot `over_budget=True`，也不会省略，并且始终位于最终 selected blocks 尾部。`current_user=None` 不创建 block、不产生字符串 `"None"`；未提供或为空的 `current_turn` 保持原有行为；多个 current-turn block 保留原相对顺序。

### 3. 新增测试

- `tests/test_context_compiler.py` 新增 Core 顺序与 `None` 行为测试。
- 新增 `ApplicationContextService` 入口测试，验证 `a → b → user` 且 user 为 selected blocks 最后一个 block。
- 新增 `UthCodeApplication.compile_context()` 入口测试，验证 runtime → environment → current-turn blocks → current user。
- 扩展超预算测试，验证 current user 与已有 current-turn block 均保留，`over_budget=True` 且 user 位于尾部。
- 原有 Projection/History/Runtime/Environment 顺序、recent history selection、semantic unit atomicity、Bundle/individual mutual exclusion、single-active Session 与 middle corruption fail closed 测试保持通过。

### 4. 精确验证结果

- `conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_context_compiler.py`：`21 passed in 6.65s`。
- `conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_session_files.py tests/test_architecture_boundaries.py`：`34 passed in 6.78s`。
- `conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_history_contract.py tests/test_project_instructions.py tests/test_application_runtime.py tests/test_application_runs.py tests/test_provider_contract.py`：`103 passed in 7.98s`。
- 全量命令（`NO_COLOR` 清除、`TERM=xterm-truecolor`）：`conda run --no-capture-output -n re-uthcode python -m pytest -q`，`1134 passed, 3 skipped in 87.58s (0:01:27)`。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests eval`：退出码 `0`。
- `conda run --no-capture-output -n re-uthcode python -m pip check`：退出码 `0`，`No broken requirements found.`。
- `git diff --check`：退出码 `0`，无 whitespace error；仅有既有 LF/CRLF 转换提示。
- Feedback 写入后 UTF-8 guard：`OK: 1 file(s) passed UTF-8 guard`；未发现 replacement character、常见乱码或不平衡 Markdown fence。

### 5. 本轮实际修改与未实施范围

本轮直接修改文件为：`src/uthcode/core/context.py`、`src/uthcode/application/context.py`、`tests/test_context_compiler.py` 及本 Feedback 文件。`git status --short` 未出现本轮范围外的新路径；既有 W02 工作树改动均保留。

本轮未实施 Task 6～Task 12、Provider mapper、GenerationRequest 两平面正式接线、Compaction、Tool Result externalization、Slash/TUI、Eval、T09-1 Model Limits 或多 Session 并行 Runtime；未恢复兼容别名，未修改冻结任务包正文或 Checklist。
