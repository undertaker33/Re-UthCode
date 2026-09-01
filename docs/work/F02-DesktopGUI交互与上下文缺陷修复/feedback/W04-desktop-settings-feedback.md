# W04 Desktop Settings 实施反馈

## 首次实施

本反馈记录 W04 按 Prompt 实施 T07 的过程与结果；后续返工只在本文真实 EOF 追加章节。

### 开工边界

- 已完整读取 `AGENTS.md`、文档路由、工作包规则、用户决策边界、F02 需求/Spec/Tasks/Checklist、`docs/OutstandingDebtList.md`、A04 当前上下文及 W01～W03 Feedback。
- 本次只触达 T07 授权的配置读取/Application use case、Desktop Bridge/API、Settings Renderer、共享 CSS/locale 与对应测试；不修改 Main、Preload、Python Runtime、CDP harness、T10 冻结文件或 current-facts 文档。
- 本轮不执行 Git commit、push、merge、rebase、tag、release、分支切换或工作包归档。

### 实施状态

- 初始已确认 Settings 只有脱敏 `settings.get` 与保存路径，没有专用 reveal；旧 UI 仍展示可编辑 `model_ref`、生成可见 `model/model-1`、提供 Clear Key/Configured 文案。
- 已先添加并运行 secret reveal 的失败回归（未知 Provider、错误读取、普通 payload 不含明文），随后实施窄读取链与 Settings 生命周期。
- Checklist 仅在取得精确自动证据后更新；未把真实 Windows/Electron、人工键盘/鼠标、DPI/zoom 或 Provider 网络验收写成通过。

### 待补充

实现、测试、扫描、Checklist 勾选、风险和 UTF-8 guard 结果将在本节后续 EOF 追加。

## 本轮实施结果

### Secret 数据流与生命周期

- `integrations.config.loader.read_user_config_api_key(path, provider_profile_id)` 只读取用户级 `config.toml` 中指定 Provider 的 `api_key` 表达；literal 原样返回，`env:VARIABLE_NAME` 只返回引用字符串，不读取环境变量，也不从 Runtime Provider 或 `SecretValue` 反向读取。
- `application.read_user_api_key` 是唯一 Application 用例入口；Bridge 只允许严格的 `provider_profile_id` 参数，新增 `settings.reveal_api_key` 是唯一可返回 `api_key` 的 Desktop response。普通 `settings.get` 及既有状态、事件、诊断、错误、偏好、日志、快照投影继续走无秘密 DTO。
- Renderer 只接收窄回调 `onRevealApiKey(providerId)`，不把完整 Desktop API 传入 Settings。revealed 值与 replacement/touched 分离：eye 的显示/隐藏不触发保存；未编辑 Key 的保存请求省略 `api_key`，因此不会把旧表达写回；用户输入只进入 transient replacement，保存失败后继续保留草稿。
- Provider modal 关闭、返回聊天、配置重新投影和组件卸载都会递增 reveal generation 并清空 renderer-local refs/state；迟到的 response 不能重新填充已关闭 modal。测试只使用合成的 `env:W04_*` 表达，不包含真实凭据。

### Settings UI 与 Model 结构

- Settings 改为分类导航与独立 sections，共享 `--sidebar-width`，Provider/Model 使用分层 modal；Provider 字段顺序为 Protocol、Base URL、API Key，eye 按钮始终渲染，含 tooltip、aria-label、aria-pressed、状态文本和错误/进行中反馈。
- Model 仅展示/编辑 remote model ID、display name、context window、max output tokens、reasoning effort 与默认选择；空 display name 以 remote ID 作为主显示名。新 Model 使用 renderer 内部唯一 ref，ref 不渲染、不进入可编辑控件或可见文案。
- Provider/Model modal 提供 Escape、Tab focus trap、初始焦点、返回焦点、背景 inert/aria-hidden、鼠标遮罩关闭和 reduced-motion CSS；locale 保持 zh-CN/en key parity，并保留 dark/light/system 主题 token。
- 清除了被新 Settings 结构替代且无调用方的旧 `.settings-profile`、`.settings-inline` 与 `.settings-model-fields` CSS 规则，未保留旧编辑入口的兼容路径。

### 修改文件

