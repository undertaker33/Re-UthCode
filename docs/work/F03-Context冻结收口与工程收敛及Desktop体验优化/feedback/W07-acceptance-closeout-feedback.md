# W07 acceptance closeout feedback

## 初始记录

W07 T08→T09 验收记录从本文件首次创建开始追加；不覆盖后续重跑事实。未执行 Git 写操作、工作包归档或冻结正文修改；`.workbuddy/` 与 `临时目录/` 保持原状。

当前已确认的基线：全量 Python 首次执行为 `1477 passed, 2 failed, 3 skipped`；两个失败分别是 Eval profile compaction fixture 未携带严格协议要求的 exact refs，以及一次 TUI session picker close flaky。两项已各定向执行一次：Eval 失败可稳定复现，TUI 定向通过。失败根因与重跑事实将在 T08/T09 完成后继续追加。

## T08：Python 与 Context measurement

### 修复与回归

- `eval/workloads.py` 的离线 `ProfileWorkloadProvider` 现在读取真实 Application compaction request 的 `Required coverage (copy only these Turn IDs)` JSON；先用 request metadata 的 Turn IDs 对齐，再把每项原始 `refs` 复制到 fixture response。缺少 coverage/refs 或顺序不一致时受控失败；没有放宽 `src/uthcode/core/compaction.py` strict parser，也没有伪造引用。
- 定向复跑：`conda run --no-capture-output -n re-uthcode python -m pytest tests/eval/test_eval_profile.py::test_profile_two_attempts_complete_distinct_read_edit_verify_routes -q` -> `1 passed in 42.99s`，exit 0。
- TUI flaky 对照：`conda run --no-capture-output -n re-uthcode python -m pytest tests/test_w06_integration_delivery.py::test_tui_session_picker_open_close_does_not_create_session -q` -> `1 passed in 1.20s`，exit 0。
- 全量回归：`conda run --no-capture-output -n re-uthcode python -m pytest -q` -> `1479 passed, 3 skipped in 186.08s (0:03:06)`，exit 0。
- post-fix 架构/编译/依赖：`python -m pytest tests/test_architecture_boundaries.py -q` -> `23 passed in 5.04s`，exit 0；`python -m compileall -q src tests eval` -> exit 0；`python -m pip check` -> `No broken requirements found`，exit 0。

### Context measurement evidence

现有测试入口已覆盖要求的 measurement 场景；没有新增第二 harness 或固定产品阈值。以下是测试断言中的 before/after 与失败语义，数字是 fixture/公开 diagnostics 的实际值：

| 场景 | before | after / 结果 | 证据 |
| --- | --- | --- | --- |
| exact/local prospective count | provider counter 返回 `input_tokens=3`，source `provider.test`；故障 counter 进入 local fallback | 两次 `prepare_prospective_request_async` 分别返回 source `exact` / `local` | `tests/test_w05_diagnostics.py::test_prospective_request_keeps_exact_or_local_count_source` |
| Application Context projection | 冷启动 default budget `256000`，`available=false`，measurement `unavailable` | Provider ceiling `32000` 后 `available=true`、measurement `estimate`、source `context_compiler`；prospective compile 保持 estimate | `tests/test_w05_diagnostics.py::test_application_context_status_uses_budget_and_downgrades_after_mutation` |
| no reduction | summary 长度为 epoch input tokens + `0` 或 `1` | `changed=false`、failure `no_reduction`、timeline records `0`、commit calls `0`；auto 路径也不 recovery/commit | `tests/test_t09_1_context_protocol_e2e.py::test_l4_equal_or_larger_output_is_a_non_committing_no_reduction`, `test_w05_auto_non_reduction_is_not_recovered_or_committed` |
| oversized | oldest complete Turn 规划为 bounded subpass；中间 summary 只在进程内 | 成功 candidate 只有一个原 Turn identity 的 Fine，refs 完整；failure/cancel/invalid 都不返回 candidate | `tests/test_context_compaction.py::test_oversized_complete_turn_builds_one_fine_with_full_refs`, `test_oversized_subpass_failure_cancel_and_invalid_leave_no_candidate` |
| malformed multi-turn | strict response 缺 entries/list、refs 或 coverage | `CompactionValidationError`，Timeline 不 append；正常 Application 重试只接受带 exact refs 的 response | `tests/test_context_compaction.py::test_multiturn_compaction_requires_explicit_entries_refs_and_coverage`, `tests/test_t09_1_context_protocol_e2e.py::test_invalid_l4_coverage_has_no_timeline_commit` |
| projection changed | first final composition `conversation_projection_changed=false` | reduced final composition fingerprint changed and flag `true`; restore to full projection remains `true` | `tests/test_w05_diagnostics.py::test_context_projection_fingerprint_only_publishes_final_request` |
| Provider cache read/write | missing usage fields -> `not_available`; explicit default-zero is not inferred | explicit `cached_tokens=3`/`cache_write_tokens=0` -> both `available` with provenance; explicit zero read -> `available,tokens=0` | `tests/test_w05_diagnostics.py::test_application_diagnostics_are_json_safe_and_do_not_copy_payloads`, `test_provider_cache_default_zero_is_not_measured_and_explicit_zero_is_available` |

