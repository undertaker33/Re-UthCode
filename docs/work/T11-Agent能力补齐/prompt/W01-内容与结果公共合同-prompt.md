# W01-内容与结果公共合同

只有用户显式指定本文件执行时才开始实施。你负责 T01 统一内容与正式输入 → T02 工具失败、副作用与进度合同 → T03 三协议图片序列化，必须严格按此顺序完成，不执行其他 Worker 的 Task。

## 必读与前置

1. 仓库根 `AGENTS.md`、`docs/README.md`、`docs/Context-Index.md`、`docs/rules/WorkPackageRules.md`；涉及新增决策时读 `docs/rules/UserDecisionBoundary.md`，涉及后置边界读 `docs/OutstandingDebtList.md`。
2. 完整读取 `docs/work/T11-Agent能力补齐/T11-Agent能力补齐.md`、`T11-Agent能力补齐-spec.md`、`T11-Agent能力补齐-tasks.md`、`T11-Agent能力补齐-checklist.md`（后三者在同一目录）。不依赖聊天记录；原需求第3节九项决定与第4节协议均已授权。
3. 按本 Worker 命中职责读取 `docs/context/A01-AgentRuntime/AgentRuntime-Context.md`、`A02-Control/Control-Context.md`、`A03-State/State-Context.md`、`A04-Orchestration/Orchestration-Context.md`（后三者相对 `docs/context/`），涉及 Desktop 时读 `docs/context/GUI/GUI-Context.md`。只沿任务读取源码，不扫描归档全库。
4. 先核对当前源码与 Tasks 本地基线；无前序 Worker。
5. 使用既有 `re-uthcode` Conda 环境；Python 与新依赖范围以 `pyproject.toml` 为准；不另建环境或构建体系。

## 修改范围与源码入口

本 Worker 写范围为 Tasks 的 T01、T02、T03 对应文件组 F01 F03 F04 F16 F02 F25 F07 F23、其真实调用点和 Checklist 指定测试；涉及文档只按当前已实现能力同步维护。下面路径来自原始需求文件组，其中新增路径尚不存在，禁止因表列就建占位文件：

- F01：`src/uthcode/core/provider.py`；扩展图片/文件引用和 ToolResult 内容序列；JSON round-trip；更新 Message 校验。
- F03：`src/uthcode/core/agent.py`、`core/agent_events.py`、`application/runs.py`；新输入值、闭合终态、工具进度路由、移除累计轮数 gate；有限异常检测和失败原因。
- F04：`src/uthcode/core/history.py`、`core/context.py`、`core/compaction.py`；新内容序列化、引用覆盖、预算计量和压缩来源保留。
- F16：`src/uthcode/integrations/tools/factory.py`、`application/bootstrap.py`；在正式启动时组合新能力、按配置/模型暴露可用工具、绑定会话资源。
- F02：`src/uthcode/core/tool.py`、`application/tools.py`；失败结构、副作用、进度出口；物化与脱敏；新工具注册组合。
- F25：`AGENTS.md` 和第 9 节文档；用户已批准的搜索秘密/事件正文边界、运行上限修订及使用说明。
- F07：`src/uthcode/integrations/providers/anthropic.py`、`openai_responses.py`、`openai_compat.py`；用户/工具图片的序列化与计量适配，支持失败明确映射。
- F23：`pyproject.toml`、`desktop/packaging/uthcode-runtime.spec`；依赖声明、平台 marker 与 Python 原生资源打包。

必须同时读取 Tasks 的“本地核验补充”和“官方参考核验”；其中补齐的实际路径按所属 F 组属于本 Worker 的范围。

## 已确认决定与执行约束

- T01：扩展 MessagePart 与 ToolResult 内容序列；定义同一文字/附件输入值，替换 start_turn、Steering、Headless、CLI/TUI/Desktop 的生产调用点及历史编码。文字入口只构造同一输入；SDK native item 身份规则保留。文件字节仍由 Integration 解析，Core 不读取文件。 完成边界：文字主链和新内容 round-trip 可运行；未实现的附件导入由 T04/T06 完成，不留 legacy 执行路径。
- T02：扩展既有 Outcome、failure.kind/retryable 与 side_effect；执行和 materialization 分离。普通错误返回模型；unknown 立即闭合剩余 FIFO ToolCall 为受控 not_executed 并终止。提供受限观察出口、归属及有界跨 chunk 脱敏。此处同步 AGENTS 的受控进度正文窄修订；不开放原参数或写入正文。 完成边界：写成功但保存失败不重复写；unknown 不纠偏重试；进度不写 RunState、不灌入模型历史；真实日志展示留 T09。
- T03：Anthropic 将图片放入 user/image 及同 ID tool_result；Responses 使用 input_image 与结构化 function_call_output；compatible 闭合 tool 文本后追加带调用身份和来源的 user 图片 wire 投影，不改 Core 历史角色。按实际安装 SDK schema 测试；资源解析边界可先使用受控 fixture，生产资产接入 T04。 完成边界：三协议真实 SDK 请求结构可检验；实际 Provider 内容理解证据必须由 T19 补齐，不能在本 Task 只凭 Mock 勾选 A02。

公共类型、会话内资产、异常截停及搜索秘密/受控进度的窄修订已被需求授权，不为同一决定重复询问。不得削减 15 项能力；不添加范围外服务、Runtime、兼容层或通用框架。普通工程选择自行完成；若新证据实质改变冻结范围，按规则记录并停止受影响范围。

共享 Core/配置/Bridge/工厂区域在当前 Worker 内保持单写者。可以委派无重叠且已授权的子任务，不自行执行未派发的后续 Worker，不为此建设全仓锁。首次派发后原始需求、Spec、Tasks、所有 Prompt 与 Checklist 文字冻结；仅可勾选已有完成框，Feedback 追加。禁止修改其他冻结工作包、Git commit/push/merge/rebase/tag/release 或归档。

## 验证与反馈

执行 Checklist 的 T01、T02、T03，覆盖 A01 A08 A02。按真实改动运行最小定向测试；涉及架构边界执行 `python -m pytest tests/test_architecture_boundaries.py -q`。引用前序有效证据不等于跳过当前未覆盖条件。真实 Provider、Windows/POSIX PTY、安装产物和官方评分不得以 Mock/CDP 代替；缺条件保留未完成，继续其他独立授权工作。

首次实施创建 `docs/work/T11-Agent能力补齐/feedback/W01-内容与结果公共合同-feedback.md`，之后只向同一文件追加返工轮次。记录实际改动、关键调用链与理由、文件、命令及精确结果、Checklist 项、差异、未验证项/风险/遗留问题和清理结果；不复制任务书、不新建 retry/v2 文件。中文文档 UTF-8 与围栏检查通过后交付。