- 配置/Application/Bridge：`src/uthcode/integrations/config/loader.py`、`src/uthcode/application/bootstrap.py`、`src/uthcode/application/__init__.py`、`src/uthcode/interfaces/desktop/bridge.py`。
- Desktop API/Renderer：`desktop/src/desktop-api.ts`、`desktop/src/renderer/App.tsx`、`desktop/src/renderer/SettingsView.tsx`、`desktop/src/renderer/app.css`、`desktop/src/renderer/locales/en.ts`、`desktop/src/renderer/locales/zh-CN.ts`。
- 测试：`tests/test_configuration.py`、`tests/test_desktop_bridge.py`、`desktop/tests/renderer.test.tsx`、`desktop/tests/render-settings-interactions-visual-fixture.tsx`。
- 本 Feedback 与 F02 Checklist 是本轮新增/更新的工作包记录；未修改 Main、Preload、Python Runtime、T10、CDP harness 或 current-facts。

### 精确验证与 Checklist 证据

- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_configuration.py tests/test_desktop_bridge.py -q`：115 passed。
- `conda run --no-capture-output -n re-uthcode npm run typecheck`（cwd=`desktop`）：通过。
- `conda run --no-capture-output -n re-uthcode npx tsx --test tests/renderer.test.tsx`（cwd=`desktop`）：84 passed。
- `conda run --no-capture-output -n re-uthcode npm test`（cwd=`desktop`）：120 passed，包含 preload、Settings/Renderer 及既有 Desktop 测试。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q`：23 passed。
- `rg -n "renameModelRef|model-1|clearKey" desktop/src/renderer desktop/tests`：无匹配；否定断言通过字符串拼接避免把禁用旧 token 作为生产/fixture 内容重新引入。
- `git diff --check`：通过。
- UTF-8 guard：`conda run --no-capture-output -n re-uthcode python C:\Users\93445\.codex\skills\uth-utf8-guard\scripts\check_utf8_docs.py "docs/work/F02-DesktopGUI交互与上下文缺陷修复/feedback/W04-desktop-settings-feedback.md" "docs/work/F02-DesktopGUI交互与上下文缺陷修复/F02-DesktopGUI交互与上下文缺陷修复-checklist.md"`：通过。
- 以上证据对应 Checklist T07 九项，均已勾选；未把人工 Electron/DPI/zoom/真实 Provider 网络验收写成自动测试通过。

### 风险、未验证项与清理

- 尚未执行真实 Electron 窗口中的人工键盘、鼠标、DPI/zoom、系统深浅色切换和 reduced-motion 视觉验收；自动测试覆盖 DOM、键盘/focus/ARIA、locale/CSS 约束及三主题类名。
- 未连接真实 Provider，也未在测试中写入真实 API Key；`env:` reveal 的环境变量解析被明确禁止且由测试断言不会发生。
- CDP Settings acceptance 仍由后续工作包按新 Settings DOM 适配，本轮按冻结 Prompt 未修改 CDP harness。
- 工作区未执行任何 Git 写操作；未创建额外临时文件、缓存或构建产物。

## Reviewer 返工（T07）

本节仅追加在本文 EOF，未覆盖首次实施记录；本轮继续不执行任何 Git 写操作。

### Finding 处置

- P2-1：`ModelEditorSnapshot` 同时保存模型 profile 与 `default_model`。Model 编辑中切换为非默认模型、勾选 Default 后按 Cancel 会恢复原 profile 和原默认模型；Renderer 测试在随后 Global Save request 中确认仍为原默认模型。
- P2-2：`settings.save` 返回成功即作为 durable boundary，Settings 的 `settingsSaving`、reveal、replacement、touched 生命周期不再等待 Runtime recovery；`project.open`、`session.resume`、`status.get`、`project.sessions` 的后续失败统一单独呈现为 Runtime recovery error，不写回 Settings error，也不重发已保存明文。测试另以延迟 `project.open` failure 证明恢复尚未结束时 Save 已解除且重新打开 Provider 的 Key 输入为空，并覆盖四个失败边界及后续 Save 无 Key。
- P2-3：Base URL 与 display name 的受控输入在编辑期保留用户输入（包括首尾空格和真实内部空格）；Provider Apply、Model Apply 与最终 Save 才按现有配置规则做边界规范化。Renderer 使用实际 `My Model` 输入回归，确认编辑期保留、Apply/Save 后得到规范化值。
- P2-4：嵌套 Model modal 打开时底层 Provider dialog 同时 `aria-hidden` 且 `inert`，移除底层 `aria-modal`；只有顶层 Model dialog 保留 `aria-modal=true`。测试覆盖可访问树唯一 modal、Tab/Shift+Tab 双向 trap、Escape 关闭和返回触发该 Model row 的焦点。
- P2-5：Bridge 的所有普通 Mapping、Application DTO 和 AgentEvent 投影均经过递归 secret-field 过滤；synthetic sentinel 回归覆盖 `settings.get`、`status.get`、events、diagnostics、errors、Runtime snapshots。Preferences 持久层只接受 UI metadata，Runtime diagnostic/log 边界只向 Renderer 发送固定无细节消息；对应 Preload persistence/diagnostic tests 与既有 stdout/stderr boundary tests 均未发现 sentinel 穿透。不存在独立 logs API，未凭空增加接口。
- P3：删除 Renderer/test-only 的 `renameProviderId`、`providerOriginalIds`、`provider_renames` 旧链与相关测试；Provider identity 仍以配置 key 生成/保留，Provider modal 没有 identity 编辑入口。现存 Application public configuration `provider_renames` 不是该 Renderer 旧链，按“不改变公共配置模型”边界保留。

