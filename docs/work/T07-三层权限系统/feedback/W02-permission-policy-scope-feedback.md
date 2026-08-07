# W02 permission-policy-scope Feedback

## 1. 完成结论

已严格按 W02 Prompt 串行完成 Task 3 → Task 4 → Task 5，确认 W01 Task 1、Task 2 已完成且测试通过。本轮未进入 Task 6—Task 10，未修改 Agent Loop、T06 interaction、Application session、Slash Command、TUI/CLI 或 Provider adapter；未执行 Git add/commit/push，也未归档工作包。

## 2. Task 3：permissions.toml Discovery / Parse / Template

### 实际格式与生命周期

- 用户级文件为 `~/.uthcode/permissions.toml`，项目级文件为当前 workdir 下的 `.uthcode/permissions.toml`。
- 用户文件缺失时通过临时文件、flush/fsync、原子替换创建私有模板，模板包含 `[guard]`、`[policy]`、默认敏感 Guard 和简短 Policy 示例；项目文件缺失时创建仅含注释的空占位。
- 规则结构为 `[[guard.rules]]` 与 `[[policy.rules]]`。规则支持 `id`、`decision`、`tool`、`action`、`effect`、`resource`、`resource_regex`、`scope`、`resource_prefix`；`resource` 与 `resource_regex` 互斥，`resource_prefix` 只能用于 `resource`。
- Integration 层负责 TOML 解析、结构校验、Effect/Scope/Decision 转换和 regex 编译，Core 不依赖 TOML 或文件系统。非法 TOML、未知枚举值、非法 regex、缺失匹配目标、未知字段、错误 section/array 结构均抛出 `PermissionConfigurationError`，不静默跳过。
- 复用 `integrations/config/loader.py` 的唯一 Git root→cwd 发现算法：Git 项目按 root 到 cwd 发现，非 Git 只发现 cwd；候选路径物理解析并去重，来源顺序为 user、父项目到最近项目。实际优先级为 default=0、user=10、项目从 20 起按 root→cwd 增长，最近项目覆盖父项目和用户。
- `RuleSet` 在 `load_permission_rules()` 返回时形成不可变快照，不监视文件、不热重载；权限发现与普通 `config.toml` 生命周期完全分离。

### 文件

- 新增：`src/uthcode/integrations/permissions.py`、`tests/test_permission_rules.py`。
- 修改：`src/uthcode/integrations/config/loader.py`、`src/uthcode/integrations/config/__init__.py`、`.gitignore`。
- `.gitignore` 只新增 `**/.uthcode/permissions.toml`；`**/.uthcode/config.toml` 未被忽略。

## 3. Task 4：Workspace / Resource Scope

### 实际机制

- `WorkspacePathResolver` 继续执行 lexical normalize → physical resolve，并由 `resolve_with_scope()` / `scope_of()` 输出最终物理目标与 `INSIDE`/`OUTSIDE` 事实；outside 不再由 Resolver 硬拒绝。
- `ReadFile`、`WriteFile`、`EditFile`、`Glob`、`Grep` 的 trusted Action 使用实际 scope 和物理展示路径；`..`、新路径、文件/目录 symlink escape 均按物理目标分类。
- workspace 内部搜索仍不跟随外部文件/目录链接；显式 outside 目录的搜索可以在其已分类的物理范围内工作，不静默扩大 inside 搜索范围。
- `FileReadTracker` 的 read-before-write、changed-since-read、物理身份和成功写后更新不变量保持不变；新增测试证明 outside 目标在 scope 分类后可通过真实安全 file/search Tool 完成读写/搜索。
- 本轮只完成 Integration Tool 的 scope 事实与回归；正式“未授权不执行、授权后执行”的生产权限链尚未由 W02 接入，因此 Checklist 对应项保持未勾选，留给后续主流程接入验收。

### 文件

- 修改：`src/uthcode/integrations/tools/workspace.py`、`file_tools.py`、`search_tools.py`。
- 修改测试：`tests/test_builtin_file_tools.py`、`tests/test_builtin_search_tools.py`。

## 4. Task 5：Rule + Strategy Evaluator 与 Guard

### 实际机制

