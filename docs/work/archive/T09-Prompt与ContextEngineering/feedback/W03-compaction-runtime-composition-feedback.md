# W03 Tool Result / Compaction / Runtime Composition Feedback

## 执行范围与冻结说明

- 已按指定 Prompt 执行 Task 6「大 Tool Result 外置与资源上限」和 Task 7「有界 Compaction 与 Runtime Request Composition」。
- W01/W02 Feedback、History、Context Compiler、Session files、AgentLoop/Run/generation、Provider mapper 与相关测试均已核对。
- 按 `docs/rules/WorkPackageRules.md`，Spec、Tasks、Prompt 及 Checklist 文字和结构保持冻结；Tasks 未改写，Checklist 只把已有验收项从 `[ ]` 改为 `[x]`。
- 未执行 Git commit、push、merge、rebase、tag、release 或工作包归档。

## 实际完成内容

### Task 6：Tool Result 外置

- Core `ToolExecutor` 不再做永久 10K 截断，返回完整 `ToolExecutionOutcome`，并保留 `SUCCEEDED`、`FAILED`、`CANCELLED`、`UNKNOWN` 等执行事实。
- Application 在执行完成后独立进行 materialization：小结果 inline，大结果写入当前 Session 的受控目录；`ToolResultPart.metadata` 记录 execution/persistence 状态、ref、size 和 SHA-256。
- Integration 以随机 opaque ref 建立 `tool-results/<ref>/content.bin` 与 `metadata.json`，写入使用临时目录、flush/fsync、原子 rename；配额、hard cap、metadata 或内容写失败会清理临时目录和本次 final 目录。
- 新增 `ToolResultRead`，只接受当前 Session 的 opaque ref、非负 offset 和受限 limit，不接受任意文件路径，不允许跨 Session 读取；读取时重新校验 Session ownership、字节数、UTF-8 内容和 SHA-256。
- Tool 已产生副作用而持久化失败时，结果明确写出“Tool already ran”，执行状态仍为 succeeded，persistence 为 failed，AgentLoop 不自动重试该 Tool。

### Task 7：Compaction 与 Runtime Request Composition

- 新增 provider-independent `CompactionPolicy`：`input_budget=64000`、`output_reserve=4096`、`summary_hard_cap=2048`；实际 summarizer 输入使用 `input_budget - output_reserve`。
- `ContextCompactor` 按完整 `SemanticUnit` 做有界滚动批次；ToolCall/ToolResult 成对保留，不拆分；summary callback 只接收文本，不接 Provider、Tool、filesystem 或 Tool Registry。
- 同一 Session 使用 single-flight；取消、非法 summary、单 unit 超预算、Projection boundary 无效等失败均返回旧 Projection，且不改写 Canonical History。Compaction 不创建 Instruction Epoch。
- Provider 413 映射为 `ContextOverflowError`。每个 Agent Turn 最多执行一次 compaction/recompile 保护；不做模型窗口 discovery、动态 denominator 或自动重试 Tool。
- 所有正式生成请求均先经 `ApplicationContextService.compose_generation_request` 和固定 258K Compiler：Instruction Plane 形成 `system_prompt`，Conversation/Contextual Plane 形成 `messages`，Tool System 的唯一结构化来源进入 `GenerationRequest.tools`；Provider Integration 只映射 native protocol 字段。
- 普通历史、伪造的 AGENTS/Runtime 标签和动态工作目录不会进入 Instruction Plane。工作目录、平台、日期、行为模式、Task/Plan 和一次性反馈进入 Contextual/Conversation Plane；模型选择和 Provider identity 也不再写入动态系统提示。
- Projection summary 保持 History authority；仅 Projection/Compaction revision 变化时，Instruction Epoch、稳定 Instruction prefix 和 fingerprint 不变。

## 资源上限选择与证据

资源限制按 UTF-8 bytes 计算，而不是字符数或远端模型窗口：

| 限制 | 数值 | 选择依据 |
| --- | ---: | --- |
| inline threshold | 8 KiB | 常规小型读写结果不产生 Session I/O；代表性小结果测试保持完整 inline。 |
| externalized preview | 2 KiB | Provider working view 只保留 bounded preview，完整内容留在 durable bytes。 |
| single-result hard cap | 1 MiB | 阻止单个 Tool Result 无界占用 Session；超限返回受控 persistence failure。 |
| Session quota | 8 MiB | 限制一个 Session 的累计外置字节；超额前置拒绝，不留下 dangling ref。 |
| ToolResultRead page | 64 KiB | 单次读取有界，避免把完整外置结果重新带回 working view。 |

