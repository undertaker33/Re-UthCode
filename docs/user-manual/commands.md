# 命令参考

## 启动命令

```powershell
uthcode [--cwd PATH] [--model MODEL_REF]
uthcode exec [--cwd PATH] [--model MODEL_REF] [PROMPT]
```

`uthcode` 启动交互界面。`uthcode exec` 执行一次任务；未提供 `PROMPT` 时从标准输入读取。`exec` 的最终回答写入 stdout，进度和错误写入 stderr。

## TUI 命令

| 命令 | 作用 |
| --- | --- |
| `/help` | 显示命令帮助 |
| `/clear` | 清空当前视口，不清除对话上下文 |
| `/model` | 打开模型选择器 |
| `/model <model-ref>` | 切换后续请求使用的模型 |
| `/permission` | 打开权限模式选择器 |
| `/permission <default\|auto\|full_access>` | 切换当前运行的权限模式 |
| `/plan` | 进入 Plan Mode |
| `/do` | 返回默认执行模式 |
| `/compact` | 通过 Application 的同一 Compact orchestrator 执行手动压缩；低 pressure 也可执行，无候选时返回成功 no-op，不创建垃圾 Timeline record |
| `/new` | 创建新的空 Session，并切换当前 Run |
| `/resume [session-id]` | 从当前项目的 Session Picker 或指定 ID 恢复已提交 Transcript、Timeline、Tool Result ref 和 Instruction State，并从新的 Run/Turn 开始；不恢复 active Runtime continuation |
| `/status` | 显示当前模型、Provider、配置来源、分维 configured/provider/default/effective limits 与 provenance、Pressure/Preflight、Auto/Hard Gate、Timeline checkpoint、Compact outcome、History persistence outcome 和 cache availability |
| `/quit` | 退出 UthCode |

常用别名：`/h`、`/?`、`/models`、`/m`、`/build`、`/s`、`/q`、`/exit`。

上表就是当前 Registry 的全部命令；未列出的 Slash 名称返回“未知命令”。`/compact` 不接受额外参数（例如 `/compact -- focus` 是用法错误）。`/new`、`/resume`、`/compact` 和 `/status` 均已接入正式 Application/Session 路径；Compact 的取消、解析失败、无安全 epoch 和一次 overflow retry 都会以受控 outcome 返回。

## `exec` 退出码

| 退出码 | 含义 |
| --- | --- |
| `0` | 成功 |
| `1` | Provider、生成或非交互暂停失败 |
| `2` | 参数或配置错误 |
| `130` | 用户取消 |
