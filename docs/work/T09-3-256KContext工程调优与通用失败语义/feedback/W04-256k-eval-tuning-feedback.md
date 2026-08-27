# W04 256K Eval 调优反馈

## 结论

W04/T05 已按冻结 Prompt 完成。三组候选均通过同一离线长上下文 workload 和 verifier；共同控制指纹保持 compatible，profile id/完整参数作为独立 candidate axis 写入报告。基于 post-compact headroom、post-compact usage、任务成功、约束保留和无 compact thrash 的逐维证据，初始工程调优候选选择 `balanced-208k`。

该选择只属于 Eval 工程候选，不是 public API、`config.toml` 字段或生产默认回写；W04 没有修改 `src/` 的 256K production resolver/default。真实 Provider 的 cache、latency、billing 和远端长上下文结果仍为 `NOT VERIFIED (authorization required)`。

本次没有修改冻结的 Request、Spec、Tasks、Prompt 正文，没有执行 commit、push、merge、rebase、tag、release 或工作包归档。任务开始前已有的 `docs/core-design/**` 变更、未跟踪文档和 `临时目录/**` 保持原样。

## 实施范围

- 新增 `eval/profile.py`：定义 `production-default`、`balanced-208k`、`compact-224k` 三组候选，保存完整参数；通过私有、可替换 seam 临时复用现有 `resolve_context_budget` 与 `ApplicationContextService.compact_async`，退出上下文后恢复 Application 原绑定。
- 扩展 `eval/workloads.py` 和 `eval/runner.py`：增加 `profile` 离线入口，使用外部 attempt workspace 生成约 `988400` 字节确定性证据文件，要求多轮探索、修改、回归验证，并通过真实 Application Tool path 外部化/读回约 `994292` 字节结果。
- 每次候选在 measured Turn 前注入同一 300-turn 可压缩 Session 历史；两组非生产候选均进入真实 L4 路径，未修改生产状态模型或公开创建入口。
- 扩展 `AttemptRecord`、execution diagnostics hook、diagnostic facts 和 report compare：候选轴与控制指纹分离；新增 pre/post compact usage、post-compact headroom、work distance、HistoryRead、failure correctness 等事实，缺测保留 `not_available`/`not_applicable`，不转换为零。
- 新增 `tests/eval/test_eval_profile.py`，同步 `tests/test_w05_diagnostics.py` 使用统一 `DIAGNOSTIC_FACTS` 集合；更新 `eval/README.md` 与版本化汇总 `eval/t09-3-256k-profile-tuning-summary.md`。

没有新增 public `create_application` 参数、产品配置字段、第二 benchmark runtime、overall/weighted score、Provider SDK 类型穿透或 live 开关。

## 候选参数与 v4 结果

最终报告均位于外部根 `D:\project\Re-UthCode-Eval-T09-3`：

- `reports/t09-3-w04-v4-production/report.json`
- `reports/t09-3-w04-v4-balanced/report.json`
- `reports/t09-3-w04-v4-compact/report.json`

三份报告的共同 `code` fingerprint 为 `97c3ae22c314b9f45e1d554cbe3738b2b13306801e2acaad8e9530226df62629`，共同 task 为 `long-context-constraint`，每组 `sample_count=1`、`task_sample_counts={"long-context-constraint": 1}`。候选完整参数如下：

| Candidate | Effective / working headroom | Auto gate / retained | Fine timeline | L4 input / output | Max epochs / allowance |
| --- | ---: | ---: | ---: | ---: | ---: |
| `production-default` | `256000 / 12800` | `243200 / 72000` | `16000` | `64000 / 4000` | `4 / 0` |
| `balanced-208k` | `256000 / 48000` | `208000 / 96000` | `16000` | `64000 / 4096` | `4 / 8192` |
| `compact-224k` | `256000 / 32000` | `224000 / 128000` | `12000` | `48000 / 3072` | `3 / 12288` |

三组均 `finish_category=success`、verifier `success=true`，并观察到 `26` Tool call、`22` 次迭代、`528/176/704` input/output/total tokens。六维结果（效率包含本机 duration，保留为运行时观察值，不作总分）为：

| Candidate | Correctness | Context | Exploration | Efficiency | Stability | Safety |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `production-default` | 100 | 100 | 60 | 77.538 | 100 | 100 |
| `balanced-208k` | 100 | 100 | 60 | 72.304 | 100 | 100 |
| `compact-224k` | 100 | 100 | 60 | 73.382 | 100 | 100 |

关键观察事实：

| Candidate | Compact orchestration | Compact epochs | Pre usage | Post usage | Post headroom | Work distance |
| --- | ---: | --- | ---: | ---: | ---: | --- |
| `production-default` | 0 | — | N/A | N/A | N/A | `0 provider / 16 ToolResultRead` |
| `balanced-208k` | 1 | `L4,L4,L4` | `258192` | `90632` | `165368` | `22 provider / 16 ToolResultRead` |
| `compact-224k` | 1 | `L4,L4,L4` | `262288` | `114140` | `141860` | `22 provider / 16 ToolResultRead` |

三组均 `repeated_exploration=4`；externalization 均为 `attempts=26, externalized=1, externalized_bytes=994292, failed=0, failed_bytes=0, inline=25`；prefix 为 stable、`instruction_epoch=1`。当前 Fake workload 没有有效 `HistoryRead` ref、没有 Provider cache read/write telemetry，rediscovery 没有真实结构化事实，成功 workload 的 failure correctness 为 `not_applicable`，报告均保留原因。原始 context snapshot 中在长页历史累积阶段可见 `over_budget=true`，但最终 request 经过现有 reduction/Hard Gate 后完成；该事实没有被隐藏或改写为质量分数。

balanced 相对 production 保持相同成功、token、Tool call、重复探索、externalization 和 prefix 结果，增加一次受控 L4 orchestration，并取得更大的 post-compact headroom。compact 相对 balanced 的 post usage 高约 `23508`、post headroom 低约 `23508`，没有质量或安全收益。因此选择 balanced；选择理由是逐维取舍，不是单一 token 指标或 overall score。

## Compare 与重复运行证据

production 对 balanced：

```text
conda run --no-capture-output -n re-uthcode python -m eval.runner compare --baseline D:\project\Re-UthCode-Eval-T09-3\reports\t09-3-w04-v4-production\report.json --candidate D:\project\Re-UthCode-Eval-T09-3\reports\t09-3-w04-v4-balanced\report.json
```

结果：`compatible=true`，`incompatibilities=[]`，`delta` 非空；`candidate_variants` 分别为 `production-default` 和 `balanced-208k`。共同控制事实中 success/tool calls/tokens/repeated exploration/externalization/prefix 保持一致，compact count 为 `0 -> 1`，post-compact work distance 为 `0 -> 22` provider requests，`ToolResultRead` 为 `16 -> 16`。

