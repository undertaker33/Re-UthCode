# W01 Core Interaction 与 Plan 实施反馈

## 首次实施

本反馈记录 W01 首次按 Prompt 串行实施 T01 → T02 的结果；后续返工只在本文末尾追加章节。

### 当前进度

- T01 AskUser Core 合同硬切：已实施并完成定向验证。
- T02 Plan 真流式公共事件：已实施并完成定向验证。

### T01 已完成事实

- `UserQuestion` 删除旧的自由输入开关；select 结构化 options 收敛为 2～3 个。
- Core typed answer validation 保留题型数量、非空、重复 ID/答案等约束，同时允许 select 的任意非空自然语言答案。
- AskUser schema、TUI interaction 和 Desktop InteractionSurface 均已同步新合同；选择题始终提供自由文本路径。

### T01 验证

- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_agent_interaction.py tests/test_tui.py -q`：154 passed，exit code 0。
- `rg -n "allow_other" src tests desktop/src desktop/tests`：0 matches。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests`：exit code 0。
- `git diff --check`：exit code 0（仅报告 Git 对 LF/CRLF 的常规提示）。

以下章节补充 T02 的最终机制、文件、测试、Checklist、偏差、未验证项、风险和清理结果。

## 本次完成：T02 Plan 真流式公共事件

### 实际机制

- 在 `core/planning.py` 增加私有 `_PlanContentDecoder`，只识别当前 `ProposePlan` 的单一 `{"plan":"..."}` 参数形状；按任意 chunk 边界增量解码 JSON 转义、换行、引号、反斜杠和 Unicode（包括 surrogate pair），不形成通用 JSON streaming framework。
- `AgentTurnExecution` 只为 `ToolCallStarted(name="ProposePlan")` 建立对应 decoder；`ToolCallArgumentsDelta` 产生已解码的新文本后追加 `PlanContentDelta`，按 `tool_call_id` 隔离不同工具调用；非 Plan 工具不产生该事件，`ToolCallCompleted` 清理临时 decoder。
- 新增严格、display-safe 的 `PlanContentDelta` AgentEvent，字段为 `run_id`、`turn_id`、`iteration`、`tool_call_id`、`text`，完成 union、dict/JSON 反序列化和 `core`/`application` 公共导出；payload 不携带 `arguments_delta`、raw JSON 或 Provider SDK 类型。
- 完整 `ToolCallPart.arguments` 仍由既有 `parse_propose_plan_arguments` 最终校验；只有最终 parser 成功才写入 `PlanState`、产生 `PlanProposed` 并进入 Plan Review，流式 draft 不持久化。

### 事件顺序

同一合法调用的可观察顺序为：Provider 参数增量 → `PlanContentDelta`（按到达顺序追加）→ `ToolCallCompleted` → 既有最终 parser → `PlanProposed` → `TurnPaused(PauseKind.PLAN_REVIEW_REQUIRED)`。malformed 参数、普通失败和取消沿用既有受控终止路径，不因增量事件伪造正式 Plan。

### 修改文件

- T01：`src/uthcode/core/interaction.py`、`src/uthcode/interfaces/tui/interaction.py`、`src/uthcode/interfaces/tui/app.py`、`desktop/src/renderer/InteractionSurface.tsx`、`tests/test_agent_interaction.py`、`tests/test_tui.py`、`desktop/tests/renderer.test.tsx`。
- T02：`src/uthcode/core/planning.py`、`src/uthcode/core/agent.py`、`src/uthcode/core/agent_events.py`、`src/uthcode/core/__init__.py`、`src/uthcode/application/__init__.py`、`tests/test_planning.py`、`tests/test_agent_events.py`、`tests/test_agent_loop.py`。
- 工作包记录：本反馈文件与 F02 Checklist 仅勾选已取得证据的 T01/T02 项。

### 精确验证

- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_agent_interaction.py tests/test_tui.py -q`：154 passed，exit code 0。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_planning.py tests/test_agent_events.py tests/test_agent_loop.py -q`：121 passed，exit code 0。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q`：23 passed，exit code 0。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests`：exit code 0。
- `npm run typecheck`（`desktop`）：exit code 0。
- `npx tsx --test tests/renderer.test.tsx`（`desktop`）：56 passed，exit code 0。
- `npm test`（`desktop`）：91 passed、1 failed，exit code 1；唯一失败为 offline Desktop Runtime 用例缺少 `re-uthcode` Python executable，未指向本次代码断言失败。
- `rg -n "allow_other" src tests desktop/src desktop/tests`：0 matches。
- `rg -n "arguments_delta" desktop/src desktop/tests desktop/scripts src/uthcode/core/agent_events.py src/uthcode/application`：0 matches；针对 T02 私有实现的扫描仅命中 `_PlanContentDecoder`，未发现通用 Tool JSON streaming、EventBus 或新增 Manager/Registry。
- `git diff --check`：exit code 0；仅有 Git 关于修改文件 LF/CRLF 的常规提示，无 whitespace error。

### Checklist 状态

- T01 五项均已勾选：Core 题型与边界、任意非空 select 答案、旧字段拒绝与零命中、TUI/Renderer 自由输入和 typed continuation/cancel 均有对应测试或扫描证据。
- T02 六项均已勾选：定向测试、事件 round-trip/display-safe payload、chunk/escape/Unicode decoder、tool-call identity 隔离、最终 Plan parser/Review 顺序及否定扫描均有对应证据。

### 偏差、未完成项与风险

