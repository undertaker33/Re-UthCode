# UthCode T09：Prompt 与 Context Engineering 任务书

> 状态：待实施  
> 目标仓库：`https://github.com/undertaker33/Re-UthCode`  
> 分析基线：`ae9f03f477bfcc99bc03ffaea99585b46da7c9d5`  
> 本任务完成后形成：**Package Prompt Assets + Session Semantic History + Projection-based Context Assembly + 固定 258K Context Budget + 按需 Compaction + 大 Tool Result 外置 + `/compact` + `/new` + `/resume` + Context Eval Diagnostics**

---

# 一、分析基线

## 1.1 当前仓库

```text
Repository: undertaker33/Re-UthCode
Branch:     main
Commit:     ae9f03f477bfcc99bc03ffaea99585b46da7c9d5
```

本任务所有实现判断均以该提交的 `src/ + tests/` 为事实基线。

## 1.2 已读取的约束与相关已完成任务

最高级约束：

```text
AGENTS.md
docs/README.md
docs/Context-Index.md
docs/rules/WorkPackageRules.md
docs/rules/UserDecisionBoundary.md
docs/OutstandingDebtList.md
```

相关已完成任务：

```text
T03  System Prompt 设计
T04  工具系统
T05  ReAct 与 Agent Loop
T06  暂停恢复与询问用户
T08  任务规划与执行控制
B01  私有测试集 v0
```

本任务命中的既有欠账：

```text
T02  /compact、/new、/resume 等预留命令真实行为
T03  动态 Context Source 参与 Prompt / Request 组装
T04  大 Tool Result 不再因当前内存模型而永久丢失
T05  长历史的选择、预算与压缩
T08  Todo / Plan 与跨 Turn、Compaction 的关系
B01  Context Compiler / Working Set / Compaction diagnostics
```

以下欠账仍不由 T09 回补：

```text
T05  完整 Run Runtime State 跨进程恢复
T06  Pending Turn / AskUser / Permission 在进程退出后的恢复
```

## 1.3 已核对的关键源码与测试

| 主题 | 当前文件 / 测试 | 基线事实 |
| --- | --- | --- |
| Prompt | `src/uthcode/core/prompt.py`、`tests/test_system_prompt.py` | 公共 Coding Prompt、Runtime 状态文本和环境事实目前仍集中硬编码在 Core |
| Provider DTO | `src/uthcode/core/provider.py`、Provider contract tests | `Message` 只允许 user / assistant / tool；`GenerationRequest` 独立持有 `system_prompt` 和 Tools |
| Agent Loop | `src/uthcode/core/agent.py`、`tests/test_agent_loop.py` | `RunState.messages` 直接作为每轮 Provider working history；Agent Loop 是 RunState 唯一写入者 |
| Planning State | `src/uthcode/core/planning.py` | TaskState / PlanState / BehaviorMode 是 Core Runtime 权威状态；不是普通历史消息 |
| Application Request | `src/uthcode/application/generation.py` | Application 每轮构造 System Prompt，并把当前完整 `messages` 直接发给 Provider |
| Run 生命周期 | `src/uthcode/application/runs.py` | `AgentRun` 是进程内多 Turn conversation；当前没有 Session 持久化 |
| Tool Result | `src/uthcode/core/tool.py` | `ToolExecutor` 在生成 `ToolResultPart` 前把内容硬截断到 10,000 chars，超过部分永久丢失 |
| 文件读取 | `src/uthcode/integrations/tools/file_tools.py` | `ReadFile` 读取 workspace 文件并支持 offset / limit |
| Permission | `tests/test_permission.py` | workspace 外 READ 在 default / auto 下仍为 ASK，因此不能把内部 Session Tool Result 当普通外部文件读取 |
| Slash Command | `src/uthcode/application/commands/builtins.py` | `/compact`、`/new`、`/resume` 已占位但未实现；`/plan`、`/do` 已实现 |
| Eval | `eval/metrics.py`、`docs/work/B01-私有测试集v0/` | 已支持可选 `context_diagnostics`，但当前没有 Context Engine 结构化事实 |

## 1.4 外部参考

| 来源 | 研究问题 | 最终采用结论 |
| --- | --- | --- |
| OpenAI Codex 当前源码 | Compaction 是否需要后台 Context Agent | 只借鉴“manual / auto 按需 compaction + replacement projection + recent tail”的机制，不引入持续后台 Context Worker |
| Claude Code 官方仓库公开 issue #81129 | 大 Tool Result 如何避免直接塞满上下文 | 借鉴“完整输出保存到 Session tool-results 文件 + inline preview + 后续可重新读取”的行为；UthCode 不复用其任意路径 Read 权限模型 |
| OpenCode 当前源码 | Context 压力是否可先做确定性处理 | 借鉴“先 prune / working view，再模型 compaction”的分层思想，不复制其 Session 数据模型 |
| 原 UthCode | 持续 Context Worker 的实际复杂度 | 明确不迁移 ContextJob / Worker / Progressive Summary Graph / 独立并发调度体系 |
| MewCode | JSONL Session / compact boundary 的简单实现 | 只借鉴 boundary 概念；不采用其复制 recent tail 或用 fake user message 表达 compact summary 的做法 |

---

# 二、当前实现基线

当前正式链路：

```text
Interface
   ↓
Application.create_run()
   ↓
AgentRun.start_turn()
   ↓
Core AgentLoop
   ↓
request_preparer(
  system_prompt,
  RunState.messages,
  ToolDefinition[]
)
   ↓
Provider Integration
```

当前有四个直接问题：

1. **Prompt 所有固定文本仍在代码中。** 开发者无法在 package 内以稳定资产方式维护公共 Coding Agent Prompt，且可编辑人格文本与 Core Runtime Contract 混在一起。
2. **完整 Session 历史和模型 working history 是同一个 `RunState.messages`。** 历史只能不断增长；一旦压缩，现有模型又缺少不改写原历史的投影层。
3. **大 Tool Result 在进入权威 ToolResult 前已永久截断。** 当前不是“模型少看一点”，而是超过 10,000 chars 的原始内容已经不存在。
4. **没有 Context Budget / Working Set / Compaction。** 每次请求只能把当前全部消息发给 Provider，无法控制长任务输入规模，也没有 `/compact`。

T09 不把现有 `RunState` 变成磁盘 Snapshot，也不把 AgentEvent 全量 dump 成历史。

---

# 三、问题定义

当前任务用于解决：

> **在保持单 Agent Loop、Core 状态唯一所有权和 Provider-independent 边界不变的前提下，将“完整 Session 语义历史”与“某次模型调用实际看到的 Context Snapshot”分离，并建立可持久、可投影、可预算、可按需压缩、可评测的第一版 Context Engine；同时将开发者可编辑的公共 Coding Prompt 从 Core 代码中独立出来。**

必须形成以下认知边界：

```text
完整 Session History
≠
当前 Context Snapshot
≠
Runtime State
≠
Runtime Log
≠
Provider wire message
```

---

# 四、任务目标

## 4.1 最终交付

T09 完成后必须具备：

1. 一套 package 内公共 Coding Agent Prompt Asset；
2. 可编辑 Prompt Asset 与不可编辑 Core Runtime Contract 分离；
3. 建立独立于 Run / Turn 生命周期的稳定 Session identity；同一 Session 可跨进程重新打开并继续新的 Turn；
4. 每个 Session 使用 append-only `history.jsonl` 保存语义历史；
5. History 同时支持强类型 Interaction Record 与 Projection Record；
6. 原始 Interaction Record 不因 Budget、Working Set 或 Compaction 被删除、覆盖或改写；
7. 独立 `runtime.jsonl` 保存 lifecycle / diagnostics / Eval facts，不作为语义历史权威；
8. Provider-independent Context Compiler，根据固定强类型 Source 编译一次 `ContextSnapshot`；
9. Context Budget、输出预留和第一版 Working Set；
10. 路线 B：按需模型 Compaction，不创建后台 Context Agent；
11. `/compact` 手动压缩；自动压力触发 Compaction；
12. `/new` 真正创建新的 Session identity；
13. `/resume` 默认只发现并恢复当前项目 / 工作目录关联的已持久 Session；恢复后仍使用原 Session identity，并从新的 Turn 继续；
14. 大 Tool Result 原文完整外置保存，模型只接收 bounded working view；
15. 专用只读 `ToolResultRead`，按 Session 内 opaque ref 分块重读完整 Tool Result；
16. T08 TaskState / PlanState 继续由 Core Runtime 持有，Compaction 不把结构化状态降级成 summary；
17. B01 可获得结构化 Context diagnostics，并能进行 before / after 效果比较；
18. TUI `/status` 增加固定 258K 口径的上下文使用进度条，并显示当前使用量 / 总量 / 百分比；
19. TUI 输入框下方状态信息区增加环形上下文使用指示器，与 `/status` 使用同一 Application Context usage 数据源；
20. `/resume` 进入独立 Session Picker 页面：按上次使用时间倒序展示当前项目 Session，每页固定 10 条，上下选择、左右翻页，条目展示上次使用时间与第一条 User Message 摘要。

## 4.2 最小完整调用链

```text
                 ┌──────────────────────────────┐
                 │ Session semantic history     │
                 │ history.jsonl                │
                 │  ├─ InteractionRecord        │
                 │  └─ ProjectionRecord         │
                 │ tool-results/<opaque>.txt    │
                 └──────────────┬───────────────┘
                                │
Prompt Asset ───────────────┐   │
Core Runtime Contract ──────┤   │
Runtime State ──────────────┤   ▼
Environment Facts ──────────┼─> Context Compiler
Interaction Projection ─────┘        │
                                     ▼
                              ContextSnapshot
                       ┌─────────────┴─────────────┐
                       │ system_prompt             │
                       │ messages                  │
                       │ diagnostics               │
                       └─────────────┬─────────────┘
                                     │
                    Tool System ─────┼─ ToolDefinition[]
                                     ▼
                              GenerationRequest
                                     │
                                     ▼
                              Provider Integration
```

