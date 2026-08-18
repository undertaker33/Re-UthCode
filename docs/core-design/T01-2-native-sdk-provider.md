# T01-2：把模型协议翻译成统一语言

在 Agent Loop 看来，模型只需接收上下文并返回文本或 Tool Call。但在真实 API 中，Anthropic Messages、OpenAI Responses 和 OpenAI-compatible Chat 对消息、流事件和工具参数的表达并不相同。

## 统一语义，而不是抹平协议

UthCode 直接使用官方 SDK，并在各自的 Integration 中完成协议翻译。Core 看到的是统一语义：

- 文本与 reasoning 增量；
- 完整的 Tool Call 名称、ID 和参数；
- Usage、完成原因与稳定错误；
- 可以加入下一轮上下文的 Assistant Message。

厂商特有字段仍可保存在协议数据中，但不会泄漏成 Core 对某个 SDK 类型的依赖。这样既保留协议保真度，也维持运行时的 Provider 无关性。

## 流式响应也是一种状态机

Tool Call 的名称和 JSON 参数可能分散在多个事件里到达。因此 Provider 适配器不能只把事件逐条转发，而要维护一个小型聚合过程：识别属于同一调用的片段、按 ID 拼接内容，并在终态到达时确认所有调用都已完成。

```text
多个 SDK 增量
  → 按 item / call ID 聚合
  → 验证唯一终态
  → 生成完整 ProviderResponse
```

如果流提前结束、Tool Call 尚未闭合，或同一项出现互相矛盾的完成信息，UthCode 会把它视为无效响应，而不是把残缺状态提交给 Agent Loop。

## 错误也必须穿过边界

认证失败、限流和网络错误会转换为 UthCode 的稳定错误类型。API Key 只允许来自用户级配置的 `api_key` literal 或 `env:VARIABLE_NAME`，进入 SDK 前解析为不可序列化且 `repr` 脱敏的内部凭据；它不成为普通配置值、Prompt、History、Event、diagnostics 或运行状态的一部分。

到这里，模型输出已经被翻译成 Core 能理解的语言。接下来要看用户输入如何从不同入口抵达这套 Core。
