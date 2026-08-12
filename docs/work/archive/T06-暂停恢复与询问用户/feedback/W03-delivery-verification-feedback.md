# W03-delivery-verification Feedback

## 前置核对与范围

已完整读取并遵守 `AGENTS.md`、`SRe-AGENTS.md`、`docs/work/README.md`、T06 原始需求、Spec、Tasks、Checklist、W01/W02 Feedback 和 W03 Prompt。W01 Task 1–3、W02 Task 4–5 的 Feedback 均存在并标记完成，因此按顺序执行 Task 6、Task 7、Task 8。

W03 Prompt 第 4 项给出的 `docs/work/T06-暂停恢复与询问用户.md` 不存在；实际原始需求文件是工作包目录内的 `docs/work/T06-暂停恢复与询问用户/T06-暂停恢复与询问用户.md`。按实际工作包结构完成读取，未修改冻结文件。

当前分支 `T06-暂停恢复与询问用户` 的 HEAD 为 `7017bdd`，其父提交为任务书固定基线 `7d9dd1d`。W03 未执行 commit、stage、push、reset、restore 或其他 Git 写操作。

## Task 6：主流程接线结果

正式调用链已核对为：

```text
Headless / CLI / TUI
        ↓
UthCodeApplication.create_run()
        ↓
AgentRun.start_turn() → Application 私有 _TurnDriver
        ↓
AgentTurnExecution.run_segment()
        ↓
Provider stream → FIFO Tool batch → Provider stream
```

- `TurnHandle` 是 CLI、TUI 和 Headless 使用的唯一活动 Turn 公共控制边界；事件通过单一 `events()` 流发布，`result()` 只返回 terminal 结果。
- Application 在组合根捕获 Provider、Model、普通 Tool definitions，并只在 Agent path 追加一次 `ASK_USER_TOOL_DEFINITION`。
- 普通 Tool Registry 和手动 Tool API 拒绝保留名 `AskUserQuestion`；Integration Tool 和用户配置注册路径没有该控制工具。
- Core 只持有显式 continuation 事实，不持有用户回答 waiter；Application `_TurnDriver` 才拥有队列、result Future、response waiter 和 driver task，并在 terminal、cancel、异常和 shutdown 后清理。
- W03 端到端测试证明同一活动 Turn 可以经历用户主动暂停、恢复、AskUser 暂停、回答、恢复和最终完成，未启动第二个 Turn，也未重复 `TurnStarted`。

W03 实际修改仅限交付测试与边界门禁：

- `tests/test_application_runs.py`：将 Headless AskUser 验收测试命名为 `test_headless_ask_user_round_trip_resumes_same_turn`，补充 run/turn ID、原始 `tool_call_id`、FIFO ToolResult 和事件序列断言；新增连续两个 AskUser 的 Headless 往返测试。
- `tests/test_cli.py`：将既有 CLI 暂停验收测试命名为 `test_exec_cancels_turn_when_agent_pauses`。
- `tests/test_tui.py`：新增 `test_tui_pause_resume_and_ask_user_pilot`，从真实 TUI 输入完成主动 pause、同 Turn resume、AskUser 回答和最终结束。
- `tests/test_architecture_boundaries.py`：新增 Core 暂停路径异步 waiter、AskUser Integration 泄漏和 Application 注入边界的静态门禁。

本轮没有修改生产协议、状态机、Provider DTO、普通 Tool、CLI/TUI 生产实现或配置；W01/W02 已完成的生产接线通过本轮回归和新增门禁验证。

## Task 7：端到端与集成验证

### 指定 E2E 用例

以下命令均通过 `conda run --no-capture-output -n re-uthcode` 执行：

```text
python -m pytest -q tests/test_application_runs.py -k "headless_ask_user_round_trip_resumes_same_turn"
1 passed, 25 deselected

python -m pytest -q tests/test_application_runs.py -k "headless_two_ask_user_prompts_resume_fifo_in_one_turn or headless_ask_user_round_trip_resumes_same_turn"
2 passed, 25 deselected

python -m pytest -q tests/test_cli.py -k "exec_cancels_turn_when_agent_pauses"
1 passed, 20 deselected

python -m pytest -q tests/test_tui.py -k "tui_pause_resume_and_ask_user_pilot"
1 passed, 41 deselected
```

关键 E2E 证据：

