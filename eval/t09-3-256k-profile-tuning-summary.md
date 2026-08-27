# T09-3 W04：256K profile 离线调优汇总

这是 T09-3 W04 的版本化、可审查汇总。原始 attempt workspace、home、artifact 和逐次 JSON 报告均位于仓库外的专用根：

`D:\project\Re-UthCode-Eval-T09-3`

本汇总不生成跨维度总分，也不把候选值写成 `create_application` 公共 API 或产品配置。W04 原始运行未修改 `src/` 的生产默认；该轮的 `production-default` 记录是采用调优结果前的历史公式基线。后续返工已将 Eval 选定的 `balanced-208k` 接入 256K 正式生产 resolver，历史候选数据仍保留用于可复核比较。

## 固定控制与候选轴

三组运行使用同一 `long-context-constraint` task、同一 Fake Provider、同一 `eval-model`、同一 Prompt salt、同一权限与运行参数、同一单样本分布。`compare` 只比较这些共同控制指纹；`candidate_variant` 单独保存 profile id 与完整参数，因此候选差异不会被误判为控制变量不兼容。

| Candidate | Effective / working headroom | Auto gate / retained | Fine timeline | L4 input / output | Max epochs / allowance |
| --- | ---: | ---: | ---: | ---: | ---: |
| `production-default` | `256000 / 12800` | `243200 / 72000` | `16000` | `64000 / 4000` | `4 / 0` |
| `balanced-208k` | `256000 / 48000` | `208000 / 96000` | `16000` | `64000 / 4096` | `4 / 8192` |
| `compact-224k` | `256000 / 32000` | `224000 / 128000` | `12000` | `48000 / 3072` | `3 / 12288` |

候选入口为：

```powershell
conda run --no-capture-output -n re-uthcode python -m eval.runner profile --candidate <production-default|balanced-208k|compact-224k> --experiment <experiment-id> --eval-root D:\project\Re-UthCode-Eval-T09-3 --attempts 1 --prompt-salt t09-3-w04-final --model eval-model
```

## 受控负载与结果

负载在 attempt workspace 生成确定性约 `988400` 字节证据文件，执行多轮探索、修改和回归验证；大结果经 Application 的外部化路径读回，脚本发出 16 次 `ToolResultRead`，外部化结果为 `994292` 字节。每组运行前注入同一 300-turn 可压缩 Session 历史。三组均完成任务且 verifier 成功，均为 `26` 个 Tool call、`22` 次迭代、`528/176/704` input/output/total tokens。

| Candidate | Correctness | Context | Exploration | Efficiency | Stability | Safety | Compact orchestration | Pre → post usage | Post headroom |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `production-default` | 100 | 100 | 60 | available* | 100 | 100 | 0 | N/A | N/A |
| `balanced-208k` | 100 | 100 | 60 | available* | 100 | 100 | 1 | `258192 → ~90.6k` | `~165.4k` |
| `compact-224k` | 100 | 100 | 60 | available* | 100 | 100 | 1 | `262288 → ~114.1k` | `~141.9k` |

两组触发 compact 的候选均产生 3 个 L4 compaction epoch；`compact_count` 是一次 compaction orchestration，不能代替 epoch 明细。两组的 `work_distance` 均为 `provider_requests_after_compaction=22`、`tool_result_read_calls=16`；没有观察到 compact 后立即 thrash。`repeated_exploration=4`，外部化为 `attempts=26, externalized=1, failed=0, inline=25`，稳定前缀为 true、`instruction_epoch=1`。具体整数会随离线编译边界出现 1 token 的正常离散差异，因此汇总用近似值，原始报告保留精确值。

W04 原始运行中的 `production-default` 使用 `count_allowance=0` 的历史生产公式，控制负载仍完成且不触发 L4。balanced 以更大的 post-compact headroom 和更低的 post usage 完成同样工作；compact 的 post usage 更高、headroom 更小，未显示出质量或安全收益。因此初始工程调优候选选择 `balanced-208k`。本汇总末尾的返工记录已说明该选择随后成为 256K 正式生产默认；它仍不是 public API 或生产配置字段。

