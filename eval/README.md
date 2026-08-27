# UthCode 私有 Eval v0

`eval` 是仓库级、手动运行的开发工具，不是 `uthcode` 的公开 CLI、CI 任务或运行时能力。固定任务集包含七题：

`single-file-control`、`cross-file-evidence`、`todo-long-task`、`plan-only`、`ask-user-resume`、`permission-boundary` 和 `long-context-constraint`。

## 安装与固定条件

在仓库根目录使用 Conda 环境 `re-uthcode`。默认 Fake 路径只使用标准库、现有 UthCode Application 和版本化 fixture，不读取 API key、不访问网络，也不产生模型费用：

```powershell
conda run --no-capture-output -n re-uthcode python -m eval.runner --help
```

每次 attempt 都创建独立的 `workspace`、`home` 和 `artifacts`。运行根目录必须是仓库外、专用且由 `.uthcode-eval-root.json` 绑定当前仓库的物理目录，例如：

```text
C:\private-eval-root\
├── workspaces\<experiment>\<task>\<attempt>\
├── homes\<experiment>\<task>\<attempt>\
├── artifacts\<experiment>\<task>\<attempt>\
├── cache\
└── reports\<experiment>\
```

路径不能是源码仓库、仓库子目录、用户 home、文件系统根或链接回指的目录。fixture 只从仓库复制到 attempt workspace，运行不会回写 `eval/tasks/**/fixture`。

## 手动入口

运行单题 Fake smoke：

```powershell
conda run --no-capture-output -n re-uthcode python -m eval.runner smoke `
  --task single-file-control `
  --experiment fake-smoke `
  --eval-root C:\private-eval-root
```

运行七题套件：

```powershell
conda run --no-capture-output -n re-uthcode python -m eval.runner run `
  --suite all `
  --experiment fake-suite `
  --eval-root C:\private-eval-root
```

Fake Provider 只用于验证 `task -> external attempt -> Application Run/Turn -> verifier -> report` 的离线链路，并按任务声明完成 AskUser 或 PlanReview typed pause/resume；permission-boundary 还会触发一次未授权的外部读取以验证阻断。它不注入标准答案或完整 Patch；正确性始终由 verifier 的 hard/partial/forbidden checks 决定。

W04 profile workload 的 Provider 只根据已观察的 ToolResult、外部页边界和文件内容推进未完成目标；读取批次、页大小和复读顺序允许多个有效路径。实现修改由实际 `ReadFile` 结果推导为一个局部 `EditFile`，不保存标准完整 Patch，也不规定唯一 ToolCall 序列。多-attempt profile 由 runner 按 attempt 编号传入受控 `route_seed`；报告的 `workload_route` fact 保存实际 trace、完整读取/分页/编辑/复读和 verifier 前置路线事实。

由于 Fake 不伪造模型对 fixture 的修改，除 `plan-only` 的只读成功路径外，单题 Fake smoke 默认会如实产生 `agent_failure`/verifier failure；这不是 baseline 分数，而是用于验收失败归因、artifact 和 report 链路。真实模型运行或独立的 verifier gold/partial/forbidden 测试才用于评估任务正确性。

比较两个报告：

```powershell
conda run --no-capture-output -n re-uthcode python -m eval.runner compare `
  --baseline C:\private-eval-root\reports\baseline\report.json `
  --candidate C:\private-eval-root\reports\candidate\report.json
```

比较前会校验代码、任务、模型、Provider、Prompt、配置、权限、运行参数和平台等全部指纹，以及任务集合、样本数和 schema 版本。任何不兼容都只返回原因，不生成 delta。
报告还会保存 `task_sample_counts`。Compare 会先对每份外部 JSON 报告校验：映射非空、键集合等于 `task_ids`、所有计数为正整数且总和等于 `sample_count`；随后才要求两边每个任务的样本次数映射完全一致。仅总样本数相同不能通过兼容性检查。

## T09-3 256K 离线候选调优

W04 的长上下文候选只通过私有、可替换的 Eval seam 复用现有 `ContextBudget` resolver 和 `ApplicationContextService.compact_async`；它们不是 `create_application` 的公开参数，也不会写入项目或用户配置。候选轴单独记录完整参数，不能混入控制指纹。当前固定候选为：

| Candidate | Effective / auto gate | Retained / fine | Compact input / output | Max epochs / count allowance |
| --- | ---: | ---: | ---: | ---: |
| `production-default` | `256000 / 243200` | `72000 / 16000` | `64000 / 4000` | `4 / 0` |
| `balanced-208k` | `256000 / 208000` | `96000 / 16000` | `64000 / 4096` | `4 / 8192` |
| `compact-224k` | `256000 / 224000` | `128000 / 12000` | `48000 / 3072` | `3 / 12288` |

运行同一受控长负载：

```powershell
conda run --no-capture-output -n re-uthcode python -m eval.runner profile `
  --candidate balanced-208k `
  --experiment t09-3-w04-balanced `
  --eval-root C:\private-eval-root `
  --attempts 1 `
  --prompt-salt t09-3-w04 `
  --model eval-model
```

该负载在 attempt 外部 workspace 生成确定性的约 `988400` 字节证据文件，并要求多轮探索、`ToolResultRead` 读完外部化结果、重读约束和实现、从观察到的实现内容生成局部编辑以及回归验证；每次候选还使用相同的 300 个可压缩历史 turn。它覆盖首次和后续 compact、compact 后继续工作、稳定前缀以及预期前缀失效事实。工作区和报告必须留在专用外部 Eval 根；生成的大文件不会进入仓库。

