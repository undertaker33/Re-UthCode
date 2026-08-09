# W01 Core Prompt Contract Worker Prompt

## 派发范围

你负责严格串行执行：

1. Task 1：建立 Core System Prompt 模块；
2. Task 2：替换 Core 请求中的临时 System Message 语义。

只执行 W01。不得开始 Task 3—Task 8，不得修改 Provider Integration、Application、Interface、README 或 Git 状态。

## 开始前必须读取

- `AGENTS.md`
- `SRe-AGENTS.md`
- `docs/work/README.md`
- `docs/work/T03-SystemPrompt设计/T03-SystemPrompt设计.md`
- `docs/work/T03-SystemPrompt设计/T03-SystemPrompt设计-spec.md`
- `docs/work/T03-SystemPrompt设计/T03-SystemPrompt设计-tasks.md`
- `docs/work/T03-SystemPrompt设计/T03-SystemPrompt设计-checklist.md`
- `src/uthcode/core/provider.py`
- `src/uthcode/core/__init__.py`
- `tests/test_provider_contract.py`
- 原始需求列出的 T01 Core contract 与相关 Feedback。

开始编码前确认 HEAD 基于原始需求固定基线，检查 `git status --short`，保留所有既有用户修改。若公共协议与任务记录存在无法解释的差异，停止并写入 Feedback。

## 已确认设计决策

- Core 是 System Prompt 语义和构建逻辑的唯一所有者。
- Prompt 使用五个固定 Section，静态规则在前、运行环境在后；只陈述当前真实能力。
- `GenerationRequest` 使用唯一独立 `system_prompt`；普通 `Message` 只允许 user、assistant、tool。
- 不保留 System Message 兼容入口，不新增 developer 或同义 Prompt 字段。
- 不创建 Prompt 框架、未来能力字段或缓存控制。

## 修改范围

允许新增：

- `src/uthcode/core/prompt.py`
- `tests/test_system_prompt.py`
- `docs/work/T03-SystemPrompt设计/feedback/W01-core-prompt-contract-feedback.md`

允许修改：

- `src/uthcode/core/__init__.py`
- `src/uthcode/core/provider.py`
- `tests/test_provider_contract.py`
- Checklist 中 Task 1、Task 2 的现有复选框，只能由 `[ ]` 改为 `[x]`。

禁止修改其他文件。发现确需越界时停止并记录，不得自行扩大范围。

## 实施约束

- 先写/调整失败测试，再实现最小代码；Task 1 验证通过后才能进入 Task 2。
- Prompt 构建保持纯函数、不可变、无 I/O、无环境读取和确定性。
- 运行值必须安全转义，不得允许换行或 Markdown 特殊字符破坏段落结构。
- 不引入第三方依赖，不复制旧仓完整文件，不添加 Adapter、Alias、Facade、Shim 或双轨逻辑。
- 不执行真实网络请求、Git commit、push、PR、merge 或工作包归档。
- 修改治理 Markdown 时使用 `uth-utf8-guard`，不得改写冻结文字。

## 测试与验收

- 严格完成 Checklist 的 Task 1、Task 2。
- 至少执行：

```powershell
conda run --no-capture-output -n re-uthcode pytest -q tests/test_system_prompt.py
conda run --no-capture-output -n re-uthcode pytest -q tests/test_provider_contract.py
conda run --no-capture-output -n re-uthcode python -m compileall -q src/uthcode/core tests/test_system_prompt.py tests/test_provider_contract.py
git diff --check
```

- 检查 W01 之外源码无新增 diff。

## Feedback 要求

首次执行创建 `docs/work/T03-SystemPrompt设计/feedback/W01-core-prompt-contract-feedback.md`。内容精简记录：实际基线与初始状态、Prompt Section/Context 实际结构、请求协议和角色变化、修改文件、精确测试结果、Checklist 完成情况、与任务书差异、遗留风险和兼容负担清理。返工只能在该文件末尾追加章节。

