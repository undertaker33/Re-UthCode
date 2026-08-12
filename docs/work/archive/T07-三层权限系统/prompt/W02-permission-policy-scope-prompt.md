# W02 Permission Policy and Scope Prompt

## 任务

严格串行执行：

1. Task 3 — permissions.toml Discovery / Parse / Template
2. Task 4 — Workspace / Resource Scope 改造
3. Task 5 — Rule + Strategy Evaluator 与 Guard

不得提前实施 Task 6～10。完成后停下，等待人工审查。

## 前置门槛

先读取 `feedback/W01-permission-foundation-feedback.md`，确认 Task 1、Task 2 已完成且相应测试通过。若文件缺失、记录未完成或实现与冻结模型冲突，停止并报告，不自行修补 W01 范围。

## 必须完整读取

- `AGENTS.md`、`SRe-AGENTS.md`、`docs/work/README.md`
- T07 原始需求、Spec、Tasks、Checklist
- W01 Prompt 与 Feedback
- T03/T04 中配置发现、workspace、file/search/process 的 Spec、Tasks、相关 Feedback
- 当前 `integrations/config/loader.py`、workspace、六 Tool、factory、W01 permission domain 与对应测试
- 原始需求指定的 MewCode `dangerous.py`、checker、sandbox 只作取舍证据

## 已确认设计决策

- 规则来源为 user + Git root→cwd recursive project；非 Git 只读 cwd。最近项目 > 父项目 > 用户 > 默认模板。
- 同一有效来源同类规则严格度为 Deny > Ask > Allow，不是跨来源全局 deny wins。
- 用户权限文件缺失时创建默认 Guard 模板，当前 workdir 项目文件缺失时创建空占位；规则在 Run 初始化时形成快照，不热重载。
- outside workspace 是物理资源范围事实，不是 Tool hard deny；批准后必须能真实操作。
- Session Grant 只覆盖精确 tool/action/effect/有界资源的普通 Strategy Ask，不能覆盖 Guard 或 Policy Deny。
- 敏感内容读取/搜索受 Guard，metadata 枚举不自动等同读取内容；Grep 不能旁路。
- 高置信 Bash Guard 默认 Ask，正反例边界按原始需求；不执行危险命令，不实现完整 Shell AST。

## 修改范围

只修改 Task 3～5 明列文件、`.gitignore` 的必要精确规则、真实职责对应测试，以及 W01 文件中为完成 evaluator 必需的既定扩展。不得修改 Agent Loop、T06 interaction、Application session、Slash Command、TUI/CLI 或 Provider adapter。

## 实施约束

- 使用 `conda run --no-capture-output -n re-uthcode ...`，测试隔离 HOME 与 workdir，禁止污染真实 `~/.uthcode/permissions.toml`。
- 配置 discovery 必须复用/提取现有算法；不得复制第二套 Git root/cwd 遍历。
- Core 不导入 `tomlkit` 或 filesystem；Integration 负责文件生命周期、regex 验证与 Core value 转换。
- 路径按 lexical normalize → physical resolve → scope classify；保留 FileReadTracker 全部不变量。
- 危险 Guard 测试只 mock/stub execute。
- 不引入新依赖、兼容层、PathSandbox、旧 YAML/local 规则、热重载、always 按钮或未来占位。
- 不执行 Git 写，不归档工作包。

## 测试与验收

- 按 Task 完成顺序执行 permission rules/config、workspace/file/search、permission matrix/Bash Guard 测试。
- 执行 T04 配置与 Tool 回归、W01 permission/tool 测试、`compileall`、`pip check`、`git diff --check`。
- 对新增/修改 Markdown 与 Feedback 执行 UTF-8 guard。
- 逐项核对 Checklist Task 3～5，只勾选有证据的项目。

## Feedback

创建并持续维护：

`docs/work/T07-三层权限系统/feedback/W02-permission-policy-scope-feedback.md`

记录规则文件实际格式和生命周期、路径范围机制、Guard 边界、修改文件、测试结果、Checklist、偏差、风险与遗留清理。返工只追加。
