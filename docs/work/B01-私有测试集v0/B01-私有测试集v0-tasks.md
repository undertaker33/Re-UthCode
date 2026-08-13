# B01 私有测试集 v0 Tasks

```text
worker_groups:
  W01-eval-contract-workspace: Task 1 -> Task 2
  W02-eval-execution: Task 3
  W03-eval-suite-delivery: Task 4 -> Task 5 -> Task 6 -> Task 7 -> Task 8 -> Task 9
worker_dependencies:
  W02 depends on W01
  W03 depends on W01 and W02
execution_rule: Workers 严格按依赖串行派发；每个 Worker 内严格按 Task 顺序实施。
```

## Task 1：任务与产物合同

- 任务目标：建立严格、版本化且可 round-trip 的 Eval 数据合同。
- 新增文件：`eval/models.py`；`tests/eval/test_eval_reporting.py` 的合同测试。
- 修改文件：无。
- 删除文件：无。
- 文件职责及实施内容：定义任务、交互、验证结果、attempt、指标、指纹和错误分类；解析 TOML/JSON 时拒绝未知字段、非法路径、重复 ID、越界分数、非法 interaction 和宽泛 permission rule；把不可用值与数值零分开表达。
- 依赖任务：无。
- 参考资料定位：原始需求第九、十一、十三、十六和十九节；现有 Application/Core 公共导出只用于避免持久化私有类型。
- 完成边界：七个任务可以通过同一合同解析；错误可定位字段且不包含秘密；不设计公共 Benchmark adapter、数据库或远程协议。

## Task 2：仓库外 workspace 与安全清理

- 任务目标：实现安全的外部 Eval 根、fixture 复制、attempt 生命周期、仓库污染基线和精确清理。
- 新增文件：`eval/workspace.py`、`tests/eval/test_eval_workspace.py`。
- 修改文件：无。
- 删除文件：无。
- 文件职责及实施内容：对所有路径做物理解析；拒绝源码仓库、其子目录、链接回仓库、根目录、home 根和非专用目标；只复制 fixture；保存创建 manifest；比较运行前后 Git status 增量；clean 仅接受 manifest 标识的具体 experiment/attempt。
- 依赖任务：Task 1。
- 参考资料定位：原始需求第五、九、十、十六、十七、十八和十九节；`docs/context/A02-Control/Control-Context.md` 的 unsandboxed 边界。
- 完成边界：成功、失败、部分创建和清理均不污染或破坏源码仓库；既有 dirty worktree 原样保留；不实现通用删除工具。

## Task 3：单次 Headless attempt 执行

- 任务目标：通过公开 Application API 完成一个任务的一次可观测执行。
- 新增文件：`eval/execution.py`、`tests/eval/test_eval_execution.py`。
- 修改文件：无。
- 删除文件：无。
- 文件职责及实施内容：为每次 attempt 建立独立 home/workspace/artifacts 和配置指纹；构造正式 Application 与一个 Run/Turn；唯一消费事件流并等待同一终态；严格响应任务声明的 AskUser/PlanReview；Permission ASK、未声明交互和 timeout 均只取消一次；分类 Provider、Runtime、verifier 和 runner 失败；保存脱敏 artifacts。
- 依赖任务：Task 1、Task 2。
- 参考资料定位：`src/uthcode/application/__init__.py`、`bootstrap.py`、`generation.py`、`runs.py`；`docs/context/A01-AgentRuntime/AgentRuntime-Context.md`、`A02-Control/Control-Context.md`、`A03-State/State-Context.md`、`A04-Orchestration/Orchestration-Context.md`；相关 Application、Event、Permission、T08 测试。
- 完成边界：正常、ASK、未声明交互、timeout、Provider failure 均形成完整 attempt；离线测试使用 Fake Provider；不修改正式产品路径或直接调用 Provider/Tool/Core 私有接口。

## Task 4：七个私有任务与 deterministic verifier

- 任务目标：建立能稳定区分 Runtime、Context、控制和安全退化的七题任务集。
- 新增文件：`eval/tasks/` 下七个任务的 `fixture/`、`instruction.md`、`task.toml`、`verify.py`；`tests/eval/test_eval_verifiers.py`。
- 修改文件：无。
- 删除文件：无。
- 文件职责及实施内容：实现 single-file control、cross-file evidence、todo long task、plan-only、ask-user resume、permission boundary、long-context constraint；每题声明 hard/partial/forbidden checks 与稳定 required evidence；verifier 子进程只读 workspace、离线输出统一 JSON。
- 依赖任务：Task 1、Task 2、Task 3。
- 参考资料定位：原始需求第九、十六和十七节；现有 Plan/Todo/AskUser/Permission 行为测试。
- 完成边界：每题正例、部分完成、禁止修改和重复执行输出稳定；不保存标准完整 Patch、不规定唯一 ToolCall 序列、不访问宿主真实敏感文件。

