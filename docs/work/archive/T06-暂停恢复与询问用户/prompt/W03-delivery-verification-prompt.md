# W03：主流程接入、端到端验证与清理

你负责连续完成 T06 的 Task 6、Task 7、Task 8。必须在 W01、W02 完成并存在有效 Feedback 后开工。

## 开工前必读

1. `AGENTS.md`
2. `SRe-AGENTS.md`
3. `docs/work/README.md`
4. `docs/work/T06-暂停恢复与询问用户/T06-暂停恢复与询问用户.md`
5. `docs/work/T06-暂停恢复与询问用户/T06-暂停恢复与询问用户-spec.md`
6. `docs/work/T06-暂停恢复与询问用户/T06-暂停恢复与询问用户-tasks.md`
7. `docs/work/T06-暂停恢复与询问用户/T06-暂停恢复与询问用户-checklist.md`
8. `docs/work/T06-暂停恢复与询问用户/feedback/W01-interaction-runtime-control-feedback.md`
9. `docs/work/T06-暂停恢复与询问用户/feedback/W02-interface-interaction-feedback.md`
10. Task 6～8 涉及的主流程、集成测试、端到端测试与打包配置

若任一上游 Feedback 缺失或标记未完成，立即停止并写明阻塞，不得用本 Worker 重做上游职责。

## 工作范围

按顺序完成：

- Task 6：[接入主流程] 贯通交互运行链路；
- Task 7：[端到端验证] 验证暂停、恢复与询问用户；
- Task 8：[遗留负担清理] 删除旧入口并完成交付检查。

允许修改的范围以 Tasks 中 Task 6～8 的文件级职责为准。发现上游实现缺陷时先记录阻塞与最小复现，不得悄然改写上游协议或状态机。

## 验证重点

- 同一 Turn 的 Ask 调用、暂停、回答、恢复、再次暂停和最终结束形成唯一事件序列。
- CLI、TUI 和无界面调用都只依赖 Application 公共边界。
- `exec` 暂停取消、错误回答、过期回答、重复回答、用户取消和异常清理具有端到端证据。
- Anthropic、OpenAI Responses、OpenAI Compatible 三组 Provider 集成测试通过，第三方类型不进入 Core。
- Core 暂停路径不存在用户回答 waiter 或异步协调原语；Application 终态后不存在遗留驱动任务、Future、waiter 或事件消费任务。
- Ask 只存在于 Application 控制工具路径，不进入 Core 普通工具、integrations 或用户注册配置。
- 删除旧入口、旧测试、不可达分支和重复职责实现；不得保留兼容层、别名或双轨逻辑。

## 实施与验证要求

1. 完成接线后执行指定端到端用例、三组 Provider 集成测试及全量测试。
2. 执行编译、安装、负向扫描、`git diff --check`、UTF-8、Markdown 围栏与工作区状态检查。
3. 使用 `conda run --no-capture-output -n re-uthcode ...` 执行 Python、pytest 和项目工具。
4. 只勾选有实际命令输出或代码证据支持的 Checklist 项。
5. 不执行 Git 写操作，不提交、不暂存、不推送。
6. 不修改需求原文。

## 交付

完成 Task 6～8 后：

- 勾选 Checklist 中 Task 6、Task 7、Task 8 的真实完成项；
- 写入 `docs/work/T06-暂停恢复与询问用户/feedback/W03-delivery-verification-feedback.md`；
- Feedback 必须包含接线结果、删除项、全部测试命令与输出摘要、三组 Provider 结果、负向扫描、资源清理证据、未决风险和逐项验收证据；
- 若任一必需验收项未通过，明确标记未完成，不得宣称 T06 可验收。
