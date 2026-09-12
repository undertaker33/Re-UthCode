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
