# W02 application-run Feedback

## 执行范围与边界

本轮由用户明确派发 `prompt/W02-application-run-prompt.md`，严格执行
Task 3 → Task 4；没有开始 Task 5–Task 9，没有执行 Git 写操作，也没有访
问真实 Provider、网络或用户工作区外路径。T05 工作包仍位于
`docs/work/`，未由 Agent 归档。

开始前已读取 AGENTS、SRe-AGENTS、工作包规则、T05 原始需求/Spec/Tasks/
Checklist、W01 Feedback、T04 Application Tool 资料和 T03 Prompt 资料。基线
验证为：`HEAD=20fc83f7275d532465d7f88c78c3e3a7c8ba0fcf`，
`387 passed, 3 skipped`，compileall、pip check 和 `git diff --check` 通过。
当前 HEAD 包含 W01 的 T05 合并提交；这与原始任务书记录的 T04 固定 SHA 不同，
但正是 W02 所要求的 W01 Core 交付基线，未回退或改写该交付。

## Task 3：Application Run/Turn 与安全 Tool 摘要

### 实际调用链

```text
UthCodeApplication.create_run()
→ AgentRun.start_turn()
→ Application 捕获 Provider / model ref / Tool definitions / token
→ Core AgentLoop.start_turn()
→ 首次 events() 或 result() 才启动 AgentTurnExecution
→ Application 每 iteration 准备 GenerationRequest
→ Core Loop 复用同一 Tool Registry/Executor
→ TurnHandle.events() / result()
```

- `AgentRun` 只保存内存中的 Core 状态引用和当前活动 Turn；`start_turn()`
  同步校验输入、创建 Turn 并立即占用 Run，不需要当前已有事件循环。
- `TurnHandle` 不公开 RunState、Provider、Registry、Executor 或取消令牌。
  事件流由 Core 的单生产者提供，第二个消费者立即拒绝；`result()` 通过同一
  terminal 可重复等待并返回同一个不可变 `TurnResult`。
- `cancel()` 首次请求成功、后续幂等；Core 完成失败/取消收口后，Application
  保存最新已协议闭合状态并释放 Run，下一 Turn 可以继续。
- 同一 Run 的下一 Turn 使用此前权威 conversation；不同 Run 的 state、
  conversation 和取消令牌独立。不同 Application 仍创建不同的 T04 Tool
  Runtime；同一 Application 的多个 Run 复用同一 Registry/Executor。
- Turn 开始时捕获 Provider 和 model ref。System Prompt 在每个 iteration 由
  Application 重新构建，但使用捕获的 Provider/model/context；活动 Turn 中
  的模型切换只影响下一 Turn。Agent 请求自动携带固定有序 Tool definitions，
  raw `start_generation()` 仍不自动注入 tools。

### 安全摘要

`ApplicationToolService.describe_tool_call()` 是正式 Tool Runtime 的唯一摘要
入口。当前默认 Tool 的摘要为命令、文件操作与相对路径、或搜索 pattern 与
scope；WriteFile 的 content、EditFile 的 old/new 文本、ToolResult、unknown
参数和任意自定义 Tool 参数不会被回显。绝对路径会被转换为工作区相对路径或
安全占位，敏感 token/secret 形态会被遮蔽，摘要压缩为单行并稳定限制在 240
个 Unicode 字符内。摘要失败由 Core 转为 `<tool summary unavailable>`，不
阻止对应 Tool 执行。

### 修改文件

- 新增 `src/uthcode/application/runs.py`。
- 修改 `src/uthcode/application/generation.py`、`tools.py`、`bootstrap.py`、
  `__init__.py`。
- 新增 `tests/test_application_runs.py`，补充 `tests/test_package.py` 的
  Application Agent 导出和内部类型隔离断言。

## Task 4：Headless Agent 端到端闭环

测试从正式入口
`create_application(temp_workdir) → create_run() → start_turn()` 开始：

