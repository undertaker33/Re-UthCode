# F02：Desktop GUI 交互与上下文缺陷修复 Spec

## 背景

T10 已建立 Windows Desktop 到 Application/Core 的正式链路，但真实使用暴露出交互可用性、状态权威、安全投影和工程收敛缺陷。其中选择题自由输入与 Plan 内容流式展示属于跨 Interface 的稳定产品语义，不能由 Renderer 单独模拟；Context、Session 与配置秘密则必须继续由 Application/Core 或既有 Integration 边界持有权威。

本包以原始需求指定且当前仓库实际检出的代码基线为准。T10 活跃工作包仅作为既有实现证据，其已冻结正文不属于 F02 修改范围。

## 目标

- 统一 Core、TUI 与 Desktop 的选择题自由输入语义，删除已经失去产品意义的旧控制字段。
- 从 Provider-independent 的既有工具参数流产生只含 Plan 自然语言内容的安全增量事件，并保持完整正式 Plan 与 Review 的既有权威。
- 由 Application 提供 Context 与 Compaction 的用户安全投影，删除 Renderer 的第二套预算和生命周期判断。
- 允许移动当前已打开但没有活动 Turn 的 Session，并保持失败时原有 Session 所有权完整。
- 修复 Desktop 的命令、Session、聊天、Tool、Todo、AskUser、Plan、Settings、布局、键盘和动画行为。
- 在 F02 触达范围内删除冗余、不可达、旧链路和没有当前调用方的抽象，完成自动与真实 Desktop 验收。

## 能力清单

### T01：AskUser Core 合同硬切

- 所有选择题只保留小型结构化选项集，并始终接受非空自然语言答案。
- 删除旧自由输入开关及其序列化、校验、界面分支和测试夹具。
- TUI 与 Desktop 都提供一致的自由输入路径，保持现有题数与 typed resume/cancel 边界。

### T02：Plan 真流式公共事件

- 从既有统一 Provider 工具参数增量中，只针对正式 Plan 控制工具解码自然语言内容增量。
- 新增最小、可序列化、显示安全的 Plan 内容事件；不暴露原始参数、JSON 片段或 SDK 数据。
- 完整合法的正式 Plan、revision 和 Review 仍由既有最终事件与 Core 状态唯一决定。

### T03：Application Context / Compact 安全投影

- Application 对外提供当前 Context 已用量、有效预算、可用性、测量性质和来源的安全状态。
- durable Session 恢复后根据已提交事实重建估算，不把无法证明的值标为精确。
- 手动、自动与溢出压缩复用同一 Application 生命周期投影；Desktop 不拥有第二状态机。

### T04：Session move 与 Plan replay

- 当前已打开且无活动 Turn 的 Session 可在 Application writer 边界内同步、移动并释放。
- 活动 Turn 仍拒绝移动；失败时源 Session、writer 和项目归属保持有效。
- durable 完整 Plan 在安全 replay 中保持 Plan 身份，未完成 draft 和原始工具正文不进入 replay。

### T05：Desktop 命令、Context 与 Session 投影收口

- Renderer 只消费 Application 的 Context、Compaction、Command、Model 与 Session 投影。
- Desktop 隐藏不适合候选菜单的命令，但不修改命令注册权威；可直接执行的命令不伪装成用户消息。
- Session 移动、排序、折叠和当前选择按冻结的展示矩阵工作，不改 durable Session truth。

### T06：Chat、Tool、Todo、AskUser、Plan 交互完成

- 同一 Tool、Todo、AskUser 和 Plan 事实只更新同一个视觉实体。
- 完成键盘、IME、焦点、菜单定位、elapsed、窄屏、无障碍和 reduced-motion 行为。
- 多题 AskUser 支持前后导航、草稿保留、统一复核与 typed 提交；Plan draft 与 Review 分离。

### T07：Settings 语义、API Key reveal 与页面结构修复

- Settings 只展示协议、端点、密钥、远端模型和显示配置等用户概念，不暴露内部稳定引用。
- 已保存 API Key 仅在用户点击 eye 后通过专用窄请求读取；普通配置、状态、事件、日志和持久 UI 偏好继续无明文。
- reveal 与 replacement/touched 状态严格分离，关闭编辑面或离开 Settings 后清除临时明文。
- Settings 使用分类页与轻量分组，一个 Provider 支持多个 Model，编辑流程具备键盘和无障碍行为。

### T08：GUI 越界、冗余、不可达与过度抽象审查

- 审查 F02 直接触达的 Desktop、Bridge 及新增公共投影，关闭范围内的 correctness、architecture、maintainability 和 privacy finding。
- 删除被新链路替代的第二 authority、重复分支、无调用方 helper、旧 locale/CSS/fixture 和不可达 fallback。
- 只在当前职责已有独立调用与测试边界时做私有局部拆分，不新增通用 Manager、Registry、EventBus 或未来协议。

### T09：[接入主流程] Desktop 生产链集成

- 把 T01～T08 接入唯一的 Renderer → Desktop transport → Bridge → Application → Core 生产链。
- 验证 AskUser、Plan、Context/Compact、Session move、命令、Settings 与 Todo/Tool/Mode 的跨层 identity 和状态连续性。
- 删除被替代的旧入口，不新增 Desktop 专用 Core facade。

