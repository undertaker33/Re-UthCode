# T02：Slash Command、配置系统与默认 Textual TUI 任务书

> 文档性质：独立文件级实施任务书  
> 本次只生成并实施本任务书，不生成 `spec`、`tasks`、`checklist`、Worker Prompt 或 Feedback 等完整任务包文件。

---

## 1. 分析基线

### 1.1 目标仓库

```text
https://github.com/undertaker33/Re-UthCode
```

固定实施基线：

```text
a605f9409cecccd4f7218f4c69b5362c76ab1b14
```

该提交为 T01「项目骨架与 Provider 抽象」完成后的合并提交。

### 1.2 全局约束

实施前必须完整读取：

```text
AGENTS.md
SRe-AGENTS.md
docs/work/README.md
```

本任务已获用户批准修改 `SRe-AGENTS.md` 中与 T02 直接冲突的旧阶段约束。除本任务书明确列出的条款外，不得顺带改写其他全局约束。

### 1.3 已完成前置任务

已完成：

```text
docs/work/T01-项目骨架与Provider抽象/
```

本任务必须以 T01 的实际源码和测试为基线，重点复用：

```text
src/uthcode/core/provider.py
src/uthcode/application/generation.py
src/uthcode/application/bootstrap.py
src/uthcode/application/__init__.py
src/uthcode/integrations/providers/config.py
src/uthcode/integrations/providers/factory.py
src/uthcode/integrations/providers/fake.py
tests/test_provider_contract.py
tests/test_application.py
tests/test_provider_factory.py
tests/test_architecture_boundaries.py
```

### 1.4 历史与外部参考

本任务没有可直接继承的旧版统一 T02 任务书。产品要求以本轮已经冻结的探索结论为准。

参考来源：

```text
MewCode：
/mnt/data/3_mewcode-python.zip

直接参考文件：
mewcode/commands/registry.py
mewcode/commands/parser.py
mewcode/commands/completion.py
mewcode/commands/handlers/*.py
```

```text
FirstCoder：
仓库 KomorGiaoGiao/FirstCoder
固定参考 Commit：
095787b888e36701656e66ff04a282f300e237dc

直接参考文件：
firstcoder/app/tui.py
firstcoder/app/tui_widgets.py
firstcoder/app/picker.py
firstcoder/app/tui.tcss
tests/test_app_tui.py
LICENSE
```

FirstCoder 只作为默认 TUI 的视觉与交互基线。允许按 MIT License 选择性迁移实质代码；发生复制或实质性改编时，必须保留其版权和许可证声明。不得整体复制 FirstCoder，不得引入其 Agent、Session、Tool、Permission、Task Plan、附件等非本任务能力。

外部依赖核对基线：

```text
Textual 8.2.8
TOMLKit 0.15.0
```

---

## 2. 当前实现基线

### 2.1 已有能力

T01 已交付：

- UthCode 自有的 Provider 请求、响应、流事件、错误和取消模型；
- `ProviderPort`；
- `CancellationToken`；
- `UthCodeApplication.stream_generation()`；
- `create_application()` 组合入口；
- Fake、Anthropic、OpenAI Responses、OpenAI-compatible Provider；
- 离线测试与显式授权的真实协议测试。

当前最小调用链：

```text
Headless Caller
→ create_application(ProviderConfig)
→ UthCodeApplication.stream_generation()
→ ProviderPort.stream()
→ ProviderEvent
```

### 2.2 当前限制

当前没有：

- CLI console script；
- `python -m uthcode` 入口；
- TUI；
- Slash Command；
- 命令 Registry；
- 配置文件加载与合并；
- 多 Provider Profile；
- Model Catalog；
- 运行时模型切换；
- 用户配置回写；
- Application 层取消句柄；
- 会话历史、Run、Turn、Session 或 Agent Loop。

`UthCodeApplication` 当前固定持有一个 Provider。调用方可以直接传入 Core 的 `CancellationToken`，但这不适合作为 TUI 的正式依赖边界。

### 2.3 本次允许修改的 T01 公共边界

为满足已经冻结的配置、模型切换和 Interface 隔离要求，本次允许：

- 扩展 `UthCodeApplication`；
- 扩展或替换 `create_application()` 的配置输入模型；
- 调整 `application.__init__` 的公开导出；
- 更新 T01 的 Application 测试和 README 示例；
- 保留 `stream_generation()` 作为 Headless 便利入口，但其内部必须复用新的 `GenerationHandle`；
- 保持 Core Provider 契约不变；
- 保持现有 Provider Integration Factory 为唯一 Provider 构造边界。

不得为了兼容 T01 的临时单 Provider 配置接口保留两套长期配置模型或两套组合入口。

---

## 3. 当前任务目标

T02 完成后必须交付：

1. 官方默认 Textual TUI；
2. 可独立使用的 Headless Python API；
3. `uthcode exec` 非交互 CLI；
4. 一个正式 Slash Command Registry；
5. Parser、Completion、Dispatcher、`CommandOutcome` 与结构化 UI Action；
6. 用户级与递归项目级 `config.toml`；
7. 多 Provider Profile 与多 Model Profile；
8. `/model` 模型 Picker、即时切换与用户默认模型持久化；
9. 基于 T01 流事件的 Markdown 流式渲染；
10. 滚动保护和双 Esc 中断。

完成后的正式调用链：

```text
uthcode
→ CLI 入口
→ Application 配置加载 API
→ create_application(EffectiveConfig)
→ UthCode Textual TUI
→ Command Dispatcher 或 GenerationHandle
→ UthCodeApplication
→ ProviderPort
```

```text
uthcode exec "prompt"
→ CLI 入口
→ Application 配置加载 API
→ create_application(EffectiveConfig)
→ GenerationHandle
→ ProviderEvent
→ stdout / stderr / exit code
```

```text
Embedded Headless Caller
→ EffectiveConfig.single_model(...) 或配置加载 API
→ create_application()
→ GenerationHandle / stream_generation()
→ ProviderEvent
```

核心边界：

```text
interfaces
   │
   ▼
application
   │
   ├──────────────► core
   │
   └──────────────► integrations
```

禁止：

```text
interfaces ─X─► core
interfaces ─X─► integrations
interfaces ─X─► Provider SDK
core       ─X─► Textual / TOML / CLI
```

---

## 4. 明确不做

本任务不实施：

- Agent Loop；
- 多轮上下文；
- Conversation、Run、Turn、Session；
- `/new` 的真实会话创建；
- `/resume` 的会话恢复；
- Context、Compact、Memory、Dream；
- Tool 执行及 Tool 专用 UI；
- Permission 及审批 UI；
- Diff Viewer；
- Task Plan；
- Skill；
- MCP；
- Hook；
- Worktree；
- Subagent 或 Multi-Agent；
- 文件附件、图片粘贴；
- `/login` 或安全凭据存储；
- `/config` 查看、打开或编辑；
- 项目通用 `.env` 自动加载；
- Web、桌面端或 IDE；
- 主题系统；
- 配置热重载；
- 从远端 Provider 自动获取模型列表；
- 对旧 UthCode 或 MewCode 的运行时兼容。

普通输入在 T02 中是单轮请求：