Context Compiler 只决定“模型本轮看到什么”；它不拥有 Session 原始历史，不写 TaskState / PlanState，也不执行 Tool。

---

# 五、能力欠账

T09 回补完成后，以下已有欠账应在后续工作包拆分阶段从 `docs/OutstandingDebtList.md` 更新或删除：

```text
T03  动态 Context 参与 Prompt 组装
T04  大 Tool Result 永久截断
T05  历史选择 / Budget / Compaction
T08  Context Compaction 后 Task/Plan 仍由结构化 Runtime State 提供
B01  Context diagnostics 不可用
```

T09 新增的真实能力欠账：

| 来源 | 欠账需求 | 回补前置 / 触发条件 |
| --- | --- | --- |
| **T09 Prompt / Context Engineering** | `/resume` 只从最后一个已完整提交的安全边界恢复 Session，并从新的 Turn 继续；不恢复进程退出时仍处于 active / paused 的旧 Turn、Pending Tool、Permission、AskUser waiter、Provider 请求或协程执行位置。 | 后续正式 Persistent Runtime Recovery 开始实施，并准备回补 T05/T06 跨进程运行状态恢复时。 |

说明：后台 Structured Notes / Context Agent 只是未来可能重新探索的独立方向，不属于当前 T09 因缺少后置前置能力而形成的真实能力欠账，不写入欠账清单。

---

# 六、核心产品行为

| 场景 | 输入 / 前置状态 | 预期行为 | 状态变化 | 对外结果 |
| --- | --- | --- | --- | --- |
| 普通新 Turn | 当前 Session 已有历史 | append 新语义交互；Context Compiler 读取当前 Projection + recent history + Runtime State | Session identity 不变 | 模型获得预算内 Context Snapshot |
| `/new` | 当前 Session idle | 创建新的 Session identity，并为其建立新的 in-memory AgentRun；旧 Session 文件保持不动 | 切换到新 session_id，新空 history/runtime log | TUI 进入新会话 |
| `/resume` | 当前无 active Turn | 默认扫描当前项目 / 工作目录关联的可恢复 Session；进入独立 Session Picker 页面；用户选定后重建其完整 Interaction History、active Projection、Tool Result namespace，并创建新的 in-memory AgentRun | session_id 保持被恢复 Session 原值；Run / Turn identity 重新创建 | TUI 回到原 Session，并从新的 Turn 继续 |
| `/resume` Session Picker | 当前项目存在可恢复 Session | 按 `last_used_at` 倒序排列；每页固定 10 条；上下键移动当前页选择，左右键翻页；Enter 恢复选中 Session；Esc 返回原聊天页且不改变当前 Session | 选择器状态仅属于 Interface；Session 真值不变，直到 Enter 确认 | 每条显示“上次使用时间 + 第一条 User Message 单行摘要”，超出可用宽度以省略号截断 |
| `/resume` 无匹配 Session | 当前项目 / 工作目录没有已保存 Session | 不跨项目兜底，不静默创建新 Session | 无状态变化 | Session Picker 显示当前项目无可恢复 Session，并允许返回 |
| TUI `/status` | 当前 Session 已建立 | 从 Application 获取统一 Context usage view | 不修改 Context / Session | 输出当前 Context 使用量、固定 258K 总量、百分比与线性进度条 |
| TUI 输入区状态栏 | TUI 正常聊天视图 | 从同一 Context usage view 渲染环形上下文使用指示器 | 纯 Interface projection | 环形指示器随 Context 使用变化刷新，不自行估算 token |
| `/compact` | Run idle 且存在可压缩历史 | 运行一次 tool-free Compactor；成功后 append 新 ProjectionRecord | 原 InteractionRecord 不变；active projection 前移 | 返回 compact 成功及可观测摘要信息 |
| `/compact` 无需压缩 | 历史不足以形成有效 head/tail | 不调用或不提交无意义 Projection | 无状态变化 | 明确返回“当前无需压缩”语义 |
| `/compact` 模型失败 | Provider error / invalid summary / cancel | 不修改 active projection | 保留旧 projection | 返回受控失败，不损坏 Session |
| 自动 Compaction | 预测输入超过安全 Budget | 在下一次正常 Provider request 前按需压缩历史 head；保留 recent raw tail | append ProjectionRecord | 主 Agent 继续同一 Turn / Session |
| 大 Tool Result | Tool 完成且结果超过外置阈值 | 先完整落盘，再生成 preview + opaque ref 的 ToolResult working view | full content 文件持久化；History 记录 ref | 模型不会一次接收完整大输出 |
| `ToolResultRead` | 模型持有当前 Session result ref | 按 offset / limit 读取对应持久结果 | 不改历史 | 返回指定片段，普通 ToolCall ID 继续闭合 |
| 非法 ToolResult ref | 其他 Session、伪造 ref、路径文本 | fail closed，不解释内部真实路径 | 无状态变化 | 普通 Tool error result |
| Compaction 后重读 Evidence | 旧 ToolResult 已不在 current raw tail | ref 仍有效 | 无历史改写 | 模型可按需重新读取完整证据 |
| Session 内跨 Turn | 上一 Turn 已完成 | 完整语义 History 继续累积；不新建 Session | history seq 继续增长 | 后续 Context 由 Projection / Working Set 决定 |
| 上一 Turn 中断且有未完成 Task | failed / cancelled + unfinished TaskState | 下一 Turn 继续保留未完成 TaskState；已批准且仍相关的 PlanState 同步保留，模型先根据新 User Message reconcile | Runtime State 延续；History 不复制 | 长任务可继续；可通过 TodoWrite / 新 Plan 正式重写 |
| 上一 Turn 正常完成 | completed | 结束 active Task/Plan Runtime State；其历史证据仍永久留在 Session | 新 Turn active Task/Plan 清空 | 不让旧已完成计划污染新目标 |
| Compaction | 任意 TaskState / PlanState | 只改变 History Projection，不改结构化 Runtime State | Task/Plan 原值不变 | Context Snapshot 重新注入当前结构化状态 |
| JSONL 尾部半写 | 进程在最后一行写入期间异常 | 只允许识别并丢弃最后一个未完成 JSON fragment；中间损坏必须硬失败 | 最后稳定 record 仍为权威 | 不伪造恢复数据 |
| Runtime Log 丢失 | history 完整 | Session 语义恢复不受影响 | diagnostics 减少 | 不改变模型任务语义 |

### 6.1 Session 与 Projection 的硬边界

```text
Session
├─ history.jsonl
│   ├─ InteractionRecord  # 原始完整语义事实
│   └─ ProjectionRecord   # 当前 Context 从原历史如何投影
├─ runtime.jsonl          # 非语义权威 diagnostics
└─ tool-results/
    └─ <opaque-id>.txt    # 大 Tool Result 完整原文
```

关键规则：

```text
/compact
  ≠ 新 Session
  ≠ 删除旧 History
  ≠ 重写 history.jsonl

/new
  = 新 Session identity
  = 新 history / runtime / tool-results namespace

/resume
  = 恢复既有 Session identity
  = 恢复该 Session 的完整 Interaction History + 最新合法 Projection + Tool Result namespace
  = 新建本次进程内 Run / Turn 生命周期
  ≠ 恢复旧 active / paused Turn
```

当前 active Projection 由 `history.jsonl` 中最后一个合法、已完整提交的 ProjectionRecord 决定。无需额外可变 `current_pointer.json`。

### 6.2 Projection 第一版只实现 Compact

第一版 Projection Operation 仅实现：

```text
operation = compact
```

ProjectionRecord 表达：

```text
previous projection（可选）
+ 已被 summary 覆盖到的稳定 history position
+ recent raw tail 起点
+ compact summary
```

不提前实现：

```text
fold
hide
pin
branch patch
任意 Projection DSL
```

二次 Compaction 使用：

```text
上一版 compact summary
+
上一版之后新增且准备被覆盖的完整 Interaction Records
```

产生新的 ProjectionRecord；旧 ProjectionRecord 保留，不原地更新。

### 6.3 大 Tool Result 不是“截断后补救”

必须删除当前“先截断再丢失”的产品语义。

正确流程：

```text
Tool.execute()
    ↓
完整 ToolExecutionResult
    ↓
结果物化
    ├─ 小结果：直接形成 inline ToolResult
    └─ 大结果：完整原文原子写入 tool-results/
                ↓
        bounded preview + opaque ref
                ↓
           ToolResultPart
```

`ToolResultRead` 只接受 opaque ref，例如：

```text
tr_01...
```

禁止接受：

```text
任意绝对路径
../
history.jsonl
runtime.jsonl
其他 Session 的 result id
```

这使它成为“读取已授权工具执行结果”的能力，而不是新的通用文件系统读取入口。

### 6.4 TUI Context Usage 与 Session Picker

#### Context usage 统一口径

TUI 不得自行统计字符、消息条数或重新实现 Token Estimator。Application / Context Engine 必须提供一个只读的当前 Context usage projection，至少包含：

```text
used_tokens
total_tokens = 258_000
usage_ratio
```

显示语义固定为：

```text
current context used / 258K
```

要求：