测试用较小的等价 policy 做边界覆盖，并以超过 10K 的代表性输出验证：Core 保留原文，Application 产生 bounded preview，文件 hash/size 与原始 UTF-8 bytes 一致。上述数值是 UthCode 本地资源上限，不代表 Provider 的物理 context window。

## 正式数据流

```text
ToolCall
  -> Core ToolExecutor
  -> ToolExecutionOutcome(full content + execution status)
  -> Application materialize_tool_result
  -> Session Integration atomic bytes/ref/hash
  -> bounded ToolResultPart + execution/persistence metadata
  -> current-Session ToolResultRead(offset, limit)

RunState/messages + InstructionLoader + Runtime/Environment facts + Projection + Tool definitions
  -> ApplicationContextService
  -> fixed 258K ContextCompiler
  -> Instruction Plane / Conversation Plane / Contextual Plane + Tool System
  -> GenerationRequest
  -> native Provider mapper
```

## 修改文件

主要源码改动集中在：

- `src/uthcode/core/provider.py`、`core/tool.py`、`core/agent.py`、`core/context.py`、`core/history.py` 及 Core exports；
- `src/uthcode/application/context.py`、`generation.py`、`tools.py`、`sessions.py`、`bootstrap.py` 及 Application exports；
- 新增 `src/uthcode/integrations/tools/tool_result_read.py`，并扩展 `integrations/session_files.py` 和三个 Provider mapper 的 overflow 映射。

测试覆盖新增或迁移至：

- `tests/test_tool_result_persistence.py`；
- `tests/test_context_compaction.py`；
- Tool Core、Application request/run、Session、Provider mapper、架构边界、CLI 与 T08 E2E 的既有断言迁移。

## 验证结果

以下命令均在 Conda 环境 `re-uthcode` 中执行：

