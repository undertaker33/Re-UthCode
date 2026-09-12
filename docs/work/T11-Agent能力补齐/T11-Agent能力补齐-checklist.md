# T11-Agent能力补齐 Checklist

状态：未实施；全部项目保持未勾选。Task 编号、名称及顺序与 Spec/Tasks 一致。

Python 命令在仓库根的 `re-uthcode` 环境执行，按下述路径使用 `python -m pytest <测试路径> -q`；Desktop 定向用例在 `desktop/` 用 `npx tsx --test <测试路径>`，类型检查用 `npm run typecheck`。所有新增测试在下文标为计划新增。单次证据可支撑多项，但必须记录命令、精确结果和对应 A 编号；不重复跑等价组合。

原需求 A01—A29 为本包验收合同。真实验收须记录具体平台、端点/模型/SDK 和结果，不记录秘密；无凭据、POSIX、Windows 安装或 Docker 条件时保留对应框，不影响独立工作，但整包不能宣称验收完成。

## T01 统一内容与正式输入

- [x] A01（R01/R06/R10，统一合同）：通过 `tests/test_provider_contract.py`、`test_tool_core.py`、`test_agent_events.py` 增补 验证；通过条件：文字/图片/文件/工具内容 round-trip；无原生对象/秘密进入公开投影；旧文本主链可用。证据记录于 W01 Feedback；前序有效实测可引用，尚未实测不得勾选。
- [x] 核对 Tasks T01 的完成边界并记录对应代码/定向证据：文字主链和新内容 round-trip 可运行；未实现的附件导入由 T04/T06 完成，不留 legacy 执行路径。

## T02 工具失败、副作用与进度合同

- [x] A08（R10/R11/R24）：通过 `tests/test_tool_result_persistence.py`、`test_agent_loop.py` 增补 验证；通过条件：写成功保存失败不重做；unknown 副作用截停；未执行批尾也有对应结果；普通工具错误返回模型继续处理。证据记录于 W01 Feedback；前序有效实测可引用，尚未实测不得勾选。
- [x] 核对 Tasks T02 的完成边界并记录对应代码/定向证据：写成功但保存失败不重复写；unknown 不纠偏重试；进度不写 RunState、不灌入模型历史；真实日志展示留 T09。

## T03 三协议图片序列化

- [x] A01（R01/R06/R10，统一合同）：通过 `tests/test_provider_contract.py`、`test_tool_core.py`、`test_agent_events.py` 增补 验证；通过条件：文字/图片/文件/工具内容 round-trip；无原生对象/秘密进入公开投影；旧文本主链可用。证据记录于 W01 Feedback；前序有效实测可引用，尚未实测不得勾选。
- [ ] A02（R03/R06，三协议真实入模）：通过 既有三个 Provider integration 测试 + 人工真实 Provider 验收 验证；通过条件：检查实际 SDK 请求并让模型分别回答用户图和工具图中的不同内容；记录具体模型/端点/SDK；不以只返回路径或 Mock 冒充通过。证据记录于 W01 Feedback；前序有效实测可引用，尚未实测不得勾选。
- [x] 核对 Tasks T03 的完成边界并记录对应代码/定向证据：三协议真实 SDK 请求结构可检验；实际 Provider 内容理解证据必须由 T19 补齐，不能在本 Task 只凭 Mock 勾选 A02。

## T04 会话原始附件与历史恢复

- [ ] A04（R02/R04）：通过 `tests/test_session_files.py`、`test_history_paging.py` 增补 验证；通过条件：源文件改变/删除后副本稳定；程序重开和历史分页仍可查看；无引用临时文件能清理，已提交原图不被缓存清除。证据记录于 W02 Feedback；前序有效实测可引用，尚未实测不得勾选。
- [ ] A07（R02/R04）：通过 `tests/test_session_authority.py` 增补及迁移样本 验证；通过条件：必要结构迁移保留既有文字 Session，重复打开无重复迁移/丢记录；不维持双写格式。证据记录于 W02 Feedback；前序有效实测可引用，尚未实测不得勾选。
- [ ] 核对 Tasks T04 的完成边界并记录对应代码/定向证据：删除源文件后已提交附件和图像仍能恢复；重发使用原副本；原图不会被缓存清除。

## T05 图片能力预检与 Context 压缩

