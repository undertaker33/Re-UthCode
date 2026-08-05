# UthCode T03：System Prompt 设计任务书

## 1. 分析基线

### 1.1 目标仓库

```text
https://github.com/undertaker33/Re-UthCode
```

固定分析与实施基线：

```text
047bd155c3980584f6b38da6e20fa62241cf7498
```

该提交为 T01-2「移除 Pydantic AI 并改用原生 SDK」合并提交。编码开始前必须确认当前分支仍基于该提交，或仅包含用户明确允许的后续工作包文件；不得基于未核对的最新 HEAD 实施。

### 1.2 最高级约束

实施前必须完整读取：

```text
AGENTS.md
SRe-AGENTS.md
docs/work/README.md
```

本任务遵守以下冻结边界：

- `core/` 拥有 System Prompt 的权威语义和构建逻辑；
- `application/` 负责把运行上下文与当前模型身份转换为 Core Prompt 输入，并在每次生成前注入；
- `integrations/` 只负责把统一 System Prompt 映射为各 Provider 的公开协议字段；
- `interfaces/` 不拼接、不覆盖、不保存第二份 System Prompt；
- 不使用 LangGraph、LangChain Agent 或第三方 Agent Runtime；
- 不兼容旧 UthCode 的 Prompt API、目录、状态和输出格式；
- 不创建 Tool、Permission、Context、Memory、Hook、Skill、MCP、Subagent 等未来能力占位。

### 1.3 已完成前置任务包

已完成并通过验收：

```text
docs/work/T01-项目骨架与Provider抽象/
docs/work/T02-SlashCommand与默认TUI/
docs/work/T01-2-移除pydantic改用原生SDK/
```

必须重点读取：

```text
T01：
- T01-项目骨架与Provider抽象.md
- T01-项目骨架与Provider抽象-spec.md
- T01-项目骨架与Provider抽象-tasks.md
- 相关 feedback

T02：
- T02-SlashCommand与默认TUI.md
- T02-SlashCommand与默认TUI-spec.md
- T02-SlashCommand与默认TUI-tasks.md
- feedback/W01-configuration-runtime-feedback.md
- feedback/W03-interface-delivery-feedback.md

T01-2：
- T01-2-移除pydantic改用原生SDK.md
- T01-2-移除pydantic改用原生SDK-tasks.md
- T01-2-移除pydantic改用原生SDK-checklist.md
- feedback/W01-native-sdk-provider-feedback.md
- W02 对应反馈文件
```

前置任务提供的稳定边界：

- UthCode 自有 `GenerationRequest`、`Message`、`ProviderPort`、Provider Event 和取消模型；
- `UthCodeApplication`、`GenerationHandle`、模型切换和 Headless API；
- `EffectiveConfig`、`ProviderProfile`、`ModelProfile` 与配置加载；
- Anthropic Messages、OpenAI Responses、OpenAI-compatible Chat Completions 三个原生 SDK Integration；
- 默认 CLI、`uthcode exec` 和 Textual TUI；
- Interface 只能依赖 Application 的架构边界。

### 1.4 原 UthCode 参考

原仓库：

```text
https://github.com/undertaker33/UthCode
```

固定参考 Commit：

```text
1c3507b761e48ac38d846bc39700ce0039f84a04
```

原任务包：

```text
docs/archive/work/Day2-SystemPrompt设计任务书/
├── Day2-SystemPrompt设计任务书.md
├── Day2-SystemPrompt-spec.md
├── Day2-SystemPrompt-tasks.md
├── Day2-SystemPrompt-checklist.md
└── Generic-Agent-SystemPrompt.zh-CN.md
```

直接参考源码：

```text
src/uthcode/prompts/builder.py
src/uthcode/prompts/context.py
src/uthcode/prompts/base.py
src/uthcode/prompts/environment.py
src/uthcode/prompts/sections.py
```

只提取以下已验证思想：

- Prompt 使用稳定分段组织；
- 分段有确定顺序；
- 空分段不输出；
- 运行环境可以通过显式上下文注入并固定测试；
- Prompt 测试锁定关键 contract，不锁死全文快照；
- 清除 MewCode 品牌、推广文本和旧架构耦合。

不得继承：

- LangGraph `prepare_turn_node`、Graph State 或 Runtime；
- Tool、Permission、Plan、Memory、Hook、Skill、Agent Catalog 等未来字段；
- 旧 `PromptContext` 的大而全占位结构；
- 旧目录和公开 API；
- 旧任务书对未来能力的预先描述。

### 1.5 MewCode 参考

来源：

```text
/mnt/data/3_mewcode-python.zip
```

直接参考：

```text
mewcode/prompts.py
mewcode/agent.py 中 System Prompt 的调用位置
```

可参考：

- `PromptSection` 和稳定排序；
- 静态规则与运行环境分离；
- Prompt 在模型请求前统一生成。

不得迁移：

- MewCode 品牌、公众号、网站和 Go 版说明；
- Tool 名称、Team、Subagent、Deferred Tool、Hook、Memory、Plan 等当前不存在的能力；
- “无限上下文”“自动摘要”等未实现声明；
- 旧 Agent Loop 和 Conversation 耦合；
- 整文件复制。

### 1.6 官方协议资料

只使用以下官方资料确认协议映射与缓存边界：

- Anthropic Messages API：System Prompt 使用顶层 `system`，不是消息角色；
- OpenAI Responses API：System Prompt 映射为顶层 `instructions`；
- OpenAI Chat Completions：兼容端点使用 `role=system` 消息；
- Anthropic Prompt Caching：缓存按 `tools → system → messages` 的完整前缀匹配；
- OpenAI Prompt Caching：命中要求相同 Prompt 前缀。

本任务不启用、配置或抽象 Prompt Cache；只保证 Prompt 结构满足“稳定内容在前、易变运行信息在后”，避免无意义地破坏未来缓存命中。

### 1.7 用户已拍板决策

以下决策已冻结，不得在实施中重新讨论：

1. `GenerationRequest` 新增独立 `system_prompt: str | None`，普通 `Message` 不再表达 System Prompt；
2. Application 新增独立运行上下文，不把工作目录、平台和日期塞入 `EffectiveConfig`；
3. Prompt 运行环境段暴露：
   - `model_ref`；
   - Provider `protocol`；
   - `remote_model_id`；
4. 不暴露 Provider Profile ID、Base URL、配置来源或秘密字段；
5. 同一运行配置下上述身份保持稳定，模型或协议切换后的缓存重新建立属于正常行为；
6. 两个不同 `model_ref` 即使指向相同协议和远端模型，也视为不同产品选择，允许形成不同 Prompt 前缀。

---

## 2. 当前实现基线

### 2.1 当前请求模型

当前文件：

```text
src/uthcode/core/provider.py
```

当前 `GenerationRequest` 包含：

```text
messages
model
tools
reasoning
max_output_tokens
temperature
metadata
```

当前没有独立 System Prompt 字段。`Message.role` 只校验为非空字符串，没有冻结合法角色集合。

当前事实实现使用：

```text
Message(role="system")
```

这只是 T01/T01-2 在 System Prompt 尚未设计时使用的临时表达，不是本任务完成后的正式 Core 语义。

### 2.2 当前 Application

关键文件：

```text
src/uthcode/application/generation.py
src/uthcode/application/bootstrap.py
src/uthcode/application/configuration.py
src/uthcode/application/__init__.py
```