balanced 对 compact：

```text
conda run --no-capture-output -n re-uthcode python -m eval.runner compare --baseline D:\project\Re-UthCode-Eval-T09-3\reports\t09-3-w04-v4-balanced\report.json --candidate D:\project\Re-UthCode-Eval-T09-3\reports\t09-3-w04-v4-compact\report.json
```

结果：`compatible=true`，`incompatibilities=[]`，`delta` 非空；候选轴完整保留。compact count、work distance、success、tokens、Tool call、repeated exploration、externalization 和 prefix 结构一致，post compact usage/headroom 显示 compact 的连续工作空间更差。

同一 balanced 候选重复运行：

```text
conda run --no-capture-output -n re-uthcode python -m eval.runner profile --candidate balanced-208k --experiment t09-3-w04-v4-repeat-balanced --eval-root D:\project\Re-UthCode-Eval-T09-3 --attempts 1 --prompt-salt t09-3-w04-final --model eval-model
conda run --no-capture-output -n re-uthcode python -m eval.runner compare --baseline D:\project\Re-UthCode-Eval-T09-3\reports\t09-3-w04-v4-balanced\report.json --candidate D:\project\Re-UthCode-Eval-T09-3\reports\t09-3-w04-v4-repeat-balanced\report.json
```

结果：`compatible=true`、`incompatibilities=[]`、candidate variant 相同；success、compact count、pre usage、work distance、repeated exploration、externalization、prefix 和六维结构稳定。post usage/headroom 在 `90632/165368` 与 `90634/165366` 之间出现 2 token 离散差异，来自外部化结果 opaque ref 的随机字符参与本地 request accounting；这是运行事实而非产品语义变化，汇总报告使用近似值，原始 JSON 保留精确值。

不兼容 compare 的手动拒绝：将 v4 production 与 smoke 报告比较，命令返回 `compatible=false`、`delta=null`，拒绝原因包含 `fingerprints.code/prompt/run_args/runtime/task`、`task_ids`、`task_sample_counts` 与对应 fingerprint variants；没有放宽共同控制变量。

## 入口、安全与清理验收

- `conda run --no-capture-output -n re-uthcode python -m eval.runner --help`：展示 `smoke/run/profile/compare/clean`。
- `conda run --no-capture-output -n re-uthcode python -m eval.runner profile --help`：展示三个候选、`--experiment`、`--eval-root`、`--attempts`、`--prompt-salt`、`--model`。
- 离线 smoke：

  ```text
  conda run --no-capture-output -n re-uthcode python -m eval.runner smoke --task single-file-control --experiment t09-3-w04-final-smoke --eval-root D:\project\Re-UthCode-Eval-T09-3 --attempts 1 --prompt-salt t09-3-w04-final --model eval-model
  ```

  返回 runner 成功并产出外部报告；Fake 未注入标准答案，故该 smoke 的 finish category 为预期的 `agent_failure`，不是候选 profile 结果。随后用 manifest-owned clean 删除了该 attempt。
- clean 边界拒绝：

  ```text
  conda run --no-capture-output -n re-uthcode python -m eval.runner clean --eval-root D:\project\Re-UthCode --experiment rejected --task long-context-constraint --attempt 1
  ```

  返回 `eval runner error: clean requires a dedicated Eval root`，没有触碰仓库。
- 30 个已验证的外部 attempt 均按 `long-context-constraint/1` 和 manifest 精确调用 clean，共清理 90 个 workspace/home/artifacts 组件；清理后 `workspace/`、`home/`、`artifacts/` 下无文件，v4 reports 保留。仓库内没有 Eval attempt、cache、home 或 workspace。
- 没有执行任何 `--live` 命令、没有读取 API key、没有网络请求或费用；`tests/eval` 的 live authorization rejection 测试通过。真实 Provider cache/latency/billing 明确为 `NOT VERIFIED (authorization required)`。

## 测试与 UTF-8 验收

以下命令均使用 `re-uthcode`：

```text
conda run --no-capture-output -n re-uthcode python -m pytest tests/eval -q
81 passed in 39.32s

conda run --no-capture-output -n re-uthcode python -m pytest tests/test_context_budget_gate.py tests/test_context_compaction.py tests/test_t09_1_context_protocol_e2e.py tests/test_w05_diagnostics.py -q
89 passed in 10.51s
```

另执行 `git diff --check`、`python -m eval.runner --help`、`profile --help`、离线 smoke、compatible/incompatible compare 和 dedicated-root clean rejection；均得到上文记录的结果。使用 `uth-utf8-guard` 检查本次实际修改的 Markdown，UTF-8、replacement character、mojibake 和 fence parity 全部通过。

## 风险与后续边界

- profile seam 是 W04 私有 Eval 实现；后续正式入口如需采用 balanced，必须由后续工作包重新评估并修改生产事实，不能把本 Feedback 的候选值当作已发布 API。
- Fake workload 没有 Provider cache wire、真实 HistoryRead 或远端 tokenizer；这些缺测已显式报告，不能从离线结果推断真实 cache ratio、latency、billing 或 256K 远端质量。
- 重复运行的 post usage 有 2 token 的 opaque-ref accounting 离散差异；宏观 compaction、工作距离、成功和六维结构稳定，精确值以外部 JSON 为准。
- `docs/OutstandingDebtList.md` 已核对，未新增或删除能力欠账；未把未授权 live Eval、一般 Out of Scope 或离线 workload 缺测登记为欠账。

## 第一轮返工追加记录（2026-08-27）

本节记录 W04/T05 第一轮返工的实际收敛结果，只关闭本轮指定的验收阻断和报告精确性问题，不进入 T06+，不修改 Prompt、Spec、Tasks 或 Checklist 的冻结内容。

### 阻断关闭：移除标准答案与唯一 ToolCall 路线

- eval/workloads.py 已删除 PROFILE_FINAL_IMPLEMENTATION，不再保存目标文件的标准完整内容；同时删除按内部 stage 驱动的 _stage、_next_calls 和 WriteFile 预置答案注入路径。
- Fake Provider 现在只根据已观察到的 ToolResult、外部化页面和实际 ReadFile 内容推进。读取批次、分页大小和后续读取顺序由 route_seed 产生多个可行观察顺序；因此 verifier 仍是离线确定性的，但不再把某一条 ToolCall 序列当作正确性条件。
- 实现修改由实际读取到的带行号内容推导为局部 EditFile，不持有标准完整 Patch。验收测试已覆盖无标准答案常量、无固定阶段序列、无 WriteFile 注入，以及不同 route_seed 的有效观察顺序。