- [ ] A05（R03）：通过 `tests/test_provider_model_limits.py`、`test_configuration.py` 增补 验证；通过条件：新图/历史图阻止不支持模型请求；切换失败保留旧模型/草稿；压缩退出当前请求后可使用文字模型，ViewImage 明确不可用。证据记录于 W02 Feedback；前序有效实测可引用，尚未实测不得勾选。
- [ ] A06（R04）：通过 `tests/test_context_compiler.py`、`test_context_budget_gate.py`、`test_context_compaction.py` 增补 验证；通过条件：图像有非零且有来源计量；真实请求 Gate；压缩后 ref 可再读，候选实际缩小、无静默丢图/多摘要复制。证据记录于 W02 Feedback；前序有效实测可引用，尚未实测不得勾选。
- [ ] 核对 Tasks T05 的完成边界并记录对应代码/定向证据：图片正常退出请求后可切文字模型；不得暗中删图或压缩以强行切换；256K 文字 profile 不重调。

## T06 Desktop 附件输入与回放

- [ ] A03（R01/R02）：通过 计划新增 `tests/test_attachments.py`；`desktop/tests/renderer-chat.test.tsx` / 新增附件交互用例 验证；通过条件：拖拽/选择/粘贴、仅附件发送、预览/移除、失败保留与重发；一个用户提交不产生重复 Turn。证据记录于 W02 Feedback；前序有效实测可引用，尚未实测不得勾选。
- [ ] A04（R02/R04）：通过 `tests/test_session_files.py`、`test_history_paging.py` 增补 验证；通过条件：源文件改变/删除后副本稳定；程序重开和历史分页仍可查看；无引用临时文件能清理，已提交原图不被缓存清除。证据记录于 W02 Feedback；前序有效实测可引用，尚未实测不得勾选。
- [ ] A05（R03）：通过 `tests/test_provider_model_limits.py`、`test_configuration.py` 增补 验证；通过条件：新图/历史图阻止不支持模型请求；切换失败保留旧模型/草稿；压缩退出当前请求后可使用文字模型，ViewImage 明确不可用。证据记录于 W02 Feedback；前序有效实测可引用，尚未实测不得勾选。
- [ ] 核对 Tasks T06 的完成边界并记录对应代码/定向证据：一个提交只有一个 Turn；切 Session 草稿归属正确；失败保留可编辑草稿；同一正式输入同时服务 Headless。

## T07 文档定位读取与工具图片

- [ ] A09（R05/R06）：通过 计划新增 `tests/test_document_tools.py`、`test_image_tools.py` 验证；通过条件：四种小型代表文件的页/段落/表/单元格/slide 定位正确；扫描 PDF 页图可读；损坏/加密/超限/取消受控；不宣称公式重算。证据记录于 W03 Feedback；前序有效实测可引用，尚未实测不得勾选。
- [ ] A10（R05/R06，实际打包依赖）：通过 Windows packaged 手动读取四格式与渲染 PDF 页 验证；通过条件：原生 PDF/图片依赖在安装产物可用，无开发机隐式依赖；当前视觉模型能收到渲染页。证据记录于 W03 Feedback；前序有效实测可引用，尚未实测不得勾选。
- [ ] 核对 Tasks T07 的完成边界并记录对应代码/定向证据：四格式、损坏/加密/超限/取消有定位和受控结果；不支持图片时明确不可用；安装产物实际读取由 T19 验证。

## T08 进程会话与原生 PTY

- [ ] A11（R12/R13/R25）：通过 `tests/test_builtin_process_tool.py` 增补；计划新增 `tests/test_process_sessions.py` 验证；通过条件：短等待返回 process_id/running；后续读到增量和退出码；等待无输出不被判死；不同 Session ID 控制被拒绝。证据记录于 W03 Feedback；前序有效实测可引用，尚未实测不得勾选。
- [ ] A12（R14）：通过 Windows + POSIX 定向 PTY 测试 验证；通过条件：子进程 isatty 为真、交互输入/EOF/resize 有效；PTY 单流标记准确，pipe 仍区分 stderr；输入不可自动重放。证据记录于 W03 Feedback；前序有效实测可引用，尚未实测不得勾选。
- [ ] A14（R11/R15）：通过 既有 descendant 终止用例扩展 PTY 验证；通过条件：timeout/cancel/异常截停后本 Turn 进程及后代不继续写 marker；此前 Turn 保留服务按规则存活；shutdown 全部回收；确认失败明确 unknown。证据记录于 W03 Feedback；前序有效实测可引用，尚未实测不得勾选。
- [ ] 核对 Tasks T08 的完成边界并记录对应代码/定向证据：短等待返回 running，后续有增量/退出码；原生 isatty、输入/EOF/resize 可测试；取消能解阻塞读并确认回收或报告 unknown。