### 返工后精确验证

- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_configuration.py tests/test_desktop_bridge.py -q`：116 passed in 8.83s。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q`：23 passed in 4.82s。
- `conda run --no-capture-output -n re-uthcode npm run typecheck`（cwd=`desktop`）：通过。
- `conda run --no-capture-output -n re-uthcode npx tsx --test tests/renderer.test.tsx`（cwd=`desktop`）：86 passed in 8.01s。
- `conda run --no-capture-output -n re-uthcode npx tsx --test tests/preload.test.ts`（cwd=`desktop`）：10 passed in 0.38s。
- `conda run --no-capture-output -n re-uthcode npm test`（cwd=`desktop`）：最终 123 passed、0 failed in 54.80s，包含 T07/Preload/Runtime/Main bundle/packaging/CDP isolation 全量集合。此前一次全量运行出现既有 T05 buffered-turn timing 1 项波动（122 passed/1 failed），该用例独立重跑通过，随后全量重跑 123/123；此时序敏感性列入风险，不把首次失败隐去。
- `rg -n 'renameProviderId|providerOriginalIds' desktop/src/renderer desktop/tests`、`rg -n 'renameModelRef|model-1|clearKey' desktop/src/renderer desktop/tests`、`rg -n 'provider_renames' desktop/src/renderer desktop/tests`：均 0 matches。
- credential-pattern scan（`sk-`/GitHub/Slack token 形态，生产源与对应 tests）以及 production secret-literal scan：均 0 matches；测试仅使用 synthetic sentinel，不含真实凭据。
- `git diff --check`：exit 0；仅有 Git 的 LF/CRLF 转换提示，无 whitespace error。
- `conda run --no-capture-output -n re-uthcode python C:\Users\93445\.codex\skills\uth-utf8-guard\scripts\check_utf8_docs.py "docs/work/F02-DesktopGUI交互与上下文缺陷修复/feedback/W04-desktop-settings-feedback.md" "docs/work/F02-DesktopGUI交互与上下文缺陷修复/F02-DesktopGUI交互与上下文缺陷修复-checklist.md"`：`OK: 2 file(s) passed UTF-8 guard`。

### Checklist 与风险

- T07 Checklist 仅维持已有九项 `[x]`；每项均有上述定向测试、投影边界测试或扫描证据，T08 及其他未授权条目未勾选。
- 首次全量 Desktop suite 的 T05 buffered-turn test 出现一次非确定性计数波动，独立重跑及后续全量重跑均通过；仍建议后续关注高负载下的 timer/poll 测试稳定性。
- 未在真实 Electron 窗口执行人工键盘/鼠标、可访问性树读取、DPI/zoom、系统主题或 reduced-motion 视觉验收；未连接真实 Provider/网络，也未写入真实 API Key。
- CDP harness、Main/Preload 源码、Python Runtime、T10 和 current-facts 仍未修改；本轮未执行 commit、push、merge、rebase、tag、release 或归档。

## 第二轮复审返工（T07 P1：Runtime recovery ownership）

本节继续只追加在本文 EOF，未覆盖前两轮记录；未写入任何真实 API Key，且未执行 Git 写操作。

### Finding 处置

