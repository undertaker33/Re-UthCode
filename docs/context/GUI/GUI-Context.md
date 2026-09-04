# Windows Desktop GUI（当前代码上下文）

```text
context_kind: current-code-context
context_file: docs/context/GUI/GUI-Context.md
scope: Windows Desktop renderer + Electron bridge + Application session boundary
source_of_truth: desktop/src/ + src/uthcode/interfaces/desktop/bridge.py + src/uthcode/application/ + desktop/tests/ + tests/
```

## 当前结论

- `[FACT]` 当前 GUI 是 Windows Desktop（Electron）Interface，不是另一套 Agent Runtime。Renderer 只消费 Python Runtime JSONL Bridge 的安全 DTO；Provider、Tool、Permission、`RunState` 与持久 Session 仍由 Application/Core 持有。
- `[FACT]` 调用链固定为 `renderer/App.tsx -> preload.ts -> main.ts -> python-runtime.ts -> interfaces/desktop/bridge.py -> UthCodeApplication -> AgentRun -> TurnHandle -> AgentEvent`。Python child 只处理受控 stdio/请求与关闭回收；Bridge 处理 Application、Run、Session 和安全投影。
- `[FACT]` 每个已打开的真实配置 Desktop Session 对应独立的 Application/Run 运行时投影。切换 Session、新建 Session 或打开另一项目时，旧 Session 的 active Turn 被停放为 background runtime，不因界面导航而取消；再次选择该 Session 会重新激活其已有 runtime，或以共享持久 Session store 的新 Application 恢复它。
- `[FACT]` background AgentEvent 附带 `session_id` 与 `project_key`。Renderer 以二者为键缓存每个 Session 的 timeline、Todo、Run、typed interaction、Context/Compact 和终态投影；侧栏按该投影显示 running、waiting、completed、failed、cancelled 或 idle。这个缓存是 Interface 投影，不是持久状态或第二份业务权威。
- `[FACT]` Desktop 的 `session.new`、`session.resume`、`project.open` 在候选 Application/Run/必要 DTO 成功准备后才切换可见 owner。当前已显示 Session 被再次选择时是视图 no-op。闲置且完成的 background runtime 会关闭回收；Desktop 关闭时会取消并等待所有仍活动的 handle，再关闭每个 Application。
- `[FACT]` Session metadata 保存可选 `model_ref`。新 Session 取得当前用户级新建默认模型；在一个 Session 内选择模型会同时原子写回用户级 `default_model` 和该 Session 的 `model_ref`，并刷新该 Session 的 Provider/Context。恢复旧 Session 会先验证再恢复其 `model_ref`，但不会改写后来用于新建 Session 的用户默认模型；失败时不发布拆分的模型/Context/metadata 状态。
- `[FACT]` Composer 仍走同一 prompt、Slash Command、Steering 与 typed interaction 合同。TodoWrite 的当前 Todo 条显示在 Composer 上方；Plan mode、完成阻断、Permission、AskUser、Provider retry 等状态由事件/Bridge 投影，不由 Renderer 自行决定。
- `[FACT]` `/model` 参数补全向用户显示 Model 的 `display_name`，但执行值仍为规范的 logical Model Profile ID。Settings 中 Provider 的可选 `display_name` 也只用于列表和弹窗标题，缺失时回退稳定 Provider Profile ID；修改显示名不会改变 Model 引用。Composer 的模型、权限选择器在 active Turn、pending interaction、Compact 或 runtime restart 时禁用，避免绕过 Application 边界。
- `[FACT]` Context ring 和 Runtime panel 只展示 Application 的 `context_status`/`compaction_status`。Bridge 在 assistant/reasoning/plan 流式文本、Todo 状态和工具完成事件到来时记录有界 `live_delta` 估计；terminal Provider usage 只更新独立的 `Last Provider Request Usage` 投影，不覆盖当前 Working Context 的 measurement。Renderer 在 active Turn 或 Compact 期间以一秒节奏补充查询 `status.get`，不会以该轮询替代事件流。
- `[FACT]` `desktop/src/renderer/state.ts` 是唯一 `RendererState`/reducer authority；`useRuntimeLifecycle` 独占 runtime generation、owner/tail、`AbortController`、stale guard 和 terminal convergence。`App.tsx` 只组合这些边界，不另建 Runtime/Run 生命周期状态机。
- `[FACT]` Settings 的 Provider→Model 编辑始终使用同一个 modal root、focus trap 和 return-focus owner。非秘密配置由 Settings 页面 draft 持有；reveal 值只存在 editor-local state，待写入的 replacement ref 只为失败重试保留，Save 仍经 Configuration Application 出口。Session ID 与 Markdown code fence 原文复制共用 `copyText`。
- `[FACT]` Sidebar/Runtime panel 宽度由 Renderer layout state 管理，viewport/窄屏只做 presentation clamp，稳定 separator commit 才写 preference。Focus Mode 是 Renderer-only transient：隐藏 Sidebar/Runtime，退出时恢复进入前的 `panelMode`/宽度且不写 preference；`Last Provider Request Usage` 与 Current Context 数值始终分离。
- `[BOUNDARY]` 现有 CDP/packaged acceptance 使用隔离 profile、DOM/keyboard/CDP 合成输入和 CSS viewport 观察；它可以证明 Renderer/Bridge/Application 投影与键盘/ARIA/布局合同，但不等同于 native pointer、Windows 原生缩放或人工视觉验收。未具备这些环境时不能把 synthetic viewport 或普通 mouse 对照写成 native input PASS。
- `[FACT]` 手动 `/compact` 发起时 Composer 立即显示 running 并锁定普通输入；Bridge/Application 返回 completed、no-change、cancelled 或 failed 的受控状态。无需 Compact 的成功 no-op 不伪造一次成功压缩。
- `[FACT]` Desktop 的无参数 `/compact` 等待 Bridge 实际结果，不使用普通 RPC 的 30 秒客户端等待上限；它仍受既有压缩步数、Provider 和 Runtime 关闭边界约束。普通 RPC 超时只结束当前等待，迟到的合法响应不会把存活 Runtime 判为协议损坏；已超时请求的 ID 保留至响应到达或进程边界结束。Bridge 仍串行处理请求，压缩期间后续请求可能等待，但不会因合法迟到响应而永久失去导航和发送能力。
- `[FACT]` Settings 页通过 Configuration 公共出口编辑 Provider、Model、用户默认权限、默认模型、界面主题和语言。API key 仅经受控配置写入/按需显示通道处理；Desktop preference 不保存 key。保存当前可见 Session 有 active Turn 时被禁止。
- `[FACT]` 普通 Session/Project navigation 与真正 `runtime.shutdown -> runtime.initialize` 生命周期分开显示：前者保留 operation gate 与 generation ownership，但不显示“正在重启”。`CustomSelect` 的 listbox 通过 `document.body` portal 进入 fixed overlay，按 trigger/viewport 几何上下放置，并在滚动、resize、键盘与 Escape 边界更新或关闭，因此不受 modal overflow 裁剪。
- `[FACT]` Session replay 可恢复失败 Turn 中已经公开的 reasoning/partial assistant，以及由稳定 `FailureReason`/`TerminationReason` 投影的 failed 状态；Renderer 不保存或解释 Provider 原生异常。
- `[BOUNDARY]` Desktop 只恢复已提交的 Session Transcript、Timeline、Tool Result ref、Instruction State 和 `model_ref`；不会跨进程恢复 active Turn、typed interaction waiter 或 Runtime checkpoint。
- `[ABSENT]` 当前没有 Web/IDE GUI、Renderer 直连 Provider/Core、Renderer 自建 Agent Loop、跨进程 Runtime continuation、Subagent 或 Multi-Agent GUI 编排。

