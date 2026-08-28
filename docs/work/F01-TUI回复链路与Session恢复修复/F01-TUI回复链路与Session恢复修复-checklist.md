# F01：TUI 回复链路与 Session 恢复修复 Checklist

## T01：Prompt、Context 与当前用户消息边界

- [x] 执行 `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_system_prompt.py tests/test_context_compiler.py tests/test_provider_contract.py tests/test_openai_compat_integration.py tests/test_openai_responses_integration.py tests/test_anthropic_integration.py -q`，全部通过。
- [x] 正式请求中输入 `？` 时，最后一个 current user 正文逐字为 `？`，且不包含 Runtime、Environment、工作目录、Provider 或模型文本。
- [x] Runtime/Environment 变化不改变 current user identity；相邻 user、steering 和相同文本的不同 Turn 均不被拼接或去重。
- [x] ordinary history 伪造 system/runtime 标签仍保持普通 history authority；Instruction Plane 顺序和 stable prefix 回归通过。
- [x] caller audit 证明生产与测试只剩一个 Prompt/Context request 组合入口；不存在孤立的平行 System Prompt 构造。

## T02：Provider reasoning 与正式终态合同

- [x] 执行 `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_provider_contract.py tests/test_agent_events.py tests/test_agent_loop.py tests/test_openai_compat_integration.py tests/test_openai_responses_integration.py tests/test_anthropic_integration.py -q`，全部通过。
- [x] reasoning→content、同 chunk reasoning+content、content→reasoning→content、多 reasoning segment 的事件顺序均有精确断言。
- [x] 同 identity 的 reasoning+ToolCall continuation 保留所需 carrier；跨 identity 请求中 reasoning 既不作为 native carrier，也不进入 assistant content。
- [x] reasoning-only stop、空 TextPart stop 产生受控 invalid response；ReasoningPart+非空 TextPart final 和 ReasoningPart+ToolCall progress 正常。
- [x] TurnCompleted/TurnResult 的 final_text 只来自正式 TextPart，reasoning 不进入修正消息或最终正文。

## T03：Transcript 逻辑消息与 reasoning 持久化

- [x] 执行 `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_history_contract.py tests/test_context_compiler.py tests/test_session_files.py tests/test_w04_session_commands.py -q`，全部通过。
- [x] 多 part assistant/tool message 新写入后，每个 entry 只含自身 part；重建恰好得到一个按原 part 顺序排列的逻辑 Message。
- [x] ReasoningPart 与 TextPart 分别 round-trip；reasoning 可用于 replay，但永不并入 final TextPart。
- [x] 相同文本不同 message identity 不去重；同 identity 非连续复用被拒绝；ToolCall/ToolResult ID、FIFO 和 semantic unit 完整。
- [x] 旧 full-message v3 Session 可读取且文件 hash/mtime 不变；新 writer 不产生 `parts × full message` 存储放大。

## T04：Session 安全回放与惰性生命周期

- [x] 执行 `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_w04_session_commands.py tests/test_application.py tests/test_cli.py tests/test_session_files.py -q`，全部通过。
- [x] Application replay DTO 按 durable sequence 完整包含 user、steering、reasoning、formal assistant 和 safe Tool terminal，且不包含 raw ToolResult、native payload、secret 或 pending state。
- [x] replay projection 不调用 Provider、不创建 Turn、不追加 Transcript；busy/corrupt/unknown/storage failure 保持当前 Session、锁和 replay 不变。
- [ ] TUI 冷启动后立即退出、只执行 help/status、打开并关闭 Session Picker 均不新增 Session ID。
- [x] 第一条普通输入恰好创建一个 Session；第一条 `/resume <id>` 不创建 throwaway Session；第一条 `/new` 只创建一个 Session；`exec <prompt>` 正常持久化。
- [x] lazy ensure 失败时无永久 user record、无 Provider call、Run 保持 idle，关闭无 active Session 安全。

## T05：Windows 进程输出解码

- [ ] 执行 `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_builtin_process_tool.py -q`，全部通过。
- [ ] UTF-8 中文 stdout/stderr、Windows OEM/ANSI 中文 stdout/stderr、非法混合 bytes、空输出和非零退出均有测试。
- [ ] Windows 正式 Bash 入口执行包含中文文件名的目录命令，结果不含 Unicode replacement character（`U+FFFD`）或 mojibake，exit code 正确。
- [ ] timeout、cancel、output limit、unsandboxed process execution 与现有 shell 选择语义不变。
- [ ] `rg -n "chardet|charset_normalizer|EncodingManager|EncodingRegistry" src tests` 不存在新编码猜测依赖或框架。

## T06：Tool 活动摘要与 FIFO 展示合同

- [ ] 执行 `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_application_tools.py tests/test_application_runs.py tests/test_agent_loop.py -q`，全部通过。
- [ ] Bash、ReadFile、WriteFile、EditFile、Glob、Grep、ToolResultRead、HistoryRead 的 name+summary 组合中 Tool 名均只出现一次。
- [ ] 至少两个 ToolCall 的同 batch 中，每个 ToolFinished 恰好一次且顺序与 call FIFO 相同；success/error/denied/cancelled/skipped 有文字状态。
- [ ] ToolStarted 只更新 transient activity，ToolFinished 才产生 permanent record；快速 Tool 不重复输出。
- [ ] 配置 secret、敏感 assignment/option、裸 key、Authorization/Bearer、`q7z`、`qz`、`q` ambient 值均脱敏，`0/1` 普通数字命令保持可读。
- [ ] Write/Edit content、Grep pattern、unknown/custom arguments 和 ToolResult 正文不进入事件、摘要或 replay。

