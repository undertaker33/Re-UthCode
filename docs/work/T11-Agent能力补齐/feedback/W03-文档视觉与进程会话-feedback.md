# W03 文档视觉与进程会话 Feedback

## 首轮实施（2026-09-12）

本轮严格按 `T07 → T08 → T09` 实施，范围停在 W03；没有修改后续 W04—W06 能力，没有 Git 写操作，也没有请求或伪造 Provider、Tavily 或其他服务凭据。

### 实际完成

- T07 新增 `ReadDocument` 与 `ViewImage`。PDF、DOCX、XLSX、PPTX 都通过受限 Integration 读取并返回定位信息；XLSX 分开保留公式与已有缓存值，不执行公式重算。PDF 页图经 PDFium 串行保护和既有 Session 附件写入路径形成 `ImagePart`/`SourcePart`，图片与 PDF 页都受字节、像素和输出预算限制。损坏、加密、超限和取消形成受控 Tool failure。
- T08 扩展 `Bash` 为唯一进程启动入口，分开 `yield_time_ms` 与可选 `timeout_seconds`，默认没有总寿命；新增 `ProcessSessionManager` 和 `Process` 的 `list/read/write/stop/resize`/EOF。pipe 继续区分 stdout/stderr，Windows 使用 pywinpty/ConPTY PTY，POSIX 路径保留 ptyprocess/process-group 实现；Windows 启动复用现有 Job 后代归属与回收。
- T09 将进程所有权绑定 Application/Session 和启动 Turn。成功 Turn 后活进程可跨 Turn 续读或控制，取消/失败/异常只清理本 Turn 新进程，Session/Application shutdown 清理全部。输出进入有界 UTF-8 ring，单调 cursor 过期返回 earliest position；Application 统一做跨 chunk Secret 脱敏并发布 `process_output`/`process_state`。Bridge 在 Turn 已完成后仍接收这些事件，使用有界 outbox；Renderer 按 `project_key + session_id` 保留有界日志并提供折叠显示。
- 正式 bootstrap 共享同一个 `ProcessSessionManager`，Bridge 增加 `process.list/read/write/stop/resize`，renderer `state.ts` 与 `ChatTimeline.tsx` 接入后台日志。同步更新 `docs/Tools.md`、四层 Context、GUI Context、命令手册和 `docs/Context-Index.md`；只将实测项改为勾选，冻结需求、Spec、Tasks、Prompt 文字保持不变。
- `pyproject.toml` 声明 Pillow、pypdfium2、python-docx、openpyxl、python-pptx 与平台限定的 pywinpty/ptyprocess；`desktop/packaging/uthcode-runtime.spec` 接入 pypdfium2_raw/winpty 原生资源和动态库收集。安装产物的人工读取与完整 PTY 验收仍留 T19。

关键调用链为：`Bash -> ProcessSessionManager -> Application.process observer -> project_process_output -> DesktopBridge outbox -> renderer processLogs`。该观察链不写 RunState、Transcript、History 或 Provider 请求；`Process` 控制仍经现有 PermissionAction，stdin/EOF 是独立输入授权，stop 是 destructive action。

## Checklist 本轮已验证并勾选

- T07：A09 与 T07 完成边界。
- T08：A11、A14。
- T09：A13、A14、A16 与 T09 完成边界。

保留未勾选：A10（Windows packaged 四格式/PDF 页图手动读取）、A12（要求 Windows + POSIX 原生 PTY）、A15（Windows packaged 后人工 PTY/日志/stdin/停止/关闭）。这些条件没有以开发机、WSL 缺失的 conda 环境、CDP 或 mock 替代。

## 依赖与验证命令

实施和验证均使用既有 `re-uthcode` Conda 环境：Python `3.12.13`、Pillow `12.3.0`、pypdfium2 `4.30.0`、python-docx `1.2.0`、openpyxl `3.1.5`、python-pptx `1.0.2`、pywinpty `2.0.15`。

