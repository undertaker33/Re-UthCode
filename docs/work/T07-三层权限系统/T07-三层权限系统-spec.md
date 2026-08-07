# T07 三层权限系统 Spec

## 1. 背景

T04 已建立唯一工具注册与执行系统，T05 已建立显式顺序 Agent Loop，T06 已建立可序列化的暂停、恢复与询问用户链路。当前六个普通工具仍缺少一套位于参数校验之后、真实副作用之前的统一授权机制；路径工具还会在工作区外直接拒绝，无法表达用户批准后的合法外部访问。

T07 在既有边界上建立 Provider 无关、界面无关的三层权限系统。系统只负责应用层决策与人工审批，不提供操作系统隔离，也不兼容旧 UthCode 的五层权限模型、旧模式、旧规则格式或旧恢复机制。

## 2. 目标

- 以 Action、Rules、Strategy 三层形成唯一权限决策链，输出 Allow、Ask 或 Deny。
- 让六个内置普通工具在参数合法且尚未执行时产生可信动作事实，并在执行前完成授权。
- 支持 `default`、`auto`、`full_access` 三种当前 Run 模式；`full_access` 跳过普通 Policy 与 Strategy，但仍受 Guard 约束。
- 将工作区内外、敏感资源和高置信危险命令作为可审查事实纳入权限决策。
- 复用 T06 的暂停恢复协议完成普通审批和 Guard 审批，支持当前 Run 内有界 Session Grant。
- 通过现有 Application Slash Command Registry 提供 `/permission` 模式选择，并在 TUI、CLI、Headless 三种入口保持安全行为。

## 3. 能力清单

### Task 1 — 全局权限约束与 Core Domain

建立不可变、可序列化、Provider 无关的权限领域模型，以及 Guard、Policy、Strategy 的单一求值语义；同步全局权限约束，使完全访问模式仍保留 Guard。

### Task 2 — Tool Preflight 与 Trusted Action

将工具调用整理为注册检查、参数校验、可信动作分类、授权、执行的单一路径。未知工具和非法参数直接形成现有错误结果，不触发审批；权限事实不进入 Provider 工具定义。

### Task 3 — permissions.toml Discovery / Parse / Template

建立用户级与递归项目级规则文件生命周期，复用现有配置路径发现语义，生成用户默认 Guard 与项目空占位，并把已验证规则转换为 Core 值对象。无效文件或规则必须阻止启动。

### Task 4 — Workspace / Resource Scope 改造

保留路径词法规范化、物理解析、新目标解析和读前写跟踪，将工作区外访问从工具硬拒绝改为权限资源范围事实，使批准后的访问能够真实执行。

### Task 5 — Rule + Strategy Evaluator 与 Guard

实现来源优先级、同来源严格度、Guard、Policy、Session Grant 与三模式 Strategy 的完整矩阵；提供默认敏感资源 Guard、内容搜索保护与跨平台高置信 Bash Guard。

### Task 6 — Permission Pause / Resume 与 Session Grant

扩展 T06 类型化交互协议承载权限审批。普通 Ask 支持单次允许、当前 Run 允许和拒绝；Guard Ask 只支持单次允许和拒绝。恢复必须保持同一 Turn、FIFO、一次执行和取消优先。

### Task 7 — `/permission` Application Session Control 与 TUI

通过唯一 Slash Command Registry 提供当前 Run 模式选择器。完全访问模式必须显示高风险提示；TUI 仅消费 Application 暴露的状态，CLI 不自动批准、不读取输入等待审批，Headless 保持公共恢复 API。

### Task 8 [接入主流程] — 全链路 Composition

在正式组合根接入规则快照、动作分类、权限求值、暂停恢复与工具执行，形成从规范化 ToolCall 到 ToolResult 的唯一生产链，并删除临时旁路或重复入口。

### Task 9 [端到端验证] — Headless / CLI / TUI / Provider

从真实入口验证三种模式、两类审批、Session Grant、外部路径、敏感资源、Bash Guard、Slash Command、取消竞态和三类 Provider 的一致行为，并证明移除 Interface 后 Core 与 Headless 仍可独立运行。

### Task 10 [遗留负担清理] — 旧语义与重复职责清理

清除被替代的工作区硬拒绝和单体工具执行边界，确认没有旧权限层级、旧模式、旧规则格式、持久化 always 决定、第二套暂停协调、第二套命令分发或未来能力占位。

## 4. 非功能要求

