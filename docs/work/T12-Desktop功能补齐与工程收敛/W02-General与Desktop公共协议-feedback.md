# W02 General 与 Desktop 公共协议 — Feedback

## T03 General 最小 Application 组合

**状态：已完成定向实现与验证；T04–T06 尚未开始。** 对应 Tasks T03、R08–R11、A07/A09/A10。Checklist 只勾选本节覆盖且已有证据的两项。

### 实际合同

- `create_application(..., application_mode=GENERAL)` 使用独立用户级 owner 和 General Prompt，复用既有 Application、Agent Loop、Provider、Context、Session 与存储 authority；不要求或伪造 Coding Project。Coding 保持默认组合。
- General Prompt、Instruction fingerprint、Context、配置发现和恢复沿同一 mode 组合；General 不发现项目配置、不读取项目指令或目录上下文。常规用户配置仍可用。跨 mode Session 引用和把无项目 Loader 当作 Coding 组合均会被拒绝。
- General 首次创建、刷新 Context、恢复及手动 compact 后的请求都不带默认 Coding/文件/联网/交互工具，不向 Provider 注入 Coding 环境提示；reload 不回填 Coding Tool builder。Coding 权限与 Headless 默认组合保持原路径。
- General Prompt 通过现有 `prompt_assets` 与 PyInstaller `datas` 打包，无复制输入或额外完整性清单。已构建的 bundled smoke 执行 Coding ready/status/shutdown JSONL，并检查 General Prompt 资产存在；此证据不代表该 smoke 已创建/恢复 General Runtime。T04 接入正式 RPC 后补实际 packaged General JSONL 组合验证。

### 修改文件

- `src/uthcode/application/configuration.py`、`application/__init__.py`、`bootstrap.py`、`context.py`、`instructions.py`、`generation.py`：mode、owner、用户级组合、General 工具/上下文/reload 行为。
- `src/uthcode/core/prompt.py`、`src/uthcode/prompt_assets/__init__.py`、`src/uthcode/prompt_assets/general_assistant.md`：General Prompt 来源。
- `src/uthcode/integrations/config/loader.py`：显式关闭项目配置发现的组合入口，Coding 默认不变。
- `desktop/packaging/uthcode-runtime.spec`、`desktop/scripts/build-python-runtime.mjs`、`desktop/tests/windows-packaging.test.ts`：既有资产打包和 smoke 检查；输出明确区分 Coding JSONL smoke 与 General asset presence。
- `tests/test_application_runtime.py`、`test_architecture_boundaries.py`、`test_config_loader_integration.py`、`test_project_instructions.py`、`test_system_prompt.py`：运行态、恢复、架构和配置/Prompt 回归。

### 验证

环境：`re-uthcode` Conda；`sys.executable=C:\Users\93445\miniconda3\envs\re-uthcode\python.exe`，Python 3.12.13。

- `python -m pytest tests/test_application.py tests/test_application_runtime.py tests/test_application_tools.py tests/test_system_prompt.py tests/test_project_instructions.py tests/test_session_authority.py tests/test_config_loader_integration.py tests/test_architecture_boundaries.py -q`：109 passed，退出码 0。
- `python -m pytest tests/test_architecture_boundaries.py::test_t06_pause_control_and_ask_tool_have_no_duplicate_runtime_path tests/test_application_runtime.py::test_general_application_is_tool_free_across_create_reload_and_recovery -q`：2 passed，退出码 0。
- `npm run build:runtime`（`desktop/`）：PyInstaller 6.22.2 构建成功；该次 bundled smoke 覆盖 Coding ready/status/shutdown JSONL 和 General Prompt 文件存在检查。后续将由 T04 的真实 `runtime.initialize` General 路径补测。
- `git diff --check`：通过；Git 给出 LF→CRLF 常规提示，无 whitespace 错误。

### 边界与后续

