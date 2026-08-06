# T02-SlashCommand与默认TUI Tasks

## Worker 分组与执行规则

任务只能由用户通过对应 Prompt 文件显式派发。每组由同一 Worker 按组内顺序严格串行完成；未完成前置组并经用户决定继续时，不得开始后续组。

| Worker 组 | Task | 串行理由 |
| --- | --- | --- |
| W01 Configuration Runtime Worker | Task 1—Task 4 | 阶段规则、有效配置、配置 Integration 与 Application Runtime 共同冻结正式组合边界 |
| W02 Command System Worker | Task 5—Task 6 | Registry、Parser、Completion、Dispatcher 与内置命令必须由同一 Worker 保持单一来源 |
| W03 Interface Delivery Worker | Task 7—Task 12 | CLI、TUI、正式接入、端到端验证与清理必须在配置和命令系统稳定后统一收口 |

Worker 依赖顺序固定为 W01 → W02 → W03。所有 Python、安装和测试命令均使用 Conda 环境 `re-uthcode`。不得修改旧 `D:\project\UthCode`、`D:\project\MewCode` 或外部 FirstCoder；不得自动归档工作包。

## Task 1：更新阶段约束与入口依赖

### 任务目标

解除旧阶段规则中与 T02 直接冲突的后置声明，准备配置、默认 TUI 和正式 CLI 所需依赖、入口与许可证。

### 新增文件

- `LICENSES/FirstCoder-MIT.txt`：保存 FirstCoder 冻结 Commit 的完整 MIT 许可证和版权声明。

### 修改文件

- `SRe-AGENTS.md`：只调整 Slash Command、默认 TUI 和本任务配置规则的阶段定位，补充 Interface 隔离、递归配置与项目安全边界；不得顺带改写其他治理规则；
- `pyproject.toml`：声明 Textual、TOMLKit、`uthcode` console script 及测试实际需要的依赖范围。

### 删除文件

无。

### 依赖任务

无。

### 参考资料定位

- 原始需求第 1、3、11、12 节；
- `SRe-AGENTS.md` 第 5、6、8、12、13 节；
- Textual 8.2.8 与 TOMLKit 0.15.0 的 PyPI 发布资料；
- FirstCoder Commit `095787b888e36701656e66ff04a282f300e237dc` 的 `LICENSE`。

### 完成边界

- editable install 与依赖检查通过；
- console script 指向本批次将实现的正式 CLI 入口；
- 不创建命令、配置、TUI 或后续能力占位模块；
- 不修改 `AGENTS.md` 中用户新增的 UTH 禁用说明。

## Task 2：建立 Application 有效配置模型

### 任务目标

建立 UthCode 自有的不可变多 Provider、多 Model 配置模型，作为配置 Integration、Application Runtime 和 Headless 调用方的稳定边界。

### 新增文件

- `src/uthcode/application/configuration.py`：定义启动选项、配置来源、Provider Profile、Model Profile 和 Effective Config；分离 Profile ID、Model Ref 与远端模型 ID；校验引用关系、Provider 种类、模型选择和数值参数；提供单模型 Headless 构造入口；
- `tests/test_configuration.py`：覆盖不可变性、标识分离、引用校验、单模型构造和第三方类型隔离。

### 修改文件

- `src/uthcode/application/__init__.py`：公开调用方所需的 Application 配置模型，不导出 Integration 或 TOMLKit 类型。

### 删除文件

- 删除被新 Effective Config 取代且没有真实调用方的 T01 临时配置公开导出；不得保留双轨配置 API。

### 依赖任务

Task 1。

### 参考资料定位

- 原始需求第 2.3、5.3—5.6、8、9 节；
- T01 `integrations/providers/config.py` 与 Provider Factory 测试；
- 本工作包 Spec 的配置与架构边界。

### 完成边界

- 本 Task 只定义纯 Application 模型，不读取文件、不读取环境变量、不构造 Provider；
- 配置对象深度不可变，异常和 `repr` 不包含秘密值；
- 不为 T01 临时单 Provider 公共接口保留 Adapter、别名或第二个组合入口。

## Task 3：实现配置发现、合并、安全与写回

### 任务目标

将用户和项目 TOML 转换为 Application Effective Config，保证首次初始化、递归发现、固定优先级、物理去重、项目安全边界和用户默认模型保真写回。

### 新增文件

