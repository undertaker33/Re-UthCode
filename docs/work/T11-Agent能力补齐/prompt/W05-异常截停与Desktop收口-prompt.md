# W05-异常截停与Desktop收口

只有用户显式指定本文件执行时才开始实施。你负责 T14 异常纠偏与截停替代固定上限 → T15 Settings 配置完整性与生效边界 → T16 Desktop 产物打开与受控预览，必须严格按此顺序完成，不执行其他 Worker 的 Task。

## 必读与前置

1. 仓库根 `AGENTS.md`、`docs/README.md`、`docs/Context-Index.md`、`docs/rules/WorkPackageRules.md`；涉及新增决策时读 `docs/rules/UserDecisionBoundary.md`，涉及后置边界读 `docs/OutstandingDebtList.md`。
2. 完整读取 `docs/work/T11-Agent能力补齐/T11-Agent能力补齐.md`、`T11-Agent能力补齐-spec.md`、`T11-Agent能力补齐-tasks.md`、`T11-Agent能力补齐-checklist.md`（后三者在同一目录）。不依赖聊天记录；原需求第3节九项决定与第4节协议均已授权。
3. 按本 Worker 命中职责读取 `docs/context/A01-AgentRuntime/AgentRuntime-Context.md`、`A02-Control/Control-Context.md`、`A03-State/State-Context.md`、`A04-Orchestration/Orchestration-Context.md`（后三者相对 `docs/context/`），涉及 Desktop 时读 `docs/context/GUI/GUI-Context.md`。只沿任务读取源码，不扫描归档全库。
4. 先读 `docs/work/T11-Agent能力补齐/feedback/W04-联网取证与代码操作-feedback.md`，再按实际依赖读更早 Feedback；缺失前置只停止依赖范围，不虚构已实现合同。
5. 使用既有 `re-uthcode` Conda 环境；Python 与新依赖范围以 `pyproject.toml` 为准；不另建环境或构建体系。

## 修改范围与源码入口

本 Worker 写范围为 Tasks 的 T14、T15、T16 对应文件组 F02 F03 F06 F20 F24 F25 F17 F18 F21 F08 F19、其真实调用点和 Checklist 指定测试；涉及文档只按当前已实现能力同步维护。下面路径来自原始需求文件组，其中新增路径尚不存在，禁止因表列就建占位文件：

- F02：`src/uthcode/core/tool.py`、`application/tools.py`；失败结构、副作用、进度出口；物化与脱敏；新工具注册组合。
- F03：`src/uthcode/core/agent.py`、`core/agent_events.py`、`application/runs.py`；新输入值、闭合终态、工具进度路由、移除累计轮数 gate；有限异常检测和失败原因。
- F06：`src/uthcode/application/context.py`、`request_preparation.py`、`generation.py`；图片能力/计量预检、真实请求组装、模型切换候选验证、关闭资源。
- F20：`desktop/src/renderer/Composer.tsx`、`ChatTimeline.tsx`、`safe-markdown.tsx`；状态与生命周期文件按现有路由修改；附件草稿/缩略、工具卡折叠/续读、来源链接、会话归属与异常原因。
- F24：`tests/` 与 `desktop/tests/` 第 8 节指定位置；最小合同/回归/端到端正反例；替换旧 max_iterations 和字符串-only 断言。
- F25：`AGENTS.md` 和第 9 节文档；用户已批准的搜索秘密/事件正文边界、运行上限修订及使用说明。
- F17：`src/uthcode/application/configuration.py`、`integrations/config/loader.py`、`writer.py`；search/vision/tool limits 配置、用户与项目边界、秘密写入脱敏。
- F18：`src/uthcode/interfaces/desktop/bridge.py`、`protocol.py`；`desktop/src/desktop-api.ts`；附件、预览、进程查询/停止/日志、安全产物 DTO；background 资源保留。
- F21：`desktop/src/renderer/SettingsView.tsx`、`SettingsEditorModal.tsx`、`settings-draft.ts`、`locales/{zh-CN,en}.ts`；搜索与图片能力配置、资源项、活动态禁用/生效提示，中英文本。
- F08：新增 `src/uthcode/application/attachments.py`、`integrations/attachment_files.py`；导入/提交/移除用例、固定副本、受控原图读取、缩略图与无引用临时清理。
- F19：`desktop/src/main.ts`、`preload.ts`；文件选择/导入、受控二进制传输/读取和打开/定位。