当前行为：

- `UthCodeApplication` 持有当前 Provider、配置、Model Ref 和模型切换能力；
- `start_generation()` 原样保存调用方传入的 `GenerationRequest`；
- `GenerationHandle.events()` 将请求直接交给 Provider；
- Application 不拥有工作目录、平台、日期或 Prompt Context；
- `EffectiveConfig` 只描述配置和模型，不应被扩展为运行上下文。

### 2.3 当前 Interface

关键文件：

```text
src/uthcode/interfaces/cli.py
src/uthcode/interfaces/tui/app.py
```

当前行为：

- CLI 的 `--cwd` 只进入配置发现；
- TUI 自己保存一份 `cwd` 供 Topbar 显示；
- CLI 和 TUI 都只构造单条 USER Message；
- Interface 不构造 System Prompt；
- CLI 与 TUI 的工作目录目前不是 Application 的统一运行事实。

### 2.4 当前 Provider 映射

关键文件：

```text
src/uthcode/integrations/providers/anthropic.py
src/uthcode/integrations/providers/openai_responses.py
src/uthcode/integrations/providers/openai_compat.py
```

当前临时映射：

```text
Message(role="system")
├── Anthropic          → 顶层 system
├── OpenAI Responses   → 顶层 instructions
└── OpenAI-compatible  → role=system message
```

三个 Integration 已具有正确的厂商协议落点，但 System Prompt 的 Core 表达必须由本任务替换。

### 2.5 当前测试

直接相关测试：

```text
tests/test_provider_contract.py
tests/test_application.py
tests/test_application_runtime.py
tests/test_anthropic_integration.py
tests/test_openai_responses_integration.py
tests/test_openai_compat_integration.py
tests/test_cli.py
tests/test_tui.py
tests/test_architecture_boundaries.py
tests/test_package.py
```

当前协议测试已经断言 `Message("system", ...)` 的三种映射。本任务必须改为断言独立 `GenerationRequest.system_prompt`，不得同时保留两套入口。

### 2.6 本次允许修改的前置公共边界

用户已明确批准：

- 修改 `GenerationRequest` 公共协议；
- 冻结 `Message` 合法角色并拒绝 `system`；
- 扩展 `UthCodeApplication` 的运行上下文与请求准备流程；
- 修改 `create_application()` 的组合参数；
- 修改 CLI/TUI 的 Application 装配方式；
- 修改三个 Provider Integration 的请求序列化；
- 更新所有受影响测试与 README 示例。

保持不动：

- Provider Response、Provider Event、Usage、错误和取消语义；
- Native Item 往返；
- Tool 数据模型；
- `EffectiveConfig`、TOML 结构和配置优先级；
- Provider Factory 和官方 SDK 构造；
- Slash Command Registry 与 Dispatcher；
- TUI 流式渲染、取消和模型 Picker 行为。

---

## 3. 当前任务目标

### 3.1 最终交付

T03 完成后必须具备：

1. Core 自有、无第三方依赖的 System Prompt 构建模块；
2. 独立 `GenerationRequest.system_prompt` 协议；
3. 明确的 USER、ASSISTANT、TOOL Message 角色 contract；
4. Application 自有的运行上下文；
5. 每次生成前由 Application 构建并注入权威 System Prompt；
6. 模型切换后下一次请求自动使用新的 Model Ref、协议和远端模型 ID；
7. CLI、TUI、Headless 共用同一 Prompt 路径和工作目录事实；
8. 三个 Provider 对统一字段进行正确协议映射；
9. 静态规则在前、运行环境在后的稳定 Prompt 结构；
10. 离线 contract、协议、Application、CLI、TUI 和架构边界测试。

### 3.2 System Prompt 当前内容边界

本任务的 Prompt 只描述当前已经存在的能力和通用编码行为：

- UthCode 身份；
- 软件工程任务定位；
- 不伪造文件读取、代码修改、命令执行和测试结果；
- 事实、推断和未知信息分离；
- 聚焦用户请求，避免无关扩展和过度抽象；
- 安全编码和高风险内容的克制表达；
- 简洁、直接、专业的用户沟通；
- 当前工作目录、平台、日期和模型身份。

本任务的 Prompt 不得声称已经拥有：

- 文件读取或编辑 Tool；
- Bash 或进程执行；
- Permission；
- Agent Loop；
- 自动验证；
- Context 压缩；
- Memory、Dream；
- Plan Mode；
- Hook、Skill、MCP；
- Subagent、Multi-Agent；
- Sandbox。

### 3.3 最小可运行调用链

```text
CLI / TUI / Headless Caller
            │
            ▼
ApplicationRuntimeContext
            │
            ▼
UthCodeApplication.start_generation(request)
            │
            ├── 当前 Model Ref
            ├── ProviderIdentity.protocol
            ├── ProviderIdentity.model
            └── Core build_system_prompt(...)
            │
            ▼
GenerationRequest(system_prompt=..., messages=...)
            │
            ▼
ProviderPort
   ┌────────┼───────────────┐
   ▼        ▼               ▼
Anthropic  Responses   OpenAI-compatible
system     instructions    system message
```

依赖方向：

```text
interfaces → application → core
                  ↓
             integrations
```

返回方向保持不变：

```text
Provider Event → Application → Interface / Headless Caller
```

---

## 4. 原任务书要求处理表

| 原要求 | 处理 | 新版落实方式 | 原因 | 验收方式 |
| --- | --- | --- | --- | --- |
| 统一 `build_system_prompt(...)` 入口 | 保留 | `core/prompt.py` 提供唯一公开构建函数 | System Prompt 属于 Core | Core contract 测试 |
| Prompt 分段、排序和空段过滤 | 保留 | 不可变 `PromptSection` + 纯构建函数 | 输出稳定、可测试 | 顺序和空段测试 |
| 中文 UthCode 身份 | 保留 | 静态身份段 | 产品身份仍有效 | 关键文本断言 |
| 软件工程任务规则 | 调整 | 只保留当前文本能力可兑现的规则 | 当前没有 Tool/Loop | Prompt 内容测试 |
| 安全编码原则 | 保留 | 静态代码质量与安全段 | 与具体 Tool 无关 | 关键规则断言 |
| 输出风格规则 | 保留 | 静态沟通段 | 当前真实能力 | 关键规则断言 |
| 工作目录、平台和日期 | 调整 | ApplicationRuntimeContext 显式传入 | 不混入配置模型 | 固定环境测试 |
| Provider 和模型信息 | 调整 | 只输出 Model Ref、协议和远端 Model ID | 用户已拍板 | 模型切换测试 |
| `PromptContext` 大型动态对象 | 废弃 | 只定义当前真实字段的 `SystemPromptContext` | 禁止未来占位 | 字段和依赖扫描 |
| LangGraph prepare-turn 接入 | 废弃 | Application 每次生成前注入 | 新版完全脱离 LangGraph | Application 集成测试 |
| Graph State Prompt 字段 | 废弃 | 不创建 Graph State | 与全局约束冲突 | 禁止目录扫描 |
| 项目自定义指令 | 后置 | 不创建字段或空 Section | 指令加载尚未设计 | 无占位测试 |
| Tool 使用规则 | 后置 | T04 Tool 系统完成后再增加 | 当前不能兑现 | Prompt 不含工具声明 |
| Permission 规则 | 后置 | Permission 任务处理 | 当前不存在 | Prompt 不含权限模式 |
| Plan Mode Reminder | 后置 | 不创建 plan.py | 属于后续能力 | 禁止文件扫描 |
| Memory、Hook、Skill、Agent Catalog | 后置 | 不创建字段或 Section | 明确后置 | 字段扫描 |
| Prompt 完整快照测试 | 调整 | 使用关键 contract 和相对顺序断言 | 避免文案演进被锁死 | 测试源码审查 |
| MewCode 品牌与推广文本 | 废弃 | 不迁移 | 旧项目痕迹 | 全局文本扫描 |
| Provider 协议转换 | 已由前置任务完成 | 替换输入来源，保留三个物理模块 | 已有成熟映射 | 三协议回归 |
| CLI/TUI 单轮请求 | 已由前置任务完成 | 由 Application 自动补 System Prompt | Interface 不拥有 Prompt | CLI/TUI 端到端测试 |

