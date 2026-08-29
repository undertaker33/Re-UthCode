# W04 Session Commands / TUI Worker Prompt

## 任务范围

只执行：

- Task 8：Session Slash Commands 与 TUI Context Status

先读取 W01～W03 Feedback，核验 use case 后再接 Interface。

## 必须读取

- `AGENTS.md`、项目路由/规则、本工作包四个主文件、W01～W03 Feedback。
- T02 Slash/TUI 归档证据、A04/TUI current context、command registry/dispatcher/models、TUI app/state/rendering 与 tests。

## 必须交付

1. 无参数 `/compact`、`/new`、`/resume [session_id]`、`/status` 的 Application/Slash/TUI 接线。
2. resume 先取得 single-writer lock，恢复 last complete History/Projection，并复用 W02 的 persisted activated scopes + 当前文件系统 AGENTS 重建 Instruction State，再创建新 Turn；不恢复 Task/Plan checkpoint。
3. 明确 busy、损坏、未知 session、compaction failure 的用户可见错误。
4. status 显示 used/258K Operating Budget、Projection revision、instruction epoch、compact count 和可选 prefix/cache 信息，并说明 258K 不是远端模型物理窗口，当前阶段不保证 `<258K` 真实窗口模型的长上下文安全。
5. TUI ring 固定使用 258K denominator；Headless 路径不依赖 TUI。
6. 独立 Picker 只列同 project key Session，按 durable last_used_at 倒序，每页 10 条；首条 User Message 单行 preview，↑/↓、←/→、Enter、Esc 行为不变，至少 21 条验证分页。
7. `/status` 与 ring 使用同一 Application usage projection；草稿不计入、不可用不伪造 0、窄终端不破坏输入。
8. 写入 W04 Feedback 并同步 Tasks/Checklist。

## 禁止

- 不宣称跨进程恢复 TaskState/PlanState、Pending Tool、AskUser 等内存 checkpoint。
- 不实现不同模型动态 denominator 或任何 T09-1 window adaptation。
- 不接受、持久化或继承 compact focus 参数。
- 不直接从 Interface 访问 Session store、Provider、Loader 或 Compiler；不做 Git 写入。

## 验证

覆盖命令路由、`/compact` 拒绝额外 focus 语义、同进程 continuation/跨进程 resume 区别、Instruction State 重建后的命令结果、session busy、new 释放旧锁、固定 used/258K、ring 阈值、Headless 路径和既有 TUI 回归。

## Feedback

首次创建 `feedback/W04-session-commands-tui-feedback.md`，记录 Application/TUI 边界、Picker 状态机、usage 同源证据、精确测试结果与 Checklist 状态。若必须让 Interface 拥有 Session 业务或改变已确认键盘语义，停止并报告。
