# AGENTS.md

拿到需求文件后，必须读取并遵守：

@docs/work/README.md

当任务中出现需要用户拍板的产品、架构、范围或安全决策时，必须读取：
@docs/rules/UserDecisionBoundary.md

## 项目说明

- 正式项目名为 UthCode，Python 包名和 CLI 名称为 `uthcode`。
- 本仓库以增量开发为主；只实施用户当前明确指定的需求或工作包，不提前建设未来能力。
- 本项目未启用 `uth-governance`。除非用户显式指定，否则不要走 UTH 场景路由。

## 开始工作前

1. 使用 Conda 环境：`conda activate re-uthcode`。
2. 先读 `docs/Context-Index.md`，按任务命中的层级读取最少必要的 `docs/context/**` 当前事实文档。
3. 收到需求文件、拆分工作包或执行 Worker Prompt 时，必须完整读取并遵守 `docs/work/README.md`。
4. 涉及尚未实现的后置能力或任务包中的“能力欠账”时，读取 `docs/OutstandingDebtList.md`；不得把一般 Out of Scope 或未来能力自动记为欠账。
5. 参考仓库和归档工作包仅用于补充证据；当前事实以 `src/ + tests/` 为准。

## 架构边界

项目采用模块化单体，顶层结构固定为：

```text
src/uthcode/
├── core/           # 无界面的 Agent Core 与权威领域模型
├── application/    # Command、用例、组合入口和统一 Event 出口
├── integrations/   # Provider SDK、存储、进程等外部系统适配
└── interfaces/     # TUI、CLI、Web、Desktop、IDE 等交互适配器
```

依赖方向固定为：

```text
interfaces -> application -> core
                  |
                  v
             integrations
```

- `core/` 不读取 stdin、不写 stdout，不依赖具体 UI、第三方 SDK、文件存储、进程实现、`application/`、`integrations/` 或 `interfaces/`。
- 第三方 SDK 类型只能存在于 `integrations/`，进入系统前必须转换为 UthCode 自有模型。
- 所有 Interface 只通过 `application/` 使用 Agent Core，不直接访问 Provider、Tool Registry、Permission Store 或 Core 内部状态。
- 删除或替换任意 Interface 不得改变 Agent Loop、Provider、Tool、Permission 和运行状态语义；Headless 路径必须可独立运行。
- 源码按稳定职责组织，不按任务编号、框架节点或一个类型一个文件组织；没有真实调用方时，不创建 Protocol、Repository、Manager、Factory、空目录或占位实现。

## 核心实现约束

- Runtime 使用显式、集中、顺序可读的 ReAct Agent Loop；不引入 LangGraph、LangChain Agent、通用图框架、工作流 DSL 或 DAG 调度器。
- Provider 逻辑保持实现无关；Runtime 中不得按 Provider 名称分支。通用 SDK、HTTP、校验和重试能力优先使用成熟依赖。
- Tool Batch 严格 FIFO；每个 `ToolCall` 必须得到对应 `ToolResult`。单个 Tool 被拒绝或发生普通错误时，应形成受控结果，不直接使整个 Run 崩溃。
- Agent Loop 是 `RunState` 的唯一写入者；Tool、Provider、Permission、Storage 和 Interface 只能返回结果、事件或控制响应。
- `Bash` 是当前 OS 用户权限下的 unsandboxed process execution，不得描述为 Sandbox。
- Permission 固定支持 `default`、`auto`、`full_access`。`full_access` 跳过内置普通 Guard、普通 Policy 与 Strategy，但仍受用户/项目显式 Guard ASK/DENY 和灾难性 circuit breaker 约束；工具注册、参数校验、OS 权限和第三方权限始终有效，项目配置不得静默启用 `full_access`。
- Permission Approval 是应用层授权，不是 OS Sandbox。Session Grant 只属于当前 `AgentRun`，不得自动持久化。
- API key 真实值只从环境变量读取，不得写入配置、事件、日志、Journal 或 Snapshot。Permission 动作规则与普通 `config.toml` 分离。

