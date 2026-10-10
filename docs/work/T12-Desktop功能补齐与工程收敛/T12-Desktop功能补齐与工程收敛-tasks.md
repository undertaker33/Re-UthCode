# T12-Desktop功能补齐与工程收敛 — Tasks

## 长期 Worker 分组、顺序与依赖

| Worker | 内部严格顺序 | 前置依赖 | 独立 Prompt |
| --- | --- | --- | --- |
| W01 会话归档与检索 | T01 → T02 | 无 | [W01-会话归档与检索-prompt.md](W01-会话归档与检索-prompt.md) |
| W02 General与Desktop公共协议 | T03 → T04 → T05 → T06 | 前一 Worker 的相关任务与定向证据已交付；由用户显式派发本 Prompt | [W02-General与Desktop公共协议-prompt.md](W02-General与Desktop公共协议-prompt.md) |
| W03 Renderer导航与审阅 | T07 → T08 → T09 → T10 | 前一 Worker 的相关任务与定向证据已交付；由用户显式派发本 Prompt | [W03-Renderer导航与审阅-prompt.md](W03-Renderer导航与审阅-prompt.md) |
| W04 配置自动保存与设置 | T11 → T12 | 前一 Worker 的相关任务与定向证据已交付；由用户显式派发本 Prompt | [W04-配置自动保存与设置-prompt.md](W04-配置自动保存与设置-prompt.md) |
| W05 工程收敛与联合验收 | T13 → T14 → T15 → T16 | 前一 Worker 的相关任务与定向证据已交付；由用户显式派发本 Prompt | [W05-工程收敛与联合验收-prompt.md](W05-工程收敛与联合验收-prompt.md) |

整体顺序：W01 → W02 → W03 → W04 → W05。每个 Worker 串行执行其强相关 Task，不能按单 Task 自动拆 Agent。只有无共享写集合与顺序依赖的只读观察/验证可以并行；本计划不默认并行实施。Session metadata/Application、Bridge/Main/协议、App/state 等共享文件在前一 Worker 交付后才向下一 Worker交接，任一时刻保持明确单写者，不建全仓锁。

任务仅由用户指定 Prompt 显式派发。本次生成 Prompt 不构成派发；不用新建任何工作包/Prompt/Feedback 文件夹。每 Worker 首次创建同级同名 Feedback，后续返工只追加原文件。

## 本地核查基线与目录例外

- 拆分日期：2026-10-10；当前分支 `T11-Agent能力补齐`，HEAD `74f9e24b64b8b587d00d057bba3a81b8906a6a90`，与任务书分析 SHA 相同。本地 `main` 为 `8d8a04bfd8c5b93ce40e09dd9c765a79e2878a90`，未 checkout/pull；当前源码是本次依据，Worker 开始时复核 HEAD/diff。
- 已完整读取任务书、AGENTS、文档路由/规则/欠账；三 PNG 已目视核查，V4 确认搜索/保存/Provider 编辑为模拟。参考中的侧栏归档、General 附件、假行数与连接状态服从任务书最新决定。
- 实际已有资产：`references/coding-reference.png`、`general-reference.png`、`settings-reference.png`、`UthCode-Desktop-V4.html`。任务书未移动、未改名。
- 用户本次明确“不新建文件夹”。覆盖 WorkPackageRules 的目录模板：Spec/Tasks/Checklist、五份 Prompt 和未来同名 Feedback **平放现有 T12 目录**，不创建 `prompt/`、`feedback/` 或新的任务目录。首次实施时才创建 `WXX-名称-feedback.md`，后续追加原文件。
- 本次只完成只读拆分核查和文档检查，未实施、未跑产品测试或真实 Provider。无新增待用户拍板的产品/架构/安全问题；已有决定足够收敛具体实现。

| 当前证据路径 / 关键符号 | 核查结果与计划含义 |
| --- | --- |
| `integrations/session_files.py` 的 SessionMetadata/from_dict、SessionWriter._write_metadata（均位于 src/uthcode/） | schema 3 读取拒绝未知字段，writer 已有 lock/原子 metadata 替换；archive 要同步读写可选合同，不 touch 活动时间。 |
| `application/sessions.py` 的 list_catalog_metadata、_project_replay_units | metadata-only 目录和安全 replay 可复用；当前无全文检索/归档事实。TUI list_catalog 与 Desktop metadata-only 均有真实消费者，不能合并成全量 restore。 |
| `application/bootstrap.py`、`generation.py` | tools=() 初次为空但默认 tool_builder 在 reload 再注册 Coding 工具；General 要闭合创建/冷克隆/恢复/刷新。 |
| `application/context.py`、`instructions.py`、`integrations/config/loader.py` | Coding public prompt 与指纹固定，配置发现总读取 cwd 项目；General 需同一组合事实和用户级发现，不能仅新增一份资产/换 home cwd。 |
| `desktop/src/renderer/Composer.tsx` → `App.tsx.executeCommand` → `state.ts.command_result` | 开 Model picker、选 Model/Permission 和业务失败回执均清正文；Session snapshot 无草稿字段。要同时闭合控制命令与 mode/Session 草稿 owner。 |
| `application/sessions.py.SessionReplayRecord`、Bridge event fields、Renderer tool handling | 缺历史公开 Assistant kind、命令摘要、起止时间及输出引用；ToolProgress 未完整接通 Desktop。T05 用安全终态记录/现有结果读取补齐，live progress 不写 History。 |
| `integrations/tools/file_tools.py`、`patch_tools.py` | Write/Edit 已有 file_change/changed/digest，ApplyPatch 有 applied/failed/not_applied；历史摘要可复用正式结果 metadata，增删行统计仍需可信前后证据。 |
| `integrations/tools/git_tools.py.GitWorkspace` | 现有只读有界 diff 在模型 Tool 使用，没有 UI Application 出口；默认 unstaged 不能自动代表所有当前变化。 |
| Bridge `_settings_save`、`_applications_for_configuration_reload`、Application `reload_configuration` | 先写盘再 reload，失败未分 durable/applied；全局活动禁止，跨项目 idle Runtime 不在刷新集合；reload 会修改共享服务，不能仅删除 guard 后在活动时直接调用。 |
| `integrations/config/writer.py`、`SettingsView.tsx` | 当前部分 section 是完整替换，页面回包重置全树 draft；字段 patch 要从最新真实配置收敛，不能旧全量回写或迟到清空新编辑。 |


