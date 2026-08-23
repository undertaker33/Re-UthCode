# AGENTS.md

拿到需求文件后，必须读取并遵守：

@docs/rules/WorkPackageRules.md

当任务中出现需要用户拍板的产品、架构、范围或安全决策时，必须读取：
@docs/rules/UserDecisionBoundary.md

## 项目说明

- 正式项目名为 UthCode，Python 包名和 CLI 名称为 `uthcode`。
- 本仓库以增量开发为主；只实施用户当前明确指定的需求或工作包，不提前建设未来能力。
- 本项目未启用 `uth-governance`。除非用户显式指定，否则不要走 UTH 场景路由。

## 开始工作前

1. 使用 Conda 环境：`conda activate re-uthcode`。
2. 先读 `docs/README.md` 和 `docs/Context-Index.md`，按文档路由与任务命中的层级读取最少必要内容。
3. 收到需求文件、拆分工作包或执行 Worker Prompt 时，必须完整读取并遵守 `docs/rules/WorkPackageRules.md`。
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
- API key 只允许出现在用户级 `config.toml` 的 Provider `api_key` 字段，形式为 literal 或 `env:VARIABLE_NAME`；项目配置禁止 Provider、端点和一切凭据等价字段。解析后的值必须进入不可序列化、`repr` 脱敏的内部 `SecretValue`，只在 Provider SDK 构造边界显式取值，不得进入 Prompt、History、Event、日志、Journal、Snapshot、diagnostics 或 Eval artifact。Permission 动作规则与普通 `config.toml` 分离。

## 配置安全

- 普通配置按“默认值 -> 用户配置 -> 项目配置”合并。Git 仓库内从仓库根到当前目录发现项目配置；非 Git 目录只读取当前目录；候选路径在加载前规范化、解析物理路径并去重。
- 项目配置只能覆盖允许字段或收紧权限，不得修改秘密来源、重定向 Provider/端点/Key，或将权限提升为 `full_access`。
- 项目配置只能引用用户配置中的可信 Provider，并调整非秘密 Model 数据；检测到凭据或等价重定向字段时必须硬失败。
- 用户默认模型写回只原子修改用户配置顶层 `default_model`，不得写入项目配置或改变 Provider/Model 表。

## 增量开发原则

- 每个任务必须可运行、可测试、可审查、可回退；只修改完成当前需求所需的最小范围。
- 已确认的公共边界不得无理由重排。产品语义与现有决策冲突或必须扩大到未获授权的后置能力时，停止并交由用户决定。
- 不为旧项目或 UthCode 早期实现保留旧类、旧 API、旧数据结构、旧行为、别名、包装层、废弃入口或双轨逻辑，除非当前需求明确要求兼容。
- 新实现替代旧实现时，删除旧代码、旧测试、不可达分支和重复调用链；不得重复实现项目现有能力或成熟依赖已经提供的能力。
- 普通编译错误、测试失败和局部实现缺陷应在当前范围内修复，不作为扩大范围的理由。
- Tool 是否已经产生副作用无法确认时停止，禁止盲目重试。

## 工程收敛与反过度设计

- 默认实现当前真实需求的最小完整闭环。已有机制能够直接解决时，不新增抽象层、校验层、恢复层或状态层。
- 不得仅因为“理论上可能发生”“更严谨”“更保险”“未来可能需要”而增加生产代码。新增防御机制前必须能够指出当前真实的失败模式、外部约束或调用方；否则不实现。
- 不为极低概率或没有现实触发条件的边界持续扩张设计。边界处理达到当前产品语义所需程度后应停止，不继续枚举假想状态。
- 用户明确排除某项设计后，不得继续保留该设计的配套抽象、状态、兼容层、测试或大段“为什么不采用”的实现性文档。

### 构建、版本与完整性

