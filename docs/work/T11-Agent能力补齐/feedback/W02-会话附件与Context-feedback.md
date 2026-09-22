# W02 会话附件与 Context Feedback

## 首轮实施（2026-09-12）

本轮按 `T04 → T05 → T06` 完成当前 Worker 范围，未实施后续 T07—T20，也未调用未配置的 Provider、Tavily 或其他收费服务。没有 Git 写操作。

### T04 会话原始附件与历史恢复

- 新增 `AttachmentFileStore` 与 `AttachmentService`。导入时把源字节原子复制到 Session 的 `attachments/<opaque-ref>/content.bin`，并写入带 SHA-256、大小、MIME、图片尺寸、提交状态的 `metadata.json`；Core、Transcript、Event 和 Provider 请求只携带 `asset_ref` 与结构化事实，不携带字节。
- Application 的 `SessionWriter` 在 Transcript append 已确认持久化后标记附件为 submitted。submitted 原图不被草稿删除或临时/派生清理移除；未提交草稿可显式删除，临时 `.tmp` 与 `derived` 内容可重建清理。
- Session replay/history projection 对 Image/File/Source 和结构化 ToolResult 保留附件引用、名称、MIME、大小和可选尺寸；重新打开 store 后仍可按 ref 读取副本。
- `tests/test_attachments.py::test_application_attachment_copy_survives_source_change_and_restart_history` 已实际修改并删除源文件，重开 Session store 读取历史，验证临时/派生清理与 submitted 原图保护。

### T05 图片能力预检与 Context 压缩

- `ModelProfile.supports_images` 在 configuration、loader、writer、Desktop Settings 中形成三态配置（`true`/`false`/`null`）；未知按不支持处理，配置页保留未知值，新增模型默认关闭图片输入。
- `AgentRun.start_turn` 和 Application 的模型切换候选均在状态变更前预检。新图、未被已提交 Context Timeline 覆盖的历史图会拒绝文字/未知模型，请求失败时旧模型、Session 和附件草稿保持不变。
- Attachment resolver 在三种 Provider Integration 的正式请求组装边界读取 Session 副本。Application 对真实待发 `GenerationRequest` 记录 `image_count`、来源、非零 `image_bytes` 与独立 `image_tokens`，不把来源或字节写入公开内容。
- Context compaction 仍使用已有 Working Context 严格下降判据；摘要响应保留 turn/ref coverage，原始 ref 可重读。提交成功、图像退出当前 Working Context 后，文字模型候选才允许通过；没有暗中删除原图或以压缩图片绕过能力拒绝。
- `test_application_image_request_has_gate_accounting_and_real_responses_wire` 通过 Application、OpenAI Responses adapter 和 fake SDK client 检查了实际 `input_image` data URL、非零来源计量与 Gate；这不是真实 Provider 内容理解验收。
- `test_unsupported_image_model_preserves_model_and_attachment_draft` 和 `test_context_compaction_preserves_source_shrinks_request_and_allows_text_model` 分别验证拒绝回滚、摘要后 ref 可读、请求严格缩小和文字模型切换。

### T06 Desktop 附件输入与回放

- Bridge 新增 `attachment.import/preview/remove`，`turn.start` 接受 `attachments` 数组并允许仅附件输入；附件 ref 由 Application Session 校验并转为 `MessageInput`，保持 Headless 与 Desktop 同一 Turn 链。
- preload 正式公开且可枚举 `chooseAttachment`、`pasteAttachment`；Main 通过受控文件选择和剪贴板图片 IPC 只传 base64 DTO。Renderer Composer 支持选择、剪贴板、拖拽、粘贴、图片预览、文件回退、移除、仅附件发送和失败后重发；提交成功才清空草稿，失败保留可编辑附件。
- Renderer 以 `project_key + session_id` 归属历史附件，成功新建/恢复 Session 清空旧草稿，历史回放只显示安全附件 DTO。Settings Model 编辑器增加中英文 `supports_images` 控件并沿用 active Turn 保存禁用边界。
- `tests/test_desktop_bridge.py::test_real_application_attachment_import_and_attachment_only_turn_have_one_durable_turn` 实际走 Bridge → Application → Run → Provider → Session writer，确认一个仅附件提交只产生一个 user/assistant Turn，并标记副本 submitted。
- `desktop/tests/renderer-attachments.test.tsx` 覆盖选择、粘贴、拖拽、预览、移除、仅附件发送和 `turn.start` 失败后重发；`renderer-chat.test.tsx` 覆盖历史图片预览与文件回退；`renderer-state.test.ts` 覆盖跨 Session 清空草稿。

