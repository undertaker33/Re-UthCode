# UthCode

UthCode 是一个面向本地项目的 AI 编程助手。它可以在终端中持续对话、阅读和修改文件、搜索代码，并按需执行命令。

当前版本提供两种使用方式：

- **交互式终端界面（TUI）**：适合围绕同一个项目连续提问和操作。
- **非交互命令（`uthcode exec`）**：适合脚本、自动化和一次性任务。

支持 Anthropic、OpenAI Responses 和 OpenAI-compatible 三类模型服务，也提供仅用于离线体验和测试的 Fake Provider。

## 功能概览

- 在同一次使用过程中连续对话，后续问题会保留前文。
- 自动使用文件读取、写入、编辑、文件匹配、内容搜索和 Bash 命令工具。
- 展示思考进度、工具运行状态和最终回答，不展示工具返回的原始正文。
- 支持随时取消当前请求。
- 支持在多个已配置模型之间切换；切换只影响下一次请求。
- API Key 只从环境变量读取，不写入配置文件。
- 项目配置与用户配置分层加载，项目配置不能重定向密钥来源或提升访问范围。

## 运行要求

- Python 3.12
- Windows、macOS 或 Linux
- 至少配置一个可用模型；也可以先使用 Fake Provider 离线体验

## 安装

克隆仓库后，在项目目录创建 Python 3.12 环境并安装：

```powershell
conda create -n re-uthcode python=3.12 -y
conda activate re-uthcode
python -m pip install -e .
```

确认命令可用：

```powershell
uthcode --help
```

## 第一次配置

UthCode 的用户配置文件位于：

```text
~/.uthcode/config.toml
```

第一次运行时，UthCode 会创建一份带注释的配置模板并停止。编辑模板、配置 Provider 和模型后，再次运行即可。

### 离线体验

下面的配置不需要 API Key，也不会访问网络：

```toml
model = "local/echo"

[providers.local]
kind = "fake"

[models."local/echo"]
provider = "local"
model = "echo"
label = "Offline Echo"
```

### 配置真实模型

API Key 必须放在环境变量中，配置文件只记录环境变量名。

OpenAI-compatible 示例：

```toml
model = "my-provider/chat"

[providers.my-provider]
kind = "openai_compat"
base_url = "https://your-provider.example/v1"
api_key_env = "MY_PROVIDER_API_KEY"

[models."my-provider/chat"]
provider = "my-provider"
model = "your-model-id"
label = "My Chat Model"
max_output_tokens = 4096
```

在当前 PowerShell 终端设置密钥：

```powershell
$env:MY_PROVIDER_API_KEY = "your-api-key"
```

其他 Provider 的配置结构相同：

| `kind` | 用途 | 必填项 |
| --- | --- | --- |
| `anthropic` | Anthropic Messages API | `api_key_env` |
| `openai_responses` | OpenAI Responses API | `api_key_env` |
| `openai_compat` | OpenAI-compatible 服务 | `api_key_env`、`base_url` |
| `fake` | 离线体验和测试 | 无 |

> 不要把真实 API Key 写入 `config.toml`、命令参数或项目文件。

## 启动交互界面

在需要操作的项目目录运行：

```powershell
uthcode
```

也可以显式指定工作目录或模型：

```powershell
uthcode --cwd C:\work\my-project
uthcode --model my-provider/chat
```

### 基本操作

- 输入问题后按 `Enter` 发送。
- 按 `Shift+Enter` 插入换行。
- 连续按两次 `Esc` 取消当前请求。
- 同一次 TUI 使用一个连续对话；下一条普通输入会带上前文。
- `/clear` 只清空屏幕内容，不会清除对话历史。
- 请求运行期间不能发送第二条普通输入，也不能切换模型。

### 当前可用命令

| 命令 | 作用 |
| --- | --- |
| `/help` | 查看命令帮助 |
| `/clear` | 清空当前界面显示 |
| `/model` | 打开模型选择器 |
| `/model <model-ref>` | 切换下一次请求使用的模型 |
| `/status` | 查看当前模型、Provider 和配置来源 |
| `/quit` | 退出界面 |

