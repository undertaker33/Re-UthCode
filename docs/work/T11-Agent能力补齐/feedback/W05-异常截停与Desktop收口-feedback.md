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

## T16 服务边界补充（2026-09-21）

本轮只补 Python Application/Integration 与相关测试，并与 UI worker 对齐已有 IPC 形状；未修改 Desktop。artifact.preview 的 mode 继续由 Bridge 校验后转发到 Application，Office/PDF 保持系统打开路径，Markdown/code/plaintext 使用有界只读文本 DTO，图片使用有界 thumbnail/full DTO。

Session attachment 的 open/reveal 仍由 ref 唯一寻址，服务端生成带正确扩展名的派生文件并返回正式 Main DTO；Renderer 不获得任意路径或 shell 权限。文本 preview 共用 Integration 有界读取实现，图片在 Pillow 解码边界校验尺寸/像素，派生缓存受 quota 和正常 Session cleanup 管理。

Python 定向组合回归为 150 passed in 14.98s，另覆盖模型历史图片切换的 image_input_unsupported 业务码和模型可见 artifact: 链接格式提示。真实 packaged/native Main 操作仍未由本轮 Python worker 验证，交总控按 A24/A10 条件验收；本轮无 Git 写操作。


## Desktop 收尾补充（2026-09-23）

本轮继续在 W05 T16 的 Desktop 范围内收口；原始需求、Spec、Tasks、Prompt 和 Checklist 文字未改动，未修改 Python、根文档或其他 Worker 的记录。

### 实际改动

- Markdown/code 只读画布现在作为主窗口 Grid 的右侧列，占用被预览时 Runtime 原有的空间。聊天与 Composer 随画布打开、拖宽和关闭重新排版；docked、floating、hidden 与 Focus Mode 均使用明确的 Grid 列。屏幕宽度不超过 620 CSS px 时暂时隐藏 Sidebar，为聊天和画布保留空间，关闭画布后恢复。
- 预览期间卸载 RuntimePanel 视图但保留 Application/Renderer 的 `panelMode` 状态；关闭画布后 Runtime 按原布局重新显示。画布宽度受当前视口、侧栏宽度与 240 px 会话最小宽度约束，窄屏可继续缩小到 220 px。
- 将 App 的受控 `state.notice` 接入聊天时间线，使 Settings 保存、附件等局部操作的安全错误提示和 `/status` 命令结果实际可见；错误仍经既有本地化安全投影，不输出原生异常内容。
- 增加历史图片预览回归：历史页增加新图片导致 IntersectionObserver effect 清理时，同一仍未完成附件请求可重新发起，旧请求迟到结果不会覆盖当前预览。当前实现的 effect cleanup 会释放 pending ref，本轮回归验证了该行为。
- 更新 App 画布开关测试，覆盖 Grid 状态、运行时面板释放以及关闭后的布局恢复；调整 ResizeObserver 回归等待其生产实现的 setTimeout fallback 完成，并按辅助标签验证 `/status` 消息。

### 修改文件

- `desktop/src/renderer/App.tsx`
- `desktop/src/renderer/DocumentPreviewPanel.tsx`
- `desktop/src/renderer/app.css`
- `desktop/tests/renderer-attachments.test.tsx`
- `desktop/tests/renderer-chat.test.tsx`
- `desktop/tests/renderer.test.tsx`
- 本 W05 Feedback

### 验证结果

- `npm run typecheck`（工作目录 `desktop/`）：通过。
- `npm test`（工作目录 `desktop/`，环境变量 `UTHCODE_PYTHON=C:\Users\93445\miniconda3\envs\re-uthcode\python.exe`）：`252 passed, 0 failed, 0 skipped`。离线 Desktop Runtime 集成测试使用既有 `re-uthcode` Conda 环境通过。
- `npx tsx --test --test-name-pattern "App preserves imported Markdown preview" tests/renderer-attachments.test.tsx`：`1 passed`。
- `npx tsx --test --test-name-pattern "ChatTimeline retries an in-flight" tests/renderer-chat.test.tsx`：`1 passed`。
- `npx tsx --test --test-name-pattern "T08 App presents localized safe fallbacks" tests/renderer.test.tsx`、`npx tsx --test --test-name-pattern "T09 App consumes typed status params" tests/renderer.test.tsx`、`npx tsx --test --test-name-pattern "timeline follows the tail" tests/renderer.test.tsx`：各 `1 passed`。
- `conda run --no-capture-output -n re-uthcode python C:/Users/93445/.codex/t11_check_frozen.py`：`PASS: 10 frozen files unchanged except permitted checklist completion marks`。