- 未修改 Application Context/Session、Desktop Main/Preload/Python transport、CDP harness、current-facts 文档或 T10 冻结文件，符合 W01 写集边界；Desktop Plan draft 的视觉投影由后续 W03 负责。
- 完整 `npm test` 尚未全绿：offline Desktop Runtime 集成测试需要当前环境未提供的 `re-uthcode` 可执行文件；已单独通过 renderer suite 和 typecheck，需由具备该运行时的后续验收环境重跑完整套件。
- 本次没有真实 Provider 或 packaged Desktop 人工验收；未将其描述为通过。decoder 使用 ScriptedProvider、严格事件和已有 Core/Application 取消/Plan Review 回归覆盖逻辑边界。

### 清理与 Git 边界

- active source/tests 中旧 `allow_other` 已清零；没有保留旧字段兼容层、旧分支或 raw tool argument 公共路径。
- 未删除用户文件或未知缓存；未执行任何 commit、push、merge、rebase、tag、release、分支切换或工作包归档。

### UTF-8 guard

- files checked: `docs/work/F02-DesktopGUI交互与上下文缺陷修复/F02-DesktopGUI交互与上下文缺陷修复-checklist.md`、`docs/work/F02-DesktopGUI交互与上下文缺陷修复/feedback/W01-core-interaction-plan-feedback.md`
- result: `OK: 2 file(s) passed UTF-8 guard`，无 replacement character、常见乱码，Markdown fenced code block 成对。
- repaired encoding issues: none。

## Reviewer 返工（P2/P3）

### P2-1：AskUser 真实 DOM 交互回归

- 将原 AskUser Renderer 静态检查与真实 DOM 流程合并到同一个测试，避免只验证 SSR markup。
- JSDOM 流程实际覆盖 single-select、multi-select、两者的自由输入、Back/Next 草稿保留、Review 展示、一次 typed submit，以及带原始 `pause_id`/`run_id`/`turn_id`/`tool_call_id` 的 cancel identity。
- 真实 DOM 测试通过 React 控件点击和受控输入事件断言提交对象，覆盖 `mode`、`tags`、`details` 的完整答案收敛。

### P2-2：Plan draft 失败/取消回归

- 新增 Agent-loop 回归：已经发出 `PlanContentDelta(text="draft")` 后，malformed `ProposePlan` final 只走受控错误并以正常 final 结束，Provider failure 以 `PROVIDER_ERROR` 终止，cancellation 以 `USER_CANCELLED` 终止。
- 三条路径均断言没有 `PlanProposed`、没有正式 `PlanState`，且 Provider failure/取消不会提交 assistant message；malformed 路径只提交后续合法 final，不把 draft 当正式 Plan。
- 新增测试位于 `tests/test_agent_loop.py` 的 `test_partial_plan_draft_is_not_committed_after_malformed_or_provider_failure` 与 `test_partial_plan_draft_is_not_committed_when_cancelled_mid_stream`。

### P3：运行环境说明更正

- 更正首次记录：`re-uthcode` Python executable 实际存在于 `C:\Users\93445\miniconda3\envs\re-uthcode\python.exe`；首次 `npm test` 失败不是 executable 缺失，而是 npm 启动 shell 未设置 `UTHCODE_PYTHON`、`CONDA_EXE`、`CONDA_PREFIX`。
- 在 `desktop` 目录显式设置 `UTHCODE_PYTHON=C:\Users\93445\miniconda3\envs\re-uthcode\python.exe`、`CONDA_EXE=C:\Users\93445\miniconda3\Scripts\conda.exe`、`CONDA_PREFIX=C:\Users\93445\miniconda3\envs\re-uthcode` 后重跑完整 `npm test`：92 passed、0 failed、exit code 0。

### 返工精确验证

- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_agent_interaction.py tests/test_tui.py -q`：154 passed，exit code 0。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_planning.py tests/test_agent_events.py tests/test_agent_loop.py -q`：124 passed，exit code 0。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q`：23 passed，exit code 0。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests`：exit code 0。
- `npm run typecheck`（`desktop`）：exit code 0。
- `npx tsx --test tests/renderer.test.tsx`（`desktop`）：56 passed，exit code 0。
- `npm test`（`desktop`，显式设置上述三个 Conda 环境变量）：92 passed、0 failed，exit code 0。
- Checklist 未新增勾选；既有 T01/T02 复选框保持仅以已取得证据的状态。
- 返工期间未执行任何 commit、push、merge、rebase、tag、release、分支切换或工作包归档。

### 返工未验证项与风险

- 未进行真实 Provider 网络调用或人工 packaged Desktop 验收；本次相关逻辑由 Core 定向回归、离线 Desktop Runtime 集成和真实 JSDOM DOM 交互覆盖。
- DOM 输入辅助同时派发 `input`、`change`、`keyup`，其中 `keyup` 是本测试中 React 在 JSDOM 初始化顺序下的受控字段兼容事件；不改变生产代码或产品协议。

### 返工 UTF-8 guard

- files checked: `docs/work/F02-DesktopGUI交互与上下文缺陷修复/F02-DesktopGUI交互与上下文缺陷修复-checklist.md`、`docs/work/F02-DesktopGUI交互与上下文缺陷修复/feedback/W01-core-interaction-plan-feedback.md`
- result: `OK: 2 file(s) passed UTF-8 guard`，exit code 0。
- repaired encoding issues: none。

### 返工验证闭环

- UTF-8 guard：`OK: 2 file(s) passed UTF-8 guard`，exit code 0；未修复任何编码问题。
- `git diff --check`：exit code 0；仅有 Git 关于 LF/CRLF 的常规提示，无 whitespace error。

- 澄清：cancel 测试实际断言 `pauseId`；`pause_id`、`run_id`、`turn_id`、`tool_call_id` 四字段属于 typed submit payload 的 identity 断言。