- `src/uthcode/integrations/config/__init__.py`：向 Application 组合边界提供配置加载与模型写回能力，不向 Interface 暴露 TOMLKit；
- `src/uthcode/integrations/config/template.py`：定义安全待填用户模板，所有 Provider、Model 和秘密来源保持注释或明显占位；
- `src/uthcode/integrations/config/loader.py`：原子创建首次模板并停止；识别 `.git` 目录或文件；发现 Git 根到 cwd 的配置链；非 Git 时只读取 cwd；规范化、解析链接、Windows 大小写归一并去重；解析、分层合并、项目安全校验、CLI 覆盖与 Effective Config 构造；
- `src/uthcode/integrations/config/writer.py`：通过 TOMLKit 和同目录临时文件原子修改用户配置顶层模型，保留注释、表顺序和其他内容。

### 修改文件

- `tests/test_configuration.py`：增加模板、递归层级、非 Git、worktree、去重、优先级、项目安全、无效引用、TOML 保真、原子失败和秘密脱敏矩阵。

### 删除文件

无。

### 依赖任务

Task 2。

### 参考资料定位

- 原始需求第 5.3—5.7、9、10.1、11.2、13 节；
- Python 文件系统原子替换与路径规范化语义；
- TOMLKit 0.15 API；
- T01 Provider 配置与构造约束。

### 完成边界

- 用户配置不存在时创建模板、报告路径并终止，不构造 Provider或发起网络请求；
- 项目配置出现 Provider 表、端点、秘密来源、Key 或等价重定向字段时硬失败并包含文件路径和字段；
- 不加载 `.env`，不向上搜索非 Git 项目配置，不写项目配置；
- TOMLKit 类型和解析树不进入 Application 模型。

## Task 4：扩展 Application Runtime

### 任务目标

用 Effective Config 建立正式 Application，提供每次请求独立的生成句柄、模型目录、状态和全成全败模型切换。

### 新增文件

- `tests/test_application_runtime.py`：覆盖独立句柄、取消隔离、模型目录、状态、Provider 构造失败、写回失败、成功切换和状态原子性。

### 修改文件

- `src/uthcode/application/generation.py`：增加独立 Generation Handle；每次生成创建独立取消状态；句柄提供事件流、幂等取消和取消状态；便利流接口统一复用句柄；继续执行 Provider 终态校验；Application 提供当前 Model、Model Catalog、Provider 身份和安全状态；
- `src/uthcode/application/bootstrap.py`：以 Effective Config 为唯一长期输入；将当前 Model Profile 组合为既有 Provider Config；通过唯一 Provider Factory 构造；注入 Provider builder 和用户模型 writer 以验证失败回滚；提供 Application 配置加载门面；
- `src/uthcode/application/__init__.py`：导出正式 Headless API、配置加载 API、生成句柄和调用方必需模型；
- `tests/test_application.py`：迁移 T01 Application 用例到正式边界，保留非法终态和显式取消回归；
- `tests/test_provider_factory.py`：确认 Provider Factory 仍是唯一构造边界。

### 删除文件

- 删除已被 Effective Config 组合入口取代的 T01 单 Provider bootstrap 路径和失效测试；不得保留兼容包装。

### 依赖任务

Task 3。

### 参考资料定位

- 原始需求第 2.3、5.1—5.2、5.6—5.7、9、10.2、10.4 节；
- T01 `application/generation.py`、`application/bootstrap.py` 与 Provider Factory；
- 本工作包 Spec 的流与状态要求。

### 完成边界

- Application 不保存全局唯一活动请求；两个句柄的取消互不影响；
- 模型切换严格按验证、候选构造、用户配置写回、内存状态替换顺序执行；任一步失败时三者均不改变；
- Application 用例不按 Provider 名称分支，Provider 构造不绕过 Integration Factory；
- 不修改 Core Provider 契约，不引入 Session、Run、Turn 或 Agent Loop。

## Task 5：实现 Command Registry 与 Parser

### 任务目标

建立唯一正式命令定义源和准确、可独立测试的 Slash Command 调用模型。

### 新增文件

- `src/uthcode/application/commands/models.py`：定义命令种类、可用状态、参数规格、调用结果、结构化 UI Action、Command Outcome 和补全候选；所有类型为 UthCode 自有模型；
- `src/uthcode/application/commands/registry.py`：公开稳定注册、解析和列表接口；校验 canonical、alias、非法名称、大小写与重复冲突；保持稳定命令顺序；
- `src/uthcode/application/commands/parser.py`：识别普通文本与 Slash 输入；通过 Registry 解析 canonical 和 alias；使用 `shlex` 处理参数和引号；保持原始 query；支持 `--`、未知命令和 Usage 错误；
- `src/uthcode/application/commands/__init__.py`：导出命令系统的正式 Application API；
- `tests/test_command_registry.py`：覆盖注册、冲突、别名、隐藏与稳定列表；
- `tests/test_command_parser.py`：覆盖普通文本、`/`、大小写、参数、引号、query、分隔符、未知命令和 Usage 错误。