完整 Desktop 自动测试与类型检查通过；本反馈未将其记作原生窗口人工验收。总控正在用当前开发窗口核对画布实际遮挡、聊天区宽度及关闭恢复，结果待其单独记录。A24 真实 Windows 文件关联/Explorer 点开、真实 Provider/Tavily、POSIX/WSL、packaged 安装与 T19 仍未验收，T11 整包状态不变。

### UTF-8 guard

- files checked：本轮追加的 W05 Feedback。
- result：`conda run --no-capture-output -n re-uthcode python C:/Users/93445/.codex/skills/uth-utf8-guard/scripts/check_utf8_docs.py "docs/work/T11-Agent能力补齐/feedback/W05-异常截停与Desktop收口-feedback.md"` 返回 `OK: 1 file(s) passed UTF-8 guard`。
- repaired encoding issues：无。

## Desktop 历史附件与图片预览收尾补充（2026-09-23）

本轮继续处理 W05 Desktop 历史回放与图片预览；冻结的 task/spec/prompt/checklist 文字未改动，Python 服务由 W02 Worker 单独修改。

### 实际改动

- 正式 `history.page` DTO 的可用附件现在保留 `type`、`available:true`、稳定 `ref`、`asset_ref` 与实际文件 metadata，经 Renderer 归一化、同 message 合并与 reducer 合并后作为用户行附件显示；图片预览仍只发送不透明 `ref`。
- 服务返回 `available:false` 时，时间线保留单独的本地化“附件不可用”占位，不构造虚假名称或大小，也不向 `attachment.preview` 发送不可用项。App history.page 集成用例覆盖同一 user message 的文本、多段 ImagePart 及不可用附件 shape。
- 清除遗留 `.timeline-attachment img`、旧 Composer attachment 图片/卡片规则与旧 fallback class，避免祖先缩略图尺寸污染双击模态图；modal stage 图片明确按自身自然尺寸并限制在可用区域内。新增 CSS 回归断言禁止 attachment ancestor 重新限定 modal 后代图片。

### 修改文件

- `desktop/src/desktop-api.ts`
- `desktop/src/renderer/App.tsx`
- `desktop/src/renderer/ChatTimeline.tsx`
- `desktop/src/renderer/FileCard.tsx`
- `desktop/src/renderer/app.css`
- `desktop/src/renderer/state-normalization.ts`
- `desktop/src/renderer/state.ts`
- `desktop/src/renderer/locales/en.ts`
- `desktop/src/renderer/locales/zh-CN.ts`
- `desktop/tests/renderer.test.tsx`
- `desktop/tests/renderer-attachments.test.tsx`
- 本 W05 Feedback

### 验证结果

- `npm run typecheck`（工作目录 `desktop/`）：通过。
- `npx tsx --test --test-name-pattern "App pages history independently" tests/renderer.test.tsx`（工作目录 `desktop/`）：`1 passed`；正式 history.page 形状经过 Renderer 归一化、同 message 合并与 state merge，图片行触发带 opaque ref 的 preview，不可用项保留占位且不触发 preview。
- `npx tsx --test --test-name-pattern "replay merges multipart user" tests/renderer-state.test.ts`（工作目录 `desktop/`）：`1 passed`。
- `npx tsx --test --test-name-pattern "full image preview sizing" tests/renderer-attachments.test.tsx`（工作目录 `desktop/`）：`1 passed`。
- `npm test`（工作目录 `desktop/`，环境变量 `UTHCODE_PYTHON=C:\Users\93445\miniconda3\envs\re-uthcode\python.exe`）：`253 passed, 0 failed, 0 cancelled, 0 skipped`，约 107.3 秒。离线 Desktop Runtime 集成与 T08 bundled Runtime smoke 均在此全量运行通过。
- W02 Worker 报告 `tests/test_history_bridge.py tests/test_attachments.py tests/test_architecture_boundaries.py`：`38 passed / 14.00s`；本 Desktop Worker 未修改 Python。
- `conda run --no-capture-output -n re-uthcode python C:/Users/93445/.codex/t11_check_frozen.py`：`PASS: 10 frozen files unchanged except permitted checklist completion marks`。
- `conda run --no-capture-output -n re-uthcode python C:/Users/93445/.codex/skills/uth-utf8-guard/scripts/check_utf8_docs.py "docs/work/T11-Agent能力补齐/feedback/W05-异常截停与Desktop收口-feedback.md"`：`OK: 1 file(s) passed UTF-8 guard`。

