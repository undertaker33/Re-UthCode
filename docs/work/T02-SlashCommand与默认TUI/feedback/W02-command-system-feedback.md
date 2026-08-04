# W02 Command System Worker Feedback

## 1. 完成结论

已严格按 Task 5 → Task 6 顺序完成本 Worker 授权范围。两项 Task 的 Checklist 条目均已取得可复现证据并勾选；Task 1—Task 4 保持 W01 的既有勾选状态，Task 7—Task 12 未实施。

本轮没有修改冻结的原始需求、Spec、Tasks 或 Prompt，没有引入 Textual、Skill Loader、Session、Agent Loop 或旧命令兼容层；没有执行 Git 提交、推送、PR、合并或工作包归档。

## 2. 实际实现

### Task 5：Command Registry 与 Parser

- `application/commands/models.py` 定义了 `CommandKind`、`CommandAvailability`、`ArgumentSpec`、`CommandDefinition`、`CommandInvocation`、`CommandOutcome`、结构化 `UiAction` 和 Completion 候选。命令定义使用不带 `/` 的小写 canonical/alias；用户输出由模型层统一补上 `/`。
- `application/commands/registry.py` 是唯一 Registry 实现。注册前完整校验 canonical、alias、重复 alias、大小写、空白、斜杠和非法字符，任何失败都不改变已有注册内容；解析支持大小写不敏感和一个可选的用户输入前导 `/`，列表保持注册顺序并保留 hidden 状态。
- `application/commands/parser.py` 区分普通文本、裸 `/`、未知命令、可执行命令和 Usage 错误，保留 raw name、canonical、alias、args、query 与 `--` 状态。结构化参数使用 `shlex`；有参数定义的命令使用 `--` 分隔原始 query，无结构化参数的 PROMPT 命令将 `--` 视为普通 prompt 文本，避免重组用户 query。

### Task 6：Completion、Dispatcher 与内置命令

- `completion.py` 从传入 Registry 生成候选；canonical 和 alias 均参与匹配，按 canonical 去重，不设置八项截断，`/help` 始终只出现一次并固定在最后。Usage、参数提示、静态候选来自 `ArgumentSpec`；`/model` 候选读取 Application Model Catalog。
- `dispatcher.py` 将 LOCAL、LOCAL_UI、PROMPT 分别包装为 `output`、结构化 `ui_action`、`prompt`，并统一处理 SUCCESS、USAGE_ERROR、UNKNOWN_COMMAND、NOT_IMPLEMENTED、EXECUTION_ERROR；普通文本和裸 `/` 不产生可执行分发结果。
- `builtins.py` 用一个定义源登记 T02 全部 15 个内置命令。`/models` 和 `/m` 是 `/model` 的 alias，不存在 `models` canonical；help、clear、model、status、quit 具备实际实现，其余命令只登记元数据并返回 `功能未实现：/<canonical>`。`/clear`、无参数 `/model`、`/quit` 分别产生 `ClearTranscript`、`OpenModelPicker`、`QuitInterface`；直接 `/model <ref>` 返回 `ModelSelected` 并调用 Application 的模型切换。
- `application/commands/__init__.py` 和 `application/__init__.py` 公开上述 Application API；命令模块不导入 Textual、参考项目或未来 Loader。

## 3. 文件改动

新增：

- `src/uthcode/application/commands/models.py`
- `src/uthcode/application/commands/registry.py`
- `src/uthcode/application/commands/parser.py`
- `src/uthcode/application/commands/completion.py`
- `src/uthcode/application/commands/dispatcher.py`
- `src/uthcode/application/commands/builtins.py`
- `src/uthcode/application/commands/__init__.py`
- `tests/test_command_registry.py`
- `tests/test_command_parser.py`
- `tests/test_command_completion.py`
- `tests/test_command_dispatcher.py`
- 本 Feedback 文件

修改：

- `src/uthcode/application/__init__.py`：公开正式命令 API。
- `docs/work/T02-SlashCommand与默认TUI/T02-SlashCommand与默认TUI-checklist.md`：仅将 Task 5、Task 6 现有复选框改为完成。

删除：无。

## 4. 验证结果

- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_command_registry.py tests/test_command_parser.py tests/test_command_completion.py tests/test_command_dispatcher.py`：`51 passed`。
- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_configuration.py tests/test_application_runtime.py`：`45 passed`。
- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_application.py tests/test_provider_factory.py tests/test_provider_contract.py`：`25 passed`。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests`：通过。
- `git diff --check`：通过；仅有 Git 关于现有工作区文件 LF/CRLF 转换的提示，无 whitespace error。
- `rg -ni "textual|mewcode|firstcoder|skillloader" src/uthcode/application/commands`：0 条。

## 5. Checklist 状态

- Task 5：9/9 已勾选。
- Task 6：9/9 已勾选。
- Task 7—Task 12：未实施，保持未勾选。

## 6. 范围、风险与遗留清理

- 现有 `tests/test_architecture_boundaries.py` 仍包含 T01 阶段“commands/interfaces 不存在”的旧阶段断言；根据冻结 Tasks，架构测试更新属于 Task 11—Task 12，本 Worker 未越权修改。W03 接入 Interface 时必须同步更新该测试。
- 本轮未实现 CLI、TUI、Completion Menu Widget、Model Picker Widget、Session、Tool、Permission、Skill、Agent Loop 或任何未来命令业务。
- 命令定义、help、completion、Usage、alias 和实现状态均通过同一个 Registry 对象流动；没有新增第二份命令列表、空 handler 文件、Textual 依赖或旧 API 适配层。
- 未读取真实 API Key，未发起网络请求；未执行 Git 写入或工作包归档。

## 7. 第一轮返工（2026-08-05）

### 7.1 返工原因

- `/model` 原先将 `select_model()` 的底层异常文本直接包装为 `CommandExecutionError`，可能泄露 API Key、带凭据 URL 或其他 Provider/配置秘密。
- Dispatcher 原先将未知 handler 异常的 `str(exc)` 拼入 `CommandOutcome.error`，未知异常文本可能继续向用户和结果 repr 传播。
- `tests/test_architecture_boundaries.py` 仍把已经正式交付的 `application/commands` 列为禁止未来模块，导致完整测试集与 Task 5—Task 6 的正式边界冲突。
- 原反馈将 Task 6 Checklist 误计为 9/9；实际 Checklist 有 10 项。

### 7.2 实际修改与脱敏策略

- `builtins.py` 为模型切换失败使用固定文案 `模型切换失败`。`select_model()` 的任何普通异常均在命令边界被截断，不再读取、记录或拼接异常文本；模型切换仍由 Application 保持原有全成全败顺序和状态回滚语义。
- `dispatcher.py` 仅对明确构造的 `CommandExecutionError` 展示其约定安全文案；未知 `Exception` 统一转换为固定的 `命令执行失败`，不再透传 `str(exc)`，也不会让异常逃逸到当前 Run。
- `tests/test_command_dispatcher.py` 将原先依赖 `boom` 透传的断言改为固定文案断言，并新增普通 handler 抛出 `sk-handler-secret-value`、`/model` 切换抛出 `sk-secret-value` 的回归测试；两者均验证 `CommandOutcome.error`、`repr(CommandOutcome)` 和错误结果不含秘密。
- `tests/test_architecture_boundaries.py` 仅删除未来模块禁止集合中的 `commands`，保留其他未来能力和 `interfaces` 禁止项；没有重写架构测试。

### 7.3 返工验证

- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_command_registry.py tests/test_command_parser.py tests/test_command_completion.py tests/test_command_dispatcher.py`：`53 passed`。
- `conda run --no-capture-output -n re-uthcode pytest -q`：`166 passed, 3 skipped`。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests`：通过。
- `git diff --check`：通过；仅有现有工作区文件 LF/CRLF 转换提示，无 whitespace error。
- 秘密扫描回归通过：模型切换秘密和普通 handler 秘密均未出现在 outcome、error 或 repr 中。

### 7.4 Checklist 与范围状态

- Task 5：9/9 已勾选。
- Task 6：实际为 10/10 已勾选；原 Feedback 中的 9/9 是计数错误，Checklist 文字、结构和顺序未修改。
- Task 7—Task 12：未实施，保持未勾选。
- 本轮未实现 CLI、TUI、Widget、Session、Agent Loop、Tool、Permission、Skill、MCP 或其他未来能力；未增加依赖，未引入兼容层或第二套命令入口；未执行 Git 提交、推送、PR、合并或归档。