```text
输入 A → 仅发送 A
输入 B → 仅发送 B，不携带 A
```

Transcript 只属于 TUI 内存显示，不是 Agent 会话状态。

---

## 5. 冻结产品行为

### 5.1 TUI 与 Headless

- `uthcode` 无子命令时默认启动 Textual TUI。
- `uthcode exec [PROMPT]` 执行单轮非交互请求。
- `PROMPT` 缺失时，`exec` 从 stdin 读取。
- Slash Command 只在交互 TUI 中解析；`exec` 中以 `/` 开头的文本仍是普通 Prompt。
- Python Headless API 不依赖 Textual。
- 删除 `src/uthcode/interfaces/tui/` 后，Application 与 Headless 测试仍可运行。

### 5.2 GenerationHandle

Application 新增独立请求句柄：

```text
UthCodeApplication.start_generation(request)
→ GenerationHandle
   ├── events()
   ├── cancel()
   └── cancelled
```

要求：

- 每次请求创建独立 `CancellationToken`；
- `GenerationHandle.cancel()` 幂等；
- TUI 不导入或持有 Core `CancellationToken`；
- `stream_generation()` 内部通过 `start_generation()` 实现；
- Application 不建立“全局唯一活动请求”状态；
- TUI 自己限制同一界面一次只运行一个普通请求；
- Provider 终态校验继续由 Application 保证。

### 5.3 配置位置

用户级：

```text
~/.uthcode/config.toml
```

项目级：

```text
<目录>/.uthcode/config.toml
```

用户配置和项目配置使用相同文件名及相同基础 TOML 结构。

第一次运行时，如果用户配置不存在：

1. 创建 `~/.uthcode/`；
2. 通过临时文件加原子替换创建待填写模板；
3. POSIX 下尽可能将文件权限设置为仅当前用户可读写；
4. 不创建 Provider；
5. 不发起网络请求；
6. 终止本次启动；
7. 明确提示模板路径和“填写后重新运行”。

模板中的 Provider、Model 与 API Key 环境变量必须保持注释或明显占位状态，不得包含真实秘密，也不得默认读取 `.env`。

### 5.4 配置发现、递归与优先级

在 Git 仓库内，从仓库根目录到当前工作目录递归寻找：

```text
<ancestor>/.uthcode/config.toml
```

`.git` 可以是目录或 worktree 使用的文件。

加载顺序：

```text
内置默认
→ 用户 ~/.uthcode/config.toml
→ Git 根目录项目配置
→ 逐级靠近 cwd 的项目配置
→ cwd 项目配置
→ CLI 覆盖
→ 当前进程运行时选择
```

越靠近 cwd，项目配置优先级越高。

不在 Git 仓库时：

```text
只加载 cwd/.uthcode/config.toml
```

不得继续向用户主目录或文件系统根目录搜索项目配置。

候选路径在加载前必须：

```text
绝对化
→ 规范化
→ 解析符号链接
→ Windows 下进行大小写归一
→ 按物理路径去重
```

同一个物理文件只加载一次。

### 5.5 项目配置安全边界

用户配置是可信 Provider 来源。

项目配置允许：

- 覆盖顶层 `model`；
- 定义或覆盖 Model Profile；
- 修改非秘密模型参数；
- 引用用户配置中已存在的 Provider Profile。

项目配置禁止：

- 新增 `[providers.*]`；
- 覆盖 Provider `kind`；
- 覆盖 Provider `base_url`；
- 覆盖 Provider `api_key_env`；
- 定义新的秘密来源；
- 写入 API Key；
- 通过任何等价字段重定向凭据。

遇到以上字段时必须硬失败并指出配置文件路径及禁止字段，不得静默忽略。

### 5.6 配置结构

有效配置至少支持：

```toml
model = "deepseek/deepseek-v4-flash"

[providers.deepseek]
kind = "openai_compat"
base_url = "https://api.deepseek.com"
api_key_env = "DEEPSEEK_API_KEY"

[models."deepseek/deepseek-v4-flash"]
provider = "deepseek"
model = "deepseek-v4-flash"
label = "DeepSeek V4 Flash"
max_output_tokens = 8192
```

身份必须分离：

```text
Provider Profile ID：
deepseek

Model Ref：
deepseek/deepseek-v4-flash

远端 Model ID：
deepseek-v4-flash
```

约束：

- `model` 必须引用合并后存在的 Model Ref；
- Model Profile 必须引用存在且可信的 Provider Profile；
- Provider Profile 的 `kind` 必须映射到 T01 已支持的 `ProviderKind`；
- OpenAI-compatible Provider 仍要求显式 `base_url`；
- Fake Provider 仅用于测试或显式配置；
- API Key 真实值只通过 `api_key_env` 指向的进程环境变量读取；
- 配置对象、异常、日志、`repr` 和测试输出不得包含真实 Key。

### 5.7 模型切换与写回

`/model`：

- 无参数时打开 Model Picker；
- Picker 列出合并后全部 Model Profile；
- 显示 Model Ref、label、Provider Profile ID 和当前选择；
- 支持键盘选择；
- 选择后立即切换当前进程 Provider/Model；
- 同时只更新用户配置中的顶层 `model`；
- 不修改 `[providers.*]`；
- 不修改 `[models.*]`；
- 不修改项目配置；
- 不修改 CLI 参数来源。

`/model <model-ref>`：

- 跳过 Picker，直接执行相同切换流程；
- Model Ref 不存在时返回错误和候选提示；
- 生成任务正在运行时拒绝切换。

切换顺序固定为：

```text
验证 Model Ref
→ 构造候选 Provider
→ 原子写入用户配置顶层 model
→ 替换 Application 当前 Provider 与 current_model
→ 返回成功
```

任一步失败时：

- 当前 Provider 不变；
- 当前 Model Ref 不变；
- 用户配置不变；
- 错误不得包含秘密。

项目配置或 CLI 可以在下一次启动时再次覆盖用户默认模型。`/model` 不篡改项目配置。

使用 TOMLKit 修改用户配置，保留原有注释、表顺序和其他配置内容。

### 5.8 Slash Command Registry

项目只有一个正式 Registry。

以下内容必须全部从 Registry 生成：

- `/help`；
- 命令搜索；
- Command Completion Menu；
- 参数提示；
- alias；
- Usage；
- implemented / not implemented 状态；
- 静态参数候选；
- 动态参数候选。

禁止：

- TUI 内硬编码第二份命令列表；
- `/help` 单独维护命令列表；
- Completion 单独维护命令列表；
- Picker 读取命令常量；
- 为未来 Skill 创建适配器或占位模块。

Registry 必须公开稳定的：

```text
register(CommandDefinition)
resolve(name_or_alias)
list_commands()
```

注册时必须拒绝：

- canonical name 冲突；
- alias 与 canonical 冲突；
- alias 与 alias 冲突；
- 非小写或非法命令名；
- 重复 alias。

后续 Skill 可以直接调用该公开注册接口；本任务不实现 Skill 加载。

### 5.9 Command 类型与结果

保留三种语义：

```text
LOCAL
LOCAL_UI
PROMPT
```

