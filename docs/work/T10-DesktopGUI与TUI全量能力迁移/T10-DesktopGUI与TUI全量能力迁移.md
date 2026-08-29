# UthCode T10：Desktop GUI 与 TUI 全量能力迁移任务书

> 状态：可实施
> 任务：T10
> 任务类型：Interface 迁移 / Desktop 产品化 / 本地进程边界
> 代码事实基线：`c46f3654b5b38d255027eda689befdbd1e5f832c`
> 生成日期：2026-08-29
> 目标仓库：`undertaker33/Re-UthCode`

---

## 1. 任务定位

T10 的目标不是“给 UthCode 套一个 Electron 聊天窗口”，也不是把现有 `prompt_toolkit` TUI 翻译成 React。

本任务要完成的是：

> **在不改变现有 Agent Core / Application 产品语义的前提下，为 UthCode 增加一个面向普通用户的 Windows Desktop Interface，并以 GUI-native 的方式完整承载当前 TUI 已经真实支持的用户能力。**

完成后的产品关系固定为：

```text
普通用户主要入口
UthCode Desktop
Electron + React/TypeScript
        │
        │ 本机私有进程协议
        ▼
Python UthCode Runtime
        │
        ▼
Application
        │
        ▼
Core

同时继续保留：

uthcode
→ TUI

uthcode exec
→ Headless CLI
```

T10 **新增 Desktop Interface，不删除、不替换 Python TUI / CLI 的正式入口**。

---

## 2. 事实基线与需求优先级

### 2.1 唯一代码事实基线

所有实施判断以：

```text
c46f3654b5b38d255027eda689befdbd1e5f832c
```

为唯一源码基线。

该 Commit 已包含 F01 的 TUI 回复链路与 Session 恢复修复。

不得用：

- 更早任务书；
- 历史聊天中的旧结构；
- 旧 TUI 行为；
- 外部 Agent 产品的功能；
- HTML 原型中的模拟数据；

替代当前代码事实。

### 2.2 需求来源优先级

发生冲突时固定按以下顺序处理：

```text
① 当前基线源码 / 测试 / 已冻结项目规则
        ↓
② 本任务已拍板的用户决策与本任务硬约束
        ↓
③ ./uthcode-desktop-ui-prototype-v5.html
        ↓
④ Codex Desktop / DeepSeek Harness
```

其中：

- HTML 是 **GUI 工程与交互参考**；
- Codex Desktop / DeepSeek Harness 是 **成熟机制参考**；
- 二者都不是 UthCode 功能事实来源。

任何参考来源中存在、但当前 UthCode 没有的能力，一律不得进入 T10。

---

## 3. 已冻结用户决策

### D-T10-01：GUI 配置范围

采用已拍板的 **1B**：

> 增加一个窄的、面向当前真实用户配置的 Application 配置管理 use case，使普通用户能够在 GUI 内完成当前 `config.toml` 已支持配置的读取与修改。

不是：

- 通用 Settings Framework；
- 任意 TOML 编辑器；
- 动态 schema 平台；
- Plugin Settings 系统。

允许 GUI 管理的共享 UthCode 配置只包括当前真实字段：

```text
root
├─ default_model
├─ default_permission_mode
├─ providers
│  └─ <provider_profile_id>
│     ├─ kind
│     ├─ base_url
│     └─ api_key
└─ models
   └─ <model_ref>
      ├─ provider
      ├─ remote_id
      ├─ display_name
      ├─ context_window
      ├─ max_output_tokens
      └─ reasoning_effort
```

其中：

```text
Provider kind:
fake
anthropic
openai_responses
openai_compat

reasoning_effort:
none
minimal
low
medium
high
xhigh
max
```

`default_permission_mode` 只允许：

```text
default
auto
```

不得把 `full_access` 保存成默认权限模式。

### D-T10-02：首发平台

采用已拍板的 **2A**：

> T10 正式打包、Installer、真实 E2E 与交付验收以 **Windows 11 x64** 为准。

本轮不承担：

- macOS 打包；
- notarization；
- Linux 安装包；
- 三平台 E2E；
- 三平台发行维护。

实现时避免无意义地写死 Windows 之外无法移植的内部结构，但不得为了未来多平台增加当前没有调用方的抽象。

### D-T10-03：能力范围

冻结原则：

> **只实现当前 UthCode 已经支持的功能的 GUI 表达。**

当前不存在的能力：

```text
Subagent
Multi-Agent
Git Diff 产品能力
Worktree
Git 分支 / PR 工作流
Memory
Skill
MCP
后台任务平台
远程设备
Voice
STT / TTS
IDE
Web Client
……
```

全部：

```text
不做
不占位
不提前定义 IPC
不提前画入口
不提前建立空页面
不提前设计领域模型
```

### D-T10-04：产品视觉约束

产品中禁止出现任何“解释设计本身”的文案。

禁止例如：

```text
三栏布局
这里展示现有配置能力
工程参考行为
GUI 化入口
设计说明
演示区域
此区域用于……
```

产品文案只能描述：

- 用户正在做什么；
- 当前状态是什么；
- 操作会产生什么真实效果。

同时：

> **禁止把产品做成各种“小卡片”拼接布局。**

GUI 应优先使用：

- 连续页面；
- 普通列表；
- 分隔线；
- 时间线；
- 行级状态；
- 内联操作区；
- 固定/停靠面板；
- 必要的轻量 modal / overlay。

禁止：

- 每个 Tool 一个圆角卡片；
- 每个状态一个卡片；
- Settings 每组一个悬浮卡片；
- Dashboard 式卡片矩阵；
- 把 AskUser / Permission / Plan 做成互相独立的小卡片堆叠。

---

## 4. 当前代码事实

### 4.1 当前最短正式调用链

基线已经收口为：

```text
interfaces/cli.py
或
interfaces/tui/app.py
        ↓
application/bootstrap.py
create_application(...)
        ↓
UthCodeApplication.create_run()
        ↓
真实 prompt / 显式命令时
ensure_session / new / resume
        ↓
AgentRun.start_turn(...)
        ↓
TurnHandle
        ↓
Core Agent Runtime
```

Desktop 必须继续走同一个 Application 公共边界。

### 4.2 当前 TUI 的性质

当前 TUI：

```text
src/uthcode/interfaces/tui/
├─ app.py
├─ completion.py
├─ interaction.py
├─ picker.py
├─ rendering.py
├─ state.py
├─ terminal.py
└─ windows_input.py
```

它只拥有：

- 终端输入；
- Picker 状态；
- Interaction 临时选择状态；
- 流式显示投影；
- 当前 `AgentRun` / `TurnHandle` 引用；
- 终端布局状态。

它不拥有：

- Session 真相；
- Permission 真相；
- Plan/Todo 真相；
- Provider 真相；
- Context 真相；
- Tool 执行真相。

Desktop 必须保持相同原则。

### 4.3 Application 已经具备的关键跨界能力

当前 Application 公共出口已经包含：

```text
UthCodeApplication
AgentRun
TurnHandle

AgentEvent

ApplicationStatus
ContextUsage

SessionCatalogEntry
SessionReplayRecord

BehaviorMode
PermissionMode

PauseRequest / PauseResponse
UserInputRequest / UserInputResponse
PermissionApprovalRequest / Response
PlanReviewRequest / Response
RetryProviderResponse

CommandRegistry
CommandParser
CommandDispatcher
CompletionEngine
UiAction / CommandOutcome
```

因此 Desktop **不得再造**：

```text
DesktopAgentEvent
DesktopSessionDomain
DesktopPermissionDomain
DesktopPlanDomain
DesktopTaskDomain
DesktopFailureTaxonomy
```

等第二套产品语义。

### 4.4 AgentEvent 已适合作为进程边界基础

当前 `AgentEvent` 已明确是：

- Provider-independent；
- display-safe；
- 可序列化；
- 不含 Provider SDK 原生对象；
- 不含异常对象；
- 不泄露 ToolResult 原始内容；
- 带 `run_id / turn_id`；
- 支持安全字典 / JSON 投影。

T10 的 Desktop Bridge 应尽量直接沿用这个边界，而不是再设计一套事件平台。

### 4.5 Session 恢复已有安全投影

当前：

```text
SessionCatalogEntry
SessionReplayRecord
```

已经用于 Interface 安全恢复。

`SessionReplayRecord.kind` 当前只包含：

```text
user
steering
reasoning
assistant
tool
```

Electron Renderer 不得：

```text
直接打开 transcript.jsonl
直接打开 timeline.jsonl
直接解析 Session 文件
直接读取 Integration Session Store
```

如果 GUI 为完成当前 Session 浏览确实缺少只读查询，只允许增加**最小 Application read use case**。

### 4.6 当前 Run 约束

一个 `AgentRun`：