- Core `Rule` 新增 provider-independent 的 `resource_regex` matcher；规则选择仍为最高有效来源优先，同一来源内 `DENY > ASK > ALLOW`，不存在跨来源全局 deny wins。
- Guard → Policy → Strategy 顺序和三模式矩阵保持：Guard Deny/Ask 在 `default`、`auto`、`full_access` 均生效；Guard Allow 在普通模式继续 Policy/Strategy，在 `full_access` 放行；`full_access` 只忽略普通 Policy/Strategy。
- 默认敏感 Guard 覆盖 `.env`（排除 `.env.example`）、SSH、AWS/GCloud/Azure/Kubernetes/Docker/Git、npm/PyPI/netrc 凭据以及 PEM/key/SSH 私钥等；规则摘要对 Windows 反斜杠做规范化。
- `Glob` 的 metadata 枚举不自动触发内容 Guard；`Grep` preflight 只扫描候选文件的 metadata，并将有限长度的敏感路径摘要加入 Action，不读取或携带文件内容；`ReadFile` 和 `Grep` 的内容读取均在敏感 Guard 下进入 Ask。
- 默认 Bash Guard 仅覆盖高置信跨平台风险：根/用户/工作区根递归删除、磁盘格式化/原始设备写入、fork bomb、提权、递归极端权限、远程脚本管道、关键 PID，以及 Windows 磁盘操作。正例只用 preflight + evaluator mock/stub 验证，不执行危险命令；`rm -f`、普通 PID `kill -9`、`rm -rf build/` 保持不命中 Guard，但仍分类为 `DESTRUCTIVE`。
- 本轮未实现完整 Shell AST、OS/Path Sandbox、持久化 always 决定或权限 Pause/Event；Bash 仍是当前 OS shell/current user 下的 unsandboxed process execution。

### 文件

- 修改：`src/uthcode/core/permission.py`、`src/uthcode/integrations/permissions.py`、`src/uthcode/integrations/tools/search_tools.py`。
- 修改测试：`tests/test_permission.py`、`tests/test_permission_rules.py`、相关 file/search/process/tool 回归测试。

## 5. 验证结果

所有 Python 命令均使用 `conda run --no-capture-output -n re-uthcode ...`，测试使用隔离的 `tmp_path` HOME/workdir，不污染真实用户目录；未发起真实 Provider、网络或危险进程执行。

| 检查 | 实际结果 |
| --- | --- |
| `pytest tests/test_permission_rules.py tests/test_config_loader_integration.py -q` | 46 passed |
| permission、Tool core、file、search、process、application tool 回归 | 122 passed |
| `pytest -q` | 624 passed, 3 skipped |
| `python -m compileall -q src tests` | 通过 |
| `python -m pip check` | `No broken requirements found.` |
| `git diff --check` | 通过；仅有 Git 的 LF→CRLF 转换提示，无空白错误 |
| `.gitignore` 精确检查 | permissions.toml 命中；config.toml 未命中 |

## 6. Checklist 状态

- Task 3：5/5 已勾选并通过。
- Task 4：3/4 已勾选并通过；正式未授权执行阻断留给后续主流程接入，未提前虚勾选。
- Task 5：5/6 已勾选并通过；`Pause/Event` 属于后续 T06 interaction，保持未勾选。
- Task 6—Task 10：未实施，保持未勾选。

## 7. 偏差、风险与遗留负担

- 未修改冻结的 T07 原始需求、Spec、Tasks、Prompt 文字；Checklist 只更新了 Task 3—5 现有复选框。
- 未新增运行时依赖、兼容层、旧 YAML/local 规则、第二套 discovery/validator、PathSandbox、OS Sandbox、热重载、always 按钮或未来能力占位。
- outside 现在是 trusted Action 的物理范围事实，但由于正式 Agent/Application 权限链尚未接入，直接调用 Integration Tool 仍可操作已解析的 outside 目标；后续主流程必须保证只有 Permission Allow 才调用真实 execute。
- 敏感路径摘要只用于 Guard 判断和脱敏资源事实；Pause/Event 尚未形成，因此本轮不能宣称完整交互事件脱敏验收。
- 全量测试中的 3 个 skipped 为既有环境/实时 Provider 门禁，本轮未启用真实 Provider。

本轮完成 W02 Task 3—5 后停止，等待人工审查；未执行 Git 写操作，未归档工作包。