定向 measurement 集合：`conda run --no-capture-output -n re-uthcode python -m pytest tests/test_context_compaction.py tests/test_context_budget_gate.py tests/test_t09_1_context_protocol_e2e.py tests/test_w05_diagnostics.py -q` -> `120 passed in 12.84s`，exit 0。该集合覆盖 exact/local、no-reduction、oversized、malformed、projection changed、cache read/write availability；真实 Provider cache/latency/费用仍不在本地 fixture 验收范围。

参数化的 manual candidate recount 还实际覆盖了两种来源迁移：`exact-before-local-after` 使用 exact `100` 的 before 计数并在受控 endpoint 故障时进入 local，`local-before-exact-after` 在 before 故障后恢复为 exact `1,000`；两条路径都要求最终 candidate changed 且 Timeline 有效。对应证据为 `tests/test_t09_1_context_protocol_e2e.py::test_manual_candidate_recounts_both_sides_after_count_transition`。

## T08：Desktop 构建与可执行验收

以下 Desktop 命令均显式设置了 `UTHCODE_PYTHON=C:\Users\93445\miniconda3\envs\re-uthcode\python.exe`，未使用系统 Python。

- `conda run --no-capture-output -n re-uthcode npm --prefix desktop run typecheck` -> `tsc --noEmit`，exit 0。
- `conda run --no-capture-output -n re-uthcode npm --prefix desktop test` -> `180 passed, 0 failed, 0 skipped`，exit 0，Vitest duration `90017.4465ms`。
- `conda run --no-capture-output -n re-uthcode npm --prefix desktop run package` -> Runtime/PyInstaller build 使用 Conda Python `3.12.13`、PyInstaller `6.22.2`，bundled Runtime `ready/status/shutdown` JSONL 与 `importlib.resources` prompt asset smoke 通过；Forge package 在既有输出目录失败，exit 1：`EBUSY: resource busy or locked, unlink 'D:\project\Re-UthCode\desktop\out\UthCode-win32-x64\resources\app.asar'`。未删除或覆盖该旧输出，因此 T08 package 项保持未勾。
- 依 Prompt 的隔离输出 fallback：`conda run --no-capture-output -n re-uthcode node --import tsx -e "import { api } from '@electron-forge/core'; import { resolve } from 'node:path'; api.package({ dir: process.cwd(), outDir: resolve('out/f03-w07-api') }).then(() => console.log('Forge API package completed')).catch((error) => { console.error(error); process.exitCode = 1; });"`（cwd=`desktop`）-> `Forge API package completed`，exit 0；可执行文件为 `desktop/out/f03-w07-api/UthCode-win32-x64/UthCode.exe`，`244440576` bytes。
- `conda run --no-capture-output -n re-uthcode npm --prefix desktop run make` -> Runtime build 与 bundled smoke 通过；Forge make 同样在既有 `desktop/out/UthCode-win32-x64/resources/app.asar` 处 EBUSY，exit 1，未生成 installer，未删除旧产物。

### Packaged CDP / visual 限制

只执行一次现有 visual driver，命令为：

```powershell
$env:UTHCODE_PYTHON='C:\Users\93445\miniconda3\envs\re-uthcode\python.exe'
conda run --no-capture-output -n re-uthcode node scripts/cdp-packaged-visual-acceptance.mjs --exe 'D:\project\Re-UthCode\desktop\out\f03-w07-api\UthCode-win32-x64\UthCode.exe' --language en --flow visual --output 'D:\project\Re-UthCode\desktop\out\f03-w07-cdp-visual-en' --timeout-ms 60000
```

结果为 exit 1，报告 `[acceptance-report.json](../../../../desktop/out/f03-w07-cdp-visual-en/acceptance-report.json)`，runId `a152faeb-72c9-477e-a441-6296aa834a36`。在失败前实际通过了 UthCode shell、Composer、en language reload、Settings、dark theme、Back-to-chat、docked Runtime panel 和 separator ARIA 合同；viewport `1264x761`、dpr `1`，截图为 `main-dark-docked.png`。报告中 `consoleErrors=0`、`consoleDiagnostics=0`、`rendererExceptions=0`，Electron/driver/fixture 均无 unexplained stderr，隔离 profile/driver/host 临时根均已清理。