必须同时读取 Tasks 的“本地核验补充”和“官方参考核验”；其中补齐的实际路径按所属 F 组属于本 Worker 的范围。

## 已确认决定与执行约束

- T14：删除 AgentLoopConfig 与普通/continuation 中累计轮数 gate，不另设总 Token/时间 fallback；保留统计、Context Gate、I/O 与用户取消。Loop 有界保存最近行动/语义结果，三类异常按需求阈值先纠偏后截停；忽略传输身份但不乱删参数。有效新证据解除怀疑，反馈本身不重置；合法 Process wait 强制实际有界等待且不计空转。unknown 立即停，不进入纠偏。 完成边界：脚本 Provider 至少 200 轮正常完成；失败/短周期/final 阻断正例、编辑重测/等待/人工输入反例通过；终态 runaway_detected 与取消区分。
- T15：收口已新增 search/vision/工具单次超时、输出/附件限量；沿用配置合同、原子 writer、秘密 editor-local state 和单 modal。显示 configured/effective/source；当前和后台 Turn/Compact 保有快照，保存用于下一安全边界；活进程保有启动参数不重启。中英文本一致，不暴露内部检测窗口，不重复 reasoning/window/max_output。 完成边界：用户/项目作用域和拒绝路径可测试；项目不能放宽限制；保存不半途换模型/端点或重启存活进程。
- T16：Application 校验存在、工作目录或已授权外部路径；Main 执行 open/reveal，图片受控预览。safe-markdown/卡片连接正式 DTO，Office 系统打开，可执行默认定位。缺失/不支持局部反馈，不重跑 Agent；模型 URI/HTML/Shell 不直达执行。 完成边界：授权文件打开定位和图片预览可用；恶意 URI 不执行命令；保持 Renderer 无任意 fs/shell。

公共类型、会话内资产、异常截停及搜索秘密/受控进度的窄修订已被需求授权，不为同一决定重复询问。不得削减 15 项能力；不添加范围外服务、Runtime、兼容层或通用框架。普通工程选择自行完成；若新证据实质改变冻结范围，按规则记录并停止受影响范围。

共享 Core/配置/Bridge/工厂区域在当前 Worker 内保持单写者。可以委派无重叠且已授权的子任务，不自行执行未派发的后续 Worker，不为此建设全仓锁。首次派发后原始需求、Spec、Tasks、所有 Prompt 与 Checklist 文字冻结；仅可勾选已有完成框，Feedback 追加。禁止修改其他冻结工作包、Git commit/push/merge/rebase/tag/release 或归档。

## 验证与反馈

执行 Checklist 的 T14、T15、T16，覆盖 A08 A22 A23 A24。按真实改动运行最小定向测试；涉及架构边界执行 `python -m pytest tests/test_architecture_boundaries.py -q`。引用前序有效证据不等于跳过当前未覆盖条件。真实 Provider、Windows/POSIX PTY、安装产物和官方评分不得以 Mock/CDP 代替；缺条件保留未完成，继续其他独立授权工作。

首次实施创建 `docs/work/T11-Agent能力补齐/feedback/W05-异常截停与Desktop收口-feedback.md`，之后只向同一文件追加返工轮次。记录实际改动、关键调用链与理由、文件、命令及精确结果、Checklist 项、差异、未验证项/风险/遗留问题和清理结果；不复制任务书、不新建 retry/v2 文件。中文文档 UTF-8 与围栏检查通过后交付。
