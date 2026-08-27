# UthCode

## 项目定位

UthCode 是一个面向本地项目的 AI 编程助手。它既可以在终端中持续对话，也可以通过 `uthcode exec` 完成一次性任务。

## 核心能力

- 阅读、搜索、创建和修改工作目录内的文件。
- 通过 `Bash` 执行命令，并对工具操作进行权限判断和必要的用户确认。
- 支持 Anthropic、OpenAI Responses 和 OpenAI-compatible 模型服务。
- Context 输入预算默认使用 `256_000` Operating Window，按 configured/provider 限制收紧，并通过统一 Application diagnostics 暴露来源、Gate、缓存可用性与失败/暂停投影。
- 在同一 `AgentRun` 内保留多轮对话，支持暂停、恢复、取消和运行中补充指令；terminal Turn 提交到 Session History 后，可由新的 Run/Turn 通过 `/resume` 继续，未提交的 Runtime checkpoint 不跨进程恢复。
- 提供 Plan Mode、计划审阅和任务状态跟踪。
- 同时提供交互式 TUI 与适合脚本调用的 `exec` 模式。

## 快速开始

需要 Python 3.12。当前从源码安装：

```powershell
conda create -n re-uthcode python=3.12 -y
conda activate re-uthcode
python -m pip install -e .
uthcode
```

首次运行会创建包含三个空 Provider/Model 槽位的 `~/.uthcode/config.toml` 并停止。填写一组完整配置后，将 `default_model` 指向模型逻辑 ID，再次运行 `uthcode` 即可；也可以填写 Fake Provider 离线体验。

> `Bash` 使用当前操作系统用户权限执行，不是 OS Sandbox。请先在受版本控制的项目中使用，并留意权限确认内容。

## 文档导航

- [文档中心](docs/README.md)
- [快速上手](docs/user-manual/getting-started.md)
- [配置说明](docs/user-manual/configuration.md)
- [命令参考](docs/user-manual/commands.md)
- [可用 Tool](docs/Tools.md)
- [核心设计](docs/core-design/README.md)

## 开发与共享入口

- 开发环境使用仓库约定的 Conda 环境：`conda activate re-uthcode`。
- 运行测试：`python -m pytest -q`。
- 需要与项目成员共享模型选择或权限规则时，可提交项目内的 `.uthcode/config.toml` 与 `.uthcode/permissions.toml`；Provider 和 `api_key` 只保存在用户级配置，不要提交 API Key。
- 了解当前实现边界可查看[核心设计索引](docs/core-design/README.md)。