## 文件级任务

以下文件路径均相对仓库根；“修改”覆盖生产与相应既有测试，是否改动以当前职责实际需要为准。可选新增仅在既有目录并有真实调用时进行，不按概念机械造文件。安全/产品公共边界若出现不能由源需求确定的冲突，按 UserDecisionBoundary 停止相关范围并在 Feedback 留证据。

### T01 Session 归档元数据与持久化

- **目标**：R04–R07；落实 A03–A04 对应的当前职责。
- **依赖**：无。
- **修改文件及职责**：`src/uthcode/integrations/session_files.py`、`src/uthcode/application/sessions.py`、`tests/test_session_files.py`、`tests/test_session_authority.py`、`src/uthcode/application/generation.py`、`src/uthcode/application/__init__.py`。生产文件承载下列步骤，测试文件验证对应公开行为与关键失败。
- **新增文件**：不要求新增生产文件；优先现有实现/测试。确有必要的当前职责文件放既有目录，新增原因须记 Feedback。
- **删除范围**：不删除持久 Session/Transcript，不移除已有 schema 读取。
- **实施顺序**：
  1. 扩展可选归档事实；缺省旧 Session 为普通 Coding，不全量迁移，不改原 Session identity、project_key、title、model_ref、用户消息时间、置顶及 Transcript。
  2. 复用单 Session writer/metadata 原子替换，形成以目标 archived 状态收敛的幂等入口；处理异常/退出后重新读真实状态与受控 writer 冲突。归档/恢复不复制或移动 Session。
  3. 普通 catalog 过滤归档；归档目录使用同一 metadata authority，保留可供后续 General scope 隔离的入口。目标 active/paused/pending/compact 的操作门禁由 T04 结合真实 Runtime 完成。
- **定向验证入口**：python -m pytest tests/test_session_files.py tests/test_session_authority.py -q。精确命令、环境/通过数及未验证项写 Feedback，Checklist 仅勾实际完成项。
- **参考定位**：任务书 §3.1、§4.1；State Context 的 History 持久化与恢复。
- **完成边界**：提供可复用存储/Application 用例；不提前修改 Desktop 主壳或强制完成尚未接入的运行态门禁。

### T02 安全正文按需搜索

- **目标**：R01–R03；落实 A01–A02 对应的当前职责。
- **依赖**：T01。
- **修改文件及职责**：`src/uthcode/integrations/session_files.py`、`src/uthcode/application/sessions.py`、`tests/test_session_authority.py`、`tests/test_history_paging.py`。生产文件承载下列步骤，测试文件验证对应公开行为与关键失败。
- **新增文件**：不要求新增生产文件；优先现有实现/测试。确有必要的当前职责文件放既有目录，新增原因须记 Feedback。
- **删除范围**：不建索引或平行目录 authority；若局部旧扫描被替换，删除对应重复实现。
- **实施顺序**：
  1. 在文件读取层与 Application 公共出口实现按需标题/首消息/正式可展示 user、assistant 文本检索；覆盖完整旧历史，不仅当前分页；排除 reasoning、原始工具、日志、秘密和隐藏诊断。
  2. 输入范围由可信 Coding 项目集合或独立 General scope 决定，返回稳定 Session identity、归属、归档标记、有界 snippet/排序依据；不构造/恢复每个 Session Runtime，不建立持久索引。
  3. 结果/查询/扫描内存有界，扫描让出执行与可取消；部分损坏、无权限、消失受控且保留其余命中。具体私有排序和批次算法复用既有机制。
- **定向验证入口**：python -m pytest tests/test_session_authority.py tests/test_history_paging.py -q。精确命令、环境/通过数及未验证项写 Feedback，Checklist 仅勾实际完成项。
- **参考定位**：任务书 R01–R03、§3.1、§4.2；State Context 的历史分页与目录。
- **完成边界**：搜索底座可定向测试；迟到响应与打开正确项目由 T04/T07 联动验收。

### T03 General 最小 Application 组合

- **目标**：R08–R11；落实 A07–A10 对应的当前职责。
- **依赖**：T01、T02。
- **修改文件及职责**：`src/uthcode/application/bootstrap.py`、`src/uthcode/application/generation.py`、`src/uthcode/application/context.py`、`src/uthcode/application/instructions.py`、`src/uthcode/application/sessions.py`、`src/uthcode/core/prompt.py`、`src/uthcode/prompt_assets/__init__.py`、`tests/test_application_runtime.py`、`tests/test_system_prompt.py`、`tests/test_project_instructions.py`、`tests/test_session_authority.py`、`src/uthcode/application/configuration.py`、`src/uthcode/integrations/config/loader.py`、`tests/test_config_loader_integration.py`、`desktop/packaging/uthcode-runtime.spec`。生产文件承载下列步骤，测试文件验证对应公开行为与关键失败。
- **新增文件**：按需在现有 src/uthcode/prompt_assets/ 中增加最小 General Prompt 文件，随现有资产机制打包。
- **删除范围**：删除只为 General 临时注册/清空 Coding 工具的过渡链；保留 Coding 真实组合。
- **实施顺序**：
  1. 通过同一 Application/Run/Provider/Context/Session 建立用户级 General 身份和最小非 Coding Prompt；同一个 store authority 隔离两模式，不伪造 Coding Project，不引入第二套 Loop。可在现有 prompt_assets 目录按需新增一份最小 General 文本资产。
  2. 把 Prompt 选择、Context 编译、Instruction 指纹及恢复置于同一组合语义；不读取 Coding 项目 AGENTS/目录配置，不让启动 cwd 成为 General 项目授权。可信用户级配置仍生效。
  3. 工具集合在创建、reload、恢复后均保持无默认 Coding/文件/联网工具；仅 tools=() 不能解决 reload 回填默认 builder 的现有路径，必须闭合组合。配置无效返回可观察引导，不伪装聊天成功。
  4. 现有配置发现链总读取 cwd 项目配置，不能仅换 home 目录；在现有 loader/组合入口提供明确 General 用户级发现语义，保留 Coding 默认。General 资产同步现有 PyInstaller datas 及 bundled smoke，不复制构建输入。
