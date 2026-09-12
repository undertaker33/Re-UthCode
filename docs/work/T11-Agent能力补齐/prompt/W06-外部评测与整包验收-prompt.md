# W06-外部评测与整包验收

只有用户显式指定本文件执行时才开始实施。你负责 T17 SWE-bench 预测与安全 Trace → T18 [接入主流程] → T19 [端到端验证] → T20 [遗留负担清理]，必须严格按此顺序完成，不执行其他 Worker 的 Task。

## 必读与前置

1. 仓库根 `AGENTS.md`、`docs/README.md`、`docs/Context-Index.md`、`docs/rules/WorkPackageRules.md`；涉及新增决策时读 `docs/rules/UserDecisionBoundary.md`，涉及后置边界读 `docs/OutstandingDebtList.md`。
2. 完整读取 `docs/work/T11-Agent能力补齐/T11-Agent能力补齐.md`、`T11-Agent能力补齐-spec.md`、`T11-Agent能力补齐-tasks.md`、`T11-Agent能力补齐-checklist.md`（后三者在同一目录）。不依赖聊天记录；原需求第3节九项决定与第4节协议均已授权。
3. 按本 Worker 命中职责读取 `docs/context/A01-AgentRuntime/AgentRuntime-Context.md`、`A02-Control/Control-Context.md`、`A03-State/State-Context.md`、`A04-Orchestration/Orchestration-Context.md`（后三者相对 `docs/context/`），涉及 Desktop 时读 `docs/context/GUI/GUI-Context.md`。只沿任务读取源码，不扫描归档全库。
4. 先读 `docs/work/T11-Agent能力补齐/feedback/W05-异常截停与Desktop收口-feedback.md`，再按实际依赖读更早 Feedback；缺失前置只停止依赖范围，不虚构已实现合同。
5. 使用既有 `re-uthcode` Conda 环境；Python 与新依赖范围以 `pyproject.toml` 为准；不另建环境或构建体系。

## 修改范围与源码入口

本 Worker 写范围为 Tasks 的 T17、T18、T19、T20 对应文件组 F22 F24 F25 F16 F18 F23、其真实调用点和 Checklist 指定测试；涉及文档只按当前已实现能力同步维护。下面路径来自原始需求文件组，其中新增路径尚不存在，禁止因表列就建占位文件：

- F22：`eval/execution.py`；新增 `eval/swebench.py`；薄适配、预测输出、新文件 diff、trace 扩展与外部评分示例。
- F24：`tests/` 与 `desktop/tests/` 第 8 节指定位置；最小合同/回归/端到端正反例；替换旧 max_iterations 和字符串-only 断言。
- F25：`AGENTS.md` 和第 9 节文档；用户已批准的搜索秘密/事件正文边界、运行上限修订及使用说明。
- F16：`src/uthcode/integrations/tools/factory.py`、`application/bootstrap.py`；在正式启动时组合新能力、按配置/模型暴露可用工具、绑定会话资源。
- F18：`src/uthcode/interfaces/desktop/bridge.py`、`protocol.py`；`desktop/src/desktop-api.ts`；附件、预览、进程查询/停止/日志、安全产物 DTO；background 资源保留。
- F23：`pyproject.toml`、`desktop/packaging/uthcode-runtime.spec`；依赖声明、平台 marker 与 Python 原生资源打包。

必须同时读取 Tasks 的“本地核验补充”和“官方参考核验”；其中补齐的实际路径按所属 F 组属于本 Worker 的范围。

## 已确认决定与执行约束

- T17：新增 eval/swebench.py 薄适配，复用 eval/execution.py 的正式 Headless Application；输入外部实例工作目录/题面/模型引用，不读 gold patch。预测三字段 instance_id/model_name_or_path/model_patch 取实际基线 diff，含新文件；实例隔离，trace 排除秘密/图片字节/原生载荷。官方评分依赖不加入产品，适配样本与运行说明入 eval/README。 完成边界：可导出官方可消费 JSONL；实际 harness 评分放 T19，resolved=false 如实报告，不要求必解。
- T18：逐项核对原始 1—15 能力及横向链路在 Application/headless/Desktop 正式入口可达；复用前序真实接入，不另造演示程序。移除替代入口与 UI 直连；检查工具可见性、权限、配置、关闭、历史同链。 完成边界：架构与 Application 定向验收通过，能力追踪无空项；只修前序范围内接缝。
- T19：在标准 Windows package/make 产物验证附件、四格式/PDF 页图、真实 PTY/后代/中文 ANSI 日志/stdin/停止/关闭；三协议分别验证用户图片及工具图片的不同内容。真实 Tavily 后 Fetch 静态页与 PDF；正式 Headless 输出一条 SWE-bench Lite 预测并由官方 harness 完成评分；联合截图+文档→Patch→失败测试→读日志修复→重跑→查看图→点击产物。 完成边界：记录端点/模型/SDK、安全命令和精确结果。缺凭据/平台/Docker 只保留对应未完成项，不能用 Mock、CDP 布局或评分环境缺失冒充完成；有效已有证据可复用。
- T20：清理旧累计上限、字符串唯一结果假设、communicate-only 重复链、不可达/演示入口、失效文案和依赖；历史失败事实不删，冻结包不改。按需求第9节及 docs/README 维护映射同步全部相关用户文档、四层/GUI 当前事实、既有核心教程、Tools、eval/README、欠账和全量索引。 完成边界：必要验证后停止；不新增兼容层/全局框架，不提交、不归档；所有必需验收仍未完成时如实报告，不能提前宣称整包完成。

公共类型、会话内资产、异常截停及搜索秘密/受控进度的窄修订已被需求授权，不为同一决定重复询问。不得削减 15 项能力；不添加范围外服务、Runtime、兼容层或通用框架。普通工程选择自行完成；若新证据实质改变冻结范围，按规则记录并停止受影响范围。

共享 Core/配置/Bridge/工厂区域在当前 Worker 内保持单写者。可以委派无重叠且已授权的子任务，不自行执行未派发的后续 Worker，不为此建设全仓锁。首次派发后原始需求、Spec、Tasks、所有 Prompt 与 Checklist 文字冻结；仅可勾选已有完成框，Feedback 追加。禁止修改其他冻结工作包、Git commit/push/merge/rebase/tag/release 或归档。

## 验证与反馈

执行 Checklist 的 T17、T18、T19、T20，覆盖 A25 A26 A27 A02 A10 A12 A15 A18 A28 A29。按真实改动运行最小定向测试；涉及架构边界执行 `python -m pytest tests/test_architecture_boundaries.py -q`。引用前序有效证据不等于跳过当前未覆盖条件。真实 Provider、Windows/POSIX PTY、安装产物和官方评分不得以 Mock/CDP 代替；缺条件保留未完成，继续其他独立授权工作。

首次实施创建 `docs/work/T11-Agent能力补齐/feedback/W06-外部评测与整包验收-feedback.md`，之后只向同一文件追加返工轮次。记录实际改动、关键调用链与理由、文件、命令及精确结果、Checklist 项、差异、未验证项/风险/遗留问题和清理结果；不复制任务书、不新建 retry/v2 文件。中文文档 UTF-8 与围栏检查通过后交付。