- `conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_document_tools.py tests/test_image_tools.py tests/test_process_sessions.py tests/test_process_application_lifecycle.py`：9 passed，1 个 pypdfium2 UserWarning（不影响结果）。真实生成 DOCX/XLSX/PPTX/PDF/PNG，真实 Application/Process/Bridge 生命周期和跨 chunk 脱敏均在用例中覆盖。
- `conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_application_runs.py tests/test_application_runtime.py tests/test_application_tools.py tests/test_builtin_process_tool.py tests/test_desktop_bridge.py`：293 passed。既有 Windows Job descendant、timeout/cancel/异常回收和 Bridge 回归包含在内。
- `conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_architecture_boundaries.py`：23 passed；新增 composition-root 对 `process_sessions` 的合法 Integration 依赖 allowlist 后通过。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src/uthcode tests`：通过。
- `npm run typecheck`（工作目录 `desktop/`）：通过。
- `npx tsx --test tests/renderer-state.test.ts tests/renderer-chat.test.tsx`（工作目录 `desktop/`）：51 passed。
- `$env:UTHCODE_PYTHON='C:\Users\93445\miniconda3\envs\re-uthcode\python.exe'; npx tsx --test tests/runtime-process.test.ts`：20 passed；真实离线 Desktop Runtime Bridge/Application/Core 主链、分页历史和 child reap 通过。
- `$env:UTHCODE_PYTHON='C:\Users\93445\miniconda3\envs\re-uthcode\python.exe'; npm test`（工作目录 `desktop/`）：224 passed，0 failed。包含新增进程日志 Renderer 用例和现有 runtime/package contract smoke；未将该离线 smoke 记录为安装产物人工验收。
- `conda run --no-capture-output -n re-uthcode python C:/Users/93445/.codex/t11_check_frozen.py`：`PASS: 10 frozen files unchanged except permitted checklist completion marks`。
- `git diff --check`：通过；仅报告当前 Windows checkout 的 LF→CRLF 提示，没有空白错误。

Windows 原生 PTY 用例实际验证子进程 `isatty(0/1)`、stdin 文本、EOF 和 resize；pipe 用例仍断开 stdout/stderr。既有 `test_bash_timeout_terminates_descendant_after_shell_exit`、`test_bash_cancellation_terminates_descendant_after_shell_exit`、`test_bash_task_cancellation_terminates_descendant_after_shell_exit` 验证 Job 后代不会继续写 marker。跨 Turn Application/Bridge 用例确认 ToolCall/Turn 完成后仍收到 `process_output`/`process_state`，并且秘密在拆分 chunk 后不出现在事件中。

## 未验证项、差异与风险

- WSL Ubuntu 预检只有 Python `3.14.4`、没有 conda；按要求没有新建平行环境，也没有把缺少 POSIX 条件冒充 A12 通过。A12 留待具备真实 POSIX/既有环境后重跑。
- 未执行 `npm run package`/`npm run make` 后的人工安装、四格式读取、PDF 页图入模、PTY/中文 ANSI/stdin/停止/关闭操作；A10/A15 与 T19 保持未完成。spec 已接入原生资源，但未把 spec 静态检查写成 packaged runtime 通过。
- 未配置或调用真实 Provider/Tavily，未验证真实视觉模型理解、真实 endpoint 用量或外部服务错误；按用户要求不请求密钥、不伪造结果。
- `pypdfium2` 测试出现其 `get_text_range()` 默认参数弃用方向的 UserWarning；当前结果和受控错误均通过，未改变依赖上游行为。
- 没有新增能力欠账。跨进程 Runtime checkpoint 与跨 Session Artifact 生命周期仍按 T11 原有后置边界保留；本轮只保证当前 Application/Session 内的资源、日志和清理。

## 清理结果

本轮测试文件均使用 pytest `tmp_path`，临时目录已由测试框架清理；工作区未创建自建 `tmp-*`/`temp-*` 目录。`desktop/packaging/.build` 为忽略的可再生成 packaging 输出，未纳入交付文件，保留以避免删除既有用户构建产物。没有执行 commit、push、merge、rebase、tag、release 或工作包归档；等待总控审核、合并和后续原 Worker 返工。

## UTF-8 guard

- files checked: 本轮修改的 `docs/Tools.md`、四层 Context、GUI Context、`docs/user-manual/commands.md`、`docs/Context-Index.md`、W03 Checklist 与本 Feedback。
- result: 写入前后均通过 `C:/Users/93445/.codex/skills/uth-utf8-guard/scripts/check_utf8_docs.py` 的 UTF-8、乱码标记和 Markdown fence 检查。
- repaired encoding issues: 无。

## 返工第1轮（2026-09-12）

总控复核指出首轮 PDFium 串行锁只能保护同步 native 调用，无法在调用内部真正响应取消；同时开发态私有宿主不能依赖 Desktop Interface，frozen 产物也不能把 `sys.executable` 当通用 Python 解释器接收 `-m`/`-c`。本轮只修正 T07 的 PDF 取消与宿主入口，不扩大 T08/T09 范围。

- 新增 `src/uthcode/integrations/tools/document_workers.py`。`ReadDocument` 的 PDF 文本与 `ViewImage` 的 PDF 页渲染都把有界请求交给一次性私有子进程；父侧每 50ms 检查 `CancellationToken`，取消或 30 秒上限触发时 terminate 后 kill，并等待子进程结束，因而不会等待仍在 PDFium native 调用中的线程。协议只传受限 base64/JSON，子进程只返回有界文本或 PNG 及来源所需尺寸。
- 开发态命令为 `sys.executable -m uthcode.integrations.pdf_worker --uthcode-pdf-worker`，Integration 可在移除 Desktop 后继续工作；`src/uthcode/interfaces/desktop/__main__.py` 仅在现有打包入口收到该 flag 时动态分派同一 worker，frozen 路径为 `(sys.executable, "--uthcode-pdf-worker")`，没有假定 frozen 可执行文件支持 `-m`/`-c`。spec 显式收集 worker hidden import 与 PDFium/winpty 原生资源。
- 真实文档/图像/进程/Application 生命周期命令：`conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_document_tools.py tests/test_image_tools.py tests/test_process_sessions.py tests/test_process_application_lifecycle.py`：`10 passed`。
- 入口与架构复核：`tests/test_architecture_boundaries.py`：`23 passed`；`conda run --no-capture-output -n re-uthcode python -m compileall -q src/uthcode tests`：通过。新增用例直接核对开发态 Integration 模块入口和 frozen flag 入口；前项真实 PDF 测试实际启动开发态 worker。
- 直接 headless 启动验证：向 `conda run --no-capture-output -n re-uthcode python -m uthcode.integrations.pdf_worker --uthcode-pdf-worker` 发送损坏 PDF 请求，返回 JSON `{"ok":false,"kind":"invalid_input","message":"Error: PDF is damaged or encrypted"}`；没有加载 Desktop Bridge。
- 受影响 Application/Bridge 回归：`conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_application_runs.py tests/test_application_runtime.py tests/test_application_tools.py tests/test_builtin_process_tool.py tests/test_desktop_bridge.py`：`293 passed`；Desktop `npm run typecheck`：通过。
- 最终 Desktop 全量：`$env:UTHCODE_PYTHON='C:\Users\93445\miniconda3\envs\re-uthcode\python.exe'; npm test`：`224 passed, 0 failed`（包含现有 bundled Runtime smoke）；`.build` 仍是忽略的可再生成 packaging 输出，未作为人工安装产物验收。
- T07 的 A09 和完成边界仍保持勾选；A10（Windows packaged 四格式/PDF 页图人工读取）仍未勾选，frozen/installer 实际运行仍留 T19。A12/A15 以及其余首轮未验证项不因本轮变更提前勾选。

本轮没有自建临时目录，没有 Git 写操作；等待总控审核后停止修改并交由原 Worker 返工。

## 返工第2轮（Terra 首轮驳回修复，2026-09-12）

本轮只处理 Terra 首轮指出的六项问题，仍停在 T07、T08、T09，没有修改 W04—W06，也没有修改冻结的原需求、Spec、Tasks、Prompt 或 Checklist 文字。六项修复如下。

1. **Process 控制统一经过 Application Permission/Tool 边界。** Desktop 的 `process.list/read/write/stop/resize` 不再直接调用 manager；Bridge 先通过 Application 形成已注册 Process Tool 的 prepared call，再由当前 Run 的既有 `authorize_action` 处理 `PermissionAction`，最后交给既有 Application ToolExecutor。stdin 与 EOF 继续是独立输入授权，stop 使用 destructive action。真实 ASK、REJECT 保持进程、ONCE 批准后执行，以及取消 prepared read 的回归在 `test_desktop_process_controls_use_application_permission_boundary` 中覆盖。
2. **Secret projection 统一在进入 ring/event/list/read/Tool 结果前完成。** Application 的跨 chunk 尾部脱敏 projector 现在是 ProcessSessionManager 的唯一输出投影入口；同一净化流负责 ring、live event、read 页面和 Tool `details`，command 也经过同一类投影。cursor 因而属于净化后的流，不能通过最后一步的独立补丁泄漏原文。跨 chunk 输出、Application 路由和 Tool 结果用例均加入秘密断言。
3. **Renderer 增加真实续读与过期呈现。** `state.ts` 为每个 `project_key + session_id` 保留 reader 状态，`App.tsx` 通过 `process.read` 读取 newer/earliest，`ChatTimeline.tsx` 提供 Read newer、Load earliest、Stop、cursor expired/earliest 和终态过期事实呈现。进程日志仍有界；后台 outbox 与 session reader 有界淘汰后，界面明确显示恢复所需的 earliest/cursor 信息。异步回包回到已停放的旧 Session 时只清理该 Session 的 loading，不把结果写入当前新 Session，避免归属串线。
4. **撤回首轮 PTY 通过证据并修复 EOF 时序。** 首轮记录的间歇失败以及“单次通过”证据全部撤回，不作为当前通过依据。根因是 native PTY pump 尚未观察到写入时就关闭输入，`write(..., eof=True)` 与 pump 调度存在竞态；现在用 PTY 写锁和输出同步信号等待已写入内容被观察后才发送 EOF/关闭输入。保持 `isatty(0/1)`、`hello\r\n`、EOF、resize 原断言不变，Windows 原生开发边界独立重复 8 次，每次均 `exit=0, 1 passed`。A12 仍不勾选，因为它还要求真实 POSIX 边界；WSL 只有 Python 3.14.4 且没有 conda，未冒充 POSIX 通过。
5. **Session 终态资源有明确会话配额和过期事实。** 每个 Session 默认最多保留 64 个进程，正常终态最多保留 32 个，最多保留 128 条 expired tombstone；单进程输出 ring 仍为 2 MiB。正常结束时立即淘汰旧终态，后续 read 返回 `expired`、原因及 earliest/next cursor，避免短命命令只等 shutdown 才清理，也没有引入全局事务或复杂持久化状态。新增 `test_terminal_processes_are_evicted_with_explicit_expired_facts` 覆盖该边界。
6. **PDF worker 父子进程输出和输入均有界可取消。** 父侧并发 drain stdout/stderr，按协议 base64 开销限制读取，超限、超时和取消都会终止并回收子进程；stdin drain 以 50ms 粒度检查 CancellationToken/timeout 后终止，不再先用无界 `communicate` 缓冲。worker 写出也执行含 base64 开销的硬上限。正常 PDF、取消、开发态 headless 入口和 frozen flag 入口保持可用；安装产物人工验证仍留 T19。

### 返工第2轮实测结果

- `conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_process_sessions.py tests/test_process_application_lifecycle.py tests/test_builtin_process_tool.py tests/test_desktop_bridge.py`：`233 passed in 22.49s`。包含统一 Permission 链路、跨 chunk 脱敏、cursor/终态淘汰、Windows Job 后代回收和 Bridge 回归。
- `conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_process_sessions.py::test_windows_pty_isatty_stdin_eof_and_resize` 独立运行 8 次：8 次均 `exit=0`、`1 passed`；未放松断言。
- `conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_document_tools.py tests/test_image_tools.py`：`5 passed in 2.42s`。
- `conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_architecture_boundaries.py`：`23 passed in 6.22s`。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src/uthcode tests`：通过。
- `npm run typecheck`（工作目录 `desktop/`）：通过；`npx tsx --test tests/renderer-state.test.ts`：`46 passed`；`npx tsx --test tests/renderer-chat.test.tsx`：`7 passed`。
- `$env:UTHCODE_PYTHON='C:\Users\93445\miniconda3\envs\re-uthcode\python.exe'; npm test`（工作目录 `desktop/`）：`226 passed, 0 failed`。这是带既有 `re-uthcode` 环境的离线 Runtime/Application/Bridge/Renderer/package-contract smoke；不作为安装产物人工验收。
- UTF-8 guard：本轮相关 10 个 Markdown 文件全部通过 UTF-8、乱码标记和 fence 检查；`C:/Users/93445/.codex/t11_check_frozen.py`：`PASS: 10 frozen files unchanged except permitted checklist completion marks`。
- Provider/Tavily、真实视觉模型、`npm run package`/`npm run make` 后安装产物和 POSIX PTY 仍未验证，分别按 A10/A12/A15/T19 保持未勾选；未请求或伪造密钥。测试临时目录由 pytest `tmp_path` 清理，已删除自建 debug 临时目录，未留下自建 tmp。没有 Git 写操作。

