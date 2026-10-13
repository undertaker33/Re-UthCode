# W05 工程收敛与联合验收反馈

## T13–T16 实施记录

- 日期：2026-10-11；按正式派发严格执行 T13 → T14 → T15 → T16。
- 分支：`T11-Agent能力补齐`；开始时 HEAD `46d3c0d4808aab63c98df0de257833bf20b3eb9f`，与远端 T11/main 一致。使用既有 `re-uthcode` Conda 环境，Python 3.12.13，解释器为 `C:\Users\93445\miniconda3\envs\re-uthcode\python.exe`。
- 开始时保留总控未提交的 `docs/Context-Index.md`、W04 Feedback 追加以及用户未跟踪的 `test-file.md`；后者不读取、不修改、不删除、不暂存。未执行 Git 写操作。
- 已完整读取冻结需求、Spec、Tasks、Checklist、W05 Prompt、W01–W04 Feedback、工作包规则、用户决策边界、文档路由及 W05 要求的当前事实文档。T12 能力欠账章节为“无”；读取欠账清单后未发现本包触发项。

## T13 全仓调用证据盘点

盘点从本段开始；删改前继续复核真实调用图、依赖、打包和受影响测试，并将每项实际清理的六段证据追加在本 Feedback。未完成证据核查前不标记 Checklist。

### T13 首轮收敛结果

盘点覆盖当前 `src/uthcode` 87 个 Python 文件、`tests` 78 个 Python 文件、`desktop/src` 29 个 TS/JS 文件及 `desktop/tests` 16 个 TS/JS 测试文件。按 import/use 搜索核对 pyproject 运行/开发依赖、Desktop 直接依赖、构建脚本、PyInstaller spec 与 Forge 配置；现有 PDF/DOCX/XLSX/PPTX、HTTP/search、PTY、Prompt 数据文件、PyInstaller native DLL/EXE 和 Forge 插件均有运行时、动态加载或打包消费者，保留。`ts-node` 是唯一未找到源码静态引用的直接开发依赖，但 TypeScript Forge 配置已由当前构建链加载，动态配置加载消费关系尚不足以证明可删，保留并待 package/make 复核。未按 LOC 拆分 bridge/App/state/Agent/Core，也未削弱安全、Headless、持久化、Permission、Process、Tool output 与历史读取路径。

实际清理逐项六段证据：

1. `desktop/src/renderer/FileCard.tsx` 的 `fileLanguage`、`attachmentAsset` → `ChatTimeline`、`Composer`、安全 Markdown 渲染继续使用 `FileCard`；`DocumentPreviewPanel` 继续使用 `FileCardAsset`，但全仓没有两个 helper 的调用 → 删除后 `rg -n 'FileCard|FileCardAsset|fileLanguage|attachmentAsset' desktop/src desktop/tests` 只命中实际组件/类型，无 helper 引用 → 仅删除两个无调用的导出 helper，不改附件处理路径 → `npx tsx --test tests/renderer-attachments.test.tsx tests/renderer-chat.test.tsx`：44 passed、0 failed；`npm run typecheck`：exit 0 → 外部仓库可能曾直接依赖未导出文档的 helper，但仓库内无调用，清理按项目不保留无调用兼容别名规则执行。
2. `src/uthcode/integrations/tools/git_tools.py` 的 `GitWorkspaceQueryTool` → 正式调用方、注册工厂和测试均使用 `GitWorkspaceTool` → `rg -n 'GitWorkspaceQueryTool' src tests desktop/src desktop/tests` 无命中；`GitWorkspaceTool` 命中实际实现、注册与 `tests/test_git_tools.py` 调用 → 删除旧别名和其 `__all__` 导出，保留真实 Tool 实现与注册 → `python -m pytest tests/test_git_tools.py tests/test_application_tools.py -q`：16 passed → 仓库外直接导入旧别名的调用方不在当前项目闭环内；源码/测试无兼容性要求或消费者。

此前候选 `saveSettings`、通用 Session/Tool alias、Git diff/Process/Result readers 和可能带动态使用的依赖均因当前调用证据而保留。上述盘点与两项收敛仍需并入 T15 全量验证；Checklist 暂不勾选。

### T14 主流程与 T15 验收修复进展

复核正式 Settings 入口后，`SettingsView` 仍由 `App` 的真实 `onSave={saveSettings}` 关联字段自动保存驱动；旧全局提交按钮、旧 rebootstrap alias、旧逐条工具渲染入口在当前源树均无可用调用，不再加兼容双轨。修正现有 packaged CDP driver 的真实产品 selector/生命周期断言：首条消息前不再把 lazy Session 当作已持久化；Tool 结果改查正式 `.timeline-activity-item`，并在产品实际 `<details>` 上展开/折叠外层活动组和内层工具明细。`node --check desktop/scripts/cdp-driver.mjs` 与 `git diff --check` 通过。完整产品流及打包验收待后续阶段完成，当前不可将其记作 packaged 通过。

### T15 追加记录：原生首轮与 packaged Lifecycle 定向诊断

- 总控在同一 isolated packaged 窗口完成原生首轮，证据为 [`root-native-first-pass.json`](../../../dist/ui-acceptance/w05-native-send-20261011-205913/root-native-first-pass.json) 和同目录六张 PNG。实际通过：Coding 新建 Session、英文无工具提示发送与 fixture 终态；Logo 菜单键盘切换 General；General 双栏且无 Coding Runtime/附件控件；Theme/语言即时自动保存并返回聊天保持；五个 Settings 分类与独立归档页；Tools 设置页滚动而侧栏稳定；原生窗口最大化还原；中英文草稿经 Focus Mode 往返保持。未验证仍包括边框拖动窄窗、OS DPI、图片缩放、工具折叠、Review 内容及真实 Provider。此原生证据不替代 packaged 搜索归档、Git Diff 或真实 API 验收。
- Packaged 驱动首次尝试命令（在 `desktop/`）：`node scripts/cdp-packaged-visual-acceptance.mjs --flow lifecycle --language en --timeout-ms 120000 --request-timeout-ms 5000`。报告 [`w05-lifecycle-en-1791724043266-1b8326c0/acceptance-report.json`](../../../dist/ui-acceptance/w05-lifecycle-en-1791724043266-1b8326c0/acceptance-report.json)：到达选中 draft Session 后因 runner 将空 Composer 必须具有 enabled Send 按钮作为 owner readiness；产品在空输入时正确禁用 Send，因此没有发起 fixture 请求。此为验收断言错误，不是产品缺陷。
- 修正后第二次相同命令到达真实 Coding 首条消息，报告 [`w05-lifecycle-en-1791724295939-009cd3e8/acceptance-report.json`](../../../dist/ui-acceptance/w05-lifecycle-en-1791724295939-009cd3e8/acceptance-report.json) 记录 fixture 请求 1 条、User prompt/fixture response 可见、Composer 清空、真实 `turn_completed` 事件与匹配 Session identity。随后 runner 仍超时，因为只接受 `session_state.status == idle`；Bridge 在真实终态将该字段投影为 `completed`（`bridge.py` `_consume_turn` 将 runtime status 设为 `completed`，并清除 handle）。已将脚本改为在 status 为 `idle` 或 `completed`、同一 Session、`active_turn == false`、Runtime `ready`、Cancel 控件消失时要求三个稳定公共 `status.get` 观察；这保留 lazy Session 首发行为且不使用固定等待代替终态。当前脚本已通过 `node --check` 和 `git diff --check`；修正后的完整 Lifecycle 尚待重跑，不能记作通过。

## 2026-10-12 收敛、全量验证与 packaged 联合结果

### T13 六段清理及实际缺陷修复

前文两项清理的六段证据完整：符号/路径、真实调用方、无调用证据、删改内容、回归命令结果及外部风险均已逐项记录；此外复查了 Python、Renderer、测试、依赖、构建脚本、PyInstaller spec 和 Forge 配置。仅删除已确认无调用的 `fileLanguage`、`attachmentAsset` 与 `GitWorkspaceQueryTool` alias；`ts-node`、各文件/Process/Git/History reader、桥接入口和安全/Headless/持久化路径因仍有真实消费者而保留。没有按 LOC 拆模块。

同一盘点中发现并修正的真实性能/正确性问题：

1. `src/uthcode/application/tools.py` 的 `_SENSITIVE_OPTION_VALUE` 曾在同一 option name 上叠加两个无界同类 `*`，100 KB 的普通 Tool 文本可导致严重回溯。保留 name 前缀及 `key`/`auth` 后缀覆盖；6144 个旧/新正则合成组合逐项相同（此为总控独立只读微测），100 KB micro-test 由 0.155486s 降至 0.016283s（仅正则微测）。正式 `ApplicationToolService` 相关 3 tests passed；全量 Python 也通过。未减少既有秘密匹配范围或输入长度。
2. Tool 正文投影曾会把 ToolResultRead/HistoryRead 的 JSON 文本按整段替换，导致公开 DTO 结构丢失；ReadFile 按行脱敏又可能破坏引用跨行的 quoted-secret 匹配。现在 `ToolResultRead` 只脱敏 JSON `content`，`HistoryRead` 只脱敏 JSON entries 的 `payload`，ReadFile 暂存并还原生成的编号前缀后继续整段脱敏。覆盖敏感 option、JSON 类型/非 payload 字段及跨行 quoted secret 的回归包含在全量 Python 结果中；不把 progress 写入 History，也不改 Core 边界。
3. `src/uthcode/interfaces/desktop/bridge.py` 冷恢复 Coding Session 时继续使用已登记项目快照，General 则取 `_general_runtime_workdir()`，不把上一个 Coding 项目的 `_workdir` 带入 General owner。归档若发现目标 Session 的 parked Application 正持有 writer，则通过该 owner 调用 `set_session_archived`；仍保留 active/unknown/busy 拒绝。桥接测试覆盖 General 当前 Application 归档 parked Coding 的不同用例；原完整 GUI Search→Open 同一 Session→Archive 用例另由下述 packaged Lifecycle 报告闭环，二者没有混为一例。
4. `desktop/src/desktop-preferences.ts` 以单 store 写队列避免观测到的多 key read-modify-write lost update；对于报告过的 Windows `rename` EPERM，只对同一原子替换做 25/50/100 ms 有界重试，其他错误原样抛出、失败临时文件仍清理。新增回归验证连续多 key 写入与临时 EPERM 后成功/重试耗尽的错误路径；没有增加仓库级锁或跨文件事务。
5. `desktop/src/renderer/FileCard.tsx` 清理的两个 unused helper 已由 Renderer 附件回归复测；另在现有 `ImagePreviewModal` 找到父层 stacking context 缺陷（见原生证据段），仅移除 `.document-preview-panel` 的 `z-index: 1`，保留定位、resize 手柄层级与主题继承。

