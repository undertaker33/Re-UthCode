# T01：搭起 Agent Core 的骨架

假设用户输入：“找出测试失败的原因并修复它。”模型不能直接看到本地项目，也不能直接修改文件。它需要一个系统把项目状态转换成上下文，把可执行操作转换成工具，再把每一步结果送回模型。这个围绕模型工作的系统，就是 Agent 的运行骨架。

## 从四个角色理解 UthCode

UthCode 将职责分成四层：

```text
Interface → Application → Core
                    ↓
               Integration
```

- Interface 接收用户输入并展示事件，例如 TUI 和 CLI。
- Application 选择配置、创建运行，并把各部分组合起来。
- Core 定义消息、工具调用、状态和 Agent Loop，不依赖具体界面或模型厂商。
- Integration 负责模型 SDK、配置文件、文件系统和进程等外部能力。

这种划分的关键，不是目录整齐，而是让“Agent 如何思考和行动”不被某个终端界面或 Provider 绑住。删除 TUI 后，Agent Loop 仍然成立；替换模型厂商后，工具与权限语义也不需要重写。

## Provider 是模型与 Core 之间的边界

Core 不直接调用 Anthropic 或 OpenAI SDK，而是只认识 UthCode 自己的请求、消息、流事件和响应。Provider 的工作是完成一次翻译：

```text
UthCode GenerationRequest
  → 厂商 SDK 请求
  → 厂商流事件
  → UthCode ProviderEvent / ProviderResponse
```

因此，模型是 Agent 的决策引擎，却不是系统状态的所有者。它提出文本或 Tool Call；真正的状态更新仍由 Core 完成。

## 无界面运行为什么重要

Agent Core 如果只能藏在 TUI 里面，就很难被脚本、测试或其他产品复用。UthCode 把无界面 Application 作为正式入口：TUI、`uthcode exec` 和嵌入式调用使用同一套 Core，只在输入输出方式上不同。

这给后续章节建立了第一个不变量：界面负责交互，Core 负责语义。下一章将继续解决另一个问题——不同模型协议怎样进入这条统一边界。
