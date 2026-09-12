# 命令参考

## 启动命令

```powershell
uthcode [--cwd PATH] [--model MODEL_REF]
uthcode exec [--cwd PATH] [--model MODEL_REF] [PROMPT]
```

`uthcode` 启动交互界面。`uthcode exec` 执行一次任务；未提供 `PROMPT` 时从标准输入读取。`exec` 的最终回答写入 stdout，进度和错误写入 stderr。

Windows Desktop 的 Composer 和 Settings 使用同一个 Application/Command/Configuration 公共出口；Slash 命令的名称、参数、权限和 Session 语义与本页 TUI 参考一致。Desktop 为每个已打开的持久 Session 保留独立运行时投影：切换会话或项目不会取消另一个 Session 的 active Turn，后台状态显示在侧栏；跨进程仍只恢复已提交的 Session 内容。

`Bash` 是唯一的进程启动 Tool。`yield_time_ms` 只决定当前调用等待多久，`timeout_seconds` 才是可选的进程总寿命限制；没有显式 timeout 时，后台服务不会因 ToolCall 返回而自动终止。返回的 `process_id` 只在所属 Application/Session 中有效，可用 `Process` 的 `list`、`read`、`write`、`stop` 和 `resize` 操作继续观察或控制。`read` 使用有界增量游标，游标过期时按返回的最早位置续读；stdin/EOF 是独立的执行输入授权。Desktop 在 Turn 完成后仍接收该 Session 的有界、脱敏进程日志，Session 关闭时才统一回收其进程。

## TUI 命令

| 命令 | 作用 |
| --- | --- |
| `/help` | 显示命令帮助 |
| `/clear` | 清空当前视口，不清除对话上下文 |
| `/model` | 打开模型选择器 |
| `/model <model-ref>` | 切换后续请求使用的模型 |
| `/permission` | 打开权限模式选择器 |
| `/permission <default\|auto\|full_access>` | 切换当前 Run 的权限模式；`default`/`auto` 同时写回用户默认权限，`full_access` 仅当前 Run 有效 |
| `/plan` | 进入 Plan Mode |
| `/do` | 返回默认执行模式 |
| `/compact` | 通过 Application 的同一 Compact orchestrator 执行手动压缩；低 pressure 也可执行，无候选时返回成功 no-op，不创建垃圾 Timeline record |
| `/new` | 创建新的空 Session，并切换当前 Run |
| `/resume [session-id]` | 从当前项目的 Session Picker 或指定 ID 恢复已提交 Transcript、Timeline、Tool Result ref 和 Instruction State，并从新的 Run/Turn 开始；不恢复 active Runtime continuation |
| `/status` | 显示当前模型、Provider、配置来源、分维 configured/provider/default/effective limits 与 provenance、Pressure/Preflight、Auto/Hard Gate、Timeline checkpoint、Compact outcome、History persistence outcome 和 cache availability；Context measurement 会明确显示 `exact`、`estimate` 或 `unavailable` |
| `/quit` | 退出 UthCode |

常用别名：`/h`、`/?`、`/models`、`/m`、`/build`、`/c`、`/s`、`/q`、`/exit`。

`/permission default` 和 `/permission auto` 会先写回用户级 `config.toml` 的 `default_permission_mode`，供后续新建 Run 使用，再更新当前 Run；不会改变其他已经创建的 Run。`/permission full_access` 不写配置，也不改变新 Run 的默认权限。

上表就是当前 Registry 的全部命令；未列出的 Slash 名称返回“未知命令”。`/compact` 不接受额外参数（例如 `/compact -- focus` 是用法错误）。`/new`、`/resume`、`/compact` 和 `/status` 均已接入正式 Application/Session 路径；Compact 的取消、解析失败、无安全 epoch 和一次 overflow retry 都会以受控 outcome 返回。

在 Desktop 中，Composer 的 `/model` 候选可显示模型的 `display_name`，但提交的仍是配置中的 Model Profile ID。`/plan`、`/do`、`/compact`、`/status` 与 typed interaction 都走 Bridge 的同一 Command/Turn 边界；运行中的 Turn 的 Todo 显示在 Composer 上方，Context ring 和 Runtime panel 只显示 Application 的安全状态投影。

Context 的 `exact` 只表示当前 Provider 提供了可靠的 preflight count；Provider count 不可用时会显示标注来源的 local estimate，首次还没有可编译请求时显示 `unavailable`。Provider 未提供 cache read/write 字段时也保持 `not_available`，不会用默认零值冒充缓存命中。

Desktop 的手动压缩在所属会话后台执行，可以切到其他会话继续工作；切换不会取消它。压缩中的会话暂时不能发送新请求或重复压缩，可使用取消控件停止。Runtime 面板会显示安全终止原因及是否已有有效提交：取消或失败不代表已完成的压缩被回滚。取消或重启后可再次发起压缩；重启不会自动重试旧请求。遇到真实文件损坏或持续读写故障时，仍需先处理显示的存储错误。

压缩是否有效按后续普通模型请求的上下文用量是否下降判断，不按摘要文字长短判断。未减少用量的候选不会替换现有上下文，会显示 `no_reduction`；没有可压缩历史的成功 no-op 也不表示上下文已经变小。压缩保留原始会话历史，聊天历史分页与模型上下文压缩互相独立。

## `exec` 退出码

| 退出码 | 含义 |
| --- | --- |
| `0` | 成功 |
| `1` | Provider、生成或非交互暂停失败 |
| `2` | 参数或配置错误 |
| `130` | 用户取消 |