- `/status` 与输入框下方环形指示器使用同一份 usage 数据；
- usage 代表当前 Session 在最新稳定 Context policy / active Projection 下的模型 working context 使用情况；
- 未提交的输入框草稿不纳入 usage；
- `/new`、`/resume`、`/compact`、Turn 完成以及其他会改变 History / Projection / Runtime Context 的稳定边界后必须刷新；
- active Turn 期间可以显示最近一次已知稳定值，但不得由 TUI 猜测；
- 当 usage 暂不可用时显示明确 unavailable 状态，不伪造为 0%。

`/status` 至少包含线性进度条以及数值，例如逻辑效果：

```text
Context  [██████████████──────────]  148K / 258K  (57%)
```

输入框下方现有状态信息区域增加一个终端可表达的**环形 / 圆环进度指示器**：

```text
activity | model | mode | permission | context: <ring> 57% | workdir
```

具体 Unicode glyph / 分段绘制可以根据终端能力实现，但必须满足：

- 可见上能表达占用比例，而不是只有纯数字；
- 仍显示百分比，便于精确读取；
- 不要求 TUI 引入图形库或 Canvas；
- 窄终端降级时优先保留百分比与环形状态，不允许影响输入和主要交互。

#### `/resume` Session Picker 页面

`/resume` 不使用普通 slash completion 候选菜单承载 Session 列表，而进入独立的 Session Picker view。

第一版交互固定为：

```text
/resume
   ↓
Session Picker
   ├─ 当前 project_key 下的 Session
   ├─ last_used_at 倒序
   ├─ 10 条 / 页
   ├─ ↑ / ↓ 选择当前页 Session
   ├─ ← / → 上一页 / 下一页
   ├─ Enter 恢复
   └─ Esc 取消并返回原聊天页
```

每条 Session 显示：

```text
<last_used_at>   <first user message preview>
```

规则：

- `last_used_at` 必须来自 UthCode 持久 Session 语义，不依赖文件系统 mtime 作为产品真值；
- 第一条消息特指该 Session 的**第一条 User Message**，不是 System Prompt、Assistant Message、Tool Result 或 Projection；
- 展示前转换为单行；
- 超过当前终端可用宽度时使用省略号；
- 排序越新越靠前；
- 一页固定 10 条，最后一页可不足 10 条；
- 左右翻页不得改变 Session；
- Enter 前不得切换当前 Session；
- 恢复成功后退出 Picker，TUI 重建并展示该 Session 的完整交互 Transcript；
- Picker 只持有候选列表、页码和选择索引等临时 UI 状态；Session discovery、排序所需 metadata、恢复与 reconstruction 仍由 Application 提供。

---

# 七、架构归属

| 能力 | 所属模块 | 状态所有者 | 调用方 | 依赖方向 | 原因 |
| --- | --- | --- | --- | --- | --- |
| Prompt Asset | package asset | Prompt Engineering | Application / Core prompt builder | application → core/resource | 开发者可编辑公共 Coding Prompt，不属于 Runtime State |
| Core Runtime Contract | `core` | Core | Context / Prompt builder | application → core | 约束 Mode、Todo/Plan、真实性等不可被人格文件绕过的运行语义 |
| Semantic Interaction value | `core` | Core 定义语义；Session Store 持久化 | Agent Loop / Application | application → core | Provider-independent，不能使用 SDK / UI DTO |
| Projection value | `core` | Context Coordinator 创建 | Context Compiler / Session Store | application → core | 它描述 History 的模型可见投影，不修改 Interaction |
| JSONL / result files | `integrations` | Session file store | Application | application → integrations | Core 不依赖文件系统实现 |
| Session History orchestration | `application` | AgentRun 对应 Session | AgentRun / Context Coordinator | interface → application | 连接 Core semantic facts 与文件存储 |
| Context Compiler | `core` 纯逻辑 + Application source assembly | 无持久状态 | request preparation | application → core | Provider-independent 决定 Context Snapshot |
| Context Compactor | `application` | 不持有长期状态 | manual `/compact` / auto budget trigger | application → core ProviderPort | 一次受控、无 Tool 的模型转换，不成为第二 Agent Loop |
| ToolResultRead | Integration Tool + Run-scoped composition | Session result store | Agent Loop | application composition → integrations/tool → core Tool contract | 真实当前调用方，且不扩大 ReadFile outside 权限 |
| Runtime Log | Integration storage | Session file store | Application / Eval projection | application → integrations | 丢失不改变 Session 语义 |
| Eval Context diagnostics | B01 Eval | Eval artifacts | Eval runner | eval → application public projection | 只测效果，不成为 Runtime 权威 |

### 7.1 不新增 Context Source Registry

当前 Context Compiler 输入固定为：

```text
PromptAssetSource
CoreRuntimeContractSource
RuntimeStateSource
InteractionHistorySource
EnvironmentFactsSource
```

这些是当前真实来源，不实现：

```text
ContextSource Protocol Registry
动态插件 Source
万能 supplemental_context
```

以后 Memory / Skill Instructions 出现真实能力时再增加强类型输入。

---

# 八、Prompt 与 Context 组装规范

## 8.1 Prompt Asset 切分

当前 `core/prompt.py` 中以下内容迁入公共 Coding Agent Prompt Asset：

```text
产品身份 / Coding Agent 定位
通用软件工程工作原则
代码质量与安全原则
沟通、结果真实性与输出风格原则
通用探索 / 实施习惯
```

以下内容必须继续由 Core 维护，不能放进开发者可编辑人格文件：

```text
BehaviorMode 的强制语义
PLAN 只读边界
TaskState / PlanState 的解释和完成约束
one-shot RuntimeFeedback 的语义
当前 Tool 能力由 ToolDefinition 决定的约束
不得伪造 Runtime 已执行行为的 Core contract
```

以下内容属于动态事实：

```text
当前 behavior mode
TaskState
PlanState
runtime feedback
workdir / platform / date
model / provider identity
active compact summary
```

## 8.2 最小 Package Layout

固定第一版只有一个公共 Prompt：

```text
src/uthcode/prompt_assets/
├─ __init__.py
└─ coding_agent.md
```

`__init__.py` 只负责稳定读取 package resource；不得创建 Registry、Profile、Overlay Manager 或用户目录加载器。

## 8.3 Cache-friendly 顺序

Context Snapshot 应保持以下相对顺序：

```text
稳定 Public Coding Prompt
        ↓
稳定 Core Runtime Contract
        ↓
动态 Projection Summary（如存在）
        ↓
动态 Runtime State
        ↓
动态 Environment Facts
        ↓
Projected Interaction Messages
```

要求：

- 同义内容不得因为 dict 无序、随机 ID、时间格式差异而无意义抖动；
- Runtime 动态内容尽量位于稳定文本之后；
- Context 正确性优先于缓存命中，不允许为了 Prefix Cache 保留过期事实；
- 不实现 Provider-specific cache-control。

---

# 九、Context Budget / Working Set

## 9.1 固定 Context Window

T09 不按模型声明、Provider 能力或模型名称动态决定 Context Window。

UthCode 第一版 Context Engine 固定使用：

```text
CONTEXT_WINDOW_TOKENS = 258_000
```

该值属于 UthCode Context policy，不属于 `ModelProfile`、Provider Integration 或用户 TOML 配置。

禁止：

```text
新增 context_window_tokens 配置字段
维护 model-name → context-window 表
从 Provider 名称或 SDK 元数据推断窗口
因模型切换而改变 Context Compiler 的总窗口
```

实际可用于输入的预算由固定 258K 总窗口扣除：

```text
当前模型 max_output_tokens 的输出预留
+ Context safety margin
```

模型服务若实际窗口与 UthCode 固定策略不一致，由正常 Provider 错误与 10.2 的单次 reactive overflow fallback 处理；不得因此在 Core 引入 Provider-specific Context Window 分支。

## 9.2 Budget 输入

第一版预算至少计算：

```text
Public Prompt
Core Contract
Projection Summary
Runtime State
Environment Facts
Projected History
当前 ToolDefinition schema 的估算成本
Output Reserve
Safety Margin
```

Context Compiler 可以接收 Tool System 提供的有序 ToolDefinition，只用于预算，不复制其内容到 Prompt。

## 9.3 Token 估算

第一版不新增 tokenizer 第三方依赖。

采用：

```text
Provider-independent deterministic conservative estimator
+
Provider 实际 Usage 作为 diagnostics 校准依据
```

具体常量属于内部 policy，不作为公共 API；必须用 B01 数据比较估算值与真实输入 token，避免“看起来合理”的固定比例长期失真。

## 9.4 Working Set

第一版规则：

**不可被普通 Budget 淘汰：**

```text
Public Prompt
Core Runtime Contract
当前 Runtime State
当前 Environment 必需事实
当前 User Message
当前未闭合 ToolCall / ToolResult 语义单元
active Projection Summary
```

**优先保留：**

```text
recent raw turns
当前任务相关的近期 Tool Result preview/ref
用户近期 Steering / AskUser answer / Plan Review
```

**可竞争剩余预算：**

```text
较旧 raw Interaction Records
旧 Tool Result working view
已经被 active Projection 完整覆盖的 raw history
```

一旦存在 active Projection，被其完整覆盖的 raw head 默认不再次进入模型 Context；它仍永久存在于 `history.jsonl`。

---

# 十、按需 Compaction

## 10.1 路线

用户已拍板采用：

```text
路线 B：按需模型 Compaction
```

禁止 T09 引入：

```text
ContextJobRepository
后台 ContextWorker
Progressive Summary Graph
长期后台 model loop
独立 Context scheduler
```

## 10.2 Trigger

第一版包含三种触发路径：