- Headless AskUser 回答回填原 `ask-1`，后续未知 ToolResult 仍按 FIFO 保留；同一 `run_id/turn_id` 进入完成，事件中只有一个 `turn_started`、一个 `turn_completed`。
- 连续两个 AskUser 依次暴露两个不同 `pause_id`，分别回答 `ask-1` 和 `ask-2`，最终 Provider 请求只出现一次，两个 ToolResult 顺序正确。
- CLI 遇到 AskUser 暂停只调用一次 `TurnHandle.cancel()`，stdout 为空、stderr 为安全诊断、退出码为 1，不输出伪 final。
- TUI Pilot 只调用一次 `AgentRun.start_turn()`；同一 `TurnHandle` 先完成主动 pause/resume，再进入 AskUser 问题面板，提交后完成最终 Provider 请求并清理交互状态。
- 既有测试同时覆盖自由文本、单选、多选、Other、复核确认、错误 ID、过期/重复回答、用户取消、NetworkError/RateLimitError retry、Authentication/Invalid response 失败和 cancel race。

### 指定回归与 Provider 集成测试

```text
python -m pytest -q tests/test_agent_interaction.py tests/test_agent_loop.py
75 passed in 0.35s

python -m pytest -q tests/test_application_runs.py tests/test_application_tools.py tests/test_package.py
40 passed in 5.08s

python -m pytest -q tests/test_cli.py tests/test_tui.py
63 passed in 13.51s

python -m pytest -q tests/test_builtin_file_tools.py tests/test_builtin_search_tools.py tests/test_builtin_process_tool.py
34 passed in 11.33s

python -m pytest -q tests/test_anthropic_integration.py tests/test_openai_responses_integration.py tests/test_openai_compat_integration.py
38 passed, 3 skipped in 3.59s

python -m pytest -q tests/test_architecture_boundaries.py
22 passed in 3.37s

python -m pytest -q
503 passed, 3 skipped in 38.83s
```

三组 Provider 的最终合计为：Anthropic `16 passed, 1 skipped`，OpenAI Responses `11 passed, 1 skipped`，OpenAI Compatible `11 passed, 1 skipped`。Skip 是既有 live 测试门禁；本轮未发起真实网络请求或产生费用，所有离线协议集成断言通过。

### 编译、安装与工作区检查

```text
python -m compileall -q src tests
passed; no output

python -m pip check
No broken requirements found.

python -m pip install --no-deps --target D:\project\Re-UthCode\.tmp-install-check .
Successfully built uthcode
Successfully installed uthcode-0.1.0
installed package import OK

git diff --check
passed; only the existing LF/CRLF working-copy warnings were reported
```

第一次使用 `--no-build-isolation` 的安装尝试因当前 Conda 环境未安装 `hatchling` 而失败；随后使用默认隔离构建环境成功完成同一安装/import 检查。临时目录已核验为 `D:\project\Re-UthCode\.tmp-install-check` 并删除，未留在工作区。

## Task 8：遗留负担清理与否定性扫描

W03 未发现需要删除的剩余生产文件，因此没有整文件删除。W01 已删除 Core 旧 waiter/API，W02 已删除 TUI 根页面双 Esc 直接 cancel 分支；本轮通过测试和扫描确认这些替代路径没有重新出现。

最终扫描结果：

```text
NONE: Core pause path async/waiter scan
NONE: forbidden persistence/recovery production scan
NONE: AskUser integration scan
NONE: Interface reverse dependency/SDK scan
NONE: forbidden production module names
NONE: T06 state-file names in workspace
```

资源清理证据来自以下回归：

- `test_application_pause_resume_keeps_one_live_event_consumer`：跨暂停继续使用单一事件消费者。
- `test_application_driver_task_cancellation_closes_turn_without_unhandled_exception` 与 `test_application_driver_unexpected_exception_closes_result_events_and_active_slot`：driver task、response waiter、segment signal、active slot 和 terminal event 均收口。
- `test_tui_pause_resume_and_ask_user_pilot` 与既有 Provider retry/cancel Pilot：TUI generation task、活动 handle、临时 interaction 状态和 background tasks 均清理。
- 新增架构测试确认 Core 暂停路径没有 `Future`、`Event`、`Queue`、`Task`、`Lock` 等回答协调对象，Integration 不包含 AskUser 控制工具，Application 才是唯一注入路径。

## Checklist 逐项结果