1. Fake Provider 先发 reasoning 和 ReadFile ToolCall。
2. Application 使用真实临时 workdir 中的 ReadFile Integration Tool 执行。
3. 同一 ToolCall ID、真实读取内容和 ToolResult 按协议进入第二次 Provider
   请求。
4. 第二次响应产生 final，事件流产生唯一 `TurnCompleted`，TurnResult 只保留
   final 与统计。

回归断言还覆盖 reasoning/Tool 活动顺序、同 Run 多 Turn、不同 Run 隔离、
失败/取消后的继续、模型快照、摘要异常继续执行、低层手动 Tool 往返和
`uthcode.application` 子进程导入不加载 `uthcode.interfaces`。ToolResult 正文
没有进入 AgentEvent、ToolFinished、RunSnapshot 或 TurnResult。

### Task 4 修改文件

- `tests/test_application_runs.py`：正式 Headless E2E、生命周期、隔离、快照、
  摘要安全和模块加载验证。
- `tests/test_agent_loop.py`：补充 E2E 所需的 ToolResult 隐藏和唯一 terminal
  协议断言。
- `README.md`：加入 Run/Turn Headless 示例，区分自动 Agent API 与低层单轮
  Generation/手动 Tool API，保留 Bash 的 unsandboxed 当前用户权限边界。

## 验证结果

| 命令 | 结果 |
| --- | --- |
| `conda run --no-capture-output -n re-uthcode pytest -q tests/test_application.py tests/test_application_runtime.py tests/test_application_tools.py tests/test_application_runs.py tests/test_package.py` | 通过，46 passed（实现最终回归） |
| `conda run --no-capture-output -n re-uthcode pytest -q tests/test_agent_loop.py tests/test_application_runs.py` | 通过，31 passed（实现最终回归） |
| `conda run --no-capture-output -n re-uthcode pytest -q` | 通过，396 passed, 3 skipped；skip 为未授权 live Provider gate |
| `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests` | 退出码 0 |
| `conda run --no-capture-output -n re-uthcode python -m pip check` | `No broken requirements found.` |
| `git diff --check` | 退出码 0 |

W01 的 Core/Provider 测试、T04 Application Tool 手动往返和三 Provider 离线
映射均保持通过；未运行 live Provider 测试。

## Checklist、差异与遗留负担

- T05 Checklist 的 Task 1–Task 2 原有勾选保持不变；本轮只将 Task 3、Task 4
  的现有项目改为 `[x]`，Task 5–Task 9 保持未勾选。
- 未修改 Provider DTO、Tool DTO/Protocol、六个默认 Tool、配置、System Prompt
  正文、CLI、TUI 或 Interface 调用链；W03/W04 继续负责后续接入。
- 没有新增第二 Registry/Executor、第二自动 Loop、Run Manager、Session、
  存储、Permission、Sandbox、Context、Memory 或持久化能力。架构扫描确认
  Headless Application 导入不加载 Interface。
- 未执行 commit、push、merge、rebase、tag 或工作树清理。

UTF-8 guard:
- files checked: `README.md`、`docs/work/T05-ReAct与AgentLoop/T05-ReAct与AgentLoop-checklist.md`、`docs/work/T05-ReAct与AgentLoop/feedback/W02-application-run-feedback.md`
- result: UTF-8 解码、常见乱码标记和 Markdown fence parity 通过
- repaired encoding issues: 无

## W02-R1 返工记录

### 返工原因

W02 复查发现两个 P1：ToolStarted/ToolFinished 的 command 摘要只按敏感词
匹配，不能可靠遮蔽无关键词的环境变量值、裸凭据和 Bearer 凭据；Application
只在事件流正常结束或调用方等待 `result()` 时释放 active Turn，事件迭代器被
放弃或取消后，Run 可能仍被错误占用。

### P1-1：Tool command 脱敏

根因是摘要生成只有关键词正则，且没有接入当前应用已知的秘密来源。返工在
`application/tools.py` 增加了 Application 内部的值级脱敏机制：服务只保存配置
中的环境变量名，在摘要处理期间临时读取当前环境值，不保存、打印或向事件传递
这些值；`bootstrap.py` 将 Provider 配置中的 `api_key_env` 名称传入摘要服务。
同时识别常见 `sk-...`、`Authorization`/`Bearer` 和敏感赋值形态。

