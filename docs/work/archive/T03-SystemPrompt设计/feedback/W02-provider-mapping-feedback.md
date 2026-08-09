# W02 Provider Mapping Worker Feedback

## 执行范围与基线

本轮由用户明确派发 `prompt/W02-provider-mapping-prompt.md`，只执行 T03 Task 3。开始前已读取项目约束、T03 原始需求/Spec/Tasks/Checklist、W01 Feedback、T01-2 原始任务/Tasks/Checklist 及两个 Feedback，并确认：

- `HEAD` 为 `047bd155c3980584f6b38da6e20fa62241cf7498`，与 T03 固定基线一致；
- W01 的 Core Prompt Contract 改动已存在，`test_system_prompt.py` 为 `9 passed`，`test_provider_contract.py` 在本轮验证为 `21 passed`；
- 开始时工作区已有 W01 未提交改动，本轮保留这些改动；没有执行 Git 写入、归档或真实 Provider 请求。

## 实际完成内容

三个 Integration 现在只读取 `GenerationRequest.system_prompt`，普通 `request.messages` 只按 Core 已冻结的 `user`、`assistant`、`tool` 角色映射，不再扫描、提取或透传 Core System Message。

### Anthropic Messages

- 有 Prompt 时写入请求顶层 `system`；没有 Prompt 时完全省略该参数。
- 普通历史继续写入 `messages`，其中没有 `role=system`；assistant 原生 Thinking、Redacted Thinking、Tool Use 和 Tool Result 映射未改动。

### OpenAI Responses

- 有 Prompt 时写入请求顶层 `instructions`；没有 Prompt 时完全省略该参数。
- `input` 只包含已有 user、assistant、tool/function-call 项，不生成 System Item；Reasoning、Native Item、Function Call、Tool Result 和终态处理未改动。

### OpenAI-compatible Chat

- 有 Prompt 时在厂商消息列表首位生成唯一 `{"role": "system", "content": ...}`；没有 Prompt 时不生成该消息。
- 后续 user、assistant、tool 历史顺序保持不变，不使用 `developer` role；Reasoning carrier、Indexed Tool Call 和 Tool Result 处理未改动。

## 修改文件

- `src/uthcode/integrations/providers/anthropic.py`
- `src/uthcode/integrations/providers/openai_responses.py`
- `src/uthcode/integrations/providers/openai_compat.py`
- `tests/test_anthropic_integration.py`
- `tests/test_openai_responses_integration.py`
- `tests/test_openai_compat_integration.py`
- `docs/work/T03-SystemPrompt设计/T03-SystemPrompt设计-checklist.md`：仅将 Task 3 的 5 个既有复选框由 `[ ]` 改为 `[x]`
- `docs/work/T03-SystemPrompt设计/feedback/W02-provider-mapping-feedback.md`

未修改 Core 公共协议、Application、Interface、Factory、配置、SDK 版本、README、T03 原始需求/Spec/Tasks/Prompt 文字或 Git 内容；Checklist 只勾选 Task 3 的既有复选框。没有新增兼容层、缓存、developer 双轨入口或 Provider 名称分支。

## 验证结果

先把测试改为独立 `system_prompt` 协议后，旧实现得到 `3 failed, 35 passed, 3 skipped`；完成最小映射后重新验证：

- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_anthropic_integration.py`：`16 passed, 1 skipped`；
- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_openai_responses_integration.py`：`11 passed, 1 skipped`；
- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_openai_compat_integration.py`：`11 passed, 1 skipped`；
- 三个 Provider 合并命令：`38 passed, 3 skipped`；
- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_provider_contract.py`：`21 passed`；
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src/uthcode/integrations/providers tests/test_anthropic_integration.py tests/test_openai_responses_integration.py tests/test_openai_compat_integration.py`：退出码 0；
- `git diff --check`：通过。仅有 Windows 工作副本的 LF/CRLF 转换提示，没有空白错误。

既有协议测试继续覆盖 Tool Result、Reasoning/Native Item、Usage、官方错误分类、显式取消、Task 取消和 Stream 关闭；本轮未改变这些响应侧与流侧语义。`role=system` 扫描结果中 Core Message 构造为 0，唯一业务残留是 Chat Integration 的厂商映射及其协议测试断言。

真实 Provider/live 测试未运行；三个 live 用例均因 `UTHCODE_RUN_LIVE` 未设置而按既有门禁跳过。未执行全量测试、Git commit/push/PR 或工作包归档。

## Checklist、差异与遗留负担

T03 Checklist 的 Task 3 五项均已取得上述证据并勾选；Task 4—Task 8 保持未勾选，未越界实施。

与任务书无实质差异。实现采用请求字段直接落到三个公开协议位置，删除了三个 Provider 中旧的历史 System Message 扫描分支；没有保留适配器、别名、Facade、Shim、Fallback、重复序列化层、Prompt Cache 或其他兼容负担。没有需要用户决定的问题。

UTF-8 guard：

- files checked：`docs/work/T03-SystemPrompt设计/T03-SystemPrompt设计-checklist.md`、`docs/work/T03-SystemPrompt设计/feedback/W02-provider-mapping-feedback.md`
- result：通过 UTF-8 解码、乱码标记和 Markdown fence 检查
- repaired encoding issues：无