它们必须通过 Dispatcher 与 `CommandOutcome` 形成真实不同的结果：

```text
LOCAL
→ CommandOutcome.output

LOCAL_UI
→ CommandOutcome.ui_action

PROMPT
→ CommandOutcome.prompt
```

`LOCAL_UI` 只能返回 UthCode 自有的结构化 UI Action，不得导入 Textual Widget。

当前 UI Action 至少包含：

```text
ClearTranscript
OpenModelPicker
QuitInterface
```

`CommandOutcome` 至少区分：

```text
SUCCESS
USAGE_ERROR
UNKNOWN_COMMAND
NOT_IMPLEMENTED
EXECUTION_ERROR
```

### 5.10 Parser

Parser 必须区分：

- 用户输入是否为 Slash Command；
- 原始调用名；
- canonical command；
- alias；
- 参数；
- query；
- `--` 分隔符；
- 未知命令；
- Usage 错误。

语义：

```text
/review 关注并发安全
```

对于没有结构化参数的 PROMPT 命令：

```text
query = "关注并发安全"
```

对于同时需要参数和 query 的 PROMPT 命令：

```text
/do target -- 请实现并测试
```

解析为：

```text
args = ["target"]
query = "请实现并测试"
```

要求：

- 命令名和 alias 大小写不敏感并归一为小写；
- 参数使用 `shlex` 语义支持引号；
- query 保留用户原始文本，不进行 `shlex` 重组；
- `/` 本身不执行命令；
- 普通文本不进入 Command Dispatcher。

即使当前 PROMPT 类内置命令均未实现，也必须使用合成测试命令证明 PROMPT 语义可运行。

### 5.11 Completion

Command Completion Menu 行为：

```text
输入 "/"
→ 显示全部非隐藏命令
→ /help 固定最后显示
```

```text
输入 "/c"
→ 显示 clear、compact 等匹配项
→ /help 固定最后显示
```

要求：

- canonical 和 alias 都参与匹配；
- 结果按 canonical 去重；
- `/help` 自身不得重复；
- 未实现命令仍显示，并标记“未实现”；
- 菜单可滚动，不得因固定 8 项上限而截断 `/` 的全部结果；
- Up/Down 切换；
- Esc 关闭；
- Tab 补全选中 canonical command；
- Enter 执行选中 command；
- 命令解析完成后显示 Usage 和参数提示；
- 支持静态参数候选；
- 支持动态参数候选；
- `/model` 的动态候选来自 Application 的 Model Catalog。

Command Completion Menu 与 Model Picker 必须是两个不同组件、两个不同状态对象。

### 5.12 内置命令

| Canonical | Alias | 类型 | T02 状态 | 行为 |
| --- | --- | --- | --- | --- |
| `/help` | `/h`、`/?` | LOCAL | 实现 | 从 Registry 生成总帮助或单命令帮助 |
| `/clear` | 无 | LOCAL_UI | 实现 | 返回 `ClearTranscript`，只清空 TUI Transcript |
| `/model` | `/models`、`/m` | LOCAL_UI | 实现 | 无参数打开 Picker；有参数切换模型 |
| `/status` | `/s` | LOCAL | 实现 | 显示当前模型、Provider、配置来源和运行状态，不显示秘密 |
| `/quit` | `/q`、`/exit` | LOCAL_UI | 实现 | 返回 `QuitInterface` |
| `/config` | 无 | LOCAL | 未实现 | 返回 `功能未实现：/config` |
| `/compact` | `/c` | LOCAL | 未实现 | 返回 `功能未实现：/compact` |
| `/plan` | `/p` | LOCAL_UI | 未实现 | 返回 `功能未实现：/plan` |
| `/new` | 无 | LOCAL | 未实现 | 返回 `功能未实现：/new` |
| `/resume` | 无 | LOCAL_UI | 未实现 | 返回 `功能未实现：/resume` |
| `/login` | 无 | LOCAL | 未实现 | 返回 `功能未实现：/login` |
| `/memory` | 无 | LOCAL | 未实现 | 返回 `功能未实现：/memory` |
| `/dream` | 无 | PROMPT | 未实现 | 返回 `功能未实现：/dream` |
| `/do` | 无 | PROMPT | 未实现 | 返回 `功能未实现：/do` |
| `/review` | 无 | PROMPT | 未实现 | 返回 `功能未实现：/review` |

`/models` 是 `/model` 的 alias，不注册第二个 canonical command。

`/clear` 不清除 Application 状态、配置或未来会话；`/new` 才负责未来的新会话语义，本任务保持未实现。

### 5.13 TUI

当前选择性迁移：

- Topbar；
- Transcript；
- Markdown；
- Composer；
- 流式渲染；
- 滚动保护；
- 双 Esc 中断；
- Model Picker；
- TCSS 视觉基线。

当前不迁移：

- Tool UI；
- Permission UI；
- Diff；
- Task Plan；
- Session Picker；
- Context；
- Skill；
- MCP；
- 附件；
- FirstCoder 的 Provider/Agent/Session 运行逻辑。

TUI 布局：

```text
┌ Topbar：UthCode | current model | cwd/project ┐
│                                               │
│ Transcript                                    │
│                                               │
├ Activity / status line                        ┤
├ Command Completion Menu 或 Model Picker       ┤
└ Composer                                      ┘
```

Transcript Entry 仅包含当前真实需要的类型：

```text
USER
ASSISTANT
REASONING
COMMAND
SYSTEM
ERROR
```

普通请求：

1. 将用户文本写入 Transcript；
2. 创建单条 `GenerationRequest`；
3. 调用 `UthCodeApplication.start_generation()`；
4. 消费 `ProviderEvent`；
5. `TextDelta` 进入 Assistant Markdown 缓冲区；
6. `ReasoningDelta` 进入简洁的 reasoning transcript 块；
7. `GenerationCompleted` 强制 flush 并结束活动状态；
8. 不保存历史；
9. 下一次请求不携带本次消息。

流式 Markdown：

- 不为每个 token 重建 Widget；
- 使用缓冲与定时批量刷新；
- 刷新间隔以 FirstCoder 的 `0.2s` 为基线；
- 终态、取消和异常前必须立即 flush；
- 流式更新期间禁止选择被替换的 Markdown block；
- 最终完成后恢复文本选择；
- Markdown 更新产生的异步取消不应被误报为应用错误。

滚动保护：

- 用户位于底部时，新内容自动跟随；
- 用户主动向上滚动后，新内容不得强制拉回底部；
- 用户重新滚到底部后恢复自动跟随；
- `/clear` 后滚动状态复位。

Composer：

- Enter 发送；
- Shift+Enter 换行；
- 空输入不发送；
- 生成进行中时拒绝第二个普通请求；
- Slash Command 仍可进入 Dispatcher，但 `/model` 在生成中必须拒绝切换；
- 本任务不实现附件或图片粘贴。

双 Esc：

```text
无弹层 + 正在生成
第一次 Esc
→ 状态行提示再次按 Esc 中断
→ 开启 1 秒窗口

1 秒内第二次 Esc
→ GenerationHandle.cancel()
```

优先级：