- Task 6 的 4 项已勾选：正式层级接线、AskUser 注入隔离、同 Turn 多次暂停/恢复、无兼容层/双轨逻辑均有测试或扫描证据。
- Task 7 的 6 项已勾选：三个指定 E2E、三组 Provider 离线集成、结构化问答/连续询问/取消/错误恢复、Core/Application 资源清理均有证据。
- Task 8 的 6 项已勾选：旧入口和 waiter 清理、禁止模块/兼容实现扫描、异步原语与 AskUser 位置扫描、全量 pytest、compileall、pip check、安装、diff/UTF-8/Markdown/工作区检查及本 Feedback 均已完成。

## 与任务书不同的实际情况与未决风险

- W03 Prompt 的第 4 项需求文件路径与实际工作包目录不一致，已按实际存在的需求文件读取并在本 Feedback 记录；冻结文件未被修改。
- W03 只补充交付测试和架构负向门禁，没有修改生产代码，因为主流程和上游 Worker 实现已满足 Task 6 的接线边界。
- Provider live 测试按任务书的 skip 门禁保持跳过，没有真实账号、网络或费用验证；本次结论仅覆盖离线 Adapter 合同测试。
- T06 任务书列出的 Windows Terminal 人工验收（双 Esc、IME、窗口缩放、宿主 scrollback、真实网络断开后的 Retry 等）未由本 Worker 执行，不能用自动化结果替代。
- 因此，W03 自动化交付 Checklist 已完成，但在用户完成 Windows Terminal 人工验收和必要的 live Provider 验证前，不宣称 T06 已达到最终人工可验收状态。

## UTF-8 guard

- files checked: Checklist、W01 Feedback、W02 Feedback（写入前）；Checklist、W03 Feedback（写入后）。
- result: 写入前后均通过 UTF-8 解码、乱码标记和 Markdown fenced block 平衡检查。
- repaired encoding issues: none。

## 返工轮次 1

### 返工原因

本轮只处理用户确认的两项问题：补齐进程退出/重新启动边界的真实自动化验收，以及修正三个 Prompt 的错误需求文件路径和 Checklist 顶部“未派工”状态。原 Feedback 中记录的旧路径是当时真实读取结果，本章节不删除或改写该历史事实；本轮依据用户授权直接修正当前三个 Prompt 和 Checklist 元数据。

未发现生产实现写入 T06 状态或恢复旧 pending 的证据，因此没有停止，也没有修改生产代码、增加持久化或扩大到新的恢复设计。

### 新增进程边界测试机制

新增测试：

```text
tests/test_package.py::test_restart_process_boundary_creates_new_run_without_pending_or_t06_state_files
```

测试使用 pytest `tmp_path` 创建互不重叠的虚拟 `home` 和 `workdir`，并用两个独立的 `subprocess.run([sys.executable, "-c", ...])` 子进程执行：

- 子进程 A 使用离线 `FakeProvider` 返回 `AskUserQuestion`，通过公开 `TurnHandle.events()` 等待真实 `pending_pause`，输出 JSON 形式的 pid、run_id、turn_id、pause_id、tool_call_id 和 pause kind；随后主协程结束，未调用 `cancel()`、restore 或任何业务状态清理。
- 子进程 B 使用相同虚拟 home/workdir 创建全新 `UthCodeApplication`、Run 和 Turn，使用离线普通文本响应完成，不读取或回放子进程 A 的问题；输出新 pid、run_id、turn_id、pending、事件序列、final text 和公开恢复入口检查结果。
- 两个子进程均设置 `PYTHONDONTWRITEBYTECODE=1`，并设置 `HOME`、`USERPROFILE`、`APPDATA`、`LOCALAPPDATA` 和测试 workdir 环境变量，避免用户目录、项目目录和 `__pycache__` 干扰。
- 父测试在 A 前、A 后和 B 后分别对两个临时根目录做递归文件清单快照，要求 `before == after_a == after_b`，并额外拒绝 recovery、session、checkpoint、journal、pending、snapshot、replay 等路径名。

### 两个独立子进程的验证证据

测试结果为：

```text
conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_package.py -k "restart_process_boundary_creates_new_run_without_pending_or_t06_state_files"
1 passed, 7 deselected in 1.25s
```

断言结果如下：

