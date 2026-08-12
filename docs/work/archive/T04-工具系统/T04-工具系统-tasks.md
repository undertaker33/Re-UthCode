# T04 工具系统 Tasks

## Worker 分组与依赖

| Worker | 严格执行顺序 | 依赖 |
| --- | --- | --- |
| W01 `config-boundary` | Task 1 | 无 |
| W02 `core-tool-runtime` | Task 2 | W01 完成并通过定向测试 |
| W03 `builtin-tools` | Task 3 → Task 4 → Task 5 | W02 完成；Task 4 依赖 Task 3 的工作区解析器 |
| W04 `application-delivery` | Task 6 → Task 7 → Task 8 → Task 9 | W01、W02、W03 全部完成 |

所有 Worker 必须在同一基线工作树中串行交接。用户只能通过对应 Prompt 文件显式派发；未派发的 Worker 不得提前实施。

## Task 1：修复配置 Integration 反向依赖

任务目标：让 Integration 返回自身拥有的不可变原始配置数据，由 Application 负责构造最终配置，并保持全部现有配置行为和错误证据。

新增文件：

- `src/uthcode/integrations/config/data.py`：定义原始配置结果与来源证据。
- `tests/test_config_loader_integration.py`：直接验证 Integration 层原始数据加载。

修改文件：

- `src/uthcode/integrations/config/loader.py`：移除 Application import，保留发现、解析、校验和合并职责。
- `src/uthcode/integrations/config/__init__.py`：移除旧有效配置公共入口。
- `src/uthcode/application/bootstrap.py`：调用原始加载器并完成最终配置转换及错误边界转换。
- `tests/test_configuration.py`：只通过 Application 公共入口验证产品配置行为。
- `tests/test_architecture_boundaries.py`：扫描全部 Integration 文件，禁止导入 Application/Interface。
- `tests/test_package.py`：校验收窄后的导出。

依赖任务：无。

参考资料定位：原始需求 1.6、2.5、8.8、8.12、Task 1；当前 loader、bootstrap、配置模型和配置测试。

完成边界：Integration 不再构造最终配置或公开旧入口；配置格式、优先级、秘密来源、模型选择、模板创建和诊断证据均不改变。不实施任何工具代码。

## Task 2：建立 Core Tool 契约、Registry 与 FIFO Executor

任务目标：建立无文件系统和进程依赖的权威工具运行语义。

新增文件：

- `src/uthcode/core/tool.py`：工具执行结果、Protocol、Registry、JSON Schema 校验、FIFO Executor 和统一截断。
- `tests/test_tool_core.py`：覆盖契约、顺序、错误、取消和截断矩阵。

修改文件：

- `pyproject.toml`：增加成熟 JSON Schema 校验依赖。
- `src/uthcode/core/__init__.py`：显式导出 Core Tool 类型。
- `tests/test_package.py`：验证公共导出和无副作用导入。

依赖任务：Task 1。

参考资料定位：原始需求 2.1、8.2–8.5、8.9、9.1、Task 2；既有 `core/provider.py` 的 Tool DTO 与取消模型；原 UthCode 固定提交中的 Registry/Executor 历史行为。

完成边界：Registry 拒绝重复名与非法 schema；Executor 对 unknown、invalid arguments、普通异常和取消生成同 ID 结果并保持 FIFO；输出只截断一次。不实现内置工具、Permission、Agent Loop 或第二套 DTO。

## Task 3：实现工作区、文件状态与文件工具

任务目标：提供受统一工作区和共享已读状态保护的读取、写入和编辑能力。

新增文件：

- `src/uthcode/integrations/tools/__init__.py`：收窄 Integration Tool 包边界。
- `src/uthcode/integrations/tools/workspace.py`：路径解析、候选安全校验和文件读取状态。
- `src/uthcode/integrations/tools/file_tools.py`：读取、写入和编辑工具。
- `tests/test_builtin_file_tools.py`：文件行为、安全、取消与截断测试。

修改文件：

- `tests/test_architecture_boundaries.py`：允许正式 Tool 目录并固化其依赖边界。

依赖任务：Task 2。

参考资料定位：原始需求 4、6、8.6–8.7、8.11、Task 3；原 UthCode 固定提交的路径与文件状态修复；本机 MewCode 对应文件仅作行为参考。

完成边界：路径不能逃逸工作区；现有文件修改需要成功读取且内容未变化；mtime 恢复仍能发现内容变化；编辑目标必须非空且唯一；成功副作用刷新状态。不提供历史、Diff、Permission 或跨 Application 状态。

## Task 4：实现安全 Glob 与 Grep

任务目标：提供不依赖 shell、稳定且不会经符号链接越界的代码库探索能力。

新增文件：

- `src/uthcode/integrations/tools/search_tools.py`：安全文件匹配、Python 正则搜索、固定跳过目录和稳定结果格式。
- `tests/test_builtin_search_tools.py`：模式、include、空结果、非法正则、跳过目录、符号链接、排序和截断测试。

允许修改：

- `src/uthcode/integrations/tools/workspace.py` 与其测试，仅补充搜索所需的通用安全 helper。