---

## 5. 前置任务影响表

| 前置能力/文件 | 当前状态 | 本次如何使用 | 是否修改 | 修改原因 | 回归测试 |
| --- | --- | --- | --- | --- | --- |
| `core/provider.py` | 已验收 | 承载 Provider 请求 | 是 | 新增独立 System Prompt、冻结 Message 角色 | `test_provider_contract.py` |
| `core/__init__.py` | 已验收 | Core 公共导出 | 是 | 导出 Prompt API | import/架构测试 |
| `application/configuration.py` | 已验收 | Provider/Model 配置 | 否 | 运行事实不得进入配置 | `test_configuration.py` |
| `application/generation.py` | 已验收 | 正式生成用例 | 是 | 每次请求构建 Prompt | Application 测试 |
| `application/bootstrap.py` | 已验收 | 正式组合入口 | 是 | 接收运行上下文 | Bootstrap/CLI 测试 |
| `application/__init__.py` | 已验收 | Interface/Headless 公共 API | 是 | 导出运行上下文 | import/CLI 测试 |
| Provider Factory | 已验收 | 构造 Provider | 否 | 与 Prompt 无关 | Factory 回归 |
| Anthropic Integration | 已验收 | 映射顶层 system | 是 | 改用请求独立字段 | Anthropic 黑盒测试 |
| Responses Integration | 已验收 | 映射 instructions | 是 | 改用请求独立字段 | Responses 黑盒测试 |
| Chat Integration | 已验收 | 映射 system message | 是 | 改用请求独立字段 | Chat 黑盒测试 |
| Fake Provider | 已验收 | 记录 Application 最终请求 | 否 | 已能观测注入结果 | Application/CLI/TUI 测试 |
| CLI | 已验收 | 组合配置与 Application | 是 | 建立统一 workdir Context | CLI 测试 |
| TUI | 已验收 | 交互适配器 | 是 | 删除独立 cwd 所有权 | TUI Pilot |
| Slash Command | 已验收 | 继续原样使用 | 否 | 与 Prompt 无关 | Command 全量回归 |
| 模型切换 | 已验收 | Prompt 读取当前选择 | 不改语义 | 仅验证切换后 Prompt 刷新 | Runtime/TUI 测试 |
| Provider Event/取消 | 已验收 | 原样返回 | 否 | 不属于本任务 | 全量回归 |

---

## 6. 目标目录树

只列出本任务涉及的文件：

```text
Re-UthCode/
├── README.md                                             # 修改
├── src/uthcode/
│   ├── core/
│   │   ├── __init__.py                                  # 修改
│   │   ├── provider.py                                  # 修改
│   │   └── prompt.py                                    # 新增
│   ├── application/
│   │   ├── __init__.py                                  # 修改
│   │   ├── bootstrap.py                                 # 修改
│   │   ├── generation.py                                # 修改
│   │   ├── runtime_context.py                           # 新增
│   │   └── configuration.py                             # 保留不动
│   ├── integrations/providers/
│   │   ├── anthropic.py                                 # 修改
│   │   ├── openai_responses.py                          # 修改
│   │   ├── openai_compat.py                             # 修改
│   │   ├── factory.py                                   # 保留不动
│   │   ├── config.py                                    # 保留不动
│   │   └── fake.py                                      # 保留不动
│   └── interfaces/
│       ├── cli.py                                       # 修改
│       └── tui/
│           ├── app.py                                   # 修改
│           └── widgets.py                               # 保留不动
└── tests/
    ├── test_system_prompt.py                             # 新增
    ├── test_provider_contract.py                        # 修改
    ├── test_application.py                              # 修改
    ├── test_application_runtime.py                      # 修改
    ├── test_anthropic_integration.py                    # 修改
    ├── test_openai_responses_integration.py             # 修改
    ├── test_openai_compat_integration.py                # 修改
    ├── test_cli.py                                      # 修改
    ├── test_tui.py                                      # 修改
    ├── test_architecture_boundaries.py                  # 修改
    ├── test_package.py                                  # 修改
    ├── test_configuration.py                            # 保留不动
    ├── test_provider_factory.py                         # 保留不动
    └── test_command_*.py                                # 保留不动
```

删除文件：无。

禁止新增：

```text
src/uthcode/prompts/
src/uthcode/core/prompt_manager.py
src/uthcode/core/prompt_registry.py
src/uthcode/core/prompt_loader.py
src/uthcode/core/prompt_cache.py
src/uthcode/core/instructions.py
src/uthcode/core/plan.py
src/uthcode/core/tools/
src/uthcode/core/permissions/
src/uthcode/core/memory/
```

---

## 7. 文件级任务清单