```text
Command Completion Menu 打开时 Esc
→ 关闭菜单，不触发中断

Model Picker 打开时 Esc
→ 关闭 Picker，不触发中断

无弹层时
→ 进入双 Esc 中断逻辑
```

### 5.14 Headless exec

```text
uthcode exec "解释这个目录"
echo "解释这个目录" | uthcode exec
```

最小参数：

```text
--cwd PATH
--model MODEL_REF
```

规则：

- `--cwd` 决定项目配置发现起点；
- `--model` 是当前进程 CLI 覆盖，不持久化；
- 有位置 Prompt 时使用位置 Prompt；
- 无位置 Prompt 时读取 stdin；
- 空 Prompt 返回 usage error；
- TextDelta 写 stdout；
- 状态、配置错误和诊断写 stderr；
- 成功后保证 stdout 以换行结束；
- Ctrl+C 或取消返回 130；
- 配置或 CLI 使用错误返回 2；
- Provider 或协议错误返回 1；
- 成功返回 0；
- 不输出 ANSI TUI 控制序列；
- 不解析 Slash Command；
- 不加载 Textual App。

---

## 6. 原始探索要求处理表

| 原要求 | 处理 | 新版落实方式 | 验收方式 |
| --- | --- | --- | --- |
| 官方默认 Textual TUI，同时保留 Headless | 保留 | `uthcode`、`uthcode exec`、Python API | CLI、TUI、Headless 测试 |
| FirstCoder 为视觉交互基线 | 调整 | 固定参考 Commit，选择性迁移并保留许可证 | 来源检查、无整体复制 |
| 迁移 Topbar、Transcript、Markdown、Composer、流式、滚动、双 Esc、Picker、TCSS | 保留 | UthCode 自有 TUI 文件重写 | Textual Pilot 测试 |
| 不迁移 Tool、Permission、Diff、Task Plan、Session、Context、Skill、MCP、附件 UI | 保留 | 不创建对应文件和状态 | 目录与依赖扫描 |
| 采用 MewCode Registry、alias、CompletionPopup 思路 | 调整 | Application 层重写 Registry/Parser/Completion；TUI 只实现 Widget | 单元测试 |
| 命令只有一个正式 Registry | 保留 | Help、Completion、Usage、状态全部从 Registry 生成 | 架构测试 |
| local、local-ui、prompt 必须真实执行 | 保留 | Dispatcher + CommandOutcome 三种结构化结果 | 合成命令测试 |
| local-ui 不依赖 Textual Widget | 保留 | UthCode 自有 UI Action dataclass union | import 边界测试 |
| Parser 区分 canonical、alias、参数、query、`--` | 保留 | Registry-aware Parser | parser 测试 |
| `/` 全部、`/c` 匹配、`/help` 固定最后且不重复 | 保留 | 纯 Application Completion Engine | completion 测试 |
| Up/Down、Esc、Tab、Enter、Usage、静态和动态候选 | 保留 | TUI Completion Menu + Application candidates | Textual Pilot 测试 |
| Completion Menu 与 Picker 分离 | 保留 | 两个模块、两个状态对象 | 架构与交互测试 |
| 实现 help、clear、model、models、status、config、quit | 调整 | `/config` 经用户决定改为注册但未实现；`/models` 为 alias | builtins 测试 |
| 其他命令注册但未实现 | 保留 | Registry availability + 固定未实现结果 | 参数化测试 |
| clear 只清 UI，new 才新会话 | 保留 | `ClearTranscript`；`/new` 未实现 | TUI 测试 |
| Skill 复用 Registry 公开接口 | 保留 | 提供公开 `register`，不实现 Skill Adapter | Registry API 测试 |
| 多层 config 与 API Key 环境变量 | 调整 | 递归项目配置、项目 Provider 禁止覆盖、CLI/运行时优先级 | config 测试 |
| 不默认读取项目 `.env`；login 后置 | 保留 | 不增加 dotenv；`/login` 未实现 | 依赖和代码扫描 |
| TUI 只能调用 Application Port | 保留 | interfaces 不导入 core/integrations | architecture test |
| 必须核对 T01 Provider、Streaming、取消和模型协议 | 已完成 | 以本任务基线文件为准，扩展 Application 不改 Core Provider 契约 | T01 回归测试 |

---

## 7. 前置任务影响表

| 前置文件/能力 | 当前状态 | 本次使用 | 是否修改 | 原因 | 回归 |
| --- | --- | --- | --- | --- | --- |
| `core/provider.py` | 已验收 | Request、Event、ProviderPort、CancellationToken | 保持不动 | Core 契约已满足 | 全部 Provider contract 测试 |
| `application/generation.py` | 单 Provider stream | GenerationHandle、模型选择、流终态 | 修改 | 隔离 TUI 取消与支持运行时模型切换 | 更新 `test_application.py` |
| `application/bootstrap.py` | 单 ProviderConfig 组合 | EffectiveConfig → ProviderConfig → Provider | 修改 | 多来源配置与 Model Catalog | bootstrap/config 测试 |
| `application/__init__.py` | 导出 T01 API | 导出 Application Config、Command、Handle | 修改 | 新正式 Application Port | import 测试 |
| `integrations/providers/config.py` | Provider 构造参数 | 由 bootstrap 内部生成 | 原则上保留 | 不把配置文件结构塞入 Provider Factory | provider factory 回归 |
| `integrations/providers/factory.py` | 唯一 Provider 构造出口 | 模型切换时重复构造 | 保持不动 | 构造已满足且无网络 | provider factory 回归 |
| Provider 协议适配器 | 已验收 | TUI/exec 间接调用 | 保持不动 | 不属于 T02 | 三协议离线与 live 跳过测试 |
| `tests/test_architecture_boundaries.py` | 约束无 interfaces | 更新为 T02 新边界 | 修改 | T02 正式引入 interfaces | architecture 回归 |
| README | T01 Headless 说明 | 增加 TUI、exec、config | 修改 | 正式入口变化 | 示例 smoke test |
| `SRe-AGENTS.md` | Slash/TUI 后置 | 更新阶段规则 | 修改 | 用户已批准解除冲突 | 文档审查 |

---

## 8. 目标目录树

标记：

```text
[新] 新增
[改] 修改
[保] 保留不动
```

```text
Re-UthCode/
├── [改] SRe-AGENTS.md
├── [改] README.md
├── [改] pyproject.toml
├── [新] LICENSES/
│   └── FirstCoder-MIT.txt
├── src/uthcode/
│   ├── [新] __main__.py
│   ├── application/
│   │   ├── [改] __init__.py
│   │   ├── [改] bootstrap.py
│   │   ├── [改] generation.py
│   │   ├── [新] configuration.py
│   │   └── [新] commands/
│   │       ├── __init__.py
│   │       ├── models.py
│   │       ├── registry.py
│   │       ├── parser.py
│   │       ├── completion.py
│   │       ├── dispatcher.py
│   │       └── builtins.py
│   ├── core/
│   │   └── [保] provider.py
│   ├── integrations/
│   │   ├── [新] config/
│   │   │   ├── __init__.py
│   │   │   ├── template.py
│   │   │   ├── loader.py
│   │   │   └── writer.py
│   │   └── providers/
│   │       ├── [保] config.py
│   │       ├── [保] factory.py
│   │       └── [保] 现有 Provider 文件
│   └── [新] interfaces/
│       ├── __init__.py
│       ├── cli.py
│       └── tui/
│           ├── __init__.py
│           ├── app.py
│           ├── state.py
│           ├── widgets.py
│           ├── rendering.py
│           ├── completion.py
│           ├── picker.py
│           └── tui.tcss
└── tests/
    ├── [改] test_application.py
    ├── [改] test_architecture_boundaries.py
    ├── [新] test_configuration.py
    ├── [新] test_application_runtime.py
    ├── [新] test_command_registry.py
    ├── [新] test_command_parser.py
    ├── [新] test_command_completion.py
    ├── [新] test_command_dispatcher.py
    ├── [新] test_cli.py
    └── [新] test_tui.py
```

