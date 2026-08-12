# W04 Permission Delivery Prompt

## 任务

严格串行执行：

1. Task 8 [接入主流程] — 全链路 Composition
2. Task 9 [端到端验证] — Headless / CLI / TUI / Provider
3. Task 10 [遗留负担清理] — 旧语义与重复职责清理

这是交付收口 Worker。不得新增 T07 范围外能力。

## 前置门槛

完整读取 W01、W02、W03 Feedback，确认 Task 1～7 与对应 Checklist 已有通过证据。若前序公共边界未完成或冻结文件与实现冲突，停止相关收口并记录，不通过改写工作包修补。

## 必须完整读取

- `AGENTS.md`、`SRe-AGENTS.md`、`docs/work/README.md`
- T07 原始需求、Spec、Tasks、Checklist 与全部 Worker Prompt/Feedback
- T04、T05、T06 的 Spec、Tasks、Checklist、交付 Feedback
- 当前 Application bootstrap/generation/tools/runs、Core Agent/Tool/Permission/Interaction、Integrations tools/rules、Interfaces CLI/TUI
- 全部相关测试与 architecture boundaries

## 已确认设计决策

- 唯一生产链为 normalized ToolCall → registered/validated → trusted Action → Guard/Policy → Session Grant/Strategy → Allow/Deny/Ask → execute/ToolResult/T06 Pause。
- 所有正式普通 Tool 执行入口必须经过同一权限边界；AskUserQuestion 维持 T06 独立控制路径。
- Provider adapters 只产出规范化 ToolCall，不包含权限分支或 Permission metadata。
- 三模式、Guard、Policy、outside、sensitive resource、Bash Guard、HITL、Session Grant、`/permission` 的语义均以原始需求和 Spec 为准。
- Interface 可删除而 Headless/Core 链仍完整；权限机制不是 OS Sandbox。
- T07 完成后不保留兼容层、旧入口、重复职责或未来能力占位。

## 修改范围

优先修改 Task 8 明列的 Application composition 文件与 Task 9 测试。仅当端到端测试暴露 Task 1～7 范围内真实缺陷时，窄幅修复对应生产文件并在 Feedback 说明。Task 10 只删除明确被替代的 T07 遗留，不删除无关历史能力。

## 实施约束

- 使用 `conda run --no-capture-output -n re-uthcode ...`。
- 先接通单一正式链，再做端到端测试，最后清理临时旁路；不得长期保留双轨。
- 所有 filesystem E2E 使用隔离临时 HOME/workdir；所有危险命令只 mock/stub。
- Provider 一致性通过对等规范化 ToolCall 验证，不在 Core/Permission 中按 provider 名称分支。
- 工作包已冻结：不得修改 Spec、Tasks、Prompt 或 Checklist 文字，只可勾选已通过复选框并追加 Feedback。
- 不执行 Git add/commit/push，不归档工作包。

## 测试与验收

- 执行 Checklist Task 8～10 的全部集成、E2E、Provider、Headless、CLI、TUI、架构和遗留扫描。
- 至少完成真实安全文件写入 once、拒绝无变化并继续、隔离 outside 批准后执行、敏感 Grep Guard 四条正式入口验收。
- 执行完整 `pytest -q`、`compileall -q src tests`、`pip check`、`git diff --check`。
- 对所有修改 Markdown 执行 UTF-8 guard；人工检查事件与错误不泄密。
- 复核 Task 1～10 全部 Checklist，只勾选有当前证据的项目。

## Feedback

创建并持续维护：

`docs/work/T07-三层权限系统/feedback/W04-permission-delivery-feedback.md`

Feedback 应给人工审查提供：最终调用链、关键状态变化、实际修改文件、逐类测试命令与结果、全部 Checklist 状态、与任务书不同的事实、未完成项/风险、遗留扫描和非兼容清理结论。返工只在同一文件末尾追加，不覆盖旧记录。
