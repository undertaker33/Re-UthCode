# W05 异常截停与 Desktop 收口 Feedback

## 首轮实施（2026-09-13）

本轮严格按 `T14 → T15 → T16` 实施，只覆盖 W05；没有修改后置 W06/T19 能力，没有请求、展示或伪造 Provider/Tavily 凭据。真实 Provider、Tavily A18、packaged 人工验收和 POSIX 条件继续按冻结边界保留未验证。

### 实际完成

- **T14 异常截停**：移除 `AgentLoopConfig` 和 normal/continuation 的累计 `max_iterations` gate，不增加总 token/time fallback。保留 `iteration_count`、Tool/Usage 统计、Context、I/O、权限和取消语义。新增有界 `_RunawayDetector`：最近 24 个语义观察只保留摘要哈希；传输 `tool_call_id` 被忽略，调用参数语义仍参与判断。相同失败、长度 1—4 的短周期和 unfinished final 阻断都在第 3 次先注入一次纠偏，纠偏后再次达到第 5 次停止并报告 `runaway_detected`。新有效结果解除对应怀疑；纠偏不会重置证据；合法 Process running 空读不计入。FIFO 批尾仍为受控 Tool Result，取消终态仍独立报告 `cancelled`。
- **T15 限制与配置生效**：增加用户级 `[tool_limits]` 的单工具 `timeout_seconds`、`output_bytes`、`attachment_bytes`，项目配置只能收紧并经过字段、数值、来源校验。配置、Desktop Settings/Bridge 和 EffectiveConfig 都以安全 DTO 显示已配置值；搜索、视觉/附件和工具输出上限沿现有 Application Tool、Attachment、Process 链路生效。idle 当前、background Application 与各自 idle Run 在保存后的下一安全边界 reload；已启动 ProcessSession 保留启动参数、旧脱敏 projector、子进程和 manager identity，不重启。单 modal 的 API key/search key 仍只在 editor-local 状态中英一致。
- **T16 Desktop 产物链**：新增 Application `ArtifactService`，校验文件存在、工作目录或显式外部授权、类型和受控图片 preview；Bridge 暴露 `artifact.describe/preview/open/reveal` 安全 DTO。Main 对注册项目/授权外部路径再次校验，Office 使用系统 open，图片 preview 只返回受控 data URL，可执行、HTML/SVG 和不支持类型默认 Explorer reveal；Renderer 通过正式 `ArtifactDescriptor`/ArtifactCard 展示，不访问任意 fs/shell，URI/HTML/shell 输入不直执行，缺失或不支持只生成局部反馈，不重跑 Agent。
- **回归修正**：ProcessSession 的 Windows 输出解码复用当前 shell 的 UTF-8/ANSI/OEM 编码候选，恢复 CP936 输出；ArtifactService 不在构造时假设测试或尚未创建的 workdir 已存在，实际 describe 仍检查文件和授权目录；同步架构边界测试白名单和 W04 reload 用例的 tool output cap 断言。

### 当前调用链

`settings.save -> DesktopBridge -> write_user_config -> load_effective_config -> current/background Application.reload_configuration -> existing Provider/Tool registry + AttachmentPolicy/ProcessSession cap`；reload 只在安全边界提交，活 Process 的 launch args 和旧 projector 保持到退出。

`Renderer ChatTimeline -> preload typed runtime request -> Electron Main path/project authorization -> Python Bridge artifact DTO -> Application ArtifactService`；`artifact.describe/preview` 只读取描述或受控 preview，`artifact.open/reveal` 才进入 Main 的真实 `shell.openPath/showItemInFolder`。

`Provider tool result -> _RunawayDetector -> one-shot RuntimeFeedback -> next Provider request`；再次达到有界阈值时先闭合当前 FIFO batch，再由 Agent Loop 产生 `runaway_detected` 失败终态。有效编辑结果、Process 空读、用户输入恢复和取消沿既有控制链，不共用 runaway 终态。

## Checklist 本轮已验证并勾选

- T14：A08、A22。
- T15：A23。

A24 保持未勾选：Main/preload/chat 定向自动化已通过，但冻结条件还要求人工点开产物；本轮未把自动化替代人工验收。A18、T19、真实 Provider、POSIX 和 packaged 条件也保持未勾选。

## 依赖与验证命令

实施和验证均使用既有 `re-uthcode` Conda 环境；没有创建环境或新增依赖。Desktop 使用仓库既有 Node 依赖；本轮没有设置或读取 Provider/Tavily 密钥。

- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_agent_loop.py -k "t14_"`：`5 passed, 65 deselected`。
- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_config_loader_integration.py tests/test_config_contract.py tests/test_configuration.py tests/test_builtin_process_tool.py tests/test_tool_result_persistence.py tests/test_desktop_artifacts.py tests/test_desktop_bridge.py`：修复完成后重跑结果记录于本节收口追加。
- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_architecture_boundaries.py`：`23 passed`。
- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_builtin_process_tool.py -k "cp936 or replacement_only"`：`2 passed, 150 deselected`。
- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_desktop_artifacts.py tests/test_desktop_bridge.py -k "artifact or settings or configuration"`：`17 passed, 63 deselected`。
- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_w04_review_fixes.py -k "settings_save_reloads_search_for_next_turn"`：`1 passed, 5 deselected`；覆盖 output cap reload 后存活进程不重启。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src/uthcode`：通过。
- `npm run typecheck`（工作目录 `desktop/`）：通过。
- `npx tsx --test tests/preload.test.ts tests/main-bundle.test.ts tests/renderer-settings.test.tsx tests/renderer-chat.test.tsx tests/renderer.test.tsx`（工作目录 `desktop/`）：`127 passed, 0 failed`。

## 未验证项、差异与风险

- 用户尚未配置真实 Tavily/Provider；没有执行 A18 真实查询、真实用量、真实模型视觉输入或真实端点验收，也没有请求或打印密钥。
- A24 的自动化链已覆盖授权 open/reveal、受控图片 preview、恶意 URI 拒绝和局部错误，但 Windows 原生 Explorer/Office/图片应用的人工点击结果未验证，故不勾选 A24。
- 未执行 packaged 安装产物、POSIX/WSL、T19 联合链路；未用 fixture、mock、CDP 或离线结果替代这些条件。
- T14 依赖语义结果哈希和最近窗口；窗口本身有界，内部纠偏阈值不暴露为用户配置。合法等待只在有实际新输出时参与 Process 状态观察。

## 清理结果

测试临时目录由 pytest/Node 测试清理，未创建交付目录。没有执行 commit、push、merge、rebase、tag、release 或工作包归档；本轮停止修改后交由总控和 Terra 审核。

## UTF-8 guard

- files checked：本 Feedback、W05 相关 Context、配置手册、Context-Index、冻结 Checklist 以及本轮修改的 governed Markdown。
- result：待本轮全部文档写入完成后执行 `check_utf8_docs.py` 并在收口追加记录精确结果。
- repaired encoding issues：无。

## 最终收口追加（2026-09-13）

- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_agent_loop.py tests/test_agent_policy.py tests/test_agent_events.py tests/test_package.py`：`108 passed in 3.94s`。
- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_config_loader_integration.py tests/test_config_contract.py tests/test_configuration.py tests/test_builtin_process_tool.py tests/test_tool_result_persistence.py tests/test_desktop_artifacts.py tests/test_desktop_bridge.py`：`347 passed in 21.71s`。
- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_process_sessions.py tests/test_w04_review_fixes.py`：`10 passed in 6.25s`。
- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_application_runs.py`：`52 passed in 5.70s`。
- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_architecture_boundaries.py`：`23 passed in 4.70s`。
- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_builtin_process_tool.py -k "cp936 or replacement_only"`：`2 passed, 150 deselected`；`tests/test_w04_review_fixes.py -k "settings_save_reloads_search_for_next_turn"`：`1 passed, 5 deselected`。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src/uthcode`：通过。
- `npm run typecheck`（`desktop/`）：通过；`npx tsx --test tests/preload.test.ts tests/main-bundle.test.ts tests/renderer-settings.test.tsx tests/renderer-chat.test.tsx tests/renderer.test.tsx`：`127 passed, 0 failed`。
- `conda run --no-capture-output -n re-uthcode python C:/Users/93445/.codex/skills/uth-utf8-guard/scripts/check_utf8_docs.py docs/Context-Index.md docs/context/A01-AgentRuntime/AgentRuntime-Context.md docs/context/GUI/GUI-Context.md docs/user-manual/configuration.md "docs/work/T11-Agent能力补齐/T11-Agent能力补齐-checklist.md" "docs/work/T11-Agent能力补齐/feedback/W05-异常截停与Desktop收口-feedback.md"`：`OK: 6 file(s) passed UTF-8 guard`。
- `conda run --no-capture-output -n re-uthcode python C:/Users/93445/.codex/t11_check_frozen.py`：`PASS: 10 frozen files unchanged except permitted checklist completion marks`。
- `git diff --check`：无空白错误；只有 Windows checkout 的 LF→CRLF 提示。

