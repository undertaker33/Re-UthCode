# UthCode 能力欠账清单

> 仅记录 **已交付任务包中，因为后置能力尚未实现而刻意没有继续设计/实施的部分**。
>
> 不把后续完整能力本身列为欠账。

| 来源 | 欠账需求 | 回补前置 / 触发条件 |
|---|---|---|
| **T01 Provider** | 暂无明确能力欠账 | 当前 Provider 边界未发现必须依赖后置能力才能补齐的部分 |
| **T02 Slash Command / TUI** | 补齐 `/memory`、`/dream` 等仍预留命令的真实行为；`/compact`、`/new`、`/resume` 已由 T09 工作包纳入回补范围 | 对应的 Memory、Dream 等底层能力已经实现 |
| **T03 System Prompt** | 在真实出现项目指令、Memory 或 Skill Instructions 时，将其作为新的强类型 Context Source 接入；T09 工作包已纳入 Prompt Asset、Runtime、Environment、Projection 和 Interaction History 的组装回补 | 首个对应动态上下文来源开始实施 |
| **T04 Tool System** | 支持运行期间动态出现、启停或消失的 Tool，而不是只处理当前稳定 Tool 集合 | Skill、MCP 或其他真实动态 Tool 来源出现 |
| **T05 Agent Loop / Run** | 当前 active/paused Turn 的有效 Runtime State 可以跨进程、跨程序生命周期恢复；T09 工作包只恢复完整提交的 Session 语义历史并从新 Turn 继续 | 正式 Persistent Runtime Recovery 开始实施 |
| **T06 Pause / Resume** | Pending Turn、AskUser、Permission 等暂停状态能够在进程退出后继续恢复 | Persistent Session 与运行状态持久化完成，并开始考虑 restart recovery |
| **T07 Permission** | Skill、MCP、Subagent 等新增执行来源能够进入现有 Permission 决策链，而不是各自绕开权限系统 | 首个新的可执行能力接入 |
| **T07 Permission** | Permission `ALLOW` 之后可以进一步受 OS 级执行隔离约束；Permission 不再承担其无法提供的安全边界 | OS Sandbox 开始实施，或出现不可信本地执行主体 |
| **T08 Runtime Hook** | 在现有两个固定 Hook Point 无法满足真实能力后，再扩充新的 Hook 生命周期点或配置能力 | 出现 Skill、MCP、Subagent 或其他**确实无法由现有 Hook 表达**的真实调用方 |
| **B01 私有测试集 v0** | Memory injection 命中指标仍不可用；T09 工作包已纳入 Context Compiler、Compaction、Working Set、Evidence 重新发现和 Tool Result 外置 diagnostics 的回补 | Memory 能力开始实施并产生结构化注入事实 |
| **T09 Prompt / Context Engineering** | `/resume` 只恢复最后一个已完整提交的安全边界并开始新 Turn；不恢复退出时仍 active/paused 的 Turn、Pending Tool、Permission、AskUser waiter、Provider 请求或协程位置 | 后续正式 Persistent Runtime Recovery 开始实施，并准备回补 T05/T06 跨进程运行状态恢复时 |

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
