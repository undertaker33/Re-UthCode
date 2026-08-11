# W04：分支整合、主流程接入、端到端验证与清理

你在最终保留的物理 worktree `D:\project\Re-UthCode`、分支 `T08-任务规划与执行控制` 工作。连续完成 Task 10、Task 11、Task 12，并负责合并 W01～W03、冲突消解、最终提交和短期 worktree/分支回收。

## 开工前核验

1. 执行 `git rev-parse --show-toplevel`，输出必须是 `D:/project/Re-UthCode`。
2. 执行 `git branch --show-current`，输出必须是 `T08-任务规划与执行控制`。
3. 执行 `git status --short`，除已知任务包基线外不得有未提交业务修改；若 W04 开工时基线未提交，先停止并报告。
4. 执行 `git worktree list --porcelain`，必须能精确看到 W01、W02、W03 三个预期路径与分支。
5. 确认 W01、W02、W03 工作树均干净、各自 Feedback 可从分支 tip 读取，且 W02/W03 tip 均包含 W01 tip。

## 必须完整读取

1. `AGENTS.md`
2. `SRe-AGENTS.md`
3. `docs/work/README.md`
4. `docs/Context-Index.md` 与四层/TUI Context 文档
5. T08 原始需求、Spec、Tasks、Checklist、全部 Prompt
6. 通过 `git show <branch>:<path>` 读取 W01、W02、W03 Feedback
7. 通过 `git diff T08-任务规划与执行控制...<branch>` 分别审查三个分支的生产、测试与文档 diff

任一上游 Feedback 缺失、明确未完成、分支有未提交修改、W02/W03 不包含 W01，或实际分支/路径不匹配时，停止；不得用 W04 静默替代整个上游 Worker。

## 合并顺序与冲突规则

1. 依次本地合并：`T08-W01-core-contracts` → `T08-W02-runtime-application` → `T08-W03-slash-tui`。
2. 使用 merge commit 保留 Worker 边界；禁止 squash、rebase、cherry-pick、强制移动分支或整侧覆盖冲突。
3. 冲突按 Spec/Tasks、当前源码事实、W01 冻结合同、上游 Feedback 和测试统一。优先保留单一 authority、单一执行链和最新已验证语义。
4. 对集成层可修复的 glue、导出、事件接线、类型收窄、测试夹具与小缺陷直接修复并记录；如果必须重写 W01 合同、W02 核心状态机或 W03 交互设计，停止并交回对应 Worker。
5. 每合并一个分支就运行其定向测试，再继续下一个；不得把所有失败推迟到最后。

## 严格工作范围

按顺序完成：

- Task 10：[接入主流程] 正式 Composition 与分支整合；
- Task 11：[端到端验证] Plan + Execution Planning + Steering；
- Task 12：[遗留负担清理] 单 Runtime 收口与 Worktree 回收。

允许修改 W01～W03 已涉及文件以解决真实集成问题，独占以下交付范围：

- `src/uthcode/application/bootstrap.py`
- `src/uthcode/core/__init__.py`
- `src/uthcode/application/__init__.py`
- `tests/test_t08_e2e.py`
- `tests/test_architecture_boundaries.py`
- `tests/test_package.py`
- `docs/Context-Index.md`
- Task 10～12 Checklist 与 `feedback/W04-integration-delivery-feedback.md`

不得扩大到 Context Compression、Memory、Session、Subagent/Multi-Agent 产品、OS Sandbox、第三个 Hook point、第二 AgentLoop 或通用 workflow。

## 主流程与 E2E 要求

- 正式链必须是 `create_application → create_run → mode/start_turn → one AgentLoop → one Application driver → public events/result`。
- Plan Tool View 由 request composition产生；pre-tool Hook 位于 trusted preflight 和 Permission 之间；completion Hook 位于 usage accounting 和 authoritative commit 之间。
- Plan v1/revise/v2/approve、Todo、Steering、Completion Block、最终写入和下一 Turn reset 必须使用正式 Application、Fake Provider、真实 builtin Tool 与临时 workspace。
- request、event、message、ToolCall result 和文件副作用都要有断言；exactly one terminal，取消竞态和 typed pause 互斥必须覆盖。
- Headless 不依赖 TUI；TUI 只通过 Application 公共类型/事件工作。

## 验证与文档

1. 使用 `conda run --no-capture-output -n re-uthcode ...` 执行 Checklist Task 10～12 的全部命令。
2. 全量 pytest、compileall、pip check、`git diff --check`、否定性扫描与 UTF-8 guard 全部通过后，才能宣称完成。
3. 只勾选有真实证据的项；合并后核对 Task 1～9 checkbox 与三个 Feedback 一致。
4. 若 `feedback/` 尚不存在，先创建该目录；首次创建 `feedback/W04-integration-delivery-feedback.md`，记录合并 commit、冲突与选择、正式调用链、E2E、全量测试、删除项、风险和 worktree 回收。
5. 只有 Checklist 全部完成、四份 Feedback 齐全且源码真实接入时，才把 `docs/Context-Index.md` 的 T08 从 `not_implemented` 改为 `implemented_unarchived`；不得移动/归档工作包。
6. 对所有改动 Markdown 执行 UTF-8 guard。

## 最终 Git 提交与 Worktree 回收

- 本 Prompt 明确授权在最终 T08 分支执行 W01～W03 的本地 merge commit、集成修复 commit 和文档/验收 commit。
- 禁止 push、删远端、改 origin、合并到 main、删除 main/T05/最终 T08 分支。
- 最终提交前检查 staged scope、完整 diff、测试结果和工作树状态。
- 清理前逐一执行 `git merge-base --is-ancestor <worker-branch> HEAD`，三个退出码都必须为 0。
- 将预期路径精确解析为：
  - `D:\project\Re-UthCode-T08-W01`
  - `D:\project\Re-UthCode-T08-W02`
  - `D:\project\Re-UthCode-T08-W03`
- 核对三者均是 `git worktree list --porcelain` 中登记的 worktree，且不等于 `D:\project\Re-UthCode`、`D:\project`、任何用户目录或盘符根；任一不满足则停止。
- 使用 `git worktree remove <exact-path>` 逐一回收；不得用 glob、环境变量展开或跨 shell 拼接递归删除。
- 仅在对应 worktree 成功移除且 tip 已合入后，使用 `git branch -d` 删除 W01、W02、W03 本地短期分支；禁止 `-D`。
- 最终 `git worktree list` 只剩主工作树，本地保留 main、T05 与最终 T08，工作树干净，远端未改变。

若任何必需测试失败、Tool 是否已产生副作用不确定、某 Worker tip 未合入、路径核验失败或 Checklist/Feedback 不一致，保留相关 worktree 和分支，记录阻塞，不得为了“清理完成”强制删除。