## 9. 第三轮验收返工：复合 Bash Guard 与 prepared 物理目标绑定

### 返工轮次与一次性授权

这是 W02 的第三轮验收返工。用户已明确一次性授权本轮突破原 W02 文件修改范围及 Worker 边界，允许修改 W01 所属 Core Tool 准备/执行边界及相关测试，以修复复合 Bash Guard 绕过和 prepared 物理目标漂移两个验收缺陷。除该一次性授权外，未扩大本轮范围；未修改冻结的原始需求、Spec、Tasks、Prompt 或 Checklist 文字，也未提前实施 Task 6—Task 10。

### 两个缺陷的根因

- 复合 Bash Guard 缺陷：Bash effect classifier 已能按连接符识别部分复合命令，但默认 Guard 仍主要把整条命令摘要交给带起止锚点的正则。安全前缀位于摘要开头时，后续 `&&`、`;` 或 `|` 片段中的危险命令无法命中 Guard。
- prepared 物理目标缺陷：preflight 根据原始路径解析出物理目标并产生 trusted Action，但 `execute_prepared()` 仍把原始参数传给 Tool；文件 Tool 和搜索 Tool 执行时再次解析/遍历原始 symlink 或别名，因此 prepare 与 execute 之间的重定向可以把实际访问切换到未授权目标。

### 实际修改文件

- Core 边界：`src/uthcode/core/tool.py`、`src/uthcode/core/__init__.py`。
- Tool/Guard 实现：`src/uthcode/integrations/tools/file_tools.py`、`src/uthcode/integrations/tools/search_tools.py`、`src/uthcode/integrations/tools/process_tools.py`、`src/uthcode/integrations/permissions.py`。
- 回归测试：`tests/test_tool_core.py`、`tests/test_builtin_file_tools.py`、`tests/test_builtin_search_tools.py`、`tests/test_builtin_process_tool.py`、`tests/test_permission_rules.py`。
- 本 Feedback 仅在已有文件末尾追加本节；未创建 v2/retry/fix Feedback 文件，未修改 Checklist。

### Bash 分段与 Guard 判断机制

- `process_tools.py` 的 classifier 与 Guard fact 提取共用 `_split_bash_segments()`：在引号、转义以及括号/花括号/方括号嵌套文本之外，识别 `&&`、`||`、`;`、`|` 可执行片段；`classify_bash_command()` 按片段汇总最高风险 Effect，安全前缀不能覆盖后续危险片段。
- 高置信 Guard 模式由这些片段提取为内部事实标记，再由默认 Guard 的精确标记规则判断；既有 fallback 正则继续使用片段起止锚点，没有删除 `^`/`$` 制造宽泛子串匹配。引号内普通文本、普通参数和相似文本不会生成危险事实。Windows 的 Remove-Item、Clear-Disk 等已增加等价后置片段回归。
- 单独及复合的 `rm -rf /`、`sudo whoami`、`kill -9 1` 均命中 Guard Ask；`rm -f`、普通 PID 的 `kill -9`、`rm -rf build/` 保持不命中高置信 Guard，但 Effect 仍为 `DESTRUCTIVE`。`full_access` 只跳过普通 Policy/Strategy，Guard Ask/Deny 仍然生效。危险命令测试只调用 preflight/evaluator，没有真实执行危险命令。

### prepared 物理目标绑定机制

- Core 新增不可变 `ToolPreparation`，同时携带 trusted `PermissionAction` 与 prepare 阶段绑定的 `execution_arguments`；`PreparedToolCall` 同时保存已注册 Tool、原始已校验调用、Action 和该执行 payload。
- `ToolExecutor.prepare_call()` 只使用注册 Tool 的单一缓存 JSON Schema validator，并调用一次无副作用 preflight；`execute_prepared()` 只向已绑定 Tool 传入 prepare 产生的 payload，不再按原始别名路径重新选择物理目标，也不重新 prepare 或试执行。
- `ReadFile`、`WriteFile`、`EditFile` 在 payload 中绑定已解析的物理路径；`Glob`、`Grep` 在 preflight 的 metadata 枚举中绑定相对匹配路径和对应物理文件，执行时使用保存的物理候选，不重新解析原始搜索路径。Grep 的显式 outside 目录 symlink 也按 prepare 时的物理 scope 和候选目标绑定。
- preflight 不读取文件内容、不写文件、不启动进程；Core 不依赖 TOML、Provider SDK、Application、Interfaces 或具体文件系统实现。本轮只保证 prepare 后原始 symlink/别名重定向不会让执行转到另一个未授权物理目标，不宣称解决所有操作系统级 TOCTOU，也未实现 OS Sandbox。

