# 工作包规则

本文件约束 `docs/work/` 下工作包的生成、派发、实施和反馈。执行相关任务前必须完整读取并遵守。

## 1. 目录职责

`docs/work/` 是工作包根目录：直接子目录 `TXX-*` 只存放仍活跃的正式工作包，`docs/work/archive/` 存放用户已归档的完成工作包。

工作包完成后，必须等待用户确认并由用户手动移动至 `docs/work/archive/`。Agent 不得自行归档。

收到需求文件 `TXX-xxxx.md` 后：

1. 创建 `docs/work/TXX-xxxx/`；
2. 将原始需求文件移动至该目录并保留；
3. 验证需求中提及的源码、报告、实验、教程和官方资料；
4. 找出影响范围、架构、行为或验收方式的待确认项；
5. 为每个待确认项提供可选方案、影响和推荐方案；
6. 用户完成全部决策后，生成正式工作包。
7. 同步维护 `docs/Context-Index.md` 的 `current-status`，再结束任务包拆分。

```text
docs/work/TXX-xxxx/
├── TXX-xxxx.md
├── TXX-xxxx-spec.md
├── TXX-xxxx-tasks.md
├── TXX-xxxx-checklist.md
├── prompt/
│   ├── W01-xxxx-prompt.md
│   └── W02-xxxx-prompt.md
└── feedback/
    ├── W01-xxxx-feedback.md
    └── W02-xxxx-feedback.md
```

`TXX-xxxx` 必须与原始需求文件名一致。同一 Worker 的 Prompt 与 Feedback 必须使用相同的 `WXX-xxxx`。

### 1.1 Context 索引维护

每次创建或重新拆分任务包时，拆分 Agent 必须重新盘点 `docs/work/` 的直接 `TXX-*` 子目录与 `docs/work/archive/`，并维护 `docs/Context-Index.md` 的 `current-status` 全量清单，不得只追加当前 Task。

- 新建、未开始或部分实施的任务包标记为 `not_implemented`；
- 只有当前源码已有实现、Checklist 全部完成且 Feedback 已记录，才标记为 `implemented_unarchived`；
- 只有目录已经由用户移动到 `docs/work/archive/`，才标记为 `archived`；
- 同步更新 `status_snapshot`、任务包路径和验收证据摘要；
- 工作包存在不等于已经实现，Feedback 存在也不等于 Checklist 已完成；必须同时核对目录、Checklist、Feedback 与当前源码；
- `current-status` 是工作包外部索引，不属于冻结的 Spec、Tasks、Prompt 或 Checklist；维护索引不授权 Agent 移动/归档工作包或修改冻结内容。

未完成上述同步时，任务包拆分不算交付完成。

## 2. Spec

`TXX-xxxx-spec.md` 定义交付边界，回答做什么、为什么做、做到什么程度。

必须包含：

- 背景；
- 目标；
- 按 Task 划分的能力清单；
- 非功能要求；
- 设计骨架；
- Out of Scope；
- 验收标准。

不得包含具体函数名、参数名、默认值、错误文本、源码行号、SDK 内部类型或逐文件实施步骤。

## 3. Tasks

`TXX-xxxx-tasks.md` 定义实施顺序和文件级改动。

文件顶部必须声明长期 Worker 分组、Worker 内部 Task 顺序及 Worker 之间的依赖关系。一个 Worker 应严格串行完成一组强相关 Task，不得默认按单个 Task 分配 Worker。

每个 Task 必须包含：

- 任务目标；
- 新增、修改和删除的文件；
- 文件职责及实施内容；
- 依赖任务；
- 参考资料定位；
- 完成边界。

单个 Task 应能在一个专注会话中完成，不得仅按文件数量拆分。

任务序列末尾必须依次包含：

- `[接入主流程]`：接入正式调用链并删除被替代的旧入口；
- `[端到端验证]`：从真实入口验证正常路径和关键失败路径；
- `[遗留负担清理]`：确认未引入或保留兼容层、废弃实现、不可达代码、重复职责、重复实现，以及仅为兼容 Re 早期内容而存在的逻辑。

## 4. Checklist

`TXX-xxxx-checklist.md` 必须与 Tasks 的 Task 编号、名称和顺序一一对应。