| 文件路径 | 操作 | 文件职责 | 核心类型/函数 | 允许依赖 | 禁止依赖 | 来源参考 | 对应测试 | 验收条件 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `src/uthcode/core/prompt.py` | 新增 | 定义 Core System Prompt 语义和纯构建逻辑 | `PromptSection`、`SystemPromptContext`、`build_system_prompt` | 标准库 | Application、Integration、Interface、SDK、配置文件、环境变量读取 | 原 Day2 分段思想、MewCode Prompt 结构 | `test_system_prompt.py` | 输出确定、中文、无未来能力声明 |
| `src/uthcode/core/provider.py` | 修改 | 扩展统一 Provider 请求并冻结 Message 角色 | `GenerationRequest.system_prompt`、Message 角色校验、JSON 恢复 | 标准库 | Provider SDK、Prompt 构建逻辑 | 当前 Core contract | `test_provider_contract.py` | 独立字段可 JSON round-trip，`role=system` 被拒绝 |
| `src/uthcode/core/__init__.py` | 修改 | 导出稳定 Core Prompt API | Prompt 类型和函数导出 | Core 内部 | Application/SDK | 当前公开包 | import/架构测试 | 调用方无需内部路径即可导入 |
| `src/uthcode/application/runtime_context.py` | 新增 | 保存一次 Application 运行所需的环境事实 | `ApplicationRuntimeContext`、`from_system` | 标准库、Core 值类型可选 | TOMLKit、SDK、Textual、文件扫描 | 用户拍板 2A | `test_application_runtime.py`、`test_system_prompt.py` | workdir 规范化，平台/日期可固定测试 |
| `src/uthcode/application/generation.py` | 修改 | 每次生成前创建权威 Prompt 并复制请求 | `_prepare_request` 或等价私有函数、`runtime_context` 属性 | Core、Application 模型 | Provider 名称分支、SDK、Interface | 当前 GenerationHandle | Application 测试 | Provider 收到带 Prompt 的新请求，原请求不被修改 |
| `src/uthcode/application/bootstrap.py` | 修改 | 正式组合 EffectiveConfig、RuntimeContext 和 Provider | `create_application(..., runtime_context=...)` | Application、Integration Factory | UI 类型 | 当前 Bootstrap | Bootstrap/CLI 测试 | RuntimeContext 独立于 EffectiveConfig |
| `src/uthcode/application/__init__.py` | 修改 | 向 Interface/Headless 导出运行上下文 | `ApplicationRuntimeContext` | Application/Core 转出 | Integration/SDK 类型 | 当前公共包 | import/架构测试 | Interface 不需导入 Core |
| `src/uthcode/integrations/providers/anthropic.py` | 修改 | 将统一字段映射到 Anthropic 顶层 `system` | 请求序列化函数 | Core、Anthropic SDK | Application/Interface | 当前原生实现、官方 Messages API | Anthropic 测试 | 不再扫描 system Message，输出顺序和历史不退化 |
| `src/uthcode/integrations/providers/openai_responses.py` | 修改 | 将统一字段映射到 `instructions` | 请求输入构造 | Core、OpenAI SDK | Application/Interface | 当前原生实现、官方 Responses API | Responses 测试 | `instructions` 来自独立字段，Input 不含 system Message |
| `src/uthcode/integrations/providers/openai_compat.py` | 修改 | 在 Chat Messages 前生成唯一 system message | 请求消息构造 | Core、OpenAI SDK | Application/Interface | 当前原生实现、Chat API | Chat 测试 | 首项为 system，历史消息中不能再出现 system role |
| `src/uthcode/interfaces/cli.py` | 修改 | 解析一次有效 workdir 并组合 Application | Application Factory 签名、`_load_application` | `uthcode.application`、标准库 | Core、Integration、SDK | 当前 CLI | `test_cli.py` | `--cwd` 同时影响配置发现和 Prompt Context |
| `src/uthcode/interfaces/tui/app.py` | 修改 | 从 Application 读取 workdir，不保存第二份事实 | `UthCodeTUI`、`run_tui`、Topbar 装配 | `uthcode.application`、Textual | Core、Integration、SDK、Prompt 文案 | 当前 TUI | `test_tui.py` | Topbar 与请求 Prompt 使用同一 workdir |
| `README.md` | 修改 | 记录正式 System Prompt 与 Headless RuntimeContext 用法 | Python 示例、CLI/TUI 说明 | 文档 | 旧 API、未来能力承诺 | 当前 README | 文档检查 | 示例使用新 API，无 `Message("system")` |
| `tests/test_system_prompt.py` | 新增 | 固化 Prompt 内容和顺序 contract | 静态、环境、转义、缓存友好顺序测试 | Core/Application | 网络、SDK | 原 Day2 contract 测试思想 | 自身 | 不使用完整全文快照 |
| `tests/test_provider_contract.py` | 修改 | 固化新请求协议 | JSON、角色、不可变性 | Core | SDK | 当前测试 | 自身 | 新字段覆盖完整 |
| 三个 Provider 测试 | 修改 | 固化厂商公开请求形状 | System Prompt 映射用例 | 对应 SDK Test Double | 真实网络 | 当前黑盒测试 | 各自文件 | 正常、历史、错误、取消全回归 |
| `tests/test_application*.py` | 修改 | 验证 Application 注入和模型刷新 | Fake 记录请求、RuntimeContext | Core/Application/Fake | 网络 | 当前 Runtime 测试 | 各自文件 | 同一入口覆盖 Headless |
| `tests/test_cli.py` | 修改 | 验证正式 CLI Prompt | `--cwd`、默认 cwd、exec | Interface/Application/Fake | SDK | 当前 CLI 测试 | 自身 | stdout/exit code 不变，Prompt 正确 |
| `tests/test_tui.py` | 修改 | 验证 TUI 共用 Context | Topbar、Fake 请求、模型切换 | Interface/Application/Fake | SDK | 当前 Pilot | 自身 | 既有流式/取消测试不退化 |
| `tests/test_architecture_boundaries.py` | 修改 | 允许并约束 Core Prompt 模块 | 依赖扫描、未来模块扫描 | AST/标准库 | 运行时网络 | 当前边界测试 | 自身 | Core Prompt 无反向依赖，Interface 不直接导入 |
| `tests/test_package.py` | 修改 | 固化包导出和无副作用导入 | Core/Application import | 标准库 | SDK 预加载 | 当前包测试 | 自身 | 根包导入仍不构造 Provider |

---

## 8. 核心协议与实现要求

### 8.1 `PromptSection`

建议定义为：

```python
@dataclass(frozen=True, slots=True)
class PromptSection:
    name: str
    priority: int
    content: str
```

要求：

- `name` 非空；
- `priority` 为整数且不接受 `bool`；
- `content` 必须为字符串；
- 构建时按 `priority` 升序稳定排序；
- 同优先级保持声明顺序；
- `content.strip()` 为空的 Section 不输出；
- Section 之间用两个换行；
- 最终文本无尾部空白；
- 构建过程不修改输入对象。

不建立 Registry、Manager 或运行时可变 Section 集合。

### 8.2 `SystemPromptContext`

建议字段：

```python
@dataclass(frozen=True, slots=True)
class SystemPromptContext:
    workdir: str
    platform_name: str
    platform_release: str
    current_date: str
    model_ref: str
    provider_protocol: str
    remote_model_id: str
```

约束：

- 只承载当前任务真实使用的数据；
- 不包含 Provider Profile ID；
- 不包含 Base URL、API Key 环境变量名和配置来源；
- 不包含 tools、permission、memory、hooks、skills、agent catalog；
- 不读取文件、环境变量、系统时间或平台信息；
- 所有外部值由 Application 传入；
- 字段值渲染时使用可辨识的引用或转义形式，避免换行和特殊字符破坏 Section 结构。

### 8.3 Prompt Section 结构

建议固定为：

```text
priority 0   身份
priority 10  工作原则
priority 20  代码质量与安全
priority 30  沟通与结果真实性
priority 100 当前运行环境
```

#### 身份

必须表达：

- 你是 UthCode；
- 面向软件工程任务；
- 当前通过文本帮助用户理解、设计、审查和编写代码相关内容；
- 不绑定 Claude、GPT、DeepSeek 或 MewCode 品牌人格。

#### 工作原则

必须表达：

- 聚焦用户当前请求；
- 不凭空假定未提供的代码和环境事实；
- 不为假设性未来需求增加功能和抽象；
- 对未知信息明确说明未知；
- 不输出内部思考链路。

#### 代码质量与安全

必须表达：

- 优先正确、清晰、可维护的实现；
- 避免引入 command injection、SQL injection、XSS、路径遍历、秘密泄漏等常见风险；
- 不把未经验证的代码或命令描述为已经可用；
- 不伪造测试、编译和运行结果。

#### 沟通与结果真实性

必须表达：