\* Efficiency 由本机 attempt duration 参与计算，属于运行环境敏感的可用观察值；它不作为跨候选总分，也不单独决定选择。完整数值保存在对应外部报告。

## Deterministic acceptance 与 tuning evidence

确定性验收包括：

- `tests/eval` 覆盖候选合同、私有 seam 恢复、candidate axis compare、失败 reason correctness、runner 外部根与 live 拒绝。
- `tests/test_context_budget_gate.py`、`tests/test_context_compaction.py`、`tests/test_t09_1_context_protocol_e2e.py`、`tests/test_w05_diagnostics.py` 保持已有 256K、High→Low、prefix/cache projection 和失败诊断语义。
- `compare` 对共同控制指纹、task ids、sample count、逐任务样本分布和 schema 继续严格校验；只把 profile id/完整参数放在 `candidate_variants`。

调优证据只解释观察值之间的取舍，不把任何一个数值变成成功阈值。Fake Provider 没有 cache read/write telemetry，当前 workload 没有有效 `HistoryRead` ref，成功负载的 failure correctness 为 `not_applicable`；这些状态和原因会留在每个 attempt 的 `diagnostic_facts` 中。真实 Provider 的 cache、latency、billing 及远端长上下文结果为 `NOT VERIFIED (authorization required)`。

## 安全边界与清理

本次只运行 Fake Provider；没有 `--live`、没有读取 API key、没有网络请求、没有费用。attempt 清理必须使用 runner 的 manifest-owned 精确命令：

```powershell
conda run --no-capture-output -n re-uthcode python -m eval.runner clean --eval-root D:\project\Re-UthCode-Eval-T09-3 --experiment <experiment-id> --task long-context-constraint --attempt 1
```

清理后外部根只保留 `.uthcode-eval-root.json` 与版本化运行报告；仓库不保留 attempt、cache、home、workspace 或第二 benchmark runner。用户在任务开始前已有的 dirty files 保留，W04 未执行 commit、push、merge、rebase、tag、release 或工作包归档。

## 第一轮返工：W04/T05 阻断与报告精度

本节为原 v4 记录后的追加证据；原有 v4 报告和 W04 Feedback 历史事实保留，不在原文件上覆盖。第一轮返工只处理冻结 Prompt 的标准答案/固定 ToolCall 阻断和报告精度，不进入 T06 及之后。

- `eval/workloads.py` 已删除标准完整实现常量、`_stage` 和固定 `_next_calls()` 序列。离线 Provider 依据已观察的 required evidence、外部 ref/page EOF、编辑结果和 post-change reads 推进目标；route seed 可产生不同的合法读取批次/顺序和分页边界。
- 修改由实际 `src/implementation.py` 的 `ReadFile` 返回内容推导为一个局部 `EditFile` replacement；verifier 仍离线读取 attempt workspace 并独立判断 public signature、行为和 forbidden side effect。
- `eval/reporting.py` 的聚合 fact 现在保留每个 unavailable reason，并保留结构化 fact 的稳定非数值字段；因此报告正文会直接显示 `HistoryRead`、cache、failure correctness 的缺测原因以及 prefix change reason，而不是只显示 `None`。
- 新一轮报告使用外部专用根中的 `t09-3-w04-r1-final-production`、`t09-3-w04-r1-final-balanced`、`t09-3-w04-r1-final-compact` 和 `t09-3-w04-r1-final-repeat-balanced`。单次运行的整数值以对应 JSON 为准；重复 balanced 的 post usage/headroom 仍可能受 opaque ref 本地 request accounting 产生约 2 token 离散，报告保留每次精确值并把该差异作为运行事实，不宣称绝对稳定。

## 返工第一轮：v5 prefix reuse、invalidation 与报告精度

本节只追加当前返工证据；上方 v4/r1 历史记录不覆盖、不作为本轮最终数值。最终候选报告为：

- D:/project/Re-UthCode-Eval-T09-3/reports/t09-3-w04-v5-production/report.json
- D:/project/Re-UthCode-Eval-T09-3/reports/t09-3-w04-v5-balanced/report.json
- D:/project/Re-UthCode-Eval-T09-3/reports/t09-3-w04-v5-compact/report.json
- D:/project/Re-UthCode-Eval-T09-3/reports/t09-3-w04-v5-repeat-balanced/report.json

