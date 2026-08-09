# W03 Application Interface Worker Feedback

## 1. 执行范围与基线

本轮由用户明确派发 `prompt/W03-application-interface-prompt.md`，严格按 Task 4 → Task 5 执行，未开始 Task 6—Task 8。

- 实际 `HEAD` 为 `047bd155c3980584f6b38da6e20fa62241cf7498`，仍为 T03 固定基线；
- 开始时工作区已有 W01/W02 的 Core、Provider Integration、测试和未跟踪 T03 工作包修改，均予以保留；
- W01/W02 定向回归：`68 passed, 3 skipped`；
- 未修改 `configuration.py`、TOML、Provider Factory、Widget 核心或 Command 系统；未执行 live Provider、Git 写入或工作包归档。

## 2. 实际完成内容

### Task 4：Application 运行上下文与权威请求准备

- 新增 `ApplicationRuntimeContext`，使用冻结 dataclass 保存绝对规范化 `workdir`、平台名称、平台版本和创建时解析的日期。`from_system()` 支持显式注入固定平台和日期，Context 不读取 TOML、秘密或项目指令。
- `UthCodeApplication` 持有唯一运行上下文；每次 `start_generation()` 读取当前 `ProviderIdentity` 和当前 Model Ref，构造 Core `SystemPromptContext`，调用唯一 `build_system_prompt()`，再以 `dataclasses.replace()` 创建带权威 `system_prompt` 的新请求。
- 调用方自带 `system_prompt` 在创建 Handle 前拒绝；Prompt 构建异常也在 Provider 迭代器创建前抛出，因此两类失败的 Fake Provider 调用计数均为 0。原请求和其嵌套消息保持不变。
- `create_application()` 新增独立 `runtime_context` 组合参数。模型切换沿用“候选 Provider 构造成功 → 写回成功 → 替换内存状态”的顺序；成功后下一请求刷新 Model Ref、协议和远端模型 ID，构造或写回失败则继续使用旧身份。
- `GenerationHandle`、`stream_generation()` 和每个 Handle 独立取消语义保持不变。

### Task 5：CLI、TUI 与 Headless 共用运行上下文

- CLI 在配置加载前创建一次 `ApplicationRuntimeContext`，将同一个规范化 `workdir` 同时传入 `LaunchOptions` 配置发现和 Application Factory；默认 cwd 与显式 `--cwd` 均覆盖。
- TUI 删除构造函数和 `run_tui()` 的独立 `cwd` 参数及成员所有权，Topbar 直接读取 `application.runtime_context.workdir`。普通生成、模型 Picker、流式定时刷新、单 Assistant Widget、双 Esc 取消和退出清理保持原行为。
- README 更新了 `--cwd` 的统一数据流和 Embedded Python 的正式 `ApplicationRuntimeContext` 用法，没有加入 Prompt 覆盖示例或未来能力声明。

## 3. 修改文件

新增：

- `src/uthcode/application/runtime_context.py`
- `docs/work/T03-SystemPrompt设计/feedback/W03-application-interface-feedback.md`

修改：

- `src/uthcode/application/generation.py`
- `src/uthcode/application/bootstrap.py`
- `src/uthcode/application/__init__.py`
- `src/uthcode/interfaces/cli.py`
- `src/uthcode/interfaces/tui/app.py`
- `tests/test_application.py`
- `tests/test_application_runtime.py`
- `tests/test_cli.py`
- `tests/test_tui.py`
- `README.md`
- `docs/work/T03-SystemPrompt设计/T03-SystemPrompt设计-checklist.md`：仅将 Task 4、Task 5 既有复选框由 `[ ]` 改为 `[x]`。

W01/W02 已有的 Core、Provider Integration 和相关测试修改未在本轮重新改动。

## 4. 验证结果

- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_application.py tests/test_application_runtime.py`：`25 passed`。
- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_cli.py tests/test_tui.py`：`31 passed`。
- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_provider_contract.py tests/test_anthropic_integration.py tests/test_openai_responses_integration.py tests/test_openai_compat_integration.py`：`59 passed, 3 skipped`；live 用例按既有门禁跳过。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests`：退出码 0。
- `git diff --check`：退出码 0；仅有 Windows 工作副本的 LF/CRLF 转换提示。
- `rg -n 'system_prompt|build_system_prompt|SystemPromptContext' src/uthcode/interfaces`：0 条。
- `rg -n 'workdir|platform_name|platform_release|current_date' src/uthcode/application/configuration.py src/uthcode/integrations/config`：0 条。
- README 旧 `Message("system", ...)`、Prompt API 直连和覆盖示例扫描：0 条。

## 5. Checklist 状态