```text
最多一个 active Turn
```

当前行为模式不能在 active Turn 中直接切换。

当前权限模式属于 Run。

当前 Session grant 也属于 Run 内存状态。

Desktop 不得通过 React store 绕过这些约束。

---

## 5. T10 成功标准

T10 完成必须同时满足：

```text
A. Desktop 可真实启动 Python UthCode Runtime
B. 用户无需自行安装或启动 Python
C. 当前 TUI 的全部用户能力在 GUI 中有等价路径
D. Session 可真实恢复并继续
E. AskUser / Permission / Plan / Retry 能完成完整暂停-回答-继续闭环
F. Renderer 无 Node / fs / process / Python 直接权限
G. TUI 与 uthcode exec 不退化
H. Windows 11 x64 可生成可安装 Setup.exe
I. Dark / Light 均可用
J. 产品中不存在当前 UthCode 尚未支持的伪功能
K. 不产生第二套 Agent / Session / Permission / Plan / Event authority
L. 不出现卡片化 Dashboard
M. 不出现解释产品设计本身的 UI 文案
```

只做到“能聊天”不算 T10 完成。

---

## 6. TUI → GUI Feature Parity Matrix

> 本表是 T10 的核心验收基线。
> 若实施过程中发现基线代码还有表中遗漏的真实 TUI 用户能力，必须补入实现与测试；不得因为任务书漏列而删除现有能力。

| 当前真实能力 | 当前权威来源 | Desktop 等价入口 / 表达 | Bridge 要求 | 核心验收 |
|---|---|---|---|---|
| 普通多轮对话 | `AgentRun.start_turn` | Composer 提交 | start turn | idle 时产生新 Turn |
| active Turn Steering | `TurnHandle.steer` | Agent 运行时继续输入并发送 | steer | 不创建第二 Turn |
| Assistant Streaming | `AgentEvent` | 中部 Timeline 增量 Markdown | event stream | delta 顺序正确 |
| Reasoning | `AgentEvent` / replay | Timeline 中低噪声 reasoning 行/段 | event + replay | 不与 final 重复 |
| Tool started | `AgentEvent` | Timeline 活动行 | event | 不显示 ToolResult 私密正文 |
| Tool finished / failed | `AgentEvent` | 同一 Tool 活动的终态行 | event | 状态与顺序正确 |
| Provider retry / reconnect | typed pause / AgentEvent | Timeline 状态 + 必要交互 Surface | typed resume | 不在 Renderer 自造 retry |
| cooperative pause | `TurnHandle` / pause semantics | 明确 Pause 操作 | pause | pause ≠ cancel |
| resume typed interaction | `TurnHandle.resume` | Interaction Surface 提交 | resume | 恢复同一个 Turn |
| cancel | `TurnHandle.cancel` | Stop / Cancel 操作 | cancel | 终态可观察 |
| AskUserQuestion | `UserInputRequest` | Timeline 状态 + Composer 上方 Interaction Surface | typed request/response | 完整问答闭环 |
| Permission approval | `PermissionApprovalRequest` | Composer 上方权限操作区 | typed request/response | Reject / Allow Once / Allow for Session |
| Plan Review | `PlanReviewRequest` | Timeline Plan + Composer 上方 Review Surface | typed request/response | Approve / Revise / Cancel |
| Plan Mode | `BehaviorMode` | Composer 模式入口 + 状态 | command / run | idle 才能切 |
| Default Mode | `BehaviorMode` | 同上 | command / run | `/do` 语义一致 |
| `/build` alias | Command Registry | Slash completion | command | 等价 `/do` |
| Todo / TaskState | `TaskStateChanged` | Composer 附近紧凑进度 + 展开列表 | event | replace-all 投影 |
| CompletionBlocked | public event | Timeline 状态 | event | 原因可见 |
| Model catalog | Application | Composer model selector | query | 候选来自 Python |
| Model select | Application command | Composer model selector / Slash | command | 不维护 TS 模型真相 |
| Run Permission mode | `AgentRun` | Composer permission selector | command / run | default/auto/full_access |
| 默认 Permission mode | user config | Settings | config use case | 只 default/auto |
| Session lazy creation | Application | 首条真实 prompt 时 | existing semantics | 启动 GUI 不空建 Session |
| New Session | Application | “新对话” / 项目“＋” | command/use case | 中部变为空白 Chat |
| Session catalog | Application | 左侧项目下 Session 列表 | query | 不扫 JSONL |
| Session resume | Application | 点击 Session 直接恢复 | resume | 无独立恢复页 |
| Session safe replay | Application | 中部 Timeline 替换为历史 | replay | 顺序与 kind 正确 |
| Context manual compact | Application | 操作入口 + `/compact` | command | 与 TUI 同语义 |
| Context usage | Application | 运行信息 + 状态 | status | dynamic limit，不猜模型窗口 |
| `/status` | Command Registry / Application | Slash + 运行信息 | command/status | 信息来自同一权威 |
| Slash completion | CompletionEngine | Composer `/` 菜单 | complete | command/alias/args 来自 Python |
| `/help` | Registry | Slash | execute | 当前真实命令 |
| `/clear` | `ClearTranscript` UI action | 清空当前可见 Timeline | command outcome | 不删除 durable Session |
| `/model` | Registry | Slash / selector | execute | 复用权威目录 |
| `/permission` | Registry | Slash / selector | execute | warning 语义保留 |
| `/quit` | Registry | Slash | Interface shutdown | 正常收口 Runtime |
| `/compact` | Registry | Slash / GUI action | execute | no-op / changed 都正确 |
| `/plan` | Registry | Slash / mode selector | execute | 进入 PLAN |
| `/new` | Registry | Slash / New chat | execute | 新 Session |
| `/resume` | Registry | Slash / Session click | execute/query | replay 可用 |
| `/do` | Registry | Slash / mode selector | execute | DEFAULT |
| `/build` | Registry alias | Slash | execute | DEFAULT |
| FailureReason | Application projection | Timeline / Runtime 错误状态 | event/error | 不重定义 taxonomy |
| Configuration error | Application bootstrap | Settings / 启动错误页 | bridge lifecycle | 可修复，不崩 GUI |
| Runtime startup failure | Desktop boundary | 应用级错误状态 | bridge lifecycle | 与 Agent failure 区分 |
| Runtime abnormal exit | Desktop boundary | 应用级错误状态 | process lifecycle | 不伪装成 Provider error |

---

## 7. 明确不迁移的 TUI 技术细节

以下属于终端实现，不属于产品能力：

```text
ANSI escape
DECSET synchronized output
prompt_toolkit Window
terminal scrollback
Rich Console 输出策略
Kitty keyboard protocol
KEY_EVENT_RECORD
terminal cell width workaround
双 Esc 键位本身
```

GUI 只迁移这些实现背后的产品语义。

例如：

```text
TUI 双 Esc
→ cooperative pause
→ Desktop 使用明确 Pause 按钮

TUI terminal scrollback
→ 已完成历史
→ Desktop 使用自己的 Timeline

TUI Rich Markdown
→ Markdown 展示
→ Desktop 使用安全 Markdown Renderer
```

---

## 8. GUI 信息架构

### 8.1 总体结构

参考：

```text
./uthcode-desktop-ui-prototype-v5.html
```

但正式实现必须接真实 Application 状态。

目标布局：

```text
┌───────────────┬──────────────────────────────────┬──────────────┐
│               │                                  │              │
│ Project /     │          Chat Timeline           │  Runtime     │
│ Session Nav   │                                  │  Info        │
│               │                                  │  Panel       │
│               │                                  │              │
│               ├──────────────────────────────────┤              │
│               │ Todo / Interaction（按需）       │              │
│               │ Composer                         │              │
├───────────────┴──────────────────────────────────┴──────────────┤
└─────────────────────────────────────────────────────────────────┘
```

右栏允许：

```text
floating
docked-right
hidden
```

窗口过窄时可自动隐藏。

不得增加第二个左侧“全局功能栏”。

### 8.2 左侧导航

只包含当前产品有现实意义的 Desktop 导航：

```text
新对话
打开项目…

置顶
项目
最近

设置
```

项目项可提供：

```text
新建 Session
置顶 / 取消置顶
编辑显示名称
在资源管理器中打开
移除项目
```

这些项目组织状态属于 Desktop-local UI state，不进入 Agent Core。

### 8.3 必须删除 HTML 原型中的伪产品入口

原型里为了演示而存在、但当前 UthCode 没有真实后端能力的内容不得上线，例如：

```text
账号头像 / 用户名
“退出登录”
账户“使用情况 / 剩余 xx%”
固定的 AskUser 演示按钮
固定的 Plan 演示按钮
固定的 Permission 演示按钮
alert() 工程提示
prompt() / confirm() 浏览器占位
静态 projectStore 作为真相
```

