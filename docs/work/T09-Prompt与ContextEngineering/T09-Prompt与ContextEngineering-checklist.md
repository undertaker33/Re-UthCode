# T09 Prompt 与 Context Engineering Checklist

> 名称和顺序与 Tasks 完全一致；仅在有代码、测试和 Worker Feedback 证据后勾选。

## Task 1：Prompt Asset、Context Source 与权限平面

- [ ] 执行 Prompt/Context contract 定向测试，asset 在 source/wheel 可读，公共 Prompt 不能删除 Core Contract，Tool schema 无副本。
- [ ] 验证 Tool Schema 仅由 Tool System 维护并进入 `GenerationRequest.tools`/Provider native tools；虽计入 token budget、`tool_schema_fingerprint` 与 cache diagnostics，但 Public Prompt/Core Contract/AGENTS 中没有人工副本。
- [ ] 构造 User/Tool instruction-like 历史与 summary，观察 Provider 前语义 authority 仍为 history。
- [ ] 普通 User/Tool 历史伪造 AGENTS/ProjectInstruction/Runtime 标签，观察其仍只在 Conversation Plane，不能进入 Instruction Plane。
- [ ] 构造长历史只更新 TaskState/PlanState，观察 instruction epoch 与 stable instruction prefix fingerprint 不变，动态 facts 位于 Contextual Plane。

## Task 2：AGENTS / Project Instructions Loader

- [ ] 执行 `python -m pytest -q tests/test_project_instructions.py tests/test_architecture_boundaries.py`，全部通过。
- [ ] 覆盖 user/root/directory scope、整行单双引号 `@include`、递归、3 个额外文件、第 4 个失败、物理去重、Windows case-fold、直接/间接循环、越界、代码围栏/行内代码忽略。
- [ ] 从 Read/Edit 路径首次进入子目录并发现新 AGENTS，观察 instruction epoch +1、stable prefix fingerprint 改变、reason 为 scope change，下一次 request 使用新 Instruction Plane；这不是 prefix regression。
- [ ] 继续访问同一已生效目录且内容未变，观察 instruction epoch/fingerprint 不变；已生效 AGENTS 合法修改时创建新 epoch 并记录 content change；Core/Interface 不直接读文件。
- [ ] 给定 persisted activated directory scopes，Loader 可从当前文件系统重建 effective instruction set；删除/修改 scope 文件产生明确 change facts，且不扫描 History/Read/Edit ToolCall 推断 scope。

## Task 3：Canonical History 与 Projection 基础

- [ ] 执行 `python -m pytest -q tests/test_history_contract.py`，覆盖 schema/kind/sequence/round-trip/unknown 值，全部通过。
- [ ] 在 ToolCall/ToolResult 中间选择或 compact，观察受控拒绝且既有 records 字节不变。
- [ ] 验证 Projection revision/previous link 不回写 History，Runtime Log/stream/UI facts 不进入语义历史。

## Task 4：Context Compiler、258K Budget 与确定性 Working Set

- [ ] 执行 `python -m pytest -q tests/test_context_compiler.py` 及相关 request composition tests，全部通过。
- [ ] 验证 Compiler、`/status` 与 ring 使用同一固定 258K Operating Budget，并明确不代表远端模型物理窗口。
- [ ] 搜索 T09 实现确认没有 Model Limits resolver、`max_input_tokens` 配置、Provider/bundled window metadata 或小/大窗口适配。
- [ ] 文档/contract tests 明确 T09 不保证真实窗口小于 258K 的模型在长上下文下安全，overflow 最多一次保护且不作 discovery 或动态 budget 解析。
- [ ] 超预算时保留 Protected Context/未闭合 unit/current user，recent complete units 从新到旧选择，result ref 只跟随保留 unit；无关键词/embedding relevance。

## Task 5：Session Store、durable append 与 single writer

- [ ] 执行 `python -m pytest -q tests/test_session_files.py`，覆盖 monotonic sequence、durable append、尾部半写、中段损坏、unknown kind，全部通过。
- [ ] 启动两个子进程 resume 同一 Session，观察只有一个取得 writer lock，另一方 session busy，无双 sequence/history corruption。
- [ ] 删除 runtime log 后恢复结果不变；同 project key 可发现，其他项目不可见；last_used 不依赖 mtime。
- [ ] 跨进程恢复新 Run/Turn 且 TaskState/PlanState 未被假装 checkpoint；同进程 continuation 仍按 T08 回归通过。
- [ ] 激活 directory AGENTS → 关闭进程 → `/resume`：metadata 提供 activated scopes/epoch/fingerprint，当前文件系统内容未变化时 effective instruction set、epoch 与 fingerprint 保持；metadata 不含 AGENTS 正文。
- [ ] 激活 directory AGENTS → 关闭进程 → 修改或删除 AGENTS → `/resume`：以当前文件系统为权威创建新 epoch、改变 fingerprint、记录明确 reason；删除后仍保留 activated directory scope 标识，使后续重新出现可被发现；无 `instruction-history.jsonl` 或独立 Instruction Event Store。

## Task 6：大 Tool Result 外置与资源上限