### 报告精度修正与最终 r1 报告

聚合事实现在保留 unavailable reason，并保留 prefix 等稳定结构化字段；compare 的 fact delta 也携带 baseline/candidate 的 reason 和 stable fields。最终报告中的缺测不会再被汇总过程丢失。

最终报告路径如下：

- D:\project\Re-UthCode-Eval-T09-3\reports\t09-3-w04-r1-final-production\report.json
- D:\project\Re-UthCode-Eval-T09-3\reports\t09-3-w04-r1-final-balanced\report.json
- D:\project\Re-UthCode-Eval-T09-3\reports\t09-3-w04-r1-final-compact\report.json
- D:\project\Re-UthCode-Eval-T09-3\reports\t09-3-w04-r1-final-repeat-balanced\report.json

四份报告的 code fingerprint 均为 baf875a8263ffc754ee9552267c71320f9968ccc25475e2ee589414cac8f1525；每份均为 sample_count=1、long-context-constraint=1、verifier success=true、correctness=100，四项 verifier checks 全部通过，25 次 Tool call、2 次 repeated exploration、25 次 externalization attempt、1 次 externalized、994292 bytes、0 次 failed、24 次 inline。工具集合为 ReadFile、ToolResultRead、EditFile。

| 报告 | 六维结果（correctness/context/exploration/efficiency/stability/safety） | compact | pre/post/headroom | work distance（provider / ToolResultRead） | token usage |
|---|---|---:|---|---|---|
| final-production | 100/100/80/66.515/100/100 | 0 | N/A | 0 / 17 | 552 / 184 / 736 |
| final-balanced | 100/100/80/62.64/100/100 | 1 | 258192 / 90634 / 165366 | 23 / 17 | 552 / 184 / 736 |
| final-compact | 100/100/80/62.64/100/100 | 1 | 262288 / 114142 / 141858 | 23 / 17 | 552 / 184 / 736 |
| final-repeat-balanced | 100/100/80/71.75/100/100 | 1 | 258192 / 90636 / 165364 | 23 / 17 | 552 / 184 / 736 |

HistoryRead 的聚合 reason 为 the offline profile workload has no valid HistoryRead ref；cache_reuse 的聚合 reason 为 offline Fake Provider has no provider cache telemetry；failure_correctness 的聚合 reason 为 successful workload; failure matrix is verified separately。prefix 的 stable fields 保留 change_reason=stable、fingerprint=1cc47...、stable=true，完整值以各报告 JSON 为准。真实 Provider cache、远端 HistoryRead、tokenizer、latency、billing 仍为 NOT VERIFIED，不从离线数据外推。

四组 final report 的 compare 均保持 schema compatible 且产生非空 delta：production 到 balanced 只观察到环境相关 efficiency 和 compaction/work-distance 差异；balanced 到 compact 的 pre/post/headroom 变化为 +4096 / +23508 / -23508；balanced 到 repeat 的 post/headroom 变化为 +2 / -2。最后的 2 token 是 opaque-ref accounting 离散差异，不能宣称逐 token 绝对稳定，精确值以 JSON 为准。production、balanced、compact、repeat-balanced 作为候选观测变体保留，未将任一离线 efficiency 数值单独提升为产品决策。

### 清理与验证

- 本轮 8 个实验 attempt 已使用 manifest-owned runner clean 清理；外部 Eval 根目录清理后 workspace、home、artifacts 文件数均为 0，reports 文件保留。
- 定向回归：conda run --no-capture-output -n re-uthcode python -m pytest tests/eval -q，84 passed in 36.87s。
- 相关上下文回归：conda run --no-capture-output -n re-uthcode python -m pytest tests/test_context_budget_gate.py tests/test_context_compaction.py tests/test_t09_1_context_protocol_e2e.py tests/test_w05_diagnostics.py -q，89 passed in 10.49s。
- conda run --no-capture-output -n re-uthcode python -m compileall -q src eval 通过；git diff --check 无 diff error；禁止的标准答案、固定序列和 WriteFile 标记在 eval/workloads.py 中均无命中。
- uth-utf8-guard 对本次实际修改的四份 Markdown 检查通过：UTF-8、replacement character、常见乱码和 Markdown fence parity 均通过。
- 未执行 Git commit、push、merge、rebase、tag、release 或工作包归档；未修改 T06+。

## 返工第一轮

本节是对本文件历史内容的追加，不删除、不覆盖、不改写此前 Feedback；只处理 W04/T05 本轮指定的两个验收阻断和报告精度问题。冻结 Prompt、Spec、Tasks、Checklist、src 生产实现、公共 API、Provider cache wire、Interface、T06+、docs/core-design 和临时目录均未改动。

### 阻断一：标准答案和固定 ToolCall 序列已移除

- eval/workloads.py 不再定义 PROFILE_FINAL_IMPLEMENTATION；不再有 _stage、_next_calls 或 WriteFile 预置完整答案路径。
- Fake Provider 只使用已观察的 ReadFile 内容、ToolResultRead 的外部页边界、EOF、编辑结果和 post-change reads 推进。实际编辑由观察到的 src/implementation.py 行内容推导为局部 EditFile replacement，最终正确性仍由离线 verifier 独立判断。
- route_seed=0 和 route_seed=1 产生不同的 required-evidence 读取顺序，同时两个顺序都保持相同路径集合；tests/eval/test_eval_profile.py 的 test_profile_workload_route_seed_allows_multiple_valid_observation_orders 已同时断言顺序不同和集合完整。因此至少有两种合法观察轨迹，不再把单一 ToolCall 序列当成答案。
- tests/eval/test_eval_profile.py 的 test_profile_workload_derives_observed_edit_and_has_no_standard_patch 对标准答案常量、固定阶段、固定序列和 WriteFile 标记均作负向断言；verifier 仍是成功/失败的权威。

### 阻断二：真实 prefix reuse 和 expected invalidation

profile attempt 在 runner 中附着实际 Application；workload 从 ApplicationContextService 的 last_snapshot 和 GenerationRequest.metadata 读取事实。prefix probe 使用生产 InstructionLoader、ApplicationContextService.compose_generation_request 和其内部 ContextCompiler，只投影返回的 fingerprint、epoch、prefix_changed、change_reason、tool schema fingerprint 及消息数，没有直接伪造 diagnostics。

四个 v5 报告均记录以下可追踪链：