AskUser / Plan / Permission **只能在真实 Runtime 发出对应请求时出现**。

### 8.4 Session 行显示

当前 Session 并没有新的“可编辑标题”产品语义。

生产 UI 应优先使用：

```text
SessionCatalogEntry.preview
```

作为可读标签；无 preview 时回退 Session ID 的短形式。

禁止仅为了 Desktop 新增 durable Session title 系统。

### 8.5 不做 Hover Preview 卡片

HTML 中项目 / Session Hover Preview 属于原型辅助效果。

由于本任务禁止小卡片式界面，本轮不实现 Hover Preview 卡片。

需要的信息：

- Project path；
- Session 时间；
- 当前状态；

应在列表、Tooltip 或右侧 Runtime Info 中使用更轻量的方式呈现。

---

## 9. Session 与项目交互

### 9.1 打开项目

正式流程：

```text
点击“打开项目…”
        ↓
Preload 窄 API
        ↓
Electron Main
        ↓
Windows Folder Picker
        ↓
返回绝对路径
        ↓
写入 Desktop recent-project preference
        ↓
初始化 / 切换该项目 Application
        ↓
加载 Session catalog
        ↓
左栏出现项目
```

Renderer 不得自行访问文件系统。

不得使用浏览器 `prompt()`。

### 9.2 Project 显示名称

“编辑名称”只修改 Desktop 的显示别名：

```text
filesystem folder name       不变
Application project_key      不变
workdir                      不变
Desktop display alias        可变
```

交互使用左栏原位编辑：

```text
项目名
→ Enter / blur 保存
→ Esc 取消
```

不得调用 rename/move 修改磁盘项目目录。

### 9.3 移除项目

正式语义：

```text
从 Desktop 项目列表移除
≠
删除磁盘目录
≠
删除 Session
```

使用 UthCode 自己的轻量确认 Surface。

不得使用浏览器 `confirm()`。

### 9.4 点击已有 Session

正式行为固定：

```text
点击 Session
        ↓
检查当前 Turn
        │
        ├─ idle
        │    ↓
        │  继续
        │
        └─ active
             ↓
           明确走现有 cancel
             ↓
           等待 terminal state
        ↓
如目标 Project 不同
关闭当前 UthCodeApplication
        ↓
按目标 workdir 重建 Application
        ↓
Application resume target Session
        ↓
取得 SessionReplayRecord[]
        ↓
中部 Timeline 原子替换成该 Session 历史
        ↓
创建 / 绑定该 Session 的当前 Run 视图
        ↓
Composer ready
        ↓
下一条输入在同一个 durable Session 中产生新 Turn
```

禁止出现：

```text
“恢复会话页”
“Session detail page”
“请点击继续”
```

用户点击 Session 本身就是恢复行为。

### 9.5 New Session

正式行为：

```text
点击“新对话”
或项目“＋”
        ↓
Application new Session
        ↓
当前 Session 切换
        ↓
中部 Timeline = []
        ↓
Composer 绑定新 Session
        ↓
ready
```

必须保证：

> 创建新 Session 后绝不能继续显示上一个 Session 的旧聊天内容。

### 9.6 多项目运行约束

一个 Desktop Python Bridge 同时只持有：

```text
一个 active UthCodeApplication
一个 active AgentRun
最多一个 active Turn
```

不得为左栏多个 Project 启动多个后台 Agent Runtime。

非当前项目的 Session 列表允许：

- 在该项目曾被激活时保存 **仅用于导航显示的 last-known catalog**；
- 项目重新激活后立刻以 Application catalog 刷新。

该缓存不是 Session authority，不得用于恢复内容。

如果为了左栏按需刷新非当前项目 Session 必须新增读能力，优先增加一个**只读、无 Agent Runtime 的 Application project-session catalog use case**，不得让 Renderer 直接扫描 Session 文件。

---

## 10. Chat Timeline 投影

### 10.1 两类输入

Timeline 来源只有：

```text
A. durable SessionReplayRecord
B. 当前 active Turn 的 AgentEvent stream
```

React 不得自己推测 Agent 已经完成什么。

### 10.2 Replay → Timeline

至少映射：

```text
user       → 用户消息
steering   → 用户追加指令
reasoning  → reasoning
assistant  → Agent Markdown
tool       → Tool 终态
```

恢复历史后：

```text
历史只读
+
新 Turn 实时追加
```

两者必须形成一条连续时间线。

### 10.3 Live Event 顺序

Bridge 保留 Application 事件顺序。

Renderer reducer 只做：

- append；
- 对当前 streaming block 做增量合并；
- 将同一 Tool 活动更新到终态；
- 在最终 authoritative event 到达时收口当前块。

不得：

- 按事件类型重新分组；
- 把 reasoning 集中到一处；
- 把 Tool 全部移动到“工具卡片区”；
- 为了 UI 美观打乱原始时序。

### 10.4 Markdown

Agent 正文使用安全 Markdown 渲染。

最低要求：

- headings；
- paragraphs；
- lists；
- blockquote；
- tables；
- links；
- inline code；
- fenced code block。

禁止直接执行 Agent 输出中的 HTML / script。

本轮可使用：

```text
react-markdown
remark-gfm
```

不启用 raw HTML。

除非现有测试证明有必要，不为“语法高亮更漂亮”额外加入大型高亮框架；普通 `<pre><code>` 足够作为首轮等价实现。

---

## 11. AskUser 完整页面状态

HTML 当前只画了“正在请求答案”的底部交互面，本任务必须补足完整生命周期。

### 11.1 Request

收到真实 `UserInputRequest` 后：

```text
AgentEvent / typed pause
        ↓
Timeline 追加请求状态
        ↓
“正在询问问题”
        ↓
“正在等待你的回答”
        ↓
Composer 上方出现 Interaction Surface
```

实际文案可以微调，但必须是用户状态文案，不得出现设计说明。

### 11.2 Pending

AskUser pending 时：

```text
普通 Composer 输入
→ 归当前 AskUser 响应
```

不得变成：

```text
Steering
新 Turn
第二个 AskUser
```

### 11.3 Answer

用户选择选项或填写允许的自由回答后：

```text
Renderer
        ↓
Preload
        ↓
Main
        ↓
Bridge
        ↓
TurnHandle.resume(UserInputResponse)
```

随后 Timeline 应形成完成态，例如：

```text
已收到回答：一小时自由时间
```

不得只让底部 Surface 突然消失、时间线没有痕迹。

### 11.4 Continue

完整流程必须可观察：

```text
User 回答
        ↓
AskUser 完成
        ↓
同一个 Turn Resume
        ↓
Agent 继续 Markdown / Tool / Reasoning
        ↓
必要时再次产生新的 Interaction Surface
```

不得创建新 Turn 伪装成“继续”。

---

## 12. Permission / Plan / Provider Retry

### 12.1 Permission

权限请求出现时：

```text
Timeline
→ 操作 / 工具上下文状态

Composer 上方
→ Permission Interaction Surface
```

选项必须来自当前真实语义：

```text
Reject
Allow Once
Allow for Session
```

`Allow for Session` 的 grant 继续由 `AgentRun` 持有。

不得保存到 Electron preference。

不得建立 Desktop Permission Store。

### 12.2 Plan Review

`PlanProposed` 每个 revision 都作为 Timeline 中完整 Plan 内容显示。

Review Surface 只提供当前真实动作：

```text
Approve and execute
Revise plan
Cancel
```

提交：

```text
TurnHandle.resume(PlanReviewResponse)
```

批准后 behavior mode 的变化继续从 Run/Application 权威状态读取。

### 12.3 Provider Retry

Provider Retry 继续使用现有 typed pause/response。

Renderer 不实现：

- 自己的 HTTP retry；
- 自己的 backoff；
- 自己的 Provider reconnect state machine。

它只显示当前 Runtime 投影并提交用户决定。

---

## 13. Todo / TaskState

Todo 属于当前真实能力，必须迁移。

建议表达：

```text
Composer 上方
“第 3 / 7 步”

点击 / hover
→ 展开连续列表
```

列表是普通行，不是 Todo cards。

`TaskStateChanged` 是 replace-all 投影：

```text
事件携带完整 TaskState
        ↓
Desktop 替换当前 Todo view
```

不得尝试由旧事件自己推导一个新的 Todo 真相。

`CompletionBlocked` 作为 Timeline 状态显示。

---

## 14. Slash Command 与 GUI 控件共用一份权威

### 14.1 Python Registry 是唯一命令来源

当前真实命令：

```text
/help
/clear
/model
/permission
/status
/quit
/compact
/plan
/new
/resume
/do
```

当前 alias 包括：

```text
/help       → /h /?
/model      → /models /m
/status     → /s
/quit       → /q /exit
/compact    → /c
/do         → /build
```

