# W03-文档视觉与进程会话

只有用户显式指定本文件执行时才开始实施。你负责 T07 文档定位读取与工具图片 → T08 进程会话与原生 PTY → T09 进程生命周期与 Desktop 有界日志，必须严格按此顺序完成，不执行其他 Worker 的 Task。

## 必读与前置

1. 仓库根 `AGENTS.md`、`docs/README.md`、`docs/Context-Index.md`、`docs/rules/WorkPackageRules.md`；涉及新增决策时读 `docs/rules/UserDecisionBoundary.md`，涉及后置边界读 `docs/OutstandingDebtList.md`。
2. 完整读取 `docs/work/T11-Agent能力补齐/T11-Agent能力补齐.md`、`T11-Agent能力补齐-spec.md`、`T11-Agent能力补齐-tasks.md`、`T11-Agent能力补齐-checklist.md`（后三者在同一目录）。不依赖聊天记录；原需求第3节九项决定与第4节协议均已授权。
3. 按本 Worker 命中职责读取 `docs/context/A01-AgentRuntime/AgentRuntime-Context.md`、`A02-Control/Control-Context.md`、`A03-State/State-Context.md`、`A04-Orchestration/Orchestration-Context.md`（后三者相对 `docs/context/`），涉及 Desktop 时读 `docs/context/GUI/GUI-Context.md`。只沿任务读取源码，不扫描归档全库。
4. 先读 `docs/work/T11-Agent能力补齐/feedback/W02-会话附件与Context-feedback.md`，再按实际依赖读更早 Feedback；缺失前置只停止依赖范围，不虚构已实现合同。
5. 使用既有 `re-uthcode` Conda 环境；Python 与新依赖范围以 `pyproject.toml` 为准；不另建环境或构建体系。

## 修改范围与源码入口

本 Worker 写范围为 Tasks 的 T07、T08、T09 对应文件组 F09 F16 F23 F10 F11 F02 F03 F05 F18 F19 F20、其真实调用点和 Checklist 指定测试；涉及文档只按当前已实现能力同步维护。下面路径来自原始需求文件组，其中新增路径尚不存在，禁止因表列就建占位文件：

- F09：新增 `src/uthcode/integrations/tools/document_tools.py`、`image_tools.py`；ReadDocument、ViewImage；四格式定位与有界读取、PDF 页图。
- F16：`src/uthcode/integrations/tools/factory.py`、`application/bootstrap.py`；在正式启动时组合新能力、按配置/模型暴露可用工具、绑定会话资源。
- F23：`pyproject.toml`、`desktop/packaging/uthcode-runtime.spec`；依赖声明、平台 marker 与 Python 原生资源打包。
- F10：`src/uthcode/integrations/tools/process_tools.py`；必要时新增同目录 `process_sessions.py`；Bash 复用分类；进程句柄、pipe/PTY、输出 pump、stdin/stop；私有 OS 适配。
- F11：`src/uthcode/application/runtime_context.py`、`application/generation.py`；发布真实 shell/OS/cwd 与进程安全状态；关闭流程覆盖活进程。
- F02：`src/uthcode/core/tool.py`、`application/tools.py`；失败结构、副作用、进度出口；物化与脱敏；新工具注册组合。
- F03：`src/uthcode/core/agent.py`、`core/agent_events.py`、`application/runs.py`；新输入值、闭合终态、工具进度路由、移除累计轮数 gate；有限异常检测和失败原因。
- F05：`src/uthcode/application/sessions.py`、`integrations/session_files.py`；会话附件绑定、恢复、结构必要迁移；文件/图片 replay；日志 ref 接入。
- F18：`src/uthcode/interfaces/desktop/bridge.py`、`protocol.py`；`desktop/src/desktop-api.ts`；附件、预览、进程查询/停止/日志、安全产物 DTO；background 资源保留。
- F19：`desktop/src/main.ts`、`preload.ts`；文件选择/导入、受控二进制传输/读取和打开/定位。
- F20：`desktop/src/renderer/Composer.tsx`、`ChatTimeline.tsx`、`safe-markdown.tsx`；状态与生命周期文件按现有路由修改；附件草稿/缩略、工具卡折叠/续读、来源链接、会话归属与异常原因。

