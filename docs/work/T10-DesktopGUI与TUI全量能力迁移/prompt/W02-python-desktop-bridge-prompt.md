# W02 Python Desktop Bridge 实施提示词

请在 `D:\project\Re-UthCode` 完整实施 T10 的 T02，只完成 Python Desktop Bridge 与协议，不得实施 Electron/Renderer/T03 之后内容。

## 开工前必须读取

1. `AGENTS.md`、`docs/README.md`、`docs/Context-Index.md`
2. `docs/rules/WorkPackageRules.md`、`docs/rules/UserDecisionBoundary.md`、`docs/OutstandingDebtList.md`
3. T10 原始需求、Spec、Tasks、Checklist 和本 Prompt
4. `docs/context/A03-State/State-Context.md`、`docs/context/A04-Orchestration/Orchestration-Context.md`、`docs/context/TUI/README.md`
5. `feedback/W01-user-config-bootstrap-feedback.md`
6. Tasks T02 定位的 runs/session/command/event/interaction 源码与 tests

## 已确认决策

- Bridge 是 Interface，只依赖 `uthcode.application` 公共导出；无 Core/Provider/Tool/Session Store 直接访问。
- 私有 transport 为单本机 child + stdin/stdout JSONL，stdout 仅协议，stderr 仅 diagnostics，不建通用 RPC/EventBus。
- one Application / one Run / one active Turn 由 Bridge 显式持有；Session/Project 切换后 fresh Run，旧 grant/history/mode 不渗入。
- Plan/Retry/Pause Cancel 调用 handle.cancel；用户 Pause Continue 使用 `ResumeTurnResponse`；Permission choices 来自每次 request。
- pending/active command 门禁必须与 TUI 当前行为一致，不可无条件 dispatch 产生副作用命令。

## 修改范围

- 只修改 Tasks T02 列出的 `interfaces/desktop`/tests，Application 只在现有 safe API 确有缺口时最小扩展。
- 首次实施创建 `feedback/W02-python-desktop-bridge-feedback.md`；返工只追加。
- 只勾选 T02 Checklist。不得修改冻结文件文字，不得 Git 写/归档。

## 实施与验证

1. 先写 protocol 严格解析、correlation、stdout purity、event order、one Turn、typed/stale response、command guard、fresh Run、transactional session/project switch 与 shutdown 失败测试。
2. replay 只恢复 `user/steering/reasoning/assistant/tool`，不扩大 durable schema 为全事件存储。
3. AgentEvent payload 保留公开字段/名称；protocol/runtime process error 与 Agent/Provider failure 分域。
4. 至少执行 T02 Checklist 命令、T01 配置回归、`git diff --check`。

## Feedback 要求

Feedback 说明 envelope/method 最终集合、Application/Run/Turn 生命周期、Session/Project/Command 门禁、typed response/cancel 映射、stdout/stderr、秘密安全、修改文件、精确测试结果、Checklist 和未完成项。
