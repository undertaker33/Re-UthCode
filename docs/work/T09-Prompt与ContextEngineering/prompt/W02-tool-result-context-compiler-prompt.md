# W02 Tool Result / Context Compiler Worker Prompt

## 执行范围

在 W01 完成后，严格串行执行 Task 4 → Task 5。不执行 Compactor、跨 Turn lifecycle、Slash/TUI、Eval 或最终文档收口。

## 必须读取

1. `AGENTS.md`、`docs/rules/WorkPackageRules.md`，本工作包原始需求、Spec、Tasks、Checklist 和 W01 Feedback。
2. `docs/context/A01-AgentRuntime/AgentRuntime-Context.md`、`docs/context/A02-Control/Control-Context.md`、`docs/context/A03-State/State-Context.md`。
3. Task 4～5 列出的当前源码/测试，T04/T05 归档中 ToolCall 闭合、FIFO、截断和 Agent Loop 边界。

## 已确认决策

- 大 Tool Result 必须先完整原子持久，再产生 bounded preview + opaque ref；写入失败不得伪造 ref 或将全文回灌 Context。
- ToolResultRead 只是当前 Session ref resolver，不是任意文件读取；PLAN 可见且 READ_ONLY。
- Context 总窗口固定 258K，不进入 ModelProfile、Provider 或 TOML；不新增 tokenizer 依赖。
- 仅有五类固定 Source，ToolDefinition 仅用于预算；不建 Context Source Registry 或万能 ContextItem。

## 实施与禁止边界

- 保持 ToolCall ID、FIFO、Permission、is_error、取消和未知 Tool 语义；Agent Loop 仍为 RunState 唯一写入者。
- Core 不依赖 storage path；Provider DTO 不携带真实磁盘路径；Interface 不解析 ref。
- 不建 Artifact Store/GC、二进制媒体仓库、Provider-specific Context policy 或 dynamic Tool registry。
- 冻结文件规则与 Checklist 勾选规则同 W01。

## 测试与验收

执行 Checklist Task 4～5 全部项、对应 builtin Tool 回归与 `tests/test_architecture_boundaries.py`。对外置文件核对原文 hash，对 diagnostics 执行 secret/content 负面断言。

## Feedback

创建 `feedback/W02-tool-result-context-compiler-feedback.md`，按 WorkPackageRules 记录实际机制、边界、命令与精确结果。返工仅追加原文件；安全能力必须扩大到任意路径/其他 Session 时停止并记录。