## T09 进程生命周期与 Desktop 有界日志

- [ ] A13（R13/R15）：通过 `tests/test_desktop_bridge.py` / process 用例 验证；通过条件：Turn 完成后服务仍在；会话导航不关闭；新 Turn 能读取/停止；显式关闭后无法再控制旧句柄。证据记录于 W03 Feedback；前序有效实测可引用，尚未实测不得勾选。
- [ ] A14（R11/R15）：通过 既有 descendant 终止用例扩展 PTY 验证；通过条件：timeout/cancel/异常截停后本 Turn 进程及后代不继续写 marker；此前 Turn 保留服务按规则存活；shutdown 全部回收；确认失败明确 unknown。证据记录于 W03 Feedback；前序有效实测可引用，尚未实测不得勾选。
- [ ] A15（R14—R16，Windows 实机）：通过 标准 `npm run package` / `npm run make`（依现有 scripts）后人工操作 验证；通过条件：安装产物中 PTY、中文/ANSI 日志、stdin、停止和关闭有效；不是 CDP 布局测试代替原生进程验证。证据记录于 W03 Feedback；前序有效实测可引用，尚未实测不得勾选。
- [ ] A16（R16/R17）：通过 Desktop renderer state/chat/session 测试；受控高频日志样本 验证；通过条件：卡片缩略/折叠/分页、后台归属、阅读位置正确；内存有界；跨 chunk Secret 不泄漏；TUI 忽略进度仍能结束。证据记录于 W03 Feedback；前序有效实测可引用，尚未实测不得勾选。
- [ ] 核对 Tasks T09 的完成边界并记录对应代码/定向证据：后台 Session 活进程不被闲置回收；已结束 Turn 日志可持续更新；跨 chunk Secret 不泄露，内存/磁盘有界；原生安装验收留 T19。

## T10 搜索、抓取与可信搜索配置

- [ ] A17（R07/R08/R20）：通过 计划新增 `tests/test_web_tools.py`；配置相关测试 验证；通过条件：无配置/认证/限额/429/取消有分类；Key 不进入事件/trace；项目 search 凭据/重定向硬失败；不自动升级收费模式。证据记录于 W04 Feedback；前序有效实测可引用，尚未实测不得勾选。
- [ ] A18（R07/R09）：通过 实际 Tavily 查询→Fetch 一个公开静态页与 PDF；本地 HTTP fixture 测失败 验证；通过条件：有真实 URL/来源/用量和后续正文读取；重定向、正文超限、登录/动态页限制准确；取消关闭读取；不记录凭据。证据记录于 W04 Feedback；前序有效实测可引用，尚未实测不得勾选。
- [ ] A23（R20）：通过 `tests/test_config_contract.py`、`test_config_loader_integration.py`、`test_configuration.py`；Desktop settings 用例 验证；通过条件：搜索/模型能力/工具配置保存/校验/来源正确；后台 active Turn 也受快照保护；存活进程不因保存重启。证据记录于 W04 Feedback；前序有效实测可引用，尚未实测不得勾选。
- [ ] 核对 Tasks T10 的完成边界并记录对应代码/定向证据：正式配置到工具集合按 Turn 快照；来源可继续读取；不发会话全文、不带浏览器 Cookie、不启动浏览器；真实服务调用由 T19 验证。

## T11 ApplyPatch 预检与部分提交

- [ ] A19（R18/R28）：通过 计划新增 `tests/test_patch_tool.py`；现有 file tool 测试 验证；通过条件：增删改/移动；未读、变化、重复 hunk/目标冲突预检零改动；提交失败 changed/failed/not_applied 与磁盘一致。证据记录于 W04 Feedback；前序有效实测可引用，尚未实测不得勾选。
- [ ] 核对 Tasks T11 的完成边界并记录对应代码/定向证据：增删改移动、重复 hunk、未读/变化/目标冲突及提交中失败结果与磁盘一致；未知副作用走 T02 停止链。

## T12 Git 工作区只读查询

- [ ] A20（R19）：通过 计划新增 `tests/test_git_tools.py`，使用临时 Git repo 验证；通过条件：status/diff/log/show/branch、未跟踪、detached/unborn/非 Git、特殊文件名准确；查询无仓库写和外部 diff 程序执行。证据记录于 W04 Feedback；前序有效实测可引用，尚未实测不得勾选。
- [ ] 核对 Tasks T12 的完成边界并记录对应代码/定向证据：查询没有仓库写、联网或外部 diff 程序执行；缺 Git 返回 unavailable，不自动安装。

