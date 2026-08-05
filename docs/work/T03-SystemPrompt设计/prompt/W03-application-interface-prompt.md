# W03 Application Interface Worker Prompt

## 派发范围

你负责严格串行执行：

1. Task 4：建立 Application 运行上下文与权威请求准备；
2. Task 5：统一 CLI、TUI 与 Headless 的运行上下文。

只执行 W03。不得开始 Task 6—Task 8，不得修改 Core Prompt contract、Provider Integration、配置格式、Factory、Widget 核心、Slash Command 或 Git 状态。

## 开始前必须读取

- `AGENTS.md`
- `SRe-AGENTS.md`
- `docs/work/README.md`
- T03 原始需求、Spec、Tasks、Checklist。
- W01、W02 Feedback，并确认 Task 1—Task 3 Checklist 已完成。
- `src/uthcode/application/generation.py`
- `src/uthcode/application/bootstrap.py`
- `src/uthcode/application/configuration.py`
- `src/uthcode/application/__init__.py`
- `src/uthcode/interfaces/cli.py`
- `src/uthcode/interfaces/tui/app.py`
- 对应 Application、CLI、TUI 测试。
- T02 W01 与 W03 Feedback，特别是模型切换、取消隔离、流式刷新和安全诊断返工记录。

开始编码前确认 W01/W02 定向测试通过，检查工作区并保留既有修改。遇到必须修改 EffectiveConfig/TOML 或让 Interface 直连 Core Prompt 的情况立即停止并记录。

## 已确认设计决策

- ApplicationRuntimeContext 与 EffectiveConfig 分离，持有稳定 workdir、平台和日期事实。
- Application 每次生成读取当前模型身份，构建新的权威 Prompt 请求；不修改调用方请求。
- 调用方自带 Prompt 必须拒绝，不能覆盖或拼接。
- 成功切换模型后下一请求刷新身份；失败后维持旧身份。
- CLI 解析一个 workdir 同时用于配置发现和 RuntimeContext；TUI 从 Application 读取 workdir。
- Interface 不导入 Core Prompt API，不改变既有流式、取消、退出码和 stdout/stderr contract。

## 修改范围

允许新增：

- `src/uthcode/application/runtime_context.py`
- `docs/work/T03-SystemPrompt设计/feedback/W03-application-interface-feedback.md`

允许修改：

- `src/uthcode/application/generation.py`
- `src/uthcode/application/bootstrap.py`
- `src/uthcode/application/__init__.py`
- `src/uthcode/interfaces/cli.py`
- `src/uthcode/interfaces/tui/app.py`
- `tests/test_application.py`
- `tests/test_application_runtime.py`
- `tests/test_cli.py`
- `tests/test_tui.py`
- `README.md`
- Checklist 中 Task 4、Task 5 的现有复选框，只能由 `[ ]` 改为 `[x]`。

禁止修改 `configuration.py`、配置 Integration、Provider Factory、Provider 实现、Widget、Command 系统和其他文件。

## 实施约束

- Task 4 先以失败测试建立 Context、请求复制、冲突拒绝和模型刷新 contract，验证通过后再实施 Task 5。
- workdir 必须绝对规范化；平台和日期在 Application Context 创建时解析一次，测试允许固定注入。
- 保持 `stream_generation()`、GenerationHandle 和取消隔离的既有语义。
- README 只描述当前正式 API；不得加入未来能力或覆盖 System Prompt 的示例。
- 不新增依赖、兼容层、第二运行上下文或第二 Prompt 所有者。
- 不执行 live Provider、Git 写入或归档；治理 Markdown 修改使用 `uth-utf8-guard`。

## 测试与验收

- 严格完成 Checklist 的 Task 4、Task 5。
- 至少执行：

```powershell
conda run --no-capture-output -n re-uthcode pytest -q tests/test_application.py tests/test_application_runtime.py
conda run --no-capture-output -n re-uthcode pytest -q tests/test_cli.py tests/test_tui.py
conda run --no-capture-output -n re-uthcode pytest -q tests/test_provider_contract.py tests/test_anthropic_integration.py tests/test_openai_responses_integration.py tests/test_openai_compat_integration.py
conda run --no-capture-output -n re-uthcode python -m compileall -q src tests
git diff --check
```

- 扫描 Interface 中 Prompt API 为 0，配置模型中新增 Runtime 字段为 0。

## Feedback 要求

首次执行创建 `docs/work/T03-SystemPrompt设计/feedback/W03-application-interface-feedback.md`。记录 RuntimeContext 实际结构、权威请求准备流程、模型切换证据、CLI/TUI/Headless workdir 数据流、取消与渲染回归、README 改动、精确测试结果、Checklist 状态、差异和风险。返工仅追加原文件。
