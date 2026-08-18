# W05：正式生命周期与命令接入 Prompt

请完整读取并执行本文件。你负责 T06 `[接入主流程]`，把 T01～T05 能力接入正式 Application/Run/Session/Command/TUI/Headless 链路，不提前做包级文档与最终清理。

## 必须先读

1. `AGENTS.md`、`docs/README.md`、`docs/Context-Index.md`、`docs/rules/WorkPackageRules.md`
2. 本工作包原始需求、Spec、Tasks、Checklist
3. W01～W04 Feedback；确认 T01～T05 Checklist 全部有证据完成。
4. `docs/context/A03-State/State-Context.md`、`docs/context/A04-Orchestration/Orchestration-Context.md`、`docs/context/TUI/README.md`
5. T06 Tasks 的全部源码与测试，特别是 Run driver、terminal persistence、command dispatcher 和 TUI input path。

使用 Conda 环境 `re-uthcode`，不得回退前序 contract。

## 冻结决策

- 每次真实 model call 前都必须通过 final-request Hard Gate：ordinary、post-tool、post-resume、manual、L4、L5、overflow retry。
- active Turn 冻结 provider/model/C/output/tools；mid-turn `/model` 只影响下一 Turn。
- closed Transcript facts 在每次下一 ordinary call 前增量 durable，terminal tail 继续提交；不持久化 open runtime continuation。
- `/compact` await 同一 Application orchestrator，manual 不依赖 Auto Gate；无候选 success no-op，不创建新 Session/Run/Turn 或 Timeline garbage。
- ordinary Provider overflow 最多 forced reduction + retry 一次；second overflow fail，不学习/修改 C/E。
- command dispatcher 只做最小 sync-or-awaitable adaptation；Interface 不拥有 Context。
- resume 仍是 durable closed facts + fresh Run，不是 Persistent Runtime Recovery。

## 修改范围

只修改 T06 Tasks 文件和必要的机械 public export/test fixture。不要修改 Permission、Plan/Todo、Runtime Hook、其它 Slash Command 产品语义或 TUI rendering 设计；不要做 Timeline GC、Memory 或 Runtime checkpoint。

## 实施要求

- request preparation 在正式 call 前提交当前已闭合 user/tool semantic facts；terminal handler 提交 final tail。cursor 只按 durable identity 前进。
- append 后异常先 reconciliation；unknown durability quarantine active writer；真正未落盘 batch 保持原 Session/Turn identity FIFO retry。
- open assistant streaming fragment、unmatched ToolCall、pending Tool/Permission/AskUser/coroutine 不写 Transcript。
- `/compact` 的 async handler 返回结构化 success/no-op/failure；未知异常不得把内部正文暴露给 UI。
- 保留全部 sync commands 的现有直接调用测试；TUI await dispatcher/outcome，不把 budget/Timeline logic 复制到 Interface。
- overflow retry 必须 rebuild final request 并重做 Hard Gate；只对普通 request 有一次 retry 预算。Tool 副作用与 persistence failure 不触发 Tool 重试。
- `/status` 使用 public safe diagnostics，展示动态 C/E/Auto/Hard/Timeline/count source，不能泄露 raw facts。

## 验证与交付

完成 T06 Checklist；同时回归 T05/T06 pause/resume、T08 Plan/Todo/Hook、Permission、CLI/headless、Session quarantine 与 architecture tests。使用 fake Provider 逐一断言每类 model call 的 Hard Gate。

首次执行时创建：

`docs/work/T09-1-Context预算与Compact协议补齐/feedback/W05-runtime-command-integration-feedback.md`

Feedback 说明 incremental persistence 时序、frozen snapshot、manual/overflow 状态流、sync/async command compatibility、正式入口测试及未验证项。只勾选 T06 Checklist；不修改冻结文本或归档。

未经用户明确要求，不执行任何 Git 写操作。