## 配置安全

- 普通配置按“默认值 -> 用户配置 -> 项目配置”合并。Git 仓库内从仓库根到当前目录发现项目配置；非 Git 目录只读取当前目录；候选路径在加载前规范化、解析物理路径并去重。
- 项目配置只能覆盖允许字段或收紧权限，不得修改秘密来源、重定向 Provider/端点/Key，或将权限提升为 `full_access`。
- 项目配置只能引用用户配置中的可信 Provider，并调整非秘密 Model 数据；检测到凭据或等价重定向字段时必须硬失败。
- 用户默认模型写回只原子修改用户配置顶层 `model`，不得写入项目配置或改变 Provider/Model 表。

## 增量开发原则

- 每个任务必须可运行、可测试、可审查、可回退；只修改完成当前需求所需的最小范围。
- 已确认的公共边界不得无理由重排。产品语义与现有决策冲突或必须扩大到未获授权的后置能力时，停止并交由用户决定。
- 不为旧项目或 UthCode 早期实现保留旧类、旧 API、旧数据结构、旧行为、别名、包装层、废弃入口或双轨逻辑，除非当前需求明确要求兼容。
- 新实现替代旧实现时，删除旧代码、旧测试、不可达分支和重复调用链；不得重复实现项目现有能力或成熟依赖已经提供的能力。
- 普通编译错误、测试失败和局部实现缺陷应在当前范围内修复，不作为扩大范围的理由。
- Tool 是否已经产生副作用无法确认时停止，禁止盲目重试。

## 工作包与能力欠账

- `docs/work/README.md` 是工作包生成、派发、实施、反馈、冻结和索引维护的完整规则；根文件不复制其细节。
- 工作包的“能力欠账”只记录：当前 `TXX` 因依赖尚未实现的后置能力而刻意未继续设计或实施的部分。
- 拆分或重新拆分工作包时，必须核对该章节并维护 `docs/OutstandingDebtList.md`：新增真实欠账、更新已有来源或触发条件，并删除已在当前任务中回补且不再成立的条目。
- 一般 Out of Scope、独立未来需求、当前实现缺陷和未确认设想都不是能力欠账；没有真实触发条件时，不为欠账预先设计方案。
- 工作包拆分完成前，同时更新 `docs/Context-Index.md` 的 `current-status`；欠账清单与索引维护不授权修改已冻结工作包或自行归档。
- 用户首次显式派发 Worker Prompt 后，严格遵守工作包冻结边界；发现任务书错误或需扩大范围时，在 Feedback 中记录并停止相关范围。

## 验证与交付

- 使用与改动风险匹配的最小定向测试，再执行任务包要求的更大范围验证。
- 修改架构边界时运行 `tests/test_architecture_boundaries.py`；修改公开行为时覆盖正常路径和关键失败路径。
- 文档必须与当前代码事实一致，中文 Markdown 以 UTF-8 保存，并检查 replacement character、常见乱码和 Markdown fence 平衡。
- 交付说明应列出实际改动、执行的命令及精确结果、未验证项、风险和遗留问题；不得把未运行的测试描述为通过。
- 未经用户明确要求，不执行 Git commit、push、merge、rebase、tag、release 或工作包归档。

## 参考来源

- 当前事实与验收：`src/`、`tests/`、`docs/Context-Index.md`
- 工作包规则：`docs/work/README.md`
- 能力欠账：`docs/OutstandingDebtList.md`
- 历史设计参考：`D:\project\UthCode`、`D:\project\MewCode`
- 外部参考：[OpenAI Codex](https://github.com/openai/codex)、[learn-claude-code](https://github.com/shareAI-lab/learn-claude-code)、[Claude Code](https://github.com/anthropics/claude-code)
- TUI 参考：[FirstCoder](https://github.com/KomorGiaoGiao/FirstCoder)
