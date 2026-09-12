# T11-Agent能力补齐 Tasks

## 长期 Worker 分组与依赖

状态：待审核、未派发。每个 Worker 严格串行执行其 Task，不按单 Task 派发新 Worker。

| Worker | 严格执行顺序 | 前置交付 |
| --- | --- | --- |
| W01-内容与结果公共合同 | T01 → T02 → T03 | 本地基线核验 |
| W02-会话附件与Context | T04 → T05 → T06 | W01 合同与实现交付；核对其 Feedback，未完成相关前置时不得臆造 |
| W03-文档视觉与进程会话 | T07 → T08 → T09 | W02 合同与实现交付；核对其 Feedback，未完成相关前置时不得臆造 |
| W04-联网取证与代码操作 | T10 → T11 → T12 → T13 | W03 合同与实现交付；核对其 Feedback，未完成相关前置时不得臆造 |
| W05-异常截停与Desktop收口 | T14 → T15 → T16 | W04 合同与实现交付；核对其 Feedback，未完成相关前置时不得臆造 |
| W06-外部评测与整包验收 | T17 → T18 → T19 → T20 | W05 合同与实现交付；核对其 Feedback，未完成相关前置时不得臆造 |

Core/配置/Bridge/工厂/打包清单在多个阶段被修改，因此以上 Worker 按依赖交接；这不是仓库全局锁。Worker 内可委派无共享写集合的只读核验或定向测试，但共享区域单写者，不自行执行未派发的后续 Worker。后续 Worker 可使用前序有效证据；尚未具备真实外部条件不阻断不依赖它的工程工作，也不得勾选对应实测项。

任务头编号、名称和顺序与 Spec/Checklist 完全一致。下列 F 编号引用本文件末尾的实际文件组；A 编号引用 Checklist 和原始需求第 8 节。所有范围均含对应现有测试，新增测试明确标为计划新增。

## 本地证据与实施前提

- 2026-09-12 只读核验：HEAD 为 `fa6b5b30f02fe7b5ce22f128b99f214ee90ba732`，与原需求基线相同；开始时只有原始需求未跟踪，无产品修改。
- `conda run --no-capture-output -n re-uthcode python --version`：Python 3.12.13。正常使用 `conda activate re-uthcode`；Shell 未初始化时使用该等价运行方式，不另建环境。
- `pyproject.toml` 是依赖权威；本次文档阶段不安装新依赖，不运行产品测试，不把外部网页核对写成 Windows wheel/打包验证。
- 在既有 Conda 环境只读导入 SDK 类型成功（exit 0）：安装版 `openai 2.53.0`、`anthropic 0.120.2`；Responses 的 `FunctionCallOutput.output` 声明为字符串或内容项列表，Anthropic 的 `ToolResultBlockParam.content` 为字符串或内容序列。该检查只证明当前类型入口存在，不等于请求序列化或真实图片理解验收通过。
- 当前 Desktop scripts 为 `npm run typecheck`、`npm test`、`npm run package`、`npm run make`，在 `desktop/` 执行。package/make 会调用现有 runtime 构建。
- 源码仍有文字唯一内容、累计轮数 gate、communicate-only Bash；本地核验补充见下方。原始需求提及的探索提示词/模板/用户讨论不是已提供本地文件，本包只采用需求正文中已收敛决定，不声称读过缺失来源。

## 本地核验补充（2026-09-12）

核对当前源码与路由后，未发现需要重新打开九项产品决定的基线变化。以下是实施必须覆盖的现有入口，属于原范围内的路径补齐，不是新增产品能力：

| 位置 | 当前证据及实施归属 |
| --- | --- |
| `src/uthcode/core/provider.py`、`core/tool.py` | `MessagePart` 无图片，`ToolResultPart`、`ToolExecutionResult`、`ToolExecutionOutcome` 均为字符串内容。T01/T02 必须一起迁移真实调用与编码假设；保留原有文本会话可读，结构必要迁移由 T04 收口，不能交付打不开既有文本会话的中间版本。 |
| `src/uthcode/core/agent.py` | 默认上限及普通循环、continuation 两处累计检查仍存在；T14 同时替换，不只删配置字段。 |
| `src/uthcode/application/compaction.py` | 摘要请求和候选提交编排已存在，纳入 F06/T05 范围；不只改 Core compiler。 |
| `src/uthcode/application/configuration.py`、`src/uthcode/integrations/config/data.py`、`loader.py`、`writer.py`、`template.py` | 配置公共模型、安全读取、允许字段、写入和模板分散在这些真实文件（后三者同目录），纳入 F17/T05/T10/T15；不存在需新建的 `config_contract.py` 源文件。 |
| `src/uthcode/integrations/tools/process_tools.py` | `_start_process` 已在 Windows 以挂起状态创建 Shell，加入 Job 后恢复；T08 优先复用该归属逻辑和已有后代测试。当前 `communicate()` 及默认总超时由 T08/T09 替换。 |
| `src/uthcode/interfaces/desktop/bridge.py` | `turn.start` 只接受 `prompt`；已有后台运行时与部分跨会话活动检查。T06 扩展输入，T09 扩展活进程保留，T15 核对所有保存/Compact 分支，不能仅凭现有一个 guard 推断已经完整。 |
| `desktop/src/renderer/state.ts`、`state-session.ts`、`state-normalization.ts`、`useRuntimeLifecycle.ts`、`App.tsx` | 上述文件均位于 `desktop/src/renderer/`，纳入 F20：保留 reducer 与 lifecycle 现有唯一所有权。 |
| `src/uthcode/integrations/tools/search_tools.py` | 当前预检候选与命中以列表汇集，使用 Python `re`；T13 使用已经在 pyproject 声明的 `regex` 提供超时，不应误写成当前 Grep 已有超时。 |
| `eval/execution.py` | `run_attempt` 默认复用 `create_application`，已有安全 artifact 和 workspace 差异；T17 复用正式链，新增官方 patch 格式，不把现有变化文件清单当 unified diff。 |

上述补充按所属 F 组纳入相应 Worker 必读/写范围。每次移交以已实现合同、定向证据和明确未完成实测为依据，不要求前序 Worker 等待 T19 才交接；但对应完整 A 项只有全部条件满足才可勾选，T19 负责汇总补齐，必要时由用户向原 Worker 派发返工。没有任何 Worker 实施结果在本次文档阶段产生，feedback 目录保持空。

## 官方参考核验（2026-09-12）

以下是网页与协议级核对，不是安装、原生资源打包、真实 Provider 或收费服务测试；实施时仍须核对实际安装版本并完成 Checklist。未对维护状况、全部许可证或 Windows wheel 组合给出未经验证的结论。