- `conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_tool_result_persistence.py tests/test_context_compaction.py tests/test_agent_loop.py tests/test_application_runs.py`：**114 passed**，3.51s。
- `conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_architecture_boundaries.py tests/test_context_compiler.py tests/test_session_files.py tests/test_anthropic_integration.py tests/test_openai_responses_integration.py tests/test_openai_compat_integration.py`：**96 passed, 3 skipped**，11.04s。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests eval`：退出码 **0**。
- `conda run --no-capture-output -n re-uthcode python -m pip check`：**No broken requirements found**。
- 全量 `python -m pytest -q`：**1152 passed, 3 skipped**，93.11s；复核时临时清除了当前 shell 的 `NO_COLOR=1` 并设置 `TERM=xterm-256color`，以便 TUI ANSI 颜色断言按真实颜色路径运行。
- `git diff --check`：无 whitespace error。仅执行了只读 Git 检查，没有 Git 写入。
- 静态扫描确认正式 Agent path 没有 `GenerationRequest(messages=messages)` 直通、永久 `Output truncated to 10000` 或 Core `_truncate` 结果截断实现。

## Checklist 状态

- Task 1 中与 Tool System 单一来源、history authority、ordinary history spoof 和动态 facts 稳定 prefix 相关的已有验收项已勾选。
- Task 6 的六项验收和 Task 7 的六项验收均已勾选，并由上述定向测试与架构/Provider 测试提供证据。
- Task 8（Slash/TUI Session commands）、Task 9（Eval/diagnostics）、Task 10 中的 compact-resume 完整主流程、Task 11 的全套跨工作包端到端矩阵和 Task 12 的全项目文档维护仍未勾选；这些属于后续 Worker 或包级收口范围，本次没有冒 scope 实施。

## 未完成项、风险与遗留边界

- 未实现 Artifact GC、任意路径读取、跨 Session ref、复杂 summary graph、Memory/relevance/embedding、Slash/TUI、Eval 或 Git 能力。
- `ToolResultRead` 需要 active Session；没有 active Session 时，大结果会返回“已执行但无法 durable persistence”的受控结果，不会假装未执行或盲目重试。
- 本次没有把所有 RunState 事实自动写入 durable Session History，也没有实现 `/compact`、`/resume` 命令级闭环；W04/W05/W06 仍需按其冻结边界执行。
- 现有 TUI 颜色测试受 shell 的 `NO_COLOR=1` 影响；最终全量验证已在明确临时解除该环境限制后通过，未修改 TUI 代码或环境持久配置。
- 未遇到需要用户拍板的产品、架构、范围或安全决策；未扩大到 W03 以外的能力。

## UTF-8 guard

- files checked: 本 Feedback、`T09-Prompt与ContextEngineering-checklist.md`。
- result: 写入后使用仓库可用的 `check_utf8_docs.py` 检查 UTF-8、replacement/mojibake marker 和 Markdown fence；结果为 **2 file(s) passed UTF-8 guard**。
- repaired encoding issues: 无。

## 第二轮定点返工（2026-08-16）

### 返工原因与冻结边界

- 本轮只处理验收确认的 5 个问题：消息内容全局去重、默认 Compaction 边界推进、execution/persistence 的 `is_error` 混淆、Compiler 后追加 `system_prompt`、ToolResultRead 分页元数据丢失。
- 未实施 Task 8～12，未引入 T09-1 Model Limits，也未扩大到 Slash/TUI、Eval、Memory、Artifact GC 或其他后置能力。
- 未修改冻结的需求文件、Spec、Tasks、Prompt；Checklist 未新增或改写验收项。

### 1. 消息恢复改为身份边界

`messages_from_context_snapshot()` 已删除按完整消息内容维护的全局 `seen` 集合。普通 User、Assistant、Tool 消息不再因为文本相同而被删除。

历史 Entry 的局部重建身份使用 `(session_id, turn_id, role)`：

- 同一历史 Message 被拆成多个 Entry 时，在连续身份范围内合并 parts；
- `_history_for_messages()` 将完整 Message 重复写入多个 part Entry 时，只在同一身份范围内保留一次完整 Message；
- 不同 turn 的相同 User 文本、当前 User 与历史 User 均保留；
- Context、Projection 或其他非历史 Block 会打断该局部重建范围；
- Compiler 选中的当前 User 仍位于最终 Conversation Plane 尾部，ToolCall/ToolResult 结构不被文本化替代。

### 2. 默认 Compaction fail closed，正式 overflow 不再伪造 Summary

- 删除原先“拼接 JSON 后从尾部截断”的默认 Summary fallback。
- `summarize is None` 时返回 `changed=False`、`failure="summarizer_unavailable"`，保留旧 Projection，不创建新 Projection，不触发伪成功 retry。
- 注入合法 summarizer 时仍按完整 SemanticUnit 分批；每个输入包含 rolling prior summary 与新增 units，并受 `input_budget - output_reserve` 限制，输出继续受 `summary_hard_cap` 限制。
- 只有所有实际生成的批次都成功并通过 Projection boundary 校验后，才返回推进到最后一个已处理完整 unit 的候选 Projection；任何批次失败均返回旧 Projection，Canonical History 不变。
- 正式调用链已由 `AgentRun -> UthCodeApplication._start_agent_turn -> ContextOverflowError -> Application overflow handler -> ApplicationContextService.compact -> ContextCompactor` 覆盖；默认缺失 summarizer 时 handler 返回 false，AgentLoop 不进行第二次 Provider 请求。

### 3. 保持 execution `is_error`，独立表达 persistence failure

hard cap、Session quota、无 active Session 和普通 persistence exception 的受控 materialization 结果现在均使用 `outcome.is_error`，不再强制设置 `is_error=True`。

结果 metadata 独立记录：

```text
execution_status
persistence_status=failed
error_code
```

成功执行但持久化失败时，Provider 看到 `is_error=False`，文本明确说明 Tool 已执行、结果持久化失败且不得自动重试；失败执行即使同时 persistence failure，仍保持 `is_error=True`。AgentLoop 的副作用调用计数保持一次，不自动重试。

### 4. 删除 Compiler 后的 `system_prompt` 追加

正式 Turn 的 request preparation 不再在 `compose_generation_request()` 返回后追加模型选择文本。Provider request 的 `system_prompt` 完全来自 Context Compiler 的 Instruction Plane；模型选择、Provider 协议和远端模型继续作为 Environment/Contextual facts 出现在 Conversation Plane。

因此 model/provider identity 变化不会改变 Instruction State、stable Instruction prefix 或 fingerprint，且真实发送的 Instruction text 与 Compiler 输出一致。

### 5. ToolResultRead 返回分页元数据

`ToolResultRead` 现在返回 bounded JSON：

```json
{"content":"...","eof":false,"next_offset":12,"offset":0,"ref":"...","sha256":"...","total_bytes":42}
```

其中 `next_offset` 使用 Integration 计算的合法 UTF-8 byte boundary；最后一页返回 `eof=true` 且 `next_offset=total_bytes`。ref 仍为当前 Session scoped opaque ref，不暴露路径，ToolResultRead 自身仍不会再次 externalize。ASCII 与多字节 UTF-8 连续分页均可无损恢复原文。

### 第二轮新增或修正测试

- `tests/test_context_compaction.py`：重复 User/current User 保留、多 part Message 按身份合并、缺失 summarizer fail closed、多批 marker 覆盖和正式 `create_application` overflow 无伪 retry。
- `tests/test_tool_result_persistence.py`：成功/失败 execution 的 `is_error` 保持、persistence status 独立、ASCII/多字节 UTF-8 分页 metadata 和 continuation。
- `tests/test_application_runs.py`、`tests/test_application_runtime.py`：model/provider facts 不进入 Compiler 后追加的 Instruction Plane，stable prefix/fingerprint 保持一致。

### 第二轮验证结果

以下命令均在 Conda 环境 `re-uthcode` 中执行：

- 定向返工与相关回归：**222 passed, 3 skipped**，31.68s。
- `python -m compileall -q src tests eval`：退出码 **0**。
- `python -m pip check`：**No broken requirements found**。
- 全量 `python -m pytest -q`：**1160 passed, 3 skipped**，139.94s；执行时仅临时移除当前 shell 的 `NO_COLOR=1` 并设置 `TERM=xterm-256color`，未修改持久环境或 TUI 代码。
- `git diff --check`：无 whitespace error；输出仅为既有工作树文件的 LF/CRLF 转换提示。
- 静态确认：无跨 semantic unit 的消息内容全局去重、无 Compiler 后追加 `system_prompt`、成功 execution 的 persistence failure 不再强制 `is_error=True`、默认 overflow 不使用伪 Summary、ToolResultRead 输出包含 `next_offset` 与 `eof`。

### 未实施范围与 Git 边界

- Task 8～12、Slash/TUI、Eval、Memory/relevance、Artifact GC、T09-1 Model Limits 及其他非本轮验收问题保持未实施。
- 未执行任何 Git commit、push、PR、merge、rebase、tag、release 或 archive。

## 第四轮定点返工（2026-08-17）

### 剩余 P0：空 Summary fail closed

修复了第三轮复验发现的最后一个 P0：`ContextCompactor` 现在在接受 summarizer 输出前先拒绝空字符串和纯空白字符串，失败原因固定为 `summary_empty`。`SummaryHardCap` 仍是严格输出验收边界：合法且非空的输出不得超过 hard cap；任何非法输出都不会通过截断、占位或其他方式继续成功。

单批空/纯空白 Summary 现在返回 `changed=False`、`failure="summary_empty"`，没有旧 Projection 时保持 `projection=None`、`summary=None`。多批场景在中途遇到空 Summary 时，整次候选 Compaction fail closed，已生成的临时 batch 不会提交，旧 Projection、旧 Summary 和 Canonical History 保持不变。正式 Provider overflow 路径同样不追加 Projection、不伪 retry，终止原因为 `provider_error`，Provider request 仍只有一次。

### 本轮测试与验证

- `tests/test_context_compaction.py`：增加单批空字符串、纯空白字符串；增加多批中途空 Summary 丢弃全部候选；正式 Application overflow 覆盖超限、空字符串和纯空白 Summary。
- 定向 W03/第二轮相关测试：**237 passed, 3 skipped**，14.74s。
- 全量 `python -m pytest -q`：**1175 passed, 3 skipped**，98.39s；仅临时调整当前测试进程的终端环境变量，未修改持久环境或 TUI 代码。
- `python -m compileall -q src tests eval`：退出码 **0**。
- `python -m pip check`：**No broken requirements found**。
- `git diff --check`：无 whitespace error；仅有既有工作树文件的 LF/CRLF 转换提示。
- `uth-utf8-guard`：Feedback 与 Checklist 均通过 UTF-8、乱码和 Markdown fence 检查。

### 范围与 Git 边界

- 第三轮已修复的 SummaryHardCap 严格失败语义和 ToolResultRead 最终 JSON bytes 预算未回退；Task 8～12、T09-1、Slash/TUI、Eval、Memory、Artifact GC 及其他范围外能力仍未实施。
- 未修改冻结的任务书、Spec、Tasks、Worker Prompt；Checklist 未改写验收要求。
- 未执行任何 Git commit、push、PR、merge、rebase、tag、release 或 archive。

## 第三轮定点返工（2026-08-17）

### 返工范围与冻结边界

- 本轮只修复两个新增边界缺口：SummaryHardCap 超限后的错误推进，以及 ToolResultRead JSON 转义后的最终输出超预算。
- 第二轮的消息身份边界、缺失 summarizer fail closed、execution/persistence 分离、Compiler request 收口和分页元数据均保持不变。
- 未修改冻结的需求文件、Spec、Tasks、Worker Prompt 或 Checklist 文字；未实施 Task 8～12、T09-1、Slash/TUI、Eval、Memory、Artifact GC。

### 1. SummaryHardCap 改为严格输出合同

删除 `_bound_summary()` 的语义未知截断行为。每个 rolling batch 的 summarizer 输出现在直接按 `token_estimator` 检查：

```text
estimated output <= summary_hard_cap
    -> 接受原始 Summary
