# W01：Context Profile 与 Low Water Feedback

## 交付结论

W01 已严格按 T01 -> T02 完成：统一 resolver 现在支持 configured、reliable Provider ceiling 与 UthCode default `256_000`，保留可观察 provenance，并按 Active Turn 冻结；Auto L4 在 High/Hard 触发后持续追到 frozen `retained_target`，不再刚低于 High Water 即停止。T03 及后续任务未实施，未执行 Git 写入或工作包归档。

## Resolver 真值表与 provenance

| configured | Provider ceiling | effective | active source | actually tightened |
| --- | --- | --- | --- | --- |
| 缺失 | 缺失 | `256_000` | `default` | 无 |
| 缺失 | `128_000` | `128_000` | `provider` | `provider` |
| 缺失 | `512_000` | `256_000` | `default` | `default` |
| `300_000` | 缺失 | `300_000` | `configured` | 无 |
| `300_000` | `400_000` | `300_000` | `configured` | 无 |
| `300_000` | `200_000` | `200_000` | `provider` | `provider` |

`ContextBudget` 分开投影 raw configured/provider/default 值、`observed_input_sources`、`effective_input_source` 与 `tightened_input_sources`。configured 存在时 default 不参与收紧，因此显式值可以高于 256K；default 是 UthCode Operating Window，不写入 `ModelLimits`，也不伪装成 Provider metadata。input、known output、known combined 的 Hard Gate 仍分维判断，unknown 维度保持 unknown。

三类真实 caller 均复用 `resolve_context_budget`：

1. Active Turn 的 request preparation 首次消费时解析一次 Provider limits，并把 budget/provenance 冻结在 Turn closure；同 Turn 多 iteration 复用，下一 Turn 重新解析。模型切换仍只影响下一 Turn。
2. idle `compact_session()` 使用同一 resolver；default-only 的空候选 manual compact 是成功 no-op。
3. `ApplicationContextService.compose_generation_request()` 在未传入已解析 budget 时统一走 resolver，包括 individual limits 全缺失的 default-only 路径；provider-independent `compile()` 仍允许无 budget。

Application diagnostics、Headless request metadata 与 `/status` 现在都能观察 configured/provider/default、effective、observed、active source 与 tightened sources，不包含正文、secret 或 Provider native object。

## ContextBudget caller audit 与清理

- `active_evidence_budget`、`uncompressed_tail_budget`、`retained_hard_cap` 在开工 HEAD 仅有字段、派生、校验、序列化或测试断言，没有生产行为消费者，已连同这些残留删除。
- `fine_timeline_budget` 由 `run_l5_if_needed()` 的 Timeline aging 真实消费，保留。
- `retained_target` 现在由已启动 Auto L4 的 rebuild/recount stop condition 真实消费，保留。
- 为避免 W01 越权替 T05 定案，当前只在删除无消费者 subdivision 后保持既有 retained-target 派生结果；没有新增 profile registry、产品配置项或公共 tuning API。

指定扫描：

```text
rg -n "active_evidence_budget|uncompressed_tail_budget|retained_hard_cap" src tests eval docs/context docs/Context-Index.md
0 matches

rg -n "ContextPolicyRegistry|ContextManager|CompactManager|CompactionJob|CompactionScheduler|next_epoch_pointer|COMPACTING_BATCH" src tests
0 matches
```

型号扫描命中了既有 `model_catalog()`：`application/configuration.py`、`application/generation.py`、commands、TUI 及其测试。它只枚举用户已配置的模型候选，未保存或猜测 context window，也没有 `model name -> limit` authority；本次未修改其职责。

## High Water -> Low Water 调用流

Auto L4 仍只由 initial `auto_pressure || !hard_safe` 启动。启动后每个成功 epoch 继续复用现有 derive -> tool-free compact request -> Hard Gate -> validate -> checkpoint-last commit -> authoritative rebuild 流程；rebuild 对候选重新 count，读取该次 `preflight_input_usage`，并与同一 frozen budget 的 `retained_target` 比较：

```text
usage > retained_target  -> 继续下一 epoch
usage <= retained_target -> Low Water reached，停止
```

显式回归固定了：初始请求触发；epoch 1 后已低于 High 但仍高于 Low，继续；epoch 2 到 Low，停止；两次 Provider compact call、两次 commit 和最终 preflight 均可观察。未触发 Auto 时，即使 usage 高于 Low，也不会主动 compact。

有限停止与原语义保持：max epochs、no progress、no safe epoch、failure、cancel 仍由现有 bounded loop 结束；已有成功 commit 后即使最终未完全追到 Low，也会重建 authoritative request，并由最终 Hard Gate 决定是否可发送，不复用触发前的 stale request。

三类入口差异保持不变：

