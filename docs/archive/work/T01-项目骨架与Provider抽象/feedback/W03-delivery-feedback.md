# W03 Delivery Worker Feedback

## 当前执行状态

W03 已按 Task 8 → Task 9 → Task 10 的顺序执行到离线验收门槛。Task 8、Task 9 和 Task 10 的离线条目已取得真实证据；Task 10 的三协议 live 验收尚未执行，因此 Task 11 尚未开始，W03 不能宣告完成。

## Task 8：配置与 Provider Factory

- 新增 `src/uthcode/integrations/providers/config.py`，配置只保存 Provider 类型、模型、普通参数和秘密环境变量名称；不包含 API Key 字段。
- 新增 `src/uthcode/integrations/providers/factory.py`，在 Integration 内唯一选择 Fake、Anthropic、OpenAI Responses 和 OpenAI-compatible Provider。真实 Provider 缺失秘密时只报告环境变量名称；OpenAI-compatible 要求显式 `base_url`；构造不发起请求。
- Factory 的 Fake 构造返回一个确定性的完成事件，使正式组合入口可以完成无网络 Headless smoke；每次构造都创建独立 Provider 状态。
- `.env.example` 只保留 `DEEPSEEK_API_KEY=`，与 W03 的秘密来源约束一致。

验证：`conda run -n re-uthcode pytest -q tests/test_provider_factory.py` 为 `11 passed`；测试拦截构造期间网络并记录 0 次请求，覆盖秘密安全、配置/异常/repr、base URL、Fake 无秘密和实例隔离。`Test-Path src/uthcode/config.py` 为 `False`，Provider 配置路径存在于 `src/uthcode/integrations/providers/config.py`。

## Task 9：正式 Headless 入口

- 新增 `src/uthcode/application/bootstrap.py`，`create_application()` 是 Application 内唯一公开组合入口，并在组合根内调用 Integration Factory。
- `generation.py` 继续只依赖 Core Provider Port；Application 包公开 `UthCodeApplication`、`create_application`、`ProviderConfig` 和 `ProviderKind`，不公开 SDK 类型；Provider Integration 包没有第二个公开组合入口。
- README 增加 Fake Headless 示例和真实 Provider 构造说明；示例已在 `re-uthcode` 环境通过 stdin 直接执行，未使用 CLI、stdin 交互或 UI。

验证：`conda run -n re-uthcode pytest -q tests/test_application.py tests/test_provider_factory.py` 为 `20 passed`；正式配置入口完成 Fake 请求并观察到唯一 `GenerationCompleted`。Application/Core 中 Provider 名称搜索为 0 条；阶段性模型直构只存在于物理 Integration 模块和 Factory。

## Task 10：离线验收

- `conda run --no-capture-output -n re-uthcode pytest -q`：`63 passed, 3 skipped`。
- `conda run -n re-uthcode python -m compileall -q src tests`：通过。
- `conda run -n re-uthcode python -m pip check`：`No broken requirements found.`。
- `conda run --no-capture-output -n re-uthcode pytest -q -m live`（未设置 live 标记变量和 Key）：`3 skipped, 63 deselected`，未发起网络请求。
- 将默认网络守卫限制于非 live 测试，并注册 `live` marker；三个 live 用例均通过正式 Headless 组合入口，模型 ID 固定为 `deepseek-v4-flash`，每个协议包含首轮工具调用和工具结果续轮。

## Checklist 状态

- Task 8：8/8 已勾选。
- Task 9：7/7 已勾选。
- Task 10：3/9 已勾选；三协议 live、输出/Key 清理和失败记录条目未勾选。
- Task 11：0/9，因 Task 10 的 live 门槛未完成而未开始。

## 未完成项与用户决策

live 验收预计执行 6 次请求：Anthropic、Responses、Chat Completions 各 2 次（首轮文本/推理/Tool Call，第二轮 Tool Result 续轮）。这些请求会访问真实服务并可能产生费用。需要用户明确确认网络请求与费用影响，并在当前 PowerShell 会话自行设置 `$env:DEEPSEEK_API_KEY = '<用户自行填写>'` 后，才能执行 `pytest -q -m live`。测试进程会在结束时移除该变量；不会读取、写入或回显真实 Key。

在获得确认前不运行 live、不勾选对应条目、不进入 Task 11，也不执行 Git 提交、推送、PR、合并或工作包归档。

## 文档与安全检查

- `uth-utf8-guard` 已对本 Feedback、README 和 Checklist 执行写前/写后检查，均通过 UTF-8、mojibake 和 Markdown fence 校验。
- 当前输出、异常、配置 repr、测试报告和新增文档未写入真实秘密；工作包未自动归档。

## 继续执行：live 验收与局部修复

用户已明确确认真实请求和费用影响，并确认 `DEEPSEEK_API_KEY` 已配置。执行期间没有把 Key 写入文件、命令参数或输出。

首次 live 集合中 Anthropic 通过；Chat 和 Responses 在构造阶段因测试用例逐项清理同一 pytest 进程的环境变量而错误地看到缺失 Key。修复为每项测试恢复环境、会话结束统一清理后，第二次运行中 Anthropic 与 Chat 通过；Responses 暴露了真实端点返回可空缓存 token 字段的兼容缺陷。先新增离线回归测试确认红灯，再将 `None` 规范化为 0，并通过离线测试。

