# T03 System Prompt 设计 Tasks

## Worker 分组与执行顺序

| Worker | 负责 Task | Worker 内顺序 | 依赖 |
| --- | --- | --- | --- |
| W01 Core Prompt Contract Worker | Task 1—Task 2 | Task 1 → Task 2 | 无 |
| W02 Provider Mapping Worker | Task 3 | Task 3 | W01 完成并通过定向测试 |
| W03 Application Interface Worker | Task 4—Task 5 | Task 4 → Task 5 | W02 完成并通过定向测试 |
| W04 Delivery Verification Worker | Task 6—Task 8 | Task 6 → Task 7 → Task 8 | W03 完成并通过定向测试 |

长期 Worker 必须严格按 `W01 → W02 → W03 → W04` 串行派发。未收到用户对对应 Prompt 文件的明确派发时，不得实施。每个 Worker 首次执行时创建同名 Feedback；返工只能追加原 Feedback。

## Task 1：建立 Core System Prompt 模块

### 任务目标

建立当前能力范围内唯一、纯函数、不可变、可测试的中文 System Prompt。

### 新增文件

- `src/uthcode/core/prompt.py`
- `tests/test_system_prompt.py`

### 修改文件

- `src/uthcode/core/__init__.py`

### 删除文件

- 无。

### 文件职责及实施内容

- 在 Core 定义不可变 `PromptSection` 与 `SystemPromptContext`，只包含需求冻结的当前字段。
- 实现唯一公开 `build_system_prompt()`，按优先级稳定排序、忽略空内容、使用双换行连接并清理尾部空白。
- 固定五个 Section：身份、工作原则、代码质量与安全、沟通与结果真实性、当前运行环境。
- 对运行环境字段使用不会破坏 Markdown 结构的可辨识转义；构建过程不得修改输入对象。
- 从 Core 包导出稳定 Prompt API；不建立 Manager、Registry、Loader、Cache 或可变注册机制。
- 测试顺序、确定性、固定运行值、空段、不变性、特殊字符转义、静态前缀与动态后缀，以及当前能力边界。

### 依赖任务

- 无。

### 参考资料定位

- 原始需求：第 3、4、6、7、8.1—8.3、8.9、14.1 节。
- `D:\project\UthCode` 固定提交中的 `src/uthcode/prompts/`：仅参考稳定分段、顺序、空段过滤和显式上下文思想。
- `D:\project\MewCode\mewcode\prompts.py`：仅参考静态规则与动态环境分离；不得复制品牌和未来能力。

### 完成边界

- Core Prompt API 与定向测试可独立运行。
- 不接 Application、Provider 或 Interface；不实现 Tool、Permission、Plan、Memory、Hook、Skill、MCP、Subagent 或缓存。

## Task 2：替换 Core 请求中的临时 System Message 语义

### 任务目标

将 System Prompt 从普通消息中分离，并冻结普通消息合法角色。

### 新增文件

- 无。

### 修改文件

- `src/uthcode/core/provider.py`
- `tests/test_provider_contract.py`

### 删除文件

- 无。

### 文件职责及实施内容

- 为 `GenerationRequest` 增加唯一独立 `system_prompt` 字段，支持 `None` 或非空字符串。
- 将字段纳入字典/JSON 序列化与恢复，保持请求深度不可变。
- 冻结 `Message` 合法角色为 `user`、`assistant`、`tool`；拒绝 `system`、未知角色和非法类型。
- 不使用 metadata 保存 Prompt，不新增 instructions、system_message、developer_prompt 等同义入口。
- 测试无 Prompt、合法 Prompt、空白/非法类型、JSON round-trip、深度不可变和非法角色矩阵。

### 依赖任务

- Task 1 完成并通过定向测试。

### 参考资料定位

- 原始需求：第 2.1、2.5、4、8.4—8.5、14.2 节。
- `src/uthcode/core/provider.py` 与 `tests/test_provider_contract.py` 当前 contract。

### 完成边界

- Core 请求协议完成正式替换。
- 不修改 Provider Response/Event、Tool Part、Application 或 Integration；不保留旧角色兼容路径。

## Task 3：重写三种 Provider 的 System Prompt 映射

### 任务目标

一次性删除三个 Integration 对 Core System Message 的处理，改用统一请求字段。

### 新增文件

- 无。

### 修改文件

- `src/uthcode/integrations/providers/anthropic.py`
- `src/uthcode/integrations/providers/openai_responses.py`
- `src/uthcode/integrations/providers/openai_compat.py`
- `tests/test_anthropic_integration.py`
- `tests/test_openai_responses_integration.py`
- `tests/test_openai_compat_integration.py`

### 删除文件

- 无。

### 文件职责及实施内容

