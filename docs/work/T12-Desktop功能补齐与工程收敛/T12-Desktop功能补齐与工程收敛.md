# T12-Desktop功能补齐与工程收敛

## 1. 分析基线与当前实现

- **仓库**：`https://github.com/undertaker33/Re-UthCode`
- **分支**：`main`
- **本轮实际核查 HEAD**：`74f9e24b64b8b587d00d057bba3a81b8906a6a90`（2026-10-10 查询）。本地拆分前必须复核该 SHA 之后的相关改动。
- **任务性质**：`T12`。新增会话检索/归档、General Agent 独立聊天入口、消息聚合及审阅能力占主要交付范围；Settings 与输入框修复是其中的体验收敛，故不采用 `F04`。
- **任务阶段**：Web 阶段只读探索后的最终需求文件；未修改仓库，未实施或执行本任务测试。

### 1.1 权威规则与当前事实

以下规则已读取，应在本地重新核查：`AGENTS.md`、`docs/README.md`、`docs/Context-Index.md`、`docs/rules/WorkPackageRules.md`、`docs/rules/UserDecisionBoundary.md`、`docs/OutstandingDebtList.md`。具体实施必须遵守 `interfaces -> application -> core`、Application 组合 Integrations、Core `RunState` 单写者、Session 和配置安全边界。T11 已在当前 `Context-Index.md` 中登记为 `implemented_unarchived`（冻结 Checklist 61/61），不得重复建设其已有能力。

| 路径 / 关键符号 | 已核实的事实及本轮影响 |
| --- | --- |
| `desktop/src/renderer/App.tsx` / `saveSettings`、导航与 `Composer` 组合 | Renderer 当前管理 Coding Project/Session、界面状态和 Runtime 操作；Settings 仍执行全局保存，并在配置写回后触发项目/Session 投影重新引导。现有 `view` 仅为 `chat/settings`。 |
| `desktop/src/renderer/Composer.tsx` / Model、Permission `CustomSelect` | 模型和权限选择目前经 `onCommand('/model …')`、`onCommand('/permission …')`；输入正文为 `state.composerText`。需检查并修复切换时草稿被命令结果/状态复位清空的真实路径。 |
| `desktop/src/renderer/Sidebar.tsx` / `SessionEntry`、`sessionGroups` | 项目与 Session、最近会话、会话 `···` 菜单、置顶/重命名/移动已存在；尚无会话归档菜单项和 General 独立列表。 |
| `desktop/src/renderer/ChatTimeline.tsx`、`state.ts` / Timeline | 已投影 user、reasoning、assistant、tool、plan、status、compaction 和工具状态，当前按条展示工具；实时工具计时主要来自 `Date.now()`，历史不能据此伪造耗时。 |
| `src/uthcode/core/agent_events.py` / `AssistantMessageKind`、`ToolStarted`、`ToolFinished`、`ToolProgress` | 已有 Progress/Final/Incomplete、ToolCall 标识、工具启动/结束/进度事件；可作为 UI 聚合依据。核心事件不包含完整历史工具输出和通用持久耗时保证。 |
| `src/uthcode/application/sessions.py` / `ApplicationSessionService`、`SessionCatalogEntry`、`read_history_page` | 已有 Session 标题/模型、项目目录、可恢复 Session、历史分页和持久 Replay；目录读取可以不恢复每个 Session 的 Agent Runtime。 |
| `src/uthcode/integrations/session_files.py` / `SessionMetadata`、`SessionFileStore` | `metadata.json` 含 `project_key/title/model_ref` 等，无 `archived` 字段；Transcript/Timeline 为 Session 持久化权威，按页读取，无现成全文索引。 |
| `src/uthcode/interfaces/desktop/bridge.py` / `DesktopBridge` | JSONL RPC/事件投影、后台 Session Runtime、配置写回与进程输出；已有 `session.rename`、`session.move`、`history.page`、`settings.save`，无正式 `session.search`/`session.archive`。 |
| `src/uthcode/application/bootstrap.py` / `create_application` | 已可组合独立 Application/Run/Session/Provider，支持传入 Tool 集合；默认 Session root 为用户级 `~/.uthcode/sessions`，Session 当前按项目身份区分。 |
| `src/uthcode/prompt_assets/__init__.py`、`core/prompt.py` | 当前打包资产为公共 Coding Prompt；General 需要最小独立 Prompt 语义，但不能由简单切换 UI 直接继承 Coding 的写代码行为。 |
| `src/uthcode/application/generation.py` / `reload_configuration` | Application 已支持重组 Provider/Tool、保留原有 Session、Context 和 ProcessSessionManager；现有 Bridge `settings.save` 因 `_ensure_no_active` 要求所有 Turn/Compact 空闲。无需为每个字段重启 Python child。 |
| `docs/Tools.md`、`integrations/tools/git_tools.py` / `GitWorkspace` | 已有只读 Git 工作区工具；可参考其可信路径、只读 Git 调用方式。现有 Agent Tool 不是自动可用于 Renderer 的任意文件读取权限。 |
| `desktop/src/renderer/FileCard.tsx`、`DocumentPreviewPanel.tsx`、`safe-markdown.tsx` | 已有附件/产物受控预览、Markdown 与语法高亮和外部文件显式授权，需复用并扩展为一致的右侧审阅，不另建绕过 Main/Application 的磁盘接口。 |
| `desktop/src/main.ts`、`preload.ts`、`desktop-api.ts` | Electron Main/preload 限制 IPC 来源和允许的方法；新增 RPC 必须经过两端的精确白名单与参数验证。 |

当前代码事实与设计说明冲突时，以 `src/ + desktop/src/ + tests/ + desktop/tests/` 为准。本轮未运行现有单测、打包或真实 Provider E2E；本文所有验收项均为**计划验证**，不是已通过结果。

### 1.2 正式视觉资产

下列文件由用户放在本任务书**同级的 `references/` 目录**。引用始终是**相对于本任务书本身**，不引用个人电脑绝对路径；本地拆分时不得擅自改名或用过往 V1—V3 代替。

