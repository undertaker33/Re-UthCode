# W03 Renderer 导航与审阅 — Feedback

## 首轮实施记录

基于 `51df763823beb6102d0154379a04a92ff1a28c72`，使用既有 `re-uthcode` Conda 环境。完成 T07 → T08 → T09 → T10；没有新增目录、没有改动后端协议/配置持久化，没有提前实施 W04。`workspace.diff`、事件、工具结果续读和归档操作均沿用 W02 已合并合同，本轮未发现阻断 Renderer 的协议缺口。

### 实际交付

- **T07 导航与 owner**：接入 Coding/General 切换、各自 Recent/Session 导航和真实搜索操作。General 固定使用 `uthcode:general`，不作为 Coding 项目持久化；搜索事件在 RPC kickoff 回包之前到达时按 operation 身份短暂缓冲，提交及结果均校验 mode/project/Session/view revision 与 owner，迟到结果不覆盖当前选择。归档继续走当前 Session 菜单和既有 archive RPC；Settings 归档管理留 W04。
- **T08 过程分组**：从当前 Timeline 派生相邻 Tool activity group，跨 batch 合并，遇到公开消息、reasoning、交互或失败等可见内容切组；组默认折叠，最终回答独立直显。计时只使用 W02 投影的 `started_at`/`completed_at`；缺少历史时间明确显示不可用。inline preview 与截断标志、外部 `output_ref` 续读保持原安全来源。
- **T09 统一审阅**：当前 Diff、文件/Markdown/图片、工具输出和 Process log 汇入按当前 owner 隔离的 ReviewPanel tabs。Diff 只接受匹配 operation/owner 的 `completed` DTO；kickoff 前到达的事件可配对，导航/关闭后取消或丢弃迟到结果。工具外部结果通过既有 `tool_result.read` 分页读取，Renderer 请求上限不超过 64 KiB；安全 Markdown、attachment preview 与原图缩放继续使用既有入口。历史 `file_changes` 与 `current_working_tree` Diff 分开标识，不以当前工作树伪造历史。
- **T10 Composer**：Model/Permission picker 的成功、业务失败、RPC 失败和关闭 picker 不清空待发输入，控件操作不发 Turn。General 仅提交文本并显示 Model/取消；Coding 保留附件与 Permission。Draft 依 mode/project/Session 缓存。提交捕获 owner、Session view revision、draft revision、文本和 attachment ref 向量；当前 owner 只清仍与提交版本匹配的字段。`turn.start` 成功回包前若用户已导航，完整 Run/Turn identity 才触发 offscreen receipt；该 receipt 仅清捕获 owner 中未编辑的 draft，惰性 Session 的剩余版本按需迁移，不改变新选中的 Session/Timeline。失败或后续编辑（即使文本改回原值）会使对应 revision 不匹配并保留草稿。附件按完整有序 ref 向量比较；后来添加附件时保留整个编辑后向量，不逐 ref 扣除。

### 修改文件

生产与测试：`desktop/src/renderer/App.tsx`、`Sidebar.tsx`、`state.ts`、`state-session.ts`、`state-normalization.ts`、`ChatTimeline.tsx`、`Composer.tsx`、`DocumentPreviewPanel.tsx`、`FileCard.tsx`、`UiIcon.tsx`、`app.css`、`locales/en.ts`、`locales/zh-CN.ts`；`desktop/tests/renderer-attachments.test.tsx`、`renderer-state.test.ts`、`renderer.test.tsx`。本 Feedback 新建于现有 T12 目录；Checklist 仅勾选两个已完整验证项。`Context-Index.md` 由总控维护。

### 遗留负担清理证据

