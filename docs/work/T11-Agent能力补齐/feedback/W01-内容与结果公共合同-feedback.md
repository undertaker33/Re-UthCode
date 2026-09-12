# W01 内容与结果公共合同 Feedback

## 范围与结果

本 Worker 串行完成 T01 → T02 → T03。实现覆盖 Core 内容/输入合同、Tool Outcome 失败与副作用合同、受限进度观察以及三条 Provider 图片 wire 序列化；未实施 T14 的 `max_iterations` 替换，未扩展 T04/T06 附件导入，也未把真实 Provider A02 入模结果记为完成。

原始需求、Spec、Tasks、Worker Prompt 和 Checklist 冻结文字均未修改；Checklist 只更新了本 Worker 已有验收框的勾选状态。未执行 Git stage、commit、push、merge、rebase、tag、release 或归档。

## T01 统一内容与正式输入

- `core.provider` 增加 `ImagePart`、`FilePart`、`SourcePart`、`ContentSequence` 与 `MessageInput`。引用只携带 asset_ref、MIME、尺寸/定位等事实，不携带图片或文件字节。
- `Message`、`ToolResultPart`、Transcript 序列化入口和 `MessageInput` 支持结构化内容 round-trip；纯文字仍保持既有字符串调用行为。
- `AgentLoop.start_turn`、`RunState.new_turn`、`AgentRun.start_turn` 和 Steering 使用同一正式输入值；字符串只在入口规范化为 `MessageInput`，没有第二套 legacy Runtime。
- 公共用户事件只投影 display-safe 内容引用，不包含 native item、SDK 对象、secret 或工具原始参数；Core 继续不读取资产字节。

## T02 工具失败、副作用与进度

- `ToolFailure`/`ToolFailureKind` 提供稳定 kind/retryable，`ToolSideEffect` 区分 none/applied/partial/unknown；Outcome 继续与 Application materialization 分离，并保留 resource、process 与退出事实字段。
- Tool 普通错误继续形成受控 `ToolResultPart` 交给下一次 Provider；执行异常或 unknown side effect 返回 unknown，立即停止当前 FIFO 批次，并按原顺序为未执行调用补 `not_executed` 终态结果后终止 Turn。
- `ToolProgress` 是有界观察值，未进入 RunState、Transcript、ToolResult 正文或 Provider history；AgentEvent 提供归属字段，Application 提供单块及短窗口跨 chunk 脱敏/限量投影。真实日志展示留 T09。
- 写入执行事实与结果保存事实保持分离；materialization 失败只生成观察端错误，不重做已经执行的 Tool。

## T03 三协议图片序列化

- Anthropic Messages：user 内容按原顺序输出 text/image block；ToolResult 使用相同 `tool_use_id`，结构化 content 内可携带文字/图片块；data URL 受实际 SDK MIME 集合校验。
- OpenAI Responses：user 使用 `input_text`/`input_image`（含安装 SDK 要求的 `detail`）；ToolResult 使用带 `call_id` 的结构化 `function_call_output`。
- OpenAI-compatible Chat Completions：user 使用 text/image_url；ToolResult 先闭合标准 tool 文本消息，再由 Adapter 追加带 ToolCall 身份提示的 user 图片 wire 投影，Core history role 不变。
- Provider identity/native item 规则保持原有边界；图片字节解析和真实资产接入留后续 T04/T07/T19 条件。

## 修改文件

- Core：`src/uthcode/core/provider.py`、`tool.py`、`agent.py`、`agent_events.py`、`interaction.py`、`__init__.py`。
- Application：`src/uthcode/application/runs.py`、`generation.py`、`tools.py`、`__init__.py`。
- Integration：`src/uthcode/integrations/providers/anthropic.py`、`openai_responses.py`、`openai_compat.py`。
- 测试：`tests/test_t11_w01_contract.py`，覆盖内容 round-trip、统一输入、Outcome 失败/副作用/进度、unknown FIFO 截停、三协议 wire 结构。

## 精确验证

| 命令 | 结果 |
| --- | --- |
| `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_t11_w01_contract.py -q` | 4 passed |
| `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_provider_contract.py tests/test_tool_core.py tests/test_agent_events.py tests/test_agent_loop.py tests/test_anthropic_integration.py tests/test_openai_responses_integration.py tests/test_openai_compat_integration.py tests/test_t11_w01_contract.py -q` | 189 passed, 3 skipped |
| `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q` | 23 passed |
| `conda run --no-capture-output -n re-uthcode python -m pytest -q` | 1524 passed, 3 skipped in 124.74s |
| `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests` | exit code 0 |
| `conda run --no-capture-output -n re-uthcode python C:\Users\93445\.codex\t11_check_frozen.py` | PASS: 10 frozen files unchanged except permitted checklist completion marks |

