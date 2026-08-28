# F01：TUI 回复链路与 Session 恢复修复 Tasks

## Worker 分组、顺序与依赖

| Worker | 执行任务 | 前置 | 写集合与并行边界 |
| --- | --- | --- | --- |
| W01 | T01 | 无 | 独占 Context/Prompt/request message projection 与对应测试 |
| W02 | T02 -> T03 | W01 | 独占 Provider reasoning mapping、Core terminal contract、History entry/reconstruction 与对应测试 |
| W03 | T04 | W02 | 独占 Application Session replay DTO、lazy lifecycle、command/session tests；不修改 TUI |
| W04 | T05 -> T06 | 无 | 独占 process output decoding、Application Tool summary 与 Tool activity contract；可与 W01～W03 并行 |
| W05 | T07 -> T08 | W02、W03、W04 | 独占 `interfaces/tui/` 与 TUI tests，避免多个 Worker 同写 `app.py` |
| W06 | T09 -> T10 -> T11 | W01～W05 | 独占跨层接入、端到端验收、当前事实文档、Checklist 和最终清理 |

所有 Worker 只能由用户通过对应 Prompt 显式派发。首次派发后，原始需求、Spec、Tasks、Prompts 和 Checklist 文案冻结；Checklist 只允许将已验证项从 `[ ]` 改为 `[x]`。W04 与 W01～W03 只有写集合确实不重叠时才可并行，W05/W06 严格等待前置 Feedback。

## T01：Prompt、Context 与当前用户消息边界

### 任务目标

消除正式请求中的 Prompt 双轨和无分隔 part 拼接，让所有 Context source 保持冻结 authority，同时让当前 user 作为逐字、独立、最后的会话语义进入 Provider。

### 新增文件

- 无预设；只有现有测试文件无法清晰承载正式入口回归时才新增定向测试文件。

### 修改文件

- `src/uthcode/core/context.py`、`prompt.py`、`provider.py`
- `src/uthcode/application/context.py`、`generation.py`
- `src/uthcode/integrations/providers/openai_compat.py`、`openai_responses.py`、`anthropic.py`（仅统一 message projection 命中时）
- `tests/test_context_compiler.py`、`test_system_prompt.py`、`test_provider_contract.py` 及三 Provider integration tests

### 删除文件

- 无预设整文件删除；删除确认无生产调用方的平行 Prompt 构造或适配 helper。

### 文件职责及实施内容

- 保留 T09 的 typed source、authority、selection、budget、stable prefix 与 current user protected-tail 语义。
- Context snapshot 到 Message 的正式转换不得把 runtime/environment/current user 合并成不可区分的字符串；每个来源必须有确定结构和分隔。
- Provider mapper 必须保留独立 message/part 的语义边界；禁止 `join` 无分隔融合不同 source。
- 最后一条 current user 正文逐字等于输入，重复文本、steering 和相邻 user message 不得内容去重。
- 普通历史中的伪标签不得进入 Instruction Plane；不得把 Runtime/Environment 擅自升级为 system role。
- 接入或删除孤立 `build_system_prompt()` 路径，生产与测试只能验证同一组合入口。

### 依赖任务

- 无。

### 参考资料定位

- F01 原始需求、Spec D-F01-01。
- `docs/context/A01-AgentRuntime/AgentRuntime-Context.md`、`A03-State/State-Context.md`。
- T03 System Prompt 与 T09 Context Compiler 的归档/活跃设计和 Feedback，仅作冻结语义证据。

### 完成边界

三 Provider 的正式 request fixture 均证明当前 user 精确、独立、位于尾部；runtime/environment 改变不污染 user；系统指令和普通历史 authority 不变；没有第二 Prompt 入口。

## T02：Provider reasoning 与正式终态合同

### 任务目标

统一 Provider typed reasoning、公共流事件和普通 final 的边界，修复跨 identity 降级、chunk 交错和 reasoning-only 空成功。

### 新增文件

- 无预设。

### 修改文件

- `src/uthcode/core/provider.py`、`agent.py`、`agent_events.py`
- `src/uthcode/integrations/providers/openai_compat.py`；其它 Provider adapter 仅在对称合同命中时修改
- `tests/test_provider_contract.py`、`test_agent_events.py`、`test_agent_loop.py`、三 Provider integration tests

### 删除文件

- 删除跨 identity `ReasoningPart -> TextPart` fallback 和被替代的错误 fixture/断言。

### 文件职责及实施内容

- 保持 reasoning delta/part/native carrier 的独立类型和到达顺序。
- 同 identity、同 active Tool continuation 保留 Provider 协议所需 carrier；不同 identity 忽略不兼容 carrier，但保留正式 TextPart 与 ToolCall。
- 同 chunk 同时含 content/reasoning、reasoning→content、content→reasoning→content、多 reasoning segment 均形成确定事件序列。
- Provider-independent terminal 校验要求普通 stop 至少存在非空正式 TextPart；reasoning-only 或空 TextPart stop 为受控 invalid response。
- reasoning+ToolCall 仍是合法 progress；final_text 只来自 TextPart。

