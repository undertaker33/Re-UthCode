# W02 core-tool-runtime Prompt

请在 `D:\project\Re-UthCode` 中完整实施 T04 的 Task 2，完成后写入 `docs/work/T04-工具系统/feedback/W02-core-tool-runtime-feedback.md`。开始前确认 W01 已完成并通过；只执行本 Worker，不开始 Task 3–Task 9，不执行 Git 写操作。

## 必读资料

1. `AGENTS.md`、`SRe-AGENTS.md`、`docs/work/README.md`。
2. T04 原始需求、Spec、Tasks、Checklist 和 W01 Feedback。
3. `src/uthcode/core/provider.py`、`src/uthcode/core/__init__.py`、`tests/test_provider_contract.py`、`tests/test_package.py`。
4. 原 UthCode 固定提交 `1c3507b761e48ac38d846bc39700ce0039f84a04` 中的 Tool 契约、Registry 和 Executor；提交 `2001d10a316d4d68371b47915c511eade261fb81` 的修复仅作历史证据，不复制旧 API。

## 已确认决策

- 既有 `ToolDefinition`、`ToolCallPart`、`ToolResultPart`、`JsonPayload` 和 `CancellationToken` 是唯一 DTO。
- Core 拥有 Tool Protocol、Registry、schema 校验、FIFO 调度、错误归一和统一截断。
- 使用成熟 `jsonschema` 依赖；第三方对象不得越过 Core。
- 所有公开集合返回 tuple；重复名硬失败；一个 batch 一次只启动一个工具。
- 当前调用失败后继续；取消后不启动后续工具，但每个 call 都必须有同 ID 结果。

## 修改范围

严格限于 Task 2 文件清单。不得实现内置工具、文件系统、进程、Application Tool API、Permission、Agent Loop 或未来字段。不得改变 Provider DTO 的冻结字段。

## 实施与验证

- 使用 `conda run --no-capture-output -n re-uthcode ...`。
- 以可观察测试覆盖 schema 自身、duplicate、顺序、unknown、invalid arguments、普通异常、batch 取消和只截断一次。
- 完成 Task 2 Checklist，只勾选现有复选框。
- 运行定向测试、受影响 Provider/package 回归、`python -m pip check` 和 `git diff --check`。

## Feedback

创建 `feedback/W02-core-tool-runtime-feedback.md`，说明权威类型、FIFO/取消/错误收口机制、修改文件、测试结果、Checklist 状态与风险。若必须改 Provider DTO、引入第二套参数模型或未来能力，停止并记录。

