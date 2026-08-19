# W01 Worker Prompt：动态模型限制与确定性请求安全链

你负责执行 T09-1 的 T01。只实施本 Prompt 明确范围，不执行 T02～T08，不做 Git commit/push/merge/归档。

## 开始前必须完整读取

1. `AGENTS.md`
2. `docs/README.md`、`docs/Context-Index.md`
3. `docs/rules/WorkPackageRules.md`
4. `docs/work/T09-1-Context预算与Compact协议补齐/` 下任务书、Spec、Tasks、Checklist
5. 当前 `application/configuration.py`、`integrations/config/loader.py`、`core/context.py`、`core/provider.py`、`application/context.py`、`application/generation.py`、`core/agent.py` 与相关测试

## 目标与完成边界

在同一竖切任务中完成：用户/项目配置 authority、Provider 分维 runtime limits、Pressure Estimate 与 Preflight Safety Count/Estimate、集中 allowance、Auto/Hard Gate、L1-L3、正式 Application→Compiler→AgentLoop→Provider request path，并删除固定 `258_000` runtime authority。T01 结束时必须可运行、可测试、可审查、可回退，不允许把正式调用方再推给 T03/T06。

## 冻结语义

- 只允许用户显式配置和可选可靠 Provider runtime metadata。不得建立 bundled model metadata、本地型号表、catalog 或硬编码默认窗口。
- 用户 `context_window` 可缺省，但用户缺省且 Provider 也无可靠 input limit 时必须 fail closed。
- 项目层只能在用户层已有值时保持/收紧 `context_window`；补造缺失值或扩大值硬失败。
- `max_input_tokens`、`max_output_tokens`、可选 `max_combined_tokens` 是不同维度；unknown 保持 unknown，不折叠成单一 `E`。
- Pressure Estimate 服务 Auto Gate；Preflight Safety Count/Estimate 服务发送前 Hard Gate；近似计数不得标成 mathematically exact。
- Hard Gate 是 UthCode operating/known Provider limits 的 fail-closed preflight；Provider overflow 仍是最终外部裁决。
- `core/agent.py` 已经 await sync/awaitable preparer 和 overflow handler。复用现有合同；不要新增第二套 Protocol、Manager 或为“支持 async”重复改造 AgentLoop。

## 实施要求

- 使用 `conda run --no-capture-output -n re-uthcode ...`。
- 先写/调整测试，再完成最小实现。final request accounting 至少覆盖 instruction、messages、tools、known framing、requested output reserve。
- input/output/combined limit 各自校验；每次 L1-L3 后 rebuild/re-gate；protected/current/tool pair 不可拆。
- 25K/1M profiles 证明 adaptive capped policy；构造 Auto pressure + Hard-safe 场景；required facts 超限时 fake Provider call count 为 0。
- Provider metadata 必须通过 fake client，无真实网络必测。
- 不修改 T02 History/Session authority，不写未来 L4/L5/manual command。

## 验证与反馈

至少执行 Checklist T01 的完整命令、受影响架构测试和你新增测试。逐项核对 T01 Checklist，完成项才勾选。把实际文件、精确命令、passed/failed/skipped、未验证项、风险写入：

`docs/work/T09-1-Context预算与Compact协议补齐/feedback/W01-dynamic-limits-request-safety-feedback.md`

若任务书错误、需扩大范围或与冻结语义冲突，记录 Feedback 并停止相关范围，不自行修改任务包定义。