真实 Provider General 请求、packaged Desktop 界面/视觉、A08/A16/A23 不在本 Worker 验收内，留待 W05 等任务。当前未将 General Runtime packaged 初始化/reload 描述为已通过。

## T04 Session 与 General Desktop 协议接入

**状态：已完成定向实现与验证。** 对应 Tasks T04、R01–R11、A01–A07/A09–A10；Checklist 三项均已有行为与协议证据。

### 实际合同

- Main 为 Runtime 初始化、General 打开、Session 搜索/归档和历史/恢复请求提供当前已登记 owner 集；Coding 路径必须经已有注册集合，General 使用固定 `uthcode:general`，General 的用户级 runtime workdir 不会被补入 Coding 注册集合。Main 与 Bridge 均执行方法专属参数白名单和未知字段拒绝。
- `runtime.initialize`、`general.open`、`session.new`、`session.resume`、`project.sessions`、`session.search`、`session.search.cancel`、`session.archive` 和 `history.page` 经 preload/Main/Bridge 精确协议接通。General 创建、恢复走同一 Application/Session authority；跨 mode owner 或未登记 owner 被拒。
- 搜索返回 operation id 后异步执行。Main 注入登记范围，General 搜索固定限制为 General owner；取消 token 唤醒协作扫描且等待其退出；结果含 owner revision 和当前 Application 身份，导航后迟到结果投影为 stale、不带 hits。安全命中经 DTO allowlist 序列化，`SessionSearchHit.to_dict()` 补齐实际协议所需投影。
- 归档以目标 Session 的 runtime/app owner 和 active handle、pause、pending/preparing、compaction 状态为准；目标繁忙只返回受控错误，不取消 Turn；不相关后台 Session 不阻断空闲目标；归档/恢复只收敛目标 archived 状态。项目移除只拒绝当前未登记读取/操作，重新登记后原 catalog metadata 可读。
- active Coding→General→Coding 时原 Application、Run、Turn handle 保持在其 background runtime；切换前后从旧 Application 到来的进程观察仍投影旧 project_key。没有创建第二个 Loop、Store 或项目注册权威。
- 既有 PyInstaller smoke 扩成隔离用户目录 JSONL 实际运行：Coding 与 General 均 initialize、new Session、status、shutdown；两种 Context 均由 bundled assets 编译且 stable-prefix fingerprint 不同。该证据不代表真实 Provider 请求或 packaged Renderer 验收。

### 修改文件

- `src/uthcode/interfaces/desktop/bridge.py`、`src/uthcode/application/sessions.py`：General/runtime owner、恢复/历史/归档授权、异步搜索与取消、搜索 DTO 安全序列化、事件 owner 归属。
- `desktop/src/main.ts`、`desktop/src/desktop-api.ts`、`desktop/tests/preload.test.ts`：Main 注入可信 owner scope、请求参数校验和 preload API 白名单测试。
- `tests/test_desktop_bridge.py`：General 初始化/搜索/恢复、跨 mode 拒绝、owner round-trip、迟到结果、cancel worker exit、目标归档门禁、幂等与移除/重登记回归。
- `desktop/scripts/build-python-runtime.mjs`、`desktop/tests/windows-packaging.test.ts`：实际 bundled General JSONL smoke 与结果断言。

### 验证

环境：先加载 `C:/Users/93445/miniconda3/shell/condabin/conda-hook.ps1`，再 `conda activate re-uthcode`；`sys.executable=C:\Users\93445\miniconda3\envs\re-uthcode\python.exe`，Python 3.12.13。

