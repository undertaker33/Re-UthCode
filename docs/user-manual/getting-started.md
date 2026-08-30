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

真实普通请求或显式 `/new`、`/resume` 时才会打开持久 Session；TUI 启动、帮助、状态和 Session Picker 不创建空 Session。terminal Turn 的已提交 Transcript、Timeline、AGENTS 激活元数据和大结果 ref 可在进程结束后通过 `/resume` 由新的 Run/Turn 继续使用。若 Transcript 已落盘而 Instruction State metadata 同步失败，状态 diagnostics 会显示 partial，不会把已提交消息重复送入下一轮；暂停中的 Turn、Permission/AskUser waiter 和 Runtime checkpoint 不会跨进程恢复。未显式配置 `context_window` 时，输入预算从 `256_000` default 开始，并可被 Provider 的可靠上限收紧；`/status` 显示实际来源。

## Windows Desktop

仓库内的 `desktop/` 提供 Windows 11 x64 Desktop shell，通过 Python Runtime JSONL Bridge 复用当前 Application、Session、Run、Turn、Interaction 和 AgentEvent。它与 TUI 共用用户级 `~/.uthcode/config.toml`，不会创建另一套模型、权限或会话事实。

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