- P1：在现有 App 内增加最小 Runtime lifecycle tail 与 generation ownership。`startup`、Settings durable-save 后的 `recovery`、项目/会话 `navigation` 共用同一 Promise tail，同一时刻只允许一个生命周期操作触达 Runtime；后来的 durable Save 或导航立即取得新 generation，旧操作即使其已发出的 RPC 迟到成功/失败，也会在下一边界停止，不能继续 `runtime.initialize`/`project.open`/`session.resume` 或 dispatch 旧 `project_opened`、`session_resumed`、`runtime_state`、`runtime_error`。卸载递增 generation 并清除 owner，迟到 recovery 不再写回。
- P1：Settings `settings.save` 仍以 durable response 为边界，立即清除 transient reveal/replacement/touched 状态；detached recovery 不再把 Settings saving 生命周期延长。recovery 期间 Runtime 明确为 `restarting`，Provider/Model 投影保留该状态，成功/失败 terminal 后分别恢复 `ready` 或呈现独立 Runtime error；设置页显示可访问的 restarting status，导航与其他 Runtime projection 等待同一 lifecycle tail。
- P1：`rebootstrapProject` 增加可选 ownership check，并在 shutdown、initialize、project.open、session.resume 以及 callback 前逐段校验，避免旧成功/失败跨代传播。快速重复 Save 由 renderer-local in-flight ref 去重，不新增通用 Manager 或跨模块锁。

### P1 定向回归

- `T07 newer durable Save supersedes a blocked recovery without concurrent Runtime ownership`：Save A 的 shutdown 阻塞时接受 Save B；A 不再继续旧 lifecycle，B 等待同一 RPC 完成后按 shutdown → initialize → project.open → session.resume 串行接管，最终 Runtime 为 Ready，且无迟到 Runtime error。
- `T07 navigation supersedes blocked recovery and unmount suppresses late lifecycle writes`：项目导航使 blocked recovery 失效并等待，不并发 project.open；随后第二次 recovery 在卸载后其迟到 shutdown 不再进入 project.open。
- `T07 duplicate Save clicks issue one durable request`：同一同步点击窗口只产生一个 `settings.save`。
- `T07 rebootstrap ownership stops stale lifecycle calls and callbacks`：ownership 在生命周期边界翻转后只保留已发出的前置调用，project/session callback 均不执行。
- 既有 durable Settings failure matrix 继续覆盖 project.open、session.resume、status.get、project.sessions 失败，以及延迟 project.open 时 durable Save 先完成、Key 草稿清空、后续 Save 不重发明文。

### 第二轮 P1 精确验证

- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_configuration.py tests/test_desktop_bridge.py -q`：116 passed in 7.55s。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q`：23 passed in 5.01s。
- `conda run --no-capture-output -n re-uthcode npm run typecheck`（cwd=`desktop`）：通过。
- `conda run --no-capture-output -n re-uthcode npx tsx --test tests/preload.test.ts`（cwd=`desktop`）：10 passed in 0.35s。
- `conda run --no-capture-output -n re-uthcode npx tsx --test tests/renderer.test.tsx`（cwd=`desktop`）：90 passed in 9.44s；新增 P1 定向用例与既有 T05 timing 用例均通过。
- `conda run --no-capture-output -n re-uthcode npm test`（cwd=`desktop`）：127 passed、0 failed in 53.59s，覆盖 Preload、Runtime process、Main bundle、Renderer、Windows packaging 与 CDP isolation。
- 额外直接 `npm test`（未进入 `re-uthcode`）曾因环境未提供 Python executable 使 offline Runtime 单测失败；按项目要求改用上述 Conda 命令后全量 127/127 通过，未将环境失败误记为代码通过或代码缺陷。
- `git diff --check`：exit 0；仅有 Git 的 LF/CRLF 转换提示，无 whitespace error。
- `conda run --no-capture-output -n re-uthcode python C:\Users\93445\.codex\skills\uth-utf8-guard\scripts\check_utf8_docs.py "docs/work/F02-DesktopGUI交互与上下文缺陷修复/feedback/W04-desktop-settings-feedback.md" "docs/work/F02-DesktopGUI交互与上下文缺陷修复/F02-DesktopGUI交互与上下文缺陷修复-checklist.md"`：待本节写回后运行并记录最终结果。

### P1 风险与边界

- Runtime lifecycle 已在 App 内串行，但无法取消已经发出的底层 RPC；generation 只保证其后不再触达/写回，若 Runtime 本身在 shutdown 中卡住，后继操作会按设计保持 restarting 并等待该边界。
- 未在真实 Electron 窗口执行人工键盘/鼠标、DPI/zoom、系统主题或 reduced-motion 视觉验收；未连接真实 Provider/网络，也未写入真实 API Key。未修改 Main、Preload、Python Runtime、T10、CDP harness 或 current-facts。

### P1 文档写回确认

- 上述 UTF-8 guard 命令最终结果：`OK: 2 file(s) passed UTF-8 guard`。

### P1 最终扫描