| 资产 | 任务包相对路径 | 作用 |
| --- | --- | --- |
| Coding 主界面 | [`references/coding-reference.png`](references/coding-reference.png) | 现有左侧项目树、中部过程聚合、右侧 Diff/文件审阅的视觉基准 |
| Settings 页面 | [`references/settings-reference.png`](references/settings-reference.png) | 设置侧边分类、字段排布、Provider 列表、保存与生效反馈 |
| General 页面 | [`references/general-reference.png`](references/general-reference.png) | 独立聊天、最近会话、模型选择及弱化技术诊断的界面 |
| V4 原型 | [`references/UthCode-Desktop-V4.html`](references/UthCode-Desktop-V4.html) | 尺寸、样式、布局及交互示意；其 JavaScript 搜索、归档、自动保存均为模拟实现 |

**参考优先级**：本任务书的明确行为与仓库冻结约束 ＞ 三张 PNG 的布局和交互位置 ＞ V4 HTML 的静态样式/模拟动作。PNG 中的命令、行数、模型名和 Git 仓库示例不是事实数据。HTML 中 General 侧栏的“归档的会话”入口**已被用户最新决定取代**：统一归档管理必须放在 Settings 内。用户要求本阶段仅做最小 General 聊天，故原型出现的附件按钮等不自动升级为必做功能。

## 2. 问题、目标与范围

### 2.1 交付目标及真实入口

**新增正式能力**：

1. **跨项目会话搜索**：从 Coding 左侧搜索入口/快捷键发起，在当前已登记项目范围搜索标题、首条消息预览和用户/Assistant 可公开消息正文；按需读取真实 Session 数据，归档结果可检索并标记，不建立持久全文索引。结果选择后打开正确 Project/Session。General 在自己的 Session 空间检索。
2. **按项目归档 Session**：会话右侧 `···` 增加“归档”；仅归档空闲 Session。Settings 内新增“已归档会话”分类，按 Coding 项目组织、可筛选和恢复，General 会话以独立分组出现。归档不删 Transcript、不移动项目或 Session、不产生第二份会话存储。
3. **General Agent 最小真实聊天**：左上 UthCode 菜单在 Coding / General 间切换，语义类似 ChatGPT Chat / Work 的入口区分，但**不是复刻 ChatGPT 的产品功能**。General 有独立用户级会话空间，使用已配置 Provider/Model，支持文本发送、流式 Assistant 输出、正常最终结果、受控失败/取消、持久历史、新建/重开；不要求打开代码项目。与 Coding 共用正式 Agent Loop/Application/Provider/Context/Session 底座，不另建 Runtime。

**现有 UI/交互改进**：

4. Coding 过程消息按连续活动段聚合、默认折叠，用户中途说明/需要回应的交互/关键失败正确切段；最终回答不折叠；给出有真实依据的耗时与错误摘要。
5. 统一右侧半屏审阅入口：当前 Git Diff、文本/Markdown/图片/产物与有界工具/进程原始输出。中心消息只呈现活动摘要、文件改动摘要和“查看更改/打开预览”等入口。
6. Settings 按视觉基准重组，取消全局保存，字段编辑自动安全持久化，区分已保存和已生效，最大限度避免不必要的 Runtime 重建；不影响现有活动 Turn 或后台进程。
7. **输入框修复**：已有未发送的文字和附件草稿在选择模型、权限时不能被清空；切换失败也应保留，实际发送成功才按既有成功边界清理。

**全仓工程收敛**：

8. 覆盖 `src/uthcode/**`、`desktop/src/**`、相关测试、依赖/打包和维护文档；在真实调用方证据下删除被替代逻辑、无调用方提前抽象、重复状态与无价值兼容，减轻职责耦合。它是本任务的实际交付之一，但不以 LOC 或文件大小作为删除 KPI。

### 2.2 明确不做

- 本次 **General 不建设** 通用工具集、Coding 工具自动继承、联网搜索/文件处理/自动化执行入口、Memory、Skill、MCP、Subagent、Multi-Agent、跨设备同步/通知或个人助理流程。未来工具和能力尚未拍板；现阶段仅要求**配置 API 后能正常聊天**。
- General 不提供模拟可点但无后端能力的附件、代码执行、文件写入或权限开关。本阶段可以不展示这些控件；必要的模型选择与基础取消等为真实功能。
- 不重新设计 Coding 项目树与主壳、不取消现有 Composer 模型选择、不在会话标题右上角另设模型菜单；Settings 入口仍在左下角。
- 不创建第二套 Session/History/Permission/Provider/Agent Loop、独立搜索数据库、后台全文索引、完整 Git 版本快照/撤销编辑器、可写 Git 操作、Worktree 管理或 IDE。
- 不因瘦身改变已有安全、权限、持久化、Tool FIFO、进程运行/回收和历史恢复合同；不进行无证据的“安全最佳实践”式扩建。

## 3. 已确认决定与产品行为

以下行为编号在后文实施和验收中保持稳定。目标是对外可观察语义，而非要求创建同名内部类型。