```text
manual:   /compact
auto:     下一次正常 Provider 请求的预测 Context 超过安全 Budget
reactive: Provider 明确以 context-overflow / prompt-too-long 语义拒绝当前请求后，允许一次受控 compact → recompile → retry
```

Reactive fallback 规则：

- 只在 Provider 明确表示输入上下文超限、且本次请求尚未产生可提交 Assistant / ToolCall 输出时触发；
- 同一逻辑请求最多执行一次 reactive compaction + retry，禁止无限重试；
- retry 继续使用同一 Session、同一真实 User Message 和相同 Runtime State，只更新 Context Projection / Snapshot；
- compaction 或 retry 再次失败时返回受控 Context / Provider failure；
- Provider Integration 只负责把自身可识别的超限错误归一成稳定错误事实，不拥有 Compaction policy。

## 10.3 Compactor 输入

Compactor 只接收：

```text
上一版 active summary（如有）
+
待 compact 的完整、稳定 semantic interaction head
```

明确不输入：

```text
Tool instances
Permission evaluator
UI state
Runtime Log
partial stream delta
未完成 Tool side effect
整个 AgentLoop
```

## 10.4 Compactor 输出

只接受一个完整文本 summary；必须：

- 保留用户仍有效约束；
- 保留当前任务目标、关键决策和已验证事实；
- 保留失败尝试中仍有后续价值的信息；
- 保留未来可能需要重新定位 Evidence 的 opaque ref；
- 区分事实与未验证推断；
- 不伪造 Tool 已执行结果；
- 不输出 ToolCall。

Compactor Provider Response 若包含 ToolCall、无有效文本、流不完整或请求失败：

```text
此次 Compaction 失败
→ 不 append ProjectionRecord
→ active Projection 保持旧值
```

## 10.5 recent raw tail

Compaction 必须保留一个按 Budget 计算的 recent raw tail，而不是把整个 Session 只剩 summary。

recent tail 起点必须落在完整 semantic unit / Turn 安全边界；不得在 ToolCall / ToolResult 配对中间切开。

---

# 十一、关键数据结构与状态

## 11.1 Session identity

Session identity 与 Run / Turn identity 分离。

```text
Session
├─ session_id                 # 跨进程稳定
├─ project_key                # 用于 /resume 默认发现范围
├─ created_workdir
├─ last_used_at               # 最近一次已完整提交的 Session 语义活动时间
├─ first_user_message         # 可由 History 稳定推导，用于 /resume 展示
├─ history store
├─ runtime log
├─ tool-result namespace
└─ active projection          # 由 history 最后合法 ProjectionRecord 推导

Process A
└─ AgentRun A / Turn 1..N

退出进程

Process B: /resume <same session>
└─ AgentRun B / Turn N+1...
```

规则：

- `session_id` 在 `/new` 时创建，在 `/resume` 时复用；
- `run_id` / Turn identity 只描述本次进程内执行生命周期，不与 `session_id` 绑定相等；
- `/compact` 不改变 `session_id`；
- `/resume` 只恢复到最后一个完整提交的安全边界，然后从新的 Turn 继续。

当前项目 / 工作目录关联规则第一版固定为：

```text
若 workdir 位于 Git 仓库：project_key = 规范化后的物理 Git repository root
否则：                  project_key = 规范化后的物理 launch workdir
```

`/resume` 默认只列出 `project_key` 与当前启动环境相同的 Session；不自动混入其他项目 Session。

用于 Session Picker 的展示投影必须满足：

- `last_used_at` 由最近一次已完整提交的 Session 语义活动推导或在同一 durable commit 中维护，不把目录/文件 mtime 当作权威；
- `first_user_message` 来自第一条 User Message，可在发现阶段形成 bounded preview，但原文仍以 Interaction History 为权威；
- Application 返回的 Session candidate 已按 `last_used_at DESC` 排序，Interface 不重新定义业务排序语义。

## 11.2 Persistent record envelope

```text
HistoryRecord
├─ schema_version
├─ record_id
├─ session_id
├─ sequence
├─ created_at
└─ record_type
   ├─ session_created
   ├─ interaction
   └─ projection
```

要求：

- 第一条 durable record 必须建立 `session_id`、`project_key`、创建 workdir 等不可变 Session metadata；
- `sequence` 在单 Session 内严格递增；
- `record_id` 永久稳定且不可复用；
- unknown `schema_version` fail closed；
- 不把 Provider SDK object、Exception、UI Widget、Future、Task 写入 record。

## 11.3 InteractionRecord

第一版强语义 kind 至少支持：

```text
user_message
assistant_message
tool_call
tool_result
ask_user_question
ask_user_answer
user_steering
plan_proposal
plan_review
```

内部 Todo 状态变化不作为 InteractionRecord；TaskState 继续由 Core Runtime 持有。

持久 assistant record 不保存 streaming delta，也不要求把 provider-native reasoning / native item 作为跨 Provider 语义权威。

## 11.4 ToolResult reference

大型结果 History payload：

```text
ToolResultContent
├─ preview
├─ content_ref
├─ content_size
└─ sha256
```

`content_ref` 是 opaque id，不是磁盘路径。

小结果可以直接 inline；大型结果完整正文只存在一次于 Session result file，History 保存稳定 metadata/ref。

## 11.5 ProjectionRecord

```text
CompactProjection
├─ projection_id
├─ previous_projection_id?
├─ covered_through_sequence
├─ tail_from_sequence
├─ summary
└─ trigger: manual | auto
```

active projection = 最后一个完整、合法的 CompactProjection。

## 11.6 ContextSnapshot

```text
ContextSnapshot
├─ system_prompt
├─ messages: tuple[Message, ...]
└─ diagnostics
```

ContextSnapshot：

```text
不持久化为 Session 权威状态
可由 History + Projection + Runtime State + Prompt Asset 重建
每次 Provider request 单独生成
```

## 11.7 ContextDiagnostics

至少包含：

```text
session_id
projection_id?
compact_count
policy_window_tokens
estimated_input_tokens
output_reserve_tokens
selected_interaction_count
omitted_interaction_count
raw_tail_start_sequence?
externalized_tool_results
externalized_bytes
context_pressure_ratio
compaction_trigger?
```

不得包含：

```text
API key
完整 Tool Result 正文
Provider native payload
未脱敏异常
```

## 11.8 Runtime State 跨 Turn

`TaskState / PlanState / BehaviorMode` 继续属于 Core Runtime，不属于 Projection。

跨 Turn 规则：

```text
prior Turn completed
→ active TaskState / PlanState 收口
→ 历史 Interaction 仍保留

prior Turn failed/cancelled
且存在 unfinished TaskState
→ 下一 Turn 保留该 TaskState
→ 若存在已批准 PlanState，同步保留为当前实施依据
→ 新 User Message 到来后模型通过既有 TodoWrite / Plan 语义 reconcile

one-shot RuntimeFeedback
→ 永不跨 Turn
```

Compaction 不读取上述状态来改写其权威值；Context Compiler 只把当前值重新注入本轮模型 Context。

---

# 十二、持久化与崩溃边界

## 12.1 Session layout

由 Integration 管理：

```text
<uthcode-user-home>/.uthcode/sessions/<session-id>/
├─ history.jsonl
├─ runtime.jsonl
└─ tool-results/
    └─ <opaque-result-id>.txt
```

测试必须注入临时 Session root；不得写真实用户目录。

## 12.2 JSONL append

每个 record：

```text
完整 JSON object
+
单个 newline
+
flush
```

语义记录提交需要 `fsync` 或等价可验证 durable append；不得依赖进程退出时缓冲区自动刷新。

读取时：

- 中间任何 malformed line：硬失败；
- 仅最后一个未完成 fragment 可被识别为未提交尾部并忽略；
- 不对 malformed 中间记录“尽量修复”；
- 不静默跳过 unknown semantic kind。

## 12.3 大 Tool Result 原子写入

```text
write temp
→ flush/fsync
→ atomic rename to final result file
→ 再产生可被 History / ToolResult 引用的 content_ref
```

若结果文件写入失败：

```text
不得返回“已保存完整结果”的 ref
不得把大结果完整塞回模型上下文作为兜底
返回受控 Tool error
```

本任务不做 orphan result GC；没有真实清理调用方前不得预建 Artifact GC。

---

# 十三、依赖与数据流

## 13.1 普通请求

```text
AgentRun / Core state
      │
      ├─ RuntimeStateSource
      │
SessionHistoryService
      ├─ active Projection
      └─ semantic Interaction tail
      │
Prompt Asset + Environment
      │
      ▼
Core ContextCompiler
      │
      ├─ Budget / Working Set
      └─ ContextDiagnostics
      │
      ▼
ContextSnapshot
      │
Application request preparation
      ├─ snapshot.system_prompt
      ├─ snapshot.messages
      └─ Tool System definitions
      │
      ▼
GenerationRequest
      │
      ▼
Provider Integration
```

## 13.2 Tool Result

```text
Integration Tool
  ↓ full ToolExecutionResult
Core Tool execution
  ↓
Application-supplied result materializer
  ├─ small → inline
  └─ large → SessionStore.persist_tool_result(full)
                     ↓
             preview/ref metadata
  ↓
ToolResultPart
  ↓
AgentLoop authoritative message commit
  ↓
semantic Interaction persistence
```

Materializer 只负责“完整内容如何被安全保存并形成 working view”，不得改变 Tool success/error 语义、Permission 决策或 ToolCall ID。

## 13.3 Compaction

```text
manual / auto trigger
      ↓
Application ContextCoordinator
      ↓
freeze compactable semantic history view
      ↓
one-shot tool-free Provider request
      ↓
validate complete summary
      ↓
append ProjectionRecord
      ↓
next ContextSnapshot reads new projection
```