六项修复及上述验证完成后停止修改，等待同一 Terra 复审。

## 返工第3轮（Terra 第二轮新增 Stop 授权 UI，2026-09-12）

Terra 第二轮已确认上一轮六项 finding 全部通过（12 项定向用例、Renderer 53 项、原生 Windows PTY 再次 8/8）。本轮只修复新增的 P1：`App.tsx` 原先丢弃 `process.stop` 的 `permission_required` 成功返回，默认 ASK 时用户看不到授权请求，进程无法继续完成 Stop。

- `stopProcess` 现在保留 Bridge 返回的 `permission_required`，以 `projectKey + sessionId + processId + permission_id` 绑定本地待审批请求，并复用现有 `InteractionSurface` 的权限文案、choices、焦点隔离和响应身份。
- 批准/拒绝通过同一个 App handler 重发 `process.stop`，参数同时携带 `permission_id` 与 `permission_choice`；批准执行停止，拒绝显示本地化结果并保持进程运行。新增取消按钮只清除本地待审批，不调用 Stop。
- 初次请求、审批提交分别使用 ref 防止重复点击；请求失败、审批失败或权限请求失效都会清除本地请求并显示安全的中英文提示，不对可能已经产生副作用的 destructive 请求盲目重试。项目或 Session 切换会清除旧请求、忽略晚到回包，不能把审批带到新归属。
- 新增中英文 `processStopFailed`、`processStopRejected` 文案；未修改冻结需求、Spec、Tasks、Prompt 或 Checklist 文字，也未扩大到 W04—W06。

