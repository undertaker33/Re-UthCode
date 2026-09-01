# W06 Acceptance 与 Cleanup 实施反馈

## 首次实施

本反馈记录 W06 按 Prompt 串行完成 T10 → T11 的验收、清理和文档同步结果；后续返工只在本文 EOF 追加，不覆盖本节。

### 开工边界

- 已完整读取 `AGENTS.md`、`docs/README.md`、`docs/Context-Index.md`、`docs/rules/WorkPackageRules.md`、`docs/rules/UserDecisionBoundary.md`、`docs/OutstandingDebtList.md`、F02 原始需求/Spec/Tasks/Checklist/W06 Prompt、W01～W05 Feedback、T10 W06 Feedback 及现有 CDP/packaged harness 事实。
- 严格串行完成 T10 后再进行 T11；只修改 T10/T11 授权的现有 CDP fixture/driver/packaged runner、`desktop/package.json`、current-facts 文档、F02 Checklist 和本 Feedback。
- 未修改 T10 冻结目录中的任何文件，未创建第二套 harness，未自动归档，未执行 Git commit、push、merge、rebase、tag 或 release。
- 本轮没有发现生产代码缺陷，因此没有停止场景或请求重新派发 W01～W05 Prompt；早期 packaged 失败均定位为现有 driver 选择器/fixture 配置与当前代码合同不一致，已在 W06 授权的 harness 范围内收敛。

## T10 端到端验收

### Harness 变更与覆盖

- `desktop/package.json` 的正式 `npm test` 脚本加入既有 `settings-acceptance-isolation.test.ts`，确保 Settings acceptance isolation 不被脚本遗漏。
- `desktop/scripts/cdp-openai-fixture.mjs` 保持本地 OpenAI-compatible HTTP fixture，只生成公开 wire payload：AskUser 生成 1 题或 4 题、2～3 个结构化 options 和选择题自由输入合同；不再生成旧 `allow_other` 字段或 “Other” option。新增 `TodoWrite` 场景并让 Todo 状态先展示再完成；Plan 参数拆成多个 chunk，增加受控 chunk delay 以覆盖 `PlanContentDelta` 流式路径。
- `desktop/scripts/cdp-driver.mjs` 仍通过现有 CDP/DOM 入口驱动真实 Renderer，覆盖 AskUser 1/4 题、Plan approve/revise/cancel、Tool、Todo、Permission、Provider retry、delay pause/cancel、Session 超过 5 个、`/compact` 和 `/status`；修正当前 command completion、session row、pause/cancel、Plan draft 等选择器，不注入 Renderer state 或 IPC 协议。
- `desktop/scripts/cdp-packaged-visual-acceptance.mjs` 继续使用现有 isolated launcher、bounded deadline 和临时 profile；将 provider flows 接入同一 runner，并为 fixture/config、临时 preferences、stdout/stderr 和 cleanup 写入已有 acceptance report。没有增加第二个 E2E/视觉框架。

### 精确自动结果

执行环境为 Windows 工作区 `D:\project\Re-UthCode` 的 `re-uthcode` Conda 环境。最终 packaged 报告均在 `desktop/dist/ui-acceptance/<run-name>/acceptance-report.json`，每个最终报告 `exit.status=passed`、driver/electron exit code 均为 0、`consoleErrors=0`、`rendererExceptions=0`，临时 electron/driver/fixture/host 根目录均已移除。

| Flow | 最终报告目录 | 覆盖结果 |
| --- | --- | --- |
| `stream` | `w06-packaged-stream-en-current` | Provider streaming 与同一 Turn 输出 |
| `tool` | `w06-packaged-tool-en-current` | `ReadFile` Tool call/result |
| `todo` | `w06-packaged-todo-en-current-r2` | `TodoWrite`、Todo strip replace-all 与完成收口 |
| `ask` / `ask-one` | `w06-packaged-ask-en-current`、`w06-packaged-ask-one-en-current` | 4 题与 1 题 AskUser typed submit/free input |
| `permission` | `w06-packaged-permission-en-current` | `.env` 请求的 Permission surface 与 Allow once |
| `plan` | `w06-packaged-plan-approve-en-current-r3`、`w06-packaged-plan-revise-en-current`、`w06-packaged-plan-cancel-en-current` | 多 chunk Plan draft、review approve/revise/cancel |
| `failure` | `w06-packaged-failure-en-current` | fixture 504 后 Retry 与最终输出 |
| `delay` | `w06-packaged-delay-pause-en-current-r2`、`w06-packaged-delay-cancel-en-current` | 延迟请求 pause/resume 与 cancel |
| `sessions` | `w06-packaged-sessions-en-current-r2` | 6 个 Session、切换/replay、continuation 与 `/compact` |
| `visual` | `w06-packaged-visual-en-current`、`w06-packaged-visual-zh-current` | packaged Electron 中英文、主题/Runtime layout/窄 viewport 截图流 |
| `shell` | `w06-packaged-shell-en-current` | packaged shell/Composer/Renderer readiness |