取消沿现有 `CancellationToken` 传播；Compaction 不创建后台 task scheduler。

---

# 十四、目标目录树

> 只列本任务直接涉及的相关文件；具体测试可在拆包时按同一职责拆分，但不得改变下面的职责边界。

```text
src/uthcode/
├─ core/
│  ├─ [修改] prompt.py
│  ├─ [修改] provider.py
│  ├─ [修改] tool.py
│  ├─ [修改] agent.py
│  ├─ [新增] history.py
│  └─ [新增] context.py
├─ prompt_assets/
│  ├─ [新增] __init__.py
│  └─ [新增] coding_agent.md
├─ application/
│  ├─ [修改] __init__.py
│  ├─ [修改] bootstrap.py
│  ├─ [修改] generation.py
│  ├─ [修改] runs.py
│  ├─ [修改] tools.py
│  ├─ [新增] session_history.py
│  ├─ [新增] context.py
│  └─ commands/
│     ├─ [修改] models.py
│     └─ [修改] builtins.py
├─ integrations/
│  ├─ [新增] session_files.py
│  └─ tools/
│     ├─ [修改] factory.py
│     └─ [新增] tool_result_read.py
└─ interfaces/
   └─ tui/
      └─ [修改] app.py

[修改] pyproject.toml

[新增] tests/test_history_contract.py
[新增] tests/test_context_compiler.py
[新增] tests/test_session_files.py
[新增] tests/test_context_compaction.py
[新增] tests/test_tool_result_persistence.py
[修改] tests/test_system_prompt.py
[修改] tests/test_provider_contract.py
[修改] tests/test_tool_core.py
[修改] tests/test_agent_loop.py
[修改] tests/test_application_runs.py
[修改] tests/test_application_runtime.py
[修改] tests/test_command_dispatcher.py
[修改] tests/test_tui.py
[修改] tests/test_architecture_boundaries.py

[修改] eval/metrics.py
[修改] eval/execution.py
[修改] tests/eval/test_eval_reporting.py
[修改] tests/eval/test_eval_execution.py

[修改] docs/Tools.md
[修改] docs/user-manual/commands.md
[修改] docs/core-design/（命中 Context / Runtime 的现有文档）
[修改] docs/context/A01-AgentRuntime/AgentRuntime-Context.md
[修改] docs/context/A03-State/State-Context.md
```

任务包拆分阶段另行按规则维护：

```text
docs/OutstandingDebtList.md
docs/Context-Index.md
```

不得在本任务书生成阶段直接修改它们。

---

# 十五、文件级任务清单

| 文件路径 | 操作 | 文件职责 | 核心类型 / 函数 | 输入 | 输出 | 允许依赖 | 禁止依赖 | 对应测试 | 验收条件 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `src/uthcode/prompt_assets/coding_agent.md` | 新增 | 默认公共 Coding Agent Prompt | Markdown asset | 无 | 稳定 prompt 文本 | 无 | Runtime facts、Tool schema、Provider 特有内容 | `test_system_prompt.py` | 可由 package resource 稳定读取 |
| `src/uthcode/prompt_assets/__init__.py` | 新增 | 读取唯一公共 Prompt Asset | loader | package resource | str | stdlib | Registry / 用户目录 | `test_system_prompt.py` | wheel/source 均可读取 |
| `src/uthcode/core/prompt.py` | 修改 | 渲染 Core Contract、Runtime/Environment/Projection 区段 | prompt builder | asset + structured sources | system prompt | core models | filesystem、SDK、UI | `test_system_prompt.py` | 可编辑 asset 不可绕过 runtime contract |
| `src/uthcode/core/history.py` | 新增 | 定义 semantic interaction / projection 值 | HistoryRecord payload models | Core semantic facts | immutable JSON-safe values | stdlib/core models | filesystem、SDK | `test_history_contract.py` | 强类型、严格版本/字段校验 |
| `src/uthcode/core/context.py` | 新增 | Provider-independent Context Compiler、Budget、Snapshot、diagnostics | ContextSnapshot / ContextDiagnostics | typed sources + budget + tool definitions | snapshot | core | Provider SDK、storage | `test_context_compiler.py` | 相同输入确定性输出，预算硬边界成立 |
| `src/uthcode/core/provider.py` | 修改 | 允许 ToolResult working view 携带 opaque full-content metadata | ToolResultPart | call_id + preview/ref | Provider-independent part | stdlib | storage path/SDK | `test_provider_contract.py` | wire adapter 仍只发送模型需要正文 |
| `src/uthcode/core/tool.py` | 修改 | 删除永久 10k data-loss 截断；向 AgentLoop 提供完整执行结果 | ToolExecutor | prepared call | full ToolExecutionResult | core | storage | `test_tool_core.py` | ToolExecutor 本身不再丢失正文 |
| `src/uthcode/core/agent.py` | 修改 | 通过 result materializer + semantic commit sink 接入 History；调整跨 Turn Task/Plan 规则 | AgentLoop / RunState.new_turn | full tool result / semantic commit | authoritative RunState | core callbacks | filesystem | `test_agent_loop.py` | 唯一 RunState writer 不变；ToolCall ID 闭合不变 |
| `src/uthcode/application/session_history.py` | 新增 | Session 生命周期、项目范围发现、语义历史提交、Projection view 与 resume reconstruction | SessionHistoryService | Core semantic facts + launch workdir | session catalog view / history view / active projection | core + storage port | UI / SDK | `test_session_files.py` | Session identity 独立于 Run；同 project_key 可发现并恢复 |
| `src/uthcode/application/context.py` | 新增 | 组装 sources、manual/auto compaction、working budget | ContextCoordinator / Compactor | Run state + history + model profile | ContextSnapshot / ProjectionRecord | core + ProviderPort | UI / SDK type | `test_context_compaction.py` | 一次 compaction 无 tool/no loop；失败不切 projection |
| `src/uthcode/application/generation.py` | 修改 | 正式 request preparation 改由 ContextCoordinator 产生 snapshot | UthCodeApplication | run/context sources | GenerationRequest | core/application | SDK | runtime tests | 不再直接发送完整 RunState.messages |
| `src/uthcode/application/runs.py` | 修改 | AgentRun 绑定 Session History / Context / result namespace；公开 idle compact | AgentRun | user input / compact request | TurnHandle / compact result | application/core | UI | run tests | `/new` 前后 Session 隔离；active Turn 不接受 manual compact |
| `src/uthcode/application/tools.py` | 修改 | 为每个 Run 组合 base tools + ToolResultRead，并注入 result materializer | ApplicationToolService | run session access | run-local Tool runtime | core Tool | hidden global/session path | tool tests | 不建设动态 Tool registry |
| `src/uthcode/application/bootstrap.py` | 修改 | 组合 JSONL Session store / Context services | create_application | config/home/workdir | application | integrations at composition root | Core 反向依赖 | runtime tests | 测试可注入 temp root |
| `src/uthcode/application/commands/builtins.py` | 修改 | 实现 `/compact`、`/new`、`/resume` | handlers | CommandContext | structured command result | application | Core direct import beyond existing values | command tests | 三个命令均不再 NOT_IMPLEMENTED |
| `src/uthcode/application/commands/models.py` | 修改 | 表达 compact/new/resume 的 UI-neutral result 与 Session candidate | result values | command handler | interface action | application | Textual | command tests | TUI 只投影，不定义 Session 业务 |
| `src/uthcode/integrations/session_files.py` | 新增 | append-only history/runtime JSONL 与 result file 原子写/读 | JsonlSessionFiles | Session records / full content | persisted bytes/records | stdlib filesystem | core execution policy | `test_session_files.py` | durable append、尾部半写规则、跨 Session ref 隔离 |
| `src/uthcode/integrations/tools/tool_result_read.py` | 新增 | 读取当前 Session persisted tool result | ToolResultRead | opaque ref + range | ToolExecutionResult | core Tool + session result accessor | arbitrary path | `test_tool_result_persistence.py` | 只读当前 Session ref |
| `src/uthcode/integrations/tools/factory.py` | 修改 | 保持 base Tool factory；支持 run-local result reader 组合所需入口 | factory helper | workdir/session accessor | Tool values | integrations/core | UI | tool tests | 默认普通工具顺序不无意义改变 |
| `src/uthcode/interfaces/tui/app.py` | 修改 | 处理 compact/new/resume 结构化 command result与当前项目 Session picker | TUI handler | Application command result | display/run swap / picker | application only | core/integrations | `test_tui.py` | Interface 不拥有 History/Compaction/Session discovery 逻辑 |
| `eval/metrics.py` / `eval/execution.py` | 修改 | 接收公开 Context diagnostics，形成效果指标 | diagnostics | attempts | Context dimension | application public projections | core private state | eval tests | 未提供事实时仍为 NA，不猜测 |
| 文档 | 修改 | 同步命令、Tool、配置、Context 当前事实 | current code facts | implementation | docs | — | 规划冒充事实 | doc guards | 与 src/tests 一致 |

---

# 十六、对现有能力的影响