不得在 TypeScript 写死第二份“完整命令表”。

### 14.2 Slash completion

Renderer 草稿以 `/` 开头时：

```text
Bridge
→ Application CompletionEngine
→ 返回 display-safe candidates
→ GUI 显示候选
```

argument candidates 同样来自 Application。

### 14.3 GUI 控件不得复制命令语义

例如：

```text
Model selector
Permission selector
Behavior mode selector
New Session
Compact
```

可以是 GUI-native 控件，但最终应复用：

- 同一个 Application use case；
- 或同一个 Command Dispatcher / CommandOutcome；

而不是在 TypeScript 复制“/model 应该做什么”。

---

## 15. Settings 与配置闭环

### 15.1 Settings 不是原型分类照搬

HTML 原型当前列出了多个演示分类，但正式产品只显示有真实内容的分类。

首版建议：

```text
模型与提供商
权限与安全
界面
关于
```

只有在当前实现确实存在对应可读/可写内容时才能增加分类。

因此本轮默认不创建空壳：

```text
会话与历史
工具与终端
上下文与性能
日志与诊断
……
```

如果这些信息只是 runtime status，就放在：

```text
运行信息
```

而不是伪装成 Settings。

### 15.2 模型与提供商

支持当前 user config 的真实编辑能力：

#### Provider

```text
profile id
kind
base_url
api_key
```

必须支持：

- 新增；
- 编辑；
- 删除；
- 校验引用关系。

`openai_compat` 必须有 `base_url`。

非 `fake` Provider 必须有 API Key。

#### Model

```text
model_ref
provider
remote_id
display_name
context_window
max_output_tokens
reasoning_effort
```

必须支持：

- 新增；
- 编辑；
- 删除；
- 选择 default model；
- 校验 provider 引用。

不得增加当前 config 不存在的：

```text
temperature
top_p
custom headers
proxy
organization
region
fallback models
model routing
```

### 15.3 API Key 安全

配置读取响应不得返回 API Key 明文。

GUI 可获得：

```text
api_key_configured: true | false
```

编辑时：

```text
用户输入新 key
→ 一次性写请求
→ 写入 user config
→ response 不回显
→ Renderer 清空输入值
```

API Key 禁止进入：

```text
AgentEvent
Session
History
Runtime log
Bridge stdout diagnostic
Bridge error object
Electron Main log
Renderer persisted state
Crash diagnostic
测试 snapshot
```

### 15.4 配置 bootstrap 必须独立于已成功创建 Application

当前配置未初始化时，`create_application` 前就可能得到：

```text
ConfigurationInitializationRequired
```

因此配置 GUI 不能依赖一个已经成功构造的 `UthCodeApplication`。

Application 层应增加最小 bootstrap use case：

```text
read_user_configuration(...)
write_user_configuration(...)
```

名字可按当前代码风格微调，但职责必须是：

```text
即使 Agent Application 尚未能启动
Desktop 仍可：
读取安全用户配置视图
→ 用户填写 Provider / Model / default_model
→ 原子保存
→ 重新 load_effective_config
→ 创建正式 Application
```

不要为此建立常驻 Configuration Manager。

### 15.5 配置文件写入

沿用现有 `tomlkit + same-filesystem temp + os.replace` 原子写方向。

扩展当前 writer，使它只处理**当前支持字段**。

要求：

- 写入前完成 Application/Integration 同等级验证；
- 尽量保留现有注释与顺序；
- 不允许写未知 root/provider/model 字段；
- user config 可保存 Provider/credentials；
- project config 的 Provider / credential 禁止规则保持不变；
- 不把 project config 变成 GUI credential store。

### 15.6 生效时机

以下配置会影响 Provider/Application construction：

```text
Provider
API Key
base_url
Model profile
default_model
```

保存后不得偷偷热改已经存在的 Provider 对象。

若当前 Turn idle：

```text
保存
→ validate
→ close current Application
→ load effective config
→ recreate Application(current workdir)
→ resume 当前 durable Session（若存在）
→ 刷新 Runtime 状态
```

若当前存在 active Turn：

```text
禁止直接重建 Runtime
```

UI 必须要求用户先结束/取消当前 Turn 后再应用影响 Runtime construction 的设置。

---

## 16. Desktop-local Preferences

以下事实只影响 Desktop 显示，可由 Electron 本地持久化：

```text
theme: system | dark | light
window size / position
sidebar collapsed
runtime panel visible / floating / docked
recent project paths
project display alias
project pin state
session pin state
last selected project
```

这些不得进入：

```text
UthCode Core config
Session transcript
AgentEvent
Context
Provider request
```

Desktop preference 文件只存 UI 元数据，不存 API Key。

---

## 17. Dark / Light Theme

### 17.1 Owner

Theme owner：

```text
Electron Renderer / Desktop preference
```

不是 Core。

### 17.2 行为

默认：

```text
system
```

用户可选：

```text
跟随系统
深色
浅色
```

手动选择覆盖系统跟随，直到改回“跟随系统”。

### 17.3 实现

使用少量 CSS semantic tokens，例如：

```text
--bg
--surface
--surface-elevated
--border
--text
--text-muted
--accent
--success
--warning
--danger
--code-bg
```

不得建立一个通用“主题引擎”。

### 17.4 两主题必须检查

```text
User message
Agent Markdown
Reasoning
Tool
Permission
Plan
Todo
Warning
Error
Code block
Selection / hover / focus
Runtime panel
Settings rows
```

颜色不能成为唯一状态信息。

---

## 18. 产品视觉与布局硬约束

### 18.1 禁止卡片化

以下全部使用连续表面/行/分隔线实现：

```text
Tool activity
Reasoning
Plan
Todo
Settings
Runtime Info
Context 状态
Permission
AskUser
Provider Retry
```

不得出现“多个独立圆角框 = 多个功能块”的布局。

### 18.2 Chat 主视觉

推荐层级：

```text
User
→ 轻量消息气泡或右对齐消息

Agent
→ 页面正文式 Markdown

Reasoning
→ muted / indented

Tool
→ 时间线行 / 左侧弱边界

System state
→ 小型文字状态行

Interaction
→ 与 Composer 连续的操作区
```

### 18.3 Settings

Settings 使用：

```text
分类导航
+
连续设置行
+
细分隔线
```

不使用：

```text
Setting cards
Dashboard tiles
每个类别一个圆角盒
```

### 18.4 产品文案检查

所有 Renderer 可见字符串必须经过一次检查，禁止包含：

```text
设计
原型
示例
工程参考
GUI 化
三栏
这里用于
该区域
布局说明
```

除非这些词是用户实际数据的一部分。

---

## 19. Desktop Process / Trust Boundary

正式进程结构：

```text
┌─────────────────────────────────────────────┐
│ Electron Renderer                           │
│                                             │
│ React UI                                    │
│ no Node / no fs / no child_process          │
└──────────────────┬──────────────────────────┘
                   │ narrow contextBridge API
                   ▼
┌─────────────────────────────────────────────┐
│ Electron Preload                            │
│                                             │
│ typed narrow methods                        │
│ no raw ipcRenderer exposure                 │
└──────────────────┬──────────────────────────┘
                   │ Electron IPC
                   ▼
┌─────────────────────────────────────────────┐
│ Electron Main                               │
│                                             │
│ BrowserWindow                               │
│ native folder dialog                        │
│ Desktop preferences                         │
│ Python child lifecycle                      │
└──────────────────┬──────────────────────────┘
                   │ stdin/stdout JSONL
                   ▼
┌─────────────────────────────────────────────┐
│ Python Desktop Bridge                       │
│ interfaces/desktop                          │
│                                             │
│ one Application                             │
│ one AgentRun                                │
│ one active Turn max                         │
└──────────────────┬──────────────────────────┘
                   │ Application public API
                   ▼
┌─────────────────────────────────────────────┐
│ UthCode Application                         │
└──────────────────┬──────────────────────────┘
                   ▼
               UthCode Core
```

### 19.1 权限所有权

| 层 | 可做什么 | 禁止什么 |
|---|---|---|
| Renderer | 展示、收集用户输入、维护纯 UI state | Node、fs、spawn、Core |
| Preload | 暴露固定窄 API | raw `ipcRenderer`、通用 shell/fs |
| Main | OS dialog、preference、child lifecycle | Agent 业务语义 |
| Python Bridge | Interface 编排、协议校验、持有 Application/Run/Turn | 复制 Core |
| Application | 产品 use case / safe projection | Interface UI |
| Core | Agent runtime authoritative semantics | Electron |

---

## 20. Electron 安全要求

基于当前 Electron 官方安全模型，必须至少满足：

```text
nodeIntegration = false
contextIsolation = true
sandbox = true
```

并落实：

