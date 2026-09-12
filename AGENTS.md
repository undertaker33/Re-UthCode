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
5. 参考仓库和归档工作包仅用于补充证据；当前事实以 `src/ + desktop/src/ + tests/ + desktop/tests/` 为准。

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
- Tool 可通过当前 `CancellationToken.report_progress()` 发布有界执行观察；Application 在唯一 `AgentEvent` 流中完成归属、跨 chunk 尾部脱敏和限量投影，进度不写入 `RunState`、History 或 Provider 请求。
- `Bash` 是当前 OS 用户权限下的 unsandboxed process execution，不得描述为 Sandbox。
- Permission 固定支持 `default`、`auto`、`full_access`。`full_access` 跳过内置普通 Guard、普通 Policy 与 Strategy，但仍受用户/项目显式 Guard ASK/DENY 和灾难性 circuit breaker 约束；工具注册、参数校验、OS 权限和第三方权限始终有效，项目配置不得静默启用 `full_access`。
- Permission Approval 是应用层授权，不是 OS Sandbox。Session Grant 只属于当前 `AgentRun`，不得自动持久化。
- API key 只允许出现在用户级 `config.toml` 的 Provider `api_key` 字段，形式为 literal 或 `env:VARIABLE_NAME`；项目配置禁止 Provider、端点和一切凭据等价字段。解析后的值必须进入不可序列化、`repr` 脱敏的内部 `SecretValue`，只在 Provider SDK 构造边界显式取值，不得进入 Prompt、History、Event、日志、Journal、Snapshot、diagnostics 或 Eval artifact。Permission 动作规则与普通 `config.toml` 分离。

## 配置安全

- 普通配置按“默认值 -> 用户配置 -> 项目配置”合并。Git 仓库内从仓库根到当前目录发现项目配置；非 Git 目录只读取当前目录；候选路径在加载前规范化、解析物理路径并去重。
- 项目配置只能覆盖允许字段或收紧权限，不得修改秘密来源、重定向 Provider/端点/Key，或将权限提升为 `full_access`。
- 项目配置只能引用用户配置中的可信 Provider，并调整非秘密 Model 数据；检测到凭据或等价重定向字段时必须硬失败。
- 用户默认模型写回只原子修改用户配置顶层 `default_model`，不得写入项目配置或改变 Provider/Model 表。

## 工程实施与收敛

- 完成当前需求的最小完整闭环，使改动可运行、可测试、可审查、可回退。优先修改现有实现；仅在当前职责无法清晰承载时新增文件，不做无关目录重排或预留未来能力。
- 新增抽象、状态、校验或恢复机制，必须服务于当前真实调用方、可指出的真实失败模式或明确外部约束；已有机制能直接解决时不重复建设。达到当前产品语义和验收要求后停止扩展，不继续枚举假想边界。
- 可以引入能减少自实现代码、维护状态可接受且符合模块边界的成熟依赖；依赖放入真实使用层，不重复实现项目或成熟依赖已有的能力。
- 替换实现时删除被替代的代码、测试、不可达分支和重复调用链。除当前需求明确要求兼容外，不保留旧类、API、数据结构、行为、别名、包装层或双轨入口；现存持久化业务数据只做结构变化所必需的迁移。
- 用户明确排除的设计，其配套抽象、状态、测试及解释该设计的大段实现性文档一并移除。
- 在授权范围内自行解决普通实现选择、编译错误、测试失败和局部缺陷。需要用户拍板时按 `docs/rules/UserDecisionBoundary.md` 判断，仅暂停受影响范围，继续可独立完成的已授权工作。
- Tool 是否已经产生副作用无法确认时，停止相关操作，禁止盲目重试。
- Python 版本、项目依赖和开发依赖以 `pyproject.toml` 为唯一权威来源。实施和验证使用既有 `re-uthcode` Conda 环境，不另建平行环境、依赖描述或构建体系。

### 构建与版本

涉及构建时，输入描述自身来源和版本，产物可以拥有唯一内容标识。版本 Pin 只服务于真实兼容性、可复现性或上游约束；不为单次构建身份绑定输入、复制输入再编译，或增加路径敏感 Hash、重复 SHA256、专用 Manifest 等无外部协议要求的完整性证明链。

### 状态变更与缓存

以下规则适用于当前任务涉及的状态或缓存，不要求无关任务建设全局恢复或清理设施。