### T14 正式 Application/RPC 链

正式入口继续使用已有 Application/RPC，不添加第二套 Session、Tool、History 或 Agent Loop。Coding 显式 `session.new` 首条消息前即返回已登记 Session；General `New chat` 可保持未持久化草稿，首次发送后才成为持久 Session。General 用自己的 owner、无 Coding 项目指令且工具列表为空。对旧 W05 runner 的修正只按真实产品 DTO/DOM 状态等待：General 等待 owner/current Runtime ready 后再输入，随后检查真实 `.composer-send`；General 不等待仅 Coding 可见的 Pause 按钮。脚本诊断原始失败报告均保留，未改生产 UI 来迎合错误 selector。

### T15 源码验证及当前打包版本

- 最终 Python 全量：1717 passed、4 skipped、164.29 秒、exit 0；架构边界 `tests/test_architecture_boundaries.py` 为 23 passed。当前保留的 pytest 摘要明确记录 3 个真实 Provider live gates 未执行；第四个 skip 是 Windows 环境不执行 POSIX PTY 合同（由对应 skip 条件识别）。这不代表 Linux/POSIX PTY 已验证；真实 General Provider 另有下方 packaged 实际请求证据。
- CSS finding 修复后的 Renderer 定向命令：`npx tsx --test --test-name-pattern='T09 chat image attachment opens|T09 App reviews preserve Runtime|T09 App reviews the kickoff event|App preserves imported Markdown preview text|full image preview sizing' tests/renderer-attachments.test.tsx tests/renderer-chat.test.tsx`，6 passed、exit 0。
- 修复后的 Desktop 全量：在 `desktop/` 执行 `npm test`，296 passed、0 failed、59.14 秒、exit 0；`npm run typecheck` exit 0。
- 修复后的构建按共享 `.runtime` 串行执行：`npm run package` exit 0，随后 `npm run make` exit 0，最终 Windows x64 Squirrel 产物在 `desktop/out/make/`。两次均构建当前 Conda Python 3.12.13 PyInstaller onedir runtime，并 smoke test Coding/General initialize、session、status、shutdown JSONL，检查两种 prompt context 分离。
- 当前原生复验 stage 指向新产物 `desktop/out/UthCode-win32-x64/UthCode.exe`，SHA-256 `65aa196dc044fd41cc2f52838021d5281cadbbf6d729426d6c458c5e9363fd0e`，244,440,576 bytes。stage receipt：[`native-stage.json`](../../../desktop/dist/ui-acceptance/w05-native-modal-recheck-20261012-101709/native-stage.json)。之前 5 条 packaged flow 使用当时的完整产品版本 `bffbe4cd780f89bb7286b2f0b4bd6599abc266d2d039604dce5e02a6e6dd4cf9`；之后唯一生产修改是 image modal stacking CSS，相关 flow 未受影响，但不得将旧 SHA 写成新产物 SHA。

### Packaged flow 结果与报告

下列报告的主状态为 passed；其 executable SHA 均为上一段列出的 `bffbe4...`。所有报告位于仓库独立 UI acceptance 目录，不覆盖旧 `desktop/dist/manual-acceptance` 报告或截图。

- Lifecycle：[`w05-lifecycle-en-1791767228602-aa1ed8cd/acceptance-report.json`](../../../desktop/dist/ui-acceptance/w05-lifecycle-en-1791767228602-aa1ed8cd/acceptance-report.json) 完成两 Coding 项目同名 Session 的首消息、搜索、打开同一公开 Session ID、归档、重启、搜索并恢复；General owner、标题/内容、pin 与用户活动顺序检查通过。请求数为 3，driver 和 Electron exit 0、无未解释 renderer/stderr。原始报告记 fixture cleanup exit code 1；请求数和主报告均 passed，故明确保留该子进程清理结果，不把所有子进程写成 exit 0。
- General 真实 Provider：[`w05-general-real-en-1791768499904-305ada5c/acceptance-report.json`](../../../desktop/dist/ui-acceptance/w05-general-real-en-1791768499904-305ada5c/acceptance-report.json) 使用复制到 runner-owned HOME 的可信配置，仅发 General 无工具请求；2 个 `assistant_message_delta`、`assistant_message_completed`、`turn_completed`、精确最终正文、同一 General owner、0 Tool event 均记录；用户配置 unchanged、isolated cleanup true，driver/Electron exit 0。密钥与正文不在本 Feedback 重述。
- General 取消与坏配置恢复：[`w05-general-cancel-en-1791767578965-436fddcc/acceptance-report.json`](../../../desktop/dist/ui-acceptance/w05-general-cancel-en-1791767578965-436fddcc/acceptance-report.json) 记录唯一请求真实进入 General 后取消并收口；[`w05-general-invalid-config-en-1791767654732-178f893a/acceptance-report.json`](../../../desktop/dist/ui-acceptance/w05-general-invalid-config-en-1791767654732-178f893a/acceptance-report.json) 记录隔离 malformed config 的限定错误引导及取消。早期门禁错误、fixture 未收到请求和错误配置 setup 尝试的失败报告仍保留，不以最终 pass 覆盖。
- 当前 Git Diff：[`w05-diff-en-1791768002702-e0f0e68f/acceptance-report.json`](../../../desktop/dist/ui-acceptance/w05-diff-en-1791768002702-e0f0e68f/acceptance-report.json) 记录受控 tracked 修改、新增、删除、rename 和真实 `??` 状态；untracked 文件没有伪造正文、红绿行或增删统计，driver/Electron exit 0。
- Tool/Settings/布局：[`w05-tool-en-1791768028324-d4af082d/acceptance-report.json`](../../../desktop/dist/ui-acceptance/w05-tool-en-1791768028324-d4af082d/acceptance-report.json) 实际展开/收起 outer activity 与 inner tool details，并覆盖 Settings 入口/自动保存、主题与 Runtime panel 布局。CDP viewport 有 1280/800/680/520 宽度、DPR 1/1.25/1.5 与 reduced-motion 观察；这是 CDP 合成输入/viewport 证据，不是原生 resize 或系统 DPI。

五个可追溯主流程报告中，旧的错误 readiness 断言和实际失败尝试仍保留在独立目录；没有把脚本初次失败改写成成功。右侧 Review 的 text、Markdown、日志 tab 切换/关闭和跨 owner 隔离尚未由完整 packaged 流逐项证明；上面的 Git Diff 与 Tool disclosure 不替代这项证据。

### 原生 ImagePreview finding 与当前暂停点

总控在前一 packaged stage 的真实 Native Review/FileCard 图片入口看到 `ImagePreviewModal` 遮罩被标题栏和 Composer 覆盖；截图 [`native-image-modal-overlap.png`](../../../desktop/dist/ui-acceptance/w05-native-artifact-en-20261012-093653/native-image-modal-overlap.png)。原因是 `.document-preview-panel { position: relative; z-index: 1 }` 创建父 stacking context，其 modal 子级 `z-index: 1400` 仍被限制在低层。最小修复已从 `desktop/src/renderer/app.css` 删除父 panel 的 z-index，保留 `position: relative` 和 resize 控件的局部 z-index，适用于 ReviewPanel 与聊天 FileCard 两个真实入口；不会提升 modal 数值来绕过父层，也不新增 overlay 系统。

修复前总控原生检查过真实 inline Markdown 链接与底部 FileCard，图片预览 `+` 从 100% 到 120%、`0` 恢复 100%，Escape 关闭并显示 Preview 按钮的可见焦点轮廓；当时同时确认遮挡问题，所以这些只作为 finding/按键行为证据，不是修复后通过。修复后 source targeted Renderer 6 passed、Desktop 296 passed、typecheck、package、make 均通过。新包 stage 已启动并可见，`native-stage.json` 记录自有 app PID 16604、fixture PID 13956、CDP 61603、fixture 9348 及隔离 profile。随后用户物理 Escape 明确停止 Computer Use；新的原生 modal 复验未发生，本 Worker 不再调用 Computer Use/CDP、不发送请求、不关闭或清理 stage。原生窄窗边框拖动先前没有改变窗口尺寸；OS DPI 也未测试。A23 因此保持未勾，不能声称当前修复已原生验证。

General Provider 旧 hard-link setup 的失败尝试保留为失败事实，不补写为成功；之后真实通过报告使用 `copyFile` 到新 runner-owned HOME。用户后来删除了旧临时链接，Root 只读确认该临时路径已不存在且原用户配置仍在；该 setup 没有完整 before/after hash 报告，不能声称 Worker 成功 unlink 或具有该次 hash 证据。

### R01–R21 / A01–A23 证据去向

R 的原编号和需求对应关系沿用冻结 Checklist 映射；下表显式列出每个验收项的主要 Feedback/报告位置。已验证证据不自动勾选尚含其他条件的复合 Checklist 行。

