# W04 配置自动保存与设置 — Feedback

## 结果

完成 T11 配置单项写回/安全边界应用及 T12 Settings 自动保存、归档管理。Settings 现按有效字段和 Provider/Model 关联组提交；保存回执、运行时 applied/pending/failed 分开。App 只跨页面保留当前非秘密失败字段，按字段身份和 revision 重试；Provider/Model 草稿与搜索 Key 仍属于受控编辑器生命周期。Settings 内归档按原 Coding 项目及 General 分组，支持项目/文本过滤和恢复。

活动 Turn 的安全边界回归找到一个真实缺陷：消费 Task 在 `finally` 中 drain 时仍被 `wait_for_idle` 的 busy 判定识别为活动任务，导致配置继续 pending 且没有后续 drain。Bridge 现在只在 `_turn_task is asyncio.current_task()` 时解除自己的 Task 身份，再同步应用 pending；运行中的 Turn 仍保持原配置快照，失败和取消也经过同一终态路径。

## 修改文件

- 配置合同和唯一写入路径：`src/uthcode/application/configuration.py`、`src/uthcode/application/bootstrap.py`、`src/uthcode/integrations/config/writer.py`。
- Desktop 持久化/应用状态及安全边界：`src/uthcode/interfaces/desktop/bridge.py`、`desktop/src/desktop-api.ts`。
- Settings 自动保存、局部编辑、归档、失败草稿和生命周期收敛：`desktop/src/renderer/App.tsx`、`SettingsView.tsx`、`SettingsEditorModal.tsx`、`settings-draft.ts`、`state.ts`、`useRuntimeLifecycle.ts`、`app.css`、`locales/en.ts`、`locales/zh-CN.ts`。
- 定向回归：`tests/test_configuration.py`、`tests/test_config_loader_integration.py`、`tests/test_desktop_bridge.py`、`tests/test_w04_review_fixes.py`、`desktop/tests/renderer-settings.test.tsx`、`renderer-runtime-lifecycle.test.tsx`、`renderer.test.tsx`。
- 本文件与 T12 Checklist 的 W04 项。共享工作区中的 `docs/Context-Index.md` 和 W03 Feedback 修改由总控负责，本 Worker 未写入。

## 清理证据

| 路径/符号 | 真实调用者 | 冗余证据 | 删改与回归 | 剩余风险 |
|---|---|---|---|---|
| `desktop/src/renderer/settings-draft.ts` 的 `configurationRequest`、`settingsSaveRequest`、`withoutRecordKey`、`SettingsTheme`、`SettingsLanguage` | 旧 Settings 全量 Save 序列化及单一测试重导出；新 UI 使用字段补丁和 `providerGroupSaveRequest` | `rg` 在 `desktop/src`、`desktop/tests` 中检索这些旧符号无残留；新的 request identity 只用于非秘密字段状态 | 删除旧 helper/type/re-export，改为部分更新；`renderer-settings.test.tsx`、`renderer.test.tsx` 及 typecheck 验证字段保存、关联组和 Secret 投影 | 无已知调用遗漏；实际原生 UI 验收留给后续包级验收 |
| `src/uthcode/integrations/config/writer.py::_write_user_preference` | `write_user_default_model` / `write_user_default_permission_mode`，由 Application bootstrap 的模型和权限 writer 调用 | 这条路径独立解析 TOML 并直接 `_atomic_write`，与 `write_user_config` 重复；调用与导出核对显示两个便捷入口有真实使用方 | 保留便捷入口但改为转交 `{default_model}` / `{default_permission_mode}` 补丁，删除第二套解析/替换实现；默认模型/权限、仅顶层写回及替换失败回归通过 | 便捷函数仍可由既有调用点使用，实际原子替换只有 `write_user_config` |
| `desktop/src/renderer/useRuntimeLifecycle.ts::rebootstrapProject` 与 App 的 Settings 全量保存恢复链 | 唯一生产调用来自旧 `App.saveSettings` | 字段自动保存不再 shutdown/initialize；全仓该 helper 无残留。一般 Session 导航仍由原生命周期拥有 | 删除 helper 和对应旧 restart/save 测试；保留并通过 `ordinary Session navigation keeps lifecycle ownership without presenting a Runtime restart` 与 `renderer-runtime-lifecycle.test.tsx` | 真实 packaged/native lifecycle 未在本 Worker 运行 |
| `desktop/tests/renderer.test.tsx` 中只证明旧全量 Save、Save 锁和 rebootstrap 的用例 | 被替换的 Settings 提交入口 | 这些测试断言已删除的全局提交/Runtime 重启语义 | 换为成功字段提交、迟到/失败 revision、跨 Settings 重试、搜索 Key 清理、Provider 局部失败覆盖；三份 Renderer 套件全通过 | React 测试输出仍有既有 `act(...)` 警告（Archive、SidebarInfo），不影响断言结果 |