四份报告均 sample_count=1、task_sample_counts={long-context-constraint:1}、verifier success=true，六维依次为 correctness/context/exploration/efficiency/stability/safety = 100/100/80/62.64/100/100。共同 code fingerprint 为 76a3252ae84da2f79be0d379e7746722ce9121b99e500fccbaf6c78cd9509767；candidate variant 与共同 control fingerprint 分离。参数完整值以各 report 的 candidate_variants 为准：production-default 为 243200 auto gate、72000 retained、12800 working headroom、64000/4000 compact input/output、4 epochs、0 allowance；balanced-208k 为 208000、96000、48000、64000/4096、4、8192；compact-224k 为 224000、128000、32000、48000/3072、3、12288；repeat-balanced 与 balanced 参数相同。

| report | compact | pre / post / headroom | provider work / ToolResultRead | repeated | externalization attempts / externalized / bytes / failed / inline | input / output / total |
| --- | ---: | --- | --- | ---: | --- | --- |
| v5-production | 1 | 262048 / 58595 / 197405 | 23 / 17 | 2 | 25 / 1 / 994292 / 0 / 24 | 552 / 184 / 736 |
| v5-balanced | 1 | 268192 / 90621 / 165379 | 23 / 17 | 2 | 25 / 1 / 994292 / 0 / 24 | 552 / 184 / 736 |
| v5-compact | 1 | 272288 / 114129 / 141871 | 23 / 17 | 2 | 25 / 1 / 994292 / 0 / 24 | 552 / 184 / 736 |
| v5-repeat-balanced | 1 | 268192 / 90623 / 165377 | 23 / 17 | 2 | 25 / 1 / 994292 / 0 / 24 | 552 / 184 / 736 |

prefix_stability 在四份报告中均 available 且 stable=true。真实 ApplicationContextService.compose_generation_request、ContextCompiler、InstructionLoader 事实显示：conversation growth 前后和 compact pre_compact/post_compact 前后均 stable_reuse=true、fingerprint_same=true、reason=stable；project/AGENTS.md source_added 后均 instruction_epoch 1 到 2、prefix_changed=true、fingerprint_changed=true、request metadata 与 loader reason 均为 instruction_source_added。变化前公共 fingerprint 为 1cc47fad8cf4ca9a62f85512668bd3697024fc25f75b111f8e7d8cc45f71ecab，tool schema fingerprint 保持不变；每份报告都保留 before/after、source、phase、message_count 和 reason。不同 dedicated attempt 根导致现有 production provenance 参与 after fingerprint，因此 after 值可不同，但不影响四份报告的共同 compatible control fingerprint。

报告精度已固定：成功 workload source 的 failure_correctness 是 not_applicable；标准 report diagnostic fact 的 status 是 not_available，source_status=not_applicable，并保留 successful workload; failure matrix is verified separately reason。cache_reuse 是 not_available，reason=offline Fake Provider has no provider cache telemetry；HistoryRead 是 not_available，原因是 offline profile workload has no valid HistoryRead ref。没有修改公共 FailureReason 或新增 cache/prefix 系统。

production 到 balanced、balanced 到 compact、balanced 到 repeat-balanced 三个 CLI compare 均 exit=0、compatible=true、incompatibilities=[]、delta 非空，六维 delta 全为 0。相关 usage/headroom delta 分别为 +6144/+32026/-32026、+4096/+23508/-23508、0/+2/-2。使用既有 final-smoke 作为负向控制时 exit=0、compatible=false、delta=null，明确列出 code/prompt/run_args/runtime/task、task_ids、task_sample_counts 和对应 fingerprint_variants 不兼容。根据新的 v5 事实，仍选择 balanced-208k；它在 production 历史基线的更激进压缩与 compact 的更高 post usage 之间取得参数和保留量折中。这不是 overall/weighted score；本汇总末尾记录了该选择已接入正式 256K 默认。