provider flow 的 fixture stdout 记录了真实本机 `127.0.0.1` HTTP `/v1/chat/completions` 请求（sessions flow 记录 6 次请求）；fixture 子进程在 runner finally 清理阶段被终止，报告中的 fixture exit code 1 是该清理细节，不改变整体 acceptance pass。没有写入真实 API key，只有临时 `env:UTHCODE_CDP_FIXTURE_KEY` 绑定。

打包命令：

```text
conda run --no-capture-output -n re-uthcode npm run package -- --platform=win32 --arch=x64
```

PyInstaller runtime smoke、Forge package 均成功；最终 packaged executable 为 `desktop/out/UthCode-win32-x64/UthCode.exe`，244440576 bytes，SHA-256 为 `1bbfa02f3d2eb963a0d2661c9e4d8c159379a0195c7a98b44aaf58939c60c00e`。

Python、Desktop 和 shell 自动结果：

- `conda run --no-capture-output -n re-uthcode python -m pytest -q`：`1447 passed, 3 skipped`，exit code 0，299.84s。
- 在 `desktop` 执行 `conda run --no-capture-output -n re-uthcode npm run typecheck`：exit code 0。
- 在 `desktop` 执行 `conda run --no-capture-output -n re-uthcode npm test`：`143 tests, 143 pass, 0 fail, 0 skipped`，exit code 0。首次整套运行出现 1 个已知 renderer timing poll flake，随后 targeted rerun 104/104 通过，最终整套重跑通过；未将首次 flake 描述为通过。
- 既有 dev-shell harness 运行 `npx electron-forge start` 加 CDP shell flow：Renderer ready、Composer、closeShell 和 driver complete 均通过，dev shell/electron exit code 0；使用的临时 host profile 已按精确路径删除。

## T10 真实 Desktop/人工矩阵

本轮只具备当前 Windows 主机上的自动 CDP 和 packaged Electron 条件，没有进行人工鼠标/键盘操作、真实外部 Provider 或干净 Windows 安装。以下是逐项真实状态；未运行项没有在 Checklist 勾选为通过。

| 维度 | 状态 | 证据/边界 |
| --- | --- | --- |
| dev shell / packaged | 自动通过；人工未执行 | dev shell shell-flow 与 packaged shell/feature reports 通过；不是人工验收 |
| dark/light、zh-CN/en、wide/narrow | packaged 自动覆盖部分通过；人工未执行 | visual flow 自动切换 dark/light、Runtime layout 并设置窄 viewport；en/zh 两份 report 通过，未覆盖所有人工布局观察 |
| keyboard-only / mouse | 未完成人工矩阵 | CDP 使用 DOM click、键盘事件和 command completion 做路径 smoke，不等价于人工键盘-only/鼠标矩阵 |
| IME | 未运行 | 当前没有人工输入法条件，未伪造结果 |
| 100%/125%/150% zoom | 未运行 | CDP viewport 不等于 Windows DPI/zoom |
| reduced motion | 未运行 | 未改变系统 `prefers-reduced-motion` 做人工确认 |
| AskUser/Plan/Tool/Compact/Session/Settings | 自动覆盖部分通过；人工未执行 | packaged fixture 覆盖 AskUser 1/4、Plan 三选择、Tool/Todo、`/compact`、Session >5 与 Settings/theme；未人工验证所有 success/fail/cancel、move/restart/resume、Key reveal/hide/untouched/replacement |
| 真实 Provider / 干净 Windows | 未运行 | 仅使用隔离本机 local fixture 和当前工作区 package；不具备真实网络 Provider、干净安装机或 Installer 安装条件 |
| crop/flicker/overlap/focus/duplicate/乱码/reorder | 自动诊断通过；人工未签收 | reports 无 renderer exception/console error，自动 DOM/截图路径通过；人工视觉、辅助功能树和 Session reorder 检查仍未完成 |

早期 packaged `plan`、`delay`、`sessions` 失败分别由旧 mode/Plan busy 选择器、旧 pause/cancel class、旧 session row class 造成；调整现有 driver 后同一 packaged executable 的最终报告通过。它们不是生产缺陷，也没有跨域修改前序实现。

## T11 遗留负担清理与验证

### 否定扫描

以下扫描均在指定 active scope 返回 0 matches（`rg` 因无匹配退出 code 1，属于预期结果）：

