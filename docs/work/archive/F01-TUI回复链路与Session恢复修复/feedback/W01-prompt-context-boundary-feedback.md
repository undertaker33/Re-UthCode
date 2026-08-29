# W01 Feedback：Prompt 与 Context 消息边界

## 范围与结论

- 本次只实施 F01/T01：Core Context/Prompt、Application composition、Provider request mapping 的边界修复及对应测试。
- 未修改 reasoning 生命周期、History schema、Session、process tool、Tool 摘要、TUI 或其他 Worker Feedback。
- 未执行任何 Git add、commit、push、checkout、merge 或其他 Git 写操作。
- T01 定向范围内，当前用户 `？` 可以作为独立的最后一条 user Message 进入正式 request；动态 Context 不再写入该 Message 的 parts。

## 根因与唯一正式链路

原 `messages_from_context_snapshot()` 先收集所有 Contextual block，随后把它们作为 `[Context]` parts 预置到最后一条 user Message。这样 runtime/environment 与当前用户共用一个 Message，短输入 `？` 不再是逐字独立正文；Provider 只能把已经污染的 user 内容继续发送。

原 `core.prompt.build_system_prompt()` 没有 `src/` 生产 caller，Application 实际走的是 Context Compiler；但旧 builder 仍被测试直接调用，形成生产/测试双轨。已删除该孤立 builder、`SystemPromptContext` 及其 section parser，并同步移除 Core 导出。`PromptSection` 仅保留为 runtime section 的内部结构，正式 request 仍由 Application 唯一组合入口负责。

正式组合链路为：

```text
AgentRun/Application generation
  -> ApplicationContextService.compose_generation_request()
  -> ContextCompiler.compile()
  -> instruction_text_from_context_snapshot() + messages_from_context_snapshot()
  -> Provider-specific request mapper
```

`compose_generation_request()` 的 counted/finalize 两次调用仍是同一个 Application 组合入口，不存在独立 System Prompt 构造路径。

## 实施内容

- `messages_from_context_snapshot()`：每个 Contextual source 独立投影为一个带 `[Context]` 结构标记的 user Message；不与当前用户、相邻 user、steering 或相同文本做 join/dedup。当前用户 Message 不再被修改。
- 保留 T09 的 typed source、authority、plane、provenance、stable prefix、budget、Tool schema 单一来源和 hard gate 语义；Runtime/Environment 仍是 Contextual source，不升级为 system role。
- Provider adapter 原有“每个 UthCode Message 一个 provider message/input item”的映射未改动；三套 integration fixture 增加了 Context、steering、重复文本和 `？` 尾部的显式 request 断言。
- 删除无生产调用方的 `build_system_prompt()`、`SystemPromptContext` 和旧 section parser；`PromptSection` 只由 runtime section 使用；更新对应旧 builder 测试为 typed Instruction source/runtime section 测试。

## 修改文件

- `src/uthcode/core/context.py`
- `src/uthcode/core/prompt.py`
- `src/uthcode/core/__init__.py`
- `tests/test_context_compiler.py`
- `tests/test_system_prompt.py`
- `tests/test_project_instructions.py`（仅因删除死 builder 后清理其直接调用）
- `tests/test_openai_compat_integration.py`
- `tests/test_openai_responses_integration.py`
- `tests/test_anthropic_integration.py`

## 测试与审计证据

先补失败回归时，Context projection 与双轨审计测试结果为 `3 failed, 9 passed`；失败分别复现了 Context 污染 current-user tail 和孤立 builder 存在。

实现后执行：

- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_system_prompt.py tests/test_context_compiler.py tests/test_provider_contract.py tests/test_openai_compat_integration.py tests/test_openai_responses_integration.py tests/test_anthropic_integration.py -q`：`90 passed, 3 skipped`。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q`：`23 passed`。
- 补充 `tests/test_context_compiler.py tests/test_system_prompt.py tests/test_project_instructions.py`：`25 passed`。
- `git diff --check`：无错误。
- `rg -n "build_system_prompt\\(|SystemPromptContext" src tests`：`0 references`；生产组合调用集中在 `ApplicationContextService.compose_generation_request()`，由 Application generation 的 compose/finalize 两个阶段复用。

三 Provider request fixture 均断言以下顺序和边界：`[Context] runtime`、`steering`、`duplicate`、`duplicate`、`？` 是五个独立 user 输入，最后一项精确等于 `？`。

## Checklist 证据

已在 F01 Checklist 仅勾选有精确证据的 T01 项：

- 定向测试命令通过：`90 passed, 3 skipped`。
- 正式 request 的 `？` 是独立、逐字的最后 user 输入，且不包含 runtime/environment/provider/model 文本。
- ordinary history 伪造 instruction/system/runtime 标签仍由 typed authority 规则拒绝进入 Instruction Plane；Instruction prefix 顺序与 stable fingerprint 回归通过。
- builder/reference caller audit 无 `build_system_prompt()` / `SystemPromptContext` 调用，正式组合集中于 Application Context service。

T01 第 3 项暂未勾选：本次 fixture 已覆盖相邻 user、steering、重复文本不拼接/不去重，但没有单独构造 runtime/environment 变化前后的 identity 对比断言。

## 偏差、未完成项与风险