- `python -m pytest tests/test_desktop_bridge.py tests/test_session_authority.py tests/test_history_prepare_lifecycle.py tests/test_architecture_boundaries.py -q`：152 passed，退出码 0（最终 T04 源码状态）。
- `python -m pytest` 五个新增/变更关键 Bridge 用例（General scope、search cancel/stale、archive gates、idempotent/unregistered owner、Coding-General-Coding owner）定向执行：7 passed；catalog 移除/重新登记及 owner round-trip 后续定向复核：2 passed。
- `desktop/.\node_modules\.bin\tsx --test tests/preload.test.ts`：17/17 passed；`npm run typecheck`：通过。
- `desktop/.\node_modules\.bin\tsx --test tests/runtime-process.test.ts`：20/20 passed。
- `desktop/npm run build:runtime`：PyInstaller 6.22.2 在 re-uthcode Python 3.12.13 构建成功；真实 packaged JSONL smoke 输出 `Bundled Runtime checks passed: Coding and General initialize/session/status/shutdown JSONL with distinct prompt contexts`。

### 边界与后续

真实 Provider General 请求、packaged Desktop 界面/视觉、R07 导航与设置归档 UI、A08/A16/A23 留给 W05/后续任务。本 T04 未更改 Renderer；没有读取真实 Key、配置真实 Provider 或做 Git 写操作。

## T05 过程回放与安全明细来源

**状态：已完成定向实现与验证。** 本轮补齐短 inline Tool 输出安全出口；未更改 Renderer，过程分组/折叠 UI 与缺失状态文案留给 W03。

### 实际合同

- ToolStarted/ToolFinished 观察时间由 Application Run 在真实事件边界捕获，经原 terminal Run delta 提交到 ToolResult metadata；replay 只接受带时区的观察值，旧记录缺值仍为 `null`，不从 Transcript 构造时间倒推。已终结 Tool 的持续时间由 `started_at`/`completed_at` 固定，不在终态后继续增长。
- 过程 replay 以 `session_id + sequence + kind + tool_call_id + part_index` 区分记录；`turn_id`、ToolCall id、消息身份及 Assistant `assistant_kind` 保持独立，Progress 保持 live-only，不写 RunState、Transcript 或 Provider request。
- 新增公开 live 字段 `tool_finished.output_preview: string | null` 与 `output_preview_truncated: boolean`。仅当 ApplicationToolService 已脱敏、并将结果标为 `persistence_status=inline` 时，Core 事件才投影首段文本；上限 1024 字符，截断通过布尔字段明确标识。既有 ToolResult 完整内容和结构化 payload 不进入事件。
- Replay `SessionReplayRecord` 使用同名 `output_preview` / `output_preview_truncated`。只有正式 transcript ToolResult 中存在 `persistence_status=inline` 时才显示脱敏文本；旧记录/不明来源不伪造明细。Externalized 结果仍只投影 Session 绑定的 `output_ref`，继续通过 `tool_result.read` 续读，不强制复制或 externalize 短结果。
- `tool_result.read` 参数为 `{session_id, project_key, ref, offset?, limit?}`；Main 仅注入已登记 owner，Bridge 校验 owner 与 Session/ref 归属并限量读取。响应字段为 `{ref, content, offset, next_offset, total_bytes, sha256, eof}`。Inline 结果没有 ref，也不接受任意路径/任意 ref 读取。

### 修改与回归

- `src/uthcode/application/tools.py`：为 inline materialization 写入安全来源标记与长度，使同一 redacted ToolResult 可用于 Loop 与历史投影；未改变短结果持久化行为。
- `src/uthcode/core/agent_events.py`、`src/uthcode/core/agent.py`：在真实 Tool 完成边界投影显式 inline 的限长 TextPart；事件 codec 兼容缺少新可选字段的旧 payload，并校验截断标记。
- `src/uthcode/application/sessions.py`、`src/uthcode/interfaces/desktop/bridge.py`：Replay safe DTO 与精确字段 allowlist 增加短输出/截断标记。
- `tests/test_tool_result_persistence.py`：真实 Application/Agent Loop 验证短 secret 输出在 live 与 replay 均脱敏、长 inline 输出限长并明确标记截断，异 owner history 读取被拒；同时检查 Transcript 与后续 Provider request 不含测试 secret。
- `tests/test_desktop_bridge.py`：事件 codec/Bridge allowlist、Replay allowlist 保留 preview/truncation/ref，并拒绝把完整 ToolResult 放入 live 事件。

