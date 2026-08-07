# T07 三层权限系统 Tasks

## 1. Worker 分组与依赖

| Worker | 严格串行 Task | 依赖 |
| --- | --- | --- |
| W01 `permission-foundation` | Task 1 → Task 2 | 无 |
| W02 `permission-policy-scope` | Task 3 → Task 4 → Task 5 | W01 完成并通过对应测试 |
| W03 `permission-interaction` | Task 6 → Task 7 | W01、W02 完成并通过对应测试 |
| W04 `permission-delivery` | Task 8 → Task 9 → Task 10 | W01、W02、W03 完成并通过对应测试 |

同一 Worker 内不得改变 Task 顺序。后续 Worker 必须先读取前序 Feedback 并确认其完成边界；发现冻结语义、真实代码或前序交付冲突时停止相关范围，在自身 Feedback 中记录并交由用户决定。

## Task 1 — 全局权限约束与 Core Domain

### 任务目标

建立三层权限系统的权威 Core 模型和单一求值语义，并同步全局 `full_access` 约束。

### 新增、修改和删除的文件

- 修改 `SRe-AGENTS.md`：仅更新 Permission 第 11 节中与 T07 冲突的完全访问和持久决定语义。
- 新增 `src/uthcode/core/permission.py`：权限模式、Effect、Action、Decision、Rule、RuleSet、SessionGrant 及 evaluator。
- 按实际公共导出需要修改 `src/uthcode/core/__init__.py`，不得导出未来占位。
- 新增 `tests/test_permission.py`。

### 文件职责及实施内容

- 所有 Core 类型使用自有不可变、JSON-safe 值，不引用 Provider SDK、TOML、Path、Application 或 Interface。
- 固定 `default / auto / full_access`、`READ / WRITE / DESTRUCTIVE / EXTERNAL / UNKNOWN` 与 Allow/Ask/Deny。
- 明确区分 Guard 与 Policy；实现来源优先级、同来源严格度、Guard Allow 后续语义、Session Grant 优先级和三模式 Strategy。
- Action 只保存安全可展示的资源摘要与范围事实，不保存秘密内容。
- 为无规则、规则命中、Guard 命中、Session Grant 和模式兜底提供稳定的决策原因事实。

### 依赖任务

无。

### 参考资料定位

- `T07-三层权限系统.md` 第 3、8 节及测试矩阵。
- `SRe-AGENTS.md` 第 11 节。
- 旧 UthCode Day5 只用于提取 Provider 无关和 Allow/Ask/Deny，不继承其类型或层级。

### 完成边界

- Core 矩阵测试通过。
- 不接 Tool、Application、TUI 或规则文件。
- 不出现 L1～L5、Plan、Sandbox、Plugin/MCP/Skill 权限占位或旧模式兼容。

## Task 2 — Tool Preflight 与 Trusted Action

### 任务目标

建立唯一的“已注册且参数已校验、尚未执行”边界，并让六个内置普通 Tool 产生可信 Action。

### 新增、修改和删除的文件

- 修改 `src/uthcode/core/tool.py`。
- 修改 `src/uthcode/integrations/tools/file_tools.py`、`search_tools.py`、`process_tools.py`、`factory.py`。
- 修改承担现有职责的 `tests/test_tool_core.py`、`tests/test_builtin_file_tools.py`、`tests/test_builtin_search_tools.py`、`tests/test_builtin_process_tool.py`、`tests/test_application_tools.py`。

### 文件职责及实施内容

- 将 ToolExecutor 的注册查找、现有 JSON Schema 校验和执行拆成单一 prepared/validated 调用链；不得复制 validator。
- 未知 Tool、非法参数与取消在进入权限前沿用标准 ToolResult 行为。
- Tool contract 提供无副作用 Action preflight；ReadFile、WriteFile、EditFile、Glob、Grep 使用可信固定 Effect 与动态资源事实，Bash 按参数动态分类。
- ToolCall 参数中的 `effect` 或同义伪字段不能覆盖可信分类。
- Provider-facing ToolDefinition 维持纯工具 schema，不增加权限字段。
- Bash 至少稳定区分常见只读 Git/查看命令、写操作、破坏操作、外部交互和未知命令；复合段避免安全前缀掩盖后续动作。

