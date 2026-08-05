# W01 Native SDK Provider Worker Feedback

## 执行范围与基线

本轮由用户明确派发 `prompt/W01-native-sdk-provider-prompt.md`，严格执行 W01 的 Task 1—Task 3；不执行 Task 4—Task 6，不卸载 Conda 环境中的发行包，不执行 Git 写入或工作包归档。

- 任务书基线提交：`2d78b4300a236ada53ac104e547a30df380953ca`。
- 实际开始提交：`8c3bc70c2571c82b0be28db74fae6393b0dc064f`。
- 差异说明：实际提交仅在任务书基线之上新增 T01-2 工作包文件；开始前工作区干净，未发现无法解释的源码前置改动。
- 开始前全量测试：`201 passed, 3 skipped`。
- 当前 SDK 版本：OpenAI `2.53.0`，Anthropic `0.120.2`；均落在 W01 要求范围内。

## 初始状态

当前真实 Provider 仍通过 `pydantic_ai.py` 的 Pydantic AI Direct Bridge、Codec 和 Recorder 运行。本轮将按 Task 1 → Task 2 → Task 3 顺序替换；Task 1 完成并验证后才进入 Task 2，Task 2 完成并验证后才进入 Task 3。

本文件后续只追加实际修改、精确测试结果、Checklist 状态、偏差与遗留负担清理记录，不修改冻结的原始需求、Spec、Tasks、Prompt 或 Checklist 文字与顺序。

## Task 1：建立原生 SDK 共用辅助边界

### 实际完成

- 新增 `src/uthcode/integrations/providers/common.py`，只包含 JSON-safe 深度转换、JSON Object 校验、严格 Usage 整数读取、公开 `aclose`/`close` 关闭和 Core 取消检查。
- JSON 转换只使用 Mapping/Sequence、官方公开 `model_dump`/`to_dict` 等序列化入口，不读取第三方私有字段；错误诊断只包含安全类型或标签，不复制对象内容。
- 新增 `tests/test_provider_sdk_common.py`，覆盖嵌套 JSON、官方 SDK 可公开序列化对象、非法值/键、bool/负数/浮点/字符串 token、四类关闭 Double、关闭异常和 CancellationToken。

### 验证

- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_provider_sdk_common.py`：`13 passed`。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src/uthcode/integrations/providers/common.py tests/test_provider_sdk_common.py`：通过。
- `rg` 检查 `common.py` 中厂商名、第二 Provider 抽象和 ProviderKind：0 条（rg 退出码 1 表示无匹配）。
- 禁止文件名扫描：0 条（rg 退出码 1 表示无匹配）。
- Task 1 范围外的 Core、Application、三个真实 Provider、Factory 和 `pyproject.toml`：无 diff。

### Checklist

Task 1 的 9 条验收项已取得真实证据，待 Task 2/3 完成后统一更新冻结 Checklist 中允许勾选的现有复选框；未修改 Checklist 文字、编号或顺序。

## Task 2：替换三个真实 Provider Integration

### 实际修改

- `src/uthcode/integrations/providers/anthropic.py` 已改为直接调用注入的官方 `AsyncAnthropic.messages.create(..., stream=True)`。请求侧保留 system、user、assistant 标准 Part、同 Identity 的 thinking/signature/redacted thinking/tool use Native Item 和 tool result；流侧按 content block index 聚合文本、thinking、redacted thinking 与 tool JSON，发布 Core Delta、Tool Call、Native Item 和唯一 GenerationCompleted，并保存 Stop Reason、input/output/cache Usage。
- `src/uthcode/integrations/providers/openai_responses.py` 已改为直接调用注入的官方 `AsyncOpenAI.responses.create(..., stream=True)`。状态按 item id、output index、call id 和公开 sequence number 关联；保留 reasoning summary/encrypted content、message、function call、Function Call Output、顺序和 Usage，重复帧去重，内容/Identity 冲突、未完成调用、error、incomplete、failed 和 EOF 拒绝成功终态。
- `src/uthcode/integrations/providers/openai_compat.py` 已改为直接调用注入的官方 `AsyncOpenAI.chat.completions.create(..., stream=True)`。请求保持 Chat system/user/assistant/tool、assistant.tool_calls、tool_call_id 和 `stream_options.include_usage`；流侧按 tool index 独立聚合 ID、名称、参数，保留 reasoning_content、正文、Nullable Usage Details 和 Finish Reason。
- `src/uthcode/integrations/providers/factory.py` 已删除旧 settings 转换，唯一 Factory 直接把官方 Client 参数和 `max_output_tokens` 传给三个 Builder；`FakeProvider`、ProviderConfig、Core/Application、CLI、TUI 未修改。
- `pyproject.toml` 已将直接依赖替换为 `anthropic>=0.117,<1` 与 `openai>=2.46,<3`，未新增直接 `httpx`，未执行环境发行包卸载。
- 删除 `src/uthcode/integrations/providers/pydantic_ai.py`；重写三个协议测试、架构边界测试和包测试，测试只使用官方 SDK 事件类型或公开 Client Test Double。