失败发生在第一次 separator 拖拽：`Input.dispatchMouseEvent` 的 `mousePressed` 后，带 `buttons:1` 的 `mouseMoved` 在 5 秒 request timeout；这是拖拽序列，不是无按键 ordinary mouse move 对照，未继续重试，真实阻塞原因未明。因而没有声称完整 wide/narrow、dark/light、zh-CN/en、100/125/150% zoom、reduced-motion、native pointer、Windows 原生缩放或人工视觉通过；T07 真实 dev identity/event/terminal 链、T08 CDP/visual 全矩阵和交互全矩阵保持未勾。W05 已知 Provider stream fixture candidate timeout 也不在本轮盲重跑。

## T09：否定扫描与文档收口

### 否定扫描事实

- 旧 compaction/history 路径扫描：`rg -n -S "uthcode\.application\.history|application/history|_transcript_entries_for_message|ContextCompactor\.compact|_compact_locked|compact_sync|synchronous.*compact" src tests eval desktop/src desktop/tests` -> `0 matches`。
- 重复 authority 扫描命中仅为当前真实 `ToolRegistry` 与单一 Slash `CommandRegistry` 的定义/说明；未发现 `EventBus`、`Manager` 或第二套 registry。`tests/test_architecture_boundaries.py` -> `23 passed` 已覆盖边界回归。
- Provider SDK import 扫描仅命中 `src/uthcode/integrations/providers/{anthropic,openai_compat,openai_responses}.py`，符合 SDK 只在 integrations 的边界；`src/uthcode/interfaces` 对 `uthcode.core`/`uthcode.integrations` 的直接 import 扫描为 `0 matches`。
- Future/placeholder 扫描命中均有当前语义：Core 的三个 `_JsonModel`/process control 抽象 `NotImplementedError`、真实 `TODO_WRITE_TOOL_DEFINITION`、Application 对未知调用的安全 placeholder 文本、Renderer 表单 `placeholder=` 文案及旧 eval fixture 注释；没有未接入的生产能力占位。无调用方的旧 history facade/export 已由 W06 删除，本轮旧入口扫描为 0。

### 文档、索引与完整性

- 按 `docs/README.md` 映射同步了 `docs/user-manual/{commands,configuration}.md`、`docs/core-design/{README.md,A04-Orchestration/01-斜杠命令编排.md}`、`docs/context/{A03-State/State-Context.md,A04-Orchestration/Orchestration-Context.md,GUI/GUI-Context.md}`；补充的是当前代码事实：exact/local/unavailable measurement、strict refs/coverage、oversized bounded subpass、no-reduction、manual/automatic 同源、Renderer/lifecycle 单一 owner、Settings 单 modal/secret draft、`copyText` 原文复制、layout/Focus 瞬态和 Last Provider Request Usage 与 Context 分离。`docs/Tools.md`、getting-started、A01 model 文档经维护映射核对后未改，因当前 Tool surface/安装入口/Provider 抽象与源码仍一致。
- 全量直接目录盘点：`docs/work/` 有 `3` 个 active package（F02、F03、T10），`docs/work/archive/` 有 `17` 个 archived package；`docs/Context-Index.md` 已更新 snapshot date `2026-09-04` 与 F03 W07 事实，仍保持 `not_implemented`，因为 Checklist 仍有 T07/T08 未验证项。
- `docs/OutstandingDebtList.md` 与 F03 无新增/变更/回补欠账，内容保持不变；未自动归档 F03/F02/T10。
- `uth-utf8-guard` 对 F03 工作包 Markdown 及全部本轮修改 Markdown 共 `26` 个文件通过（exit 0），未发现 replacement character、常见乱码或不成对 fenced block。
- 文档内部 Markdown link checker 共检查 `38` 个链接，`BROKEN_LINKS=0`；秘密示例扫描仅保留 `env:MY_PROVIDER_API_KEY`、`literal-secret` 和历史 feedback 中的 fixture/test marker，均为文档示例/测试标记而非真实凭据；未发现 provider key、raw native secret 或 payload 泄漏。`git diff --check` exit 0，仅报告工作树 LF→CRLF 提示。
- `git -c core.quotePath=false diff --name-only` scope check 的 tracked modified 共 `10` 个文件，全部位于 F03 checklist、`eval/workloads.py`、Context Index、A03/A04/GUI、core-design、user-manual；`out_of_scope_tracked=0`。本轮没有修改其他冻结工作包、`.workbuddy/` 或 `临时目录/`，也未执行任何 Git 写操作。

### 结构职责与 file-size 对比

只记录结构事实和辅助大小对比，不设置 LOC KPI。W07 除离线 Eval fixture 外没有改生产源码结构；当前职责仍为：`core/compaction.py` 唯一 Core compaction；`application/context.py` 负责 Context snapshot/gate/projection；`application/generation.py` 保持唯一 `UthCodeApplication` authority；`desktop/src/renderer/state.ts` 为 Renderer reducer authority；`useRuntimeLifecycle.ts` 为 runtime lifecycle owner；Settings/layout/Runtime 投影仍由各自现有 Renderer 组件承载。