| 原验收 | 证据位置及状态 |
| --- | --- |
| A01 | W01 搜索/登记所有权测试，W03 导航记录；W05 Lifecycle report 搜索并打开同名 Coding Session 的 owner/id 检查。 |
| A02 | W01/W02 搜索拒绝、取消与脱敏边界；W05 仅补充 packaged 搜索路径，不替代既有 negative cases。 |
| A03 | W01/W02 归档 busy/幂等与 writer 回归；W05 bridge full-path archive 和 parked writer 归属修复。 |
| A04 | W01 持久化归档/恢复验证；W05 Lifecycle report 跨重启恢复同一 Session。 |
| A05 | W04 归档页/恢复/排序结果；W05 Lifecycle report 保留 pin 与用户活动排序观察。 |
| A06 | W05 packaged Lifecycle report：双 Coding 同名、General、search/open/archive/restart/restore。 |
| A07 | W02 General 创建/恢复、mode 隔离、fingerprint 结果；W05 Lifecycle 与 real-provider 报告记录 General owner。 |
| A08 | W05 General real-provider、cancel、invalid-config reports；Python live pytest gates仍 skipped，真实 API 来自独立 packaged flow。 |
| A09 | W02/W04 模式/owner/配置边界；W05 Lifecycle General owner 与 Settings 结果。 |
| A10 | W02 General empty-tool 架构与测试；W05 Lifecycle、General-real、General-cancel 报告均记录 0 工具。 |
| A11 | W03 过程分组/折叠结果；W05 Tool report 实际 outer activity 与 inner tool details 展开/折叠。 |
| A12 | W03 live/replay/paging 及计时结果；W05 未替代为新的 Runtime 状态权威。 |
| A13 | W02/W03 Tool result ref、跨 chunk 脱敏与 progress 边界；W05 Python 全量包含字段级 JSON 与跨行 ReadFile 回归。 |
| A14 | W02 Git boundary/history 摘要结果；W05 controlled Git Diff report 显示 status 与 staged/unstaged sections。 |
| A15 | W03 Review/FileCard Renderer 结果；W05 报告真实 inline artifact 与 modal overlap finding。完整 packaged Review tabs/日志/关闭/owner 仍待验。 |
| A16 | W05 Diff report 有真实路径与 modified/added/deleted/rename/status；跨 owner stale Review 和历史摘要时点的完整 packaged 复验仍待验。 |
| A17 | W04 Settings 字段自动写入、失败重试；W05 tool flow + Desktop full test/typecheck。 |
| A18 | W04 runtime snapshot/active boundary；W05 packaged Settings/Runtime panel CDP 观察，非原生 DPI。 |
| A19 | W04 Secret/config writer/security DTO；W05 real-provider report 记录只读配置副本、user config unchanged。 |
| A20 | W03 Composer picker/owner/草稿结果；W05 原生首轮的真实输入/Send 结果保留在 root-native evidence，不在本轮复验。 |
| A21 | 本 Feedback 的两项 T13 六段清理及本轮 T16 文档/留保记录；无价值 alias 搜索见 T13 段。 |
| A22 | 本轮 Python 1717/4、architecture 23、Desktop 296、typecheck、package/make 和 bundled Runtime smoke 结果。 |
| A23 | W05 native first-pass、modal finding/修复前按键证据、CDP matrix 与当前 stage receipt；新包原生 modal、窄窗边框和 OS DPI 未验，故复合项保持未勾。 |

R01–R21 到 A 的主映射仍以 Checklist 的冻结表为准：R01→A01；R02–R03→A02；R04→A03/A06；R05→A03；R06→A04–A05；R07→A04/A06；R08→A07；R09→A07–A09；R10→A09；R11→A08/A10；R12–R13→A11–A13；R14→A12–A13；R15–R16→A14–A16；R17→A17；R18→A18；R19→A19；R20→A20；R21→A21。Checklist 的 A22/A23 是最终工程/视觉复合验收，不改变需求的 R 映射。

### T16 文档、链接和停止边界

按 `docs/README.md` 维护映射同步了根 README、getting-started/configuration/commands、Tools、GUI/A01/A03/A04 当前事实、可替换交互层设计和 Context-Index；真实 Provider、图片 Review、General 零工具与自动保存描述均以当前源码和实际 flow 为准。`OutstandingDebtList.md` 保持不变；此包无能力欠账。T12 目录仍在原路径，未归档；未执行任何 Git 写操作。

此前本文件第一轮 Native artifact 链接写成 `../../../dist/...`，从当前 Feedback 所在目录会解析到仓库根的 `dist`，路径错误。以上本轮新增的 artifact 链接均以正确路径 `../../../desktop/dist/...` 指向 `desktop/dist`；原文旧链接不改写事实，只在此处标明并提供正确引用。

文档校验结果：UTH UTF-8 guard 对本轮 13 份 Markdown 检查通过；README、手册、Tools、当前事实、核心设计、Index 与 Checklist 共 12 份维护文档的文件目标链接检查通过；本轮 W05 Feedback 新增的 artifact 链接也逐一解析成功。全文件路径检查仍会指出本文件前段 3 个旧链接目标错误；遵循 Feedback append-only 边界保留原记录，以上更正链接可用，但不把这 3 个历史目的地声称为有效。

本次待总控重新接手的原生 stage 仍在运行：隔离 stage 根目录 `C:\Users\93445\AppData\Local\Temp\uthcode-w05-native-modal-00b1888f91a341b2bacfcb8fa1be1ae2`，Electron userData `...\electron-user-data`，受控项目 `...\projects\native-preview`，新 package SHA 与进程/端口见同目录 [`native-stage.json`](../../../desktop/dist/ui-acceptance/w05-native-modal-recheck-20261012-101709/native-stage.json)。这是 stage receipt，不是新包原生 PASS。

本轮完成纯文档后即停笔交 Root 独立 Reviewer。Root 要求的 Computer Use 因用户在 native 操作中按物理 Escape 停止，本轮不得继续原生/CUA/CDP、发送请求或关闭 stage。源码和文档未由独立 Reviewer 审核；当前 package/native 复验、Review text/Markdown/log 的完整右栏流、窄窗原生 resize 和 OS DPI 均不写成已通过；不标 `implemented_unarchived`，不提交/推送/合并/归档。

### Review tab 补充回归（追加记录）

在总控接管既有 Native stage 期间，我只修改了 `desktop/tests/renderer-attachments.test.tsx`，没有操作窗口或 CDP。既有 `T09 App reviews the kickoff event, bounded output pages, process log, and rejects stale owners` 增加了可见 Review tabs 的选择/关闭断言：切换当前 Diff 与单路径 Diff、切换 tool-output 与 process-log、关闭单个 Tab 后保留其余 Review 内容、关闭整栏后清空 Review tabs。该测试仍通过 fake public API harness 验证 RPC DTO 行为；它不是 packaged UI 的 text/Markdown/log Tab 通过证据，也不替代打包产品的 tab/owner 原生验收。

变更后执行 `npx tsx --test --test-name-pattern='T09 App reviews the kickoff event' tests/renderer-attachments.test.tsx`：1 passed、0 failed、exit 0；随后在 `desktop/` 执行 `npm test`：296 passed、0 failed、0 skipped、53.26 秒、exit 0；`npm run typecheck` exit 0。仅测试文件有此追加修改，production source、packaged binary 与 native stage 未变。Renderer App 回归对 tool output 的 64 KiB 单页上限、offset 续读和 process.read cursor 使用 fake API 返回值；stale owner 和迟到响应断言亦在同一测试中。正式 packaged Text/Markdown/Log Review tabs 的真实入口/关闭、跨 tab 和 owner 切换证据仍未有，不能由该测试推导通过；T15 的复合 Git Diff/owner 与原生 UI 条件仍按 Checklist 保持未勾。

## 2026-10-12 最终 Review/Diff 返工与当前验收闭环

本节为当前状态；前文 native 用户中断、Review 内容待验及 Checklist 未完成均是早先时间点的现场记录，不覆盖本节之后取得的证据。仅追加本节，不改写旧失败报告或旧 Feedback 内容。

### 最终 packaged Review 与 Diff

前一次 Review 报告 `w05-review-en-1791776499688-83625efa/acceptance-report.json` 保留失败事实：实际 Review image preview 已加载并关闭；测试随后在 Markdown artifact 被双击打开的等待点耗尽 180 秒。逐项日志表明耗时全落在文件卡点击后。受控 image attachment 加入消息后，较早的 `review.md` 卡片可在聊天滚动区视口外；旧 driver 只读取矩形并向不可见坐标发送双击。只改 `doubleClickReviewArtifact`：先将真实 FileCard 滚入视口，重新读取坐标，并以 `elementFromPoint` 确认点击命中卡片，再执行鼠标双击。没有延长 deadline、注入 DOM 卡片或更改产品行为。

`node --check desktop/scripts/cdp-driver.mjs` 通过；随后在 `desktop/` 运行以下当前 packaged 脚本：

```powershell
node scripts/cdp-packaged-visual-acceptance.mjs --exe out/UthCode-win32-x64/UthCode.exe --flow review --language en --port 9357 --timeout-ms 180000
node scripts/cdp-packaged-visual-acceptance.mjs --exe out/UthCode-win32-x64/UthCode.exe --flow diff --language en --port 9358 --timeout-ms 120000
```

两条命令分别 exit 0，报告为 [`Review acceptance-report.json`](../../../desktop/dist/ui-acceptance/w05-review-en-1791776902758-9b4593e2/acceptance-report.json) 与 [`Diff acceptance-report.json`](../../../desktop/dist/ui-acceptance/w05-diff-en-1791776919330-d823c580/acceptance-report.json)。两份均来自最终 exe SHA-256 `eb939da075ebf857b3924fbf20aa25320aec67714c91fdeca6eb152210c5f398`（244,440,576 bytes）。

- **Review**：受控 Coding Session 消息经真实 Composer image drop/import/send，Timeline 显示带 opaque ref 的 image FileCard；真实 Review 预览为已加载 `data:image/jpeg`，natural dimensions 非零，正式 image modal 成功打开并返回 Review。实际聊天工具执行 ReadFile 和 Bash 两次；每次请求提供 16 个工具定义，不代表执行 16 个工具。Review File Read 首/末页分别 65,536 / 114,025 字符并显示分页终止；Markdown rendered/source、Text 与 Process log（sequence 0、24）均从真实入口打开；多 tab 选择、单 tab 关闭、关 Review 后新建 Coding Session 均通过，owner 为新 Session 且没有旧 Review/image。fixture 请求 2/2；driver/Electron exit 0，console error、renderer exception、unexplained stderr 均为 0，四个 runner-owned cleanup 均为 true。原报告的 `fixture.exit.code=1` 保留，主报告 PASS 不表示 fixture 子进程为 0。
- **Diff**：受控 Git 项目真实呈现 tracked added/deleted/modified/rename 项及 `??` 路径；untracked 正文没有被加入 Diff，Staged / Unstaged 段分别为 29 / 9 行且时间戳可解析。保持 Diff 打开时通过真实 UI 创建新 Coding Session；最终公开 Runtime owner 与所选 Session ID 一致、Runtime ready、无旧 Diff。driver/Electron exit 0，console error、renderer exception、unexplained stderr 均为 0，隔离目录清理成功。

此前两个失败报告分别保留“fixture 模型未启用 image capability，因此 Composer 拒绝提交”和“正式 attachment preview 规范化为 JPEG，而脚本错误要求 PNG data URL”；它们发生在最终通过前，未改产品迎合错误断言。第三个保留的失败是上述视口点击等待。最终报告覆盖同一正式 image attachment / Review 路径，未用 fixture DOM 状态代替产品。