不得创建：

```text
session/
tools/
permissions/
skills/
mcp/
context/
memory/
login/
attachments/
task_plan/
diff/
```

---

## 9. 文件级任务清单

| 文件路径 | 操作 | 职责与核心内容 | 允许依赖 | 禁止依赖 | 对应测试 |
| --- | --- | --- | --- | --- | --- |
| `SRe-AGENTS.md` | 修改 | 将 Slash Command、默认 TUI 从后置移出；写入新的 config 递归、安全和 Interface 约束 | 无 | 实现细节堆砌 | 人工审查 |
| `README.md` | 修改 | 说明 `uthcode`、`uthcode exec`、首次配置模板、示例配置、单轮限制 | 无 | 真实 Key | CLI smoke |
| `pyproject.toml` | 修改 | 添加 Textual、TOMLKit 和 `uthcode` console script | PyPI 依赖 | Typer、dotenv、LangGraph | `pip check` |
| `LICENSES/FirstCoder-MIT.txt` | 新增 | 保留 FirstCoder MIT 声明 | 无 | 修改许可证文本 | 文件存在检查 |
| `src/uthcode/__main__.py` | 新增 | `python -m uthcode` 转发 CLI `main()` | `interfaces.cli` | core、SDK | `test_cli.py` |
| `application/configuration.py` | 新增 | `LaunchOptions`、`ConfigSource`、`ProviderProfile`、`ModelProfile`、`EffectiveConfig`；验证不可变配置和 `single_model` Headless 构造 | stdlib | Textual、文件 I/O、SDK | `test_configuration.py` |
| `application/bootstrap.py` | 修改 | 配置加载 Application 门面；将 Profile 组合为 T01 `ProviderConfig`；注入 Provider builder 和模型 writer | application、integrations | Textual | `test_application_runtime.py` |
| `application/generation.py` | 修改 | `GenerationHandle`；`start_generation`；现有 stream 复用；当前模型状态；模型切换的全成全败流程 | core、application types、注入 callable | Textual、TOMLKit、SDK | `test_application.py`、`test_application_runtime.py` |
| `application/__init__.py` | 修改 | 只公开 Interface/Headless 所需的 UthCode 类型与入口 | application | SDK 类型 | import 测试 |
| `application/commands/models.py` | 新增 | CommandKind、Availability、ArgumentSpec、Invocation、Outcome、UiAction、Candidate | stdlib、application config types | Textual | command tests |
| `application/commands/registry.py` | 新增 | 唯一 Registry、注册冲突校验、canonical/alias resolve、稳定排序 | command models | TUI | `test_command_registry.py` |
| `application/commands/parser.py` | 新增 | Registry-aware parser、`shlex` 参数、raw query、`--` | registry/models | TUI | `test_command_parser.py` |
| `application/commands/completion.py` | 新增 | canonical/alias 搜索、help 固定最后、Usage、静态/动态参数候选 | registry/application | Textual | `test_command_completion.py` |
| `application/commands/dispatcher.py` | 新增 | 执行 LOCAL/LOCAL_UI/PROMPT；统一错误和未实现结果 | application、command models | Textual | `test_command_dispatcher.py` |
| `application/commands/builtins.py` | 新增 | 单一内置命令注册表、help/status/model/clear/quit handler、未实现命令元数据 | dispatcher、application | TUI Widget | command tests |
| `application/commands/__init__.py` | 新增 | 公开未来 Skill 可复用的最小 Registry API | commands | Textual | import 测试 |
| `integrations/config/template.py` | 新增 | 用户配置待填模板常量；不得包含可用秘密 | stdlib | Provider SDK | `test_configuration.py` |
| `integrations/config/loader.py` | 新增 | 用户模板初始化、Git 根发现、递归路径、去重、TOML parse、层级 merge、项目安全校验、EffectiveConfig 构造 | TOMLKit、application config | Textual、dotenv | `test_configuration.py` |
| `integrations/config/writer.py` | 新增 | 仅原子修改用户配置顶层 `model`，保留注释与其他表 | TOMLKit、filesystem | 项目配置写入 | `test_configuration.py` |
| `integrations/config/__init__.py` | 新增 | 仅向 bootstrap 暴露 loader/writer，不作为 Interface API | config modules | Textual | architecture test |
| `interfaces/cli.py` | 新增 | argparse；默认 TUI；`exec`；cwd/model override；stdout/stderr/exit code | application | core、integrations、Textual 具体 Widget（除启动 TUI 类） | `test_cli.py` |
| `interfaces/__init__.py` | 新增 | Interface 包说明，不导出 Core | 无 | core、SDK | architecture test |
| `interfaces/tui/state.py` | 新增 | TranscriptEntry、TranscriptState、StreamRenderState、ScrollFollowState、EscArmState | application event/outcome types | core、SDK | `test_tui.py` |
| `interfaces/tui/widgets.py` | 迁移后重写 | Topbar、Markdown、Composer；保留 FirstCoder Enter/Shift+Enter 与 selectable Markdown 行为，删除附件耦合 | Textual、TUI state | Provider/Agent/Session | `test_tui.py` |
| `interfaces/tui/rendering.py` | 迁移后重写 | ProviderEvent 到 Transcript 的批量刷新、终态 flush、reasoning 简洁渲染、滚动跟随 | Textual、application events | Tool UI、Session | `test_tui.py` |
| `interfaces/tui/completion.py` | 迁移后重写 | Command Completion Menu Widget 与键盘控制；消费 Application Candidate | Textual、application commands | Model Picker 状态复用 | `test_tui.py` |
| `interfaces/tui/picker.py` | 迁移后重写 | 独立通用 Picker 状态和 Model Picker Widget | Textual、application model profiles | Session/Skill Picker | `test_tui.py` |
| `interfaces/tui/app.py` | 迁移后重写 | TUI 编排；只调用 Application API；普通输入、命令、流式 worker、双 Esc、清屏、退出、模型选择 | Textual、application | core、integrations、SDK | `test_tui.py` |
| `interfaces/tui/tui.tcss` | 迁移后重写 | 选择性采用 FirstCoder 色彩、Topbar、Transcript、Composer 基线；删除 Tool/Permission/Task Plan 样式 | Textual CSS | 未使用未来 UI 样式 | TUI smoke |
| `interfaces/tui/__init__.py` | 新增 | 公开 TUI 启动类/函数 | TUI modules | core、SDK | import test |
| `tests/test_application.py` | 修改 | 改用 GenerationHandle，保留 T01 流和终态回归 | pytest | 网络 | 全部通过 |
| `tests/test_application_runtime.py` | 新增 | 模型切换、持久化顺序、失败回滚、并发独立句柄 | Fake Provider | 网络 | 全部通过 |
| `tests/test_configuration.py` | 新增 | 模板、递归、优先级、去重、安全、TOML 保真、秘密脱敏 | tmp_path | 网络 | 全部通过 |
| `tests/test_command_*.py` | 新增 | Registry、Parser、Completion、Dispatcher、builtins | application commands | Textual（除 TUI 测试） | 全部通过 |
| `tests/test_cli.py` | 新增 | 默认 TUI 分派、exec、stdin、输出和退出码 | Fake Application | 真 TTY/网络 | 全部通过 |
| `tests/test_tui.py` | 新增 | Textual Pilot 验证组件、流、滚动、Esc、菜单、Picker、命令 | Textual、Fake Application | 网络、真实 Provider | 全部通过 |
| `tests/test_architecture_boundaries.py` | 修改 | 允许 interfaces 存在；禁止 interfaces→core/integrations；禁止 core→Textual/TOMLKit | AST/文件扫描 | 宽泛脆弱断言 | 全部通过 |

