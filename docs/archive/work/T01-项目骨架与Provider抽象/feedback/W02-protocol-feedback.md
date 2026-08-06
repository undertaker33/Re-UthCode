# W02 Protocol Feedback

## 本轮结果

Task 5—Task 7 已完成，三条协议均通过离线 Mock SDK 测试和 W01 基线回归。未修改 Core 契约、Application 语义、依赖声明或后置 Task 8—Task 11 能力。

## 实际实现

- `pydantic_ai.py` 增加协议无关的 `PydanticAICodec` 扩展点、Direct 流原始事件记录、JSON-safe Mapping/Sequence 转换、缓存用量归一化，以及交错 Tool Call 在最终响应阶段补发完成事件。共用层没有 Provider 名称分支或协议专有字段。
- `anthropic.py` 实现 Messages Model 构造和 Codec：保留 Thinking、Signature、Redacted Thinking、Text、Tool Use 的顺序与同身份 Native Item，并映射 Tool Result、缓存读写用量、`message_stop`/stop reason、取消和错误。
- `openai_responses.py` 实现 Responses Model 构造和 Codec：按 output index 保存 Reasoning、Summary、Message、Function Call 的原始完成 Item；对重复 Delta/Done/Terminal frame 去重，对冲突、缺失终态、未完成调用和非 completed 终态拒绝；同协议请求恢复 Reasoning、Function Call 和 `function_call_output`。
- `openai_compat.py` 实现 Chat Completions Model 构造和 Codec：使用 function tool、assistant `tool_calls` 和 `role=tool`，从原始 chunk 恢复 Tool Call stream index，支持 `reasoning_content` carrier、缓存用量、完成原因、取消和错误；未引入 Responses Item 结构。

Native Item 只在 `ProviderIdentity(provider, protocol, model)` 完全匹配时回放，切换身份时只保留 Core 通用语义。

## 文件变更

- 新增：`src/uthcode/integrations/providers/anthropic.py`
- 新增：`src/uthcode/integrations/providers/openai_responses.py`
- 新增：`src/uthcode/integrations/providers/openai_compat.py`
- 新增：`tests/test_anthropic_integration.py`
- 新增：`tests/test_openai_responses_integration.py`
- 新增：`tests/test_openai_compat_integration.py`
- 修改：`src/uthcode/integrations/providers/pydantic_ai.py`
- 修改：`T01-项目骨架与Provider抽象-checklist.md`，仅将 Task 5—Task 7 已通过条目标为完成。

## 验收证据

- `conda run -n re-uthcode pytest -q tests/test_anthropic_integration.py`：10 passed。
- `conda run -n re-uthcode pytest -q tests/test_openai_responses_integration.py`：9 passed。
- `conda run -n re-uthcode pytest -q tests/test_openai_compat_integration.py`：6 passed。
- Task 5、Task 6 完成后分别运行 W01 基线：各 25 passed。
- 最终命令 `conda run -n re-uthcode pytest -q tests/test_package.py tests/test_provider_contract.py tests/test_application.py tests/test_architecture_boundaries.py tests/test_anthropic_integration.py tests/test_openai_responses_integration.py tests/test_openai_compat_integration.py`：50 passed。
- `conda run -n re-uthcode python -m pip check`：`No broken requirements found.`
- `conda run -n re-uthcode python -m compileall -q src tests`：通过。
- `rg -n "pydantic_ai\.Agent|pydantic_graph|langgraph|langchain" src tests`：仅命中架构测试中用于断言的禁止字符串，未命中实现代码。
- `git diff --check`：通过；仅有 Git 的 LF/CRLF 提示。
- 最终 Checklist：Task 5、Task 6、Task 7 共 18 项已勾选；Task 8—Task 11 保持未勾选。

## 依赖、安全与遗留

`pyproject.toml` 未新增依赖，环境中 Pydantic AI 为 2.22.0，依赖检查通过。所有协议测试使用注入的 Mock SDK Client/Transport，未访问真实端点，未读取、输出或写入 `DEEPSEEK_API_KEY` 或其他凭据，也未生成缓存或提交产物。

未执行 Git 提交、推送、PR、合并或工作包归档。没有保留旧 Provider API、别名、兼容包装层或不可达协议分支。后续 Task 8—Task 11 仍需按各自 Prompt 实施配置、Factory、正式组合入口、live 验收和界面/Agent Loop 能力。
