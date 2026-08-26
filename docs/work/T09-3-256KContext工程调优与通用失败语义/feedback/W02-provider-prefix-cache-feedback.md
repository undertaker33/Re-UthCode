# W02：Provider Prefix Cache Feedback

## 交付结论

W02 已按 T03 完成：OpenAI Responses 仅在存在稳定 UthCode request facts 时发送有界、确定性的 `prompt_cache_key`；Anthropic 在稳定 tools/system 前缀末端发送显式 block `cache_control`，并让 count endpoint 与生成请求使用同一 wire shape；OpenAI-compatible 保持不发送专有缓存字段。现有 usage availability/provenance mapper 已满足 T03 契约，没有重复改写。未实施 FailureReason、Eval tuning、Interface 展示或 Git 写入/归档。

## 官方资料与 SDK 证据

实施日为 2026-08-25。核对的官方资料：

- [OpenAI Prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching)：Responses 的稳定前缀由模型、工具及请求前缀事实共同决定；`prompt_cache_key` 用于相同前缀的 routing/grouping，不能保证 cache read；usage 通过 `input_tokens_details.cached_tokens` 与 `cache_write_tokens` 观察。当前没有可靠的模型 capability authority，因此没有发送 `prompt_cache_options`、`prompt_cache_retention` 或显式 breakpoint 等不确定参数。
- [Anthropic Prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)：官方前缀顺序为 tools -> system -> messages；显式 breakpoint 应放在最后一个稳定 block，cache usage 由 `cache_read_input_tokens` 与 `cache_creation_input_tokens` 观察。

在 `re-uthcode` 中用 fake key 仅实例化 SDK、未发起请求，signature/version 结果为：

```text
openai 2.53.0
responses.create: prompt_cache_key、prompt_cache_options、prompt_cache_retention 均存在于当前 signature
anthropic 0.120.2
messages.create: system 支持 str 或 Iterable[TextBlockParam]，tools 支持 Iterable[ToolUnionParam]
messages.count_tokens: system 支持 str 或 Iterable[TextBlockParam]，tools 支持 Iterable[MessageCountTokensToolParam]
```

## Provider wire 选择

### OpenAI Responses

`_prompt_cache_key()` 只读取 `stable_prefix_fingerprint`、存在 tools 时的 `tool_schema_fingerprint`，以及实际生效的 model；将这些稳定事实以排序 canonical JSON 编码后计算 SHA-256，输出 `uthcode:` 前缀的有界字符串。没有稳定 prefix、或有 tools 但没有可靠 tool schema fingerprint 时不发送 key。

conversation 正文、system 正文、secret、Provider native object、`prefix_change_reason` 和其它动态 metadata 都不进入 key。fake fixture 证明相同稳定 facts 的不同 conversation 得到相同 key；instruction prefix、tool schema 或 model 变化得到不同 key；缺少 tool fingerprint 时不猜测发送。请求只发送 `prompt_cache_key`，不发送当前缺少 capability authority 的其它 Responses cache 参数。

### Anthropic Messages

当 stable prefix facts 可用且有 system prompt 时，tools 保持正式 `input_schema` 映射，system 发送为单个 text block，并在该稳定 system block 末端加：

```json
{"cache_control":{"type":"ephemeral"}}
```

这使 marker 位于 tools 之后、messages 之前；system 文本没有复制 Tool Schema。当没有 system prompt 但有 tools 时，marker 放在最后一个 tool definition；没有稳定 facts 时保留原有无 marker shape。`stream()` 与 `count_input_tokens()` 共用同一 mapping helper，fixture 精确比较两者的 system/tools/messages shape。

### OpenAI-compatible

即使 request metadata 含 stable prefix/tool fingerprint，也不发送 `prompt_cache_key`、`prompt_cache_options`、`prompt_cache_retention` 或 Anthropic `cache_control`。当前没有 capability/config authority，未新增配置或按端点名称猜测。

## Usage availability 与 invalidation

三个 Provider 的现有 mapper 继续把 provider 已报告的 read/write 字段映射到 Core `Usage`；`application/provider_usage.py` 已按 details path 输出 `available` 与 provenance，明确报告零值仍为 available，缺字段保持 `not_available` 且 tokens 为 `None`。因此本轮没有改动该文件或重建 availability/provenance 链；`tests/test_w05_diagnostics.py` 的缺失、显式零、provider provenance 与累计 usage 回归均通过。缺失 cache ratio 也没有伪造数值。