### 修改文件

- `src/uthcode/application/__init__.py`：按调用方需要公开命令 API，不导出 Textual 类型。

### 删除文件

无。

### 依赖任务

Task 4。

### 参考资料定位

- 原始需求第 5.8—5.10、8、9、10.3 节；
- `D:\project\MewCode\mewcode\commands\registry.py` 与 `parser.py`，仅作冲突校验和解析思路参考；
- 本工作包 Spec 的命令一致性要求。

### 完成边界

- `application/commands` 不依赖 Textual、MewCode、Provider SDK 或未来 Skill Loader；
- `/` 本身不执行命令，普通文本不进入 Dispatcher；
- query 不被 `shlex` 重组；
- 不创建第二个 Registry、UI Widget 或未来命令 handler 占位。

## Task 6：实现 Completion、Dispatcher 与内置命令

### 任务目标

从唯一 Registry 生成帮助和补全，完成三类命令的真实结构化分发，并注册全部 T02 内置命令及状态。

### 新增文件

- `src/uthcode/application/commands/completion.py`：按 canonical 和 alias 搜索、canonical 去重、help 固定最后、未实现标记、Usage、静态参数和动态参数候选；模型候选读取 Application Model Catalog；
- `src/uthcode/application/commands/dispatcher.py`：执行 LOCAL、LOCAL_UI 和 PROMPT handler；统一成功、Usage、未知、未实现与执行错误结果；不接触 Widget；
- `src/uthcode/application/commands/builtins.py`：建立唯一内置 Registry；实现 help、clear、model、status、quit；为其余命令只登记明确的未实现元数据；`models` 仅作为 model alias；
- `tests/test_command_completion.py`：覆盖 `/`、`/c`、help 排序去重、隐藏、未实现、Usage、静态与动态候选；
- `tests/test_command_dispatcher.py`：使用合成命令分别证明三类结果；覆盖内置命令、模型切换、错误和统一未实现文本。

### 修改文件

- `src/uthcode/application/commands/__init__.py`：公开 Completion、Dispatcher 和 built-in Registry 构造入口；
- `src/uthcode/application/__init__.py`：只转出 Interface 和 Headless 调用方需要的命令能力。

### 删除文件

- 删除实现过程中产生的第二份命令列表、帮助列表、候选列表或按命令拆分但没有真实职责的空 handler。

### 依赖任务

Task 5。

### 参考资料定位

- 原始需求第 5.8—5.12、8、9、10.3 节；
- MewCode `completion.py` 与 `handlers`，只参考交互意图；固定八项截断、UI Controller 和 Session 耦合均不得迁移；
- Application Runtime 的 Model Catalog 与模型切换 API。

### 完成边界

- `/help`、Completion、Usage、alias 和实现状态均由同一 Registry 生成；
- LOCAL_UI 只返回 Clear Transcript、Open Model Picker、Quit Interface 等 UthCode 结构化动作；
- 未实现内置命令不执行占位业务，统一返回规定结果；
- 不引入 Textual、Session、Skill、Context、Memory 或 Agent Loop。

## Task 7：实现默认 CLI 与 Headless exec

### 任务目标

建立 `uthcode` 与 `python -m uthcode` 正式入口，默认进入 TUI，并提供不加载 Textual App 的单轮非交互执行。

### 新增文件

- `src/uthcode/__main__.py`：调用 Interface CLI 主函数并返回退出码；
- `src/uthcode/interfaces/__init__.py`：保持轻量 Interface 命名空间；
- `src/uthcode/interfaces/cli.py`：使用 `argparse` 解析默认启动和 `exec`；处理 cwd、model、位置 Prompt、stdin、配置初始化/错误、事件输出、Ctrl+C 与退出码；通过可注入 runner 测试默认 TUI 启动；
- `tests/test_cli.py`：覆盖 console/module 入口、默认 TUI runner、位置 Prompt、stdin、空输入、cwd、临时 model 覆盖、输出流、配置错误、Provider 错误和取消。

### 修改文件

无。

### 删除文件

无。

### 依赖任务

Task 6。

### 参考资料定位

- 原始需求第 3、5.1、5.14、9、10、12 Task 7 节；
- Application 正式配置加载与 Generation Handle API；
- Python `argparse`、stdin/stdout/stderr 约定。

### 完成边界