- **定向验证入口**：python -m pytest tests/test_application.py tests/test_application_runtime.py tests/test_application_tools.py tests/test_system_prompt.py tests/test_project_instructions.py tests/test_session_authority.py tests/test_config_loader_integration.py tests/test_architecture_boundaries.py -q。精确命令、环境/通过数及未验证项写 Feedback，Checklist 仅勾实际完成项。
- **参考定位**：任务书 §3.2、§4.1；Orchestration/State/AgentRuntime Context。
- **完成边界**：完成最小正式后端组合，不建设 General 附件、工具、Memory、个人助理或跨设备能力。

### T04 Session 与 General Desktop 协议接入

- **目标**：R01–R11；落实 A01–A07、A09–A10 对应的当前职责。
- **依赖**：T03。
- **修改文件及职责**：`src/uthcode/interfaces/desktop/bridge.py`、`src/uthcode/application/sessions.py`、`desktop/src/desktop-api.ts`、`desktop/src/main.ts`、`desktop/src/preload.ts`、`tests/test_desktop_bridge.py`、`desktop/tests/preload.test.ts`、`desktop/tests/runtime-process.test.ts`。生产文件承载下列步骤，测试文件验证对应公开行为与关键失败。
- **新增文件**：不要求新增生产文件；优先现有实现/测试。确有必要的当前职责文件放既有目录，新增原因须记 Feedback。
- **删除范围**：删除本次替代的 Session/General 旁路；现有 rename/move 的全局门禁合同不借机改变。
- **实施顺序**：
  1. 接入搜索、目标归档状态收敛、归档目录/恢复和 General 创建/恢复/Turn 等正式 RPC；精确更新 DTO、Main/preload 白名单与参数校验，只通过 Application 使用底座。
  2. Main 持有已登记可信项目或 General 用户级授权；不能把 renderer project_key 任意当路径。搜索作为可取消有界操作不阻塞 Bridge 接收，导航/请求身份拒绝迟到响应。
  3. 归档基于目标 Session 的 active/paused/pending/compact 状态；无关后台 Session 活跃不阻断空闲目标。切模式不关闭 Coding Run，后台事件保持原 owner；Project 移除只解除登记。
- **定向验证入口**：python -m pytest tests/test_desktop_bridge.py tests/test_session_authority.py tests/test_history_prepare_lifecycle.py -q；Desktop 定向运行 preload.test.ts、runtime-process.test.ts。精确命令、环境/通过数及未验证项写 Feedback，Checklist 仅勾实际完成项。
- **参考定位**：任务书 §4.2–§4.3；GUI Context 的 Session 与运行时切换。
- **完成边界**：协议路径正式可调用；视觉导航与 Settings 归档页留给 T07/T12，不新增旁路磁盘访问。

### T05 过程回放与安全明细来源

- **目标**：R12–R14；落实 A11–A13 对应的当前职责。
- **依赖**：T04。
- **修改文件及职责**：`src/uthcode/application/generation.py`、`src/uthcode/application/sessions.py`、`src/uthcode/interfaces/desktop/bridge.py`、`src/uthcode/integrations/session_files.py`、`desktop/src/desktop-api.ts`、`desktop/src/main.ts`、`desktop/src/preload.ts`、`tests/test_tool_result_persistence.py`、`tests/test_timeline_contract.py`、`tests/test_history_paging.py`、`tests/test_desktop_bridge.py`、`src/uthcode/application/tools.py`、`src/uthcode/application/runs.py`。生产文件承载下列步骤，测试文件验证对应公开行为与关键失败。
- **新增文件**：优先扩展现有安全记录；仅真实职责无法承载时在既有 application/ 中新增局部观察/审阅实现，不建目录。
- **删除范围**：删除被正式安全投影替代的重复 DTO/输出路径；不删除现有 ToolResultRead、进程脱敏或模型工具。
- **实施顺序**：
  1. 补齐安全 live/replay 所需的公开 Assistant kind、Tool/Turn/Message identity、可证明启动/结束时间及安全命令摘要/输出引用；复用现有提交边界保存必要终态观察，旧记录缺字段显示 unavailable。
  2. 增加真实按需有界安全工具结果读取出口，复用 Session.read_tool_result 与现有脱敏/配额；不得把原始 Provider/异常/秘密传给 UI，也不得开放任意 ref。
  3. ToolProgress 只按既有 Application 唯一事件流作 live 有界投影，不写 RunState、History 或 Provider request；不为过程组存逐帧展开状态，不伪造旧历史输出和总耗时。
- **定向验证入口**：python -m pytest tests/test_tool_result_persistence.py tests/test_timeline_contract.py tests/test_history_paging.py tests/test_desktop_bridge.py -q。精确命令、环境/通过数及未验证项写 Feedback，Checklist 仅勾实际完成项。
- **参考定位**：任务书 §3.3、§4.1；State Context 的 Event、Transcript、Tool externalization。
- **完成边界**：供 Renderer 派生聚合及明细使用，Core 事件只在真实必要时按既有合同调整，不建立第二套状态权威。

### T06 变更摘要与当前只读 Diff 出口

