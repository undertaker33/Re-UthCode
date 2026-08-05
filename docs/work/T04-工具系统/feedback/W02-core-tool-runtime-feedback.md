# W02 core-tool-runtime Feedback

## 1. 完成结论

已完成 T04 Task 2，未开始 Task 3—Task 9，未执行任何 Git 写操作。

W01 前置已通过：W01 Feedback 记录了配置 Integration 边界修复、定向回归和全量 `269 passed, 3 skipped`；本 Worker 未修改 W01 实现。

## 2. 实际实现

Core 现在只有一套工具运行契约：

- `ToolDefinition`、`ToolCallPart`、`ToolResultPart`、`JsonPayload` 和 `CancellationToken` 继续来自 `core.provider`，没有新增 DTO。
- `core.tool.Tool` 是 Integration 工具实现的唯一 Protocol；`ToolExecutionResult` 只包含内容和错误标记。
- `ToolRegistry` 按注册顺序保存工具，返回 tuple 定义/工具集合；重复名称在写入前硬失败，注册时使用 `jsonschema` 的 Draft 2020-12 schema 检查。
- `ToolExecutor` 先把不可变 Core JSON 值转换为普通 dict/list 交给第三方校验器，再把已校验的 `JsonPayload` 传给 Tool；校验器、ValidationError 和 SchemaError 不会越过 Core。
- `execute_batch()` 严格 FIFO，一次只等待一个工具。未知工具、参数错误、普通执行异常和取消都生成对应 call ID 的 `ToolResultPart`；普通失败不会阻断后续调用，取消后不再启动后续 Tool，但为每个剩余 call 生成取消结果。
- 成功和错误结果都只经过 Executor 一次确定性截断，默认限制为 10,000 字符并追加稳定后缀。

## 3. 修改文件

新增：

- `src/uthcode/core/tool.py`
- `tests/test_tool_core.py`
- `docs/work/T04-工具系统/feedback/W02-core-tool-runtime-feedback.md`

修改：

- `pyproject.toml`：增加 `jsonschema>=4.25,<5`。
- `src/uthcode/core/__init__.py`：显式导出 `Tool`、`ToolExecutionResult`、`ToolRegistry` 和 `ToolExecutor`。
- `tests/test_package.py`：验证 Core 工具公共导出。
- `docs/work/T04-工具系统/T04-工具系统-checklist.md`：仅勾选 Task 2 的六项既有验收项。

## 4. 验证结果

开发环境：`conda run --no-capture-output -n re-uthcode ...`。

- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_tool_core.py tests/test_package.py`：`12 passed`。
- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_tool_core.py tests/test_provider_contract.py tests/test_package.py`：`33 passed`。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests`：通过。
- `conda run --no-capture-output -n re-uthcode python -m pip check`：通过，输出 `No broken requirements found.`。
- `conda run --no-capture-output -n re-uthcode git diff --check`：通过；仅有工作树 LF/CRLF 转换提示，无 diff 错误。

## 5. Checklist、偏差与风险

- Task 2：6/6 已勾选。
- Task 1：保留 W01 已有的 5/5 勾选；Task 3—Task 9 保持未勾选、未实施。
- 本 Worker 未修改 Provider DTO、Application、Integration Tool、Permission、Agent Loop、内置工具或未来字段。
- `jsonschema` 已安装到当前 `re-uthcode` 环境；项目依赖声明为 `jsonschema>=4.25,<5`。
- 普通工具异常的返回内容使用稳定归一化文本，不暴露第三方异常类型或校验库对象。
- 未执行 Git 写操作；当前工作树中其他既有删除、修改和未跟踪文件未被整理或覆盖。

## 6. 遗留负担清理

- 未新增 Pydantic、LangGraph、LangChain、Permission、Sandbox、deferred、parallel 或兼容适配层。
- 未创建第二套 ToolCall、ToolResult、ToolDefinition 或 CancellationToken。
- Core Tool 模块只依赖标准库、`jsonschema` 和 `core.provider`，不导入 Application、Integration 或 Interface。

## 返工第 1 轮

### 1. 返工原因

审查发现 Registry 只缓存注册名称和 validator，`definitions()` 却在调用时重新读取 `tool.definition`。当 Tool 对象注册后改变名称或参数 schema 时，Provider 可能看到与 Registry 查找键、validator 不一致的定义；同时非法 schema 转换使用 `raise ... from exc`，使 `SchemaError` 通过 `__cause__` 暴露。

### 2. 实际修改

- `ToolRegistry` 新增按注册名称保存的 `_definitions` 映射。注册时获取一次 `ToolDefinition`，完成类型和 JSON Schema 校验后，与 Tool 和 validator 一起写入 Registry。
- `definitions()` 只返回 `_definitions` 的注册顺序 tuple，不再读取 Tool 对象的 `definition` 属性。
- `get(name)`、注册快照和 `_validator_for(name)` 共用同一个注册名称键；Tool 对象自身仍可变，但名称漂移不会改变已注册入口、定义或 validator。
- `SchemaError` 转换为稳定的 `ValueError` 时使用 `from None`，错误文本只保留稳定前缀和工具名称，不携带 jsonschema metaschema、validator 或完整异常内容。
- 非法 schema 在所有 Registry 状态写入前失败，失败后不会出现非法 Tool、定义或 validator。

### 3. 新增回归测试

- `test_registry_keeps_definition_and_schema_snapshot_when_tool_definition_drifts`：验证注册后名称和 schema 改变时，定义 tuple 仍保持注册快照，原名称可查，新名称不可见。
- `test_registry_snapshot_controls_execution_after_tool_definition_drifts`：验证原名称仍能按注册 schema 执行，新名称返回 unknown，漂移后的参数按原 validator 拒绝。
- `test_invalid_schema_error_hides_jsonschema_cause_and_details`：验证暴露异常不是 `SchemaError`、`__cause__ is None`、文本不含第三方 metaschema/validator 细节，且失败后 Registry 为空。

### 4. 验证结果

- `conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_tool_core.py -k "snapshot or invalid_schema_error"`：`3 passed, 8 deselected`。
- `conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_tool_core.py tests/test_provider_contract.py tests/test_package.py`：`36 passed`。
- `conda run --no-capture-output -n re-uthcode python -m pytest -q`：`281 passed, 3 skipped`。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests`：通过。
- `conda run --no-capture-output -n re-uthcode python -m pip check`：通过，输出 `No broken requirements found.`。
- `conda run --no-capture-output -n re-uthcode git diff --check`：通过；仅有既有工作树 LF/CRLF 转换提示，无 diff 错误。

### 5. 偏差、风险与遗留负担

- 未修改 Checklist；Task 2 原有 6 项继续保持已勾选，Task 3—Task 9 未开始。
- 未修改 Provider DTO、Application、Integration Tool、Permission、Agent Loop，未增加第二套 ToolDefinition、兼容层或后续能力。
- `Tool` 对象自身仍可变，这是协议允许的状态；Registry 通过注册时的不可变 `ToolDefinition` 快照保持公开定义、查找名称和参数 validator 一致。
- `from None` 抑制第三方异常上下文的公开 traceback/cause；对外异常仍是稳定的 Python `ValueError`。当前没有发现需要扩大范围的风险。
- UTF-8 guard 已在返工后单独执行，文件通过 UTF-8、乱码标记和 Markdown fence 检查；未修复任何编码问题。
- 未执行 Git 写操作，其他既有删除、修改和未跟踪文件保持原状。
