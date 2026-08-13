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

第一次运行 `uthcode` 时，程序会创建 `~/.uthcode/config.toml` 并停止。编辑该文件后重新运行。完整字段见[配置说明](configuration.md)。

不连接网络的最小配置：

```toml
model = "local/echo"

[providers.local]
kind = "fake"

[models."local/echo"]
provider = "local"
model = "echo"
label = "Offline Echo"
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

> UthCode 的 `Bash` 工具不是 OS Sandbox，命令以当前操作系统用户权限执行。