### 验证

- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests`：通过；单独 `compileall -q src`：通过。
- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_provider_factory.py tests/test_provider_contract.py tests/test_application.py tests/test_application_runtime.py tests/test_configuration.py tests/test_cli.py tests/test_tui.py`：`90 passed`。
- 三个 Builder 的官方 Client 构造与 Factory 网络拦截均为 0 次；Factory 传递的最大输出 token 实测为 Anthropic `17`、Responses `19`、Chat `23`，Identity 分别为 `anthropic/messages`、`openai/responses`、`openai/chat_completions`。
- 三个 Provider 的正常、官方 Authentication、Permission、Rate Limit、Connection、Timeout、500 Status Error、显式 Core 取消和 Task 取消路径均有离线验证；流均关闭，显式取消为 `GenerationCancelled`，Task 取消原样传播，错误文本不复制 SDK 异常内容。
- 定向扫描：无 `pydantic_ai`/Pydantic AI/Bridge/Codec/Recorder 源码引用、无 `provider_details`、无 `record_model_stream`、无 `._response` 或 `_source_iter` 私有字段访问；`openai_responses` 模块名和 Builder 名称中的合法 `_response` 子串是宽松正则扫描的唯一结果，不是第三方私有字段。
- `conda run --no-capture-output -n re-uthcode python -m pip check`：`No broken requirements found.`（仅检查，未安装/卸载）。

## Task 3：重写协议测试并保持行为等价

### 实际完成

- Anthropic 黑盒测试覆盖公开 Raw Event 的 thinking/signature、redacted thinking、text、tool use、Tool Result 下一轮请求、Content Block 顺序、Usage/Stop Reason、缺失终态、空 Stop Reason、非法 JSON/Signature/Redacted Data、官方异常、显式取消、Task 取消和关闭。
- Responses 黑盒测试覆盖公开 Responses Event 的 Reasoning、A/B 交错 Function Call、Message、Function Call Output 下一轮请求、Item/Call/Output Index/顺序、重复 Delta/Done/Terminal 去重、冲突、未完成调用、error、incomplete、failed、EOF、Nullable cache Usage、官方异常、两类取消和关闭。
- Chat 黑盒测试覆盖官方 `ChatCompletionChunk` 的 reasoning_content、正文、两个 Indexed Tool Call、system/user/assistant/tool 往返、Nullable Usage、缺少 Finish Reason、缺少 ID/名称、非法 JSON、Identity 冲突、官方异常、两类取消和关闭。
- 三个 Provider 均增加 `UTHCODE_RUN_LIVE=1` 门禁测试；当前环境变量未设置，live 未运行且默认 skipped。

### 精确结果

- `pytest -q tests/test_provider_sdk_common.py`：`13 passed`。
- `pytest -q tests/test_anthropic_integration.py`：`10 passed, 1 skipped`。
- `pytest -q tests/test_openai_responses_integration.py`：`9 passed, 1 skipped`。
- `pytest -q tests/test_openai_compat_integration.py`：`8 passed, 1 skipped`。
- `pytest -q tests/test_provider_factory.py`：`12 passed`。
- 最终全量 `conda run --no-capture-output -n re-uthcode pytest -q`：`212 passed, 3 skipped`。
- `git diff --check`：通过；仅有 Windows CRLF/LF 提示，无空白错误。

## Checklist 与边界

- T01-2 Checklist 中 Task 1、Task 2、Task 3 的现有复选框已逐项改为 `[x]`；只修改了复选框状态，未改编号、文字或顺序。
- Task 4、Task 5、Task 6 保持全部 `[ ]`，未执行主流程收敛、端到端/live 运行、Pydantic AI Conda 卸载或环境重装。
- 未修改 Core Provider 契约、Application API、配置模型、Fake Provider、CLI、TUI；未建立兼容 Alias、Shim、Adapter、双轨 Provider 或第二构造根。
- 未执行 Git 写入、提交、推送、分支操作或工作包归档；当前工作区改动均为本 W01 代码、测试、Checklist 复选框和本 Feedback 文件。
- 初始基线与实际提交差异已在本 Feedback 开头记录；开始前的 `201 passed, 3 skipped` 与最终 `212 passed, 3 skipped` 的差异来自原生 Provider/测试重写及 live 门禁保留。

