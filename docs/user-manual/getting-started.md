# 快速上手

## 安装

UthCode 需要 Python 3.12。当前从源码安装：

```powershell
conda create -n re-uthcode python=3.12 -y
conda activate re-uthcode
python -m pip install -e .
uthcode --help
```

## 首次配置

第一次运行 `uthcode` 时，程序会创建包含三个空 Provider/Model 槽位的 `~/.uthcode/config.toml` 并停止。填写一组完整槽位并设置 `default_model` 后重新运行。完整字段见[配置说明](configuration.md)。

不连接网络的最小配置：

```toml
default_model = "local/echo"

[providers.local]
kind = "fake"

[models."local/echo"]
provider = "local"
remote_id = "echo"
display_name = "Offline Echo"
```

## 开始使用

在需要操作的项目目录启动交互界面：

```powershell
uthcode
```

也可以指定工作目录或执行一次性任务：

```powershell
uthcode --cwd C:\work\my-project
uthcode exec --cwd C:\work\my-project "解释这个项目的目录结构"
```

交互界面中输入需求并按 `Enter` 发送；`Shift+Enter` 或 `Ctrl+J` 插入换行，`Ctrl+C` 退出。可用命令见[命令参考](commands.md)。

真实普通请求或显式 `/new`、`/resume` 时才会打开持久 Session；TUI 启动、帮助、状态和 Session Picker 不创建空 Session。terminal Turn 的已提交 Transcript、Timeline、AGENTS 激活元数据和大结果 ref 可在进程结束后通过 `/resume` 由新的 Run/Turn 继续使用。若 Transcript 已落盘而 Instruction State metadata 同步失败，状态 diagnostics 会显示 partial，不会把已提交消息重复送入下一轮；暂停中的 Turn、Permission/AskUser waiter 和 Runtime checkpoint 不会跨进程恢复。每个 Session 可以保存其当前模型；恢复它会采用该模型，但不会把旧选择倒写为新 Session 的默认模型。未显式配置 `context_window` 时，输入预算从 `256_000` default 开始，并可被 Provider 的可靠上限收紧；`/status` 显示实际来源。

## Windows Desktop

仓库内的 `desktop/` 提供 Windows 11 x64 Desktop shell，通过 Python Runtime JSONL Bridge 复用当前 Application、Session、Run、Turn、Interaction 和 AgentEvent。它与 TUI 共用用户级 `~/.uthcode/config.toml`，不会创建另一套模型、权限或会话事实。

Desktop 的侧栏从当前项目的 Session catalog 打开或新建对话。Session 切换和项目切换不会取消已在另一 Session 中运行的 Turn：该 Turn 会在后台继续，侧栏显示其 running/waiting/completed/failed/cancelled 状态；再次打开该 Session 会恢复其已提交 replay 和当前安全运行时投影。关闭 Desktop 会取消仍在运行的 Turn；跨进程只恢复已提交的 Session 内容，不恢复活动 Turn 或等待中的交互。

打开长对话时先显示最近 30 个完整交互单元；向上滚动接近顶部时再加载更早历史。工具调用与结果不会拆到两页，加载失败可以在聊天页局部重试，已有内容不清空。首次打开的会话可能显示准备中：历史可以先查看，普通发送需等准备完成；这不会缩减模型上下文，也不会自动在后台加载全部旧页。

Composer 顶部显示当前 Todo，底部可选择模型与权限并查看 Context ring。`/compact` 执行期间普通输入会锁定，Runtime panel 显示 Context 与 Compact 的实时安全状态；这些界面信息来自 Application 投影，而不是 Desktop 自行计算的会话状态。

宽屏 Desktop 的 Sidebar 与 Runtime panel 分隔条同时支持 Pointer 拖拽和键盘调整，并以稳定边界写回宽度 preference；拖动预览、窗口变化和缩放只做 viewport clamp，窄屏会关闭分隔条并使用 Runtime overlay。Focus Mode 是临时的 Renderer 展示状态：它隐藏 Sidebar/Runtime，退出时恢复进入前的 `panelMode` 与宽度，不写入 preference。Session ID 和 Markdown fenced code 的复制都经由 `copyText`，代码复制保留解析前的原文；用户滚离底部时 streaming 不抢回 scroll position，并显示 new-message 入口，点击后才回到底部并恢复 follow-tail。

Runtime panel 将两种口径分开显示：Current Context 是 Application 的 `exact` / `estimate` / `unavailable` measurement projection，Last Provider Request Usage 则只表示最近一次 Provider request 的 input/output/total 与明确可用的 cache read/write 字段；后者不会覆盖前者，也不会用默认零值冒充测量。

在已激活 `re-uthcode` 环境的 Windows 机器上从源码启动：

```powershell
conda activate re-uthcode
cd desktop
npm ci
npm run start
```

构建 Windows 安装包：

```powershell
npm run make -- --platform=win32 --arch=x64
```

安装包输出在 `desktop/out/make/squirrel.windows/x64/UthCode Setup.exe`。当前构建未签名，仅用于 development/release-candidate 验收；首次配置仍按上面的用户级配置说明完成。

> UthCode 的 `Bash` 工具不是 OS Sandbox，命令以当前操作系统用户权限执行。
