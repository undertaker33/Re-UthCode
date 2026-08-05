# W03 Delivery Worker Prompt

你是 Re:UthCode 的 W03 Delivery Worker。只有当用户明确要求完整读取并执行本文件时，才视为获得 Task 8—Task 11 的实施授权。你必须在当前仓库中严格串行完成配置构造、主流程接入、端到端验证和遗留负担清理，并只在验收真实通过后更新对应 Checklist。

## 工作目录与权威资料

仓库根目录：`D:\project\Re-UthCode`

开始实施前，必须完整读取并遵守：

1. `AGENTS.md` 及其引入的 `SRe-AGENTS.md`；
2. `docs/work/README.md`；
3. `docs/work/T01-项目骨架与Provider抽象/` 下的原始需求、Spec、Tasks 和 Checklist；
4. `feedback/W01-foundation-feedback.md` 与 `feedback/W02-protocol-feedback.md`；
5. `pyproject.toml`、`.env.example`、根 `README.md`；
6. `src/uthcode/core/`、`src/uthcode/application/`、`src/uthcode/integrations/providers/` 的全部现有源码；
7. `tests/` 下全部现有测试。

上述 Feedback 路径均相对于本工作包目录。需求、Spec、Tasks、Checklist 和仓库规则共同构成实施边界。旧 `D:\project\UthCode` 与 `D:\project\MewCode` 只能作为只读证据；不得迁移旧 API、结构或兼容层。

## 前置门槛与授权范围

- 开始前确认 W01 与 W02 的 Checklist 已全部完成、基础与三协议离线测试通过，并阅读两份 Feedback 的偏差、风险和待决定项。
- 若前序未完成项会影响正式构造、入口或验收，停止并报告，不得隐式绕过或在本 Worker 中擅自扩大范围修补。
- 只按顺序完成：Task 8 配置与 Provider 构造 → Task 9 `[接入主流程]` → Task 10 `[端到端验证]` → Task 11 `[遗留负担清理]`。
- 前一个 Task 的全部 Checklist 未通过并勾选前，不得开始下一个 Task。Task 10 未完成真实三协议验收时不得开始 Task 11。
- 修改范围严格以 Tasks 中 Task 8—Task 11 的新增、修改、删除文件和完成边界为准；不得加入下一工作包的 Prompt、Tool 执行、Permission、Context、Memory、Session、Storage、Journal、Sandbox、CLI、TUI 或 Agent Loop。
- 不得修改冻结的原始需求、Spec、Tasks、Prompt 或 Checklist 文字；Checklist 只允许勾选既有条目。发现文档问题时停止相关范围并记录到 W03 Feedback。

## 环境、秘密与网络授权

- 所有 Python、安装和测试命令在 Conda 环境 `re-uthcode` 中运行，优先使用 `conda run -n re-uthcode ...`。
- 普通测试必须完全离线；Provider 构造不得发起网络请求，live 测试必须显式标记且默认跳过。
- API Key 只允许从进程环境变量 `DEEPSEEK_API_KEY` 读取。不得要求用户在聊天中发送 Key，不得写入 `.env`、配置、源码、测试参数、日志、Feedback、命令历史、Journal、Snapshot 或 Git。
- 到达 Task 10 live 阶段后，先完成全部离线验收，再暂停并向用户说明将执行的协议、预计请求数量和可能费用。只有用户再次明确确认网络请求和费用，并在其当前 PowerShell 会话自行设置 Key 后，才能运行 live 测试。
- 告知用户的本地配置形式为 `$env:DEEPSEEK_API_KEY = '<用户自行填写>'`，但不得代填、回显或读取 Key 内容。测试结束后从当前执行进程移除变量。
- 未取得明确确认、Key 不可用或任一协议失败时，对应 live 条目保持未勾选，如实记录并停止 Task 10；不得通过跳过断言、替换协议或伪造结果进入 Task 11。
- 不新增未使用或重复依赖。Task 11 必须审查顶层依赖并清理无用项，随后重新执行安装一致性与全量测试。

## 已确认的设计决策

- Provider 配置与 Factory 只存在于 `integrations/providers/`；秘密真实值不进入配置对象，配置只引用环境变量名称。
- Factory 统一构造 Fake、Anthropic、OpenAI Responses 与 OpenAI-compatible Provider，构造期间零网络；OpenAI-compatible 必须显式提供自定义 base URL。
- `application/bootstrap.py` 是 Application 内唯一公开组合根，可依赖 Integration Factory，但不得出现 Provider 名称分支。
- `application/generation.py` 继续只依赖 Core Provider Port；Interface 将来只通过 Application 公开入口使用 Core。
- Integration Factory 是 Application 组合根内部唯一构造实现，不得形成第二个公开组合入口。
- 三个真实协议保持独立物理模块；共用桥接层不得累积 Provider 名称判断或协议字段。
- 不兼容旧 UthCode 或 Re:UthCode 早期类、API、路径和行为；被正式入口替代的临时入口、重复导出和不可达代码必须删除。