1. Renderer 只加载本地打包内容；
2. Production CSP 不允许任意远程 script；
3. 不使用 `<webview>`；
4. 不允许任意 navigation；
5. Main IPC handler 校验 sender；
6. Preload 每个能力暴露一个明确方法；
7. 不把 `ipcRenderer` 本身暴露给 Renderer；
8. 不把 `shell` / `fs` / `child_process` 暴露给 Renderer；
9. Python 返回值全部按不可信跨进程输入校验；
10. 未知 Desktop method 不执行；
11. 非法 JSON / 未知字段返回 Bridge protocol error，不进入 Agent Runtime。

---

## 21. Python Desktop Bridge

### 21.1 位置

新增：

```text
src/uthcode/interfaces/desktop/
```

它仍然属于：

```text
interfaces
```

因此只通过：

```text
uthcode.application
```

工作。

### 21.2 最小文件

建议：

```text
src/uthcode/interfaces/desktop/
├─ __init__.py
├─ __main__.py
├─ bridge.py
└─ protocol.py
```

只有真实复杂度证明需要时才能继续拆文件。

禁止一开始新增：

```text
DesktopRuntimeManager
RpcManager
TransportFactory
UniversalProtocol
DeviceProtocol
DesktopDomain
EventBus
PluginHost
```

### 21.3 Bridge 生命周期

```text
Electron Main spawn
        ↓
python bridge boot
        ↓
stdout ready response
        ↓
project/config initialize
        ↓
Application ready
        ↓
request/event loop
        ↓
shutdown
        ↓
cancel active Turn if any
        ↓
await bounded close
        ↓
Application.close()
        ↓
process exit
```

### 21.4 stdout / stderr

硬约束：

```text
stdout = JSONL protocol only
stderr = diagnostics only
```

任何：

```text
print()
第三方日志
debug banner
trace
```

都不得污染 stdout。

---

## 22. Desktop 私有 JSONL 契约

### 22.1 选择

T10 使用：

> **单个本机 Python child process + stdin/stdout newline-delimited JSON。**

原因：

- 当前 Desktop 只需要一个父子进程；
- 生命周期天然绑定；
- 无端口；
- 无 localhost attack surface；
- 无 WebSocket server；
- 无未来 Device Protocol 包袱；
- 与 Codex rich-interface 使用 stdio JSONL 的成熟方向一致。

本轮不实现：

```text
FastAPI
HTTP localhost
WebSocket
Named Pipe protocol platform
gRPC
MCP
```

### 22.2 Envelope

协议保持私有、窄、可测试。

Request：

```json
{
  "type": "request",
  "id": "desktop-request-id",
  "method": "turn.start",
  "params": {}
}
```

Response：

```json
{
  "type": "response",
  "id": "desktop-request-id",
  "ok": true,
  "result": {}
}
```

Error response：

```json
{
  "type": "response",
  "id": "desktop-request-id",
  "ok": false,
  "error": {
    "kind": "invalid_request",
    "message": "..."
  }
}
```

Agent event：

```json
{
  "type": "agent_event",
  "event": {}
}
```

Runtime lifecycle：

```json
{
  "type": "runtime_state",
  "state": "ready"
}
```

### 22.3 Correlation

Bridge request ID 只用于跨进程 request/response correlation。

Agent 身份继续使用现有：

```text
session_id
run_id
turn_id
pause/request identity
```

不得由 Desktop 发明第二套 Agent identity。

### 22.4 最小方法集合

实现时只需要当前 GUI 有调用方的方法。

建议 contract：

```text
runtime.initialize
runtime.shutdown

project.open
project.sessions

session.new
session.resume

turn.start
turn.steer
turn.pause
turn.resume
turn.cancel

command.complete
command.execute

status.get

settings.get
settings.save
```

允许实施时把能由 `command.execute` 统一承载的重复 method 合并掉。

判断标准：

> 方法数量越少越好，但不得为了“统一”造一个任意反射式 RPC。

禁止：

```text
call(method_name, arbitrary_args)
eval
generic object invocation
```

### 22.5 Event

Agent 事件 payload 直接基于：

```text
AgentEvent.to_dict()
```

Bridge 只包 Envelope。

不得重命名事件形成第二套：

```text
desktop_tool_started
desktop_plan_event
desktop_agent_delta
```

### 22.6 Typed Pause

`turn.resume` payload 必须根据当前真实 pending request 构造现有：

```text
UserInputResponse
PermissionApprovalResponse
PlanReviewResponse
RetryProviderResponse
PauseResponse
```

Bridge 校验：

```text
当前是否确实 pending
request kind 是否匹配
response fields 是否合法
```

未知/过期 response 必须拒绝。

---

## 23. Desktop Runtime 生命周期

### 23.1 开发环境

开发模式：

```text
Electron Main
→ 使用当前开发 Python
→ python -m uthcode.interfaces.desktop
```

允许通过开发脚本解析 repo virtualenv / 当前 Python。

不得让最终普通用户依赖这个开发路径。

### 23.2 Production

Production：

```text
Electron Main
→ process.resourcesPath
→ bundled uthcode Python runtime
→ spawn runtime executable
```

Main 不调用系统 `python`。

### 23.3 Project switch

Project path 是一个 `UthCodeApplication` 的 runtime fact。

因此：

```text
switch project
→ active Turn 必须先收口
→ close current Application
→ create_application(new workdir)
→ create fresh AgentRun
→ load/resume selected Session
```

不得在一个 Application 内偷偷改 `workdir`。

### 23.4 Window close

关闭 Desktop：

```text
BrowserWindow close
        ↓
停止接收新用户请求
        ↓
如果 active Turn
turn.cancel()
        ↓
消费 / 等待 terminal result（bounded）
        ↓
Application.close()
        ↓
关闭 child stdin
        ↓
等待 child 正常退出（bounded）
        ↓
仍未退出则 terminate
        ↓
reap child
        ↓
Electron exit
```

不得留下 orphan Python process。

### 23.5 明确不做后台 Agent

本轮：

```text
关窗口
→ Runtime 结束
```

不做：

```text
Tray host
Windows Service
Daemon
关闭窗口继续 Agent
runtime checkpoint
active Turn restart recovery
```

---

## 24. Electron 技术栈落点

### 24.1 版本线

按任务书生成时的当前稳定事实：

```text
Electron: 44.x stable
Electron Forge: 7.11.2 stable
```

不得使用：

```text
Electron 45 alpha
Electron Forge 8 alpha
```

### 24.2 Bundler

使用 Electron Forge 官方：

```text
@electron-forge/plugin-webpack
```

不使用 Forge Vite Plugin。

原因：

- 当前 Vite Plugin 官方仍标为 experimental；
- T10 没有必须使用 Vite 的产品需求；
- 本任务优先减少工具链不确定性。

### 24.3 Package manager

使用：

```text
npm
package-lock.json
```

不为 monorepo / workspace 预留 pnpm/turborepo 架构。

### 24.4 React state

优先：

```text
React state
useReducer
small Context where needed
```

不得默认加入：

```text
Redux
Zustand
MobX
XState
```

除非实际实现已经证明普通 React state 无法清晰表达当前状态。

### 24.5 Component library

默认不用大型 UI Component Framework。

原因：

- 当前视觉约束非常明确；
- 需要避免组件库默认 Card 语言；
- 需要接近高密度 Coding Agent Desktop；
- 当前页面数量有限。

使用普通 React + CSS。

---

## 25. Renderer 状态所有权

### 25.1 Python authoritative

这些事实不能只存在 Renderer：

```text
current durable Session
AgentRun
active Turn
Permission mode
Session grant
Behavior mode
Plan
TaskState
Provider
Model selection
Context usage
Compact result
FailureReason
```

### 25.2 Renderer-only

这些可以属于 UI：

```text
当前选中的导航 item
scroll position
draft
hover/focus
modal open/close
sidebar collapsed
runtime panel view mode
theme
setting form draft
```

### 25.3 Project navigation local

这些属于 Desktop shell：

```text
recent project paths
project display aliases
project pins
session pins
```

删除 Desktop 后这些信息消失，不影响 Agent 事实。

---

## 26. Runtime Info Panel

右侧只展示当前 Application 已有、安全、可解释的信息。

可包括：

```text
Project / workdir
Session
Turn status

Model
Permission mode
Behavior mode

Context usage
Compact count / latest outcome
必要的 safe diagnostics
```

不得展示：

```text
API Key
Provider native payload
raw prompt
raw transcript path
raw ToolResult
内部 exception
```

布局为：

```text
标题
行
行
分隔线
行
行
```

不是 card stack。

---

## 27. External Reference 结论

### 27.1 Codex Desktop / Codex App Server

只采用以下机制：

