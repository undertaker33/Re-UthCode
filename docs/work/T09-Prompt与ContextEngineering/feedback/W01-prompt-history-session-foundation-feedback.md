# W01 Prompt / Instructions / History Foundation Feedback

## 执行结论

W01 已按冻结范围完成 Task 1～Task 3 的实现与定向验收。没有实施 Task 4～Task 12、T09-1 Model Limits、Memory/Skill/MCP/Subagent 或 Git 写入。

当前提交范围仍是工作树变更，未执行 commit、push、merge、rebase、tag、release 或工作包归档。

## 实际修改

### Task 1：Prompt Asset、Context Source 与权限平面

- 新增版本化 package asset：`src/uthcode/prompt_assets/coding_agent.md` 与资源读取入口；`build_system_prompt` 从 package asset 读取公共编码提示。
- Core 继续直接维护不可编辑的 Core Runtime Contract；asset 变化不会移除 Core Contract。
- 在 `core.prompt` 定义 `Instruction`、`Conversation`、`Contextual` Plane，typed authority、stability、scope、provenance、semantic unit 与稳定前缀 epoch/fingerprint；普通历史、Projection、Runtime facts 不能通过标签伪装进入 Instruction Plane。
- 提供命名的 Context Source contract：`PromptAssetSource`、`CoreRuntimeContractSource`、`ProjectInstructionSource`、`HistoryProjectionSource`、`RuntimeStateSource`、`EnvironmentSource` 与 `ToolDefinitionSource`。Tool Definition 保持结构化、独立估算和 `schema_fingerprint`，没有被渲染为 Prompt/AGENTS 文本。

### Task 2：AGENTS / Project Instructions Loader

- `integrations/instruction_files.py` 负责 UTF-8 文件读取、物理 canonical path、link/junction 与 trusted-root 边界、physical identity、内容 fingerprint；`application/instructions.py` 负责 user/project/directory scope、惰性激活、排序、去重、epoch、change reason、persisted scope metadata 与诊断。
- 只识别整行单双引号 `@include(...)`；代码围栏和行内代码忽略；引用递归最多 3 个额外文件，并对循环、越界、超限、缺失和读取失败 fail closed。
- Session startup 载入 user/project root；Read/Edit 路径访问通过 Application callback 激活 project-root-to-target directory scopes。已激活目录 scope、epoch、prefix fingerprint 和最小 source fingerprints 可通过 `InstructionStateMetadata` 重建，不读取 History 或 ToolCall 猜测 scope。
- 当前生成入口接收 loader 的有效 instruction blocks；文件访问通知不会改变 Read/Edit 的原有 ToolResult 语义。

### Task 3：Canonical History 与 Projection 基础

- `core/history.py` 定义 immutable `HistoryEntry`、strict contiguous `CanonicalHistory`、`HistoryKind`、`SemanticUnit`、不可变 `Projection` 与非权威 `RuntimeLog`。
- ToolCall/ToolResult 以完整 semantic unit 选择；中间边界受控拒绝；Projection revision/previous link 不修改 Canonical History。
- `application/history.py` 只提供当前范围内的 immutable value/orchestration 骨架，不打开文件、不提供 Session Store 或跨进程恢复。

## 改动文件

- Prompt/Context：`src/uthcode/prompt_assets/`、`src/uthcode/core/prompt.py`、`src/uthcode/core/__init__.py`。
- Loader/接入：`src/uthcode/application/instructions.py`、`src/uthcode/integrations/instruction_files.py`、`src/uthcode/application/bootstrap.py`、`src/uthcode/application/generation.py`、`src/uthcode/application/__init__.py`、`src/uthcode/integrations/tools/factory.py`、`src/uthcode/integrations/tools/file_tools.py`。
- History：`src/uthcode/core/history.py`、`src/uthcode/application/history.py`。
- Tests：`tests/test_project_instructions.py`、`tests/test_history_contract.py`、`tests/test_architecture_boundaries.py`，以及既有 Prompt/Runtime/Provider/Tool 回归覆盖。
- 文档：本 Feedback 与 W01 Checklist 状态；用户原先已修改的 W01 Prompt feedback 路径保持不变，未改动 Prompt/Spec/Tasks 正文。

## 精确验证记录

