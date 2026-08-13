# UthCode 文档中心

本文件说明 `docs/` 下各类文档的职责、读取方式和维护要求。它是文档路由入口，不要求编码代理默认展开读取所有文档。

## 1. 文档目录

| 路径 | 面向读者 | 职责 |
| --- | --- | --- |
| `user-manual/` | UthCode 用户 | 安装、配置和命令使用说明 |
| `core-design/` | 用户与开发者 | 结合 UthCode 讲解 Agent Core 的技术教程 |
| `Tools.md` | 用户与开发者 | 当前可用 Tool、模式可见性和安全边界 |
| `Context-Index.md` | 编码代理 | 当前代码事实入口、上下文路由和工作包状态 |
| `context/` | 编码代理 | 按执行、控制、状态和编排层记录当前代码事实 |
| `work/` | 拆分、实施和审查人员 | 活跃工作包与已归档历史记录 |
| `OutstandingDebtList.md` | 拆分与设计人员 | 因后置能力未实现而保留的真实能力欠账 |
| `rules/` | 编码代理 | 工作包规则、用户决策边界等长期工程规则 |

当前事实发生冲突时，以 `src/ + tests/` 为准；`Context-Index.md` 与 `context/` 用于定位和解释当前事实，工作包与归档记录只提供需求和历史证据。

## 2. 按场景读取

| 场景 | 最少读取范围 |
| --- | --- |
| 普通开发或修复 | `Context-Index.md`，再读取命中的 `context/**` |
| 拆分或重新拆分工作包 | 本文件、`Context-Index.md`、`rules/WorkPackageRules.md`、`OutstandingDebtList.md`，再读取命中的当前事实 |
| 执行 Worker Prompt | `rules/WorkPackageRules.md`、指定 Prompt 及其要求的文件 |
| 包级验收 | 本文件、任务包 Checklist 与 Feedback、相关源码和测试，再按下表检查文档 |
| 用户手册或核心设计维护 | 本文件、目标文档及对应的当前代码事实 |

读取本文件不等于读取整个 `docs/`。只沿任务命中的路由加载必要内容，不默认遍历 `work/archive/` 或全部设计文档。

## 3. 文档维护映射

| 发生的改动 | 必须检查和按需更新 |
| --- | --- |
| 项目定位、安装入口或主要能力 | 根 `README.md`、`user-manual/getting-started.md` |
| 配置字段、发现规则或安全边界 | `user-manual/configuration.md`、相关 `context/**` |
| CLI 或 Slash Command | `user-manual/commands.md`、相关 `context/**` |
| Tool 新增、删除、改名或模式可见性变化 | `Tools.md`、相关用户手册、`core-design/`、相关 `context/**` |
| Agent Core 的运行语义或长期边界 | 相关 `core-design/`、相关 `context/**`，必要时更新根 README |
| 工作包创建、重拆或状态变化 | `Context-Index.md`、`OutstandingDebtList.md` 和工作包要求的记录 |
| 包级验收 | 上述所有与该包能力相关的文档；不得只更新工作包 Feedback |

用户手册回答“如何使用”，核心设计回答“Agent Core 如何运作”，当前事实文档回答“代码现在如何实现”，工作包回答“本次交付要求和结果是什么”。不同文档可以描述同一能力，但不要互相替代，也不要让用户文档直接变成任务书摘要。

## 4. 文档验收

维护文档时至少检查：

- 内容与当前 `src/ + tests/` 一致，不把规划中或归档中的能力写成当前事实；
- 文档内部链接有效；
- 中文 Markdown 能以 UTF-8 解码，无 replacement character 和常见乱码；
- Markdown fenced code block 成对闭合；
- 示例不包含真实 API Key、token 或其他秘密；
- 包级验收已覆盖该包影响的用户手册、核心设计、Tool 清单、当前事实和索引。

## 5. 工作包规则

工作包生成、派发、实施、反馈、冻结和索引维护统一遵守：

- [工作包规则](rules/WorkPackageRules.md)

`docs/work/` 只保存活跃工作包和已归档历史记录，不再保存规则副本。