每项必须可执行、可观测，并能够明确判断通过或失败。

```text
- [ ] 执行 `pytest ...`，全部用例通过。
- [ ] 执行 `grep -r "LegacyX" src tests`，返回 0 条。
- [ ] 从正式入口输入 X，可以观察到输出 Y。
```

禁止使用“实现完整”“质量良好”“架构合理”“功能正常”“测试充分”等模糊表述。

Checklist 末尾必须分别包含：

- `[接入主流程]`；
- `[端到端验证]`；
- `[遗留负担清理]`。

至少包含一条真实端到端验收。

## 5. Prompt

`prompt/` 由工作包拆分 Agent 编写，每个长期 Worker 使用一个独立文件：

```text
prompt/WXX-xxxx-prompt.md
```

Prompt 必须能够脱离聊天记录独立执行，并至少包含：

- Worker 负责的 Task 及严格执行顺序；
- 必须读取的工作包文件和源码；
- 已确认的设计决策；
- 修改范围和禁止修改范围；
- 实施约束；
- 测试与验收要求；
- Feedback 编写要求。

任务只能由用户通过指定 Prompt 文件显式派发。未收到明确指派时，不得自行开始实施。

```text
请完整读取并执行：docs/work/TXX-xxxx/prompt/W01-xxxx-prompt.md
```

## 6. Feedback

`feedback/` 由执行长期 Worker 的 Agent 编写，每个 Worker 始终使用同一个文件：

```text
feedback/WXX-xxxx-feedback.md
```

Feedback 面向人工审查，应让用户能够理解：

- 实际完成了什么；
- 关键实现如何工作；
- 为什么采用当前实现；
- 修改了哪些文件；
- 执行了哪些测试及其结果；
- Checklist 完成情况；
- 与任务书不同的实际情况；
- 未完成项、风险或需要用户决定的问题；
- 遗留负担清理结果。

涉及关键机制时，可以按照简短教程的方式说明实际调用流程、核心数据结构和状态变化，但必须以审查所需信息为限。

禁止：

- 堆砌源码；
- 逐行复述实现；
- 重复任务书内容；
- 记录无关操作过程；
- 使用空泛总结；
- 为显得完整而生成超长文档。

Feedback 应在保证用户能够理解和复审的前提下尽可能精简。

首次执行时创建对应 Feedback 文件。返工时必须在原文件末尾追加新章节，不得：

- 新建 `v2`、`retry`、`fix` 等反馈文件；
- 删除或覆盖旧记录；
- 修改此前已经记录的事实。

每次追加必须标明返工轮次、返工原因、实际修改和重新验证结果。

## 7. 实施冻结

用户首次显式派发任意 Worker Prompt 后，该工作包进入实施阶段。

实施开始后，以下内容立即冻结：

- 原始需求文件；
- Spec；
- Tasks；
- Prompt；
- Checklist 的文字内容、结构、编号和顺序。

实施 Agent 不得修改、补充、重排或重写上述文件。

Checklist 只允许将现有复选框由未完成状态改为完成状态，不得修改验收项内容。

实施期间只有 Feedback 允许追加写。

发现任务书错误、缺失、冲突或需要扩大范围时：

1. 停止相关范围的实施；
2. 在 Feedback 中记录问题和影响；
3. 交由用户决定是否终止当前工作包并重新生成工作包。

不得通过直接修改冻结文件修补实施计划。

## 8. 一致性要求

工作包必须满足：

```text
Spec 中的能力
→ Tasks 中有对应实施任务
→ Checklist 中有对应验收证据
→ Prompt 中有明确执行指令
→ Feedback 中有实际完成记录
```

同时必须满足：

- Spec、Tasks 和 Checklist 的 Task 编号、名称及顺序一致；
- Tasks 中的 Worker 分组与 Prompt 文件一一对应；
- Prompt 与 Feedback 通过相同的 `WXX-xxxx` 一一对应；
- Out of Scope 不得进入 Tasks 或 Prompt；
- 未经用户确认的重大决策不得写成既定方案；
- Feedback 中发现的范围外问题不得直接实施；
- 不得为兼容旧类、旧 API、旧行为或 Re:UthCode 早期实现而偏离当前 Spec。