| Codex 机制 | T10 处理 |
|---|---|
| Project 下组织 threads/sessions | 采用为导航思路 |
| 点击 thread/session 直接继续 | 采用 |
| Rich interface 与 Agent runtime 分离 | 采用 |
| stdio JSONL 双向边界 | 采用最小版本 |
| server/runtime event 驱动 UI | 采用现有 AgentEvent |
| approval/request 与 turn identity 关联 | 采用现有 typed pause |
| Desktop 高信息密度、低噪声 | 作为视觉参考 |
| Multi-Agent | 不采用 |
| Worktree | 不采用 |
| Git Diff 产品面 | 不采用 |
| Automations | 不采用 |
| Skills | 不采用 |
| 通用 App Server 公共平台 | 不采用 |

Codex 的能力范围不能反向定义 UthCode T10。

### 27.2 DeepSeek Harness

DeepSeek Harness 对 T10 有价值的参考只有：

```text
session/event
        ↓
UI projection

user input
        ↓
agent followup / steer
```

UthCode 对应：

```text
SessionReplayRecord + AgentEvent
        ↓
Desktop Timeline

user input
        ↓
AgentRun.start_turn / TurnHandle.steer / typed resume
```

明确不采用 DeepSeek Harness 的：

```text
Everything is a Plugin
Cordis plugin platform
全局 capability registry
新 event store
新 session event-sourcing
Subagent provider
generic extension API
```

因为 UthCode 当前已经有自己的 Application / Session / Event 边界。

---

## 28. Python Runtime 打包

### 28.1 目标

普通用户安装 UthCode Desktop 后：

```text
无需安装 Python 3.12
无需 pip install
无需打开终端
无需手动启动 uthcode runtime
```

### 28.2 方案

使用：

```text
PyInstaller onedir
```

原因：

- 包含 Python interpreter 与运行依赖；
- onedir 比 onefile 更容易调试；
- 避免每次启动 onefile 自解压；
- Electron 最终 Installer 已经负责对用户隐藏内部目录。

### 28.3 构建产物

概念结构：

```text
desktop/.runtime/uthcode-runtime/
├─ uthcode-desktop-runtime.exe
└─ _internal/...
```

该目录是 build artifact，不提交二进制。

### 28.4 PyInstaller 收集原则

禁止盲目：

```text
--collect-all everything
```

实施时检查 UthCode 实际 package data / prompt assets，只加入 Runtime 真正依赖的非 Python 资源。

### 28.5 Forge 集成

构建顺序：

```text
Python tests
        ↓
PyInstaller build runtime
        ↓
verify runtime smoke
        ↓
Electron build
        ↓
Forge package/make
```

Forge 使用 `packagerConfig.extraResource` 或等价官方机制，把 runtime onedir 加入 app resources。

---

## 29. Windows Installer

使用：

```text
@electron-forge/maker-squirrel
```

目标产物至少：

```text
UthCode Setup.exe
```

T10 验收在 Windows 11 x64：

```text
干净环境安装
→ 启动 Desktop
→ 无系统 Python 也可启动 Runtime
→ 打开项目
→ 配置模型
→ 对话
→ Session 恢复
→ 卸载
```

Squirrel 同时会生成 update metadata，但：

> **T10 不实现自动更新产品能力。**

代码签名不是本轮功能前置；若没有真实证书，验收允许 unsigned development/release-candidate installer。不得为了未来证书体系建立配置框架。

---

## 30. 建议目标目录树

以下只列 T10 直接相关内容。

```text
Re-UthCode/
├─ desktop/                                      [新增]
│  ├─ package.json                               [新增]
│  ├─ package-lock.json                          [新增]
│  ├─ forge.config.ts                            [新增]
│  ├─ tsconfig.json                              [新增]
│  ├─ webpack.main.config.ts                     [新增]
│  ├─ webpack.renderer.config.ts                 [新增]
│  ├─ webpack.rules.ts                           [新增/仅实际需要时]
│  ├─ packaging/
│  │  └─ uthcode-runtime.spec                    [新增]
│  ├─ scripts/
│  │  └─ build-python-runtime.mjs                [新增]
│  ├─ src/
│  │  ├─ main.ts                                 [新增]
│  │  ├─ python-runtime.ts                       [新增]
│  │  ├─ desktop-preferences.ts                  [新增]
│  │  ├─ preload.ts                              [新增]
│  │  ├─ desktop-api.ts                          [新增]
│  │  └─ renderer/
│  │     ├─ index.html                           [新增]
│  │     ├─ main.tsx                             [新增]
│  │     ├─ App.tsx                              [新增]
│  │     ├─ app.css                              [新增]
│  │     ├─ state.ts                             [新增]
│  │     ├─ Sidebar.tsx                          [新增]
│  │     ├─ ChatTimeline.tsx                     [新增]
│  │     ├─ Composer.tsx                         [新增]
│  │     ├─ InteractionSurface.tsx               [新增]
│  │     ├─ RuntimePanel.tsx                     [新增]
│  │     └─ SettingsView.tsx                     [新增]
│  └─ tests/
│     ├─ renderer.test.tsx                       [新增]
│     ├─ preload.test.ts                          [新增]
│     └─ runtime-process.test.ts                  [新增]
│
├─ src/uthcode/
│  ├─ application/
│  │  ├─ __init__.py                             [修改]
│  │  ├─ bootstrap.py                            [修改]
│  │  ├─ configuration.py                        [修改]
│  │  ├─ generation.py                           [按实际需要最小修改]
│  │  └─ sessions.py                             [仅缺少只读项目 catalog 时修改]
│  ├─ integrations/config/
│  │  ├─ loader.py                               [按真实需要修改]
│  │  └─ writer.py                               [修改]
│  └─ interfaces/
│     ├─ cli.py                                  [保留现有行为]
│     ├─ tui/                                    [原则上不重写]
│     └─ desktop/                                [新增]
│        ├─ __init__.py
│        ├─ __main__.py
│        ├─ protocol.py
│        └─ bridge.py
│
├─ tests/
│  ├─ test_architecture_boundaries.py            [修改]
│  ├─ test_configuration.py / 当前对应配置测试   [修改]
│  ├─ test_config_writer.py / 当前对应测试        [修改]
│  ├─ test_desktop_protocol.py                   [新增]
│  └─ test_desktop_bridge.py                     [新增]
│
└─ docs/work/T10-.../
   └─ uthcode-desktop-ui-prototype-v5.html       [用户提供参考]
```

说明：

- 实施前先核对现有测试文件真实名称；
- 不得为了完全匹配本树而创建没有真实职责的文件；
- 若两个小文件可以清晰合并，允许减少文件；
- 不得额外搭建 `packages/`、monorepo、shared SDK 等未来结构。

---

# 31. 文件级实施任务

## T01：用户配置 GUI 闭环

### 目标

让 Desktop 即使在 Application 尚未成功初始化时，也能安全读取/填写/保存当前真实 user config。

### 修改

```text
src/uthcode/application/configuration.py
src/uthcode/application/bootstrap.py
src/uthcode/application/__init__.py
src/uthcode/integrations/config/writer.py
src/uthcode/integrations/config/loader.py（仅实际需要）
相关配置测试
```

### 实施

1. 增加安全 user-config view：
   - Provider API Key 只暴露 `configured`；
   - 不返回 plaintext。
2. 增加 current-schema write request。
3. 支持 Provider/Model profile 的新增、修改、删除。
4. 使用现有校验语义验证：
   - provider kind；
   - required API key；
   - openai_compat base_url；
   - model → provider；
   - positive context/output；
   - reasoning effort；
   - default model；
   - default permission。
5. 原子写 user config。
6. 保持 project config credential 禁止规则。
7. 保存后可重新 `load_effective_config`。
8. 不新增通用配置 registry / schema server。

### 完成边界

```text
无有效配置
→ GUI 可创建一份有效配置
→ Application 可启动
```

---

## T02：Python Desktop Bridge

### 目标

新增一个只依赖 Application 的 Desktop Interface 进程入口。

### 新增

```text
src/uthcode/interfaces/desktop/__init__.py
src/uthcode/interfaces/desktop/__main__.py
src/uthcode/interfaces/desktop/protocol.py
src/uthcode/interfaces/desktop/bridge.py
tests/test_desktop_protocol.py
tests/test_desktop_bridge.py
```

### 修改

```text
tests/test_architecture_boundaries.py
```

### 实施

1. JSONL parser/writer；
2. request/response correlation；
3. runtime lifecycle state；
4. one Application / one Run / one active Turn；
5. project initialize/switch；
6. Session catalog/new/resume/replay；
7. turn start/steer/pause/resume/cancel；
8. AgentEvent passthrough；
9. command completion/execute；
10. status；
11. settings bootstrap；
12. stdout protocol purity；
13. stderr diagnostics；
14. graceful shutdown。

### 禁止

