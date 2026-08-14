# T09 Prompt 与 Context Engineering Spec

## 背景

当前 UthCode 将公共 Coding Prompt 与运行时强制语义集中在 Core 代码中，并且把完整交互历史直接作为每次模型请求的 working history。长 Session 没有预算、投影或压缩边界；大型 Tool Result 在 Core 中被永久截断；`/compact`、`/new`、`/resume` 仍为占位命令。

T09 在保持单 Agent Loop、Core 状态唯一写入者和 Provider-independent 边界不变的前提下，建立第一版可持久 Session 语义历史与 Context Engine。

## 目标

- 将可编辑公共 Coding Prompt 迁入 package asset，与 Core Runtime Contract 和动态事实分离。
- 建立独立于 Run/Turn 的稳定 Session identity，支持当前项目范围的跨进程发现与继续新 Turn。
- 以 append-only 语义历史保存原始 Interaction 与不可变 Projection，将非权威运行日志独立存放。
- 建立固定 258K 窗口的 Provider-independent Context Compiler、Budget、Working Set 和诊断事实。
- 实现手动、自动和单次 reactive overflow 的按需模型 Compaction，不引入后台 Context Worker。
- 完整外置大型 Tool Result，只向模型提供有界 preview 与 Session 内 opaque ref，并支持分块重读。
- 完成 `/compact`、`/new`、`/resume`、Session Picker 和 TUI Context usage 的产品闭环。
- 向 B01 提供可比较的 Context diagnostics，保持概率性效果与 pytest 硬门禁分离。

## 能力清单

### Task 1 — Prompt Asset 与 Core Runtime Contract 分离

提供唯一公共 Coding Prompt package asset；Core 继续权威维护 Behavior Mode、Plan/Task、Runtime Feedback、Tool 能力真实性和完成约束；动态 Runtime/Environment/Projection 事实稳定排在公共文本之后。

### Task 2 — Semantic History / Projection Core Contract

定义 Provider-independent 的强类型 Session record envelope、Interaction 和 Compact Projection。原始 Interaction 不因预算或压缩被改写，Projection 只表达当前模型可见投影。

### Task 3 — JSONL Session Files 与 Runtime Log

为每个 Session 建立 durable append history、非语义权威 runtime log 和隔离的 Tool Result namespace；支持当前 project key 下的 Session 发现、排序和重建。

### Task 4 — 大 Tool Result 外置与 ToolResultRead

移除 Core 的永久数据截断语义。大结果先原子持久完整内容，再生成有界 working view；专用只读工具只能解析当前 Session 的 opaque ref。

### Task 5 — Context Compiler、Budget 与 Working Set

使用固定强类型 Source 编译确定性 Context Snapshot，在固定 258K 总窗口中扣除输出预留和安全余量，保护当前用户输入、Runtime State、active Projection 和未闭合 Tool 语义单元。

### Task 6 — 按需 Compactor 与 Projection Commit

实现 tool-free 单次模型压缩；支持 manual、安全请求边界的 auto 和最多一次 reactive overflow retry。只在 summary 完整有效时追加新 Projection。

### Task 7 — 跨 Turn Runtime State 与正式 Request Composition

所有正式 Agent Turn 改为消费 Context Snapshot。已完成 Turn 收口 active Task/Plan；中断且仍有未完成任务时保留结构化状态供后续 Turn reconcile；Compaction 不改写该状态。

### Task 8 — `/compact`、`/new`、`/resume` 与 TUI 产品闭环

实现三个命令的 Application 语义。`/resume` 进入独立 Session Picker，仅列出当前项目 Session，按最后使用时间倒序、每页 10 条，并支持键盘选择、翻页、确认和取消。`/status` 与输入区环形指示器消费同一 Application usage projection。

### Task 9 — B01 Context Diagnostics 与 Before/After Eval

将压缩、Working Set、Evidence 保留/重新发现、大结果外置和实际 Provider usage 纳入受控诊断，支持同实验指纹的前后比较。

### Task 10 — [接入主流程] 正式 Composition 收口

打通 Bootstrap 到 Provider 的唯一 Session/Context/Tool 正式路径，删除全量消息直通和永久截断旧语义，保留不冒充 Agent Context 路径的低层单次 generation。

### Task 11 — [端到端验证] Context / Compaction / Evidence

从真实 Application 入口验证多 Turn、新建/恢复 Session、Picker、Context usage、大结果重读、多次 Projection、失败不破坏和 diagnostics 比较。

### Task 12 — [遗留负担清理] 单历史 / 单 Context Path 收口

清除被替代的截断、Prompt 硬编码、命令占位、双轨 Context 组装、不可达代码和误导文档，确认未引入后台 Worker、第二 Agent Loop、通用 Registry、SQLite checkpoint 或兼容层。