### 新增防回归测试

- Guard：六个单独/复合 Unix 高风险命令、`full_access` 下 Guard Ask、quoted/similar text 反例、Windows 复合后置危险片段，以及低置信删除/普通 PID 反例。
- File Tool：ReadFile、WriteFile、EditFile 在 prepare 后将 symlink 从 workspace 内目标改指 workspace 外目标，分别验证实际读取/写入/编辑仍绑定原物理目标；Action resource 与实际目标一致。
- Search Tool：Glob/Grep 的文件 symlink 重定向回归，以及 Grep 的目录 symlink 重定向回归；验证不会搜索或返回重定向目标中的标记文本。Tool Core 另验证 prepared 执行不会重复 preflight。

### 验证结果

所有 Python 命令均使用 `conda run --no-capture-output -n re-uthcode ...`；pytest 使用隔离临时目录，未污染真实 HOME 或 `~/.uthcode`，未访问真实敏感文件，未执行危险 Bash 命令。

| 检查 | 实际结果 |
| --- | --- |
| `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_permission.py tests/test_permission_rules.py tests/test_builtin_process_tool.py -q` | 127 passed |
| `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_tool_core.py tests/test_builtin_file_tools.py tests/test_builtin_search_tools.py -q` | 48 passed |
| `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_permission.py tests/test_permission_rules.py tests/test_tool_core.py tests/test_builtin_file_tools.py tests/test_builtin_search_tools.py tests/test_builtin_process_tool.py tests/test_application_tools.py tests/test_config_loader_integration.py -q` | 187 passed |
| `conda run --no-capture-output -n re-uthcode python -m pytest -q` | 643 passed, 3 skipped |
| `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests` | 通过 |
| `conda run --no-capture-output -n re-uthcode python -m pip check` | `No broken requirements found.` |
| `git diff --check` | 通过；仅有 Git 的 LF→CRLF 转换提示，无空白错误 |
| `conda run --no-capture-output -n re-uthcode python C:\Users\93445\.codex\skills\uth-utf8-guard\scripts\check_utf8_docs.py AGENTS.md SRe-AGENTS.md docs/work/README.md docs/work/T07-三层权限系统/T07-三层权限系统.md docs/work/T07-三层权限系统/T07-三层权限系统-spec.md docs/work/T07-三层权限系统/T07-三层权限系统-tasks.md docs/work/T07-三层权限系统/T07-三层权限系统-checklist.md docs/work/T07-三层权限系统/prompt/W01-permission-foundation-prompt.md docs/work/T07-三层权限系统/prompt/W02-permission-policy-scope-prompt.md docs/work/T07-三层权限系统/feedback/W01-permission-foundation-feedback.md docs/work/T07-三层权限系统/feedback/W02-permission-policy-scope-feedback.md` | `OK: 11 file(s) passed UTF-8 guard` |

### Checklist、后续边界与收尾

- Task 4 的“outside 文件未授权不执行、授权后通过正式权限 Tool 链执行”仍未勾选，归属后续 Task 8 的正式 Application/Composition 权限链；本轮只修复物理目标绑定，不提前实现正式授权链。
- Task 5 的“Pause/Event 只包含脱敏摘要”仍未勾选，归属后续 Task 6/T06 interaction；本轮未实现 Pause/Event。
- 本轮未实现 OS Sandbox、完整 Shell AST、Pause/Event 或正式 Application 权限链，未接入 Agent Loop、TUI、CLI 或 Slash Command；Task 6—Task 10 继续保持未实施/未勾选。
- 未执行任何 Git add、commit、push 或其他 Git 写操作，未归档工作包；本节完成后停止，等待人工复查。

## 10. 第四轮验收返工：嵌套、换行与后台 Bash Guard

### 返工原因与根因

