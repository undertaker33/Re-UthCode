# T09-2 工程收敛与提前抽象清理 Spec

## 1. 背景

UthCode 已完成单 Agent Loop、Provider/Tool/Permission、Run/Turn、持久 Transcript/Timeline、Context Budget/Compact、Slash/TUI 与 Eval 的正式链路。当前主要维护风险不是缺少能力，而是部分历史任务为了理论扩展保留了第二公共入口、通用 Hook 组合、空状态持久格式、多形态 Context 输入和未来命令协议。

本任务以“抽象必须由已经存在的需求证明”为准绳，将测试便利、历史任务书或假设性外部调用方不能证明的扩展面直接删除，同时保持已经进入生产调用链的行为不变。

## 2. 目标

- 只保留 `create_application -> create_run -> start_turn -> AgentLoop` 的公开执行链。
- 把 PLAN 只读与 unfinished-task 完成控制变成 Agent Loop 内固定规则。
- 让 Context Compiler 只接受一种强类型输入，删除身份包装和多形态 estimator。
- 删除 RuntimeLog 和 ApplicationHistory，建立不含空 runtime 文件的 Session v3。
- 让命令 Registry 只包含已实现命令，并以异步 Dispatcher 为唯一执行入口。
- 定点缩小公共导出，删除未被真实类型边界使用的 Protocol。
- 通过正式 Headless、CLI/TUI、Session 与 Context 路径证明行为未回退。

## 3. 能力清单

### Task 1 — 正式 Run/Turn 入口收敛

删除早期 Generation facade、手工 Tool API 墓碑及其专用辅助链；Provider Adapter 测试直接验证 Provider，Application 测试统一走 Run/Turn。

### Task 2 — 固定 Runtime 控制收敛

删除通用 Hook 框架，在 Agent Loop 固定位置直接执行 PLAN 非 READ 拒绝和 unfinished-task 完成阻断。

### Task 3 — Context 合同单轨化

删除五个身份包装、Compiler 独立参数、duck typing、双形态 estimator、同步 Application Compact facade 和 Compactor 双入口。

### Task 4 — Session v3 硬切

删除 RuntimeLog/ApplicationHistory；Session v3 只持久化 metadata、Transcript、Timeline、Tool Result 与 writer lock，并明确拒绝 v1/v2。

### Task 5 — 命令系统收敛

删除五个未实现命令、availability/PROMPT/query 协议与同步 Dispatcher；所有注册命令都有真实 handler。

### Task 6 — 定点公共边界清理

删除本任务涉及的旧 facade、空状态、Hook、Context 包装、命令占位和幽灵 Protocol 导出；其他现有导出不重排。

### Task 7 `[接入主流程]` — 正式组合与文档同步

从唯一组合根验证 Run/Turn、固定控制、Context、Session v3 和异步命令链；同步当前事实与用户文档，不修改冻结工作包。

### Task 8 `[端到端验证]` — Headless、Session 与 TUI 验收

使用离线 Provider、临时配置和临时工作区验证正式 Headless Run、PLAN/Task 控制、Session v3 new/resume/compact 和命令投影。

### Task 9 `[遗留负担清理]` — 否定扫描与全量回归

删除被替代测试和文案，更新能力欠账与 Context 索引，执行架构、Eval、全量测试及 UTF-8 检查。

## 4. 非功能要求

- 保持 `interfaces -> application -> core` 与 Provider SDK 隔离。
- Agent Loop 仍是 RunState 唯一写入者；Tool Batch 保持 FIFO 和 call/result 一一对应。
- PLAN 非 READ 必须在 Permission 前受控拒绝，`full_access` 不能绕过。
- unfinished-task 阻断继续发生在 usage accounting 后、assistant final 权威提交前。
- Transcript/Timeline crash recovery、Instruction State、Tool Result ref、Hard Gate、L4/L5 与 Provider 精确计数保持不变。
- 不新增运行时依赖，不调用真实模型作为必过验收。
- 不保留兼容类、弃用包装、双读写、动态 registry、Plugin 生命周期或 future placeholder。

## 5. 设计骨架

```text
create_application
  -> create_run
  -> start_turn
  -> AgentLoop
       ToolCall: schema/preflight -> fixed PLAN effect check -> Permission -> execute
       final: usage -> fixed unfinished-task check -> authoritative commit
```

```text
Context Application assembly
  -> ContextSourceBundle
       instruction/runtime/environment/protected/protocol: ContextBlock
       current-turn: ContextBlock | Message | str
  -> ContextCompiler.compile(bundle, previous_snapshot=...)
```

```text
Session v3
  metadata.json
  transcript.jsonl
  timeline.jsonl
  writer.lock
  tool-results/
```

## 6. 公共接口变化

- 删除 `GenerationHandle` 及 `UthCodeApplication.start_generation/stream_generation/execute_tool_calls/compile_context`。
- 删除 Runtime Hook 公开类型和 AgentLoop 的 Hook 注入参数。
- 删除 `ApplicationHistory`、RuntimeLog 类型及 Session runtime 访问/追加 API。
- `ContextCompiler.compile` 只接受 Bundle；estimator 只接受 callable；Compactor 只接受 `CompactionPolicy`。
- 删除五个 Context Source 身份包装。
- 删除同步 Command Dispatcher、命令 availability、PROMPT/query 结果与五个占位命令。
- 删除 `SupportsModelLimits`、`SupportsInputTokenCount`、`ToolPreflight`，保留现有可选能力探测行为。

## 7. 能力欠账

无。本任务不实现任何后置能力，也不为未来能力保留入口。实施完成时删除 `OutstandingDebtList.md` 中 T02 占位命令和 T08 假设性 Hook 扩展条目；其他真实欠账不变。

## 8. Out of Scope

- Memory、Dream、Review Prompt、登录流程或配置编辑界面。
- Skill、MCP、Subagent、Multi-Agent、动态 Tool/Hook/plugin registry。
- Persistent Runtime checkpoint 或 active/paused Turn 跨进程恢复。
- Session v1/v2 迁移或兼容读取。
- 全量公共 API 重新设计、包版本发布与 Git 写操作。

## 9. 验收标准

1. 正式 Headless、CLI/TUI 全部只经 Run/Turn 驱动。
2. 固定 PLAN/Task 控制顺序和结果与当前生产语义一致。
3. Context Compiler 只有 Bundle 输入且所有 source 类型明确。
4. 新建 Session 为 v3 且不存在 `runtime.jsonl`；v1/v2 明确 incompatible。
5. Help/Completion 只展示已实现命令，命令只经异步 Dispatcher 执行。
6. 目标旧符号在 `src/` 和活动文档中扫描为零，归档历史不改。
7. 架构、定向、Eval 和全量测试通过，UTF-8 与 Markdown 检查通过。
