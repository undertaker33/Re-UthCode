# UthCode 能力欠账清单

> 仅记录 **已交付任务包中，因为后置能力尚未实现而刻意没有继续设计/实施的部分**。
>
> 不把后续完整能力本身列为欠账。

| 来源 | 欠账需求 | 回补前置 / 触发条件 |
|---|---|---|
| **T01 Provider** | 暂无明确能力欠账 | 当前 Provider 边界未发现必须依赖后置能力才能补齐的部分 |
| **T02 Slash Command / TUI** | 补齐 `/memory`、`/dream` 等仍预留命令的真实行为；`/new`、`/resume` 已由 T09 回补，`/compact` 只有命令与安全失败路径，生产 summarizer 由 T09-1 回补 | 对应的 Memory、Dream 或 T09-1 Compaction 底层能力已经实现 |
| **T03 System Prompt** | Memory 或 Skill Instructions 在真实能力出现时作为新的强类型 Context Source 接入；已冻结的 AGENTS / Project Instructions、Prompt Asset、Runtime、Environment、Projection 和 Interaction History 由 T09 正式回补 | 首个 Memory 或 Skill Instructions 来源开始实施 |
| **T04 Tool System** | 支持运行期间动态出现、启停或消失的 Tool，而不是只处理当前稳定 Tool 集合 | Skill、MCP 或其他真实动态 Tool 来源出现 |
| **T05 Agent Loop / Run** | 当前 active/paused Turn 的有效 Runtime State 可以跨进程、跨程序生命周期恢复；T09 工作包只恢复完整提交的 Session 语义历史并从新 Turn 继续 | 正式 Persistent Runtime Recovery 开始实施 |
| **T06 Pause / Resume** | Pending Turn、AskUser、Permission 等暂停状态能够在进程退出后继续恢复 | Persistent Session 与运行状态持久化完成，并开始考虑 restart recovery |
| **T07 Permission** | Skill、MCP、Subagent 等新增执行来源能够进入现有 Permission 决策链，而不是各自绕开权限系统 | 首个新的可执行能力接入 |
| **T07 Permission** | Permission `ALLOW` 之后可以进一步受 OS 级执行隔离约束；Permission 不再承担其无法提供的安全边界 | OS Sandbox 开始实施，或出现不可信本地执行主体 |
| **T08 Runtime Hook** | 在现有两个固定 Hook Point 无法满足真实能力后，再扩充新的 Hook 生命周期点或配置能力 | 出现 Skill、MCP、Subagent 或其他**确实无法由现有 Hook 表达**的真实调用方 |
| **B01 私有测试集 v0** | Memory injection 命中指标仍不可用；T09 已回补 Context Compiler、Working Set、Tool Result 外置与 Compaction diagnostics 机制，但生产 summarizer 尚未提供可比较的真实压缩结果 | Memory 能力开始实施，或 T09-1 生产 Compaction 可运行并产生结构化事实 |
| **T09 Prompt / Context Engineering** | `/resume` 只恢复最后一个已完整提交的安全边界并开始新 Turn；不恢复退出时仍 active/paused 的 Turn、Pending Tool、Permission、AskUser waiter、Provider 请求或协程位置 | 后续正式 Persistent Runtime Recovery 开始实施，并准备回补 T05/T06 跨进程运行状态恢复时 |
| **T09 Prompt / Context Engineering** | 确定性 Working Set 只保护必要上下文并按预算保留 recent complete semantic units；不检索久远但“相关”的证据 | Memory / Evidence Retrieval 有正式需求和可靠证据模型时 |
| **T09 Prompt / Context Engineering** | 大 Tool Result 只有单项/Session 配额与 session-scoped ref；不提供跨 Session Artifact 生命周期、清理与 GC | 出现独立 Artifact Store 生命周期需求时 |
| **T09 Prompt / Context Engineering** | Compaction 只做有界滚动批次；不实现层级 Summary Graph、后台 Context Agent 或高级渐进式压缩 | Eval 证明简单 Compaction 无法满足真实长任务时 |
| **T09-1 Context 预算与 Compact 协议补齐** | 探索并实现真实 Context Window / max input limit 获取、可查询 Provider metadata、官方模型 bundled metadata、OpenAI-compatible / Local 显式配置、统一 Model Limits contract，以及真实窗口与 UthCode Working Budget 的解析；正式解决 T09 固定 258K 阶段不保证真实窗口小于 258K 的模型在长上下文下预算安全的问题 | 已由 `docs/work/T09-1-Context预算与Compact协议补齐/` 的 Task 1 承接；待对应 Checklist 与 Feedback 完成后删除本条 |
| **T09-1 Context 预算与 Compact 协议补齐** | 为现有有界 `ContextCompactor` 接通正式 tool-free summarizer use case，收口异步 Provider 请求、模型选择、取消、失败和最多一次 overflow retry；在此之前 `/compact` 与 overflow compaction 均只会返回 `summarizer_unavailable` | 已由 `docs/work/T09-1-Context预算与Compact协议补齐/` 的 Task 4、Task 6 承接；待对应 Checklist 与 Feedback 完成后删除本条 |
| **T09-1 Context 预算与 Compact 协议补齐** | 完成 small-window / large-window adaptation，并基于 Prefix Cache、token、success Eval 调优 Operating Profile、Working Set、Compaction trigger、recent tail 与 safety headroom | 已由 `docs/work/T09-1-Context预算与Compact协议补齐/` 的 Task 1、Task 3、Task 7 承接；待对应 Checklist 与 Feedback 完成后删除本条 |

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