别名包括 `/h`、`/?`、`/models`、`/m`、`/s`、`/q` 和 `/exit`。

界面中还会列出部分规划中的命令；这些命令会明确显示“功能未实现”，不会静默执行。

## 执行一次性任务

不启动交互界面，直接执行一条任务：

```powershell
uthcode exec "解释这个项目的目录结构"
uthcode exec --cwd C:\work\my-project "检查测试失败的原因"
uthcode exec --model my-provider/chat "总结当前目录"
```

也可以通过标准输入传递内容：

```powershell
"列出最值得优先处理的问题" | uthcode exec
```

`exec` 的输出规则适合脚本使用：

- 最终回答只写入标准输出（stdout）。
- reasoning、进度、工具状态、失败和取消信息写入标准错误（stderr）。
- 以 `/` 开头的内容仍然作为普通提示词，不会被当作 TUI 命令。

退出码：

| 退出码 | 含义 |
| --- | --- |
| `0` | 成功 |
| `1` | Provider 或生成失败 |
| `2` | 参数或配置错误 |
| `130` | 用户取消 |

## 配置作用范围

UthCode 会合并用户配置和项目配置：

- 用户配置：`~/.uthcode/config.toml`
- 项目配置：`<项目目录>/.uthcode/config.toml`

在 Git 仓库中，项目配置会从仓库根目录向当前目录逐层发现；在非 Git 目录中，只读取当前目录的项目配置。

项目配置可以选择用户已信任的模型并调整非敏感模型参数，但不能：

- 定义或替换 Provider；
- 修改服务端点；
- 修改 API Key 的环境变量来源；
- 静默提升为更宽泛的访问模式。

## 内置工具

当前默认工具包括：

| 工具 | 用途 |
| --- | --- |
| `ReadFile` | 读取项目文件 |
| `WriteFile` | 写入文件 |
| `EditFile` | 精确编辑文件 |
| `Glob` | 按文件名模式查找 |
| `Grep` | 搜索文件内容 |
| `Bash` | 在项目工作目录执行命令 |

文件与搜索工具会限制在启动时确定的工作目录内，并检查路径穿越和符号链接边界。

## 安全说明

请在运行前了解以下边界：

- `Bash` 使用当前操作系统用户的权限执行，是**未沙箱化的进程执行**。
- 当前版本没有 OS Sandbox，也没有危险命令审批流程。
- 工具仍受操作系统权限、工作目录限制、参数校验和 Provider 权限约束。
- 工具活动只显示经过脱敏和截断的摘要，不显示写入正文、工具返回的原始内容、API Key、token、配置秘密或未知参数。
- 当前对话只保存在内存中；退出后不会提供会话恢复、Memory 或持久化历史。

建议先在受版本控制的项目中使用，并在执行高影响任务前确认工作区状态。

## 常见问题

### 第一次运行后为什么直接退出？

这是正常行为。UthCode 已创建 `~/.uthcode/config.toml` 模板。完成配置后重新运行即可。

### 为什么提示缺少 API Key？

确认 `api_key_env` 指向的环境变量已在启动 UthCode 的同一个终端中设置。配置文件中应保存环境变量名，而不是真实密钥。

### `/clear` 会开始新对话吗？

不会。它只清空界面显示，后续输入仍会保留之前的对话。

### 如何彻底开始一段新对话？

当前版本没有持久 Session 或 `/new` 功能。退出并重新启动 TUI 即可创建新的内存对话。

### 为什么不能在请求运行时切换模型？

每次请求开始时都会固定 Provider 和模型，避免运行过程中发生不一致。当前请求结束后即可切换，下一次请求会使用新模型。

## 当前状态

UthCode 目前处于早期版本，核心对话、工具调用、CLI 和 TUI 已可离线测试。Permission、OS Sandbox、持久 Session、Memory、Diff Viewer、MCP、Skill 和 Multi-Agent 尚未提供。

## License

MIT