代码与自动测试已稳定，原生窗口中 history.page 恢复、画布布局及 100% 图片模态尺寸由总控继续复验；本反馈不将该人工复验提前记为通过。真实 Provider/Tavily、A24 原生 Windows 关联/Explorer、packaged 安装、POSIX/WSL 与 T19 仍未验收，T11 整包状态不变。

## Python 语法颜色与画布窄列工具栏补充（2026-09-24）

本轮按总控 9/24 构建产物验收修复两项 Desktop 表现；冻结的 task/spec/prompt/checklist 文字未改动，也未改 Python 服务或其他根文档。

### 实际改动

- 只读代码画布按 Prism 实际输出的 `.token.*` 类着色，覆盖关键字、字符串、数字、函数/内建、属性、运算符、标点和注释；色值使用主题变量，并为暗色、亮色及 system-light 提供可读的独立色板。删除不再匹配 Prism 输出的旧 `.syntax-*` 规则。
- 文档画布可见时，聊天 `main` 按自身 inline-size 建立查询容器；聊天列不超过 720 px 时，Composer 将模型选择器移至第二行、发送操作固定在首行；列宽不超过 380 px 时附件按钮和权限选择器继续分行，避免依赖整个窗口宽度推断可用聊天宽度及按钮逐字竖排。
- 增加实际 Python Prism 输出回归，确认注释、关键字、用户函数、内建名、运算符、数字与字符串 token 均产生 DOM 类，并检查 token 主题规则；另增加聊天列容器及窄列布局 CSS 契约回归。

### 修改文件

- `desktop/src/renderer/app.css`
- `desktop/tests/renderer-attachments.test.tsx`
- 本 W05 Feedback

### 验证结果

- `npx tsx --test tests/renderer-attachments.test.tsx`（工作目录 `desktop/`）：`15 passed, 0 failed`。
- `npm run typecheck`（工作目录 `desktop/`）：通过。
- `npm test`（工作目录 `desktop/`，执行前显式设置 `UTHCODE_PYTHON=C:\Users\93445\miniconda3\envs\re-uthcode\python.exe`）：`255 passed, 0 failed, 0 cancelled, 0 skipped`，约 53.5 秒；含新增两项回归以及离线 Desktop Runtime / packaged Runtime smoke 测试。
- 总控的原生验收记录：`sample.xlsx` 双击后由系统 Excel 打开，工作表 `SHEET-5937` 的 `B2=42` 正确；PPT 文件触发系统“打开方式”选择器，已选择 PowerPoint 一次，启动结果仍由总控观察。本轮源码测试未代替画布高亮颜色与 1266×793 下 Composer 实际排版的构建产物目视复验。
- 当前待总控标准重建后复核 Python token 的实际色彩、460 px 画布下 Composer 发送与附件控件不竖排，以及 PPT 启动结果。真实 Provider/Tavily、A24 Windows 关联/Explorer 全覆盖、POSIX/WSL 与 T19 仍未验收，T11 整包状态不变。

### UTF-8 guard

- files checked：本轮追加的 W05 Feedback。
- `conda run --no-capture-output -n re-uthcode python C:/Users/93445/.codex/skills/uth-utf8-guard/scripts/check_utf8_docs.py "docs/work/T11-Agent能力补齐/feedback/W05-异常截停与Desktop收口-feedback.md"`：`OK: 1 file(s) passed UTF-8 guard`。
- `conda run --no-capture-output -n re-uthcode python C:/Users/93445/.codex/t11_check_frozen.py`：`PASS: 10 frozen files unchanged except permitted checklist completion marks`。
- repaired encoding issues：无。

## 图片附件卡片与文本框菜单收尾（2026-09-24）

本轮继续收敛 W05 的 Desktop 文件卡片和 Composer 输入交互；Spec、Tasks、Prompt、Checklist 均未修改。

### 实际改动