相对 W07 起始 HEAD 的选定文件 bytes/lines 对比：`eval/workloads.py` `36553/807 -> 39021/834`（fixture helper 增加 exact refs 校验）；`src/uthcode/core/compaction.py` `86524/1874 -> 86960/1874`、`src/uthcode/application/context.py` `84467/1842 -> 86016/1842`、`src/uthcode/application/generation.py` `129763/2800 -> 132058/2800`、`desktop/src/renderer/App.tsx` `73646/1293 -> 74566/1293`、`RuntimePanel.tsx` `10731/146 -> 10837/146`（均为起始 HEAD 已存在的 W01-W06 结果，本轮未改）；`SettingsEditorModal.tsx` `19984/332 -> 19984/332`、`ChatTimeline.tsx` `10508/165 -> 10508/165` 不变。没有以这些数字宣称质量或性能 KPI。

## W07 Checklist 状态与清理结论

- T01～T06 原有证据保持勾选；T07 仅真实 Desktop dev identity/event/terminal 链未勾；T08 的 full Python、architecture/compileall/pip、measurement 已勾，标准 package/make、CDP/visual 全矩阵和交互全矩阵、真实 Provider/干净 Windows/人工视觉仍未勾；T09 的否定扫描、文档映射、work/archive 盘点与索引、OutstandingDebt、UTF-8、link/secret/diff、W01～W07 Feedback、结构职责/file-size、未归档/Git 禁止项均在完成相应证据后勾选。
- 本 Feedback 是首次创建；没有覆盖或改写 W01～W06 Feedback，任何后续重跑应继续追加到本文件末尾。
- 生成的 Desktop `.runtime`、`.webpack`、`packaging/.build`、隔离 `out/f03-w07-api` 与 CDP 报告属于本轮可再生成验收产物；旧 `desktop/out/UthCode-win32-x64` 未删除，`.workbuddy/`、`临时目录/` 未触碰。

## 返工 1：Reviewer P2 measurement 与文档修订

- Checklist 的 T09 两条冻结正文已恢复为 `HEAD adfddb8` 原文，仅保留有证据的 `[x]` checkbox：盘点索引条目仍是“只有 Checklist 全部完成且 Feedback 齐全时才将 F03 标为 `implemented_unarchived`”，欠账条目仍是“F03 仍无新增、变更或回补欠账时保持其内容不变”。
- 使用现有 `tests/test_t09_1_context_protocol_e2e.py` 的 `_L4Provider`、`_seed_session`、`ApplicationSessionService` 和 `UthCodeApplication.compact_session()` 做一次 PowerShell stdin 短测量；没有写入脚本、测试平台或产品代码。普通请求计数直接取实际 `account_generation_request(request).input_tokens`，exact Provider 返回 `ContextCountEstimate`，local Provider 让既有 `OSError` fallback 生效；输出来自 `validate_manual_candidate` 的实际 immutable before/after requests。

| Application fixture | ordinary before → after | source before → after | commit/result |
| --- | --- | --- | --- |
| Provider count available | `1425 → 932` | `exact → exact` | `changed=true`，`timeline_records=2`、`fine_entries=1` |
| Provider count outage on both sides | `1425 → 932` | `local → local` | `changed=true`，`timeline_records=2`、`fine_entries=1` |
| short summary but ordinary unchanged | `5000 → 5000` | `exact → exact` | `changed=false`，`timeline_records=0`、`fine_entries=0`；`summary=short`，seed Turn 原文 `2007` chars |

前两行是同一个真实 Application manual candidate validator 的最终比较值，均允许一个 Fine 加一个 checkpoint durable commit。第三行使用现有 `_L4Provider(ordinary_count_override=5000, compaction_summary=short)` fixture：summary 确实比 seed Turn 短，但 ordinary before/after 相等，因此按既有 `no_reduction` 规则在 durable append 前拒绝。首轮 stdin probe 曾因 JSON 不能序列化测试内部 `FrozenList` 而 exit 1；未触及产品，随后加 `finally: app.close()` 和字符串化输出重跑成功，三个 `TemporaryDirectory` 根均清理，首轮残留 lock/root 也已按精确路径清理。

- F03 实施前后职责/大小对比已补充为 `cc270f3` → 当前工作树：`git show cc270f3:<path>` 与当前文件均按统一 LF 字节读取，职责迁移仅记录真实变化：Core compaction 从 `core/context.py` 收敛到唯一 `core/compaction.py`；Application request preparation/compaction 与 Context orchestrator 汇合，`generation.py` 保持唯一 `UthCodeApplication` authority；Renderer state/lifecycle 分别由 `state.ts`/`useRuntimeLifecycle.ts` 唯一持有；Desktop Settings/layout/Runtime 投影仍由现有组件承载。新增的是 W02 Application compaction/request preparation、W03 Renderer helper/lifecycle、W05 Settings/layout/Focus 组件，删除的是 W06 `application/history.py` facade；没有新增第二套 authority。F03 实施前后统一 LF bytes/lines 的确切表格将在本节后续记录中追加，W07 起始 HEAD 的旧 physical-CRLF 对比表只作为 W07 自身 fixture/docs 变化，不再冒充 F03 结构对比。

