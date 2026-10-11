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


## 总控：W03 Git交付与用户验收暂停

2026-10-11，最终Reviewer PASS、package/bundled smoke通过后，显式暂存20个审定实现/测试/必要文档文件，9份冻结正文与Checklist单向勾选、staged scope/diffcheck通过；UTF-8 guard 4/4通过，无编码修复。提交 `fd7b5a69b9963904dc418b80ae45cf21db6c8df2` 已推送T11-Agent能力补齐，[PR129](https://github.com/undertaker33/Re-UthCode/pull/129) 的head/20文件范围核对一致，MERGEABLE/CLEAN后按exact head合并，merge为 `614570df27057ff5eba3fae07b8b14657b52ad3b`。仓库无PR status checks，依据本轮本地验证和指定独立复审交付。

本地T11、远端T11及main均验证为上述merge；合并后的工作区干净。构建输入范围与审定提交/merge之间无源码、测试或打包输入差异，运行版仍有效。已启动 `desktop/out/UthCode-win32-x64/UthCode.exe`，进程实际存活且窗口标题为UthCode；这只证明运行版已打开，不代替人工页面/交互验收。

按用户第5步，当前暂停等待W03页面/交互验收，不启动W04/W05，不声明整包完成或归档。此Git交付记录与索引状态更新进入下一Prompt的必要文档提交，不另拆单独文档提交；当前新增未提交内容仅这两份总控记录。

## 用户界面验收返工

2026-10-11，用户验收指出活动卡、模式切换和 Markdown 表格仍偏离提供的界面参考。本轮按最新明确反馈覆盖冻结 Prompt 中对旧活动摘要显示的约定；冻结需求、Spec、Tasks、Prompt 与 Checklist 正文均未修改。再次查看 `references/coding-reference.png`、`references/general-reference.png`、用户提供的三张截图以及 `UthCode-Desktop-V4.html` 中 activity/sidebar 对应样式，按参考实现而未另行改版。

- **活动与公开思考**：`ChatTimeline.tsx` 仅展示已有公开 reasoning，并以默认收起的 disclosure 包裹；没有增加或投影其他内部推理。活动组默认收起，摘要按参考显示计数、状态、观测耗时和自绘 caret；打开后显示紧凑工具行，输入、命令和输出操作在默认关闭的第二层详情中。隐藏原生 marker，去掉重复工具名与 `<task state update>` 伪命令；失败条目直接显示命令、状态及安全输出入口，正常相邻工具仍跨 batch 成组，最终回复、关键状态提示与审阅入口保留。
- **品牌模式菜单**：Coding/General 入口移至左上品牌按钮下拉，标明当前选项；移除独立模式按钮。复用 `FloatingMenu` 的键盘移动、Escape、外点关闭和焦点返回，仍调用原 owner 导航路径并保留模式草稿。锚点从品牌左缘下方开始，定向 JSDOM 回归用实际矩形 `(left=14, top=8, width=112, height=34)` 验证菜单 `left=14px, top=47px`，侧边项目菜单原定位不变。
- **Markdown 表格**：用户截图格式为标题后无空行紧接 pipe 表头和分隔行。原段落聚合没有将后续 table header 视为 block 边界，导致已有 table parser 永远未被触发；本轮使段落在 table 起始处结束，并将表格放在可横向滚动的容器中，沿用安全 inline renderer 与亮/暗主题变量。真实流式回归覆盖未完成分隔行、中文表头/正文、inline code、不安全链接和原始 HTML。

本轮触及的源码/测试为 `desktop/src/renderer/ChatTimeline.tsx`、`desktop/src/renderer/Sidebar.tsx`、`desktop/src/renderer/safe-markdown.tsx`、`desktop/src/renderer/app.css`、`desktop/tests/renderer-chat.test.tsx`、`desktop/tests/renderer.test.tsx`、`desktop/tests/renderer-attachments.test.tsx`。未更改协议、Backend/Main、W04 设置/归档或新增目录。

### 本轮验证

以下测试在 `desktop/`、既有 `re-uthcode` Conda 环境执行。活动、表格、菜单和 T09 交接定向组：

```powershell
npx tsx --test --test-name-pattern='safe Markdown parses streamed pipe tables|T07 App switches fixed General owner|T08 tool activity groups stay collapsed|T08 duplicate TodoWrite|T08 activity group uses|T08 seven adjacent Tools|T08 a failed live Tool|T09 App reviews preserve Runtime error|T09 App reviews the kickoff event' tests/renderer-chat.test.tsx tests/renderer.test.tsx tests/renderer-attachments.test.tsx
```

结果：9 passed、0 failed、0 skipped，退出码 0。此前已闭环的 owner 草稿、lazy Turn、失败 Tool、迟到归档/搜索恢复、Runtime 与 T09 面板交接回归组：

```powershell
npx tsx --test --test-name-pattern='General lazy Turns|current-owner accepted|failed live Tool|delayed archive catalog|restoring a search hit|Runtime switch|seven adjacent|T09 App reviews|T10 control receipts|successful lazy Turn|App parks a lazy turn' tests/renderer-state.test.ts tests/renderer-attachments.test.tsx tests/renderer.test.tsx
```

结果：12 passed、0 failed、0 skipped，退出码 0。最后 `npm run typecheck` 通过，退出码 0；ref 类型修正后补跑菜单/Markdown/活动及审阅子集为 7 passed、0 failed。以上为新增覆盖与本轮回归，不替代此前返工 1 的 252 项完整 Renderer 组合。

Checklist 保持全包 14/40 完成、26/40 待验（W03 仅已验证的 A11、A20 两项勾选），本轮不因 JSDOM/定向验证增加复合项勾选。当前修改后的实际运行版尚未重新构建；真实窗口截图/鼠标、键盘输入、缩放与用户视觉确认仍待总控准备运行版后验收。真实 Provider、packaged/native 联合验收仍未由本 Worker 验证。不做 Git 写操作。

### 最终复跑与文档检查

收窄品牌菜单锚点 ref 类型后，补跑最终受影响定向子集：

```powershell
npx tsx --test --test-name-pattern='T07 App switches fixed General owner|safe Markdown parses streamed pipe tables|T08 duplicate TodoWrite|T08 tool activity groups stay collapsed|T08 seven adjacent Tools|T08 a failed live Tool|T09 App reviews the kickoff event' tests/renderer-chat.test.tsx tests/renderer.test.tsx tests/renderer-attachments.test.tsx
```

结果：7 passed、0 failed、0 skipped，退出码 0。`npm run typecheck` 退出码 0。Conda Python 3.12.13 下运行 `python 'C:/Users/93445/.codex/skills/uth-utf8-guard/scripts/check_utf8_docs.py' 'docs/work/T12-Desktop功能补齐与工程收敛/W03-Renderer导航与审阅-feedback.md'`，1 个文件通过 UTF-8/乱码标记/fence 检查；`git diff --check` 退出码 0，仅报告现有 LF→CRLF 转换提示。对 T12 主需求、Spec、Tasks、Checklist 与 W01–W05 五份 Prompt 的 `git diff --exit-code -- <9 frozen paths>` 退出码 0。


## 总控：指定会话只读诊断

用户询问会话 `9362432214734ba7bf4904e4e5f4f68e` 是否存在提示词循环注入。独立 gpt-6-luna/max Worker 只读核查该会话本机 Transcript 与当前 Agent/Context 源码：13 条记录、3 个 Turn，唯一成功 TodoWrite 在第二个 Turn 留下 1 个 in_progress 项，同 Turn 终态为 runaway_detected；没有重复工具调用或同类消息内容指纹，未发现 stable system prompt 累计写入 History 的证据。

当前 DEFAULT 行为会因未完成 TaskState 阻断 final；相同任务状态第 3 次进入纠偏、第 5 次停止。动态反馈是一次性 Context 消息，Provider 尝试前消费；按该代码路径推导停止前最多 4 个重试请求携带反馈，不是会话日志直接记录的请求次数。新 Turn 显式重置 TaskState/Plan/RuntimeFeedback，未见跨 Turn 残留阻断。会话未保存实际 Provider 请求或运行快照，不能据此判断此刻仍运行或宣称全面排除 Provider 自身问题。诊断没有发 Provider 请求、重放或修改用户会话，也没有关闭 App；本轮不改变已冻结 Agent/Context 语义。


## 总控：用户界面返工独立复审

2026-10-11，同一 gpt-6.1-sol/medium Reviewer 独立复审 PASS，未发现本轮残留 finding；已实际查看两张参考图、三张用户截图及 V4 HTML，核对活动一级摘要和默认关闭二级详情、失败摘要、Logo 下拉及无空行表格根因修复。执行 `npx tsx --test --test-name-pattern='safe Markdown|T07 App switches fixed General owner|General lazy Turns|current-owner accepted|failed live Tool|delayed archive catalog|restoring a search hit|Runtime switch|T08|T09 App reviews|T10 control receipts|successful lazy Turn|App parks a lazy turn' tests/renderer-chat.test.tsx tests/renderer-state.test.ts tests/renderer-attachments.test.tsx tests/renderer.test.tsx`：29 passed、0 failed；`npm run typecheck` 和 `git diff --check` 均退出码 0。另以 `node --import tsx -e $reviewCode` 只读内存 smoke 确认公开 reasoning 默认折叠、展开后流式更新保留展开，progress/Plan/final 直显，menuitemradio 和 Tab/Shift-Tab 焦点、品牌 below-start 与原 context 定位均通过；此前六项缺陷关联回归无回退。

复审没有编辑、构建、Git 写入或操作用户 App。当前旧运行版仍占用标准打包输出，无法据持久会话文件确认是否有活动 Turn；总控已向用户确认窗口空闲/关闭后再替换运行版，防止中断执行。此时尚未重建或重验原生窗口，不把 CSS/JSDOM 审核当作用户视觉验收。W04/W05 尚未启动，Checklist 保持 14/26，包状态仍 not_implemented。


## 总控：用户界面返工 Git 交付与运行版等待

2026-10-11，原 Worker 和同一 Reviewer 复审 PASS 后，仅暂存 7 个 Renderer 实现/测试文件及 Context-Index、W03 Feedback 共 9 文件；9 份冻结文档与 Checklist 逐字未变，Feedback 从 HEAD 原内容开始的追加性校验通过；UTF-8 guard 2/2 与 staged diffcheck 均通过。提交 `734553c915397ef67b18d1938eb134dd4861a08f` 已推送 T11-Agent能力补齐，[PR130](https://github.com/undertaker33/Re-UthCode/pull/130) 的 head/9 文件范围与本地审定集一致，MERGEABLE/CLEAN 后按 exact head 合并，merge 为 `a284ca19cb280c819ca51ca7f66d8979c901ebca`。本地 T11、远端 T11、main 和 PR merge SHA 经 Git/GitHub API 核对一致，合并后的工作区干净；merge 未改变审定 Renderer、测试、Backend 或构建输入。

当前运行版仍是前次 PR129 的旧包，本轮没有重建，也未以它验证新 UI。旧 UthCode 窗口仍在使用标准打包输出，无法可靠判断其活动 Turn；总控已提出只针对旧窗口空闲/关闭的确认，等待回复后才能安全替换并打开新包。此等待只影响运行版重建与用户复验，代码审查及授权 Git 交付已完成。W04/W05 未启动，Checklist 仍 14/26，未宣称用户视觉通过或整包完成。这份交付记录与索引状态按既有约定进入下一次必要文档提交，不单拆文档提交。


## 总控：用户关闭旧窗口后的重建与复验交付

2026-10-11，用户回复“我已关闭旧窗口”，总控实测 UthCode 进程已全部退出。在 PR130 merge `a284ca19cb280c819ca51ca7f66d8979c901ebca`、无生产源码写入的工作树中，经 Conda hook 激活既有 re-uthcode（Python 3.12.13），执行 `desktop/ npm run package`：退出码 0。标准 PyInstaller onedir、bundled Coding/General initialize/session/status/shutdown JSONL 与独立 Prompt Context smoke、webpack/Electron Forge win32-x64 均通过。新 `desktop/out/UthCode-win32-x64/UthCode.exe` 时间为本机 2026-10-11 12:54:52，app.asar 为 12:54:50；构建日志位于本机临时目录 `uthcode-t12-w03-ui-package.log`。未执行 make 或安装器验收。

针对新包执行 `desktop/ node scripts/cdp-packaged-visual-acceptance.mjs --language zh --flow visual --exe out/UthCode-win32-x64/UthCode.exe --output dist/manual-acceptance --port 9346 --timeout-ms 60000`：退出码 0，driver/Electron 正常退出，报告 exit.status=passed、failure=null、consoleErrors=[]、rendererExceptions=[]、unexplained stderr=[]。本轮复用既有 dist/manual-acceptance 目录，其报告文件此前不存在；未新建工作包文件夹或覆盖旧验收报告。检查 zh-CN、暗/亮主题、1264×761 与 760×640 CSS 视口，以及 docked/floating/hidden 布局，生成 6 张新包窗口截图；总控实际打开查看暗色 docked 和亮色截图。报告：`desktop/dist/manual-acceptance/acceptance-report.json`；隔离 host/Electron/driver profile 均清理完成，无 Provider 服务/真实请求。

以上只证明新包真实 Renderer 的 shell/响应式布局及对应测试路径，不是此次思考/工具/Markdown 真实内容交互的人工验收，也不替代真实 Provider、原生输入/缩放或完整 T15 联合验证。思考和工具折叠、Logo 菜单与表格内容回归仍依据前述 Worker/Reviewer 定向证据，最终效果待用户确认。构建/视觉验证前后审定生产源码、测试及构建输入无差异；正式新包已打开，按用户第5步再次暂停 W03 页面/交互复验。W04/W05 尚未启动，Checklist 维持 14/26，不以 shell 报告追加复合项勾选。交付记录和索引随下一次必要文档提交，不单独拆文档提交。


## 用户验收返工（二）：当前工作区摘要与正文 Artifact 卡片

2026-10-11，按用户最新 UI 反馈在 Renderer 内完成三项修正；W03 Prompt、Spec、Tasks、Checklist 等冻结正文未改，本记录只追加到本 Feedback。按用户明确授权，旧“完成后等待 W03 UI 验收再继续”的暂停约定由总控按原授权顺序覆盖；本 Worker 不实施 W04/W05。

- **内容区对齐**：在 `.app-shell` 统一使用 820px 内容最大宽度和 24px 最小 gutter，时间线消息、一级活动卡、当前工作区摘要与 Composer 共用同一几何规则，随 Runtime docked/hidden/floating 和 Review 所在内容列变化。正文附件仍保持既有次序：用户消息附件在正文前，Assistant/工具附件在正文后；Artifact 卡片最后显示。本轮未运行可见窗口矩形/人工视觉验收。
- **当前工作区摘要**：只在当前可见 Coding owner 收到成功 `tool_finished` 的 `WriteFile`、`EditFile` 或 `ApplyPatch` 时触发，以 120ms 合并近邻写操作，再调用既有 `workspace.diff({project_key})`；响应必须是现有 `source=current_working_tree` Diff DTO。摘要使用与右栏审阅分离的局部查询上下文，但共享现有 RPC、owner 匹配、cancel 命令、DTO 校验和 operation 身份路由；kickoff 前事件分别有界缓存，kickoff 后仅消费匹配 operation_id。切换 mode/project/session/viewRevision 后丢弃摘要并取消已知 operation，迟到的 kickoff 回包取消其 operation；读取摘要不打开/夺取 Review 或 Runtime 面板。文件数按 status.entries 的 path 去重，行数只解析 staged 与 unstaged Git diff hunk 上下文；同文件 a/b 路径去重，避免重复统计，rename 用真实 original_path/当前路径匹配。二进制、untracked 和未知/截断行数显示为不可用或下界，摘要不会捏造完整精确统计，也不把当前 Diff 归属为历史 Turn。卡片先显示真实前两条路径，“再显示 N 个文件”展开剩余项；明确点击“查看变更”或文件行才调用现有 ReviewPanel 路径。
- **正文 Artifact 引用**：仅从安全 Markdown 真正解析出的 `artifact:` 链接 token 收集引用；inline code/code fence 等文字不生成卡片，完全相同的引用只生成一张卡。引用留在正文原位置作为链接，卡片通过原 `describeArtifact`、`openArtifact`、`FileCard` 预览/打开/授权等受控路径在消息末尾展示。点击/授权描述失败时显示通用本地 alert，不暴露异常路径或细节；普通路径文本仍不自动变成链接。

本轮实际执行（均在 `desktop/`，Conda `re-uthcode`，Python 3.12.13）：

```powershell
npx tsx --test --test-name-pattern='ChatTimeline keeps artifact references|ChatTimeline exposes controlled artifact-link failures|ChatTimeline summarizes only counted workspace diff hunks|T09 App auto-discovers current workspace changes' tests/renderer-chat.test.tsx tests/renderer-attachments.test.tsx
```

结果：4 passed、0 failed、退出码 0。初次运行暴露统计缺陷：`diff --git a/x b/x` 的两侧路径 alias 在同一路径下将 +/- 翻倍；现已在 Diff section 内按唯一路径去重，复跑上述回归转绿。新增 App 回归验证成功 writer→真实 DTO 摘要、kickoff 前事件、自动摘要不夺取右栏、显式查看打开原 ReviewPanel、跨 Session 迟到 kickoff 被取消且旧 owner 结果不显示。纯 Diff 投影回归验证 hunk 上下文中的 `+++` 内容、暂存与未暂存合并、空格中文路径、rename、untracked/binary 未知行数、截断下界、真实文件数去重及展开路径。Artifact 回归验证正文链接/底部去重卡、代码块伪引用忽略、现有受控预览/打开回调和通用可见失败。

```powershell
npx tsx --test tests/renderer-chat.test.tsx
```

结果：17 passed、0 failed、退出码 0；包含中文标题后无空行的流式 pipe table、安全链接与原始 HTML、Artifact、附件历史投影和 process 文本回归。

```powershell
npx tsx --test --test-name-pattern='T09 App|T08 .*tool activity|T07 App switches fixed General owner' tests/renderer-attachments.test.tsx tests/renderer.test.tsx
```

结果：10 passed、0 failed、退出码 0；包含本轮 T09 摘要/迟到 owner、现有 Review/Runtime 错误归属交接、General owner 菜单/搜索隔离与 T08 默认折叠工具组。

```powershell
npm run typecheck
```

结果：`tsc --noEmit` 退出码 0。本轮未执行 build/package、真实 Provider、原生可见窗口检查或人工视觉验收；这些仍未验证，Checklist 未新增勾选。本轮没有协议/Backend/Main 改动、能力欠账变更、W04/W05 实施或 Git 写操作。


## 用户验收返工（二）复审修复：Git 空格路径与共享边距

2026-10-11，同一 Reviewer 复审发现两项 P2，本 Worker 仅修复以下 Renderer 范围并增加必要回归；没有扩大到其他模块。

- **普通空格路径统计串线**：`diff --git a/src/file name.md b/src/file name.md` 的路径本身未被 Git 引号包裹，按空白读 token 会把 `src/file` 和 `name.md` 当成两条路径，导致同前缀文件串统计。本次对完整 header 搜索 ` b/` 边界，只接受唯一且完整的双路径候选；无法无歧义解析时不把截断 token 用于统计。回归同时覆盖同前缀 `src/file`（+1）和 `src/file name.md`（+2），并逐行断言计数互不串线；原有 quoted 中文空格与 rename 覆盖保留。
- **响应式 gutter 分离**：原 max-width 820px 只将 timeline 调到 16px，Composer 仍为 24px；max-width 680px 又分别写 timeline 10px、Composer 左右 8px。现改为在 app-shell 的断点分别更新共享 `--chat-content-gutter`（820px 下 16px、680px 下 10px），删除 timeline 与 Composer 各自的水平覆盖。宽屏 24px/820px 内容上限以及 Runtime/Review 网格行为不变。本次未运行原生窗口矩形或用户视觉验收。

在 `desktop/` 执行：

```powershell
npx tsx --test tests/renderer-chat.test.tsx
```

结果：17 passed、0 failed、0 skipped，退出码 0；其中 Diff 摘要回归确认普通空格的两条近似路径各自得到真实 +1 与 +2 行统计。

```powershell
npm run typecheck
```

结果：`tsc --noEmit` 退出码 0。本轮未执行 Git 命令、build/package 或用户 App 操作；未验证 packaged/native 矩形与视觉效果，交同一 Reviewer 复审。


## 总控：用户验收返工（二）独立复审闭环

2026-10-11，同一 gpt-6.1-sol/medium Reviewer 首轮发现两项 P2：未 quoted 的普通空格 Git 路径会串入同前缀文件计数；窄屏 media 仍单独覆盖 Timeline/Composer gutter。原 gpt-6-luna/max Worker 修复并追加返工记录，同一 Reviewer 复审 PASS，未发现残留 finding。独立内存 smoke 确认 src/file +1、src/file name.md +2 正确归属，rename old-only/new-only/original_path 匹配正确，歧义 header 保持不可用。CSS 源码几何核算确认 760px 两者均532px、600px均426px，宽屏 Runtime 三布局及 Review 同宽；这不是 native 矩形验收。

Reviewer 在 desktop/、既有 re-uthcode 环境执行 `npx tsx --test --test-name-pattern='artifact|safe Markdown|counted workspace|T09 App|General lazy Turns|current-owner accepted|failed live Tool|delayed archive catalog|restoring a search hit|Runtime switch|T08 .*activity|seven adjacent|T07 App switches fixed General owner|T10 control receipts|successful lazy Turn|App parks a lazy turn' tests/renderer-chat.test.tsx tests/renderer-state.test.ts tests/renderer-attachments.test.tsx tests/renderer.test.tsx`：28 passed、0 failed；`npm run typecheck`、`git diff --check` 和 `node --import tsx -e $reviewCode` 均退出码0。已实际查看最新三张截图，并对照既有参考图/HTML。最新摘要、Artifact、折叠/菜单/表格和此前六项缺陷关联回归通过。

本轮未构建打包、操作用户 App或验证真实窗口/native/真实Provider，旧包不用于证明最新修改。Checklist 未新增勾选；用户明确取消后续UI暂停，完成本轮授权Git交付后直接W04/W05，运行版重建和剩余真实联合验收由后续完成。未跟踪 test-file.md 为用户测试数据，保持原样且排除提交。
