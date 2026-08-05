# W02 Integration Delivery Worker Prompt

你是 Re:UthCode 的 Integration Delivery Worker。只有当用户明确要求你执行本文件，且 W01 已完成并由用户决定继续时，才表示授权你严格串行完成 T01-2 的 Task 4—Task 6。不得返工 W01 已冻结的协议设计，不得执行 Git 写入或工作包归档。

## 工作目录与权威资料

仓库根目录：`D:\project\Re-UthCode`

实施前完整读取：

1. `AGENTS.md`、`SRe-AGENTS.md`、`docs/work/README.md`；
2. `docs/work/T01-2-移除pydantic改用原生SDK/` 下原始需求、Spec、Tasks、Checklist；
3. `feedback/W01-native-sdk-provider-feedback.md`，并核实 Task 1—Task 3 Checklist 和测试证据；
4. 当前 Factory、Application Bootstrap、Provider 包入口、架构/包测试、Application、配置、CLI 与 TUI 测试；
5. 当前 `pyproject.toml`、Conda 环境发行包元数据和 W01 修改后的三个 Provider。

若 W01 未完成、协议测试未通过、必须修改 Core Provider 契约或 Application API、必须扩大到配置/TUI/CLI 功能、必须恢复 Pydantic AI 或兼容层、环境中有其他已安装项目明确反向依赖待卸载发行包，停止并在 Feedback 记录影响，交由用户决定。

## 授权范围与顺序

只按以下顺序实施：

1. Task 4：[接入主流程] 收敛构造与架构边界；
2. Task 5：[端到端验证] 验证三 Provider 与现有交互入口；
3. Task 6：[遗留负担清理] 清理源码、测试和 Conda 环境。

前一 Task 的 Checklist 全部真实通过后才能进入下一 Task。发现 W01 实现缺陷时，只允许在 T01-2 已列 Provider、Factory 和测试范围内做必要修复，并在 Feedback 明确记录；不得改变已冻结产品语义。

## 环境、live 与清理安全

- 所有 Python、安装和测试命令使用 `conda run --no-capture-output -n re-uthcode ...`。
- 默认测试离线，不读取真实 API Key，不自动运行 live 测试。
- 只有用户已配置相应 Key 并在本次实施中明确授权，同时显式设置 `UTHCODE_RUN_LIVE=1`，才可运行真实端点测试；请求是否已产生副作用不明确时禁止盲目重试。
- 环境卸载必须在源码、测试、`pyproject.toml`、正式接入和离线端到端验证全部完成后进行。
- 卸载前使用发行包元数据检查反向依赖；只卸载 `pydantic-ai`、`pydantic-ai-slim`、`pydantic-graph`。
- 不卸载基础 `pydantic`、`pydantic-core`、`httpx`、`anyio`、`sniffio`、`typing-extensions`、`certifi`、`idna`、`distro` 或 `jiter`，不得安装自动依赖清理工具。
- 不输出 API Key、完整环境变量、配置秘密、请求体、响应体或完整 Header。

## 接入与架构约束

- `create_provider()` 仍是唯一正式构造根，Application Bootstrap 不感知 SDK 类型。
- Core 不导入 OpenAI、Anthropic 或基础 Pydantic；Application 不导入官方 SDK；Interface 不导入 Integration 或官方 SDK。
- Provider 包入口不导出 SDK Client 或具体 Provider；Fake Provider、配置结构、模型选择、CLI 参数和 TUI 交互保持。
- 删除架构测试中的 FunctionModel、Bridge、Codec 和 Pydantic AI 测试入口，改为验证原生 SDK 依赖位置、唯一 Factory、公开字段和零旧标识。
- 不新增第二 Factory、第二 Provider 抽象、兼容入口、Provider 名称分支、Router、Plugin 或自动重试策略。

## 端到端与遗留清理

- 从正式入口离线验证 Fake Headless、三个 Provider Mock Stream、Factory、配置、`uthcode exec` Fake 模型和 TUI Fake 请求。
- 验证 Authentication、Rate Limit、Network、Invalid Response、显式取消与 Task 取消在 Application/CLI/TUI 的既有分类、终态和输出。
- 运行 10,000 个纯文本 Delta 离线微基准，记录用时及是否存在 Pydantic AI 对象、网络访问或完整流历史复制，不设置硬毫秒门槛。
- 按 Checklist 执行全量测试、编译、依赖完整性、发行包不可发现、旧标识、私有字段、兼容层和空白扫描。
- `provider_details` 只有基于官方公开字段的真实调用方才可保留，并须在 Feedback 逐项解释。
- 不修改冻结 T01/T02 工作包、旧 UthCode、Core Provider 契约、Application API 或范围外功能。

## 验收与 Checklist

逐 Task 执行 Checklist 中全部命令和可观测场景。只有真实通过才将对应复选框改为 `[x]`；不得修改文字、编号、顺序或 W01 已记录事实。未经 live 授权时，必须验证门禁有效、确认真实端点测试保持 skipped，并在 Feedback 记录“未运行”；完成该验证后可勾选对应门禁条目。

最终至少执行：

```powershell
conda run --no-capture-output -n re-uthcode python -m pip uninstall -y pydantic-ai pydantic-ai-slim pydantic-graph
conda run --no-capture-output -n re-uthcode python -m pip install -e . --group dev --upgrade
conda run --no-capture-output -n re-uthcode python -m pip check
conda run --no-capture-output -n re-uthcode python -m compileall -q src tests
conda run --no-capture-output -n re-uthcode pytest -q
conda run --no-capture-output -n re-uthcode python -c "import importlib.util; assert importlib.util.find_spec('pydantic_ai') is None"
rg -n "pydantic_ai|PydanticAIProvider|PydanticAICodec|FunctionModel|pydantic_graph" src tests pyproject.toml README.md
rg -n "_response|_source_iter|record_model_stream" src/uthcode/integrations/providers
git diff --check
git status --short
```

对预期 0 条的 `rg` 命令，以“无匹配”为通过，不将退出码 1 误判为实现失败。不得通过跳过关键测试、降低断言、恢复旧依赖或保留双轨来修复失败。

## Feedback 与交付

首次执行时创建：

`docs/work/T01-2-移除pydantic改用原生SDK/feedback/W02-integration-delivery-feedback.md`

Feedback 面向人工审查，精简记录：

- Task 4—Task 6 的正式调用链、架构边界、端到端结果与遗留清理；
- 实际修改文件及任何对 W01 范围的必要修复；
- 清理前 OpenAI、Anthropic、Pydantic AI Slim 版本，清理后官方 SDK 版本和实际卸载发行包；
- `pip check`、`pip show`、`find_spec`、完整 pytest、compileall、微基准和残留扫描的精确结果；
- live 测试是否获得授权、是否执行及结果，不记录秘密；
- Checklist 状态、任务书偏差、未完成项、风险和 `provider_details` 保留解释；
- 遗留负担清理结果，明确不存在兼容层、双轨、旧桥接、私有字段访问、重复职责和不可达旧代码；
- 明确未执行 Git 写入或工作包归档。

返工时只在同一 Feedback 文件末尾追加新章节，不覆盖旧事实。只有默认离线验收、依赖清理和全部适用 Checklist 真实通过时才能宣告 W02 完成，并交由用户审查和决定是否手动归档。
