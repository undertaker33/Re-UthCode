# T06 暂停恢复与询问用户 Tasks

## 1. Worker 分组与依赖

| Worker | 严格顺序 | 职责 | 依赖 |
| --- | --- | --- | --- |
| `W01-interaction-runtime-control` | Task 1 → Task 2 → Task 3 | 交互协议、Core 显式 continuation、Application 私有协调 | 无 |
| `W02-interface-interaction` | Task 4 → Task 5 | CLI 暂停收口与 TUI 交互 | W01 完成 |
| `W03-delivery-verification` | Task 6 → Task 7 → Task 8 | 主流程收口、端到端验证、遗留清理 | W01、W02 完成 |

Task 2 与 Task 3 必须由同一 Worker 连续完成：Core 不得为了形成中间可运行版本而持有暂停 waiter，Application 协调必须在同一 Worker 内接管暂停等待。

---

## Task 1 — Core 交互协议与事件

### 任务目标

建立与 UI、Application 协调和 Integration 无关的不可变暂停/问答协议。

### 新增文件

- `src/uthcode/core/interaction.py`
  - 定义 `PauseKind`、`PauseReason`、`QuestionKind`、`QuestionOption`、`UserQuestion`、`UserInputRequest`、`PauseRequest` 和三类 typed response。
  - 校验 1–4 个必答问题、2–6 个唯一选项、text/single/multi/Other 答案与所有关联 ID。
  - 定义严格 `ASK_USER_TOOL_DEFINITION`，各层拒绝额外字段。
  - 只使用 frozen dataclass/Enum/json 与现有 Core DTO；不含异步、UI、SDK 或持久化对象。
- `tests/test_agent_interaction.py`
  - 覆盖合法往返、数量边界、类型错误、空值、额外/缺失字段、ID 错配、答案边界和 schema。

### 修改文件

- `src/uthcode/core/agent_events.py`：增加 `TurnPausing`、`UserInputRequested`、`TurnPaused`、`TurnResumed` 及严格序列化。
- `src/uthcode/core/__init__.py`：导出公共交互协议与事件，不导出内部 continuation 或协调对象。
- `tests/test_package.py`：验证允许/禁止导出。

### 删除文件

无。

### 依赖任务

无。

### 参考资料定位

原始需求第 5、7、8.1–8.5、10 节；现有 Provider DTO/Event 序列化；固定 Codex request/response ID 与 MewCode 多问题交互参考。

### 完成边界

只完成协议、schema 和事件，不启动 Provider/Tool，不建立任何 waiter。

---

## Task 2 — Core 显式 Continuation 与暂停边界

### 任务目标

将唯一 Agent Loop 改为可运行至 pause/terminal 边界的分段执行引擎，Core 不等待恢复响应。

### 新增文件

无。

### 修改文件

- `src/uthcode/core/agent.py`
  - 定义不导出的显式 continuation，固定保存 stage、iteration、provider retry、assistant tool message、tool calls、completed results、next index 和 pending pause。
  - Core 执行段产生事件并以 paused 或 terminal 边界结束；paused 边界返回后不保留等待响应的协程栈。
  - 用户 pause 仅设置事实并取消当前 Provider attempt token；网络/限流返回 provider retry 边界。
  - Tool 暂停保存已完成结果和 next index；AskUser 恢复命令生成原 call ID 结果。
  - Core 不新增暂停 Future/Event/Queue/Task/Lock，不保存 Python frame、SDK、Tool 实例或 Exception。
  - `RunStatus`、RunState、Usage、FIFO、预算和唯一 terminal 语义保持。
- `tests/test_agent_loop.py`
  - 直接驱动 Core 执行段，验证 paused boundary 返回后没有未决 waiter/task/frame。
  - 覆盖 Provider partial、异步 request preparer、Tool 安全边界、AskUser Batch、network/rate retry、非可恢复错误、ID 错配、取消和 terminal。
- `tests/test_package.py`：禁止 continuation 与 Core 暂停协调类型公开导出。

### 删除文件

无计划删除整个文件。必须删除 `agent.py` 内 Core 暂停 waiter 及任何等价协调替代。

### 依赖任务

Task 1。

### 参考资料定位

原始需求第 8.6–8.9 节；T05 Agent Loop、Provider terminal-held-until-EOF 与 Tool FIFO 语义。

### 完成边界

Core 只返回显式边界与事实，不保证独立等待用户的长生命运行。Task 2 完成后必须立即继续 Task 3，不单独交付。

---

## Task 3 — Application Turn 协调与控制工具隔离

### 任务目标

由 Application 驱动 Core 执行段、等待暂停响应并对外维持单事件流和 terminal-only result。

### 新增文件

无。

### 修改文件

- `src/uthcode/application/runs.py`
  - Application 私有 Turn driver、事件 queue、result future 和 response waiter；暂停解决、terminal、cancel、shutdown 后必须清理。
  - `TurnHandle` 提供 pause、pending pause 与 typed resume；wrong/stale/duplicate response 不改变状态。
  - driver 连续消费 Core 执行段：遇 paused 时发布 pending 并等待，合法响应后驱动下一段，terminal 时完成结果。
- `src/uthcode/application/generation.py`：自动 Agent 请求在普通 Tool definitions 后只追加一次 AskUser。
- `src/uthcode/application/tools.py`：普通 Registry 拒绝保留名，手动 Tool API 不执行控制工具。
- `src/uthcode/application/__init__.py`：导出 Headless 所需暂停请求与响应类型。
- `tests/test_application_runs.py`：覆盖 driver、pending 可见期、单流、result 等待、active slot、ID 校验、竞态和协调清理。
- `tests/test_application_tools.py`：覆盖保留名、追加顺序、普通 Tool 回归与手动 API 隔离。
- `tests/test_package.py`：验证只通过 Application 完成 Headless 全链，无 restore/persist API。