- `rg -n 'renameProviderId|providerOriginalIds|renameModelRef|model-1|clearKey|provider_renames' desktop/src/renderer desktop/tests`：0 matches。
- production source boundary-aware credential-pattern scan（`sk-`、GitHub、Slack token 形态，目标 `src/uthcode` 与 `desktop/src`）：0 matches；production debug-residue scan（`console.log`/`console.debug`/`debugger`）：0 matches。
- changed-file核对仍只包含此前 W04 授权的 Config/Application/Bridge/Desktop API/Settings/共享 Renderer/tests 与本 Feedback/Checklist；未出现 Main、Preload、Python Runtime、T10、CDP 或 current-facts 文件的新改动。工作区未执行 Git 写操作。

### 第二轮最终重跑确认

- 在事件 envelope 过滤、启动竞态保护和卸载前 durable continuation guard 的最后调整后，`conda run --no-capture-output -n re-uthcode npm test`（cwd=`desktop`）再次为 127 passed、0 failed，耗时 53.31s。

## 第三轮复审返工（T07 P1：owner terminal cleanup 与 Composer 生命周期门禁）

本节继续只追加在本文 EOF，未覆盖既有记录；未写入任何真实 API Key，且未执行 Git 写操作。

### Finding 处置

- P1-1：App 内 lifecycle owner 现在在 operation `finally` 按 generation、owner identity 与 promise identity 校验后清空；旧 owner 的迟到 finally 不能清除新 owner。`waitForRuntimeLifecycleIdle` 会在 owner terminal 后重新观察 tail，清理完成即返回 idle，未再依赖 unmount 才释放。成功 terminal 发布 `ready`/`stopped`，失败保留独立 Runtime error 后释放 owner。
- P1-1：补充 terminal recovery 后的普通 `settings.get`、`status.get`、`project.sessions` 与 `runtime_state` event 回归；恢复前的旧 `runtime_state` envelope 仍被 owner 拦截，恢复后的 stopped/ready envelope 可正常更新 Runtime projection。既有 Save A/Save B 用例继续证明 stale owner 不能清除新 owner 或阻断其生命周期。
- P1-2：Composer 将 `runtimeState === "restarting"` 纳入统一 `inputLocked`，文本框、发送、暂停、取消、Permission/Model 控件均带 disabled；completion menu 在 recovery 中隐藏，文本框通过 `aria-describedby` 关联 restarting 状态，Composer 保留 `aria-disabled` 与中英文提示。`submitComposer`、`executeCommand`、`completeCommand`、Interaction resume/cancel、pause、Session rename/move、API-key reveal 等用户 Runtime 入口在已有 owner 时统一等待 lifecycle idle；Settings durable save 继续遵守既有“持久化成功即脱离 Settings transient 状态、由新 generation 接管 recovery”的产品语义。
- P1-2：Settings→Back 返回聊天时保持 Composer 的 recovery 门禁；terminal 后自动恢复可发送/补全。Settings 导航在读取配置前等待 lifecycle idle，避免 recovery 期间进入可保存的 Settings 页面；项目/Session 入口继续经同一 navigation tail 串行化。

### 第三轮 P1 定向回归

- `T07 Composer locks every chat control while Runtime recovery owns the lifecycle`：restarting 状态下验证 Composer `aria-disabled`、文本框/发送/暂停/取消/Permission/Model disabled、restarting placeholder/说明及 completion 隐藏。
- `T07 completed lifecycle owner releases ordinary refreshes and runtime events`：Save shutdown pending→Back 后发送与 Model/Slash completion 入口不发 RPC；terminal 后 Composer 解锁、completion 恢复，普通 command 触发 `status.get` 与 `project.sessions`，Settings 触发 `settings.get`，owner 清理后的 runtime_state stopped/ready event 均正常生效。
- `T07 newer durable Save supersedes a blocked recovery without concurrent Runtime ownership` 与 `T07 navigation supersedes blocked recovery and unmount suppresses late lifecycle writes`：继续覆盖旧 owner 迟到、导航接管、卸载 stale 与新 owner 保持，证明 stale finally 不会清空新 owner。

### 第三轮精确验证

- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_configuration.py tests/test_desktop_bridge.py -q`：116 passed in 7.18s。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q`：23 passed in 5.16s。
- `conda run --no-capture-output -n re-uthcode npm run typecheck`（cwd=`desktop`）：通过。
- `conda run --no-capture-output -n re-uthcode npx tsx --test tests/preload.test.ts`（cwd=`desktop`）：10 passed in 0.37s。
- `conda run --no-capture-output -n re-uthcode npx tsx --test tests/renderer.test.tsx`（cwd=`desktop`）：92 passed、0 failed。
- `conda run --no-capture-output -n re-uthcode npm test`（cwd=`desktop`）：129 passed、0 failed，耗时 54.22s，覆盖 Preload、Runtime process、Main bundle、Renderer、Windows packaging 与 CDP isolation 全量集合。
- `git diff --check`：exit 0；仅有 Git 的 LF/CRLF 转换提示，无 whitespace error。
- legacy chain scan（`renameProviderId`、`providerOriginalIds`、`renameModelRef`、`model-1`、`clearKey`、`provider_renames`，目标 `desktop/src/renderer desktop/tests`）：0 matches。
- production source credential-pattern scan（`sk-`、GitHub、Slack token 形态，目标 `src/uthcode desktop/src`）：0 matches；production secret-literal scan：0 matches；production debug-residue scan（`console.log`/`console.debug`/`debugger`）：0 matches。

### 风险与未验证项

- 已发出的底层 Runtime RPC 不能被 Renderer 取消；generation/owner 只阻止其后续 lifecycle 调用和 reducer/event 写回，底层 shutdown 若卡住，后继 Save/导航按设计等待并维持 restarting。
- 未在真实 Electron 窗口执行人工键盘/鼠标、可访问性树、DPI/zoom、系统主题或 reduced-motion 视觉验收；未连接真实 Provider/网络，也未写入真实 API Key。
- Checklist T07 仅维持已有九项 `[x]`，未勾选其他条目；本轮只修改授权 Renderer/tests 与本 Feedback EOF。

## 第三轮复审补充（terminal event poll gate）

本节仍为 EOF 追加；此前记录、Checklist 与 Git 状态均未覆盖或改写。

- 对 recovery owner 期间到达的 terminal AgentEvent 增加补充 poll 门禁，避免事件触发的 `status.get` 与 shutdown/rebootstrap 并发；仅生命周期 owner 内部 `closeActiveTurn` 的已授权 poll 保留。Settings→Back→聊天门禁测试新增 recovery 阻塞期间 terminal event 无 status RPC 断言。
- 最后一轮验证：`conda run --no-capture-output -n re-uthcode python -m pytest tests/test_configuration.py tests/test_desktop_bridge.py -q` 为 116 passed in 7.01s；`conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q` 为 23 passed in 5.32s；`conda run --no-capture-output -n re-uthcode npm run typecheck` 通过；`conda run --no-capture-output -n re-uthcode npx tsx --test tests/preload.test.ts` 为 10 passed；Renderer 为 92 passed；`conda run --no-capture-output -n re-uthcode npm test` 为 129 passed、0 failed，耗时 54.54s。
- 最后一轮 `git diff --check` exit 0（仅 LF/CRLF 转换提示）；legacy chain、credential-pattern、production secret-literal 与 production debug-residue 扫描仍均为 0 matches。UTF-8 guard 在本节追加后执行并通过：`OK: 2 file(s) passed UTF-8 guard`。

## 第三轮最终复核确认

- 在上一轮记录后仅继续收敛 lifecycle gate 与 Composer disabled 断言；最终独立 Renderer 全量 `conda run --no-capture-output -n re-uthcode npx tsx --test tests/renderer.test.tsx`：92 passed、0 failed（10.01s）。同一时段一次并发运行出现既知 `T05 buffers synchronous turn.start stdout...` 计数波动（128/129），该用例独立重跑通过，随后全量 Desktop 重跑通过；不隐去该时序风险。
- 最终 Python 配置/Bridge：116 passed in 7.76s；架构边界：23 passed in 5.33s；typecheck：通过；Preload：10 passed；`conda run --no-capture-output -n re-uthcode npm test`：129 passed、0 failed（55.49s）。
- 最终 legacy chain、credential-pattern、production secret-literal、production debug-residue 扫描均为 0 matches；`git diff --check` exit 0（仅 LF/CRLF 转换提示）。本节追加后重新执行 UTF-8 guard：`OK: 2 file(s) passed UTF-8 guard`。

## 第四轮复审返工（T07 P1：durable Save 纳入 lifecycle owner）

本节继续只追加在本文 EOF，未覆盖既有记录；未写入任何真实 API Key，且未执行任何 Git 写操作。

### Finding 处置