- 子进程 A 的 `pending_kind == "user_input_required"`，`tool_call_id == "old-call"`，且 `run_id`、`turn_id`、`pause_id` 均非空；说明测试确实在旧进程内到达了真实 pending pause。
- 子进程 B 的 pid 与 A 不同；新 `run_id`、新 `turn_id` 均非空，且分别不同于 A；`pending == False`，`recovery_surface == False`。
- 子进程 B 的事件序列为 `turn_started → iteration_started → usage_updated → assistant_message_completed → turn_completed`，没有 `turn_paused`、`user_input_requested`、`turn_resumed` 或旧问题回放；最终文本为 `fresh process`。
- A 前、A 后、B 后的 home/workdir 文件快照均相等且为空；没有产生 T06 状态文件、状态目录、`__pycache__` 或安装产物。

### 元数据修正

已直接替换以下三个 Prompt 中的错误路径，三个文件均只保留正确路径：

```text
docs/work/T06-暂停恢复与询问用户/prompt/W01-interaction-runtime-control-prompt.md
docs/work/T06-暂停恢复与询问用户/prompt/W02-interface-interaction-prompt.md
docs/work/T06-暂停恢复与询问用户/prompt/W03-delivery-verification-prompt.md
```

正确路径为：

```text
docs/work/T06-暂停恢复与询问用户/T06-暂停恢复与询问用户.md
```

已将 Checklist 顶部状态从“状态：未派工。所有验收项均须由对应 Worker 完成并提供证据。”直接改为“状态：实施完成，待用户验收。”；未修改 Checklist 的验收项文字、结构、编号或顺序，既有 Task 6–8 checkbox 状态保持上一轮真实验收结果。

### 返工重新执行的全部命令与结果

```text
conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_package.py
8 passed in 1.33s

conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_architecture_boundaries.py
22 passed in 3.60s

conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_agent_loop.py tests/test_application_runs.py tests/test_application_tools.py tests/test_cli.py tests/test_tui.py
123 passed in 16.51s

conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_anthropic_integration.py tests/test_openai_responses_integration.py tests/test_openai_compat_integration.py
38 passed, 3 skipped in 3.72s

conda run --no-capture-output -n re-uthcode python -m pytest -q
504 passed, 3 skipped in 33.28s

conda run --no-capture-output -n re-uthcode python -m compileall -q src tests
passed; no output

conda run --no-capture-output -n re-uthcode python -m pip check
No broken requirements found.

git diff --check
passed; only existing LF/CRLF working-copy warnings were reported
```

三组 Provider 的 `3 skipped` 仍是既有 live 测试门禁；本轮只执行离线 Adapter 集成测试，没有真实网络请求或费用。

本轮还执行了：

```text
NONE: no T06 state or install artifacts in workspace
NONE: incorrect prompt path
NONE: old checklist status
```

UTF-8 guard 对本轮修改的五个 Markdown 文件（三个 Prompt、Checklist、W03 Feedback）通过 UTF-8、乱码标记和 Markdown fence 检查；工作区没有测试临时文件、状态目录或安装产物。未执行 commit、stage、push、merge、reset 或 restore。

### 未完成项及人工风险

- 真实进程边界、离线 Provider、全量自动化和文档校验已完成；没有发现需要停止并报告的生产行为偏差。
- Windows Terminal 双 Esc、IME、窗口缩放、宿主 scrollback 和真实网络断开后的人工 Retry 仍未执行，不能由本轮自动化替代。
- 三组 Provider live 测试仍按既有门禁跳过，未验证真实账号、网络和费用链路。
- 本轮返工已停止，等待用户重新验收；不执行任何 Git 写操作。

## 返工轮次 2

### 返工原因

本轮只修正进程重启边界测试的证据失真问题。原测试的 `_run_restart_child()` 虽然接收 `workdir` 参数，但 `subprocess.run()` 仍固定使用仓库根目录作为 `cwd`；子进程中的 `ApplicationRuntimeContext.from_system()` 因而捕获的是仓库根目录。与此同时，子进程输出的 `workdir` 来自 `UTHCODE_TEST_WORKDIR` 环境变量回显，父测试快照检查的虚拟 workdir 实际未被 Application 使用，因此原断言只能证明一个未使用目录为空，属于假阳性。

本轮未修改生产代码、Prompt、Checklist 或返工轮次 1 内容；没有扩大到恢复、持久化、Session、Journal、Checkpoint 或兼容层设计。

### 实际修正

