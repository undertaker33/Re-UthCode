# T02-SlashCommand与默认TUI Spec

## 1. 背景

T01 已建立 UthCode 自有 Provider 契约、Headless Application、Provider Factory，以及 Fake、Anthropic、OpenAI Responses、OpenAI-compatible Provider。当前项目仍缺少正式启动入口、配置文件系统、Slash Command 和默认交互界面，调用方只能以单 Provider 配置直接使用 Python API。

本工作包在不引入 Agent Loop、Session、Tool、Permission 或其他后续能力的前提下，建立配置驱动的 Application、统一命令系统、非交互 CLI 和官方默认 Textual TUI。旧 UthCode、MewCode 与 FirstCoder只作为行为和实现证据，不成为运行时依赖，也不保留任何旧接口兼容层。

## 2. 目标

完成本工作包后，项目应具备：

1. 无子命令时启动的官方默认 Textual TUI；
2. 不依赖 Textual 的 Headless Python API 和单轮非交互 CLI；
3. 用户级与递归项目级 TOML 配置加载、合并、安全校验和用户默认模型写回；
4. 多 Provider Profile、多 Model Profile 与运行时模型切换；
5. 每次请求独立、可取消的生成句柄；
6. 唯一正式 Slash Command Registry，以及统一 Parser、Completion、Dispatcher 和结构化结果；
7. 从同一 Registry 生成的帮助、补全、Usage、别名和实现状态；
8. 基于 T01 Provider 流事件的 Markdown 流式渲染、滚动保护、命令菜单、模型选择器和双 Esc 中断；
9. 安装入口、模块入口、TUI、CLI 与 Headless API 共用同一配置和 Application 组合链；
10. 默认完全离线的自动化验证和清晰的架构边界。

## 3. 按 Task 划分的能力清单

### Task 1：更新阶段约束与入口依赖

解除本批次与旧阶段规则的直接冲突，声明 Textual、TOMLKit 和 console script，并保留所参考 FirstCoder 代码的 MIT 许可证声明。

### Task 2：建立 Application 有效配置模型

建立不可变的启动选项、配置来源、Provider Profile、Model Profile 和有效配置，分离 Provider 身份、Model Ref 与远端模型 ID，并提供单模型 Headless 构造能力。

### Task 3：实现配置发现、合并、安全与写回

实现首次用户模板、Git 根到当前目录的递归项目配置、非 Git 目录规则、物理路径去重、固定优先级、项目 Provider 安全边界和保真原子写回。

### Task 4：扩展 Application Runtime

建立独立生成句柄、模型目录、运行状态和全成全败的模型切换；保留便利流接口但统一复用正式句柄。

### Task 5：实现 Command Registry 与 Parser

建立唯一正式命令注册表、命令定义和调用模型，完成名称及别名冲突校验、Slash 输入识别、参数解析、原始 query 与分隔符语义。

### Task 6：实现 Completion、Dispatcher 与内置命令

从 Registry 生成命令和参数候选，真实区分本地输出、本地 UI 动作和 Prompt 三类命令结果，并注册本批次完整内置命令表。

### Task 7：实现默认 CLI 与 Headless exec

建立安装入口和模块入口；默认启动 TUI，非交互模式从参数或标准输入执行单轮请求，并遵守输出流与退出码约定。

### Task 8：实现 TUI 基础组件和流式渲染

建立 Topbar、Transcript、Markdown、Composer、纯状态模型、批量流式渲染与滚动跟随保护，只迁移 FirstCoder 中本批次实际需要的交互机制。

### Task 9：实现 Completion Menu、Model Picker 与双 Esc

完成两个独立弹层组件及状态、键盘控制、命令与模型选择、单活动请求约束、清屏、退出和双 Esc 取消链路。

### Task 10：[接入主流程] 接入正式启动链路

收口安装入口、模块入口、配置加载、Application、TUI、命令系统和非交互执行，删除 T01 已失效说明与被替代入口。

### Task 11：[端到端验证] 验证真实离线用户流程

从正式入口验证首次配置、Fake 模型流、命令菜单、模型切换、清屏、取消、非交互执行和配置安全失败路径。

### Task 12：[遗留负担清理] 清理重复职责和越界依赖

删除双 Registry、双配置、旧组合入口、越界导入、参考项目运行时依赖和后续能力占位，确认 README、公开导出和测试使用同一正式边界。

## 4. 非功能要求

### 4.1 环境与依赖

- 所有开发和验证使用 Conda 环境 `re-uthcode` 与 Python 3.12；
- Textual 只用于默认 TUI，TOMLKit 只用于配置 Integration；
- CLI 使用标准库参数解析，不增加另一套 CLI 框架；
- 不新增 dotenv、Rich 直依赖、DI 容器、事件总线、Session 或持久化框架；
- 默认测试不得调用真实模型服务或读取真实秘密。

### 4.2 架构边界

- Interface 只通过 Application 公共 API 工作，不导入 Core、Integration 或 Provider SDK；
- Application 用例依赖 Core，组合边界可以调用 Integration；
- Provider 构造仍只发生在既有 Integration Factory；
- Core 不依赖 Textual、TOMLKit、CLI、Application、Integration 或 Interface；
- TOML 解析树和第三方配置类型不得越过 Integration；
- Textual Widget 和事件类型不得越过 Interface。

### 4.3 配置与秘密安全

- 用户配置是唯一可信 Provider 来源；项目配置只能选择可信 Provider 并调整非秘密模型数据；
- 项目配置出现 Provider、端点、秘密来源或等价重定向字段时必须硬失败并指出来源；
- API Key 只从配置指向的进程环境变量读取，不写入文件、模型、异常、日志或测试输出；
- 首次模板不包含可用 Provider 或真实秘密，创建后终止本次启动且不联网；
- 用户默认模型写回只修改用户配置顶层选择，并保留注释、顺序和其他内容。