- 默认使用简洁、直接、专业的中文；
- 用户指定其他语言或格式时遵循用户要求；
- 区分已知事实、合理推断和未验证内容；
- 不声称已经读取文件、修改代码、运行命令或执行测试，除非当前请求上下文中确有对应能力和结果。

#### 当前运行环境

必须输出：

```text
workdir
platform_name + platform_release
current_date
model_ref
provider_protocol
remote_model_id
```

运行环境段必须位于静态规则之后。不得包含每轮随机值、请求 ID、时间戳、用户消息或 Transcript。

### 8.4 `GenerationRequest.system_prompt`

正式字段：

```python
system_prompt: str | None = None
```

要求：

- `None` 表示 Core 直接 Provider 调用没有 System Prompt；
- 非 `None` 时必须为非空字符串；
- 进入 `to_dict()`、`to_json()`、`from_dict()` 和 `from_json()`；
- 保持请求不可变；
- 不使用 `metadata` 保存 Prompt；
- 不新增同义字段 `instructions`、`system_message` 或 `developer_prompt`。

### 8.5 Message 角色

正式合法角色：

```text
user
assistant
tool
```

要求：

- `Message(role="system", ...)` 必须明确失败；
- 三个 Integration 不再处理历史中的 system role；
- 不保留兼容转换或警告后继续；
- 不引入第二种 Developer Message Core 角色；
- Provider 特有角色差异继续由 Integration 映射。

### 8.6 `ApplicationRuntimeContext`

建议定义：

```python
@dataclass(frozen=True, slots=True)
class ApplicationRuntimeContext:
    workdir: Path
    platform_name: str
    platform_release: str
    current_date: str

    @classmethod
    def from_system(...): ...
```

要求：

- `workdir` 转为绝对、规范化路径；
- 默认从当前进程工作目录建立；
- 平台和日期在 Context 创建时解析一次，保证同一 Application 运行期间稳定；
- 测试可显式传入固定平台和日期；
- 不写入 `EffectiveConfig`；
- 不读取 TOML、Provider Secret 或项目指令；
- `repr` 不包含秘密，因为该类型不得持有秘密。

### 8.7 Application Prompt 注入

`UthCodeApplication` 必须在每次 `start_generation()` 时：

```text
读取 ApplicationRuntimeContext
→ 读取 current_model_ref
→ 读取当前 ProviderIdentity.protocol/model
→ 构造 SystemPromptContext
→ build_system_prompt()
→ 复制 GenerationRequest 并填入 system_prompt
→ 创建 GenerationHandle
```

要求：

- 不修改调用方原请求；
- Application 是权威 Prompt 所有者；
- 调用方传入非 `None` 的 `system_prompt` 时必须明确拒绝，不能静默覆盖或拼接；
- `GenerationHandle` 保存准备完成后的请求；
- `stream_generation()` 继续复用 `start_generation()`；
- Prompt 构建失败时不得调用 Provider；
- 模型切换成功后，下一次请求使用新 Model Ref、协议和远端模型 ID；
- 模型切换失败时 Prompt 身份仍保持旧值；
- 不在 Application 中按 Anthropic/OpenAI 名称分支。

### 8.8 Provider 映射

#### Anthropic

```text
request.system_prompt → messages.create(system=...)
request.messages      → messages=[user/assistant/tool ...]
```

- 无 Prompt 时不发送 `system`；
- 不从 `messages` 中提取 System；
- 保持 Thinking、Redacted Thinking、Tool Use/Result 和 Usage 行为。

#### OpenAI Responses

```text
request.system_prompt → responses.create(instructions=...)
request.messages      → input=[...]
```

- 无 Prompt 时不发送 `instructions`；
- Input 中不生成 system item；
- 保持 Reasoning、Function Call、Native Item、终态和 Usage 行为。

#### OpenAI-compatible Chat

```text
request.system_prompt → messages[0] = {role: "system", content: ...}
request.messages      → messages[1:]
```

- 无 Prompt 时不生成 system message；
- 最多生成一个 system message；
- 不使用 `developer` 角色，因为通用兼容端点不能统一保证支持；
- 保持 reasoning carrier、Indexed Tool Call、Tool Result 和 Usage 行为。

### 8.9 缓存友好约束

本任务不实现 Cache API，但 Prompt 必须满足：

```text
稳定静态规则
→ 稳定 Application 级环境和模型身份
→ Provider 侧会话消息
```

要求：

- 同一 Application、同一模型选择下 System Prompt 文本完全一致；
- 不加入每轮时间、随机数、请求 ID、计数器或用户输入；
- 模型切换导致 Prompt 身份变化属于预期；
- 不新增 `prompt_cache_key`、`cache_control`、缓存存储或缓存管理模块；
- Cache 启用应由后续独立 Provider 能力任务处理，不应污染 Core Prompt contract。

---

## 9. 依赖与数据流

### 9.1 数据所有者

```text
Core
├── PromptSection
├── SystemPromptContext
├── build_system_prompt
└── GenerationRequest.system_prompt

Application
├── ApplicationRuntimeContext
├── current_model_ref
├── ProviderIdentity 读取
└── 请求准备与 Prompt 注入

Integration
└── 厂商协议字段映射

Interface
└── workdir 启动参数与显示适配
```

### 9.2 调用方向

```text
Interface / Embedded Caller
        ↓
create_application(config, runtime_context)
        ↓
UthCodeApplication
        ↓
build_system_prompt(SystemPromptContext)
        ↓
GenerationRequest(system_prompt=...)
        ↓
ProviderPort
        ↓
Native SDK Integration
```

### 9.3 禁止方向

```text
core ─X─► application
core ─X─► integrations
core ─X─► interfaces
core ─X─► OpenAI / Anthropic SDK

interfaces ─X─► core
interfaces ─X─► integrations
interfaces ─X─► Provider SDK

integrations ─X─► Textual
integrations ─X─► ApplicationRuntimeContext
```

### 9.4 第三方类型边界

- `ApplicationRuntimeContext`、`SystemPromptContext` 和 `GenerationRequest` 都是 UthCode 自有类型；
- Anthropic/OpenAI SDK 类型只能出现在对应 Integration；
- SDK Request、Event、Message 类型不得进入 Core、Application 或 Interface；
- Prompt 本身只是字符串，不保存 SDK Content Block 对象。

### 9.5 Interface 可替换性

删除：

```text
src/uthcode/interfaces/
```

后仍必须能够：

```text
EffectiveConfig.single_model(...)
→ ApplicationRuntimeContext(...)
→ create_application(...)
→ start_generation(...)
→ FakeProvider 记录带 System Prompt 的请求
→ Provider Event 正常返回
```

---

## 10. 第三方依赖

### 10.1 新增依赖

无。

### 10.2 修改依赖

无。

### 10.3 现有依赖使用范围

| 依赖 | 本次用途 | 是否进入 Core | 影响 |
| --- | --- | --- | --- |
| `anthropic` | 既有 Anthropic 请求映射 | 否 | 仅修改参数来源 |
| `openai` | 既有 Responses/Chat 请求映射 | 否 | 仅修改参数来源 |
| `textual` | 既有 TUI | 否 | 只调整 workdir 来源 |
| `tomlkit` | 既有配置加载 | 否 | 本次不修改 |

不得为了 Prompt 拼接引入模板引擎、Pydantic、Jinja、Prompt 框架或 DI 容器。标准库和简单不可变数据结构足以满足当前任务。

---