- [ ] 执行 tool/provider/result persistence 定向测试，阈值下 inline、阈值上完整文件 hash 等于原文且 working view bounded。
- [ ] 单 Result hard cap、Session quota、写入失败均返回受控结果，无 partial file/dangling ref；Feedback 记录数值选择证据。
- [ ] Tool 已成功产生副作用但 persistence 失败时，模型/History/diagnostics 均不显示为 Tool 未执行，且不自动重试该 Tool。
- [ ] 有效 range 可读；伪造 ref、路径文本、跨 Session ref、过大 range 全部 fail closed。
- [ ] ToolCall ID、FIFO、Permission、`is_error`、取消和普通错误回归不变。

## Task 7：有界 Compaction 与 Runtime Request Composition

- [ ] 执行 `python -m pytest -q tests/test_context_compaction.py tests/test_agent_loop.py tests/test_application_runs.py`，全部通过。
- [ ] 待压缩历史超过 Compactor input budget 时按完整 semantic unit 有界滚动分批，每批输入/输出受限且 ToolCall/ToolResult 不拆。
- [ ] manual/auto/一次 overflow 保护、single-flight、取消/非法 summary/ToolCall/二次 overflow 失败路径均不改变旧 Projection/History。
- [ ] 记录三类 Provider contract request，观察 Instruction Plane、Conversation Plane 与 `GenerationRequest.tools` 分字段构造，Integration 只做原生协议映射；Tool Schema 不复制进 Prompt，Projection 保持 history authority，ordinary history 无法进入 Instruction Plane。
- [ ] 仅 Projection/Compaction revision 变化时，观察 instruction epoch、Instruction Plane 与 stable prefix fingerprint 均不变。

## Task 8：Session Slash Commands 与 TUI Context Status

- [ ] 执行 command/TUI 定向测试，`/compact`、`/new`、`/resume` 不再 NOT_IMPLEMENTED；active compact unavailable，`/clear` 不换 Session。
- [ ] 以至少 21 个同项目 Session 验证 durable last-used 倒序、每页 10 条、首 User 单行 preview/省略、上下选择、左右翻页、Enter、Esc 无副作用；其他 project key 不出现。
- [ ] 并发 busy、损坏、未知 Session 有明确错误；resume 恢复同 session id/history/projection/ref、重建 effective Instruction State 并开始新 Turn。
- [ ] `/status` 线性条和输入区 ring 使用同一 Application usage，统一显示 used/258K Operating Budget；unavailable/窄终端/Headless 通过，无动态模型 denominator。

## Task 9：Context Diagnostics 与 Eval

- [ ] 执行 `python -m pytest -q tests/eval/test_eval_reporting.py tests/eval/test_eval_execution.py` 及新增 diagnostics tests，全部通过。
- [ ] baseline/candidate 报告包含 success/tokens/tool calls/compact/rediscovery/repeated exploration/externalization/stable prefix/cache reuse（可获得时）。
- [ ] Provider 不支持 cache metrics 时报告 `not_available`，不把 Usage 默认 0 冒充实测；diagnostics 不额外复制 Runtime credential、完整外置结果、Provider native payload 或未脱敏内部异常。
- [ ] fixtures 覆盖 Runtime/Projection 变化保持 epoch/fingerprint、目录 AGENTS 新 scope 改变 epoch/fingerprint、已生效未变化 AGENTS 稳定复用，以及 resume 后未变化保持/离线变化产生明确 reason；候选策略不要求在 pytest 中概率性胜出。

## Task 10：[接入主流程] 正式 Context Composition 收口

- [ ] 从正式 `create_application` Headless 入口执行多 Turn → 大结果 → ToolResultRead → compact → 重建 resume → final，全部通过。
- [ ] 执行 `python -m pytest -q tests/test_architecture_boundaries.py`，Core 不依赖 filesystem/SDK/Interface，Interface 不直连 Integration Session Store。
- [ ] 执行静态扫描，正式 Agent path 无全量 `RunState.messages` 直通、永久 10K 截断和三个命令占位。

## Task 11：[端到端验证] Context / Session / Prefix

- [ ] 从真实入口覆盖 runtime/projection prefix stability、AGENTS epoch/stable reuse、Instruction State resume 未变化/离线变化、Tool Schema 单一来源、authority spoof rejection、fixed 258K及小窗口阶段边界、compactor overflow、concurrent resume、runtime boundary、quota/ref、execution/persistence outcome、Picker。
- [ ] 执行 `python -m pytest -q`，记录精确 passed/failed/skipped 和耗时。
- [ ] 执行 `python -m compileall -q src tests eval` 与 `python -m pip check`，均退出 0。

## Task 12：[遗留负担清理] 单历史 / 单 Context Path 收口

- [ ] 扫描 `src tests docs eval`，不存在重复 Loader/Context path、mutable history rewrite、任意路径 result read、第二 Loop/Scheduler、SQLite checkpoint、动态 Context Source Registry、relevance/embedding 或兼容壳。
- [ ] 按 `docs/README.md` 维护映射同步 UserManual、Tools、A01/A03/A04/TUI、Context-Index、OutstandingDebtList，与最终 `src/ + tests/` 一致。
- [ ] 对改动 Markdown 执行 strict UTF-8、replacement character、常见 mojibake、fence balance 与链接检查，全部通过。
- [ ] 执行 `git diff --check` 和 `git status --short`，无 whitespace error，范围仅含 T09，且未归档或执行 Git 写入。