本轮最终四个 v5 attempt 均用 manifest-owned dedicated-root clean 清除，workspace/home/artifacts 对应目录不存在且文件数为 0，四份 report.json/report.md 保留。repo-root clean 以仓库根为 eval-root 返回 exit=2 和 clean requires a dedicated Eval root。标准答案、固定 ToolCall 序列、T06+、生产默认和 Git 写操作均未恢复或执行。

## 返工第一轮补充：多 attempt 合法路线与新 v5 证据

上一节的单 attempt v5 数值保留为历史记录。本补充对应验收返工后的最终候选，不覆盖历史正文。

- `eval/runner.py` 现在按 attempt 编号传给 `ProfileWorkloadProvider`：attempt 1/2 的 `route_seed` 为 0/1；同一 seed 在各候选间共享，且不进入 candidate variant 或共同 control fingerprint。`eval/workloads.py` 仅记录实际发出的 ToolCall 最小投影，依据实际 ToolResult/EOF/EditFile/修改后读取结果推进，没有标准完整答案或固定唯一序列。
- 四份最终报告均为 `sample_count=2`、`task_sample_counts={long-context-constraint:2}`、`finish_categories={success:2}`，共同 code fingerprint 为 `2e628dbe09ee05af2d3b6945bd23370c33b99b5a20b45dd28e853baec5ffbffd`，candidate variant 与控制 fingerprint 分离，六维没有 overall/weighted score。

| report | candidate parameters（auto / retained / working headroom；compact input/output；epochs；allowance） | correctness / context / exploration / efficiency / stability / safety | compact | pre → post usage；headroom | route seeds / trace |
| --- | --- | --- | ---: | --- | --- |
| v5-production | `243200 / 72000 / 12800；64000 / 4000；4；0` | `100 / 100 / 80 / 71.148 / 100 / 100` | 1 | `262048 → 58595；197405` | `0,1 / 25 calls each` |
| v5-balanced | `208000 / 96000 / 48000；64000 / 4096；4；8192` | `100 / 100 / 80 / 72.32 / 100 / 100` | 1 | `268192 → 90621；165379` | `0,1 / 25 calls each` |
| v5-compact | `224000 / 128000 / 32000；48000 / 3072；3；12288` | `100 / 100 / 80 / 72.7965 / 100 / 100` | 1 | `272288 → 114129；141871` | `0,1 / 25 calls each` |
| v5-repeat-balanced | same as balanced | `100 / 100 / 80 / 72.405 / 100 / 100` | 1 | `268192 → 90623；165377` | `0,1 / 25 calls each` |

每条 seed 路线均包含四个 required evidence 的完整读取、`docs/profile-evidence.txt` 的 externalized ref 和 17 次 `ToolResultRead` 至 EOF、`EditFile(src/implementation.py)`、修改后复读 regression/implementation；`route.complete=true`、`read_failures=[]`、`edit_succeeded=true`，verifier `success=true` 且 4/4 checks passed。seed 0 初始读取顺序为 `tests/test_public_api.py → src/public_api.py → src/implementation.py → docs/early-constraint.md`；seed 1 为 `tests/test_public_api.py → src/implementation.py → src/public_api.py → docs/early-constraint.md`。正式测试 `test_profile_two_attempts_complete_distinct_read_edit_verify_routes` 检查两条完整 trace、报告聚合后的 seeds、修改和 verifier 成功，而不只检查排序。

四候选的 `provider_requests_after_compaction=23`、`ToolResultRead=17`、`repeated_exploration=2`；externalization 均为 `attempts=25, externalized=1, externalized_bytes=994292, failed=0, inline=24`。HistoryRead 均为 `not_available`，reason 为 `the offline profile workload has no valid HistoryRead ref`；cache 均为 `not_available`，reason 为 `offline Fake Provider has no provider cache telemetry`。

prefix 仍来自真实 `ApplicationContextService.compose_generation_request`、`ContextCompiler`、`InstructionLoader`：conversation growth 和 compact pre/post 均 `stable_reuse=true`、`fingerprint_same=true`、`reason=stable`；新增 project `AGENTS.md` 后真实观察到 epoch `1→2`、`prefix_changed=true`、fingerprint/key 不同、`fingerprint_changed=true`，snapshot/request/loader reason 均为 `instruction_source_added`。成功 workload source 的 `failure_correctness` 为 `not_applicable`；标准 report diagnostic fact 为 `status=not_available`、`source_status=not_applicable` 并保留 successful workload reason。