统一 LF 读取的选定职责文件 bytes/lines（`cc270f3 → current`）如下；`absent` 表示该职责在 F03 实施前不存在或已在 W06 删除：

| 文件 | cc270f3 | current | 职责/迁移 |
| --- | ---: | ---: | --- |
| `src/uthcode/core/context.py` | `98964/2380` | `66234/1582` | 保留 budget/compiler/gate，移出 compaction 执行主体 |
| `src/uthcode/core/compaction.py` | `22317/518` | `86524/2059` | 唯一 Core compaction parser/plan/candidate |
| `src/uthcode/application/context.py` | `73315/1752` | `84467/1975` | Application Context snapshot/gate/projection 与 compaction orchestrator |
| `src/uthcode/application/compaction.py` | absent | `10980/315` | tool-free Provider compaction path、Hard Gate、usage |
| `src/uthcode/application/request_preparation.py` | absent | `8755/257` | counted/prospective request 与 exact/local source |
| `src/uthcode/application/generation.py` | `122557/2922` | `129763/3024` | 唯一 `UthCodeApplication` use-case authority |
| `src/uthcode/application/history.py` | `555/17` | absent | W06 删除无语义 history facade |
| `desktop/src/renderer/state.ts` | `90608/1791` | `61434/1169` | 唯一 RendererState/reducer authority |
| `desktop/src/renderer/useRuntimeLifecycle.ts` | absent | `15897/398` | runtime generation/owner/tail/stale/terminal lifecycle |
| `desktop/src/renderer/state-normalization.ts` | absent | `12965/290` | 纯 state/text normalization helper |
| `desktop/src/renderer/state-session.ts` | absent | `21669/452` | 纯 Session/runtime projection helper |
| `desktop/src/renderer/safe-markdown.tsx` | absent | `8718/211` | Markdown safe rendering/copy projection |
| `desktop/src/renderer/SettingsEditorModal.tsx` | absent | `19984/354` | 单 Settings Provider/Model modal transaction |
| `desktop/src/renderer/App.tsx` | `74401/1423` | `73646/1361` | 组合界面 owner，不再持有重复 reducer/lifecycle |
| `desktop/src/renderer/SettingsView.tsx` | `41854/602` | `15360/247` | Settings 页面 draft/导航，modal 分离承载 |
| `desktop/src/renderer/RuntimePanel.tsx` | `8410/122` | `10731/148` | Context/Compact 与 Last Provider Usage 安全投影 |

该表只描述 F03 实施前后的职责与文件形态，不设 LOC KPI；W07 自身只新增离线 fixture exact refs 校验及文档/验收记录，未改变上述生产职责。

- `docs/user-manual/getting-started.md` 已补充 Desktop 分隔条 Pointer/键盘调整与稳定边界持久化、viewport clamp/窄屏 overlay、Focus Mode 临时恢复、`copyText` 保留代码原文、user-scroll/new-message 入口，以及 Current Context (`exact`/`estimate`/`unavailable`) 与 Last Provider Request Usage 双口径。`docs/core-design/README.md` 已补充 prospective ordinary 同源 before/after、mixed source 不直接比较、summary 变短但 ordinary 不缩小时 `no_reduction`，以及 manual retained target 多 epoch/bounded stop。

返工 1 收口校验：`checklist_non_checkbox_diff=0`，F03 main/spec/tasks/prompt 的 tracked changes 为空；最终 `uth-utf8-guard` 为 `OK: 27 file(s) passed UTF-8 guard`、exit 0；文档 link checker `38` links / `BROKEN_LINKS=0`，`git diff --check` exit 0（仅 LF→CRLF 工作树提示）。

## 返工 2：Desktop acceptance / CDP restore boundary

本轮只调整现有 CDP 验收脚本的等待参数传递、CSS viewport 的合成 resize 边界和 fixture candidate 的显示断言；未改生产 UI、未新增 harness，也未执行 Git 写操作。

### 已完成证据