本轮验证完成后停止修改，交由总控和 Terra 审核。没有执行任何 Git 写操作、提交、推送、合并或工作包归档。

## 返工第1轮（Terra 首轮修复，2026-09-14）

Terra 首轮指出 3 项 P1 与 1 项 P2。本轮只在 W05 既有实现上修复这四项，冻结需求、Spec、Tasks、Prompt 和 Checklist 文字没有改动，既有完成勾选没有回退。

### 修复内容

- **Process 有界等待**：`Process` schema 的 `wait_ms` 现在是 50—60000 毫秒，默认 1000；执行层使用已有 `ProcessSession` 输出 signal 与取消 token 等到新输出、终态或 deadline，running 且无变化时不会直接高速 `read`，显式 `wait_ms=0` 也会被 schema/运行时拒绝。新增实际运行中的 idle process 计时、取消提前返回和 zero-wait 拒绝反例。
- **Loop 有效证据**：ReadFile 返回内容摘要事实，WriteFile/EditFile 返回 `file_change` 与 `changed`，Process 新输出/终态和 Todo/Plan 实际状态变化才解除对应 final/cycle 怀疑；无变化重写、心跳和重复无效结果不会清空截停证据。正式 AgentLoop 用例覆盖三次 final block、有效 EditFile changed、再次 final block、Todo 完成后终态，同时保留重复无效循环的截停。
- **Settings 分层**：配置加载保留每个 search、vision、tool limit 字段的来源；Bridge 返回 `configured`（用户可写）、`effective`（工作目录合并）和 `source` 安全 DTO。Renderer Settings 显示搜索、视觉、工具输出与附件上限的实际值和来源；Save 仍只写用户层，项目收紧值不会反写用户配置，当前/background/compact 继续复用既有安全 reload 和快照边界。
- **外部 Artifact 生产授权**：新增 Main-owned `desktop.artifact.authorize-external` 原生单文件 picker。Main 对用户选中的绝对路径做 stat/file 复核后写入进程内单路径 grant；preload/Renderer 只触发 picker，不接受模型 URI 或 Renderer boolean 授权。未授权 artifact 仍被 Main 拒绝，describe/preview/open/reveal 每次继续复核；聊天 artifact link 的显式“Authorize external file/授权外部文件”入口通过同一正式 DTO 返回。

### 定向验证

- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_process_sessions.py -k "process_read"`：`3 passed, 4 deselected`，覆盖 50—60000 边界内实际计时、取消和 `wait_ms=0` 拒绝。
- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_agent_loop.py -k "t14_" tests/test_builtin_file_tools.py`：`6 passed, 88 deselected`，覆盖 formal Loop 纠偏与文件变化证据。
- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_config_loader_integration.py::test_tool_limits_merge_and_project_can_only_tighten_user_values`：`1 passed`。
- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_desktop_bridge.py::test_settings_get_separates_user_configured_effective_project_limits_and_sources`：`1 passed`。
- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_desktop_artifacts.py tests/test_architecture_boundaries.py`：`27 passed`。
- `npm run typecheck`（工作目录 `desktop/`）：通过。
- `npx tsx --test --test-name-pattern='preload exposes only|Main routes authorized artifacts|Main registers one picker|Settings displays effective|ChatTimeline resolves artifact links' tests/preload.test.ts tests/renderer-settings.test.tsx tests/renderer-chat.test.tsx`（工作目录 `desktop/`）：`5 passed`。其中 Main 授权用例不注入 `authorizedExternalArtifacts`，覆盖未授权拒绝 → picker 授权 → describe/preview/open → 替换路径拒绝。

一次早期错误地把 `--test-name-pattern` 放在 npm 脚本参数尾部的探索命令实际运行了整套 Desktop 测试，结果 `230 passed, 1 failed`；唯一失败是既有 offline Runtime 用例没有设置 `UTHCODE_PYTHON`，不是本轮链路。后续已按正确 `npx tsx --test --test-name-pattern ... 文件` 形式完成上述定向验证，未再运行需要 Runtime 的 Desktop 测试。

### 未验收与风险

真实 Provider/Tavily、A18、A24 原生人工点开、packaged、POSIX/WSL、T19 和后置 W06 仍未验收；没有请求或伪造密钥，也没有用自动化替代 A24 人工条件。外部授权只存于当前 Main 进程，重启后需用户再次 picker 确认；文件删除、替换或路径不匹配仍由每次 Main stat/path 复核拒绝。其余 W05 既有风险与未勾选项保持不变。

本轮修复完成后停止修改，交由总控和 Terra 复审；没有执行 commit、push、merge、rebase、tag、release 或工作包归档。

### 返工文档守门结果

- `conda run --no-capture-output -n re-uthcode python C:/Users/93445/.codex/skills/uth-utf8-guard/scripts/check_utf8_docs.py docs/Context-Index.md docs/context/A01-AgentRuntime/AgentRuntime-Context.md docs/context/GUI/GUI-Context.md docs/user-manual/configuration.md "docs/work/T11-Agent能力补齐/T11-Agent能力补齐-checklist.md" "docs/work/T11-Agent能力补齐/feedback/W05-异常截停与Desktop收口-feedback.md"`：`OK: 6 file(s) passed UTF-8 guard`。
- `conda run --no-capture-output -n re-uthcode python C:/Users/93445/.codex/t11_check_frozen.py`：`PASS: 10 frozen files unchanged except permitted checklist completion marks`。
- `git diff --check`：无空白错误；仅有 Windows checkout 的 LF→CRLF 提示。

## 返工第1轮补充（Process 终态唤醒，2026-09-14）

复核有界等待 helper 后补齐一个真实边界：子进程无任何输出就退出时，`ProcessSession._finish_state` 现在显式 signal，bounded `Process.read` 会在终态立即返回而不是等满 deadline。`conda run --no-capture-output -n re-uthcode pytest -q tests/test_process_sessions.py -k "process_read"`：`4 passed, 4 deselected`，新增无输出终态提前返回用例；其余取消、idle timeout 与 zero-wait 拒绝仍通过。该补充仍在 W05 Process 范围内，没有改变冻结文字或扩大后置范围。

## 返工第2轮（重复 ReadFile 证据，2026-09-14）

Terra 复审唯一 P1 指出 `read_content + content_digest` 每次都无条件清疑：同一文件同一 digest 在 final block 纠偏后重新读取，会错误抹掉已有截停证据。本轮只调整 `_RunawayDetector` 的受信 read 判定，没有新增安全框架或改变真实文件工具的 `file_change.changed` 事实。

- `ReadFile` 结果指纹对 `read_content` 只取 `content_digest`。首次读取或 digest 变化才清除 final/cycle 怀疑；同一 action、同一 digest 的重复读取只作为再次观察，保留已有证据。EditFile/WriteFile 的 `file_change.changed=True`、Process 新输出/终态以及 Todo/Plan 实际变化继续沿用原有有效证据语义。
- 新增正式 AgentLoop 反例：先读取 `same.txt`，连续三次 final block 触发纠偏，再以同 digest 重复读取，连续两次 final block 后终止 `runaway_detected`。同时保留成功 EditFile 正例，并增加首次/变化 digest 清除 final block 的 detector 正例。

验证命令：

- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_agent_loop.py -k "t14_" tests/test_builtin_file_tools.py`：`8 passed, 88 deselected`。

返工第2轮完成后停止修改，交同一 Terra 复审；没有执行 commit、push、merge、rebase、tag、release 或工作包归档。

返工第2轮守门：`check_utf8_docs.py` 返回 `OK: 6 file(s) passed UTF-8 guard`；`t11_check_frozen.py` 返回 `PASS: 10 frozen files unchanged except permitted checklist completion marks`；`git diff --check` 无空白错误，仅有 Windows checkout 的 LF→CRLF 提示。

## 总控审核收口（2026-09-14）

Luna（max）完成 W05 实施及两轮返工，Terra（high）第三轮审核 PASS。Process 实际有界等待、有效进展与重复读取的区别、Settings configured/effective/source、Main picker 外部产物授权四项问题均闭环。最终 Reviewer T14 正反例 8 passed、88 deselected；前轮 Process read 4 passed、Settings/config 2 passed、Desktop typecheck 与 Main/preload/Chat/Settings 5 项、Artifact/架构 27 passed 的证据有效。未把带 -k 的命令中被 deselect 的文件测试计作通过。Worker 首轮核心 108、配置相关 347、Desktop 定向 127 是分阶段结果，后续按具体修复运行受影响测试，没有宣称最终全量重跑。人工产物 A24、真实 Provider/Tavily、POSIX、packaged 与 T19 仍待验收；整包不标记完成、不归档。