1. conversation_growth_before/after 的 message_count 为 1 到 2，stable_reuse=true、fingerprint_same=true、prefix_change_reason=stable，前后 stable prefix fingerprint 均为 1cc47fad8cf4ca9a62f85512668bd3697024fc25f75b111f8e7d8cc45f71ecab。
2. measured Application request 的 compact before/after phase 为 pre_compact 到 post_compact，message_count 为 224 到 301，stable_reuse=true、fingerprint_same=true，前后 stable prefix fingerprint 仍相同，reason=stable。
3. 相同的 project instruction source 变化用于每个候选：在专用 attempt artifacts 下加入 project/AGENTS.md，InstructionLoader 返回 loader_change_reason=instruction_source_added，ContextCompiler/Application request 返回 prefix_changed=true、instruction_epoch 1 到 2、request metadata reason=instruction_source_added，且变化前后 fingerprint 不同。四个 after fingerprint 分别是 production 94fc870de4e30316b624beac2d0d0bb5113d3257fae01453b942e747b8dc306a、balanced ccb272813f0d0a2acc729f67be84e50455b0c5a0f5845386cbf3ed85ab070e90、compact 385e267927ac03809254c1ffd57b2a717d1e4ab23e9e44ddd986f87798ccaba、repeat-balanced 60a48482ff7904a69ec4c023bbb93f2a50b1d53d799aacbc26816b32b386f5d5。
4. invalidation 场景的 source 内容、相对路径、source_added 方式、model、messages 和 tool definitions 对三组候选相同；tool schema fingerprint 在变化前后保持相同。候选 variant 不写入 compatible control fingerprints，四份 v5 的控制指纹完全一致。生产 fingerprint 本身包含 instruction block provenance，专用 attempt 根的绝对路径是现有生产事实的一部分，所以各报告的 after fingerprint 可以不同；验收依据是每份报告内部 before 与 after 的真实变化、同一 reason 和相同控制变量，而不是把 candidate variant 混入 fingerprint。

tests/eval/test_eval_profile.py 的 test_profile_prefix_probe_uses_production_facts_for_reuse_and_invalidation 覆盖真实 loader reason、epoch、fingerprint、request metadata reason、tool schema 保持不变和 stable reuse；同文件的 test_prefix_and_success_failure_facts_keep_unavailable_distinct 覆盖 prefix unavailable 及原因仍可观察。报告投影测试还确认 expected_invalidation 的嵌套事实在聚合后仍保留。

### 报告精度修正

本轮明确区分两个层次：

- workload source：成功 workload 的 diagnostics.eval_workload.failure_correctness.status 是 not_applicable，原因是 successful workload; failure matrix is verified separately。
- standard report diagnostic fact：diagnostic_facts.failure_correctness.status 以及聚合 facts.failure_correctness.status 是 not_available，source_status=not_applicable，并保留上述 reason；不是把标准 report 写成 not_applicable。

同样，Fake Provider 的 cache_reuse 是 not_available，reason=offline Fake Provider has no provider cache telemetry；HistoryRead 是 not_available，reason=the offline profile workload has no valid HistoryRead ref。聚合和 compare 均保留这些 reason。没有新增 FailureReason 公共语义或第二套 cache/prefix 系统。

### v5 重新生成的候选证据

最终报告只使用本轮新运行的四个版本化 experiment：

- D:\project\Re-UthCode-Eval-T09-3\reports\t09-3-w04-v5-production\report.json
- D:\project\Re-UthCode-Eval-T09-3\reports\t09-3-w04-v5-balanced\report.json
- D:\project\Re-UthCode-Eval-T09-3\reports\t09-3-w04-v5-compact\report.json
- D:\project\Re-UthCode-Eval-T09-3\reports\t09-3-w04-v5-repeat-balanced\report.json

四份报告均 sample_count=1、task_sample_counts={long-context-constraint:1}、verifier success=true、四项 verifier checks 通过，25 次 Tool call，25 次 provider iteration，tool 集合为 ReadFile、ToolResultRead、EditFile。共同 control fingerprint 的 code 值为 76a3252ae84da2f79be0d379e7746722ce9121b99e500fccbaf6c78cd9509767；task、model、model_id=eval-model、provider、prompt、config、permission、run_args、platform、runtime 和 uthcode_revision 在四份报告中也完全相同。candidate variant 单独记录如下：

| report | candidate parameters |
| --- | --- |
| v5-production | production-default: effective_input_limit=256000, auto_gate_limit=243200, retained_target=72000, working_headroom=12800, fine_timeline_budget=16000, compaction_input_budget=64000, compaction_output_reserve=4000, max_epochs=4, count_allowance=0 |
| v5-balanced | balanced-208k: effective_input_limit=256000, auto_gate_limit=208000, retained_target=96000, working_headroom=48000, fine_timeline_budget=16000, compaction_input_budget=64000, compaction_output_reserve=4096, max_epochs=4, count_allowance=8192 |
| v5-compact | compact-224k: effective_input_limit=256000, auto_gate_limit=224000, retained_target=128000, working_headroom=32000, fine_timeline_budget=12000, compaction_input_budget=48000, compaction_output_reserve=3072, max_epochs=3, count_allowance=12288 |
| v5-repeat-balanced | balanced-208k，参数与 v5-balanced 完全相同 |

| report | correctness / context / exploration / efficiency / stability / safety | compact | pre / post / headroom | work distance provider / ToolResultRead | repeated exploration | externalization attempts / externalized / bytes / failed / inline | usage input / output / total |
| --- | --- | ---: | --- | --- | ---: | --- | --- |
| v5-production | 100 / 100 / 80 / 62.64 / 100 / 100 | 1 | 262048 / 58595 / 197405 | 23 / 17 | 2 | 25 / 1 / 994292 / 0 / 24 | 552 / 184 / 736 |
| v5-balanced | 100 / 100 / 80 / 62.64 / 100 / 100 | 1 | 268192 / 90621 / 165379 | 23 / 17 | 2 | 25 / 1 / 994292 / 0 / 24 | 552 / 184 / 736 |
| v5-compact | 100 / 100 / 80 / 62.64 / 100 / 100 | 1 | 272288 / 114129 / 141871 | 23 / 17 | 2 | 25 / 1 / 994292 / 0 / 24 | 552 / 184 / 736 |
| v5-repeat-balanced | 100 / 100 / 80 / 62.64 / 100 / 100 | 1 | 268192 / 90623 / 165377 | 23 / 17 | 2 | 25 / 1 / 994292 / 0 / 24 | 552 / 184 / 736 |

四份报告的 prefix_stability 均 available、stable=true、growth stable reuse=true、compact stable reuse=true、expected invalidation=true、fingerprint_changed=true、instruction_epoch_changed=true、change_reason=instruction_source_added。cache、HistoryRead 和 failure correctness 的状态与 reason 已按上一节记录；failure correctness 的标准报告投影为 not_available/source_status=not_applicable。

### Compare 结果和候选选择