必须同时读取 Tasks 的“本地核验补充”和“官方参考核验”；其中补齐的实际路径按所属 F 组属于本 Worker 的范围。

## 已确认决定与执行约束

- T07：新增 ReadDocument/ViewImage；PDF 页、DOCX 顺序 block、XLSX sheet/range、PPTX slide 有界读取。PDF 页图经共享资产路径实际入模；公式与缓存值区分，不重算。PDFium 串行受控使用，昂贵解析需要可取消时用可回收私有子进程。依赖仅 pyproject，原生资源接入既有 PyInstaller spec。 完成边界：四格式、损坏/加密/超限/取消有定位和受控结果；不支持图片时明确不可用；安装产物实际读取由 T19 验证。
- T08：Bash 为唯一启动入口，yield_time_ms 与显式 timeout_seconds 分离；默认无总寿命。后续 Process 支持 list/read/write/stop/resize 与 EOF，按所属 Session 查句柄。pipe 分 stdout/stderr，PTY 单 terminal 流；Windows pywinpty/ConPTY、POSIX ptyprocess。复用 Job/process-group 后代回收，必要私有宿主先入 Job 再启动命令。stdin 独立走执行权限，不能自动重放。 完成边界：短等待返回 running，后续有增量/退出码；原生 isatty、输入/EOF/resize 可测试；取消能解阻塞读并确认回收或报告 unknown。
- T09：成功 Turn 和导航保留活进程；取消/异常截停仅回收本 Turn 新进程，shutdown 全回收后关闭 writer。输出持续 drain 到有界 spool/ring，游标过期报告最早位置；终态日志按既有 ref 封口并正常淘汰记录。事件按 Session/process 单调序号路由，不伪造新 Turn。Desktop 缩略/折叠/续读、状态/退出码、安全 ANSI 文本与阅读位置保护；TUI 忽略新增进度。 完成边界：后台 Session 活进程不被闲置回收；已结束 Turn 日志可持续更新；跨 chunk Secret 不泄露，内存/磁盘有界；原生安装验收留 T19。

公共类型、会话内资产、异常截停及搜索秘密/受控进度的窄修订已被需求授权，不为同一决定重复询问。不得削减 15 项能力；不添加范围外服务、Runtime、兼容层或通用框架。普通工程选择自行完成；若新证据实质改变冻结范围，按规则记录并停止受影响范围。

共享 Core/配置/Bridge/工厂区域在当前 Worker 内保持单写者。可以委派无重叠且已授权的子任务，不自行执行未派发的后续 Worker，不为此建设全仓锁。首次派发后原始需求、Spec、Tasks、所有 Prompt 与 Checklist 文字冻结；仅可勾选已有完成框，Feedback 追加。禁止修改其他冻结工作包、Git commit/push/merge/rebase/tag/release 或归档。

## 验证与反馈

执行 Checklist 的 T07、T08、T09，覆盖 A09 A10 A11 A12 A14 A13 A15 A16。按真实改动运行最小定向测试；涉及架构边界执行 `python -m pytest tests/test_architecture_boundaries.py -q`。引用前序有效证据不等于跳过当前未覆盖条件。真实 Provider、Windows/POSIX PTY、安装产物和官方评分不得以 Mock/CDP 代替；缺条件保留未完成，继续其他独立授权工作。

首次实施创建 `docs/work/T11-Agent能力补齐/feedback/W03-文档视觉与进程会话-feedback.md`，之后只向同一文件追加返工轮次。记录实际改动、关键调用链与理由、文件、命令及精确结果、Checklist 项、差异、未验证项/风险/遗留问题和清理结果；不复制任务书、不新建 retry/v2 文件。中文文档 UTF-8 与围栏检查通过后交付。