1. `App.tsx: documentPreview` 单一预览 state/setter → 实际调用者为 Composer/FileCard、ChatTimeline 文件入口、Diff/Tool/Process 审阅按钮 → 单内容状态无法同时保留并切换异类审阅 tab，且原 Session owner 需要统一过滤 → 改为 `reviewPanel` tab state 与统一 owner；原 `DocumentPreviewPanel` 仍作为文件 tab 内容复用 → `T09 App reviews...`、附件/Markdown/图片用例及完整受影响文件套件通过 → packaged/native 视觉和关闭/重开人工验收仍留 T15。
2. `state.ts: command_result.preserveComposer` 分支/包装参数 → 实际调用者是 `App.executeCommand` 的 typed command result → picker、模型、Permission 结果不应写 Composer draft，原特殊清理分支令同一 reducer 兼任命令反馈与文本提交 → 删除该分支和参数，文本只由明确编辑/Turn 提交路径维护 → T10 control-receipt、Picker 成功/失败/取消及发送回归通过 → 后续对新增命令结果应保持 typed UI action，不复建“命令结果顺手清输入”的副作用。
3. `ChatTimeline.tsx: 相邻 Tool 活动组` → 实际调用者为 App 的 live 与 history Timeline 投影 → 分组可从既有 Timeline 顺序派生，不需第二份持久 group 状态；逐项工具耗时相加也不代表真实墙钟跨度 → 删除旧测试对单个 Tool 行/elapsed 的旧布局断言，保留 Timeline 条目并在渲染时派生相邻活动组、按最早起点至最终完成点计算跨度 → T08 七个跨 batch Tool、可见内容切组、墙钟跨度和时间缺失用例通过 → 旧记录没有时间戳时仍保持 unavailable，不补造时间。

### Checklist、验证与未验收

W03 Checklist 共 9 项，其中本轮仅将 T08 连续七个 Tool/切组（A11）和 T10 Coding 控件命令保留草稿、不发 Turn/真实提交清理（A20）标为完成；其余复合项有条件尚未逐项完成证据，继续未勾。全包此前 12/40 已勾；加本轮 2 项后当前为 14/40，剩余 26/40。此状态不代表 T12 完成。

以下命令在 `desktop/` 执行。最终受影响 Renderer 文件组合（在测试名与最后一个无行为影响的 offscreen payload 字段收敛之前执行）：

```powershell
npx tsx --test tests/renderer-session.test.tsx tests/renderer-state.test.ts tests/renderer-state-ui.test.tsx tests/renderer-runtime-lifecycle.test.tsx tests/renderer-chat.test.tsx tests/renderer-attachments.test.tsx tests/renderer.test.tsx tests/preload.test.ts
```

结果：248 passed、0 failed，退出码 0（21.85s）。随后 `npm run typecheck` 通过、退出码 0。最后将 lazy Turn 回归名改为准确反映“编辑后的文本和附件向量完整保留”，并移除 offscreen receipt 未消费的 `viewRevision` payload 字段；这两项不改变执行语义。之后按改动范围补跑：

```powershell
npx tsx --test --test-name-pattern="T10 control receipts|T10 a successful lazy Turn preserves|App parks a lazy turn accepted after navigation" tests/renderer-state.test.ts tests/renderer-attachments.test.tsx
npm run typecheck
```

结果：3 passed、0 failed，退出码 0；typecheck 通过、退出码 0。

文档及冻结范围检查：`check_utf8_docs.py` 检查本次修改的 Checklist/Feedback 共 2 个文件，均通过 UTF-8、乱码标记与 Markdown fence 检查；`git diff --check` 退出码 0（Git 对现有 LF→CRLF 转换给出提示）；冻结需求、Spec、Tasks、W03 Prompt 的 `git diff --exit-code` 退出码 0。Checklist diff 只有上述两处复选框由未完成改为完成；`rg -n preserveComposer desktop` 返回 0 条旧分支/参数。

没有真实 Provider 请求、packaged Desktop/T15、原生窗口/输入/缩放或用户视觉验收；总控准备可运行 Desktop 后应暂停交用户 UI 验收。W04 Settings 自动保存/归档管理未实施，T09 packaged 当前 Diff 对照和其他未满足的 A 条件保持 Checklist 未勾。不做 Git 写操作。

## Reviewer 返工 1

独立 Reviewer 首轮指出 5 项 P2 覆盖空白。此前的 248 项组合与 Reviewer 的 57 项通过只能证明各自已执行范围，不覆盖以下五条行为；本轮在既有 W03 职责内修复并补真实状态/UI 路径回归，没有改动后端协议或配置持久化，也未扩到 W04/W05。