配置写入以缺失字段代表未编辑，显式 null profile 代表删除，空 mapping 无变更；`default_model` 仅顶层原子写回。`settings.retry_apply` 只重读并重试运行时应用，不重复 writer 副作用。调用者已核对：唯一 UI RPC 入口为 Bridge `settings.save`，内部唯一文件 writer 为 `write_user_configuration`，Application bootstrap 的调用只更新顶层默认模型。未编辑 literal/`env:` Key 不投影回 Renderer，搜索 Key 和 Provider 组失败不会进入 App 通用非秘密重试队列。

## 验证

使用既有 `re-uthcode` Conda 环境（Python 3.12.13）；Desktop 命令在 `desktop/` 执行。

| 命令 | 结果 |
|---|---|
| `C:\Users\93445\miniconda3\envs\re-uthcode\python.exe -m pytest tests/test_configuration.py tests/test_config_contract.py tests/test_config_loader_integration.py tests/test_application_runtime.py tests/test_desktop_bridge.py tests/test_w04_review_fixes.py -q` | 217 passed in 18.50s |
| `C:\Users\93445\miniconda3\envs\re-uthcode\python.exe -m pytest tests/test_architecture_boundaries.py -q` | 23 passed in 5.03s |
| `npx tsx --test tests/renderer-settings.test.tsx tests/renderer-runtime-lifecycle.test.tsx tests/renderer.test.tsx` | 126 passed, 0 failed in 9.75s |
| `npx tsx --test tests/preload.test.ts` | 17 passed, 0 failed in 0.45s |
| `npm run typecheck` | 通过 |
| `C:\Users\93445\miniconda3\envs\re-uthcode\python.exe -m pytest tests/test_w04_review_fixes.py::test_desktop_settings_save_keeps_active_turn_snapshot_then_applies_at_idle -q` | 1 passed in 1.09s |
| `npx tsx --test --test-name-pattern='T12 failed Search key' tests/renderer.test.tsx` | 1 passed, 0 failed |
| `git diff --check` | 通过；Git 仅提示仓库配置会在后续 Git 操作时将工作副本 LF 转为 CRLF |

原生 Electron 窗口、打包/bundled Runtime、真实 Provider 请求未验证；没有启动或关闭用户 App，也未执行 package/make。事实文档的包级同步交 W05。未新增生产文件。未跟踪的 `test-file.md` 保持原状。

## Checklist

已勾选 T11 三项和 T12 三项。对应自动化覆盖配置读写/秘密投影、Turn/Compact/Process 与 General 生命周期、Settings 字段状态/失败重试/Secret 编辑器、归档筛选恢复和 Recent/搜索 owner 行为；未把原生、打包或真实 Provider 验收宣称为已完成。

UTF-8 guard:
- files checked: `docs/work/T12-Desktop功能补齐与工程收敛/T12-Desktop功能补齐与工程收敛-checklist.md`, `docs/work/T12-Desktop功能补齐与工程收敛/W04-配置自动保存与设置-feedback.md`
- result: `check_utf8_docs.py` passed both files (UTF-8, mojibake markers, Markdown fence parity)
- repaired encoding issues: none

