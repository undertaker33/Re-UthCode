# W03 Slash Command 与 TUI Feedback

## 1. 实际完成

- 完成 Task 8：`/plan` 选择 `BehaviorMode.PLAN`，`/do` 选择 `BehaviorMode.DEFAULT`，`/build` 仅作为 `/do` alias；三者均无参数且只返回 interface-neutral `BehaviorModeSelected` action。旧 `/p` 与旧 Prompt `/do` 已删除。
- 完成 Task 9：TUI 支持 idle start Turn、active same-Turn Steering、typed interaction 优先、Behavior/Permission 双维状态、PLAN separator、Plan revision、Plan Review、Todo checklist、Steering 与 CompletionBlocked 投影。
- 未读取或合并 W02 实现，未修改 Core、`application/runs.py`、`generation.py`、`tools.py`、CLI 或跨层 E2E；正式 W02 API 接线与端到端验收仍由 W04 完成。

## 2. 关键实现

### 2.1 Slash 最终定义

- Registry 仍是解析、help、completion、availability 与 alias 的唯一事实源。
- `BehaviorModeSelected` 只携带目标 `BehaviorMode`；命令 handler 不保存 Run 状态，也不直接操作 TUI。
- TUI 仅在 idle 时把 action 应用到当前 `AgentRun.set_behavior_mode(...)`；active Turn 的 Slash 切模请求稳定拒绝，不改变当前 mode。

### 2.2 输入优先级与 Plan Review

输入顺序固定为：

```text
visible typed interaction
  > pending typed pause
  > active Turn Steering
  > idle start_turn
```

- AskUser、Permission、Provider Retry、Plan Review 打开或 pending 时，普通文本不能旁路成 Steering。
- active 且无 typed interaction 时只调用当前 `TurnHandle.steer(text)`；接受后用户文本追加一次，Steering 事件只更新 activity，不重复渲染正文或增加 Turn 分隔。
- Plan Review 使用现有 `TurnHandle.resume(...)` 提交精确 `PlanReviewResponse`；界面只保存 action index 与 revision draft，不保存 `PlanState`。

### 2.3 Plan、Todo 与完成拦截投影

- `BehaviorMode` 与 `PermissionMode` 在 status 中分开显示；PLAN separator 使用专用 `plan_accent`，批准后读取 Run 的 DEFAULT 状态并立即恢复默认色。
- 每个 `PlanProposed` 都以 `UthCode · Plan vN`、完整 Markdown 和 `plan_background` 追加为独立 block；旧 revision 不回写。
- `TaskStateChanged` 全量投影为 `✓ completed`、`› in_progress`、`○ pending`；TUI 不维护 Todo authority。
- `CompletionBlocked` 只显示继续执行的短状态，事件与 RenderBatch 均不携带 candidate final。

## 3. 修改文件

- Command：`src/uthcode/application/commands/models.py`、`builtins.py`、`commands/__init__.py`、`src/uthcode/application/__init__.py`。
- TUI：`src/uthcode/interfaces/tui/app.py`、`interaction.py`、`rendering.py`、`terminal.py`。
- 测试：`tests/test_command_dispatcher.py`、`test_command_registry.py`、`test_command_completion.py`、`test_tui.py`。
- 文档：`docs/TUI/README.md`、T08 Checklist 与本 Feedback。

## 4. 测试与检查证据

- 开工前 Slash/TUI 基线：`108 passed in 9.60s`；导入路径确认命中 `D:\project\Re-UthCode-T08-W03\src\uthcode\__init__.py`。
- 测试先行红测：新增合同尚未实现时出现 2 个预期 collection errors；首轮实现后为 `111 passed, 2 failed`，两处失败均为测试对 slots/Rich ANSI 的断言问题，修正后转绿。
- Task 8/9 精确 Checklist 集合最终复跑：`115 passed in 8.70s`。
- 含 parser 的 Slash/TUI 扩展回归：`126 passed in 7.94s`。
- Architecture + package：`31 passed in 6.45s`。
- 最终全量回归：`804 passed, 3 skipped in 47.75s`；skip 数与既有环境门禁一致。
- `compileall -q src tests` 退出码为 0；`pip check` 输出 `No broken requirements found.`；`git diff --check` 无 whitespace error。
- 静态扫描无旧 `/p`、无 canonical `/build`、Interface 无 `core`/`integrations` 导入；`CommandKind.PROMPT` 只剩未实现的 `/dream` 与 `/review`，`/do` 已是 `LOCAL_UI`。

## 5. Checklist 状态