```text
Core import
Provider direct import
Tool direct execution
generic RPC reflection
universal event bus
future device protocol
```

---

## T03：Electron Shell 与 Python Process

### 目标

建立安全 Desktop Shell，并稳定拥有 Python child lifecycle。

### 新增

```text
desktop/package.json
desktop/package-lock.json
desktop/forge.config.ts
desktop/tsconfig.json
Webpack configs
desktop/src/main.ts
desktop/src/python-runtime.ts
desktop/src/preload.ts
desktop/src/desktop-api.ts
desktop/src/desktop-preferences.ts
```

### 实施

1. Electron 44 stable；
2. Forge 7.11.2 stable；
3. Webpack plugin；
4. secure BrowserWindow；
5. narrow contextBridge；
6. child_process.spawn Python bridge；
7. 不使用 shell wrapper；
8. stdin/stdout JSONL；
9. stderr 单独收集；
10. request timeout / process exit rejection；
11. folder picker；
12. open-in-Explorer narrow action；
13. preference persistence；
14. app close graceful shutdown；
15. orphan process test。

### 完成边界

Renderer 可以通过一组窄 API：

```text
openProject
requestRuntime
subscribeAgentEvents
read/write Desktop preference
```

工作，但拿不到 Node 原生对象。

---

## T04：Desktop 主界面、Project 与 Session

### 目标

把 HTML 原型收口为真实 React Desktop Shell。

### 新增/修改

```text
desktop/src/renderer/App.tsx
Sidebar.tsx
state.ts
app.css
对应测试
```

### 实施

1. 左栏 New chat / Open project；
2. pinned / projects / recent；
3. 项目 expand/collapse；
4. native folder picker；
5. inline project alias rename；
6. in-app remove confirmation；
7. project open/switch；
8. session catalog；
9. session click direct resume；
10. safe replay 替换 Timeline；
11. new Session → blank Timeline；
12. Session label 使用 preview / ID fallback；
13. settings entry；
14. 删除 fake account/logout/usage；
15. 删除 hover preview cards；
16. 禁止静态 projectStore 成为生产事实。

### 完成边界

真实切换三个不同 Session 时，中部内容必须随 Session 改变，且继续输入写入被选中的 Session。

---

## T05：Conversation Timeline、Streaming 与 Composer

### 目标

完成普通对话与运行状态的 GUI parity。

### 新增/修改

```text
ChatTimeline.tsx
Composer.tsx
state.ts
app.css
对应测试
```

### 实施

1. replay projection；
2. AgentEvent live projection；
3. assistant Markdown；
4. reasoning；
5. Tool start/end/fail；
6. errors；
7. provider retry state；
8. active turn state；
9. normal start_turn；
10. steering；
11. pause；
12. cancel；
13. Todo compact progress；
14. CompletionBlocked；
15. status/context runtime projection；
16. model selector；
17. permission selector；
18. behavior mode selector；
19. Slash completion；
20. Slash execute；
21. `/clear` 只清 visible view；
22. `/quit` 正常 shutdown。

### 完成边界

当前 TUI 普通交互不需要打开终端即可完成。

---

## T06：Typed Interaction Surface

### 目标

完整迁移 AskUser / Permission / Plan Review / Retry。

### 新增/修改

```text
InteractionSurface.tsx
ChatTimeline.tsx
Composer.tsx
state.ts
对应测试
```

### 实施

#### AskUser

```text
request
→ Timeline asking/waiting
→ Surface
→ answer
→ Timeline answered
→ same Turn resume
→ Agent continue
```

#### Permission

```text
request
→ Reject / Allow Once / Allow for Session
→ same Turn resume
```

#### Plan

```text
Plan vN
→ Approve / Revise / Cancel
→ same Turn resume
```

#### Retry

```text
typed retry request
→ user decision
→ same Turn resume
```

### 强约束

pending typed interaction 时 Composer 不得发送 steering。

---

## T07：Settings 与 Theme

### 目标

将已拍板 1B 落到正式 Desktop Settings，同时完成 Dark/Light。

### 新增/修改

```text
SettingsView.tsx
app.css
desktop-preferences.ts
相关 Application config use case 调用
对应测试
```

### 实施

1. 只显示真实 Settings category；
2. Provider editor；
3. Model editor；
4. default model；
5. default permission；
6. API Key masked/replace；
7. runtime-affecting config save + safe rebootstrap；
8. active Turn 阻止 runtime rebootstrap；
9. system/dark/light；
10. theme persistence；
11. 删除 HTML fake settings；
12. settings flat rows，禁止 cards；
13. 产品中不出现工程/设计说明文案。

---

## T08：Windows Runtime Bundle 与 Installer

### 目标

普通用户无需 Python 即可安装运行。

### 新增/修改

```text
desktop/packaging/uthcode-runtime.spec
desktop/scripts/build-python-runtime.mjs
desktop/forge.config.ts
desktop/package.json
pyproject.toml（仅增加实际 build/dev 依赖）
```

### 实施

1. PyInstaller onedir；
2. 构建 `uthcode-desktop-runtime.exe`；
3. smoke test；
4. Forge extraResource；
5. packaged path resolution；
6. Squirrel.Windows maker；
7. `Setup.exe`；
8. Windows 11 x64 clean install test；
9. no system Python test；
10. startup/shutdown test；
11. uninstall test。

### 禁止

```text
Auto Update product
Windows Service
Tray Agent
Background daemon
```

---

## T09：[接入主流程] Desktop 全链路接入

### 目标

所有分块能力接入真实 Desktop，不保留 prototype stub。

### 实施

必须删除/不存在：

```text
alert() 工程行为
prompt()
confirm()
static fake runtime state
fake AskUser button
fake Plan button
fake Permission button
fake Settings categories
fake session messages
```

正式链路：

```text
User
→ Renderer
→ Preload
→ Main
→ Python Bridge
→ Application
→ Core
→ AgentEvent
→ Bridge
→ Main
→ Renderer
```

同时验证：

```text
uthcode
仍启动 TUI

uthcode exec
仍为 headless
```

---

## T10：[端到端验证] Windows Feature Parity

### 目标

逐条完成第 6 节 Feature Parity Matrix。

至少使用一个真实 Windows 11 x64 E2E 场景：

```text
安装
→ 首次配置
→ 打开 Re-UthCode 项目
→ 新建 Session
→ 普通对话
→ Tool
→ AskUser
→ Permission
→ Plan
→ Todo
→ Steering
→ Pause
→ Resume
→ Model
→ Permission Mode
→ Compact
→ Status
→ 退出
→ 重启
→ 点击旧 Session
→ 历史恢复
→ 继续对话
```

另测关键失败路径：

```text
invalid config
bad api key / provider failure
invalid IPC
Python runtime crash
Session corrupt/busy
active Turn close
active Turn project switch
```

---

## T11：[遗留负担清理] 迁移收口

检查并删除：

```text
重复命令定义
重复 Agent event model
Desktop Session truth
Desktop Permission truth
Desktop Plan/Todo truth
unused abstraction
future protocol placeholder
fake HTML data
unused component
dead IPC method
card component
design-description product copy
old prototype interaction
```

同时执行：

```text
Python architecture tests
Python full pytest
Desktop unit tests
Desktop Electron E2E
npm build
Forge package
Forge make
PyInstaller smoke
```

---

## 32. 测试矩阵

### 32.1 Python Bridge

必须覆盖：

| 场景 | 验收 |
|---|---|
| valid request | 对应 Application use case 被调用一次 |
| invalid JSON | 返回 protocol error，不崩 |
| unknown method | 拒绝 |
| duplicate/unknown response | 拒绝 |
| start Turn | 一个 active handle |
| second start | 不允许 |
| steer | 同一 handle |
| typed resume | request kind 匹配 |
| cancel | terminal state |
| event | 顺序保持 |
| shutdown | Application close |
| stdout | 每行均是合法 JSON protocol |
| stderr | 不影响 parser |
| secret | response/event/error 无 API Key |

### 32.2 Electron Main / Preload

必须覆盖：

```text
Renderer 无 require
Renderer 无 process
Renderer 无 fs
Renderer 无 child_process
window.electron / window.uthcode 仅窄 API
IPC sender validation
folder dialog 只能返回 path
openPath 只能通过明确项目 action
Python child exit → pending request reject
shutdown → child reaped
```

### 32.3 Renderer

必须覆盖：

```text
new Session clears old timeline
resume replaces timeline
replay + live continuity
streaming
reasoning
tool
failure
AskUser request
AskUser answer
AskUser → agent continue
Permission
Plan revision / review
Retry
Todo
CompletionBlocked
steering
pause
cancel
model
permission mode
behavior mode
slash
clear
compact
status
settings
dark
light
```

### 32.4 Visual rule guard

