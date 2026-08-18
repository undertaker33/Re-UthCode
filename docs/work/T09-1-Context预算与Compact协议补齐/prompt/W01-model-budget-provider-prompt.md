# W01：模型预算与 Provider 能力实施 Prompt

请完整读取并执行本文件。你负责 T01，严格只完成模型窗口、Provider optional capability 与双 Gate 预算基础，不提前实现 Transcript/Timeline、L1-L5 或生命周期接入。

## 必须先读

1. `AGENTS.md`
2. `docs/README.md`
3. `docs/Context-Index.md`
4. `docs/rules/WorkPackageRules.md`
5. `docs/work/T09-1-Context预算与Compact协议补齐/T09-1-Context预算与Compact协议补齐.md`
6. 同目录的 `-spec.md`、`-tasks.md`、`-checklist.md`
7. `docs/context/A03-State/State-Context.md`
8. T01 Tasks 列出的源码和测试；当前事实以 `src/ + tests/` 为准。

使用 Conda 环境 `re-uthcode`。确认 HEAD 仍基于需求指定提交或其仅含本工作包/前序 Worker 改动的后继；若出现无关用户改动，保留并避让。

## 冻结决策

- 每个 runnable model 的 `context_window=C` 必填且为 positive int，不存在 258K fallback。
- reliable Provider input ceiling 只收紧：`E=min(C, ceiling)`；能力缺失时 E=C，不虚构 metadata。
- Provider count 是高可信度 estimate，不是绝对事实；local estimate 也进入同一 typed contract，uncertainty 集中解析。
- Auto Gate 是 proactive pressure，Hard Gate 是最终 request safety；两者可以同时为 true/false 的不同组合。
- headroom/adaptive retained profile 的具体默认值是单点内部 tuning，不是用户配置或公共 API；小窗口收缩、大窗口绝对封顶。
- Anthropic SDK 类型截止在 Integration；OpenAI Responses/Compat 不为了统一接口伪造 limits/count。
- 无新增第三方依赖、Model Catalog、自动联网枚举 UI 或独立 headroom 配置系统。

## 修改范围

只修改 T01 Tasks 列出的文件及其必要的机械 import/export/test fixture 跟随。`core/` 不得导入 SDK/network/fs；Application 只消费 UthCode-owned DTO。

已有 Core request preparer/overflow hook 支持 awaitable，不属于本 Worker 重构范围。不要实现 Timeline、Session v2、semantic compaction、HistoryRead、async command 或文档包级收口。

## 实施要求

- 先用测试表达 C/E、count source/uncertainty、Auto/Hard、25K/1M profile 不变量，再做最小实现。
- `ModelProfile`、loader、template、single-model/test factories 必须全部显式提供 C；测试默认值只能位于 fixture/helper，不能成为生产 fallback。
- Provider capability 保持 optional；不强迫所有 Provider 实现新方法。
- Anthropic limits/count 复用正式 request serialization shape，fake SDK/client 覆盖成功、absent、受控失败和 SDK type 截止。
- 不把任何 API key、raw request 或异常正文写入 diagnostics。
- 如当前 SDK 的真实 API 已与原始需求发生实质冲突，停止该范围，在 Feedback 记录证据并交用户决定；普通 fixture/typing 差异自行修复。

## 验证与交付

至少执行 T01 Checklist 的完整命令，再执行与 `application/bootstrap.py`、Provider integration、architecture boundary 直接相关的定向测试。精确记录命令、passed/failed/skipped 与未验证项。

首次执行时创建：

`docs/work/T09-1-Context预算与Compact协议补齐/feedback/W01-model-budget-provider-feedback.md`

Feedback 必须包含：实际改动、C/E/Auto/Hard contract、Anthropic conversion、测试结果、与任务书差异、风险、未完成项和遗留负担检查。只可把 T01 Checklist 中已用证据完成的复选框改为 `[x]`；不得修改 Checklist 文字、Spec、Tasks、Prompt 或原始需求。

未经用户明确要求，不执行 Git commit/push/merge/rebase/tag/release，不归档工作包。