三个 skipped 用例是既有未授权 live Provider gate；未发起网络/计费请求。真实 Provider 图片理解、具体端点/模型/SDK 证据仍由 A02/T19 在配置完成后补测，不能由本地 fixture 或 Mock 代替。

## 未验证项与边界

- A02（三协议真实入模）保持未勾选，真实 Provider A02 留 T19；本 Worker 不冒充完成。
- T04/T06 的附件副本、Desktop 输入与恢复，T07 的生产资产读取，以及 T14 的 runaway/max_iterations 替换均未实施。
- 未修改 `docs/OutstandingDebtList.md`；本 Worker 没有新增因依赖后置能力而刻意不实施的能力欠账。
- 文档修改按 `uth-utf8-guard` 执行 UTF-8、replacement/mojibake 与 Markdown fence 检查，未发现编码问题。

## Reviewer 返工第 1 轮

### 返工原因

首轮审核指出三项实现缺口：Tool progress 只停留在结果类型中，没有接入执行期间的 Application 事件主链；大结果物化把结构化图片、文件和来源引用丢成纯文本；持久化失败结果没有保留已知 execution metadata。另要求把当前实现同步到受控进度正文、A01/A03 当前事实与 Context-Index。

### 实际修改

- `CancellationToken` 增加执行范围内的 `report_progress()` 出口；`ToolExecutor.execute_prepared_outcome()` 安装并恢复该出口，`AgentLoop._execute_prepared()` 在 Tool 未结束时发布文本安全 heartbeat，并把有界 progress 尾部交给 Application 投影。Application 调用 `redact_progress_chunks()` 和 `project_tool_progress()`，跨 chunk 的秘密只在合并后脱敏，进度不进入 RunState、History 或 Provider 请求。
- `ApplicationToolService.materialize_tool_result()` 只按文本正文计算阈值和写入 Session ref；inline、externalized、hard-cap failure 与 persistence failure 均通过结构化 content 保留 Image/File/Source 及原顺序。
- 持久化失败元数据复用统一 execution facts，继续保留 failure kind/retryable、side effect、resource、process、stream、cursor 和 exit code，并叠加 persistence failure 字段。
- 按当前代码事实窄修订根 `AGENTS.md` 的受控进度正文、`docs/context/A01-AgentRuntime/AgentRuntime-Context.md`、`docs/context/A03-State/State-Context.md` 与 `docs/Context-Index.md`；未修改冻结需求、Spec、Tasks、Prompt 或 Checklist 文字。
- 新增/补强职责测试位于 `tests/test_application_runs.py` 与 `tests/test_tool_result_persistence.py`；原有 W01 合同测试文件保留用于 Core/Provider 合同覆盖。

### 返工验证

| 命令 | 结果 |
| --- | --- |
| `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_application_runs.py::test_tool_progress_is_projected_live_and_cross_chunk_redacted tests/test_tool_result_persistence.py::test_materialization_externalizes_only_text_and_keeps_reference_order tests/test_tool_result_persistence.py::test_materialization_hard_cap_keeps_structured_references tests/test_tool_result_persistence.py::test_materialization_inline_keeps_structured_references tests/test_tool_result_persistence.py::test_persistence_failure_keeps_successful_execution_and_never_requests_retry tests/test_tool_result_persistence.py::test_persistence_failure_preserves_failed_execution_error_truth -q` | 6 passed |
| `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_application_runs.py tests/test_tool_result_persistence.py tests/test_provider_contract.py tests/test_tool_core.py tests/test_agent_events.py tests/test_agent_loop.py tests/test_anthropic_integration.py tests/test_openai_responses_integration.py tests/test_openai_compat_integration.py tests/test_t11_w01_contract.py -q` | 259 passed, 3 skipped in 7.14s |
| `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q` | 23 passed in 3.28s |
| `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests` | exit code 0 |

新增 live-chain 用例确认 Tool 尚未释放时已经收到 `ToolProgress` heartbeat，并确认跨 chunk secret 未出现在任何进度事件或 RunSnapshot；结构化物化用例分别覆盖 inline、externalized 和 hard-cap/persistence failure。A02/T19 真实 Provider、T04/T06/T07、T14 以及其他后置 Task 仍未验证或未实施，继续保持原边界。

### 返工第 1 轮进度链补正

