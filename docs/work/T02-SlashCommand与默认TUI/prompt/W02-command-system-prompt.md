# W02 Command System Worker Prompt

你是 Re:UthCode 的 Command System Worker。只有当用户明确要求你执行本文件，且 W01 已完成并由用户决定继续时，才表示授权你严格串行完成 T02 的 Task 5—Task 6。

## 工作目录与权威资料

仓库根目录：`D:\project\Re-UthCode`

开始前完整读取 `AGENTS.md`、`SRe-AGENTS.md`、`docs/work/README.md`、T02 原始需求、Spec、Tasks、Checklist、W01 Feedback，以及当前 Application 配置和 Runtime 源码测试。若 W01 未完成、冻结文件冲突、Application Model Catalog/模型切换边界不存在或继续需要 Textual/未来 Skill Loader，停止并报告。

## 授权范围与顺序

只按顺序实施：

1. Task 5：实现 Command Registry 与 Parser；
2. Task 6：实现 Completion、Dispatcher 与内置命令。

Task 5 全部验收通过并勾选后才能进入 Task 6。不得实施 Task 1—Task 4 的返工，也不得实施 Task 7—Task 12、CLI、Widget、TUI 或未来命令业务。若前置缺陷影响本组，在 Feedback 记录并交由用户决定，不得越权修复其他 Worker 范围。

## 环境与参考

- 所有 Python 和测试命令使用 `conda run -n re-uthcode ...`，默认离线。
- 只读参考 `D:\project\MewCode\mewcode\commands` 的 Registry、Parser、Completion 与 handlers；只吸收思路，不复制其 UI Controller、Session、Agent、八项截断或运行时依赖。
- 不修改旧 UthCode、MewCode、FirstCoder 或外部仓库。
- 不增加依赖；命令系统应只使用标准库和 Application 自有模型。

## 实施约束

- 项目只有一个正式 Registry，公开稳定的注册、解析和列表接口。
- 注册必须拒绝 canonical/alias 的所有交叉冲突、重复 alias、非法或非小写定义，且失败不污染 Registry。
- Parser 必须区分普通文本、`/`、未知命令、原始调用名、canonical、alias、args、query、`--` 和 Usage 错误。
- 命令调用名解析大小写不敏感；定义名保持小写合法格式；args 使用 `shlex`；query 保持用户原始文本，不由 token 重新拼接。
- LOCAL、LOCAL_UI、PROMPT 必须由 Dispatcher 产生结构不同的 Command Outcome；LOCAL_UI 只返回 UthCode 结构化动作，不导入 Textual。
- Completion 的 canonical 与 alias 都参与匹配，按 canonical 去重；`/` 不截断全部命令；`/help` 恰好一次且固定最后；未实现命令可见并标记。
- Usage、参数提示、静态参数和动态参数候选都来自 Registry 定义；`/model` 动态候选读取 Application Model Catalog。
- built-in Registry 必须按原始需求完整登记命令、alias、kind 和实现状态；`/models` 仅为 `/model` alias。
- help、Completion、TUI 未来调用方不得各自维护第二份命令列表。
- config、compact、plan、new、resume、login、memory、dream、do、review 只返回统一未实现结果，不创建 handler 占位业务。
- 使用合成命令证明 PROMPT 可执行语义，不提前实现真实 Prompt 命令。
- 不导入 Textual、MewCode、FirstCoder、Provider SDK；不实现 Skill Loader、Session、Agent Loop 或其他后续能力。
- 不保留旧命令 API 兼容层，不执行 Git 写入或归档。

## 验收与 Checklist

逐 Task 执行对应 Checklist。每条只有在命令或可复现测试真实通过后才能勾选；不得修改 Checklist 文本、顺序或其他 Worker 条目。完成本组后至少运行：

```powershell
conda run -n re-uthcode pytest -q tests/test_command_registry.py tests/test_command_parser.py tests/test_command_completion.py tests/test_command_dispatcher.py
conda run -n re-uthcode pytest -q tests/test_configuration.py tests/test_application_runtime.py
conda run -n re-uthcode python -m compileall -q src tests
git diff --check
git status --short
```

同时静态确认 `application/commands` 不导入 Textual、参考项目或未来 Loader，built-in/help/completion 没有第二来源。

## Feedback 与交付

首次执行时创建：

`docs/work/T02-SlashCommand与默认TUI/feedback/W02-command-system-feedback.md`

Feedback 记录实际实现、Registry 单一来源、Parser 数据语义、三类 Outcome、文件改动、测试结果、Checklist 状态、偏差、风险和遗留清理。返工仅追加章节。

最终回复说明 Task 5—Task 6 结果、文件变更、验证证据、勾选状态和风险；明确未实施 Task 7—Task 12，未执行 Git 写入或归档。只有本组全部验收真实通过才能宣告完成。