| 编号 | 场景与触发 | 必须观察到的结果 | 状态/边界 |
| --- | --- | --- | --- |
| R01 | Coding 侧栏搜索，输入标题或正文关键字 | 搜索已登记的所有 Coding 项目会话，展示匹配摘要、所属项目、标题和归档状态；同名会话也能正确区分 | 不为每个会话创建/恢复 Agent Runtime，不写 Session，不建持久全文索引 |
| R02 | 搜索结果属于归档、旧历史或某个收起项目 | 可定位并打开正确原项目/Session；必要时展开项目或明确展示归档提示 | 页面切换和迟到查询响应不覆盖新的选择；不要求自动跳转到消息历史精确行 |
| R03 | 搜索中出现损坏、无权限、已移除或不可读取项目/Session | 结果有界、可取消；局部不可用受控反馈，不泄露项目之外资料；不因单条失效清空其他结果 | Coding 仅搜索当前可信已登记项目；退出项目登记不删除磁盘 Session |
| R04 | 某空闲 Session 的 `···` →“归档” | 只归档此 Session，从普通项目子列表及最近列表消失，可在 Settings 归档页看到 | 持久归档标记；不更改内容、项目归属、消息时间与模型 |
| R05 | Session 有 active/paused Turn、未完成交互或 Compact | “归档”被禁止或返回可理解的拒绝，不主动取消任务 | 以目标 Session 的真实运行/操作状态为依据；无关 Session 活跃不应妨碍归档另一个空闲 Session |
| R06 | Settings →“已归档会话” | 按原 Coding 项目分类，可按项目/关键字筛选并恢复；General 归档会话独立分组 | 恢复后按照原有 `last_user_message_at`/既定排序规则出现在原 Session 列表；与置顶状态相容 |
| R07 | 归档、恢复后重启 Desktop；或用户从最近项目中移除项目再重新登记 | 归档标记和历史可靠保留；重新登记原项目后可继续查到其会话 | 不创建第二份 Session、复制/移动 Transcript；项目移除仅解除 GUI 登记 |
| R08 | 左上产品标识展开菜单 | 仅含 Coding Agent 与 General Agent 的模式切换；Settings 仍从左下进入 | 返回 Settings 后恢复进入前的模式；切换不重建另一套 Agent Loop |
| R09 | 第一次打开 General，没有选项目，已配置有效 Provider/Model | 可新建 General 文本聊天、流式输出、显示正常最终回答；普通模型失败可重试/重新发送 | 独立用户级会话身份，不要求 Coding 工作目录或项目树 |
| R10 | General 新建/恢复/应用重启；在 Coding 与 General 间切换 | 两边各自保有选中会话、历史及未发送输入；已提交 General 历史可持久恢复 | 同一 `Session` 不能误出现在另一模式目录；导航不应自动取消 Coding 正在运行的 Turn |
| R11 | General 对话进行中 | 文本流式增量正常呈现；取消与失败反馈可用；默认不出现代码诊断、Git Diff/项目树、Coding 任务控制 | 本阶段 General 不暴露 Coding/文件/联网 Tool，配置刷新后也不能悄悄重新注册这些工具 |
| R12 | 连续七次工具/命令调用，中间没有面向用户说明/公开 reasoning/待回应交互 | 默认只显示一个折叠活动组，标题显示数量、状态和有据可查的总历时；展开后有每条命令及可用的安全输出 | 可跨 Tool batch 按可见连续片段聚合；不按并发子项耗时求和冒充墙钟耗时 |
| R13 | 连续工具中插入 PROGRESS 自然语言说明、公开 reasoning、审批/问答/计划审阅或关键失败 | 在语义边界切分活动组；重要审批、决策和失败始终直接可见 | 用户消息和最终 Assistant 正文正常显示；不展示未公开的模型私有推理 |
| R14 | Turn streaming、取消、失败、切换 Session 后返回或重载历史 | 分组位置/计数/终态稳定；旧记录缺少原始时间或输出时显示不可用，不伪造耗时、输出 | 有界、脱敏的 UI/History 投影；不改变 Core RunState 或 Provider request |
| R15 | 模型修改工作区文件，用户点“查看更改” | 聊天显示**可验证**的文件及增删统计，右侧可打开当前 Git Diff；历史 Turn 的摘要与当前差异来源清楚标识 | 不将当前工作区状态冒充旧 Turn 的完整 Diff；来源不足不显示假数值 |
| R16 | 右侧打开文件、图片、附件、文档或 Tool/Process 日志 | 复用既有授权、预览和有界输出；支持选项卡/关闭、返回和 Session 归属隔离 | 不让 Renderer 任意读磁盘；非 Git、文件丢失或权限不足明确显示局部不可用 |
| R17 | Settings 修改单个已支持字段 | 合法值自动保存，显示正在保存、已保存或失败；成功持久化不等于当前所有 Runtime 已生效 | 未保存失败不得虚报成功；不使用全局 Save/提交按钮 |
| R18 | 修改 Theme/Language、Provider/Model/搜索/工具限制/权限默认等 | 界面偏好立即生效；执行配置在现有安全边界重组或标记待生效；尽量不重启/取消运行中的 Runtime | 活跃 Turn、后台 Session 和已启动进程捕获的配置保持不变；生效来源与时间可见 |
| R19 | 连续编辑、保存失败、离开 Settings、切换 Session | 不丢用户有效编辑、不写旧值覆盖新值、不泄露 Key；失败项可修正/重试；已确认持久化事实正确展示 | API Key 维持 SecretValue、用户级可信配置及安全 DTO；项目配置不得提权 |
| R20 | Composer 已有文本/附件草稿时切换 Model/Permission | 切换成功、取消或受控失败后，原草稿保持不变，不产生 Turn，不发送该草稿 | 两种 Agent 模式及各 Session 的草稿各归其主；成功真正提交消息后才清理已提交草稿 |
| R21 | 收敛本次涉及旧路径及审查出的冗余 | 有调用方/替代路径证据的旧实现、重复状态及失效测试被删除或合并，现有行为保持 | 先提交收敛清单和回归证据，不以文件行数替代质量标准 |

### 3.1 归档和检索的补充语义

- 搜索为**跨项目、按需全文检索（用户选 B）**：匹配标题、首条用户消息预览和**正式可展示的用户/Assistant 文本**。不搜索未授权文件、原始 Tool Result、内部 reasoning、Secret、进程日志或隐藏诊断。结果采用稳定 Session identity 和有界命中摘要，排序优先最近匹配或现有 Session 最近用户活动；具体私有排序算法可在实现中收敛。
- **已归档仍可搜索**；搜索结果有明确归档标记。项目下会话仅普通态可见；归档管理只在 Settings 内，不在 Coding/General 侧栏另建“归档的会话”固定入口。
- 归档只对 Session 生效，目标空闲后可归档；若归档对象恰为当前可见会话，安全切换到无选中会话/其他会话，不丢未提交用户输入而不误将草稿写到其他 Session。
- Settings 的归档列表按项目分组；General 单列为独立会话组，避免为其伪造一个 Coding Project。除非确有真实用户操作需要，不增设批量删除、清空归档或整项目归档能力。

### 3.2 General 能力边界的最新修订

- General 的定位是未来承接多端互通的日常私人 Agent，但**当前不是该产品的完整第一期**。本任务只有最小真实聊天闭环，暂不定义未来 Tool、Memory、设备权限或个人任务编排。
- General 可以提供真正的文本输入、模型选择、发送/取消、流式显示、会话新建/选择、持久恢复和基础错误反馈。无需复制 Coding 的 Permission/Plan/Todo/Bash 等控件。暂不启用 General 附件发送；原型“＋ 附件”不作为功能承诺。
- 使用独立的用户级 General 归属和最小非 Coding Prompt；不继承 Coding 专用 AGENTS/目录指令、默认 Coding Tool Registry 或项目级提权。若历史数据没有模式标签，既有会话归为 Coding，不进行无必要全量迁移。
- 当前 Provider 配置无效时，可以进入 General 页面与 Settings，但不能显示假成功聊天；给出配置引导。普通 Session 切换的隔离/所有权沿用已有 Desktop 机制。

