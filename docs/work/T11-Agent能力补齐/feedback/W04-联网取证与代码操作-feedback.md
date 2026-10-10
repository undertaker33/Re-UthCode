# W04 联网取证与代码操作 Feedback

## 首轮实施（2026-09-13）

本轮严格按 `T10 → T11 → T12 → T13` 实施，范围停在 W04；没有修改后置 W05/W06/W19 能力，没有 Git 写操作，也没有请求、展示或伪造 Provider/Tavily 凭据。真实 Tavily A18 依照用户当前未配置条件保持未验证。

### 实际完成

- **T10 搜索、抓取与可信配置**：新增用户级 `[search]` 配置模型、Tavily `SecretValue` 解析和原子写回；项目配置只能禁用或收紧 `max_results`、`max_fetch_bytes`、`timeout_seconds`，不能写 key、endpoint 或在用户未配置时启用。Tavily endpoint 固定为代码常量，请求固定 `search_depth=basic`、`auto_parameters=false`、`include_answer=false`、`include_usage=true`。`WebSearch` 只在有效用户配置和正式 Application 组合中注册。
- `WebFetch` 只接受公开 HTTP(S) 地址，逐跳重新检查重定向目标和授权；正文流式有界读取，取消会关闭读取任务；正文只在本地下载后交给 Trafilatura，PDF 复用 W03 Session 资产路径。登录页、动态页、私有/本地地址、超限、认证、限额、网络和取消均返回受控失败及安全来源元数据。
- Desktop Settings/Bridge 接入搜索启用、固定 provider、key 草稿、结果/字节/超时上限的保存和安全回读；key 不进入 Renderer preference、事件、History、diagnostics 或 Tool Result；active Turn 时整次保存受阻。配置、工具组合、Application/ToolResultRead 路径已通过真实测试。
- **T11 ApplyPatch**：新增 Codex patch 方言解析，先完成整份 patch 的路径、目标冲突、读取版本、hunk 和移动目标预检；预检失败零变更。通过后逐目标再次核对并以原子文件替换提交，移动的源/目标分别绑定；部分失败报告 `applied`、`failed`、`not_applied`，磁盘状态按实际已提交结果表达。
- **T12 GitWorkspace**：新增只读 `status`、`diff`、`log`、`show`、`branch` 查询，使用 argv、NUL/路径/ref 校验、输出上限和超时；固定 `GIT_OPTIONAL_LOCKS=0`、`--no-ext-diff`、`--no-textconv`、无 pager/交互网络，不写 index。临时 repo 覆盖未跟踪、特殊文件名、detached、unborn、非 Git 和外部 diff 程序未执行。
- **T13 Glob/Grep**：按目录继承 `.gitignore`/`.ignore`，隐藏、二进制、敏感路径、符号链接和权限事实均在候选预检处理；遍历先受候选上限约束，再按 page size/max bytes 返回。续读 cursor 绑定完整 query fingerprint，续读重新预检权限和链接事实；正则使用有界 timeout，超时返回 `ToolFailureKind.TIMEOUT`，大结果经 Application `ToolResultRead` 有界续读且不递归物化。
- 同步 `AGENTS.md`、`docs/Tools.md`、配置手册、四层 Context、GUI Context、A01 核心设计和 `docs/Context-Index.md`；Checklist 仅将 A17/A19/A20/A21/A23 及对应 Tasks 核对项由未完成改为完成。A18、POSIX/packaged/T19 以及后置 T14+ 项保持未勾选，冻结需求、Spec、Tasks、Prompt 文字未修改。

### 当前调用链

`create_application -> create_default_tools -> ApplicationToolService -> AgentRun/AgentLoop -> trusted preflight -> Permission -> execute -> Application result materialization -> AgentEvent/History/ToolResultRead`。

搜索配置随 EffectiveConfig 进入 Application，key 只在 Tavily HTTP 请求边界显式取值；WebFetch 的每个实际 redirect 都重新进入地址与授权判断。ApplyPatch 以一次完整计划形成单一 WRITE action，再逐目标提交；GitWorkspace 只形成 READ action。Desktop Settings 经 `Bridge -> configuration.save -> write_user_config`，active Turn 由 Bridge 拒绝，既有 runtime 不重启。

## Checklist 本轮已验证并勾选

- T10：A17、A23 与 T10 完成边界。
- T11：A19 与 T11 完成边界。
- T12：A20 与 T12 完成边界。
- T13：A21 与 T13 完成边界。

保留未勾选：A18（需要用户配置后的真实 Tavily 查询→公开页/PDF Fetch）、T19 真实端到端验收、T07/T08/T09 既有 POSIX/packaged 项和所有 W05/W06 项。本轮没有用 fixture、mock、CDP 或本地离线结果替代 A18/T19。

