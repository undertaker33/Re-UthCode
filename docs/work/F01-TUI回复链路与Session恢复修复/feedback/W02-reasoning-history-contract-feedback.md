# W02 Feedback：Reasoning 与 History 合同

## 范围与结论

- 本次严格按依赖顺序实施 F01/T02 -> T03；W01/T01 已完成并作为前置边界使用。
- 未修改 Application Session replay DTO、lazy Session、process tool、Tool 摘要、TUI、当前事实文档或其他 Worker Feedback。
- 未执行任何 Git add、commit、push、checkout、merge 或其他 Git 写操作。
- T02/T03 的 Provider typed reasoning、terminal 判定、Transcript 持久化和 Context 重建合同已落地；TUI 时序显示与 `/resume` hydrate 不在本次完成声明内。

## T02：Provider 流与 terminal 合同

Provider 流真值表如下：

| 输入序列 | 公开事件顺序 | 持久化/终态语义 |
| --- | --- | --- |
| reasoning -> content | `ReasoningDelta -> TextDelta` | 保持为 `ReasoningPart`、`TextPart` 两种 typed part |
| 同 chunk reasoning + content | `ReasoningDelta -> TextDelta` | 先处理 reasoning，再处理正式正文 |
| content -> reasoning -> content | `TextDelta -> ReasoningDelta -> TextDelta` | 三个有序 segment，不把中间 reasoning 并入正文 |
| 连续同 kind delta、多 reasoning segment | 同 kind 合并；kind 转换形成新 segment | 每个 segment 保持自身类型与顺序 |

- 同 Provider/model identity 的 reasoning + ToolCall continuation 保留所需 native carrier；跨 identity 的 reasoning 不作为 native carrier，也不降级进入 assistant content。
- `_message_text`、assistant request 映射只提取 `TextPart`（以及合法 ToolResult 文本），不会把 `ReasoningPart` 当作普通用户/助手文本。
- `STOP` 必须包含非空正式 `TextPart`；reasoning-only 和空 `TextPart` stop 形成受控 invalid response。`ReasoningPart + 非空 TextPart` 是合法 final，`ReasoningPart + ToolCall` 是合法 progress。
- `TurnCompleted`/`TurnResult.final_text` 只从正式 `TextPart` 派生；reasoning 不进入 final 正文或修正消息。

## T03：逻辑 Message 与 typed History

- 新 Transcript 每个 entry 只保存自己的 `part`，并带有 role、确定性的 `message_id`、`message_part_index`；native item 仅随对应 part 保存，不再复制完整 Message，因此消除了 `parts × full message` 存储放大。
- Context compiler 按 message identity 和连续 part index 重建恰好一个逻辑 Message，并保持原 part 顺序；同文本的不同 identity 不去重，同 identity 在 A -> B -> A 后再次出现会拒绝。
- `ReasoningPart` 与 `TextPart` 可分别 round-trip；reasoning 是可回放的 typed history/display record，但永不并入 final TextPart。ToolCall/ToolResult 的 ID、FIFO 和 semantic unit 读取同时兼容新的嵌套 part payload。
- 现有旧 full-message v3 Session reader 保持只读兼容，不原地迁移；回归测试验证读取前后文件 hash/mtime 不变。

## 修改文件

生产代码：

- `src/uthcode/core/agent.py`
- `src/uthcode/core/context.py`
- `src/uthcode/core/history.py`
- `src/uthcode/application/history.py`
- `src/uthcode/integrations/providers/anthropic.py`
- `src/uthcode/integrations/providers/openai_compat.py`
- `src/uthcode/integrations/providers/openai_responses.py`
- `src/uthcode/integrations/session_files.py`

测试：

- `tests/test_agent_loop.py`
- `tests/test_anthropic_integration.py`
- `tests/test_context_compiler.py`
- `tests/test_history_contract.py`
- `tests/test_history_read_tool.py`
- `tests/test_openai_compat_integration.py`
- `tests/test_openai_responses_integration.py`
- `tests/test_session_files.py`
- `tests/test_w06_integration_delivery.py`

后两处测试只将既有断言从旧 full-message/顶层 metadata 形状更新为新 part-local payload 形状；未扩大生产范围。

## 测试与审计证据

- T02 精确套件：`conda run --no-capture-output -n re-uthcode python -m pytest tests/test_provider_contract.py tests/test_agent_events.py tests/test_agent_loop.py tests/test_openai_compat_integration.py tests/test_openai_responses_integration.py tests/test_anthropic_integration.py -q`：`154 passed, 3 skipped`。
- T03 精确套件：`conda run --no-capture-output -n re-uthcode python -m pytest tests/test_history_contract.py tests/test_context_compiler.py tests/test_session_files.py tests/test_w04_session_commands.py -q`：`55 passed`。
- 架构边界：`conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q`：`23 passed`。
- 全量：`conda run --no-capture-output -n re-uthcode python -m pytest -q`：`1258 passed, 3 skipped in 172.42s (0:02:52)`。
- 编译：`conda run --no-capture-output -n re-uthcode python -m compileall -q src tests eval`：退出码 `0`。
- 依赖：`conda run --no-capture-output -n re-uthcode python -m pip check`：`No broken requirements found.`。
- 差异检查：`git diff --check`：退出码 `0`，仅有 Windows 工作副本 LF/CRLF 提示，无 whitespace 错误。

## Checklist 证据

- 仅勾选 F01 Checklist 的 T02 五项和 T03 五项；T04 及之后项目保持未勾选。
- T02 勾选依据为 Provider 流矩阵、same/cross identity、terminal invalid/progress/final 和 `final_text` 定向回归。
- T03 勾选依据为 per-part Transcript、typed reasoning/text round-trip、identity 连续性、Tool semantic unit、旧 v3 只读兼容和存储放大回归。

## 偏差、未完成项与风险

- 未进行真实 Provider 网络调用或 Windows Terminal 人工视觉验证。
- 未实施或验证 T04 之后的 Session replay DTO、lazy 生命周期、TUI renderer、`/resume` hydrate、进程解码、Tool 摘要和端到端主流程；不得从本 Feedback 推断这些能力已完成。
- 没有新增依赖，也没有执行 Git 写操作。

## UTF-8 guard

- files checked: `docs/work/F01-TUI回复链路与Session恢复修复/feedback/W02-reasoning-history-contract-feedback.md`、`docs/work/F01-TUI回复链路与Session恢复修复/F01-TUI回复链路与Session恢复修复-checklist.md`
- result: `conda run --no-capture-output -n re-uthcode python C:\\Users\\93445\\.codex\\skills\\uth-utf8-guard\\scripts\\check_utf8_docs.py docs/work/F01-TUI回复链路与Session恢复修复/feedback/W02-reasoning-history-contract-feedback.md docs/work/F01-TUI回复链路与Session恢复修复/F01-TUI回复链路与Session恢复修复-checklist.md`：`OK: 2 file(s) passed UTF-8 guard`。
- repaired encoding issues: none