## Checklist 本轮已验证并勾选

- T04：A04；T04 完成边界。
- T05：A05、A06；T05 完成边界。
- T06：A03、A04、A05；T06 完成边界。

未勾选 A02（三协议真实模型内容理解）以及其他 Worker/T19 的真实 Provider、Tavily、打包和联合验收项目。现有三协议 wire fixture 与 fake SDK 请求只证明本地序列化/资产读取路径，不替代用户配置后的真实请求。

## 验证命令与结果

- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_attachments.py -q`：4 passed。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_desktop_bridge.py -q`：74 passed。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q`：23 passed。
- `conda run --no-capture-output -n re-uthcode python -m pytest -q`：1536 passed，3 skipped。
- `npm run typecheck`（`desktop/`）：通过。
- `UTHCODE_PYTHON=C:\Users\93445\miniconda3\envs\re-uthcode\python.exe npm test`（`desktop/`）：221 passed，0 failed。
- `python C:/Users/93445/.codex/skills/uth-utf8-guard/scripts/check_utf8_docs.py ...`：本轮文档写入前后目标 Markdown 均通过 UTF-8、乱码标记和 fence 检查。

## 未验证项、差异与风险

- 未请求或读取任何 Provider/Tavily 凭据；真实 Provider 的图片理解、端点计量、三协议用户图/工具图差异、费用行为留待用户配置后由 A02/T19 补测，不能以本轮 fake SDK 结果勾选。
- 未执行 Windows 原生文件选择、系统剪贴板、人工拖放或 packaged 安装后的附件验收；本轮 Main/preload/Renderer 走了离线受控 IPC 与 DOM 用例。
- 本轮 Context 压缩减少的是待发 Working Context 的摘要内容，保留原始附件副本和 ref；没有新增不可回建的像素压缩缓存，也没有用删除图片来通过 Gate。
- 没有新增能力欠账：跨程序 Runtime checkpoint 与跨 Session Artifact 生命周期仍由原任务边界保留，当前 Session 内原始附件和派生清理已接通。

## 清理结果

实验目录 `D:\project\Re-UthCode\tmp-compact-test`、`tmp-compact-test2`、`tmp-resp-test` 已按绝对路径清理；正式附件测试使用 pytest `tmp_path`，工作区未留下本轮临时目录。当前未执行 commit、push、merge 或归档。

## 首轮交付前补充核对（2026-09-12）

- A07 保持未勾选。当前实现没有修改 Session v3 metadata schema（仍为 schema 3）或 record envelope（仍为 schema 2），也没有新增旧 Session 到新格式的迁移器；附件自己的 `attachments/<ref>/metadata.json` schema 1 是 Session 目录下的新增附属资料，replay 的 `attachments` 字段为空时不写入，因此既有文字 Session 的持久形状没有双写分支。全量回归包含 `tests/test_session_files.py::test_session_v3_reads_legacy_full_message_payload_without_rewriting`、Unicode 文字 Session 重开和 history paging，证明当前只读兼容与文字数据回归；但没有新增 A07 要求的独立迁移样本、重复打开幂等迁移证据，所以不声称 A07 完成。
- Attachment metadata 中的 SHA-256 只用于导入副本读取时的本地 size/hash 一致性检查，服务于发现截断或损坏的副本；没有签名、外部来源证明、Manifest、跨对象校验或其他完整性证明链，也不改变 replay/Context/Provider 请求的 ref-only 合同。
- Desktop 全量测试在 PowerShell 中实际使用：`$env:UTHCODE_PYTHON = (conda run --no-capture-output -n re-uthcode python -c "import sys; print(sys.executable)").Trim(); npm test`（工作目录 `desktop/`），结果仍为 221 passed、0 failed；之前的简写仅表达同一环境变量设置，不作为独立 POSIX 命令要求。

## 返工第1轮（2026-09-12）

首轮 Terra 复审指出五类行为证据不足或边界缺失。本轮只在当前 W02 的 T04→T06 范围内修复，并在本节追加记录；没有修改冻结需求、Spec、Tasks、Prompt 的文字，没有 Git 写操作，也没有调用未配置的 Provider/Tavily。

### 实际修复

- 图片限制和计量已接入实际请求链：`AttachmentPolicy` 现在在导入、读取和 Application 请求边界统一检查有限的宽度、高度和像素数；`RequestAccounting` 将有来源的尺寸/字节估算纳入图片 token 与 input Gate，Provider exact count 仍优先，未知估计在正式 Application 请求中拒绝。新增大尺寸 PNG 导入拒绝，以及历史/候选模型切换和真实待发 Gate 的定向覆盖；未改变冻结的 256K 文字策略。
- Application 现在在导入、预览、移除、`ImagePart`/`FilePart`/`ToolResultPart` 请求路径和 Provider resolver 边界校验 `asset_ref` 必须属于 active Session；Headless 负例证明伪造其他 Session 的 ref 被拒绝，当前 ref 与历史 ref 仍可读取。
- Desktop `App.tsx` 的附件导入在 import/preview 两次异步边界保存 project、Session、`sessionViewRevision` 与 runtime generation owner；切 Session 后迟到结果不会 dispatch 到新 Composer，首次惰性创建 Session 的合法结果仍能落入草稿。
- durable Transcript 引用现在是删除保护的权威来源。metadata 写入失败不会撤销已落盘 Turn；Session writer 的 open/close 生命周期会幂等 reconcile submitted 标记并清理临时/无引用派生文件，重开只收敛状态、不重做 Turn。测试覆盖 metadata 写失败、关闭重开、删除尝试、submitted 原图保护和单条 Transcript 保持。
- 正式 Session writer open/close 已接入附件 cleanup/reconcile，测试通过正式 Application close/open 观察 crash `.tmp` 与无引用 `derived` 被回收；已提交原图可重新读取。没有把手工 `service.cleanup` 调用当作生命周期证据。

### A07 与 schema 事实

- Checklist 的 A07 已勾选。`tests/test_session_authority.py::test_existing_text_session_reopens_without_duplicate_records_or_dual_write` 从既有 Session v3 / record envelope 2 文字样本出发，重复 resume/close/reopen 后对比 Transcript/Timeline 字节、replay 和记录数，证明没有丢记录或双写；本轮没有新增迁移器，因为 schema 3/envelope 2 未变化，旧文字 full-message 仍按既有只读兼容路径读取。

### 返工验证

- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_attachments.py tests/test_context_budget_gate.py tests/test_session_files.py tests/test_session_authority.py tests/test_architecture_boundaries.py tests/test_application_runtime.py`：131 passed。
- `cd desktop; npx tsx --test tests/renderer-attachments.test.tsx`：4 passed；`npm run typecheck`：通过。
- PowerShell 设置 `UTHCODE_PYTHON` 后在 `desktop/` 执行 `npm test`：222 passed，0 failed。
- 已覆盖真实 Application/Bridge 入口的附件导入、仅附件 Turn、历史读取、失败重发、请求 Gate、跨 Session 拒绝、metadata 失败重开和正式 close/open cleanup；未用只调用私有函数的 mock 作为主链通过依据。
- A02/T19 的真实 Provider/Tavily 内容理解、端点实际计量，以及 Windows 原生选择/剪贴板/拖拽和 packaged 手工验收仍待用户配置或环境后补测；本轮不把 fake SDK/wire fixture 或离线 DOM 用例写成真实服务通过。
- `C:\Users\93445\.codex\skills\uth-utf8-guard\scripts\check_utf8_docs.py` 对本轮修改的 Markdown 通过；冻结校验 `conda run --no-capture-output -n re-uthcode python C:/Users/93445/.codex/t11_check_frozen.py` 通过。自建 `tmp-compact-test*`、`tmp-resp-test` 目录均已清理，正式测试使用 pytest `tmp_path`。