- **目标**：R15–R16；落实 A14–A16 对应的当前职责。
- **依赖**：T05。
- **修改文件及职责**：`src/uthcode/application/attachments.py`、`src/uthcode/application/generation.py`、`src/uthcode/application/sessions.py`、`src/uthcode/integrations/tools/git_tools.py`、`src/uthcode/interfaces/desktop/bridge.py`、`desktop/src/desktop-api.ts`、`desktop/src/main.ts`、`desktop/src/preload.ts`、`tests/test_git_tools.py`、`tests/test_desktop_artifacts.py`、`tests/test_desktop_bridge.py`、`src/uthcode/application/tools.py`、`src/uthcode/integrations/tools/file_tools.py`、`src/uthcode/integrations/tools/patch_tools.py`、`tests/test_builtin_file_tools.py`、`tests/test_patch_tool.py`。生产文件承载下列步骤，测试文件验证对应公开行为与关键失败。
- **新增文件**：仅现有 Artifact/Git 不能清晰承载时，在既有 application/ 或 integrations/ 目录新增最小只读审阅文件。
- **删除范围**：删除被统一只读出口替代的重复 Git 读取；现有模型 Git Tool 与权限链仍是真实调用者。
- **实施顺序**：
  1. 复用 GitWorkspace 的只读、有界、取消路径，经过 Application 提供已登记工作区审阅；必要时在现有 application/integrations 目录按职责增加最小实现文件，不直调模型 Tool 作为 UI 权限。
  2. 优先复用 Write/Edit 的正式 file_change/changed/content_digest、ApplyPatch 的 applied/failed/not_applied 安全结果元数据及 ToolCall 路径建立历史摘要；缺增删行统计须从可信写入前后或观察获得，不能由声明/命令文字推算；有并发或归属不足降级为观察而非确定编辑。
  3. 当前 diff 始终标注查看时状态；处理非 Git、untracked、binary、rename、删除、文件缺失/输出截断，不造行数或完整旧 Diff。预览仍复用 ArtifactService 及 Main 外部单文件显式授权。
  4. 核对 staged/unstaged 的不同 current diff 来源及 untracked 状态，不假定现有默认 unstaged diff 覆盖全部工作区；只读 Git 禁外部 diff/textconv，原有取消/输出上限保持。
- **定向验证入口**：python -m pytest tests/test_git_tools.py tests/test_desktop_artifacts.py tests/test_desktop_bridge.py -q。精确命令、环境/通过数及未验证项写 Feedback，Checklist 仅勾实际完成项。
- **参考定位**：任务书 §3.3、§4.1；GUI Context 的附件与产物预览；现有 Git 工具与写入测试。
- **完成边界**：只读 UI 审阅和有据摘要，禁止 Git 写入、回滚、Worktree 或完整版本存储。

### T07 双模式导航与搜索归档界面

- **目标**：R01–R11；落实 A01–A07、A09 对应的当前职责。
- **依赖**：T04–T06。
- **修改文件及职责**：`desktop/src/renderer/App.tsx`、`desktop/src/renderer/Sidebar.tsx`、`desktop/src/renderer/state.ts`、`desktop/src/renderer/state-session.ts`、`desktop/src/renderer/state-normalization.ts`、`desktop/src/renderer/useRuntimeLifecycle.ts`、`desktop/src/renderer/i18n.tsx`、`desktop/src/renderer/locales/zh-CN.ts`、`desktop/src/renderer/locales/en.ts`、`desktop/tests/renderer-session.test.tsx`、`desktop/tests/renderer-state.test.ts`、`desktop/tests/renderer-runtime-lifecycle.test.tsx`、`desktop/src/renderer/app.css`。生产文件承载下列步骤，测试文件验证对应公开行为与关键失败。
- **新增文件**：可在现有 renderer/ 中按真实调用方增加搜索/General 局部组件，不新建目录。
- **删除范围**：删除失效的单 mode 导航/目录临时状态；不删 Coding 项目树或现有后台会话控制。
- **实施顺序**：
  1. 左上产品菜单仅切 Coding/General，Settings 左下，返回原模式；Coding 保留项目树，General 独立 Session/最近列表和可用文本聊天，不显示未实现 Coding/附件/权限控件。
  2. 接入真实按需搜索入口/快捷键、身份/项目/归档结果、取消/错误；结果正确定位 Project/Session，归档结果有提示/恢复流程，不静默变为普通会话。
  3. Session 菜单接归档；普通/Recent 排除归档且当前归档后保留 owner 草稿并安全离开；Settings 分组列表由 T12 实施。双 mode/Session 选择、历史、草稿 owner 独立，迟到/后台通知不串台。
- **定向验证入口**：Desktop 定向运行 renderer-session.test.tsx、renderer-state.test.ts、renderer-runtime-lifecycle.test.tsx。精确命令、环境/通过数及未验证项写 Feedback，Checklist 仅勾实际完成项。
- **参考定位**：任务书 §1.2、§3.1–§3.2、§4.3；三 PNG/V4；GUI Context。
- **完成边界**：完成真实导航及列表，不照搬原型侧栏归档入口、General 附件或虚假已连接数据。

### T08 连续过程分组与真实计时

- **目标**：R12–R14；落实 A11–A13 对应的当前职责。
- **依赖**：T05、T07。
- **修改文件及职责**：`desktop/src/renderer/state.ts`、`desktop/src/renderer/state-normalization.ts`、`desktop/src/renderer/ChatTimeline.tsx`、`desktop/tests/renderer-state.test.ts`、`desktop/tests/renderer-chat.test.tsx`、`desktop/src/renderer/app.css`、`desktop/src/renderer/locales/zh-CN.ts`、`desktop/src/renderer/locales/en.ts`。生产文件承载下列步骤，测试文件验证对应公开行为与关键失败。
- **新增文件**：可在现有 renderer/ 中增加纯派生活动组组件，不能另建状态权威。
- **删除范围**：删除被活动组替代的逐条 Tool summary/elapsed 渲染分支及仅测试旧排列的断言。
- **实施顺序**：
  1. 从正式 live/replay 按可见连续语义段派生活动组，跨 batch 合并；计数、状态、真实墙钟跨度和按需安全明细来源统一，默认折叠。
  2. PROGRESS 自然语言、公开 reasoning、用户输入、审批/AskUser/Plan review、关键失败切组且直接可见；最终正文独立，不合并为过程。
  3. 取消/失败/历史分页重叠/切 Session/重载后位置与终态稳定；旧无起点记录不可用，不以每项耗时求和冒充总时间，运行中的显示仅基于真实起点。