原始命令字段先完成脱敏，再进行安全语义格式化、单行化和 240 Unicode 字符
截断；最终摘要仍只展示 Bash、文件安全路径、搜索 pattern/scope 或 unknown
占位。写入 content、EditFile 文本、ToolResult 和 unknown 参数没有进入摘要；
脱敏异常仍降级为 `<tool summary unavailable>`。没有修改 Provider/Tool DTO，
没有添加兼容入口或双轨逻辑。

### P1-2：Turn 终态自动释放 Run

根因是 Application 的 `_complete_turn()` 只由 `TurnHandle._wait_result()` 的
正常等待路径调用；`aclose()`、消费者任务取消等路径不会经过该 fallthrough。
返工在 `core/agent.py` 增加最小公共 Core 边界：`AgentTurnExecution.start()`
用于 Application 在异步上下文启动唯一 producer，`add_completion_listener()`
在 Core 创建 completed、failed 或 cancelled 的最终 `TurnResult` 时通知一次。

`application/runs.py` 在创建 Turn 时注册一个幂等收尾监听器。监听器保存最终
Core State、缓存结果并清除 active Turn；`events()` 和 `result()` 仍共享同一个
Core producer，重复入口不会重复 Provider 请求、Tool 执行或终态处理。Application
不再调用 Core 私有 `_ensure_started()`；`start_turn()` 仍可在没有运行 event loop
的同步上下文中创建 Handle。

### 返工测试与验证

新增/补充回归覆盖：

- 环境变量值不含 key/secret/token 关键词、裸 `sk-...`、`Authorization: Bearer`
  以及普通命令摘要；ToolStarted 和 ToolFinished 均不泄漏；既有写入正文、unknown
  参数、截断和失败降级断言继续保留。
- 只等待 `result()`、完整消费 `events()`、同时消费两者、调用 `events()` 后不
  迭代、首个事件后 `aclose()`、事件消费者任务取消；completed、failed、cancelled
  都能在同一 Run 启动下一 Turn，且每条路径只使用一个 Core producer。
- Core completion listener 在 events/result 竞争时只回调一次，并保持一次 Provider
  执行。

本轮实际验证：

| 命令 | 结果 |
| --- | --- |
| `conda run --no-capture-output -n re-uthcode pytest -q tests/test_application.py tests/test_application_runtime.py tests/test_application_tools.py tests/test_application_runs.py tests/test_package.py` | 通过，53 passed |
| `conda run --no-capture-output -n re-uthcode pytest -q tests/test_agent_loop.py tests/test_application_runs.py` | 通过，39 passed |
| `conda run --no-capture-output -n re-uthcode pytest -q` | 通过，404 passed, 3 skipped；skip 为未授权 live Provider gate |
| `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests` | 退出码 0 |
| `conda run --no-capture-output -n re-uthcode python -m pip check` | `No broken requirements found.` |
| `git diff --check` | 退出码 0；仅报告现有工作树的 LF/CRLF 转换提示 |

UTF-8 guard：追加后对本 Feedback 重新执行；UTF-8 解码、乱码标记和 Markdown
fence parity 通过。Checklist 未在本轮修改，原有勾选状态保持不变；没有开始
W03–W09，没有执行任何 Git 写操作。除上述两项 P1 外未发现新的失败或阻塞风险。

## W02-R2 返工记录

### 返工原因与修复

W02-R1 复查发现安全摘要仍有两个缺陷：敏感 flag 的空格参数以及
`Authorization: Basic` 会留下可辨认的凭据主体；同时对全部环境变量值执行无
边界子串替换，会让 `0`、`1` 等短值破坏普通命令。

本轮在 `application/tools.py` 补齐敏感 option 的“参数名 + 后续 shell 值”
遮蔽，并让 Authorization 统一保留可选认证方案、完整替换凭据值。因此
`--token VALUE`、`--api-key=VALUE`、Basic、Bearer 和裸 `sk-...` 均在事件
发布前完成脱敏。

