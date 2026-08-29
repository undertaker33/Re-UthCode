# W02 Provider Prefix Cache 实施提示词

请在 W01 已完成并通过审查后，完整实施 T09-3 的 T03；只处理 Provider cache hint/control、usage availability 与对应 deterministic fixtures，不得实施 FailureReason 或 Eval tuning。

## 开工前必须读取

1. `AGENTS.md`
2. `docs/README.md`、`docs/Context-Index.md`
3. `docs/rules/WorkPackageRules.md`、`docs/rules/UserDecisionBoundary.md`
4. `docs/OutstandingDebtList.md`
5. T09-3 原始任务书、Spec、Tasks、Checklist
6. `feedback/W01-context-profile-low-water-feedback.md`
7. Tasks T03 定位的三个 Provider Integration、`application/provider_usage.py`、相关 tests、当前 instruction/context fingerprint 实现
8. 实施时最新官方 OpenAI Responses Prompt Caching 与 Anthropic Prompt Caching 文档，以及当前安装 SDK signature

## 已确认决策

- Core/Application 只提供稳定 UthCode request facts；Provider cache wire 字段只存在于 Integration。
- 当前依赖下 OpenAI Responses 使用由稳定前缀事实派生的 `prompt_cache_key`；不发送缺少可靠模型 capability authority 的 model-gated cache options，也不按模型名猜测。
- Anthropic 在 tools -> system -> messages 的官方前缀顺序上设置稳定 instructions/tools 前缀末端的显式 `cache_control` breakpoint；不复制 Tool Schema。若真实 SDK/API事实变化，以官方资料和 fixture为准，无法可靠确认则停止该 Provider猜测发送并写 Feedback。
- OpenAI-compatible 默认不发送 OpenAI Responses专有缓存参数；现有配置无 capability authority时保持兼容。
- cache metric 缺失是 `not_available`，不是 measured zero；真实报告为零时保留 available/provenance。
- 普通 conversation growth/Timeline compact 不改变稳定 instruction/tool prefix；真实 AGENTS/instruction/tool schema/model identity 变化才形成 expected invalidation。
- 不新增 CacheManager/Registry、Core cache DTO、Provider KV lifecycle、本地 Cache DB 或第三方依赖。

## 修改范围

- T03 Tasks 列出的三个 Provider Integration、`application/provider_usage.py`、相关 integration/diagnostics/fingerprint tests。
- `pyproject.toml` 原则上不改；只有实施时官方 SDK事实证明当前声明版本不支持冻结最小字段时，按 Tasks规则处理并完整回归。
- 首次实施创建 `feedback/W02-provider-prefix-cache-feedback.md`；返工只追加。
- 只勾选 T03 已验证 Checklist。

禁止修改 Core FailureReason、Interface 失败展示、Context profile/Low Water（除非修复 W01 已确认的直接回归并在 Feedback说明）、Eval runner、冻结文档或 Git 状态。

## 实施约束

1. 使用 Conda 环境 `re-uthcode`，先通过 fake client/request fixture 固化 wire shape，再作最小实现。
2. OpenAI key 必须有界、确定性，只依赖 stable prefix/tool fingerprint 与必要的稳定 model/request identity；不得包含 conversation正文、secret 或 Provider native object。
3. Anthropic system/tools block marker必须与 token count/request shape一致或由测试证明 token-equivalent；tools仍通过正式 Tool System映射。
4. Compat 测试必须显式断言无专有 cache fields；不得为了未来端点增加无调用方 capability config。
5. 保留现有 cache usage mapper；只有真实缺口才修改，不重写已工作的 availability/provenance链。
6. 所有验收离线，禁止网络、真实 key、费用调用；live收益继续未验证。
7. 修改治理 Markdown时使用 `uth-utf8-guard`；本 Worker原则上只写 Feedback和勾选 Checklist。

## 测试与验收

至少执行：

```powershell
conda run --no-capture-output -n re-uthcode python -m pytest tests/test_openai_responses_integration.py tests/test_anthropic_integration.py tests/test_openai_compat_integration.py tests/test_w05_diagnostics.py -q
conda run --no-capture-output -n re-uthcode python -m pytest tests/test_context_compiler.py tests/test_application_runs.py -q
conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q
git diff --check
```

另执行 Checklist 的 cache field 否定扫描，并验证 same prefix/different conversation、instruction change、tool schema change、model identity change、missing metric、measured zero 和 Compat no-field。

## Feedback 要求

Feedback 必须记录官方文档链接/日期、SDK版本与 signature 证据、OpenAI key事实输入、Anthropic breakpoint位置、Compat保持不发送的依据、usage availability、expected/unexpected invalidation、修改文件、精确测试结果、未验证 live项、风险和遗留负担。不得引用或记录 secret/raw request正文。

## 冻结决策覆盖

- 必须在 W02 Feedback映射 D-T09-3-04、06、08，并说明未改变 D-T09-3-01～03/05/07。