- `conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_project_instructions.py tests/test_architecture_boundaries.py`：`29 passed`。
- `conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_history_contract.py`：`4 passed`。
- `conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_system_prompt.py`：`12 passed`。
- 最终定向组合 `conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_project_instructions.py tests/test_history_contract.py tests/test_system_prompt.py tests/test_architecture_boundaries.py`：`45 passed in 7.01s`。
- 既有 Application/Provider/Tool/架构回归：`154 passed in 21.46s`。
- 首次默认环境全量 `conda run --no-capture-output -n re-uthcode python -m pytest -q` 受到当前环境 `NO_COLOR=1`、`TERM=dumb` 影响，TUI 的 3 个 ANSI 真彩断言失败；其余为 `1091 passed, 3 skipped`。未修改 TUI 代码。
- 清除仅本次测试进程的 `NO_COLOR` 并设置 `TERM=xterm-truecolor` 后重跑同一全量命令：最终 `1094 passed, 3 skipped in 128.96s (0:02:08)`。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests`：退出码 `0`。
- `conda run --no-capture-output -n re-uthcode python -m pip check`：退出码 `0`，`No broken requirements found.`。
- `pip wheel . --no-deps`：构建成功；wheel 中存在并可按 UTF-8 读取 `uthcode/prompt_assets/coding_agent.md`。
- `git diff --check`：无 whitespace error；仅报告既有工作树文件的 LF/CRLF 转换提示。

## Checklist 证据与未勾选项

- Task 1：已勾选 Prompt/Context asset、Core Contract、Tool schema 无 Prompt 副本的定向证据，以及普通 User/Tool/Summary 历史 authority spoof rejection；涉及正式 `GenerationRequest.tools` provider mapping、长历史 Compiler/Runtime stability 的 3 项仍保持未勾选，留给后续 Task 4/7/10/11。
- Task 2：5 项全部勾选，证据覆盖 scope、include grammar、递归/限额、physical dedupe/case-fold、直接/间接循环、越界、fence/inline、Read/Edit lazy activation、epoch stable/content change、architecture boundary 与 persisted scope rebuild。
- Task 3：3 项全部勾选，证据覆盖 schema/kind/sequence/round-trip/unknown、semantic-unit atomic selection、Projection non-escalation、revision link、Runtime Log separation 与 History 字节不变。
- Task 4～Task 12：未改动、未勾选。

## 与历史/代码的差异

- 旧 UthCode Day7 的 AGENTS 产品语义被恢复为当前模块化单体的 Integration 文件边界 + Application 加载策略；没有复制旧的 LangGraph/旧工具结构，也没有为裸 `@file` 增加第二语法。
- 旧实现中的可变/持久化职责没有提前放入 W01；本次 History 与 ApplicationHistory 明确是 immutable in-memory contract，durable bytes、lock、Session resume 属于后续 Task。
- `load_session(strict=True)` 保持严格 fail-closed 语义，正式 Application startup 使用 `strict=False` 收集显式诊断；诊断不会把损坏的 instruction source 当作成功加载。
- W01 Prompt、Spec、Tasks 已冻结，不能通过本次 Worker 自行改写；因此只同步 Checklist 勾选并创建本 Feedback。

## 风险、未完成与后续边界

- 当前仍没有 Context Compiler、固定 258K budget、Tool Result 外置、Compaction、durable Session Store、single-writer resume、Slash/TUI/Eval 或正式两平面 Provider mapper；这些不是 W01 的可实施范围。
- 现有 `RunState.messages` 与正式 request composition 仍需后续 Compiler/Runtime Composition Worker 收口；W01 仅将 typed instruction blocks 接入现有 system-prompt 入口。
- History 尚未跨进程持久化；`ApplicationHistory` 不应被解释为 Session recovery 或 checkpoint。
- 全量 pytest 的 TUI 颜色断言依赖 ANSI 真彩测试环境；在 `NO_COLOR=1`/`TERM=dumb` 环境下会出现环境性失败，清除该变量后全量通过。

## UTF-8 guard

- files checked: W01 Checklist、W01 Feedback、W01 Prompt。
- result: `check_utf8_docs.py` 报告 `OK: 3 file(s) passed UTF-8 guard`。
- repaired encoding issues: none.

## 验收返工（W01 第 1 轮）

本节为本次定点返工的追加记录。返工只覆盖缺失 `@include` fail closed、Canonical History strict contract、W01 新增范围内无依据兼容层清理及其直接测试；未改写 Prompt、Spec、Tasks 或 Checklist 文案，也未执行任何 Git 写入。

### 返工问题与修复

#### 1. 显式 `@include` 的 fail-closed 语义

- 根因是递归加载已经 canonicalize 的引用路径后，仍按非引用入口传递 `is_reference=False`；缺失文件因此走了“可选根文件不存在则忽略”的分支。
- `_load_file` 现在保留显式 reference 语义，并区分“路径已 canonicalize”与“是否为显式引用”。递归引用始终以 `is_reference=True` 进入统一 Loader，没有新增第二套 Loader 或第二套 include 语法。
- 显式引用缺失、非普通文件、非法 UTF-8、物理读取失败和路径拒绝均进入正式 `InstructionError` 映射：`strict=True` 受控抛出，`strict=False` 生成明确 `InstructionDiagnostic`。顶层可选 user/project/directory `AGENTS.md` 不存在时仍按既有 scope 发现规则忽略。
- 直接引用和递归引用共用同一失败路径；最多 3 个额外引用、物理身份去重、循环检测和 trusted-root 规则保持不变。

#### 2. Strict、diagnostic 与 Application callback 最终行为

- `load_session(strict=True)` 对 root `AGENTS.md -> missing.md` 及 `A -> B -> missing.md` 抛出 `InstructionSourceNotFoundError`；非文件和非法 UTF-8 分别受控为 `InstructionReadError`。
- `load_session(strict=False)` 不吞掉失败，返回的 `InstructionLoadResult.diagnostics` 与 Loader 的 `diagnostics` 明确包含失败事实；失败不会被表示为无诊断的完整加载成功。
- 正式 Application session-start 与 Read/Edit 路径访问使用 `strict=False` 的同一 Loader callback，因此 Loader 失败可从 `application.instruction_loader.diagnostics` 观察。Read/Edit 的文件执行结果仍与 Loader 诊断分开表达：callback 在文件 I/O 前执行，正常 diagnostic 不伪造为工具失败；诊断存在时 Read/Edit 仍按原工具语义返回，Edit 的实际副作用仍可观察。callback 自身的意外异常不再由 `except Exception: return` 静默吞掉，并会阻止后续 Edit 文件写入。

#### 3. Canonical History strict contract

- `HistoryKind` 只接受当前正式值 `user_message`、`assistant_message`、`tool_call`、`tool_result`、`user_steering`；移除了 `_missing_` 及 `user`、`assistant`、`tool` 等旧别名。
- `HISTORY_SCHEMA_VERSION` 固定为当前支持的 `1`。持久化 `HistoryEntry.from_dict/from_json` 要求完整 envelope：`schema_version`、`session_id`、`sequence`、`turn_id`、`kind`、`payload`、`created_at`、`commit_boundary`、`semantic_unit_id`；缺失字段、未知字段、非 JSON object payload、非字符串 object key 和类型错误均受控拒绝。
- 持久化恢复不再默认补齐 `schema_version`、`created_at` 或 `commit_boundary`；只有内部 `CanonicalHistory.append` 构造入口在明确未提供时间时生成 `created_at`。
- `ToolCall` 与 `ToolResult` 都必须具有合法非空 `tool_call_id`。重复 call ID、重复 result ID、缺失 result、额外 result、call/result ID 不匹配或无法一一对应的 tool group 均不会形成 complete semantic unit。
- JSONL 序列继续要求 session ownership 与严格连续 sequence；合法 JSONL 的 `to_jsonl -> from_jsonl -> to_jsonl` 保持字节语义稳定。

#### 4. 无依据兼容层清理

已从 W01 新增范围删除且在当前 `src/`、`tests/` 未发现真实调用方的旧名称、别名或重复包装入口：

- `InstructionSegment = InstructionBlock`、`InstructionService = InstructionLoader`、`ProjectInstructionLoader = InstructionLoader`；同步删除 Application 导出。
- Loader 的 `load`、`load_for_target`、`load_path`、`notify_path_access`、`load_persisted_scopes`，以及 `current_instruction_set`、`activated_scopes` 等别名；`config_dir` 构造参数和 metadata 的 `activated_scopes` 兼容拼写。
- `InstructionLoadResult` 的 `segments/new_segments`、`state`、`source` 重复入口；测试统一使用正式 `blocks/new_blocks` 与 `instruction_state` / `project_instruction_source`。
- `ContextSource = ContextBlock`、`InstructionPrefixEpoch = StableInstructionPrefixEpoch`、`instruction_sources` 参数，以及 `ContextPlane.CONTEXT`、旧 Context authority/source kind 别名和对应 `_missing_` 兼容逻辑。

保留的是当前职责模型中的正式类型和显式操作，不新增旧 API、别名、包装层或双轨 Loader。

### 新增或修改的测试

- `tests/test_project_instructions.py`：新增 root/递归缺失 include 的 strict 与 diagnostic 路径，目录 AGENTS 经 Read/Edit callback 的缺失 include，非普通文件、非法 UTF-8 和 callback 异常不吞掉/不误写路径；同步正式 `blocks` 字段。
- `tests/test_history_contract.py`：新增 canonical kind、必填 envelope、schema version、unknown field、JSON object、ToolCall/ToolResult call ID、重复/缺失/额外/不匹配 tool group 及 JSONL round-trip 测试。

### 精确验证记录

- `conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_project_instructions.py`：`10 passed in 3.15s`。
- `conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_history_contract.py`：`8 passed in 2.29s`。
- `conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_architecture_boundaries.py`：`23 passed in 5.12s`。
- `conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_system_prompt.py`：`12 passed in 0.36s`。
- `conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_application_runtime.py tests/test_application_runs.py tests/test_application_tools.py tests/test_provider_contract.py tests/test_builtin_file_tools.py`：`131 passed in 6.45s`。
- 全量命令前清除本次测试进程的 `NO_COLOR` 并设置 `$env:TERM='xterm-truecolor'`；`conda run --no-capture-output -n re-uthcode python -m pytest -q`：`1102 passed, 3 skipped in 85.39s (0:01:25)`。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests`：退出码 `0`。
- `conda run --no-capture-output -n re-uthcode python -m pip check`：退出码 `0`；`No broken requirements found.`。
- `git diff --check`：退出码 `0`；无 whitespace error，仅有既有工作树文件的 LF/CRLF 转换提示。
- `git status --short`：退出码 `0`；工作树仍保留既有用户/W01 修改和本轮未提交修改，未执行 commit、push、merge、rebase、tag、release 或 archive。

