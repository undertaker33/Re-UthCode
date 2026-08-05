# T01-2-移除pydantic改用原生SDK Spec

## 背景

现有三个真实 Provider 已经通过统一 Core 契约接入 Application，但运行链路仍经过 Pydantic AI 的模型、消息、事件和 Codec。为补回被中间归一化削弱的厂商协议信息，当前实现还维护了原始流 Recorder、私有字段访问和第二次事件转换，增加了复杂度、协议失真风险和依赖负担。

本任务对真实 Provider Integration 做一次破坏式替换：保留已经验收的 UthCode Core 与 Application 边界，删除 Pydantic AI 中间层，由官方 Anthropic 和 OpenAI 异步 SDK 直接完成请求序列化、流事件解析和错误映射。

## 目标

- 三个真实 Provider 分别直接接入 Anthropic Messages、OpenAI Responses 和 OpenAI-compatible Chat Completions。
- 三个 Provider 直接满足现有 Core Provider 契约，不改变公共消息、事件、Usage、错误、取消和终态语义。
- 保持文本、Reasoning、Tool Call、Native Item、Usage、错误、取消和终态行为的协议保真。
- 删除 Pydantic AI Bridge、Codec、Recorder、运行时依赖和测试入口，不保留兼容层或双轨实现。
- 默认测试完全离线，Provider 构造不发起网络请求。
- CLI、TUI、配置加载和 Headless Application 的已验收行为不回退。

## 能力清单

### Task 1：建立原生 SDK 共用辅助边界

- 建立仅包含厂商无关纯辅助逻辑的内部模块。
- 支持 JSON-safe 数据校验、Usage 整数读取、异步流关闭和取消检查。
- 继续以 Core 契约作为唯一 Provider 抽象，不新增基类、管理器、注册表或路由层。

### Task 2：替换三个真实 Provider Integration

- Anthropic Provider 直接处理 Messages 请求和公开流事件，保留 Thinking、Signature、Redacted Thinking、Tool Use、顺序、Usage 和 Stop Reason。
- OpenAI Responses Provider 直接处理 Responses 请求和公开流事件，保留 Reasoning、Message、Function Call、标识、顺序、Usage、去重和终态验证。
- OpenAI-compatible Provider 直接处理 Chat Completions 请求和 Chunk，保留 Reasoning Content、按索引聚合的 Tool Call、Usage 和 Finish Reason。
- Factory 直接构造官方 SDK Client 和对应 Provider；构造过程不进行网络请求。
- 项目生产依赖改为直接声明官方 SDK。

### Task 3：重写协议测试并保持行为等价

- 使用官方 SDK 公开类型或只模拟公开 Client 方法的 Test Double 验证三种协议。
- 覆盖请求序列化、文本与 Reasoning 增量、Tool Call、Native Item 往返、Usage、错误、取消、流关闭和终态。
- 覆盖重复帧、冲突帧、异常 EOF、未完成调用和跨 Provider Native Item 隔离。
- 默认测试不读取真实 API Key，不访问网络。

### Task 4：[接入主流程] 收敛构造与架构边界

- 正式 Application 调用链只经过唯一 Factory 和原生 SDK Provider。
- Application 与 Interface 不感知官方 SDK 类型；Core 不依赖官方 SDK或基础 Pydantic。
- 删除旧桥接入口及其源码、测试引用和公共导出。
- Fake Provider、配置结构和现有交互入口保持不变。

### Task 5：[端到端验证] 验证三 Provider 与现有交互入口

- 从正式入口离线验证 Fake Headless、三个真实 Provider Mock Stream、配置、Factory、CLI 与 TUI。
- 验证 Provider 错误、显式取消和任务取消在 Application 与 Interface 中保持现有行为。
- 仅在用户已配置相应凭据且显式启用 live 开关时执行真实端点验证。
- 通过离线微基准确认普通文本增量不再经过双重事件转换或复制完整流历史。

### Task 6：[遗留负担清理] 清理源码、测试和 Conda 环境

