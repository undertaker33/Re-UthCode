# W04-联网取证与代码操作

只有用户显式指定本文件执行时才开始实施。你负责 T10 搜索、抓取与可信搜索配置 → T11 ApplyPatch 预检与部分提交 → T12 Git 工作区只读查询 → T13 Glob/Grep 有界检索与续读，必须严格按此顺序完成，不执行其他 Worker 的 Task。

## 必读与前置

1. 仓库根 `AGENTS.md`、`docs/README.md`、`docs/Context-Index.md`、`docs/rules/WorkPackageRules.md`；涉及新增决策时读 `docs/rules/UserDecisionBoundary.md`，涉及后置边界读 `docs/OutstandingDebtList.md`。
2. 完整读取 `docs/work/T11-Agent能力补齐/T11-Agent能力补齐.md`、`T11-Agent能力补齐-spec.md`、`T11-Agent能力补齐-tasks.md`、`T11-Agent能力补齐-checklist.md`（后三者在同一目录）。不依赖聊天记录；原需求第3节九项决定与第4节协议均已授权。
3. 按本 Worker 命中职责读取 `docs/context/A01-AgentRuntime/AgentRuntime-Context.md`、`A02-Control/Control-Context.md`、`A03-State/State-Context.md`、`A04-Orchestration/Orchestration-Context.md`（后三者相对 `docs/context/`），涉及 Desktop 时读 `docs/context/GUI/GUI-Context.md`。只沿任务读取源码，不扫描归档全库。
4. 先读 `docs/work/T11-Agent能力补齐/feedback/W03-文档视觉与进程会话-feedback.md`，再按实际依赖读更早 Feedback；缺失前置只停止依赖范围，不虚构已实现合同。
5. 使用既有 `re-uthcode` Conda 环境；Python 与新依赖范围以 `pyproject.toml` 为准；不另建环境或构建体系。

## 修改范围与源码入口

本 Worker 写范围为 Tasks 的 T10、T11、T12、T13 对应文件组 F12 F16 F17 F21 F23 F25 F13 F14 F15、其真实调用点和 Checklist 指定测试；涉及文档只按当前已实现能力同步维护。下面路径来自原始需求文件组，其中新增路径尚不存在，禁止因表列就建占位文件：

- F12：新增 `src/uthcode/integrations/tools/web_tools.py`；Tavily Search、HTTP Fetch、本地正文提取、分页与错误。
- F16：`src/uthcode/integrations/tools/factory.py`、`application/bootstrap.py`；在正式启动时组合新能力、按配置/模型暴露可用工具、绑定会话资源。
- F17：`src/uthcode/application/configuration.py`、`integrations/config/loader.py`、`writer.py`；search/vision/tool limits 配置、用户与项目边界、秘密写入脱敏。
- F21：`desktop/src/renderer/SettingsView.tsx`、`SettingsEditorModal.tsx`、`settings-draft.ts`、`locales/{zh-CN,en}.ts`；搜索与图片能力配置、资源项、活动态禁用/生效提示，中英文本。
- F23：`pyproject.toml`、`desktop/packaging/uthcode-runtime.spec`；依赖声明、平台 marker 与 Python 原生资源打包。
- F25：`AGENTS.md` 和第 9 节文档；用户已批准的搜索秘密/事件正文边界、运行上限修订及使用说明。
- F13：`src/uthcode/integrations/tools/file_tools.py`、`workspace.py`；新增 `patch_tools.py`；ApplyPatch 方言、目标集合权限、先读后写、预检/提交结果。
- F14：新增 `src/uthcode/integrations/tools/git_tools.py`；GitWorkspace 只读查询和 NUL/受控 argv 处理。
- F15：`src/uthcode/integrations/tools/search_tools.py`、`tool_result_read.py`；分页迭代、忽略规则、二进制、正则时间限制、续读。