复审指出上一段的 heartbeat 仍将真实文本延迟到 Tool 完成；本次在同一返工轮内继续收敛：移除 Agent 侧整批 `pending_progress`，每次 `report_progress()` 立即通过 Application 唯一事件出口投影当前安全前缀，仅在服务内按 run/turn/iteration/batch/tool 归属保留最多 256 字符原始短尾，Tool 结束时调用 flush 释放尾部。跨 chunk 脱敏继续实际调用 `redact_progress_chunks()`，并覆盖 ambient/configured secret 的前缀匹配；真实链测试在首个和第二个报告、Tool 完成前分别断言收到非空安全文本，事件与 RunSnapshot 均不含 secret。

补正后的定向六项测试为 6 passed；受影响职责回归为 259 passed, 3 skipped。后续架构、compileall、冻结和 UTF-8 检查仍按交付命令执行并记录最终结果。

此处“复审指出”指总控对首轮返工实现的补充检查；Terra 第二轮尚未运行，当前状态仍为待审。

## Reviewer 返工第 2 轮

Terra 第 2 轮指出唯一 P1：固定 256 字符尾部会让已知 400 字符 Secret 在 300+100 两次真实 `report_progress()` 中跨事件泄漏。修复仅收敛该问题：已知配置/环境 Secret 的前缀匹配按实际 Secret 长度保留所需有限尾部，完整 Secret 命中后从其末尾重新计算待保留后缀；形状兜底使用单个 `ToolProgress` 已有的 512 字符观测上限，不新增 Secret 长度限制，也不丢弃正常日志。当前事实文档继续只描述有界尾部，不再把 256 写成进度尾部上限；上一轮段落中的“最多 256”保留为历史记录，未改写冻结/历史文字。

新增真实 Agent→Tool→Application→AgentEvent 链回归覆盖 400 字符 Secret 的 300+100 两次报告、完成 flush 与事件/RunSnapshot 脱敏；既有短 Secret 两报告即时投影回归也保留。精确验证：`conda run --no-capture-output -n re-uthcode python -m pytest tests/test_application_runs.py::test_tool_progress_is_projected_live_and_cross_chunk_redacted tests/test_application_runs.py::test_long_known_secret_progress_tail_is_bounded_by_secret_and_flushed -q` 为 2 passed；受影响 Application/物化职责回归 `tests/test_application_runs.py tests/test_tool_result_persistence.py` 为 71 passed。Terra 第 2 轮尚未运行，当前状态仍为待审。

## Reviewer 返工第 3 轮

Terra 第 3 轮指出普通进度空白丢失：进度路径复用 `_single_line()` 会剥除报告首尾空格，使 `ordinary alpha ` 与 `ordinary beta` 拼成 `ordinary alphaordinary beta`。本轮仅在进度净化路径改为保留普通空白、只将 CR/LF 转为空格；工具摘要继续使用原 `_single_line()`，未扩大其他摘要语义。补充真实 Agent→Tool→Application→AgentEvent 两报告与直接 Application 投影两报告回归，确认跨报告空白保持；短/长 Secret 测试继续保留。

精确验证：`conda run --no-capture-output -n re-uthcode python -m pytest tests/test_application_runs.py::test_tool_progress_is_projected_live_and_cross_chunk_redacted tests/test_application_runs.py::test_long_known_secret_progress_tail_is_bounded_by_secret_and_flushed tests/test_application_runs.py::test_tool_progress_preserves_whitespace_between_live_reports tests/test_application_tools.py::test_projected_progress_preserves_whitespace_between_reports -q` 为 4 passed。上一轮末尾“Terra 第 2 轮尚未运行”是记录时点的误述；Terra 第 2 轮已实际运行并确认长 Secret P1 修复，本轮完成后状态转为 Terra 第 3 轮待审。

## 总控审核收口

Terra（high）共完成四轮审核：首轮发现进度主链、非文本物化、失败元数据及文档缺口；第二轮发现长 Secret 泄漏；第三轮确认长 Secret 修复并发现分块空白丢失；第四轮确认全部修复，无新增 finding，四项进度回归为 4 passed。上述轮次为最终准确对应，前文轮次误述保留为历史。原 Luna（max）Worker 完成三轮返工后停止修改。

总控检查：六份改动文档 UTF-8/fence 通过，十份冻结文件检查通过，git diff --check 通过。全量 1524 passed、3 skipped 为首版实现证据；返工后采用所列受影响定向证据，不将旧全量结果当作最终版本重跑结果。真实 Provider A02 依用户“做完我配了再测”保持未完成；W01 工程审核通过，不表示 T11 整包完成。