## 总控审核收口

Luna（max）完成首轮实施与一轮返工；Terra（high）第二轮审核通过，无新增 actionable finding。首轮图片 Gate/尺寸、Application 会话归属、异步导入归属、durable 原图保护及正常清理五项均已关闭。Reviewer 定向复跑附件与 Session 权威 28 passed、Renderer 附件 4 passed、架构 23 passed；冻结与 diff 检查通过。A07 既有文字样本重复打开不改 JSONL 字节，无需新增迁移器。最终返工受影响 Python 131 passed、Desktop 222 passed 和 typecheck 的 Worker 证据有效；首版全量 1536 passed、3 skipped 未作为最终版全量重跑结果。真实 Provider、Windows 原生和安装产物验收按既定安排保留未完成。

## 用户附件发送缺陷补充（2026-09-16）

用户报告带附件的消息无法发送。本次只修复当前 T06 发送链路的受控错误可达性，没有修改冻结需求、Spec、Tasks、Prompt 或 Checklist，也没有 Git 写操作。

### 真实复现与根因

- 通过真实 `UthCodeApplication → DesktopBridge → AgentRun → FakeProvider → Session` 路径验证，普通 `text/plain` 文件的文本+附件和仅附件均可提交；显式 `supports_images=true` 的模型图片两种形态也可提交并进入 Provider 请求。
- 当前用户模型配置的 `supports_images` 为未知（`null`）。图片输入在 Application 预检阶段按合同拒绝，原 Bridge 把该 `ProviderConfigurationError` 与其他启动异常一起折叠为 `turn_error`；Python Runtime 虽已解析 `kind`，Electron `invoke` 直接抛出的自定义 Error 字段不能可靠跨 Main/preload/contextBridge 到达 Renderer，Renderer 因而只能显示通用失败。