## Task 5：六维指标、报告与 compare

- 任务目标：从已有结构化事实生成可解释、可重复的六维报告和严格比较。
- 新增文件：`eval/metrics.py`、`eval/reporting.py`；补全 `tests/eval/test_eval_reporting.py`。
- 修改文件：无。
- 删除文件：无。
- 文件职责及实施内容：计算 correctness、context、exploration、efficiency、stability、safety 的原始值、分数、证据和可用性；只规范化可确认的文件/搜索/工具摘要；输出 JSON、Markdown、终端摘要；校验所有实验指纹并拒绝不兼容正式 delta。
- 依赖任务：Task 1 至 Task 4。
- 参考资料定位：原始需求第十一、十三、十六、十七和十九节；公开 AgentEvent、TurnResult、Usage 合同。
- 完成边界：固定 artifacts 重复生成相同报告；安全失败不可被平均掩盖；缺失 diagnostics 显示不可用；不提供数据库、Web UI、远程上传或单一综合排名。

## Task 6：手动入口与开发者文档

- 任务目标：提供完整的人工运行入口和安全操作说明。
- 新增文件：`eval/__init__.py`、`eval/runner.py`、`eval/README.md`。
- 修改文件：无；`pyproject.toml`、`.gitignore`、`tests/conftest.py` 必须保持不动。
- 删除文件：无。
- 文件职责及实施内容：接通 help、smoke、run、compare、clean；默认拒绝真实 Provider，只有显式 live 开关和用户费用授权才允许；文档说明安装、固定条件、成本、结果解释、外部路径、安全清理和回滚。
- 依赖任务：Task 1 至 Task 5。
- 参考资料定位：原始需求第四、五、九、十、十五、十六、十九和二十一节；`docs/README.md` 文档维护规则。
- 完成边界：帮助和错误路径不访问网络；Fake smoke 和 suite 可运行；入口不注册到正式 `uthcode` CLI、不加 CI。

## Task 7：[接入主流程]

- 任务目标：将 B01 全部组件接入唯一 Eval 手动调用链并删除任何被替代的临时入口。
- 新增文件：仅 Task 1 至 Task 6 已列文件中的必要测试数据。
- 修改文件：Task 1 至 Task 6 新增文件及对应测试；不得扩大到 `src/uthcode/**` 或正式 Interface。
- 删除文件：开发过程中被正式 runner 替代的临时脚本或重复入口。
- 文件职责及实施内容：验证 runner 只经 `uthcode.application` 公共导出创建和驱动 Run；保证同一 attempt 只运行一个 Turn、消费一条事件流、运行一个 verifier，并把结果交给统一报告链。
- 依赖任务：Task 1 至 Task 6。
- 参考资料定位：`src/uthcode/application/__init__.py` 与架构边界测试；原始需求第四、六、十二、十四和十九节。
- 完成边界：真实入口闭环完整，且生产源码、正式 CLI/TUI、公共 Event、Permission/Agent Loop 语义保持不动。

## Task 8：[端到端验证]

- 任务目标：从真实 Eval 入口验证正常路径和关键失败路径，并完成包级回归。
- 新增文件：无。
- 修改文件：测试、`eval/README.md`、Checklist 与对应 Feedback；实施完成后按代码事实更新相关当前事实文档。
- 删除文件：无。
- 文件职责及实施内容：执行 Fake 单题 smoke、全 suite 聚合、Permission ASK、未声明交互、timeout、三类错误、严格 compare、clean 拒绝与架构边界；再执行定向回归、全量测试、compileall、pip check、UTF-8 guard 和 diff check。真实 baseline 只在用户另行授权网络和费用后运行。
- 依赖任务：Task 1 至 Task 7。
- 参考资料定位：原始需求第十七和十九节；`docs/README.md` 的包级文档维护映射。
- 完成边界：所有实际执行命令和精确结果进入 Feedback；未授权或未运行的真实 baseline 明确标为未验证，不得伪造通过。

## Task 9：[遗留负担清理]

- 任务目标：确认交付不包含兼容层、废弃实现、不可达代码、重复职责、重复实现或仓库内运行产物。
- 新增文件：无。
- 修改文件：仅为删除 Task 1 至 Task 8 范围内确认的遗留负担所需的文件。
- 删除文件：误生成的仓库内 Eval artifacts/cache/temp home/workspace；无调用方的 Benchmark/Adapter/Registry 抽象；临时 key/endpoint/日志正文/自动授权逻辑。
- 文件职责及实施内容：盘点新增调用链、导入、测试数据和运行产物；验证用户既有未提交改动未被清理；记录精确结果。
- 依赖任务：Task 1 至 Task 8。
- 参考资料定位：原始需求第十八、二十和二十一节；任务开始时的 Git baseline。
- 完成边界：只保留当前七题私有 Eval 所需的最小职责；不引入早期兼容、未来扩展占位或重复 Runtime/Permission 实现。