### 依赖任务

- T01。

### 参考资料定位

- F01 Spec T02、D-F01-01。
- T01 Provider、T03 System Prompt、T05 Agent Loop 的 frozen contracts。

### 完成边界

Provider contract 与 Agent Loop tests 覆盖完整流矩阵；跨 identity 请求中 reasoning 既不作为 native carrier也不作为 content；所有 terminal 只有一个明确结果。

## T03：Transcript 逻辑消息与 reasoning 持久化

### 任务目标

去除 per-part 完整 Message 复制，建立可恢复、可回放且不会混淆 reasoning/final 的唯一逻辑消息重建合同。

### 新增文件

- 无预设。

### 修改文件

- `src/uthcode/core/history.py`、`context.py`
- `src/uthcode/application/history.py`、`context.py`
- `src/uthcode/integrations/session_files.py`（仅兼读现有 envelope 所需）
- `tests/test_history_contract.py`、`test_context_compiler.py`、`test_session_files.py`、`test_w04_session_commands.py`

### 删除文件

- 删除每个 part payload 中重复完整 Message 的新写入路径和仅服务该重复形状的去重逻辑。

### 文件职责及实施内容

- 新 entry 只保存自身 typed part、role、message identity、part order 和必要 native carrier。
- 重建按 session/turn/role/message identity 聚合相邻 parts，拒绝不连续复用 identity，保留相同文本的独立消息。
- ReasoningPart 与 TextPart 分别持久化和重建；TUI replay 可见 reasoning，但 final projection 永不包含它。
- ToolCall/ToolResult 的 ID、顺序、完整 semantic unit 与 durability cursor 不变。
- 读取现有 v3 full-message payload 并投影为同一逻辑模型，不原地改写旧文件，不新增迁移服务或双 writer。

### 依赖任务

- T02。

### 参考资料定位

- F01 Spec T03、D-F01-01/02。
- T09/T09-1 Transcript、Timeline、strict sequence、durability 和 resume 设计。

### 完成边界

新旧格式均能精确 round-trip 多 part assistant/tool message；新文件体积随实际 part 内容线性增长；reasoning/final 类型、Tool pair 和重复用户文本全部保持。

## T04：Session 安全回放与惰性生命周期

### 任务目标

由 Application 提供完整安全回放记录，并使持久 Session 只在真实对话或显式 Session 命令需要时创建。

### 新增文件

- 无预设；优先扩展现有 Application Session/command value models。

### 修改文件

- `src/uthcode/application/sessions.py`、`generation.py`
- `src/uthcode/application/commands/models.py`、`builtins.py`
- `src/uthcode/interfaces/cli.py`（仅移除无 prompt 的提前 ensure）
- `tests/test_w04_session_commands.py`、`test_application.py`、`test_cli.py`、Session tests

### 删除文件

- 删除 TUI/CLI 冷启动无条件 `ensure_session()` 的 Application 依赖入口；TUI 文件由 W05 修改。

### 文件职责及实施内容

- Application 将 durable Transcript 聚合为 JSON-safe/interface-neutral replay records：user、steering、reasoning、formal assistant、safe tool terminal。
- Tool replay 复用 Application 安全摘要/脱敏能力，不复制 raw arguments/result/native payload。
- resume staging 成功后才返回完整 replay；busy/corrupt/unknown/storage failure 保持当前 Session 和 replay 未改变。
- Application 可在无 active Session 时安全提供帮助、状态、catalog、关闭和创建 Run 所需非持久事实。
- 第一条普通输入在显示用户永久记录和启动 Turn 前确保一个 Session；失败不产生半个 Turn。
- `/new` 显式创建一个，`/resume` 直接打开目标，`exec <prompt>` 仅因真实 prompt 创建。

### 依赖任务

- T03。

### 参考资料定位

- F01 Spec T04、D-F01-02/03。
- T09 Session commands、staged resume 与 single-writer Feedback。

### 完成边界

Application tests 证明完整安全 replay、原子失败、无副作用 hydrate 和所有 lazy lifecycle 场景；Interface 不接触 Session 文件或 History 类型。

## T05：Windows 进程输出解码

### 任务目标

修复 Windows shell 中文 stdout/stderr 的 replacement mojibake，同时保持既有 Bash 执行、取消和结果合同。

### 新增文件

- 无。

### 修改文件

- `src/uthcode/integrations/tools/process_tools.py`
- `tests/test_builtin_process_tool.py`

### 删除文件

- 无。

### 文件职责及实施内容

