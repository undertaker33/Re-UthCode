# W01 config-boundary Prompt

请在 `D:\project\Re-UthCode` 中完整实施 T04 的 Task 1，完成后写入 `docs/work/T04-工具系统/feedback/W01-config-boundary-feedback.md`。只执行本 Worker，不开始 Task 2–Task 9，不执行 Git 写操作。

## 必读资料

1. `AGENTS.md`
2. `SRe-AGENTS.md`
3. `docs/work/README.md`
4. `docs/work/T04-工具系统/T04-工具系统.md`
5. `docs/work/T04-工具系统/T04-工具系统-spec.md`
6. `docs/work/T04-工具系统/T04-工具系统-tasks.md`
7. `docs/work/T04-工具系统/T04-工具系统-checklist.md`
8. `docs/archive/work/T01-项目骨架与Provider抽象/`、`T01-2-移除pydantic改用原生SDK/`、`T02-SlashCommand与默认TUI/`、`T03-SystemPrompt设计/` 中与配置、Application 边界和最终返工有关的正式文档及 Feedback。
9. 当前配置 loader、Application bootstrap/configuration、架构测试、配置测试和 package 测试。

## 已确认决策

- Integration 负责配置发现、解析、验证和合并，只返回自身拥有的不可变原始数据。
- Application 负责把原始数据转换为唯一的 `EffectiveConfig`。
- 不改变配置 TOML、发现规则、合并优先级、秘密来源、模型选择和用户默认模型写回行为。
- Integration 不得导入 Application/Interface，也不再公开旧有效配置加载入口。

## 修改范围

严格按 Tasks 的 Task 1 文件清单新增或修改。不得实现 Core Tool、内置工具、Application Tool API、Interface 或 Provider 变更。不得触碰用户已归档的 T01–T03 文件。

## 实施与验证

- 使用 `conda run --no-capture-output -n re-uthcode ...` 执行 Python 与 pytest。
- 先补足能捕获反向依赖和原始数据语义的测试，再做最小实现并保持全部配置回归。
- 完成 Task 1 Checklist 的全部项目，但只勾选已有复选框，不改其文字、编号或顺序。
- 对修改的 Markdown 运行 UTF-8 guard；对源码运行对应测试与 `git diff --check`。

## Feedback

首次执行创建 `feedback/W01-config-boundary-feedback.md`，简洁记录实际机制、文件、测试结果、Checklist 状态、偏差、风险和遗留负担清理结果。若发现必须改变冻结配置行为或扩大到工具实现，停止并在 Feedback 记录，不得修改冻结工作包。