- Anthropic：把独立 Prompt 映射到顶层 `system`，普通历史只序列化合法 Message。
- Responses：把独立 Prompt 映射到顶层 `instructions`，输入项中不生成 System Message。
- Chat：有 Prompt 时在厂商消息首位生成唯一 `role=system`，无 Prompt 时不生成；不改用 developer role。
- 删除从 `request.messages` 扫描、提取或透传 Core System Message 的分支。
- 每个协议测试有/无 Prompt、普通历史顺序、Tool Result、Reasoning/Native Item、Usage、错误、显式取消、Task 取消和流关闭。

### 依赖任务

- Task 2 完成；三个 Provider 的既有定向测试先保持通过。

### 参考资料定位

- 原始需求：第 1.6、2.4、4、5、8.8、10、14.4 节。
- Anthropic Messages API 官方文档：顶层 System Prompt。
- OpenAI Responses API 官方文档：请求级 instructions。
- OpenAI Chat Completions 官方文档：兼容消息中的 system role。
- T01-2 两个 Feedback：既有原生 SDK 映射、流关闭、错误与取消证据。

### 完成边界

- 三协议请求形状使用统一 Core 字段，既有响应和流语义无退化。
- 不修改 Factory、SDK 版本、Provider 公共事件、Native Item、Usage 或取消模型；不启用缓存。

## Task 4：建立 Application 运行上下文与权威请求准备

### 任务目标

让 Application 在每次请求前根据统一运行上下文和当前模型身份构建 Prompt。

### 新增文件

- `src/uthcode/application/runtime_context.py`

### 修改文件

- `src/uthcode/application/generation.py`
- `src/uthcode/application/bootstrap.py`
- `src/uthcode/application/__init__.py`
- `tests/test_application.py`
- `tests/test_application_runtime.py`

### 删除文件

- 无。

### 文件职责及实施内容

- 定义不可变 `ApplicationRuntimeContext`，持有绝对规范化 workdir、平台名、平台版本和创建时解析的当前日期。
- 提供系统默认构造和测试固定值构造，不读取 TOML、秘密或项目指令。
- `UthCodeApplication` 每次 `start_generation()` 读取当前模型选择与 ProviderIdentity，构造 Core Context 和权威 Prompt，再复制输入请求创建 Handle。
- 调用方请求已有 Prompt 时明确拒绝；Prompt 构建失败时 Provider 不得被调用。
- `stream_generation()` 继续复用 `start_generation()`；模型切换成功刷新下一请求身份，构造或写回失败保持旧身份。
- `create_application()` 接收独立 RuntimeContext，不修改 `EffectiveConfig` 或配置格式。
- 测试固定环境、Fake Headless、输入不变、冲突拒绝、构建失败、模型切换成功/失败和两个 Handle 取消隔离。

### 依赖任务

- Task 3 完成并通过三协议定向测试。

### 参考资料定位

- 原始需求：第 2.2、3.3、5、8.6—8.7、9、14.3 节。
- T01/T02 Application、配置、模型切换和取消 Feedback。
- `src/uthcode/application/generation.py`、`bootstrap.py`、`configuration.py` 当前边界。

### 完成边界

- Application 成为运行上下文和 Prompt 注入的唯一组合入口。
- 不按 Provider 名称分支，不修改 `configuration.py`、TOML、Provider Factory、终态或取消公共语义。

## Task 5：统一 CLI、TUI 与 Headless 的运行上下文

### 任务目标

移除 TUI 独立 workdir 所有权，使所有正式入口组合同一个 ApplicationRuntimeContext。

### 新增文件

- 无。

### 修改文件

- `src/uthcode/interfaces/cli.py`
- `src/uthcode/interfaces/tui/app.py`
- `tests/test_cli.py`
- `tests/test_tui.py`
- `README.md`

### 删除文件

- 无。

### 文件职责及实施内容

- CLI 解析一个绝对规范化 workdir，并同时用于配置发现和 RuntimeContext。
- TUI 从 Application 读取 workdir 用于 Topbar，删除构造与启动函数中的第二份 cwd 所有权。
- 确保 `uthcode exec`、默认 TUI 和 Embedded Headless 均由 Application 注入 Prompt；Interface 不导入 Core Prompt API。
- 更新 README 的正式 Python、CLI 和 TUI 用法，删除普通 System Message 示例，不承诺未来能力。
- 测试默认 cwd、显式 `--cwd`、stdin/位置 Prompt、Topbar 与 Fake 请求一致、模型 Picker 切换后 Prompt 身份刷新，以及现有流式刷新、双 Esc、退出码与 stdout/stderr 回归。

### 依赖任务

- Task 4 完成并通过 Application 定向测试。

### 参考资料定位

