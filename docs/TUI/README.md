# TUI 当前实现

本文记录 UthCode 交互式终端界面的长期实现上下文，供后续维护和扩展时查阅。它不是需求文件或任务工作包，不改变冻结的历史工作包。

## 交互目标

TUI 使用终端主缓冲区和原生 scrollback。已经完成的用户消息、Agent 消息与工具终态只追加一次；生成期间可以继续用 Windows Terminal 自带的滚动、选择和复制功能查看历史。

实现参考成熟终端 Agent 的通用交互：

- Pi 的高度感知多行编辑器、输入焦点与候选列表；
- Codex 的 inline 模式和主缓冲区 scrollback；
- Claude Code 的启动欢迎区与底部状态；
- FirstCoder 的角色抬头、左侧竖线和低噪声工具记录。

以下约束不可破坏：

- 不进入 alternate screen，不捕获鼠标，不实现应用内滚动条；
- 不发送清除 scrollback 的 `CSI 3J`；
- 全局背景沿用用户的终端配色，只给消息和代码块设置局部背景；
- 已进入 scrollback 的内容不可回写、删除或重排；
- TUI 只调用 Application 公共接口并消费公开事件，不直接依赖 Agent Core、Provider 或工具内部类型。

## 模块结构

```text
src/uthcode/interfaces/tui/
├── app.py         # prompt_toolkit Application、按键、命令和 Turn 生命周期
├── completion.py  # Slash Command 候选状态
├── interaction.py  # 暂停菜单、问题导航、答案草稿与复核
├── picker.py      # 模型候选状态
├── rendering.py   # Application 事件投影与 Markdown 流式边界
├── state.py       # 双 Esc 状态与 Unicode grapheme 计算
├── terminal.py    # Rich 永久输出、欢迎区、消息和工具样式
└── windows_input.py # Windows 原生 Unicode 与 Shift+Enter 映射
```

依赖方向保持为 `interfaces → application → core`。TUI 通过 `UthCodeApplication`、`AgentRun`、`TurnHandle` 和公开 `AgentEvent` 工作，不维护第二份会话事实。

## 输入数据流

```text
Windows Console Unicode / VT 按键 / bracketed paste
                          ↓
              prompt_toolkit Buffer
                 ↓              ↓
        Slash / Model 候选     普通消息
                 ↓              ↓
              UthCodeApplication / AgentRun
                          ↓
                    公开 AgentEvent
                          ↓
         AgentEventRenderer + MarkdownStream
                 ↓                    ↓
     run_in_terminal 永久追加       临时预览
```

`prompt_toolkit.Application` 固定使用：

```python
Application(
    full_screen=False,
    mouse_support=False,
    erase_when_done=False,
)
```

Windows 使用 prompt_toolkit 的原生 `KEY_EVENT_RECORD` Unicode 输入路径，并对 `Shift+Enter` 做一处修饰键映射。这样既不把 IME 提交拆成单字节，也不要求 Windows Terminal 支持 Kitty 键盘协议；模型或工具进程修改控制台代码页后，输入仍以 Unicode 进入 `Buffer`。粘贴由 prompt_toolkit 处理并原样保留多行文本。

Composer 的提示符和 `BufferControl` 使用两个并排的持久 Window。禁止在 `DynamicContainer` 回调中重新创建焦点 Window：屏幕光标坐标以 Window 实例为键，实例变化会使 Renderer 回退到 `(0, 0)`，从而让中文 IME 预编辑锚到最左侧。提示符保留左侧内边距，硬件光标始终属于同一个 Buffer Window。

## 永久输出与临时布局

用户消息、完整 Markdown 块、工具终态和系统消息通过 `run_in_terminal` 暂停临时界面后增量写入主缓冲区。候选、Composer、尚未形成完整块的 Agent 尾部预览和状态栏由 prompt_toolkit 差分刷新，不写入 scrollback。

流式投影只属于当前 Turn。开始下一次请求时会统一清除上一 Turn 的 `MarkdownStream`、消息类型和显示边界状态；已提交内容已经属于终端 scrollback，不需要也不得在内存中保留一份界面副本。

`run_in_terminal` 会擦除临时布局、写入永久内容并重绘布局。所有正在运行的永久提交必须使用 DECSET 2026 Synchronized Output 包住整个过程，使终端只展示完成后的原子帧，禁止暴露中间空屏。同步标记、永久正文、prompt_toolkit 的擦除与重绘必须全部通过 `Application.output` 的同一个 `Output` 实例；禁止另持 `sys.stdout` 或测试专用文本流形成双输出通道。同一个 `RenderBatch` 中的用户消息、Agent 块和工具终态先在内存中合并，再调用一次 `run_in_terminal`；不得按块反复擦除和重绘。每次生成永久 Rich 内容前按当前 `Application.output` 宽度更新渲染宽度，窗口缩放后不得继续沿用启动宽度。