- 将 bytes→text 收口到单一私有解码路径。
- UTF-8 strict 优先；Windows 根据实际执行 shell 的系统编码事实做有限 fallback；全部失败后才 replacement。
- stdout/stderr 分别处理，非零退出、超时、取消、输出上限和 unsandboxed 语义不变。
- 不引入 chardet 类猜测依赖、全局代码页修改或第二进程工具。

### 依赖任务

- 无。

### 参考资料定位

- F01 Spec T05。
- 当前 process tool 实现与 Windows 平台测试。

### 完成边界

UTF-8、Windows 常见 OEM/ANSI、非法混合 bytes、空输出、非零退出均有确定测试；Windows `dir` 中文名真实入口无 replacement character。

## T06：Tool 活动摘要与 FIFO 展示合同

### 任务目标

按 T05 原设计保留安全摘要，同时消除 Tool 名重复并为多 Tool batch 建立可观察的 FIFO UI-neutral 合同。

### 新增文件

- 无。

### 修改文件

- `src/uthcode/application/tools.py`、`runs.py`（仅事件投影确有需要时）
- `tests/test_application_tools.py`、`test_application_runs.py`、`test_agent_loop.py`

### 删除文件

- 删除重复拼接 Tool 名的单一一侧实现；不删除原脱敏器。

### 文件职责及实施内容

- 明确 `tool_name` 与安全 `command`/参数摘要的展示所有权，使任何 Interface 组合后名称只出现一次。
- 保持 ToolStarted transient activity、ToolFinished permanent terminal 的当前产品语义。
- 同 batch 所有 ToolFinished 按 call FIFO，各 call 恰好一次；denied/error/cancelled/skipped 有文本状态。
- 原设计继续脱敏 API key、token、敏感 assignment/option、配置 secret 和 ambient 环境值；保留 `0/1` 例外。
- Write/Edit content、Grep pattern、unknown/custom arguments、ToolResult 正文继续不可见。

### 依赖任务

- 无；与 T05 由同一 Worker 串行。

### 参考资料定位

- F01 D-F01-04。
- `docs/work/archive/T05-ReAct与AgentLoop/` 原始任务、W02/W04 Feedback。
- 提交 `f32ad439aaf200adc98d177540ffdf6344668254` 与当前 tests。

### 完成边界

所有默认 Tool 的 name/summary 组合无重复；多 Tool FIFO、所有终态与原脱敏回归通过；不泄露任何构造的 secret/ambient value。

## T07：TUI 时序化流式投影与 reasoning 视觉

### 任务目标

在 append-only scrollback 下同时保证 reasoning 实时流式、正式回复实时预览、最终永久顺序和独立颜色。

### 新增文件

- 无。

### 修改文件

- `src/uthcode/interfaces/tui/rendering.py`、`terminal.py`、`app.py`、`state.py`（仅现有状态职责命中时）
- `tests/test_tui.py`

### 删除文件

- 删除按 kind 分组 flush 的多字典状态和通过角色文字猜颜色的逻辑。

### 文件职责及实施内容

- 使用单一 chronological projection 表达当前活跃 block、segment、Markdown buffer、角色标题和颜色。
- 消费 ReasoningStarted/Finished 的 segment boundary；多段 reasoning 独立显示。
- Reasoning 每个刷新周期更新 preview，安全块可增量永久提交；bar 使用显式 reasoning 语义色。
- Assistant delta 独立实时预览，消息完成后使用权威 TextPart 永久提交一次；不得因 late reasoning 重排 scrollback。
- 同一批永久内容合并为一次 synchronized output；窗口 resize、fence、tool force-flush 和 correction 保持。
- pending preview 不得把 reasoning 与 assistant 尾部拼成一个无类型块。

### 依赖任务

- T02、T03、T06。

### 参考资料定位

- F01 Spec T07、D-F01-01。
- `docs/context/TUI/README.md` 的主缓冲区、append-only、MarkdownStream 与同步输出约束。

### 完成边界

交错流矩阵在生成期间有多次 preview 更新；永久输出 reasoning 在前、final 一次；不同 segment 和角色有正确标题，reasoning/final bar 色值明确不同。

## T08：TUI `/resume` hydrate

### 任务目标

把 Application 的完整安全 replay 接入 TUI，并在长历史下保持界面可调度和恢复后的上下文连续性。

### 新增文件

- 无。

### 修改文件

- `src/uthcode/interfaces/tui/app.py`、`terminal.py`、`rendering.py`（仅 replay 展示复用需要时）
- `tests/test_tui.py`、`test_w04_session_commands.py`

### 删除文件

- 删除 SessionChanged 后仅清空投影、不 hydrate 的旧分支和 TUI 启动提前 ensure。

### 文件职责及实施内容