---

## 10. 依赖与数据流

### 10.1 配置加载

```text
CLI LaunchOptions
→ application.load_effective_config()
→ integrations.config.loader
→ 发现用户/项目 config.toml
→ 校验项目安全边界
→ 合并 Provider/Model/Profile
→ EffectiveConfig
→ application.create_application()
→ integrations.providers.factory.create_provider()
→ UthCodeApplication
```

配置文件的解析树和 TOMLKit 类型不得越过 Integration。Application 只接收 UthCode 自有的不可变配置模型。

### 10.2 普通输入

```text
Composer text
→ TUI 构造单消息 GenerationRequest
→ UthCodeApplication.start_generation()
→ GenerationHandle.events()
→ ProviderEvent
→ TUI rendering
```

TUI 不保存可回送 Provider 的消息历史。

### 10.3 Slash Command

```text
Composer slash text
→ Parser
→ Registry resolve
→ Dispatcher
→ CommandOutcome
   ├── output
   ├── ui_action
   └── prompt
→ TUI 适配结果
```

当前内置 PROMPT 命令未实现，因此不会启动生成；PROMPT 语义只通过合成注册测试证明。

### 10.4 模型切换

```text
/model <ref>
→ Dispatcher
→ UthCodeApplication.select_model(ref)
→ Provider builder 构造候选 Provider
→ Model writer 更新用户 config.toml 顶层 model
→ Application 原子替换 current model/provider
→ CommandOutcome.success
```

### 10.5 取消

```text
第一次 Esc
→ TUI EscArmState

第二次 Esc
→ GenerationHandle.cancel()
→ 内部 CancellationToken.cancel()
→ Provider Integration
→ GenerationCancelled
→ TUI flush + cancelled 状态
```

---

## 11. 第三方依赖

### 11.1 Textual

版本范围：

```toml
"textual>=8.2,<9"
```

用途仅限：

```text
src/uthcode/interfaces/tui/
```

以及 TUI 测试。

不得进入：

```text
core/
application/commands/
application/configuration.py
integrations/providers/
```

采用原因：

- 提供终端布局、输入、Markdown、滚动、异步 Worker 与测试 Pilot；
- FirstCoder 基线已使用 Textual；
- 自行实现终端状态机和跨平台输入不具备收益。

替换成本：只影响 `interfaces/tui/`，Application 与 Headless 不应变化。

### 11.2 TOMLKit

版本范围：

```toml
"tomlkit>=0.15,<0.16"
```

用途仅限：

```text
src/uthcode/integrations/config/
```

采用原因：

- 读取 TOML；
- 回写顶层 `model` 时保留注释、表顺序和用户格式；
- 标准库 `tomllib` 不提供写入。

替换成本：只影响配置 Integration，不改变 Application 配置模型。

### 11.3 不新增

不得新增：

- Typer / Click；
- python-dotenv；
- Rich 直依赖；
- LangGraph / LangChain；
- 配置热重载库；
- DI 容器；
- 通用事件总线；
- Session 或持久化框架。

顶层 CLI 使用标准库 `argparse`。

---

## 12. 实施任务拆分

### Task 1：更新阶段约束与依赖

**目标**

解除全局规则冲突并准备正式入口依赖。

**涉及文件**

```text
SRe-AGENTS.md
pyproject.toml
LICENSES/FirstCoder-MIT.txt
```

**完成结果**

- Slash Command、默认 TUI 不再被声明为后置；
- 配置规则与本任务一致；
- 安装 Textual/TOMLKit；
- 注册 `uthcode` console script；
- 保留 FirstCoder MIT 声明。

**测试**

```text
python -m pip install -e . --group dev
python -m pip check
```

**明确不做**

不创建 TUI 或命令占位目录之外的未来能力。

**提交边界**

只提交规则、依赖和许可证。

---

### Task 2：实现 Application 配置模型

**目标**

建立 UthCode 自有的多 Provider、多 Model 有效配置模型。

**涉及文件**

```text
src/uthcode/application/configuration.py
src/uthcode/application/__init__.py
tests/test_configuration.py
```

**完成结果**

- Profile ID、Model Ref、远端 Model ID 分离；
- 配置模型不可变；
- 验证 unknown provider/model；
- 提供 Headless 单模型构造入口；
- 不包含 TOMLKit 类型。

**测试**

仅运行配置模型单元测试。

**明确不做**

不读写文件，不构造 Provider。

**提交边界**

Application 纯模型。

---

### Task 3：实现配置发现、合并、安全与写回

**目标**

实现用户模板、递归项目配置、优先级、去重和安全写回。

**涉及文件**

```text
src/uthcode/integrations/config/*
tests/test_configuration.py
```

**完成结果**

- 首次模板原子创建后停止；
- Git 根到 cwd 递归加载；
- 非 Git 只读 cwd；
- 物理路径去重；
- 项目 Provider 字段硬失败；
- CLI model 覆盖；
- TOMLKit 只修改用户顶层 model；
- 注释与其他配置保持。

**测试**

覆盖所有配置矩阵，不发起网络请求。

**明确不做**

不读取 `.env`，不编辑项目配置，不做热重载。

**提交边界**

完整配置 Integration。

---

### Task 4：扩展 Application Runtime

**目标**

实现 GenerationHandle 和全成全败模型切换。

**涉及文件**

```text
src/uthcode/application/generation.py
src/uthcode/application/bootstrap.py
src/uthcode/application/__init__.py
tests/test_application.py
tests/test_application_runtime.py
```

**完成结果**

- TUI 可通过 Handle 取消；
- `stream_generation` 复用 Handle；
- Application 提供 Model Catalog/current model/status；
- Provider 构造仍只有 Integration Factory；
- 切换失败时 Provider、配置和 current model 均不变；
- 更新 T01 Headless 示例所需 API。

**测试**