```text
rg -n "allow_other" src tests desktop/src desktop/tests desktop/scripts
rg -n "DEFAULT_CONTEXT_WINDOW|configuredContextWindow|renameModelRef|model-1" desktop/src desktop/tests desktop/scripts
rg -n "arguments_delta" desktop/src desktop/tests desktop/scripts
rg -n "DesktopManager|SessionManager|SessionStore|ContextManager|ContextEngine|PlanManager|TodoManager|EventBus|PluginRegistry|TransportFactory" src/uthcode desktop/src tests desktop/tests
rg -n "waitForIdle|IdleWait" src tests desktop/src desktop/tests desktop/scripts
```

历史 F02/T10 冻结文档仍可能保留需求/替代关系中的旧词，但没有修改冻结文件；active source/tests/scripts 不再有旧合同、第二 authority、旧 model/ref、raw argument 或无调用 idle helper 命中。`git diff --name-only -- docs/work/T10-DesktopGUI与TUI全量能力迁移` 和对 `desktop/src/main.ts`、`desktop/src/preload.ts`、`desktop/src/python-runtime.ts` 的 diff 均为空。

### 全量回归与静态检查

- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q`：`23 passed`，exit code 0。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests`：exit code 0。
- `conda run --no-capture-output -n re-uthcode python -m pip check`：`No broken requirements found.`，exit code 0。
- `git diff --check`：exit code 0，仅有 LF/CRLF 常规提示。
- Python full suite、Desktop typecheck/tests 和上述最终 packaged/CDP matrix 均已在 T11 重新核对；精确结果见本 Feedback 的 T10 与本节。

### 文档、欠账与清理

- 按 `docs/README.md` 维护映射同步了 `docs/Tools.md`、`docs/context/A02-Control/Control-Context.md`、`docs/context/A03-State/State-Context.md`、`docs/context/A04-Orchestration/Orchestration-Context.md`、`docs/context/TUI/README.md` 和 `docs/Context-Index.md`，只写入最终代码事实：AskUser free-input hard cut、PlanContentDelta、Application Context/Compaction status 和唯一 Application command/interaction 链。
- `docs/OutstandingDebtList.md` 仅核对未修改；F02 Spec/原始任务书仍明确能力欠账为无，未触发 Persistent Runtime Recovery。W06 在文档中保留了现有 T05/T06/T09 欠账边界，没有新增未来方案。
- 对 F02 工作包与所有本轮修改 Markdown 运行 `uth-utf8-guard`：全部文件通过 UTF-8、replacement/mojibake 与 fenced-code 检查。
- W01～W06 Feedback 均存在；本轮只首次创建本文件，没有覆盖或代写 W01～W05 Feedback。
- 未删除业务源码、测试或未知文件；`desktop/.runtime`、`.webpack`、`node_modules`、`out`、`packaging/.build` 均保留。acceptance 使用的临时 roots 在各报告中标记 removed；没有清理用户构建内容。

## Checklist 与工作包状态

- T10：仅勾选 Python full suite、Desktop typecheck/npm test、现有 CDP fixture/driver、packaged runner 和不可执行条件记录；人工 dev/packaged 全矩阵、人工功能验收、人工视觉/可访问性项保持 `[ ]`。
- T11：否定扫描、architecture/compile/pip/diff、full regression、current-facts 同步、OutstandingDebt 核对、W01～W06 Feedback、UTF-8 guard、Context Index 盘点和 Git/archive/build-cache 边界均已取得证据并勾选。
- 因 T10 仍有人工/真实环境项未完成，F02 Checklist 不是全 `[x]`，`docs/Context-Index.md` 将 F02 保持为 `not_implemented`；没有自动归档 F02 或 T10。

## 复跑补充：Settings reveal 与 Todo packaged flow

本节是首次反馈后的 EOF 追加。为使 acceptance 报告覆盖本轮最后的 driver/fixture 版本，沿用同一个 packaged runner 串行复跑全部 provider flows；没有修改前文事实或 T10 冻结文件。

- 现有 `cdp-driver.mjs` 的共同 Settings 路径增加了窄的 reveal/hide 检查：打开 fixture provider，点击 API Key eye，确认 `env:UTHCODE_CDP_FIXTURE_KEY` 仅在 modal input 中可见，再隐藏并确认密码框为空，最后关闭 modal。只验证 synthetic env expression，不输出真实 secret。
- 现有 `cdp-openai-fixture.mjs` 的 `todo` flow 先发送 `TodoWrite` in-progress 状态，再发送完成状态；driver 对 `.todo-strip` 和最终 continuation 做断言。`cdp-packaged-visual-acceptance.mjs` 仍只扩展既有 provider flow 集合，没有新增 harness。
- 最后版本的 13 个 provider packaged reports 全部 `exit.status=passed`、driver/electron code 0：`w06-final-stream-en`、`w06-final-tool-en`、`w06-final-todo-en`、`w06-final-ask-en`、`w06-final-ask-one-en`、`w06-final-permission-en`、`w06-final-plan-approve-en`、`w06-final-plan-revise-en`、`w06-final-plan-cancel-en`、`w06-final-failure-en`、`w06-final-delay-pause-en`、`w06-final-delay-cancel-en`、`w06-final-sessions-en`。其中 sessions 使用 120000 ms deadline，其余使用 60000 ms；每个报告仍无 renderer exception/console error 且临时根目录清理为 true。
- 复跑仍使用 `desktop/out/UthCode-win32-x64/UthCode.exe` 的 244440576-byte、SHA-256 `1bbfa02f3d2eb963a0d2661c9e4d8c159379a0195c7a98b44aaf58939c60c00e` 包；未重新编译或改变用户构建内容。

