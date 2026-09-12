# Windows Desktop GUI（当前代码上下文）

侧栏历史容器仅允许纵向滚动，禁止横向滚动；会话按钮的 flex 收缩规则跨过悬停信息包装，长标题省略而不挤出菜单按钮。

```text
context_kind: current-code-context
context_file: docs/context/GUI/GUI-Context.md
snapshot_date: 2026-09-12
verified_through_commit: 1218e31
scope: Windows Desktop renderer + Electron bridge + Application session boundary
source_of_truth: desktop/src/ + src/uthcode/interfaces/desktop/bridge.py + src/uthcode/application/ + desktop/tests/ + tests/
```

## 当前结论

- `[FACT]` 当前 GUI 是 Windows Desktop（Electron）Interface，不是另一套 Agent Runtime。Renderer 只消费 Python Runtime JSONL Bridge 的安全 DTO；Provider、Tool、Permission、`RunState` 与持久 Session 仍由 Application/Core 持有。
- `[FACT]` 调用链固定为 `renderer/App.tsx -> preload.ts -> main.ts -> python-runtime.ts -> interfaces/desktop/bridge.py -> UthCodeApplication -> AgentRun -> TurnHandle -> AgentEvent`。Python child 只处理受控 stdio/请求与关闭回收；Bridge 处理 Application、Run、Session 和安全投影。
- `[FACT]` 每个已打开的真实配置 Desktop Session 对应独立的 Application/Run 运行时投影。切换 Session、新建 Session 或打开另一项目时，旧 Session 的 active Turn 被停放为 background runtime，不因界面导航而取消；再次选择该 Session 会重新激活其已有 runtime，或以共享持久 Session store 的新 Application 恢复它。
- `[FACT]` background AgentEvent 附带 `session_id` 与 `project_key`。Renderer 以二者为键缓存每个 Session 的 timeline、Todo、Run、typed interaction、Context/Compact 和终态投影；侧栏按该投影显示 running、waiting、completed、failed、cancelled 或 idle。这个缓存是 Interface 投影，不是持久状态或第二份业务权威。
- `[FACT]` Desktop 将聊天历史显示与完整运行时准备分开：`history.page` 返回最近页或更早页，`session.resume` 建立或重新激活运行时，不再返回完整 replay。冷 Session 返回 preparing，完成准备后才允许普通发送；已有运行时可直接重新激活。闲置且完成的 background runtime 会关闭回收，尚未选择的准备结果保留待激活；Desktop 关闭时取消并等待活动任务，再关闭每个 Application。
- `[FACT]` Session metadata 保存可选 `model_ref`。新 Session 取得当前用户级新建默认模型；在一个 Session 内选择模型会预检后依次写回用户级 `default_model` 和该 Session 的 `model_ref`，再刷新该 Session 的 Provider/Context。恢复旧 Session 会先验证再恢复其 `model_ref`，但不会改写后来用于新建 Session 的用户默认模型；异常时尝试回滚配置、metadata 与运行时状态，回滚失败会明确报错；单文件原子写入不构成跨文件或进程退出的全局事务。
- `[FACT]` Composer 仍走同一 prompt、Slash Command、Steering 与 typed interaction 合同。TodoWrite 的当前 Todo 条显示在 Composer 上方；Plan mode、完成阻断、Permission、AskUser、Provider retry 等状态由事件/Bridge 投影，不由 Renderer 自行决定。
- `[FACT]` Composer 的附件选择、剪贴板、拖拽和粘贴都先导入当前 Session 的 Application-owned 副本；附件 ref 与 prompt 合并为一次 `turn.start`，仅附件也可提交，提交失败保留草稿，成功后清除当前 Session 草稿。历史 replay 显示安全附件元数据和图片预览/文件回退，不让 Renderer 读取任意路径。
- `[FACT]` Renderer 的附件导入/预览在跨 IPC await 前捕获 `project_key`、Session、`sessionViewRevision` 和运行代次 owner；返回后只向仍拥有该视图的 Composer 写入草稿或错误，切换 Session 不会把迟到结果污染新 Session，首次惰性创建 Session 仍可正常接收结果。
- `[FACT]` `/model` 参数补全向用户显示 Model 的 `display_name`，但执行值仍为规范的 logical Model Profile ID。Settings 中 Provider 的可选 `display_name` 也只用于列表和弹窗标题，缺失时回退稳定 Provider Profile ID；修改显示名不会改变 Model 引用。Composer 的模型、权限选择器在 active Turn、pending interaction、Compact 或 runtime restart 时禁用，避免绕过 Application 边界。
- `[FACT]` Context ring 和 Runtime panel 只展示 Application 的 `context_status`/`compaction_status`。Bridge 在 assistant/reasoning/plan 流式文本、Todo 状态和工具完成事件到来时记录有界 `live_delta` 估计；terminal Provider usage 只更新独立的 `Last Provider Request Usage` 投影，不覆盖当前 Working Context 的 measurement。Renderer 在 active Turn 或 Compact 期间以一秒节奏补充查询 `status.get`，不会以该轮询替代事件流。
- `[FACT]` `desktop/src/renderer/state.ts` 是唯一 `RendererState`/reducer authority；`useRuntimeLifecycle` 独占 runtime generation、owner/tail、`AbortController`、stale guard 和 terminal convergence。`App.tsx` 只组合这些边界，不另建 Runtime/Run 生命周期状态机。
- `[FACT]` Settings 的 Provider→Model 编辑始终使用同一个 modal root、focus trap 和 return-focus owner。非秘密配置由 Settings 页面 draft 持有；reveal 值只存在 editor-local state，待写入的 replacement ref 只为失败重试保留，Save 仍经 Configuration Application 出口。Session ID 与 Markdown code fence 原文复制共用 `copyText`。
- `[FACT]` Sidebar/Runtime panel 宽度由 Renderer layout state 管理，viewport/窄屏只做 presentation clamp，稳定 separator commit 才写 preference。Focus Mode 是 Renderer-only transient：隐藏 Sidebar/Runtime，退出时恢复进入前的 `panelMode`/宽度且不写 preference；`Last Provider Request Usage` 与 Current Context 数值始终分离。
- `[FACT]` 侧栏历史容器只允许纵向滚动；会话按钮跨过悬停信息包装保持 flex 收缩，长标题省略而不挤出菜单按钮。项目整行（菜单和编辑输入除外）切换展开状态，选中子会话不阻止收起。侧栏移除缓存和项目归属行内标签，悬停卡片展示项目/会话名称及所属路径；Runtime 布局使用隐藏、浮动、停靠三个图标按钮，专注模式使用独立图标。
- `[FACT]` Composer 不再展示就绪/运行中的通用状态文案；运行结束且用户未将焦点移至其他控件时恢复输入焦点。回复或压缩完成产生会话级未读标记，只有可见且获得焦点的窗口已显示聊天尾部才清除；清除标记不删除聊天内容。
- `[FACT]` 压缩进度是聊天中的单行提示，运行时带旋转与省略点动画。完成后的持久提示来自历史页，按实际提交位置排列，不固定在最新回复之后；刷新最近页保留已加载旧页和游标，不自动补载全部历史。失败、取消和无需变更的即时提示不被既有成功记录遮蔽。
- `[BOUNDARY]` 现有 CDP/packaged acceptance 使用隔离 profile、DOM/keyboard/CDP 合成输入和 CSS viewport 观察；它可以证明 Renderer/Bridge/Application 投影与键盘/ARIA/布局合同，但不等同于 native pointer、Windows 原生缩放或人工视觉验收。未具备这些环境时不能把 synthetic viewport 或普通 mouse 对照写成 native input PASS。
- `[FACT]` 手动 `/compact` 返回操作身份后由 Session 所属的后台任务执行，Bridge 通过带 `session_id`、`project_key`、`operation_id` 的 `compaction_operation` 通知投影进度和结果。Composer 锁定该 Session 的普通输入并提供显式取消入口，`compaction.cancel` 校验 Session/操作身份；状态区分 completed、no_change、cancelled、failed，另保留有效提交 `changed` 与安全 `reason`，Runtime 面板显示原因和提交说明。无需 Compact 的成功 no-op 不伪造一次成功压缩。
- `[FACT]` Bridge 请求接收仍串行，仅长时间手动压缩脱离该循环；切换 Session 不取消压缩，已停放的压缩运行时保留至终态。`/compact` 启动请求恢复使用普通 RPC 等待上限，不再靠免除 30 秒超时等待整个压缩。普通 RPC 超时只结束当前等待，迟到的合法响应不会把存活 Runtime 判为协议损坏；已超时请求的 ID 保留至响应到达或进程边界结束。关闭时取消活动操作、等待收尾，再关闭 writer；外层 PythonRuntime 保留有界 child 回收边界，重新启动不会自动重试旧压缩。
- `[FACT]` Settings 页通过 Configuration 公共出口编辑 Provider、Model、用户默认权限、默认模型、界面主题和语言。API key 仅经受控配置写入/按需显示通道处理；Desktop preference 不保存 key。保存当前可见 Session 有 active Turn 时被禁止。
- `[FACT]` Settings 的 Model 编辑保留 `supports_images` 三态能力字段；未知按不支持参与图片输入预检，新模型默认关闭图片输入，保存仍服从 active Turn 禁止边界。
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
- 普通侧栏与 Slash 导航保留 Session-owned Run 的事件接收，不把停放的 Run 当作已失效 Run；真正清空工作区时清除显示缓存并拒绝已知旧 Run 的迟到事件。目录刷新省略运行状态时保留已有 running/waiting 等投影；带身份的 status 只更新匹配 Project/Session 的投影，不覆盖另一可见会话。
- 活跃会话的补充 status 轮询为 single-flight，导航或重启操作占用期间跳过，不积压等待任务。Desktop catalog 读取元数据，并从 Transcript 头部读取到首条完整用户记录生成单行预览，不为每个目录项重建完整历史；侧栏优先显示手动标题，否则显示首条用户消息预览。聊天默认显示最近 30 个完整交互单元，向上接近顶部再读取更早页，不自动补载全部历史。
- 分页请求按 Session 保持 single-flight，并校验导航/请求身份；失败只显示局部重试，不清空已显示内容。旧页前插保留阅读位置，持久记录使用稳定身份并与当前实时投影合并；完整运行时恢复仍由 Application 执行，分页不裁剪模型上下文。游标同时保存 Transcript 与 Timeline 字节边界，翻旧页不会重复扫描更新的 Timeline；压缩完成记录从 Timeline 投影，并按对应的 Transcript 提交位置插入聊天。
- Session rename/move 是 Application 的持久元数据操作。Bridge 在任一已保存 runtime 仍有 active Turn 时拒绝这些变更，避免修改与运行中的 Session 边界竞争。
- 进程内的 per-Session runtime 是导航连续性机制，不是 Session v3 持久格式的一部分。Runtime crash/protocol error 仍与 Provider/Turn 的正式失败投影分离。