## 非功能要求

- 保持 `interfaces -> application -> core` 依赖方向，Application 仅在 composition root 组合 Integration。
- Core 不读写文件系统，不依赖 Provider SDK、UI 或具体存储。
- Agent Loop 仍为唯一自动 Loop 和 RunState 唯一写入者；Tool Batch 仍严格 FIFO 并闭合每个 ToolCall ID。
- 持久写入具有可验证 durable/atomic 边界；unknown schema、中间损坏、伪造引用和跨 Session 访问 fail closed。
- 不新增第三方运行时依赖，不将固定 Context 窗口暴露为模型或用户配置。
- 测试必须注入临时 Session root，不得写入真实用户目录。
- 诊断和日志不包含 API key、完整外置 Tool Result、Provider native payload 或未脱敏异常。

## 设计骨架

```text
Package Prompt Asset + Core Runtime Contract + Runtime/Environment Facts
                                +
Session append-only Interaction History + active Compact Projection
                                |
                                v
                     Context Compiler / Budget
                                |
                                v
                         Context Snapshot
                                |
                ToolDefinition + Provider request

large Tool result -> atomic Session result file -> bounded preview/ref
                                                   -> ToolResultRead
```

Session History 保存“发生过什么”；Projection 表达“当前怎么看”；Context Compiler 决定“本轮模型看到什么”；Runtime State 保存“当前执行事实”；Runtime Log 只保存诊断事实。

## 能力欠账

| 来源 | 欠账需求 | 回补前置 / 触发条件 |
| --- | --- | --- |
| T09 Prompt / Context Engineering | `/resume` 只恢复最后一个已完整提交的安全边界并开始新 Turn；不恢复退出时仍 active/paused 的 Turn、Pending Tool、Permission、AskUser、Provider 请求或协程位置。 | 后续启动正式 Persistent Runtime Recovery，并回补 T05/T06 跨进程运行状态恢复时。 |

## Out of Scope

- active/paused Turn、Pending Tool/Permission/AskUser 和 Tool side effect 的跨进程恢复或重放。
- 跨项目全局 Session Browser、Fork、Worktree、Memory、Dream、Skill、MCP、Subagent 和 Multi-Agent。
- 后台 Context Agent/Worker、Structured Notes、Scheduler、工作流框架或第二 Agent Runtime。
- Provider-specific Prompt Overlay、cache-control、Context Window 和 retry policy。
- 用户 Prompt 系统、向量数据库、通用 Artifact Store/GC、Context Source Registry 或 Projection DSL。
- OS Sandbox、SQLite checkpoint 和旧 Re:UthCode 兼容层。

## 验收标准

1. 所有正式 Agent Turn 由唯一 Context Compiler 产生预算内 Snapshot，不再无条件发送全部 Run 消息。
2. Session identity 独立于 Run/Turn；同 Session 可跨 Turn、跨进程继续，只有 `/new` 创建新 Session。
3. 语义历史 append-only；压缩只追加 Projection，既有 Interaction 和旧 Projection 不被改写或删除。
4. Runtime Log 丢失不改变 Session 语义恢复；stream delta、UI lifecycle 和 ToolProgress 不进入语义历史。
5. 大 Tool Result 完整持久且 hash 可核对，模型只收到有界 preview/ref；专用工具只能重读当前 Session 引用。
6. Prompt asset、Core Contract、Runtime State、Environment Facts 和 ToolDefinition 各有唯一权威来源，不存在 Provider-specific 分支或 schema 手写副本。
7. Context policy 固定使用 258K 总窗口，输出预留、安全余量、Tool schema 估算和受保护 Source 全部进入预算。
8. manual/auto/reactive Compaction 均在安全边界执行；reactive retry 最多一次；失败、取消、ToolCall 或无效 summary 不改变 active Projection。
9. `/compact`、`/new`、`/resume` 不再为占位；Session Picker 和 Context usage 展示符合已确认交互，Interface 不拥有 Session 业务真值。
10. TaskState/PlanState 仍是 Core Runtime authority；Compaction 不以 summary 替代结构化状态，跨 Turn 规则有正常和中断路径测试。
11. B01 可报告 Context diagnostics 并执行同指纹 before/after compare，概率性效果不作为 pytest 硬门禁。
12. Headless 端到端链路、定向与全量 pytest、compileall、pip check、架构边界、UTF-8/fence 检查和 `git diff --check` 都留下精确结果。
13. 相关用户手册、Tool 清单、Core Design、当前事实和索引与最终 `src/ + tests/` 一致，不把 Out of Scope 写成已实现。