第三次 live 集合最终结果：`3 passed, 64 deselected`。Anthropic、OpenAI Responses 和 Chat Completions 均从正式 Headless 入口完成两轮调用；分别观察到文本、推理语义、Tool Call、对应 Tool Result 续轮和成功终态。Responses 端点未提供可见的 reasoning delta，但提供了可验证的 reasoning 响应语义（统一 `ReasoningPart` 或 Responses reasoning Native Item），因此测试按协议桥接后的 Core 语义验收。

为透明记录网络影响：最终成功运行包含 6 次请求；此前两次修复性运行还产生了 Anthropic 的首轮/续轮、Chat 的首轮/续轮，以及一次 Responses 首轮请求，实际 live 尝试总量约为 13 次。所有失败均为本地测试清理或响应映射断言问题，没有 HTTP、认证或网络失败；没有通过删减协议断言伪造通过。

新增 Responses 可空缓存用量回归覆盖，且 `tests/conftest.py` 现在在测试间恢复环境、在 pytest 会话结束时移除 Key 和 live 标记。对应代码修改后 `tests/test_openai_responses_integration.py` 为 `10 passed, 1 skipped`，最终 live 集合全通过。

## Task 11：遗留负担清理与最终复核

- 架构边界测试最终为 `15 passed`。新增静态断言覆盖旧图框架/旧项目名称、`interfaces/` 缺失、三协议字段物理隔离、共享桥接层无 Provider 名称分支，以及 Factory 的唯一正式组合出口。
- `rg -ni "langgraph|langchain|StateGraph|GraphState|Checkpoint|mewcode" pyproject.toml src tests` 的命中仅为架构测试自身的禁止字符串断言；运行时源码没有这些依赖或导入。
- `rg --files src/uthcode` 只包含当前的 `core`、`application`、`integrations` 及其实际实现，没有 `interfaces/`、Prompt、Tool、Permission、Context、Memory、Session、Storage、Journal、Sandbox、Command、Hook、Skill、MCP、Agent 或 Worktree 占位模块。旧入口/兼容层搜索没有命中。
- 三个协议模块的特有字段只在对应物理模块出现，共用 `pydantic_ai.py` 没有 Anthropic、Responses、Chat 协议名称或字段分支。`factory.py` 是唯一 `create_provider` 定义与公开构造出口；Application 只通过 `bootstrap.py` 组合。
- `pip list --not-required --format=freeze` 已结合 `pyproject.toml` 审查：项目直接依赖为 `pydantic-ai-slim[anthropic,openai]`，开发依赖为 pytest 与 pytest-asyncio；`pydantic-graph` 等为允许的传递依赖，未发现应删除的额外项目依赖。`pip check` 输出 `No broken requirements found.`。
- 最终离线回归：`conda run --no-capture-output -n re-uthcode pytest -q` 为 `68 passed, 3 skipped`；`compileall -q src tests` 通过。此前授权的最终 live gate 为 `3 passed, 64 deselected`，三协议各完成两轮真实调用；最终成功运行 6 次请求，连同前两次修复性尝试实际约 13 次请求，未发生 HTTP、认证或网络失败。
- `git diff --check` 无空白错误。秘密扫描未发现真实 API Key 写入文件；输出中的 Key 形态仅为占位符、环境变量名和合成测试 sentinel。测试生成的 `.pytest_cache` 与 `__pycache__` 已在最终审计后清理。

## W03 完成状态

Task 8（8/8）、Task 9（7/7）、Task 10（9/9）和 Task 11（9/9）均已完成。`uth-utf8-guard` 对 README、Checklist 和本 Feedback 的写前/写后检查均通过。未执行 Git 提交、推送、PR、合并或工作包归档。

## 记录校正

Checklist 的 Task 11 实际包含 10 个条目，当前状态为 10/10 已勾选；上段的 “9/9” 是反馈计数笔误，不影响任何验收条目或实现结果。

## 验收复测：修复离线网络守卫顺序依赖

验收复现命令 `python -m pytest -q tests/test_provider_factory.py tests/test_application.py` 首次结果为 `13 passed, 7 errors`。根因是全局 `pytest_runtest_call` 守卫与 Factory 测试 fixture 都修改 `socket.socket.connect`：调用阶段结束时全局守卫先恢复原函数，随后 fixture teardown 又恢复了已经失效的全局阻断函数，导致后续 pytest-asyncio 创建本地事件循环时被误判为外网访问。

修复方式是将 `tests/test_provider_factory.py` 中 Factory 构造期间的三个 socket patch 放入测试函数内部的 `monkeypatch.context()`，使局部 patch 在全局守卫退出前恢复，不再跨测试泄漏。

修复后反序回归命令结果为 `20 passed`；标准全量离线回归为 `68 passed, 3 skipped`。本次未运行 live 测试、未产生新的付费请求；`pip check`、`compileall` 和 `git diff --check` 均通过。W03 的这次验收阻断已修复，工作区仍未执行 Git 提交、推送、PR 或合并。
