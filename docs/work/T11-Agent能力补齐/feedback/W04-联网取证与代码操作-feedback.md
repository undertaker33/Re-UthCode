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