### 工作包盘点补充

最终只读盘点 `docs/work/` 的 active 目录为 `F02-DesktopGUI交互与上下文缺陷修复`、`T10-DesktopGUI与TUI全量能力迁移`，archive 目录保持既有历史工作包；F02 feedback 目录已齐全包含 W01、W02、W03、W04、W05、W06 六份文件。该盘点不改变目录归档状态。

### 最终全量回归补充

在本反馈最后一次脚本复跑后重新执行：`conda run --no-capture-output -n re-uthcode python -m pytest -q` 返回 `1447 passed, 3 skipped in 234.27s (0:03:54)`，exit code 0。该结果与前述 Desktop typecheck、`npm test` 的最终通过结果一致。

## 返工追加：W06 Reviewer NOT APPROVED 后最终验收

本节为 Reviewer NOT APPROVED 后重新派发 W06 原 Prompt 的最终 EOF 追加，只补充返工事实，不覆盖前文，也不修改 T10 冻结文件。

### 返工边界与硬门禁

- 串行重跑 T10 → T11，继续复用 `desktop/scripts/cdp-driver.mjs`、`cdp-openai-fixture.mjs`、`cdp-packaged-visual-acceptance.mjs` 与现有 isolated launcher；没有创建第二 harness，没有修改 `desktop/src`/Python 生产链，没有执行 Git 写操作，也没有清理用户已有 `desktop/out` 构建内容。
- 全部 packaged 报告继续使用 `desktop/out/UthCode-win32-x64/UthCode.exe`，244440576 bytes，SHA-256 `1bbfa02f3d2eb963a0d2661c9e4d8c159379a0195c7a98b44aaf58939c60c00e`；没有重新编译或覆盖该用户构建。
- `cdp-packaged-visual-acceptance.mjs` 现在把 `consoleDiagnostics`、`rendererExceptions`、Renderer console errors、Electron/driver/fixture stderr 和 fixture secret marker 纳入最终 status gate。Electron stderr 只允许固定端口的 DevTools listening 行（以及严格匹配当前 packaged renderer 路径的 ResizeObserver console 行）；本次最终报告只出现前者，所有 unexplained stderr 均为 0。首轮 shell 的 `RuntimeBoundaryError: Python Runtime child must be closed before it can be started again` 未被 allowlist，而是通过 driver 在语言 reload 前等待 Runtime Ready 后消除。
- packaged runner 为 fixture/provider 与 visual/shell flow 都写入 runner-owned valid configuration，并仅在新文档完成语言读取后移除精确的 `desktop-preferences.json` seed；最终报告的 `seededPreferenceRemoved`、各临时 root removed 均为 `true`。fixture 仅使用 `env:UTHCODE_CDP_FIXTURE_KEY` 引用；`fixture-test-key`、`raw-native-secret` 在最终报告及其 process artifacts 中均无命中，未使用真实 API key。

### T10 最终 packaged/CDP 矩阵

下表列出本轮最终报告（旧的 `final`/历史失败目录不作为结论）。16 份最终报告均为 `exit.status=passed`，driver/electron exit code 均为 0，`consoleErrors=0`、`consoleDiagnostics=0`、`rendererExceptions=0`，Electron/driver/fixture unexplained stderr 均为 0。