- **定向验证入口**：Desktop 定向运行 renderer-state.test.ts、renderer-chat.test.tsx。精确命令、环境/通过数及未验证项写 Feedback，Checklist 仅勾实际完成项。
- **参考定位**：任务书 R12–R14、§3.3；coding-reference.png；GUI/State Context。
- **完成边界**：仅派生 UI，不复写 RunState 或私有推理，不把失败与需回应交互折叠隐藏。

### T09 统一右侧文件与日志审阅

- **目标**：R15–R16；落实 A14–A16 对应的当前职责。
- **依赖**：T06、T08。
- **修改文件及职责**：`desktop/src/renderer/App.tsx`、`desktop/src/renderer/ChatTimeline.tsx`、`desktop/src/renderer/DocumentPreviewPanel.tsx`、`desktop/src/renderer/FileCard.tsx`、`desktop/src/renderer/safe-markdown.tsx`、`desktop/tests/renderer-chat.test.tsx`、`desktop/tests/renderer-attachments.test.tsx`、`desktop/tests/preload.test.ts`、`desktop/src/renderer/app.css`、`desktop/src/renderer/locales/zh-CN.ts`、`desktop/src/renderer/locales/en.ts`。生产文件承载下列步骤，测试文件验证对应公开行为与关键失败。
- **新增文件**：可在现有 renderer/ 中增加局部 Diff/tab 组件，不能开新文件系统接口。
- **删除范围**：删除被统一 owner/右栏替代的重复 preview 回调/状态；图片 zoom/pan/focus 等真实能力保持或正式等价接通后替换。
- **实施顺序**：
  1. 聊天显示可验证变更摘要与入口，右侧复用文件/Markdown/图片/附件/产物/有界工具与进程输出，支持 tab、关闭/切换及局部失败；Runtime 与预览共用已有布局 owner。
  2. 标注历史 Turn 摘要与查看时 Git diff 的不同来源，不把当前树当旧 Turn 完整变化；不显示无证据数量、行数或虚构历史 tab 能力。
  3. 异步结果捕获 mode/project/Session/view revision；切换、关闭/新开拒绝迟到回包。沿用安全 Markdown、Main picker 授权和 Artifact preview，不开 Renderer fs/shell。
- **定向验证入口**：Desktop 定向运行 renderer-chat.test.tsx、renderer-attachments.test.tsx、preload.test.ts。精确命令、环境/通过数及未验证项写 Feedback，Checklist 仅勾实际完成项。
- **参考定位**：任务书 R15–R16；coding-reference.png/V4；GUI Context 的 Artifact 授权。
- **完成边界**：替换旧重复预览链而保持消息附件/原图预览既有能力，不扩为 IDE。

### T10 Composer 控制命令与草稿所有权

- **目标**：R20、R09–R11；落实 A20、A09 对应的当前职责。
- **依赖**：T07–T09。
- **修改文件及职责**：`desktop/src/renderer/Composer.tsx`、`desktop/src/renderer/App.tsx`、`desktop/src/renderer/state.ts`、`desktop/src/renderer/state-session.ts`、`desktop/tests/renderer-state.test.ts`、`desktop/tests/renderer-attachments.test.tsx`、`desktop/tests/renderer-session.test.tsx`、`desktop/tests/renderer.test.tsx`。生产文件承载下列步骤，测试文件验证对应公开行为与关键失败。
- **新增文件**：不要求新增生产文件；优先现有实现/测试。确有必要的当前职责文件放既有目录，新增原因须记 Feedback。
- **删除范围**：移除控件命令导致 composerText 清空的分支和失效旧草稿断言；不删成功发送清理或 active 门禁。
- **实施顺序**：
  1. 沿 Composer onCommand→App executeCommand→command_result 修正控制命令清空输入的路径，区分控件命令与真正提交；开 Model picker、选择 Model/Permission、受控失败/取消不清文本或附件，不产生 Turn。
  2. 草稿以 mode/Session owner 保持，初次惰性 Session 创建、导航恢复及回包竞态均不写到另一主；实际成功提交仅清其已提交版本，不清后来新编辑。
  3. General 只提供文本发送/模型选择/取消，Coding 保留附件与权限选择的真实行为；active/pending/compact 控件门禁保持。
- **定向验证入口**：Desktop 定向运行 renderer-state.test.ts、renderer-attachments.test.tsx、renderer-session.test.tsx、renderer.test.tsx。精确命令、环境/通过数及未验证项写 Feedback，Checklist 仅勾实际完成项。
- **参考定位**：任务书 R20；GUI Context 的惰性 Session/附件 owner；本 Tasks 基线证据表。
- **完成边界**：以最小修改清除真实缺陷；不新增平行命令系统或关闭现有成功发送清理。

### T11 配置单项持久化与安全边界应用

- **目标**：R17–R19；落实 A17–A19 对应的当前职责。
- **依赖**：T03–T06、T10。
- **修改文件及职责**：`src/uthcode/application/configuration.py`、`src/uthcode/application/bootstrap.py`、`src/uthcode/application/generation.py`、`src/uthcode/integrations/config/writer.py`、`src/uthcode/integrations/config/loader.py`、`src/uthcode/interfaces/desktop/bridge.py`、`desktop/src/desktop-api.ts`、`desktop/src/main.ts`、`desktop/src/preload.ts`、`tests/test_configuration.py`、`tests/test_application_runtime.py`、`tests/test_desktop_bridge.py`、`tests/test_config_contract.py`、`tests/test_config_loader_integration.py`、`tests/test_w04_review_fixes.py`。生产文件承载下列步骤，测试文件验证对应公开行为与关键失败。
- **新增文件**：不要求新增生产文件；优先现有实现/测试。确有必要的当前职责文件放既有目录，新增原因须记 Feedback。
- **删除范围**：删除仅服务旧全局保存/全局活动禁止的重复链；其他真实命令门禁、项目收紧与 Process 旧快照保护保留。
- **实施顺序**：
  1. 复用唯一用户配置 writer 实现字段/关联编辑组的最小更新，从真实最新配置合并，避免旧全量 draft 覆盖新字段；用现有机制和最小冲突/顺序状态处理连续编辑、失败重试，不引入仓库事务或专用 manifest。
  2. 区分 durable/applied/pending/failure 和来源；写成功但 reload 失败仍报告已保存及应用失败，不重复写副作用。偏好立即，执行配置在安全边界重组；所有相关前台/后台/跨项目 Runtime 的待应用状态准确。
  3. 替换 Bridge 全局 _ensure_no_active 保存禁止链：活动 Turn/compact 保留捕获快照，idle 安全边界应用，已启动 Process 保留旧启动参数/脱敏，不 shutdown/initialize 每字段。General reload 仍无工具。
  4. Secret 不回传；未编辑 Key 保留 literal/env，替换值仅在 editor-local/受控写入生命周期；项目收紧/可信 Provider/默认模型顶层写回边界保持。
