# W05 Context Diagnostics / Eval Worker Prompt

## 任务范围

只执行：

- Task 9：Context Diagnostics 与 Eval

先读取 W01～W04 Feedback，以实际事件/Usage/Snapshot contract 为准。

## 必须读取

- `AGENTS.md`、项目路由/规则、本工作包四个主文件、W01～W04 Feedback。
- B01 Spec/Tasks/Feedback、`eval/README.md`、metrics/execution/reporting、Application public diagnostics、Provider Usage mapping 与 tests。

## 必须交付

1. selected/omitted、compact、externalization、session recovery/busy、instruction epoch 与 stable-prefix diagnostics/change reason。
2. 复用 Provider 现有 cache read/write token Usage 映射并增加 availability/provenance；Provider 不支持时报告 `not_available`，不把现有默认 0 冒充实测值。
3. baseline/candidate Eval 比较 success、tokens、tool calls、compact count、rediscovery、repeated exploration、externalization、prefix stability/cache reuse。
4. 加入 Runtime/Projection 变化不改 epoch/fingerprint、目录 AGENTS 新 scope 改变 epoch/fingerprint、已生效未变化 AGENTS 稳定复用，以及 resume 后未变化保持/离线修改删除产生明确 reason 的场景。
5. 增加 ordinary history 伪造 AGENTS/Project/Runtime 标签仍不能进入 Instruction Plane，以及 Tool 已执行但 persistence 失败不误报/重试的场景。
6. Eval 只衡量策略，不把“候选必须更优”写为 pytest 通过条件。
7. 写入 W05 Feedback 并同步 Tasks/Checklist。

## 禁止

- 不额外复制 Runtime credential/API key、完整大型 Tool Result、Provider native payload 或未脱敏内部异常；不承诺通用 Secret/DLP。
- 不要求所有 Provider 提供相同 cache metrics。
- 不实施 Memory injection、embedding/retriever、生产上下文策略重写或 Git 写入。
- 不实现 128K/1M/unknown-model window Eval 或 258K 阈值专项优化；这些属于 T09-1。

## 验证

覆盖 diagnostics schema/序列化、缺失 cache metrics 的 NA 语义、现有 Usage 映射、deterministic Eval、baseline/candidate 报告一致性、Instruction Epoch 在运行时与跨进程 resume 中的预期变化及全部前缀回归场景。

## Feedback

首次创建 `feedback/W05-eval-diagnostics-feedback.md`，记录字段来源、NA 语义、对比边界、精确测试结果、Checklist 状态和未执行的真实远程 Eval。需要读取私有/敏感数据或修改生产策略时停止。