- `exec` 中以 `/` 开头的文本作为普通 Prompt；
- `exec` 不实例化 Textual App、不输出 ANSI TUI 控制序列、不持久化 CLI model 覆盖；
- Interface 不导入 Core、Integration 或 Provider SDK；
- 不增加其他 CLI 子命令或兼容旧入口。

## Task 8：实现 TUI 基础组件和流式渲染

### 任务目标

选择性重写 FirstCoder 的视觉与交互机制，建立只依赖 Application 的最小默认 TUI 基础视图、状态和流式渲染。

### 新增文件

- `src/uthcode/interfaces/tui/state.py`：定义当前需要的 Transcript Entry、Transcript、Stream Render、Scroll Follow 和 Esc Arm 状态；只包含用户、助手、推理、命令、系统、错误六类；
- `src/uthcode/interfaces/tui/widgets.py`：实现 Topbar、可控选择的 Markdown、Enter 发送/Shift+Enter 换行 Composer 和基础 Transcript Widget；删除附件、Provider、Session、Tool 和 Permission 耦合；
- `src/uthcode/interfaces/tui/rendering.py`：将 Application Provider Events 批量转换为 Transcript；以约 0.2 秒刷新；终态、取消、异常强制 flush；简洁渲染 reasoning；安全观察 Markdown 异步更新取消；
- `src/uthcode/interfaces/tui/tui.tcss`：基于 FirstCoder 视觉基线重写当前布局，只保留本任务实际存在的选择器；
- `tests/test_tui.py`：覆盖纯状态、组件、Composer、批量流、终态 flush、Markdown 选择和滚动跟随。

### 修改文件

- `LICENSES/FirstCoder-MIT.txt`：如实际改编范围需要，确认许可证内容完整，不改变上游声明。

### 删除文件

无。

### 依赖任务

Task 7。

### 参考资料定位

- 原始需求第 1.4、5.13、6、9、12 Task 8 节；
- FirstCoder 冻结 Commit 的 `tui.py`、`tui_widgets.py`、`tui_state.py`、`tui.tcss` 和测试；
- Textual 8.2.8 Markdown、TextArea、VerticalScroll、Timer 与 Pilot API。

### 完成边界

- 不整体复制 FirstCoder；不迁移 Tool、Permission、Diff、Task Plan、Session、Skill、附件或其 Provider/Agent 逻辑；
- 流式更新不为每个 token 重建 Widget；用户上滚后不被强制到底；
- TUI 模块只导入 Application 公共 API 和 Textual；
- 本 Task 不接入命令菜单或模型 Picker。

## Task 9：实现 Completion Menu、Model Picker 与双 Esc

### 任务目标

完成两个独立弹层、TUI 编排、普通生成、Slash Command、模型切换、清屏、退出和双 Esc 取消。

### 新增文件

- `src/uthcode/interfaces/tui/completion.py`：Command Completion Menu Widget 与独立状态；消费 Application Candidates；支持滚动、Up/Down、Esc、Tab 和 Enter；
- `src/uthcode/interfaces/tui/picker.py`：独立通用 Picker 状态和 Model Picker Widget；展示 Model Ref、label、Provider 与当前项；支持键盘选择和关闭；
- `src/uthcode/interfaces/tui/app.py`：编排布局、普通输入、命令解析分发、结构化 UI Action、流式 worker、单活动普通请求、生成中模型切换拒绝、双 Esc、滚动、清屏与退出；
- `src/uthcode/interfaces/tui/__init__.py`：公开默认 TUI 启动入口。

### 修改文件

- `tests/test_tui.py`：使用 Textual Pilot 覆盖弹层优先级、菜单补全、Picker、模型切换、普通流、拒绝并发、清屏、退出和双 Esc 取消；
- `src/uthcode/interfaces/cli.py`：默认 runner 接入正式 TUI 启动入口，不改变 `exec` 的 Headless 性质。

### 删除文件

- 删除 Completion 与 Picker 之间共享的错误状态、TUI 硬编码命令列表和任何未来 Picker 占位。

### 依赖任务

Task 8。

### 参考资料定位

- 原始需求第 5.7、5.11—5.13、9、10、12 Task 9 节；
- FirstCoder 冻结 Commit 的 Picker、Esc、流 worker 与 Pilot 测试；
- Application Command、Model Catalog、模型切换与 Generation Handle API。

### 完成边界

- Completion Menu 与 Model Picker 为不同模块、Widget 和状态对象；
- Esc 优先关闭当前弹层，无弹层且生成中才进入一秒双击取消窗口；
- `/clear` 只清 Transcript，`/new` 仍未实现；
- 下一次普通请求不携带上一次历史；不引入 Session 或全局活动请求到 Application。