- **General lazy Turn 偏好污染**：General lazy Session 被接受时仍更新当前 catalog，但不再写 Coding 的 `selectedSessionId` 偏好；只有 Coding lazy Session 写该偏好。回归 `General lazy Turns keep their accepted Session out of the Coding resume preference` 验证实际 App 接受路径只更新 General 当前 Session，不产生 `selectedSessionId=general-lazy-session` 写入。
- **前台接受回执清除已编辑草稿**：当前 owner 的 `turn_accepted` 现在同时匹配提交时捕获的 `draftRevision`、文本和有序 attachment-ref 向量。用户在提交后编辑再改回原文时，旧回执保留正文与完整附件向量；未编辑且版本匹配的成功回执仍清理提交草稿，lazy Session 迁移仍保留。回归 `T10 a current-owner accepted receipt cannot clear an edited-and-reverted draft version`。
- **失败工具未切组/不可见**：失败或取消 Tool 直接渲染在折叠组之外；前后正常活动仍各自依相邻规则折叠。真实 reducer 的 success → failed → success 回归 `T08 a failed live Tool breaks collapsed groups and leaves its command and safe output action visible` 检查失败行无 `details` 祖先，命令及安全输出操作直接可见；既有七个正常 Tool 跨 batch 单组覆盖仍通过。
- **异步归档/搜索恢复抢新导航**：归档/恢复操作捕获开始时的导航 owner；持久化成功后仍刷新真实 catalog，但异步 catalog 回包后的自动 resume/切换仅在原 owner 仍有效时执行。回归 `T07 App restores archived search results and preserves a newer owner during delayed archive catalog refresh` 及 `T07 restoring a search hit after async archive work does not navigate over a newer owner` 分别覆盖延迟归档目录响应和搜索恢复延迟响应，均保留用户后来选择的 Session/Project，不启动旧目标恢复。
- **General 暴露 Coding Runtime 面板**：General 模式不渲染 Runtime 面板、开关和 splitter，并以隐藏布局释放 docked Runtime 列；Coding 的已保存面板偏好及 docked/floating/hidden 行为不变。`T07 Runtime switch and three layout modes remain operational` 覆盖 General 不显示 Runtime 技术诊断、配置错误仍在会话中可见、真实文本草稿和活动 Turn cancel 控件仍存在，并覆盖 Coding 面板布局。

### 本轮验证

在 `desktop/`、`re-uthcode` Conda 环境执行：

```powershell
npx tsx --test tests/renderer-session.test.tsx tests/renderer-state.test.ts tests/renderer-state-ui.test.tsx tests/renderer-runtime-lifecycle.test.tsx tests/renderer-chat.test.tsx tests/renderer-attachments.test.tsx tests/renderer.test.tsx tests/preload.test.ts
```

结果：252 passed、0 failed、0 skipped，退出码 0（23.10s）。该组合覆盖上述新增回归及原 W03 受影响 Renderer 文件。

```powershell
npm run typecheck
```

结果：通过，退出码 0。返工后未重跑 package/native/真实 Provider；尚无 packaged Desktop、原生窗口/输入/缩放及用户视觉验收证据，这些仍按 Checklist 留待后续验收。Checklist 当前 W03 仍只勾已满足的 A11、A20；其余复合项未因本次返工改变勾选状态。
## Reviewer 返工 2

同一 Reviewer 复审确认返工 1 的 5 项 P2 全部关闭，并指出 T09 右栏与 Coding Runtime 交接仍有 1 项 P2。根因是 `runtimeVisible` 只反映 Coding 的保存偏好/窄屏规则，而 ReviewPanel 会占用同一右侧槽并卸载 RuntimePanel；Timeline 因而隐藏错误提示，Runtime Toggle 却仍报告 `Close`/`aria-expanded=true`。本轮只修正 Renderer 的实际可见归属与既有 Toggle 入口，没有新增面板状态或改变协议。

- `runtimeVisible` 现同时要求 ReviewPanel 不可见。ReviewPanel 占用右侧时，唯一 Runtime error alert 归 Timeline，避免 RuntimePanel 卸载后错误消失；同一布尔值驱动 Toggle 标签和 `aria-expanded`，与真实显示一致。
- 从 ReviewPanel 点击 Runtime Toggle 时，复用 `closeReviewPanel` 清除 owner-bound tabs 并取消当前 workspace diff。若保存偏好为 `hidden`，或窄屏下为不可见的 `docked`，则沿原打开语义切到 `floating`；其余可见布局保留原偏好。关闭 Review 后 RuntimePanel 按 Coding 原有布局恢复。General 仍隐藏 Runtime 控件，现有文件/图片 tab 及焦点逻辑未另行改造。
- 新增真实 App/JSDOM 回归 `T09 App reviews preserve Runtime error ownership and let its toggle restore the panel`：让启动 `runtime.initialize` 真实失败以形成错误；打开 current Diff 后断言 ReviewPanel 可见、RuntimePanel 卸载、错误仍作为唯一 Timeline alert 显示，Toggle 为 Open/false；点击 Toggle 断言既有 diff 被取消、Runtime 错误回到 RuntimePanel、偏好保留 docked、标签与展开状态匹配且焦点留在稳定 Toggle；再次打开 Review 并切回 Runtime 验证交接可逆。该回归在生产修复前失败于 Review 打开后无错误 owner，修复后通过。

