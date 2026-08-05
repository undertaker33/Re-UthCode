# W02 Provider Mapping Worker Prompt

## 派发范围

你只负责 Task 3：重写三种 Provider 的 System Prompt 映射。不得开始 Task 4—Task 8，不得修改 Core 公共协议、Application、Interface、README、Factory、配置或 Git 状态。

## 开始前必须读取

- `AGENTS.md`
- `SRe-AGENTS.md`
- `docs/work/README.md`
- T03 原始需求、Spec、Tasks、Checklist。
- W01 Feedback，并确认 Task 1、Task 2 Checklist 已完成。
- 三个 Provider 实现及对应测试。
- `src/uthcode/core/provider.py`
- T01-2 原始任务、Tasks、Checklist 和两个 Feedback。

开始编码前确认 W01 改动存在且定向测试通过；检查 `git status --short` 并保留既有修改。若 Core 协议与冻结方案不一致，停止并写入 Feedback。

## 已确认设计决策

- Anthropic 使用顶层 `system`，Responses 使用顶层 `instructions`，OpenAI-compatible Chat 在消息首位生成唯一 `role=system`。
- 无 Prompt 时不发送对应字段或消息。
- Integration 不再从 Core 历史中扫描、提取或透传 System Message。
- Chat 不使用 developer role；不启用 Prompt Cache。
- Provider Response/Event、Reasoning、Native Item、Tool、Usage、错误、取消和资源关闭语义保持不变。

## 修改范围

允许修改：

- `src/uthcode/integrations/providers/anthropic.py`
- `src/uthcode/integrations/providers/openai_responses.py`
- `src/uthcode/integrations/providers/openai_compat.py`
- `tests/test_anthropic_integration.py`
- `tests/test_openai_responses_integration.py`
- `tests/test_openai_compat_integration.py`
- Checklist 中 Task 3 的现有复选框，只能由 `[ ]` 改为 `[x]`。

允许新增：

- `docs/work/T03-SystemPrompt设计/feedback/W02-provider-mapping-feedback.md`

禁止修改 Factory、配置、SDK 版本、Core、Application、Interface 及其他文件。

## 实施约束

- 先让映射测试表达新协议并失败，再做最小实现；三个 Provider 均完成后统一回归。
- 只改变请求侧 Prompt 来源和厂商落点，不重构无关流事件或 Codec。
- 保留既有历史顺序、Native Item 身份、工具往返和关闭路径。
- 不添加兼容逻辑、重复序列化层或 Provider 名称分支到上层。
- 不执行 live Provider、真实网络、Git 写入或归档。
- 修改治理 Markdown 时使用 `uth-utf8-guard`。

## 测试与验收

- 严格完成 Checklist 的 Task 3。
- 至少执行：

```powershell
conda run --no-capture-output -n re-uthcode pytest -q tests/test_anthropic_integration.py tests/test_openai_responses_integration.py tests/test_openai_compat_integration.py
conda run --no-capture-output -n re-uthcode pytest -q tests/test_provider_contract.py
conda run --no-capture-output -n re-uthcode python -m compileall -q src/uthcode/integrations/providers tests/test_anthropic_integration.py tests/test_openai_responses_integration.py tests/test_openai_compat_integration.py
git diff --check
```

- 对 `role=system` 搜索结果逐项确认：Core 输入为 0，Chat 厂商映射及其协议测试可保留。

## Feedback 要求

首次执行创建 `docs/work/T03-SystemPrompt设计/feedback/W02-provider-mapping-feedback.md`。记录三协议实际请求形状、有/无 Prompt 行为、未变的 Reasoning/Tool/Usage/错误/取消证据、修改文件、精确测试结果、Checklist 状态、差异和风险。返工仅追加原文件。