### 原生证据与最终包版本边界

总控独立操作真实 packaged 窗口并记录 [`root-native-modal-pass.json`](../../../desktop/dist/ui-acceptance/w05-native-modal-recheck-20261012-101709/root-native-modal-pass.json)：SHA-256 `65aa196dc044fd41cc2f52838021d5281cadbbf6d729426d6c458c5e9363fd0e` 的包中，真实 Review image modal 完整覆盖标题栏与 Composer；`=` 从 100% 到 120%，`0` 回 100%，Tab 在 Close/Reset 中可见焦点移动，Escape 关闭并使 Preview 图片按钮出现可见焦点轮廓，关闭真实文件预览 tab 后 Runtime 恢复。native stage 同时实测聊天文字发送、正文文件超链接/底部 Referenced files 卡与真实 FileCard 双击。早一轮 Settings/General 真实操作见 [`root-native-first-pass.json`](../../../desktop/dist/ui-acceptance/w05-native-send-20261011-205913/root-native-first-pass.json)。

最终 packaged SHA `eb939…` 与 native SHA `65aa…` 不是同一字节产物：后者包含已修复的 modal stacking CSS，前者随后只增加了 App terminal idle 后按当前 Session 刷新 durable History 的 App/state 行为；CSS、FileCard 与 modal 没有再改变。最终 `eb939…` Review 报告又直接验证其 image MIME/尺寸/modal 开关。CDP 窄宽 viewport 证据独立记录；native border drag/system size 尝试未改变观察到的 1266×793 尺寸，不能称 native 窄窗通过。OS DPI/IME 未测；冻结 A23 没有要求系统 DPI/IME，也不把它们登记为欠账。

### 全量验证与 R01–R21 / A01–A23 最终证据索引

最终生产源码验证与构建证据沿用上述当前源轮次，不因本次脚本-only 点击修复重复执行：既有 `re-uthcode` Conda 的命令 `conda run --no-capture-output -n re-uthcode python -m pytest -q --tb=short -rs` 为 1717 passed、4 skipped、164.29s、exit 0；4 个 skip 原因按 `-rs` 保留，其中 3 个是 live-provider gates，另一个是 Windows 不执行 POSIX PTY 合同，均未计为通过。`python -m pytest tests/test_architecture_boundaries.py -q` 为 23 passed。`desktop/` 中 `npm test` 最终为 297 passed、0 failed、0 skipped、exit 0，`npm run typecheck` exit 0；先后串行 `npm run package`、`npm run make` 均 exit 0。两步从当前 Python 3.12.13 Conda 源构建打包 Runtime 并通过 Coding/General bundled initialize/session/status/shutdown smoke；Squirrel 产物在 `desktop/out/make/`。以上证据作用于最终产品源码；本节新 driver scroll/hit-test 变更仅用 node syntax check 与最终 packaged flows 定向验证。

| 验收 | 最终证据位置 | 对应 R |
| --- | --- | --- |
| A01 | W01 搜索定向 45 passed；W02 Bridge 已登记 owner/未知 owner 负例；W05 Lifecycle 同名 Session 搜索/打开同一公开 ID。 | R01 |
| A02 | W01/W02 搜索范围、归档命中、局部不可用、取消、秘密/私有字段过滤与 Main/Bridge owner 拒绝测试。 | R02–R03 |
| A03 | W01/W02 归档幂等、busy/writer 冲突和目标归属 Bridge 测试；W05 完整 Coding Search/Open/Archive 生命周期。 | R04–R05 |
| A04 | W01 关闭 store 后恢复、metadata 兼容/失败回归；W05 Lifecycle 重启恢复同一 Session。 | R06–R07 |
| A05 | W04 归档筛选、恢复、Recent/置顶排序；W05 Lifecycle 核对 archived、pin 与用户活动顺序。 | R06 |
| A06 | W05 packaged Lifecycle：两个 Coding 项目同名 Session、General、Search→Open→Archive→Restart→Search→Restore，owner/标题/内容保持。 | R04、R07、R09 |
| A07 | W02 General create/resume、mode owner 与配置指纹回归；W05 Lifecycle 实际 General owner。 | R08–R09 |
| A08 | W05 General real-provider/cancel/invalid-config 通过报告，含 streamed delta/final、General 无 Tool；pytest live gates skip 不冒充真 API。 | R11 |
| A09 | W03/W04 Renderer owner、草稿、mode/Settings 保持及活动门禁回归；W05 Lifecycle 与原生 Coding/General 操作。 | R09–R10 |
| A10 | W02 General empty-tools 架构/请求测试；W05 real-provider、cancel、Lifecycle 请求实测 0 Tool。 | R11 |
| A11 | W03 真 reducer 七 Tool/切组/失败可见回归；W05 tool flow 与最终 Review outer/inner disclosure 实际开合。 | R12–R13 |
| A12 | W02/W03 live/replay/paging、cancel、owner 与时间语义测试；Python 1717 和 Desktop 297 最终回归。 | R12–R14 |
| A13 | W02/W03 结果 ref/限量/脱敏/跨 chunk/progress 不入 History 回归；W05 全 Python 回归及 Review 首/末页 65,536/114,025。 | R13–R14 |
| A14 | W02 可信 workspace diff/history 摘要边界测试；W05 当前 Diff 的真实 tracked 状态与 staged/unstaged 输出报告。 | R15–R16 |
| A15 | W02 artifact 单文件授权、Session/ref owner 和缺失/拒绝负例；W03 安全 Markdown/FileCard 局部错误回归；最终 packaged Review 实际 Text/Markdown/image/log/FileCard 与有界 ReadFile。 | R15–R16 |
| A16 | 最终当前 SHA packaged Diff report 的路径/status/时点及 owner Session 切换无旧 Diff；最终 Review report 切 Session 无旧 Review。 | R15–R16 |
| A17 | W04 字段自动保存/重读/失败重试测试与 packaged Tool/Settings flow。 | R17 |
| A18 | W04 安全边界 drain/后台 owner 与配置应用回归；packaged Settings 分类/Theme/语言及 W05 panel layouts。 | R18 |
| A19 | W04 Secret/config writer DTO 测试；General real-provider 使用复制到 owned HOME 的用户配置副本并确认原配置 unchanged。 | R19 |
| A20 | W03 Composer picker/命令失败/取消及草稿 revision owner 测试；原生 first pass 实际 Composer 输入/Send。 | R20 |
| A21 | 本 Feedback T13 两项删除的调用者/冗余/删改/回归/风险六段记录；Python、Renderer、测试、依赖、打包调用盘点。 | R21 |
| A22 | 最终 Python/架构/Desktop/typecheck/package/make/bundled smoke 精确结果与本节报告。 | R01–R21 工程收尾 |
| A23 | 三参考视图/V4 复核见 W03 最终 Reviewer 记录；原生首轮 Settings/导航与本次 modal/image/zoom/focus JSON+PNG；CDP narrow viewport 与当前 packaged Review/Diff 截图。native 与 CDP 分开，OS DPI 非原验收要求。 | R01–R21 视觉验收 |

R01–R21 的映射仍按冻结 Checklist：R01→A01；R02–R03→A02；R04→A03/A06；R05→A03；R06→A04–A05；R07→A04/A06；R08→A07；R09→A07–A09；R10→A09；R11→A08/A10；R12–R13→A11–A13；R14→A12–A13；R15–R16→A14–A16；R17→A17；R18→A18；R19→A19；R20→A20；R21→A21。每条 Checklist 复合条件现在有对应 W01–W05 自动化、真实 packaged/native 或构建证据；40 项均已满足，Checklist 为 40 checked / 0 unchecked。A22/A23 的最终工程/视觉证据在上表及对应报告中。

### T16 文档链接与最终停止边界

此前将 `../../../dist/...` 写入了 3 个较早 Feedback artifact 链接；从 Feedback 所在目录它们错误指向仓库根 `dist`。旧行按 append-only 保留；正确目标分别为 `../../../desktop/dist/ui-acceptance/w05-native-send-20261011-205913/root-native-first-pass.json`、`../../../desktop/dist/ui-acceptance/w05-lifecycle-en-1791724043266-1b8326c0/acceptance-report.json`、`../../../desktop/dist/ui-acceptance/w05-lifecycle-en-1791724295939-009cd3e8/acceptance-report.json`。本节所有新 artifact link 均解析至 `desktop/dist`。链接检查保留这三条历史坏链接为已知旧记录，不将其描述为目标存在；修订后的引用可解析。

最终 Checklist 40/40，`OutstandingDebtList.md` 不变（W05 能力欠账无）；T12 保留在 `docs/work/`，状态可更新为 `implemented_unarchived`，不归档。W05 Feedback 和包级文档与当前源码及上述最终报告一致。已交付源集合等待 Root 指定的独立 Reviewer；此 Worker 不做 Git commit/push/merge、窗口操作或新测试/构建。

### 独立 Reviewer 返工：ReadFile 多行秘密与文档更正（2026-10-12）

独立 Reviewer 复现 P1：给 `ApplicationToolService` 配置 `SecretValue("synthetic-alpha` 后接换行与 `synthetic-beta")`，将 `ReadFile` 正文物化为 `1\tsynthetic-alpha`、`2\tsynthetic-beta` 两行时，旧的逐行编号保护符隔开了连续秘密，两个片段原样泄漏。现在 [`tools.py`](../../../src/uthcode/application/tools.py) 的 ReadFile 专用投影先移除正式生成的行号前缀，在连续正文上做既有完整脱敏，再恢复原编号；脱敏替换保留匹配范围内的换行，因此跨行 SecretValue、配置 env literal 和跨行 quoted-secret 继续匹配，行号和 JSON/结果元数据形状保留。新增 literal 与环境变量两种多行回归，同时断言编号、全文无秘密片段、details 与结果 metadata。没有改其他 Tool 的文本/JSON 投影路径。

实际定向验证：

- `conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_application_tools.py -k 'read_file_redaction or multiline_configured' --tb=short`：3 passed、7 deselected，0.77s，exit 0。
- `conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_application_tools.py --tb=short`：10 passed，0.56s，exit 0。

