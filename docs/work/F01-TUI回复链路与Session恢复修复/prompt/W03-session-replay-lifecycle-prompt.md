# W03 Session Replay 与惰性生命周期实施提示词

请在 `D:\project\Re-UthCode` 完整实施 F01 的 T04，只建立 Application replay 和 Session lifecycle；不得修改 TUI 或实施后续任务。

## 开工前必须读取

1. `AGENTS.md`、`docs/README.md`、`docs/Context-Index.md`
2. 工作包规则、用户拍板边界、欠账清单
3. F01 原始需求、Spec、Tasks、Checklist 和本 Prompt
4. W01、W02 Feedback
5. A03/A04 current context
6. T09 Session commands、staged resume、single-writer 和 History persistence 的相关 Spec/Feedback
7. T04 Tasks 定位的源码和测试

## 已确认决策

- `/resume` 完整回放 durable user、steering、reasoning、formal assistant 和安全 Tool 终态。
- raw ToolResult、native payload、secret、pending interaction 和 Runtime checkpoint 不回放。
- TUI 冷启动不创建 Session；首条普通输入前 lazy ensure；`/new` 显式创建；`/resume` 直接恢复目标。
- replay 无 Provider、Turn 或 persistence 副作用；失败原子保持当前 Session。

## 修改范围

- Tasks T04 列出的 Application Session/generation/command models、必要 CLI cold-start 调整和 tests。
- 首次实施创建 `feedback/W03-session-replay-lifecycle-feedback.md`；返工追加。
- 只勾选 T04 已验证 Checklist。

禁止修改 `interfaces/tui/`、Provider/History contract、process tool、Tool redaction policy、当前事实文档、其它 Feedback 或 Git。

## 实施约束

1. Application DTO 必须 interface-neutral、JSON-safe、按 durable sequence 排序并已脱敏。
2. Tool replay 复用 Application 现有安全摘要能力，不把原始 payload交给 TUI。
3. staged resume 全部成功后才公开 replay；失败不得部分切换。
4. 无 active Session 时 help/status/catalog/close/create Run 所需无持久操作必须安全。
5. 第一条普通输入在永久显示和 Provider call 前 ensure；失败不留下半状态。
6. 不删除旧空 Session，不新增 GC、migration、ReplayManager 或第二 store。

## 测试与验收

执行 Checklist T04 的全部命令，另执行架构测试与 `git diff --check`。记录 catalog/session ID 集合，验证 exit/help/status/picker/resume/new/ordinary/exec 和 ensure failure。

## Feedback 要求

说明 replay DTO 字段、安全过滤、原子 resume、lazy lifecycle 状态表、修改文件、测试结果、Checklist、偏差和风险。明确 TUI 尚未 hydrate，由 W05 负责。