## 11. 实施任务拆分

### Worker 分组

| Worker | Task | 串行理由 |
| --- | --- | --- |
| W01 Core Prompt Contract Worker | Task 1—Task 2 | Prompt 内容模型和 GenerationRequest 公共协议必须一起冻结 |
| W02 Provider Mapping Worker | Task 3 | 三种协议映射必须保持同一 Core 语义且一次性删除旧 system Message 路径 |
| W03 Application Interface Worker | Task 4—Task 5 | RuntimeContext、Application 注入和 Interface workdir 所有权必须共同收口 |
| W04 Delivery Verification Worker | Task 6—Task 8 | 主流程接入、端到端验证和遗留清理必须基于全部实现完成后统一执行 |

执行顺序：

```text
W01 → W02 → W03 → W04
```

未收到用户对对应 Worker Prompt 的明确派发时，不得实施。

### Task 1：建立 Core System Prompt 模块

**任务目标**

建立当前能力范围内唯一、纯函数、可测试的中文 System Prompt。

**前置条件**

- 基线 Commit 已确认；
- 全局约束已读取；
- 不存在未解释的 Core Prompt 文件。

**涉及文件**

新增：

```text
src/uthcode/core/prompt.py
tests/test_system_prompt.py
```

修改：

```text
src/uthcode/core/__init__.py
```

**允许修改的前置文件**

仅上述 Core 导出文件。

**完成结果**

- `PromptSection`、`SystemPromptContext`、`build_system_prompt()` 可用；
- Prompt 包含五个确定 Section；
- 动态环境位于最后；
- 无未来能力字段和声明；
- 无旧品牌与推广文本。

**测试**

```text
test_system_prompt_orders_sections
test_system_prompt_uses_fixed_runtime_values
test_system_prompt_omits_blank_sections
test_system_prompt_does_not_mutate_sections
test_system_prompt_contains_only_current_capabilities
test_system_prompt_escapes_runtime_values
test_system_prompt_static_prefix_precedes_runtime_suffix
```

**明确不做**

- 不接 Application；
- 不改 Provider；
- 不创建 Tool/Permission/Plan 等 Section；
- 不实现 Cache Control。

**提交边界**

```text
feat(core): add system prompt contract
```

### Task 2：替换 Core 请求中的临时 System Message 语义

**任务目标**

将 System Prompt 从普通 Message 中分离，并冻结合法 Message 角色。

**前置条件**

Task 1 通过。

**涉及文件**

修改：

```text
src/uthcode/core/provider.py
tests/test_provider_contract.py
```

**允许修改的前置文件**

只允许修改 Core Provider 请求模型和直接 contract 测试。

**完成结果**

- `GenerationRequest.system_prompt` 完整参与 JSON round-trip；
- `Message` 只允许 user/assistant/tool；
- `Message("system", ...)` 被拒绝；
- 没有同义字段和兼容入口。

**测试**

- System Prompt 为 `None` 和合法文本；
- 空文本、非字符串拒绝；
- JSON 恢复；
- 请求深度不可变；
- 非法角色矩阵。

**明确不做**

- 不修改 Response/Event；
- 不调整 Tool Part；
- 不实现 Application 注入。

**提交边界**

```text
refactor(core): separate system prompt from messages
```

### Task 3：重写三种 Provider 的 System Prompt 映射

**任务目标**

一次性删除三个 Integration 对 `Message(role="system")` 的处理，改用统一字段。

**前置条件**

Task 2 完成；三个 Provider 现有定向测试通过。

**涉及文件**

修改：

```text
src/uthcode/integrations/providers/anthropic.py
src/uthcode/integrations/providers/openai_responses.py
src/uthcode/integrations/providers/openai_compat.py
tests/test_anthropic_integration.py
tests/test_openai_responses_integration.py
tests/test_openai_compat_integration.py
```

**允许修改的前置文件**

只允许三个物理协议模块和各自黑盒测试。

**完成结果**

- Anthropic 使用顶层 `system`；
- Responses 使用 `instructions`；
- Chat 前置唯一 `role=system`；
- 无 Prompt 时不发送相应字段；
- Native Item、历史、工具、Usage、错误、取消和关闭行为不变。

**测试**

每个 Provider 至少覆盖：

- 有 System Prompt；
- 无 System Prompt；
- 普通历史消息顺序；
- Tool Result 往返；
- 现有 Reasoning/Native Item；
- 错误、显式取消、Task 取消和 Stream 关闭；
- 请求中不存在旧 system Message Core 输入。

**明确不做**

- 不改 Provider Factory；
- 不启用 Prompt Cache；
- 不使用 Chat developer role；
- 不修改 SDK 版本。

**提交边界**

```text
refactor(providers): map core system prompt to native protocols
```

### Task 4：建立 ApplicationRuntimeContext 与权威请求准备

**任务目标**

让 Application 在每次请求前根据统一运行上下文和当前模型身份构建 Prompt。

**前置条件**

Task 1—Task 3 完成。

**涉及文件**

新增：

```text
src/uthcode/application/runtime_context.py
```

修改：

```text
src/uthcode/application/generation.py
src/uthcode/application/bootstrap.py
src/uthcode/application/__init__.py
tests/test_application.py
tests/test_application_runtime.py
```

**允许修改的前置文件**

仅 Application 组合和生成用例；不得修改 `configuration.py`。

**完成结果**

- RuntimeContext 与 EffectiveConfig 独立；
- Application 每次生成建立新请求并注入 Prompt；
- 原请求不变；
- 调用方自带 System Prompt 被拒绝；
- Fake Provider 可记录最终 Prompt；
- 模型切换后身份正确刷新；
- GenerationHandle 和取消语义不变。

**测试**

- 固定 workdir、平台、日期；
- Headless Fake 正常请求；
- 原请求不可变；
- Prompt 构建失败时 Provider 未被调用；
- 自带 Prompt 拒绝；
- 成功模型切换；
- Provider 构造失败和写回失败后身份不变；
- 两个 Handle 取消隔离。

**明确不做**

- 不在 Application 按 Provider 名称分支；
- 不加载项目指令；
- 不持久化 RuntimeContext；
- 不修改配置 TOML。

**提交边界**

```text
feat(application): inject system prompt from runtime context
```

### Task 5：统一 CLI、TUI 与 Headless 的运行上下文

**任务目标**

移除 TUI 独立 workdir 所有权，使所有正式入口组合同一个 ApplicationRuntimeContext。

**前置条件**

Task 4 完成。

**涉及文件**

修改：

```text
src/uthcode/interfaces/cli.py
src/uthcode/interfaces/tui/app.py
tests/test_cli.py
tests/test_tui.py
README.md
```

**允许修改的前置文件**

只允许 Interface 组合、显示和对应测试；不得修改 Widget 核心渲染、Command 系统或配置加载规则。

**完成结果**

- CLI 解析一个规范化 workdir；
- 同一 workdir 同时用于配置发现和 RuntimeContext；
- TUI Topbar 从 Application 读取 workdir；
- `uthcode exec`、TUI 和 Embedded Headless 都经过 Application Prompt 注入；
- Interface 不导入 Core Prompt API。

**测试**

- 默认 cwd；
- 显式 `--cwd`；
- stdin 和位置 Prompt；
- TUI Topbar 与 Provider 记录 Prompt 一致；
- 模型 Picker 切换后下一次 Prompt 身份变化；
- 既有流式刷新、双 Esc、退出码和 stdout/stderr 不变。