## T13 Glob/Grep 有界检索与续读

- [ ] A21（R26）：通过 `tests/test_builtin_search_tools.py` 增补 验证；通过条件：忽略/隐藏/二进制/敏感路径/链接权限、分页、正则超时；大结果先限量而非全部加载后截断；续读条件不串查询。证据记录于 W04 Feedback；前序有效实测可引用，尚未实测不得勾选。
- [ ] 核对 Tasks T13 的完成边界并记录对应代码/定向证据：忽略/隐藏/超时/分页/变化与权限回归可观测；不承诺全局检索快照，不引入必须分发的 rg。

## T14 异常纠偏与截停替代固定上限

- [ ] A08（R10/R11/R24）：通过 `tests/test_tool_result_persistence.py`、`test_agent_loop.py` 增补 验证；通过条件：写成功保存失败不重做；unknown 副作用截停；未执行批尾也有对应结果；普通工具错误返回模型继续处理。证据记录于 W05 Feedback；前序有效实测可引用，尚未实测不得勾选。
- [ ] A22（R22—R25）：通过 `tests/test_agent_loop.py`、`test_agent_policy.py`；计划新增 `tests/test_runaway_detection.py` 验证；通过条件：正常脚本 Provider 连续至少 200 轮仍能完成；相同失败/短周期/完成阻断先纠偏后停止；编辑后重测、合法等待和人工重试不误停；无累计轮数 fallback。证据记录于 W05 Feedback；前序有效实测可引用，尚未实测不得勾选。
- [ ] 核对 Tasks T14 的完成边界并记录对应代码/定向证据：脚本 Provider 至少 200 轮正常完成；失败/短周期/final 阻断正例、编辑重测/等待/人工输入反例通过；终态 runaway_detected 与取消区分。

## T15 Settings 配置完整性与生效边界

- [ ] A23（R20）：通过 `tests/test_config_contract.py`、`test_config_loader_integration.py`、`test_configuration.py`；Desktop settings 用例 验证；通过条件：搜索/模型能力/工具配置保存/校验/来源正确；后台 active Turn 也受快照保护；存活进程不因保存重启。证据记录于 W05 Feedback；前序有效实测可引用，尚未实测不得勾选。
- [ ] 核对 Tasks T15 的完成边界并记录对应代码/定向证据：用户/项目作用域和拒绝路径可测试；项目不能放宽限制；保存不半途换模型/端点或重启存活进程。

## T16 Desktop 产物打开与受控预览

- [ ] A24（R27）：通过 Desktop Main/preload/chat 定向用例 + 人工点开产物 验证；通过条件：已授权文件可打开/定位、图片可看；缺失文件局部报错；可执行文件默认定位；恶意 URI 不执行命令。证据记录于 W05 Feedback；前序有效实测可引用，尚未实测不得勾选。
- [ ] 核对 Tasks T16 的完成边界并记录对应代码/定向证据：授权文件打开定位和图片预览可用；恶意 URI 不执行命令；保持 Renderer 无任意 fs/shell。

## T17 SWE-bench 预测与安全 Trace

- [ ] A25（R21）：通过 计划新增 `tests/eval/test_swebench_adapter.py` 验证；通过条件：预测三字段和实际 diff、新文件正确；实例隔离，trace 不含秘密/图像字节/原生载荷；不获取 gold patch。证据记录于 W06 Feedback；前序有效实测可引用，尚未实测不得勾选。
- [ ] A26（R21，外部可消费）：通过 一条真实 SWE-bench Lite 实例，经正式 Headless；官方 `python -m swebench.harness.run_evaluation --dataset_name princeton-nlp/SWE-bench_Lite --predictions_path <预测文件> --instance_ids <实际实例> --run_id <新运行标识>` 验证；通过条件：生成预测并由官方 harness 完成评分，记录 resolved 与失败原因；不要求单例必解，不把评分环境缺失当成功。证据记录于 W06 Feedback；前序有效实测可引用，尚未实测不得勾选。
- [ ] 核对 Tasks T17 的完成边界并记录对应代码/定向证据：可导出官方可消费 JSONL；实际 harness 评分放 T19，resolved=false 如实报告，不要求必解。

## T18 [接入主流程]