- Task 4：7/7 已勾选，并取得上述 Application/Runtime 测试和 Runtime 字段扫描证据。
- Task 5：8/8 已勾选，并取得上述 CLI/TUI 测试、workdir 数据流、Interface Prompt 扫描和 README 检查证据。
- Task 6—Task 8：保持未勾选，等待 W04 按顺序执行。

## 6. 差异、风险与遗留负担

与 W03 Prompt 和 T03 Tasks 无实质差异。没有修改 EffectiveConfig/TOML，没有让 Interface 直连 Core Prompt，没有按 Provider 名称分支，也没有新增第二运行上下文、兼容层、别名、Facade、Shim 或双轨 Prompt 入口。

本轮未运行真实 Provider/live 测试，未读取或输出真实 API Key；Task 6—Task 8 的主流程架构验证、全量回归和最终遗留扫描不属于本 Worker 范围。工作包未归档，未执行任何 Git 提交、推送或其他 Git 写操作。

UTF-8 guard：

- files checked：`README.md`、`docs/work/T03-SystemPrompt设计/T03-SystemPrompt设计-checklist.md`、`docs/work/T03-SystemPrompt设计/feedback/W03-application-interface-feedback.md`
- result：通过 UTF-8 解码、常见乱码标记和 Markdown fence 检查
- repaired encoding issues：无

## 7. W03 验收返工

### 7.1 返工原因

验收发现：在模型 `one/ref` 下创建旧 `GenerationHandle` 后切换到 `two/ref`，再消费旧 Handle 时，旧请求虽然在 `start_generation()` 已经生成了声明 `one/ref`、旧协议和 `remote-one` 的 System Prompt，但 `events()` 通过 Application 动态读取了当前 Provider，导致请求实际发送给新 Provider，旧 Provider 未收到请求。

### 7.2 根因

`GenerationHandle` 原先只保存 `Application` 和准备完成的 `GenerationRequest`，未保存创建时对应的 `ProviderPort`。因此 `events()` 调用 `_stream_with_token()` 时，内部再次读取 `self._provider`，模型切换后发生了请求快照中的 Provider 与执行 Provider 不一致。

### 7.3 实际修改

- `GenerationHandle` 现在在创建时保存对应的 `ProviderPort`。
- `start_generation()` 先固定当前 Provider，再把同一个 Provider 传给请求准备逻辑和 Handle；System Prompt 仍在 `start_generation()` 内按该时点的 Model Ref、Provider 协议和远端模型 ID 构建。
- `_stream_with_token()` 改为接收 Handle 固定的 Provider，保留原有独立 `CancellationToken`、单次消费、终态事件验证和流关闭语义。
- 新增回归测试 `test_generation_handle_binds_provider_snapshot_across_model_switch`；未修改 Core Prompt contract、Provider Integration、配置、CLI、TUI、README 或 Checklist，也未增加锁、调度器、兼容层、Alias、Facade、Shim 或双轨逻辑。

### 7.4 回归测试

- 修复前先运行新增回归测试，结果为 `1 failed, 14 deselected in 0.13s`；失败点为旧 Provider 调用数为 0，确认了本次验收问题。
- 修复后新增回归测试验证：旧 Handle 在切换模型后只由旧 Provider 收到请求，旧 Prompt 包含 `one/ref`、`protocol-one/ref` 和 `remote-one`；新 Handle 只由新 Provider 收到请求，新 Prompt 包含 `two/ref`、`protocol-two/ref` 和 `remote-two`；两个 Handle 均正常产生 `GenerationCompleted`。
- 既有 `test_generation_handles_cancel_independently_and_record_requests` 继续验证两个 Handle 的 CancellationToken 独立、单独取消和终态行为；原有流关闭与终态校验测试保持通过。

### 7.5 验证结果

- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_application.py tests/test_application_runtime.py`：`26 passed in 3.34s`。
- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_cli.py tests/test_tui.py`：`31 passed in 20.94s`。
- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_provider_contract.py tests/test_anthropic_integration.py tests/test_openai_responses_integration.py tests/test_openai_compat_integration.py`：`59 passed, 3 skipped in 2.88s`。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests`：退出码 0。
- `conda run --no-capture-output -n re-uthcode pytest -q`：`252 passed, 3 skipped in 27.98s`。
- `git diff --check`：退出码 0；仅有 Windows 工作副本 LF/CRLF 转换提示。
- `git status --short`：保留既有工作区修改；本次仅新增/修改 W03 返工涉及的测试、Application 实现和本 Feedback，未执行 Git 写入。

### 7.6 遗留风险

本次验收缺陷已由 Fake Provider 回归覆盖，未发现新的 W03 行为回归。Provider Integration 分组中的 3 个 live 用例仍按既有门禁跳过，未执行真实 Provider 请求；W04 未开始，工作包未归档，未执行 Git 提交、推送或其他 Git 写操作。等待再次验收 W03。