### 本轮验证

返工 1 已记录的 8 文件 Renderer 完整组合为 **252 passed、0 failed**，且 typecheck 通过；该证据属于返工 1，本轮未因局部面板交接改动机械重跑。针对本轮，在 `desktop/`、`re-uthcode` Conda 环境执行：

```powershell
npx tsx --test --test-name-pattern='T09 App reviews|T09 chat image|preserves imported Markdown|Runtime error owns one accessible DOM entity|responsive Runtime error owner handoff|Runtime drawer restores focus|T07 Runtime switch and three layout modes' tests/renderer-attachments.test.tsx tests/renderer.test.tsx
```

结果：8 passed、0 failed、0 skipped，退出码 0（3.70s）；覆盖本轮新增真实 App 回归、原 T09 Diff/output 分页与 owner 隔离、文档/图片 Review tab、Runtime 错误唯一归属、响应式错误焦点交接、Runtime drawer 焦点及 Coding 三态布局。

```powershell
npm run typecheck
```

结果：通过，退出码 0。本轮没有重跑 packaged/native/真实 Provider 或用户视觉验收；这些仍未验收，Checklist 不新增勾选。没有 Git 写操作。

## 总控：独立复审闭环

2026-10-11，指定的同一 gpt-6.1-sol/medium Reviewer 最终 PASS。首轮5项P2经原 gpt-6-luna/max Worker 返工1修复；复审确认原5项关闭，并指出右栏占用后Runtime错误归属/切换失真1项P2，经原Worker返工2修复。最终独立App/JSDOM smoke确认打开Review后错误仍在Timeline显示、Runtime按钮标签与展开状态真实、点击可关闭Review并恢复Runtime，未见原5项回退。

Reviewer独立执行（均在desktop目录，既有re-uthcode环境）：

- 首轮：`npx tsx --test --test-name-pattern='T07|T08|T09|T10|App parks a lazy turn' tests/renderer-state.test.ts tests/renderer-attachments.test.tsx tests/renderer.test.tsx`：57 passed、0 failed；另以只读内存smoke复现5项覆盖空白。
- 返工1复审：`npx tsx --test --test-name-pattern='General lazy Turns|current-owner accepted|failed live Tool|delayed archive catalog|restoring a search hit|Runtime switch|seven adjacent|T09 App reviews|T10 control receipts|successful lazy Turn|App parks a lazy turn' tests/renderer-state.test.ts tests/renderer-attachments.test.tsx tests/renderer.test.tsx`：11 passed、0 failed；原5项独立smoke通过，右栏错误缺口仍复现。
- 最终复审：`npx tsx --test --test-name-pattern='T09|Runtime switch|runtime error|runtime failure|Runtime failure|focus.*Runtime|Runtime.*focus' tests/renderer-attachments.test.tsx tests/renderer.test.tsx`：12 passed、0 failed，退出码0。
- 每轮 `npm run typecheck` 与 `git diff --check` 均退出码0。

Worker返工1完整8文件252 passed与返工2局部8 passed按原记录复用；Reviewer未机械重复252项。Checklist仍14完成/26待验，未以审核通过替代真实Provider、packaged联合E2E、原生输入/缩放和用户视觉验收。W04/W05尚未实施；无能力欠账变更，不自行归档。


## 总控：可运行版本构建

最终独立复审PASS后，在没有其他源码写入者的T11工作树（base `51df763` + 本次审定W03改动）中，通过Conda hook激活既有re-uthcode环境，执行 `desktop/ npm run package`：退出码0。该标准脚本重新生成PyInstaller onedir、通过bundled Coding/General initialize/session/status/shutdown JSONL与独立Prompt Context smoke，再完成webpack、Electron Forge win32-x64打包。产物：`desktop/out/UthCode-win32-x64/UthCode.exe`；原始日志保存在本机临时目录 `uthcode-t12-w03-package.log`。

构建期间未改变生产源码；本轮不执行make安装包。构建和bundled smoke通过不等于packaged联合交互、真实Provider或原生视觉验收，相关Checklist仍未勾；交付Git后暂停请用户验收W03页面/交互，再执行W04。
