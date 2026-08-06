# W04 Delivery Verification Worker Feedback

## 1. 执行范围与基线

本轮由用户明确派发 `prompt/W04-delivery-verification-prompt.md`，严格按 Task 6 → Task 7 → Task 8 执行。未修改原始需求、Spec、Tasks、Prompt 的文字、编号或顺序；未执行 Git 写入、真实 Provider 请求或工作包归档。

- 实际 `HEAD`：`047bd155c3980584f6b38da6e20fa62241cf7498`，与 T03 固定基线一致。
- 开始时工作区已有 W01—W03 的 T03 实现、测试、README 和工作包未提交修改；没有发现范围外文件。
- W01—W03 定向基线：Core/Provider `30 passed`；三协议 `38 passed, 3 skipped`；Application/CLI/TUI `57 passed`。
- 架构与包基线：`11 passed`。

W04 实际业务代码没有新增能力。Task 8 扫描发现 `tests/test_system_prompt.py` 的禁词自检本身包含旧品牌字面量；已将该测试项改为运行时拼接，保持原断言语义并使仓库扫描结果为零。另新建本 Feedback，并只把 Checklist Task 6—Task 8 的既有复选框改为 `[x]`。

## 2. Task 6：正式调用链与架构边界

最终确认的唯一数据流为：

```text
CLI/TUI/Embedded Headless
→ ApplicationRuntimeContext
→ UthCodeApplication.start_generation()
→ Core SystemPromptContext/build_system_prompt()
→ GenerationRequest.system_prompt
→ ProviderPort
```

实际结构如下：

- `SystemPromptContext` 仅包含 workdir、平台名/版本、日期、model ref、Provider protocol 和远端 model ID；Core Prompt 使用固定五个 Section，静态内容位于运行环境段之前。
- `ApplicationRuntimeContext` 独立于 `EffectiveConfig`，在 Application 创建时规范化 workdir 并固定平台和日期；每个 `start_generation()` 根据当前 ProviderIdentity 构建一次 Prompt，并用不可变请求副本注入。
- `GenerationRequest.system_prompt` 是唯一 Core System Prompt 字段；普通 `Message` 只接受 `user`、`assistant`、`tool`。
- Anthropic 使用请求顶层 `system`；OpenAI Responses 使用顶层 `instructions`；OpenAI-compatible Chat 仅在厂商消息首位生成一个 `role=system`。Core Message 不再表达 System Prompt。
- CLI 的同一个规范化 workdir 同时进入配置发现和 RuntimeContext；TUI 从 Application RuntimeContext 读取 Topbar 和生成事实；Headless 不依赖 Interface。

架构证据：

- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_architecture_boundaries.py tests/test_package.py`：`11 passed`。
- Embedded Headless 正式 Bootstrap + Fake：`pytest ... tests/test_application.py -k formal_bootstrap_builds_a_fake_headless_application`：`1 passed, 10 deselected`。
- CLI 正式入口 + Fake：`pytest ... tests/test_cli.py -k 'exec_uses_one_normalized_workdir_for_config_and_prompt or formal_module_exec_uses_fake_config_without_tui_or_network'`：`2 passed, 12 deselected`。
- TUI 正式 Bootstrap + Fake：`pytest ... tests/test_tui.py -k formal_fake_tui_flow_covers_commands_isolation_and_cancel`：`1 passed, 16 deselected`。
- Headless 子进程、根包无 SDK/Provider Client 副作用、接口依赖和 AST 边界均包含在架构/包测试中并通过。

## 3. Task 7：端到端与全量验证

按 Prompt 要求执行的精确结果：

| 命令 | 结果 |
| --- | --- |
| `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests` | 退出码 0 |
| `conda run --no-capture-output -n re-uthcode pytest -q tests/test_system_prompt.py tests/test_provider_contract.py` | `30 passed` |
| `conda run --no-capture-output -n re-uthcode pytest -q tests/test_anthropic_integration.py tests/test_openai_responses_integration.py tests/test_openai_compat_integration.py` | `38 passed, 3 skipped` |
| `conda run --no-capture-output -n re-uthcode pytest -q tests/test_application.py tests/test_application_runtime.py tests/test_cli.py tests/test_tui.py` | `57 passed` |
| `conda run --no-capture-output -n re-uthcode pytest -q tests/test_architecture_boundaries.py tests/test_package.py` | `11 passed` |
| `conda run --no-capture-output -n re-uthcode pytest -q` | `252 passed, 3 skipped` |
| `conda run --no-capture-output -n re-uthcode python -m pip check` | `No broken requirements found.` |
| `git diff --check` | 退出码 0；仅有既存 LF/CRLF 转换提示 |

离线端到端证据覆盖：

- Headless Fake 记录 Application 生成的完整 Prompt，原始请求保持不变。
- `uthcode exec` 的位置参数、stdin、默认 cwd 和显式 `--cwd` 均沿用正式 Application 组合；配置发现目录与 Prompt workdir 相同。
- Textual TUI 的 Topbar、Fake 请求、模型 Picker、流式渲染、双 Esc 取消和退出清理均通过；模型切换后第二个 Provider 请求包含新的 model ref、协议和远端模型 ID。
- 三个协议 Mock 均验证了有/无 Prompt、历史和工具映射，以及 Reasoning/Native Item、Usage、错误、取消和流关闭回归。
- live Provider 测试未运行；3 个 live 用例按既有 `UTHCODE_RUN_LIVE` 门禁显式跳过。

## 4. Task 8：遗留扫描与逐项结论

- `Message(...)` 或赋值形式的 Core `system` 角色扫描：0 条。生产代码唯一合法的厂商 System Message 为 `src/uthcode/integrations/providers/openai_compat.py:184`；对应协议测试只验证该 Chat 映射，Anthropic/Responses 测试验证历史中没有 system 消息。
- 未来字段扫描 `custom_instructions`、`hook_prompts`、`memory_section`、`skill_section`、`agent_catalog`、`deferred_tool`、`plan_mode`：0 条。
- 旧品牌与推广文本扫描：0 条。
- `prompt_(manager|registry|loader|cache)`、`prompts/`、`plan.py` 文件扫描：0 条。
- `src/uthcode/interfaces` 中的 `system_prompt` 扫描：0 条；Interface 不持有 Prompt 正文或覆盖入口。
- `configuration.py` 与 Integration config 中的 `workdir`、平台和日期字段扫描：0 条；运行事实没有进入配置模型。
- 兼容性审查未发现 Alias、Facade、Shim、Fallback、双轨请求、不可达分支或仅为早期实现保留的重复职责。Responses 的 `instructions` 是其正式公开协议字段，Core 的 `TypeAlias` 和命令系统的普通 alias 不是 Prompt 兼容入口。

Task 8 扫描命令均无匹配（PowerShell 中 `rg` 的无匹配退出码为 1，命令本身成功完成），并已重新执行 compileall 和全量 pytest。最终 `git status --short` 仍只包含 T03 工作包、W01—W03 已批准实现/测试、README，以及本轮允许的 Checklist、测试自检和 W04 Feedback；没有执行删除历史工作包或未知用户文件。

## 5. 与任务书的差异、风险和收口

- 与 T03 冻结任务书无实质差异；W04 没有扩大产品能力、修改公共协议或引入新依赖。
- 任务书要求的架构测试、三入口 Fake 验证、三协议映射、离线全量测试、依赖检查和遗留扫描均已取得证据。
- 尚未运行真实 Provider/live 测试，原因是 W04 明确要求离线可复现且未授权真实费用请求；该状态不是实现失败。
- 工作包尚未归档，需等待用户确认后由用户手动移动；未执行 commit、push、PR、merge、tag 或 release。

## 6. UTF-8 guard

- files checked：`README.md`、`docs/work/T03-SystemPrompt设计/T03-SystemPrompt设计-checklist.md`、`docs/work/T03-SystemPrompt设计/feedback/W04-delivery-verification-feedback.md`
- result：通过 UTF-8 解码、常见乱码标记和 Markdown fence 检查
- repaired encoding issues：无

## 7. T03 独立审查返工

无上下文独立审查发现一个交付阻断问题：Application 构造 System Prompt 时使用当前 Provider 的远端模型身份，但仍允许调用方通过 `GenerationRequest.model` 覆盖实际 Provider 请求模型，可能导致 Prompt 声明的模型与真正请求的模型不一致。

本轮按回归测试优先完成窄修复：

- 新增 Application 边界测试，先确认调用方传入 `model` 时旧实现不会拒绝，测试按预期失败。
- 在统一的 `_prepare_request` 入口拒绝调用方设置 `GenerationRequest.model`；模型选择仍只由 Application 当前配置和 Provider 快照负责。
- 保留 Provider 端既有请求模型能力，不修改 Core 协议，也没有引入清空字段、别名、包装层或双轨兼容逻辑。
- 修复后边界回归测试为 `2 passed, 10 deselected`，Application/CLI/TUI 组合为 `58 passed`。
- Core 与三 Provider 协议组合为 `68 passed, 3 skipped`，架构/包测试为 `11 passed`，全量测试为 `253 passed, 3 skipped`。
- `compileall`、`pip check`、`git diff --check` 均通过；`git diff --check` 仅报告既存 LF/CRLF 转换提示。
- live Provider 测试仍按 `UTHCODE_RUN_LIVE` 门禁跳过，未产生真实费用请求。