- [ ] A27（四层边界与主链）：通过 `python -m pytest tests/test_architecture_boundaries.py tests/test_application.py tests/test_application_runs.py -q`，加上述受影响定向测试 验证；通过条件：所有新增工具从 Application/headless 可达；Core 无 SDK/OS/UI 依赖；无 Renderer 直连新工具。证据记录于 W06 Feedback；前序有效实测可引用，尚未实测不得勾选。
- [ ] 核对 Tasks T18 的完成边界并记录对应代码/定向证据：架构与 Application 定向验收通过，能力追踪无空项；只修前序范围内接缝。

## T19 [端到端验证]

- [ ] A02（R03/R06，三协议真实入模）：通过 既有三个 Provider integration 测试 + 人工真实 Provider 验收 验证；通过条件：检查实际 SDK 请求并让模型分别回答用户图和工具图中的不同内容；记录具体模型/端点/SDK；不以只返回路径或 Mock 冒充通过。证据记录于 W06 Feedback；前序有效实测可引用，尚未实测不得勾选。
- [ ] A10（R05/R06，实际打包依赖）：通过 Windows packaged 手动读取四格式与渲染 PDF 页 验证；通过条件：原生 PDF/图片依赖在安装产物可用，无开发机隐式依赖；当前视觉模型能收到渲染页。证据记录于 W06 Feedback；前序有效实测可引用，尚未实测不得勾选。
- [ ] A12（R14）：通过 Windows + POSIX 定向 PTY 测试 验证；通过条件：子进程 isatty 为真、交互输入/EOF/resize 有效；PTY 单流标记准确，pipe 仍区分 stderr；输入不可自动重放。证据记录于 W06 Feedback；前序有效实测可引用，尚未实测不得勾选。
- [ ] A15（R14—R16，Windows 实机）：通过 标准 `npm run package` / `npm run make`（依现有 scripts）后人工操作 验证；通过条件：安装产物中 PTY、中文/ANSI 日志、stdin、停止和关闭有效；不是 CDP 布局测试代替原生进程验证。证据记录于 W06 Feedback；前序有效实测可引用，尚未实测不得勾选。
- [ ] A18（R07/R09）：通过 实际 Tavily 查询→Fetch 一个公开静态页与 PDF；本地 HTTP fixture 测失败 验证；通过条件：有真实 URL/来源/用量和后续正文读取；重定向、正文超限、登录/动态页限制准确；取消关闭读取；不记录凭据。证据记录于 W06 Feedback；前序有效实测可引用，尚未实测不得勾选。
- [ ] A26（R21，外部可消费）：通过 一条真实 SWE-bench Lite 实例，经正式 Headless；官方 `python -m swebench.harness.run_evaluation --dataset_name princeton-nlp/SWE-bench_Lite --predictions_path <预测文件> --instance_ids <实际实例> --run_id <新运行标识>` 验证；通过条件：生成预测并由官方 harness 完成评分，记录 resolved 与失败原因；不要求单例必解，不把评分环境缺失当成功。证据记录于 W06 Feedback；前序有效实测可引用，尚未实测不得勾选。
- [ ] A28（R28，联合真实端到端）：通过 Windows Desktop 输入截图+文档→Agent 定位并 Patch→运行失败测试→读日志修复→重跑→查看图片→点击交付物 验证；通过条件：每个观察与修改来自正式工具结果，Desktop 可折叠日志并打开产物；需要模型理解的步骤有真实 Provider 证据。证据记录于 W06 Feedback；前序有效实测可引用，尚未实测不得勾选。
- [ ] 核对 Tasks T19 的完成边界并记录对应代码/定向证据：记录端点/模型/SDK、安全命令和精确结果。缺凭据/平台/Docker 只保留对应未完成项，不能用 Mock、CDP 布局或评分环境缺失冒充完成；有效已有证据可复用。

## T20 [遗留负担清理]

- [ ] A29（文档与清理）：通过 定向搜索旧 max_iterations 执行 gate/旧结果路径；`npm run typecheck` 与相关 Desktop 测试；文档 UTF-8/fence/链接检查 验证；通过条件：无活动固定轮数上限、无旧协议双轨；全部必需文档/索引/欠账核对完成，历史记录不被当作需删除的运行逻辑。证据记录于 W06 Feedback；前序有效实测可引用，尚未实测不得勾选。
- [ ] 核对 Tasks T20 的完成边界并记录对应代码/定向证据：必要验证后停止；不新增兼容层/全局框架，不提交、不归档；所有必需验收仍未完成时如实报告，不能提前宣称整包完成。