### 删除文件

无。

### 依赖任务

Task 2。

### 参考资料定位

原始需求第 8.5、9.1 节；T04 Tool service、T05 Application Run/Turn 与 Codex 私有 waiter 清理边界。

### 完成边界

Task 2–3 联合测试必须证明 Core 无暂停 waiter、Application 无泄漏、Headless 可完整往返。W01 完成 Feedback 后停止。

---

## Task 4 — 非交互 CLI 暂停收口

### 任务目标

非交互 exec 遇到暂停时确定性取消并退出。

### 新增文件

无。

### 修改文件

- `src/uthcode/interfaces/cli.py`：识别 paused，stderr 输出安全摘要，只 cancel 一次并继续消费至 terminal，stdout 无伪 final，退出码 1，Ctrl+C 仍为 130。
- `tests/test_cli.py`：覆盖四类 reason、取消、消费完成、输出隔离和既有回归。

### 删除文件

无。

### 依赖任务

Task 3。

### 参考资料定位

原始需求第 9.3 节与 T05 CLI 输出分层。

### 完成边界

不等待 stdin、不自动回答/重试、不建立恢复命令。

---

## Task 5 — 默认 TUI 暂停与结构化问答

### 任务目标

在现有 prompt_toolkit/Rich TUI 接入上下文敏感 Esc、暂停菜单、问答和 Provider retry。

### 新增文件

- `src/uthcode/interfaces/tui/interaction.py`：管理 Interface 私有菜单、Esc context generation、问题导航、答案草稿和复核，不复制权威 pending。

### 修改文件

- `src/uthcode/interfaces/tui/app.py`：modal/picker 优先消费 Esc，根页面双 Esc 请求 pause，接入 Resume/Cancel/Retry/回答，paused 期间保留 active handle。
- `src/uthcode/interfaces/tui/rendering.py`、`terminal.py`：追加显示安全的暂停/恢复活动，不显示答案或 ToolResult 正文。
- `tests/test_tui.py`：覆盖 Esc 分层、Turn/focus/context 失效、三类菜单、问答、取消、退出、scrollback 和现有 TUI 回归。
- `docs/TUI/README.md`：说明合作式暂停、问答、取消与同进程限制。

### 删除文件

无。删除 `app.py` 中被替代的根页面双 Esc 直接取消分支。

### 依赖任务

Task 4。

### 参考资料定位

原始需求第 9.2 节；T02/T05 TUI 与 MewCode 问答交互。

### 完成边界

不导入 Core/Integration，不启用全屏/鼠标，不保存答案或暂停状态。

---

## Task 6 [接入主流程] — 统一活动 Turn 调用链

### 任务目标

收口唯一正式链路和公共导出，删除被替代路径。

### 新增文件

无。

### 修改文件

- `src/uthcode/core/agent.py`、`core/__init__.py`：收口分段执行与内部 continuation。
- `src/uthcode/application/runs.py`、`generation.py`、`application/__init__.py`：收口唯一 driver 和 Headless 导出。
- `src/uthcode/interfaces/cli.py`、`tui/app.py`：只通过 Application TurnHandle。
- `tests/test_architecture_boundaries.py`、`tests/test_package.py`：固化所有权、依赖与禁止导出。

### 删除文件

无预定整文件删除；删除有零调用方证据的旧分支和 helper。

### 依赖任务

Task 1–5。

### 参考资料定位

AGENTS.md 分层/非兼容原则；T04/T05 最终 Feedback。

### 完成边界

正式路径唯一为 `Headless/CLI/TUI → Application driver → Core execution segments`。

---

## Task 7 [端到端验证] — Headless、CLI 与 TUI 全链验收

### 任务目标

从正式入口验证主要成功、暂停、重试、取消和失败路径。

### 新增文件

无。

### 修改文件

- `tests/test_application_runs.py`：Headless AskUser、主动 pause、network retry 和 cancel race E2E。
- `tests/test_cli.py`：正式 exec pause-cancel E2E。
- `tests/test_tui.py`：默认 TUI pause/resume/answer Pilot。
- 其他 T06 测试：只补齐全链发现的协议回归。

### 删除文件

无。

### 依赖任务

Task 6。

### 参考资料定位

原始需求第 12–14 节和 W01/W02 Feedback。

### 完成边界

使用正式公开入口与离线 Fake Provider/Tool，不直接调用私有 continuation，不发真实网络请求。

---

## Task 8 [遗留负担清理] — 删除重复职责与持久恢复占位

### 任务目标

执行否定性扫描，删除被替代实现，证明无兼容层、重复职责和持久恢复。

### 新增文件

无。

### 修改文件

- 本任务全部生产文件：删除零调用方的 Core waiter、重复 continuation、旧 CLI/TUI 分支、重复 renderer 与兼容入口。
- `tests/test_architecture_boundaries.py`、`tests/test_package.py`：固化否定性门禁。
- `docs/TUI/README.md`：删除与最终行为冲突的描述。

### 删除文件

无预定整文件删除；只删除有调用方与测试证据的被替代代码。

### 依赖任务

Task 7。

### 参考资料定位

AGENTS.md 非兼容原则；原始需求第 3、6、13、14 节。

### 完成边界

清理后重跑受影响定向测试、架构/package、全量 pytest、compileall、pip check、diff check 和 UTF-8 guard；不自行归档或执行 Git 写操作。