### 验证

环境：先加载 `C:/Users/93445/miniconda3/shell/condabin/conda-hook.ps1`，再 `conda activate re-uthcode`；`sys.executable=C:\Users\93445\miniconda3\envs\re-uthcode\python.exe`，Python 3.12.13。

- `python -m pytest tests/test_tool_result_persistence.py tests/test_timeline_contract.py tests/test_history_paging.py tests/test_desktop_bridge.py -q`：136 passed，退出码 0（输出预览 truncate 标志接入前的首次整套结果）。
- 新增截断字段后的 codec、Replay、真实 Agent Loop redaction/owner 回归：3 passed，退出码 0；另对真实 inline preview 行为复跑 1 passed，退出码 0。最终状态将重跑 T05 定向命令并以其结果为准。

### 边界与交接

输出预览只用于已有结果展开；UI 对 `output_preview_truncated=true` 应明确展示“预览已截断”，并用 `output_ref` 续读 externalized 明细。旧无标记输出、不可用历史时间及读取失败应由 W03 显示局部 unavailable 状态。没有新增历史快照、逐帧 Progress 存储或 Renderer 文件访问。

### T05 最终验证补充

- 截断标志接入后的最终复跑：`python -m pytest tests/test_tool_result_persistence.py tests/test_timeline_contract.py tests/test_history_paging.py tests/test_desktop_bridge.py -q`：136 passed，退出码 0。上一段同命令的首次结果与此最终结果相同。

### T04 复核补充：General 下管理已登记 Coding owner

- 复核发现 General Settings 需要读取/恢复 Coding 项目的归档项，但直接调用 General Application 时会因 Session owner 与当前 General owner 不同而拒绝。使用 Main 注入的既有已登记 Project 集作为唯一授权依据，General Application 的 `session_catalog_metadata` 与 `set_session_archived` 仅在调用方提供该集合且目标 owner 在集合内时允许跨 owner 的 catalog/archive 元数据操作。
- Bridge 对 `project.sessions` 与 `session.archive` 继续校验 owner，并把已登记集合仅传入 General 的归档行政操作；不会创建 Coding Runtime、切换当前 Application、改变 General 搜索/恢复 Session 隔离，也不接受未知 owner。
- 真实 `UthCodeApplication` 回归 `tests/test_desktop_bridge.py::test_general_runtime_can_manage_archives_for_registered_coding_owner` 覆盖 General 下读取 Coding 归档列表、归档、读取已归档列表、恢复、拒绝未登记 owner 与跨 mode Session resume；结束时 Application、mode、owner 不变。此行为包含在最终 T06 受影响套件 221 passed 中。

## T06 变更摘要与当前只读 Diff 出口

**状态：已完成 W02 当前范围实现与定向验证；Renderer 审阅交互及 packaged 操作仍留后续任务。** 对应 Tasks T06、R15–R16、A14–A16；未修改 Renderer。

### 实际公共合同