新 CLI compare 精确结果：production→balanced `compatible=true`、六维 delta `0/0/0/+1.172/0/0`，pre/post/headroom delta `+6144/+32026/-32026`；balanced→compact `compatible=true`、六维 delta `0/0/0/+0.4765/0/0`，`+4096/+23508/-23508`；balanced→repeat-balanced `compatible=true`、六维 delta `0/0/0/+0.085/0/0`，`0/+2/-2`，三者 `incompatibilities=[]`。用 `t09-3-w04-final-smoke` 对 v5 balanced 的 incompatible compare 为 `compatible=false`、`delta=null`，不兼容项为 `fingerprints.code/prompt/run_args/runtime/task`、`task_ids`、`sample_count`、`task_sample_counts` 及对应 `fingerprint_variants.code/prompt/run_args/runtime/task`。

根据新证据仍选择 `balanced-208k`：所有候选质量/安全相关维度和 verifier 相同；compact 有最高 efficiency 但更高 post usage、更低 headroom/working headroom，production 历史基线有更大总 headroom但 auto gate/working headroom 更紧，balanced 是上下文余量和 compaction 行为的折中。该选择现已由返工接入正式 256K 默认；候选轴和历史 baseline 仍用于 Eval 比较。

本轮实际创建 11 个外部 attempt：route-debug 1 个、首次 balanced 验证 2 个、最终四候选各 2 个；compact 错误 candidate 名称在 attempt 创建前拒绝。11 个 attempt 均用 manifest-owned dedicated-root clean 清除了 workspace/home/artifacts；最终四个 v5 experiment 的这些组件文件数为 0，每份报告目录只保留 `report.json` 与 `report.md`。repo-root clean 仍 exit=2 并拒绝非 dedicated root。

本轮验证：`tests/eval` `87 passed`；上下文/诊断 `89 passed`；架构 `23 passed`；全量 `1247 passed, 3 skipped`；`compileall` exit=0；`git diff --check` exit=0（仅 CRLF 提示）；runner/profile help 均 exit=0；路线/报告定向测试及三组 compatible、一次 incompatible compare 均通过。live Provider、远端 cache/latency/billing、远端长上下文和费用仍未验证。W04 历史运行未修改生产默认；后续返工接入记录见下节，未触碰排除目录或执行 Git 写操作。

## 返工追加：采纳 balanced-208k 为 256K 正式生产默认（2026-08-27）

包级审核发现 W04 历史报告把 `balanced-208k` 仅描述为 Eval 候选，未证明它进入生产链。该返工只补齐冻结 Tasks 要求的生产回写证据，不改变候选比较、公共 API、配置字段或既有失败/缓存语义。

- `ContextBudget` 的正式 resolver 在 effective input 为 `256_000` 时使用选定的 `balanced-208k` 初始工程默认：working headroom `48_000`、High Water `208_000`、retained/Low Water `96_000`、fine timeline `16_000`、compaction input/output `64_000/4_096`、count allowance `8_192`；Application Turn 的有界 L4 epoch 上限仍为既有 `4`。
- effective input 小于或大于 `256_000` 时继续使用现有有界自适应派生；Provider/configured ceiling 仍只收紧 effective limit，不会把 balanced 的 256K 数值硬写进更小窗口。input、output、combined 三个 Hard Gate 以及 Active Turn freeze 未改变。
- `eval/profile.py` 中的 `production-default` 保留为 W04 原始历史公式 baseline，用于复核原始 compare；它不再代表当前生产 resolver。`balanced-208k` 仍是候选轴记录，同时也是当前 256K 正式默认的事实来源。
- 新增 Core exact-profile 与正式 Application Turn 回归，并调整 High→Low fake provider 断言按实际 safety allowance 计算；本轮定向、Eval、架构、全量和工具链精确结果记录在对应返工 Feedback。