- 先用既有 Application/fixture 做普通输入对照：`desktop/out/f03-w07-cdp-input-round2/input-comparison.json` 记录无按键 `mouseMoved`（`buttons=0`、未先 `mousePressed`）两次均 `returned`，耗时分别 `5014ms`；拖拽序列 `mousePressed=9ms`、`mouseMoved(buttons=1)=5024ms`、`mouseReleased=13ms`，拖拽后 sidebar `aria-valuenow=310`，普通输入后仍为 `286`。两类 CDP 请求都在约 5 秒返回，原有 `request-timeout-ms=5000` 会先超时；因此新增现有 acceptance script 的 `--request-timeout-ms` 透传（默认仍为 `5000`），本次 packaged acceptance 使用 `10000`，没有放宽行为断言，也没有声称 native pointer/OS zoom 通过。对应 isolation 检查 `packaged acceptance forwards an explicit CDP request timeout to its existing driver` -> `1 passed, 0 failed`。
- 现有 driver 在 responsive/layout probes 的 CSS viewport 进入点显式 dispatch 合成 `resize`，并在四处 `Emulation.clearDeviceMetricsOverride` restore 边界后 dispatch 同一合成事件、等待实际宽屏布局恢复再继续截图。恢复断言按真实界面核对：docked 为两个 separator，hidden/floating 为一个；en/zh 报告均记录恢复后宽度 `1264`、separator 值 `[286,260]`（docked）或 `[286]`（hidden），没有把窄屏状态带入后续宽屏截图。此处仅证明 CDP/CSS 合成边界，不证明原生窗口 resize。
- 使用当前标准包 `desktop/out/UthCode-win32-x64/UthCode.exe`（`244440576` bytes，SHA-256 `22a71860c08f98a922d92e0203377ba7e39ec39785b7f6749437a3a6c0a2eef8`）运行现有 visual acceptance：en 报告 `[acceptance-report.json](../../../../desktop/out/f03-w07-cdp-round2-en-restore/acceptance-report.json)`，runId `3ba669ca-706e-464c-8feb-43908400f1b0`，exit 0；zh-CN 报告 `[acceptance-report.json](../../../../desktop/out/f03-w07-cdp-round2-zh-restore/acceptance-report.json)`，runId `816e8b6f-7173-4486-9e35-d556d4f290aa`，exit 0。每份报告均为 6 张截图、dark/light、docked/floating/hidden、`1264x761` 与 `760x640`，并在 `1280/800/680/520` CSS 宽度执行 `1/1.25/1.5` page scale 与 reduced-motion；`consoleErrors=0`、`consoleDiagnostics=0`、`rendererExceptions=0`、unexplained stderr=0。page scale/CSS resize 是 CDP 合成证据，native pointer、Windows 原生缩放和人工视觉仍未验证。
- 当前标准包和标准构建已恢复成功：`conda run --no-capture-output -n re-uthcode npm --prefix desktop run package` -> exit 0；`conda run --no-capture-output -n re-uthcode npm --prefix desktop run make` -> exit 0。安装器为 `desktop/out/make/squirrel.windows/x64/UthCode Setup.exe`（`175683072` bytes），nupkg `175000935` bytes，`RELEASES` `78` bytes。首轮既有 `app.asar` EBUSY 事实保留为历史记录；WorkBuddy 由用户关闭后才解除锁，本轮未手动 kill 或强制删除解锁，标准构建随后正常重建当前输出。
- Desktop 回归证据：显式 `UTHCODE_PYTHON=C:\Users\93445\miniconda3\envs\re-uthcode\python.exe`；`npm test` -> `181 passed, 0 failed, 0 skipped`；typecheck exit 0；现有 Settings acceptance exit 0，包含 single modal/ARIA/focus、Provider→Model、cancel rollback、secret reveal/replacement、chat scroll geometry 与 language hydrate；`renderer-chat.test.tsx` + `renderer.test.tsx` -> `92 passed, 0 failed`；离线 runtime identity 入口 -> `14 passed, 0 failed`，这不是真实 dev shell 链。

### Provider fixture 与未验证边界

- `/model` candidate 的可见标签断言改为真实 fixture display name `CDP fixture`，wire ref 仍由既有 status 断言固定为 `fixture/fixture-model`。修复后的 stream run `[acceptance-report.json](../../../../desktop/out/f03-w07-cdp-round2-stream-en-label/acceptance-report.json)`（runId `0a0f907d-efb2-43cd-b39e-d4abe522a4b6`）真实命中 fixture HTTP request `count=1`、`model=fixture-model`、`stream=true`，但在 global deadline 内没有出现 `fixture response`，因此 stream output 不通过，未将候选标签修复误记为端到端成功。
- 对当前标准包的短 probe `[acceptance-report.json](../../../../desktop/out/f03-w07-stream-diagnostic-round2-probe-standard/acceptance-report.json)`（runId `65bb2716-6199-4da0-b03f-d6d768b68ff2`）只读取安全 status/DOM/fixture request：status 已从 running 收敛为 completed、`termination_reason=final_answer`，run/turn 与 `fixture/fixture-model` 一致，fixture request 为 1；DOM timeline 仍为 0 且没有 `fixture response`。该 probe 在 driver 语言 `Page.reload` 前注入 `window.__w07Events`，reload 会清除页面 listener/数组，所以 reload 后的 `events=[]` 不能证明事件通道缺失；不据此提出生产缺陷归因。真实 Provider 输出、真实 Desktop dev shell 的 Renderer→Bridge→Application→Core identity/event/terminal 完整链仍未验证，交由对应责任方后续处理。
- 真实 Provider、干净 Windows、人工视觉、native pointer/Windows zoom 和用户实际桌面输入环境均不可在本机本轮确认；这些项保持未勾选并只记录为限制，不描述为通过。现有 packaged visual 的 console/renderer/stderr allowlist 结果为零 unexplained，但不替代上述环境证据。