- 为删除无生产调用方的旧 builder，修改了 `tests/test_project_instructions.py`；这是清理直接调用的必要范围，不是新增能力。
- T01 之外的旧测试中仍有若干断言假设 Context 会被嵌入最后 user Message。一次非 T01 兼容性扫描结果为 `163 passed, 17 failed`，失败集中在 `test_application_runs.py`、`test_t08_e2e.py` 和 `test_cli.py` 的旧 projection/helper 断言；本 Worker 未修改这些 T02+ 或跨包测试，后续 Worker/包级验收需按新的独立 Message 语义复核。
- 未验证真实 Windows Terminal TUI 展示、reasoning 生命周期、Session `/resume` hydrate、History replay 和最终 PR；这些属于 T02～T11，不能由本 Feedback 推断为已完成。

## UTF-8 guard

- files checked: `docs/work/F01-TUI回复链路与Session恢复修复/feedback/W01-prompt-context-boundary-feedback.md`、`docs/work/F01-TUI回复链路与Session恢复修复/F01-TUI回复链路与Session恢复修复-checklist.md`
- result: 待写回后执行 `check_utf8_docs.py` 验证 UTF-8、乱码标记和 Markdown fence。
- repaired encoding issues: none

## 返工第一轮（Reviewer CHANGES REQUESTED）

### 原因

- P1：缺少 Application composition 在 Runtime/Environment 变化前后的 current-user identity 对比，以及相邻 user、steering、重复文本的不同事实回归。
- P1：新 Context message projection 使 `test_application_runs.py`、`test_t08_e2e.py`、`test_cli.py` 中 17 个旧位置/helper 断言失效。
- P2：初始记录的 UTF-8 guard 状态写成“待写回后执行”，与实际已执行结果不一致。

### 实际修改

- 在 `tests/test_context_compiler.py` 增加 Application composition 回归：同一 `？` 在两组不同 Runtime/Environment 值下均保持精确、独立、尾部；相邻 user、steering、相同文本保持三个独立事实，未做内容去重。
- 在 `tests/test_application_runs.py` 增加 Context message 识别、Context 文本选择和按 role 的 Tool message 选择；将旧的固定位置断言改为语义断言。
- 在 `tests/test_t08_e2e.py` 更新 Context 过滤 helper，使其过滤独立 Context message 而不留下空占位 Message。
- 在 `tests/test_cli.py` 按非 Context user Message 选择并断言 exec 输入，保持 `/help` 等输入逐字验证。
- T01 Checklist 第 3 项已勾选；其余已勾选项保持不变，未改写初始记录内容。

### 返工验证

- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_application_runs.py tests/test_t08_e2e.py tests/test_cli.py -q`：`73 passed`。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_system_prompt.py tests/test_context_compiler.py tests/test_provider_contract.py tests/test_openai_compat_integration.py tests/test_openai_responses_integration.py tests/test_anthropic_integration.py -q`：`91 passed, 3 skipped`。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q`：`23 passed`。
- 全量 `conda run --no-capture-output -n re-uthcode python -m pytest -q`：`1238 passed, 11 failed, 3 skipped`。剩余失败均在 T07/TUI 相关测试，仍假设 ToolResult 位于最后 Message；不属于本次 Reviewer 点名的三文件，也未实施 T02+ 或 TUI 修复。
- `git diff --check`：无错误。
- UTF-8 guard 重跑：`OK: 2 file(s) passed UTF-8 guard`，检查 Feedback 与 F01 Checklist；无编码修复。

## 返工第二轮（Reviewer CHANGES REQUESTED）

### 原因与纠正

- 第一轮返工记录中“剩余失败均在 T07/TUI 相关测试”的分布描述不完整。全量的 11 个失败实际精确分布为：`tests/test_permission_delivery.py` 2 个、`tests/test_t07_1_e2e.py` 6 个、`tests/test_tui.py` 3 个。
- 三组失败的共同原因是 W01 将 Context 投影为独立 Message 后，environment Context 位于 request 末尾；这些测试仍用 `provider.requests[1].messages[-1]` 固定取 ToolResult，因而取到了 Context Message。

### 实际修改

- 仅修改 `tests/test_permission_delivery.py`、`tests/test_t07_1_e2e.py`、`tests/test_tui.py` 的 request inspection：新增 `_latest_tool_message()`，按 `role == "tool"` 从尾部选择最新 ToolResult。
- 保留原有 ToolResult ID、FIFO 顺序、secret 不泄漏和 permission 行为断言；未修改 TUI/Permission 生产代码，未实施 W05，也未执行任何 Git 写操作。

### 返工第二轮验证

- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_permission_delivery.py tests/test_t07_1_e2e.py tests/test_tui.py -q`：`131 passed`。
- W01 精确套件：`91 passed, 3 skipped`。
- `tests/test_architecture_boundaries.py`：`23 passed`。
- 全量 `conda run --no-capture-output -n re-uthcode python -m pytest -q`：`1249 passed, 3 skipped`。
- UTF-8 guard 已在本轮 Feedback 追加后重跑：`OK: 2 file(s) passed UTF-8 guard`，检查本 Feedback 与 F01 Checklist；无编码修复。
- `git diff --check`：无错误。