- Auto：High/Hard 启动，启动后追 Low。
- Manual：不依赖 High，固定一次尝试；无 candidate/no reduction 为成功 no-op。
- Overflow：forced reduction，固定一次 L4 recovery；Core exactly-one retry guard 不变。
- L5：继续独立按 `fine_timeline_budget` aging，不参与 Low Water 判定。

## 修改文件

- 生产：`src/uthcode/core/context.py`；`src/uthcode/application/context.py`、`generation.py`、`commands/builtins.py`。
- 测试：`tests/test_context_budget_gate.py`、`tests/test_application_runs.py`、`tests/test_t09_1_context_protocol_e2e.py`。
- 治理：本 Feedback；T09-3 Checklist 只将 T01/T02 已验证复选框改为 `[x]`。

## 验证结果

全部命令在 `D:\project\Re-UthCode` 使用 Conda `re-uthcode`，Provider 均为 fake/test double，无网络和真实 secret：

```text
conda run --no-capture-output -n re-uthcode python -m pytest tests/test_context_budget_gate.py tests/test_application_runs.py tests/test_w05_diagnostics.py tests/test_t09_1_context_protocol_e2e.py -q
103 passed in 15.86s

conda run --no-capture-output -n re-uthcode python -m pytest tests/test_context_budget_gate.py tests/test_context_compaction.py tests/test_t09_1_context_protocol_e2e.py tests/test_application_runs.py -q
100 passed in 11.89s

conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q
23 passed in 4.28s

conda run --no-capture-output -n re-uthcode python -m pytest tests/test_w04_session_commands.py tests/test_application_runtime.py -q
13 passed in 6.97s

git diff --check
exit code 0；只有既有 LF/CRLF 转换提示，无 whitespace error
```

## Checklist 与冻结决策映射

- D-T09-3-01：default `256_000`、小 ceiling 收紧、大 ceiling default cap 与 configured >256K 均有真值表/正式链测试。
- D-T09-3-02：三来源 raw/observed/active/tightened provenance、三类 caller、Active Turn freeze 与 next-Turn refresh 已覆盖。
- D-T09-3-03：现有 input/output/combined 分维 Gate 与 unknown 回归包含在 T01 定向集合。
- D-T09-3-04：无 bundled limit catalog 或型号猜测；既有 `model_catalog()` 命中仅为用户配置候选列表。
- D-T09-3-05：显式 two-epoch High->Low 正式链与“Low 不主动触发”测试已覆盖。
- D-T09-3-06：W01 只建立可调参数的真实消费者并保持既有初值；至少三候选 Eval 与最终 profile 选择属于未派发 T05，未写成通过。
- D-T09-3-08：T01/T02 的 Spec -> Tasks -> W01 Prompt -> Checklist -> 本 Feedback 可追踪；其它 Task 未勾选。

## 差异、未完成项与风险

- 当前 HEAD 与任务书基线 Commit `958c699fa1cd58c49154928655a3e655e9388291` 一致，未发现需要修改冻结设计或扩大范围的任务书差异。
- T03 Provider cache hints、T04 FailureReason、T05 profile Eval 调优及后续接入/包级验收均未实施。
- 未运行全量 pytest、compileall、pip check 或真实 Provider；它们不属于 W01 最低命令，不能据此声明整个 T09-3 完成。
- 未对用户开工前已有的 `docs/Context-Index.md` 修改、`docs/core-design/T09-context-engineering.md` 删除、T09-3/`临时目录/` 未跟踪内容执行清理或恢复；工作期间另出现的 Core Design 文档/图片也未触碰。
- 未执行 commit、push、merge、rebase、tag、release 或归档。

## 返工第一轮

### 返工原因与关闭结论

本轮只返工 W01 的 T01/T02。验收指出五个证据缺口，其中前四项涉及生产行为，provenance 项只补公开投影合同：

1. `ContextBudget` 曾允许 `retained_target == auto_gate_limit`，小 effective limit 的默认派生也可能让 High/Low 退化为同一值。现在默认 Low 在既有派生公式上额外受 `auto_gate_limit - 1` 约束，显式 equality 由合同拒绝；没有扩大最小窗口、增加 Profile Registry 或公共 tuning 配置。
2. 同一 epoch 第一次 summary/parse 失败、第二次成功时，旧 `last_failure` 曾污染最终成功结果。现在合法 candidate 建立后清除该 epoch 的瞬时失败；后续 no-reduction、no-progress、no-safe-epoch、commit failure、cancel、repeated failure 与 epoch limit 仍分别写入真实终止原因。
3. Auto L4 成功 epoch 后已经取得 Provider 精确 count，但最终 diagnostics 曾重新用本地估算 Gate 覆盖该结论。现在保留最后一次 authoritative rebuild Gate 与 Low Water decision；Provider exact Low 优先于本地 pressure 的伪 unresolved，最终普通请求仍通过原有 count/rebuild/final Hard Gate 流程重新计数。
4. 补齐真正持续到 `epoch_limit_reached`、成功 checkpoint 后 no-safe partial success、hard-safe 继续与 hard-unsafe fail closed 的正式回归。最后真实 checkpoint 保留，未压缩的下一 Turn 没有伪记录，diagnostics 保留真实 breaker reason。
5. provenance 公开投影增加对象值、`to_dict()`、`/status` 与 JSON-safe diagnostics 的精确断言；正文标记、Provider secret 和 Provider native object 均不会进入公开 diagnostics。