- 将状态收敛到目标时，优先使用一个幂等入口；没有独立产品语义时，不按历史动作维护平行执行链。
- 原子性采用满足当前一致性要求的最小粒度，文件系统原则上以单个目标文件 / inode 为单位。优先短事务、局部原子替换和重新读取真实状态，不默认引入全局事务、跨大量对象的 Journal 或两阶段提交。
- 对当前状态变更处理进程退出、异常和 cancel，不假定前序步骤完整执行。能依据真实状态自动恢复时继续收敛；只有冻结产品或安全语义要求时，才以 `fail-fast` / `fail-closed` 停止并交给用户。
- Cache 不是权威状态，删除后必须可重建；相关缓存应接入统一清理能力，并在正常运行时淘汰失效、无引用或确定不再复用的内容，不依赖用户手动 `clean` 才限制增长，也不演变成需要独立迁移、事务恢复或人工修复的业务状态。

### Safety / Security 设计边界

- 落实当前任务要求和已冻结安全边界，普通功能开发不自行扩大为安全审计。新增安全机制（包括完整性校验、权限隔离及 `fail-closed`）须有明确攻击者、受保护资产和具体攻击路径；不能仅以“安全最佳实践”为依据。
- 已控制机器或运维权限的攻击者不作为普通功能的默认威胁模型；不据此妨碍日志、诊断、状态观察和恢复。无真实权限或隔离边界时，不在内部调用链反复切换权限身份。
- 上述收敛原则不改变 Permission、Secret、配置隔离、灾难性 circuit breaker 或其他已冻结安全约束。

### Subagent 与并行实施

- 复杂任务应按职责、依赖和修改范围拆分给 Agent / Worker，避免无边界重复探索；用户明确要求不使用子代理时由当前 Agent 完成。
- 无写集合重叠且无顺序依赖的任务可以并行；共享变动区域保持单写者，局部串行或重新划分，不默认加整个仓库的全局单写锁。
- 不为未来并行 Agent 预建通用锁、调度、租约或仓库级事务机制。

## 工作包与能力欠账

- `docs/rules/WorkPackageRules.md` 是工作包生成、派发、实施、反馈、冻结和索引维护的完整规则；根文件不复制其细节。
- 工作包的“能力欠账”只记录：当前任务包因依赖尚未实现的后置能力而刻意未继续设计或实施的部分。
- 拆分或重新拆分工作包时，必须核对该章节并维护 `docs/OutstandingDebtList.md`：新增真实欠账、更新已有来源或触发条件，并删除已在当前任务中回补且不再成立的条目。
- 一般 Out of Scope、独立未来需求、当前实现缺陷和未确认设想都不是能力欠账；没有真实触发条件时，不为欠账预先设计方案。
- 工作包拆分完成前，同时更新 `docs/Context-Index.md` 的 `current-status`；欠账清单与索引维护不授权修改已冻结工作包或自行归档。
- 用户首次显式派发 Worker Prompt 后，严格遵守工作包冻结边界；发现任务书错误或需扩大范围时，在 Feedback 中记录并停止相关范围。

## 验证与交付

- 使用与改动风险匹配的最小定向测试，覆盖当前行为和关键回归，并完成任务包明确要求的更大范围验证。低影响改动不新增仅复述实现的测试。
- 必要检查通过后，仅在新增修改、失败或具体未解决问题出现时扩大或重复验证；否则结束验证并交付。
- 进行包级验收时，必须按 `docs/README.md` 的维护映射同步所有与该包能力相关的文档，确保用户手册、核心设计、当前事实文档、索引和工作包记录与当前代码一致。
- 修改架构边界时运行 `tests/test_architecture_boundaries.py`；修改公开行为时覆盖正常路径和关键失败路径。
- 文档必须与当前代码事实一致，中文 Markdown 以 UTF-8 保存，并检查 replacement character、常见乱码和 Markdown fence 平衡。
- 交付说明应列出实际改动、执行的命令及精确结果、未验证项、风险和遗留问题；不得把未运行的测试描述为通过。
- 用户要求提交时，按可独立运行、测试、审查和回退的实际功能边界组织提交，不机械拆碎；对 `feat:` 等不完整 message，按已确认范围补全为准确描述改动的内容。
- 未经用户明确要求，不执行 Git commit、push、merge、rebase、tag、release 或工作包归档。

## 参考来源

- 当前事实与验收：`src/`、`desktop/src/`、`tests/`、`desktop/tests/`、`docs/Context-Index.md`
- 文档路由与维护：`docs/README.md`
- 工作包规则：`docs/rules/WorkPackageRules.md`
- 能力欠账：`docs/OutstandingDebtList.md`
- 历史设计参考：`D:\project\UthCode`、`D:\project\MewCode`
- 外部参考：[OpenAI Codex](https://github.com/openai/codex)、[learn-claude-code](https://github.com/shareAI-lab/learn-claude-code)、[Claude Code](https://github.com/anthropics/claude-code)、[Deepseek Harness](https://github.com/deepseek-ai/deepseek-harness/)
- TUI 参考：[FirstCoder](https://github.com/KomorGiaoGiao/FirstCoder)