| Flow | 最终报告 | fixture 请求数 | 代表性截图 |
| --- | --- | ---: | --- |
| `stream` | `desktop/dist/ui-acceptance/w06-rework-stream-en-final2/acceptance-report.json` | 1 | Settings reveal/hide |
| `tool` | `desktop/dist/ui-acceptance/w06-rework-tool-en-final2/acceptance-report.json` | 2 | `tool-result`、Settings reveal/hide |
| `todo` | `desktop/dist/ui-acceptance/w06-rework-todo-en-final2/acceptance-report.json` | 3 | `todo-strip`、`todo-complete`、Settings reveal/hide |
| `ask` | `desktop/dist/ui-acceptance/w06-rework-ask-en-final3/acceptance-report.json` | 2 | `ask-user-questions`、`ask-user-review`、`ask-user-complete`、Settings reveal/hide |
| `ask-one` | `desktop/dist/ui-acceptance/w06-rework-ask-one-en-final2/acceptance-report.json` | 2 | 1 题 Questions/review/complete、Settings reveal/hide |
| `permission` | `desktop/dist/ui-acceptance/w06-rework-permission-en-final2/acceptance-report.json` | 2 | Settings reveal/hide |
| `plan approve` | `desktop/dist/ui-acceptance/w06-rework-plan-approve-en-final10/acceptance-report.json` | 2 | `plan-draft-partial`、`plan-review`、`tool-result`、Settings reveal/hide |
| `plan revise` | `desktop/dist/ui-acceptance/w06-rework-plan-revise-en-final4/acceptance-report.json` | 3 | `plan-draft-partial`、`plan-review`、`plan-review-revised`、`tool-result`、Settings reveal/hide |
| `plan cancel` | `desktop/dist/ui-acceptance/w06-rework-plan-cancel-en-final1/acceptance-report.json` | 1 | `plan-draft-partial`、`plan-review`、Settings reveal/hide |
| `failure` | `desktop/dist/ui-acceptance/w06-rework-failure-en-final1/acceptance-report.json` | 2 | Retry/final continuation、Settings reveal/hide |
| `delay pause` | `desktop/dist/ui-acceptance/w06-rework-delay-pause-en-final1/acceptance-report.json` | 2 | `delayed-controls`、Settings reveal/hide |
| `delay cancel` | `desktop/dist/ui-acceptance/w06-rework-delay-cancel-en-final1/acceptance-report.json` | 1 | `delayed-controls`、Settings reveal/hide |
| `sessions` | `desktop/dist/ui-acceptance/w06-rework-sessions-en-final2/acceptance-report.json` | **8/8** | `sessions-over-five`、`compact-command-menu`、`compact-terminal`、Settings reveal/hide |
| `visual en` | `desktop/dist/ui-acceptance/w06-rework-visual-en-final1/acceptance-report.json` | — | dark/light × docked/floating/hidden、narrow |
| `visual zh` | `desktop/dist/ui-acceptance/w06-rework-visual-zh-final1/acceptance-report.json` | — | dark/light × docked/floating/hidden、narrow |
| `shell` | `desktop/dist/ui-acceptance/w06-rework-shell-en-final2/acceptance-report.json` | — | Renderer readiness（shell flow 不产生截图） |

### Plan、Session 与健康矩阵补充

- Plan 三条 flow 均以 `--plan-chunk-delay-ms 1000` 运行（runner 下限为 250ms）。现有 driver 在真实 Renderer 的 MutationObserver/CDP `Debugger.paused` 边界捕获 partial draft：`plan-draft-partial` 的 prefix 为 `Read the fi`，此时同一 `.timeline-entry--plan` 为 `aria-busy=true`，且 `[aria-label="Plan review"]` 不存在；随后才恢复运行并原地出现唯一 Plan Review。approve/cancel 均通过；revise 通过 Revision 2、enabled Approve、`plan-review-revised`，并按两次不同 ProposePlan call 保留两条合法 plan/tool rows。approve partial/review SHA-256 分别为 `7626c0266a44451cee78b63883d5aaaddf03c9ccf5a1b67d8240edca4feae3e8` 与 `844d2b1a769717656e55cf4117726a369fa489d523c4f85b804b50b021fd9b7b`；revise partial/review/revised 为 `8c0a85b1de3860eb5090c124cd5bdce80fa1199bf8d65496acf8a7149d6bed01`、`7d7f71391f616f4b1592699c088b8c8f2bfc899cbd2e2d499063509262cfb46e`、`5848971d546ad52dfeb939c36c1d3c4862694994fa5f5471aeceff001be5067b`。
- sessions 的第一次返工报告曾真实观察到 9 次请求：driver 生成 7 个 Session 后又发送 replay continuation 与 `/compact`。这是验收脚本计数/场景设计错误，不是生产缺陷；driver 已收敛为初始 Session + `session two`～`session six`（共 6 个，满足 >5），加 replay continuation 和 compact，最终 `requestCount=8`、`expectedRequestCount=8`、`requestCountOk=true`。因此前文“6 次请求”的旧结论被本节 8/8 报告明确更正。
- visual en/zh 报告均观察到 requested language、`themes=dark,light`、`runtimePanelLayouts=docked,floating,hidden`；driver 在 dark/light 两次各执行 680/520 viewport × page scale 1/1.25/1.5，并通过 `prefers-reduced-motion=reduce` emulation。每份 visual 报告各有 12 条 responsive assertion，均 `ok=true`、`overflow=false`；computed rect 检查 Composer、textarea、Send、Settings 在 viewport 内，Send 与 Settings 不重叠，focus 保持在消息输入（en `Message UthCode`，zh 为本地化 label）。Tool/Todo/AskUser/Plan/Provider Settings modal 的 CDP DOM identity 断言为单实体；Plan revise 的两行仅对应两次不同 ProposePlan call。
- stream flow 的 driver 还在当前 fixture catalog 上实际断言 `/new`、`/do`、`/model`、`/model ` 的 completion/keyboard focus 与 `fixture/fixture-model` candidate；`/status` 在 terminal status convergence 后才关闭 shell。现有 Desktop tests 同时通过 Session mutation failure 保持原 projection、terminal authoritative idle、manual compact single-flight/compaction gate、Application model catalog-only projection 等断言；W06 未添加第二 Runtime/catalog authority。