### 实际修改

- `src/uthcode/core/context.py`：严格化 High/Low 合同与小窗口默认派生。
- `src/uthcode/application/context.py`：合法 retry candidate 建立后清除当前 epoch 的瞬时失败。
- `src/uthcode/application/generation.py`：复用 authoritative rebuild Gate/Low decision 生成最终 compaction diagnostics。
- `tests/test_context_budget_gate.py`：equality rejection、小 effective limit、observed provenance 对象/序列化合同。
- `tests/test_context_compaction.py`：first-invalid -> second-success 与真实 epoch-limit/checkpoint 合同。
- `tests/test_t09_1_context_protocol_e2e.py`：Overflow 成功重试、Provider/local divergence、High->Low 最终 recount、partial hard-safe/hard-unsafe 正式链。
- `tests/test_w05_diagnostics.py`：public diagnostics JSON/provenance/正文与 secret 隔离。
- `tests/test_w04_session_commands.py`：`/status` default/effective/source/observed/tightened 精确投影。
- 本 Feedback：仅在原文件末尾追加本章节。

### 新增测试证明

- equality 与 `effective=600/1024/4096` 证明 `0 < Low < High`，不会以 equality 退化迟滞。
- first-invalid -> second-success 证明两次尝试后 `changed=True`、`failure=None`、只提交一个带 `ActiveCheckpoint` 的合法 candidate。
- Overflow first-invalid -> second-success 证明 compact Provider 两次尝试成功后 ordinary Provider 总调用恰为两次，即只执行一次 ordinary retry；recovery diagnostics 为 `recovered` 且无 failure。
- Provider/local divergence 通过显著不同的 local pressure 与 Provider exact count，证明达到 Low 后 status 为 completed、无 `auto_pressure_unresolved`，`gate_after_compaction` 与最终 ordinary Gate 均来自 `provider.preflight_count`；最终 Low count 至少执行两次，覆盖 epoch rebuild 与 ordinary final recount。
- configured `max_epochs=2` 的持续继续场景证明最多执行两个 epoch，返回 `epoch_limit_reached`，保留 turn-2 checkpoint，且没有 turn-3 伪提交。
- partial no-safe 正式 Application 场景证明已有成功 checkpoint 时：authoritative Gate hard-safe 则 ordinary request 继续，hard-unsafe 则 Provider ordinary stream 为零并 fail closed；两者都保留 `no_safe_epoch` breaker。
- provenance 测试证明 raw observed tuple 与 JSON list 一致，`/status` 字段完整，公开 diagnostics 可 `json.dumps()` 且不含正文、secret 或 native object。

### 精确验证结果

所有命令均在 `D:\project\Re-UthCode` 使用 Conda `re-uthcode`，测试 Provider 均为 fake/test double，无网络或真实 secret：

```text
新增合同测试（生产修复前）
5 failed, 7 passed in 3.29s

新增合同测试（生产修复后）
13 passed in 5.16s

conda run --no-capture-output -n re-uthcode python -m pytest tests/test_context_budget_gate.py tests/test_application_runs.py tests/test_w05_diagnostics.py tests/test_t09_1_context_protocol_e2e.py -q
111 passed in 12.74s

conda run --no-capture-output -n re-uthcode python -m pytest tests/test_context_budget_gate.py tests/test_context_compaction.py tests/test_t09_1_context_protocol_e2e.py tests/test_application_runs.py -q
110 passed in 12.95s

conda run --no-capture-output -n re-uthcode python -m pytest tests/test_w04_session_commands.py tests/test_application_runtime.py -q
13 passed in 5.46s

conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q
23 passed in 4.47s

conda run --no-capture-output -n re-uthcode python -m pytest -q
1210 passed, 3 skipped in 101.38s (0:01:41)

conda run --no-capture-output -n re-uthcode python -m compileall -q src tests eval
exit code 0

conda run --no-capture-output -n re-uthcode python -m pip check
No broken requirements found.

git diff --check
exit code 0；仅有工作区 LF/CRLF 转换提示，无 whitespace error
```

### 未完成项、风险与边界确认