Reviewer 的 P2 文档更正同步到 [`GUI-Context.md`](../../../docs/context/GUI/GUI-Context.md)、[`getting-started.md`](../../../docs/user-manual/getting-started.md)、[`State-Context.md`](../../../docs/context/A03-State/State-Context.md) 与 [`Orchestration-Context.md`](../../../docs/context/A04-Orchestration/Orchestration-Context.md)：Settings 不再声称 active Turn 时禁止保存，改为说明运行中的 Turn 使用已捕获配置、新设置在安全边界应用；补充 Coding/General 搜索范围、归档 Session 的搜索/打开/恢复、Review tabs 与活动组/单条 Tool 折叠等用户操作和对应状态机制。GUI 原先“native modal 尚未复验”也已由 SHA `65aa…` 的实际 native pass 与 SHA `eb939…` 的最终 packaged Review 事实更正，窄窗 CDP 与 native 证据仍分开。

同时更正本文前段一项历史记载：曾写 `desktop-preferences.ts` 回归覆盖临时 Windows `rename` EPERM 成功与重试耗尽；经 Reviewer 对照实际测试，当前回归只证明多 key 写入和 invalid-key 写入失败后的队列恢复，没有直接模拟 EPERM/rename 的成功或耗尽分支，也没有独立运行证据可证明该分支通过。旧句按 Feedback append-only 保留，本段明确撤销其“EPERM 测试已通过”的表述；EPERM 分支无直接回归证据。

当前仅完成上述定向 Python 测试与文档同步，尚未重跑完整 Python、重新 package/make 或执行更新后 packaged ReadFile Review；这些验证等待 Reviewer 复审通过后再按要求执行。既有 UI/CSS、Desktop 与 native 证据保持其原 SHA 与原报告范围，不由本次 Python/Markdown 修改推导为新包验证。
### Reviewer PASS 后最终受影响验证（2026-10-12）

同一独立 Reviewer 已复审并关闭 P1 与 P2。Reviewer 定向命令 `conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_application_tools.py tests/test_tool_result_persistence.py tests/test_builtin_file_tools.py tests/test_builtin_search_tools.py --tb=short` 为 76 passed、2.27s、exit 0，覆盖裸 literal/env 多行秘密、quoted/短秘密、行号、metadata 与 144000 字符普通 ReadFile。其后 Worker 最终完整 Python 命令 `conda run --no-capture-output -n re-uthcode python -m pytest -q --tb=short -rs` 为 1719 passed、4 skipped、198.62s、exit 0。4 个 skip 为 3 个 live-provider gate（各要求 `UTHCODE_RUN_LIVE=1`）和 Windows 上不运行的 native POSIX PTY contract；另有 2 条 `PytestUnraisableExceptionWarning`，均来自 `tests/test_builtin_process_tool.py::test_bash_cancellation_terminates_descendant_after_shell_exit`：Windows Proactor pipe 析构报告 `ValueError: I/O operation on closed pipe`，另一次 subprocess transport 析构报告 `RuntimeError: Event loop is closed`。本次如实记录 2 warnings，不记作零 warning 或测试失败。

随后在 `desktop/` 按顺序执行 `npm run package`、`npm run make`，两条均 exit 0；两次都以 `re-uthcode` Conda 的 Python 3.12.13 / PyInstaller 6.22.2 重建 bundled Runtime，并通过 Coding 与 General initialize/session/status/shutdown JSONL smoke，确认两种 prompt context 分离。Desktop Renderer/Application 源未在本次 Python 脱敏修复中变化；此前 `npm test` 297 passed 与 `npm run typecheck` 通过仍适用于该未变源码，不重复执行。

当前产物 `desktop/out/UthCode-win32-x64/UthCode.exe` 的正式 packaged Review 命令为 `node scripts/cdp-packaged-visual-acceptance.mjs --exe out/UthCode-win32-x64/UthCode.exe --flow review --language en --port 9359 --timeout-ms 180000`，exit 0。报告 [`acceptance-report.json`](../../../desktop/dist/ui-acceptance/w05-review-en-1791781914071-05a3e368/acceptance-report.json) 来自这次重新 package/make 后的 Runtime。ReadFile 外置结果首/末页为 65,536/114,025 字符且分页结束正确；真实 review flow 也通过 Markdown、Text、Process log、多 tab、image attachment 正式预览及 owner 切换无旧 Review。两次 Provider fixture 请求各声明 16 个工具定义；实际执行 ReadFile 与 Bash 两个 ToolCall。fixture 子进程原始 exit code 1 保留，主报告状态 passed，driver/Electron exit 0，console/renderer/unexplained stderr 为空，4 个 runner-owned cleanup 均 true。报告的 `packagedExe.sha256` 为 `eb939da075ebf857b3924fbf20aa25320aec67714c91fdeca6eb152210c5f398`、244,440,576 bytes；该字段是 Electron launcher 文件哈希，和先前构建相同，不单独用作区分全部 package contents 的身份证明。旧 Lifecycle、General、Diff、Tool 与原生 modal evidence 的范围不因 Python 修复扩大；Renderer/CSS 未变，原生 modal SHA `65aa…` 仍是该 UI/CSS 行为证据，不冒称本轮新做 native 操作。

当前 Checklist 40/40 和 `implemented_unarchived` 状态未变；T12 保留未归档。真实 POSIX PTY 与系统 DPI 未在此 Windows 运行验证，OS DPI 不是冻结验收条件。EPERM/rename 分支没有直接回归证据，按上一节更正。本段之后停止 Worker 写入、测试、构建和窗口操作，交 Root 做最终只读核对与交付。
补充来源勘误：Reviewer 的 76 passed 来自上述 pytest 命令；144000 字符普通 ReadFile 检查来自独立 stdin 微测，不属于该 pytest 命令覆盖。该更正只澄清证据来源，不改变已有代码、Checklist 或构建结果。

## 用户追加的 Desktop UI 调整（2026-10-12）

按追加授权更新 Settings、Review Diff 与关闭操作：去掉 Settings 的 idle 成功常驻提示和重复产品眉题；保留保存中/失败/pending 与重试；Settings 使用本地化名称/说明索引搜索并定位分类或 Model 图片能力字段，不搜索配置值；Archive 项目下拉按精确 project key 区分同名项目并包含 General；搜索启用和 supports_images 使用可键盘操作的紧凑开关；CustomSelect portal 随当前 theme scope 继承 light/dark/system；Diff 在当前工作区标题和查看时间旁提供范围下拉，使用原始 Git staged/unstaged unified patch 显示 hunk 上下文、行号、红绿变化及三种 scope；无 patch 时只显示一次空状态，untracked 仅显示原状态/路径；关闭动作统一使用带可访问名称与焦点样式的 SVG close，普通正文和控件字重轻微加强。

同步 [`GUI-Context.md`](../../../docs/context/GUI/GUI-Context.md) 与 [`getting-started.md`](../../../docs/user-manual/getting-started.md)，补充当前 Settings 搜索、状态、主题/开关、Archive project filter 和 Review Diff scope 的用户行为/维护映射。冻结 T12 需求/Checklist 未改；原 40/40 仅表示原工作包条件，本次追加 UI 条件不计入该数。源码相关覆盖新增于 `desktop/tests/renderer-settings.test.tsx` 与 `desktop/tests/renderer-attachments.test.tsx`。

定向结果：在 desktop/ 执行 node_modules/.bin/tsx --test tests/renderer-settings.test.tsx tests/renderer-attachments.test.tsx 为 41 passed、0 failed、3.85s、exit 0；node_modules/.bin/tsx --test --test-name-pattern='T06 CustomSelect flips by available geometry|main workspace visual contract|W04 settings application events refresh only valid counters and reject an old API generation' tests/renderer.test.tsx 为 3 passed、0 failed、1.13s、exit 0；npm run typecheck（tsc --noEmit）exit 0。五处旧断言分别更新为：归档列表同名项目按 project key 区分；Settings search 导航断言对应目标字段容器；supports_images 搜索直接打开 Model 编辑器；close SVG 按 .ui-icon--close 选择；portal 主题 wrapper 随 theme scope。新增的 Diff header/time 与空 patch 单次提示断言包含在 41 项结果中。未将初次组合运行失败说成通过，也未把此次结果冒充完整 npm test。完整 Desktop npm test、package/make、更新后的 packaged/native 视觉验收待同 Reviewer 复审后按串行顺序执行；当前新源尚无本轮 package/native 证据。

### Reviewer P2 修正：Settings 搜索逐字段定位（2026-10-12）

原 Reviewer 指出 Settings 搜索仅覆盖 Provider 分类词和一个 Model 图片能力入口：Base URL 命中后只聚焦 Provider 分类中的首个控件，Model context window、max output、reasoning 等可编辑字段没有独立命中。本次在现有搜索目录中按当前有效 Provider/Model 生成逐字段目标，使用本地化字段名称和已有提示文案匹配；结果只显示字段名称及 Protocol N / Model N 序号，不搜索或显示配置值、模型值、Provider ID 或密钥。选择 Provider 字段会打开 Provider 编辑器并聚焦对应输入/CustomSelect；选择 Model 字段会打开该 Model 编辑器并聚焦 Remote ID、Display name、Context window、Max output、Reasoning、图片支持或默认模型控件。API Key 搜索聚焦仍为 password 且值为空的编辑控件，不触发凭据读取。配置值本身（128000、4096、remote-model、gateway.example）均没有搜索命中。

新增逐字段路由回归覆盖 Provider 名称、协议、Base URL、API Key，以及 Model Remote ID、Display name、Context window、Max output、Reasoning、图片支持和默认模型；逐项断言实际 modal 类型和 document.activeElement 控件，并检查已保存密钥保持未显示。desktop/ 中命令 .\node_modules\.bin\tsx --test tests/renderer-settings.test.tsx 为 13 passed、0 failed、1.74s、exit 0；npm run typecheck（tsc --noEmit）exit 0。此次只修改 SettingsView 搜索目录/路由、SettingsEditorModal 初始焦点和 Settings 测试；无 Python、CSS、CDP driver、构建或窗口操作。此为独立 Reviewer P2 的定向修复，等待同 Reviewer 复审；既有 41 项 Settings/附件及 3 项 renderer focused 结果适用于此前 UI 版本，不替代本次 13 项 Settings 回归。

## 用户追加 Desktop UI 最终 packaged 验收（2026-10-12）

