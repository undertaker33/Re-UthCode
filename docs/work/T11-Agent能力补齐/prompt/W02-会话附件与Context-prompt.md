# W02-会话附件与Context

只有用户显式指定本文件执行时才开始实施。你负责 T04 会话原始附件与历史恢复 → T05 图片能力预检与 Context 压缩 → T06 Desktop 附件输入与回放，必须严格按此顺序完成，不执行其他 Worker 的 Task。

## 必读与前置

1. 仓库根 `AGENTS.md`、`docs/README.md`、`docs/Context-Index.md`、`docs/rules/WorkPackageRules.md`；涉及新增决策时读 `docs/rules/UserDecisionBoundary.md`，涉及后置边界读 `docs/OutstandingDebtList.md`。
2. 完整读取 `docs/work/T11-Agent能力补齐/T11-Agent能力补齐.md`、`T11-Agent能力补齐-spec.md`、`T11-Agent能力补齐-tasks.md`、`T11-Agent能力补齐-checklist.md`（后三者在同一目录）。不依赖聊天记录；原需求第3节九项决定与第4节协议均已授权。
3. 按本 Worker 命中职责读取 `docs/context/A01-AgentRuntime/AgentRuntime-Context.md`、`A02-Control/Control-Context.md`、`A03-State/State-Context.md`、`A04-Orchestration/Orchestration-Context.md`（后三者相对 `docs/context/`），涉及 Desktop 时读 `docs/context/GUI/GUI-Context.md`。只沿任务读取源码，不扫描归档全库。
4. 先读 `docs/work/T11-Agent能力补齐/feedback/W01-内容与结果公共合同-feedback.md`，再按实际依赖读更早 Feedback；缺失前置只停止依赖范围，不虚构已实现合同。
5. 使用既有 `re-uthcode` Conda 环境；Python 与新依赖范围以 `pyproject.toml` 为准；不另建环境或构建体系。

## 修改范围与源码入口

本 Worker 写范围为 Tasks 的 T04、T05、T06 对应文件组 F04 F05 F08 F16 F06 F07 F17 F18 F19 F20 F21、其真实调用点和 Checklist 指定测试；涉及文档只按当前已实现能力同步维护。下面路径来自原始需求文件组，其中新增路径尚不存在，禁止因表列就建占位文件：

- F04：`src/uthcode/core/history.py`、`core/context.py`、`core/compaction.py`；新内容序列化、引用覆盖、预算计量和压缩来源保留。
- F05：`src/uthcode/application/sessions.py`、`integrations/session_files.py`；会话附件绑定、恢复、结构必要迁移；文件/图片 replay；日志 ref 接入。
- F08：新增 `src/uthcode/application/attachments.py`、`integrations/attachment_files.py`；导入/提交/移除用例、固定副本、受控原图读取、缩略图与无引用临时清理。
- F16：`src/uthcode/integrations/tools/factory.py`、`application/bootstrap.py`；在正式启动时组合新能力、按配置/模型暴露可用工具、绑定会话资源。
- F06：`src/uthcode/application/context.py`、`request_preparation.py`、`generation.py`；图片能力/计量预检、真实请求组装、模型切换候选验证、关闭资源。
- F07：`src/uthcode/integrations/providers/anthropic.py`、`openai_responses.py`、`openai_compat.py`；用户/工具图片的序列化与计量适配，支持失败明确映射。
- F17：`src/uthcode/application/configuration.py`、`integrations/config/loader.py`、`writer.py`；search/vision/tool limits 配置、用户与项目边界、秘密写入脱敏。
- F18：`src/uthcode/interfaces/desktop/bridge.py`、`protocol.py`；`desktop/src/desktop-api.ts`；附件、预览、进程查询/停止/日志、安全产物 DTO；background 资源保留。
- F19：`desktop/src/main.ts`、`preload.ts`；文件选择/导入、受控二进制传输/读取和打开/定位。
- F20：`desktop/src/renderer/Composer.tsx`、`ChatTimeline.tsx`、`safe-markdown.tsx`；状态与生命周期文件按现有路由修改；附件草稿/缩略、工具卡折叠/续读、来源链接、会话归属与异常原因。
- F21：`desktop/src/renderer/SettingsView.tsx`、`SettingsEditorModal.tsx`、`settings-draft.ts`、`locales/{zh-CN,en}.ts`；搜索与图片能力配置、资源项、活动态禁用/生效提示，中英文本。