返工 2 收口校验：仅 Checklist checkbox 变化及本 Feedback/Context Index 文档同步；保留返工 1 历史，不覆盖旧 EBUSY/旧 stream 失败事实。`T07` 真实 dev shell、`T08` 真实 Provider/干净 Windows/人工视觉与 native 环境项继续未勾选，F03 状态继续为 `not_implemented`。

### 返工 2 最终 guard

- 追加本轮后执行 `conda run --no-capture-output -n re-uthcode python C:\Users\93445\.codex\skills\uth-utf8-guard\scripts\check_utf8_docs.py "docs/Context-Index.md" "docs/work/F03-Context冻结收口与工程收敛及Desktop体验优化/F03-Context冻结收口与工程收敛及Desktop体验优化-checklist.md" "docs/work/F03-Context冻结收口与工程收敛及Desktop体验优化/feedback/W07-acceptance-closeout-feedback.md"` -> exit 0，`OK: 3 file(s) passed UTF-8 guard`；无 replacement character、常见乱码或不平衡 fenced block。
- Context Index、F03 工作包 Markdown 的增量内部链接检查：`11 links`，`BROKEN_LINKS=0`；`git diff --check` exit 0，仅有 LF/CRLF autocrlf 提示。
- `adfddb8` 冻结 Checklist 对比（忽略 checkbox 状态）`checklist_non_checkbox_diff=False`；F03 冻结正文、spec、tasks、prompt 的 tracked diff 为空。本轮不触碰 `.workbuddy/`、`临时目录/`，未执行 Git 写操作。

## 返工 3：真实 Desktop dev shell identity/event/terminal 链

- Reviewer 已独立复核并通过 T07 真实 dev shell 链。本轮只使用现有 Electron Forge `start` 入口与既有本地 HTTP fixture；没有改生产源码、冻结正文或新增通用 harness。独立 ignored 证据为 `[probe-report.json](../../../../desktop/out/f03-w07-dev-renderer-probe/probe-report.json)` 及同目录的 Forge/fixture stdout、stderr 日志，未覆盖 W03 packaged 证据目录。
- 成功 probe 的实际命令为：

  ```powershell
  node out/f03-w07-dev-renderer-probe.mjs 9471
  ```

  probe 内部将 `UTHCODE_PYTHON` 精确设置为 `C:\Users\93445\miniconda3\envs\re-uthcode\python.exe`，并以 development launch `-m uthcode.interfaces.desktop` 启动 Python runtime。Forge 命令为 `electron-forge start --enable-logging -- --remote-debugging-port=9471 --no-sandbox --disable-gpu --user-data-dir=<isolated temp>`；Renderer target 实际为 `http://localhost:3000/main_window/index.html`，因此该记录是 dev shell（`isPackaged=false`）而非 packaged executable。
- 真实链路结果：`listenerInstalled=true`；`window.uthcode` 的 `requestRuntime`、`subscribeAgentEvents`、preference API 均可用且 API frozen。事件顺序精确为 `runtime_state → turn_started → iteration_started → assistant_message_delta → usage_updated → assistant_message_completed → turn_completed`（7 events）。除无 identity 的 `runtime_state` 外，其余 6 个事件全部匹配最终 run/session/project；selected status 的 run 为 `529f155489f84ebcab4dece4af037fc3`、session 为 `1f8e2523d0614b92995b095a28722a90`、project 为 `D:\project\Re-UthCode`，最终 turn 为 `844f05c45b9a4f13aaf25a46dbd70502`。最终 `runtime.run.status=completed`、`termination_reason=final_answer`；fixture HTTP request 为 1 次（`model=fixture-model`、`stream=true`），UI `timelineCount=2` 且 prompt/`fixture response` 均可见，Last Provider Request Usage 为 input `2`、output `3`、total `5`。
- 进程结束必须按真实事实解释：probe 收尾时只对自己启动的 Forge/fixture 子树执行了 `taskkill /PID /T /F`，所以报告中的 Forge 与 fixture `exit=1` 是受控强制结束，不是自然 `exit=0`；不能据此写“无异常”或“stderr clean”。`forge.stderr.log` 实际包含 Electron `sandboxed_renderer.bundle.js script failed to run` 与 `TypeError: Cannot destructure property 'preloadScripts' of 'binding.startupData' as it is null`，另有 React DevTools 开发提示；`fixture.stderr.log` 为空。该 stderr 事实保留为 dev probe 限制，不影响已通过的 Renderer/Bridge/Application/Core identity/event/terminal 断言。
- T08 未验证边界继续保持未勾：packaged wrapper stream output、真实 Provider、native pointer/Windows zoom、干净 Windows、人工视觉和用户实际桌面输入环境。本轮未将 packaged stream 的 reload 前 listener 误报为事件通道缺陷，也未用 dev probe 替代这些环境证据。