### 3.3 Diff 与过程耗时的证据口径

- **用户选 C：混合模式**。历史 Turn 只保存可以从已执行的文件写入行为、可信文件/工作区观察或其他明确来源证明的**变更摘要**，标注属于哪个 Turn/Session；右侧 Git Diff 是**查看时**的当前工作区差异，始终明确其时点。没有可靠的历史快照，不生成“历史完整 Diff”。
- 不能将某条 Bash 命令文本中的文件名、模型自然语言声明或单一当前 `git status` 当作那一 Turn 已编辑文件的充分证据；若有并发外部写入或归属不确定，应降低为“本时间段观察到的变化/无法归属”，或不显示计数。
- 展开活动组至少提供可核实的 Tool 名、执行状态、命令/参数的**安全摘要**与已有安全输出；未持久化的旧输出不得伪造。新生成的输出如需跨重启查看，应通过 Application-owned 有界脱敏投影/现有 Session Tool Result 持久化边界供给，而不是由 Renderer 抓取任意 Tool 文件。
- 总耗时是活动组从首条真实开始时间到最后一个真实终态的墙钟间隔；处于运行中使用实时计时；只知道部分时间就显示不完整/不可用。旧历史缺证据不回填假的秒数。

## 4. 架构、协议与数据流

### 4.1 总体链路与状态所有权

```text
Coding / General UI（两个视图，分别缓存草稿与选择）
  │
  ├── Session Search / Archive / Restore
  │      -> preload / Main 校验调用来源、可信项目和参数
  │      -> Desktop Bridge RPC
  │      -> ApplicationSessionService（搜索/归档用例与可见数据）
  │      -> SessionFileStore（唯一持久 Session/metadata/Transcript）
  │
  ├── General Text Turn
  │      -> Bridge（独立用户级 General 归属）
  │      -> 同一 UthCodeApplication / AgentRun / Provider 模式的正式调用链
  │      -> AgentEvent 安全流 -> Renderer 的 General 投影
  │
  └── Coding Timeline / Preview / Settings
         -> 现有 Bridge/Application/Artifact/Config 权威出口
         -> Renderer 只维护 UI 投影，绝不成为文件/RunState 权威
```

- `SessionFileStore` 负责归档标记持久化以及按需扫描历史的底层文件访问。`ApplicationSessionService` 负责可观察的搜索/归档/恢复语义、Session owner 校验和安全结果投影。Desktop Bridge 只编排请求、取消和当前用户可访问范围，不单独修改 `metadata.json`。
- 归档标记作为 Session v3 metadata 的**可选兼容字段**（缺省未归档），保留已有 Session 物理结构及 schema 的现有兼容约束；仅在确有协议要求时变更 schema。新增归档操作应复用现有 Session writer 的单 Session 一致性边界，原子提交一个目标 metadata 文件，不建设第二份 archive index/文件夹。
- 搜索在 Application/Integration 中以取消友好、有界读取的方式遍历元数据和可展示的 Transcript 文本，避免阻塞 Bridge 主接收循环；**不保存持久索引**。请求/结果携带模式范围与 Session、项目身份，结果仅返回有界 snippet/状态。搜索取消、导航代次和迟到 RPC 由 Desktop 处理。
- General Session 采用可信用户级身份/命名空间（由现有 Session store 和 Application 工厂组合），不复用任意 Coding 项目身份；默认不存在“当前打开的项目”。应用须确保新建、恢复、配置重新加载、模式切换后的 Prompt 与可见 Tool 集合都符合 General 最小聊天边界。General Runtime 的有效工作目录及其可信配置发现不能静默读取 Coding 项目指令，也不能让用户项目目录变成默认 General 权限范围。
- General 流式对话仍走同一 `TurnHandle.events()`、Session Transcript/Timeline、Provider 错误映射/Context 预算；仅页面和组合配置有差异。不要新增 `GeneralAgentLoop`、`GeneralProvider` 或第二套 History/Permission。
- 聚合是 Application 公开 Event/Replay 及 Renderer 的**派生 UI 投影**，不重新解释 Provider 原始 chunk，也不写入 Core RunState。需要历史稳定性的时间/输出/变更摘要只在现有 Application Session Timeline 或等价正式安全记录边界持久；不保存逐帧 UI 展开状态作为模型历史。
- 右侧审阅使用受信 Artifact/File/Tool Result 与 Git 只读查询；Main 仍负责实际系统打开及外部单文件授权。Diff 读取限制在已登记工作区，使用只读 Git 且输出有界；默认不对 untracked 文件生成虚假行数，遇到无 Git 仓库明确说明。切换 Session/项目后，旧 Preview 的迟到回包必须被拒绝。
- Settings **持久化/生效分离**：用户级配置 writer 仍是唯一写入口；字段级编辑避免用陈旧全量草稿覆盖并发修改。保存成功产生持久版本/字段状态，Application 能安全重组的配置在安全边界激活；仍在活动的 Turn 和启动后进程继续使用旧快照，等安全边界到来才应用待更新配置，且不随单项设置频繁 `runtime.shutdown/initialize`。应用失败可观察且不得谎称已生效。

### 4.2 必需公共协议语义（具体名称可按现有风格调整）

| 用例 | 输入与返回合同 | 失败/隔离规则 |
| --- | --- | --- |
| 搜索 Session（**新增 RPC**） | `scope`（Coding 当前已登记项目集或 General 空间）、`query`、有界结果量/必要 continuation；返回 `session_id`、`project_key` 或 General scope、`title`、`snippet`、`archived`、排序依据等安全字段 | query 超限、未知项目、取消、损坏历史、迟到响应受控；不能返回未经授权项目的消息；不构造 Session Runtime |
| Archive/Restore Session（**新增 RPC**） | 明确 `session_id` + 归属 + 目标 `archived: true/false`；幂等返回最终可观察状态/元数据最小字段 | active/paused/compact 拒绝；并发 writer 冲突受控；不能顺便停止 Turn/删除 Transcript |
| General 会话入口（**新增最小能力**） | 独立 General 创建、目录、恢复和 `turn.start` 使用同一公共 Application/Run 合同；界面能识别 mode/session owner | 不能在任意 Project 下偷偷创建 General Session；配置无效明确返回状态；交叉会话/交叉模式引用拒绝 |
| 过程组及审阅来源（**扩展安全投影**） | 利用已有 Run/Turn/ToolCall/Message identity；过程片段的运行时间与状态、可用输出 refs、文件摘要来源和查看时 Git Diff 来源明确 | 缺乏时间/输出/历史 Diff 证据时显式 unavailable，不能做合成完整历史 |
| 设置字段更新（**收敛现有 RPC**） | 可校验的单项/单组变更与独立保存结果，返回 durable/applied/pending/failure 状态及安全来源；不返回秘密 | 更新与应用有独立事实，重复提交不产生重复副作用；运行时活动不被打断；项目配置不可提升权限 |