Application、Provider Factory 和 Provider Contract 回归。

**明确不做**

不引入 Session 或全局 active generation。

**提交边界**

Application 正式调用面。

---

### Task 5：实现 Command Registry 与 Parser

**目标**

形成唯一正式 Registry 和准确解析模型。

**涉及文件**

```text
src/uthcode/application/commands/models.py
src/uthcode/application/commands/registry.py
src/uthcode/application/commands/parser.py
src/uthcode/application/commands/__init__.py
tests/test_command_registry.py
tests/test_command_parser.py
```

**完成结果**

- canonical/alias 冲突检查；
- 参数/query/`--` 语义；
- 公开未来 Skill 可调用的 `register`；
- 不依赖 TUI。

**测试**

Registry 和 Parser 独立测试。

**明确不做**

不实现 Skill Loader。

**提交边界**

命令定义与解析。

---

### Task 6：实现 Completion、Dispatcher 与内置命令

**目标**

完成三种命令语义和单来源帮助/补全。

**涉及文件**

```text
src/uthcode/application/commands/completion.py
src/uthcode/application/commands/dispatcher.py
src/uthcode/application/commands/builtins.py
tests/test_command_completion.py
tests/test_command_dispatcher.py
```

**完成结果**

- `/` 全部；
- `/c` clear/compact；
- help 固定最后；
- static/dynamic args；
- LOCAL/LOCAL_UI/PROMPT 结果分离；
- builtins 表完整；
- 未实现命令统一返回；
- `/model` 动态读取 Application catalog。

**测试**

使用合成命令覆盖三类语义；不引入 Textual。

**明确不做**

不真正实现 compact/plan/new/resume/login/memory/dream/do/review/config。

**提交边界**

Application Command System。

---

### Task 7：实现默认 CLI 与 Headless exec

**目标**

建立无子命令 TUI 默认入口和非交互执行入口。

**涉及文件**

```text
src/uthcode/__main__.py
src/uthcode/interfaces/__init__.py
src/uthcode/interfaces/cli.py
tests/test_cli.py
```

**完成结果**

- `uthcode` 进入 TUI；
- `uthcode exec` 使用同一 Application；
- prompt/stdin、cwd/model override；
- stdout/stderr/exit code；
- `python -m uthcode` 可用。

**测试**

全部使用 Fake Application 或注入式 runner，禁止真终端和网络。

**明确不做**

不增加更多 CLI 子命令。

**提交边界**

CLI 与 Headless。

---

### Task 8：实现 TUI 基础组件和流式渲染

**目标**

迁移后重写 FirstCoder 的基础视觉与渲染机制。

**涉及文件**

```text
src/uthcode/interfaces/tui/state.py
src/uthcode/interfaces/tui/widgets.py
src/uthcode/interfaces/tui/rendering.py
src/uthcode/interfaces/tui/tui.tcss
LICENSES/FirstCoder-MIT.txt
tests/test_tui.py
```

**完成结果**

- Topbar、Transcript、Composer、Markdown；
- 0.2s 批量刷新；
- reasoning 简洁显示；
- 滚动保护；
- Enter/Shift+Enter；
- 无 Tool/Permission/Task/附件代码。

**测试**

Textual Pilot 与纯状态测试。

**明确不做**

不接命令菜单或 Picker。

**提交边界**

TUI 基础视图。

---

### Task 9：实现 Completion Menu、Model Picker 与双 Esc

**目标**

完成 TUI 交互状态和 Application 接入。

**涉及文件**

```text
src/uthcode/interfaces/tui/completion.py
src/uthcode/interfaces/tui/picker.py
src/uthcode/interfaces/tui/app.py
src/uthcode/interfaces/tui/__init__.py
tests/test_tui.py
```

**完成结果**

- Completion Menu 与 Picker 独立；
- Up/Down/Esc/Tab/Enter；
- `/model` Picker；
- `/clear`、`/quit`；
- 双 Esc 取消；
- 单活动普通请求；
- TUI 只导入 Application。

**测试**

Textual Pilot 覆盖键盘优先级和取消链路。

**明确不做**

不实现 Session/Skill Picker。

**提交边界**

完整默认 TUI。

---

### Task 10：[接入主流程] 接入正式启动链路

**目标**

从安装后的正式入口完成配置、TUI、命令、模型切换与 exec 调用。

**涉及文件**

```text
README.md
src/uthcode/application/__init__.py
src/uthcode/interfaces/cli.py
相关测试
```

**完成结果**

```text
uthcode
uthcode exec
python -m uthcode
```

均走同一配置和 Application 组合链。

更新 README，不保留 T01 已失效的入口说明。

**测试**

正式入口 smoke，不访问网络。

**明确不做**

不创建旧入口兼容包装。

**提交边界**

主链收口。

---

### Task 11：[端到端验证] 验证真实用户流程

**目标**

验证完整离线用户流程和关键失败路径。

**场景**

1. 用户配置不存在；
2. 启动创建模板并停止；
3. 填写 Fake Provider/Model；
4. `uthcode` 进入 TUI；
5. 输入 `/`、`/c`、`/help`；
6. 输入普通 Prompt 获得流式输出；
7. `/clear` 清空；
8. `/model` 切换；
9. 双 Esc 取消延迟 Fake 请求；
10. `uthcode exec` 输出结果；
11. 项目配置试图定义 Provider 被拒绝；
12. interfaces 删除或隔离时 Headless 测试仍通过。

**测试**

```text
pytest -q
python -m compileall -q src tests
python -m pip check
```

真实 Provider 测试仍必须受既有 live 开关和用户费用确认约束。

**提交边界**

只修复本任务范围内发现的问题。

---

### Task 12：[遗留负担清理] 清理重复职责和越界依赖

**目标**

确认 T02 没有引入双 Registry、双 Config、TUI 反向依赖和未来占位。

**检查**

- 只有一个 built-in Registry；
- `/help` 和 Completion 不含硬编码第二列表；
- interfaces 不导入 core/integrations；
- core 不导入 Textual/TOMLKit；
- 不存在 dotenv；
- 不存在旧 UthCode/MewCode 运行时依赖；
- 不存在 FirstCoder 包依赖；
- 不存在 Tool/Permission/Session/Skill/MCP 占位；
- 不存在已替代 T01 组合入口的不可达代码；
- README、公开导出和测试使用同一正式入口。

**提交边界**

仅删除本任务产生或暴露的重复代码。

---

## 13. 测试矩阵