- Task 8 的 5 项与 Task 9 的 6 项均已按实际命令、事件、fake Run/Handle、TUI 投影和测试证据完成。
- 未勾选 Task 3～7 或 Task 10～12；W03 分支不宣称 Runtime/Application 正式接线或包级 E2E 已完成。

## 6. 与任务书差异、风险及 W04 边界

- 无需求差异、无冻结工作包错误、无越界生产修改。
- 当前 W03 分支没有 W02 的 `AgentRun.behavior_mode`、`set_behavior_mode` 与 `TurnHandle.steer` 实现。`tests/test_tui.py` 只在这些成员缺失时安装最小 fake 合同；W02 合入后检测到真实成员即不覆盖，W04 必须在合并分支上重跑同一测试并完成正式接线/E2E。
- Steering 用户正文由提交成功的 Interface 输入追加一次；W01 的 Steering events 不含正文，仅用于 activity。W04 需确认 W02 不额外发送带同一正文的第二个 display event。
- Plan approve 后 separator 读取 `AgentRun.behavior_mode`；W04 需确认 W02 在公开 `BehaviorModeChanged`/resume 可见前已同步 Run mode。
- Windows Terminal 仍需人工复核 PLAN/DEFAULT 色差、Plan 多 revision scrollback、Plan Review 键盘路径、active Steering 与 typed interaction 优先级。

## 7. 遗留负担检查

- 未增加第三种 Build mode、旧 `/p`、旧 Prompt `/do`、第二 command registry、Interface-owned Run/Plan/Task state、第二 Turn/Runtime 或 W02 placeholder Runtime。
- 未回写 scrollback，未进入 alternate screen，未启用鼠标，未发送 `CSI 3J`；永久内容仍按一个 RenderBatch 一次提交。
- 未 push、rebase、普通 merge、reset、操作远端或清理任何 worktree/分支。

## 8. 返工第 1 轮

### 8.1 审查问题与修复

- 审查发现：临时 typed interaction 被 Esc 关闭后，`_handle_submission(...)` 会先分发 Slash；因此 active Turn 仍有 Plan Review、AskUser、Permission 或 Provider Retry pause 时，`/clear`、`/permission`、`/quit` 等命令可能先产生副作用。
- 已把 active handle 的 `pending_pause` 判定移到 Slash dispatch、Steering 与 idle `start_turn` 之前。发现 pending pause 时只调用既有 `_open_pending_interaction()` 恢复临时交互层并立即返回，不解析或分发本次 Slash。
- 已彻底删除 `tests/test_tui.py` 模块加载阶段对真实 `AgentRun`、`TurnHandle` 的条件性 `setattr`。W03 分支测试改用测试本地 `_FakeRunProxy`、`_FakeModeRun` 与 `_FakeSteeringHandle` 注入，不修改生产类。
- 本节取代第 6 节中“成员缺失时安装最小 fake 合同”的旧说明；旧记录按返工规则保留，不再代表当前实现。

### 8.2 测试先行与复验

- 当前源码导入路径确认：`D:\project\Re-UthCode-T08-W03\src\uthcode\__init__.py`。
- 红测：四类 closed pending typed pause 均先进入 Slash dispatch，隔离进程也检测到加载 W03 测试后生产类新增属性，共 `5 failed`。
- 修复后 reviewer 复现集合：`6 passed, 65 deselected in 2.06s`；覆盖 Plan Review + `/plan`、AskUser + `/clear`、Permission + `/permission auto`、Retry + `/quit`，并验证 dispatcher、Steering、resume、cancel、quit 均无副作用。
- 完整 `tests/test_tui.py`：`71 passed in 7.92s`。
- Task 8/9 精确 command + TUI 集合：`120 passed in 8.40s`。
- Architecture + package：`31 passed in 5.07s`。
- 全量回归：`809 passed, 3 skipped in 44.09s`。
- `compileall -q src tests` 退出码为 0；`pip check` 为 `No broken requirements found.`；`git diff --check` 无 whitespace error。
- 负向扫描确认没有模块导入期生产类补丁，也没有 Interface 对 `core` 或 `integrations` 的直接导入。

### 8.3 Checklist 与接线边界

- Task 8、Task 9 的既有勾选继续由上述新证据支持；未修改冻结 Spec、Tasks、Prompt 或 Checklist 文字。
- 未读取或合并 W02 未完成实现。测试本地代理只表达 W03 所需预期合同；真实 `AgentRun.behavior_mode`、mode setter 与 `TurnHandle.steer(text)` 仍由 W04 在合并分支接线并端到端复验。
- Windows Terminal 人工复核项保持不变；本轮未新增生产兼容层、命令入口或跨层状态所有权。