### 依赖任务

Task 1。

### 参考资料定位

- `T07-三层权限系统.md` 第 2.1、3.4、7、8.2、9.5 节。
- T04 工作包与当前 `core/tool.py`、六工具实现。
- MewCode `permissions/dangerous.py` 仅参考少量高置信模式，不复制巨大安全白名单。

### 完成边界

- 只建立 preflight 与分类，不加载 Rules、不触发 HITL、不修改 TUI。
- unknown/invalid 不 Ask，prepared 调用仅执行一次，现有 Tool FIFO、截断、取消和错误行为回归通过。

## Task 3 — permissions.toml Discovery / Parse / Template

### 任务目标

建立用户级与递归项目级权限规则来源、模板生命周期和严格解析。

### 新增、修改和删除的文件

- 修改 `src/uthcode/integrations/config/loader.py`：提取或复用物理路径与 Git root→cwd 发现能力。
- 新增 `src/uthcode/integrations/permissions.py`；只有真实职责需要时才可拆为小型同名包。
- 按现状必要时修改 `.gitignore`，只精确忽略项目 `.uthcode/permissions.toml`，不得忽略整个 `.uthcode/`。
- 新增 `tests/test_permission_rules.py`，修改 `tests/test_config_loader_integration.py`。

### 文件职责及实施内容

- 用户文件缺失时原子创建含 Guard、Policy、默认 Guard 和简短示例的模板。
- 当前 workdir 项目文件缺失时创建空占位；Git 项目发现 root 到 cwd 的各级文件，非 Git 只使用 cwd。
- 候选路径在加载前规范化、物理解析并去重，保留最近项目、父项目、用户的来源身份与优先级。
- 使用现有 TOML 依赖解析，启动时编译验证 regex，并转换为 Task 1 的 Core 值；无效 TOML、Effect、regex、结构或缺失目标必须硬失败。
- RuleSet 是 Run 初始化快照，不实现文件监视或热重载。

### 依赖任务

Task 2。

### 参考资料定位

- `T07-三层权限系统.md` 第 2.6、8.3、9.1、9.2 节。
- 当前 `src/uthcode/integrations/config/loader.py` 与 T03/T04 配置回归测试。

### 完成边界

- 不接 Agent Loop、HITL 或 UI。
- `config.toml` 的发现、合并和安全边界零回归；权限规则不进入普通配置文件。

## Task 4 — Workspace / Resource Scope 改造

### 任务目标

将工作区外路径从 Tool 硬拒绝改为可信 Scope 事实，同时保留路径与读前写安全不变量。

### 新增、修改和删除的文件

- 修改 `src/uthcode/integrations/tools/workspace.py`。
- 修改 `src/uthcode/integrations/tools/file_tools.py`、`search_tools.py`、`factory.py`。
- 修改现有 file/search/application tool 测试；按真实职责补充 workspace/scope 测试，不为名称一致复制文件。

### 文件职责及实施内容

- 将路径解析与“必须在 workspace 内”解耦，输出规范化物理路径和 inside/outside 范围事实。
- 保留 `..` 词法规范化、已有目标严格解析、新目标最近已有父目录解析、符号链接逃逸识别和 Windows case/drive 处理。
- 允许已获授权的文件工具对 outside 物理目标真实执行；未经权限链不得直接执行。
- 保留 FileReadTracker 的 read-before-write、changed-since-read、物理身份与成功写后更新行为。
- 搜索 walker 不得因范围改造静默遍历意外物理目标；候选范围必须可供 Permission 保护。

### 依赖任务

Task 3。

### 参考资料定位

