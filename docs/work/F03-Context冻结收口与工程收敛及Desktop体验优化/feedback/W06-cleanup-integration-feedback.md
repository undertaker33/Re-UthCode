# W06 cleanup/integration feedback

## 结论

W06 按 T06 → T07 完成了最小清理与生产链集成收口。没有执行 Git 写操作、归档或修改冻结正文；`.workbuddy/` 与 `临时目录/` 保持原状。T06 全部 Checklist 项和 T07 的自动化/静态证据项已勾选；真实 Desktop dev shell 只完成 shell smoke，未冒充完整 identity 主链，因此对应项保持未勾选。T08/T09 全部保持未勾选。

## T06：实际清理

- 删除无语义 wrapper：`src/uthcode/application/history.py` 已删除。
- `src/uthcode/application/context.py`、`src/uthcode/application/generation.py` 与 `eval/workloads.py` 直接导入并调用 `uthcode.core.history.transcript_entries_from_message`；相关测试也已迁移到 Core 转换函数。
- 定向扫描

  ```text
  rg -n -S "uthcode\.application\.history|application/history|_transcript_entries_for_message|ContextCompactor\.compact|_compact_locked" src tests eval desktop/src desktop/tests
  -> 0 matches
  ```

- 未删除或拆分 Agent Loop、Session durability、Provider factory/fake、Permission、Secret、Hard Gate、TUI/CLI、pause/resume/cancel 或 legacy durable reader。没有新增 facade、alias、Manager、EventBus 或 placeholder。
- T07 集成缺口仅修正 `src/uthcode/application/compaction.py` 的 compactor system prompt：明确要求每个 entry 原样携带 Required coverage 的 exact refs，和 W01 的严格 multi-turn parser/coverage contract 对齐；没有改变 compaction authority、single-flight、Hard Gate 或 durable append 语义。
- `tests/test_w04_session_commands.py` 的旧 fixture 补齐 exact refs，并将 compact history 改为足够长的 prospective ordinary request；compact 后断言 `Current Context` 仍可用且为 estimate，`last_provider_request_usage.status` 独立为 `not_available`。这是 stale fixture/断言修正，不是以 unavailable 掩盖应有投影。

## T07：集成证据

Core/Application context contract 与真实入口回归覆盖 ordinary、manual `/compact`、auto pressure、overflow recovery、L4 oversized、L5 aging，以及 no-reduction、malformed、failure、cancel、invalid candidate、Hard-unsafe gate。有效 candidate 后 Timeline、Current Context 和 Last Provider Request Usage 仍由各自权威更新；tool-free compaction request 先过既有 Hard Gate。

实际命令与结果：

```text
conda run --no-capture-output -n re-uthcode python -m pytest tests/test_context_compaction.py tests/test_t09_1_context_protocol_e2e.py -q
-> 49 passed in 12.03s, exit code 0

conda run --no-capture-output -n re-uthcode python -m pytest tests/test_desktop_bridge.py -q
-> 66 passed in 5.24s, exit code 0

conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q
-> 23 passed in 5.17s, exit code 0

conda run --no-capture-output -n re-uthcode python -m pytest tests/test_agent_loop.py tests/test_agent_interaction.py tests/test_agent_policy.py tests/test_application.py tests/test_application_runs.py tests/test_application_runtime.py tests/test_cli.py tests/test_config_loader_integration.py tests/test_configuration.py tests/test_permission.py tests/test_permission_integration.py tests/test_permission_delivery.py tests/test_provider_contract.py tests/test_provider_factory.py tests/test_session_files.py tests/test_tui.py tests/test_tool_result_persistence.py tests/test_history_contract.py tests/test_history_read_tool.py -q
-> 580 passed in 43.39s, exit code 0

conda run --no-capture-output -n re-uthcode python -m pytest tests/test_history_contract.py tests/test_history_read_tool.py tests/test_context_compiler.py tests/test_session_authority.py tests/test_w04_session_commands.py tests/test_w05_diagnostics.py tests/test_t09_1_context_protocol_e2e.py tests/test_w06_integration_delivery.py -q
-> 135 passed in 24.38s, exit code 0
```

上述是本轮实际执行的完整文件集合与命令；结果未省略失败项。该集合覆盖 Agent Loop/Application/CLI/TUI、Permission/Secret/Hard Gate、Provider protocol/factory、Session files/durability、history contract/read tool 和 W04/W05/T09/W06 contracts。

Desktop 结果：

```text
cd desktop
npm run typecheck
-> exit code 0

npm test
-> 首次 179 pass, 1 fail；唯一失败是 npm shell 未提供 UTHCODE_PYTHON/CONDA discovery，offline Desktop Runtime 无法定位 re-uthcode executable。

$env:UTHCODE_PYTHON='C:\Users\93445\miniconda3\envs\re-uthcode\python.exe'; npm test
-> 180 pass, 0 fail, 0 skipped，exit code 0
```

Architecture test 同时验证 import boundary；没有发现 Interface → Core/Integration 越权或 Provider SDK 类型穿透。Desktop Bridge/runtime、Session background/rebootstrap、clipboard、layout/Focus/scroll/status、renderer owner/reducer 与 settings 生命周期由正式 `npm test` 及 Bridge 文件回归覆盖。

## 真实 dev shell smoke 边界

按既有 runner 执行了最小 dev shell 启动和 shell flow：

```text
conda run --no-capture-output -n re-uthcode npx electron-forge start --enable-logging -- --remote-debugging-port=9239 --disable-gpu

conda run --no-capture-output -n re-uthcode node scripts/cdp-launcher.mjs -- node scripts/cdp-driver.mjs --port 9239 --flow shell --timeout-ms 30000 --request-timeout-ms 5000
-> target http://localhost:3000/main_window/index.html；UthCode shell、Composer、Runtime ready、Renderer ready、closeShell、driver_complete 均通过，driver exit code 0。
```

该 flow 没有执行 Provider、Session、Settings 或 command dispatch，不能证明完整 `Renderer → DesktopApi → Main/Preload → DesktopBridge → Application → Core` request/Run/Turn identity、事件顺序和 terminal convergence；dev Electron 启动使用当前主机 profile，driver 本身由既有 isolated launcher 运行。未将此 shell smoke 写成完整链路证据，T07 对应 Checklist 项保持 `[ ]`。没有主动执行会话设置、Provider 写入或 secret reveal；profile/config 写入边界未达到完整验收标准，留给后续有隔离 profile 的 acceptance。

## 未完成项、限制与清理

- 未运行 F03 T08/T09；未运行 Python 全量 `pytest -q`、`compileall`、`pip check`、package/make 或全量 packaged/CDP/visual matrix。
- W05 已明确的 CDP `mouseMoved` timeout（Emulation 前也存在）、native resize/真正 Windows zoom，以及 Provider available usage packagedE2E 限制保持原样，属于 W07/环境验收边界，不在 W06 无限排查。
- 本轮未合并或删除重复测试；已有高价值 contract 数量未下降。没有新增能力欠账，未修改 `docs/OutstandingDebtList.md`、Context Index 或任何冻结 Spec/Tasks/Prompt 文本。
- 文档只新增本 Feedback 并更新 Checklist 既有 T06/T07 复选框；没有改编号、顺序或正文。未执行 commit、push、merge、rebase、tag、release 或归档。
