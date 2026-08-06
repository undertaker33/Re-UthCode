# W04 Delivery Verification Worker Prompt

## 派发范围

你负责严格串行执行：

1. Task 6：[接入主流程] 收口正式调用链；
2. Task 7：[端到端验证] 验证三协议与全部正式入口；
3. Task 8：[遗留负担清理] 删除临时语义和未来占位。

W04 是交付验证 Worker，只修复当前 T03 范围内的接入和验收缺陷。不得扩展产品能力、改变冻结协议、运行 live Provider、执行 Git 写入或归档工作包。

## 开始前必须读取

- `AGENTS.md`
- `SRe-AGENTS.md`
- `docs/work/README.md`
- T03 原始需求、Spec、Tasks、Checklist。
- W01、W02、W03 Feedback，并确认 Task 1—Task 5 Checklist 已完成。
- T03 涉及的全部 Core、Application、Provider、Interface、README 和测试文件。
- `tests/test_architecture_boundaries.py` 与 `tests/test_package.py`。
- T01、T02、T01-2 中原始需求指定的相关 Feedback，确认既有 Provider、取消、Headless 与 Interface contract。

开始前记录实际 HEAD 和 `git status --short`，运行 W01—W03 定向测试。若发现冻结文件错误、公共协议冲突或必须扩大到 Out of Scope，停止相关范围并写入 Feedback。

## 已确认设计决策

- 正式唯一链路是 `CLI/TUI/Headless → ApplicationRuntimeContext → UthCodeApplication → Core Prompt → GenerationRequest.system_prompt → ProviderPort`。
- Core Prompt、Application 运行上下文、Integration 映射和 Interface 显示的所有权不得混淆。
- Chat 厂商请求中的 `role=system` 是唯一允许的 System Message 映射；Core Message 不能表达 System Prompt。
- 不实现缓存 API、项目指令或任何未来能力占位。
- 不保留兼容 Alias、Facade、Shim、Fallback、双轨请求或被替代旧测试。

## 修改范围

允许修改：

- `tests/test_architecture_boundaries.py`
- `tests/test_package.py`
- `README.md`
- 仅为修复 T03 接入或验收缺陷而窄幅修改 Task 1—Task 5 已列文件及对应测试。
- Checklist 中 Task 6—Task 8 的现有复选框，只能由 `[ ]` 改为 `[x]`。

允许新增：

- `docs/work/T03-SystemPrompt设计/feedback/W04-delivery-verification-feedback.md`

禁止新增业务模块、依赖、缓存、未来能力或新 Feedback 变体文件。不得修改原始需求、Spec、Tasks、Prompt 或 Checklist 文字、编号和顺序。

## 实施约束

- Task 6 先用正式入口和架构测试收口调用链；通过后执行 Task 7 全矩阵；最后执行 Task 8 扫描和清理。
- 测试必须离线可复现；不得使用真实凭据、端点或付费请求。
- 扫描命中必须逐项解释，不能把 Chat 协议合法 system message 误删，也不能放过 Core 旧入口。
- 清理只限 T03 产生或替代的旧语义，不清理历史工作包或无关用户文件。
- 使用 `conda run --no-capture-output -n re-uthcode ...`；治理 Markdown 修改使用 `uth-utf8-guard`。
- 不执行 commit、push、PR、merge、tag、release 或归档。

## 测试与验收

- 严格完成 Checklist 的 Task 6、Task 7、Task 8，记录每条命令精确结果。
- 必须执行：

```powershell
conda run --no-capture-output -n re-uthcode python -m compileall -q src tests
conda run --no-capture-output -n re-uthcode pytest -q tests/test_system_prompt.py tests/test_provider_contract.py
conda run --no-capture-output -n re-uthcode pytest -q tests/test_anthropic_integration.py tests/test_openai_responses_integration.py tests/test_openai_compat_integration.py
conda run --no-capture-output -n re-uthcode pytest -q tests/test_application.py tests/test_application_runtime.py tests/test_cli.py tests/test_tui.py
conda run --no-capture-output -n re-uthcode pytest -q tests/test_architecture_boundaries.py tests/test_package.py
conda run --no-capture-output -n re-uthcode pytest -q
conda run --no-capture-output -n re-uthcode python -m pip check
git diff --check
git status --short
```

- 还必须执行 Checklist Task 8 的全部 `rg` 扫描并逐项审查。

## Feedback 要求

首次执行创建 `docs/work/T03-SystemPrompt设计/feedback/W04-delivery-verification-feedback.md`。至少记录：实际基线和工作区、最终 Prompt/运行上下文结构、请求协议、三协议映射、CLI/TUI/Headless workdir 数据流、模型切换证据、定向与全量测试精确结果、live 测试状态、旧 System Message 与未来占位扫描、与任务书差异、遗留风险和非兼容性清理结果。不得堆砌完整 Prompt 正文或逐行源码；返工仅追加原文件。