### 返工第3轮实测结果

- `npx tsx --test tests/renderer.test.tsx`（工作目录 `desktop/`）：`102 passed, 0 failed`。新增真实 `App` 挂载交互覆盖首次 ASK 可见、连续 Stop 点击只发一次、Allow once 重发带 `permission_id/permission_choice` 并完成、Reject 重发后进程继续运行、Cancel 不执行第二次 Stop。
- `npx tsx --test tests/renderer-state.test.ts tests/renderer-chat.test.tsx`（工作目录 `desktop/`）：`53 passed, 0 failed`。
- `npm run typecheck`（工作目录 `desktop/`）：通过；中英文 locale parity 也在 Renderer 回归中通过。
- 没有重复无关 Python/PTY/packaged 测试；上一轮 Terra 已通过的六项证据保持有效。本轮没有 Git 写操作，也没有修改冻结文件。

本轮 Stop 授权 UI 修复和定向验证完成后停止修改，等待同一 Terra 复审。

## 返工第4轮（Terra 第三轮 pending approval 回收，2026-09-12）

Terra 第三轮只剩 P2：Stop 首次 ASK 后，Renderer 的 Cancel/导航只清理本地状态，Bridge 的 `_pending_process_operations` 会继续保留 prepared call，反复操作可能造成无界累积。本轮没有改变 Stop 的批准/拒绝语义，没有修改冻结需求、Spec、Tasks、Prompt 或 Checklist，也没有扩大到 W04—W06。