| 现有能力 / 文件 | 当前状态 | 本次如何使用 | 是否修改 | 原因 | 回归测试 |
| --- | --- | --- | --- | --- | --- |
| Provider Integration | 三种真实 Provider 已统一 | 继续只接收 `GenerationRequest` | 修改映射测试为主 | Context Compiler 不得出现 provider 分支 | Provider integration tests |
| ToolDefinition | Tool System 唯一权威 | 继续作为 request tools；同时用于预算估算 | 保持权威 | Prompt 不复制 Tool schema | Tool/provider tests |
| ToolExecutor | FIFO + 参数校验 + 当前 10k truncate | 保留 FIFO/错误语义，移除数据丢失 truncation | 修改 | 大结果改由 Session externalization | Tool core tests |
| AgentLoop | 单一显式 Runtime | 继续唯一推进 RunState | 修改 | 接入 Context request 与 semantic commit | AgentLoop tests |
| T06 Pause/Resume | 同进程 active Turn | 继续复用，不持久 waiter/continuation | 保持产品边界 | T09 不做 active crash recovery | interaction/run tests |
| Permission | 三层策略 | `ToolResultRead` 作为内部 Session read-only Tool，不映射成 workspace outside file read | 只扩 Tool 行为 | 防止绕过/重复 ASK | Permission + tool tests |
| T08 Task/Plan | Core Runtime State | 作为强类型 Runtime Context Source，按终态决定跨 Turn active 状态 | 修改 narrow lifecycle | 回补跨 Turn/Compaction 欠账 | T08 regression tests |
| Slash Registry | 单一 Registry | 将 `/compact`、`/new`、`/resume` 从占位改成真实 handler | 修改 | T02 欠账触发 | command/TUI tests |
| `/resume` | 预留未实现 | 恢复当前项目既有 Session 到最后稳定提交边界，并从新的 Turn 继续 | 修改 | Session persistence 已在 T09 成立；不要求 active Runtime recovery | resume/session/TUI tests |
| B01 | 私有 Eval v0 | 接收 Context diagnostics，增加可比较指标/case | 修改 | 测量 Context 改进效果 | eval tests |

---

# 十七、第三方依赖

**无新增第三方运行时依赖。**

继续使用：

```text
Python stdlib filesystem / json / hashlib / importlib.resources
现有 Provider SDK（仅 Integration 内）
现有 tomlkit / jsonschema / Textual
```

不得为了 T09 引入：

```text
SQLite ORM
LangGraph saver
向量数据库
Tokenizer 大依赖
后台任务框架
工作流框架
```

---

# 十八、实施任务拆分

> 后续任务包拆分 Agent 可以将下列 Task 组合给长期 Worker，但 Spec / Tasks / Checklist 必须保持相同编号与顺序。

## Task 1 — Prompt Asset 与 Core Runtime Contract 分离

**任务目标**  
把开发者可编辑公共 Coding Prompt 从 `core/prompt.py` 移至 package asset，同时保留不可编辑 Runtime Contract 和动态 facts。

**前置条件**  
T03 当前 System Prompt tests 通过。

**涉及文件**  
`prompt_assets/*`、`core/prompt.py`、`pyproject.toml`、`tests/test_system_prompt.py`。

**实现要求**

- 只有一套公共 Coding Prompt；
- 使用 `importlib.resources` 或等价标准库 package resource；
- ToolDefinition 不复制到 Markdown；
- PLAN / Todo / Plan / completion runtime contract 不放入可编辑 asset；
- stable prefix 顺序确定。

**完成结果**  
相同资产与 facts 产生确定性 System Prompt；二开开发者可直接修改 package Markdown。

**测试**  
asset 缺失/空文本、确定性顺序、runtime contract 不可由 asset 删除、wheel/package data。

**明确不做**  
用户 `.uthcode` Prompt、模型 Overlay、Prompt Registry。

**提交边界**  
不得同时改 Context History。

---

## Task 2 — Semantic History / Projection Core Contract

**任务目标**  
建立 provider-independent 的 Interaction / CompactProjection 强类型模型。

**涉及文件**  
`core/history.py`、相关序列化测试。

**实现要求**

- strict schema/version；
- 明确 semantic kinds；
- 不存 delta / UI event / SDK native object；
- Projection 指向 history position，不复制/删除旧 records；
- compact boundary 不允许切断 ToolCall/ToolResult semantic unit。

**完成结果**  
Core 能表达“完整交互事实”和“模型视图投影”两类不同事实。

**测试**  
round-trip、unknown kind/version、非法 sequence/ref、projection boundary。

**明确不做**  
通用 event sourcing framework、Projection DSL。

**提交边界**  
只定义领域值，不接文件系统。

---

## Task 3 — JSONL Session Files 与 Runtime Log

**任务目标**  
实现每 Session append-only history/runtime storage 与 tool-results namespace。

**涉及文件**  
`integrations/session_files.py`、`application/session_history.py`、storage tests。

**实现要求**

- `session_id` 独立于 run_id / Turn identity；
- durable append；
- final partial tail 容错，中间损坏 hard fail；
- runtime log 与 semantic history 分离；
- full Tool Result 原子写；
- opaque ref 不暴露路径；
- Test root 可注入；
- Session 首个 durable record 固化 `project_key` / `created_workdir`；
- 可稳定得到 `last_used_at` 与第一条 User Message preview，供 `/resume` Session Picker 使用；
- `last_used_at` 不以 filesystem mtime 作为产品真值；
- Application 可按当前 `project_key` 扫描并重建可恢复 Session 列表，并按 `last_used_at DESC` 返回，不引入 Session catalog DB。

**完成结果**  
Session 原始语义历史可在进程退出后保留，并能在同项目下被发现和重建；Runtime Log 丢失不影响语义重建。

**测试**  
并列 Session 隔离、project_key 过滤、`last_used_at` 排序、第一条 User Message preview、append 顺序、partial tail、malformed middle、atomic result write、跨 Session ref、同 Session 跨进程 reconstruction。

**明确不做**  
SQLite、Session catalog DB、GC、active / paused Turn recovery。

**提交边界**  
先完成可恢复 Session 的持久层与 Application reconstruction，不在本 Task 接 TUI picker。

---

## Task 4 — 大 Tool Result 外置与 ToolResultRead

**任务目标**  
消除 10k 字符永久数据丢失，将大结果完整保存并提供当前 Session 内按需重读。

**涉及文件**  
`core/provider.py`、`core/tool.py`、`core/agent.py`、`application/tools.py`、`integrations/tools/tool_result_read.py`、tool tests。

**实现要求**

- ToolExecutor 不再永久截断原始 `ToolExecutionResult`；
- Application result materializer 决定 inline / externalize；
- 大结果完整写成功后才生成 ref；
- working view 包含 deterministic preview + opaque ref + size；
- `ToolResultRead` 按 ref + range 读取；
- 当前 Session 外 ref hard fail；
- ToolResultRead 规划模式可见且为 READ_ONLY；
- 不经过普通 outside-path Permission ASK；其能力范围由 opaque ref resolver 固定；
- ToolCall ID / is_error / FIFO 不变。

**完成结果**  
模型不因单条大输出挤爆 Context，也不会失去完整结果。

**测试**  
阈值上下、写入失败、hash/ref、range read、伪造 ref、跨 Session、PLAN view、原 Tool error。

**明确不做**  
通用 Artifact Store、任意 Session 文件读取、二进制媒体仓库。

**提交边界**  
先证明完整结果与 working view 分离，再接 Context Compiler。

---

## Task 5 — Context Compiler、Budget 与 Working Set

**任务目标**  
建立纯、Provider-independent 的 Context Snapshot 编译链。

**涉及文件**  
`core/context.py`、Context policy constants、context tests。

**实现要求**

- Context Engine 总窗口固定为 `258_000` tokens，不进入 ModelProfile / Provider / 用户配置；
- Context Compiler 接受 5 类固定 source；
- 使用现有 `Message` 作为模型 working message，不创建万能 ContextItem；
- ToolDefinition 只用于预算估算；
- 关键内容保底 + recent raw tail + 可淘汰旧 history；
- ContextSnapshot 不持久化；
- diagnostics JSON-safe / display-safe；
- estimator 确定且保守。

**完成结果**  
相同 sources 可重建相同 ContextSnapshot，并在 hard budget 内工作。

**测试**  
边界正好/超限、固定 258K window、recent tail、protected semantic unit、stable ordering、diagnostics。

**明确不做**  
provider-specific tokenizer/cache-control、Memory/Skill Source、通用 Source Registry。

**提交边界**  
还不发起 compaction model call。

---

## Task 6 — 按需 Compactor 与 Projection Commit

**任务目标**  
实现路线 B 的 manual / auto / reactive one-shot model compaction。

**涉及文件**  
`application/context.py`、`generation.py`、`runs.py`、compaction tests。

**实现要求**

- tool-free、single Provider request；
- 不进入 AgentLoop，不维护独立 conversation；
- manual idle-only；
- auto 只发生在普通 Provider request 组装前的安全边界；
- recent raw tail 由 Budget 决定；
- 成功 summary 后 append ProjectionRecord；
- failure/cancel/invalid output 不改变 old projection；
- repeated compaction 使用 prior summary + new head；
- Provider 明确 context-overflow 时允许同一逻辑请求一次 reactive compact → recompile → retry；
- reactive retry 不创建新 User Message、不切 Session、不循环重试；
- compactor Usage 进入 runtime diagnostics，但不伪装成主 Agent Usage。

**完成结果**  
长 Session 能在不改原 History 的情况下缩小 working context。

**测试**  
manual、auto、reactive overflow one-shot retry、second overflow hard fail、failure、cancel、ToolCall response rejection、double compact、projection rebuild。

**明确不做**  
后台 Context Worker、Structured Notes、Provider-specific retry policy。

**提交边界**  
Projection 能独立验证后再接命令/TUI。

---

## Task 7 — 跨 Turn Runtime State 与正式 Request Composition

**任务目标**  
让 AgentLoop 的每次 request 使用 ContextSnapshot，并回补 Task/Plan 跨 Turn/Compaction 关系。

**涉及文件**  
`core/agent.py`、`application/generation.py`、`application/runs.py`、AgentLoop/Application tests。