- 图片附件卡片使用 104 × 104 px 有界缩略图，不展示可见名称、类型或大小；文件名仍保留在卡片可访问名称和图片替代文本中。仅 Composer 草稿卡片提供直接移除 X，历史/已发送卡片没有移除入口，X 的双击不会触发卡片预览。
- Composer 的附件选择入口收敛为纯加号。文本粘贴、文件粘贴和拖放继续走各自既有输入处理。
- Electron Main 为文本框提供原生剪切、复制、粘贴和全选菜单，保留 Electron 对应编辑角色；菜单语言每次按 Desktop preference 读取，未能读取时回退到系统语言。

### 修改文件

- `desktop/src/main.ts`
- `desktop/src/renderer/Composer.tsx`
- `desktop/src/renderer/FileCard.tsx`
- `desktop/src/renderer/UiIcon.tsx`
- `desktop/src/renderer/app.css`
- `desktop/tests/main-bundle.test.ts`
- `desktop/tests/renderer-attachments.test.tsx`
- 本 W05 Feedback

### 验证结果

- `npm run typecheck`（工作目录 `desktop/`）：通过。
- `npx tsx --test tests/main-bundle.test.ts`（工作目录 `desktop/`）：`1 passed`。测试编译真实 Webpack Main 入口，确认只有 textarea 弹出菜单、剪切/复制/粘贴/全选角色正确，默认简体中文标签正确，并在持久偏好改为英文后读到英文标签。
- `npx tsx --test tests/renderer-attachments.test.tsx`（工作目录 `desktop/`）：`16 passed, 0 failed`。覆盖纯加号入口、粘贴/拖放、104 px 图片卡片、可访问文件名、草稿移除与历史卡片无移除入口。
- `$env:UTHCODE_PYTHON='C:/Users/93445/miniconda3/envs/re-uthcode/python.exe'; npm test`（工作目录 `desktop/`）：`256 passed, 0 failed, 0 cancelled, 0 skipped`，`duration_ms 81551.0371`；包含 packaged Runtime 构建 smoke。
- 总控此前报告已用 Computer Use 在开发窗口确认图片缩略图尺寸、草稿 X 移除、Python 语法着色，以及 1266 × 793 窗口下 460 px 文档画布与 Composer 工具栏布局。本记录不把该开发窗口证据当作最终包内菜单验收。

Main bundle 与定向 Renderer 检查均通过。完整测试中的构建 smoke 与总控的 package 曾并行写入同一 `.runtime` 输出目录；总控报告并行产物首次启动时 Runtime 状态失败，随后改为串行重包并复验。当前没有可读取的 UthCode Python stderr 持久日志或匹配的 Windows Application Error 事件；Main 仅把固定脱敏诊断投影到界面。最终包启动及包内中文菜单的人工复验由总控在串行重包后记录；A24 其余 Windows 文件关联、真实 Provider/Tavily、POSIX/WSL 与 T19 仍按现有工作包证据保持未验收，T11 整包状态不变。

### UTF-8 guard

- files checked：本轮追加的 W05 Feedback。
- repaired encoding issues：无。

### 串行重包后的总控复验补记（2026-09-24）

总控在完整 Desktop 测试结束后串行重建最终包，消除了与 packaged Runtime smoke 同时写入 `.runtime` 的构建冲突。总控报告标准 `npm run package` 构建记录 24186 exit 0；随后 packaged Runtime 显示 ready，原有历史恢复正常。

总控随后在最终包中用 Computer Use 实测中文原生菜单的剪切、复制、粘贴、全选四项；全选、剪切快捷键及粘贴菜单均正确恢复测试文本。按 Alt+PrintScreen 复制测试窗口图像后，用 Ctrl+V 从真实剪贴板导入图片，Composer 显示 104 px、无可见元数据的卡片；点击 X 后卡片移除、未打开图片 overlay、草稿清空且没有向模型发送消息。

以上是总控提供的最终包原生窗口证据，不是测试桩或 Webpack bundle 模拟。该结果补齐了上一节留给总控的最终包及中文菜单复验；其他 T11 包级未验收项保持原状。
### 验收环境口径澄清（2026-09-25）

上节将总控的 104px 图片、草稿 X、Python 着色和窄列布局检查称为开发窗口，环境口径不准确：这些检查实际在标准 package 生成的 UthCode.exe 中完成。最终中文菜单和真实剪贴板检查另在串行重建的产物中完成；原 W06 Feedback 已分别记录，不扩大其余包级验收结论。