### T10：[端到端验证] Desktop 人工与自动验收

- 运行 Python、TypeScript 和 Desktop 全量自动验证，并复用现有 packaged/CDP 验收链。
- 在真实 Desktop 覆盖主题、语言、窗口宽度、键盘/鼠标、IME、缩放、reduced motion、Session、交互、压缩、恢复与 Settings 密钥场景。
- 精确记录已验证、失败和无法验证项，不把未运行的场景写成通过。

### T11：[遗留负担清理] 否定扫描、文档与全量回归

- 对旧 AskUser、Renderer Context、可见内部 model 引用、伪 Plan 流式、重复 Tool 行和 raw 参数路径做否定扫描。
- 同步 Tool、控制层、状态层和 Context Index 当前事实文档，不修改 T10 冻结文件。
- 完成架构、回归、UTF-8 和 diff 检查，保留清晰的未验证项与风险记录。

## 非功能要求

- 保持 `interfaces -> application -> core`，由 Application 组合 Integrations；Renderer 不导入或复制 Core/Integration 权威。
- 原始 Provider/Tool 私有正文、内部 diagnostics、Session 路径和秘密不得因新投影进入普通 Desktop payload。
- API Key 明文只允许存在于用户主动触发的专用 reveal response 与当前组件临时内存；错误、日志、持久状态、Session、Timeline 和测试快照均不得包含。
- 不改变既有 Context Gate、Low Water、Hard Gate、Permission、Secret、Session durability 和 Agent Loop 产品语义。
- 无新增第三方依赖，不引入通用 Tool JSON streaming、第二 Session/Context/Plan/Todo store 或系统级抽象。
- 只处理 F02 明确触达范围，不扩成全仓安全审计、God file 重写或未来能力建设。
- 中文 Markdown 使用 UTF-8，文档与最终 `src/ + tests/` 事实一致。

## 设计骨架

```text
Provider-independent tool argument events
  -> Core private Plan text decoder
  -> display-safe Plan content event
  -> Application / Desktop Bridge
  -> one Renderer Plan block
  -> final Core Plan state and Review
```

```text
Transcript / Timeline / active request / model and provider limits
  -> existing Context compiler and budget authority
  -> Application safe Context and Compaction status
  -> Desktop status projection
  -> display-only Renderer
```

```text
Desktop user action
  -> narrow Desktop API
  -> Desktop Bridge
  -> Application use case
  -> Core or Integration authority
  -> safe result/event
  -> one Renderer projection
```

## 能力欠账

无。

F02 只从已安全提交的 durable Session 重建 Context 和完整 Plan replay，不恢复进程退出时仍活动或暂停的 Turn、AskUser/Permission/Plan Review waiter、Provider 协程或 pending Tool，因此不触发已有 Persistent Runtime Recovery 欠账。`docs/OutstandingDebtList.md` 保持不变。

## Out of Scope

- Persistent Runtime checkpoint、活动或暂停 Turn 跨进程恢复。
- Memory、Dream、Review Prompt、Skill、MCP、Plugin、Subagent、Multi-Agent、Worktree 或新的 Git 能力。
- Voice、登录、云同步、远端设备、新 Provider 协议或新 Context 压缩算法。
- TUI/CLI 替换或删除、全仓大文件重构、与 F02 无关的 Core/Application 清理。
- 通用 Secret Manager、Credential Vault、Event Bus、Manager/Registry/Protocol 体系或兼容旧 AskUser payload 的长期双轨。
- 修改或归档 T10 冻结工作包。

## 验收标准

1. Core、TUI 与 Desktop 的选择题自由输入行为一致，旧控制字段在 active source/tests 中不存在。
2. 正式 Plan 内容从真实 Provider 工具参数流安全增量显示，最终合法 Plan 与 Review 仍由 Core 最终权威决定。
3. Renderer 不再推导 Context 安全预算或 Compaction 生命周期，界面与实际 Context safety chain 使用同源 Application 投影。
4. durable Session 恢复后的 Context 状态不伪造精确值；手动、自动与溢出压缩保持单一生命周期。
5. 当前 open idle Session 可事务移动，活动 Turn 不可移动，失败不损坏源 Session；完整 Plan replay 不泄漏原始工具正文。
6. 命令直接动作、Model/status、Session 排序与折叠符合冻结矩阵，Slash 文本不进入模型消息。
7. Tool、Todo、AskUser 和 Plan 各自只更新一个视觉实体，键盘、IME、焦点、窄屏、缩放与 reduced motion 行为通过。
8. Settings 不展示内部引用；已保存 API Key 可主动 reveal/hide，查看不等于修改，普通投影和持久状态不含明文。
9. F02 GUI 审查中的范围内 P0/P1/P2 finding 全部关闭，旧链路、冗余和无调用方抽象已删除。
10. Python 全量测试、Desktop typecheck/tests、架构测试、现有 packaged/CDP 验收和真实 Desktop 人工矩阵均有精确结果。
11. TUI、CLI、Headless、Permission、Session durability、Context Gate 与配置安全不退化，T10 冻结文件无修改。
12. 当前事实文档、Checklist 与 Feedback 和最终代码一致；工作包不被 Agent 自动归档，也不执行未经用户要求的 Git commit/push。