- **定向验证入口**：python -m pytest tests/test_configuration.py tests/test_config_contract.py tests/test_config_loader_integration.py tests/test_application_runtime.py tests/test_desktop_bridge.py tests/test_w04_review_fixes.py -q。精确命令、环境/通过数及未验证项写 Feedback，Checklist 仅勾实际完成项。
- **参考定位**：任务书 R17–R19、§4.1–§4.2；配置手册/GUI Context；UserDecisionBoundary。
- **完成边界**：持久化和应用各有事实；不重新设计权限、Provider 安全或 Process 生命周期。

### T12 Settings 自动保存与归档管理

- **目标**：R06–R07、R17–R19；落实 A05、A17–A19 对应的当前职责。
- **依赖**：T11、T07。
- **修改文件及职责**：`desktop/src/renderer/App.tsx`、`desktop/src/renderer/SettingsView.tsx`、`desktop/src/renderer/SettingsEditorModal.tsx`、`desktop/src/renderer/settings-draft.ts`、`desktop/src/renderer/state.ts`、`desktop/src/renderer/i18n.tsx`、`desktop/src/renderer/locales/zh-CN.ts`、`desktop/src/renderer/locales/en.ts`、`desktop/tests/renderer-settings.test.tsx`、`desktop/tests/renderer-runtime-lifecycle.test.tsx`、`desktop/src/renderer/useRuntimeLifecycle.ts`、`desktop/src/renderer/app.css`、`desktop/tests/renderer.test.tsx`。生产文件承载下列步骤，测试文件验证对应公开行为与关键失败。
- **新增文件**：不要求新增生产文件；优先现有实现/测试。确有必要的当前职责文件放既有目录，新增原因须记 Feedback。
- **删除范围**：删除全局 Save、Save-only draft/返焦/阻塞状态、App Settings rebootstrap 调用及 useRuntimeLifecycle.rebootstrapProject（无其他真实调用后）；替换相应旧测试。
- **实施顺序**：
  1. 按 settings-reference 重组分类与字段；取消全局 Save 和仅服务全局提交的 draft/rebootstrap 恢复链，保留实际 Provider/Model 关联组局部编辑、校验、focus trap/返回焦点。有效完整字段自动安全提交，部分非法输入不自动持久化。
  2. 字段展示正在保存、已保存、失败重试，以及当前已应用/待边界/应用失败和来源；离开 Settings/连续更改不丢有效待保存编辑，迟到回执不覆盖新值，不能伪称 Provider 已连接。
  3. Settings 内唯一归档分类按 Coding 项目/General 分组与项目/文本过滤、恢复；普通/Recent/search 与同一 metadata 事实收敛。Secret 清理与局部失败保留只满足必要重试。
- **定向验证入口**：Desktop 定向运行 renderer-settings.test.tsx、renderer-runtime-lifecycle.test.tsx。精确命令、环境/通过数及未验证项写 Feedback，Checklist 仅勾实际完成项。
- **参考定位**：任务书 §3.1、R17–R19；settings-reference.png/V4；GUI Context。
- **完成边界**：现有字段完整收敛，不照搬原型无后端的开关或全局假保存提示。

### T13 全仓调用证据与定点工程收敛

- **目标**：R21；落实 A21 对应的当前职责。
- **依赖**：T01–T12。
- **修改文件及职责**：`src/uthcode/**（仅有当前证据的定点删改）`、`desktop/src/**（仅有当前证据的定点删改）`、`tests/**、desktop/tests/**（相应失效或重复覆盖）`、`pyproject.toml`、`desktop/package.json`、`desktop/package-lock.json`、`desktop/scripts/build-python-runtime.mjs`、`desktop/packaging/uthcode-runtime.spec`、`desktop/forge.config.ts`。生产文件承载下列步骤，测试文件验证对应公开行为与关键失败。
- **新增文件**：不要求新增生产文件；优先现有实现/测试。确有必要的当前职责文件放既有目录，新增原因须记 Feedback。
- **删除范围**：只删除候选中复核无调用或已有正式替代的符号、测试、资源和依赖；未证实项不删。
- **实施顺序**：
  1. 复核下方三类清理候选及当前真实调用图，覆盖 Python/Desktop/测试/依赖/打包；在本 Worker Feedback 记录路径/符号→调用者→冗余证据→具体删改→定向回归结果→风险。
  2. 优先本次替代路径随功能删；剩余高把握项逐项清理，需功能协调项在替代链正式接通后删除，证据不足项明确保留理由。依赖删除需真实无消费者和构建验证，不为 KPI 强删。
  3. 审查 bridge/App/state/generation/context/core.agent/sessions 的职责与调用链；只在实际混乱且能清晰承担当前职责时局部拆分，不按 LOC、概念或未来功能造文件/抽象。
- **定向验证入口**：每项精确 rg 引用检查与受影响定向测试；更大回归纳入 T15，不机械重复。精确命令、环境/通过数及未验证项写 Feedback，Checklist 仅勾实际完成项。
- **参考定位**：任务书 §9.1–§9.2；本 Tasks 清理候选；AGENTS 工程收敛。
- **完成边界**：全仓是证据盘点覆盖，不是无边界改写授权；新发现独立范围问题留 Feedback。

