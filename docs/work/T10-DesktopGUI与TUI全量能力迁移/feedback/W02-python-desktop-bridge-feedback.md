# W02 Python Desktop Bridge 实施反馈

## 状态

已完成 T02 实施与验证。本文档为 W02 首次实施创建，以下为收敛结果；未执行 Git 写操作。

## 实施边界

- 只实现 T02 Python Desktop Bridge 与 stdin/stdout JSONL 协议。
- 不实现 Electron、Renderer、Windows 打包、T03 及后续任务。
- Bridge 通过 `uthcode.application` 公共导出访问 Application、Run、Turn、Session、Command 和公开 AgentEvent；不直接访问 Core、Provider、Tool 或 Session Store。

## 初始验证记录

- 已按要求先建立协议与 Bridge 定向测试，再进入生产实现。

## 实施结果

- `protocol.py` 实现严格 JSONL request/response/agent-event/runtime-state envelope，校验 JSON、字段、请求 ID、method、params、重复键和非有限数值；协议错误使用稳定类型和消息，不暴露异常文本。
- `bridge.py` 只通过 `uthcode.application` 公共导出调用 Application、Run、Turn、Session、Command 和公开 AgentEvent；不直接依赖 Core、Provider、Tool 或 Session Store。支持的 method 为：`runtime.initialize`、`runtime.shutdown`、`project.open`、`project.sessions`、`session.new`、`session.resume`、`turn.start`、`turn.steer`、`turn.pause`、`turn.resume`、`turn.cancel`、`command.complete`、`command.execute`、`status.get`、`settings.get`、`settings.save`。
- Bridge 保持单 Application、单 Run、最多一个 active Turn；second start、pending/active command 门禁、同一 TurnHandle 的 steer/pause/resume/cancel、terminal 清理、project/session fresh Run 和安全 replay 均已覆盖。project candidate 失败时保留旧 active Session。
- typed interaction 已覆盖 ResumeTurn、AskUser、Permission、Plan、Retry；stale/wrong-kind/duplicate response 不调用 handle，Plan revise 要求非空 feedback，Permission 仅使用 request.choices；Plan/Retry/Pause cancel 均调用 `TurnHandle.cancel()`。
- completion 同时使用 command 与 argument candidates；AgentEvent 原名、identity、顺序保持不变，Runtime/lifecycle/protocol error 与 TurnFailed/Provider failure 分域。公开投影拒绝 secret、native exception、未知对象字符串化和 raw ToolResult。
- `serve_forever` 只向 stdout 输出 JSONL，stderr 仅保留稳定诊断；实际 `python -m uthcode.interfaces.desktop` 子进程已验证 ready/status/shutdown 协议路径，直接 Bridge 测试验证 Application close。

## 精确验证记录

- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_desktop_protocol.py tests/test_desktop_bridge.py tests/test_architecture_boundaries.py -q`：`65 passed in 6.31s`。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_configuration.py tests/test_config_contract.py tests/test_config_loader_integration.py -q`：`80 passed in 4.74s`（T01 回归）。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests`：退出码 0。
- `conda run --no-capture-output -n re-uthcode python -m pip check`：退出码 0，`No broken requirements found.`
- `git diff --check`：退出码 0。
- 全量 `conda run --no-capture-output -n re-uthcode python -m pytest -q`：`1364 passed, 3 skipped, 1 failed in 165.71s`。唯一失败为既有 `tests/test_w06_integration_delivery.py::test_tui_session_picker_open_close_does_not_create_session` 的异步关闭等待；未修改该范围，随后隔离重跑该测试为 `1 passed in 1.58s`。

## Checklist 状态

- T02 Checklist 10/10 项已在精确验证后勾选；仅修改 T02 的十个 `[ ]` 为 `[x]`，未修改 T01、T03+ 或冻结任务书内容。

## 未验证项与风险

- 未验证 Electron/Renderer、Windows runtime bundle/installer、打包 Runtime 或 T03+ 能力；这些均按 Prompt 保持 Out of Scope。
- 未在带真实用户配置的生产桌面包中执行 `runtime.initialize` 全链路；已验证实际 Python module 子进程协议，以及注入 fake Application/Run/Turn 的生命周期、错误和秘密安全路径。
- 全量测试出现一次既有 W06 异步时序波动；隔离重跑通过，未将其归因于 W02，也未扩大修改范围。

## UTF-8 guard closeout

- files checked: `docs/work/T10-DesktopGUI与TUI全量能力迁移/feedback/W02-python-desktop-bridge-feedback.md`、`docs/work/T10-DesktopGUI与TUI全量能力迁移/T10-DesktopGUI与TUI全量能力迁移-checklist.md`。
- result: 写前字节读取与 UTF-8 decode 通过；写后 `check_utf8_docs.py` 通过（`OK: 2 file(s) passed UTF-8 guard`），replacement character、常见 mojibake 和 Markdown fence 不平衡均为 0。
- repaired encoding issues: none。

## 返工第 1 轮

### 原因

Reviewer 未批准 W02，指出安全投影反射、project candidate 预检顺序、Session/Run 事务边界、重复 wire authority、USER_REQUESTED cancel 和失败路径测试证据不足。本轮只在 W02 既有写集内修复，未修改冻结任务书文字或 T03+。

### 实际修改

- `_safe_value` 移除按模块名前缀发现 `to_dict` 的反射路径，改为 JSON 原子值/容器与明确白名单 `ApplicationStatus`、`PauseRequest`、`RunSnapshot`、`SessionReplayRecord`、`UserConfigurationView`；未知 Provider/Core/native 对象（包括真实 `ToolResultPart`）不再序列化。
- `project.open` 先构造 candidate Application/Run、Dispatcher/Completion、Session catalog 和 Run snapshot 的全部公开投影，再收口旧 Turn、关闭旧 Application 并一次提交引用；candidate 投影失败时旧 Application、Run、Session 和 active handle 保持不动。
- `session.new`、`session.resume` 及内建 `/new`/`/resume` 的 `SessionChanged` 在 Session mutation/dispatch 前预创建 fresh Run，成功后只提交该 Run 一次；permission rules loader 或 `create_run` 失败不会改变旧 Session/Run。
- `SessionChanged.replay` 仅保留在 command result 顶层；status 的 Run 仅保留在 `runtime.run`。补齐 USER_REQUESTED Pause 的 `handle.cancel()`、busy/corrupt/unknown/projection failure、candidate catalog/snapshot failure、真实 `ToolResultPart` 和真实 permission loader failure 回归。

### 重新验证

- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_desktop_protocol.py tests/test_desktop_bridge.py tests/test_architecture_boundaries.py -q`：`79 passed in 6.54s`。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_configuration.py tests/test_config_contract.py tests/test_config_loader_integration.py -q`：`80 passed in 4.30s`。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests`：退出码 0。
- `conda run --no-capture-output -n re-uthcode python -m pip check`：退出码 0，`No broken requirements found.`
- `git diff --check`：退出码 0；仅工作区 LF/CRLF 提示，无 whitespace error。
- 全量 `conda run --no-capture-output -n re-uthcode python -m pytest -q`：`1379 passed, 3 skipped in 154.42s (0:02:34)`。

### Checklist、范围与遗留负担

- T02 Checklist 仍为 10/10 项 `[x]`；本轮未改变 Checklist 验收文字、结构、顺序或 T01/T03+ 项。
- 修改文件仍限于 `src/uthcode/interfaces/desktop/`、`tests/test_desktop_protocol.py`、`tests/test_desktop_bridge.py`、本 Feedback 和 T02 Checklist；未修改 Application/Core/Provider、Electron/Renderer 或其他任务包文件。
- 未引入兼容层、重复 Runtime/Event authority、通用 RPC、Session Store 直连或新的依赖；未执行任何 Git 写操作。
- 未验证真实 Electron/Renderer、Windows 打包和 T03+；生产打包 Runtime 的真实用户配置初始化仍由后续任务验证。

### UTF-8 guard（返工第 1 轮）

- files checked: `docs/work/T10-DesktopGUI与TUI全量能力迁移/feedback/W02-python-desktop-bridge-feedback.md`、`docs/work/T10-DesktopGUI与TUI全量能力迁移/T10-DesktopGUI与TUI全量能力迁移-checklist.md`。
- result: 写前字节读取与 UTF-8 decode 均通过；写后 `check_utf8_docs.py` 通过，replacement character、常见 mojibake 和 Markdown fence 不平衡均为 0。
- repaired encoding issues: none。