**明确不做**

- 不新增 CLI Prompt 参数；
- 不允许用户直接覆盖 System Prompt；
- 不修改 Slash Command；
- 不增加 TUI 设置页面。

**提交边界**

```text
refactor(interfaces): share application runtime context
```

### Task 6：[接入主流程] 收口正式调用链

**任务目标**

证明所有正式生成入口都只通过 Application 构建一次 System Prompt，并删除旧路径。

**前置条件**

Task 1—Task 5 全部完成。

**涉及文件**

原则上只修改：

```text
tests/test_architecture_boundaries.py
tests/test_package.py
README.md
```

如发现接入缺陷，只允许窄幅修改 Task 1—Task 5 已列文件。

**完成结果**

```text
CLI/TUI/Headless
→ ApplicationRuntimeContext
→ UthCodeApplication
→ Core Prompt
→ GenerationRequest.system_prompt
→ ProviderPort
```

旧路径必须不存在：

```text
Message(role="system")
Interface 拼 Prompt
Provider 从历史中提取 System
EffectiveConfig 保存 workdir/date/platform
```

**测试**

- 正式 Bootstrap Fake 请求；
- Interface 删除后 Headless 子进程；
- 根包导入无 SDK/Interface 副作用；
- 依赖边界 AST 检查；
- Prompt 模块无反向依赖。

**明确不做**

- 不实现后续能力；
- 不改 Provider Event 或配置格式。

**提交边界**

```text
refactor: connect formal system prompt pipeline
```

### Task 7：[端到端验证] 验证三协议与全部正式入口

**任务目标**

通过离线可复现测试证明 System Prompt 从正式入口到三种厂商请求形状完整贯通。

**前置条件**

Task 6 完成。

**涉及文件**

原则上无新增业务文件。只允许修复当前工作包范围内缺陷。

**完成结果**

至少验证：

1. Embedded Headless + Fake：记录完整 Prompt；
2. `uthcode exec` + Fake：workdir 和模型身份正确；
3. Textual TUI + Fake：Topbar、请求和模型切换一致；
4. Anthropic Mock Client：顶层 `system`；
5. Responses Mock Client：顶层 `instructions`；
6. Chat Mock Client：首个 `role=system`；
7. 三种协议现有 Reasoning、Tool、Usage、错误和取消回归；
8. 全量离线测试和字节码编译通过。

**测试命令**

```bash
conda run --no-capture-output -n re-uthcode python -m compileall -q src tests
conda run --no-capture-output -n re-uthcode pytest -q tests/test_system_prompt.py tests/test_provider_contract.py
conda run --no-capture-output -n re-uthcode pytest -q tests/test_anthropic_integration.py tests/test_openai_responses_integration.py tests/test_openai_compat_integration.py
conda run --no-capture-output -n re-uthcode pytest -q tests/test_application.py tests/test_application_runtime.py tests/test_cli.py tests/test_tui.py
conda run --no-capture-output -n re-uthcode pytest -q tests/test_architecture_boundaries.py tests/test_package.py
conda run --no-capture-output -n re-uthcode pytest -q
conda run --no-capture-output -n re-uthcode python -m pip check
```

Live Provider 测试保持显式门禁，未获用户授权不得运行。

**明确不做**

- 不进行真实费用请求；
- 不实现缓存 API；
- 不做 Prompt 质量大规模评测。

**提交边界**

```text
test: validate system prompt pipeline end to end
```

### Task 8：[遗留负担清理] 删除临时语义和未来占位

**任务目标**

确认 T03 没有留下双轨 Prompt、旧角色、重复上下文或未来能力占位。

**前置条件**

Task 7 全部通过。

**涉及文件**

只在扫描发现本任务产生的残留时修改 Task 1—Task 7 已列文件。

**完成结果**

- `Message(role="system")` 的业务源码和测试调用为 0；
- Provider 不扫描 System Message；
- Interface 不包含 Prompt 正文；
- EffectiveConfig 不含 Runtime 字段；
- 不存在 Prompt Manager、Registry、Loader、Cache；
- 不存在未来动态 Section 字段；
- 不存在 MewCode 品牌与推广内容；
- 没有兼容别名、Shim 或双轨 API；
- README 只描述正式入口。

**验证命令**

```bash
rg -n 'Message\([^\n]*["'"']system["'"']|role\s*=\s*["'"']system["'"']' src tests
rg -n 'custom_instructions|hook_prompts|memory_section|skill_section|agent_catalog|deferred_tool|plan_mode' src/uthcode/core/prompt.py src/uthcode/application/runtime_context.py
rg -n 'MewCode|xiaolincoding|xiaolinnote|公众号|Go版' src tests README.md
rg --files src/uthcode | rg 'prompt_(manager|registry|loader|cache)|prompts/|plan.py'
rg -n 'system_prompt' src/uthcode/interfaces
rg -n 'workdir|platform_name|platform_release|current_date' src/uthcode/application/configuration.py src/uthcode/integrations/config
conda run --no-capture-output -n re-uthcode python -m compileall -q src tests
conda run --no-capture-output -n re-uthcode pytest -q
git diff --check
git status --short
```

说明：Chat Integration 中生成厂商 `role="system"` 是合法映射，扫描结果必须逐项确认只存在于该物理模块及其协议测试；Core Message 构造不得存在。

**明确不做**

- 不清理与 T03 无关的历史工作包；
- 不归档工作包；
- 不执行 Git 提交、推送、PR 或合并，除非用户另行明确要求。

**提交边界**

```text
chore: remove legacy system prompt paths
```

---

## 12. 测试矩阵