| 场景 | 预期 | 测试文件 |
| --- | --- | --- |
| 用户配置不存在 | 创建注释模板、0 网络、启动失败并给出路径 | `test_configuration.py` |
| 用户配置有效 | 生成 EffectiveConfig | `test_configuration.py` |
| 根到 cwd 多层配置 | 越近 cwd 优先 | `test_configuration.py` |
| 非 Git cwd 配置 | 只加载 cwd | `test_configuration.py` |
| symlink/大小写重复 | 同一物理文件只加载一次 | `test_configuration.py` |
| 项目定义 Provider | 硬失败，报告路径/字段 | `test_configuration.py` |
| 项目定义 Model 引用用户 Provider | 成功 | `test_configuration.py` |
| Model Ref 不存在 | 配置失败 | `test_configuration.py` |
| `/model` 写回 | 只改用户顶层 model，注释/表保持 | `test_configuration.py` |
| Provider 构造失败 | current model 和文件均不变 | `test_application_runtime.py` |
| 写回失败 | current Provider 和 model 均不变 | `test_application_runtime.py` |
| 两个 GenerationHandle | 取消一个不影响另一个 | `test_application_runtime.py` |
| Provider 缺终态/多终态 | 继续由 Application 拒绝 | `test_application.py` |
| Registry 名称/alias 冲突 | 注册失败 | `test_command_registry.py` |
| alias resolve | 得到 canonical | `test_command_registry.py` |
| `/review query` | query 原文保留 | `test_command_parser.py` |
| `args -- query` | 参数和 query 分离 | `test_command_parser.py` |
| `/` completion | 全部命令，help 最后且一次 | `test_command_completion.py` |
| `/c` completion | clear、compact、help | `test_command_completion.py` |
| 动态 model 候选 | 来自 Application Catalog | `test_command_completion.py` |
| LOCAL | 输出结果 | `test_command_dispatcher.py` |
| LOCAL_UI | 结构化 UI Action | `test_command_dispatcher.py` |
| PROMPT | Prompt Outcome | `test_command_dispatcher.py` |
| 未实现命令 | `功能未实现：/<canonical>` | `test_command_dispatcher.py` |
| TUI 普通输入 | 单轮请求、流式 Markdown | `test_tui.py` |
| 用户向上滚动 | 新输出不强制到底 | `test_tui.py` |
| Completion Esc | 只关菜单 | `test_tui.py` |
| Picker Esc | 只关 Picker | `test_tui.py` |
| 双 Esc | 第二次取消 Handle | `test_tui.py` |
| `/clear` | 只清 Transcript | `test_tui.py` |
| `/model` | 打开独立 Picker并切换 | `test_tui.py` |
| 生成中 `/model` | 拒绝切换 | `test_tui.py` |
| `uthcode` | 默认启动 TUI | `test_cli.py` |
| `uthcode exec PROMPT` | stdout 文本、0 | `test_cli.py` |
| stdin exec | 正常读取 | `test_cli.py` |
| exec 配置失败 | stderr、2 | `test_cli.py` |
| exec Provider 错误 | stderr、1 | `test_cli.py` |
| exec Ctrl+C | 130 | `test_cli.py` |
| Interface 边界 | 不导入 core/integrations | `test_architecture_boundaries.py` |
| Headless 无 TUI | Application 测试可独立运行 | `test_architecture_boundaries.py` |
| 无后续能力偷跑 | 禁止目录/模块不存在 | `test_architecture_boundaries.py` |
| T01 回归 | Provider 与三协议测试不退化 | 现有测试 |

---

## 14. 删除与清理

本任务原则上不删除 T01 Core 或 Provider 文件。

允许删除或替换：

- T01 README 中已失效的“没有 CLI/TUI”说明；
- 被新 `EffectiveConfig` 取代且没有真实调用方的 Application 配置导出；
- 新实现过程中产生的临时入口；
- FirstCoder 迁移时残留的附件、Tool、Permission、Task Plan、Session 代码；
- Command 列表的任何第二份硬编码副本；
- 已失效测试。

不得保留：

- `legacy_*`；
- `compat_*`；
- 旧/新配置双轨；
- 旧/新 Application bootstrap 双轨；
- MewCode/FirstCoder import；
- 为未来命令创建的空 handler 文件；
- 未使用的 UI Action；
- 未使用的 Protocol、Manager、Factory 或 Repository。

---

## 15. 验收标准

T02 通过验收必须同时满足：

1. 安装后执行 `uthcode` 默认进入可交互 Textual TUI。
2. `uthcode exec` 和 Python API 在不启动 TUI 的情况下可完成单轮请求。
3. 首次运行在用户配置不存在时创建安全待填模板并停止，不发网络请求。
4. 用户配置、多层项目配置、CLI 和运行时选择遵守冻结优先级。
5. 项目配置无法定义或重定向 Provider、端点和秘密来源。
6. 多 Provider Profile、多 Model Profile 能被解析和验证。
7. `/model` 展示全部模型，切换当前 Provider，并只持久化用户顶层 `model`。
8. `/models` 作为 alias 工作，不存在第二个命令定义。
9. `/help`、Completion、Usage、alias 和实现状态全部来自唯一 Registry。
10. `/`、`/c` 和 `/help` 固定排序行为准确。
11. LOCAL、LOCAL_UI、PROMPT 均有真实 Dispatcher/Outcome 测试。
12. 未实现命令统一返回 `功能未实现：/<canonical>`。
13. TUI 支持 Topbar、Transcript、Markdown、Composer、流式刷新、滚动保护、双 Esc、Completion Menu 和 Model Picker。
14. Command Completion Menu 与 Model Picker 是不同组件和状态。
15. `/clear` 只清 UI，`/new` 保持未实现。
16. TUI 只调用 Application API，不导入 Core、Integration 或 Provider SDK。
17. Application 的 `GenerationHandle` 隔离每次取消。
18. 现有 T01 Provider Contract、Factory、三协议与 Headless 回归测试全部通过。
19. 默认测试离线；live 测试仍须显式授权。
20. 没有 Agent Loop、Session、Tool、Permission、Context、Skill、MCP、附件等未来能力占位。
21. 没有旧 UthCode、MewCode 或 FirstCoder 运行时依赖。
22. FirstCoder 实质代码迁移符合 MIT 声明要求。
23. `pytest -q`、`compileall`、`pip check` 全部通过。
24. T02 完成后的 Application 和 Interface 边界可以作为后续 Agent Loop 的真实基线，无需推翻 TUI 独立性或命令 Registry。

---

## 16. 编码停止条件

编码代理遇到以下情况必须停止相关范围并报告：

- 实际基线不是 `a605f9409cecccd4f7218f4c69b5362c76ab1b14`；
- `AGENTS.md` 或未修改条款与本任务书发生新的实质冲突；
- 必须修改 Core Provider 请求、事件、错误或 ProviderPort 才能继续；
- 必须引入多轮 Conversation、Run、Turn、Session 或 Agent Loop；
- 必须实现 Tool、Permission、Context、Skill、MCP、附件或 Diff UI；
- 项目配置安全边界无法在不读取秘密的情况下保证；
- `/model` 无法做到失败时配置与运行状态均不改变；
- Textual 类型必须进入 Application 或 Core；
- TOMLKit 类型必须越过 Integration；
- 需要第二个 Registry 或第二套配置模型；
- 需要加载项目 `.env`；
- 需要直接依赖 FirstCoder/MewCode；
- 需要整文件复制 FirstCoder；
- 实际文件范围明显超出本任务书；
- 产生无法确认的持久化副作用；
- 两项冻结决策发生冲突。

以下情况不属于停止条件，应自行修复：

- 普通编译错误；
- 测试失败；
- Textual 局部 API 适配；
- CSS 细节；
- 私有函数拆分；
- fixture 组织；
- 不影响公共边界的文件内重构。