每个流式块只使用一个内部投影对象保存 Markdown 缓冲、消息类型、是否已经显示角色抬头以及是否仍处于连续竖线区间。禁止用多份以 block id 为键的字典或集合并行表达同一状态。

根布局最上方使用弹性空白，将分隔线、Composer 和状态栏固定在终端底部。Composer 默认三行，按实际换行和终端单元格宽度自适应增加，最多十行；使用精确高度，禁止由 HSplit 把空余高度分配给输入框。小窗口或输入变长时，预览与候选先缩短；模型和命令候选围绕当前选中项窗口化。窗口缩放只重排临时区域，已经提交的历史不重写。

同一条最终回复虽然按安全 Markdown 边界增量提交，但只输出一次角色抬头；后续块使用无空隙的连续绿色竖线，因此视觉上仍是一条消息。Reasoning、工具记录以及工具之后产生的新 Agent 消息仍是各自独立的记录。Fenced code block 的关闭围栏必须满足以下条件：

- 与开启围栏使用相同字符；
- 长度不短于开启围栏；
- 围栏之后只剩空白。

未闭合代码块或没有段落边界的长文本会留在临时预览。预览按终端单元格宽度换行并只保留最新可见行，不能固定显示开头；因此即使尚不能安全写入 scrollback，用户仍能持续看到最新 delta。

当 Agent 返回 Markdown-in-Markdown 代码块，并错误地让内外层使用同样长度的 fence 时，终端渲染器会把最外层 fence 扩展一位，再交给 Rich。这样内层代码块保持为外层代码示例的一部分，不会提前关闭或产生多余空代码块。

工具边界和运行终态会强制提交尾部。若最终权威响应与已经提交的流式内容不一致，追加“响应已修正”和完整权威结果，不回写历史。

## 消息与颜色

终端全局背景不变，局部层级固定如下：

| 内容 | 样式 |
| --- | --- |
| 欢迎区与强调色 | `#FEA62B` |
| 用户消息 | 左侧竖线、`you` 抬头、`#242F38` 背景 |
| Agent 消息 | 左侧竖线、`UthCode:` 抬头、终端原有背景 |
| 正文 | `#E0E0E0` |
| fenced code block | `#121212` 背景与语法高亮；未单独配色的 token 回退为 `#E0E0E0` |
| inline code | `#FEA62B` |
| 工具竖线 | `#9A9A9A` |
| 工具成功圆点与状态 | `#4EBF71` |
| 工具失败、拒绝或错误圆点与状态 | `#B93C5B` |

Markdown 的标题、列表、引用、表格、链接和代码由 Rich 渲染。工具开始只更新底部状态；结束时才写入一条带状态文字的永久记录，颜色不是唯一信息来源。

## 键位

| 按键 | 行为 |
| --- | --- |
| `Enter` | 提交消息，或执行当前可见候选 |
| `Shift+Enter` | 插入换行 |
| `Ctrl+J` | 无修改键协议时的换行后备 |
| 方向键 | 标准光标编辑；候选打开时上下移动选择 |
| `Home` / `End` | 移到当前行首或行尾 |
| `Backspace` | 按 Unicode grapheme 删除光标前一个字符；空输入无动作 |
| `Delete` | 删除光标后的字符 |
| `Tab` | 补全当前 Slash Command |
| `Esc` | 由最上层候选、模型选择或问答层优先消费；根页面普通输入无动作 |
| 连续两次 `Esc` | 对话根页面生成期间请求 cooperative pause；不是取消 |
| `Ctrl+C` | 退出 UthCode |

只有 `Ctrl+C` 和 `/quit` 会退出。输入解析异常会显示可恢复错误并恢复终端状态，不会被静默转换成退出。

Windows 直接读取带修饰键的原生 Unicode 控制台事件，从而在 Windows Terminal 1.24 等不支持 Kitty 键盘协议的版本中区分 `Enter` 和 `Shift+Enter`。其他支持 Kitty 协议的终端使用增强键盘事件；不支持时仍可使用 `Ctrl+J`。

## Slash Command 与模型选择

Slash Command 使用 Application 的正式 Completion 数据源。候选随草稿实时过滤，字符输入、Backspace 和左右编辑继续作用于同一份草稿。上下键只在当前可见窗口中移动，`Tab` 补全，`Enter` 执行，`Esc` 关闭。

