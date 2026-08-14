# W02 Model Limits / Context Compiler / Session Store Worker Prompt

## 任务范围

只执行：

- Task 4：Model Limits、Context Compiler 与确定性 Working Set
- Task 5：Session Store、durable append 与 single writer

开始前读取 W01 Feedback 并核验代码，不把未勾选 Task 当已完成。

## 必须读取

- `AGENTS.md`、项目路由/规则、本工作包四个主文件与 W01 Feedback。
- `application/configuration.py`、config loader/template/security tests、Provider config/factory/integrations、`core/provider.py` Usage、bootstrap/run/generation 与架构测试。

## 必须交付

1. provider-independent `ResolvedModelLimits`；来源为可靠 Provider metadata、精确 bundled metadata、用户级显式 ModelProfile。
2. OpenAI 标准 Models API 不当作窗口来源；compatible/local 未知模型要求显式输入限制，否则首请求前失败。禁止名称子串猜测。
3. 258K 仅为 policy cap；`effective_input_limit=min(258K,resolved max_input_tokens)`。
4. Compiler/Snapshot、Protected Context、Projection、recent complete semantic units、ref 跟随 unit；不得实现“相关性”算法。
5. stable-prefix token/fingerprint/changed/reason diagnostics；runtime-only delta 不改 stable fingerprint。
6. Session versioned layout、durable append、strict sequence、last complete boundary recovery。
7. `runtime.jsonl` 保持非语义权威；删除不影响恢复，stream/UI lifecycle 不写入 History。
8. 进程持有的跨平台 OS 排他锁；resume 先锁后读，并发第二 writer fail closed。
9. 写入 W02 Feedback 并同步 Tasks/Checklist。

## 禁止

- 不新增统一 `provider.get_context_window()` 强制接口。
- 不把 258K 当模型事实或 fallback，不靠 overflow discovery。
- 当前仓库没有 Gemini Provider，不在本 Worker 新增。
- 不实现 Tool Result 外置、Compaction、Slash/TUI、Eval、Memory 或 Git 写入。

## 验证

覆盖 small-window、large-window、unknown compatible、project limit 不能提高可信上限、runtime-only prefix stability、deterministic working set、并发子进程 resume、双 sequence 防护、尾记录恢复、中段损坏与跨进程 Runtime State 非 checkpoint 边界。

## Feedback

首次创建 `feedback/W02-tool-result-context-compiler-feedback.md`，记录限制来源矩阵、文件职责、精确测试结果、Checklist 状态、数值/失败边界和未完成项。需要猜测模型限制或改变配置安全语义时停止相关范围并报告。
