# W04 Permission Delivery Feedback

## 2026-08-08 初始交付记录

### 范围与前置结论

- 已完整读取并遵守 `AGENTS.md`、`SRe-AGENTS.md`、`docs/work/README.md`、T07 原始需求/Spec/Tasks/Checklist、W01～W03 Prompt/Feedback，以及 T04～T06 的 Spec/Tasks/Checklist/Feedback。
- 当前分支已有的 W03 实现、Checklist 改动和 `W03-permission-interaction-feedback.md` 均保留；本次未执行还原、覆盖、Git add、commit、push 或归档。
- W02 Task 4/5 的两个未勾选项按用户确认作为 W04 正式 Composition/E2E 的待补证据处理，没有阻断 W04。
- 未启用 `.uth-governance/project.json`，未走 UTH 场景路由。

### Task 8～9 已接通的正式生产链

正式 `create_application(...).create_run()` 现在为每个 Run 加载一次 user/project `permissions.toml`，生成新的不可变 `RuleSet`/`PermissionEvaluator` 快照。普通 Tool 的唯一生产链为：

```text
Provider normalized ToolCall
  -> Application AgentLoop
  -> ToolRegistry registered/schema validation
  -> ToolExecutor prepare_call / trusted Tool preflight Action
  -> Run-local PermissionEvaluator: Guard -> Policy -> Session Grant -> Strategy
  -> Allow / Deny / Ask
  -> one execute_prepared / ToolResult
  -> T06 Application TurnHandle Pause/Resume when Ask
```

AskUserQuestion 仍是 T06 独立控制路径。Application 的公开手动 Tool 入口明确拒绝；未被生产调用的 `ApplicationToolService.execute_calls` 手动旁路已删除。Provider adapter 只输出规范化 Provider/Core ToolCall，不含权限分支或权限 metadata。

### 本次实际修改文件

- `src/uthcode/application/bootstrap.py`：在正式 Composition root 注入权限规则加载器。
- `src/uthcode/application/generation.py`：在 Run 创建边界加载一次 `RuleSet` 快照，并安全拒绝手动 Tool 执行入口。
- `src/uthcode/application/tools.py`：删除未被生产调用的手动 batch 执行旁路；Grep 的事件/暂停摘要不再回显搜索 pattern。
- `tests/test_permission_delivery.py`：新增正式 Application/Headless、文件安全、敏感 Guard、mode/session、非法配置和三 Provider 对等 E2E。
- `tests/test_application_tools.py`、`tests/test_application_runs.py`、`tests/test_cli.py`、`tests/test_architecture_boundaries.py`：更新手动入口、脱敏摘要、隔离 workdir 和架构边界回归证据。
- `tests/conftest.py`：所有测试自动使用临时 HOME，避免权限/config 生命周期文件污染真实用户目录。
- `docs/work/T07-三层权限系统/T07-三层权限系统-checklist.md`：仅在最终验证确实通过后勾选已有项目，不修改 Checklist 文字。

### Task 4/5 暂缓项的补齐证据

- Task 4：`test_formal_outside_write_is_unchanged_until_approval_then_writes_once` 从正式 Application bootstrap/Run 发起 outside `WriteFile`；Permission Pause 前隔离临时目标不存在，批准后真实写入，且 preflight/execute 各一次。
- Task 5：`test_formal_read_and_grep_sensitive_resources_enter_guard_without_content_leak` 对 `.env` 的 `ReadFile` 与 Grep 均进入 Guard；仅允许 once/reject；本次选择 reject，Pause/Event、ToolFinished、ToolResult/error 中均不出现敏感内容。Grep 摘要不包含 pattern。

### 已完成的聚焦证据

- W04 delivery tests：8 passed。
- Application/tools/runs/CLI/architecture 聚焦回归：本轮已通过；初始 Composition 回归为 76 passed，权限/配置/内置文件与搜索回归为 120 passed。
- 三 Provider 对等测试实际驱动 Anthropic、OpenAI Responses、OpenAI-compatible adapter，规范化 ToolCall 经同一 Registry/Preparation 后得到相同 Action 与 Decision。

### 当前待最终验证项目

- Task 8～10 Checklist 的最终勾选、全量 pytest、compileall、pip check、git diff --check、修改 Markdown 的 UTF-8/fence 检查，待同一轮最终验证完成后追加记录。
- 危险 Bash 仅保留 preflight/evaluator/mock 证据，本次没有真实执行危险命令，也没有访问真实敏感文件。

## 2026-08-08 最终验证记录

### 最终测试与门禁结果