### T11 最终回归、扫描与文档状态

- `conda run --no-capture-output -n re-uthcode python -m pytest -q`：`1447 passed, 3 skipped`，exit code 0，175.96s。
- 在 `desktop` 执行 `conda run --no-capture-output -n re-uthcode npm run typecheck`：exit code 0。
- 在 `desktop` 首次执行 `conda run --no-capture-output -n re-uthcode npm test`：146 pass / 1 fail（既有 renderer timing flake，`T05 buffers synchronous turn.start stdout...`，3 次 poll 对 2 次期望）；随后同一完整命令重跑 `147 pass / 0 fail / 0 skipped`，exit code 0。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q`：`23 passed`，exit code 0；`conda run --no-capture-output -n re-uthcode python -m compileall -q src tests` 与 `conda run --no-capture-output -n re-uthcode python -m pip check` 均 exit code 0，后者输出 `No broken requirements found.`；`git diff --check` exit code 0（仅 CRLF 转换提示）。
- 否定扫描均在 active scope 返回 0 matches（rg exit 1 为无匹配预期）：`rg -n "allow_other" src tests desktop/src desktop/tests desktop/scripts`；`rg -n "DEFAULT_CONTEXT_WINDOW|configuredContextWindow|renameModelRef|model-1|arguments_delta" desktop/src desktop/tests desktop/scripts`；`rg -n "DesktopManager|SessionManager|SessionStore|ContextManager|ContextEngine|PlanManager|TodoManager|EventBus|PluginRegistry|TransportFactory" src/uthcode desktop/src tests desktop/tests`；`rg -n "waitForIdle|IdleWait" src tests desktop/src desktop/tests desktop/scripts`。最终报告目录扫描 `fixture-test-key|raw-native-secret` 也无匹配。
- T10 冻结目录 diff 为空；`desktop/src/main.ts`、`desktop/src/preload.ts`、`desktop/src/python-runtime.ts` diff 为空；`docs/OutstandingDebtList.md` 未修改且仍无当前 F02 新增能力欠账。已同步 current-facts 文档与 `docs/Context-Index.md`，Context Index 保持 F02 `not_implemented`，因为人工键鼠/IME/DPI、真实 Provider、干净 Windows、安装/卸载、人工视觉/辅助功能与完整 move/restart/resume 仍未执行。
- F02 Checklist 只保留具有精确自动证据的 `[x]`；人工、真实 Provider、干净 Windows 和未被完整自动覆盖的语义继续为 `[ ]`，没有伪造人工结果。W01～W06 Feedback 齐全，本轮只在 W06 本文 EOF 追加，没有代写 W01～W05。
- 本轮修改的 Markdown 已执行 `uth-utf8-guard`：UTF-8、replacement/mojibake、fenced-code 检查应全部通过；未自动归档 F02/T10，未执行 commit/push/merge/rebase/tag/release。

本轮最终未发现生产缺陷，因此没有停止任何场景，也无需重新派发 W01～W05 原 Prompt；前述 sessions 计数与 shell 启动问题均已在 W06 允许的现有 harness 范围修正。

### 返工证据更正

- 上述 UTF-8 guard 已实际执行，命令输出为 `OK: 8 file(s) passed UTF-8 guard`；不是待执行或推测结果。

## P3 尾项追加：stderr allowlist 收紧与受限复核（2026-09-02）

本节继续只追加到 W06 Feedback EOF；不覆盖前文、不修改 T10 冻结文件、不代写 W01～W05 Feedback，也未执行 Git 写操作。

### P3 修复

- `desktop/scripts/cdp-packaged-visual-acceptance.mjs` 删除了可匹配任意 `file:///` 路径的宽泛 ResizeObserver 规则。当前唯一的额外 Electron stderr allowlist 仅在 Windows 生效，并同时严格匹配 Chromium 的固定 `INFO:CONSOLE:0` 消息、完整 `ResizeObserver loop completed with undelivered notifications.` 文本和由本次 `--exe` 推导的精确 `resources/app.asar/.webpack/renderer/main_window/index.html` URI；固定端口 DevTools listening 行仍按端口和 browser UUID 匹配，其余 Electron/driver/fixture stderr、consoleDiagnostics、rendererExceptions 和 console errors 继续使报告失败。Node 语法检查和一个合成边界检查均通过：精确 renderer URI 命中为 `true`，替换为 `file:///D:/other/index.html` 为 `false`。
- `desktop/scripts/cdp-packaged-visual-acceptance.mjs` 现在把 `--plan-choice` 传给同一个既有 `cdp-openai-fixture.mjs`；fixture 的第二个 `ProposePlan` 分支仅在 `plan-choice=revise` 时启用。首次 P3 sweep 的 `w06-final-p3-plan-approve-en` 失败经 driver/fixture 日志确认是该验收 fixture 在 approve 分支误发 revised plan（第二个合法 ProposePlan），不是生产 Desktop 缺陷；已在现有 fixture/harness 内修正。