无需为上述所有用例预建统一 Registry、消息总线、跨所有应用的后台任务系统或新的架构层。实际公开字段、协议版本和局部 DTO 拆分，以满足现有 JSONL 安全边界与验收的最小方案确定，但不能删掉这里已明确的对外语义。

### 4.3 页面与生命周期

- 左上仅切换 Coding/General；从 Settings 返回进入 Settings 前的模式。各模式**独立**选中会话/Composer 草稿/历史显示状态，且 Session 目录互不混入。General 切换回 Coding 不自动关闭后台 Coding Run。
- Coding 保留项目树、最近会话、输入框模型选择、Todo/Permission/Plan 和当前 Runtime 面板可用性；General 默认简洁对话/历史列表，隐藏代码专属技术面板。不能因为视觉隐藏而使 Coding 运行中的审批不可被找回。
- Settings 归档页归类于设置导航，不再按照 HTML 示例放侧栏“归档的会话”。搜索结果中归档会话可进入归档位置/恢复流程；不得悄然当作普通未归档 Session。

## 5. 文件级改动与现有能力影响

以下均为 HEAD 中已验证存在的文件；拟新增的文件以“**按职责可新增**”标识，禁止逐个概念机械造文件。不同任务共享的文件应在本地 Worker 分组中安排**单写者**，减少反复返工。

| 路径 | 操作 | 当前职责、计划改动与复用边界 | 对应行为 |
| --- | --- | --- | --- |
| `src/uthcode/integrations/session_files.py` | 修改 | SessionMetadata 可选 `archived`、writer 幂等更新、列表过滤/归档展示所需字段、按需 Transcript 文本检索与受控损坏处理；无第二存储 | R01–R07 |
| `src/uthcode/application/sessions.py` | 修改 | 搜索/归档/恢复 Application 用例、Catalog 安全 DTO、模式归属与历史文本范围限制；复用分页与 Session writer | R01–R07、R09–R10 |
| `src/uthcode/application/bootstrap.py` | 修改 | General 可信用户级会话/工作目录组合与禁用 Coding Tool 的最小创建路径；保持现有 Coding 默认不变 | R08–R11 |
| `src/uthcode/prompt_assets/__init__.py` + `src/uthcode/prompt_assets/` 内**计划新增 General Prompt 资产** | 修改/新增 | 提供最小非 Coding 公共提示词，仍按现有包资产机制读取，不创建多套 Provider Prompt | R09–R11 |
| `src/uthcode/core/prompt.py`、`src/uthcode/application/generation.py` | 按需修改 | 通过现有 Context/Prompt 合同选择 General 内容并保证配置 reload 后 Tool 可见性不漂移；只变更真实需要的公共边界 | R09–R11、R18 |
| `src/uthcode/interfaces/desktop/bridge.py` | 修改 | 增加 Search、Archive/Restore、General 会话 RPC 与配置字段写回/待生效状态；复用后台 Session 和安全事件投影；拆除被替代的全局拦截/重复重启链 | R01–R11、R17–R19 |
| `desktop/src/desktop-api.ts`、`desktop/src/preload.ts`、`desktop/src/main.ts` | 修改 | 精确列入新增方法、输入 DTO 与 IPC 主体/可信项目校验，新增必要 General 可信空间授权，不放开任意路径 | R01–R11、R15–R16 |
| `desktop/src/renderer/Sidebar.tsx` | 修改 | 搜索入口、Session `···` 归档操作、Coding/General 菜单入口和 mode-aware Session 列表；保留旧项目树 | R01–R05、R08–R10 |
| `desktop/src/renderer/App.tsx` | 修改 | 协调两模式会话/草稿、搜索、归档、右侧面板、Settings 状态；替换导致输入被清空的模型/权限切换路径，删掉重复恢复动作 | R01–R20 |
| `desktop/src/renderer/state.ts`、`state-session.ts`、`state-normalization.ts` | 修改 | mode-aware 的 Renderer 派生/Session 投影、归档/搜索结果与过程片段归并；真实 Event identity 防串台 | R01–R14、R20 |
| `desktop/src/renderer/ChatTimeline.tsx` | 修改 | Tool 过程分组、展开明细/安全输出、耗时、文件改动摘要与右侧审阅入口；最终回答独立展示 | R12–R16 |
| `desktop/src/renderer/Composer.tsx` | 修改 | 模型/权限切换保持草稿；为 General 提供文本聊天必要控件，隐藏尚无功能的 Tool/附件入口 | R09–R11、R20 |
| `desktop/src/renderer/DocumentPreviewPanel.tsx`、`FileCard.tsx`、`safe-markdown.tsx` | 修改 | 统一右侧文件/图片/产物/日志审阅卡片和 tab，沿用现有预览/外部授权，避免完整内容淹没聊天 | R15–R16 |
| `src/uthcode/application/attachments.py`、`src/uthcode/integrations/tools/git_tools.py` | 按需修改 | 复用或少量扩展已存在 Artifact/只读 Git 安全边界；不直接把 Tool 的模型权限等同于 Renderer 文件权限 | R15–R16 |
| `desktop/src/renderer/SettingsView.tsx`、`SettingsEditorModal.tsx`、`settings-draft.ts` | 修改 | Settings 视觉分类、单项自动保存/失败重试/生效来源、Secret 草稿管理和 Settings 归档列表；移除全局 Save | R06–R07、R17–R19 |
| `desktop/src/renderer/` 下**计划按需新增局部组件/样式** | 新增（可选） | 搜索结果弹层、General 会话展示或 Diff 只读审阅等当前真实页面组件；仅在有实际调用方且能使职责清楚时新增 | R01–R03、R08–R16 |
| `src/uthcode/application/` 或 `integrations/` 下**计划按需新增只读审阅实现** | 新增（可选） | 当现有 Artifact/Git 能力不能直接承载 UI 安全只读 Diff/变更摘要时，集中在真实使用层；不得为此造 Git 写入框架 | R15–R16 |
| `tests/test_session_authority.py`、`tests/test_session_files.py`、`tests/test_history_paging.py`、`tests/test_desktop_bridge.py`、`tests/test_desktop_artifacts.py` | 修改 | 新增/调整目录搜索、归档持久化、General Session 隔离、Diff/文件授权、Bridge 失败与竞态回归 | R01–R16 |
| `desktop/tests/renderer-state.test.ts`、`renderer-session.test.tsx`、`renderer-chat.test.tsx`、`renderer-settings.test.tsx`、`renderer-attachments.test.tsx`、`renderer-runtime-lifecycle.test.tsx`、`preload.test.ts` | 修改 | 搜索导航、过程分组/重放、归档 UI、两模式切换、输入草稿、字段保存与迟到响应测试 | R01–R20 |
| `src/uthcode/**`、`desktop/src/**`、相关 tests、打包与依赖描述 | **在具体审计后定点删改** | 有调用方/重复证据才删除或合并；严禁依据本表“全仓范围”自行大规模重排 | R21 |