- `_run_restart_child()` 的 `subprocess.run()` 现在使用传入的 `cwd=workdir`；`PYTHONPATH` 仍显式指向仓库 `src`，所以两个独立子进程可以从虚拟 workdir 导入 `uthcode`。
- 删除仅用于回显的 `UTHCODE_TEST_WORKDIR` 设置和读取逻辑；`_restart_process_environment()` 不再接收未使用的 workdir 参数。
- 子进程 A、B 都输出 `str(application.runtime_context.workdir)`，不再输出环境变量推导的 workdir。
- 子进程 A、B 都输出实际运行环境解析出的 `str(Path.home())`；父测试使用 `Path(...).resolve()` 分别断言 home 与 pytest 创建的虚拟 home 相同，并断言两个 Application 的 `runtime_context.workdir.resolve()` 与虚拟 workdir 相同。
- 保留两个独立 `subprocess.run([sys.executable, "-c", ...])` 进程和 `PYTHONDONTWRITEBYTECODE=1`。

### 两个独立子进程与实际目录证据

测试名称保持为：

```text
tests/test_package.py::test_restart_process_boundary_creates_new_run_without_pending_or_t06_state_files
```

- 子进程 A 在实际虚拟 workdir 中创建 Application、Run 和 Turn，离线 FakeProvider 返回 `AskUserQuestion`；测试观察到 `pending_kind == "user_input_required"`，`tool_call_id == "old-call"`，且旧 `run_id`、`turn_id`、`pause_id` 均非空，随后子进程退出且不恢复、不清理业务状态。
- 子进程 B 在相同实际虚拟 workdir 和虚拟 home 中创建全新 Application、Run 和 Turn；实际 pid 与 A 不同，`run_id`、`turn_id` 均非空且分别不同于 A，`pending is False`，无恢复 API 表面，事件序列为 `turn_started → iteration_started → usage_updated → assistant_message_completed → turn_completed`，最终文本为 `fresh process`，未回放旧问题。
- A、B 输出的实际 `Path.home()` 均通过父测试的 `home.resolve()` 断言；A、B 输出的 `application.runtime_context.workdir` 均通过 `workdir.resolve()` 断言。由此验证的是 Application 实际捕获的目录，而非自定义环境变量。
- 父测试在 A 前、A 后、B 后对实际虚拟 home/workdir 做递归快照；结果均为 `{"home": (), "workdir": ()}`，即 `before == after_a == after_b`，没有新增 recovery、session、checkpoint、journal、pending、snapshot、replay 或其他 T06 状态路径。

### 全部复验命令与精确结果

```text
conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_package.py -k "restart_process_boundary_creates_new_run_without_pending_or_t06_state_files"
1 passed, 7 deselected in 1.39s

conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_package.py
8 passed in 1.59s

conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_architecture_boundaries.py
22 passed in 4.39s

conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_agent_loop.py tests/test_application_runs.py tests/test_application_tools.py tests/test_cli.py tests/test_tui.py
123 passed in 19.50s

conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_anthropic_integration.py tests/test_openai_responses_integration.py tests/test_openai_compat_integration.py
38 passed, 3 skipped in 4.60s

conda run --no-capture-output -n re-uthcode python -m pytest -q
504 passed, 3 skipped in 36.04s

conda run --no-capture-output -n re-uthcode python -m compileall -q src tests
passed; no output

conda run --no-capture-output -n re-uthcode python -m pip check
No broken requirements found.

git diff --check
exit code 0; only existing LF/CRLF working-copy warnings were reported
```

W03 Feedback 写入前后均执行 `uth-utf8-guard`，本轮 Feedback 文件通过 UTF-8 解码、乱码标记和 Markdown fence 检查。工作区临时文件与 T06 状态目录扫描在清理测试缓存后无命中；未执行 commit、stage、push、merge、reset 或 restore。

### 未完成项及人工风险

- 修正后的真实进程边界测试、离线 Provider、全量自动化、编译、依赖和文档校验均已完成；没有发现生产实现写入 T06 状态或恢复旧 pending 的行为偏差，因此未修改生产代码。
- Windows Terminal 双 Esc、IME、窗口缩放、宿主 scrollback 和真实网络断开后的人工 Retry 仍未执行，不能由本轮自动化替代。
- 三组 Provider live 测试仍按既有 skip 门禁跳过，未验证真实账号、网络和费用链路。
- 本轮返工已停止，等待用户重新验收；不执行任何 Git 写操作。

### UTF-8 guard

- files checked: `docs/work/T06-暂停恢复与询问用户/feedback/W03-delivery-verification-feedback.md`（写入前后）。
- result: 通过 UTF-8 解码、乱码标记和 Markdown fenced block 平衡检查。
- repaired encoding issues: none。