## 依赖与验证命令

实施和验证均使用既有 `re-uthcode` Conda 环境；本轮声明 `httpx`、`trafilatura`、`pathspec`，未创建新环境。已安装版本为 httpx `0.28.1`、trafilatura `2.2.0`、pathspec `0.12.1`。

- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_web_tools.py tests/test_patch_tool.py tests/test_git_tools.py tests/test_builtin_search_tools.py tests/test_config_loader_integration.py tests/test_application_tools.py tests/test_desktop_bridge.py -q`：`126 passed in 7.56s`。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_application_runs.py -q`：`52 passed in 4.55s`；新增 W04 工具后同步更新既有精确 Tool View 断言，Plan 只读视图包含 `GitWorkspace`/`WebFetch`，Default 视图另含 `ApplyPatch`。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q`：`23 passed in 4.00s`。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_application.py tests/test_config_contract.py tests/test_configuration.py tests/test_builtin_file_tools.py -q`：`106 passed`（其中 application 2、config contract 21、configuration 60、file tools 23）。
- `$env:UTHCODE_PYTHON='C:\Users\93445\miniconda3\envs\re-uthcode\python.exe'; npm run typecheck`（工作目录 `desktop/`）：通过；带同一环境的 Desktop 全量上一阶段结果为 `229 passed, 0 failed`，本轮未改 Renderer/Bridge 代码，仅同步 Python 断言。
- `conda run --no-capture-output -n re-uthcode python C:/Users/93445/.codex/t11_check_frozen.py`：待本轮文档写入完成后执行并记录最终结果。
- `conda run --no-capture-output -n re-uthcode python C:/Users/93445/.codex/skills/uth-utf8-guard/scripts/check_utf8_docs.py ...`：待本轮 Feedback 写入完成后对全部修改 Markdown 执行并记录最终结果。

## 未验证项、差异与风险

- 用户级 Tavily 当前没有配置，未执行真实 Tavily 查询、真实用量或真实 endpoint 验收；A18 保持未勾选，不请求或打印密钥。
- 未执行 Windows packaged 安装产物人工验收、POSIX 条件、真实 Provider/视觉模型、T19 联合链路；既有 W03 未验证项不因本轮源码变更提前关闭。
- W04 本地 fixture 覆盖 Fetch 重定向、认证/限额/超限/取消和 PDF 资产闭环，但不代表第三方真实服务可用性。
- Git 查询的安全边界在临时 repo 和外部 diff marker 用例中验证；不涉及任何本仓库提交、推送或分支写操作。
- 没有新增能力欠账；真实服务、安装产物和 POSIX 条件属于已有后置验收，不转写为欠账。

## 清理结果

测试临时目录由 pytest `tmp_path` 清理，未创建自建交付目录。没有执行 commit、push、merge、rebase、tag、release 或工作包归档；等待总控审核、合并和后续原 Worker 返工。

## 最终收口追加（2026-09-13）

恢复中断后确认原定向 Python 进程已经退出；旧 `test_application_runs.py` 的四处工具集合断言因正式 W04 工具增加而失败，已更新为当前 Plan/Default 视图并重新验证 `52 passed in 4.55s`。这四处是测试合同同步，不是放宽产品断言。

- `$env:UTHCODE_PYTHON='C:\Users\93445\miniconda3\envs\re-uthcode\python.exe'; npm run typecheck`（工作目录 `desktop/`）：通过。
- `$env:UTHCODE_PYTHON='C:\Users\93445\miniconda3\envs\re-uthcode\python.exe'; npm test -- --runInBand`（工作目录 `desktop/`）：`229 passed, 0 failed, 0 cancelled, 0 skipped`，`duration_ms 66919.2385`。
- `conda run --no-capture-output -n re-uthcode python C:/Users/93445/.codex/skills/uth-utf8-guard/scripts/check_utf8_docs.py AGENTS.md docs/Context-Index.md docs/Tools.md docs/context/A01-AgentRuntime/AgentRuntime-Context.md docs/context/A02-Control/Control-Context.md docs/context/A03-State/State-Context.md docs/context/A04-Orchestration/Orchestration-Context.md docs/context/GUI/GUI-Context.md 'docs/core-design/A01-AgentRuntime/04-工具调用闭合协议.md' 'docs/core-design/A01-AgentRuntime/05-文件修改事实门禁.md' docs/user-manual/configuration.md 'docs/work/T11-Agent能力补齐/T11-Agent能力补齐-checklist.md' 'docs/work/T11-Agent能力补齐/feedback/W04-联网取证与代码操作-feedback.md'`：`OK: 13 file(s) passed UTF-8 guard`。
- `conda run --no-capture-output -n re-uthcode python C:/Users/93445/.codex/t11_check_frozen.py`：`PASS: 10 frozen files unchanged except permitted checklist completion marks`。
- `git diff --check`：clean；仅有 Windows checkout 的 LF→CRLF 提示，没有空白错误。

