# W04 Settings 与 Markdown Feedback

## 结果

T04 已完成最小闭环，未执行 Git 写操作。Settings Provider/Model 现在共用一个 modal root、focus trap、return-focus owner 与 transaction；modal 生命周期将 Settings 背景导航/内容标记为 `inert` 与 `aria-hidden`，Model Back 返回 Provider，Cancel 回滚整笔草稿，Save 仍只通过既有 Configuration write。API Key 的 reveal 值只存在 editor-local lifecycle，关闭/取消/卸载后丢弃；只有显式 replacement 才进入保存请求，失败时保留 replacement 以便重试，成功后清除。

Markdown 保留原有安全子集并迁至 `safe-markdown.tsx`，禁止 raw HTML 与 unsafe URL；Code Fence 增加 language label、原文 Copy 及局部成功/失败反馈。Main/Preload/API 将 Session 专用 clipboard 收敛为经 sender/frame/origin 校验的 `copyText(text)`，Session ID 与 Code Fence 共用同一窄边界，Renderer 未直接取得 Electron/clipboard 对象。ChatTimeline 在用户离底后保持 scroll position，新增显式新消息/回到底部入口，点击后恢复 follow-tail。

## 修改文件

- `desktop/src/renderer/SettingsEditorModal.tsx`
- `desktop/src/renderer/settings-draft.ts`
- `desktop/src/renderer/safe-markdown.tsx`
- `desktop/src/renderer/SettingsView.tsx`
- `desktop/src/renderer/ChatTimeline.tsx`
- `desktop/src/renderer/App.tsx`
- `desktop/src/renderer/app.css`
- `desktop/src/renderer/locales/en.ts`
- `desktop/src/renderer/locales/zh-CN.ts`
- `desktop/src/desktop-api.ts`
- `desktop/src/preload.ts`
- `desktop/src/main.ts`
- `desktop/tests/renderer-settings.test.tsx`
- `desktop/tests/renderer-chat.test.tsx`
- `desktop/tests/renderer.test.tsx`
- `desktop/tests/renderer-runtime-lifecycle.test.tsx`
- `desktop/tests/preload.test.ts`
- `desktop/tests/render-settings-interactions-visual-fixture.tsx`
- `desktop/scripts/cdp-settings-acceptance.mjs`
- `desktop/package.json`
- 本 Feedback 与 Checklist 的 T04 项

## 验证记录

- `conda run --no-capture-output -n re-uthcode npm --prefix desktop run typecheck`：exit code 0。
- `conda run --no-capture-output -n re-uthcode npm --prefix desktop test`：exit code 0，173 passed，0 failed，0 skipped。
- `conda run --no-capture-output -n re-uthcode node scripts/build-settings-acceptance.mjs`（cwd `desktop`）：exit code 0，Webpack fixture 编译成功。
- `conda run --no-capture-output -n re-uthcode node scripts/cdp-settings-acceptance.mjs`（cwd `desktop`）：exit code 0；Settings dark/light/narrow 截图成功，单 modal root/focus、Model step、Cancel rollback、reveal lifecycle、replacement write、语言写回、structure 与 console error 检查均通过。
- `git diff --check`：exit code 0。
- Renderer boundary scan：无直接 `window`/`navigator.clipboard` 或 Electron import 命中。

## 偏差、未完成项与风险

- CDP 使用当前机器可用的 headless Edge 与隔离临时 profile；未执行真实 Provider、干净 Windows 人工视觉检查，也未触碰 `.workbuddy/` 或 `临时目录/`。
- CDP 产出的 `desktop/dist/ui-acceptance/prompt-2` 截图/报告属于可再生成验收产物；未纳入源码范围。
- 既有 Sidebar 的用户可见文案仍称 Session ID，这是产品入口名称；底层 API 已统一为 `copyText`。

## Checklist

仅勾选 F03 Checklist 的 T04 八项，未修改其他任务项。

## 返工第 1 轮（Review REQUEST CHANGES）

针对 Review 的四项意见完成最小修复，未执行 Git 写操作：

- Settings API Key 输入改为 editor-local `replacementTouchedLocal` 与 `replacementValue`，每次 input 都先更新本地受控值，再把显式 replacement 写入父级 ref；连续输入不会因父 ref 不触发 render 而回退或只保留末字符。
- Model Back/Apply 不再保存已卸载的 DOM 节点，改以稳定 model ref 和重挂载后的 `data-model-edit-ref` 触发器恢复焦点；测试覆盖 Back 与 Apply 两条路径。
- `.timeline-new-messages` 增加可见 `top: 12px` sticky inset；CDP chat harness 在真实 Edge 几何中以 scrollTop 500 验证按钮仍处于 timeline viewport 内。
- safe Markdown 用原始正文 slice 作为 fence copy 内容，只用逐行文本做解析；empty、CRLF、blank、trailing whitespace、unclosed fence 均保持原始换行与空白，不再无条件追加 newline。

### 返工验证

- `conda run --no-capture-output -n re-uthcode npm --prefix desktop run typecheck`：exit code 0。
- `conda run --no-capture-output -n re-uthcode npm --prefix desktop test`：exit code 0，174 passed，0 failed，0 skipped。
- 定向 Settings/Markdown 测试：6 passed，0 failed。
- `conda run --no-capture-output -n re-uthcode node scripts/build-settings-acceptance.mjs`（cwd `desktop`）：exit code 0。
- `conda run --no-capture-output -n re-uthcode node scripts/cdp-settings-acceptance.mjs`（cwd `desktop`）：exit code 0；modal a11y、Model step、rollback、reveal lifecycle、replacement write、language hydrate、structure、console errors 均通过；chat 几何为 `scrollTop=500` 后按钮出现时 `top=12px`、`buttonTop=96`、`buttonBottom=126`、`timelineTop=50`、`timelineBottom=900`、`visible=true`。
- `git diff --check`：exit code 0。
- 修改后的 Feedback 与既有 Checklist 运行 UTF-8 guard：2 files passed。

### 返工未验证项与清理

真实 Provider、干净 Windows 人工视觉检查仍未运行；CDP 使用当前机器可用的 headless Edge 与隔离临时 profile。CDP 截图/报告为可再生成验收产物，未纳入源码范围；未触碰 `.workbuddy/` 或 `临时目录/`。