### 本次修复

- Bridge 仅将两条已知图片能力预检拒绝映射为稳定的 `image_input_unsupported`，其他 Turn 启动失败继续使用通用 `turn_error`。
- Main 仅对 `turn.start` 的该业务拒绝返回受控 JSON envelope；preload 原样传递 JSON，Renderer 在解析 Turn identity 前识别 envelope，显示中英文“所选模型不支持图片输入/在设置中启用图片能力或选择其他模型”提示，并保留附件草稿供重试。未把原始异常信息暴露给 Renderer。
- 未自动修改或伪造 Provider 的 `supports_images` 能力；当前用户需在设置中启用真实支持图片的模型后再发送图片。未配置真实 Provider/Tavily，不把 fake Provider 结果写成真实服务验收。

### 定向验证

- `conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_desktop_bridge.py -k 'real_application_bridge_attachment_send_paths or real_application_attachment_import_and_attachment_only_turn_have_one_durable_turn'`：4 passed；覆盖真实 Application/Bridge 的普通文件、支持图片模型和未知图片能力模型，包含文本+附件、仅附件、Provider 实际请求和拒绝零调用。
- `npx tsx --test tests/preload.test.ts tests/renderer-attachments.test.tsx`（工作目录 `desktop`）：19 passed；覆盖 Main envelope、preload/contextBridge JSON 传递、Renderer 中英文提示、失败保留草稿与重试。
- `npm run typecheck`（工作目录 `desktop`）：通过。
- 本补充未请求凭据、未调用未配置服务、未改变附件 schema 或 W02 冻结范围；真实图片理解和用户配置后的 Provider 请求仍按既定安排待补测。

### IPC 证据边界修正

- 本补充记录的 Desktop `19 passed` 是离线 TypeScript 契约测试，使用受控 fake `ipc`/`contextBridge` fixture 验证 JSON envelope 形状和 preload→Renderer 传递；没有把它写成 packaged Electron 进程或 Windows 原生运行实测。
- 受影响 Bridge 全测为 `80 passed`，架构边界为 `23 passed`；两项均使用 `re-uthcode` 环境执行。

## 本次缺陷复审收口（2026-09-16）

同一 Terra（high）复审已通过，无新增 actionable finding。复审采用当前源码和本补充证据：真实 Application/Bridge 附件路径 4 passed、Bridge 受影响全测 80 passed、架构边界 23 passed、Desktop Main/preload/Renderer 定向 19 passed、typecheck 通过；IPC 部分仍明确为离线契约 fixture，不宣称 packaged Electron 或 Windows 原生实测。

## 服务侧预览与模型错误码补充（2026-09-21）

本轮恢复 T11 已批准修复计划，只写 Python 服务、相关测试和本 Feedback；冻结任务书、Spec、Tasks、Prompt、Checklist 以及 Desktop 工作区没有修改。实现继续沿用既有 Session 附件 schema、派生缓存和 Application 活跃 Session 边界。

### 实际修复

- AttachmentFileStore.preview() 现在按 MIME 或保存的 display_name 扩展名识别 Markdown、Python 及其他 code/plaintext；通过 Integration 共享的受限读取、严格解码和 UTF-8 截断函数返回 preview_kind=text、text、encoding、truncated。读取只取预算前缀，不整文件读完再截断，最终文本 UTF-8 字节数不超过预算。
- 图片预览在 Pillow load() 前后检查实际宽度、高度和像素数，并继续受 thumbnail 160、full 2048 及编码 payload 上限约束；超出时返回既有附件业务错误。导入元数据无法覆盖真实解码尺寸。
- attachment.open/attachment.reveal 继续只接收 opaque ref，由 Application 校验活跃 Session 归属；System DTO 现在明确提供 source=session_attachment、session_id、ref、asset_ref、派生 path、name、mime 和 default_action。系统打开使用带原始扩展名的派生副本，保留 content.bin 不变；派生 quota 和 Session 正常 cleanup 保持接通。
- /model 遇到 Session 历史图片与目标模型能力不兼容时，Application 抛出稳定 image_input_unsupported，CommandOutcome/Bridge 保留该业务码，不再折叠成 generic command_failed。环境事实边界说明对当前工作目录中的正式文件使用 Markdown [显示名](artifact:相对路径) 引用，路径不含空白且不 URL 编码，并说明该引用不扩大外部授权；未把 Core 绑定 Desktop。