## 当前界面投影

| 区域 | 当前行为 | 权威来源 |
| --- | --- | --- |
| Sidebar | Project/Session 目录、title/preview、pin、rename/move 和 per-Session 运行状态；选择一行不取消其他 Session 的后台 Turn | Session catalog + Renderer 的事件缓存；rename/move 由 Application 提交 |
| Chat timeline | 最近历史优先显示，上翻按页加载；与当前 Session 的安全 AgentEvent 流合并 | Bridge 安全 DTO / Application Session |
| Composer | prompt/Slash 输入、Steering、暂停/取消、模型/权限选择、Context ring、选择/粘贴/拖拽附件和仅附件发送；Todo 条置于输入区上方 | Command/Turn/Context/Session Attachment Application 投影 |
| Runtime panel | Turn、Run、模型、Permission、Context、Compact、Mode、Project、Session 的安全事实 | `status.get` / `/status` 的 Application 投影 |
| Interaction surface | AskUser、Permission、Plan review、Pause、Retry 的 typed response | 同一 `TurnHandle` 的 pending interaction |
| Settings | Provider/Model/default/Permission 与 theme/language 编辑、Model 图片能力声明；不保存明文 API key 到 Desktop preference | Configuration Application boundary + Renderer preference |

## 修改路由

```text
Electron 生命周期、IPC、Python child  -> desktop/src/main.ts + desktop/src/preload.ts + desktop/src/python-runtime.ts
Desktop JSONL 协议、Session/Turn 边界 -> src/uthcode/interfaces/desktop/bridge.py
Session 模型、Context 更新与回滚        -> src/uthcode/application/generation.py + context.py + sessions.py
Session metadata/store                  -> src/uthcode/application/sessions.py + integrations/session_files.py
Renderer reducer authority              -> desktop/src/renderer/state.ts
Session / DTO 纯转换                    -> desktop/src/renderer/state-session.ts + state-normalization.ts
Runtime generation / owner / terminal   -> desktop/src/renderer/useRuntimeLifecycle.ts
Renderer 导航、布局与组合                -> desktop/src/renderer/App.tsx
Composer / Todo / Context 显示          -> desktop/src/renderer/Composer.tsx + RuntimePanel.tsx
侧栏 Session 管理                       -> desktop/src/renderer/Sidebar.tsx
聊天分页、阅读位置、代码块复制          -> desktop/src/renderer/ChatTimeline.tsx + safe-markdown.tsx
Settings draft / 单根编辑器             -> desktop/src/renderer/SettingsView.tsx + SettingsEditorModal.tsx + settings-draft.ts
历史分页与压缩提示持久投影               -> application/sessions.py + integrations/session_files.py（位于 src/uthcode/）
```