- production v5 到 balanced v5：CLI exit=0，compatible=true，incompatibilities=[]，delta 非空；六维 delta 全为 0.0。compact/pre/post/headroom 的变化为 0/+6144/+32026/-32026，work distance、repeated exploration、externalization 和 token usage 不变。
- balanced v5 到 compact v5：CLI exit=0，compatible=true，incompatibilities=[]，delta 非空；六维 delta 全为 0.0；pre/post/headroom 变化为 +4096/+23508/-23508，其他工作距离和探索观察值不变。
- balanced v5 到 repeat-balanced v5：CLI exit=0，compatible=true，incompatibilities=[]，delta 非空；六维 delta 全为 0.0；pre 变化为 0，post/headroom 为 +2/-2，作为一次 opaque-ref accounting 离散事实保留。
- incompatible negative control 使用既有 D:\project\Re-UthCode-Eval-T09-3\reports\t09-3-w04-final-smoke\report.json，仅用于验证拒绝路径，不作为 v5 结论。CLI exit=0，compatible=false，delta=null；明确不兼容控制变量为 fingerprints.code、prompt、run_args、runtime、task，task_ids、task_sample_counts，以及对应 fingerprint_variants.code、prompt、run_args、runtime、task。

六维事实没有显示候选质量、安全或稳定性差异，因此没有预设改变结论。仍选择 balanced-208k 作为 Eval 候选：production-default 的 post usage 最低、headroom 最大，代表更激进的保留折中；compact-224k 的 post usage 最高、headroom 最小，未显示质量/安全收益；balanced-208k 在两者之间提供中间 post usage/headroom，并保持 64000 compact input、4 epochs 和 8192 count allowance 的参数折中。该选择没有 overall/weighted score，也没有回写生产默认或公共配置。

### D-T09-3-01 映射

- 候选参数证据：四份 v5 candidate_variant 都明确 effective_input_limit=256000；production-default 的 auto_gate_limit=243200，另两种候选的 auto gate 也以同一 256K operating window 为基准。
- 报告和选择理由证据：四份报告均 success=true、context=100，均在同一 256000 effective limit 下比较；balanced 的选择只是 Eval 参数观察，不把物理模型窗口或本次候选选择写回生产默认。
- FailureReason/cache、测试和追踪证据：failure correctness 按 source/report 两层投影，cache 仍为 not_available 并保留 reason；test_profile_candidates_are_distinct_and_include_full_parameters 断言 256000；依据 docs/work/T09-3-256KContext工程调优与通用失败语义/T09-3-256KContext工程调优与通用失败语义.md 的 D-T09-3-01，经当前 Checklist、Prompt、Feedback 和四份 v5 report 可回溯。

### D-T09-3-05 映射

- 候选参数证据：v5 报告记录 working_headroom、auto_gate_limit、retained_target、compact input/output 和 max_epochs；实际 compact/pre/post/headroom 为 production 262048/58595/197405、balanced 268192/90621/165379、compact 272288/114129/141871，repeat balanced 的 post/headroom 为 90623/165377。
- 报告和选择理由证据：四候选均完成 1 次真实 L4、post-compaction work distance=23/17，没有 compact 后 thrash；balanced 在两端保留中间参数与 usage/headroom，因此仍被选作 Eval 候选，不宣称任何阈值。
- FailureReason/cache、测试和追踪证据：cache not_available reason 和 failure correctness not_available/source_status=not_applicable 都在报告保留；tests/eval 及 context budget/compaction 回归验证 High 到 Low 与 compact 行为；追踪链为 D-T09-3-05 -> Spec/Task/Prompt -> candidate_variant -> compact facts -> compare。

### D-T09-3-06 映射

- 候选参数证据：三种 distinct candidate id 为 production-default、balanced-208k、compact-224k；每份报告完整记录参数，repeat-balanced 复跑 balanced 参数不变。
- 报告和选择理由证据：三组拥有相同 task/sample 分布和共同 control fingerprints，candidate_variants 独立于 fingerprints；六维并列、没有 overall/weighted score，balanced 的选择只按逐维相同下的 usage/headroom/参数折中。
- FailureReason/cache、测试和追踪证据：每份 report 的 failure correctness/cache 状态均保留 reason；test_profile_candidates_are_distinct_and_include_full_parameters 与 candidate_axis compare 证明候选轴不制造 incompatible；对应 D-T09-3-06、Checklist T05、冻结 Prompt、四份 v5 report 和 compare 结果互相可追。

### D-T09-3-07 映射

- 候选参数证据：candidate parameters 只存在 Eval variant，不引入生产 FailureReason、公共 API 或 cache wire；四候选使用同一 Fake Provider 和同一 failure projection。
- 报告和选择理由证据：成功 workload source 的 failure correctness=not_applicable，标准 diagnostic fact=not_available 并带 source_status=not_applicable/reason；cache_reuse=not_available 且 reason=offline Fake Provider has no provider cache telemetry，所以这些缺测没有被误当成零或质量优势，未影响 balanced 的逐维选择。
- FailureReason/cache、测试和追踪证据：真实失败 reason 的 expected/actual 比较仍由既有 compute_diagnostic_facts 保持；test_failure_correctness_compares_expected_and_observed_failure_reason、test_prefix_and_success_failure_facts_keep_unavailable_distinct、test_eval_reporting 中的聚合/render/compare 断言覆盖；没有修改 FailureReason 公共语义。D-T09-3-07 -> minimal hybrid C -> W04/T05 -> metrics/reporting -> tests/report 可回溯。

### D-T09-3-08 映射

- 候选参数和报告证据：D-T09-3-08 的 Decision -> Spec -> Task -> Prompt -> Checklist 链在本节列出的三候选参数、四份 v5 report、三组 compatible compare 和一组 incompatible compare 中均有落点。
- 选择理由证据：选择 balanced-208k 的理由仅引用六维并列和每份 JSON 的 usage/headroom/work distance，不引用历史 v4/r1 数值，也不修改冻结文字。
- FailureReason/cache、测试和追踪证据：Feedback 新增章节保留 source/report failure distinction、cache/HistoryRead reason、测试名称、命令结果和外部 report 路径；summary 只在末尾追加当前 v5 事实。因而决策、实现、验证和反馈记录能沿 D-T09-3-08 反向定位。

### 清理、验证与边界确认

