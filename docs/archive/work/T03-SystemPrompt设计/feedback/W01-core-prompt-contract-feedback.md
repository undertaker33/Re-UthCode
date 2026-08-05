# W01 Core Prompt Contract Worker Feedback

## 执行范围与实际基线

本轮由用户明确派发 `prompt/W01-core-prompt-contract-prompt.md`，严格按 Task 1 → Task 2 执行。开始前确认：

- `HEAD` 为 `047bd155c3980584f6b38da6e20fa62241cf7498`，与 T03 固定基线一致；
- 初始工作区只有用户提供的未跟踪 T03 工作包目录，没有其他代码修改；
- 未执行 Task 3—Task 8，未修改 Provider Integration、Application、Interface、README 或 Git 状态。

## 实际完成内容

### Task 1：Core System Prompt

新增 `src/uthcode/core/prompt.py`，Core 现在拥有唯一的纯 Prompt 构建入口 `build_system_prompt()`，以及不可变的 `PromptSection`、`SystemPromptContext`。固定 Section 按优先级 `0/10/20/30/100` 输出：身份、工作原则、代码质量与安全、沟通与结果真实性、当前运行环境。静态内容始终位于运行环境之前；同优先级保持声明顺序，空白 Section 被忽略，段间使用两个换行，最终文本不保留尾部空白。

运行上下文只包含工作目录、平台名称与版本、日期、模型选择、Provider 协议和远端模型 ID。运行值由显式 Context 提供，换行、反斜杠、反引号和常见 Markdown 结构字符会被转义；Prompt 构建不读取文件、环境变量、系统状态或配置，也不声明尚未实现的能力。

### Task 2：Core 请求协议

`GenerationRequest` 新增唯一独立字段 `system_prompt: str | None`，参与字典/JSON 序列化与恢复，并继续保持 dataclass 深度不可变。`None` 表示没有 Prompt；非 `None` 值必须是非空白字符串。`Message.role` 现在只接受 `user`、`assistant`、`tool`，`system`、`developer`、未知角色和非法类型均明确拒绝；没有新增同义字段或兼容入口。

## 修改文件

- 新增：`src/uthcode/core/prompt.py`
- 修改：`src/uthcode/core/__init__.py`
- 修改：`src/uthcode/core/provider.py`
- 新增：`tests/test_system_prompt.py`
- 修改：`tests/test_provider_contract.py`
- 修改：`docs/work/T03-SystemPrompt设计/T03-SystemPrompt设计-checklist.md`，仅将 Task 1、Task 2 既有复选框由 `[ ]` 改为 `[x]`
- 新增：本 Feedback 文件

未修改其他源码、测试、需求、Spec、Tasks、Prompt 或 Checklist 文字内容。

## 验证结果

- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_system_prompt.py`：`9 passed`。
- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_provider_contract.py`：`21 passed`。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src/uthcode/core tests/test_system_prompt.py tests/test_provider_contract.py`：退出码 0。
- `git diff --check`：退出码 0；Git 仅提示现有 Windows 工作副本的 LF/CRLF 转换，不是空白错误。
- Prompt 未来能力扫描：`src/uthcode/core/prompt.py` 中 `Tool/Permission/Plan/Memory/Hook/Skill/MCP/Subagent/Sandbox/LangGraph/LangChain/MewCode` 无匹配。
- UTF-8 guard：Checklist 和本 Feedback 均通过 UTF-8 解码、常见乱码标记和 Markdown fence 检查；未修复任何编码问题。

## Checklist 状态

Task 1 的 5 项和 Task 2 的 4 项均已取得上述测试或扫描证据并勾选。Task 3—Task 8 保持未勾选，等待后续 Worker 按顺序执行。

## 差异、风险与遗留负担

本轮没有偏离 W01 的冻结设计。由于 `Message("system", ...)` 是临时 Core 语义且已被拒绝，后续 W02 必须把三个 Provider Integration 的输入改为 `GenerationRequest.system_prompt`；本轮按范围未修改这些文件，也未运行依赖它们旧入口的 Provider 集成测试或全量测试。

没有引入 Prompt Manager、Registry、Loader、Cache、适配器、别名、Facade、Shim、双轨 API 或未来能力字段。未运行真实 Provider/live 测试，未执行 Git commit、push、PR、合并或工作包归档。