最终仍未验证真实 Tavily A18、真实 Provider、Windows packaged 人工验收、POSIX 条件和 T19 联合链路；没有请求或伪造密钥。收口后停止修改，交由总控/ Terra 审查。

## UTF-8 guard

- files checked: `AGENTS.md`、W04 本轮修改的 12 份 Markdown 及本 Feedback，共 13 个文件。
- result: `OK: 13 file(s) passed UTF-8 guard`；UTF-8、乱码标记和 Markdown fence 均通过。
- repaired encoding issues: 无。

## 返工第1轮（Terra 首轮修复，2026-09-13）

Terra 首轮指出的 8 项旧证据不足已经逐项补齐；本节只追加事实，不回退此前已勾选的 Checklist。冻结需求、Spec、Tasks、全部 Prompt 和 Checklist 文字没有修改，A18/T19 仍未勾选。真实 Tavily/Provider 仍由用户后配，本轮没有请求、展示或伪造凭据。

- **#1 WebFetch 重定向授权**：正式 `create_application` 组合现在把重定向授权器注入默认 `FetchWebTool`。每个实际 hop 都用当前 `AgentRun` 的 resolver 形成 `WebFetch/redirect` `PermissionAction`；ASK 返回暂停并保存安全续读事实，ONCE/SESSION 批准后只请求已批准目标，DENY/取消在请求目标前结束。`tests/test_w04_review_fixes.py` 的两个 Application fixture 分支证明批准会收到 `start`、`final` 两次请求，拒绝只收到 `start`。
- **#2 Glob 敏感候选**：Glob 预检按本次实际候选构造敏感 resource，包含 `.env`/私钥类候选时进入默认 sensitive Guard；分页 cursor 每次重新扫描、重做外部/敏感/符号链接权限事实，并把 query fingerprint 绑定到续读。
- **#3 ApplyPatch Guard**：ApplyPatch 加入默认 sensitive Guard；完整 patch 的所有源/目标先预检，包含敏感目标时按既有 `full_access` Guard 规则处理，多目标不再只按第一个目标授权。已有预检零变更和部分提交测试加上本轮定向覆盖。
- **#4 Git 有界输出**：Git 查询改为 `Popen` 双线程逐块 drain，单 stdout/stderr 各自受上限，超出部分继续受控丢弃并返回 `truncated`；timeout/cancel 会 terminate、回收子进程，不使用全量 `communicate()`。新增真实 400k 行 diff、`max_output_bytes=1024` 验证结果 `truncated=True` 且 `size_bytes<=1024`。
- **#5 Grep 有界输入**：Grep 改为逐文件/逐行增量读取，输入文件预算、单行预算、regex timeout 和输出 page/max bytes 分开受控；目录遍历使用有界 iterator，不再 `sorted` 全目录或 `read_text().splitlines()` 全文件。cursor 续读仍绑定 query 并重新预检权限。
- **#6 搜索 Secret 反射脱敏**：Application bootstrap 和配置 reload 都把 `SearchConfiguration.api_key` 加入内部 redactor。materialization 在计算大小、持久化 artifact、metadata 和可见 ToolResult 之前递归清理正文、details、progress；Tavily fixture 故意在 title/content/usage 反射同一 opaque value，实测 Event、TurnResult、第二 Provider tool message、Session transcript/history 和 sessions artifact 均不含 secret，并包含 `<redacted>`。
- **#7 Settings 下一 Turn reload**：idle `settings.save` 在 TOML 原子写入后加载新 EffectiveConfig，原地重组 Provider/Tool registry/redactor；保留当前 Session、Run/context、同一 `ProcessSessionManager` 和其存活子进程，active Turn 仍先拒绝。新增 Desktop Application 测试实测保存后 `WebSearch` 工具视图和 `max_results=3`/`max_fetch_bytes=4096` 生效，下一真实 Turn 的 Provider request 看见新工具，真实子进程在保存和下一 Turn 后仍为 `running`。
- **#8 Patch Windows 物理别名**：所有源/目标通过 resolver 的物理路径再以 Windows `normcase` 规范键比较；`Foo.txt`/`foo.txt` 同物理目标在预检阶段冲突并保持磁盘零变更。Windows 实际别名测试已加入，非 Windows 环境按平台条件跳过。