- Renderer 经 preload `requestRuntime("workspace.diff", {project_key, path?})` 请求当前工作区审阅；`path` 是可选、限长的工作区相对路径。Main 拒绝未知参数、General owner、未登记 Project 与非法路径，然后把规范化 `project_key` 和当前 `catalog_project_keys` 交给 Bridge。
- Bridge 再校验 Main 登记集合并只在 Coding Application 上调用 `read_workspace_diff`；Application 将 owner 规范化到物理目录并再次校验其在可信登记集合内。请求可针对另一个已登记 Coding Project，但不会切换或创建 Application。General、未知 owner、非 Git 目录及 Git 查询失败均为局部受控 unavailable。
- 成功 DTO：`{source:"current_working_tree", project_key, viewed_at, status, staged_diff, unstaged_diff, truncated}`。`viewed_at` 为 UTC ISO 时间；`status` 含 `{branch, entries:[{xy,path,original_path?}], unborn, truncated}`；每个 diff 含 `{text,truncated,size_bytes}`。status 保留 untracked/rename/deleted 状态；untracked 不伪造 diff 或红绿行。staged 与 unstaged 分开；二者和总 DTO 都显式给截断状态。Git 禁止外部 diff/textconv，沿用既有输出上限及 CancellationToken 路径。
- 当前 diff 只代表 `viewed_at` 时读取到的工作树状态，没有写回 Session 历史。历史 `SessionReplayRecord.file_changes` 只在 ToolCall 与同 id ToolResult 配对后，由正式结果投影：成功且确有变化、带合法 digest 的 WriteFile/EditFile 产生 `{tool_name,path,status:"changed"}`；ApplyPatch 只投影正式 `applied`/`partial`、安全 `applied_paths` 和 `failed_count`/`not_applied_count`。Digest、原始 patch、工具输出与不安全路径不出 wire；Bash、模型文字、单独 git status 和未匹配 call/result 不生成确定编辑摘要。
- 历史不产生完整旧 Diff 或变更行数；真实当前 Diff 与历史可核实摘要保持独立。既有 ArtifactService、Main 单文件外部文件授权及 Session-bound ref 行为继续承担文件预览，W02 未增加 Renderer 文件读取路径。

### 修改文件

- `src/uthcode/integrations/tools/git_tools.py`：只读 review 汇总 status、staged/unstaged diff；rename status 与选中文件两侧路径、untracked、binary、deleted、非 Git、取消及输出截断沿用 GitWorkspace 边界。
- `src/uthcode/application/generation.py`、`application/__init__.py`：Application 已登记 Coding owner 审阅入口及 Application-owned `WorkspaceReviewError`；只允许这一现有 Application 职责使用 GitWorkspace。架构测试为此条精确依赖增加允许项，四层其余边界不变。
- `src/uthcode/application/sessions.py`、`src/uthcode/interfaces/desktop/bridge.py`：安全历史 `file_changes` 投影和 wire allowlist；workspace.diff 严格 DTO/owner 校验、受控错误及精确 RPC 方法。
- `desktop/src/desktop-api.ts`、`desktop/src/main.ts`、`desktop/tests/preload.test.ts`：公开方法加入 preload whitelist，Main 对 owner/路径/额外字段校验并注入可信项目集合，验证已登记 owner 与 General/未登记负例。
- `tests/test_git_tools.py`、`tests/test_history_paging.py`、`tests/test_desktop_bridge.py`、`tests/test_architecture_boundaries.py`：覆盖 Git 状态/内容、正式写入来源、安全相对路径、Main/Bridge owner、Application 不切换、DTO 与架构依赖。

### 验证

环境：先执行 `. C:/Users/93445/miniconda3/shell/condabin/conda-hook.ps1`，再 `conda activate re-uthcode`；确认 `sys.executable=C:\Users\93445\miniconda3\envs\re-uthcode\python.exe`、Python 3.12.13。

- `python -m pytest tests/test_git_tools.py tests/test_desktop_artifacts.py tests/test_desktop_bridge.py tests/test_history_paging.py tests/test_application_runtime.py tests/test_tool_result_persistence.py tests/test_timeline_contract.py tests/test_builtin_file_tools.py tests/test_patch_tool.py tests/test_architecture_boundaries.py -q`：221 passed，退出码 0。包括 Tasks T06 指定 GitWorkspace/Artifact/Bridge 测试、正式历史写入与结果时间/inline 安全回归、架构边界及 General→Coding 归档行政出口。
- `python -m pytest tests/test_architecture_boundaries.py -q`：23 passed，退出码 0。
- `desktop/ npm run typecheck`：通过；`desktop/ npx tsx --test tests/preload.test.ts`：17/17 passed，退出码 0。
- `desktop/ npx tsx --test tests/runtime-process.test.ts`：T04 最终验证 20/20 passed，退出码 0；本次 T06 没有修改 Runtime 子进程实现。

