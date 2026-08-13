# UthCode 能力欠账清单

> 仅记录 **已交付任务包中，因为后置能力尚未实现而刻意没有继续设计/实施的部分**。
>
> 不把后续完整能力本身列为欠账。

| 来源 | 欠账需求 | 回补前置 / 触发条件 |
|---|---|---|
| **T01 Provider** | 暂无明确能力欠账 | 当前 Provider 边界未发现必须依赖后置能力才能补齐的部分 |
| **T02 Slash Command / TUI** | 补齐 `/compact`、`/new`、`/resume`、`/memory`、`/dream` 等已预留命令对应的真实行为；届时重新确认命令语义 | 对应的 Context、Session、Memory 等底层能力已经实现 |
| **T03 System Prompt** | 支持运行时动态上下文参与 Prompt 构造，而不再只依赖当前固定 Prompt Section 与少量 Runtime Facts | Context Engineering 开始实施；出现项目指令、Memory、Skill Instructions 等真实动态上下文来源 |
| **T04 Tool System** | 支持运行期间动态出现、启停或消失的 Tool，而不是只处理当前稳定 Tool 集合 | Skill、MCP 或其他真实动态 Tool 来源出现 |
| **T04 Tool System** | 大型 Tool Result 在被截断后仍可被后续上下文可靠引用，而不是只能依赖当前消息内容 | Context 压缩/引用机制或持久化内容能力开始实施 |
| **T05 Agent Loop** | 长对话下对历史消息进行选择、预算控制和压缩，避免 Run 的 messages 持续完整累积 | Context Budget / Context Compaction 开始实施 |
| **T05 Agent Loop / Run** | Run 的有效状态可以跨进程、跨程序生命周期恢复，而不再仅存在于内存 | Persistent Session 能力开始实施 |
| **T06 Pause / Resume** | Pending Turn、AskUser、Permission 等暂停状态能够在进程退出后继续恢复 | Persistent Session 与运行状态持久化完成，并开始考虑 restart recovery |
| **T07 Permission** | Skill、MCP、Subagent 等新增执行来源能够进入现有 Permission 决策链，而不是各自绕开权限系统 | 首个新的可执行能力接入 |
| **T07 Permission** | Permission `ALLOW` 之后可以进一步受 OS 级执行隔离约束；Permission 不再承担其无法提供的安全边界 | OS Sandbox 开始实施，或出现不可信本地执行主体 |
| **T08 Todo / Plan** | Todo / Plan 可以跨 Turn 延续，并定义何时继续使用、何时更新、何时失效，而不是每个新 Turn 直接重新开始 | Context Engineering 开始实施，能够明确跨 Turn 状态与上下文的关系 |
| **T08 Todo / Plan** | Context Compaction 后仍能保留并恢复长期任务的有效 Todo / Plan 状态 | Structured Compaction 开始实施 |
| **T08 Runtime Hook** | 在现有两个固定 Hook Point 无法满足真实能力后，再扩充新的 Hook 生命周期点或配置能力 | 出现 Skill、MCP、Subagent 或其他**确实无法由现有 Hook 表达**的真实调用方 |
| **B01 私有测试集 v0** | 上下文有效性当前只能记录已有 evidence discovery、Usage 和 Tool 轨迹；无法计算压缩、Working Set 选择与淘汰、证据保留与恢复、Memory injection 命中等指标 | Context Compiler、Compaction、Working Set 或 Memory 任一能力开始实施并产生结构化运行事实时，在对应任务中接入 B01 的版本化 diagnostics |

## 维护原则

后续开发某项能力时，只需要检查它是否命中了上表的“回补前置 / 触发条件”。

例如：

```text
开始做 Context
→ 回看 T03 / T04 / T05 / T08 欠账

开始做 Session
→ 回看 T02 / T05 / T06 欠账

开始做 Skill 或 MCP
→ 回看 T03 / T04 / T07
→ 若现有 Hook 不够，再回看 T08 Hook

开始做 Sandbox
→ 回看 T07 Permission → Execution 边界
```

**没有真实 Trigger 时，不提前为这些欠账设计解决方案。**
