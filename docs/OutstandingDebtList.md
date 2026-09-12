# UthCode 能力欠账清单

> 仅记录 **任务包中因后置能力尚未实现而刻意未继续设计或实施、仍待回补的部分；在工作包拆分时登记，后续按实际回补情况更新或删除**。
>
> 不把后续完整能力本身列为欠账。

| 来源 | 欠账需求 | 回补前置 / 触发条件 |
|---|---|---|
| **T03 System Prompt** | Memory 或 Skill Instructions 在真实能力出现时作为新的强类型 Context Source 接入；已冻结的 AGENTS / Project Instructions、Prompt Asset、Runtime、Environment、Transcript/Timeline 和 Interaction History 由 T09/T09-1 正式回补 | 首个 Memory 或 Skill Instructions 来源开始实施 |
| **T04 Tool System** | 支持运行期间动态出现、启停或消失的 Tool，而不是只处理当前稳定 Tool 集合 | Skill、MCP 或其他真实动态 Tool 来源出现 |
| **T05 Agent Loop / Run** | 当前 active/paused Turn 的有效 Runtime State 可以跨进程、跨程序生命周期恢复；T09 工作包只恢复完整提交的 Session 语义历史并从新 Turn 继续 | 正式 Persistent Runtime Recovery 开始实施 |
| **T06 Pause / Resume** | Pending Turn、AskUser、Permission 等暂停状态能够在进程退出后继续恢复 | Persistent Session 与运行状态持久化完成，并开始考虑 restart recovery |
| **T07 Permission** | Skill、MCP、Subagent 等新增执行来源能够进入现有 Permission 决策链，而不是各自绕开权限系统 | 首个新的可执行能力接入 |
| **T07 Permission** | Permission `ALLOW` 之后可以进一步受 OS 级执行隔离约束；Permission 不再承担其无法提供的安全边界 | OS Sandbox 开始实施，或出现不可信本地执行主体 |
| **B01 私有测试集 v0** | Memory injection 命中指标仍不可用；T09/T09-1 已回补 Context Compiler、Working Set、Tool Result 外置、生产 Compaction 与安全 diagnostics，生产 Compaction 不可运行不再作为欠账 | Memory injection 部分继续保留到 Memory 能力开始实施 |
| **T09 Prompt / Context Engineering；T11 Agent能力补齐** | `/resume` 只恢复最后一个已完整提交的安全边界并开始新 Turn；不恢复退出时仍 active/paused 的 Turn、Pending Tool、Permission、AskUser waiter、Provider 请求或协程位置。T11 补充后续恢复边界：旧 process_id 必须映射为不可恢复/已结束事实，并闭合待定工具与输入，不自动重启命令或重放 stdin；本次程序内进程管理与退出收尾仍属 T11 必需实施范围 | 后续正式 Persistent Runtime Recovery 开始实施，并准备回补 T05/T06 跨进程运行状态恢复时 |
| **T09 Prompt / Context Engineering** | 确定性 Working Set 只保护必要上下文并按预算保留 recent complete semantic units；不检索久远但“相关”的证据 | Memory / Evidence Retrieval 有正式需求和可靠证据模型时 |
| **T09 Prompt / Context Engineering；T11 Agent能力补齐** | 大 Tool Result 只有单项/Session 配额与 session-scoped ref；不提供跨 Session Artifact 生命周期、清理与 GC。T11 补充未来统一管理对象为会话原始附件与工具图像引用，届时明确跨会话引用、迁移和清理关系；T11 会话内原始资料保存及派生缓存清理仍是本次必需实施范围，当前尚未实施 | 出现独立跨 Session Artifact Store 生命周期需求时 |
| **T09 Prompt / Context Engineering** | Compaction 只做有界滚动批次；不实现层级 Summary Graph、后台 Context Agent 或高级渐进式压缩 | Eval 证明简单 Compaction 无法满足真实长任务时 |

## 维护原则

清单只保留真实未结欠账，不添加“暂无欠账”占位行；任务包自身无欠账时在其对应章节写“无”。后续开发先核对是否命中上表的“回补前置 / 触发条件”，命中不自动授权扩大范围；维护流程遵守 [工作包规则](rules/WorkPackageRules.md)。

例如：

```text
开始做 Memory / Evidence Retrieval
→ 回看 T03 / B01 / T09 的对应条目

开始做跨进程 Runtime Recovery
→ 回看 T05 / T06 / T09 的恢复边界

开始做 Skill 或 MCP
→ 回看 T03 / T04 / T07

开始做 Sandbox
→ 回看 T07 Permission → Execution 边界
```

**没有真实 Trigger 时，不提前为这些欠账设计解决方案。**