- `conda run --no-capture-output -n re-uthcode python -m pytest -q`：`684 passed, 3 skipped`。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests`：退出码 0。
- `conda run --no-capture-output -n re-uthcode python -m pip check`：`No broken requirements found.`。
- `git diff --check`：退出码 0，无空白错误；Git 输出的 CRLF 转换提示不是 diff 检查错误。
- UTF-8/fence guard：对 `SRe-AGENTS.md` 与 T07 工作包 13 个 Markdown 文件执行严格 UTF-8 解码和 fenced block 配对检查，全部通过。
- Task 10 遗留扫描：精确命令命中的内容只有 SRe-AGENTS.md 对 LangGraph 的明确否定治理文字和 `tests/test_system_prompt.py` 的负向能力测试；未发现生产遗留语义。

### Checklist 最终状态

- Task 4 outside 真实 Tool 读写项：`[x]`。
- Task 5 ReadFile/Grep 脱敏项：`[x]`。
- Task 8 五项：全部 `[x]`。
- Task 9 七项：全部 `[x]`。
- Task 10 七项：全部 `[x]`。
- Checklist 仅发生已有项目的 `[ ]` → `[x]` 状态变化；未修改任何 Checklist 文字。W03 原有 Task 6/7 勾选状态和实现继续保留。

### 遗留清理、安全与风险

- 删除了未被生产调用的 `ApplicationToolService.execute_calls` 手动执行旁路；正式普通 Tool 只由 AgentRun/Application AgentLoop 驱动。
- 未发现第二 schema validator、第二 Pause waiter、第二 Slash dispatcher、Interface→Core/Integration 反向依赖或 Provider 权限特判。
- 全部本轮 filesystem E2E 使用 pytest 临时 HOME/workdir；危险 Bash 没有真实执行。
- 初始测试在隔离 fixture 加入前曾生成 `C:\Users\93445\.uthcode\permissions.toml` 和仓库 `.uthcode\permissions.toml` 两个模板；已确认后仅删除这两个本轮生成文件，保留更早存在的用户 `config.toml`，最终路径均不存在。
- 未完成风险：W04 未扩大到 OS Sandbox、完整 Shell AST、持久化批准或其他 T07 范围外能力；这些均按边界不实现。
- Git 写操作未执行：未 add、commit、push、建分支、合并或归档工作包，等待人工验收。

## 2026-08-08 T07 包级缺陷修复返工记录

### 范围与修复结论

本轮针对 T07 包级验收发现的四项缺陷返工，未修改冻结的需求、Spec、Design、Tasks；Checklist 未在本轮改写。除本 Feedback 追加外，没有写入其他工作包 Markdown。未执行 Git add、commit、push、PR、merge、reset、checkout 或其他 Git 写操作，完成后等待独立复查。

四项缺陷均已修复：Bash 凭据不再进入 Action/Pause/Approval JSON/ToolStarted/Event；普通 Tool 不再有旧直执行入口且缺少 resolver 会硬失败；outside 文件 Session Grant 绑定规范化父目录并保留 tool/action/effect/scope 维度；Bash metadata 与真实内容读取、搜索、写入已分离，嵌套和组合命令保持保守拦截。

### 根因与修改

1. Bash 原有摘要只覆盖少量 assignment、Bearer 和 token 形状，没有覆盖 URL userinfo、curl/wget 认证选项、Authorization/Proxy-Authorization header 和敏感 query 参数；PermissionAction.resource 与 Application 的 ToolStarted 摘要因此各自存在泄漏缺口。新增 `src/uthcode/core/command_security.py` 作为集中安全摘要实现，由 Bash preflight 与 Application 事件摘要共同复用，并在 Bash Action resource 中加入可信的操作事实标记。默认 Bash Guard 只匹配 content-read、content-search、write、mixed、unknown 标记，认证方案和命令结构保留，秘密值被替换。
2. `ToolExecutor.execute_call()`、`execute_batch()` 和 Application Tool service 的手动执行路径形成 evaluator 旁路；AgentLoop 在没有 permission resolver 时仍有直接 execute 分支。生产代码删除旧 Core 入口，Application 手动入口明确拒绝，AgentRun 在创建 AgentLoop 时注入 Run-local resolver/session sink，AgentLoop、configure_permission 和执行前分支均对缺少 resolver 硬失败；AskUserQuestion 仍只保留 T06 独立控制路径。
3. `_store_session_grant()` 原来保存 outside 文件的精确 resource，无法复用同一物理目录。现在 outside `ReadFile`/`WriteFile`/`EditFile` 的 Session Grant 使用规范化父目录 prefix；Core 使用 Windows drive/UNC 的大小写不敏感规范化、POSIX 规范化和 component boundary 匹配，避免相邻目录、父目录误扩大或名称前缀相似误授权。tool、action、effect、scope 仍全部参与匹配，Guard/Policy 仍先于 Session Grant。
4. default Guard 原来直接对 Bash 完整摘要匹配敏感文件名，metadata 命令因此与内容访问混淆。Bash preflight 现在按分段、重定向、命令替换、管道、组合和常见 opaque nested executor 生成 metadata/content-read/content-search/write/mixed/unknown 事实；只有可信的内容读取、搜索、写入或无法安全判定的 unknown 事实进入敏感 Bash Guard，metadata 不因文件名单独触发。

实际修改的生产文件：

- `src/uthcode/core/command_security.py`
- `src/uthcode/core/tool.py`
- `src/uthcode/core/agent.py`
- `src/uthcode/core/permission.py`
- `src/uthcode/application/generation.py`
- `src/uthcode/application/runs.py`
- `src/uthcode/application/tools.py`
- `src/uthcode/integrations/permissions.py`
- `src/uthcode/integrations/tools/process_tools.py`

实际修改的回归测试文件：

- `tests/test_permission_delivery.py`
- `tests/test_tool_core.py`
- `tests/test_agent_loop.py`
- `tests/test_application_tools.py`
- `tests/test_builtin_file_tools.py`
- `tests/test_builtin_process_tool.py`
- `tests/test_builtin_search_tools.py`
- `tests/test_architecture_boundaries.py`

### 修复前失败测试记录

- 首次新增回归测试运行：`conda run --no-capture-output -n re-uthcode python -m pytest tests/test_permission_delivery.py -q`，结果为 `17 failed, 11 passed`。
- 修正 Guard 回归测试的 RuleSet 测试夹具后，缺陷聚焦运行 `-k "bash_credentials or bash_sensitive or outside_session or legacy_direct or hard_fails"`，结果为 `11 failed, 9 passed, 8 deselected`。
- 失败覆盖了 URL userinfo、curl `-u/--user`、认证 header、metadata 敏感误报、outside 精确 Grant 无法复用、旧直执行属性仍存在，以及缺少 permission resolver 仍可启动执行等问题；这些结果均发生在生产修复之前。

### 修复后验证证据

- Bash 凭据、metadata/content Guard、outside Session Grant 正式 Agent Run、旧入口删除和 resolver 硬失败聚焦测试：`tests/test_permission_delivery.py` 全部 `35 passed`。
- T07 W01-W04 相关测试（Permission/Core Tool、内置 File/Process/Search、Permission Rules/Integration、Agent/Interaction、Application Run/Tools/Delivery、Provider parity、CLI/TUI/Command、Architecture）：`548 passed, 3 skipped`。
- 全量测试：`conda run --no-capture-output -n re-uthcode python -m pytest -q`，结果 `711 passed, 3 skipped`。
- 静态/环境检查：`conda run --no-capture-output -n re-uthcode python -m compileall -q src tests` 退出码 0；`conda run --no-capture-output -n re-uthcode python -m pip check` 输出 `No broken requirements found.`；`git diff --check` 退出码 0，仅有既存的 LF/CRLF 转换提示，无 whitespace error。
- 权限链扫描：`src/uthcode` 中不存在 `execute_call`、`execute_batch`、`execute_calls` 名称；唯一保留的 `execute_prepared` 是 W01 frozen prepared boundary，由正式 AgentTurnExecution 在 evaluator Allow 后调用。
- Markdown UTF-8/fence guard：`conda run --no-capture-output -n re-uthcode python C:\Users\93445\.codex\skills\uth-utf8-guard\scripts\check_utf8_docs.py docs/work/T07-三层权限系统/feedback/W04-permission-delivery-feedback.md`，结果 `OK: 1 file(s) passed UTF-8 guard`。

### 已知剩余风险

- Bash 仍是保守的结构化扫描器，不是完整 shell AST，也不提供 OS sandbox；无法安全证明的组合会落入 unknown 并触发敏感 Guard，复杂 shell 语法仍需独立复查。
- 本轮未真实执行危险 Bash 或真实敏感文件内容；全量测试中的 3 个 skipped 保持既有实时 Provider/环境门禁语义。
- outside Grant 解决的是 Run-local 逻辑范围与路径边界，不宣称消除操作系统级 TOCTOU 或提供持久化授权。

## 2026-08-08 根级 Grant、metadata 管道与重复注入入口返工记录

### 根因与实际修改

- 根级 outside Grant 的根因是 `_outside_parent_resource()` 对所有文件都无条件保存父路径；POSIX `/`、Windows `C:/` 和 UNC share root 因而变成宽泛 prefix。`src/uthcode/application/runs.py` 现在显式识别三类根，根级目标回退规范化 exact-file grant；`src/uthcode/core/permission.py` 对 drive/UNC 使用大小写不敏感的规范化 exact 匹配，并拒绝根路径 prefix 与不安全裸字符串边界。普通目录仍绑定规范化父目录，tool/action/effect/scope、Guard 和 Policy 优先级保持不变。
- metadata 管道误报的根因是 Bash action marker 只记录整条命令的聚合 content-read/unknown 类型，默认敏感 Guard 再对整条摘要查找敏感文件名；`ls/stat/echo .env | cat` 中后续 stdin reader 因而继承了前段 metadata 路径。`src/uthcode/integrations/tools/process_tools.py` 现在按 segment、输入/输出重定向和嵌套执行关联敏感 target fact，`src/uthcode/integrations/permissions.py` 的 Bash Guard 只匹配关联 marker；显式内容 reader、搜索、写入、`-exec`/`xargs`/shell/PowerShell nested 仍保守进入 Guard。
- 重复 Permission 注入的根因是 `AgentTurnExecution.configure_permission()` 暴露了构造阶段注入之外的第二个 callback 入口。`src/uthcode/core/agent.py` 已删除该方法；resolver/session sink 只保留 `AgentLoop`/`AgentTurnExecution` 构造注入，普通 Tool 缺 resolver 仍在 start/execute 硬失败。

### 修改文件

生产代码：

- `src/uthcode/application/runs.py`
- `src/uthcode/core/permission.py`
- `src/uthcode/core/agent.py`
- `src/uthcode/integrations/permissions.py`
- `src/uthcode/integrations/tools/process_tools.py`

回归测试：

- `tests/test_permission_delivery.py`

本轮只追加本 Feedback；未修改冻结的需求、Spec、Design、Tasks、Prompt 或 Checklist。

### 修复前失败证据

先加入回归测试再运行：

```text
conda run --no-capture-output -n re-uthcode python -m pytest tests/test_permission_delivery.py -k "root_outside_session_grant_is_exact_file_only or session_grant_resource_prefix_never_crosses_root_or_dimension_boundaries or bash_sensitive_guard_distinguishes_metadata_from_content or agent_turn_execution_has_only_constructor_permission_injection" -q
```

修复前结果：`9 failed, 19 passed, 20 deselected`。失败稳定覆盖三类根级路径越权、根 prefix 防护、五种 metadata 管道/格式化误报和 `configure_permission()` 残留。

### 修复后验证

- 新增回归聚焦测试：`28 passed, 20 deselected`。
- T07 W01-W04 相关 Permission、Agent、Tool、Application、Process、CLI/TUI、Provider 和架构测试：`614 passed, 3 skipped`。
- 全量测试：`conda run --no-capture-output -n re-uthcode python -m pytest -q`，`724 passed, 3 skipped`。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests`：退出码 0。
- `conda run --no-capture-output -n re-uthcode python -m pip check`：`No broken requirements found.`。
- `git diff --check`：退出码 0；仅有既有 LF/CRLF 转换提示，无 whitespace error。
- `rg` 扫描 `src/uthcode`：`configure_permission`、`execute_call`、`execute_batch`、`execute_calls` 均无匹配；生产执行引用只保留 AgentLoop evaluator Allow 后的 `execute_prepared`。
- UTF-8 guard：已对本 Feedback 执行 UTF-8、mojibake 和 Markdown fence 检查，结果 `OK: 1 file(s) passed UTF-8 guard`。

### 已知剩余风险

- Bash 仍是保守的分段扫描器，不是完整 Bash/PowerShell AST，也不提供 OS sandbox；无法可靠判断的复杂嵌套继续按 unknown/Guard 保守处理。
- 根级 exact Grant 解决的是 Run-local 逻辑边界，不提供操作系统级 TOCTOU 防护或持久化授权。
- 全量测试中的 3 个 skipped 仍是既有实时 Provider/环境门禁；本轮未执行危险 Bash 或真实敏感文件操作。
- Checklist 未回退或改写；本轮没有执行任何 Git add、commit、push、PR、merge、reset、checkout 或其他 Git 写操作，等待独立复查。