## Session 与运行时切换

```text
visible Session A 有 active Turn
  -> session.new / session.resume(B) / project.open(B)
  -> Bridge 保存 A 的 Application + Run + TurnHandle + task 投影
  -> 为 B 复用已保存 runtime，或创建共享 Session store 的 Application
  -> Renderer 切换到 B 的 replay / live projection
  -> A 的事件仍带 A 的 session_id/project_key，更新 A 的缓存与侧栏状态
  -> A terminal 后才可被 Bridge 回收
```

- 同一 Session 同时最多一个 active Turn，仍遵守 `AgentRun` 的独占约束；在该 Session 可见时，普通输入是 Steering，暂停/恢复/取消仍指向同一 Turn。
- Session rename/move 是 Application 的持久元数据操作。Bridge 在任一已保存 runtime 仍有 active Turn 时拒绝这些变更，避免修改与运行中的 Session 边界竞争。
- 进程内的 per-Session runtime 是导航连续性机制，不是 Session v3 持久格式的一部分。Runtime crash/protocol error 仍与 Provider/Turn 的正式失败投影分离。

## 当前界面投影

| 区域 | 当前行为 | 权威来源 |
| --- | --- | --- |
| Sidebar | Project/Session 目录、title/preview、pin、rename/move 和 per-Session 运行状态；选择一行不取消其他 Session 的后台 Turn | Session catalog + Renderer 的事件缓存；rename/move 由 Application 提交 |
| Chat timeline | 已提交 replay 与当前 Session 的安全 AgentEvent 流；切换后使用该 Session 的缓存或 replay | Bridge 安全 DTO / Application Session |
| Composer | prompt/Slash 输入、Steering、暂停/取消、模型/权限选择、Context ring；Todo 条置于输入区上方 | Command/Turn/Context Application 投影 |
| Runtime panel | Turn、Run、模型、Permission、Context、Compact、Mode、Project、Session 的安全事实 | `status.get` / `/status` 的 Application 投影 |
| Interaction surface | AskUser、Permission、Plan review、Pause、Retry 的 typed response | 同一 `TurnHandle` 的 pending interaction |
| Settings | Provider/Model/default/Permission 与 theme/language 编辑；不保存明文 API key 到 Desktop preference | Configuration Application boundary + Renderer preference |

## 修改路由

```text
Electron 生命周期、IPC、Python child  -> desktop/src/main.ts + desktop/src/preload.ts + desktop/src/python-runtime.ts
Desktop JSONL 协议、Session/Turn 边界 -> src/uthcode/interfaces/desktop/bridge.py
Session 模型、Context 原子提交        -> src/uthcode/application/generation.py + context.py + sessions.py
Session metadata/store                  -> src/uthcode/application/sessions.py + integrations/session_files.py
Renderer 状态、导航、事件投影          -> desktop/src/renderer/state.ts + App.tsx
Composer / Todo / Context 显示          -> desktop/src/renderer/Composer.tsx + RuntimePanel.tsx
侧栏 Session 管理                       -> desktop/src/renderer/Sidebar.tsx
Settings 视图                           -> desktop/src/renderer/SettingsView.tsx
```

## 最小验证索引

```powershell
conda activate re-uthcode
python -m pytest tests/test_application_runtime.py tests/test_desktop_bridge.py tests/test_session_files.py -q
cd desktop
npm test
```