## T07：TUI 时序化流式投影与 reasoning 视觉

- [ ] 执行 `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_tui.py -q`，全部通过。
- [ ] 长 reasoning 在 terminal 前至少产生两次 preview 更新，安全 Markdown block 可增量进入 scrollback，不等待完整 Turn。
- [ ] assistant delta 到达期间独立 preview 持续变化；权威 assistant block 只在消息完成后永久提交一次。
- [ ] `reasoning R -> assistant A`、`assistant A1 -> reasoning R -> assistant A2`、多 segment reasoning 的永久顺序、标题和出现次数均有精确断言。
- [ ] reasoning bar 与 formal assistant bar 使用不同语义色值；正文色可相同，颜色不是唯一角色标识。
- [ ] pending preview 不混合 reasoning/final；fenced code、resize、Tool force flush、terminal correction 均不重排或重复 scrollback。
- [ ] renderer 不再用多份以 `message_id:kind` 为键的字典分组 flush，已永久输出内容不可回写。

## T08：TUI `/resume` hydrate

- [ ] 跨进程创建包含 user、reasoning、final、两个 ToolCall 的 Session，重启后 `/resume`，全部安全记录按原 sequence 各显示一次。
- [ ] 回放中不存在 raw ToolResult、Tool arguments、native payload、API key、环境值或未提交 interaction；Tool 名无重复。
- [ ] replay 前后 Provider call count、Turn count 和 Transcript entry count不增加；`/new` 不回放旧 Session。
- [ ] 长 Session 按有界 batch 回放且 batch 间事件循环可调度；不会一次拼接巨型字符串冻结 TUI。
- [ ] hydrate 完成后第一条新消息的 Provider 请求包含恢复历史和唯一 current user tail；旧内容不重复持久化。
- [ ] busy/corrupt/unknown resume 原子失败，当前屏幕、Session 和 Run 不被部分替换。

## T09：[接入主流程] 唯一请求、历史、Session 与 TUI 链路

- [ ] 执行 F01 全部定向测试，普通、post-tool、post-resume、model switch、`/new`、CLI、Headless 和 TUI 均走唯一正式链。
- [ ] `tests/test_architecture_boundaries.py` 证明 Interface 不读取 Core History、Provider SDK、Session files、Tool Registry 或 Secret internals。
- [ ] active Turn reasoning/tool continuity、terminal Transcript、resume replay 与下一 Turn context 使用各自正确 typed view，无正文降级或双写。
- [ ] caller audit 证明 Prompt 双轨、reasoning→text fallback、full-message duplicate payload、cold-start ensure、kind-grouped renderer 和重复 Tool title 旧入口均不可达或已删除。

## T10：[端到端验证] 四现象、九类问题与真实入口验收

- [ ] 从正式 TUI 依次输入 `你好`、`你是什么模型`、`当前工作环境是？`、`？`，捕获请求证明消息来源、角色和 current user 尾部正确。
- [ ] 从正式入口完成 reasoning→Tool batch→final→退出→重启→`/resume`→继续对话，永久输出顺序、颜色、次数和上下文连续性符合 Spec。
- [ ] 在 Windows Terminal 人工验证 reasoning/final 流式刷新、不同 bar 色、Markdown fence、中文 shell 输出、scrollback、resize 和复制，结果写入 W06 Feedback。
- [ ] 执行 `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q`，全部通过。
- [ ] 执行 `conda run --no-capture-output -n re-uthcode python -m pytest -q`，精确 passed/failed/skipped 写入 W06 Feedback。
- [ ] 执行 `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests eval`，退出码为 0。
- [ ] 执行 `conda run --no-capture-output -n re-uthcode python -m pip check`，结果为 `No broken requirements found.`。
- [ ] 执行 `git diff --check`，退出码为 0；用户开工前已有改动未被覆盖。
- [ ] A01、A03、A04、TUI、用户手册及维护映射命中的当前文档与最终代码一致，全部通过 UTF-8 guard。

## T11：[遗留负担清理] 单一路径与历史负担收口

- [ ] `rg -n "ReasoningPart.*TextPart|text_values.*reasoning|reasoning.*text_values" src/uthcode/integrations/providers tests` 不存在跨 identity reasoning 降级正文逻辑；合理类型测试命中在 Feedback 说明。
- [ ] `rg -n "ensure_session\(" src/uthcode/interfaces` 的命中均有真实 prompt 或显式 Session 命令前置，不存在 TUI cold-start ensure。
- [ ] renderer、History 和 Prompt caller audit 不存在第二状态仓库、full-message payload duplication、分类型 flush 双轨或孤立 Prompt path。
- [ ] `rg -n "ReplayManager|HistoryManager|SessionMigration|EncodingManager|SecretManager" src tests` 返回 0 条。
- [ ] 本包临时 Session、probe、日志、截图和缓存已清理，不删除旧 Session 或用户文件。
- [ ] `docs/OutstandingDebtList.md` 已按“能力欠账：无”核对并保持不变；Out of Scope 未登记为欠账。
- [ ] 清理后重新执行 F01 最小定向、架构、全量、compileall、pip check、diff check 与 UTF-8 guard，精确结果写入 W06 Feedback。
- [ ] W01～W06 Feedback 齐全且全部 Checklist 有证据后，`docs/Context-Index.md` 将 F01 标记为 `implemented_unarchived`；未归档、未 commit、未 push。