- 新增内部 `process.permission.release` RPC，参数必须同时包含已知 `permission_id` 与 `process_id`。它只从 Bridge pending map 删除匹配的 prepared record，绝不调用 Process Tool、manager 或 Stop；未知 ID 幂等返回未释放，process_id 不匹配则拒绝。
- App 的 Stop ASK 结果会保留归属；Cancel 立即清理本地弹窗并发送一次 release。项目/Session 切换 effect 会释放旧归属；Stop 请求在导航或卸载后才返回旧 Session 的 ASK 时，也先解析 permission，再发送 release，不显示旧弹窗、不重发 Stop。release 失败只显示安全提示，不盲目重试可能带副作用的请求；Bridge shutdown 仍执行全量清理。
- Bridge boundary test 在 ASK 后调用 release，确认 pending map 为空且进程仍 running，然后重新 ASK 验证原有拒绝/批准路径；App 真实挂载测试覆盖 Cancel 的 release 参数、导航期间延迟 ASK 的 release、旧 Session 不弹授权以及 Stop 只发一次。

### 返工第4轮实测结果

- `npx tsx --test tests/renderer.test.tsx`（工作目录 `desktop/`）：`103 passed, 0 failed`，含 Stop ASK→Cancel release 与导航晚到 ASK 回收测试。
- `npx tsx --test tests/renderer-state.test.ts tests/renderer-chat.test.tsx`（工作目录 `desktop/`）：上一轮 `53 passed, 0 failed`，本轮未改变这些 reducer/UI 文件。
- `conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_process_application_lifecycle.py tests/test_desktop_bridge.py tests/test_builtin_process_tool.py`：`229 passed in 16.07s`。
- `npm run typecheck`（工作目录 `desktop/`）：通过。
- `conda run --no-capture-output -n re-uthcode python C:/Users/93445/.codex/skills/uth-utf8-guard/scripts/check_utf8_docs.py docs/Tools.md docs/Context-Index.md docs/context/A01-AgentRuntime/AgentRuntime-Context.md docs/context/A02-Control/Control-Context.md docs/context/A03-State/State-Context.md docs/context/A04-Orchestration/Orchestration-Context.md docs/context/GUI/GUI-Context.md docs/user-manual/commands.md 'docs/work/T11-Agent能力补齐/T11-Agent能力补齐-checklist.md' 'docs/work/T11-Agent能力补齐/feedback/W03-文档视觉与进程会话-feedback.md'`：`OK: 10 file(s) passed UTF-8 guard`。
- `conda run --no-capture-output -n re-uthcode python C:/Users/93445/.codex/t11_check_frozen.py`：`PASS: 10 frozen files unchanged except permitted checklist completion marks`。
- `git diff --check`：clean；仅有 Windows checkout 的 LF→CRLF 提示。没有 Git 写操作，没有新增自建临时目录，没有请求或伪造 Provider/Tavily 凭据。

