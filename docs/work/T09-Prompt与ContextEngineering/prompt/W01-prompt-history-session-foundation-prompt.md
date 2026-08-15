# W01 Prompt / Instructions / History Foundation Worker Prompt

## 任务范围

只执行：

- Task 1：Prompt Asset、Context Source 与权限平面
- Task 2：AGENTS / Project Instructions Loader
- Task 3：Canonical History 与 Projection 基础

先完整读取任务书、Spec、Tasks、Checklist、项目路由与规则，以及旧 UthCode Day7 AGENTS 证据。当前代码事实优先；旧仓库只恢复产品语义，不复制 LangGraph/旧工具结构。

## 必须读取

- `AGENTS.md`、`docs/README.md`、`docs/Context-Index.md`、`docs/rules/WorkPackageRules.md`。
- 本工作包四个主文件；T03/T04/T05/T08 相关当前 Context；`core/prompt.py`、`core/provider.py`、`core/agent.py`、Application tool/run composition 与对应测试。
- 旧 UthCode Day7 任务书、InstructionService/models/parser/errors/tests 中与 AGENTS 冻结语义直接相关的部分。

## 必须交付

1. Public Coding Prompt 迁入版本化 package asset；Core Runtime Contract 继续由 Core 权威维护，两者不得合并成可编辑 asset。
2. 定义 Instruction Plane、Contextual Plane、typed authority 与 Stable Instruction Prefix Epoch；Projection 始终是历史权限，Runtime facts 不是 Instructions。
3. 当前架构中的 AGENTS Loader：用户级、项目根、目录级惰性 scope；输出当前有效 instruction set，新 scope/内容变化创建 epoch，未变化复用当前 epoch。
4. 严格实现历史语义：整行 `@include(...)`、递归、最多 3 个额外引用、物理路径去重、Windows case-fold、循环/越界/代码块处理和显式诊断。
5. append-only History、strict sequence、semantic unit、Projection revision；ToolCall/ToolResult 不拆。
6. 写入 `feedback/W01-feedback.md`，同步 Tasks/Checklist 状态。

## 禁止

- 不把裸 `@file` 发明成另一套语法，不把仓库自身 AGENTS 当成 Runtime 已实现事实。
- 不实现 T09-1 Model Limits。
- 本 Worker 也不实现 T09 后续 Task 中的 Compiler、Session Store、Compaction、Slash/TUI、Eval。
- 不实施 Memory/Skill/MCP/Subagent，不做 Git 写入。

## 验证

定向覆盖 source authority、ordinary history 伪造 AGENTS/Project/Runtime 标签不能进入 Instruction Plane、prefix ordering、目录 AGENTS epoch change/stable reuse、全部 AGENTS frozen semantics、History append-only、Projection non-escalation、semantic-unit 原子性；按改动运行架构测试。

## Feedback

首次创建 `feedback/W01-prompt-history-session-foundation-feedback.md`，记录修改文件、精确命令/结果、Checklist 证据、与历史/代码差异、风险和未完成项。发现需扩大产品或架构边界时停止相关范围，其余继续。
