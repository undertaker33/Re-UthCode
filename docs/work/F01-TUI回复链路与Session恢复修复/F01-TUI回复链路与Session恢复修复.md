# F01：TUI 回复链路与 Session 恢复修复

## 原始需求

本文件根据用户在 2026-08-28 的聊天需求原样归纳创建；用户未提供独立需求文件。

用户首次报告：

> TUI 中整个回复的逻辑很乱，至少暴露了以下几个问题，我需要你先进行问题排查和定位：
>
> 1. reasoning 和正式回复的顺序有问题
> 2. agent 无法区分哪些是 system prompt，哪些是 user prompt，甚至它自己的回复它也分不出来
> 3. 思考内容会跑到最终回复中
> 4. `/resume` 没法恢复原 session 聊天记录

用户随后要求：

> 从我给出的几轮会话的内容中，还能看出哪些问题，一并排查出来。

> 探索后新建 F01 任务包，制定修复计划，修复四个现象 + 9 类问题。

## 用户已确认决策

### D-F01-01：Reasoning 保持可见和流式

- Reasoning 继续作为独立记录实时展示，不隐藏、不折叠进正式回复。
- Reasoning 与正式回复必须有严格类型边界和确定顺序。
- Reasoning 左侧竖线使用不同于正式回复的语义颜色；正文颜色可以保持一致。
- 为保证 append-only scrollback 不被重排，reasoning 按安全 Markdown 边界实时提交；正式回复 delta 保持实时临时预览，在权威消息完成后只永久提交一次。

### D-F01-02：`/resume` 完整安全回放

- 回放目标 Session 全部 durable 用户消息、独立 reasoning、正式 assistant 回复和安全 Tool 终态摘要。
- 不回放原始 ToolResult 正文、Provider native payload、秘密、未完成 Turn 或暂停 continuation。
- 回放不调用 Provider、不创建 Turn、不再次持久化。

### D-F01-03：Session 延迟创建

- TUI 启动、退出、帮助、状态和 Session Picker 不创建持久 Session。
- 第一条普通用户输入前才确保 Session；显式 `/new` 创建新 Session；`/resume` 直接恢复目标 Session。
- `uthcode exec` 已有真实 prompt，可以在执行前创建 Session。

### D-F01-04：按原 Tool 摘要脱敏设计修复

原设计证据来自已归档 T05 任务与其 W02-R1～R4 反馈，以及引入该行为的提交 `f32ad439aaf200adc98d177540ffdf6344668254`：

- Tool 活动只展示状态、Tool 名和安全命令/参数摘要，不展示 ToolResult 正文。
- 摘要不得显示 API key、token、环境变量值或配置秘密。
- 配置明确指定的秘密始终脱敏；其余非空 ambient 环境值按 token 边界脱敏，仅 `0`、`1` 作为普通 feature flag 例外。
- 因此本包不放宽 ambient 环境值脱敏；`<redacted>` 在命中该规则时是预期结果。
- 本包修复 Tool 名重复、摘要展示所有权和多 Tool FIFO 投影，不把安全边界误判为普通文案缺陷。

## 探索确认的四个现象

1. Reasoning 与正式回复被不同缓冲区按类型归并，永久输出不再保持 Provider/Event 时间线。
2. Runtime、Environment 与当前用户文本被放进同一条 user message 的多个文本 part，Provider 映射又无分隔拼接；历史 reasoning 还可能跨 identity 降级为 assistant 正文。
3. Reasoning 既可能在 TUI 视觉上黏到正式回复，又可能在跨模型历史映射中真实变成普通正文。
4. `/resume` 已恢复模型所用 Transcript/Timeline/Instruction State，但 TUI 只切换 Session 和 Run，没有 hydrate 聊天显示记录。

## 探索确认的九类问题

1. **当前用户边界丢失**：独立 Context part 与当前输入被直接拼接，短输入会黏到模型、Provider 等上下文尾部。
2. **Prompt 组合双轨**：独立 System Prompt 构造路径与生产 Context Compiler 路径并存，测试与正式入口可能验证不同语义。
3. **Reasoning 产品合同不一致**：Provider、公共事件、TUI、Prompt 约束和持久历史对 reasoning 的角色定义没有统一。
4. **Reasoning 历史污染**：跨 Provider/model identity 时 reasoning 可降级为普通 assistant content；同 identity 也缺少明确的 typed replay 边界。
5. **空正式回复成功**：reasoning-only 的 stop 响应可能被当成成功 Turn，但最终文本为空。
6. **Windows 输出乱码**：进程 stdout/stderr 固定按 UTF-8 replacement 解码，OEM/ANSI 中文输出会损坏。
7. **Tool 活动投影混乱**：Tool 名和摘要重复组合，多 Tool batch 的 FIFO 终态缺少明确 UI 合同；脱敏边界需要按原设计保留。
8. **Transcript 存储放大与回放缺口**：每个 part 重复携带完整 Message，重建依赖去重；Application 没有 display-safe replay projection。
9. **空 Session 累积**：启动时提前创建 Session，直接退出或先 `/resume` 会留下未使用条目。

## 已执行探索验证

- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_openai_compat_integration.py tests/test_context_compiler.py tests/test_w04_session_commands.py tests/test_tui.py -q`：`107 passed, 1 skipped`。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_builtin_process_tool.py tests/test_application_tools.py tests/test_application_runs.py tests/test_tui.py -q`：`274 passed`。

这些通过结果说明当前测试未覆盖真实事件交错、消息来源分隔、TUI hydrate、Windows shell 编码和空 Session 生命周期，不能作为问题不存在的证据。

## 实施授权边界

创建本工作包不授权修改生产代码。只有用户显式指定 `prompt/WXX-...-prompt.md` 后，对应 Worker 才能开始实施。