## 返工 3 追加：locale seed 与 packaged stream/visual 收口

本轮继续只修改现有 acceptance wrapper/driver 及其 isolation test；未改生产 UI、未新增 harness、未触碰冻结正文，也未执行 Git 写操作。之前英文 packaged probe 报告中的中文界面事实保留为历史限制：旧 wrapper 在 reload 后删除 seeded `desktop-preferences.json`，后续正常写入从默认 `zh-CN` 重建偏好；原截图又使用缓存的 `observedLanguage`，因此不能作为英文当前 locale 证据。本轮移除 seed-delete workaround，保留隔离 seed 让 Desktop 走正常原子偏好写入，并让截图读取 `window.uthcode.readPreference("language")` 与当前可见 Composer textarea 的 locale ARIA（静态 `document.documentElement.lang` 不作为依据）。

- wrapper 用既有 `resolvePath` 规范化 `workspaceRoot`，去除末尾反斜杠；现有 `--request-timeout-ms` 透传保留默认 `5000`，本轮标准包验收显式使用 `10000`，全局 deadline 仍为 `120000`。
- `submitStatusCommand` 在选择候选后等待 textarea 为 `/status` 且真实 `.composer-send` 可用，再点击既有 Send；UI Model 保持显示名 `CDP fixture`，另用本次 `/status` 的安全 `requestRuntime("status.get", {})` 断言 wire `provider_profile=fixture`、`current_model=fixture/fixture-model`。forbidden marker 仅扫描本次 timeline notice 与 `.runtime-facts` label/value，不扫描整页历史正文。
- 当前标准包 `desktop/out/UthCode-win32-x64/UthCode.exe` 的既有入口、显式 `UTHCODE_PYTHON=C:\Users\93445\miniconda3\envs\re-uthcode\python.exe` 和 `--request-timeout-ms 10000` 运行结果如下：

| flow/language | report | runId | result | locale evidence |
| --- | --- | --- | --- | --- |
| stream/en | [`acceptance-report.json`](../../../../desktop/out/f03-w07-cdp-round3-en-stream-locale-dom/acceptance-report.json) | `730b8b96-3485-4e43-84d0-fec6476f79eb` | exit 0；fixture request `1`；driver/electron `0` | requested `en`、preference `en`、main UI `en`；`Runtime information` / `CDP fixture` / `fixture/fixture-model` |
| stream/zh | [`acceptance-report.json`](../../../../desktop/out/f03-w07-cdp-round3-zh-stream-locale-dom/acceptance-report.json) | `563cd2aa-1c72-4827-a98c-308e3048efc7` | exit 0；fixture request `1`；driver/electron `0` | requested `zh`、preference `zh-CN`、main UI `zh-CN`；`运行时信息` / `CDP fixture` / `fixture/fixture-model` |
| visual/en | [`acceptance-report.json`](../../../../desktop/out/f03-w07-cdp-round3-en-visual-locale-dom/acceptance-report.json) | `c19c9300-51f4-4149-b951-f3867914bdbf` | exit 0；6 screenshots；console/renderer errors `0` | all 6 screenshots preference/current UI `en` |
| visual/zh | [`acceptance-report.json`](../../../../desktop/out/f03-w07-cdp-round3-zh-visual-locale-dom/acceptance-report.json) | `876c7e4b-d771-490c-a3e6-2aa001e10e3c` | exit 0；6 screenshots；console/renderer errors `0` | all 6 screenshots preference/current UI `zh-CN` |

Stream 的 `/status` 日志还记录了当前 facts：en `Turn Idle`、`Current Context 5,751 / 128,000 · estimate`、`Last Provider Request Usage Total: 5 · Input: 2 · Output: 3`；zh 为对应本地化字段，数值相同。旧 stream 失败报告未删除或改写；本轮只把当前标准包的 locale-correct、display/wire-separated 结果作为新的验收证据。`npm test` 使用同一显式 Python 环境最终为 `183 passed, 0 failed, 0 skipped`，exit 0；前述标准 `npm run package`/`npm run make` 的 exit 0 结果沿用主控已记录证据。

本轮仍不宣称真实 Provider、native pointer/Windows 原生缩放、干净 Windows、人工视觉或用户实际桌面输入通过；这些 Checklist 项保持未勾。此前 dev probe 的受控 `taskkill`/sandboxed-renderer stderr 与 packaged reload 前 listener 限制均保留在历史段落中，不被本轮 packaged stream/visual 结果覆盖。