第三轮实现仍在扫描前用空格折叠整条命令，导致未引用换行这一真实命令分隔符消失；扫描器同时跳过圆括号和花括号内部，且没有识别单 `&` 后台连接符。因此安全前缀后的换行命令、子 Shell/分组、命令替换和后台命令可在 `full_access` 下绕过 Guard。

### 实际修改

- 修改 `src/uthcode/integrations/tools/process_tools.py`：以同一个确定性扫描器同时服务 effect classifier 与 Guard fact 提取。扫描器保留未引用换行，识别 `&&`、`||`、`;`、`|` 和单 `&`；不会把重定向中的 `>&`/`&>` 当成后台连接符。
- 对未引用的圆括号分组、花括号分组、`$(...)` 和反引号命令替换生成 `nested-execution` Guard fact。当前实现不声称完整解析嵌套 Shell 语法；无法可靠展开但会执行嵌套命令的结构保守进入 Guard Ask。
- 引号和转义继续由同一扫描器识别；引号内换行、命令文本和被转义的反引号不生成嵌套执行 fact，也没有改成宽泛的危险字符串子串匹配。
- 修改 `tests/test_permission_rules.py`：先增加失败回归，再验证换行、单 `&`、圆/花括号分组、`$(...)` 和反引号命令替换在 `full_access` 下仍为 Guard Ask；同时验证指定的引号与转义反例保持 Allow。测试只调用 `BashTool.preflight()` 和 `PermissionEvaluator`，未执行任何命令。
- 未修改第三轮已经验收的 prepared 物理目标绑定，也未修改冻结的原始需求、Spec、Tasks、Prompt 或 Checklist。

### 重新验证结果

所有 Python 命令均使用 `conda run --no-capture-output -n re-uthcode ...`。

| 检查 | 实际结果 |
| --- | --- |
| `python -m pytest tests/test_permission_rules.py -q`（修复前） | 6 failed, 57 passed；六个新增危险结构均稳定复现绕过 |
| `python -m pytest tests/test_permission_rules.py tests/test_builtin_process_tool.py -q` | 111 passed |
| `python -m pytest tests/test_permission.py tests/test_permission_rules.py tests/test_tool_core.py tests/test_builtin_file_tools.py tests/test_builtin_search_tools.py tests/test_builtin_process_tool.py tests/test_application_tools.py tests/test_config_loader_integration.py -q` | 197 passed |
| `python -m pytest -q` | 653 passed, 3 skipped |
| `python -m compileall -q src tests` | 通过 |
| `python -m pip check` | `No broken requirements found.` |
| `git diff --check` | 通过；仅有 LF→CRLF 转换提示，无空白错误 |

### 边界与收尾

- 本轮没有实现完整 Shell AST、OS Sandbox、Pause/Event、正式 Application 权限链或 Task 6—Task 10。
- Task 4 的正式权限 Tool 链验收项和 Task 5 的 Pause/Event 脱敏验收项仍保持未勾选，等待其所属后续 Worker 提供证据。
- 未执行 Git add、commit、push 或其他 Git 写，未归档工作包；完成后停止，等待独立验收。

## 11. 第五轮验收返工：双引号内命令替换

### 返工原因与根因

第四轮把所有引号内容统一视为普通文本，这是错误的 POSIX shell 假设。单引号会抑制命令替换，但双引号中的未转义 `$()` 和反引号仍会执行内部命令；因此 `echo "$(rm -rf /)"` 与双引号包裹的反引号命令替换仍可在 `full_access` 下绕过 Guard。

### 实际修改

- 修改 `src/uthcode/integrations/tools/process_tools.py`：扫描器现在区分单引号与双引号。单引号内容保持不解释；双引号内未转义的 `$(` 与反引号生成 `nested-execution` Guard fact；双引号内用反斜杠转义的 `$` 或反引号不生成该 fact。
- 修改 `tests/test_permission_rules.py`：先增加两个失败回归，证明双引号内 `$()` 与反引号替换此前为 Allow；修复后两者在 `full_access` 下均为 Guard Ask。反例覆盖单引号内 `$()`/反引号、双引号内转义替换符、纯双引号危险文本及双引号内普通换行，均保持 Allow。
- 所有测试仍只调用 `BashTool.preflight()` 与 `PermissionEvaluator`，没有执行测试命令。
- 未修改 prepared 物理目标绑定、Checklist 或其他冻结文件。

