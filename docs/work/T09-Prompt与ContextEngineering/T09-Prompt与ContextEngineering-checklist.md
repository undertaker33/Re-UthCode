# T09 Prompt 与 Context Engineering Checklist

> 名称和顺序与 Tasks 完全一致；仅在有代码、测试和 Worker Feedback 证据后勾选。

## Task 1：Prompt Asset、Context Source 与权限平面

- [ ] 执行 Prompt/Context contract 定向测试，asset 在 source/wheel 可读，公共 Prompt 不能删除 Core Contract，Tool schema 无副本。
- [ ] 构造 User/Tool instruction-like 历史与 summary，观察 Provider 前语义 authority 仍为 history。
- [ ] 构造长历史只更新 TaskState，观察 stable-prefix fingerprint 不变，动态 delta 位于历史尾部附近。

## Task 2：AGENTS / Project Instructions Loader

- [ ] 执行 `python -m pytest -q tests/test_project_instructions.py tests/test_architecture_boundaries.py`，全部通过。
- [ ] 覆盖 user/root/directory scope、整行单双引号 `@include`、递归、3 个额外文件、第 4 个失败、物理去重、Windows case-fold、直接/间接循环、越界、代码围栏/行内代码忽略。
- [ ] 从 Read/Edit 路径首次进入子目录，观察只追加新命中 instruction delta；Core/Interface 不直接读文件。

## Task 3：Canonical History 与 Projection 基础

- [ ] 执行 `python -m pytest -q tests/test_history_contract.py`，覆盖 schema/kind/sequence/round-trip/unknown 值，全部通过。
- [ ] 在 ToolCall/ToolResult 中间选择或 compact，观察受控拒绝且既有 records 字节不变。
- [ ] 验证 Projection revision/previous link 不回写 History，Runtime Log/stream/UI facts 不进入语义历史。

## Task 4：Model Limits、Context Compiler 与确定性 Working Set

- [ ] 执行 `python -m pytest -q tests/test_model_limits.py tests/test_context_compiler.py tests/test_configuration.py tests/test_config_loader_integration.py`，全部通过。
- [ ] 验证 128K 模型使用不超过 128K、>258K 模型最多 258K，均在首个 Provider 请求前解析。
- [ ] 未知 compatible model 无可靠 metadata/用户声明时前置失败；搜索实现确认无 model-name substring 窗口猜测和 overflow discovery。
- [ ] 超预算时保留 Protected Context/未闭合 unit/current user，recent complete units 从新到旧选择，result ref 只跟随保留 unit；无关键词/embedding relevance。

## Task 5：Session Store、durable append 与 single writer

- [ ] 执行 `python -m pytest -q tests/test_session_files.py`，覆盖 monotonic sequence、durable append、尾部半写、中段损坏、unknown kind，全部通过。
- [ ] 启动两个子进程 resume 同一 Session，观察只有一个取得 writer lock，另一方 session busy，无双 sequence/history corruption。
- [ ] 删除 runtime log 后恢复结果不变；同 project key 可发现，其他项目不可见；last_used 不依赖 mtime。
- [ ] 跨进程恢复新 Run/Turn 且 TaskState/PlanState 未被假装 checkpoint；同进程 continuation 仍按 T08 回归通过。

## Task 6：大 Tool Result 外置与资源上限

- [ ] 执行 tool/provider/result persistence 定向测试，阈值下 inline、阈值上完整文件 hash 等于原文且 working view bounded。
- [ ] 单 Result hard cap、Session quota、写入失败均返回受控结果，无 partial file/dangling ref；Feedback 记录数值选择证据。
- [ ] 有效 range 可读；伪造 ref、路径文本、跨 Session ref、过大 range 全部 fail closed。
- [ ] ToolCall ID、FIFO、Permission、`is_error`、取消和普通错误回归不变。

## Task 7：有界 Compaction 与 Runtime Request Composition

