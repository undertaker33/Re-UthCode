# W02 Context Compiler / Session Store Worker Prompt

## 任务范围

严格顺序执行：

- Task 4：Context Compiler、258K Budget 与确定性 Working Set
- Task 5：Session Store、durable append 与 single writer

开始前读取 W01 Feedback 并核验代码，不把未勾选 Task 当已完成。

## 必须读取

- `AGENTS.md`、项目路由/规则、本工作包四个主文件与 W01 Feedback。
- Prompt/Provider request contract、History/Projection、bootstrap/run/generation、Session composition、现有 Usage 与架构测试。

## 已确认决策

1. T09 固定使用 258,000-token Context Operating Budget；它不是远端模型物理窗口声明。
2. Working Set 只使用 Protected Context、active Projection、recent complete semantic units 与 current-turn deltas。
3. stable-prefix diagnostics 保留；阈值和不同模型档位优化后置 T09-1。
4. Session single writer、strict sequence、durable append 和 Runtime State 非 checkpoint 边界保持不变。

## 必须交付

1. Provider-independent Compiler/Snapshot、固定 258K Budget 和 deterministic token estimate。
2. Protected Context、Projection、recent complete semantic units、ref 跟随 unit；不得实现“相关性”算法。
3. stable-prefix token/fingerprint/changed/reason diagnostics；runtime-only delta 不改 stable fingerprint。
4. Session versioned layout、durable append、strict sequence、last complete boundary recovery。
5. `runtime.jsonl` 保持非语义权威；删除不影响恢复，stream/UI lifecycle 不写入 History。
6. 进程持有的跨平台 OS 排他锁；resume 先锁后读，并发第二 writer fail closed。
7. 写入 W02 Feedback 并同步 Tasks/Checklist。

## 禁止

- 不实现 `ResolvedModelLimits`、Provider/bundled metadata、`ModelProfile.max_input_tokens`、compatible/local window config 或小/大窗口适配。
- 不计算 `min(model_window, 258K)`，不按物理窗口改变 TUI denominator，不靠 overflow discovery。
- 不冻结最佳 compact threshold、headroom、Working Set 比例或 recent-tail 大小。
- 不实现 Tool Result 外置、Compaction、Slash/TUI、Eval、Memory 或 Git 写入。

## 验证

覆盖 fixed 258K、runtime-only prefix stability、deterministic working set、无 T09-1 实现残留、并发子进程 resume、双 sequence 防护、尾记录恢复、中段损坏与跨进程 Runtime State 非 checkpoint 边界。

## Feedback

首次创建 `feedback/W02-tool-result-context-compiler-feedback.md`，记录固定预算语义、文件职责、精确测试结果、Checklist 状态和未完成项。发现必须依赖真实模型窗口才能完成的优化时记录为 T09-1，不在本 Worker 扩大实现。