## Reviewer 修复轮次（2026-10-11）

同一 Reviewer 发现的四项缺口已按当前合同修复：

1. Bridge 安全边界 drain 现在只对显式 `pending` / `failed` 的已加载 Application 重读配置；普通 Turn 终态 `current=None` 不触发配置 reload 或 Permission 重置。新增真实 Turn 成功、Provider 失败和 cancel 回归：不发生 Settings 写入时，外部磁盘 Provider 变更不被读入，`FULL_ACCESS` 与运行时 Provider 保持不变，也不发布 Settings 应用事件。
2. Provider/Model modal 的 Apply 接收保存返回的安全配置投影，局部并入仍等于已提交草稿的关联字段并更新 `api_key_configured` 标记，不复制或展示 Key 值；其他仍未提交的草稿不会被安全回读覆盖。现有 Provider Apply UI 回归覆盖真实 modal Apply、Provider/Model 事实和 Key 标记。
3. Turn/Compact 的终态先于 Bridge 的 pending drain 发布。Drain 后，唯一现有 AgentEvent Envelope 通知只携带 `applied/pending/failed` 计数；App 严格验证计数并更新当前 Settings 投影，未增加配置副本或写入入口，旧 API generation 的迟到回调仍被隔离。新 Bridge 回归覆盖跨项目后台 Turn 的应用成功/失败，以及跨项目后台 Compact 的 no-change 完成和失败，断言终态事件先发、drain 计数随后到达；Compact 自身失败不误报为配置应用失败。
4. Settings 依参考五类将 Provider/默认模型、About、搜索与工具限制、权限、主题与语言分别归位；页面标题跟随所选分类。Settings 内保留单独可发现的 Archive 第六页，按现有 Coding 项目/General 分组并可过滤/恢复；不在侧栏增加全局 Archive 项。

修复轮次验证（既有 `re-uthcode` Conda 环境，Python 3.12.13）：

| 命令 | 结果 |
|---|---|
| `python -m pytest tests/test_w04_review_fixes.py -k 'turn_terminal_without_configuration_patch or cross_project_background_turn_publishes or compaction_terminal_publishes' -q` | 7 passed, 10 deselected |
| `python -m pytest tests/test_configuration.py tests/test_config_contract.py tests/test_config_loader_integration.py tests/test_application_runtime.py tests/test_desktop_bridge.py tests/test_w04_review_fixes.py -q` | 224 passed in 15.00s |
| `python -m pytest tests/test_architecture_boundaries.py -q` | 23 passed in 4.24s |
| `npx tsx --test tests/renderer-settings.test.tsx tests/renderer-runtime-lifecycle.test.tsx tests/renderer.test.tsx` | 129 passed, 0 failed in 21.61s |
| `npm run typecheck` | 通过，退出码 0 |

首轮验证期间暴露一处 cancel 测试 Provider 没有响应 cancellation 的夹具缺陷、两处新增 Renderer 断言问题，以及 Compact 失败与配置应用状态被错误耦合的测试预期；均已最小修正并由最终完整定向套件覆盖。最终 Renderer 测试输出仍有既有 React `act(...)` 提示，129 项断言通过。

此轮未执行原生窗口、真实 Provider 请求或 packaged Desktop；未执行 package/make，未启动/关闭用户 App，未做 Git 写入。Checklist 原有标记未改；当前新增证据补齐了真实跨项目后台 Turn 与后台 Compact 终态路径。包级事实文档同步仍由 W05 处理。

## Reviewer 补充验证（2026-10-11）

继续按 Reviewer 要求补齐真实配置应用失败矩阵。上一轮 7 项及其后的 224 项 Python 结果覆盖了跨项目后台 Turn 的 reload 失败，但 Compact 失败只证明配置应用仍成功；它们没有覆盖 Compact 边界上真实 `reload_configuration` 失败。此次对真实前台活动 Turn 增加 reload 成功/失败两个分支，对跨项目后台 Compact 把 Compact operation 成功/失败与 Application reload 成功/失败组成独立 2×2。因而 Compact operation `failed` 且设置应用 `applied`，以及 Compact operation `no_change` 且设置应用 `failed` 都分别有真实 Bridge/Configuration 状态流证据；事件计数没有把两种失败混同。

