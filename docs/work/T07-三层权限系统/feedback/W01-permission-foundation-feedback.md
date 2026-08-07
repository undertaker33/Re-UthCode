# W01 permission-foundation Feedback

## 1. 完成结论

已严格按 W01 Prompt 完成 Task 1 → Task 2，未开始 Task 3—Task 10，未执行 Git add/commit/push，也未归档工作包。

本次形成的 W01 边界为：

```text
registered ToolCall
    → cached JSON Schema validation
    → synchronous trusted Action preflight
    → PreparedToolCall
    → execute_prepared()
```

Permission Core 已可独立对 `PermissionAction` 求值，但按 Task 2 完成边界尚未接入 Agent Loop、Rules 文件、Application、HITL 或 UI。

## 2. Task 1：全局权限约束与 Core Domain

### 实际机制

- 新增 `src/uthcode/core/permission.py`，定义不可变、JSON-safe 的 `PermissionMode`、`Effect`、`ResourceScope`、`PermissionAction`、`Decision`、`Rule`、`RuleSet`、`SessionGrant`、`PermissionDecision` 和 `PermissionEvaluator`。
- 唯一求值顺序为 Guard → Policy → Strategy。Guard `DENY/ASK` 在三种模式均终结；Guard `ALLOW` 在 `default/auto` 继续 Policy/Strategy，在 `full_access` 放行；`full_access` 忽略普通 Policy 与 Strategy。
- Rule 来源使用显式 `priority`，高优先级来源覆盖低优先级来源；同一来源同一优先级按 `DENY > ASK > ALLOW`，没有实现全局 deny-wins。
- Session Grant 只替代 ordinary Strategy ASK，精确绑定 tool、action、Effect、资源和可选 scope；不覆盖 Guard 或 Policy DENY，不写入持久文件。
- `PermissionDecision` 保留稳定的 decision、reason、mode、matched rule/source/kind、guard continuation 和 trusted Action 事实；`to_dict()/to_json()` 不携带 Provider、Path 或第三方对象。
- 仅按 T07 要求最小更新 `SRe-AGENTS.md` 第 11 节：明确 `full_access` 仍受 Guard Ask/Deny 约束，并将持久 exact 决定改为当前 Run Session Grant 语义；其他章节未改动。

### 文件

- 新增：`src/uthcode/core/permission.py`、`tests/test_permission.py`。
- 修改：`SRe-AGENTS.md`、`src/uthcode/core/__init__.py`。

## 3. Task 2：Tool Preflight 与 Trusted Action

### 实际机制

- `ToolRegistry` 的既有 JSON Schema validator 仍只创建并缓存一份。`ToolExecutor.prepare_call()` 完成 registered check、同一缓存 validator 校验和无副作用 preflight；未知 Tool、非法参数、取消或 preflight 失败直接返回标准 error `ToolResultPart`。
- `PreparedToolCall` 保存已校验调用、注册 Tool 和可信 `PermissionAction`；`execute_prepared()` 不再次校验、不再次 preflight，只执行已准备调用并保留原有异常、取消、FIFO 和输出截断语义。
- 现有 `Tool` Protocol 保持 T04 自定义工具可用；具备权限事实的具体 Tool 实现 `ToolPreflight` hook。缺少该 hook 的嵌入式 Tool 得到保守 `UNKNOWN` Action，不生成宽泛 Allow。
- `ReadFile` 固定为 `READ/read`，`WriteFile`、`EditFile` 固定为 `WRITE/write|edit`；`Glob`、`Grep` 固定为 workspace 内 `READ`，资源使用 resolver 的规范化展示路径。
- `Bash` 新增保守分类器：覆盖常见 Git/查看命令、写操作、删除/破坏操作、外部交互和 UNKNOWN；对 `&&`、`||`、`;`、`|` 复合段逐段分类，安全前缀不能掩盖后续已知动作。命令摘要做有限凭据模式脱敏，并明确不构成 OS Sandbox。
- 六个 Provider-facing `ToolDefinition` 未增加 Effect、Action 或 Permission 字段；ToolCall 中的伪 `effect` 不参与可信分类。

### 文件

- 修改：`src/uthcode/core/tool.py`、`src/uthcode/core/__init__.py`、`src/uthcode/integrations/tools/file_tools.py`、`search_tools.py`、`process_tools.py`、`factory.py`。
- 修改测试：`tests/test_tool_core.py`、`tests/test_builtin_file_tools.py`、`tests/test_builtin_search_tools.py`、`tests/test_builtin_process_tool.py`、`tests/test_application_tools.py`。

## 4. 测试与验收结果

所有命令均使用 `conda run --no-capture-output -n re-uthcode ...`，除 UTF-8 guard 外不触发网络或真实 Provider 请求。