### P3 后受限报告事实

- 按本回合“最多一个 bounded acceptance、禁止重复耗时全矩阵”的约束，未重新生成第二套 16 场矩阵。已存在的 `w06-rework-*` 16 份报告仍为此前 runner 版本的完整通过证据；本次 P3 代码变更后的第一轮 `w06-final-p3-*` 只作为诊断记录：16 场中 13 场通过，`plan-approve` 因上述 fixture 分支问题失败，`delay-pause` 与 `visual-zh` 仅因实际 Electron stderr 出现精确 packaged renderer ResizeObserver 行而被旧的“仅 DevTools”分类判失败；这两份报告的 consoleErrors、consoleDiagnostics、rendererExceptions 和 driver/fixture stderr 均为 0，Electron 进程本身退出码为 0，不能把它们描述为生产错误。
- 唯一的受限 packaged acceptance 是 `desktop/dist/ui-acceptance/w06-p3-targeted-delay-pause-en/acceptance-report.json`：`exit.status=passed`，driver/electron code 均为 0，consoleErrors/consoleDiagnostics/rendererExceptions 及 Electron/driver/fixture unexplained stderr 均为 0，fixture request count 为 2，`seededPreferenceRemoved` 与四个 runner-owned root cleanup 标记均为 `true`。本次输出没有再次产生 ResizeObserver 行；上条合成检查和第一轮两份实际 stderr 记录共同证明 allowlist 仅覆盖该精确来源，不能据此声称 P3 后全 16 场已重新通过。
- 现有通过报告中的 Plan partial-before-review、AskUser/Plan/Tool/Todo/Settings 截图与 DOM identity、sessions `8/8`、中英文 dark/light、680/520 × zoom 1/1.25/1.5、reduced-motion、overflow/focus/rect 健康断言继续可追溯；本轮没有重新生成截图，也没有伪造人工键鼠、IME、真实 Provider、干净 Windows、安装器或完整 move/restart/resume 结果。

### 受限检查与状态

- 已执行 `node --check scripts/cdp-packaged-visual-acceptance.mjs`、`node --check scripts/cdp-openai-fixture.mjs`、精确 allowlist 合成检查和上述一个 bounded packaged acceptance，均通过；没有重新运行 Python/Desktop 全量回归，以免违反本回合禁止重复耗时矩阵的边界。此前本文件已记录的 Python full suite、Desktop typecheck/npm test、architecture/compile/pip/diff 与 UTF-8 guard 结果仍保持原样。
- `docs/Context-Index.md` 的 F02 当前事实已同步为：既有 16 份 `w06-rework-*` 报告通过，P3 收紧后有一个定向报告通过，post-P3 16 场未重新完整复跑；因此 F02 仍为 `not_implemented`，人工、真实 Provider、干净 Windows 与视觉/可访问性未验证项继续保持未完成。F02 Checklist 未新增勾选，所有人工/真实环境项仍为 `[ ]`。

## P1 返工追加：当前生产包 command flow（2026-09-02）

本节继续只追加 EOF。Reviewer 指出此前全部 packaged 报告使用 SHA-256 `1bbfa02f3d2eb963a0d2661c9e4d8c159379a0195c7a98b44aaf58939c60c00e` 的旧包，不能证明随后合入的 W03 Slash 本地化和 W05 typed command-result 生产代码；该 finding 成立。