### 重新验证结果

| 检查 | 实际结果 |
| --- | --- |
| 双引号命令替换聚焦测试（修复前） | 2 failed, 13 passed；两个新增绕过均稳定复现 |
| 双引号命令替换聚焦测试（修复后） | 15 passed, 53 deselected |
| `python -m pytest tests/test_permission_rules.py tests/test_builtin_process_tool.py -q` | 116 passed |
| `python -m pytest tests/test_permission.py tests/test_permission_rules.py tests/test_tool_core.py tests/test_builtin_file_tools.py tests/test_builtin_search_tools.py tests/test_builtin_process_tool.py tests/test_application_tools.py tests/test_config_loader_integration.py -q` | 202 passed |
| `python -m pytest -q` | 658 passed, 3 skipped |
| `python -m compileall -q src tests` | 通过 |
| `python -m pip check` | `No broken requirements found.` |
| `git diff --check` | 通过；仅有 LF→CRLF 转换提示，无空白错误 |

### 边界与收尾

- 本轮仍未实现完整 Shell AST、OS Sandbox、Pause/Event、正式 Application 权限链或 Task 6—Task 10。
- Task 4 与 Task 5 的两个跨 Worker Checklist 项保持未勾选。
- 未执行 Git add、commit、push 或其他 Git 写，未归档工作包；完成后等待独立验收。

## 12. 第六轮验收返工：算术展开误报

### 返工原因与根因

第五轮把所有 `$((` 前缀也按 `$(` 命令替换标记为 `nested-execution`，导致纯 Bash 算术展开在 `full_access` 下错误进入 Guard Ask。`$((...))` 本身不执行命令，不能作为高置信危险事实；但算术表达式内部仍可能包含真实的 `$()` 或反引号命令替换。

### 实际修改

- 修改 `src/uthcode/integrations/tools/process_tools.py`：在既有确定性扫描器中增加最小算术括号深度状态。未引用和双引号内的 `$((...))` 只跟踪配对括号，不生成嵌套执行 fact，也不把表达式内的控制字符误当作顶层连接符。
- 算术状态不会整段跳过内容：内部遇到 `$()` 时记录 `nested-execution` 并跟踪其括号，遇到未转义反引号时同样记录危险事实。单引号与双引号转义语义保持第五轮结果。
- 修改 `tests/test_permission_rules.py`：先增加纯算术展开失败回归，覆盖未引号、双引号和赋值后复合命令；另增加算术内部 `$()`、反引号及双引号包裹场景，确保仍为 Guard Ask。所有用例只执行 preflight/evaluator。
- 未实现完整 Shell AST，未扩大到其他 Shell 语法；未修改 prepared 绑定、Checklist 或其他冻结文件。

### 重新验证结果

| 检查 | 实际结果 |
| --- | --- |
| 算术展开聚焦测试（修复前） | 3 failed, 3 passed；三个纯算术误报均稳定复现 |
| 算术与既有嵌套/引号矩阵（修复后） | 21 passed, 53 deselected |
| `python -m pytest tests/test_permission_rules.py tests/test_builtin_process_tool.py -q` | 122 passed |
| `python -m pytest tests/test_permission.py tests/test_permission_rules.py tests/test_tool_core.py tests/test_builtin_file_tools.py tests/test_builtin_search_tools.py tests/test_builtin_process_tool.py tests/test_application_tools.py tests/test_config_loader_integration.py -q` | 208 passed |
| `python -m pytest -q` | 664 passed, 3 skipped |
| `python -m compileall -q src tests` | 通过 |
| `python -m pip check` | `No broken requirements found.` |
| `git diff --check` | 通过；仅有 LF→CRLF 转换提示，无空白错误 |

### 边界与收尾

- 本轮仍未实现完整 Shell AST、OS Sandbox、Pause/Event、正式 Application 权限链或 Task 6—Task 10。
- Task 4 与 Task 5 的两个跨 Worker Checklist 项继续保持未勾选。
- 未执行 Git add、commit、push 或其他 Git 写，未归档工作包；完成后等待独立验收。
