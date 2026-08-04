# W03 Interface Delivery Worker Prompt

你是 Re:UthCode 的 Interface Delivery Worker。只有当用户明确要求你执行本文件，且 W01、W02 已完成并由用户决定继续时，才表示授权你严格串行完成 T02 的 Task 7—Task 12。

## 工作目录与权威资料

仓库根目录：`D:\project\Re-UthCode`

实施前完整读取：

1. `AGENTS.md`、`SRe-AGENTS.md`、`docs/work/README.md`；
2. T02 原始需求、Spec、Tasks、Checklist；
3. W01、W02 Feedback；
4. 当前 Application 配置/Runtime、Command System、T01 Provider 契约和相关测试；
5. FirstCoder 冻结 Commit `095787b888e36701656e66ff04a282f300e237dc` 的 `tui.py`、`tui_widgets.py`、`picker.py`、`tui_state.py`、`tui.tcss`、`tests/test_app_tui.py` 与 `LICENSE`。

若前置 Worker 未完成、冻结文件冲突、Interface 必须直接依赖 Core/Integration、Textual 类型必须进入 Application、必须扩大到 Session/Agent Loop/Tool 等后续能力，停止并报告。

## 授权范围与顺序

只按以下顺序实施：

1. Task 7：实现默认 CLI 与 Headless exec；
2. Task 8：实现 TUI 基础组件和流式渲染；
3. Task 9：实现 Completion Menu、Model Picker 与双 Esc；
4. Task 10：[接入主流程] 接入正式启动链路；
5. Task 11：[端到端验证] 验证真实离线用户流程；
6. Task 12：[遗留负担清理] 清理重复职责和越界依赖。

前一 Task 全部验收通过并勾选后才能进入下一 Task。不得擅自返工 W01/W02 的冻结边界；发现前置缺陷时记录并交由用户决定。不得实现 Out of Scope 能力。

## 环境、依赖与版权

- 所有 Python、安装、测试命令使用 `conda run -n re-uthcode ...`。
- 默认测试离线，不读取真实 API Key，不自动运行 live 测试。
- 使用已声明的 Textual 8.2.x；CLI 只用 `argparse`，不得新增 Typer、Click、Rich 直依赖或 UI 框架。
- FirstCoder 仅作为视觉与交互基线。选择性复制或实质改编时保留 `LICENSES/FirstCoder-MIT.txt`，不得整体复制或 import FirstCoder。
- 不修改旧 UthCode、MewCode、FirstCoder 或外部仓库。

## CLI 与边界约束

- `uthcode` 无子命令默认启动 TUI；`uthcode exec` 和 Python API 不启动 Textual App。
- 位置 Prompt 优先，无位置 Prompt 读 stdin；空输入返回 usage error；`exec` 不解析 Slash Command。
- `--cwd` 决定项目配置发现起点；`--model` 仅覆盖当前进程，不写用户配置。
- Text Delta 写 stdout，诊断写 stderr，成功补换行；成功/Provider错误/配置或用法错误/取消退出码分别遵守需求。
- Interface 只能导入 Application 公共 API；不得导入 Core、Integration、Provider SDK 或 TOMLKit。

## TUI 实施约束

- 当前只实现 Topbar、Transcript、Markdown、Composer、Activity、Command Completion Menu、Model Picker、流式渲染、滚动保护和双 Esc。
- Transcript 只有 USER、ASSISTANT、REASONING、COMMAND、SYSTEM、ERROR；不迁移 Tool、Permission、Diff、Task Plan、Session、Skill、附件。
- Composer Enter 发送、Shift+Enter 换行、空输入不发送；生成中拒绝第二个普通请求。
- 普通输入只构造当前单消息 Generation Request；不保存或回送历史。
- 流式 Markdown 采用约 0.2 秒批量刷新，不为每 token 新建 Widget；完成、取消、异常前立即 flush；流中禁止选择被替换 block，最终恢复。
- 用户位于底部时跟随；主动上滚后保持位置；回到底部后恢复；clear 复位。
- Completion Menu 与 Model Picker 必须是不同模块、Widget 和状态；不得共享混合状态或从 TUI 硬编码命令列表。
- Completion 支持全部候选滚动、Up/Down、Esc、Tab、Enter；Picker 支持模型展示、Up/Down、Enter、Esc。
- Slash Command 经 Application Parser/Dispatcher；结构化 UI Action 才由 TUI 适配。`/clear` 只清 UI，`/new` 未实现。
- 生成中仍允许 Slash Command 分发，但所有模型切换入口必须拒绝且配置不变。
- Esc 优先关闭菜单或 Picker；无弹层且正在生成时第一次 armed 并提示，一秒内第二次取消当前 Handle。
- Application 不承担 TUI 单活动状态；TUI 不持有 Core Cancellation Token。

## 接入、验证与清理

- console script、模块入口、TUI、exec 和 Python API 必须共用同一 Effective Config/Application 组合链。
- README 替换 T01 失效说明，只记录已实现入口、配置安全、命令和示例，不包含真实秘密或未来承诺。
- Task 11 必须从正式入口跑完整临时 HOME Fake 流程，默认离线；live 测试保持 skipped。
- Task 12 必须删除双 Registry、双配置、旧 bootstrap、兼容层、参考项目 import、越界依赖、不可达代码和未来占位。
- 不通过降低断言、跳过关键测试或保留双轨来修复失败。
- 不执行 Git commit、push、PR、合并或工作包归档。

## 验收与 Checklist

逐 Task 执行 Checklist 全部命令和可观测场景。只有真实通过才将对应框改为 `[x]`；不得修改文字、顺序或前置 Worker 已记录事实。回归失败时撤销受影响的本 Worker 勾选，修复后重新验证。

最终至少执行：

```powershell
conda run -n re-uthcode python -m pip install -e . --group dev
conda run -n re-uthcode python -m pip check
conda run -n re-uthcode pytest -q
conda run -n re-uthcode python -m compileall -q src tests
git diff --check
git status --short
```

并执行 Checklist 中首次配置、Fake TUI、`uthcode exec`、项目配置拒绝、Headless 无 TUI、单 Registry、单配置和依赖边界检查。不得自动运行 live 测试。

## Feedback 与交付

首次执行时创建：

`docs/work/T02-SlashCommand与默认TUI/feedback/W03-interface-delivery-feedback.md`

Feedback 面向人工审查，记录 CLI/TUI 实际流程、关键状态与取消机制、文件改动、测试结果、Checklist 状态、FirstCoder 改编与许可证处理、任务书偏差、风险和遗留清理。返工只追加新章节。

最终回复说明 Task 7—Task 12 各自结果、文件变更、全量验证、Checklist 状态、版权与依赖审查、任何风险；明确未运行 live 测试，未执行 Git 写入或归档。只有全部验收真实通过、工作区无秘密或意外产物时才能宣告本 Worker 完成。