本节更新上一节的“等待最终 UI 验收”状态；历史失败和早期版本报告保留原样，最终结果只取本节所列当前包报告。W05 本轮 Settings 和 Diff 最终报告来自同一 Electron launcher SHA-256 `660d73026f2bea44e3563cf4a47e69c4e8f3930ec15790aaebea8d5969c69a06`；该值只标识 launcher 文件，不作为整个安装包内容的身份凭据。

在 `desktop/` 执行最终 `npm test`：304 passed、0 failed、0 skipped、0 cancelled，72,254.2042 ms，exit 0；日志为 [`ui-refinement-final-npm-test.log`](../../../desktop/dist/ui-acceptance/ui-refinement-final-npm-test.log)，本机完整路径 `D:/project/Re-UthCode/desktop/dist/ui-acceptance/ui-refinement-final-npm-test.log`。`npm run typecheck`（`tsc --noEmit`）exit 0，适用于当前 TypeScript 产品改动；其后仅有 CDP 脚本的截图等待修正。按顺序执行 `npm run package` 与 `npm run make` 均 exit 0，日志分别为 [`ui-refinement-final-package.log`](../../../desktop/dist/ui-acceptance/ui-refinement-final-package.log) 与 [`ui-refinement-final-make.log`](../../../desktop/dist/ui-acceptance/ui-refinement-final-make.log)；两步均通过 Coding/General bundled JSONL initialize/session/status/shutdown smoke。Make 生成 `desktop/out/make/squirrel.windows/x64/UthCode Setup.exe`，204,823,552 bytes，时间为 2026-10-12 16:59:32；本轮没有执行 Installer 安装测试。

最终 Settings 流报告 [`acceptance-report.json`](../../../desktop/dist/ui-acceptance/w05-settings-ui-en-1791795631783-0e897214/acceptance-report.json) 为 passed，driver/Electron 均 exit 0，共 9 张 PNG。它核对浅色菜单实际背景为 `rgb(255, 255, 255)`、深色为 `rgb(36, 36, 39)`，CDP emulated `prefers-color-scheme` 下的 System/light 与 Light、System/dark 与 Dark 各自一致；这不是 Windows 原生主题或 DPI 验收。5 个本地化字段搜索均聚焦实际编辑字段，API Key 保持空白 password 控件；键盘开关保存成功且不显示常驻成功条；General 与两个同名 Coding 项目按 owner 精确筛选，720px viewport 截图通过。截图前 modal/backdrop 动画已结束、计算 opacity 为 1；switch checked 为 true，轨道背景 `rgb(86, 95, 215)`、旋钮 transform 为 16px 终态矩阵。终态图见 [`settings-search-model-field.png`](../../../desktop/dist/ui-acceptance/w05-settings-ui-en-1791795631783-0e897214/settings-search-model-field.png)、[`settings-light-modal-menu.png`](../../../desktop/dist/ui-acceptance/w05-settings-ui-en-1791795631783-0e897214/settings-light-modal-menu.png) 与 [`settings-light-tools-switch.png`](../../../desktop/dist/ui-acceptance/w05-settings-ui-en-1791795631783-0e897214/settings-light-tools-switch.png)。

最终 Diff 流使用 wrapper 支持的 `--language zh`（driver 内部区域设置归一为 `zh-CN`），命令为 `node scripts/cdp-packaged-visual-acceptance.mjs --exe out/UthCode-win32-x64/UthCode.exe --flow diff --language zh --port 9361 --timeout-ms 90000`；报告 [`acceptance-report.json`](../../../desktop/dist/ui-acceptance/w05-diff-zh-1791795716094-d5f44f21/acceptance-report.json) 为 passed，driver/Electron 均 exit 0，共 5 张 PNG。真实 controlled Git 状态包含 added/deleted/modified/rename 和 `?? untracked.txt`；untracked 路径保留而正文不进入 patch。最终实包 modified hunk 显示 `@@ -1,2 +1,2 @@`。1000 行文件仅显示变更附近 7 行上下文；新增/删除色、行号、时间戳及 header scope selector 均由当前包检查通过。Staged / Unstaged 分别呈现真实 29 / 22 行和精确路径；切换至新 Session 后公开 Runtime owner 匹配、旧 Diff 清空。范围图见 [`current-workspace-diff-unstaged.png`](../../../desktop/dist/ui-acceptance/w05-diff-zh-1791795716094-d5f44f21/current-workspace-diff-unstaged.png) 与 [`diff-owner-switched.png`](../../../desktop/dist/ui-acceptance/w05-diff-zh-1791795716094-d5f44f21/diff-owner-switched.png)。两份报告的 console errors、renderer exceptions 与未解释 stderr 均为空，runner-owned cleanup 均成功。

此前失败报告继续保留且不作为通过：Settings 首轮 driver 点击了控件容器而没有打开真实下拉，下一轮错误要求 portal 菜单与允许透明/不同层次的 trigger 背景完全同色；Diff 报告显示行首 count 形如 `<redacted>` 时，Renderer 将 hunk 和后续更改行误分类为 meta。现在 Settings flow 按 portal/root/list 的主题 token 与实际颜色核对并留有匹配前诊断截图；Diff 解析只允许 count 位置出现 `<redacted>`，数字 start 仍用于行号，baseline 仅忽略运行时生成的 `/.uthcode/permissions.toml`，`untracked.txt` 仍参与真实状态断言。Settings 通过报告 `w05-settings-ui-en-1791795022779-cfb0284e` 曾在 modal/switch transition 中拍摄中间帧；当前 QA 在截图前有界等待 animation/transition 结束、modal opacity=1 和 switch 终态。曾用不受 wrapper 支持的 `--language zh-CN` 启动 Diff flow 时参数校验失败且没有启动产品；本节只引用使用 `--language zh` 的最终成功报告，不把参数失败算作产品验收。上述历史报告均未覆盖或替代最终 Settings/Diff 通过报告。count 脱敏兼容性由失败报告、count 占位符定向回归及 Reviewer 复核支持；最终实包使用普通可见数字 count，不单独证明脱敏 count 路径。窄视图和 System 配色是在本包 CDP flow 中检查的 Renderer 状态，不是原生窗口尺寸或 OS DPI 结果。

Context-Index 已同步 PR #133 合并、7 项 UI 追加和当前 304/typecheck/package/make/Settings/Diff 证据；GUI 当前事实补充脱敏 hunk count 保持隐藏的行为，用户手册既有 Diff 操作说明已覆盖可见行为。原 T12 Checklist 仍是 40/40；7 项追加 UI 不计入冻结 Checklist 条目。1719/4 skip Python、297 项 Desktop 与 SHA `65aa…` native modal 为之前源码轮次证据，本轮没有重跑 Python、执行新的原生验收或安装生成的 Installer。独立 Reviewer 已只读核对两个最终报告和关键 7 张截图，通过且无新 finding；本轮记录完成后停止 Worker 写入。

勘误：PR133 仅合并前一轮原 W01–W05；本轮 7 项 UI 的实现、独立 Review 与最终 packaged QA 已通过，Git 提交和合并待 Root 完成。

### 用户追加 8 项 UI 的 Renderer 回归更新（2026-10-12）

本轮追加的界面范围在此前 7 项之上，包含左侧 Settings 全局搜索、Diff scope 收紧与无时间展示、未跟踪可读文本正文、空 Composer 稳定高度、Settings 单一清除按钮，以及同一 Turn 的整体活动折叠与 interaction 时间顺序。更新 [GUI 当前事实](../../../docs/context/GUI/GUI-Context.md)、[State 当前事实](../../../docs/context/A03-State/State-Context.md)、[Getting Started](../../../docs/user-manual/getting-started.md) 与 Context-Index；T12 冻结 Checklist 未改，原 40/40 只表示冻结工作包条件。

首轮完整 Desktop npm 有 305 项，299 passed、6 failed；原报告 [`ui-refinement-round2-npm-test.log`](../../../desktop/dist/ui-acceptance/ui-refinement-round2-npm-test.log) 的失败均在 `renderer-attachments.test.tsx`：旧 Diff 时间戳、旧“无可用内容”尾部、未跟踪 status-only，以及把 reasoning 作为独立 timeline-entry 的断言。更新这些测试为当前 UI 合同，保留真实 Diff scope/status 与 lazy Session、背景 owner、迟到历史和 Tool output hydration 检查。实际回归又确认旧 activity group key 把带 Run ID 的 live reasoning 与缺少 Run ID 的同 Turn history reasoning 分到不同组，并生成重复 React key。`ChatTimeline` 现在按当前 Session 中公开的 `turn_id` 归组，同 Turn 的 live/replay reasoning、Tool 与 interaction status 共用一组；缺少 Turn ID 的记录仍各自成组。测试确认两条 reasoning 与 Tool 位于一个懒 Session 回放组，迟到的其他 Turn 保持独立，Session 选择和新草稿不被抢占，外置 Tool output 仍从同一组恢复。

当前执行的受影响 Renderer 命令为 `npm exec -- tsx --test tests/renderer-attachments.test.tsx tests/renderer.test.tsx tests/renderer-chat.test.tsx tests/renderer-state.test.ts tests/renderer-state-ui.test.tsx`：223 passed、0 failed、9.60s、exit 0；输出包含既有 `SidebarInfo` 测试未包入 `act(...)` 的 React warning。`npm run typecheck` (`tsc --noEmit`) exit 0。Root 之前的架构边界 23 passed 与隔离 QA 13 passed 属于本轮尚未变化的现有证据，可按原命令和日志引用。Root 正重跑完整 npm；前一轮 source 变化前的 `npm run package` exit 0 不作为当前包证据，最终 npm、package/make 与 packaged QA 均待 Root 的后续结果。本段没有新的 packaged、native、Installer 或真实 Provider 结果。

范围更正：上一节的“untracked 仅状态/路径、不生成正文”记录的是此前 7 项 UI 轮次。随后用户明确要求 Review 显示真实未跟踪文本文件内容；当前范围依此显示受限的 Unstaged/all 新文件 patch，staged 仍不包含它。二进制、消失或不可读文件保持局部不可用状态，不伪造正文或统计。此前 116 项 Git/Bridge Python 与本段新增 DTO Renderer 回归分别验证后端投影和界面合同；旧记录不作为当前行为描述。

### Reviewer P1/P2 修正：untracked Review 脱敏与窄 Composer（2026-10-12）

