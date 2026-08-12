# W04 application-delivery Prompt

请在 `D:\project\Re-UthCode` 中严格按 Task 6 → Task 7 → Task 8 → Task 9 完成 T04 接入、端到端验证和清理，并写入 `docs/work/T04-工具系统/feedback/W04-application-delivery-feedback.md`。开始前确认 W01–W03 已完成并通过；不执行 Git 写操作。

## 必读资料

1. `AGENTS.md`、`SRe-AGENTS.md`、`docs/work/README.md`。
2. T04 原始需求、Spec、Tasks、Checklist 与 W01–W03 Feedback。
3. 当前 Core Tool、Integration Tool、Application generation/bootstrap/runtime context、Fake Provider、Provider contract 和相关测试。
4. `docs/archive/work/T03-SystemPrompt设计/` 的最终 Feedback，重点核对 Provider 快照及 Application 拒绝覆盖 model/system prompt 的返工语义。

## 已确认决策

- Application 是唯一 Headless 工具入口；具体 Integration Tool、Registry 和 Executor 不向调用方暴露。
- 默认六工具按固定顺序装配，使用同一 runtime workdir；显式工具注入完整替代默认集合。
- `start_generation()` 不自动注入工具；调用方显式传定义、执行调用、构造 tool 消息并发起下一次请求。
- CLI/TUI 继续保持单轮行为；T04 不增加 Agent Loop、自动追加消息、Permission 或 UI 工具状态。
- README 必须准确说明工作区边界以及 Bash 是当前用户权限的 unsandboxed process execution。

## 修改范围与顺序

1. Task 6：按清单完成 factory、Application Tool Service、组合根和公开 API。
2. Task 7：用 Fake Provider 从正式入口完成真实文件读取的手动单次往返，并更新 README。
3. Task 8：按 Checklist 执行全部定向、分层和全量验证，仅修复 T04 范围内缺陷。
4. Task 9：扫描并删除 T04 引入或替代的重复入口、临时 helper、兼容层、不可达代码和未来占位。

不得修改 Provider DTO 冻结字段、Provider SDK Adapter、System Prompt、CLI/TUI 行为或后续能力。不得归档或删除任何工作包。

## 实施与验证

- 使用 `conda run --no-capture-output -n re-uthcode ...`。
- 按 Task 边界逐步运行定向测试；最终完整执行 Checklist 中的编译、全部测试组、全量 pytest、pip check、架构/grep 扫描和 diff check。
- 未授权 live Provider 测试必须保持 skip。
- 修改 README 后使用 `uth-utf8-guard` 检查 UTF-8、乱码标记与 Markdown fence。
- Checklist 只允许勾选现有复选框，不修改文字、结构、编号和顺序。

## Feedback

创建 `feedback/W04-application-delivery-feedback.md`，以人工审查为目标说明最终调用链、默认装配、手动往返、修改文件、全部测试结果、Checklist 状态、与任务书差异、风险和遗留负担清理结果。若需要自动 Agent Loop、Permission、Sandbox、放宽路径边界或修改冻结 DTO，停止并记录。