最终状态流回归命令：

| 命令 | 结果 |
|---|---|
| `python -m pytest tests/test_w04_review_fixes.py -k 'keeps_active_turn_snapshot_then_applies_at_idle or cross_project_background_turn_publishes or compaction_terminal_publishes or turn_terminal_without_configuration_patch' -vv -q` | 11 passed, 9 deselected |
| `python -m pytest tests/test_configuration.py tests/test_config_contract.py tests/test_config_loader_integration.py tests/test_application_runtime.py tests/test_desktop_bridge.py tests/test_w04_review_fixes.py -q` | 227 passed in 15.83s |
| `python -m pytest tests/test_architecture_boundaries.py -q` | 23 passed in 4.44s |

偏好边界复核：`App.tsx` 的 `setTheme` 只 dispatch `set_theme` 并写 Desktop `theme` preference；`setLanguage` 只 dispatch `hydrate_preferences({language})` 并写 Desktop `language` preference。Reducer 对偏好使用 state spread，只更新 theme/language，不写配置、不调用 Runtime reload；当前 Session 的 `currentModelRef` 和 `permissionMode` 不被偏好更新覆盖。Renderer 全套最终仍为 129 passed，`npm run typecheck` 退出码 0；两项源文件自该结果后未再改动。

本轮没有修改 Worker Checklist 标记或其它包文档。

## Reviewer 修复轮次 2（2026-10-11）

同一 Reviewer 复审只剩一个 P2：普通 owner 终态会在检查配置应用意图之前先判断其他 Application 是否 busy；没有 Settings 写入、该 owner 也没有 `pending`/`failed` 状态时，仍会把另一个活动 owner 错误标为 `pending`，其后续终态因此无依据地 reload 配置并重设显式 Permission。

最小修复将普通 drain 的 `pending`/`failed` 筛选提前到 busy 判定之前。非 force、非 retry 调用只 drain 真实待应用 owner；显式 `force_all` 与 `retry_failed` 的既有写后应用和失败重试行为不变。新增两项真实跨项目状态流回归：Project A 的 Turn 与 Project B 的 Compact 同时运行，不调用 `settings.save`，仅由磁盘外部变更 Provider 配置使误 reload 可观察；分别以 Turn、Compact 先结束。两种顺序都断言首次及最终 drain 的状态表仍为空、无配置 reload、Provider 配置与两边 `FULL_ACCESS` 不变且无 `settings_applications` 通知。既有成功写入后 pending→applied/failed、retry 和 Turn/Compact reload 失败矩阵继续覆盖。

本轮验证使用既有 `re-uthcode` Conda 环境（Python 3.12.13）：

| 命令 | 结果 |
|---|---|
| `& 'C:\Users\93445\miniconda3\envs\re-uthcode\python.exe' -m pytest tests/test_w04_review_fixes.py::test_owner_terminal_drains_without_save_do_not_create_cross_owner_pending -vv -q` | 2 passed in 0.95s |
| `& 'C:\Users\93445\miniconda3\envs\re-uthcode\python.exe' -m pytest tests/test_w04_review_fixes.py -k 'settings_save_keeps_active_turn_snapshot_then_applies_at_idle or turn_terminal_without_configuration_patch or cross_project_background_turn_publishes or compaction_terminal_publishes or owner_terminal_drains_without_save' -vv -q` | 13 passed, 9 deselected in 2.97s |
| `& 'C:\Users\93445\miniconda3\envs\re-uthcode\python.exe' -m pytest tests/test_configuration.py tests/test_config_contract.py tests/test_config_loader_integration.py tests/test_application_runtime.py tests/test_desktop_bridge.py tests/test_w04_review_fixes.py -q` | 229 passed in 14.95s |
| `& 'C:\Users\93445\miniconda3\envs\re-uthcode\python.exe' 'C:\Users\93445\.codex\skills\uth-utf8-guard\scripts\check_utf8_docs.py' 'docs/work/T12-Desktop功能补齐与工程收敛/W04-配置自动保存与设置-feedback.md'` | `OK: 1 file(s) passed UTF-8 guard` |