- 依赖方向保持 `interfaces → application → core`，Application 可组合 Integrations，Core 不依赖文件系统、TOML、具体界面或 Provider SDK。
- Agent Loop 仍是 RunState 唯一写入者；Tool Batch 保持严格 FIFO，每个 ToolCall 恰好一个 ToolResult。
- 权限请求、事件、日志和规则摘要不得携带秘密值或未脱敏凭据命令。
- 路径范围以规范化后的物理目标判断，覆盖父目录跳转、符号链接、新路径和 Windows 路径差异。
- 规则集在 Run 初始化时形成稳定快照，不热重载；项目规则不能静默提升到完全访问模式。
- Bash 分类与 Guard 只承诺高置信覆盖，无法可靠判断时进入 UNKNOWN；不得描述为 Sandbox。
- 原则上不新增运行时依赖；规则解析复用现有 TOML 依赖，正则与路径处理使用标准库。
- 保持 T04、T05、T06 的公共行为与回归测试，不为兼容旧实现增加适配器、别名、双轨逻辑或废弃入口。

## 5. 设计骨架

```text
Provider normalized ToolCall
        ↓
registered check + schema validation
        ↓
trusted Permission Action
        ↓
Guard Rules → Policy Rules → Session Grant / Strategy
        ↓
ALLOW ───────────────→ execute validated Tool
DENY  ───────────────→ error ToolResult → next ToolCall
ASK   → T06 PauseRequest → Application → Interface/Headless
                                  ↓
                           same Turn resume
```

规则来源按“最近项目 → 父项目 → 用户 → 默认模板”选择最高优先级的有效匹配来源；同一来源同类规则按 Deny、Ask、Allow 的严格度处理。Guard Deny 与 Guard Ask 在三种模式均有效；Guard Allow 在普通模式继续 Policy 与 Strategy，在完全访问模式直接放行。Session Grant 只来自普通 Ask，绑定工具、动作、Effect 与有界资源范围，且不能覆盖 Guard 或显式 Deny。

## 6. Out of Scope

- OS、容器、路径或网络 Sandbox，以及任何权限提升或凭据代理完整系统。
- LangGraph、通用工作流、Shell/PowerShell 完整 AST、通用 Policy DSL 或 OPA/Rego。
- Plan/Todo、Context/Memory、Skill/MCP/Hook、Subagent/Multi-Agent、Worktree。
- AI 权限审查、自动学习、规则热重载、自动持久化 Allow/Deny、`/permission add` 或 `/permission reset`。
- Plugin Permission API、未来扩展 Protocol、Adapter、Registry、字段或占位目录。
- 兼容旧 UthCode 或 Re:UthCode 早期权限类、API、模式、YAML 规则、PathSandbox 或五层模型。

## 7. 验收标准

1. 六个内置普通工具均在注册与参数校验后、真实副作用前生成不可由模型覆盖的可信动作事实。
2. 未知工具和非法参数不触发权限 Ask；Permission 元数据不进入 Provider 工具定义。
3. Action → Rules → Strategy 是唯一生产权限链，三种模式与 Guard/Policy 矩阵一致。
4. 完全访问模式忽略普通 Policy 与 Strategy，但 Guard Ask/Deny 仍生效；Guard Allow 语义无歧义。
5. 工作区外访问不再由工具层硬拒绝，按物理资源范围审批后能够执行；路径与读前写不变量全部回归。
6. 默认敏感资源受到内容级 Guard，Grep 不能旁路；高置信 Bash Guard 的正反例均有不执行危险命令的自动测试。
7. 普通审批、Guard 审批与当前 Run Session Grant 的选项、边界、优先级和生命周期符合需求。
8. Permission Ask 复用 T06 的暂停恢复链；拒绝形成标准错误 ToolResult，同批后续调用继续，恢复不重复副作用。
9. `/permission` 由现有 Registry 提供且只改变当前 Run；完全访问模式有风险提示，CLI 不自动批准，Headless 独立可用。
10. 用户级与递归项目级规则文件的创建、发现、优先级、快照、TOML/regex 错误行为均有自动验证。
11. Anthropic、OpenAI Responses 与 OpenAI-compatible 对等 ToolCall 得到一致权限行为，Interface 不进入 Core 链路。
12. T04/T05/T06 回归、全量测试、编译、依赖检查、差异与编码检查全部通过。
13. 扫描证明无旧权限模式、五层模型、PathSandbox、旧规则文件、持久化 always 决定、重复职责和范围外占位。