## 事实与测试定位

| 关注点 | 对应测试 |
| --- | --- |
| reducer、Session 缓存和导航隔离 | `desktop/tests/renderer-state.test.ts`、`renderer-session.test.tsx` |
| runtime ownership、迟到事件和终态收敛 | `desktop/tests/renderer-runtime-lifecycle.test.tsx`、`runtime-process.test.ts` |
| 单根 Settings、返回焦点和秘密显示生命周期 | `desktop/tests/renderer-settings.test.tsx` |
| Markdown 原文复制、历史分页和阅读位置 | `desktop/tests/renderer-chat.test.tsx` |
| 附件选择/粘贴/拖拽、预览/移除、仅附件发送和失败重发 | `desktop/tests/renderer-attachments.test.tsx`、`tests/test_desktop_bridge.py` |
| 布局与临时 Focus Mode | `desktop/tests/renderer-state-ui.test.tsx`、`renderer.test.tsx` |
| 冷 Session 准备、压缩取消及跨 Session 运行 | `tests/test_history_prepare_lifecycle.py`、`tests/test_desktop_bridge.py` |
| 历史游标与持久压缩提示 | `tests/test_history_paging.py` |
| 目录首条消息预览 | `tests/test_session_authority.py` |

以下是行为改动后的验证入口，不表示本次文档同步重新执行了功能验收。

## 最小验证索引

```powershell
conda activate re-uthcode
python -m pytest tests/test_application_runtime.py tests/test_desktop_bridge.py tests/test_session_files.py -q
cd desktop
npm test
```