Reviewer 发现真实未跟踪文件 diff 将换行分开的配置秘密改写为 `+` 行后，普通整串脱敏未覆盖 `synthetic-alpha\nsynthetic-beta`。Review 投影现仅在 unified diff 的 `@@` hunk 内识别新增源码行，去掉 Git 行首标记后对连续正文复用 Application redactor 的保留换行模式，再恢复 patch 标记；新的 `diff --` 文件头会退出 hunk。这样真实源码首行 `++ literal-alpha-9d41` 对应的 `+++ literal-alpha-9d41` 仍会脱敏，而文件头 `+++ b/...` 不会误入正文。真实隔离 Git/Bridge 回归覆盖 literal 与 env 多行值、该 `++` 边界、未跟踪正文、输出字节上限和截断；命令 `conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_application_tools.py tests/test_desktop_bridge.py tests/test_git_tools.py --tb=short` 结果为 127 passed、13.95s、exit 0。

第二项 packaged 诊断曾显示 720px 空 Composer 的权限、模型和 Send 控件换成三行，撑高输入区。空 Composer 在窄窗口/侧栏下使用单行网格和图标 Send；Send 仍保留真实 `title` 与 `aria-label`，有内容时原有按钮文字与布局不变。Renderer 回归命令 `npm exec -- tsx --test tests/renderer-attachments.test.tsx` 为 30 passed、0 failed、0 skipped、3.68s、exit 0；`npm run typecheck`（`tsc --noEmit`）exit 0；`git diff --check` exit 0。以上是定向源码验证，不代表本次完整 Desktop 测试或 packaged 复验；Python 脱敏变更使此前包不适用，后续完整验证与重建由 Root 串行执行。未运行 Ruff（既有环境缺少该模块）。

### Reviewer 复审后续修正：截断秘密尾部与宽 Composer（2026-10-12）

Reviewer 复现了 diff 字节上限正好落在多行秘密中间的情况：Git 保留了秘密第一行并设置 `truncated=true`，完整值无法匹配。Application redactor 现可在明确标记为不完整输入时复用既有 `progress_tail_length`，把可能组成已配置秘密的末尾片段一并保留到脱敏边界；Workspace Diff 仅在 Diff 自身被截断且最后一个 added-row 组到达输出末尾时使用此处理，并按原换行恢复 Git patch 行。Bridge 集成回归用真实未跟踪 Git patch 动态计算 byte cap，使其恰好截在 literal 多行秘密两行之间，同时检查完整 literal/env 值、多行片段均未进入 wire、截断事实和输出界限。命令 `conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_application_tools.py tests/test_desktop_bridge.py tests/test_git_tools.py --tb=short` 结果为 127 passed、18.31s、exit 0。

窄 Composer 复审指出空态 Send 的 30px 宽度也落在宽布局基础规则上，而其文字标签只在窄布局隐藏。固定宽度现仅位于两处隐藏标签的窄 viewport / conversation 容器规则；宽空态和有内容状态按可见文字自然确定按钮宽度。Renderer CSS 回归确认基础规则没有固定宽度、两个窄规则才固定 30px，并继续检查两处窄规则隐藏标签。命令 `npm exec -- tsx --test tests/renderer-attachments.test.tsx` 结果为 30 passed、0 failed、0 skipped、4.33s、exit 0；`npm run typecheck`（`tsc --noEmit`）exit 0。`git diff --check` 与 UTF-8 guard 在本次记录后通过。没有运行完整 Desktop npm、package/make 或实际 packaged QA；最终打包及真实界面复验仍待 Root 串行执行，本节定向结果不代替它们。

### Reviewer packaged 复测后续修正：空 Composer 跨断点高度（2026-10-12）

Root 的 packaged Settings 报告 [`acceptance-report.json`](../../../desktop/dist/ui-acceptance/w05-settings-ui-en-1791810980060-b975f426/acceptance-report.json) 发现空 Composer 虽已单行工具栏，1280/900 viewport 的 outer/content/padding 为 123/106/17px，720 docked 为 130/112/18px；两处 textarea 均 64px、Send 均为图标且 resize 为 none。差值来自 docked narrow 下 `.composer-input` 的 column `gap: 6px` 和底部 padding 多 1px。空态在该断点现继续使用原 grid 输入行（动作区仍可在旁边布局），并把 docked 空态底 padding 设为 8px，与宽态 9px top + 8px bottom 一致；有内容的 narrow Composer 仍沿用既有纵向布局与间距。Renderer 回归现检查这一 docked-empty grid/padding 覆盖。`npm exec -- tsx --test tests/renderer-attachments.test.tsx` 为 30 passed、0 failed、3.71s、exit 0；`npm run typecheck`（`tsc --noEmit`）exit 0。

本次只是 CSS/Renderer 回归修正。之前的 npm 306/306 与 package/make exit 0 均早于此改动，不能作为最终包证据；尚未对本修复构建或重新跑 packaged Settings。Root 负责后续串行刷新与实包比较，本段定向验证不替代高度验收。

最终定向回归在保留 filled Composer 窄态纵向布局断言后重跑：`npm exec -- tsx --test tests/renderer-attachments.test.tsx` 为 30 passed、0 failed、4.29s、exit 0；`npm run typecheck` 重新执行 exit 0。该结果替代上一段同一测试在最终断言加入前的 3.71s 计时记录。

### 最终追加 8 项 UI 收口验收（2026-10-12）

本节更新此前关于窄 Composer 高度、Diff 导航及待构建/待验收的中间状态；旧失败报告保留为诊断历史，不代替以下当前源与最终包证据。本轮 8 项 UI 修改尚未提交或合并。此前 W01–W05 经 PR127–133 合并，前一轮 7 项 UI 经 PR134（`701bfc0`）合并；本轮没有预设 PR 编号。原冻结 Checklist 保持 40/40、`implemented_unarchived`，追加 UI 条件未写入冻结文件。

源码定向证据仍有效：`npm exec -- tsx --test tests/renderer-attachments.test.tsx` 为 30 passed、0 failed、4.29s、exit 0；`npm run typecheck`（`tsc --noEmit`）exit 0；Conda `re-uthcode` 下 `conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_application_tools.py tests/test_desktop_bridge.py tests/test_git_tools.py --tb=short` 为 127 passed、18.31s、exit 0。架构 23 项和隔离 QA 13 项沿用此前各自命令结果，本轮未重跑。

最终构建与完整 Desktop 测试串行完成：`npm run package`、`npm run make` 均 exit 0，随后 `npm test` 为 306 passed、0 failed、0 skipped、0 cancelled，60,865.8855ms、exit 0。日志分别为 [`ui-refinement-round2-height-package.log`](../../../desktop/dist/ui-acceptance/ui-refinement-round2-height-package.log)、[`ui-refinement-round2-height-make.log`](../../../desktop/dist/ui-acceptance/ui-refinement-round2-height-make.log) 和 [`ui-refinement-round2-height-npm-test.log`](../../../desktop/dist/ui-acceptance/ui-refinement-round2-height-npm-test.log)。两个打包阶段的 bundled Runtime Coding 与 General 独立 prompt initialize/session/status/shutdown smoke 均通过。生成的安装器为 `desktop/out/make/squirrel.windows/x64/UthCode Setup.exe`，204,828,672 bytes，时间 2026-10-12 21:34:12；本轮只生成，未安装。

最终 packaged/CDP 命令均从 `desktop/` 执行，`--port 9361 --timeout-ms 180000`：

```powershell
node scripts/cdp-packaged-visual-acceptance.mjs --flow settings-ui --language en --port 9361 --timeout-ms 180000
node scripts/cdp-packaged-visual-acceptance.mjs --flow diff --language zh --port 9361 --timeout-ms 180000
node scripts/cdp-packaged-visual-acceptance.mjs --flow permission --language en --port 9361 --timeout-ms 180000
```

Settings 最终报告 [`acceptance-report.json`](../../../desktop/dist/ui-acceptance/w05-settings-ui-en-1791812583145-e6e1d467/acceptance-report.json) 为 passed，共 14 张 PNG。它验证了搜索位于侧栏标题下、单一清除按钮、浅色/深色/System 主题和 portal 菜单配色、Model/API Key 等真实字段定位、API Key 保持隐藏、键盘开关保存及同名项目/General Archive owner 筛选；保存全过程没有成功提示闪现。空 Composer 在 1280、900、720 viewport 的外层高度均为 123px、textarea 均为 64px 且 `resize:none`；宽态 Send 标签适配，菜单切换不改变高度，Escape 恢复焦点。代表截图：[侧栏搜索](../../../desktop/dist/ui-acceptance/w05-settings-ui-en-1791812583145-e6e1d467/settings-sidebar-search-single-clear.png)、[720px 空 Composer](../../../desktop/dist/ui-acceptance/w05-settings-ui-en-1791812583145-e6e1d467/empty-composer-720.png)。

Diff 最终报告 [`acceptance-report.json`](../../../desktop/dist/ui-acceptance/w05-diff-zh-1791812659437-e1aec125/acceptance-report.json) 为 passed，共 6 张 PNG。工作区标题旁 selector 为 120×28px；页面没有可见时间或重复空段。真实 tracked added/deleted/modified/rename 路径呈现 Git hunk、行号和红绿行；1000 行文件只呈现变更附近 7 行上下文。正式 `?? untracked.txt` 在 All/Unstaged 有受限新增正文，staged 不含该正文；切换 Session 后旧 Diff 清空。另由真实 unborn-project 的 New Session 导航进入后，`new-file.txt` 的 `UNBORN_NEW_FILE_BODY` 以新增行显示，staged 排除且 unstaged 恢复。该 unborn 项目同时出现运行时生成的 `.uthcode/permissions.toml` 路径，因此不将其描述为仅有一个未跟踪路径。代表截图：[未暂存 Diff](../../../desktop/dist/ui-acceptance/w05-diff-zh-1791812659437-e1aec125/current-workspace-diff-unstaged.png)、[unborn 新文件](../../../desktop/dist/ui-acceptance/w05-diff-zh-1791812659437-e1aec125/diff-unborn-new-file.png)。