### 返工定向验证

- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_w04_review_fixes.py -q`：`4 passed`。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_git_tools.py tests/test_patch_tool.py tests/test_w04_review_fixes.py -q`：`14 passed`。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_agent_loop.py tests/test_web_tools.py tests/test_application_runs.py tests/test_desktop_bridge.py tests/test_patch_tool.py tests/test_git_tools.py tests/test_builtin_search_tools.py tests/test_w04_review_fixes.py -q`：`229 passed`。
- `conda run --no-capture-output -n re-uthcode python C:/Users/93445/.codex/t11_check_frozen.py`：`PASS: 10 frozen files unchanged except permitted checklist completion marks`。

返工后停止修改并交由同一 Terra Reviewer 复审。未验证项仍为真实 Tavily A18、真实 Provider、Windows packaged 人工验收、POSIX 条件和 T19 联合链路；没有执行任何 Git 写操作或工作包归档。

### 返工验证计数校正（2026-09-13）

返工段落记录的首次组合结果为 `229 passed`；随后新增的 Git 大输出和 Windows 物理别名两个测试已纳入同一命令，最终当前组合结果为 `231 passed in 16.59s`。为保持 Application→Integration 依赖边界，配置 reload 使用由 bootstrap 注入的 Tool builder；`tests/test_architecture_boundaries.py` 最终为 `23 passed in 5.44s`。

## 返工第2轮（Terra 第二轮修复，2026-09-13）

Terra 第二轮指出的 3 项运行时闭环已经逐项补齐；本节只追加当前事实，不回退此前已勾选的 Checklist。冻结需求、Spec、Tasks、全部 Prompt 和 Checklist 文字没有修改，A18/T19 仍未勾选。真实 Tavily/Provider 仍由用户后配，本轮没有请求、展示或伪造凭据。

- **#1 后台 Application 配置传播**：`settings.save` 在全局安全边界通过后，枚举同一 `workdir`/配置域的当前及所有保留后台 Application/Run，原地 reload Provider、Tool 组合、搜索上限、redactor，并同步 idle Run 的 permission mode。Session、Run/transcript、Context、ProcessSessionManager、子进程和 Bridge dispatcher/completion 身份均保留，不重启 Application 或进程。未完成的当前/后台 Turn task、active handle 和任一 Session compaction 继续拒绝保存。新增真实 Desktop 流程证明：后台 Session 持有活进程时，另一 Session 保存配置，切回后旧 Application 使用新 WebSearch/limits/permission，真实下一 Turn 看见新工具，进程仍为 `running` 且 manager identity 不变。
- **#2 metadata 映射键脱敏**：Application `_redact_value` 现在递归处理 Mapping 的 key 和 value；非字符串 key 先转换为字符串再脱敏，保持 JSON object 的 string-key 约束。Tavily fixture 将同一 opaque value 反射到 usage 的 key 和 value，经过正式 Application ToolResult materialization、Event、第二次 Provider tool message、History 和 sessions artifact，实测均不含 secret。
- **#3 活进程旧 Secret projector 生命周期**：ProcessSessionManager 在子进程创建时绑定当时的 output/command projector；共享 manager reload 后只影响新进程，旧进程继续用旧 SecretValue 完成跨 chunk/event/read/Process.list 脱敏。退出时 ring 与已投影 command 保留可读，投影回调/SecretValue 闭包释放，未建立全局 Secret registry。新增真实 Application reload 活进程测试证明旧 key 不出现在 event/read/command projection，子进程结束后旧 projector 已回收。

### 第二轮定向验证

- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_w04_review_fixes.py`：`6 passed in 2.46s`。
- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_process_sessions.py tests/test_process_application_lifecycle.py tests/test_desktop_bridge.py tests/test_history_bridge.py tests/test_history_prepare_lifecycle.py tests/test_session_authority.py`：`107 passed in 10.53s`。
- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_application_tools.py tests/test_application_runs.py tests/test_builtin_search_tools.py tests/test_web_tools.py`：`82 passed in 5.53s`。
- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_architecture_boundaries.py`：`23 passed in 4.85s`。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests/test_w04_review_fixes.py`：通过。

最终仍未验证真实 Tavily A18、真实 Provider、Windows packaged 人工验收、POSIX 条件和 T19 联合链路；没有请求或伪造密钥。没有执行任何 Git 写操作、提交、推送、合并或工作包归档；本轮完成最终 UTF-8 guard、冻结 checker、`git diff --check` 后停止，交由同一 Terra Reviewer 复审。