具体 CSS 路径、局部组件名称和新文件位置由本地代理以当前构建入口确认，不在尚未核实的目录下虚构固定文件。若 HEAD 之后代码已调整，应保留行为与边界、更新实施路径，不静默扩大范围。

## 6. 外部依赖与参考结论

- **当前不要求新增第三方依赖**。优先复用现有 GitWorkspace 的只读调用、Artifact/File 预览、Session 历史分页、安全 markdown、Provider 与配置 writer。若阅读/渲染 Diff 必须引入成熟小型依赖，本地代理需核实当前锁文件、许可证、维护状态及打包大小，再按真实需要引入，不为高亮新建通用 IDE。
- 实施素材以本任务书 §1.2 的三张 PNG 和 V4 HTML 为准；HTML 自己明确其搜索、归档列表、自动保存与 Provider 编辑器为假数据/展示模拟。
- 外部 Codex/Claude/Cursor/ChatGPT 的界面可作补充参照，但本任务没有把未经逐项验证的竞品内部机制作为合同；核心行为以用户已拍板的本任务书为准。

## 7. 实施顺序与依赖

实施分组由本地 `WorkPackageRules.md` 决定；本节描述**一份 T12 正式工作包内部的可验收实施顺序**，并不允许代理未经用户指派自动开始 Worker。可以让文件写集合独立的测试/视觉观察并行，但 `App.tsx`、`bridge.py`、Session metadata 和 Settings 协调代码必须保持明确单写者。

1. **Session 元数据与归档闭环**（R04–R07）：在 `session_files.py` 扩展兼容归档字段/单 Session 写入，再由 Application 暴露归档/恢复、Catalog 过滤和 Bridge/Main RPC；先证实同一个 Session 不被移动/复制且重启后状态不变；完成 A03–A06。
2. **按需跨项目搜索**（R01–R03）：在 SessionStore/Application 实现 metadata+安全正文按需检索、可信项目过滤、有界返回/取消；接入搜索 UI 和正确的 Session 选择。无外部索引。完成 A01–A02、A06。
3. **General 独立最小聊天**（R08–R11）：可信用户级 General Session scope、独立可持续选择、最小 Prompt、模型/Provider 真实请求、Streaming/History/Cancel；切模式时维持 Coding 活动 Turn，Settings 返回原模式。General 无未定工具能力。完成 A07–A10。
4. **过程消息与安全明细投影**（R12–R14）：先从真实事件和 Replay 设计连续过程段、计时与失效回退，再改 ChatTimeline 渲染；同时接入按需安全输出，确保关键交互不被折叠。完成 A11–A13。
5. **文件变更摘要与右侧审阅**（R15–R16）：复用 Artifact/File + GitWorkspace 的只读边界；标注历史 Turn 摘要和当前 Working Tree Diff 的不同来源，支持文件、图片、产物、命令/进程输出的统一右栏、关闭/切换/错误反馈。完成 A14–A16。
6. **Settings 自动保存与归档入口**（R06–R07、R17–R19）：按视觉基准重组分类，移除全局 Save，逐项持久化状态与安全边界应用，归档列表分类/筛选/恢复；确保多次设置修改不触发 Python Runtime 反复重启。完成 A05、A17–A19。
7. **Composer 草稿保持修复**（R20）：定位 Model/Permission 命令回执引起清空的真实路径，避免界面控制命令重置未发送草稿；覆盖文本、附件、失败、Session 和 mode 切换。完成 A20。
8. **工程瘦身与整体联动审查**（R21）：先对当前全仓建立有证据的清理候选（真实调用方、重复/不可达证据、删改风险、回归命令）；已由本次替换的冗余在对应功能步骤随改随删，剩余高把握候选在此定点收敛。对耦合较重的 `bridge.py`、`App.tsx`、`state.ts`、`agent.py`、`context.py`、`sessions.py`，以职责与调用链而不是 LOC 决定是否拆分。完成 A21。
9. **[接入主流程]**：校验 Coding/General 两模式真实入口、Session/搜索/归档/审阅/Settings 共享链路，清理旧全局保存和重复投影；不得保留假功能按钮、双轨或无调用方占位。对应 A01–A21。
10. **[端到端验证]**：执行 §8 中定向自动回归、真实 Provider 文本流式 E2E、受控 Git Diff 和 packaged Desktop UI/CDP/人工验证；记录实际环境与未验证条件。对应 A01–A23。
11. **[遗留负担清理]**：检查失效测试、重复 DTO、冗余 Compatibility 入口、过度封装、旧 UI 样式和无价值构建负担；只删除有证据项，复核未破坏既有安全与文档。对应 A21–A23。

本任务同时涉及 Python Session 与 Desktop UI，建议本地 Worker 按**状态/存储 → Bridge/General 组合 → Renderer UI → 配置修复 → 联合验收/瘦身**组织，相关模块不得被并行 Worker 同时写入。强相关步骤不要求人为拆成独立 Commit，也不授权 Git 写操作。

## 8. 测试与验收

表中既有文件名为真实测试定位；“计划新增测试”并不表示文件/用例现在已经存在。生产 Provider、Windows 原生输入和 packaged UI 需实际条件，不得用 Mock/HTML 截图代替。