### 4.4 流、取消与状态

- 每次生成拥有独立取消状态，取消一个请求不得影响其他请求；
- Application 不建立全局唯一活动请求，单活动限制由 TUI 自身承担；
- Provider 成功流仍必须恰有一个合法终态；
- 流式 UI 使用有界批量刷新，终态、取消和异常前强制刷新；
- 用户主动上滚后不得被新输出强制拉回底部。

### 4.5 命令一致性

- 命令定义只有一个正式 Registry；
- 帮助、搜索、补全、Usage、别名、实现状态和参数候选均来自 Registry；
- Command Completion Menu 与 Model Picker 是独立组件和独立状态；
- 未实现命令保持可发现，并返回统一的未实现结果；
- 普通文本和非交互输入不误入 Slash Command Dispatcher。

### 4.6 可测试性与版权

- 配置、Application、命令系统、CLI 和 TUI 均具备离线自动化测试；
- Textual 交互通过 Pilot 验证，核心状态转换优先使用纯状态测试；
- 删除或隔离 TUI 后，Application 与 Headless 测试仍可运行；
- 如复制或实质性改编 FirstCoder 代码，随项目保留其 MIT 版权和许可证声明；
- 不依赖 FirstCoder 或 MewCode 包，不整体复制参考项目。

## 5. 设计骨架

正式启动与依赖方向为：

```text
Installed CLI / python -m uthcode
                 ↓
           Interface CLI
          ↙             ↘
   Textual TUI        Headless exec
          ↘             ↙
       Application Public API
        ↙                 ↘
 Core Provider Port    Composition Boundary
                              ↓
                 Config + Provider Integrations
```

配置文件由 Integration 发现、解析和安全校验，转换为 Application 自有不可变模型。Application 根据当前 Model Profile 通过既有 Provider Factory 构造 Provider，并对 Interface 暴露生成句柄、模型目录、状态、模型切换和命令系统所需信息。Interface 不接触 Provider 或配置实现细节。

Slash 输入由 Parser 解析，经 Registry 定位后交给 Dispatcher。Dispatcher 只返回 UthCode 自有的输出、UI 动作或 Prompt 结果；TUI 再负责把结构化 UI 动作适配为清屏、模型选择或退出。普通生成仍是单消息请求，不保存或回送历史。

## 6. Out of Scope

本工作包不实现：

- Agent Loop、多轮 Conversation、Run、Turn、Session 或历史浏览；
- `/new`、`/resume`、`/compact`、`/plan`、`/login`、`/memory`、`/dream`、`/do`、`/review`、`/config` 的真实业务能力；
- Tool、Permission、Context、Memory、Dream、Skill、MCP、Hook、Worktree 或 Subagent；
- Diff、Task Plan、Session Picker、Skill Picker、附件或图片粘贴；
- Provider 远端模型发现、配置热重载、项目 `.env`、OS Sandbox；
- Web、Desktop、IDE、主题系统或正式完整 TUI；
- 旧 UthCode、MewCode、FirstCoder API 或行为兼容；
- live 模型费用验收，除非用户另行明确授权。

## 7. 验收标准

### 7.1 配置与模型

- 用户配置不存在时安全创建待填模板、明确提示路径、终止启动且不联网；
- Git 仓库内按根到当前目录加载项目配置，非 Git 环境只读取当前目录项目配置；
- 同一物理配置文件只加载一次，越近当前目录的合法模型设置优先；
- 项目配置不能新增或重定向 Provider、端点或秘密来源；
- 多 Provider 和多 Model 配置可验证并形成不可变有效配置；
- 模型切换失败时运行时 Provider、当前模型和用户配置均保持不变；成功时只持久化用户顶层默认模型。

### 7.2 Application 与命令系统

- 两个生成句柄相互隔离，取消一个不影响另一个；
- 便利流接口复用正式句柄并继续拒绝非法 Provider 终态；
- Registry 拒绝所有名称与别名冲突并提供稳定解析与列表；
- Parser 准确区分普通文本、命令、参数、原始 query、分隔符、未知命令和 Usage 错误；
- 三类命令分别产生输出、结构化 UI 动作和 Prompt 结果；
- `/help`、Completion、别名、Usage 和实现状态没有第二份硬编码来源；
- 内置命令及别名、固定排序和统一未实现行为与需求一致。

### 7.3 CLI 与 TUI

- `uthcode` 默认进入 Textual TUI，`uthcode exec` 和 Python API 不启动 TUI；
- 非交互模式正确处理位置 Prompt、标准输入、工作目录、模型覆盖、stdout、stderr 和退出码；
- TUI 支持 Topbar、Transcript、Markdown、Composer、批量流式刷新和滚动保护；
- TUI 支持独立命令菜单和模型选择器、完整键盘控制、清屏、退出及双 Esc 取消；
- 生成中拒绝第二个普通请求和模型切换，但仍允许其他 Slash Command 进入 Dispatcher；
- TUI 只调用 Application 公共 API，不直接依赖 Core、Integration 或 SDK。

### 7.4 回归与范围

- T01 Provider Contract、Factory、三协议和 Headless 离线测试不退化；
- 全量离线测试、字节码编译、依赖检查和静态架构检查通过；
- README、安装入口、模块入口、公开导出和测试使用同一正式组合链；
- 不存在双 Registry、双配置、兼容层、旧入口、参考项目运行时依赖、不可达代码或后续能力占位；
- 工作包完成后仍由用户决定是否归档，不执行未经授权的 Git 提交、推送或 PR。
