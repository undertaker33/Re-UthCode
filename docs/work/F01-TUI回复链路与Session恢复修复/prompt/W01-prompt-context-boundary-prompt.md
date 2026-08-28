# W01 Prompt 与 Context 消息边界实施提示词

请在 `D:\project\Re-UthCode` 完整实施 F01 的 T01，只修复 Prompt、Context 和当前用户消息边界；不得实施 T02 之后内容。

## 开工前必须读取

1. `AGENTS.md`
2. `docs/README.md`
3. `docs/Context-Index.md`
4. `docs/rules/WorkPackageRules.md`
5. `docs/rules/UserDecisionBoundary.md`
6. `docs/OutstandingDebtList.md`
7. F01 原始需求、Spec、Tasks、Checklist
8. `docs/context/A01-AgentRuntime/AgentRuntime-Context.md`、`A03-State/State-Context.md`
9. T03 System Prompt、T09 Prompt/Context 的 Spec、相关 Feedback
10. T01 Tasks 定位的源码和测试

## 已确认决策

- T09 的 Instruction/Conversation authority、source provenance、budget、stable prefix 和 current user protected-tail 语义保持。
- Runtime/Environment 不擅自升级为 system role；普通历史伪标签不能提升 authority。
- 当前 user 必须逐字、独立、位于尾部；输入 `？` 时不得与 model/provider/environment 文本拼接。
- 生产与测试只保留一个 Prompt/Context 组合入口，不保留兼容双轨。

## 修改范围

- 仅限 Tasks T01 列出的 Core Context/Prompt/Provider request、Application composition、必要 Provider mapping 与对应 tests。
- 首次实施创建 `feedback/W01-prompt-context-boundary-feedback.md`；返工只在该文件末尾追加。
- 只勾选 T01 已用精确证据验证的 Checklist。

禁止修改 reasoning 生命周期、History schema、Session、process tool、Tool 摘要、TUI、其它 Worker Feedback 或 Git 状态。

## 实施约束

1. 使用 Conda 环境 `re-uthcode`，先补能复现短输入黏连和 Prompt 双轨的失败测试。
2. 不以字符串标签模拟 Provider 高权限角色；保留 typed source 与原 authority。
3. 不用内容去重修复拼接；重复文本的不同消息仍是不同事实。
4. mapper 不得无分隔 `join` 独立 semantic parts；最终 wire shape 由唯一正式 composition 决定。
5. 若 `build_system_prompt()` 无生产 caller，删除或收口到唯一入口，不为历史测试保留包装层。
6. 保持 Context Hard Gate、Tool Schema 单一来源、compaction 与 stable prefix semantics。
7. 修改治理 Markdown 时使用 `uth-utf8-guard`；本 Worker 原则上只写 Feedback 和勾选 Checklist。

## 测试与验收

至少执行 Checklist T01 的定向命令和：

```powershell
conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q
git diff --check
```

显式捕获三 Provider request，验证 `？`、相邻 user、steering、重复文本、runtime/environment 变化、伪造标签、Projection 和 current user tail。

## Feedback 要求

说明根因、唯一 composition 调用链、各 source 最终角色/边界、删除的双轨、修改文件、测试精确结果、Checklist 证据、偏差、未完成项和风险。不得声称 T02～T11 已完成。