| 检查 | 结果 |
| --- | --- |
| `pytest tests/test_permission.py -q` | 26 passed |
| Tool core、file、search、process、application tool 定向回归 | 65 passed |
| `pytest -q` | 553 passed, 3 skipped |
| `python -m compileall -q src tests` | 通过 |
| `python -m pip check` | `No broken requirements found.` |
| `git diff --check` | 通过；仅有 Git 的 LF→CRLF 转换提示，无空白错误 |
| UTF-8 guard | `SRe-AGENTS.md` 与本 Feedback 均通过 |

当前全量测试中的 3 个 skip 仍是既有 live Provider 门禁，没有发起真实费用请求。

## 5. Checklist 状态

- Task 1：4/4 已勾选并通过。
- Task 2：5/6 已勾选并通过；“Permission evaluator 调用次数为 0”按 Task 2 明确的“不接 Rules、不触发 HITL”边界，当前以 `prepare_call()` 对 unknown/invalid/cancelled 不执行 preflight 的测试证明，正式 evaluator 调用次数留给后续主流程接入验收，不提前接入。
- Task 3—Task 10：未实施，保持未勾选。

## 6. 偏差、风险与遗留负担

- 未修改冻结的 T07 原始需求、Spec、Tasks、Prompt 文字；Checklist 只允许更新已有复选框，尚未做除此之外的内容修改。
- 未改动 `core/agent.py`、`application/runs.py`、规则 loader、Workspace outside 语义、Agent Loop、T06 Pause/Resume、TUI、CLI 或 Provider adapter；因此 Permission Ask 尚未进入正式运行链路，这是 W01 的明确完成边界而非遗漏。
- 没有新增运行时依赖、旧入口别名、双轨 executor、第二份 JSON Schema validator、PathSandbox、OS Sandbox、规则文件 loader 或未来 Skill/MCP/Plugin 占位。
- Bash 分类只承诺高置信应用层事实；无法可靠判断的命令为 `UNKNOWN`。进程执行仍是当前 OS shell/current user 下的 unsandboxed process execution。
- 当前工作树原有的 T07 工作包未跟踪目录和本次代码修改均未进行 Git 写操作；工作包等待用户审查后手动归档。

## 7. 第一轮返工

### 返工原因

首轮验收发现 Bash Git 分类器依赖宽泛只读前缀，导致 Git 分支、远端、切换/恢复、标签和删除操作被误判为 READ 或 UNKNOWN；同时 Task 2 还缺少“仅对 PreparedToolCall 调用 evaluator”的明确 gate/spy 验收证据。

### Git 分类修正方式

- 从通用 READ/WRITE/DESTRUCTIVE/EXTERNAL 命令集合中移除 Git 条目，避免整条命令以前缀命中宽泛只读项。
- 新增按 Git 子命令和关键参数分类的保守解析：只读 status/diff/log/show/rev-parse/ls-files，以及 branch/remote/tag 查询为 READ；branch 创建、checkout、switch、remote add/set-url/remove、tag 创建、add/commit/merge/rebase/stash 等为 WRITE；branch/tag 删除、rm、clean、reset --hard 和恢复工作区内容为 DESTRUCTIVE；clone/fetch/pull/push 为 EXTERNAL。
- Git 未知子命令或无法可靠判断的参数继续返回 UNKNOWN；复合命令仍逐段分类并按最高风险效果汇总，安全前缀不能掩盖后续操作。

### 新增测试覆盖

- 在 `tests/test_builtin_process_tool.py` 新增 20 个 Git 参数化样例，覆盖 branch/remote/checkout/switch/restore/rm/tag/clean/reset/fetch/pull/push 的 READ、WRITE、DESTRUCTIVE、EXTERNAL 分类，同时保留既有 Bash 复合、取消和执行回归。
- 在 `tests/test_tool_core.py` 新增 `prepare_call()` gate/spy 测试：unknown Tool 和非法参数均直接得到 error `ToolResultPart`，spy evaluator 调用次数为 0；合法调用得到 `PreparedToolCall`，evaluator 恰好调用一次。

### Task 2 Checklist 闭合情况

已仅将现有 Checklist 中 Task 2 的 evaluator 调用次数验收项由 `[ ]` 改为 `[x]`，未修改其文字、结构或顺序。Task 2 现为 6/6；Task 3—Task 10 仍未勾选且未实施。

### 验证结果

以下命令均使用 `conda run --no-capture-output -n re-uthcode`：