- `T07-三层权限系统.md` 第 2.4、3.3、7、13.7 节。
- T04 workspace、file、search 实现与测试。

### 完成边界

- outside 不再由 Resolver 硬拒绝；路径无法解析等普通错误仍明确失败。
- inside/outside、`..`、symlink、新路径、Windows 路径与 tracker 回归全部通过。

## Task 5 — Rule + Strategy Evaluator 与 Guard

### 任务目标

把可信 Action、规则快照、Session Grant 和模式收敛为最终 Decision，并提供默认敏感资源与高置信命令 Guard。

### 新增、修改和删除的文件

- 修改 `src/uthcode/core/permission.py`。
- 修改 `src/uthcode/integrations/permissions.py` 或其真实同名包。
- 修改 `src/uthcode/integrations/tools/process_tools.py`、`search_tools.py`。
- 扩充 `tests/test_permission.py`、`tests/test_permission_rules.py`、file/search/process 与 permission integration 测试。

### 文件职责及实施内容

- 严格实现最高匹配来源优先与同来源 `DENY > ASK > ALLOW`，不得误写成全局 deny wins。
- Guard 在三模式均生效；Policy 在 `full_access` 忽略；Guard Allow 在普通模式继续 Policy/Strategy，在 `full_access` 放行。
- Session Grant 不覆盖 Guard 或 Policy Deny，仅替代相同工具、动作、Effect、有界资源的 Strategy Ask。
- 默认敏感 Guard 覆盖 `.env`（排除示例文件）、SSH、云平台、容器、Git、包管理凭据和私钥文件；metadata 枚举不自动等同内容读取。
- Grep/内容搜索必须识别候选敏感资源，不能通过目录级搜索泄露内容。
- 高置信 Bash Guard 覆盖跨平台根目录/用户目录/工作区根递归删除、磁盘破坏、fork bomb、提权、极端权限修改、远程脚本管道、关键进程和 Windows 磁盘操作；负例不命中 Guard，但仍可由 Effect/Strategy Ask。

### 依赖任务

Task 4。

### 参考资料定位

- `T07-三层权限系统.md` 第 3.3、8.3～8.5、9.3～9.5 与 13.2～13.4、13.8 节。
- MewCode `dangerous.py` 仅参考高置信正则意图；其 checker、PathSandbox、安全白名单和 UI 耦合均不得迁入。

### 完成边界

- 完整矩阵、来源优先级、敏感资源、Grep 旁路和 Bash 正反例自动测试通过。
- 危险命令测试只 mock/stub execute；代码和文档不把 Guard/classifier 宣传为 Sandbox。

## Task 6 — Permission Pause / Resume 与 Session Grant

### 任务目标

将 Ask 接入 T06 continuation，保持同一 Turn 恢复、Run-local Grant、FIFO 与取消优先。

### 新增、修改和删除的文件

- 修改 `src/uthcode/core/interaction.py`、`agent.py`、`agent_events.py`。
- 修改 `src/uthcode/application/runs.py`。
- 修改 `tests/test_agent_interaction.py`、`tests/test_agent_loop.py`、`tests/test_application_runs.py`，新增或扩充 permission integration 测试。

### 文件职责及实施内容

- 扩展现有 PauseRequest/Response 联合类型，加入脱敏 Permission Approval 请求与响应，保持严格 JSON 编解码和关联 ID 校验。
- 请求包含安全展示的 run/turn/tool_call、tool、action、Effect、resource、reason、mode、choices 与 Guard/ordinary 类型，不含 secret value。
- ordinary Ask 提供 once/session/reject；Guard Ask 只提供 once/reject。
- Agent Loop 在 ToolStarted 后、execute 前求值；Deny/Reject 生成标准 error ToolResult 和 ToolFinished，再继续同 batch。
- Resume 使用已 prepared 的同一次调用和授权模式快照，不重复 preflight 副作用；stale/wrong ID 拒绝。
- Application AgentRun 持有当前 mode 与 Session Grant；新 Run 恢复 default，取消和审批竞态保持取消优先。