| 测试范围 | 场景 | 预期 | 测试文件 |
| --- | --- | --- | --- |
| Prompt 正常 | 固定 Context 构建 | Section 顺序和内容正确 | `test_system_prompt.py` |
| Prompt 确定性 | 相同 Context 连续构建 | 字节完全一致 | `test_system_prompt.py` |
| Prompt 动态值 | workdir/平台/日期/模型变化 | 只改变运行环境段 | `test_system_prompt.py` |
| Prompt 空段 | 私有渲染接收空内容 | 不产生空标题 | `test_system_prompt.py` |
| Prompt 安全 | 路径含换行/引号 | 结构不被破坏 | `test_system_prompt.py` |
| 当前能力边界 | 搜索 Tool/Permission 等声明 | 0 条 | `test_system_prompt.py`/扫描 |
| Core 请求 | system_prompt JSON round-trip | 值保持 | `test_provider_contract.py` |
| Core 请求错误 | 空 Prompt、非法类型 | 明确拒绝 | `test_provider_contract.py` |
| Message 角色 | user/assistant/tool | 接受 | `test_provider_contract.py` |
| Message 角色错误 | system/未知角色 | 拒绝 | `test_provider_contract.py` |
| Application 注入 | Fake Provider 记录请求 | 有权威 Prompt | `test_application.py` |
| 原请求隔离 | 调用后检查输入请求 | 未修改 | `test_application.py` |
| 调用方冲突 | 请求自带 Prompt | Provider 未调用并报错 | `test_application.py` |
| 模型切换 | one/ref → two/ref | 下一请求身份段刷新 | `test_application_runtime.py` |
| 切换失败 | Provider/写回失败 | Prompt 仍为旧身份 | `test_application_runtime.py` |
| 取消 | 独立 Handle 取消 | 语义不变 | `test_application_runtime.py` |
| Anthropic | 有/无 Prompt | 顶层 system 正确 | `test_anthropic_integration.py` |
| Responses | 有/无 Prompt | instructions 正确 | `test_openai_responses_integration.py` |
| Chat | 有/无 Prompt | 唯一首项 system | `test_openai_compat_integration.py` |
| Provider 历史 | assistant/tool 往返 | 顺序与 Native Item 不退化 | 三协议测试 |
| Provider 错误 | 官方错误/非法终态 | 分类不变 | 三协议测试 |
| Provider 取消 | 显式与 Task 取消 | Stream 关闭 | 三协议测试 |
| CLI 默认 | `uthcode exec` | Prompt 使用实际 cwd | `test_cli.py` |
| CLI 覆盖 | `--cwd` | 配置和 Prompt 同一目录 | `test_cli.py` |
| TUI | 普通生成 | Topbar 与 Prompt 同源 | `test_tui.py` |
| TUI 模型切换 | Picker 切换后生成 | 身份段刷新 | `test_tui.py` |
| Headless | 无 Interface 子进程 | 完整请求可运行 | `test_architecture_boundaries.py` |
| 边界 | Core Prompt import 扫描 | 无反向依赖和 SDK | `test_architecture_boundaries.py` |
| 第三方类型 | Core/Application/Interface AST | 无 SDK 类型 | `test_architecture_boundaries.py` |
| 未来能力 | 目录/字段/文本扫描 | 0 条 | 边界测试/rg |
| 旧项目依赖 | import/text 扫描 | 无运行时依赖 | 边界测试/rg |
| 全量回归 | 全量 pytest | 全部离线通过，live skipped | 全量测试 |

---

## 13. 删除与清理

本任务没有计划删除物理文件，但必须删除以下旧语义：

1. `Message(role="system")` 作为 Core 请求入口；
2. Anthropic/Responses 从 `request.messages` 中提取 System 的循环分支；
3. Chat 直接透传 Core system Message 的分支；
4. TUI 构造函数和 `run_tui()` 中独立的 `cwd` 所有权；
5. README 和测试中的旧 System Message 示例；
6. 架构测试中“Prompt 必须完全不存在”的旧阶段断言；
7. 仅为兼容前置临时语义而新增的 Alias、Fallback 或警告路径。

不得删除：

- Provider Native Item 和 Reasoning 处理；
- Tool 数据模型；
- 配置系统；
- 命令系统；
- TUI 既有渲染和取消；
- 历史工作包文件。

---

## 14. 验收标准

### 14.1 Core Prompt

- `src/uthcode/core/prompt.py` 是唯一 Prompt 正文和构建逻辑所有者；
- Prompt 使用中文并包含 UthCode 身份；
- Prompt 只陈述当前真实能力；
- 静态规则位于运行环境之前；
- 相同 Context 输出完全一致；
- 不读取文件、环境变量、配置、SDK 或 Interface 状态；
- 不包含 MewCode 和推广文本。

### 14.2 Core 请求协议

- `GenerationRequest.system_prompt` 可序列化、不可变、可恢复；
- `Message` 只允许 user/assistant/tool；
- 不存在第二 System Prompt 字段；
- 不存在旧角色兼容层。

### 14.3 Application

- ApplicationRuntimeContext 与 EffectiveConfig 独立；
- Application 每次生成前构建 Prompt；
- 调用方原请求不被修改；
- 调用方不能覆盖权威 Prompt；
- 模型切换后的 Prompt 身份正确；
- Application 不按 Provider 名称分支；
- GenerationHandle、终态和取消不退化。

### 14.4 Provider

- Anthropic、Responses、Chat 分别使用正式公开协议字段；
- 三个 Provider 不再接受 Core system Message；
- Reasoning、Tool、Native Item、Usage、错误、取消和资源关闭全部回归通过；
- SDK 类型仍只存在于 Integration。

### 14.5 Interface 与 Headless

- CLI、TUI、Headless 共用 Application Prompt 路径；
- `--cwd`、TUI Topbar 和 Prompt workdir 一致；
- Interface 不导入 Core Prompt；
- 删除 Interface 后 Headless 全链路仍能运行；
- stdout、stderr、退出码、流式渲染和双 Esc 行为不变。

### 14.6 范围与遗留负担

- 不存在 Tool、Permission、Plan、Memory、Hook、Skill、MCP、Subagent 占位；
- 不存在 Prompt Manager、Registry、Loader 或 Cache 框架；
- 不存在旧 UthCode/MewCode 运行时依赖；
- 不存在兼容 Alias、Facade、Shim 或双轨请求；
- 配置 TOML 和 Provider Factory 未被无理由修改；
- 全量离线测试、compileall、pip check 和架构扫描通过；
- 当前实现可以作为 T04 Tool 系统的真实代码基线；T04 只需在获得真实 Tool 能力后扩展 Prompt 内容，不需要推翻 System Prompt 公共协议。

---

## 15. 编码停止条件

编码代理遇到以下情况必须停止对应范围并写入 Feedback，交由用户决定：

1. 当前源码与本任务记录的基线存在无法解释的公共协议差异；
2. 需要修改 `EffectiveConfig` 或 TOML 结构才能继续；
3. 需要让 Interface 直接调用 Core Prompt；
4. 需要让 Core 导入 Provider SDK、Textual 或 Integration；
5. 需要引入 LangGraph、LangChain Agent、通用工作流框架或 Prompt 框架；
6. 需要创建 Tool、Permission、Plan、Context、Memory、Hook、Skill、MCP 或 Agent 占位；
7. 需要允许调用方覆盖或拼接 Application 权威 System Prompt；
8. 三种 Provider 无法通过独立字段实现公开协议映射；
9. 需要使用 `developer` 角色才能支持某个 OpenAI-compatible 端点；
10. 需要启用或设计 Prompt Cache API 才能完成当前任务；
11. 需要修改 Provider Response/Event、Native Item、Usage 或取消公共语义；
12. 需要整文件复制旧 UthCode 或 MewCode；
13. 实际修改文件明显超出本任务目录树；
14. 两项用户冻结决策发生实质冲突；
15. 发现秘密泄漏、外部写入或不可逆副作用风险。

以下不属于停止条件，应由编码代理自行处理：

- 普通编译错误；
- 测试失败；
- 类型标注错误；
- 私有函数拆分；
- Test Double 或 Fixture 调整；
- 不影响公共边界的文案压缩；
- 现有测试因正式协议替换需要更新。

---

## 16. 实施完成后的最小验证报告

Feedback 至少记录：

```text
1. 实际基线 Commit 与工作区状态
2. Prompt Section 和运行上下文实际结构
3. GenerationRequest 公共协议变化
4. 三种 Provider 的实际映射
5. CLI/TUI/Headless 的统一 workdir 数据流
6. 模型切换后的 Prompt 刷新证据
7. 定向测试与全量测试精确结果
8. live 测试是否运行
9. 旧 system Message 和未来占位扫描结果
10. 与任务书不同的实际情况及原因
11. 遗留风险或需要用户决定的问题
```

不得在 Feedback 中堆砌完整 Prompt 正文或逐行源码。