**实现要求**

- 不再把 `RunState.messages` 无条件全量发给 Provider；
- RunState 仍是当前 Runtime authority；
- completed Turn 收口 active Task/Plan；
- failed/cancelled + unfinished Task 延续到下一 Turn；
- one-shot feedback reset；
- Compaction 只能影响 History Projection；
- Semantic History 在整个 Session 继续追加。

**完成结果**  
“完整 Session History”“当前 Context Snapshot”“Runtime State”三者职责分离。

**测试**  
多 Turn、completed reset、cancelled continuation、approved plan、compaction before/after、Steering/Pause 回归。

**明确不做**  
Runtime State 跨进程 checkpoint。

**提交边界**  
保持单 AgentLoop / single RunState writer。

---

## Task 8 — `/compact`、`/new`、`/resume` 与 TUI 产品闭环

**任务目标**  
补齐三个当前已预留命令的真实 Session / Context 行为。

**涉及文件**  
`application/commands/models.py`、`builtins.py`、`application/session_history.py`、`interfaces/tui/app.py`、picker / command / TUI tests。

**实现要求**

- `/compact` → 当前 idle Session manual compact；
- active Turn 调用 `/compact` 返回明确 unavailable，不偷偷暂停/截断 active turn；
- `/new` → 创建全新 Session identity，并建立新的 in-memory AgentRun；旧 Session 文件保留；
- `/resume` → 默认只发现当前 `project_key` 下的已持久 Session；
- `/resume` 打开独立 Session Picker view，不把 Session 列表塞进普通 completion/candidate 菜单；
- Application 返回的候选 Session 已按 `last_used_at DESC` 排序；
- Session Picker 每页固定 10 条，最后一页允许不足 10 条；
- 每条显示 `last_used_at + 第一条 User Message 单行 preview`，过长以省略号截断；
- ↑ / ↓ 只改变当前页选中 Session；← / → 翻页；Enter 确认恢复；Esc 取消并回原聊天页；
- Enter 前不得修改当前 Session；翻页和取消均不得产生 Session 状态变化；
- `/resume` 选择 Session 后恢复原 `session_id`、完整 Interaction History、最新合法 Projection 和 Tool Result namespace，并建立新的 in-memory AgentRun；
- `/resume` 从新的 Turn 继续，不恢复旧 active / paused Turn、Pending Tool、Permission、AskUser 或 Provider continuation；
- 当前项目无 Session 时不得自动展示其他项目 Session；
- TUI 用 Application 返回的候选数据做 picker，Session discovery/filter/sort/reconstruction 仍归 Application；
- `/status` 显示 Context 使用线性进度条、used/258K 与百分比；
- 输入框下方现有 status 区显示终端兼容的环形 Context 使用指示器 + 百分比；
- `/status` 与环形指示器必须消费同一 Application Context usage projection，TUI 不自行重新估算 token；
- `/clear` 继续只清当前界面 Transcript，不等价于 `/new` 或 `/compact`；
- Interface 只消费结构化 Application result。

**完成结果**  
用户能主动压缩当前 Session、显式创建新 Session，也能在重新启动 UthCode 后恢复当前项目已有 Session 并继续新的 Turn。

**测试**  
help/completion、manual compact UI、active rejection、new isolation、旧 session files intact、current-project resume filter、Session Picker `last_used_at DESC`、每页 10 条、上下选择、左右翻页、Enter 恢复、Esc 取消、首条 User Message preview 省略、resume same session id、resume projection、resume tool-result ref、no-match、`/status` Context 进度条、输入区环形 indicator 与 `/status` 同口径、`/clear` 语义不变。

**明确不做**  
跨项目全局 Session Browser、Fork UI、active Runtime crash recovery。

**提交边界**  
不把 TUI 做成 Session owner。

---

## Task 9 — B01 Context Diagnostics 与 Before/After Eval

**任务目标**  
让 B01 能测量 T09 是否真正改善长上下文，而不是只验证代码运行。

**涉及文件**  
`eval/metrics.py`、`eval/execution.py`、eval tests 与少量代表性 task fixture。

**实现要求**

新增/接入至少以下效果观察：

```text
compact_count
estimated / actual provider input tokens
selected / omitted interaction counts
required evidence retention / rediscovery
repeated file/tool exploration
externalized result count / bytes
ToolResultRead hit count
long-task correctness / stability
```

在实施 Context 改进前保留 pre-context baseline；改进后按同模型、同任务、同运行参数进行 compare。

**完成结果**  
报告能明确显示 Context 机制的收益/退化，不产生单一综合“通过分”。

**测试**  
确定性 diagnostics 用 pytest；概率性效果只进 Eval compare。

**明确不做**  
CI quality gate、LLM Judge、公共 benchmark、leaderboard。

**提交边界**  
不因某次模型随机失败让 pytest 红灯。

---

## Task 10 — [接入主流程] 正式 Composition 收口

**任务目标**  
从 Bootstrap → AgentRun → Context → AgentLoop → Provider 打通唯一正式路径。

**实现要求**

- 所有正式 Agent Turn 都经 Context Compiler；
- ToolResult externalization 进入正式 Tool path；
- `/compact` / `/new` / `/resume` 走 Application；
- 删除旧 `RunState.messages → GenerationRequest` 直通路径；
- 删除 Core Tool 10k data-loss truncate；
- 低层 `start_generation()` 仍可用于无 Session 的单次低层 generation，但不得冒充 Agent Context path。

**测试**  
Headless Fake Provider 完整长历史 + Tool + compact + 进程重建式 resume + final。

**明确不做**  
第二 Agent Runtime。

**提交边界**  
正式路径必须唯一。

---

## Task 11 — [端到端验证] Context / Compaction / Evidence

**任务目标**  
从真实 Application 入口验证完整产品行为。

**场景至少包含：**

1. 多 Turn Session 历史持续增长；
2. `/new` 后旧 Session 不受影响；
3. 退出并重新创建 Application 后，`/resume` 只发现当前项目 Session，并进入独立 Session Picker；
4. Session Picker 按 last-used 倒序、每页 10 条、上下选择、左右翻页，条目显示上次使用时间与第一条 User Message 摘要；
5. 选择 Session 后恢复原 session_id / history / projection 并继续新的 Turn；
6. `/status` 与输入框下方环形 indicator 显示同一 Context 使用比例；
7. 大 Tool Result 完整落盘，模型只看到 preview/ref；
8. 模型调用 ToolResultRead 重新获得旧 Evidence；
9. manual `/compact` 后原 history line 数只增不减；
10. auto compact 在预算压力下触发；
11. 二次 compact 不覆盖第一次 projection；
12. current Task/Plan 不被 summary 替代；
13. compact provider failure 后主 Session projection 保持；
14. B01 diagnostics 可比较。

**验证**  
定向测试 + 全量 pytest + compileall + pip check + architecture boundaries + UTF-8 + `git diff --check`。

---

## Task 12 — [遗留负担清理] 单历史 / 单 Context Path 收口

**任务目标**  
清除被 T09 正式机制替代的旧职责和误导文档。

**必须确认不存在：**

```text
10k Tool Result 永久截断
Interface 自建 history
Context Compiler 写 TaskState/PlanState
AgentEvent 全量持久化
Prompt 中手写 ToolDefinition
三 Provider 三套 Prompt
Context Worker / scheduler / second loop
fake user message 承载 compact summary
mutable history rewrite
SQLite checkpoint
无调用方 Artifact Repository / Context Registry
```

**文档**  
按 `docs/README.md` 维护映射同步 Tool、命令、配置、Core design、A01/A03 current context。

---

# 十九、测试矩阵

| 场景 | 测试文件 | 关键断言 |
| --- | --- | --- |
| Prompt asset 读取 | `tests/test_system_prompt.py` | package asset 稳定加载，Core contract 仍存在 |
| Prompt stable prefix | `tests/test_system_prompt.py` | 仅动态 facts 改变时稳定前段字节不变 |
| History record | `tests/test_history_contract.py` | strict schema、round-trip、unknown fail |
| JSONL append | `tests/test_session_files.py` | monotonic seq、durable append、partial last line |
| JSONL corruption | `tests/test_session_files.py` | middle corruption hard fail |
| Session isolation | `tests/test_session_files.py` / run tests | 不同 session_id 不共享 history/ref；run_id 可变化但 resume 后 session_id 不变 |
| 大 Tool Result | `tests/test_tool_result_persistence.py` | full file hash == 原始 content，working view bounded |
| ToolResultRead | 同上 | only current session opaque ref；range 正确 |
| Tool error | Tool tests | 原 `is_error` / call_id / FIFO 不退化 |
| Budget | `tests/test_context_compiler.py` | snapshot <= safe input budget |
| Protected source | 同上 | runtime state / current user / active projection 不被普通淘汰 |
| Working Set | 同上 | old covered raw history 不重复进入 snapshot |
| Manual compact | `tests/test_context_compaction.py` | append projection，interaction records 不变 |
| Compact failure | 同上 | old projection 保持，no partial record |
| Repeat compact | 同上 | previous projection link + new summary；old record 保留 |
| Auto compact | context/application tests | 超预算前触发；同 Session / Turn 继续 |
| Task/Plan completed | `tests/test_agent_loop.py` | next Turn active state 收口但 history 保留 |
| Task/Plan interrupted | 同上 | unfinished state 延续；one-shot feedback 不延续 |
| Pause/Steering | existing T06/T08 tests | 不重放 Tool、不破坏 active turn |
| `/compact` | `tests/test_command_dispatcher.py` | idle success / active unavailable |
| `/new` | command/TUI tests | new Session id；旧文件保持 |
| `/resume` | command/TUI/session tests | 默认仅当前 project_key；恢复同 session_id / history / projection / result refs；从新 Turn 继续，不恢复旧 active Turn |
| Resume Session Picker 排序 | TUI/session tests | `last_used_at DESC`；越近越靠前；不使用 filesystem mtime 作为产品真值 |
| Resume Session Picker 展示 | TUI tests | 每条含上次使用时间 + 第一条 User Message；超宽省略；一页固定 10 条 |
| Resume Session Picker 键盘 | TUI tests | ↑/↓ 选择；←/→ 翻页；Enter 恢复；Esc 无状态变化返回 |
| Context `/status` | command/TUI tests | 线性进度条、used/258K、百分比来自 Application usage |
| Context ring indicator | TUI tests | 输入框下方显示环形占用状态 + 百分比，与 `/status` 使用同一 ratio |
| Provider boundary | provider integration tests | Core Context 无 provider-name branch；SDK type 不越界 |
| Eval | `tests/eval/*` | Context facts 可用；概率性质量不成为 pytest 门禁 |
| Architecture | `tests/test_architecture_boundaries.py` | `interfaces → application → core`，Integration SDK 截止 |