- T03 Provider cache、T04 FailureReason、T05 Eval 与 T06～T08 均未实施；本轮没有修改 Provider cache、FailureReason、Eval runner 或 Interface 失败分类。
- 未执行真实 Provider、费用调用或网络测试；本轮 deterministic acceptance 全部使用离线 fake/test double。
- 未修改 T09-3 原始需求、Spec、Tasks、Prompt 或 Checklist；Checklist 当前勾选状态保持不动，没有新建 `v2`、`retry` 或 `fix` Feedback。
- 未覆盖或恢复用户已有 dirty files；未执行 add、commit、push、merge、rebase、tag、release、worktree 变更或归档等 Git 写操作。

## 返工第二轮

### 根因与结论更正

本轮处理第一轮返工后唯一剩余阻断：严格 High/Low 修复与小 effective input limit 冲突。

上一轮记录“没有扩大最小窗口”的结论需要更正。实际代码中的 `adaptive_working_headroom()` 仍以 `effective_input_limit - 1` 作为上限；因此 effective 为 2..513 时会派生 `working_headroom = effective - 1`，得到 `auto_gate_limit = 1`，再由严格 Low 合同得到 `retained_target = 0`。这形成了事实上的隐式可运行下限 514，且最终错误落在误导性的 `retained_target` ValueError，而不是明确领域错误。

本轮没有放宽 High/Low 合同，也没有引入新的最小窗口配置。最终合同为：

```text
effective_input_limit >= 3
0 < retained_target < auto_gate_limit < effective_input_limit
```

其中默认 headroom 上限改为 `effective_input_limit - 2`，保证所有数学上能够表达严格关系的 effective limit 都能生成合法默认值：effective=3 时 High=2、Low=1；effective=512/513 时 High=2、Low=1；effective=514 时 High=2、Low=1；effective=600 时 High=88、Low=87。effective=2 无法满足严格三段关系，因此在最小窗口校验处稳定抛出：

```text
effective input limit must be at least 3 to separate High and Low Water
```

### 边界测试与实际修改

- `tests/test_context_budget_gate.py` 新增并覆盖 effective `2、3、512、513、514、600`，同时覆盖 configured 与 Provider ceiling 来源。
- 新增 Provider 小 ceiling 不被 default 放大断言，以及 Provider ceiling 大于 default 时仍使用 `256_000` Operating Window 的断言。
- equality rejection contract test 保持并再次通过。
- `src/uthcode/core/context.py` 仅调整小窗口 headroom 上限和 effective<3 的 `ContextBudgetError` 领域校验；High/Low 严格比较未改变。
- 本 Feedback 仅在末尾追加本章节；Checklist、原始需求、Spec、Tasks、Prompt 未修改。

### 精确验证结果

所有命令均在 `D:\project\Re-UthCode` 使用 Conda `re-uthcode`；Provider 仍为 fake/test double，无网络或真实 secret：

```text
边界合同测试
18 passed in 0.63s

conda run --no-capture-output -n re-uthcode python -m pytest tests/test_context_budget_gate.py -q
41 passed in 3.41s

conda run --no-capture-output -n re-uthcode python -m pytest tests/test_context_budget_gate.py tests/test_application_runs.py tests/test_w05_diagnostics.py tests/test_t09_1_context_protocol_e2e.py -q
125 passed in 13.68s

conda run --no-capture-output -n re-uthcode python -m pytest tests/test_context_budget_gate.py tests/test_context_compaction.py tests/test_t09_1_context_protocol_e2e.py tests/test_application_runs.py -q
124 passed in 13.32s

conda run --no-capture-output -n re-uthcode python -m pytest tests/test_w04_session_commands.py tests/test_application_runtime.py -q
13 passed in 5.02s

conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q
23 passed in 4.94s

conda run --no-capture-output -n re-uthcode python -m pytest -q
1224 passed, 3 skipped in 107.99s (0:01:47)

conda run --no-capture-output -n re-uthcode python -m compileall -q src tests eval
exit code 0

conda run --no-capture-output -n re-uthcode python -m pip check
No broken requirements found.

git diff --check
exit code 0；仅有工作区 LF/CRLF 转换提示，无 whitespace error
```

### 本轮范围与未验证项

- 本轮实际生产修改仅为 `src/uthcode/core/context.py`；实际新增边界测试仅在 `tests/test_context_budget_gate.py`；Feedback 追加本章节。
- 第一轮已关闭的 retry failure、Overflow exactly-one retry、Provider exact Low、epoch limit、partial checkpoint、provenance、`/status` 与 JSON-safe diagnostics 均由上述定向回归和全量回归重新覆盖。
- 未实施 T03+，未执行真实 Provider/网络/费用验证，未执行任何 Git 写操作或归档，未改变 Checklist 勾选状态。