### 第二轮文档与冻结收口

- `conda run --no-capture-output -n re-uthcode python C:/Users/93445/.codex/skills/uth-utf8-guard/scripts/check_utf8_docs.py AGENTS.md docs/Context-Index.md docs/Tools.md docs/context/A01-AgentRuntime/AgentRuntime-Context.md docs/context/A02-Control/Control-Context.md docs/context/A03-State/State-Context.md docs/context/A04-Orchestration/Orchestration-Context.md docs/context/GUI/GUI-Context.md 'docs/core-design/A01-AgentRuntime/04-工具调用闭合协议.md' 'docs/core-design/A01-AgentRuntime/05-文件修改事实门禁.md' docs/user-manual/configuration.md 'docs/work/T11-Agent能力补齐/T11-Agent能力补齐-checklist.md' 'docs/work/T11-Agent能力补齐/feedback/W04-联网取证与代码操作-feedback.md'`：`OK: 13 file(s) passed UTF-8 guard`。
- `conda run --no-capture-output -n re-uthcode python C:/Users/93445/.codex/t11_check_frozen.py`：`PASS: 10 frozen files unchanged except permitted checklist completion marks`。
- `git diff --check`：通过；仅报告 Windows checkout 的 LF→CRLF 提示，没有空白错误。

## 总控审核收口

Luna（max）完成 W04 实施与两轮返工；Terra（high）第三轮审核 PASS，无剩余实质 finding。首轮八项权限/限量/脱敏/配置/Windows 冲突问题与后续后台配置同步、JSON key 脱敏、活进程旧 Secret 生命周期均关闭。Reviewer 最终复跑 W04 因果链 6 passed，以及进程/会话/历史/Desktop 组合 113 passed；前轮工具与重定向证据继续有效。Worker 最终受影响回归 107 passed、82 passed，架构 23 passed，compileall、UTF-8、冻结和 diff 检查通过。Desktop 229 passed 为首轮全量，后续修复按受影响 Python/Bridge 生命周期定向验证，没有宣称最终全量重跑。A18/T19 和既有真实 Provider、POSIX、安装产物人工验收仍保留未完成，整包不标记完成、不归档。

### 行尾保留与正式搜索参数接缝（2026-10-07）

原 GPT-6 Luna / max 实施，GPT-6.1 Sol / medium 独立复审 PASS。`EditFile` 在归一化文本视图唯一匹配旧文本，只映射匹配区间两个边界，再替换原始字节区间；保留区间外 LF、CRLF、CR 和混合换行，替换文本按匹配区间→文件→平台选择样式，不产生 CRCRLF。不改变已读取版本与写权限语义。Reviewer 指出早期逐字符偏移数组额外内存过大，该临时方案已移除并复审，不作为最终实现。四类行尾的字节回归包含在 `tests/test_builtin_file_tools.py`：27 passed，1.12s。

用户已配置 Tavily，安全检查仅记录 enabled/api_key_configured，不输出秘密。正式 Application 驱动首个启动因事件类型导入路径错误 exit 1，尚未创建 Application 或发请求；修正外部驱动导入并通过 import 检查后，首轮正式 ToolCall 的 `domains` 又因 Core JsonPayload 将数组归一为 FrozenList 被工具的 list/tuple 检查拒绝。两次 invalid_input 都发生在 HTTP 前，不记搜索用量。产品最小修复接受排除 str/bytes 的 Sequence，仍校验数量和字符串成员，HTTP 投影为 list；回归直接使用真实 ToolCallPart.arguments，未放宽端点或权限。

Web fixture 增补取消后 AsyncClient 已关闭的观察和空 root + script 动态页受控 unsupported，保留重定向逐跳授权、超限、登录页及取消覆盖。Worker 最终 WebTools 8 passed / 1.58s、builtin search 17 passed / 1.10s。总控执行 `C:/Users/93445/miniconda3/envs/re-uthcode/python.exe -m pytest tests/test_builtin_file_tools.py tests/test_web_tools.py tests/test_application_tools.py tests/test_application_runs.py tests/test_architecture_boundaries.py -q`：116 passed，11.79s，exit 0。源码修复已通过复审；真实 A18 链路结果另行追加，不把这些 fixture 或受控 Turn 完成冒充联网闭环。

### A18 真实 Tavily、静态页与 PDF 闭环（2026-10-07）

本节经原 Luna / max 实施、Sol / medium 独立审核真实报告 PASS。正式配置来自用户级 search，固定端点 `https://api.tavily.com/search`、basic、include_answer=false，httpx 0.28.1；驱动使用 ScriptedProvider 发正式 Application ToolCall、ToolExecutor 与 typed PermissionApprovalResponse.ONCE，不调用外部模型、不直接调用工具 execute 或替代 HTTP 客户端、不写全局授权。真实网络服务不是 Mock。失败记录与后续证据分目录保留，没有自动重试或查询刷到成功。

