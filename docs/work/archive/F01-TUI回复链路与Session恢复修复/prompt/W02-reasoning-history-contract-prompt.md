# W02 Reasoning 与 History 合同实施提示词

请在 `D:\project\Re-UthCode` 严格串行实施 F01 的 T02 -> T03；不得实施 T04 之后内容。

## 开工前必须读取

1. `AGENTS.md`、`docs/README.md`、`docs/Context-Index.md`
2. `docs/rules/WorkPackageRules.md`、`UserDecisionBoundary.md`
3. `docs/OutstandingDebtList.md`
4. F01 原始需求、Spec、Tasks、Checklist 和本 Prompt
5. W01 Feedback，并确认 T01 已完成
6. A01/A03 current context
7. T01 Provider、T05 Agent Loop、T09/T09-1 History/Session 的相关 Spec 与 Feedback
8. T02/T03 Tasks 定位的源码和测试

## 已确认决策

- Reasoning 继续通过 typed Provider part、公开 AgentEvent 和 TUI 独立显示，不能混入 final。
- Reasoning 作为 typed history/display record 持久化，供 `/resume` 完整回放。
- 同 identity active continuation 保留合法 carrier；跨 Provider/model identity 不兼容 reasoning 必须忽略，绝不降级成 TextPart。
- 普通 stop 必须有非空正式 TextPart；reasoning+ToolCall 仍合法。
- 新 Transcript 每 entry 只保存自身 part；旧 v3 可读但不原地迁移。

## 修改范围

- Tasks T02/T03 列出的 Provider/Core Agent/Event、History/Context、Session compatibility 与对应 tests。
- 首次实施创建 `feedback/W02-reasoning-history-contract-feedback.md`；返工追加。
- 只勾选 T02/T03 已验证 Checklist。

禁止修改 Application Session replay DTO、lazy Session、process tool、Tool 摘要、TUI、当前事实文档、其它 Feedback 或 Git。

## 实施约束

1. 先补流矩阵、跨 identity、reasoning-only final 和 storage amplification 失败测试。
2. Provider-level native carrier 不穿透为普通文本；Core 不按 Provider 名称分支。
3. `final_text` 只从 TextPart 派生；UI 纠正文本同样不得包含 ReasoningPart。
4. History identity 聚合必须保持相同文本的独立 Turn、part 顺序和 Tool pair，不做全局内容去重。
5. 兼读旧 payload 只在现有 reader 内收敛，不新增 migration manager、schema 双写或旧 API alias。
6. 保持 strict sequence、durability cursor、unknown quarantine、Tool semantic unit 与 compaction 输入边界。

## 测试与验收

执行 Checklist T02/T03 的全部命令，另执行：

```powershell
conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q
git diff --check
```

至少覆盖同 chunk reasoning+content、交错 stream、多 segment、same/cross identity、reasoning+ToolCall、reasoning-only stop、新旧 Session round-trip 和新旧存储体积/复制次数。

## Feedback 要求

说明 Provider 流真值表、same/cross identity 行为、terminal 判定、typed reasoning 持久化、逻辑 Message 重建、旧 Session 兼读、存储放大修复、文件和测试结果。不得把 TUI 顺序或 resume hydrate 写成已完成。