## W01 第一次返工

### 返工原因与范围

- 原 W01 验收发现 Anthropic 合法 `ping` 事件被当作未知事件拒绝；本次仅补充该已知事件的安全忽略路径，其他未知或非法事件仍保持原有 `InvalidProviderResponseError` 验证边界。
- 原 W01 验收发现 OpenAI-compatible Chat Tool Call 的参数可能先于身份到达，旧路径会使用 `index-N` 发布参数增量。本次仅修复 Tool Call 状态聚合、延迟发布和对应离线黑盒测试。
- 返工开始时先撤回受影响的 W01 Checklist 项：Anthropic/Chat 流行为、三个 Provider 关闭路径、Anthropic 与 Chat 定向测试命令、Anthropic/Chat 黑盒及非法输入验收项；修复和验证完成后已重新勾选这些既有项目。未改 Checklist 文字、编号、顺序或冻结需求文档。

### 实际改动

- `src/uthcode/integrations/providers/anthropic.py` 在已识别的事件分支中增加 `ping` 安全忽略；未知事件仍落入原有拒绝分支。
- `tests/test_anthropic_integration.py` 增加一个和多个交错 `ping` 的黑盒回归，并增加未知事件仍被拒绝的边界测试。
- `src/uthcode/integrations/providers/openai_compat.py` 为每个 Indexed Tool Call 缓存参数增量；在真实 ID 和名称完整并完成流校验后，按 `ToolCallStarted → ToolCallArgumentsDelta（全部缓存增量）→ ToolCallCompleted` 发布，三类事件均使用同一个真实 `tool_call_id`，不再生成或发布 `index-N`。
- `tests/test_openai_compat_integration.py` 增加两个交错 Indexed Tool Call 的参数先到、ID 后到、名称后到回归，逐项断言事件顺序、真实 ID、名称、参数增量和最终参数。

### 精确验证结果

- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests`：退出码 0。
- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_provider_sdk_common.py`：`13 passed`。
- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_anthropic_integration.py`：`14 passed, 1 skipped`；含一个/多个交错 `ping` 及未知事件拒绝回归。
- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_openai_responses_integration.py`：`10 passed, 1 skipped`。
- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_openai_compat_integration.py`：`11 passed, 1 skipped`；延迟身份回归中无 `index-N`，每个真实调用的 Started、全部 Arguments Delta 和 Completed ID 一致。
- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_provider_factory.py`：`12 passed`。
- `conda run --no-capture-output -n re-uthcode python -m pip check`：`No broken requirements found.`
- `rg -n "pydantic_ai|PydanticAIProvider|PydanticAICodec|FunctionModel|pydantic_graph" src tests pyproject.toml README.md`：仅命中按范围恢复的 `tests/test_architecture_boundaries.py` 和 `tests/test_package.py`；未新增 W01 Provider/协议测试引用。
- `rg -n "\._response\b|_source_iter|record_model_stream|provider_details" src/uthcode/integrations/providers`：0 条匹配。
- `conda run --no-capture-output -n re-uthcode pytest -q`：未通过收集阶段；唯一错误为恢复后的 `tests/test_architecture_boundaries.py` 导入已按 W01 Task 2 删除的 `uthcode.integrations.providers.pydantic_ai`，`ModuleNotFoundError`，`1 error during collection`。该结果是 W01 删除旧桥接与恢复 W02 Task 4 文件之间的范围冲突，不通过新增兼容层或修改 W02 文件处理。

### Checklist 状态与范围偏差处理

- 受影响的 W01 Checklist 项已在返工开始时撤回为 `[ ]`，取得上述定向真实证据后恢复为 `[x]`；Task 4、Task 5、Task 6 仍全部为 `[ ]`，未执行任何 W02 内容。
- 原 Checklist 第 46 项“默认环境全部通过”因全量收集被恢复的 W02 Task 4 测试阻断，保持 `[ ]`，未以定向测试结果替代全量证据。
- `tests/test_architecture_boundaries.py` 和 `tests/test_package.py` 已使用明确的只读 HEAD 内容恢复到 W01 开始前状态；`git diff --exit-code -- tests/test_architecture_boundaries.py tests/test_package.py` 无差异。未修改、删除或重写这两个 W02 Task 4 文件以迁就全量测试，也未恢复已删除的 Pydantic AI Bridge。
- 未修改冻结需求、Spec、Tasks、Prompt 或 Checklist 文字；本节为既有 Feedback 末尾追加，未覆盖既有事实。
- `UTHCODE_RUN_LIVE` 未授权，live 用例保持 skipped；未卸载 Conda 发行包；未执行 Git commit、push、PR、合并、分支写入或工作包归档。