Permission 最终报告 [`acceptance-report.json`](../../../desktop/dist/ui-acceptance/w05-permission-en-1791812728440-25e5b941/acceptance-report.json) 为 passed，共 4 张 PNG。隔离本地 synthetic Provider 完成预期 3 次 streaming 请求（不是外网真实 Provider）；每次请求提供 16 个 Tool definitions，界面投影为 2 个 Tool activity 条目，其中 1 个失败。单 Turn 有 3 段 reasoning、1 个默认折叠的一级组、无逐段 reasoning 折叠；失败命令在默认折叠的二级详情中，pending Permission 控件保持可操作，已完成的 waiting/answered 状态位于 final 前，活动组与 Composer 等宽。Fixture report 的子进程 exit code 为 1，但 flow、driver 与 Electron 主状态均为 passed/0，3 次预期请求已观察到，fixture stderr 为空且 owned cleanup 标记成功；因此不表述为所有子进程均 exit 0。代表截图：[pending control](../../../desktop/dist/ui-acceptance/w05-permission-en-1791812728440-25e5b941/permission-pending-control.png)、[折叠活动组](../../../desktop/dist/ui-acceptance/w05-permission-en-1791812728440-25e5b941/permission-turn-collapsed.png)、[展开失败命令](../../../desktop/dist/ui-acceptance/w05-permission-en-1791812728440-25e5b941/permission-failed-command-expanded.png)。三个最终报告的 Electron/driver exit code 均为 0，console errors、renderer exceptions、unexplained stderr 均为空，runner-owned cleanup 均成功。CDP viewport 结果不代表本轮原生窗口、系统 DPI 或安装流程验收；本轮未执行外网真实 Provider 请求，也未触碰用户配置、已安装窗口或 `test-file.md`。

GUI-Context、A03-State 与 Getting Started 已包含本轮可长期复用的 Settings、Review Diff、未跟踪文件、空 Composer、Turn 活动组、失败 Tool 与 pending interaction 行为，故本次仅更新 Context-Index 当前状态，不重复扩写上述文档。Context-Index 将 PR134 与本轮尚待 Git 的 8 项 UI 分开记载；W05 最终记录完成后停止 Worker 写入，等待原 Reviewer 终审。

链接勘误：更早的 native 首轮与两份 Lifecycle 历史段把三个产物链接写成 `../../../dist/...`，该相对路径落到仓库根 `dist/`，目标不存在。历史文字和结果保持不变；实际文件位于 [`root-native-first-pass.json`](../../../desktop/dist/ui-acceptance/w05-native-send-20261011-205913/root-native-first-pass.json)、[`w05-lifecycle-en-1791724043266-1b8326c0/acceptance-report.json`](../../../desktop/dist/ui-acceptance/w05-lifecycle-en-1791724043266-1b8326c0/acceptance-report.json) 与 [`w05-lifecycle-en-1791724295939-009cd3e8/acceptance-report.json`](../../../desktop/dist/ui-acceptance/w05-lifecycle-en-1791724295939-009cd3e8/acceptance-report.json)；三处目标路径均已核实存在。

最终截图复核补充：当前轮的 [`current-workspace-diff-unstaged.png`](../../../desktop/dist/ui-acceptance/w05-diff-zh-1791812659437-e1aec125/current-workspace-diff-unstaged.png) 中，modified hunk 的 count 实际显示为 `<redacted>`；它支持本轮 count 占位符的实际渲染，不沿用前轮可见数字 count 的截图事实。Permission 报告里的 fixture exit code `1` 是 runner 清理终止记录；本轮仍只记录 3 次预期请求、flow passed 与 driver/Electron exit 0，不写成 fixture exit 0。

### Composer 响应式选择器与活动 Turn 空输入修正（2026-10-13）

本次追加修正将权限和模型选择器的文字/图标状态绑定到 Composer 实际内容宽度：宽度至少 600px 时显示当前值，空间不足时收为单个图标；菜单宽度不再受紧凑触发器限制，并按视口约束位置和高度（最高 220px）。空白或纯空白输入在活动 Turn 中继续显示禁用 Send，输入非空白文字后才启用 Steering；空闲 Coding 会话的仅附件提交仍保留。空 Composer 固定高度、空 textarea 的 `resize:none` 与有内容输入的既有扩展行为未改变。

在 `desktop/` 执行 `.\node_modules\.bin\tsx.cmd --test tests/renderer-attachments.test.tsx tests/renderer.test.tsx`，结果为 147 passed、0 failed、0 skipped、0 cancelled，21,535.219ms，exit 0；`npm run typecheck`（`tsc --noEmit`）exit 0。首次定向运行有 1 项因临时改变既有 CustomSelect `title` 文案契约失败；恢复原文案后完整定向集通过。此次未运行完整 npm、package/make 或 packaged QA；独立复审已启动，Root 后续负责串行整包构建与 Settings/Delay 实包验收。本节结果不代表其尚未运行的报告。

### Reviewer 复现宽态模型名称截断及修正（2026-10-13）

Root 对此前构建包的 Settings flow 首次报告 [`w05-settings-ui-en-1791853998025-6afc1e85/acceptance-report.json`](../../../desktop/dist/ui-acceptance/w05-settings-ui-en-1791853998025-6afc1e85/acceptance-report.json) 失败：1264px viewport、820px Composer 内容宽度下，`qwen3.7-flash-openai-responses` 仍被固定 280px 模型选择器截断。第二份旧包报告 [`w05-settings-ui-en-1791854108271-51e23864/acceptance-report.json`](../../../desktop/dist/ui-acceptance/w05-settings-ui-en-1791854108271-51e23864/acceptance-report.json) 同样在宽态完整名称断言处失败；它在此之前已实际通过权限/模型菜单 210/320px 宽度、220px 高度与视口边界及 Escape 恢复焦点检查。本次将宽态模型选择器改为内容自然宽度、最大不超过父级 Composer 可用宽度并保留 flex 收缩，未改变 600px 显示文字断点或 599px 以下单图标状态。

新源码定向命令 `.\node_modules\.bin\tsx.cmd --test tests/renderer-attachments.test.tsx tests/renderer.test.tsx` 结果为 147 passed、0 failed、0 skipped、0 cancelled，21,508.819ms，exit 0；`npm run typecheck`（`tsc --noEmit`）exit 0。此前包上的 Delay flow [`w05-delay-en-1791854067355-a4328723/acceptance-report.json`](../../../desktop/dist/ui-acceptance/w05-delay-en-1791854067355-a4328723/acceptance-report.json) 实测空/空白 Send disabled、非空 Steering enabled、清空后 disabled、Pause/Cancel 保留且真实取消收口；这是旧包及本地 fixture 证据，不是修复后当前包验收，也不是外网 Provider 测试。当前宽态 CSS 修正尚待 Reviewer 复审及 Root 重跑新包 Settings/Delay flows；未运行 full npm 或 package/make。

### 宽态模型名修正后的最终 Desktop 与 packaged 验收（2026-10-13）

以下新证据来自宽态选择器采用自然宽度后的当前源码，取代前两份旧包 Settings 的长名称失败和“待重跑”状态；旧失败报告仍保留作诊断记录。Root 在 `desktop/` 顺序执行 `npm test`（307 passed、0 failed、0 skipped、0 cancelled，52,100.7974ms，exit 0）、`npm run package`（exit 0）与 `npm run make`（exit 0）。完整测试日志、package 日志和 make 日志分别为 [`ui-refinement-round3-final-npm-test.log`](../../../desktop/dist/ui-acceptance/ui-refinement-round3-final-npm-test.log)、[`ui-refinement-round3-final-package.log`](../../../desktop/dist/ui-acceptance/ui-refinement-round3-final-package.log) 和 [`ui-refinement-round3-final-make.log`](../../../desktop/dist/ui-acceptance/ui-refinement-round3-final-make.log)；两次构建的 bundled Runtime Coding 与 General initialize/session/status/shutdown smoke 均通过。

当前安装器为 [`UthCode Setup.exe`](../../../desktop/out/make/squirrel.windows/x64/UthCode%20Setup.exe)，204,825,088 bytes，2026-10-13 09:22:20 本地时间；仅生成，未安装。

当前包 Settings report [`acceptance-report.json`](../../../desktop/dist/ui-acceptance/w05-settings-ui-en-1791854569786-b342f8af/acceptance-report.json) passed，共 18 张 PNG。1280/900/720 viewport 下 Composer 内容宽度为 728/348/188px，对应文字选择器数为 2/0/0；空 Composer 外层高度 123px、textarea 64px 且 `resize:none`。长模型 `qwen3.7-flash-openai-responses` 在宽态空输入与已输入状态均完整显示，fit 均为 true；窄态填充输入收为图标。Permission 菜单实际为 210×144.375px，顶部 699px、底部 843.375px；Model 菜单为 320×220px，顶部 635px、底部 855px，在 720×900 viewport 内完整显示 6 项（Choose 与 5 个模型），无溢出，Escape 恢复触发器焦点。Root 已目视检查宽态空输入、宽态有输入及活动 Turn 空 Composer 截图。

当前包 Delay report [`acceptance-report.json`](../../../desktop/dist/ui-acceptance/w05-delay-en-1791854593196-5c1f88ea/acceptance-report.json) passed，共 6 张 PNG。空输入是空态且 Send 禁用、标签为 Send，Pause/Cancel 均存在；空白输入仍禁用 Steering，非空文字启用，清空后再次禁用。实际 Cancel 收束了运行中的 Turn。该本地 fixture 共 1 次请求；fixture exit code 1 是 runner 清理终止记录，不代表所有子进程 exit 0，也不是外网 Provider 验收。

上述两个当前包报告的 driver/Electron exit code 均为 0，console errors、renderer exceptions、unexplained stderr 均为空，runner-owned cleanup 均成功。当前修正已通过包级 Settings/Delay 复验；本轮未重新执行原生窗口或系统 DPI 验收，未安装生成的 Installer，未运行外网真实 Provider，也未触碰用户配置、已安装窗口或 `test-file.md`。本轮修改已验收，Git 收口待 Root 处理；前一轮 8 项 UI 已由 PR135（`3bbdcbaf`）合并，不与本轮 pending 修改混记。

最终验收记录勘误（2026-10-13）：上文旧 Settings 失败段中的“820px Composer 内容宽度”应读作“820px Composer 外层宽度”；当前包 Model 菜单段中的“完整显示 6 项”应替换为“包含 6 个 DOM 选项（Choose 与 5 个模型），220px 高的可滚动菜单只同时呈现部分选项，超出部分可滚动查看；菜单自身位于视口内”。原记录保留为历史文字，本 EOF 勘误明确替代这两处不准确表述。