| 检查 | 实际结果 |
| --- | --- |
| `python -m pytest tests/test_permission.py tests/test_tool_core.py tests/test_builtin_process_tool.py -q` | 80 passed |
| `python -m pytest tests/test_tool_core.py tests/test_builtin_file_tools.py tests/test_builtin_search_tools.py tests/test_builtin_process_tool.py tests/test_application_tools.py -q` | 86 passed |
| `python -m pytest -q` | 574 passed, 3 skipped |
| `python -m compileall -q src tests` | 通过 |
| `python -m pip check` | `No broken requirements found.` |
| `git diff --check` | 通过；仅有 LF→CRLF 转换提示，无空白错误 |
| `python C:\Users\93445\.codex\skills\uth-utf8-guard\scripts\check_utf8_docs.py SRe-AGENTS.md docs\work\T07-三层权限系统\T07-三层权限系统-checklist.md docs\work\T07-三层权限系统\feedback\W01-permission-foundation-feedback.md` | `OK: 3 file(s) passed UTF-8 guard` |

### 未完成项和风险

- Task 3—Task 10 的 Rules、Workspace scope、Agent Loop、HITL、Application、TUI、CLI、Provider 和端到端接入仍是后续范围，本轮未进入这些任务。
- Git 分类器仍只承诺高置信子命令和关键参数覆盖；无法可靠判断的形式保持 UNKNOWN。Bash 仍是当前 OS 用户权限下的 unsandboxed process execution，不构成 OS Sandbox。
- 全量测试中的 3 个 skipped 仍为既有 live Provider 门禁，本轮未发起真实费用请求。
- 未执行 Git add、commit、push，未归档工作包；完成本轮后停止，等待重新验收。

本轮确认没有进入 Task 3～Task 10。

## 8. 第二轮返工

### 返工原因

第二轮验收发现 `git remote show origin` 和 `git remote show -n origin` 被统一分类为 READ，未反映 `show` 默认会查询远端、而 `-n/--no-query` 明确禁止查询的网络语义。

### `git remote show` 网络语义修正

- 将 `remote show` 从普通只读查询中拆出独立解析：默认 `show` 查询远端，分类为 EXTERNAL。
- 仅当 `show` 参数包含 `-n` 或 `--no-query`，且不存在未知选项时分类为 READ；`show` 中的未知选项组合分类为 UNKNOWN。
- 保持 `remote -v`、`remote get-url` 为 READ，`remote update/prune` 为 EXTERNAL，`remote add/set-url/remove` 为 WRITE；没有将所有 `git remote` 查询统一归为 READ。

### 新增测试用例

在 `tests/test_builtin_process_tool.py` 保留第一轮全部 Git 分类、复合命令、取消、执行和 spy evaluator 相关回归，并新增：

- `git remote get-url origin` → READ；
- `git remote show origin` → EXTERNAL；
- `git remote show -n origin` → READ；
- `git remote show --no-query origin` → READ；
- `git remote update`、`git remote prune origin` → EXTERNAL；
- `git remote show --no-query --unknown origin`、`git remote -v origin` → UNKNOWN。

第一轮已有的 `git remote -v`、`git remote add origin ...`、`git remote set-url origin ...` 用例继续保留并通过。

### 验证结果

以下命令均使用 `conda run --no-capture-output -n re-uthcode`：

| 检查 | 实际结果 |
| --- | --- |
| `python -m pytest tests/test_builtin_process_tool.py -q` | 48 passed |
| `python -m pytest tests/test_permission.py tests/test_tool_core.py tests/test_builtin_process_tool.py -q` | 88 passed |
| `python -m pytest tests/test_tool_core.py tests/test_builtin_file_tools.py tests/test_builtin_search_tools.py tests/test_builtin_process_tool.py tests/test_application_tools.py -q` | 94 passed |
| `python -m pytest -q` | 582 passed, 3 skipped |
| `python -m compileall -q src tests` | 通过 |
| `python -m pip check` | `No broken requirements found.` |
| `git diff --check` | 通过；仅有 LF→CRLF 转换提示，无空白错误 |
| `python C:\Users\93445\.codex\skills\uth-utf8-guard\scripts\check_utf8_docs.py docs\work\T07-三层权限系统\T07-三层权限系统-checklist.md docs\work\T07-三层权限系统\feedback\W01-permission-foundation-feedback.md` | `OK: 2 file(s) passed UTF-8 guard` |

### 未完成项和风险

- Task 3—Task 10 的 Rules、Workspace scope、Agent Loop、HITL、Application、TUI、CLI、Provider 和端到端接入仍未实施。
- Git 分类器仍只承诺高置信子命令和关键参数覆盖；无法可靠判断的组合保持 UNKNOWN。Bash 仍是当前 OS 用户权限下的 unsandboxed process execution，不构成 OS Sandbox。
- 全量测试中的 3 个 skipped 仍为既有 live Provider 门禁，本轮未发起真实网络或费用请求；本轮只验证分类事实，不执行远端 Git 操作。
- Task 1、Task 2 Checklist 状态未修改；未执行 Git add、commit、push，未归档工作包。

本轮确认没有进入 Task 3～Task 10，完成后停止，等待重新验收。