### 依赖任务

Task 5。

### 参考资料定位

- `T07-三层权限系统.md` 第 2.2、2.3、8.5、10.1 与 13.5、13.6 节。
- T05 Agent Loop 和 T06 interaction/runtime 工作包、Feedback 与现有测试。

### 完成边界

- 不创建第二套 waiter、queue、future 或 UI 直连。
- AskUserQuestion 保持 T06 控制路径，不进入普通 Tool Permission。
- 普通/Guard 审批、同 Run 下一 Turn grant、拒绝继续、stale response 与取消竞态测试通过。

## Task 7 — `/permission` Application Session Control 与 TUI

### 任务目标

提供用户主动的当前 Run 模式切换与 Permission Approval 界面，并保持 Headless/CLI 安全边界。

### 新增、修改和删除的文件

- 修改 `src/uthcode/application/commands/models.py`、`builtins.py`；仅当现有 context 无法承载 session 操作时修改 `dispatcher.py`。
- 修改 `src/uthcode/application/runs.py` 的公共 session 控制 API。
- 修改 `src/uthcode/interfaces/tui/interaction.py`、`app.py`，按现有组件职责必要时调整 picker/state/rendering，但不得建立新 dispatcher。
- 修改 `src/uthcode/interfaces/cli.py`。
- 修改 command、completion、TUI、CLI、Application/Headless 测试。

### 文件职责及实施内容

- `/permission` 通过唯一 Registry 返回三模式 picker 所需的 Application action/DTO；help 与 completion 自动从同一 Registry 得到命令。
- 模式只属于当前 Run/Application session，不写任何配置或规则文件，也不能由模型、Tool 或项目规则切换。
- `full_access` 只能由用户 slash 操作选择并展示明确高风险提示。
- pending Permission 使用授权开始时的模式快照；模式切换不得改写现有 request。
- TUI ordinary approval 显示三选项，Guard approval 只显示两选项，并只调用 Application 公共恢复 API。
- CLI 遇到 Permission Pause 不自动 allow、不读取 stdin 等待、不无限挂起，沿用非交互安全收口。

### 依赖任务

Task 6。

### 参考资料定位

- `T07-三层权限系统.md` 第 2.7、10.2、13.9、13.10 节。
- 当前 Application command Registry/Dispatcher、T06 TUI interaction 与 CLI 行为。
- MewCode `/permission` 仅参考用户主动切换意图，不继承其 UI 直连 checker、规则增删或 reset。

### 完成边界

- command、picker、风险提示、pending 快照、TUI 两类审批、CLI 与 Headless 测试通过。
- Interface 不导入 Core Permission evaluator 或 Integration Rule loader，不持有权威模式/规则状态。

## Task 8 [接入主流程] — 全链路 Composition

### 任务目标

在正式 Composition Root 接通唯一权限调用链并删除临时旁路。

### 新增、修改和删除的文件

- 修改 `src/uthcode/application/bootstrap.py`。
- 按真实接线需要修改 `src/uthcode/application/generation.py`、`tools.py`、`runs.py`。
- 修改前述任务涉及文件的最终接线与对应 bootstrap/application tests。

### 文件职责及实施内容

- Run 初始化时创建用户/项目权限文件、严格加载稳定 RuleSet，并组合 Core evaluator、工具 preflight 与 Run-local session 状态。
- 正式链路固定为 ToolCall → registered/validated → Action → Rules → Strategy → Allow/Deny/Ask → execute/ToolResult/T06 Pause。
- 手动 Tool 执行等既有公共入口必须使用同一授权边界，或在产品边界明确禁止；不得保留可绕过权限的生产入口。
- 规则解析错误在启动边界以稳定、脱敏方式硬失败。
- 删除实施中产生的 wrapper、adapter、重复 loader、重复 validator 或双轨 executor。

### 依赖任务

Task 7。

### 参考资料定位

