# B01 私有测试集 v0 Spec

## 背景

UthCode 已具备单 Agent 的 Headless Application、稳定 Run/Turn 生命周期、公开事件、typed pause/resume、三层权限和 Plan/Todo 控制，但尚无固定任务集、隔离运行目录、确定性验收、实验指纹和可比较报告。Context Engineering 开始前，需要先建立一把不依赖 Context 实现、能够长期复用的私有评测尺子。

## 目标

- 提供一个仓库内版本化、运行态全部位于仓库外的私有 Eval 开发工具。
- 固定七个低维护任务，覆盖基础控制、跨文件证据、长任务、只读规划、询问恢复、权限边界和长上下文约束。
- 只通过公开 Application API 驱动真实 Agent Run，不复制 Agent Loop、权限系统或状态权威。
- 以 deterministic verifier 为正确性权威，并并列报告 correctness、context、exploration、efficiency、stability、safety 六个维度。
- 支持手动 smoke、baseline、compare 和精确 clean；默认离线且不产生真实模型费用。
- 在用户另行明确授权网络与费用后，完成一次固定条件的 pre-context baseline。

## 能力清单

### Task 1：任务与产物合同

建立严格、版本化的任务定义、验证结果、单次尝试记录和指标值合同；未知字段、非法路径、重复标识、非法交互、越界值和过宽权限规则必须拒绝，缺失指标与数值零必须严格区分。

### Task 2：仓库外 workspace 与安全清理

建立物理路径防线、只复制 fixture 的独立 attempt 布局、源码仓库污染基线和基于 manifest 的精确清理。不得覆盖、误报或清理任务开始前已有的用户改动。

### Task 3：单次 Headless attempt 执行

经公开 Application 入口运行同一个 Run/Turn，唯一消费事件流并获得稳定终态；支持任务声明的 typed interaction、权限阻断、超时取消和失败分类，且不在同一 workspace 盲目重试。

### Task 4：七个私有任务与 deterministic verifier

建立七个固定任务四件套。每个 verifier 只读 workspace、离线运行，并对 hard、partial、forbidden 情况给出稳定、统一的结构化结果。

### Task 5：六维指标、报告与 compare

从公开事件、终态、verifier 和可选 diagnostics 生成带原始值、分数、证据引用和可用性的报告。比较前校验全部实验指纹；安全失败不得被其他分数抵消，不生成单一综合排名。

### Task 6：手动入口与开发者文档

接通 smoke、run、compare、clean，记录安装、固定条件、成本、安全边界、结果解释、清理与回滚。真实 Provider 始终需要显式开关与用户费用授权。

### Task 7：[接入主流程]

将合同、workspace、执行、verifier、指标和报告串成唯一手动 Eval 链路；仅依赖 `uthcode.application` 公共边界，不接入正式产品 CLI、CI 或生产运行路径。

### Task 8：[端到端验证]

以 Fake Provider 从真实 Eval 入口完成单题 smoke 和全 suite 聚合，并覆盖关键失败路径；用户授权后再执行真实七题 baseline，未获授权时明确保留为未验证门禁。

### Task 9：[遗留负担清理]

移除开发中误生成的仓库内运行产物、临时秘密/自动授权逻辑、无调用方的通用抽象、兼容层、重复职责和不可达实现，同时完整保留用户原有改动。

## 非功能要求

- 默认 pytest、帮助与错误路径完全离线，不触发真实 Provider 或费用。
- 不新增第三方依赖；使用 Python 标准库和项目现有依赖。
- 所有 workspace、home、cache、日志、artifact 和报告位于经校验的仓库外专用根目录。
- 事件和产物不得包含 API key、token、Provider 原生对象或未经脱敏的 ToolResult 正文。
- 运行结果必须可复现、可解析、可比较；当前没有结构化事实的 Context 指标明确标为不可用。
- 中文 Markdown 使用 UTF-8；代码与文档通过与风险相匹配的定向和全量验证。

## 设计骨架