estimated output > summary_hard_cap
    -> failure="summary_hard_cap_exceeded"
       changed=False
```

不再按字符、bytes 或 token 截断后继续成功，因此不会出现 Summary 丢失最新 marker 但 Projection 仍推进的情况。

单批或中间批次超限都会返回旧 Projection 与旧 Summary；即使之前已有成功的临时 `CompactionBatch`，也不会构造或持久化新的 Projection，Canonical History 保持字节不变。没有旧 Projection 时返回 `projection=None`、`summary=None`、`changed=False`。正式 overflow handler 看到 `changed=False` 后不追加 Projection，也不发起第二次 Provider request。

边界值已验证：估算输出等于 `SummaryHardCap` 可以成功，超过 1 token 失败；多批场景中第二批超限会丢弃整次候选，而不是提交第一批。

### 2. ToolResultRead 最终输出预算

ToolResultRead 的预算分为两个已有/新增的 operational limit：

- `read_page_limit_bytes`：原始 Integration page 的最大读取请求；
- `read_output_limit_bytes`：最终模型可见 JSON envelope 的 UTF-8 bytes 上限。

最终有效预算定义为：

```text
effective_read_output_limit = min(
    read_page_limit_bytes,
    read_output_limit_bytes,
)
```

因此正文原始 bytes、JSON key/ref/offset/total_bytes/sha256/eof 元数据、JSON 对控制字符/引号/反斜杠产生的转义 bytes，全部共同计入最终上限。`ToolResultRead` 会在不超过原始 page limit 的候选范围内搜索最大可用页，并只返回满足最终 JSON UTF-8 bytes 预算且能够前进的页面。

候选页仍由 Integration 计算真实 UTF-8 boundary：`offset`、`next_offset` 不拆 code point，下一次读取直接使用 `next_offset`；当候选 raw limit 小于下一个多字节字符时，搜索会扩大候选下界，而不是错误地放弃能够前进的更大 limit。若预算连 envelope 和一个可前进字符都无法容纳，则返回 `tool_result_output_limit_exceeded` 受控错误，不返回空的非 EOF 页面。

ToolResultRead 继续返回 `ref`、`offset`、`next_offset`、`total_bytes`、`sha256`、`eof` 和 `content`，ref 仍为当前 Session scoped opaque ref，不暴露路径、不允许跨 Session，也不递归 externalize。

### 第三轮新增测试

- `tests/test_context_compaction.py`：单批超限、多批中途超限、严格等于 cap、超过 cap+1、正式 Application overflow 超限；覆盖旧 Projection、Canonical History、Provider request 数量和 `provider_error`。
- `tests/test_tool_result_persistence.py`：NUL/控制字符、双引号、反斜杠、普通 ASCII、多字节 UTF-8 的最终 JSON bytes 限制；使用 `next_offset` 连续读取并按原始 UTF-8 bytes 无损恢复；覆盖无法容纳 envelope/字符时的受控错误和最后一页 `eof=true`。

### 第三轮验证结果

以下命令均在 Conda 环境 `re-uthcode` 中执行：

- W03 返工与第二轮全部相关回归：**232 passed, 3 skipped**，15.06s。
- 全量 `python -m pytest -q`：**1170 passed, 3 skipped**，99.03s；执行时仅临时移除当前 shell 的 `NO_COLOR=1` 并设置 `TERM=xterm-256color`，未修改持久环境或 TUI 代码。
- `python -m compileall -q src tests eval`：退出码 **0**。
- `python -m pip check`：**No broken requirements found**。
- `git diff --check`：无 whitespace error；仅有既有工作树文件的 LF/CRLF 转换提示。
- 静态确认：不存在 Summary 超限截断后 `changed=True` 的路径；`summary_hard_cap_exceeded` 可由单批和中途批次真实到达；超限 batch 不推进 Projection；ToolResultRead 最终 JSON bytes 受有效预算约束；控制字符和多字节分页可持续前进并无损恢复。

### 未实施范围与 Git 边界

- Task 8～12、T09-1 Model Limits、Slash/TUI、Eval、Memory/relevance、Artifact GC 及其他范围外能力保持未实施。
- 未执行任何 Git commit、push、PR、merge、rebase、tag、release 或 archive。