---

# 二十、删除与清理

本任务导致以下现有内容失效，实施时必须删除或替换：

1. `core/tool.py` 中“所有 Tool Result 最终统一截到 10,000 chars”的永久数据丢失语义；
2. `application/generation.py` 中 Agent Turn 直接把全部 `RunState.messages` 作为 Provider working context 的唯一路径；
3. `core/prompt.py` 中属于开发者可编辑公共 Coding Agent Prompt 的硬编码长文本；
4. `/compact`、`/new`、`/resume` 的 NOT_IMPLEMENTED 占位状态；
5. 与上述旧行为绑定的测试断言和误导文档。

不得借本任务清理其他无关历史代码。

---

# 二十一、验收标准

1. `main` 基线上的所有正式 Agent Turn 经唯一 Context Compiler 产生 `ContextSnapshot`，不再无条件重传完整 `RunState.messages`。
2. Session identity 独立于 Run / Turn；同一 Session 跨 Turn、跨进程 resume 持续追加语义历史，只有 `/new` 创建新 Session。
3. `history.jsonl` append-only；Compaction 前后既有 InteractionRecord 字节不被覆盖、删除或重写。
4. `ProjectionRecord` 只描述模型可见投影；连续两次 Compaction 形成两条不可变 ProjectionRecord，active view 由最后合法记录推导。
5. `runtime.jsonl` 删除后仍能从 semantic history 得到相同逻辑 Session history；runtime log 不被 Context Compiler 当权威输入。
6. Stream delta、ToolProgress、UsageUpdated、UI lifecycle 不进入 semantic history。
7. 当前 Tool 10k 字符永久截断被移除；大型 Tool Result 完整原文 hash 与持久文件一致。
8. 大结果模型可见 ToolResult 是 bounded preview/ref，不把完整原文重新灌入 Context。
9. `ToolResultRead` 只读取当前 Session 的 opaque result ref；伪造路径、跨 Session ref、history/runtime 文件访问全部 fail closed。
10. ToolResult externalization 不改变 ToolCall ID、FIFO、Permission、is_error、取消和普通失败语义。
11. 公共 Coding Prompt 位于 package asset；Core Runtime Contract、Runtime State、Environment Facts 不被开发者 Prompt 文件拥有。
12. ToolDefinition 仍由 Tool System 唯一维护，Prompt Asset 和 Core Contract 均不存在 schema 人工副本。
13. Context Compiler 中不存在 Provider 名称分支；三类 Integration 继续只负责各自 wire 映射。
14. Context Engine 固定使用 258,000-token 总窗口；该值不进入 ModelProfile / Provider / 用户配置，也不靠 model name 猜测或切换。
15. Context Snapshot 对相同输入确定；关键 source 不被普通 Working Set 淘汰，并为输出保留空间。
16. `/compact` 在 idle Session 可手动调用；active Turn 不通过暗中暂停来执行 manual compact。
17. auto compaction 只在安全 request boundary 按需调用 tool-free model transform；Provider 明确 context-overflow 时同一逻辑请求最多允许一次 reactive compact → recompile → retry；不存在后台 Context Worker、scheduler 或第二 AgentLoop。
18. Compactor 失败、取消、返回 ToolCall 或非法结果时不改变 active Projection。
19. `/new` 创建新 Session 并保持旧 Session 持久文件不变；TUI 不拥有 Session 业务状态。
20. `/resume` 已形成当前项目范围的正式产品闭环：恢复原 Session 的完整 Interaction History、最新合法 Projection 与 Tool Result 引用，并从新的 Turn 继续；不得把它扩张或描述为旧 active / paused Turn 的 crash recovery。
20.1 `/resume` 必须进入独立 Session Picker 页面；候选仅来自当前 `project_key`，按上次使用时间倒序，每页固定 10 条。
20.2 Session Picker 每条必须显示上次使用时间与第一条 User Message 单行摘要；过长以省略号处理；↑/↓ 选择、←/→ 翻页、Enter 恢复、Esc 取消。
20.3 `/status` 必须展示 Context 线性进度条、used/258K 和百分比；输入框下方状态区必须展示环形 Context 使用指示器与百分比；两者使用同一 Application usage 数据源，TUI 不自行估算。
21. TaskState / PlanState 保持 Core Runtime authority；Compaction 不修改它们，不用自然语言 summary 替代其结构化真值。
22. completed Turn 收口 active Task/Plan；failed/cancelled 且存在 unfinished Task 时可在同 Session 下一 Turn 延续，并由模型基于新用户输入重新 reconcile。
23. B01 能报告 Context diagnostics，并可用同实验指纹做 pre-context / post-context compare；概率性 Eval 结果不是 pytest 式硬门禁。
24. Headless 路径可以不依赖 Textual 完成：多 Turn → 大 Tool Result → ToolResultRead → manual/auto compact → final。
25. `tests/test_architecture_boundaries.py` 证明 Core 不依赖 filesystem storage、SDK 或 Interface；Interface 不直连 Core/Integration Session Store。
26. 全量离线 pytest、`compileall`、`pip check`、架构测试、UTF-8 guard、Markdown fence 检查和 `git diff --check` 均有精确结果记录。
27. 文档与当前 `src/ + tests/` 一致；只把当前项目范围的稳定 Session `/resume` 写成已实现，不把 active Runtime crash recovery、Memory、后台 Notes、Provider-specific cache 等后置能力冒充为已实现。
28. 无旧项目 Runtime 依赖、无 LangGraph/LangChain、无 SQLite checkpoint、无 Context Source Registry、无无调用方未来抽象。

---

# 二十二、编码停止条件

编码代理遇到以下任一情况必须停止相关范围并写入 Feedback，交由用户决定：

- 实际源码与本任务书关键假设不一致；
- 与 AGENTS.md、WorkPackageRules 或用户本轮拍板冲突；
- 必须改变 `interfaces → application → core` 依赖方向才能继续；
- 需要引入新的系统级 Registry / Scheduler / Workflow / 第二 Agent Runtime；
- JSONL 无法在当前需求下满足正确性且必须改用数据库；
- ToolResultRead 必须扩大为任意 Session 文件读取或绕过既有安全边界才能成立；
- Provider 协议迫使 Core 按 Provider 名称维护不同 Context 体系；
- 为实现 `/resume` 必须吞并 Pending Tool / Permission / AskUser / Coroutine crash recovery；
- Compaction 必须恢复或重放可能已经产生副作用的 Tool；
- 实际文件修改范围明显扩展到 Memory、Skill、MCP、Subagent、Sandbox 等独立能力；
- 需要为旧 Re:UthCode 行为增加长期兼容层；
- 已冻结的 Prompt / Session / Projection / Context Budget / Compaction 设计发生实质冲突。

以下情况不得停下来等待用户，应在当前任务范围内自行修复：

```text
普通编译错误
类型错误
单元测试失败
lint / format
fixture 问题
私有函数拆分
局部错误处理
低成本内部实现调整
```

---

# 二十三、明确不做 / Out of Scope

T09 明确不包含：

```text
完整 Persistent Runtime checkpoint
active / paused Turn 跨进程恢复
Pending Tool / Permission / AskUser 跨进程恢复
Tool side effect replay
跨项目全局 Session Browser
Fork / Worktree 产品能力
Memory / Dream
Skill Instructions / MCP Context Source
Subagent / Multi-Agent
后台 Context Agent / Context Worker
后台 Structured Notes
Provider-specific Prompt Overlay
用户 .uthcode Prompt 系统
OpenAI / Anthropic / Gemini 专属 cache-control
服务器端 KV Cache editing/composition
向量数据库 / Retrieval Memory
通用 Artifact Store / Artifact GC
通用 ContextSource Registry / Projection DSL
Provider-specific Context Window / provider-specific retry policy
OS Sandbox
```

这些 Out of Scope 不得自动复制成能力欠账；只有第五节明确列出的 active Runtime 跨进程恢复边界符合当前任务留下的真实回补条件。

---

# 二十四、任务书实施总原则

```text
交互历史层保存“发生过什么”
Projection 保存“当前从完整历史怎么看”
Context Compiler 决定“这一轮模型看到什么”
Runtime State 保存“当前执行事实是什么”
Runtime Log 保存“这次运行发生了哪些诊断事实”
```

任何实现如果重新把上述五件事塞回一个 `messages` 列表、一个 Snapshot 文件或一个通用 Event 流，即视为偏离本任务书。