```text
manual eval entry
  -> validate repo + external root
  -> load versioned task + immutable fixture
  -> create isolated workspace/home/artifacts
  -> uthcode.application public API
  -> one AgentRun / one Turn / one event stream
  -> deterministic verifier subprocess
  -> six-dimensional attempt record
  -> JSON + Markdown + terminal report / compatible compare
```

Agent Loop 继续是 RunState 的唯一写入者。Eval 只收集公开事件与终态、响应任务预声明的 typed interaction，并将 Permission ASK 视为阻断；Bash 仍是当前 OS 用户权限下的 unsandboxed process execution。

## 能力欠账

| 来源 | 欠账需求 | 回补前置 / 触发条件 |
| --- | --- | --- |
| B01 私有测试集 v0 | 上下文有效性当前只能使用已有 evidence discovery、Usage 和 Tool 轨迹；无法计算压缩、Working Set 选择与淘汰、证据保留与恢复、Memory injection 命中等指标。 | Context Compiler、Compaction、Working Set 或 Memory 任一能力开始实施并产生结构化运行事实时，由对应任务接入 B01 的版本化 diagnostics。 |

本项不回补既有 Context、Session、Memory 或跨 Turn Todo/Plan 欠账，只建立未来比较基线。原始需求提出拆包阶段不改全局清单，但现行 `WorkPackageRules.md` 要求真实欠账同步，因此本工作包创建时同步登记该项。

## Out of Scope

- CI、定时回归、后台调度、自动上传和 PR required checks。
- 公共 Benchmark、第三方数据集、Leaderboard、跨 Agent 排名和单一综合总分。
- LLM Judge、数据库、Web UI、趋势服务、容器编排和 OS Sandbox。
- Context Compiler、Compaction、Working Set、Memory、Session 与长期上下文策略本身。
- 正式 `uthcode` CLI/TUI、公共 AgentEvent、Agent Core 状态模型、Provider 或 Permission 语义修改。
- 自动批准 Permission、自动修复失败任务、自动重试可能已产生副作用的 Tool。
- 为未来 Skill、MCP、Subagent、Multi-Agent 或通用评测预建扩展点。

## 验收标准

1. 手动入口提供帮助、smoke、run、compare、clean，且不注册正式产品命令或新增 CI。
2. 仓库、仓库子目录、回指仓库的链接、文件系统根、盘符根、用户 home 根在任何写入或删除前被拒绝。
3. 成功、Agent failure、Permission block、未声明交互、timeout、verifier error 和 runner error 有独立、可解析的结束分类。
4. 每个 attempt 独立使用 workspace/home/artifacts，fixture 不回写，用户原有 Git 改动保持不变且运行不新增仓库污染。
5. Eval 只经 Application 公共入口驱动 Run，不出现第二 Agent Loop、手工 Tool 执行或私有 Core 状态读取。
6. Run 使用 `auto` 和有界任务规则；Permission ASK 不自动批准且不建立 Session Grant。
7. 七个 verifier 覆盖 hard、partial、forbidden，重复运行结果稳定，模型 final 不能覆盖 verifier 失败。
8. attempt artifacts 包含足够的元数据、事件、终态、验证、diagnostics、workspace diff 与输出 manifest，且不泄露秘密或原生对象。
9. 六维报告保留原始指标、逐次结果、中位数、分数与 delta；安全硬失败独立展示，不生成单一排名。
10. 缺少 Runtime 结构化事实时，相应 Context 指标为不可用而不是零或猜测值。
11. compare 校验代码、任务、模型、Provider、Prompt、配置、权限、运行参数和平台指纹；不兼容结果不生成正式 A/B delta。
12. 默认测试和 Fake smoke 离线；真实 Provider 仅在显式开关及用户授权费用后运行。
13. 用户授权后完成固定模型、七题、固定次数的 pre-context baseline，并记录命令、实验标识、指纹、逐题与聚合结果；未运行不得宣称通过。
14. Eval 定向测试、相关 Application/Permission/Event/T08 回归、全量 pytest、compileall、pip check、架构边界、UTF-8 guard 和 `git diff --check` 均有精确结果记录。
15. 开发者文档明确 Bash 非 Sandbox、运行成本、外部目录、清理边界、结果解释、回滚和 Context 指标可用性。