- TUI 仅消费 replay DTO，复用 user/reasoning/assistant/tool 的正式渲染入口。
- 按 durable turn/有界 record batch 顺序输出，每批 synchronized，批间让出事件循环。
- hydrate 不伪造 TurnStarted/AgentEvent，不调用 Provider，不写 Transcript，不污染 live stream state。
- resume 成功后替换 Run；失败保持旧界面和 Session；`/new` 不回放旧内容。
- 无 active Session 的欢迎区、help/status/picker/exit 保持正常；首条普通输入 lazy ensure 失败时不显示永久 user record。

### 依赖任务

- T04、T07。

### 参考资料定位

- F01 Spec T04/T08、D-F01-02/03。
- T09 W04 Session command/TUI Feedback 和当前 TUI context。

### 完成边界

跨进程完整 Session 可按原 sequence 回放全部安全记录；长回放不冻结事件循环；随后新消息只追加一次并携带已恢复上下文。

## T09：[接入主流程] 唯一请求、历史、Session 与 TUI 链路

### 任务目标

把各 Worker 能力接入唯一 `create_application -> create_run -> start_turn`、Session commands 与 TUI 事件链，删除被替代入口。

### 新增文件

- 无预设。

### 修改文件

- T01～T08 实际命中的正式组合入口和跨层集成测试。

### 删除文件

- 经 caller audit 确认无用的 Prompt 双轨、reasoning fallback、重复 history payload、提前 Session ensure、重复 Tool 标题和 renderer 状态。

### 文件职责及实施内容

- 验证普通、post-tool、post-resume、model switch、new Session 和 Headless/CLI/TUI 全部走同一合同。
- 确保 Context/History/Session/Secret/Provider 权威不下沉到 Interface。
- 确保 active Run 的 reasoning/tool continuity 与 terminal durable history/replay 各自使用正确 typed view。

### 依赖任务

- T01～T08。

### 参考资料定位

- F01 全部 Feedback；A01/A03/A04/TUI 当前上下文。

### 完成边界

正式入口不存在第二组合路径；所有跨层回归通过，架构依赖方向不变。

## T10：[端到端验证] 四现象、九类问题与真实入口验收

### 任务目标

从真实入口逐项证明原始四现象和九类根因均已关闭，并同步当前事实文档。

### 新增文件

- 仅在现有测试无法承载完整场景时增加职责单一的 F01 E2E test。

### 修改文件

- 跨层 E2E tests
- `docs/context/A01-AgentRuntime/AgentRuntime-Context.md`
- `docs/context/A03-State/State-Context.md`
- `docs/context/A04-Orchestration/Orchestration-Context.md`
- `docs/context/TUI/README.md`
- `docs/user-manual/getting-started.md`、`commands.md` 及 `docs/README.md` 维护映射命中的其它当前文档
- F01 Checklist 与 W06 Feedback

### 删除文件

- 本包产生的临时探针、Session、输出文件与缓存。

### 文件职责及实施内容

- 自动 E2E 复现输入 `你好`、模型询问、环境询问、`？`，捕获真实 request 和永久输出。
- 跨进程 seed/close/restart/resume/continue；覆盖 reasoning、final、tool batch、model identity 和长 replay。
- Windows Terminal 人工验证流式刷新、bar 颜色、中文输出、scrollback、resize 和快捷键。
- 执行定向、架构、全量和工程校验，记录未验证项。

### 依赖任务

- T09。

### 参考资料定位

- F01 原始需求和 Spec 验收 1～12。
- `docs/README.md` 文档维护映射。

### 完成边界

十三项问题映射均有自动或明确人工证据；当前事实文档与最终 `src/ + tests/` 一致；未运行项未被写成通过。

## T11：[遗留负担清理] 单一路径与历史负担收口

### 任务目标

清除本包替代的旧行为、重复状态与临时产物，确认没有以兼容或未来扩展名义留下第二路径。

### 新增文件

- 无。

### 修改文件

- 必要的最终 tests、F01 Checklist、W06 Feedback、`docs/Context-Index.md`。

### 删除文件

- 无调用方 helper、旧 fixture/expectation、临时脚本和测试产物；不删除用户文件或旧 Session。

### 文件职责及实施内容

- 扫描 Prompt 双轨、reasoning→text fallback、full-message payload duplication、cold-start ensure、kind-grouped stream state、重复 Tool name。
- 复核无第二 replay store、Session migration framework、encoding detector、Secret policy 或 UI history authority。
- 清理后重跑最小定向、架构、全量和文档 guard。
- F01 全部 Checklist 与 Feedback 有证据后更新为 `implemented_unarchived`；不归档、不执行 Git 写。

### 依赖任务

- T10。

### 参考资料定位

- F01 全部文档与 Feedback；`docs/rules/WorkPackageRules.md`。

### 完成边界

否定扫描和全部验证有精确结果；能力欠账仍为无；F01 留在 `docs/work/` 等待用户审查和手动归档。
