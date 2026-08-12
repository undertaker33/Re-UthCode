# T06 暂停恢复与询问用户 Spec

## 1. 背景

T06 在 T05 的唯一 Agent Loop、Application Run/Turn 入口、单消费者事件流与 terminal-only 结果边界上，为同一进程、同一内存和同一活动 Turn 增加合作式暂停、结构化询问和恢复能力。

本任务不引入会话持久化、重启恢复、Tool 重放或第二套 Agent Loop。

## 2. 目标

1. 建立与 UI 无关、不可变、JSON-safe 的暂停、问题和恢复协议。
2. 用显式 continuation 保存 Core 从暂停边界继续所需的最小业务事实。
3. 由 Application 私有异步协调对象，在不泄漏给 Core、Tool 或 Interface 的前提下维持同一 Turn 事件流与结果。
4. 支持 Provider 用户暂停、普通 Tool 安全边界暂停、结构化询问以及网络/限流重试。
5. 保持 FIFO、原 ToolCall ID、iteration、Usage、预算和唯一终态语义。
6. 为 Headless、CLI 和 TUI 提供同一 Application 控制面。

## 3. 能力清单

### Task 1 — Core 交互协议与事件

- 定义三类暂停、四类原因和三类匹配的恢复响应。
- 定义文本、单选、多选、Other 问题及稳定答案序列化。
- 定义保留的 `AskUserQuestion` 控制工具协议。
- 增加暂停中、请求输入、已暂停和已恢复事件。

### Task 2 — Core 显式 Continuation 与暂停边界

- Agent Loop 运行至暂停边界时返回可继续的事实，不在 Core 中等待用户响应。
- Provider 用户暂停与网络/限流暂停从同一 iteration 请求边界继续。
- 普通 Tool 完成当前调用后在下一调用前暂停；已完成结果不重放。
- 结构化询问在原 ToolCall 位置暂停，合法答案闭合原调用。
- continuation 不包含异步协调对象、Python 栈帧、SDK、Tool 实例、UI 对象或持久化字段。

### Task 3 — Application Turn 协调与控制工具隔离

- Application 拥有当前 Turn 的 driver、事件队列、terminal result 和暂停响应 waiter。
- Headless 通过现有 Turn 句柄请求暂停、读取 pending 并提交一次响应。
- paused Turn 继续占用 Run 的活动槽位；事件流跨暂停保持，结果只在终态返回。
- 控制工具只追加至自动 Agent 路径，不进入普通 Registry、Integration 或手动 Tool API。

### Task 4 — 非交互 CLI 暂停收口

- CLI 遇到暂停后输出安全摘要、立即取消并消费至取消终态。
- 暂停路径不输出伪 final，使用普通失败退出语义。

### Task 5 — 默认 TUI 暂停与结构化问答

- Esc 先由顶层交互上下文消费，只有对话根页面的新双 Esc 才请求暂停。
- 支持 Resume/Cancel、Retry/Cancel 及文本/单选/多选/Other/返回/复核/提交。
- 保持非全屏、无鼠标、不清除宿主历史和 append-only scrollback。

### Task 6 [接入主流程] — 统一活动 Turn 调用链

- 统一 Headless/CLI/TUI 通过 Application 驱动 Core 分段执行。
- 删除被替代的 Core waiter、根页面双 Esc 直接取消及重复运行路径。
- 保留低层 Generation API、手动 Tool API、六个普通 Tool 和 Provider wire 边界。

### Task 7 [端到端验证] — Headless、CLI 与 TUI 全链验收

- 从三个正式入口验证主动暂停、问答、网络重试、取消竞态和终态。
- 回归 Provider、Tool、Usage、FIFO、多 Turn 及现有 Interface 能力。

### Task 8 [遗留负担清理] — 删除重复职责与持久恢复占位

- 删除无调用方的旧 waiter、旧分支、重复状态和兼容入口。
- 固化无 recovery/session/storage/journal/checkpoint/replay 及分层边界。

## 4. 设计骨架

### 4.1 分层所有权

```text
Interface
    ↓ Application 公开 Turn API
Application driver
    ├── 私有 Task / Queue / Future / Event
    ├── 单事件流与 terminal result
    └── typed response 校验与一次性提交
            ↓
Core Agent execution segment
    ├── 运行至 pause 或 terminal 边界
    ├── 产生 AgentEvent
    └── 显式 continuation facts
```

Core 暂停边界不等待用户响应。Application 接收暂停边界后发布 pending，在私有 waiter 上等待；合法响应转换为 typed Core 继续命令。

### 4.2 Continuation 事实

continuation 只包含执行下一段所需的不可变事实：阶段、iteration、Provider 是否重试、assistant tool message、不可变 ToolCall 列表、已完成结果、下一索引和当前 PauseRequest。

continuation 不包含 Task、Future、Queue、Event、Lock、Python 栈帧、Provider SDK 对象、Tool 实例、Exception、UI 对象或持久化元数据。

### 4.3 暂停边界

- Provider 用户暂停：取消当前 attempt token，丢弃未权威提交流，返回同 iteration 请求边界。
- Provider 不可用：只有网络和限流返回可 retry 边界。
- Tool 暂停：当前普通 Tool 正常闭合，暂停边界保存已完成结果和下一索引。
- 询问用户：暂停边界保存原 ToolCall ID 和问题，回答后转换为原 ID 结果。

## 5. 非功能要求

- 依赖方向保持 `interfaces → application → core`；Core 不反向依赖外层。
- Interface 不直接导入 Core、Integration 或 Provider SDK。
- 公开 payload 不包含答案活动摘要、异常、密钥、请求头、原始响应或 traceback。
- 暂停不改变 Run 四种生命周期状态。
- 不增加运行时依赖，不使用并行 Tool Batch、自动后台 retry 或固定超时。
- 不提供旧 API、旧行为或早期 T06 实现的兼容层。

## 6. Out of Scope

- 进程/应用/机器重启恢复。
- Session、快照、检查点、Journal、Lease、Fencing、文件或数据库持久化。
- Provider 请求、Tool 副作用、Python 调用栈或协程局部变量重放。
- Permission Ask、Plan Mode、Todo、MCP elicitation、secret/password 问题。
- 新 Slash Command、会话列表、恢复 UI、全屏或鼠标交互。
- Provider wire DTO、普通 Tool Protocol/schema、六个内置 Tool、System Prompt 正文和配置体系重构。

## 7. 验收标准

1. 公开交互协议不可变、可严格 JSON 往返且不含运行对象。
2. Core 暂停 continuation 是显式事实，不持有或等待任何异步协调对象。
3. Application 私有暂停 waiter、事件流和 terminal result 协调，terminal/shutdown 后全部清理。
4. Provider 用户暂停、网络和限流均从同 iteration 继续，不重复 Usage 或提交 partial conversation。
5. Tool 暂停不中断当前普通 Tool，已完成调用不重放，后续调用不抢跑。
6. `AskUserQuestion` 可通过 Headless 完整往返，答案回填原 ToolCall ID。
7. wrong/stale/duplicate response 不改变 pending；cancel 在竞态中优先并且 terminal 唯一。
8. CLI 遇到暂停不悬挂、不输出伪 final；TUI 的 Esc 不跨交互上下文串联。
9. 正式链路唯一，不存在 Core 暂停 waiter、第二套 Agent Loop、持久恢复或兼容负担。
10. 全量离线测试、编译、依赖、差异、UTF-8 和否定性扫描全部通过。