修复 FrozenList 后的首轮 `application-run-20261007-seqfix`：IANA 查询受控 network_error、usage 不可观测；W3C 查询成功，5 个真实 URL、credits=1，但没有可用 PDF URL，未抓取，exit 1 / partial_or_failed。随后预先规划不同方案：复用该轮返回的 W3C 静态 URL，只新增一次针对 W3C PDF 的查询，按实际返回结果选择 `https://www.w3.org/WAI/flyer/handout2007a.pdf`，不重复 IANA 请求。

后续正式网络命令为 `C:/Users/93445/miniconda3/envs/re-uthcode/python.exe D:/uthcode-audits/t11-closeout-20261007/web-tools/run_tavily_application_audit.py --workdir D:/project/Re-UthCode --output D:/uthcode-audits/t11-closeout-20261007/web-tools/application-run-20261007-followup`。真实新增查询成功，5 个 URL、credits=1；WebFetch [W3C Reflow](https://www.w3.org/WAI/WCAG21/Understanding/reflow.html) 与 [W3C PDF flyer](https://www.w3.org/WAI/flyer/handout2007a.pdf) 均 HTTP 200，PDF MIME application/pdf、Session 副本 128572 bytes。静态正文 31113 bytes 被正式 ToolResult ref 外置；初版审计脚本直接解析占位文本导致摘要 source/content 为空，不是产品缺少正文。该轮 PDF 后续解析遇到 W03 已记录的 Windows UnicodeEncodeError，故该次 exit 1 / partial_or_failed；未改写为整轮通过。两次成功搜索各报告 1 credit，失败查询用量未知，不宣称完整累计消费恰为 2。

PDF worker 修复与独立复审后，仅恢复同 Session `e4541d63d1b244d3aef2704a22514af8`，不重搜、不重新下载：`C:/Users/93445/miniconda3/envs/re-uthcode/python.exe D:/uthcode-audits/t11-closeout-20261007/web-tools/run_tavily_session_readback.py --run-authorized`，exit 0 / passed，1.245s，网络请求与外部模型请求均 0。正式 ToolResultRead 读取静态正文 offset 0→4096 / total 31113，含 HTTP 200 来源与 Reflow 标题；正式 ReadDocument 使用已下载的完整附件引用，第一页 1947 字符、SourcePart.page=1，两条 ToolFinished 均 finished/is_error=false。没有旁路读取保存的正文文件冒充工具结果。

真实网络及本地续读报告分别在 `D:/uthcode-audits/t11-closeout-20261007/web-tools/application-run-20261007-followup/application-audit.json` 与 `application-run-20261007-local-readback/local-readback.json`，初始 invalid_input、IANA network_error 与 PDF 编码失败记录保留。结合当前 8 项 Web 测试中的重定向、超限、登录/动态空页限制与取消关闭客户端覆盖，A18 的两处引用可以补勾。该结论是正式工具真实搜索/抓取/正文链，不代表任意模型都能自主正确选用搜索工具，也不表示 T11 整包完成。


## 2026-10-08 用户 WebSearch 不可用报告与配置保存缺陷复现

用户指定Session `587b7152e4744e8ba6836af40889fccc`，要求gpt-6.1-sol / medium子代理排查“问了半天Tavily额度没有减少”。独立Sol只读排查完成：88个正式Transcript记录（13 user、41 assistant、17 tool_call/17对应tool_result），WebSearch=0、WebFetch=8、Bash=6、ToolResultRead=3；native响应均为openai/chat_completions/qwen3.7-flash。8次WebFetch含3次HTTP200成功、2次正文byte limit、1次JSON非支持文本、2次登录或动态页unsupported；6次Bash都是curl/wttr天气路径。此Session没有Tavily HTTP、鉴权、Permission拒绝或额度扣减结果，不能把Fetch限制归作Tavily搜索错误。

安全配置核对只输出字段存在性：当前用户search enabled=true、api_key字段缺失，正式load_effective_config的api_key_configured=false；该项目没有额外配置。用户配置mtime为2026-10-08 05:07:51 UTC，早于此Session创建10:10:54 UTC；正式factory只有enabled且配置Key时才注册WebSearch。native记录不保留当时SDK request.tools，未恢复当时实际请求工具列表；配置时间、当前正式加载/注册与WebSearch零调用支持“搜索凭据缺失导致工具未提供”，不单凭额度未下降归因模型能力。

发现并用正式writer/factory离线精确复现产品缺陷：Renderer settingsSaveRequest在搜索Key未编辑时省略api_key；writer._apply_search却删除请求遗漏字段，包括原有api_key。外部合成fixture通过write_user_config普通保存后Key由存在变为缺失、enabled仍true；factory有Key时注册WebSearch，丢Key后不注册。复现证据 `D:/uthcode-audits/t11-closeout-20261007/search-diagnosis/offline-20261008T103626139735Z/diagnosis.json`，只含布尔与安全配置摘要；指定Session逐次工具脱敏投影为同目录上级 `session-projection-20261008T103751729746Z.json`。两项离线脚本由既有re-uthcode解释器执行exit0，没有修改用户真实配置或仓库，没有网络/模型请求；未执行pytest，不计作修复后测试通过。此复现证明保存缺陷存在，但未保存用户当时设置操作日志，不能断言凭据恰由某次已知操作删除。

原Luna worker已接收确定finding实施最小补修：未提供搜索api_key保留原literal/env引用，显式清空继续删除；不修改Agent Loop强制联网、不放宽凭据安全或请求限量，补正式保存/加载/注册回归并交原Sol独立复审。真实丢失Key不能从上述安全视图恢复，待修复新包完成后请用户仅在设置重新输入，不在聊天传Key。本记录时源码修复与新包真实搜索续验尚未完成。另有公开正文带“Sign in”导航被登录页启发式误拒的离线候选，实际下载body未持久化，不能断言上述两个Fetch错误一定由它造成；其方案另行评估。

昨日A18正式工具真实Tavily/静态页/PDF证据保留，未通过普通设置保存测试，不用该正例否定今日配置丢失报告；也不将本次零HTTP的诊断写成搜索通过。整包仍not_implemented，冻结Checklist文字不改、不归档。


### 2026-10-08 搜索密钥省略保存补修：源码、定向与独立复审通过

原Desktop Luna / max实施、原Sol / medium独立复审PASS，三文件限 `integrations/config/writer.py`、`tests/test_w04_review_fixes.py`、`desktop/tests/renderer.test.tsx`。api_key请求省略时保留原TOML literal/env来源，显式null/空白才删除；其他Search字段原完整表删改语义不变。禁用保留凭据但factory不注册WebSearch，真实用户配置未读写，未发联网/模型请求。

新增正式write_user_configuration→load_effective_config→Application factory参数化回归先在旧代码literal/env两种均失败，补修后2 passed / 3.88s；覆盖未编辑保存继续注册、禁用保留但不注册、显式空清除且不注册，Application全部关闭。实际Renderer生产者契约 `T07 configuration request keeps API key transient and maps current schema fields`：1 passed / 1.956ms，确认未编辑不回传保存的secret/api_key_configured，清空发送空串。

worker实际执行 `C:/Users/93445/miniconda3/envs/re-uthcode/python.exe -m pytest tests/test_configuration.py::test_user_configuration_write_preserves_or_replaces_keys_without_exposing_them tests/test_configuration.py::test_user_configuration_write_retains_env_key_without_resolving_it tests/test_w04_review_fixes.py::test_settings_save_preserves_untouched_search_key_and_factory_registration tests/test_architecture_boundaries.py -q`：28 passed in 8.18s，exit0；未与导航Backend编辑混跑。Sol只读scoped diffcheck exit0，source/test复审无finding。用户手册、GUI事实与Tools说明同步省略/清空/注册条件，三文档UTF-8 guard PASS。

本段只记录源码与离线定向通过，不冒充最终新包或真实搜索通过；原worker正在继续用户反馈的目录展开/全量Recent排序修复，完成后统一更大验证与标准串行构建。当前用户搜索Key仍缺失，需要修复新包完成后在设置自行补填，再真实续验；没有修改当前失效配置，也没有刷Tavily请求。


### 2026-10-08 WebFetch 登录内容误判补修：定向与独立复审通过

用户会话 `587b7152e4744e8ba6836af40889fccc` 的两次 HTTP 200 抓取被归类为登录或动态页，但原响应正文未保存，不能将这两次失败逐一断定为本缺陷。Sol / medium 用离线 MockTransport 经过正式工具准备和执行复现：仅加入 Sign in 导航链接或公开登录教程就可能使可读正文被拒。未联网、未修改用户配置，也未消耗 Tavily 额度。

原 Luna / max worker 只修改 `src/uthcode/integrations/tools/web_tools.py` 与 `tests/test_web_tools.py`。初版复审仍发现页眉密码表单挡住公开文章、短教程被长度/标点条件误拒，交原 worker 修复；下一版仍把教程中的 Enter your password 指令误判成登录门槛，继续退回修复。最终移除长度/标点启发式，对明确登录密码提示做整段匹配；剔除密码表单后用既有提取器检查剩余正文，保留纯表单、纯 Sign in password 和明确密码门槛拒绝。公开短文、列表、页眉登录表单旁正文以及登录教程均有回归。权限、SSRF、重定向、字节上限和取消未改变。

worker 执行 `C:/Users/93445/miniconda3/envs/re-uthcode/python.exe -m pytest tests/test_web_tools.py -q`：16 passed in 1.69s，exit 0；scoped diff check 通过，原 Sol / medium 最终独立复审 PASS，全部已提 finding 关闭。Tools 与 Runtime 当前事实同步。本段为最终源码离线证据，不代表最终新包或真实网络验收通过；新包构建、用户补填搜索凭据后的真实 WebSearch 与 WebFetch 续验仍待完成。


### 2026-10-08 总控冻结后端组合回归

搜索凭据省略保存、WebFetch 登录误判及 Responses 事件补修已冻结并独立复审通过后，总控执行 `C:/Users/93445/miniconda3/envs/re-uthcode/python.exe -m pytest tests/test_configuration.py tests/test_w04_review_fixes.py tests/test_web_tools.py tests/test_openai_responses_integration.py tests/test_openai_compat_integration.py tests/test_anthropic_integration.py -q`：148 passed, 3 skipped in 7.58s，exit 0。3 个 skip 为三协议测试文件既有 live gate，测试本身明确不执行 W01 联网验收，不是三协议真实入模通过。本轮未发模型或 Tavily 网络请求、未读写用户真实配置。

该命令未包括仍在修复的导航 Application/Bridge 测试，不复用旧导航测试为新版本背书；完整 Desktop 与标准串行 package/make 待导航复审收口后执行。Responses 工具图、安装产物原生 PTY 以及最终新包真实搜索的待验边界保持不变。


### 2026-10-09 最终安装包：用户导航反馈与真实模型搜索闭环通过

用户关闭初次启动的PowerShell后报告UthCode窗口同时退出；复用同一EvidencePath被外部脚本的防覆盖保护拒绝，这是启动证据保护，不是产品新故障证据。保留原记录，用户用新r2路径重启并保持PowerShell窗口；r2证据2026-10-09 01:20:01.723 UTC，Desktop PID4628，总控readonly CIM确认Runtime14740为直接子进程、二者使用native安装目录。启动证据记录剥离Conda/四个系统PATH和所需Runtime资源存在；本轮未重新读取运行时PEB，不能把launcher环境构造描述成新的PEB实测。

用户按总控新包续验步骤反馈“都正常了”，并指定Session `9049814c91a946f991d2e38bf50f99fe`；项目展开无需新会话及Recent超过6条按该用户反馈记录，未由总控再次操作GUI。该步骤包括确认搜索配置及普通设置保存，未读取或输出用户密钥。总控仅读指定Session生成有界证据 `D:/uthcode-audits/t11-closeout-20261007/installed/final-navigation-search-session-20261009T012413130933Z.json`；原Sol独立核对指定正式记录与证据PASS：12 entries（user1、assistant5、tool_call3、tool_result3），无turn_failure。

- WebSearch sequence3→4：1次正式调用、唯一成功结果、5个Python官方文档URL；Tavily响应usage.credits=1。这是实际响应用量，未查Tavily仪表盘，不把它写成仪表盘扣费观察。
- WebFetch sequence6→7：读取 `https://docs.python.org/3/library/pathlib.html`，实际HTTP200/text-html，成功完整输出存储；没有Bash/curl替代。
- ToolResultRead sequence9→10：ref与Fetch外部输出ref精确一致，eof=true、total_bytes=61219、完整Fetch JSON60816字符，三次调用均success且按tool_call_id一对一配对。
- 持久native metadata为openai/chat_completions/qwen3.7-flash，最终assistant text2215字符已存储；本轮未捕获SDK请求正文、未单独查询Run终态，不把最终文本存储当作terminal状态poll。

本轮最终安装包真实模型WebSearch→Fetch→完整正文读取闭环已通过，弥补此前用户会话WebSearch零调用/Key缺失的界面验证空缺；不宣称所有网页或所有模型永不误调用。此前A18的真实静态页/PDF及失败fixture有效证据继续复用，本轮不新增或改写冻结验收文字。原生PTY交互/停止/关闭及Responses工具图仍待完成，Checklist5行保持未勾，整包not_implemented、未归档，尚未提交。