- 本轮最终证据计四个 v5 attempt（每个 experiment 的 attempt=1）。四个 final attempt 均在报告生成和 compare 后分别使用 manifest-owned dedicated-root clean，清理 workspace、home、artifacts 各一个路径；四份 v5 report.json/report.md 保留。清理后四组对应组件目录均不存在、文件数为 0，四份 report.json 仍存在，大小分别为 137837、156957、171309、157006 bytes。
- 正式入口结果：python -m eval.runner --help exit=0；python -m eval.runner profile --help exit=0。四次 profile CLI 均 exit=0，均使用 Fake Provider、未使用 live。
- 精确定向结果：conda run --no-capture-output -n re-uthcode python -m pytest tests/eval -q，86 passed in 63.66s (0:01:03)；补充 prefix/report 定向命令 conda run --no-capture-output -n re-uthcode python -m pytest tests/eval/test_eval_profile.py tests/eval/test_eval_reporting.py -q，34 passed in 1.41s。
- 上下文/诊断回归：conda run --no-capture-output -n re-uthcode python -m pytest tests/test_context_budget_gate.py tests/test_context_compaction.py tests/test_t09_1_context_protocol_e2e.py tests/test_w05_diagnostics.py -q，89 passed in 23.58s。
- 架构边界：conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q，23 passed in 20.45s。
- 全量回归：conda run --no-capture-output -n re-uthcode python -m pytest -q，1246 passed, 3 skipped in 173.73s (0:02:53)。
- compileall：conda run --no-capture-output -n re-uthcode python -m compileall -q src tests eval，exit=0、无输出。
- git diff check：git diff --check，exit=0、无 diff error；Git 仅报告 LF will be replaced by CRLF 警告。
- 正式入口：conda run --no-capture-output -n re-uthcode python -m eval.runner --help，exit=0，显示 smoke/run/profile/compare/clean；conda run --no-capture-output -n re-uthcode python -m eval.runner profile --help，exit=0，显示三个候选 choices 和 profile 参数。
- UTF-8 guard：conda run --no-capture-output -n re-uthcode python C:\Users\93445\.codex\skills\uth-utf8-guard\scripts\check_utf8_docs.py eval\README.md eval\t09-3-256k-profile-tuning-summary.md docs\work\T09-3-256KContext工程调优与通用失败语义\feedback\W04-256k-eval-tuning-feedback.md，OK: 3 file(s) passed UTF-8 guard。
- repo-root clean 拒绝验证使用 eval-root=D:\project\Re-UthCode，exit=2，错误为 clean requires a dedicated Eval root；没有删除仓库内容。
- 未读取 API key、未联网、未产生费用；真实 Provider cache、latency、billing、远端长上下文和 live 结果仍为 NOT VERIFIED (authorization required)。
- 未修改生产默认、生产配置、src、公共 FailureReason、Provider cache wire、Interface 或 T06+；未触碰 docs/core-design/** 和 临时目录/**；未执行 Git commit、push、PR、merge、rebase、tag、release 或归档。Markdown 变更后执行 uth-utf8-guard，结果为 UTF-8、replacement character、常见乱码和 Markdown fence parity 通过。

## 返工第一轮补充：按 attempt 派生路线与完整合法轨迹

本节只追加针对验收剩余阻断的补充证据；前文历史反馈和上一节 v5 单 attempt 记录均不改写。本轮关闭的唯一阻断是：多 attempt 不再重复默认路线，且每条路线都有完整读取、修改、回归读取和 verifier 成功证据。

### 路线变量与实现边界

- `eval/runner.py` 的 profile attempt builder 现在按 runner 已生成的 attempt 编号传入 `route_seed = int(attempt_id) - 1`，构造 `ProfileWorkloadProvider(model_id=model_id, route_seed=route_seed)`。因此 attempt 1/2 的 seed 分别为 0/1；同一 attempt 编号在 production、balanced、compact 和 repeat-balanced 间使用相同 seed，路线变量没有进入 candidate variant 或共同 control fingerprint。
- `eval/workloads.py` 不保存标准完整实现，也不保存唯一 ToolCall 序列。它只把实际发出的 ToolCall 的最小安全投影记录为 `eval_workload.route.trace`，并依据已观察的 ToolResult、分页 EOF、EditFile 结果和修改后读取事实继续推进。
- `eval/metrics.py` 只把既有 workload diagnostics 投影为 `workload_route` diagnostic fact；没有新增第二套 prefix/cache 系统，也没有修改生产 `src/`、公共 FailureReason 或 Provider cache wire。

### 两条完整合法轨迹

四份新 v5 报告均使用 2 个样本，`task_sample_counts={"long-context-constraint":2}`，且 `finish_categories={"success":2}`。每份报告的 `facts.workload_route.values` 都包含 route seed 0 和 1；两条路线各有 25 个实际 ToolCall、17 次 `ToolResultRead` 分页，并满足 `complete=true`、`read_failures=[]`、`profile_ref_available=true`、`pages_finished=true`、`edit_attempted=true`、`edit_succeeded=true`。

两条路线的可复核差异和共同完成事实如下：

| route seed | 初始 required evidence 读取顺序 | 分页方式 | 末尾路线 | verifier |
| ---: | --- | --- | --- | --- |
| 0 | `tests/test_public_api.py` → `src/public_api.py` → `src/implementation.py` → `docs/early-constraint.md` | 17 pages，limit 从 65536/61440/65536/49152 的 seed-0 周期开始 | `EditFile(src/implementation.py)` → 复读 regression → 复读 implementation | `success=true`，4/4 checks passed |
| 1 | `tests/test_public_api.py` → `src/implementation.py` → `src/public_api.py` → `docs/early-constraint.md` | 17 pages，limit 从 61440/65536/49152 的 seed-1 周期开始 | `EditFile(src/implementation.py)` → 复读 regression → 复读 implementation | `success=true`，4/4 checks passed |

这两条路线都读取 `PROFILE_REQUIRED_EVIDENCE_PATHS` 的四个文件和 `docs/profile-evidence.txt`，先取得 externalized ref，再持续 `ToolResultRead` 至 EOF；修改前只从 `ReadFile` 返回内容推导最小替换，修改后重新读取 `tests/test_public_api.py` 与 `src/implementation.py`。测试 `test_profile_two_attempts_complete_distinct_read_edit_verify_routes` 直接运行正式 `eval.runner profile` 两 attempts，检查上述 complete/read/edit/post-read/verifier 事实，并检查报告聚合后的两个 seed 和两条不同 trace，而不只检查路径排序。

### 新 v5 候选与六维事实

共同 control fingerprint 的新 code 值为 `2e628dbe09ee05af2d3b6945bd23370c33b99b5a20b45dd28e853baec5ffbffd`；四份报告均 `model_id=eval-model`、相同 task、prompt、run_args、runtime、platform、permission 和 provider fingerprints。candidate variant 单独保留完整参数：

| report | candidate variant 参数（auto / retained / working headroom；compact input/output；max epochs；allowance） | correctness / context / exploration / efficiency / stability / safety |
| --- | --- | --- |
| v5-production | `243200 / 72000 / 12800；64000 / 4000；4；0` | `100 / 100 / 80 / 71.148 / 100 / 100` |
| v5-balanced | `208000 / 96000 / 48000；64000 / 4096；4；8192` | `100 / 100 / 80 / 72.32 / 100 / 100` |
| v5-compact | `224000 / 128000 / 32000；48000 / 3072；3；12288` | `100 / 100 / 80 / 72.7965 / 100 / 100` |
| v5-repeat-balanced | 与 balanced 完全相同 | `100 / 100 / 80 / 72.405 / 100 / 100` |

四份最终报告路径仍为：

- `D:/project/Re-UthCode-Eval-T09-3/reports/t09-3-w04-v5-production/report.json`
- `D:/project/Re-UthCode-Eval-T09-3/reports/t09-3-w04-v5-balanced/report.json`
- `D:/project/Re-UthCode-Eval-T09-3/reports/t09-3-w04-v5-compact/report.json`
- `D:/project/Re-UthCode-Eval-T09-3/reports/t09-3-w04-v5-repeat-balanced/report.json`

每份 report.json 的 `sample_count=2`、`task_sample_counts={long-context-constraint:2}`，没有 overall 或 weighted score。四份报告的 compact 均为 `1`；production/balanced/compact/repeat-balanced 的 `pre_compact_usage` 分别为 `262048/268192/272288/268192`，post usage 分别为 `58595/90621/114129/90623`，post headroom 分别为 `197405/165379/141871/165377`。四者 `provider_requests_after_compaction=23`、`ToolResultRead=17`、`repeated_exploration=2`；externalization 均为 `attempts=25, externalized=1, externalized_bytes=994292, failed=0, inline=24`。HistoryRead 均 `not_available`，reason 为 `the offline profile workload has no valid HistoryRead ref`；cache 均 `not_available`，reason 为 `offline Fake Provider has no provider cache telemetry`。

### prefix、failure correctness 与报告精度

- prefix 证据仍来自真实 `ApplicationContextService.compose_generation_request`、`ContextCompiler` 和 `InstructionLoader`。四份报告的 conversation growth before/after 均 `stable_reuse=true`、`fingerprint_same=true`、`prefix_change_reason=stable`；compact pre/post 也均 `stable_reuse=true`、`fingerprint_same=true`、`prefix_change_reason=stable`。
- 同一 probe 在 dedicated attempt artifacts 下实际创建 `project/AGENTS.md`，重新 load session 后再次调用 production request composition。四份报告均观察到 `instruction_epoch=1→2`、`prefix_changed=true`、before/after stable prefix fingerprint 不同、`fingerprint_changed=true`，`loader_change_reason`、request metadata reason 和 snapshot reason 均为 `instruction_source_added`；`instruction_source={kind:project, change:source_added, path:project/AGENTS.md}`，tool schema fingerprint 保持相同。每个最终候选的 report.json 都保存 before/after、source、phase、message_count、fingerprint 和 reason。
- 成功 workload source 的 `eval_workload.failure_correctness` 仍为 `status=not_applicable`；标准 report diagnostic fact `facts.failure_correctness` 准确投影为 `status=not_available`、`source_status=not_applicable`，并保留 reason `successful workload; failure matrix is verified separately`。这不是把 source 的 not_applicable 错写成 report 的 status。

### compare 与选择

| compare | compatible | incompatibilities | 六维 candidate-baseline delta（correctness/context/exploration/efficiency/stability/safety） | 关键 fact delta |
| --- | --- | --- | --- | --- |
| production → balanced | `true` | `[]` | `0 / 0 / 0 / +1.172 / 0 / 0` | pre `+6144`，post `+32026`，headroom `-32026` |
| balanced → compact | `true` | `[]` | `0 / 0 / 0 / +0.4765 / 0 / 0` | pre `+4096`，post `+23508`，headroom `-23508` |
| balanced → repeat-balanced | `true` | `[]` | `0 / 0 / 0 / +0.085 / 0 / 0` | pre `0`，post `+2`，headroom `-2` |

使用已有 `t09-3-w04-final-smoke/report.json` 对新 v5 balanced 做负向 incompatible compare，结果为 `compatible=false`、`delta=null`。机器可读不兼容控制变量为：`fingerprints.code`、`fingerprints.prompt`、`fingerprints.run_args`、`fingerprints.runtime`、`fingerprints.task`、`task_ids`、`sample_count`、`task_sample_counts`、`fingerprint_variants.code`、`fingerprint_variants.prompt`、`fingerprint_variants.run_args`、`fingerprint_variants.runtime`、`fingerprint_variants.task`。

根据新证据仍选择 `balanced-208k`，不是预设结论：所有候选 correctness/context/exploration/stability/safety 均相同且 verifier 全成功；compact 虽有最高本轮 efficiency，但 post usage=114129、headroom=141871 且 working headroom=32000；production 的 headroom=197405 但 working headroom=12800、auto gate 更靠近上限；balanced 的 post usage/headroom 和 working headroom=48000 位于两者之间，并在 repeat compare 中只出现 +2 usage/-2 headroom 的离散差异。因此选择是逐维事实和上下文余量的折中，不是 overall/weighted ranking，也没有改写生产默认。

### 决策映射与追踪

- **D-T09-3-01**：候选参数在四个 `candidate_variants` 中完整记录；六维并列分数、compact/usage/headroom、路线 seeds/traces、verifier checks 和 compare 均在对应 report.json；选择理由只使用本轮新 v5 事实，测试 `test_profile_two_attempts_complete_distinct_read_edit_verify_routes` 与四候选 profile CLI 是可复核入口。
- **D-T09-3-05**：conversation growth、compact 前后 stable reuse 和 instruction source added invalidation 均由 production request facts 观察；`workload_route` 只投影实际 ToolCall，不规定唯一序列；prefix fact、attempt trace 和 `test_profile_prefix_probe_uses_production_facts_for_reuse_and_invalidation` 提供 source→report→test 追踪。
- **D-T09-3-06**：同一 attempt seed 跨三候选保持一致，candidate variant 与共同 control fingerprint 分离；production/balanced、balanced/compact、balanced/repeat 三组 compatible compare 和 final-smoke incompatible compare 验证了控制变量合同。
- **D-T09-3-07**：FailureReason 公共语义未改；successful workload source/report 的 `not_applicable`/`not_available` 区分、HistoryRead/cache unavailable reason、`workload_route` 的 read/edit/verifier facts 和既有 failure correctness 测试均保留。`tests/eval` 及上下文/诊断回归证明 unavailable 仍保持 unavailable。
- **D-T09-3-08**：报告路径、候选参数、sample counts、fingerprints、六维结果、prefix/failure/cache 事实、三组 compatible compare、一次 incompatible compare、attempt 清理和验证命令均记录在本节；选择仍为 `balanced-208k`，没有修改生产默认或扩展 T06+。

### attempt 清理、正式入口与验证

- 本轮实际创建并可由命令/manifest 复核的外部 attempt 共 11 个：初次路线探针 `t09-3-w04-route-debug/1` 1 个；首次 balanced 两-attempt 验证 `t09-3-w04-v5-balanced/1-2` 2 个；最终四个 v5 experiment 各 2 个共 8 个。compact 的错误 candidate 名称在创建 attempt 前即被拒绝，没有产生 attempt。上述 11 个 attempt 均使用 manifest-owned dedicated-root `eval.runner clean` 清理了 workspace/home/artifacts；清理后这些组件文件数为 0，最终四个 v5 目录各只保留 `report.json` 与 `report.md`。路线探针报告仍作为 report 保留，未把它计入最终四候选结论。
- `conda run --no-capture-output -n re-uthcode python -m eval.runner --help`：exit `0`；显示 `smoke/run/profile/compare/clean`。
- `conda run --no-capture-output -n re-uthcode python -m eval.runner profile --help`：exit `0`；显示三个 candidate choices 和 profile 参数。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/eval -q`：`87 passed in 80.81s`。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/eval/test_eval_profile.py::test_profile_two_attempts_complete_distinct_read_edit_verify_routes tests/eval/test_eval_reporting.py -q`：`27 passed in 40.97s`。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_context_budget_gate.py tests/test_context_compaction.py tests/test_t09_1_context_protocol_e2e.py tests/test_w05_diagnostics.py -q`：`89 passed in 10.31s`。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q`：`23 passed in 6.10s`。
- `conda run --no-capture-output -n re-uthcode python -m pytest -q`：`1247 passed, 3 skipped in 151.21s`。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests eval`：exit `0`、无输出。
- `git diff --check`：exit `0`；仅输出既有 LF will be replaced by CRLF warnings，无 diff error。
- repo-root clean 拒绝验证：`conda run --no-capture-output -n re-uthcode python -m eval.runner clean --eval-root D:\project\Re-UthCode` 返回 exit `2`，错误为 `clean requires a dedicated Eval root`，未删除仓库内容。
- live Provider、远端 cache/latency/billing、真实远端长上下文和 live 费用仍未验证；本轮未读取 API key、未联网。
- 本轮没有修改生产默认、产品配置、`src/**`、公共 FailureReason、Provider cache wire、Interface、CI/依赖/正式 CLI 或 T06+；没有触碰 `docs/core-design/**`、`临时目录/**`；没有执行 Git commit、push、PR、merge、rebase、tag、release 或归档。

## 返工第二轮：将 balanced-208k 接入 256K 生产默认（2026-08-27）

### 返工原因与边界

包级审核发现 W04 的历史结论把 `balanced-208k` 仅作为 Eval 候选，生产 `ContextBudget` 仍按历史公式得到 `243200/72000/12800/4000/0`，没有满足冻结 Tasks 对“选定初始工程默认进入正式生产链”的要求。本轮只关闭该 P1：不修改 Spec、Tasks、Prompt、Checklist、候选比较结论或公共配置/API，不新增 Context policy/Manager/Registry，不触碰真实 Provider、网络、费用、`docs/core-design/**` 或 `临时目录/**`，不执行 Git 写操作。

### 实际修改

- `src/uthcode/core/context.py`：effective input 为 `256_000` 时，正式 resolver 使用已选 `balanced-208k` 的 working headroom `48_000`、High Water `208_000`、retained/Low Water `96_000`、fine timeline `16_000`、compaction input/output `64_000/4_096`、count allowance `8_192`。`ContextBudget.from_limits` 的未指定 allowance 只对该 256K Operating Window采用 `8_192`；显式 allowance 及 compact 内部归零仍保持原语义。其它 effective window 继续使用原有有界自适应派生，因此 configured/provider 小窗口不会被 balanced 常量放大。
- `tests/test_context_budget_gate.py`：新增 Core 精确 profile 合同、正式 `UthCodeApplication -> AgentRun -> Turn` 请求/diagnostics 精确 profile 断言和非 256K 窗口合法性断言（`0 < retained < auto < effective`、compact budget 合法）。
- `tests/test_t09_1_context_protocol_e2e.py`：High→Low fake provider 的低水位 raw count 按实际 provider/budget safety allowance 计算，保留 epoch 2 到 Low Water 的既有迟滞合同；该调整只修正测试夹具对新选定 allowance 的计数预期。
- `eval/t09-3-256k-profile-tuning-summary.md`、`eval/README.md`：把历史 `production-default` 明确标为采纳前公式 baseline，并追加 balanced 已接入正式 256K resolver 的事实与参数。
- `docs/context/A01-AgentRuntime/AgentRuntime-Context.md`、`A03-State/State-Context.md`、`A04-Orchestration/Orchestration-Context.md`、`docs/Context-Index.md`：同步当前生产 profile 与非 256K 收紧事实。

`eval/profile.py` 的 `production-default` candidate id/历史参数没有删除或改写，以保留 W04 原始报告 compare 的可复核 baseline；它不再被当作当前生产 resolver 的代表。正式生产默认的事实来源是 `balanced-208k` 的冻结 Eval 选择及本轮 Core resolver 实现。

### 验证结果

- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_context_budget_gate.py tests/test_context_compaction.py tests/test_t09_1_context_protocol_e2e.py tests/test_application_runs.py tests/test_w05_diagnostics.py -q`：`139 passed`。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/eval -q`：`87 passed in 121.82s`。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q`：`23 passed`。
- `conda run --no-capture-output -n re-uthcode python -m pytest -q`：`1251 passed, 3 skipped in 232.37s`。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests eval`：exit `0`，无输出。
- `conda run --no-capture-output -n re-uthcode python -m pip check`：`No broken requirements found.`
- `git diff --check`：exit `0`；仅有 Windows `core.autocrlf` 的 LF→CRLF 提示，无 whitespace error。

未授权的真实 Provider cache/latency/billing、远端 tokenizer、远端长上下文和 live 结果仍为 `NOT VERIFIED (authorization required)`；本轮未读取 API key、未联网。Checklist 未改写或重新勾选，冻结 Spec/Tasks/Prompt/Checklist 未修改。

### 文档编码补充

对本轮修改的 8 个 Markdown 文件执行 `uth-utf8-guard`：`OK: 8 file(s) passed UTF-8 guard`，UTF-8、replacement character、常见 mojibake 与 Markdown fence parity 均通过。