- 构建输入描述其自身来源和版本，构建产物可以拥有自己的唯一内容标识；不得无真实需求地把源码、依赖、镜像组件或资源绑定到某一次构建实例。
- 禁止为了构建隔离而复制一份输入再编译、引入路径敏感 Hash、重复 SHA256 校验、构建专用 Manifest 或其他没有外部协议要求的完整性证明链。
- Pin 版本必须服务于真实的兼容性、可复现性或上游约束，不得为了给单次构建制造唯一身份而 Pin。
- 已取得机器或运维控制权的攻击者不作为普通功能设计中的默认威胁模型；不得以此为理由妨碍正常 observability、调试、恢复和运维。

### 状态变更与原子性

- 对“把现有状态收敛到目标状态”的操作，优先设计一个幂等入口，而不是按历史动作拆出多套执行链。例如不存在独立产品语义时，`install` 应同时覆盖空状态、旧状态、目标状态和部分完成状态，不再额外维护平行的 `update` 主流程。
- 原子性使用完成当前一致性要求所需的最小粒度。文件系统修改原则上以单个目标文件 / inode 为一个原子修改单元，不为整个工作区建立长事务或全局事务。
- 优先使用短事务、局部原子替换、幂等操作和重新判定当前状态；不得为了支持回滚而默认引入跨大量对象的 Journal、两阶段提交或复杂恢复协议。
- 任意步骤都应考虑进程退出、异常和 cancel。恢复时优先重新读取真实状态并继续收敛，不依赖“之前一定完整执行过”的假设。
- 状态不一致属于实现需要解决的问题。除非已有冻结产品或安全语义明确要求，否则不得简单通过新增 `fail-fast` / `fail-closed` 把可自动处理的恢复工作推回给用户。

### 缓存

- Cache 不是权威状态。删除全部缓存后，系统必须能够从权威状态重新构建。
- 提供统一的缓存清理能力；正常运行时也应主动淘汰失效、无引用、被替代、任务已放弃或确定不再复用的缓存。
- 不得让缓存演变成第二套需要独立 migration、事务恢复、完整性校验或人工修复的业务状态。
- 用户没有显式执行 `clean` 不能成为缓存无限增长或长期保留废弃状态的理由。

### Safety / Security 设计边界

- 普通功能开发不得自行扩大为 Safety / Security 审计；只落实当前任务明确要求以及仓库已经冻结的安全边界。
- 不新增没有明确攻击者、受保护资产和具体攻击路径的安全机制。
- 不因假想的高权限攻击者增加妨碍日志、诊断、状态观察、故障恢复或正常运维的设计。
- 已有明确安全语义继续有效；本节不得用于绕过 Permission、Secret、配置隔离、灾难性 circuit breaker 或其他已经冻结的安全约束。
- 新的 `fail-closed`、`fail-fast`、完整性校验、权限隔离或防篡改机制必须有当前真实安全边界作为依据；不能仅以“安全最佳实践”为理由引入。
- 没有外部调用、真实权限边界或明确隔离需求时，不得在内部调用链中反复执行提权、降权或权限身份切换。

### Subagent 与并行实施

- 复杂任务应主动拆分并使用适合任务类型和复杂度的 Agent / Worker；调度者负责划分职责、依赖关系、修改范围和结果汇总，而不是让多个 Worker 无边界探索同一问题。
- 并行任务按照实际写集合隔离。只要求同一变动区域保持单写者，不得默认使用整个仓库的全局单写锁。
- 两个 Worker 的修改区域没有重叠且不存在顺序依赖时，可以并行；存在共享文件或共享状态时，由调度者重新划分边界或串行化该局部范围。
- 不得为了支持未来可能出现的并行 Agent，提前建设通用锁服务、调度框架、租约系统或仓库级事务机制。

### 技术与实现约束