### T14 [接入主流程]

- **目标**：R01–R21；落实 A01–A21 对应的当前职责。
- **依赖**：T13。
- **修改文件及职责**：`src/uthcode/interfaces/desktop/bridge.py`、`desktop/src/renderer/App.tsx`、`desktop/src/renderer/state.ts`、`desktop/src/main.ts`、`desktop/src/preload.ts`、`tests/test_desktop_bridge.py`、`desktop/tests/renderer-session.test.tsx`、`desktop/tests/renderer-settings.test.tsx`、`desktop/tests/renderer-chat.test.tsx`。生产文件承载下列步骤，测试文件验证对应公开行为与关键失败。
- **新增文件**：不要求新增生产文件；优先现有实现/测试。确有必要的当前职责文件放既有目录，新增原因须记 Feedback。
- **删除范围**：删除残留旧全局提交、逐条工具/重复预览入口与无后端按钮，不保留双轨。
- **实施顺序**：
  1. 从正式 Coding/General 入口联通搜索→归档→Settings 恢复、真实发送/取消/历史、过程展开→右侧审阅、自动保存→安全边界应用及草稿 owner。
  2. 移除被替代全局保存、重复工具渲染/预览调用链及假功能按钮，保留现有后台 Session、审批/AskUser/Plan、Context/Compact 与 Coding 功能。
  3. 仅修复当前已授权链的组合缺陷；在 Feedback 建 R01–R21/A01–A23→命令/报告/截图映射，复用仍有效证据而不省略未覆盖项。
- **定向验证入口**：跨层定向回归并引用 T01–T13 有效结果；未覆盖真实场景交 T15。精确命令、环境/通过数及未验证项写 Feedback，Checklist 仅勾实际完成项。
- **参考定位**：任务书 §7 第9步、§11；docs/README.md 维护映射。
- **完成边界**：接入正式主流程并清旧入口，不能用组件或 RPC 存在声称 E2E 已验。

### T15 [端到端验证]

- **目标**：R01–R21；落实 A06、A08、A16、A22–A23 对应的当前职责。
- **依赖**：T14。
- **修改文件及职责**：`tests/test_architecture_boundaries.py`、`desktop/scripts/cdp-driver.mjs`、`desktop/scripts/cdp-packaged-visual-acceptance.mjs`、`desktop/tests/renderer.test.tsx`、`desktop/tests/cdp-isolation.test.ts`、`desktop/tests/windows-packaging.test.ts`。生产文件承载下列步骤，测试文件验证对应公开行为与关键失败。
- **新增文件**：不要求新增生产文件；优先现有实现/测试。确有必要的当前职责文件放既有目录，新增原因须记 Feedback。
- **删除范围**：不为验收删除生产行为；仅替换已失效旧验收场景，保留隔离与清理保证。
- **实施顺序**：
  1. 执行定向公开正常/关键失败路径、架构测试、Desktop 全量 npm test/typecheck；从当时 pyproject/package 脚本选择必要 Python 全量、串行标准 package/make 与 bundled Runtime smoke，记录命令和精确结果。
  2. 计划扩展现有隔离 CDP 流程覆盖真实 Session 搜索/归档/重启/恢复、双模式、过程/审阅和自动保存；fixture 只证明确定性路径，真实 General Provider 验收单独实际请求且不修改/泄露用户凭据。
  3. 必须完成至少一次 General 真 API 新聊天流式 delta/正式最终回答，另验配置无效引导/取消；真实可核实 Git 修改从聊天进入 packaged current diff；Windows 原生点击/缩放、键盘/焦点和三 PNG 布局对照单独记录，CDP viewport 不冒充原生。
- **定向验证入口**：conda activate re-uthcode；python -m pytest tests/test_architecture_boundaries.py -q；desktop 工作目录 npm test、npm run typecheck、npm run package、npm run make（串行）；其余依脚本和实际条件记录。精确命令、环境/通过数及未验证项写 Feedback，Checklist 仅勾实际完成项。
- **参考定位**：任务书 §8；references；desktop/package.json；现有隔离 CDP launcher/driver/packaged runner。
- **完成边界**：缺真实 Provider/原生环境如实写未验收，不用 Mock/HTML 代替，不声称整包完成；不重复修改有效构建身份体系。

### T16 [遗留负担清理]

- **目标**：R21及全部实际长期事实；落实 A21–A23 对应的当前职责。
- **依赖**：T15（可先做不依赖外部验收的文档与清理）。
- **修改文件及职责**：`docs/context/GUI/GUI-Context.md`、`docs/context/A03-State/State-Context.md`、`docs/context/A04-Orchestration/Orchestration-Context.md`、`docs/context/A01-AgentRuntime/AgentRuntime-Context.md`、`docs/user-manual/getting-started.md`、`docs/user-manual/configuration.md`、`docs/user-manual/commands.md`、`docs/Tools.md`、`docs/core-design/A04-Orchestration/02-可替换交互层.md`、`README.md`、`docs/Context-Index.md`、`docs/OutstandingDebtList.md`、`本包 W05 Feedback`。生产文件承载下列步骤，测试文件验证对应公开行为与关键失败。
- **新增文件**：不要求新增生产文件；优先现有实现/测试。确有必要的当前职责文件放既有目录，新增原因须记 Feedback。
- **删除范围**：删除已证实废弃代码/测试/样式/过度封装及失效当前说明；不修改冻结历史工作包。
- **实施顺序**：
  1. 复核新增兼容层、废弃实现、不可达分支、重复职责/DTO/测试、旧样式和构建负担；有新改动只补跑受影响证据，不机械重跑全部。
  2. 按 docs/README 维护映射同步全部相关实际能力：GUI/State/Orchestration、必要 AgentRuntime、用户操作、Tools 的 General 无默认工具；核心设计/README 只更新确有长期意义的变化。源码未实现或未验收不写成通过事实。
  3. 全量再核对工作包目录/Checklist/Feedback/source 更新 current-status；核对能力欠账无则保持清单不变。UTF-8、乱码、fence、内部链接检查；冻结任务文档不改文字，仅 Checklist 勾选与原 Feedback 追加。