- P1：`settings.save` 请求现在由现有 App-local lifecycle tail 发起。generation/owner 在 RPC 发出前同步建立，durable Save 与后续 `runtime.shutdown`、`runtime.initialize`、`project.open`、`session.resume`、status/catalog projection recovery 共用同一串行 ownership；同一时刻不会并发操纵 Runtime。新 Save/项目导航可接管 generation，旧 owner 只允许已发出的 Save response 安全收敛，不再 dispatch `settings_loaded`、旧 `project_opened`/`session_resumed` 或启动旧项目 recovery。
- P1：durable response 使用独立的本地 completion boundary。成功 response 即释放 `settingsSaving`，Settings 清理 reveal/replacement/touched 瞬态；后续 recovery 失败单独呈现 Runtime error。失败 response 不重试、不把不可确认副作用当作可安全重发；若 response 已 stale，只取消旧调用方而不覆盖新 owner 的 Settings/runtime 状态。
- P1：durable Save pending 时 Settings Back/Cancel 在 DOM 与 App callback 两层门禁，避免同一事件循环内绕过 React state；reveal 与其余 Runtime 入口仍等待 lifecycle idle，Project/Session 导航经同一 tail 接管或等待，Composer/runtime projection 继续保持 restarting 门禁。

### 第四轮 P1 定向回归

- `T07 durable Save owns the lifecycle before its RPC, gates Back, and lets newer navigation supersede stale recovery`：项目 A 的 `settings.save` 延迟期间仅有 Save RPC、没有 shutdown，Back/Cancel 均 disabled 且无法离开 Settings；durable response 后恢复开始，随后导航项目 B 等待 A 已发出的 shutdown，旧 A recovery 不再 initialize/open/resume，最终只打开 B 并恢复 Ready。
- `T07 durable Save failure releases its lifecycle owner without starting Runtime recovery`：durable Save 失败只产生 Settings error，未发出任何 Runtime recovery RPC，Save 返回可操作状态。
- `T07 unmount invalidates a pending durable Save without continuing its old recovery`：卸载后迟到 Save response 不发布 Settings projection，也不继续旧项目 recovery。
- `T07 newer durable Save supersedes a blocked recovery without concurrent Runtime ownership`：后续 Save 等待前一个已发出的生命周期 RPC；调整断言确认第二个 `settings.save` 不会与第一个 shutdown 并发。
- `T07 duplicate Save clicks issue one durable request`：同一同步点击窗口仍只有一个 durable request；既有 recovery failure matrix、terminal owner cleanup、Composer Runtime gate 回归继续通过。

### 第四轮精确验证

- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_configuration.py tests/test_desktop_bridge.py -q`：116 passed in 8.28s。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q`：23 passed in 5.97s。
- `conda run --no-capture-output -n re-uthcode npm run typecheck`（cwd=`desktop`）：通过。
- `conda run --no-capture-output -n re-uthcode npx tsx --test tests/preload.test.ts`（cwd=`desktop`）：10 passed。
- `conda run --no-capture-output -n re-uthcode npx tsx --test tests/renderer.test.tsx`（cwd=`desktop`）：95 passed、0 failed。
- `conda run --no-capture-output -n re-uthcode npm test`（cwd=`desktop`）：132 passed、0 failed in 55.60s，覆盖 Preload、Runtime process、Main bundle、Renderer、Windows packaging、CDP isolation 与现有 T08 build smoke。
- `rg` legacy-chain、credential-pattern、production-secret-literal、production-debug-residue scans：均 0 matches；`git diff --check`：exit 0，仅有 Git 的 LF/CRLF 转换提示。
- 本节追加后执行 `conda run --no-capture-output -n re-uthcode python C:\Users\93445\.codex\skills\uth-utf8-guard\scripts\check_utf8_docs.py "docs/work/F02-DesktopGUI交互与上下文缺陷修复/feedback/W04-desktop-settings-feedback.md" "docs/work/F02-DesktopGUI交互与上下文缺陷修复/F02-DesktopGUI交互与上下文缺陷修复-checklist.md"`：待执行最终记录。

### Checklist 与风险

- T07 Checklist 继续只保留已有九项 `[x]`；本轮新增的 lifecycle/Save 门禁证据已写入 Feedback，未勾选 T08 或其他未授权条目。
- 已发出的底层 Runtime/Save RPC 不能由 Renderer 取消；generation/owner 只阻止 stale response 后续 Runtime 调用和 reducer/event 写回。Runtime shutdown 若长期不返回，后继 Save/导航按设计等待并保持 restarting。
- 未在真实 Electron 窗口执行人工键盘/鼠标、可访问性树、DPI/zoom、系统主题或 reduced-motion 视觉验收；未连接真实 Provider/网络，也未写入真实 API Key。未修改 Main、Preload、Python Runtime、T10、CDP harness 或 current-facts。

本节列出的 UTF-8 guard 已执行并通过：`OK: 2 file(s) passed UTF-8 guard`。