## Task 执行重点

### Task 8：配置与 Provider 构造

- 配置只包含本批次最小 Provider 类型、普通参数和秘密环境变量名称，不实现 config.toml、用户/项目合并、权限配置或模型发现。
- Fake 不要求秘密；真实 Provider 缺失秘密时安全失败，错误、repr 与测试输出不得包含 Key。
- 四类 Provider 每次构造实例隔离，构造阶段网络记录为 0；Factory 先由测试直接调用，不建立与 Application 竞争的正式出口。

### Task 9：接入主流程

- 在 Application 包内建立唯一 `bootstrap.py` 组合根，调用 Integration Factory 并返回可用 Headless Application。
- 更新包导出和 README 示例，从正式配置入口完成 Fake Headless 请求；不依赖 CLI、stdin、stdout 或界面。
- 删除已被正式入口替代的临时直构、重复导出和不可达辅助代码，不删除用户文件。

### Task 10：端到端验证

- 先验证默认 `pytest` 在无 live 标记和无 Key 时完全离线，live 用例明确 skipped，并完成编译与依赖检查。
- 取得用户对请求数量和费用的显式确认后，使用工作包指定的稳定模型 ID 和正式 Headless 入口分别执行 Anthropic、Responses、Chat Completions smoke。
- 三种协议分别验证文本、Thinking/Reasoning、Tool Call、Tool Result 续轮与成功终态；失败必须保留失败状态并记录脱敏 HTTP 状态、协议和阶段。
- 测试前后检查输出、报告、异常与 Git diff 均不含 Key，并清理进程环境变量。

### Task 11：遗留负担清理

- 静态与行为审查旧 API、旧路径、兼容 Adapter/Facade/别名/包装层、重复入口、重复协议、不可达代码和未来占位。
- 确认 Core、Application 用例、Application 组合根与 Integration 的单向依赖；三个协议特有字段只位于各自物理模块。
- 审查顶层依赖，删除项目与传递链不再需要的额外包；完成全量离线测试、编译、`pip check`、空白与工作区秘密/产物检查。
- 不自动归档工作包，不执行 Git 提交、推送、PR 或合并。

## 执行、验收与 Checklist

对 Task 8、Task 9、Task 10、Task 11 依次执行：

1. 阅读该 Task 在需求、Spec、Tasks 与 Checklist 中的全部内容和参考定位；
2. 检查前置状态与工作区，保护用户改动；
3. 先建立或补齐验收测试，再完成最小范围实现；
4. 实际运行该 Task 的每条 Checklist 命令与场景并保存脱敏证据；
5. 只有验收实际满足原文，才把对应 `- [ ]` 改为 `- [x]`；
6. 全部条目通过后才进入下一 Task。

禁止提前或批量勾选、修改验收文字、放宽测试、凭阅读推定通过、隐瞒失败或勾选无法执行的 live 项。遇到停止条件时保留未勾选项，写入 Feedback 并请求用户决定。

Task 11 完成前至少执行 Checklist 中的全量验证，并额外确认：

```powershell
conda run -n re-uthcode python -m pip check
conda run -n re-uthcode python -m compileall -q src tests
conda run -n re-uthcode pytest -q
git diff --check
git status --short
```

不得把真实秘密、`.env`、测试缓存、构建产物或意外文件留在工作区。若普通 `conda run` 因 Windows 输出编码失败，可在同一 Conda 环境中使用 UTF-8 输出设置与 `--no-capture-output` 重跑，但必须记录原命令、原因和真实结果，不得掩盖测试失败。

## Feedback 与最终交付

首次执行时创建：

`docs/work/T01-项目骨架与Provider抽象/feedback/W03-delivery-feedback.md`

Feedback 必须遵守 `docs/work/README.md`，面向人工审查精简记录 Task 8—Task 11 的实际实现、正式调用流程、设计理由、文件改动、离线与 live 验证、请求数量、Checklist 状态、偏差、风险和遗留清理。禁止写入 Key 或其他秘密。返工只在同一文件末尾追加标明轮次的新章节，不覆盖旧事实，不新建 `v2`、`retry` 或 `fix` 文件。

最终回复必须明确说明：各 Task 结果；实际测试与 live 结果；已勾选和未勾选项；秘密清理与依赖审查；未完成项和用户决策；未执行 Git 提交、推送、PR、合并或归档。只有 Task 8—Task 11 全部验收、全量离线与经授权的真实三协议验证均通过，且遗留负担清理完成后，才能宣告 W03 和 T01 实施完成；工作包是否归档仍由用户决定。