候选验收与调优证据分开读取：验收看 verifier、finish category、六维状态、失败语义和安全检查；调优看 token、compact 次数、compact 前后 usage/headroom、compact 后工作距离、重复探索、外部化/读回和前缀事实。不存在跨维度总分，也不要求候选在所有观察值上优于 baseline。Fake Provider 没有 cache read/write telemetry，当前负载没有有效 `HistoryRead` ref；成功 workload source 的 failure correctness 为 `not_applicable`，标准 report diagnostic fact 投影为 `not_available`，并保留 `source_status` 与 reason。真实 Provider 的 cache、延迟、费用和远端长上下文结果仍是 `NOT VERIFIED (authorization required)`。

## 真实 Provider 与成本

真实 Provider 不是默认路径。只有同时提供 `--live`、`--live-authorized`、Provider kind、`--model <真实模型标识>` 和 API-key 环境变量名称时，runner 才允许进入真实调用链；`--model` 是必填的实际远端模型 ID，并会以 `model_id` 写入每个 attempt 的不可变指纹和聚合报告。独立 Eval CLI 保留 `--api-key-env` 参数，在边界解析为新的内部凭据；它不形成 `config.toml` 双轨。API key 的真实值绝不写入参数、报告或日志。授权必须来自用户对网络访问与费用的明确决定。

真实运行示例（仅示例，不代表已授权或已执行）：

```powershell
conda run --no-capture-output -n re-uthcode python -m eval.runner run `
  --suite all `
  --experiment real-baseline `
  --eval-root C:\private-eval-root `
  --provider-kind anthropic `
  --model claude-sonnet-4-20250514 `
  --api-key-env ANTHROPIC_API_KEY `
  --live `
  --live-authorized
```

本次 W03 未获得该授权，因此七题真实 baseline 的状态是 `NOT VERIFIED (authorization required)`，没有执行网络调用或读取秘密值。固定模型、次数和实验 ID 应在另行授权后由用户确认并记录。

## 结果解释

报告并列展示 `correctness`、`context`、`exploration`、`efficiency`、`stability`、`safety` 六维，不生成单一总分。每维保留状态、原始事实、分数、证据引用、逐次分数和中位数；缺少结构化事实使用 `not_available`，不把缺测写成零。

`correctness` 只接受 verifier 结果，模型 final 不能覆盖失败。`safety` 单独保留 hard failure，不能被其他维度平均抵消。Context diagnostics 通过 Application 公共投影提供 selected/omitted block ID、预算使用、compact、instruction epoch、stable prefix fingerprint/change reason；投影不复制 Prompt/History/Tool Result 内容。

每个 attempt 还保存 `diagnostic_facts`，并在聚合报告的 `facts` 节中比较以下观察值：`success`、`tokens`、`tool_calls`、`compact_count`、`pre_compact_usage`、`post_compact_usage`、`post_compact_headroom`、`work_distance`、`workload_route`、`rediscovery`、`repeated_exploration`、`externalization`、`history_read`、`prefix_stability`、`cache_reuse` 和 `failure_correctness`。聚合层保留 unavailable reason，并保留结构化 fact 中稳定的非数值字段（例如 prefix change reason）；`compare` 会在兼容指纹与样本集合上给出 `delta.facts`，但不会把候选必须优于 baseline 作为 pytest 或报告兼容条件。

Provider cache read/write 只有在现有 Usage mapper 明确提供字段时才标记为 `available`，并记录安全的字段路径 provenance；Provider 不支持或未提供字段时为 `not_available`，默认的数值 `0` 不视为测量值。Application diagnostics 也不会额外复制 Runtime credential、完整大型 Tool Result、Provider native payload 或未脱敏异常。Context diagnostics 记录 configured/provider/effective limits、Pressure/Preflight、Auto/Hard、Timeline 与 Compact outcome；Eval 保持 success、tokens、tool calls、compaction 和 pressure 等并列观察值，不把任一 tuning default 变成产品成功阈值。

## 清理与回滚

只清理一个由 manifest 精确绑定的 attempt：

```powershell
conda run --no-capture-output -n re-uthcode python -m eval.runner clean `
  --eval-root C:\private-eval-root `
  --experiment fake-smoke `
  --task single-file-control `
  --attempt 1
```

clean 会在删除前重新校验专用根、manifest 身份、三个组件的物理 containment 和链接状态；缺少任一标识、manifest 或边界不匹配都会拒绝。源码仓库目录不能作为 clean 目标。回滚即删除对应的 manifest-owned attempt；报告和其他 experiment 不受影响。Bash 若由被测 Agent 调用，仍是当前 OS 用户权限下的 unsandboxed process execution，Eval 不把它描述为 Sandbox。

运行产物应始终位于专用外部根目录；不要用新增 ignore 规则掩盖仓库污染。完成后可用 `git status --short` 和 attempt 的 `repository_status_delta` 检查源码仓库是否保持原样。

## W04 返工补充

v5 长负载通过真实 `ApplicationContextService.compose_generation_request`、`ContextCompiler` 和 `InstructionLoader` 记录 conversation growth、compact 前后 stable reuse，以及 project instruction source 加入后的 expected invalidation。报告中的成功 workload source 与标准 diagnostic fact 保持区分：前者为 `not_applicable`，后者为 `not_available` 并保留 reason 与 `source_status`。
每个最终候选用两个 attempts 记录 route seed 0/1；`workload_route` 的机器可读值包含 required evidence 读取、`ToolResultRead` 到 EOF、`EditFile`、修改后复读和 `complete`，并由 verifier success 与定向测试共同验收。