本轮 pending approval 回收修复和验证完成后停止修改，等待同一 Terra 复审。

## 返工第5轮（Terra 第四轮卸载回收补充，2026-09-12）

Terra 第四轮指出，上一轮 Feedback 将“卸载释放”写成已覆盖并不准确：当时代码已覆盖 Cancel、导航和晚到旧 Session 回包，但 App 的 root unmount 尚没有调用 `releaseProcessPermission`。本轮只补齐这一遗漏；上一轮文字保持原样，并在本节明确纠正，不修改冻结的原需求、Spec、Tasks、Prompt 或 Checklist，也没有扩大到 W04—W06。

- App 新增生命周期 cleanup，直接读取 `pendingProcessPermissionRef`，先清理本地 pending/submission ref，再调用既有 `releaseProcessPermission`。cleanup 不依赖 mounted 状态做 UI dispatch；release helper 的 permission-id guard 使 React StrictMode、重复卸载和其他释放路径至多发送一次 release RPC。
- Bridge 继续使用专用 `process.permission.release` RPC，仅删除匹配的 prepared record，不执行 Stop 或其他 Process Tool；取消、导航和晚到回包路径保持第4轮已验证的回收语义。卸载期间晚到结果不会重新显示旧授权请求，也不会重试 destructive Stop。
- 新增真实 App root `unmount()` 用例：可见 ASK 授权后卸载，断言只发送一次 `{permission_id, process_id}` release、没有第二次 Stop；既有 Stop ASK→Cancel 与导航晚到回包回归仍保留。