| 参考 | 本次确认与实施限制 |
| --- | --- |
| [OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling)、[Vision](https://developers.openai.com/api/docs/guides/images-vision) | Responses 工具输出可用图片/文件对象数组；用户图片有 `input_image` 路径。T03 核对安装 SDK，T19 实测模型理解；不外推到所有 compatible 服务。 |
| [Claude Vision](https://platform.claude.com/docs/en/build-with-claude/vision)、[PDF](https://platform.claude.com/docs/en/build-with-claude/pdf-support) | 官方提供图像内容及 PDF 支持说明；本包仍按已确认本地解析/页图设计，不引入 Files API 生命周期。工具结果 schema 同时核对实际 Anthropic SDK。 |
| [Codex view_image](https://github.com/openai/codex/blob/53ff712a48379ce8df605e292afd6046ca88ae9b/codex-rs/core/src/tools/handlers/view_image.rs)、[unified_exec](https://github.com/openai/codex/blob/53ff712a48379ce8df605e292afd6046ca88ae9b/codex-rs/core/src/tools/handlers/unified_exec.rs)、[apply-patch](https://github.com/openai/codex/blob/53ff712a48379ce8df605e292afd6046ca88ae9b/codex-rs/apply-patch/src/lib.rs) | 三个固定提交路径可访问；有限等待参数和 Begin/End Patch 文本入口可定位。只参考机制，权限、回收与提交原子性以 UthCode 需求为准。 |
| [pywinpty](https://github.com/andfoy/pywinpty)、[ConPTY](https://learn.microsoft.com/en-us/windows/console/creating-a-pseudoconsole-session)、[ptyprocess](https://ptyprocess.readthedocs.io/en/latest/) | 提供 PTY 进程与读写接口；ConPTY 关闭期间仍需 drain，错误句柄/同步 I/O 生命周期可死锁。Python 3.12/Windows wheel、Job 后代回收及打包实际行为留 T08/T19。 |
| [pypdfium2](https://pypdfium2.readthedocs.io/en/stable/python_api.html)、[Pillow](https://pillow.readthedocs.io/en/stable/reference/Image.html) | PDFium 明确禁止跨线程同时调用（不同文档也不例外）；图像解码和页图转换留 Integration，不用普通线程取消假装中断原生解析。 |
| [python-docx](https://python-docx.readthedocs.io/en/latest/api/document.html)、[openpyxl](https://openpyxl.readthedocs.io/en/stable/optimized.html)、[python-pptx](https://python-pptx.readthedocs.io/en/latest/user/text.html) | DOCX 有顺序段落/表格迭代；XLSX read-only 延迟读取须显式关闭；PPTX 有文本框/段落接口。稳定导航和限制仍需四格式 fixture 验证。 |
| [MarkItDown](https://github.com/microsoft/markitdown)、[ripgrep](https://github.com/BurntSushi/ripgrep) | 官方仓库可访问；只作需求已有选型的参考，不添加整文转换层或必须分发的 rg。 |
| [Tavily Search](https://docs.tavily.com/documentation/api-reference/endpoint/search)、[Credits](https://docs.tavily.com/documentation/api-credits) | API 含 `auto_parameters`、`include_usage` 与 `usage.credits`。T10 显式 `search_depth=basic`、`auto_parameters=false`、`include_answer=false`、`include_usage=true`，服务缺用量时报 unknown，不报零；这是落实既定范围与用量要求。 |
| [HTTPX](https://www.python-httpx.org/async/)、[Trafilatura](https://trafilatura.readthedocs.io/en/latest/usage-python.html) | 异步流必须关闭；正文提取可接收已下载内容。权限逐跳检查不能交给隐藏下载入口。 |
| [pathspec](https://python-path-specification.readthedocs.io/en/latest/readme.html) | 公共 `GitIgnoreSpec` 存在；当前文档有可选正则后端，T13 使用基础 Python 后端，不引入额外 native backend。 |
| [Git status](https://git-scm.com/docs/git-status) | porcelain 是面向脚本的稳定格式；NUL 处理特殊路径。T12 仍需临时仓库验证 diff/show 禁外部程序及无索引写。 |
| [SWE-bench Evaluation](https://www.swebench.com/SWE-bench/guides/evaluation/) | 预测为三字段 JSONL，官方 harness 提供评分入口；T17 导出、T19 实际消费并记录 resolved/失败原因。评分未运行不能宣称完成。 |

## T01 统一内容与正式输入

- 任务目标：扩展 MessagePart 与 ToolResult 内容序列；定义同一文字/附件输入值，替换 start_turn、Steering、Headless、CLI/TUI/Desktop 的生产调用点及历史编码。文字入口只构造同一输入；SDK native item 身份规则保留。文件字节仍由 Integration 解析，Core 不读取文件。
- 新增、修改与删除：F01 F03 F04 F16（见文件组表）；按这些文件的当前职责实施，新增文件仅在表中注明“新增/计划新增”时创建；删除被本 Task 替换的旧分支、断言和重复入口，不默认整文件删除。
- 文件职责：扩展图片/文件引用和 ToolResult 内容序列；JSON round-trip；更新 Message 校验; 新输入值、闭合终态、工具进度路由、移除累计轮数 gate；有限异常检测和失败原因; 新内容序列化、引用覆盖、预算计量和压缩来源保留; 在正式启动时组合新能力、按配置/模型暴露可用工具、绑定会话资源。
- 依赖任务：本地核验，无前序实施 Task。
- 参考资料定位：[T11-Agent能力补齐.md](T11-Agent能力补齐.md) 第 4.2、4.3 节及行为 R01 R02 R04 R06 R10；外部接口使用第6节官方来源，不复制参考仓库架构。
- 测试与验收：Checklist 的 T01，映射 A01；真实环境条件不足记录未完成，不替换通过条件。
- 完成边界：文字主链和新内容 round-trip 可运行；未实现的附件导入由 T04/T06 完成，不留 legacy 执行路径。

## T02 工具失败、副作用与进度合同

- 任务目标：扩展既有 Outcome、failure.kind/retryable 与 side_effect；执行和 materialization 分离。普通错误返回模型；unknown 立即闭合剩余 FIFO ToolCall 为受控 not_executed 并终止。提供受限观察出口、归属及有界跨 chunk 脱敏。此处同步 AGENTS 的受控进度正文窄修订；不开放原参数或写入正文。
- 新增、修改与删除：F02 F03 F16 F25（见文件组表）；按这些文件的当前职责实施，新增文件仅在表中注明“新增/计划新增”时创建；删除被本 Task 替换的旧分支、断言和重复入口，不默认整文件删除。
- 文件职责：失败结构、副作用、进度出口；物化与脱敏；新工具注册组合; 新输入值、闭合终态、工具进度路由、移除累计轮数 gate；有限异常检测和失败原因; 在正式启动时组合新能力、按配置/模型暴露可用工具、绑定会话资源; 用户已批准的搜索秘密/事件正文边界、运行上限修订及使用说明。
- 依赖任务：T01；并复用原需求第7节的能力前置。
- 参考资料定位：[T11-Agent能力补齐.md](T11-Agent能力补齐.md) 第 4.5 节及行为 R10 R11 R16 R17 R24；外部接口使用第6节官方来源，不复制参考仓库架构。
- 测试与验收：Checklist 的 T02，映射 A08；真实环境条件不足记录未完成，不替换通过条件。
- 完成边界：写成功但保存失败不重复写；unknown 不纠偏重试；进度不写 RunState、不灌入模型历史；真实日志展示留 T09。

## T03 三协议图片序列化

- 任务目标：Anthropic 将图片放入 user/image 及同 ID tool_result；Responses 使用 input_image 与结构化 function_call_output；compatible 闭合 tool 文本后追加带调用身份和来源的 user 图片 wire 投影，不改 Core 历史角色。按实际安装 SDK schema 测试；资源解析边界可先使用受控 fixture，生产资产接入 T04。
- 新增、修改与删除：F07 F16 F23（见文件组表）；按这些文件的当前职责实施，新增文件仅在表中注明“新增/计划新增”时创建；删除被本 Task 替换的旧分支、断言和重复入口，不默认整文件删除。
- 文件职责：用户/工具图片的序列化与计量适配，支持失败明确映射; 在正式启动时组合新能力、按配置/模型暴露可用工具、绑定会话资源; 依赖声明、平台 marker 与 Python 原生资源打包。
- 依赖任务：T02；并复用原需求第7节的能力前置。
- 参考资料定位：[T11-Agent能力补齐.md](T11-Agent能力补齐.md) 第 4.3、6 节及行为 R03 R04 R06；外部接口使用第6节官方来源，不复制参考仓库架构。
- 测试与验收：Checklist 的 T03，映射 A01 A02；真实环境条件不足记录未完成，不替换通过条件。
- 完成边界：三协议真实 SDK 请求结构可检验；实际 Provider 内容理解证据必须由 T19 补齐，不能在本 Task 只凭 Mock 勾选 A02。

## T04 会话原始附件与历史恢复

- 任务目标：新增附件用例和文件适配承载临时导入、固定副本、提交绑定、移除、读取及派生缓存；副本就绪才提交引用，失败不重复 Turn。接入 Session、Transcript/Timeline 和分页；只做结构必要迁移，重复打开幂等，不保留长期双写。已提交原图不是缓存；无引用临时与派生文件正常淘汰。
- 新增、修改与删除：F04 F05 F08 F16（见文件组表）；按这些文件的当前职责实施，新增文件仅在表中注明“新增/计划新增”时创建；删除被本 Task 替换的旧分支、断言和重复入口，不默认整文件删除。
- 文件职责：新内容序列化、引用覆盖、预算计量和压缩来源保留; 会话附件绑定、恢复、结构必要迁移；文件/图片 replay；日志 ref 接入; 导入/提交/移除用例、固定副本、受控原图读取、缩略图与无引用临时清理; 在正式启动时组合新能力、按配置/模型暴露可用工具、绑定会话资源。
- 依赖任务：T03；并复用原需求第7节的能力前置。
- 参考资料定位：[T11-Agent能力补齐.md](T11-Agent能力补齐.md) 第 4.2、4.3 节及行为 R01 R02 R04；外部接口使用第6节官方来源，不复制参考仓库架构。
- 测试与验收：Checklist 的 T04，映射 A04 A07；真实环境条件不足记录未完成，不替换通过条件。
- 完成边界：删除源文件后已提交附件和图像仍能恢复；重发使用原副本；原图不会被缓存清除。

## T05 图片能力预检与 Context 压缩

- 任务目标：模型配置加入明确图片能力声明，贯通现有 application/configuration.py、integrations/config/data.py 的配置模型与 loader/writer。按真实待发请求（含历史及切换候选）预检，未知按不支持；拒绝时保留模型/草稿。Integration 提供有来源的图片非零估计或 count；字节/尺寸与 Token 分别检查。摘要保留可重读来源，沿用 F03 实际 Working Context 缩减判据。
- 新增、修改与删除：F04 F06 F07 F17（见文件组表）；按这些文件的当前职责实施，新增文件仅在表中注明“新增/计划新增”时创建；删除被本 Task 替换的旧分支、断言和重复入口，不默认整文件删除。
- 文件职责：新内容序列化、引用覆盖、预算计量和压缩来源保留; 图片能力/计量预检、真实请求组装、模型切换候选验证、关闭资源; 用户/工具图片的序列化与计量适配，支持失败明确映射; search/vision/tool limits 配置、用户与项目边界、秘密写入脱敏。
- 依赖任务：T04；并复用原需求第7节的能力前置。
- 参考资料定位：[T11-Agent能力补齐.md](T11-Agent能力补齐.md) 第 4.3、4.10 节及行为 R03 R04 R20；外部接口使用第6节官方来源，不复制参考仓库架构。
- 测试与验收：Checklist 的 T05，映射 A05 A06；真实环境条件不足记录未完成，不替换通过条件。
- 完成边界：图片正常退出请求后可切文字模型；不得暗中删图或压缩以强行切换；256K 文字 profile 不重调。

## T06 Desktop 附件输入与回放

- 任务目标：Main 文件选择/粘贴字节经 Application 导入；Composer 支持拖拽、粘贴、选择、仅附件发送、预览移除和失败重发。更新 desktop-api、Bridge protocol、状态及生命周期；历史分页显示附件，首条仅附件有标题/预览回退。大字节不放入通用事件，Renderer 不直读任意路径。
- 新增、修改与删除：F18 F19 F20 F21（见文件组表）；按这些文件的当前职责实施，新增文件仅在表中注明“新增/计划新增”时创建；删除被本 Task 替换的旧分支、断言和重复入口，不默认整文件删除。
- 文件职责：附件、预览、进程查询/停止/日志、安全产物 DTO；background 资源保留; 文件选择/导入、受控二进制传输/读取和打开/定位; 附件草稿/缩略、工具卡折叠/续读、来源链接、会话归属与异常原因; 搜索与图片能力配置、资源项、活动态禁用/生效提示，中英文本。
- 依赖任务：T05；并复用原需求第7节的能力前置。
- 参考资料定位：[T11-Agent能力补齐.md](T11-Agent能力补齐.md) 第 4.2、4.7 节及行为 R01 R02 R03 R04；外部接口使用第6节官方来源，不复制参考仓库架构。
- 测试与验收：Checklist 的 T06，映射 A03 A04 A05；真实环境条件不足记录未完成，不替换通过条件。
- 完成边界：一个提交只有一个 Turn；切 Session 草稿归属正确；失败保留可编辑草稿；同一正式输入同时服务 Headless。

## T07 文档定位读取与工具图片

- 任务目标：新增 ReadDocument/ViewImage；PDF 页、DOCX 顺序 block、XLSX sheet/range、PPTX slide 有界读取。PDF 页图经共享资产路径实际入模；公式与缓存值区分，不重算。PDFium 串行受控使用，昂贵解析需要可取消时用可回收私有子进程。依赖仅 pyproject，原生资源接入既有 PyInstaller spec。
- 新增、修改与删除：F09 F16 F23（见文件组表）；按这些文件的当前职责实施，新增文件仅在表中注明“新增/计划新增”时创建；删除被本 Task 替换的旧分支、断言和重复入口，不默认整文件删除。
- 文件职责：ReadDocument、ViewImage；四格式定位与有界读取、PDF 页图; 在正式启动时组合新能力、按配置/模型暴露可用工具、绑定会话资源; 依赖声明、平台 marker 与 Python 原生资源打包。
- 依赖任务：T06；并复用原需求第7节的能力前置。
- 参考资料定位：[T11-Agent能力补齐.md](T11-Agent能力补齐.md) 第 4.4、6 节及行为 R05 R06；外部接口使用第6节官方来源，不复制参考仓库架构。
- 测试与验收：Checklist 的 T07，映射 A09 A10；真实环境条件不足记录未完成，不替换通过条件。
- 完成边界：四格式、损坏/加密/超限/取消有定位和受控结果；不支持图片时明确不可用；安装产物实际读取由 T19 验证。

## T08 进程会话与原生 PTY

- 任务目标：Bash 为唯一启动入口，yield_time_ms 与显式 timeout_seconds 分离；默认无总寿命。后续 Process 支持 list/read/write/stop/resize 与 EOF，按所属 Session 查句柄。pipe 分 stdout/stderr，PTY 单 terminal 流；Windows pywinpty/ConPTY、POSIX ptyprocess。复用 Job/process-group 后代回收，必要私有宿主先入 Job 再启动命令。stdin 独立走执行权限，不能自动重放。
- 新增、修改与删除：F10 F11 F16 F23（见文件组表）；按这些文件的当前职责实施，新增文件仅在表中注明“新增/计划新增”时创建；删除被本 Task 替换的旧分支、断言和重复入口，不默认整文件删除。
- 文件职责：Bash 复用分类；进程句柄、pipe/PTY、输出 pump、stdin/stop；私有 OS 适配; 发布真实 shell/OS/cwd 与进程安全状态；关闭流程覆盖活进程; 在正式启动时组合新能力、按配置/模型暴露可用工具、绑定会话资源; 依赖声明、平台 marker 与 Python 原生资源打包。
- 依赖任务：T07；并复用原需求第7节的能力前置。
- 参考资料定位：[T11-Agent能力补齐.md](T11-Agent能力补齐.md) 第 4.6、6 节及行为 R12 R13 R14 R15 R25；外部接口使用第6节官方来源，不复制参考仓库架构。
- 测试与验收：Checklist 的 T08，映射 A11 A12 A14；真实环境条件不足记录未完成，不替换通过条件。
- 完成边界：短等待返回 running，后续有增量/退出码；原生 isatty、输入/EOF/resize 可测试；取消能解阻塞读并确认回收或报告 unknown。

## T09 进程生命周期与 Desktop 有界日志

- 任务目标：成功 Turn 和导航保留活进程；取消/异常截停仅回收本 Turn 新进程，shutdown 全回收后关闭 writer。输出持续 drain 到有界 spool/ring，游标过期报告最早位置；终态日志按既有 ref 封口并正常淘汰记录。事件按 Session/process 单调序号路由，不伪造新 Turn。Desktop 缩略/折叠/续读、状态/退出码、安全 ANSI 文本与阅读位置保护；TUI 忽略新增进度。
- 新增、修改与删除：F02 F03 F05 F10 F11 F18 F19 F20（见文件组表）；按这些文件的当前职责实施，新增文件仅在表中注明“新增/计划新增”时创建；删除被本 Task 替换的旧分支、断言和重复入口，不默认整文件删除。
- 文件职责：失败结构、副作用、进度出口；物化与脱敏；新工具注册组合; 新输入值、闭合终态、工具进度路由、移除累计轮数 gate；有限异常检测和失败原因; 会话附件绑定、恢复、结构必要迁移；文件/图片 replay；日志 ref 接入; Bash 复用分类；进程句柄、pipe/PTY、输出 pump、stdin/stop；私有 OS 适配; 发布真实 shell/OS/cwd 与进程安全状态；关闭流程覆盖活进程; 附件、预览、进程查询/停止/日志、安全产物 DTO；background 资源保留; 文件选择/导入、受控二进制传输/读取和打开/定位; 附件草稿/缩略、工具卡折叠/续读、来源链接、会话归属与异常原因。
- 依赖任务：T08；并复用原需求第7节的能力前置。
- 参考资料定位：[T11-Agent能力补齐.md](T11-Agent能力补齐.md) 第 4.5、4.6、4.7 节及行为 R11 R13 R15 R16 R17 R25；外部接口使用第6节官方来源，不复制参考仓库架构。
- 测试与验收：Checklist 的 T09，映射 A13 A14 A15 A16；真实环境条件不足记录未完成，不替换通过条件。
- 完成边界：后台 Session 活进程不被闲置回收；已结束 Turn 日志可持续更新；跨 chunk Secret 不泄露，内存/磁盘有界；原生安装验收留 T19。

## T10 搜索、抓取与可信搜索配置

- 任务目标：独立 Tavily Search 固定官方端点/basic/include_answer=false；用户 search.api_key 转 SecretValue，项目禁止任何凭据/重定向且不可自动启用。同步 AGENTS 搜索秘密窄修订。HTTPX 显式逐跳有界抓取，重定向按实际 URL 重新权限决策；Trafilatura 只处理已下载内容；PDF 复用 T07。未配置时不可用，429/额度/取消分类与用量明确，不自动升级收费模式。
- 新增、修改与删除：F12 F16 F17 F21 F23 F25（见文件组表）；按这些文件的当前职责实施，新增文件仅在表中注明“新增/计划新增”时创建；删除被本 Task 替换的旧分支、断言和重复入口，不默认整文件删除。
- 文件职责：Tavily Search、HTTP Fetch、本地正文提取、分页与错误; 在正式启动时组合新能力、按配置/模型暴露可用工具、绑定会话资源; search/vision/tool limits 配置、用户与项目边界、秘密写入脱敏; 搜索与图片能力配置、资源项、活动态禁用/生效提示，中英文本; 依赖声明、平台 marker 与 Python 原生资源打包; 用户已批准的搜索秘密/事件正文边界、运行上限修订及使用说明。
- 依赖任务：T09；并复用原需求第7节的能力前置。
- 参考资料定位：[T11-Agent能力补齐.md](T11-Agent能力补齐.md) 第 4.8、4.10、6 节及行为 R07 R08 R09 R10 R11 R20；外部接口使用第6节官方来源，不复制参考仓库架构。
- 测试与验收：Checklist 的 T10，映射 A17 A18 A23；真实环境条件不足记录未完成，不替换通过条件。
- 完成边界：正式配置到工具集合按 Turn 快照；来源可继续读取；不发会话全文、不带浏览器 Cookie、不启动浏览器；真实服务调用由 T19 验证。

## T11 ApplyPatch 预检与部分提交

- 任务目标：新增 Codex 文本 Patch 方言，复用 resolver/FileReadTracker/PermissionAction。全量语法、目标冲突、读取事实、变化与授权预检；失败零变更。按目标顺序单文件原子替换，提交前再次核对；移动两路径分别记录 applied/failed/not_applied。更新读事实，保留有独立用途的 EditFile，不建立全仓事务或自动回滚。
- 新增、修改与删除：F13 F16（见文件组表）；按这些文件的当前职责实施，新增文件仅在表中注明“新增/计划新增”时创建；删除被本 Task 替换的旧分支、断言和重复入口，不默认整文件删除。
- 文件职责：ApplyPatch 方言、目标集合权限、先读后写、预检/提交结果; 在正式启动时组合新能力、按配置/模型暴露可用工具、绑定会话资源。
- 依赖任务：T10；并复用原需求第7节的能力前置。
- 参考资料定位：[T11-Agent能力补齐.md](T11-Agent能力补齐.md) 第 4.8 节及行为 R18 R28 R11；外部接口使用第6节官方来源，不复制参考仓库架构。
- 测试与验收：Checklist 的 T11，映射 A19；真实环境条件不足记录未完成，不替换通过条件。
- 完成边界：增删改移动、重复 hunk、未读/变化/目标冲突及提交中失败结果与磁盘一致；未知副作用走 T02 停止链。

## T12 Git 工作区只读查询

- 任务目标：新增 GitWorkspace 的 status/diff/log/show/branch；argv、NUL porcelain、有界输出；禁 external diff/textconv 及可选索引写，不 fetch。处理非 Git、缺 Git、detached/unborn、未跟踪与特殊文件名。使用临时 repo 验证，绝不对用户工作区做测试写入。
- 新增、修改与删除：F14 F16（见文件组表）；按这些文件的当前职责实施，新增文件仅在表中注明“新增/计划新增”时创建；删除被本 Task 替换的旧分支、断言和重复入口，不默认整文件删除。
- 文件职责：GitWorkspace 只读查询和 NUL/受控 argv 处理; 在正式启动时组合新能力、按配置/模型暴露可用工具、绑定会话资源。
- 依赖任务：T11；并复用原需求第7节的能力前置。
- 参考资料定位：[T11-Agent能力补齐.md](T11-Agent能力补齐.md) 第 4.8 节及行为 R19；外部接口使用第6节官方来源，不复制参考仓库架构。
- 测试与验收：Checklist 的 T12，映射 A20；真实环境条件不足记录未完成，不替换通过条件。
- 完成边界：查询没有仓库写、联网或外部 diff 程序执行；缺 Git 返回 unavailable，不自动安装。

## T13 Glob/Grep 有界检索与续读

- 任务目标：保留名称和正则合同；pathspec GitIgnoreSpec 按目录继承 .gitignore/.ignore，明确 hidden/ignored，跳过二进制。用既有 regex 超时；先限制遍历/输出再分页，不全量汇集。续读绑定查询条件且新候选继续走敏感/外部/symlink 权限前置；复用 ToolResultRead，防止递归物化。
- 新增、修改与删除：F15 F16 F23（见文件组表）；按这些文件的当前职责实施，新增文件仅在表中注明“新增/计划新增”时创建；删除被本 Task 替换的旧分支、断言和重复入口，不默认整文件删除。
- 文件职责：分页迭代、忽略规则、二进制、正则时间限制、续读; 在正式启动时组合新能力、按配置/模型暴露可用工具、绑定会话资源; 依赖声明、平台 marker 与 Python 原生资源打包。
- 依赖任务：T12；并复用原需求第7节的能力前置。
- 参考资料定位：[T11-Agent能力补齐.md](T11-Agent能力补齐.md) 第 4.8、6 节及行为 R17 R26；外部接口使用第6节官方来源，不复制参考仓库架构。
- 测试与验收：Checklist 的 T13，映射 A21；真实环境条件不足记录未完成，不替换通过条件。
- 完成边界：忽略/隐藏/超时/分页/变化与权限回归可观测；不承诺全局检索快照，不引入必须分发的 rg。

## T14 异常纠偏与截停替代固定上限

- 任务目标：删除 AgentLoopConfig 与普通/continuation 中累计轮数 gate，不另设总 Token/时间 fallback；保留统计、Context Gate、I/O 与用户取消。Loop 有界保存最近行动/语义结果，三类异常按需求阈值先纠偏后截停；忽略传输身份但不乱删参数。有效新证据解除怀疑，反馈本身不重置；合法 Process wait 强制实际有界等待且不计空转。unknown 立即停，不进入纠偏。
- 新增、修改与删除：F02 F03 F06 F20 F24 F25（见文件组表）；按这些文件的当前职责实施，新增文件仅在表中注明“新增/计划新增”时创建；删除被本 Task 替换的旧分支、断言和重复入口，不默认整文件删除。
- 文件职责：失败结构、副作用、进度出口；物化与脱敏；新工具注册组合; 新输入值、闭合终态、工具进度路由、移除累计轮数 gate；有限异常检测和失败原因; 图片能力/计量预检、真实请求组装、模型切换候选验证、关闭资源; 附件草稿/缩略、工具卡折叠/续读、来源链接、会话归属与异常原因; 最小合同/回归/端到端正反例；替换旧 max_iterations 和字符串-only 断言; 用户已批准的搜索秘密/事件正文边界、运行上限修订及使用说明。
- 依赖任务：T13；并复用原需求第7节的能力前置。
- 参考资料定位：[T11-Agent能力补齐.md](T11-Agent能力补齐.md) 第 4.9 节及行为 R22 R23 R24 R25 R11 R15；外部接口使用第6节官方来源，不复制参考仓库架构。
- 测试与验收：Checklist 的 T14，映射 A08 A22；真实环境条件不足记录未完成，不替换通过条件。
- 完成边界：脚本 Provider 至少 200 轮正常完成；失败/短周期/final 阻断正例、编辑重测/等待/人工输入反例通过；终态 runaway_detected 与取消区分。

## T15 Settings 配置完整性与生效边界

- 任务目标：收口已新增 search/vision/工具单次超时、输出/附件限量；沿用配置合同、原子 writer、秘密 editor-local state 和单 modal。显示 configured/effective/source；当前和后台 Turn/Compact 保有快照，保存用于下一安全边界；活进程保有启动参数不重启。中英文本一致，不暴露内部检测窗口，不重复 reasoning/window/max_output。
- 新增、修改与删除：F06 F17 F18 F21（见文件组表）；按这些文件的当前职责实施，新增文件仅在表中注明“新增/计划新增”时创建；删除被本 Task 替换的旧分支、断言和重复入口，不默认整文件删除。
- 文件职责：图片能力/计量预检、真实请求组装、模型切换候选验证、关闭资源; search/vision/tool limits 配置、用户与项目边界、秘密写入脱敏; 附件、预览、进程查询/停止/日志、安全产物 DTO；background 资源保留; 搜索与图片能力配置、资源项、活动态禁用/生效提示，中英文本。
- 依赖任务：T14；并复用原需求第7节的能力前置。
- 参考资料定位：[T11-Agent能力补齐.md](T11-Agent能力补齐.md) 第 4.10 节及行为 R03 R08 R20；外部接口使用第6节官方来源，不复制参考仓库架构。
- 测试与验收：Checklist 的 T15，映射 A23；真实环境条件不足记录未完成，不替换通过条件。
- 完成边界：用户/项目作用域和拒绝路径可测试；项目不能放宽限制；保存不半途换模型/端点或重启存活进程。

## T16 Desktop 产物打开与受控预览

- 任务目标：Application 校验存在、工作目录或已授权外部路径；Main 执行 open/reveal，图片受控预览。safe-markdown/卡片连接正式 DTO，Office 系统打开，可执行默认定位。缺失/不支持局部反馈，不重跑 Agent；模型 URI/HTML/Shell 不直达执行。
- 新增、修改与删除：F08 F18 F19 F20（见文件组表）；按这些文件的当前职责实施，新增文件仅在表中注明“新增/计划新增”时创建；删除被本 Task 替换的旧分支、断言和重复入口，不默认整文件删除。
- 文件职责：导入/提交/移除用例、固定副本、受控原图读取、缩略图与无引用临时清理; 附件、预览、进程查询/停止/日志、安全产物 DTO；background 资源保留; 文件选择/导入、受控二进制传输/读取和打开/定位; 附件草稿/缩略、工具卡折叠/续读、来源链接、会话归属与异常原因。
- 依赖任务：T15；并复用原需求第7节的能力前置。
- 参考资料定位：[T11-Agent能力补齐.md](T11-Agent能力补齐.md) 第 4.7 节及行为 R27；外部接口使用第6节官方来源，不复制参考仓库架构。
- 测试与验收：Checklist 的 T16，映射 A24；真实环境条件不足记录未完成，不替换通过条件。
- 完成边界：授权文件打开定位和图片预览可用；恶意 URI 不执行命令；保持 Renderer 无任意 fs/shell。

## T17 SWE-bench 预测与安全 Trace

- 任务目标：新增 eval/swebench.py 薄适配，复用 eval/execution.py 的正式 Headless Application；输入外部实例工作目录/题面/模型引用，不读 gold patch。预测三字段 instance_id/model_name_or_path/model_patch 取实际基线 diff，含新文件；实例隔离，trace 排除秘密/图片字节/原生载荷。官方评分依赖不加入产品，适配样本与运行说明入 eval/README。
- 新增、修改与删除：F22 F24 F25（见文件组表）；按这些文件的当前职责实施，新增文件仅在表中注明“新增/计划新增”时创建；删除被本 Task 替换的旧分支、断言和重复入口，不默认整文件删除。
- 文件职责：薄适配、预测输出、新文件 diff、trace 扩展与外部评分示例; 最小合同/回归/端到端正反例；替换旧 max_iterations 和字符串-only 断言; 用户已批准的搜索秘密/事件正文边界、运行上限修订及使用说明。
- 依赖任务：T16；并复用原需求第7节的能力前置。
- 参考资料定位：[T11-Agent能力补齐.md](T11-Agent能力补齐.md) 第 4.10、6 节及行为 R21；外部接口使用第6节官方来源，不复制参考仓库架构。
- 测试与验收：Checklist 的 T17，映射 A25 A26；真实环境条件不足记录未完成，不替换通过条件。
- 完成边界：可导出官方可消费 JSONL；实际 harness 评分放 T19，resolved=false 如实报告，不要求必解。

## T18 [接入主流程]

- 任务目标：逐项核对原始 1—15 能力及横向链路在 Application/headless/Desktop 正式入口可达；复用前序真实接入，不另造演示程序。移除替代入口与 UI 直连；检查工具可见性、权限、配置、关闭、历史同链。
- 新增、修改与删除：F16 F18 F22 F24（见文件组表）；按这些文件的当前职责实施，新增文件仅在表中注明“新增/计划新增”时创建；删除被本 Task 替换的旧分支、断言和重复入口，不默认整文件删除。
- 文件职责：在正式启动时组合新能力、按配置/模型暴露可用工具、绑定会话资源; 附件、预览、进程查询/停止/日志、安全产物 DTO；background 资源保留; 薄适配、预测输出、新文件 diff、trace 扩展与外部评分示例; 最小合同/回归/端到端正反例；替换旧 max_iterations 和字符串-only 断言。
- 依赖任务：T17；并复用原需求第7节的能力前置。
- 参考资料定位：[T11-Agent能力补齐.md](T11-Agent能力补齐.md) 第 2、4、7 节及行为 R01 R02 R03 R04 R05 R06 R07 R08 R09 R10 R11 R12 R13 R14 R15 R16 R17 R18 R19 R20 R21 R22 R23 R24 R25 R26 R27 R28；外部接口使用第6节官方来源，不复制参考仓库架构。
- 测试与验收：Checklist 的 T18，映射 A27；真实环境条件不足记录未完成，不替换通过条件。
- 完成边界：架构与 Application 定向验收通过，能力追踪无空项；只修前序范围内接缝。

## T19 [端到端验证]

- 任务目标：在标准 Windows package/make 产物验证附件、四格式/PDF 页图、真实 PTY/后代/中文 ANSI 日志/stdin/停止/关闭；三协议分别验证用户图片及工具图片的不同内容。真实 Tavily 后 Fetch 静态页与 PDF；正式 Headless 输出一条 SWE-bench Lite 预测并由官方 harness 完成评分；联合截图+文档→Patch→失败测试→读日志修复→重跑→查看图→点击产物。
- 新增、修改与删除：F23 F24（见文件组表）；按这些文件的当前职责实施，新增文件仅在表中注明“新增/计划新增”时创建；删除被本 Task 替换的旧分支、断言和重复入口，不默认整文件删除。
- 文件职责：依赖声明、平台 marker 与 Python 原生资源打包; 最小合同/回归/端到端正反例；替换旧 max_iterations 和字符串-only 断言。
- 依赖任务：T18；并复用原需求第7节的能力前置。
- 参考资料定位：[T11-Agent能力补齐.md](T11-Agent能力补齐.md) 第 8 节及行为 R01 R02 R03 R04 R05 R06 R07 R09 R12 R13 R14 R15 R16 R17 R18 R21 R27 R28；外部接口使用第6节官方来源，不复制参考仓库架构。
- 测试与验收：Checklist 的 T19，映射 A02 A10 A12 A15 A18 A26 A28；真实环境条件不足记录未完成，不替换通过条件。
- 完成边界：记录端点/模型/SDK、安全命令和精确结果。缺凭据/平台/Docker 只保留对应未完成项，不能用 Mock、CDP 布局或评分环境缺失冒充完成；有效已有证据可复用。

## T20 [遗留负担清理]

- 任务目标：清理旧累计上限、字符串唯一结果假设、communicate-only 重复链、不可达/演示入口、失效文案和依赖；历史失败事实不删，冻结包不改。按需求第9节及 docs/README 维护映射同步全部相关用户文档、四层/GUI 当前事实、既有核心教程、Tools、eval/README、欠账和全量索引。
- 新增、修改与删除：F24 F25（见文件组表）；按这些文件的当前职责实施，新增文件仅在表中注明“新增/计划新增”时创建；删除被本 Task 替换的旧分支、断言和重复入口，不默认整文件删除。
- 文件职责：最小合同/回归/端到端正反例；替换旧 max_iterations 和字符串-only 断言; 用户已批准的搜索秘密/事件正文边界、运行上限修订及使用说明。
- 依赖任务：T19；并复用原需求第7节的能力前置。
- 参考资料定位：[T11-Agent能力补齐.md](T11-Agent能力补齐.md) 第 9、10、11 节及行为 R01 R02 R03 R04 R05 R06 R07 R08 R09 R10 R11 R12 R13 R14 R15 R16 R17 R18 R19 R20 R21 R22 R23 R24 R25 R26 R27 R28；外部接口使用第6节官方来源，不复制参考仓库架构。
- 测试与验收：Checklist 的 T20，映射 A29；真实环境条件不足记录未完成，不替换通过条件。
- 完成边界：必要验证后停止；不新增兼容层/全局框架，不提交、不归档；所有必需验收仍未完成时如实报告，不能提前宣称整包完成。

## 文件组与职责

下表按真实职责组合文件；新增路径是本任务计划，不冒充当前存在。私有拆分可在本地核对代码后调整，但不可改变第 3、4 节公共语义，不按一个类型一个文件组织，不为新功能复制另一套 Registry/Runtime。

| 编号 | 路径 | 操作与具体改动 | 接入或替换关系 | 行为 |
| --- | --- | --- | --- | --- |
| F01 | `src/uthcode/core/provider.py` | 扩展图片/文件引用和 ToolResult 内容序列；JSON round-trip；更新 Message 校验 | 统一替换文本唯一假设；保留身份和 native item 隔离 | R01—R06、R10 |
| F02 | `src/uthcode/core/tool.py`、`application/tools.py` | 失败结构、副作用、进度出口；物化与脱敏；新工具注册组合 | 复用 Outcome、Executor、materializer，去除字符串解析失败语义 | R10、R11、R16、R17 |
| F03 | `src/uthcode/core/agent.py`、`core/agent_events.py`、`application/runs.py` | 新输入值、闭合终态、工具进度路由、移除累计轮数 gate；有限异常检测和失败原因 | Loop 仍唯一状态写者，复用 RuntimeFeedback 与 Turn driver | R01、R10—R17、R22—R25 |
| F04 | `src/uthcode/core/history.py`、`core/context.py`、`core/compaction.py` | 新内容序列化、引用覆盖、预算计量和压缩来源保留 | 复用原三重历史、语义单元和实际缩减验证 | R02—R04 |
| F05 | `src/uthcode/application/sessions.py`、`integrations/session_files.py` | 会话附件绑定、恢复、结构必要迁移；文件/图片 replay；日志 ref 接入 | Session store 保持权威，原始资料与缓存明确区分 | R02、R04、R13、R17 |
| F06 | `src/uthcode/application/context.py`、`request_preparation.py`、`generation.py` | 图片能力/计量预检、真实请求组装、模型切换候选验证、关闭资源 | 不改成 UI 预算，不新增平行 Context 编译器 | R03、R04、R15、R20 |
| F07 | `src/uthcode/integrations/providers/anthropic.py`、`openai_responses.py`、`openai_compat.py` | 用户/工具图片的序列化与计量适配，支持失败明确映射 | SDK 留 Integration；compatible 图片追加仅为 wire 投影 | R03、R04、R06 |
| F08 | 新增 `src/uthcode/application/attachments.py`、`integrations/attachment_files.py` | 导入/提交/移除用例、固定副本、受控原图读取、缩略图与无引用临时清理 | 由 Session/正式 Application 组合；不建通用 Artifact Store | R01—R06、R27 |
| F09 | 新增 `src/uthcode/integrations/tools/document_tools.py`、`image_tools.py` | ReadDocument、ViewImage；四格式定位与有界读取、PDF 页图 | 共享 asset_ref 和既有权限/物化链，解析器不直接调模型 | R05、R06 |
| F10 | `src/uthcode/integrations/tools/process_tools.py`；必要时新增同目录 `process_sessions.py` | Bash 复用分类；进程句柄、pipe/PTY、输出 pump、stdin/stop；私有 OS 适配 | 替换 communicate-only 执行，保留后代回收能力；不改为 terminal UI | R12—R17、R25 |
| F11 | `src/uthcode/application/runtime_context.py`、`application/generation.py` | 发布真实 shell/OS/cwd 与进程安全状态；关闭流程覆盖活进程 | 不探测未授权网络或环境秘密；同步 close 可在内部适配异步清理边界 | R12、R13、R15 |
| F12 | 新增 `src/uthcode/integrations/tools/web_tools.py` | Tavily Search、HTTP Fetch、本地正文提取、分页与错误 | 复用 PermissionAction/ToolResultRead，保持两个明确工具职责 | R07—R11 |
| F13 | `src/uthcode/integrations/tools/file_tools.py`、`workspace.py`；新增 `patch_tools.py` | ApplyPatch 方言、目标集合权限、先读后写、预检/提交结果 | 复用 resolver/tracker，不绕过 EditFile 的变化保护 | R18、R28 |
| F14 | 新增 `src/uthcode/integrations/tools/git_tools.py` | GitWorkspace 只读查询和 NUL/受控 argv 处理 | 不添加 Git 写操作 | R19 |
| F15 | `src/uthcode/integrations/tools/search_tools.py`、`tool_result_read.py` | 分页迭代、忽略规则、二进制、正则时间限制、续读 | 保留 Glob/Grep；大结果读取不递归外置自己 | R17、R26 |
| F16 | `src/uthcode/integrations/tools/factory.py`、`application/bootstrap.py` | 在正式启动时组合新能力、按配置/模型暴露可用工具、绑定会话资源 | Headless/Desktop 同一组合入口，不加只供 UI 的孤立工具 | 全部 |
| F17 | `src/uthcode/application/configuration.py`、`integrations/config/loader.py`、`writer.py` | search/vision/tool limits 配置、用户与项目边界、秘密写入脱敏 | 复用 TOML 原子写入和 SecretValue；清理旧允许字段假设 | R03、R08、R20 |
| F18 | `src/uthcode/interfaces/desktop/bridge.py`、`protocol.py`；`desktop/src/desktop-api.ts` | 附件、预览、进程查询/停止/日志、安全产物 DTO；background 资源保留 | 复用 JSONL Bridge；新增方法仍走 Application | R01、R02、R13—R17、R27 |
| F19 | `desktop/src/main.ts`、`preload.ts` | 文件选择/导入、受控二进制传输/读取和打开/定位 | 不暴露任意 fs/shell；不把大 base64 塞进通用事件 | R01、R16、R27 |
| F20 | `desktop/src/renderer/Composer.tsx`、`ChatTimeline.tsx`、`safe-markdown.tsx`；状态与生命周期文件按现有路由修改 | 附件草稿/缩略、工具卡折叠/续读、来源链接、会话归属与异常原因 | 复用 state.ts / useRuntimeLifecycle 所有权；状态文件本地定向核对后改 | R01—R04、R13、R16、R17、R23、R27 |
| F21 | `desktop/src/renderer/SettingsView.tsx`、`SettingsEditorModal.tsx`、`settings-draft.ts`、`locales/{zh-CN,en}.ts` | 搜索与图片能力配置、资源项、活动态禁用/生效提示，中英文本 | 复用现有单 modal 与秘密 editor-local state | R03、R08、R20 |
| F22 | `eval/execution.py`；新增 `eval/swebench.py` | 薄适配、预测输出、新文件 diff、trace 扩展与外部评分示例 | 不复制现有 run_attempt 的 Loop，提取需要复用的最小调用段 | R21 |
| F23 | `pyproject.toml`、`desktop/packaging/uthcode-runtime.spec` | 依赖声明、平台 marker 与 Python 原生资源打包 | 使用既有 Conda/build/package 体系，不建新环境 | R05、R06、R14 |
| F24 | `tests/` 与 `desktop/tests/` 第 8 节指定位置 | 最小合同/回归/端到端正反例；替换旧 max_iterations 和字符串-only 断言 | 不为可替换私有函数镜像造测试 | 全部 |
| F25 | `AGENTS.md` 和第 9 节文档 | 用户已批准的搜索秘密/事件正文边界、运行上限修订及使用说明 | 不修改已冻结工作包来覆盖新决定 | 全部 |

## 文档交付范围

必须清理的替换项：

- AgentLoopConfig 及普通执行/continuation 路径中的固定累计轮数终止；相应旧“50 轮必失败”测试改为异常截停正反例。历史记录中既有失败标记按迁移需要处理，不删除用户历史。
- ToolResult 字符串唯一载荷分支、只支持文字的 Message 校验/序列化假设、重复配置允许字段定义中的遗漏。
- Bash communicate-only 与新进程会话并存的重复执行路径；保留被复用的命令分类、权限事实和 OS 回收实现。
- 为新功能临时建立的孤立演示入口、UI 直连 SDK、全量日志双写到聊天/模型的代码。
- 失效的 GUI/配置文案与未使用依赖；不借机做全仓瘦身、目录重排或修改冻结工作包。

按 `docs/README.md` 维护映射交付：

| 文档 | 更新内容 |
| --- | --- |
| `AGENTS.md` | 仅两项已批准边界修订：用户级 search Secret；受控工具进度正文允许范围。同步移除若有的固定轮数产品约束，保留 Permission/Secret/配置隔离和最小原子性 |
| `README.md`、`docs/user-manual/getting-started.md` | 图片/文档/联网/PTY 能力、依赖和实际平台限制；Bash 仍是当前 OS 用户权限下 unsandboxed execution |
| `docs/user-manual/configuration.md` | Search/图片能力/资源项、费用/凭据、用户项目作用域、生效时机；不把所有内部常量暴露为用户配置 |
| `docs/user-manual/commands.md`、`docs/Tools.md` | 新工具参数和模式、文件/图片、进程生命周期/等待/取消、Git 只读与来源导航 |
| `docs/context/A01-AgentRuntime/AgentRuntime-Context.md` | 强类型内容、结果失败、进度、异常检测，取代固定轮数 |
| `docs/context/A02-Control/Control-Context.md` | stdin/远端 URL/Patch 权限与 unknown 副作用截停；审批不等于 OS Sandbox |
| `docs/context/A03-State/State-Context.md` | 原始附件与派生缓存、图片历史/Context、进程日志与 Turn 状态分离 |
| `docs/context/A04-Orchestration/Orchestration-Context.md` | Application 资源组合、Headless 输入与关闭；Eval 正式入口 |
| `docs/context/GUI/GUI-Context.md` | 附件、工具卡/分页、后台活进程保留、产物打开和 Settings |
| 相关 `docs/core-design/` 教程 | 按既有真实主题补充被改变的 Core/Tool/Context 机制；本任务不要求额外批量生图 |
| `eval/README.md` | SWE-bench 适配运行/预测/评分边界与 trace 说明；不发布未测性能结论 |
| `docs/Context-Index.md`、`docs/OutstandingDebtList.md` | 由本地拆包按规则维护 current-status 与真实欠账；不自行归档 |

本地执行反馈只记录实际改动、关键机制、命令和精确结果、未验证条件及与任务书不一致处；不把本文件重复复制成探索报告。
