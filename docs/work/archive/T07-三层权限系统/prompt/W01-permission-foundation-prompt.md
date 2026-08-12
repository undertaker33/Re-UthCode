# W01 Permission Foundation Prompt

## 任务

严格串行执行：

1. Task 1 — 全局权限约束与 Core Domain
2. Task 2 — Tool Preflight 与 Trusted Action

不得提前实施 Task 3～10。完成后停下，等待人工审查。

## 必须完整读取

- `AGENTS.md`
- `SRe-AGENTS.md`
- `docs/work/README.md`
- `docs/work/T07-三层权限系统/T07-三层权限系统.md`
- `docs/work/T07-三层权限系统/T07-三层权限系统-spec.md`
- `docs/work/T07-三层权限系统/T07-三层权限系统-tasks.md`
- `docs/work/T07-三层权限系统/T07-三层权限系统-checklist.md`
- T04 工具系统的 Spec、Tasks、相关 Feedback
- 当前 `core/tool.py`、六个内置 Tool、factory、对应测试

历史 UthCode 与 MewCode 仅按原始需求指定位置只读参考，禁止复制旧类型、旧 API、五层 checker、PathSandbox、安全命令巨大白名单或 UI 耦合。

## 已确认设计决策

- 唯一领域链为 Action → Guard/Policy Rules → Strategy → Decision；HITL 不是第四层。
- 模式固定为 default、auto、full_access；Effect 固定为 READ、WRITE、DESTRUCTIVE、EXTERNAL、UNKNOWN。
- full_access 忽略普通 Policy/Strategy，但 Guard Ask/Deny 仍有效；Guard Allow 在普通模式继续后续求值。
- Action/Effect 是内部可信事实，模型参数不能声明或覆盖，Provider ToolDefinition 不携带权限元数据。
- unknown/invalid ToolCall 不进入 Permission；现有 JSON Schema 校验只能保留一份。
- Bash 无法可靠判断时是 UNKNOWN；Guard/classifier 不是 OS Sandbox。

## 修改范围

只修改 Task 1、Task 2 明列文件，以及确有必要的 `core/__init__.py` 公共导出和对应现有测试。不得修改 Application runs、规则文件 loader、Agent Loop、TUI、CLI 或 Provider adapter 权限行为。

## 实施约束

- 使用 `conda run --no-capture-output -n re-uthcode ...`。
- 先写失败测试，再实现最小生产代码；保持不可变、JSON-safe、Provider 无关与依赖方向。
- prepared/validated 边界不得在 resume 时重复任何有副作用逻辑。
- 不引入新运行时依赖，不增加兼容层、旧入口别名、未来 Protocol/Registry 或空目录。
- 遇到工作包冻结语义与真实代码发生会改变公共边界的冲突，停止相关实施并写入 Feedback，不修改工作包文字。
- 不执行 Git add/commit/push，不归档工作包。

## 测试与验收

- 完成 Task 1 后执行 `tests/test_permission.py`。
- 完成 Task 2 后执行 Tool core、file、search、process、application tool 相关测试。
- 执行 T04 全部相关回归、`python -m compileall -q src tests`、`git diff --check`。
- 对 `SRe-AGENTS.md` 和 Feedback 执行 UTF-8 guard。
- 逐项核对 Checklist 的 Task 1、Task 2；只允许把实际通过项改为 `[x]`。

## Feedback

首次执行创建并持续维护：

`docs/work/T07-三层权限系统/feedback/W01-permission-foundation-feedback.md`

Feedback 精简记录实际机制、修改文件、测试命令与结果、Checklist 状态、任务书偏差、风险和遗留负担。返工只在同一文件末尾追加新章节，不覆盖旧事实。