### 定向验证

- conda run --no-capture-output -n re-uthcode python -m pytest tests/test_attachments.py tests/test_desktop_artifacts.py tests/test_desktop_bridge.py tests/test_command_dispatcher.py tests/test_application_runtime.py tests/test_architecture_boundaries.py -q：150 passed in 14.98s。
- 覆盖 .py + application/octet-stream 的 Session 附件文本预览和 UTF-8 字节预算、合法超像素图片在导入后预览时的解码尺寸拒绝、派生副本扩展名/原始 content.bin 保持、派生 quota、活跃 Session 拒绝、Artifact mode、Bridge 业务错误码和环境 artifact: 链接格式提示。

### 未验证项与交接

本轮未执行 Desktop/npm、Windows 原生 open/reveal、packaged 安装产物、真实 Provider/Tavily 或 Git 操作；这些继续由 UI worker、W06 和总控验收负责。Python 服务修改集已冻结，交 Terra 复审；如发现 finding，只在本 Python 写集内修复。

## 复制路径与 artifact 链接协议补充（2026-09-21）

本轮按 UI worker 对齐后的 IPC 合同补充 Python Bridge，未修改 Desktop、冻结规则或 Git。附件复制路径使用明确的 attachment.copy_path 方法：Renderer 只发送 ref，Bridge 复用现有活跃 Session resolve 派生 DTO，Main 负责把 DTO 的 path 写入系统剪贴板；不读取 Renderer 文件系统，不借用 attachment.open/reveal 触发系统操作。

attachment.copy_path 与 attachment.open/reveal 共用 source=session_attachment、session_id、ref、asset_ref、path、name、mime、default_action 校验和派生扩展名缓存，因此跨 Session ref、伪造 path 或额外参数都会在 Python Bridge 边界被拒绝。Main 的剪贴板执行和 UI 入口由 UI worker 负责。

同时根据 UI parser 的实际协议更正模型环境提示：对已写入当前工作目录的正式文件使用 Markdown [显示名](artifact:相对路径)；普通相对路径直接写，空白和保留字符按界面协议 percent-encode，链接不扩大外部路径授权。此前同一 Feedback 的旧记录保持原样，本节记录当前事实。

定向验证：conda run --no-capture-output -n re-uthcode python -m pytest tests/test_desktop_bridge.py tests/test_application_runtime.py tests/test_architecture_boundaries.py -q：115 passed in 10.45s；其中包含 attachment.copy_path ref-only DTO、伪造 path 拒绝、环境链接提示和架构边界回归。Python 补充完成后冻结，交 Terra 与 UI worker 联合审核。

## 历史重放同一用户消息附件归属补充（2026-09-22）

Terra 复核发现：当前 transcript writer 将同一用户 Message 的多个 part 按 `message_id` 分成多个 part-local entry；旧 replay 投影只用 `turn_id` 的 `user_seen` 判断首次用户消息，正文先投影后，图片会被误标为 `steering`，导致重启后的历史附件卡片脱离原用户消息。

本轮只修改 `src/uthcode/application/sessions.py` 与 `tests/test_history_bridge.py`。replay 现在按 `(turn_id, message_id)` 记住已确定的用户消息 kind：同一消息的正文、图片及其他 part 保持首次 `user`/`steering` 归属；没有 message identity 的旧形状继续使用原 `user_seen` 回退，显式 `USER_STEERING` 仍保持 `steering`。新增真实 `SessionFileStore` 写入、关闭、新 Application resume、Desktop Bridge `history.page` 回归，验证正文和图片共享 message_id 且均为 `user`，真正后续 steering 仍为 `steering`。

定向验证：

- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_history_bridge.py::test_restarted_session_history_keeps_image_with_same_user_message -q`：1 passed in 1.33s。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_history_bridge.py -q`：4 passed in 1.06s。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_history_bridge.py tests/test_desktop_bridge.py tests/test_application_runtime.py tests/test_architecture_boundaries.py -q`：119 passed in 13.73s；覆盖本轮 copy_path ref-only DTO、artifact percent-encode 环境说明、历史恢复回归和架构边界。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_attachments.py tests/test_session_authority.py -q`：32 passed in 7.55s。

本轮仍未执行 Desktop/npm、Windows 原生或 packaged 验收、真实 Provider/Tavily，也未执行 Git 写操作；Python 服务补充已冻结，交 Terra 复审。
