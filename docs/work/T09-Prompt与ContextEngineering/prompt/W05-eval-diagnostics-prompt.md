# W05 Eval Diagnostics Worker Prompt

## 执行范围

在 W03 完成后执行 Task 9。写入范围与 W04 不交叉；不修改 Session/TUI 产品语义，不执行 Task 10～12。

## 必须读取

1. `AGENTS.md`、`docs/rules/WorkPackageRules.md`，本工作包原始需求、Spec、Tasks、Checklist 和 W01～W03 Feedback。
2. B01 Spec/Tasks/Checklist 与 W01～W03 Feedback，`eval/README.md`、`eval/metrics.py`、`eval/execution.py`和对应 tests。
3. Application 对外的 Context diagnostics/usage 安全投影，不读取 Core 私有状态作为 Eval 公共合同。

## 已确认决策

- 报告并列展示结构化 Context 事实，不生成单一综合分。
- 没有事实时使用 `not_available`，不猜测。
- 确定性 diagnostics 用 pytest；概率性效果只用同模型/任务/运行参数 compare，不成为 pytest/CI gate。
- 本 Worker 不执行需远程模型、凭据或成本的真实 baseline，除非用户另行授权。

## 实施与禁止边界

- Eval 只消费 Application 公开、JSON-safe、脱敏投影；不读完整 Tool Result、Session 磁盘文件或 Provider native payload。
- 不注册正式 CLI、不接 CI、不引入 LLM Judge/公共 benchmark/leaderboard。
- 冻结文件规则与 Checklist 勾选规则同 W01。

## 测试与验收

执行 Checklist Task 9 全部项、B01 现有定向 Eval tests 和 secret scan。验证报告指纹与 task sample count 现有一致性不回归。

## Feedback

创建 `feedback/W05-eval-diagnostics-feedback.md`。记录新 diagnostics 来源、NA 语义、报告对比边界、测试精确结果与未执行的真实 Eval。需要修改生产语义或读取私有/敏感数据时停止并记录。