### 冻结 Prompt 差异与后续边界

- 当前 `docs/work/T09-Prompt与ContextEngineering/prompt/W01-prompt-history-session-foundation-prompt.md` 相对 HEAD 仍存在正文差异（其中 `feedback/W01-feedback.md` 变为 `feedback/W01-prompt-history-session-foundation-feedback.md`）。本轮 Worker 未继续修改、恢复或自行裁决该冻结文件；差异归属尚未被证明，现记录为“待用户确认的冻结文件差异”，不得用 checkout/reset 覆盖。
- Task 4～Task 12、T09-1 Model Limits、Context Compiler、258K Budget、Working Set、Session Store、`/resume`、single-writer lock、Tool Result externalization、Compaction、Slash/TUI、Eval、Memory/Skill/MCP/Subagent/Multi-Agent 均未实施。
- 本轮遗留风险是冻结 Prompt 差异仍需用户确认，以及 History/Instruction State 尚未获得后续 Task 的 durable Session Store、跨进程 resume 和正式 Context Composition 能力；这些不在本次返工授权内。

### 本轮返工直接改动文件

- `src/uthcode/application/instructions.py`
- `src/uthcode/integrations/tools/file_tools.py`
- `src/uthcode/core/history.py`
- `src/uthcode/core/prompt.py`
- `src/uthcode/core/__init__.py`
- `src/uthcode/application/__init__.py`
- `tests/test_project_instructions.py`
- `tests/test_history_contract.py`
- `docs/work/T09-Prompt与ContextEngineering/feedback/W01-prompt-history-session-foundation-feedback.md`

### 本轮 UTF-8 guard

- 命令：`python C:\Users\93445\.codex\skills\uth-utf8-guard\scripts\check_utf8_docs.py <W01 Feedback> <W01 Prompt> <W01 Checklist>`。
- 结果：`OK: 3 file(s) passed UTF-8 guard`；未发现 replacement character、常见乱码或 Markdown fence 不平衡。
- repaired encoding issues: none.