## 第五轮复审返工（T07 P1：durable Save 期间 Settings 全面门禁）

本节仅追加在本文 EOF，未覆盖既有记录；未写入任何真实 API Key，未执行 Git 写操作。

### Finding 处置

- P1：Settings 根面在 durable Save pending 期间暴露 `aria-busy="true"`，通过 `aria-describedby` 关联可聚焦的中英文忙碌状态提示；Settings content 同时暴露 `aria-disabled`。Add Provider、Provider row、默认权限/模型、主题、语言、Save/Cancel/Back，以及 Provider/Model modal 的 open、edit、delete、input、select、Apply、reveal 和确认入口均使用 native `disabled` 与回调门禁，不能产生新的 draft、replacement 或偏好写入。
- P1：若 Save 由程序化调用从已打开 modal 发起，Settings 在 saving 状态边界关闭 Provider/Model modal，清理 reveal cache 但保留 draft/replacement/touched 供失败语义使用；busy status 在锁定期间获得焦点，durable 成功或失败后 Save action 恢复焦点。Provider delete confirmation 的直接状态入口也保留同一 Settings lock 检查；App 的 Back/theme/language callback 继续保留 `settingsSaving` 与 in-flight 双门禁。
- P1：CustomSelect 在 disabled 状态关闭已展开 listbox 并释放 trigger focus，避免菜单残留；disabled controls 使用 raised surface、line-strong 与可读 muted 文本，Save 保留清晰的 accent 状态；busy status 同时提供文字、左边界和旋转指示，不依赖纯颜色。暗色/浅色 busy disabled 对比度断言及 reduced-motion CSS 合约继续覆盖。

### 第五轮 P1 真实 DOM 回归

- `T07 durable Settings Save locks the real Settings DOM and clears an A draft after success`：真实 App/Settings DOM 中让项目 A 的 Provider modal（含嵌套 Model modal）保持打开后发起 Save；断言 Settings `aria-busy`、忙碌 status/focus、modal 关闭、Save RPC 先于 Runtime recovery、所有 Add/Provider/default/theme/language/Back/Cancel/Save 入口 disabled；尝试 Provider、theme/language、Add Provider/Add Model 与旧 modal input 均不产生第二次保存或 B draft；durable success 后 transient replacement 清理、配置投影准确恢复且 recovery 状态最终退出。
- `T07 durable Settings Save failure keeps the A draft after the modal closes and re-enables editing`：真实 DOM 中 Save pending 期间关闭 modal，durable failure 后 Settings error 呈现、busy 解除、A 的编辑期 URL/replacement 保留，Provider/Model 数量不变且字段可再次编辑。
- `main workspace visual contract keeps 16px SVGs and readable theme tokens`：补充 busy indicator 非纯颜色 cue、spin keyframe、busy disabled surface/text 选择器和暗/浅色 raised surface 对比度断言。

### 第五轮精确验证

- `conda run --no-capture-output -n re-uthcode npm run typecheck`（cwd=`desktop`）：通过。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_configuration.py tests/test_desktop_bridge.py -q`：116 passed in 8.21s。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q`：23 passed in 5.38s。
- `conda run --no-capture-output -n re-uthcode npx tsx --test tests/preload.test.ts`（cwd=`desktop`）：10 passed。
- `conda run --no-capture-output -n re-uthcode npx tsx --test tests/renderer.test.tsx`（cwd=`desktop`）：97 passed、0 failed。
- `conda run --no-capture-output -n re-uthcode npm test`（cwd=`desktop`）：134 passed、0 failed in 58.43s，覆盖 Preload、Runtime process、Main bundle、Renderer、Windows packaging、CDP isolation 与 T08 smoke。
- legacy-chain、credential-pattern、production-secret-literal、production-debug-residue 四类扫描：均 0 matches；`git diff --check`：exit 0，仅有 Git 的 LF/CRLF 转换提示。
- T07 Checklist 继续只保留已有九项 `[x]`；本轮只修改授权 Settings/共享 Renderer/tests 与本 Feedback EOF，未改 Main、Preload source、Python Runtime、T10、CDP 或 current-facts。

### 风险与未验证项

- 已发出的 durable Save/Runtime RPC 仍不能由 Renderer 取消；本轮门禁阻止 pending 期间的 UI 与程序化新 draft/入口，底层调用若长期不返回仍按既有 lifecycle ownership 保持 restarting。
- 未在真实 Electron 窗口执行人工键盘/鼠标、可访问性树、DPI/zoom、系统主题或 reduced-motion 视觉验收；未连接真实 Provider/网络，也未写入真实 API Key。