- 在 `desktop` 执行 `conda run --no-capture-output -n re-uthcode npm run package`，exit code 0。当前源码生成的 `out/UthCode-win32-x64/UthCode.exe` 为 SHA-256 `6cf2fd8e9e79074554aeb072de713f8edf7696679a5b656f12ae25a0c7c32849`，`resources/app.asar` 为 SHA-256 `e0a3b6161db820f60230eb4ee6fabdcc76b21b9546df8cbe9756925f7b5a3af8`。
- 在现有 runner/driver 中增加 `commands` flow，没有创建第二 harness。该 flow 对真实 packaged Renderer 逐项断言：`/compact` 与 `/status` 候选各只有一个 canonical value，说明只来自当前 locale 且无中英文混排；执行 `/compact` 后只有一个本地化 terminal notice；执行 `/status` 后 RuntimePanel 消费 typed safe params，模型为 `fixture/fixture-model`，页面不含 `RuntimeRequestError`、native、diagnostics、配置路径或 `file://`；并保留 Settings、theme、Runtime layout 与 responsive health 路径。
- 英文报告 `desktop/dist/ui-acceptance/w06-current-package-commands-en/acceptance-report.json`：`passed`，driver/electron exit code 0，4 张截图，consoleErrors/consoleDiagnostics/rendererExceptions 均为 0，Electron/driver/fixture unexplained stderr 均为 0。
- 中文首次报告 `w06-current-package-commands-zh` 在新会话标题等待处达到 120000 ms deadline；原因是 driver 的标题与 Composer selector 只覆盖英文 aria/text，是 acceptance harness 本地化缺口，不是生产故障。driver 已把新会话标题和 Composer selector 收敛为 en/zh-CN 两种真实 locale，未修改生产代码。
- 修复后的中文报告 `desktop/dist/ui-acceptance/w06-current-package-commands-zh2/acceptance-report.json`：`passed`，使用同一当前包 hash，driver/electron exit code 0，4 张截图，consoleErrors/consoleDiagnostics/rendererExceptions 均为 0，Electron/driver/fixture unexplained stderr 均为 0。
- 旧 16 场报告继续只作为旧生产包的历史交互矩阵证据；当前包只完成上述 en/zh-CN command 定向集成，不外推为当前包完整 16 场、人工键鼠/IME/OS DPI、真实 Provider、干净 Windows 或安装器验收。F02 因 Checklist 仍有未完成项保持 `not_implemented`，不自动归档。

## 总控人工补充：隔离 packaged Windows UI（2026-09-02）

- 总控使用当前 SHA-256 `6cf2fd8e9e79074554aeb072de713f8edf7696679a5b656f12ae25a0c7c32849` 的 packaged EXE，在 `desktop/dist/manual-acceptance/` 下的隔离 HOME/APPDATA/LOCALAPPDATA/Electron user-data 启动真实窗口；没有使用或写回日常用户配置，没有保存 Settings，没有发送消息或触发真实 Provider 请求，结束后通过窗口正常关闭。
- 鼠标进入 Settings；键盘打开 Theme 下拉、ArrowDown/Enter 切换深色草稿，再打开 Language 下拉切换 English。中文/英文和浅色/深色页面均未观察到下拉闪烁、菜单遮挡、横向裁切、重复控件或明显颜色对比异常；Cancel 返回 Chat 后页面保持可操作。
- Chat 中通过 Tab 可见焦点依次到达 permission 与 model 控件；真实键盘输入 `/` 打开英文 Slash menu，六个候选各为一条 canonical value + 英文说明，无中文泄漏或重复说明；ArrowDown 改变 active row，Escape 关闭 menu 且保留输入文本，没有意外提交。
- 本次人工操作只覆盖当前 packaged app 的普通鼠标/键盘、主题/语言和 Slash 交互。未切换真实 Windows IME，未修改 OS DPI，未在 dev shell 或干净 Windows/Installer 环境运行，也未执行真实 Provider、完整 AskUser/Plan/Tool/Todo/Session move/restart/resume 人工矩阵；因此 Checklist 对应复合项继续保持 `[ ]`，不把局部人工证据描述为整项通过。

### 总控提交前最终回归

- `conda run --no-capture-output -n re-uthcode python -m pytest -q`：`1448 passed, 3 skipped in 179.66s`，exit code 0。
- `conda run --no-capture-output -n re-uthcode npm run typecheck`：exit code 0。
- Desktop `npm test` 首跑为 149/150，唯一失败仍是本文件此前记录的 `T05 buffers synchronous turn.start stdout...` timing flake（轮询次数 3，而测试期望 2）；未改代码直接完整复跑为 `150 passed, 0 failed, 0 skipped in 60.25s`，exit code 0。该首跑失败被保留，不描述为首次全绿。
- `tests/test_architecture_boundaries.py`：`23 passed in 4.92s`；`python -m compileall -q src tests` 与 `python -m pip check` 均 exit code 0，后者输出 `No broken requirements found.`。
- 三组 active-scope 否定扫描（`allow_other`；旧 Context/Model/raw Plan 符号；禁止的 Manager/Registry/Factory 抽象）均为 0 matches；三个 CDP 脚本 `node --check`、`git diff --check` 均 exit code 0。
- 对 7 个 tracked 修改 Markdown 与新建 W06 Feedback（合计 8 个）重新执行严格 UTF-8 解码、replacement/常见乱码与 fenced-code 成对检查，全部通过。