必须同时读取 Tasks 的“本地核验补充”和“官方参考核验”；其中补齐的实际路径按所属 F 组属于本 Worker 的范围。

## 已确认决定与执行约束

- T04：新增附件用例和文件适配承载临时导入、固定副本、提交绑定、移除、读取及派生缓存；副本就绪才提交引用，失败不重复 Turn。接入 Session、Transcript/Timeline 和分页；只做结构必要迁移，重复打开幂等，不保留长期双写。已提交原图不是缓存；无引用临时与派生文件正常淘汰。 完成边界：删除源文件后已提交附件和图像仍能恢复；重发使用原副本；原图不会被缓存清除。
- T05：模型配置加入明确图片能力声明，贯通现有 application/configuration.py、integrations/config/data.py 的配置模型与 loader/writer。按真实待发请求（含历史及切换候选）预检，未知按不支持；拒绝时保留模型/草稿。Integration 提供有来源的图片非零估计或 count；字节/尺寸与 Token 分别检查。摘要保留可重读来源，沿用 F03 实际 Working Context 缩减判据。 完成边界：图片正常退出请求后可切文字模型；不得暗中删图或压缩以强行切换；256K 文字 profile 不重调。
- T06：Main 文件选择/粘贴字节经 Application 导入；Composer 支持拖拽、粘贴、选择、仅附件发送、预览移除和失败重发。更新 desktop-api、Bridge protocol、状态及生命周期；历史分页显示附件，首条仅附件有标题/预览回退。大字节不放入通用事件，Renderer 不直读任意路径。 完成边界：一个提交只有一个 Turn；切 Session 草稿归属正确；失败保留可编辑草稿；同一正式输入同时服务 Headless。

公共类型、会话内资产、异常截停及搜索秘密/受控进度的窄修订已被需求授权，不为同一决定重复询问。不得削减 15 项能力；不添加范围外服务、Runtime、兼容层或通用框架。普通工程选择自行完成；若新证据实质改变冻结范围，按规则记录并停止受影响范围。

共享 Core/配置/Bridge/工厂区域在当前 Worker 内保持单写者。可以委派无重叠且已授权的子任务，不自行执行未派发的后续 Worker，不为此建设全仓锁。首次派发后原始需求、Spec、Tasks、所有 Prompt 与 Checklist 文字冻结；仅可勾选已有完成框，Feedback 追加。禁止修改其他冻结工作包、Git commit/push/merge/rebase/tag/release 或归档。

## 验证与反馈

执行 Checklist 的 T04、T05、T06，覆盖 A04 A07 A05 A06 A03。按真实改动运行最小定向测试；涉及架构边界执行 `python -m pytest tests/test_architecture_boundaries.py -q`。引用前序有效证据不等于跳过当前未覆盖条件。真实 Provider、Windows/POSIX PTY、安装产物和官方评分不得以 Mock/CDP 代替；缺条件保留未完成，继续其他独立授权工作。

首次实施创建 `docs/work/T11-Agent能力补齐/feedback/W02-会话附件与Context-feedback.md`，之后只向同一文件追加返工轮次。记录实际改动、关键调用链与理由、文件、命令及精确结果、Checklist 项、差异、未验证项/风险/遗留问题和清理结果；不复制任务书、不新建 retry/v2 文件。中文文档 UTF-8 与围栏检查通过后交付。
