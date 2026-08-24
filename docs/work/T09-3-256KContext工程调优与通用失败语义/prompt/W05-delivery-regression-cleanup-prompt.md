# W05 主链接入、交付验收与清理提示词

请在 W01～W04 全部完成并通过审查后，严格按 T06 -> T07 -> T08 串行完成唯一主链接入、全链路离线验收、文档同步、遗留负担清理和最终索引更新。

## 开工前必须读取

1. `AGENTS.md`
2. `docs/README.md`、`docs/Context-Index.md`
3. `docs/rules/WorkPackageRules.md`、`docs/rules/UserDecisionBoundary.md`
4. `docs/OutstandingDebtList.md`
5. T09-3 原始任务书、Spec、Tasks、Checklist和全部 W01～W04 Feedback
6. A01～A04 命中的当前 Context与 TUI README
7. `docs/README.md` 维护映射命中的用户手册、Core Design、Tools和根 README
8. T06～T08 Tasks定位的 Application/Interface/Eval/测试与最新 `src/ + tests/`
9. 开工时 `git status --short`，特别记录用户既有 `docs/core-design/T09-context-engineering.md` 删除与 `临时目录/`

## 已确认决策

- 唯一正式链为 `create_application -> create_run -> start_turn -> AgentLoop`；Interface只通过 Application消费。
- configured/provider/default provenance、256K profile、High->Low、cache usage和 failure projection必须进入同一正式链，不保留双轨。
- Application唯一拥有用户失败文案；TUI/CLI/Headless不自行分类 Provider/Context错误。
- live Provider/cache/latency/billing没有单独授权时保持未验证，不读取 key、不访问网络。
- 能力欠账为“无”；Out of Scope和未授权 live项不得登记为欠账。
- 不恢复用户开工前删除的文档、不清理用户 `临时目录/`，不修改 T09/T09-1/T09-2冻结工作包。
- 不自动归档，不执行 commit、push、merge、rebase、tag或 release。

## 修改范围

- T06～T08 Tasks列出的 Application/bootstrap/status、CLI/TUI展示、tests/eval和验收必要修正。
- `docs/Context-Index.md`、A03/A04与 `docs/README.md`维护映射实际命中的当前文档。
- 首次实施创建 `feedback/W05-delivery-regression-cleanup-feedback.md`；返工只追加。
- 只勾选 T06～T08，以及复核前序已完成项；不得修改 Checklist文案。

禁止新增功能、调整冻结产品语义、扩大为安全审计、建立 Manager/Registry/FSM/兼容层或执行 Git写操作。

## 实施约束

1. 使用 Conda环境 `re-uthcode`；先收口正式调用方，再做端到端验收，最后清理，顺序不得颠倒。
2. status/diagnostics只投影安全机器事实和 Application文案，不含正文、summary、Tool Result、secret、raw body、traceback或 SDK对象。
3. Interface源码不得导入 Core/Integration/SDK做 failure/cache/context分类；同一 reason跨 TUI/CLI/Headless语义一致。
4. 验收发现普通局部缺陷可在当前范围修复；若触发任务书 Coding停止条件或新的长期公共决策，停止相关范围并在 Feedback记录交由用户。
5. 文档只描述最终 `src/ + tests/`事实；尊重用户已有 dirty worktree，不用恢复/覆盖来“补齐”维护映射。
6. 使用 `uth-utf8-guard`检查所有本包修改 Markdown；中文保持 UTF-8，fence成对。
7. 只有所有 Checklist与 Feedback有真实证据后，才把 T09-3标为 `implemented_unarchived`。

## 测试与验收

按风险递增至少执行：

```powershell
conda run --no-capture-output -n re-uthcode python -m pytest tests/test_context_budget_gate.py tests/test_context_compaction.py tests/test_t09_1_context_protocol_e2e.py tests/test_application_runs.py tests/test_w05_diagnostics.py -q
conda run --no-capture-output -n re-uthcode python -m pytest tests/test_openai_responses_integration.py tests/test_anthropic_integration.py tests/test_openai_compat_integration.py tests/test_agent_events.py tests/test_agent_loop.py tests/test_cli.py tests/test_tui.py -q
conda run --no-capture-output -n re-uthcode python -m pytest tests/eval -q
conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q
conda run --no-capture-output -n re-uthcode python -m pytest -q
conda run --no-capture-output -n re-uthcode python -m compileall -q src tests eval
conda run --no-capture-output -n re-uthcode python -m pip check
git diff --check
```

另从正式 Headless/Application与 `python -m eval.runner`入口执行 Checklist要求的离线 E2E、candidate compare、help/smoke/clean拒绝，并运行所有否定扫描。live项未授权时不得运行。

## 文档与 UTF-8 验收

- 更新 A03/A04、Context Index与实际命中文档；不把规划或 live未验证写成事实。
- 对 T09-3工作包、Context Index、A03/A04和实际修改 Markdown运行 `uth-utf8-guard` bundled checker。
- 校验内部链接、replacement character、常见 mojibake、fence parity和示例 secret。

## Feedback 要求

Feedback必须面向人工审查说明唯一调用链、跨 Interface投影、E2E矩阵、Eval最终报告、修改/删除/保留文件、所有精确命令与结果、Checklist证据、文档同步、live未验证项、用户既有 dirty files保护、能力欠账核对、否定扫描、风险和遗留问题。不得复制秘密、大型日志或重写前序 Feedback。

## 冻结决策覆盖

- 最终逐项证明 D-T09-3-01～08 均有 Spec -> Task -> Worker Prompt -> Checklist -> Feedback -> test/eval证据；任一缺失都不得更新为 implemented_unarchived。