`/model` 打开模型候选时保存原草稿；按 `Esc` 后关闭选择器并恢复原对话输入。命令定义、参数提示和模型目录都来自 Application，TUI 不维护副本。

## 暂停、恢复与问答

暂停只属于当前进程、当前内存 Run 的活动 Turn。对话根页面连续按两次 `Esc` 后，状态栏先显示 `pausing…`，到达安全边界后显示 `paused` 并打开临时动作层。动作层提供 `Resume` 或 `Cancel current turn`；网络/限流暂停提供 `Retry` 或 `Cancel current turn`。暂停期间仍保留原 `TurnHandle`，不会启动第二个 Turn，也不会产生第二个 `TurnStarted`。

模型调用 `AskUserQuestion` 时，TUI 打开临时问题面板。面板支持文本、单选、多选和 `Other`，可用方向键导航、返回上一题、查看答案汇总并在确认后一次性提交。提交只调用 Application 公共 `TurnHandle.resume(...)`，问题答案和 pending pause 不在 TUI 形成第二份权威状态；答案正文也不会写入工具活动或永久系统消息。

`Esc` 在模型选择、Slash 候选、暂停动作和问题临时层中先由当前层消费；关闭层会清空双 Esc arm，不能因为关闭 picker/modal 而意外暂停根页面。`Ctrl+C`、关闭 TUI、异常、进程退出或重启都只执行当前 Turn 的取消收口；任务、pending 问题和答案不会保存，下一次启动创建全新 Run，不提供跨进程恢复。

## 启动、`/clear` 与退出

启动先发送 `CSI 2J` 和 Home，只清当前视口，然后显示包含 UthCode Logo、当前模型、cwd 和主要快捷键的欢迎区。

`/clear` 使用相同的清视口语义并打印新视图分隔线：

- 不发送 `CSI 3J`，用户向上滚动仍能看到旧历史；
- 不替换 `AgentRun`，也不清除 Application 对话上下文。

欢迎面板必须在 prompt_toolkit Application 已运行后通过 `run_in_terminal` 提交，不能在 Renderer 建立自身屏幕坐标之前直接写入；否则后续永久输出可能回到欢迎面板所在行并覆盖 Logo。正常退出和异常恢复都会关闭增强键盘模式，并由 prompt_toolkit 恢复输入模式。

## 扩展边界

后续改动不得恢复全屏双轨界面、复制按钮、应用内滚动条或自建键盘字节解析器。新交互应进入 prompt_toolkit 的临时布局；永久历史只接受可追加的最终记录。

内部展示模型保持最小化：候选项只保存当前界面实际使用的值与显示文字；颜色名称按实际用途命名；焦点 Window 直接由布局持有，不增加只返回同一对象的包装方法或兼容入口。

以下事项不属于 TUI 内部扩展，必须单独设计：

- 修改 Application 公共事件；
- 修改 Agent Core、Provider 或工具协议；
- 增加持久 Session、Permission、Diff Viewer 或会话存储；
- 从界面读取 Provider SDK 类型或工具原始结果。

## 验证方法

自动验证：

```powershell
conda activate re-uthcode
python -m pytest tests/test_tui.py tests/test_architecture_boundaries.py -q
python -m pytest -q
python -m compileall -q src tests
python -m pip check
```

静态检查需要确认源码与依赖中不存在旧 TUI 双轨实现，不包含 alternate-screen、鼠标跟踪和 `CSI 3J`。

Windows Terminal 人工验收：

1. 启动后确认先清当前视口，再显示 Logo；外部滚动条可用。
2. 用中文输入法发送“你好”，确认界面文字和 Provider 收到的内容完全一致。
3. 连续按 Backspace，确认依次删除“好”“你”，空输入继续按不会退出。
4. 让模型或工具切换 UTF-8 代码页后继续输入中文，确认不崩溃。
5. 验证多行中文粘贴、`Shift+Enter` 与 `Ctrl+J` 换行。
6. 从 `/` 开始逐字输入、退格、左右编辑和补全 `/status`，确认界面不冻结。
7. 打开 `/model` 后按 `Esc`，确认关闭选择器并恢复原草稿。
8. 生成期间上翻、选择和复制旧文本，调整窗口大小，确认生成继续且历史不重写。
9. 检查用户和 Agent 角色样式、Rich Markdown、代码块背景及工具终态颜色。
10. 执行 `/clear` 后向上滚动，确认旧记录仍存在且对话上下文保留。