## Task 10：[接入主流程] 接入正式启动链路

### 任务目标

从安装入口收口配置、Application、命令系统、TUI 和非交互执行，确保所有公开说明和调用方使用同一正式组合链。

### 新增文件

无。

### 修改文件

- `README.md`：替换 T01 已失效的无 CLI/TUI 说明；记录 Conda 安装、首次配置模板、配置结构、安全边界、TUI、Slash Command、模型切换、`exec` 和 Headless Python API；示例不得包含真实秘密；
- `src/uthcode/application/__init__.py`：复核并收口正式公开导出；
- `src/uthcode/interfaces/cli.py`、`src/uthcode/interfaces/tui/__init__.py`：确保 console script、模块入口和默认 TUI 使用同一配置/Application 组合链；
- 相关测试：补齐正式入口 smoke 和公开示例验证。

### 删除文件

- 删除 T01 被替代的单 Provider README 示例、临时 bootstrap、重复导出和不可达入口。

### 依赖任务

Task 9。

### 参考资料定位

- 原始需求第 3、9、10、12 Task 10、14 节；
- 本工作包前序 Task 的正式 API；
- T01 README 与 Application 公开导出。

### 完成边界

- `uthcode`、`uthcode exec`、`python -m uthcode` 和 Python API 共享同一 Effective Config 与 Application；
- Interface 仍不直接导入 Core 或 Integration；
- README 只描述已交付能力，不承诺 Out of Scope 功能；
- 不保留新旧配置或 bootstrap 双轨。

## Task 11：[端到端验证] 验证真实离线用户流程

### 任务目标

从正式入口证明首次配置、默认 TUI、Slash Command、Fake 流、模型切换、取消、非交互执行和安全失败路径形成完整离线闭环。

### 新增文件

无。

### 修改文件

- `tests/test_configuration.py`、`tests/test_application_runtime.py`、`tests/test_cli.py`、`tests/test_tui.py`：仅补齐端到端场景发现的本任务测试缺口；
- `tests/test_architecture_boundaries.py`：验证删除或隔离 TUI 后 Headless 仍可运行，并阻止 Interface 越界依赖；
- 本任务范围内源码：只修复端到端验证暴露的问题。

### 删除文件

无。

### 依赖任务

Task 10。

### 参考资料定位

- 原始需求第 12 Task 11、13、15 节；
- README 正式用户流程；
- 全部前序 Task 的 Checklist。

### 完成边界

- 首次配置和 Fake 用户流程全程离线；
- live Provider 测试继续保持显式授权与默认跳过，不在本 Task 自动运行；
- 全量 pytest、compileall、pip check 和正式入口 smoke 全部通过；
- 只修复当前工作包缺陷，不扩展到后续能力。

## Task 12：[遗留负担清理] 清理重复职责和越界依赖

### 任务目标

审查并删除 T02 引入或暴露的重复配置、重复命令来源、旧入口、越界导入、参考项目耦合、不可达代码和未来占位。

### 新增文件

无。

### 修改文件

- `tests/test_architecture_boundaries.py`：补齐单 Registry、单配置模型、Interface/Application/Core/Integration 边界、禁止依赖、禁止未来目录和正式入口检查；
- `README.md`、`src/uthcode/**`、`tests/**`：只删除审查发现的重复或越界内容并修复相应测试。

### 删除文件

- 删除兼容旧类、旧 API、旧配置或 T01 临时 bootstrap 的 Adapter、Facade、别名、包装层和双轨逻辑；
- 删除 TUI 中第二份命令列表、帮助列表、模型列表或与 Application 重复的配置解析；
- 删除 FirstCoder/MewCode import、Tool/Permission/Session/Skill/MCP 等未来能力占位和不可达代码。

### 依赖任务

Task 11。

### 参考资料定位

- `AGENTS.md` 非兼容性原则与固定目录依赖；
- `SRe-AGENTS.md` 重做、后置能力和停止条件；
- 原始需求第 12 Task 12、14、15 节；
- 本工作包 Spec 的 Out of Scope 与验收标准。

### 完成边界

- built-in Registry、Effective Config 和 Application bootstrap 各只有一个正式来源；
- Core 不导入 Textual/TOMLKit，Interface 不导入 Core/Integration，Application 命令层不导入 Textual；
- 不存在 dotenv、旧项目运行时依赖、FirstCoder 包依赖或后续能力占位；
- 全量离线测试、编译、依赖检查、静态检查和 diff 检查通过；
- 不执行 Git 提交、推送、PR 或工作包归档。