### 边界与交接

- W03 可直接消费 `workspace.diff` 和 `SessionReplayRecord.file_changes` DTO；`output_preview_truncated`、`output_ref` 续读合同见上方 T05。UI 应用显式字段表达截断，不从文本内容猜测。
- A16 packaged Desktop 操作及完整 UI 反馈留 W05/T15；真实 Provider、Renderer 状态/页面和视觉行为未在 W02 验收。W02 没有执行 Git 写入、生成历史快照或改动冻结需求文件。

### W02 收尾复核补充

- 在最后一次验证前补强 Git pathspec 的相对路径检查（拒绝嵌套 `..` 与 Windows drive path），并将历史 `file_changes` 加入 Bridge 精确 replay DTO 回归；随后对受影响集最终复跑：`python -m pytest tests/test_git_tools.py tests/test_desktop_artifacts.py tests/test_desktop_bridge.py tests/test_history_paging.py tests/test_application_runtime.py tests/test_tool_result_persistence.py tests/test_timeline_contract.py tests/test_builtin_file_tools.py tests/test_patch_tool.py tests/test_architecture_boundaries.py -q`：221 passed，18.06s，退出码 0。
- 最终 T06 代码状态保留：`npm run typecheck` 通过、`npx tsx --test tests/preload.test.ts` 17/17 passed；T04 已验证 `npx tsx --test tests/runtime-process.test.ts` 20/20 passed。
- W02 Feedback UTF-8 解码正常、U+FFFD 为 0、常见乱码模式未命中、Markdown fence 平衡；`git diff --check` 退出码 0（仅报告工作树既有 LF→CRLF 提示）。

## Reviewer返工1

首轮独立复审指出三项缺口：workspace Diff 文本未经过配置秘密脱敏；Coding-first Settings 的 catalog 不含固定 General owner，导致无法读取或恢复 General 归档项；同步 `workspace.diff` 阻塞 Bridge event loop，且没有可由外部 RPC 触发并等待底层清理的取消路径。

- Diff 继续在原 `UthCodeApplication.read_workspace_diff` 和 Main 登记的 Coding workspace 边界内执行；将 branch、状态路径、重命名原路径、staged/unstaged Diff 文本交给 Application 已有 `SecretValue` 感知脱敏器。RPC 回归以本地测试用非真实 Provider/Search key 验证秘密值不出现在成功结果中，同时验证正常行和状态仍可读；owner `project_key` 保持为授权身份字段。
- Main 对 Coding `runtime.initialize`、`project.open` 和 Diff 请求均沿用现有登记项目集合，并附加固定 `uthcode:general` catalog owner。Bridge 只让已登记目录/归档管理请求使用该 owner；没有切换或创建 Application。真实 Coding `UthCodeApplication` 测试覆盖读取和恢复 General 归档项、未知 owner 拒绝、跨 mode resume 拒绝、搜索 scope 排除 General，且结束时 mode/application/owner 不变。反向 General 管理已登记 Coding 归档测试继续通过。
- `workspace.diff` 现在只在 event loop 上校验请求并返回有界后台操作身份，Git 审阅通过 `asyncio.to_thread` 执行；每 Bridge 同时最多 4 项。Bridge 将同一个 `CancellationToken` 传给 Application / `GitWorkspace`，`workspace.diff.cancel` 取消 token 并等待操作 task 和 Git 子进程完成清理后才回复。当前 owner revision、Application 身份和选中 owner 用于过滤迟到结果；导航后只发 `stale` 事件，不附 Diff。

### 最终 workspace.diff wire 合同