- `T07-三层权限系统.md` 第 3.2、5、8 与 Task 8。
- 当前 `application/bootstrap.py`、`generation.py`、`tools.py`、`runs.py`。

### 完成边界

- 所有正式普通 Tool 执行路径都经过唯一权限链。
- 未修改 Provider adapter 的权限语义，AskUserQuestion 保持独立控制能力。
- Composition 与 Application 集成测试通过，无临时旁路。

## Task 9 [端到端验证] — Headless / CLI / TUI / Provider

### 任务目标

从真实入口证明三层权限系统的关键正常路径、失败路径、接口隔离和 Provider 一致性。

### 新增、修改和删除的文件

- 新增或扩充 `tests/test_permission_integration.py`。
- 修改 `tests/test_application_runs.py`、`test_application_tools.py`、`test_cli.py`、`test_tui.py`。
- 修改 `tests/test_anthropic_integration.py`、`test_openai_responses_integration.py`、`test_openai_compat_integration.py` 与 `test_architecture_boundaries.py`。
- 只在测试暴露真实缺陷时修改对应生产文件，不扩大功能范围。

### 文件职责及实施内容

- 参数化验证三模式、普通 once/session/reject、Guard once/reject、outside path、敏感资源与 Grep、Bash Guard、`/permission`。
- 验证 Permission Ask 的 ToolStarted/Pause/Resume/ToolFinished 顺序、同 batch 继续、一次执行、stale response 与 cancel race。
- 使用规范化 ToolCall 验证 Anthropic、OpenAI Responses、OpenAI-compatible 得到相同 Action 与 Decision；不得复制 Provider 特判。
- 验证 CLI 不自动批准，TUI 仅经 Application，Headless 完成完整 round trip。
- 以不导入/不依赖 Interfaces 的架构测试证明 Core/Application Headless 链路独立。

### 依赖任务

Task 8。

### 参考资料定位

- `T07-三层权限系统.md` 第 13 节完整测试矩阵与第 15 节验收标准。
- T04/T05/T06 全部回归测试和 Feedback。

### 完成边界

- 关键路径至少有一条从正式 Application 入口到真实安全文件操作的端到端测试。
- 三 Provider、Headless、CLI、TUI 与架构回归通过；危险 Bash 永不真实执行。

## Task 10 [遗留负担清理] — 旧语义与重复职责清理

### 任务目标

完成全量验证并清理被替代入口、重复职责、旧权限语义和范围外占位。

### 新增、修改和删除的文件

- 删除 Task 1～9 明确替代的旧执行入口、硬授权职责和临时实现。
- 修改现有测试以删除被替代旧行为；不得删除与 T07 无关的历史能力。
- 创建并持续追加 `feedback/W04-permission-delivery-feedback.md`，汇总最终验收证据。

### 文件职责及实施内容

- 扫描并清理 L1～L5、旧模式、PathSandbox、旧 YAML/local 规则、persistent always、LangGraph permission interrupt、Plan Permission、未来 Plugin/MCP/Skill 权限占位。
- 确认 outside 不 hard deny、无重复 schema validator、无第二 Pause waiter、无 Interface→Core/Integration 反向依赖、无第二 Slash dispatcher。
- 执行全量 pytest、Python compile、依赖检查、`git diff --check`、UTF-8/Markdown 检查和精确遗留扫描。
- Feedback 记录实际文件、机制、命令、结果、Checklist 状态、偏差、风险和清理结论；不得修改已冻结工作包文字。

### 依赖任务

Task 9。

### 参考资料定位

- `T07-三层权限系统.md` 第 14～16 节。
- `AGENTS.md` 非兼容性原则与 `docs/work/README.md` Feedback/冻结规则。

### 完成边界

- 全量测试、编译、依赖、差异、编码和架构扫描全部通过。
- 无兼容层、废弃实现、不可达分支、重复职责、重复实现或未来能力占位。
- 只完成实现与 Feedback，不提交、不推送、不归档工作包。