- 从源码、测试和项目依赖中清除 Pydantic AI、Pydantic Graph 及旧桥接标识。
- 从 `re-uthcode` 环境卸载仅由当前项目需要的 Pydantic AI 发行包，重新安装项目并检查依赖完整性。
- 保留官方 SDK 仍然依赖的基础 Pydantic 及其他共享依赖。
- 确认不存在私有流字段访问、兼容 Shim、Alias、双轨开关、重复职责或不可达旧代码。

## 非功能要求

- 依赖方向保持 `interfaces → application → core`，Application 的组合根可依赖 Integration；Core 不反向依赖外层。
- Provider 特有协议状态只能存在于对应 Integration 物理模块。
- 所有流在正常、错误、显式取消和任务取消路径均必须关闭。
- 每个完成事件只发布一次；异常、失败或不完整终态不得产生成功完成事件。
- 错误归一化不得复制可能包含 API Key、请求体、响应体或完整 Header 的第三方异常文本。
- 默认测试离线且可重复；真实端点测试必须显式授权。
- 普通文本增量只维护必要的有界状态，不复制完整流历史。
- 不访问第三方对象的私有字段，不以无边界动态类型绕过协议边界。

## 设计骨架

```text
Interface / Headless Caller
            ↓
       Application API
            ↓
        ProviderPort
   ┌────────┼───────────┐
   ↓        ↓           ↓
Anthropic  OpenAI      OpenAI-compatible
Messages   Responses   Chat Completions
   ↓        ↓           ↓
官方异步 SDK 公开请求与流事件
```

三个 Provider 共享的内部模块只承担厂商无关的 JSON、Usage、取消和资源关闭辅助。请求序列化、协议状态、事件聚合、终态判断和官方异常映射分别归属对应 Provider，不建立新的通用 Provider 框架。

Native Item 继续作为同 Provider 多轮协议保真的载体；来自其他 Provider 的 Native Item 必须被忽略并回退到标准 Core Part，不允许跨协议泄漏厂商数据。

## Out of Scope

- 修改 Core Provider 契约、Core Message/Event 或 Application API。
- 修改配置 TOML 结构、Provider Kind、模型选择语义、CLI 参数或 TUI 交互。
- 新增 Provider、Provider 自动发现、能力注册表、Router、Fallback、Plugin 或负载均衡。
- 建立统一 HTTP Client、手写厂商 HTTP 协议或新增自动重试策略。
- 实现 Responses WebSocket、Realtime、Prompt Cache 扩展或厂商补丁表。
- 修改 System Prompt、Agent Loop、Tool、Permission、Context、Memory 或其他后续能力。
- 改写已经冻结的 T01、T02 工作包或旧 UthCode。
- 删除官方 SDK 仍需要的基础 Pydantic 或共享网络依赖。
- 自动执行真实端点请求、Git 写入或工作包归档。

## 验收标准

- 三个真实 Provider 均直接消费官方 SDK 公开请求和流事件，并保持现有 Core 契约与 Application 行为。
- Anthropic 的 Thinking、Signature、Redacted Thinking、Tool Use、顺序、Usage、合法终态和取消关闭通过往返验证。
- OpenAI Responses 的 Reasoning、Message、交错 Function Call、标识、顺序、去重、冲突、失败终态和 Usage 通过验证。
- OpenAI-compatible Chat 的 Reasoning Content、多个 Indexed Tool Call、Tool Result、Nullable Usage 和合法终态通过验证。
- Factory 构造所有 Provider 时不访问网络，正式 Application 只通过唯一 Factory 接入。
- 全量离线测试、编译检查和依赖完整性检查通过；live 测试默认跳过。
- 项目生产依赖直接声明官方 OpenAI 与 Anthropic SDK，不再声明 Pydantic AI 或 Pydantic Graph。
- 源码、测试、项目元数据和根 README 中不存在旧 Pydantic AI 运行时标识，旧桥接文件不存在。
- `re-uthcode` 环境中 Pydantic AI 发行包不可发现，官方 SDK 可导入且依赖关系完整。
- 离线处理 10,000 个纯文本增量时不创建 Pydantic AI 对象、不访问网络、不复制完整流历史；结果记录于实施 Feedback，不设固定毫秒门槛。
- 冻结的 Core、Application、配置、Fake Provider、CLI、TUI、T01/T02 工作包及旧参考仓库没有被修改。