### 返工第5轮实测结果

- `npx tsx --test tests/renderer.test.tsx`（工作目录 `desktop/`）：`104 passed, 0 failed`，包含新增 root unmount release 用例；测试输出中的两个既有 SidebarInfo `act(...)` 提示不影响通过结果。
- `npm run typecheck`（工作目录 `desktop/`）：通过。
- 第4轮后最近一次受影响 Python 回归保持 `229 passed in 16.07s`；本轮仅修改 Renderer cleanup 与对应 Desktop 用例，没有变更 Python/Bridge 实现。
- 第4轮已通过的 `renderer-state`/`renderer-chat` `53 passed`、UTF-8 guard、frozen guard 和 `git diff --check` 仍作为基线；本节追加后重新执行三项守卫，结果分别为 `OK: 10 file(s) passed UTF-8 guard`、`PASS: 10 frozen files unchanged except permitted checklist completion marks`、`git diff --check: clean`（仅过滤 Windows LF→CRLF 提示）。
- 测试临时目录由测试框架清理；没有新增自建临时目录、Git 写操作或 Provider/Tavily 凭据。完成本轮后停止修改，等待同一 Terra 复审。

## 总控审核收口

Luna（max）完成 W03 首轮实施、总控 PDF 私有宿主预审返工，以及 Terra（high）四轮审核返工；Terra 第五轮最终审核 PASS，无剩余实质 finding。六项首轮问题（进程权限链、统一脱敏、Renderer 续读、Windows PTY 稳定性、终态资源淘汰、PDF 限长读取）和后续 Stop 授权交互、取消/导航/晚到回包/卸载审批记录回收均已关闭。最终 Reviewer 对 Stop 授权与 root unmount release 复跑 2 passed，TypeScript、冻结和 diff 检查通过；前轮 Reviewer 文档/图片/进程定向 12 passed、Renderer 53 passed、Windows PTY 连续 8/8 passed、Bridge 74 passed 与生命周期 3 passed 的证据仍有效。

最终 Worker Renderer 104 passed、typecheck，以及前轮受影响 Python 229 passed、文档图片 5 passed、架构 23 passed 的分阶段证据见上文；Desktop 226 passed 为第2轮全量结果，后续 UI/Bridge 修复使用受影响定向回归，没有宣称最终代码全量重跑。旧 PTY 单次通过与第4轮卸载覆盖声明已由追加记录纠正。真实 Provider/Tavily、POSIX PTY、Windows 安装产物人工验收仍待条件补齐，整包不标记完成，不归档。