- **定向验证入口**：UTF-8 guard、内部链接检查、清理符号 rg 与受影响定向回归；汇总 T15 有效证据。精确命令、环境/通过数及未验证项写 Feedback，Checklist 仅勾实际完成项。
- **参考定位**：任务书 §9–§11；docs/README.md；WorkPackageRules；OutstandingDebtList。
- **完成边界**：交付可审查的代码事实和限制；正式包级结束/归档由用户决定。

## 工程瘦身候选（实施前再次精确检索）

已扫描 Python/Core/Application/Integration、Renderer、测试、依赖与打包真实消费者。下表是候选及回归去向，不是“已清理”结果。每位 Worker 随替代删除自己的旧路径并在同一 Feedback 记录证据；W05 复核全仓。

| 分类 | 路径 / 符号 | 当前调用或重复证据 | 实施时机与回归 |
| --- | --- | --- | --- |
| 高把握低风险 | `desktop/src/renderer/FileCard.tsx`：fileLanguage、attachmentAsset | src/tests 精确查询仅定义；真实高亮由 DocumentPreviewPanel 使用 | W03 或 W05 删除无调用 helper；typecheck、chat/attachments。 |
| 高把握低风险 | `src/uthcode/integrations/tools/git_tools.py`：GitWorkspaceQueryTool | 仅 alias 定义和 __all__，factory/tests 使用 GitWorkspaceTool | W02 或 W05 删除无消费者 alias；git/factory 定向。 |
| 高把握低风险 | `settings-draft.ts`：SettingsTheme/SettingsLanguage、withoutRecordKey | 前二仅定义；helper 仅 SettingsView 重导出与 renderer.test 镜像测试，生产未调用 | W04/W05 删除无调用 alias/helper/re-export 及镜像断言，保留删除 Provider/Secret 行为覆盖。 |
| 高把握局部合并 | `SettingsEditorModal.tsx`：applyModel、goBackToProvider | 两处重复回到 Provider 的 step/ref/focus 逻辑 | W04 局部复用，不改变 Apply 归一化和 Cancel；单 modal/返回焦点测试。 |
| 需功能协调 | `useRuntimeLifecycle.ts.rebootstrapProject`、App.saveSettings | 唯一生产调用是 Settings；内部 shutdown/initialize/project.open/session.resume | W04 字段保存接通后连调用/helper/旧 restart 测试删除，保留一般 lifecycle owner。 |
| 需功能协调 | Settings 全局 Save、保存锁、全量 draft 重置/恢复链 | 当前真实 writer 前端入口，不能只删按钮 | W04 替换后删除专用状态，保留局部合法候选、Secret、失败重试、响应 owner。 |
| 需功能协调 | ChatTimeline 单条 Tool elapsed/summary、图片 modal 与右栏重复状态 | 目前有真实渲染、zoom/pan/focus 消费 | W03 新链等价接通后清旧投影/重复状态；history/live/图像/原生焦点回归。 |
| 证据不足暂不处理 | ToolProgressEvent 公共 alias、core/tool.execute_prepared | 有公共导出/真实测试调用，不能凭名称认定无用 | 不预授权删除；复核公共合同与覆盖，证据不足保留。 |
| 证据不足且有真实来源 | state legacy context fallback、Process ring/cursor、ToolResultRead、旧历史读取 | Application status/context_usage、进程/结果读取、业务历史仍消费 | 保留关键失败、安全、分页与进程回归；不按 legacy 字面删。 |
| 证据不足暂不处理 | bridge/App/state/agent/context 整体拆分、native hiddenimports/resources、依赖 | 现有职责、动态 native/PTY/Prompt 打包与依赖均查到使用层，暂无可直接删依赖证据 | 按调用图处理局部混乱，不按 LOC 强拆，不削减 PyInstaller native 资源；General 资产只补现有 datas。 |

全仓引用核查示例：`rg -n 'GitWorkspaceQueryTool|fileLanguage|attachmentAsset|SettingsTheme|SettingsLanguage|withoutRecordKey|rebootstrapProject' src desktop/src desktop/tests tests`。最终结果记录实际删改后的精确命令、命中和定向测试，不把拆分时的候选当已通过证据。

## 验证命令与文档职责

- Python 全程使用 `conda activate re-uthcode`，本地已确认 Python 3.12.7；版本/依赖以 `pyproject.toml` 为准。
- 上述 Python 命令均在仓库根执行。Desktop 定向“运行文件”展开为在 `desktop/` 执行 `npx tsx --test tests/<对应既有文件>`；当前实际完整 scripts 是 `npm test`、`npm run typecheck`、`npm run package`、`npm run make`。package/make 串行，build:runtime 为既有构建链。
- 现有 `desktop/scripts/cdp-{launcher,driver,packaged-visual-acceptance}.mjs` 是入口定位，新增 T12 flows 为计划实施。运行前核查脚本支持的参数/flow，记录可复制精确命令；未支持 flow 不能假称已跑。保持隔离 profile 和子进程清理，不写真实用户秘密到报告。
- 每项改动从风险匹配定向验证开始，完成明确更大验收后停止。T15 需要当前产物、真实 General Provider、真实本地 Git、packaged Desktop及 Windows 原生操作；缺条件保持未验收。
- 每 Worker 只更新同名 Feedback、勾选实际完成项；W05 包级同步 GUI/State/Orchestration、必要 AgentRuntime、三个现有用户手册、Tools、必要核心设计/README、索引。不提前把规划能力写成当前事实。
- 能力欠账：**无**。本次未触发原清单的 Memory、动态 Tool、跨进程恢复、OS Sandbox、跨 Session Artifact 生命周期或高级压缩；清单保持不变。独立 General 完整工具/私人助理/历史版本管理不登记为欠账。