- UthCode 当前为 Python 项目。Python 版本、项目依赖和开发依赖以 `pyproject.toml` 为唯一权威来源，不在其他规则中重复维护版本号。
- 实施和验证使用项目既有 `re-uthcode` Conda 环境；不得为了当前任务另建平行运行环境、第二套依赖描述或额外构建体系。
- 可以为当前真实需求引入成熟第三方依赖。引入前只需确认其确实减少自实现代码、符合现有模块边界且维护状态可接受；不得为了避免合理依赖而自行实现已有成熟能力，也不得为了“以后可能用到”提前增加依赖。
- 新依赖必须放入其真实使用层。Provider SDK、存储驱动、进程实现等外部技术不得因此穿透 `integrations/` 边界进入 `core/`。
- 不兼容旧 UthCode 实现，不为旧类、旧 API、旧数据结构、旧目录或旧行为增加迁移式兼容层。若当前仓库已经存在真实持久化业务数据，结构变化时只处理这些现存数据所必需的迁移。
- 可以在当前需求确有必要时调整目录和文件组织，但必须保持既有 `core / application / integrations / interfaces` 顶层边界；不得借功能开发进行无关的目录重排、架构美化或预留未来模块。
- 优先直接修改现有实现。只有当前职责已经无法由现有文件清晰承载时才新增文件；不得按“一个类型一个文件”机械拆分，也不得创建无当前调用方的公共抽象。
- 测试规模与真实改动风险匹配。优先验证当前行为和关键回归，不为无法影响当前产品语义的组合、极端状态或假想边界大量增加测试。
- Git 提交继续遵守仓库现有规则：未经用户明确要求不得自行 commit；用户要求提交时，再按照可独立运行、测试、审查和回退的实际功能边界组织提交，不机械制造细碎 commit。

## 工作包与能力欠账

- `docs/rules/WorkPackageRules.md` 是工作包生成、派发、实施、反馈、冻结和索引维护的完整规则；根文件不复制其细节。
- 工作包的“能力欠账”只记录：当前 `TXX` 因依赖尚未实现的后置能力而刻意未继续设计或实施的部分。
- 拆分或重新拆分工作包时，必须核对该章节并维护 `docs/OutstandingDebtList.md`：新增真实欠账、更新已有来源或触发条件，并删除已在当前任务中回补且不再成立的条目。
- 一般 Out of Scope、独立未来需求、当前实现缺陷和未确认设想都不是能力欠账；没有真实触发条件时，不为欠账预先设计方案。
- 工作包拆分完成前，同时更新 `docs/Context-Index.md` 的 `current-status`；欠账清单与索引维护不授权修改已冻结工作包或自行归档。
- 用户首次显式派发 Worker Prompt 后，严格遵守工作包冻结边界；发现任务书错误或需扩大范围时，在 Feedback 中记录并停止相关范围。

## 验证与交付

- 使用与改动风险匹配的最小定向测试，再执行任务包要求的更大范围验证。
- 进行包级验收时，必须按 `docs/README.md` 的维护映射同步所有与该包能力相关的文档，确保用户手册、核心设计、当前事实文档、索引和工作包记录与当前代码一致。
- 修改架构边界时运行 `tests/test_architecture_boundaries.py`；修改公开行为时覆盖正常路径和关键失败路径。
- 文档必须与当前代码事实一致，中文 Markdown 以 UTF-8 保存，并检查 replacement character、常见乱码和 Markdown fence 平衡。
- 交付说明应列出实际改动、执行的命令及精确结果、未验证项、风险和遗留问题；不得把未运行的测试描述为通过。
- 用户要求提交但只给出类似 `feat:` 的不完整 commit message 时，必须根据已确认的提交范围补全为语义完整、能够准确概括实际改动的 commit message，不得原样使用空泛前缀。
- 未经用户明确要求，不执行 Git commit、push、merge、rebase、tag、release 或工作包归档。

## 参考来源

- 当前事实与验收：`src/`、`tests/`、`docs/Context-Index.md`
- 文档路由与维护：`docs/README.md`
- 工作包规则：`docs/rules/WorkPackageRules.md`
- 能力欠账：`docs/OutstandingDebtList.md`
- 历史设计参考：`D:\project\UthCode`、`D:\project\MewCode`
- 外部参考：[OpenAI Codex](https://github.com/openai/codex)、[learn-claude-code](https://github.com/shareAI-lab/learn-claude-code)、[Claude Code](https://github.com/anthropics/claude-code)、[Deepseek Harness]((https://github.com/deepseek-ai/deepseek-harness/))
- TUI 参考：[FirstCoder](https://github.com/KomorGiaoGiao/FirstCoder)