依赖任务：Task 2、Task 3。

参考资料定位：原始需求 4、8.6、8.11、Task 4；原 UthCode 提交 `2001d10a316d4d68371b47915c511eade261fb81`；MewCode 搜索行为。

完成边界：只返回安全文件；不跟随目录符号链接；候选逐个做词法和物理路径校验；结果稳定排序并由 Core 截断。不调用 `grep`、`find`、`rg`，不建索引或监听文件。

## Task 5：实现 Bash 进程工具

任务目标：提供在当前 OS shell 中可取消、可超时且可回收的命令执行。

新增文件：

- `src/uthcode/integrations/tools/process_tools.py`：命令执行、输出整理、超时/取消和进程树或进程组收口。
- `tests/test_builtin_process_tool.py`：工作目录、输出、退出状态、超时、取消、回收、schema 和截断测试。

依赖任务：Task 2、Task 3 的工作目录解析。

参考资料定位：原始需求 8.4、8.11、Task 5；原 UthCode 与 MewCode 的 Bash 行为；Python `asyncio` 当前平台能力。

完成边界：命令使用 Application workdir、当前用户权限和当前 OS shell；超时或取消后必须等待回收；不声称 POSIX Bash 兼容或 Sandbox。不实现黑名单、审批、环境隔离或管理员提权。

## Task 6：默认工具 Factory 与 Application Headless API

任务目标：把六个工具组合为每个 Application 独立的工具系统，并只通过 Application 暴露。

新增文件：

- `src/uthcode/integrations/tools/factory.py`：创建共享 resolver/tracker 并按固定顺序返回默认工具。
- `src/uthcode/application/tools.py`：封装 Registry/Executor 的 Application Tool Service。
- `tests/test_application_tools.py`：默认集合、隔离、注入、公共类型和执行测试。

修改文件：

- `src/uthcode/application/generation.py`：持有 Tool Service 并公开定义查询和执行方法。
- `src/uthcode/application/bootstrap.py`：按 runtime workdir 装配默认工具，支持完整替代式工具注入。
- `src/uthcode/application/__init__.py`：导出 Headless 调用所需的自有模型。
- `tests/test_application.py`、`tests/test_package.py`：组合根和回归断言。

依赖任务：Task 1–Task 5。

参考资料定位：原始需求 2.2、3.3–3.4、8.2、8.10、Task 6；当前 Application、runtime context 与 bootstrap。

完成边界：默认顺序固定；每个 Application 状态隔离；注入工具完整替代默认集合；调用方看不到 Registry、Executor 或具体 Integration Tool；不自动修改生成请求或执行 Provider ToolCall。

## Task 7：[接入主流程] 打通手动单次工具往返

任务目标：从正式 Headless Application 入口验证最小完整工具链路。

修改文件：

- `tests/test_application_tools.py`：增加 Fake Provider 两次请求的手动往返 E2E。
- `tests/test_provider_contract.py`：仅在现有断言不足时补充统一 ToolCall/ToolResult 契约回归。
- `README.md`：说明 Headless 工具调用、安全边界、手动回填以及 unsandboxed shell 语义。

允许修改的实现文件：仅在 E2E 暴露正式链路缺陷时，修改 Task 2 或 Task 6 已列实现文件。

依赖任务：Task 1–Task 6。

参考资料定位：原始需求 3.3–3.4、Task 7；Fake Provider、GenerationRequest 与 Message 公共模型。

完成边界：工具定义进入第一次请求，Fake Provider 返回文件读取调用，Application 执行后由调用方构造工具消息进入第二次请求；断言同一 runtime context、同一 call ID 和真实临时文件内容。不得增加循环、自动消息追加或 Interface 行为。

## Task 8：[端到端验证] 全量测试与边界验证

任务目标：验证 T04 与全部冻结前置能力共同工作。

修改文件：仅限测试发现的 T04 缺陷对应文件和 `README.md`，不得扩展产品范围。

依赖任务：Task 7。

参考资料定位：原始需求 Task 8、测试矩阵和验收标准；本工作包 Checklist。

完成边界：编译、T04 定向测试、配置、Provider、Application、CLI/TUI、架构、包、全量测试、依赖检查和 diff 检查通过；未授权 live Provider 测试继续跳过。不修复无关历史问题。

## Task 9：[遗留负担清理] 删除重复入口与未来占位

任务目标：确认交付仅保留一套工具契约、一个配置转换所有者和一条 Application 工具入口。

检查及按需修改范围：

- `src/`、`tests/`、`README.md` 中由 T04 引入或替代的实现、测试和文档。

依赖任务：Task 8。

参考资料定位：原始需求 12、13.7、Task 9；AGENTS.md 非兼容性原则。

完成边界：删除旧配置反向入口、重复 DTO、临时 helper、兼容层、不可达代码和无调用方扩展；扫描确认没有 MewCode/旧 UthCode 运行时依赖、LangGraph/LangChain、Pydantic Tool 模型、Interface 直连或 Sandbox 误导。不得删除历史工作包或归档用户文件；若无需代码清理，不制造无意义改动。