预期失效边界为真实 AGENTS/instruction source、tool schema 或 model identity 变化；普通 conversation growth 与 Timeline compact 不改变 stable instruction/tool prefix。现有 Context compiler/W05 fingerprint tests 覆盖 runtime/timeline 不变和真实 instruction scope 变化；本轮 OpenAI fixture 进一步覆盖 stable key 的相同/变化关系。没有新增动态 conversation 造成的意外 key 变化。

## 实际修改

- 生产：`src/uthcode/integrations/providers/openai_responses.py`、`src/uthcode/integrations/providers/anthropic.py`。
- 测试：`tests/test_openai_responses_integration.py`、`tests/test_anthropic_integration.py`、`tests/test_openai_compat_integration.py`。
- `src/uthcode/integrations/providers/openai_compat.py` 与 `src/uthcode/application/provider_usage.py` 已核对；没有真实生产缺口，因此保持不变。
- 治理：本 Feedback；T09-3 Checklist 仅勾选已验证的 T03 项。未修改原始任务书、Spec、Tasks、Prompt 或其它冻结文档。

## 验证结果

所有命令均在 `D:\project\Re-UthCode` 使用 Conda `re-uthcode`；Provider 调用均为 fake client/request fixture，无网络、真实 API key 或费用调用：

```text
conda run --no-capture-output -n re-uthcode python -m pytest tests/test_openai_responses_integration.py tests/test_anthropic_integration.py tests/test_openai_compat_integration.py tests/test_w05_diagnostics.py -q
56 passed, 3 skipped in 8.25s

conda run --no-capture-output -n re-uthcode python -m pytest tests/test_context_compiler.py tests/test_application_runs.py -q
53 passed in 12.97s

conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q
23 passed in 8.95s

rg -n "prompt_cache_key|cache_control" src/uthcode/core src/uthcode/interfaces
0 matches

git diff --check
exit code 0；只有工作区既有的 LF/CRLF 转换提示，无 whitespace error
```

Live Provider cache hit、latency、billing 和真实 token usage 未验证：`NOT VERIFIED (authorization required)`。本轮未读取真实 secret，未修改 `pyproject.toml`，未新增 CacheManager/Registry、Core cache DTO、Provider KV lifecycle、本地 Cache DB、capability config 或第三方依赖。

## 决策与范围映射

- D-T09-3-04：不按 model name 猜测能力；model identity 只作为已确定 request fact 进入 OpenAI key，专有 wire 字段仍封装在 Integration，Compat 默认无专有参数。
- D-T09-3-06：使用 deterministic fake wire fixtures 和现有 diagnostics/fingerprint tests，未修改 Eval runner、未引入 tuning 或 live 收益声明。
- D-T09-3-01、D-T09-3-02、D-T09-3-03：W01 的 budget/provenance、Context fingerprint 与 gate/compact 语义只被消费，未在 W02 重排或扩展。
- D-T09-3-05、D-T09-3-07：FailureReason、统一 Application/Interface failure projection 和包级端到端交付属于后续 W03/W05，未在本 Worker提前实施。

## 返工第一轮

### 返工原因与关闭结论

本轮只处理 T03 的当前验收问题，没有实施 T04+、FailureReason、Eval tuning 或 Interface 失败分类，也没有修改 Checklist。关闭的四项问题为：OpenAI `prompt_cache_key` 原先为 `uthcode:` 加 64 位 SHA-256 hex、总长 72；无 tools 时无关 `tool_schema_fingerprint` 会制造 routing key 变化；OpenAI fixture 未把真实 Tool Schema 接入 request；Timeline/compact 证据没有执行正式 compact 链；旧 Feedback 未映射 D-T09-3-08。

### OpenAI key shape 与 tool fingerprint 条件