本节合同覆盖上文 T06 记录的同步 `workspace.diff` 结果 DTO 描述，供 W03 实现时采用。

- preload/Main/Bridge 请求：`workspace.diff({ project_key, path? })`；Main 规范化路径并注入 `catalog_project_keys`，General owner 和未知/未登记 Coding Project 在 RPC 边界拒绝。Bridge 仅对当前 Coding Application 接受请求。
- 成功 kickoff 响应：`{ operation_id, owner_key, state: "reviewing" }`。它不携带 Diff 内容。
- 终态通过 Agent event `{ type: "workspace_diff_result", operation_id, owner_key, state, ... }` 返回。`state` 为 `completed`、`cancelled`、`stale` 或 `failed`。仅 `completed` 带 Application 投影的 Diff DTO：`source`、`project_key`、`viewed_at`、`status`、`staged_diff`、`unstaged_diff`、`truncated`；`failed` 带通用 `error_kind: "workspace_unavailable"`，其他非成功状态不带 Diff 数据。
- 取消 RPC：`workspace.diff.cancel({ operation_id })`。成功响应为 `{ operation_id, state: "cancelled" }`，返回前等待底层 Git 查询退出/回收。已终结或未知身份返回 `workspace_diff_unknown`；达到并发上限返回 `workspace_diff_busy`。

### Reviewer返工1验证

- `python -m pytest tests/test_desktop_bridge.py -k "workspace_diff or coding_runtime_can_manage_general_archives" -q`：3 passed；覆盖真实 Application Diff 秘密脱敏、Coding-first General 归档读取/恢复与隔离、工作线程中的真实子进程 token 取消回收、事件循环推进、导航后迟到结果丢弃。
- `python -m pytest tests/test_desktop_bridge.py tests/test_application_runtime.py tests/test_git_tools.py tests/test_tool_result_persistence.py tests/test_history_paging.py tests/test_architecture_boundaries.py tests/test_config_loader_integration.py tests/test_project_instructions.py tests/test_system_prompt.py tests/test_application.py tests/test_application_tools.py -q`：219 passed，退出码 0。
- `desktop/ npx tsx --test tests/preload.test.ts`：17/17 passed；覆盖 fixed General Main owner、Coding Settings catalog/archive RPC 和 `workspace.diff.cancel` 参数边界。
- `desktop/ npm run typecheck`：通过，退出码 0。
- `desktop/ npx tsx --test tests/runtime-process.test.ts`：20/20 passed，退出码 0。
- 返工完成后恢复 Checklist T06 A14 当前 Diff 框；History A14 框继续保留。Renderer 及 packaged UI 验收仍按原边界留后续工作。

## 总控：Reviewer返工1复审与交付核对

2026-10-11，同一 gpt-6.1-sol/medium Reviewer 复审通过，首轮3项 finding关闭，未发现修复引入的具体新问题。独立执行：

- `python -m pytest tests/test_desktop_bridge.py -k 'workspace_diff or coding_runtime_can_manage_general_archives or general_runtime_can_manage_archives' -q`：4 passed、96 deselected，1.74s。
- `python -m pytest tests/test_git_tools.py tests/test_tool_result_persistence.py tests/test_architecture_boundaries.py -q`：55 passed，10.46s。
- `desktop/ npm run typecheck`：退出码0；`npx tsx --test tests/preload.test.ts`：17/17 passed。
- 独立内存 smoke：运行中的 Diff 调用 shutdown 后，真实测试子进程已回收、worker task已完成、operation map清空，PASS。
- `git diff --check`：退出码0。

Reviewer未重跑Worker219项全套、runtime-process、打包smoke、真实Provider及packaged/原生视觉验收。总控核对9份冻结文件正文不变（Checklist仅复选框变化），Checklist为12完成/28待验；UTF-8 guard：索引、W01/W02 Feedback及Checklist共4份通过，无编码修复。W03及后续真实UI验收尚未实施，本轮不声明整包完成。
