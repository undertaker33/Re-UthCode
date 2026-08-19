# W05 Worker Prompt：Application 生命周期与正式入口接入

你负责按顺序执行 T09-1 的 T05、T06。T01～T04 必须完成并有 Feedback。先独立完成并验收 T05，再执行 T06；不得执行 T07/T08，不做 Git 写入或归档。

## 实施起点与事实核对

以用户实际派发本 Prompt 时的当前仓库状态为实施起点，不要求 HEAD 等于任何固定 SHA，也不要求 checkout 历史 Commit。完整读取前置 Feedback 与下列文件后，必须重新核对当前真实 `src/ + tests/`；只有源码实质变化已经使冻结产品语义、架构边界或 T05/T06 完成范围失效时，才停止相关范围并按 Feedback 规则报告。普通后续 Commit、Feedback 追加或 Checklist 勾选不构成基线冲突。

## 开始前必须完整读取

- `AGENTS.md`、`docs/README.md`、`docs/Context-Index.md`、`docs/rules/WorkPackageRules.md`、T09-1 四份主文档与 W01～W04 Feedback。
- `core/agent.py` awaitable preparer/overflow 代码及测试；Application generation/context/session/tools/bootstrap；command registry/dispatcher/builtins；CLI/TUI 正式入口。

## T05：Application/Headless 完成边界

- first ordinary call 前、complete tool batch 后/next call 前、terminal tail 增量 durable append closed facts；不持久化 open continuation。
- durable cursor 防重复；确定 append failure 保留原 identity/FIFO retry；unknown durability quarantine 新语义写入。
- active Turn 冻结 provider/model/configured/effective/provider input、output、combined limits 和 tools；`/model` 只影响下一 Turn。
- 暴露 async Application manual compact API，复用 L4/L5 orchestrator；低 pressure 可执行，无候选 success no-op。
- ContextOverflow 最多一次 forced reduce→rebuild→re-gate→retry；第二次失败，不修改任何 limit facts。
- T05 必须先通过 direct Application/Headless tests；命令/TUI 不应是其可运行前提。

## T06：主流程接入边界

- `/compact` 调用 T05 API；`/status` 显示安全的分维 limits/Gate/Timeline/outcome。
- dispatcher 只为必要 command 支持 awaitable，所有 sync commands 保持行为。
- TUI 只 await command outcome；CLI/TUI/Headless 不复制 Context orchestration。
- bootstrap 完成依赖组合并删除 synchronous-only placeholder/重复入口。
- `AgentLoop` 已支持 sync/awaitable preparer 和 overflow handler：只复用与回归 cancellation/error，不新增第二套协议；无必要不要修改 `core/agent.py`。

## 验证与反馈

先执行/勾选 Checklist T05，再执行/勾选 T06；运行两个任务的完整命令、awaitable hook 回归和架构测试。始终使用与 Prompt 同名的单一 Feedback：

`feedback/W05-application-interface-integration-feedback.md`

首次执行创建该文件；返工只在末尾追加章节。分别记录 T05/T06 实际文件、调用边界、Provider call count、精确测试统计、风险与未验证项。遇到冻结语义冲突立即停止相关范围。