- 原始需求：第 2.3、3.3、5、6、9.5、14.5 节。
- T02 W03 Interface Feedback 及其返工记录。
- `src/uthcode/interfaces/cli.py`、`src/uthcode/interfaces/tui/app.py` 当前实现。

### 完成边界

- 三种正式入口共用相同 Application Prompt 路径和 workdir 事实。
- 不修改 Widget 核心渲染、Slash Command、配置规则，不增加 CLI Prompt 覆盖参数或 TUI 设置页面。

## Task 6：[接入主流程] 收口正式调用链

### 任务目标

证明全部正式生成入口只通过 Application 构建一次 System Prompt，并删除被替代旧入口。

### 新增文件

- 原则上无。

### 修改文件

- `tests/test_architecture_boundaries.py`
- `tests/test_package.py`
- `README.md`
- 仅在发现接入缺陷时，窄幅修改 Task 1—Task 5 已列文件。

### 删除文件

- 无物理文件；删除旧 System Message、Interface Prompt、Provider 历史提取和配置运行字段语义。

### 文件职责及实施内容

- 固化 `CLI/TUI/Headless → ApplicationRuntimeContext → UthCodeApplication → Core Prompt → GenerationRequest → ProviderPort` 唯一链路。
- 增加正式 Bootstrap Fake 请求、无 Interface Headless 子进程、根包无副作用导入和 AST 依赖边界测试。
- 确认 Prompt 模块无反向依赖，Interface 不导入 Core/Integration/SDK。
- README 只展示正式调用入口。

### 依赖任务

- Task 1—Task 5 全部完成并通过各自定向测试。

### 参考资料定位

- 原始需求：第 3.3、6、9、11 Task 6、14 节。
- 当前 `tests/test_architecture_boundaries.py`、`tests/test_package.py`。

### 完成边界

- 正式调用链唯一且架构边界可自动验证。
- 不实现任何后续能力，不修改 Provider Event 或配置格式。

## Task 7：[端到端验证] 验证三协议与全部正式入口

### 任务目标

以离线可复现测试证明 System Prompt 从真实入口到三种厂商请求形状完整贯通。

### 新增文件

- 无。

### 修改文件

- 原则上无；只允许修复 Task 1—Task 6 范围内的缺陷及对应测试。

### 删除文件

- 无。

### 文件职责及实施内容

- 验证 Embedded Headless + Fake 记录完整 Prompt。
- 验证 `uthcode exec` + Fake 的 workdir 和模型身份。
- 验证 Textual TUI + Fake 的 Topbar、请求和模型切换一致。
- 验证 Anthropic 顶层 system、Responses 顶层 instructions、Chat 首项 system message。
- 回归三协议 Reasoning、Tool、Native Item、Usage、错误、取消和关闭。
- 执行定向测试、全量离线测试、compileall 和 pip check；live Provider 测试保持跳过。

### 依赖任务

- Task 6 完成并通过主流程与架构定向测试。

### 参考资料定位

- 原始需求：第 11 Task 7、第 12 测试矩阵、第 14 节。
- 本工作包 Checklist 的 Task 7 命令。

### 完成边界

- 所有离线验收有精确命令和结果证据。
- 不进行真实费用请求，不设计缓存 API，不进行大规模 Prompt 质量评测。

## Task 8：[遗留负担清理] 删除临时语义和未来占位

### 任务目标

确认 T03 没有留下双轨 Prompt、旧角色、重复上下文、兼容层或未来能力占位。

### 新增文件

- 无。

### 修改文件

- 只在扫描发现本任务产生的残留时修改 Task 1—Task 7 已列文件。

### 删除文件

- 删除被新协议替代的旧代码、旧测试调用和不可达分支；不删除历史工作包或范围外文件。

### 文件职责及实施内容

- 扫描 Core/Test 中的 `Message(role="system")`，逐项确认 Chat Integration 厂商映射是唯一合法残留。
- 扫描未来能力字段、Prompt Manager/Registry/Loader/Cache、Interface Prompt 正文、配置运行字段、旧品牌与推广文本。
- 确认没有 Alias、Facade、Shim、Fallback、双轨 API、重复职责或仅为兼容早期实现存在的逻辑。
- 重新执行 compileall、全量测试、diff 检查和工作区状态检查。

### 依赖任务

- Task 7 全部通过。

### 参考资料定位

- 原始需求：第 1.2、1.4—1.5、3.2、6、11 Task 8、13—15 节。
- `AGENTS.md` 与 `SRe-AGENTS.md` 非兼容性原则。

### 完成边界

- 扫描结果逐项解释并写入 W04 Feedback，所有当前范围遗留负担清零。
- 不归档工作包，不执行 Git commit、push、PR、merge、tag 或 release。