环境值脱敏现区分两个来源：配置明确指定的 secret env 当前值始终完整替换；
其余环境值只有长度至少为 8 且以独立 token 边界出现时才替换。该规则继续保护
无敏感关键词的长环境值，同时避免 `0`、`1` 等短值污染
`echo 2026-08-06`。秘密值仍只在摘要调用期间临时读取，不保存、记录或进入事件。

### 回归测试与验证

`tests/test_application_runs.py` 的事件级测试现同时检查 ToolStarted 和
ToolFinished：长环境值、裸 API key、空格/等号敏感 flag、Bearer、Basic 的
完整值及可辨认主体均不出现；测试还要求所有合成凭据共有的 `W02` 标记完全
消失。另以长度小于环境筛选阈值的配置 secret 证明配置来源仍强制脱敏，并以
显式短环境值 `0`、`1` 证明普通数字命令摘要保持 `Bash echo 2026-08-06`。

本轮实际验证：

| 命令 | 结果 |
| --- | --- |
| `conda run --no-capture-output -n re-uthcode pytest -q tests/test_application.py tests/test_application_runtime.py tests/test_application_tools.py tests/test_application_runs.py tests/test_package.py` | 通过，53 passed |
| `conda run --no-capture-output -n re-uthcode pytest -q tests/test_agent_loop.py tests/test_application_runs.py` | 通过，39 passed |
| `conda run --no-capture-output -n re-uthcode pytest -q` | 通过，404 passed, 3 skipped；skip 为未授权 live Provider gate |
| `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests` | 退出码 0 |
| `conda run --no-capture-output -n re-uthcode python -m pip check` | `No broken requirements found.` |
| `git diff --check` | 退出码 0；仅有现有工作树的 LF/CRLF 转换提示 |

本轮修改仅涉及 `src/uthcode/application/tools.py`、
`tests/test_application_runs.py` 和本 Feedback；Checklist 未修改，没有开始
W03–W09，没有执行任何 Git 写操作。

## W02-R3 包级返工记录

包级独立验收发现普通环境变量值只有长度至少为 8 时才进入摘要脱敏候选，
导致 `q7z` 这类短值可原样出现在 Bash 的 ToolStarted/ToolFinished command。
本轮将普通环境值的有界匹配阈值调整为 3 个字符；配置明确指定的 secret env
仍不受长度限制，`0`、`1` 等单字符值仍不会破坏普通数字命令。

`tests/test_application_runs.py` 已把短环境值加入真实 ToolStarted/ToolFinished
事件级回归，并继续覆盖长环境值、裸 `sk-...`、敏感 flag、Basic/Bearer、
配置短 secret、写入正文、unknown 参数和普通数字命令。

重新验证：

- Application/Run 定向：`53 passed`。
- 独立事件探针：两个 Tool command 均为 `Bash echo <redacted>`，
  `short_env_leak=False`。
- 全量测试：`416 passed, 3 skipped`。
- 未修改 Checklist，未执行 Git 写操作。

## W02-R4 包级复查补充

独立复查继续构造两字符 `qz`，证明 W02-R3 的三字符阈值仍未覆盖全部短
ambient 环境值。本轮移除长度阈值，所有非空 ambient 值都按 token 边界参与
脱敏；仅保留 `0`、`1` 两个单字符 feature flag 例外，避免破坏
`echo 2026-08-06` 等普通数字命令。

事件级回归现同时覆盖 `q7z`、`qz` 和 `q`，三个值在
ToolStarted/ToolFinished command 中均被完整替换。独立探针结果：

```text
q7z => Bash echo <redacted>
qz  => Bash echo <redacted>
q   => Bash echo <redacted>
ordinary => Bash echo 2026-08-06
```

Application/Run 定向为 `53 passed`，全量为 `416 passed, 3 skipped`。
Checklist 未修改；未执行 Git 写操作。