| 验收 | 行为/约束 | 验证入口（现有或计划新增） | 通过条件 |
| --- | --- | --- | --- |
| A01 | R01 | 计划新增 Session Search 单测、Desktop Bridge/Renderer 搜索用例 | 两个已登记 Coding 项目、同名 Session、标题/正文匹配与无匹配均正确；不注册新项目 Runtime；未知项目不可搜 |
| A02 | R02–R03 | `tests/test_history_paging.py`、`tests/test_desktop_bridge.py` + 新增搜索取消/损坏用例 | 旧历史命中可进入正确 Session；归档结果带状态；查询取消/迟到不会篡改当前选择；部分损坏有局部反馈 |
| A03 | R04–R05 | `tests/test_session_files.py`、`tests/test_session_authority.py`、`tests/test_desktop_bridge.py` 计划新增 | 空闲目标可归档；active/paused/compact 目标受控拒绝；无关 Session 正在执行不阻断该空闲目标；不删除持久历史 |
| A04 | R06–R07 | 真实持久 Session round-trip 测试 | 归档后重启保持；恢复原 `project_key`、标题、model_ref、时间与内容；移除再登记 Project 不丢归档状态；历史 schema 兼容读取 |
| A05 | R06 | `desktop/tests/renderer-settings.test.tsx` + UI/CDP | Settings 内按 Coding 项目/General 分组，支持项目/文本筛选和恢复；普通/Recent 目录不再显示归档项；Session `···` 有归档入口 |
| A06 | R01–R07 | 计划 Desktop 真正搜索→归档→重启→搜索→恢复联动 E2E | 复核多个项目、多个同名会话、归档与恢复、返回原项目；事件/Session ownership 正确；无假数据 |
| A07 | R08–R09 | 新增 General Renderer/Bridge 定向测试 | 从左上切入 General，不选 Project 也能新建用户级 Session；Settings 返回原模式；没有 Coding 目录串入 |
| A08 | R09–R11 | **真实已配置 API Provider E2E**（必须实际请求、非 Mock） | General 至少一次新对话发送、流式 delta、最终正式回答；配置无效可进入 Settings 并有正确失败提示；正常取消受控 |
| A09 | R10 | Session store 持久化测试 + Renderer mode 切换用例 | 重启 Desktop 后 General 历史可恢复；Coding/General 历史、草稿和选中 Session 互不覆盖；模式切换不断开已有 Coding 后台 Turn |
| A10 | R11 | 应用工厂/配置刷新/Bridge Tool 可见性测试 | General 默认不注册 Coding/文件/联网工具，且配置保存与再次恢复后也不泄漏；原 Coding Tool 列表及权限行为不变 |
| A11 | R12–R13 | `desktop/tests/renderer-chat.test.tsx`、`renderer-state.test.ts` 计划新增过程片段测试 | 连续 7 个 Tool→一组默认折叠；插入公开进度说明/审批/关键失败时正确切组，最终正式回答可见 |
| A12 | R12–R14 | event replay/live 合并、取消及历史分页回归 | Run/Turn/ToolCall/Message 归属准确，切换不混组；不对无历史时间的记录生成假耗时；运行中可显示真实流逝时间 |
| A13 | R12–R14 | Tool/Process 输出安全投影与历史用例 | 展开可看真实安全信息及可用输出；超限/缺失/旧历史显示正确不可用反馈；审批、失败始终显著可见 |
| A14 | R15 | 计划新增 Git 只读服务/文件写入观测测试 | 当前 Git Diff 是当前状态；历史 Turn 摘要只展示可证实来源；非 Git 或外部并发变化不虚构文件数、增删行数 |
| A15 | R16 | `tests/test_desktop_artifacts.py`、`desktop/tests/renderer-chat.test.tsx`、`preload.test.ts` | 文件/Markdown/图片/安全附件/日志审阅均受限，右侧可关闭/切换；外部路径必须有原有显式授权；错误局部反馈 |
| A16 | R15–R16 | **真实本地 Git 工作区操作 + packaged Desktop 审阅** | 在可核实修改后从聊天进入右侧正确 current diff，红绿行与路径可靠；切换项目/Session 无旧预览串台 |
| A17 | R17 | `desktop/tests/renderer-settings.test.tsx` + 配置 writer 测试 | Settings 字段无全局 Save；逐项修改真实持久化；失败保留输入并可重试，状态区分保存与实际应用 |
| A18 | R18 | `tests/test_desktop_bridge.py` + `desktop/tests/renderer-runtime-lifecycle.test.tsx` | 连续改偏好/配置不逐次 shutdown/initialize；安全边界可生效；后台 Run/活进程不取消或被重新绑定到新快照 |
| A19 | R19 | 配置/Secret 安全负例测试 + UI 测试 | Provider Key 不进入 Session/Prompt/日志/安全 DTO；未编辑密钥仍保留原 literal/env 表达；项目配置不得提权；无静默覆盖竞争 |
| A20 | R20 | `desktop/tests/renderer-state.test.ts`、`renderer.test.tsx`、`renderer-attachments.test.tsx` + 计划用例 | 输入非空文字+至少一份未提交附件，成功/失败切换 Model、Permission 后都保留；不产生 Turn；只有成功发送才清理其所属草稿 |
| A21 | R21 | 本地可复核瘦身清单 + 精确引用检查、定向测试 | 每项删除有真实调用证据与回归验证；无过渡兼容层/重复权威；合理复杂性、安全边界和核心测试未因追求 LOC 被削弱 |
| A22 | 主流程与四层依赖 | `python -m pytest tests/test_architecture_boundaries.py -q`；`cd desktop && npm test`、现有 typecheck/build 脚本 | 所有受影响的公开路径、架构及 Renderer 回归通过；脚本/结果记录精确；不得冒称未运行的命令已通过 |
| A23 | 视觉与交付 | Windows Desktop packaged/CDP + 原生缩放/点击与人工截图对照 `references/` | Coding、General、Settings 对照三 PNG 与 HTML 布局；搜索/归档/自动保存/右栏为真实交互，不以模拟网页截图验收；无明显溢出、错误弹层或焦点破坏 |