官方 [OpenAI Responses compact API reference](https://developers.openai.com/api/reference/java/resources/responses/methods/compact) 的 `promptCacheKey` 明确为 `maxLength 64`；该事实在 2026-08-26 重新核对。当前实现保持 `uthcode:` namespace，使用 canonical JSON 输入的 SHA-256，并截取摘要前 56 位：

```text
uthcode: + sha256(canonical stable facts).hexdigest()[:56]
总长 = 8 + 56 = 64
```

key 仍只依赖 stable prefix fingerprint、实际生效 model，以及在 `request.tools` 非空时的可靠 tool schema fingerprint；不含 conversation 正文、system 正文、secret、Provider native object、原始 fingerprint 或 model 原文。fixture 精确断言长度 `<= 64`、相同稳定事实得到完全相同 key、正文/fingerprint/model/secret 不出现在 key 中，并且不发送 `prompt_cache_options` 或 `prompt_cache_retention`。

`request.tools` 非空时才读取并要求 `tool_schema_fingerprint`；缺少时不发送 key。`request.tools=()` 时完全忽略 metadata 中的 tool fingerprint，因此新增或改变无关 tool metadata 不改变 key，不产生 routing churn。

### 真实 Tool Schema fixture

`tests/test_openai_responses_integration.py` 现在用实际 `ToolDefinition` 构造 request，并用同一组 definition 通过 `ToolDefinitionSource` 产生 schema fingerprint。测试覆盖：相同 tools/不同 conversation 正文保持 key；修改真实 tool description 与 parameters、同时传入对应新 definition 和 fingerprint 后 key 变化；有 tools 缺 fingerprint 不发送 key；无 tools 时改变无关 tool fingerprint 仍保持 key；instruction prefix 和 model identity 变化仍按合同失效。

### 正式 Timeline compact 稳定性证据

`tests/test_context_compiler.py` 新增正式链测试：使用 `ContextCompiler`、`Transcript`、`ToolDefinitionSource` 和 `ContextCompactor`，先编译 compact 前 snapshot/request，再执行现有 `ContextCompactor` 生成真实 `Timeline` 与 `ActiveCheckpoint`，把该 Timeline 重新交给 Compiler 编译 compact 后 snapshot/request。测试精确证明 ordinary conversation growth 与 Timeline checkpoint/derived records 变化不改变 `stable_prefix_fingerprint`、tool fingerprint 或 cache key；实际 instruction source、真实 Tool Schema 和 model identity 变化分别产生预期 key invalidation。

### 实际修改文件与冻结边界

- 本轮生产：`src/uthcode/integrations/providers/openai_responses.py`。
- 本轮测试：`tests/test_openai_responses_integration.py`、`tests/test_context_compiler.py`。
- 本轮文档：仅向本 Feedback 文件末尾追加本节。
- W02 既有 Anthropic/Compat/usage 行为、Checklist 勾选状态、W01 Context limit/High-Low/compact 行为均未改动；本轮未修改 `src/uthcode/integrations/providers/anthropic.py`、`src/uthcode/integrations/providers/openai_compat.py` 或 `src/uthcode/application/provider_usage.py`。
- D-T09-3-04：key 只使用已确定的 request facts，未按 model name 猜测 capability，cache wire 仍只在 Integration。
- D-T09-3-06：使用 deterministic fake client、真实 ToolDefinition/ContextCompactor fixture，未修改 Eval runner 或调优参数。
- D-T09-3-08：补齐 T03 Provider request shape、Context Compiler/Timeline 稳定性、架构边界与本 Feedback 的可追踪证据。
- D-T09-3-01～03、D-T09-3-05、D-T09-3-07：W01 budget/provenance、Context gate/compact、FailureReason、统一 Application/Interface failure projection 与包级交付均未改变。

### 精确验证结果

以下命令均在 `D:\project\Re-UthCode` 使用 Conda `re-uthcode`；Provider 测试使用 fake client/request，无网络和真实 API key：

```text
conda run --no-capture-output -n re-uthcode python -m pytest tests/test_openai_responses_integration.py tests/test_anthropic_integration.py tests/test_openai_compat_integration.py tests/test_w05_diagnostics.py -q
56 passed, 3 skipped in 4.36s

conda run --no-capture-output -n re-uthcode python -m pytest tests/test_context_compiler.py tests/test_application_runs.py -q
54 passed in 6.19s

conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q
23 passed in 4.48s

conda run --no-capture-output -n re-uthcode python -m pytest -q
1228 passed, 3 skipped in 104.71s (0:01:44)

conda run --no-capture-output -n re-uthcode python -m compileall -q src tests eval
exit code 0

conda run --no-capture-output -n re-uthcode python -m pip check
No broken requirements found.

rg -n "prompt_cache_key|cache_control" src/uthcode/core src/uthcode/interfaces
0 matches

git diff --check
exit code 0；仅有工作区 LF/CRLF 转换提示，无 whitespace error
```

本轮新增 focused regression 为 `2 passed in 4.43s`，已包含在上述两组定向测试和全量结果中。Live Provider cache hit、latency、billing、真实 token usage 仍为 `NOT VERIFIED (authorization required)`；未读取真实 API key、未访问真实 Provider、未执行 Git commit/push/PR/归档。

### 风险与遗留负担

key 截断只解决 OpenAI 的 64 字符 wire 合同，不把 routing key 误报为 cache hit 保证；真实命中率、费用和模型端 capability 仍需有授权的 live 验证。没有新增 CacheManager、Registry、Core cache DTO、capability config、Provider KV lifecycle、本地 Cache DB、依赖或兼容双轨逻辑。
