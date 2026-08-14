# W06 Integration / Delivery Worker Prompt

## 任务范围

只执行：

- Task 10：[接入主流程] 正式 Context Composition 收口
- Task 11：[端到端验证] Context / Session / Prefix
- Task 12：[遗留负担清理] 单历史 / 单 Context Path 收口

先读取 W01～W05 Feedback；任何前置 Task 未完成时停止对应集成，不代替前置 Worker 扩大实现。

## 必须读取

- `AGENTS.md`、`docs/README.md`、`docs/Context-Index.md`、WorkPackageRules、本工作包四个主文件和 W01～W05 Feedback。
- A01～A04/TUI current context、UserManual、Tools、全部 T09 改动的 `src/ + tests/ + eval/`；历史只在当前事实不足时读取。

## 必须交付

1. 验证 Prompt → Instructions → History/Projection → fixed 258K Budget/Compiler → Session/Results → Compaction → Slash/TUI → Eval 全链路。
2. 端到端覆盖 prefix stability、authority spoof rejection、fixed 258K、AGENTS、compactor overflow、concurrent resume、runtime recovery boundary、result quota/ref 与 execution/persistence outcome。
3. 运行定向、`tests/test_architecture_boundaries.py` 与全量测试，记录精确结果。
4. 同步 State/Interface Context、UserManual、Context-Index、OutstandingDebtList、Tasks/Checklist；保留真实后置欠账。
5. 删除本包替代出的重复/不可达路径，不保留兼容壳。
6. 检查 UTF-8、乱码、replacement character、Markdown fence 和 diff scope。
7. 写入 W06 Feedback；不自行归档、commit、push。

## 一致性审查清单

- 258K 只写为 T09 固定 Context Operating Budget，不冒充远端模型物理窗口。
- 当前 Runtime AGENTS 状态与历史冻结语义表述一致。
- stable prefix 后没有动态 state 再阻断长历史。
- Projection 没有 System/Core authority 升级。
- T09 中没有 Model Limits discovery、不同窗口适配或 Operating Profile 阈值优化；这些只出现在 T09-1 欠账。
- Working Set 无隐藏 relevance 算法。
- Compactor 有独立硬预算。
- Session 是 single writer。
- `/resume` 不承诺 Runtime checkpoint。
- Tool Result 有最薄资源上限且 ref 非路径接口。
- Tool 已执行后的 persistence failure 不伪造未执行，也不触发副作用自动重试。
- Eval 包含 prefix/cache 诊断。

未运行或被阻塞项必须明确列出，不得称完成。

## Feedback

首次创建 `feedback/W06-integration-delivery-feedback.md`，记录全链路、修改文件、精确测试计数/耗时、Checklist、文档/欠账同步、风险和未验证项。只修复 T09 范围集成缺陷；不自行归档或执行 Git 写入。