**执行规则**：从现有定向测试开始，必要时扩展至 Python 全量 `pytest`、Desktop `npm test`、现有 TypeScript typecheck、package/make 和仓库规定的 GUI 端到端验收；命令以当时 `pyproject.toml` 与 `desktop/package.json` 为准，不擅自猜测 script 名称。测试通过后只有当新改动、失败或具体疑点破坏原证据时才重跑。完整 E2E 必须覆盖真实 Provider 的 General 流式聊天、真实 Git Diff 与可操作 Desktop；条件不足要标明未验收，不用 Mock 冒充。

## 9. 清理与文档交付

### 9.1 直接替代清理

- 移除 Settings 的**全局保存按钮及仅服务该交互的重复 draft/恢复路径**，保留最小必要的 Provider/Model 单项编辑局部草稿与 Secret 生命周期；勿误删真实 Application 配置写入口。
- 删除在过程组/文件右侧审阅正式接入后失效的逐条工具渲染分支、冗余 Preview 回调及重复状态，只保留一个数据权威；如旧接口仍是 TUI/测试/CLI 的真实调用方，不能误删。
- 清理会话列表里与归档筛选重复的临时 UI 状态，避免普通目录、Recent、Search 和 Settings archive 四套互相矛盾的目录真相。
- 实现后审查 `bridge.py`、`App.tsx`、`state.ts`、`generation.py`、`context.py`、`core/agent.py` 等巨大文件是否存在**实际职责混乱**；按调用图逐项分离而非强制拆文件。测试合并必须保持关键安全/回归覆盖。

### 9.2 全仓收敛记录要求

本地拆分代理先扫描真实调用图，实施 Worker 的 Feedback 对每项实际清理记载：**路径/关键符号 → 唯一或重复调用方 → 冗余证据 → 具体删改 → 回归入口与结果 → 剩余风险**。候选分为高把握低风险、须与功能顺序协调、证据不足暂不处理三类；不得为“零重复代码”制造新 Manager/Protocol/Registry。确有维护成本的旧测试、打包资源、文档与无用依赖同步清理，不对安全回归做无依据瘦身。

### 9.3 应检查及按需更新的文档

- `docs/context/GUI/GUI-Context.md`：双模式导航、搜索/归档与设置、生效边界、Timeline 分组、右侧审阅和 Compose 草稿所有权。
- `docs/context/A03-State/State-Context.md`：Session archived metadata、索引/检索非持久化、历史摘要/真实耗时与会话作用域。
- `docs/context/A04-Orchestration/Orchestration-Context.md`：General 经 Application 的最小组合、Desktop Bridge 公共入口与导航生命周期。
- `docs/context/A01-AgentRuntime/AgentRuntime-Context.md`：仅在 General Prompt/Tool 可见性实际改变公共 Runtime 事实时更新；不扩写未来私人 Agent 架构。
- `docs/user-manual/`：搜索、归档与恢复、Coding/General 选择、右侧审阅、Settings 自动保存的实际用户操作；以 `docs/README.md` 确定对应已有页面。
- `docs/Tools.md`：确认 Coding Tool 列表不变，说明 General 当前仅文本聊天、**无默认工具**；不把 UI 只读 Diff 当成新增模型 Tool。
- `docs/core-design/`、根 README：只对真正新增且具有长期机制意义的知识与产品能力更新，不把本工作包过程直接搬入教程。
- `docs/Context-Index.md`：由本地工作包拆分/包级验收按规则维护状态；本 Web 阶段不修改。

## 10. 能力欠账

**本轮无新增、变更或完成回补的能力欠账项。**

已核对 `docs/OutstandingDebtList.md`：T03 的 Memory/Skill 指令来源、T04 的动态 Tool、T05/T06/T09 的跨进程 Runtime 恢复、T07 的 Sandbox、T09 的 Evidence Retrieval/跨 Session Artifact 和 Compaction 后置项，均不因本次仅新增 General 基础聊天、会话归档或只读 Diff 而触发完整回补。

用户设想的多端互通私人 Agent（跨设备工具、任务路由、Memory、设备通知与权限）、General 完整 Tool 能力，以及历史完整 Git Diff 版本管理均属于**明确独立未来方向/Out of Scope**，不是“本工作包因某个后置能力未完成而遗漏的必需子功能”，因此不制造欠账记录。若本地实施发现某项既有正式能力确因后置能力而有真实未收口部分，只在符合 `WorkPackageRules.md` 且取得必要决定后登记。索引及欠账清单在本地拆分阶段按规则检查；无变化时保持原清单。

## 11. 本地交接与停止条件

1. 将本 Markdown 作为 `docs/work/T12-Desktop功能补齐与工程收敛/T12-Desktop功能补齐与工程收敛.md` 放入工作包目录，按 §1.2 在同目录建立 `references/`，放入**完全同名**的三 PNG 和 V4 HTML。材料按任务书路径相对解析。
2. 本地代理首先核对 `main` 的实际 HEAD 及 T10/F02/F03/T11 活跃工作包现状，读取 `AGENTS.md`、`docs/README.md`、`docs/Context-Index.md`、`docs/rules/WorkPackageRules.md`、`docs/rules/UserDecisionBoundary.md`，依据路由读取当前相关源码/测试，禁止仅凭本文当作当前代码事实。
3. 按 `WorkPackageRules.md` 拆分本 T12 的 Spec、Tasks、Checklist、Worker Prompt：**Spec** 定范围，**Tasks** 定可执行文件级步骤和 Worker 顺序，**Checklist** 与 §3 行为及 §8 验收建立一一可追踪关系，**Prompt** 只引用独立 Worker 的冻结任务。用户审核 Spec + Checklist 并明确派发后才能实施。
4. 在本地做实际全仓瘦身证据盘点，发现普通私有实现/测试取舍由编码代理自行决策。必须改变冻结的产品行为、共享状态所有权、公共安全边界或实施范围时，引用 `UserDecisionBoundary.md` 给出具体证据/选项并只暂停受影响任务；不得以此反复询问已经拍板的五项及 General 最小范围。
5. 工作包首次正式派发后冻结需求、Spec、Tasks、Prompt 和 Checklist 文字；实施情况追加到对应 Feedback，Checklist 仅勾选。未获用户批准不得自行修改冻结文件、归档、commit、push 或重构无关模块。
6. **交付停止条件**：R01–R21 均有可观察正式链路及 A01–A23 对应有效证据，视觉参照真实 Desktop，用户仍可正常执行 Coding Agent 原任务；确实因外部条件未执行的验收如实标记，不得声称整包已完成。正式包级结束与归档由用户决定。