必须同时读取 Tasks 的“本地核验补充”和“官方参考核验”；其中补齐的实际路径按所属 F 组属于本 Worker 的范围。

## 已确认决定与执行约束

- T10：独立 Tavily Search 固定官方端点/basic/include_answer=false；用户 search.api_key 转 SecretValue，项目禁止任何凭据/重定向且不可自动启用。同步 AGENTS 搜索秘密窄修订。HTTPX 显式逐跳有界抓取，重定向按实际 URL 重新权限决策；Trafilatura 只处理已下载内容；PDF 复用 T07。未配置时不可用，429/额度/取消分类与用量明确，不自动升级收费模式。 完成边界：正式配置到工具集合按 Turn 快照；来源可继续读取；不发会话全文、不带浏览器 Cookie、不启动浏览器；真实服务调用由 T19 验证。
- T11：新增 Codex 文本 Patch 方言，复用 resolver/FileReadTracker/PermissionAction。全量语法、目标冲突、读取事实、变化与授权预检；失败零变更。按目标顺序单文件原子替换，提交前再次核对；移动两路径分别记录 applied/failed/not_applied。更新读事实，保留有独立用途的 EditFile，不建立全仓事务或自动回滚。 完成边界：增删改移动、重复 hunk、未读/变化/目标冲突及提交中失败结果与磁盘一致；未知副作用走 T02 停止链。
- T12：新增 GitWorkspace 的 status/diff/log/show/branch；argv、NUL porcelain、有界输出；禁 external diff/textconv 及可选索引写，不 fetch。处理非 Git、缺 Git、detached/unborn、未跟踪与特殊文件名。使用临时 repo 验证，绝不对用户工作区做测试写入。 完成边界：查询没有仓库写、联网或外部 diff 程序执行；缺 Git 返回 unavailable，不自动安装。
- T13：保留名称和正则合同；pathspec GitIgnoreSpec 按目录继承 .gitignore/.ignore，明确 hidden/ignored，跳过二进制。用既有 regex 超时；先限制遍历/输出再分页，不全量汇集。续读绑定查询条件且新候选继续走敏感/外部/symlink 权限前置；复用 ToolResultRead，防止递归物化。 完成边界：忽略/隐藏/超时/分页/变化与权限回归可观测；不承诺全局检索快照，不引入必须分发的 rg。

公共类型、会话内资产、异常截停及搜索秘密/受控进度的窄修订已被需求授权，不为同一决定重复询问。不得削减 15 项能力；不添加范围外服务、Runtime、兼容层或通用框架。普通工程选择自行完成；若新证据实质改变冻结范围，按规则记录并停止受影响范围。

共享 Core/配置/Bridge/工厂区域在当前 Worker 内保持单写者。可以委派无重叠且已授权的子任务，不自行执行未派发的后续 Worker，不为此建设全仓锁。首次派发后原始需求、Spec、Tasks、所有 Prompt 与 Checklist 文字冻结；仅可勾选已有完成框，Feedback 追加。禁止修改其他冻结工作包、Git commit/push/merge/rebase/tag/release 或归档。

## 验证与反馈

执行 Checklist 的 T10、T11、T12、T13，覆盖 A17 A18 A23 A19 A20 A21。按真实改动运行最小定向测试；涉及架构边界执行 `python -m pytest tests/test_architecture_boundaries.py -q`。引用前序有效证据不等于跳过当前未覆盖条件。真实 Provider、Windows/POSIX PTY、安装产物和官方评分不得以 Mock/CDP 代替；缺条件保留未完成，继续其他独立授权工作。

首次实施创建 `docs/work/T11-Agent能力补齐/feedback/W04-联网取证与代码操作-feedback.md`，之后只向同一文件追加返工轮次。记录实际改动、关键调用链与理由、文件、命令及精确结果、Checklist 项、差异、未验证项/风险/遗留问题和清理结果；不复制任务书、不新建 retry/v2 文件。中文文档 UTF-8 与围栏检查通过后交付。
