# T06 暂停、恢复与询问用户 Checklist

> 状态：实施完成，待用户验收。

## Task 1 — Core 交互协议与事件

- [x] `src/uthcode/core/interaction.py` 定义自有交互标识、请求、回答、选项和恢复命令模型。
- [x] 交互模型不依赖 Application、Interface、第三方 SDK、异步原语或持久化实现。
- [x] Core 事件能够表达暂停原因、待处理交互、恢复与终态，不泄漏第三方类型。
- [x] `tests/test_agent_interaction.py` 覆盖模型校验、序列化边界、选项约束与非法输入。
- [x] 负向扫描证明交互协议中不存在 `Future`、`Event`、`Queue`、`Task`、`Lock` 等运行时协调对象。

## Task 2 — Core 显式 Continuation 与暂停边界

- [x] Agent Loop 以执行分段运行，每段只在暂停边界或终态结束。
- [x] 暂停结果显式返回恢复所需事实，不在 Core 内等待用户响应。
- [x] Provider 部分输出、同轮继续、异步预处理器暂停、工具安全边界和 Ask 工具调用结果均有测试。
- [x] 暂停返回后不存在等待回答的 Core Python 栈帧或活动响应等待任务。
- [x] Core 的 T06 暂停路径不持有 `Future`、`Event`、`Queue`、`Task`、`Lock` 或等价等待器。
- [x] 错误、取消、重复恢复和无效 continuation 均有确定行为与测试。

## Task 3 — Application Turn 协调与控制工具隔离

- [x] Application 私有驱动器负责连续执行 Core 分段并统一输出事件与终态结果。
- [x] Application 私有状态拥有事件队列、终态 Future 和暂停回答 waiter；Core 不拥有这些对象。
- [x] 公共 TurnHandle 能查询运行/暂停/终态、读取待处理交互、提交类型化恢复命令并取消 Turn。
- [x] 错误 Turn、错误交互 ID、过期回答和重复回答均被拒绝，且不会污染活动槽位。
- [x] 暂停、恢复、取消、异常和正常结束都会清理私有任务与等待器。
- [x] Ask 控制工具只由 Application 自动注入，不进入普通工具注册表或 Provider 工具实现。

## Task 4 — 非交互 CLI 暂停收口

- [x] CLI 能识别各类暂停事件，在 stderr 输出不含敏感内容的安全摘要。
- [x] `exec` 遇到暂停时只请求一次取消，并持续消费事件直至唯一取消终态。
- [x] 暂停路径不读取 stdin、不自动回答、不自动重试，也不构造恢复命令。
- [x] 暂停路径不在 stdout 输出伪 final，退出码为 1；键盘中断仍返回 130。
- [x] CLI 测试不直接访问 Core 或 Application 私有协调状态。

## Task 5 — 默认 TUI 暂停与结构化问答

- [x] TUI 使用独立交互状态展示自由文本、单选、多选和确认请求。
- [x] TUI 提交回答时只调用 Application 公共恢复入口。
- [x] 暂停期间输入焦点、快捷键、重复提交、取消和恢复后的消息流均有测试。
- [x] TUI 退出或取消时不会遗留后台 Turn、waiter 或事件消费任务。

## Task 6 [接入主流程] — 统一活动 Turn 调用链

- [x] Core、Application、CLI 与 TUI 通过正式公共边界完成接线。
- [x] Ask 工具自动可用且不会出现在常规工具管理、Provider 集成或用户配置注册路径中。
- [x] 同一 Turn 可经历多次暂停/恢复，事件顺序与最终结果保持一致。
- [x] 主流程接入没有新增兼容层、别名、包装入口或双轨逻辑。

## Task 7 [端到端验证] — Headless、CLI 与 TUI 全链验收

- [x] `test_headless_ask_user_round_trip_resumes_same_turn` 通过。
- [x] `test_exec_cancels_turn_when_agent_pauses` 通过。
- [x] `test_tui_pause_resume_and_ask_user_pilot` 通过。
- [x] Anthropic、OpenAI Responses、OpenAI Compatible 三组 Provider 集成测试通过。
- [x] 自由文本、单选、多选、确认、连续两次询问、取消和错误恢复均有端到端证据。
- [x] 测试证明暂停期间 Core 不持有用户回答 waiter，Application 清理全部私有协调资源。

## Task 8 [遗留负担清理] — 删除重复职责与持久恢复占位

- [x] 删除被本任务替代的旧暂停等待器、旧入口、旧测试与不可达分支。
- [x] 扫描确认不存在禁止的旧模块名、兼容别名、双轨模型或重复职责实现。
- [x] 扫描确认 Core 暂停路径不存在异步协调原语，Ask 不位于 Core 普通工具或 integrations。
- [x] 全量 `pytest`、编译检查和安装检查通过。
- [x] `git diff --check`、UTF-8 校验、Markdown 围栏校验和工作区状态检查通过。
- [x] Feedback 记录改动、测试命令、输出摘要、未决风险和逐项 Checklist 证据。