至少增加一组简单静态/组件检查：

不得存在生产 UI 中的：

```text
“工程参考”
“设计说明”
“GUI 化”
“演示”
```

不得引入：

```text
Card
CardGrid
DashboardCard
SettingCard
ToolCard
```

等用于卡片式产品布局的自建通用组件。

这里不是禁止所有有边界的 Dialog/Surface，而是禁止将信息架构变成卡片堆叠。

### 32.5 Regression

现有：

```text
tests/test_tui.py
tests/test_application_runs.py
tests/test_agent_events.py
tests/test_agent_interaction.py
tests/test_architecture_boundaries.py
以及全量 pytest
```

必须继续通过。

---

## 33. Windows 人工验收清单

### 安装

- [ ] `Setup.exe` 可安装。
- [ ] 没有 Python 的 Windows 11 x64 机器可启动。
- [ ] 启动时不出现终端窗口作为产品入口。
- [ ] Runtime 异常时显示可理解错误，不显示 Python traceback 给普通用户。

### Project

- [ ] “打开项目…”打开 Windows 文件夹选择器。
- [ ] 选中路径后项目进入左栏。
- [ ] 编辑名称只改显示名。
- [ ] 移除项目不删除磁盘文件。
- [ ] 右键/菜单无浏览器 prompt/confirm。

### Session

- [ ] 点击 Session 立即显示真实历史。
- [ ] 不存在“恢复会话页”。
- [ ] 恢复后下一条消息继续该 Session。
- [ ] 新 Session 中部为空。
- [ ] Session 切换不残留上一个 Timeline。

### Chat

- [ ] Agent Markdown 可读。
- [ ] reasoning 与 final 区分。
- [ ] Tool 时序正确。
- [ ] Provider failure/retry 正确。
- [ ] active Turn 可 steering。
- [ ] pause 与 cancel 明确区分。

### Interaction

- [ ] AskUser 请求出现在 Timeline。
- [ ] AskUser waiting 有状态。
- [ ] 回答后 Timeline 显示完成态。
- [ ] Agent 从同一 Turn 继续。
- [ ] Permission 三种当前真实动作可用。
- [ ] Plan Approve/Revise/Cancel 可用。
- [ ] 新 interaction 可以在继续后再次出现。

### Settings

- [ ] 未配置状态可直接进入 Provider/Model 配置。
- [ ] API Key 保存后不回显。
- [ ] 不存在 UthCode 当前不支持的配置项。
- [ ] 不存在空 Settings category。
- [ ] Dark / Light / System 可用。
- [ ] Settings 不使用卡片堆叠。

### Layout

- [ ] 主页面没有设计说明文案。
- [ ] Tool/Plan/Permission/Settings 不使用小卡片布局。
- [ ] Runtime panel 可 floating/dock/hide。
- [ ] 窄窗口下主 Chat 仍可用。

### Exit

- [ ] 有 active Turn 时退出可收口。
- [ ] Electron 退出后没有残留 UthCode Python child。
- [ ] 重启后 durable Session 可重新恢复。
- [ ] 不恢复已中断的 active Turn。

---

## 34. 能力欠账

### 当前 T10 新增能力欠账

**无。**

说明：

当前项目已有的：

```text
active / paused Turn 跨进程重启恢复
pending Permission / AskUser waiter 重启恢复
Provider request checkpoint
Persistent Runtime Recovery
```

仍属于既有后置能力。

T10 不触发它们的实现条件，因为本任务已明确：

```text
Desktop 退出
→ cancel / close active Runtime
→ 下次只恢复 durable Session safe boundary
```

因此不得把这些既有后置能力偷偷纳入 T10。

---

## 35. Out of Scope

T10 明确不做：

```text
Subagent
Multi-Agent
Agent teams
Git Diff 产品页
Git staging
Git commit UI
Git branch manager
Worktree
PR
Code review UI
Memory
Skill
MCP
Plugin platform
Everything-is-plugin
Universal Event Store
Universal Agent SDK
Remote Device
FastAPI gateway
WSS
Android
Wear OS
iOS / watchOS
Car
Voice
STT
TTS
Computer Use
Browser
IDE extension
Web UI
Cloud sync
Account / Login
Usage billing
Automations
Background Agent
Windows Service
Tray Host
Auto Update
Session title system
Project filesystem rename
Runtime checkpoint
Active Turn restart recovery
```

Codex Desktop 或 DeepSeek Harness 中即使存在上述能力，也不得因此进入 T10。

---

## 36. 外部工程参考定位

实施时只需查看与 T10 当前问题直接相关的部分：

### Codex

- OpenAI：Codex Desktop 当前正式产品界面；
- `openai/codex`：
  - `codex-rs/app-server/README.md`
  - stdio JSONL；
  - request/response/event；
  - turn/steer；
  - approval/server-initiated request；
  - shutdown / bounded lifecycle。

只参考机制，不复制其 Multi-Agent / Diff / Worktree / Skills / Automations。

### DeepSeek Harness

- `deepseek-ai/deepseek-harness`
- `docs/cookbook/extension-cookbook.md`
  - UI 从 `session/event` 投影；
  - 输入通过 agent API 返回。
- `docs/architecture.md`
  - 只作为“UI 不拥有 Agent 真相”的对照。

不采用其 Everything-is-a-Plugin 与 Event Store 架构。

### Electron / Forge

以当前官方文档为权威：

- Electron Process Model；
- Security Checklist；
- Context Isolation；
- Sandbox；
- contextBridge；
- IPC；
- Electron Forge Webpack Plugin；
- Squirrel.Windows Maker。

### Python Bundle

以 PyInstaller stable 文档的 `onedir` 行为为依据。

---

## 37. 实施顺序

固定依赖顺序：

```text
T01 Config use case
        ↓
T02 Python Bridge
        ↓
T03 Electron Shell / Process
        ↓
T04 Project / Session
        ↓
T05 Timeline / Composer
        ↓
T06 Interaction
        ↓
T07 Settings / Theme
        ↓
T08 Packaging
        ↓
T09 接入主流程
        ↓
T10 E2E
        ↓
T11 清理
```

可以在同一 Worker 内串行合并强相关 Task，但不得在 Bridge 与 Application contract 尚未稳定前大规模写 Renderer 假数据。

禁止实施顺序：

```text
先把 HTML 完整 React 化
→ 用 fake store 跑通
→ 最后再接 Python
```

正确顺序是：

```text
Application truth
→ Bridge
→ Electron process
→ UI projection
```

---

## 38. Definition of Done

只有同时满足以下条件，T10 才可判定完成：

- [ ] 当前基线 TUI 用户能力全部进入 GUI Feature Parity。
- [ ] Desktop 不拥有第二套 Agent Runtime 事实。
- [ ] Session 恢复使用 Application safe replay。
- [ ] 新 Session 页面为空白。
- [ ] AskUser 完整 request → answer → continue 链路可观察。
- [ ] Permission / Plan / Retry 复用 typed resume。
- [ ] Slash Commands 仍以 Python Registry 为唯一权威。
- [ ] GUI Settings 只包含当前真实配置。
- [ ] API Key 不通过 read/event/log 回显。
- [ ] Runtime 未初始化时仍可通过 GUI 配置。
- [ ] Renderer 无 Node / filesystem / child process 权限。
- [ ] Python runtime 使用 stdio JSONL。
- [ ] 一个 Desktop 只有一个 active Application / Run / Turn。
- [ ] 关闭 Desktop 后无 orphan Python process。
- [ ] Windows 11 x64 Installer 可安装并运行。
- [ ] 用户机器无需 Python。
- [ ] Dark / Light / System 均通过验收。
- [ ] 产品不存在“小卡片”信息架构。
- [ ] 产品不存在“设计说明式”可见文案。
- [ ] 不存在 Subagent / Git Diff / Worktree 等未来能力入口或占位。
- [ ] `uthcode` TUI 行为不退化。
- [ ] `uthcode exec` 行为不退化。
- [ ] Python 全量测试通过。
- [ ] Desktop 单元 / 集成 / E2E 通过。
- [ ] 无重复 authority、未来占位、兼容层、dead code。

---

## 39. 实施代理最终约束

执行 T10 时始终遵守：

> **先证明这是当前 UthCode 已有能力，再给它做 GUI。**

如果在 Codex Desktop、DeepSeek Harness、HTML 原型或实现过程中发现一个“看起来很适合顺手做”的能力，但当前基线没有真实调用链：

```text
不要实现
不要画入口
不要新增协议字段
不要写 TODO placeholder
不要为未来抽象
```

如果某一 GUI 需求只能通过改变现有 Core 稳定语义才能成立：

```text
停止该范围
记录事实与影响
交由用户重新拍板
```

否则按本任务书继续完成 T10，不再为普通实现细节制造新的拍板事项。