- [ ] 执行 `python -m pytest -q tests/test_context_compaction.py tests/test_agent_loop.py tests/test_application_runs.py`，全部通过。
- [ ] 待压缩历史超过 Compactor input budget 时按完整 semantic unit 有界滚动分批，每批输入/输出受限且 ToolCall/ToolResult 不拆。
- [ ] manual/auto/一次 overflow 保护、single-flight、取消/非法 summary/ToolCall/二次 overflow 失败路径均不改变旧 Projection/History。
- [ ] 记录 Fake Provider request，观察正式路径消费 ContextSnapshot，Projection 是 history authority，Core 无 Provider 名称分支。

## Task 8：Session Slash Commands 与 TUI Context Status

- [ ] 执行 command/TUI 定向测试，`/compact`、`/new`、`/resume` 不再 NOT_IMPLEMENTED；active compact unavailable，`/clear` 不换 Session。
- [ ] 以至少 21 个同项目 Session 验证 durable last-used 倒序、每页 10 条、首 User 单行 preview/省略、上下选择、左右翻页、Enter、Esc 无副作用；其他 project key 不出现。
- [ ] 并发 busy、损坏、未知 Session 有明确错误；resume 恢复同 session id/history/projection/ref 并开始新 Turn。
- [ ] `/status` 线性条和输入区 ring 使用同一 Application usage；128K/1M 分母分别为 effective limit，另显示 258K policy cap；unavailable/窄终端/Headless 通过。

## Task 9：Context Diagnostics 与 Eval

- [ ] 执行 `python -m pytest -q tests/eval/test_eval_reporting.py tests/eval/test_eval_execution.py` 及新增 diagnostics tests，全部通过。
- [ ] baseline/candidate 报告包含 success/tokens/tool calls/compact/rediscovery/repeated exploration/externalization/stable prefix/cache reuse（可获得时）。
- [ ] Provider 不支持 cache metrics 时报告 `not_available`，不把 Usage 默认 0 冒充实测；安全投影不含秘密或完整外置结果。
- [ ] 长历史不变仅 Runtime State 更新的 fixture 能检测 prefix 回归；候选策略不要求在 pytest 中概率性胜出。

## Task 10：[接入主流程] 正式 Context Composition 收口

- [ ] 从正式 `create_application` Headless 入口执行多 Turn → 大结果 → ToolResultRead → compact → 重建 resume → final，全部通过。
- [ ] 执行 `python -m pytest -q tests/test_architecture_boundaries.py`，Core 不依赖 filesystem/SDK/Interface，Interface 不直连 Integration Session Store。
- [ ] 执行静态扫描，正式 Agent path 无全量 `RunState.messages` 直通、永久 10K 截断和三个命令占位。

## Task 11：[端到端验证] Context / Session / Prefix

- [ ] 从真实入口覆盖 prefix stability、authority、small/large/unknown model、AGENTS、compactor overflow、concurrent resume、runtime boundary、quota/ref、Picker。
- [ ] 执行 `python -m pytest -q`，记录精确 passed/failed/skipped 和耗时。
- [ ] 执行 `python -m compileall -q src tests eval` 与 `python -m pip check`，均退出 0。

## Task 12：[遗留负担清理] 单历史 / 单 Context Path 收口

- [ ] 扫描 `src tests docs eval`，不存在重复 Loader/Context path、mutable history rewrite、任意路径 result read、第二 Loop/Scheduler、SQLite checkpoint、动态 Context Source Registry、relevance/embedding 或兼容壳。
- [ ] 按 `docs/README.md` 维护映射同步 UserManual、Tools、A01/A03/A04/TUI、Context-Index、OutstandingDebtList，与最终 `src/ + tests/` 一致。
- [ ] 对改动 Markdown 执行 strict UTF-8、replacement character、常见 mojibake、fence balance 与链接检查，全部通过。
- [ ] 执行 `git diff --check` 和 `git status --short`，无 whitespace error，范围仅含 T09，且未归档或执行 Git 写入。
