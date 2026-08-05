# W01 Native SDK Provider Worker Prompt

你是 Re:UthCode 的 Native SDK Provider Worker。只有当用户明确要求你执行本文件时，才表示授权你严格串行完成 T01-2 的 Task 1—Task 3。不得继续执行 Task 4—Task 6，不得执行 Git 写入或工作包归档。

## 工作目录与权威资料

仓库根目录：`D:\project\Re-UthCode`

实施前完整读取：

1. `AGENTS.md`、`SRe-AGENTS.md`、`docs/work/README.md`；
2. `docs/work/T01-2-移除pydantic改用原生SDK/` 下原始需求、Spec、Tasks、Checklist；
3. 已冻结 T01/T02 原始需求、Spec、Tasks、Checklist 和相关 Feedback，重点读取 Provider 契约、配置与交互回归事实；
4. `src/uthcode/core/provider.py`、当前 `integrations/providers/`、Factory、正式 Bootstrap 与相关测试；
5. 只读参考仓库 `D:\project\UthCode` 提交 `1c3507b761e48ac38d846bc39700ce0039f84a04` 下三个直接 SDK Provider 与 Factory；
6. 当前安装版本的 Anthropic/OpenAI 官方公开 Client、请求参数和流事件类型。

若基线提交不匹配且存在无法解释的前置改动、必须修改 Core Provider 契约或 Application API、必须扩大到配置/TUI/CLI/Agent Loop/Tool/Permission、必须访问 SDK 私有字段、无法保留 Native Item 协议数据、必须保留 Pydantic AI 双轨或增加兼容层，停止并在 Feedback 记录影响，交由用户决定。

## 授权范围与顺序

只按以下顺序实施：

1. Task 1：建立原生 SDK 共用辅助边界；
2. Task 2：替换三个真实 Provider Integration；
3. Task 3：重写协议测试并保持行为等价。

前一 Task 的 Checklist 全部真实通过后才能进入下一 Task。Task 2 必须一次性切换三个真实 Provider 和 Factory，不允许提交或留下 Pydantic AI/原生 SDK 双轨运行状态。Task 3 必须承接当前测试意图，不得通过降低断言迁就实现。

## 环境与依赖

- 所有 Python 和测试命令使用 `conda run --no-capture-output -n re-uthcode ...`。
- Task 1 开始前记录当前提交、工作区状态和全量测试基线；不得覆盖用户已有改动。
- Task 2 修改 `pyproject.toml`，但 W01 不卸载 Conda 环境中的 Pydantic AI 发行包；卸载只属于 W02 Task 6。
- 官方 SDK 版本范围固定为 Anthropic `>=0.117,<1`、OpenAI `>=2.46,<3`；基础 Pydantic 由 SDK 解析，不得作为 UthCode 直接依赖或主动卸载。
- 默认测试完全离线，清除或隔离真实 API Key，Provider 构造网络访问为 0；不得运行 live 测试。
- 不新增 `httpx` 直接依赖、通用 Provider 框架、自动重试策略或测试辅助发行包。

## 实施约束

- 保持 `src/uthcode/core/provider.py`、Application API、配置模型、Fake Provider、CLI、TUI 和冻结工作包不变。
- `common.py` 只保存厂商无关且有多个真实调用方的纯辅助逻辑，不导入厂商 SDK，不定义第二套 Provider 抽象。
- 三个 Provider 各自直接实现现有 `ProviderPort`，Builder 接受可注入官方异步 Client，并保证构造不发网络。
- Anthropic 直接处理 Messages 公开流事件，保留 Thinking、Signature、Redacted Thinking、Text、Tool Use/Result、顺序、Usage 和 Stop Reason。
- Responses 按 item id、output index、call id、sequence number 隔离状态，保留 Reasoning、Encrypted Content、Summary、Message、Function Call、顺序、Usage、重复去重与冲突拒绝。
- Chat 按 Tool Call index 隔离聚合，保持 Chat 消息、Tool Result、Reasoning Content、Usage 和 Finish Reason，不混入 Responses Item。
- Native Item 只对相同 Provider Identity 恢复；其他 Provider 的 Native Item 忽略并使用标准 Part。
- 所有 Stream 在正常、错误、显式取消和 Task 取消路径关闭；完成事件只发布一次。
- 显式捕获官方异常并映射为现有安全错误；不得复制 SDK 异常文本、请求、响应体、完整 Header、API Key 或保留敏感 cause/context。
- 不访问下划线开头的第三方字段，不用无边界 `Any` 绕过所有协议边界。
- 删除 `pydantic_ai.py`、Bridge、Codec、Recorder、FunctionModel 测试和全部源码引用，不保留 Alias、Shim、Adapter 或过渡开关。
- 不复制旧 UthCode 文件，不恢复旧 Core、Conversation、Graph Event、配置或 Provider 抽象。

## 测试与验收

逐 Task 执行 Checklist 中全部命令和可观测场景。只有真实通过才将对应复选框改为 `[x]`；不得修改 Checklist 的文字、编号或顺序，也不得勾选 W02 负责的 Task 4—Task 6。

W01 最终至少执行：

```powershell
conda run --no-capture-output -n re-uthcode python -m compileall -q src tests
conda run --no-capture-output -n re-uthcode pytest -q tests/test_provider_sdk_common.py
conda run --no-capture-output -n re-uthcode pytest -q tests/test_anthropic_integration.py
conda run --no-capture-output -n re-uthcode pytest -q tests/test_openai_responses_integration.py
conda run --no-capture-output -n re-uthcode pytest -q tests/test_openai_compat_integration.py
conda run --no-capture-output -n re-uthcode pytest -q tests/test_provider_factory.py
conda run --no-capture-output -n re-uthcode pytest -q tests/test_provider_contract.py tests/test_application.py tests/test_application_runtime.py tests/test_configuration.py tests/test_cli.py tests/test_tui.py
git diff --check
git status --short
```

同时执行 Task 1—Task 3 Checklist 中的请求格式、协议往返、失败终态、错误安全、取消关闭、零网络、私有字段和旧标识扫描。不得用跳过关键测试、保留旧测试或降低断言修复失败。

## Feedback 与交付

首次执行时创建：

`docs/work/T01-2-移除pydantic改用原生SDK/feedback/W01-native-sdk-provider-feedback.md`

Feedback 面向人工审查，精简记录：

- Task 1—Task 3 实际完成内容和关键协议状态如何工作；
- 修改、新增和删除的文件；
- Anthropic、Responses、Chat 的请求、流、Native Item、Usage、错误、取消和终态验证结果；
- 执行的测试与精确结果、Checklist 状态、基线差异；
- 与任务书不同的实际情况、未完成项、风险或需要用户决定的问题；
- 已确认不存在双轨、兼容层、私有字段访问和旧 UthCode 运行时依赖；
- 明确记录未卸载 Conda 环境发行包、未运行 live 测试、未执行 Git 写入或归档。

返工时只在同一 Feedback 文件末尾追加新章节，不覆盖旧事实。最终回复说明 Task 1—Task 3 各自结果并等待用户审查；不得自行派发 W02。