Bridge 修改没有改变模块依赖边界，复用本轮前有效架构检查 `tests/test_architecture_boundaries.py`：23 passed in 4.44s。未改 Renderer；复用最新独立 Renderer 129 passed 与 `npm run typecheck` 退出码 0。未重复执行这三项。未执行真实 Provider、原生或 packaged 验收；未执行 package/make，未启动或关闭用户 App，未做 Git 写入；未改冻结 Checklist，`test-file.md` 保持不动。包级事实文档同步仍交 W05。

文档与补丁检查：上述 UTF-8 guard 实际执行结果为 `OK: 1 file(s) passed UTF-8 guard`；`git diff --check` 退出码 0，仅输出工作副本 LF 后续转换 CRLF 的仓库提示，无空白错误。

## 总控独立复审收口（2026-10-11）

同一 Reviewer（gpt-6.1-sol / medium）最终 PASS。首轮四项 P2 与第二轮多 owner 无 Save drain 的一项残留 P2，共五项均由原 Worker（gpt-6-luna / max）关闭，无新增 actionable finding。Reviewer 独立内存复现后台 Turn/Compact 两种 busy 条件，前后台先后 drain 均保持 reloads=0、FULL_ACCESS、不含应用状态和通知；新增真实跨项目 Turn+Compact 双终态顺序通过，合法保存、应用失败与 retry_apply 保持。

最终独立命令：`python -m pytest tests/test_w04_review_fixes.py -k 'settings_save_keeps_active_turn_snapshot_then_applies_at_idle or turn_terminal_without_configuration_patch or cross_project_background_turn_publishes or compaction_terminal_publishes or owner_terminal_drains_without_save or settings_retry_apply' -q`，结果 14 passed、8 deselected、2.53s，退出码 0。内存复现与 git diff --check 退出码 0；复用上一轮独立 Renderer 129 passed、typecheck 通过和架构 23 passed 有效证据。Worker 最终六文件 Python 回归为 229 passed，未冒称本轮重新执行 Renderer 或架构。

T11/T12 六项复合条件已有对应源码与自动化证据；冻结 Checklist 只增加六个完成标记，九份冻结文档正文核对未变，既有 Feedback 按轮次追加。用户 test-file.md 保留且排除提交。packaged/native/真实 Provider 与全包长期事实文档仍交 W05，包状态保持 not_implemented，不自行归档。用户已明确取消 UI 验收暂停，审核与 Git 后直接继续 W05。

## 总控 Git 交付与 W05 交接（2026-10-11）

W04 提交 `1d52d93a6c5e9035dea61df3bdf563b6e33c7e4d`（feat(desktop): autosave settings at safe runtime boundaries），精确 25 文件，包含本轮源码/测试/反馈、六个 Checklist 勾选与总控 W03 PR131 收口、索引更新，未提交用户 test-file.md。PR [#132](https://github.com/undertaker33/Re-UthCode/pull/132) 经 head/files/mergeable 核对，以匹配该 head 的 merge 于 2026-10-11T11:00:46Z 合并，merge `46d3c0d4808aab63c98df0de257833bf20b3eb9f`。

SSH 临时 URL 改写仅用于 fetch/push，HTTPS origin 保持不变。merge 后本地 T11、远端 T11、GitHub main 与 PR merge 均一致；`git diff 1d52d93 HEAD -- src desktop` 无差异，已审核输入未变，tracked 工作区当时干净，仅 test-file.md 未跟踪。此追加 Git 记录和后续索引交接将随下一个必要 W05 提交纳入，不额外拆碎提交。按用户持续授权直接派发 W05，真实 packaged/native/Provider 与包级文档验收仍不能提前视为完成。
