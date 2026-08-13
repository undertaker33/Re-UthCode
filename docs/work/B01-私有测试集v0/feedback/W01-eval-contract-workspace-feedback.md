# W01 Eval 合同与 Workspace Feedback

## 执行范围

- Worker：`W01-eval-contract-workspace`
- 执行顺序：Task 1 -> Task 2
- 执行日期：2026-08-13
- Conda 环境：`re-uthcode`
- 开始时 Git 状态：`## main...origin/main`；已有改动为 `docs/Context-Index.md`、`docs/OutstandingDebtList.md`，以及未跟踪的 B01 工作包目录。以上内容均未覆盖、清理或改写。
- 源码仓库物理路径：`D:\project\Re-UthCode`

本次严格限制在 `eval/models.py`、`eval/workspace.py`、对应离线测试、Task 1～2 Checklist 和本 Feedback。没有修改 `src/uthcode/**`、`pyproject.toml`、`.gitignore`、`tests/conftest.py`、正式 CLI/TUI、Provider、Permission、Agent Loop 或公共 Event。

## Task 1：实际合同

`eval/models.py` 建立 schema version `1` 的独立 Eval 数据合同，不持久化 UthCode Core 类型，包含：

- `TaskDefinition`、`RequiredEvidence`、`InteractionSpec`、`PermissionRule` 和 `ScoringSpec`；支持严格 TOML/JSON 入口。
- `VerifierCheck` 与 `VerifierResult`；检查项区分 `hard`、`partial`、`forbidden`，分数限制在合法范围，`success` 必须与 hard/forbidden 检查事实一致。
- `MetricValue`；`available` 且值为 `0` 与 `not_available` 且值为 `null` 使用不同的序列化形状。
- `AttemptRecord`；保存实验/任务/attempt 标识、指纹、路径、时间、结束分类、公开 turn 投影、verifier、指标和 artifact manifest，不接受 Provider 原生对象。

解析和构造会硬失败于未知或缺失字段、未知 schema、非规范相对路径、重复 ID、非法交互、宽泛/通配权限规则、越界分数和不一致成功状态。嵌套合同值在构造后冻结；错误文本只包含字段定位，不回显测试秘密或输入正文。

## Task 2：实际 Workspace 与安全边界

`eval/workspace.py` 的生命周期如下：

```text
repo root + external root
  -> physical resolve / repo-home-root-link checks
  -> dedicated .uthcode-eval-root.json marker
  -> workspaces/<experiment>/<task>/<attempt>
     homes/<experiment>/<task>/<attempt>
     artifacts/<experiment>/<task>/<attempt>
  -> fixture copy + SHA-256 + ready manifest
  -> exact manifest preflight
  -> clean only the named attempt components
```

实际防线包括：

- 拒绝源码仓库及其子目录、用户 home 及其子目录、filesystem/盘符根、未带专用 marker 的现有目录、符号链接和可识别的 Windows junction；外部 root 与 marker 绑定到同一物理源码仓库后才可重用。
- fixture 只复制到独立 workspace；fixture 本身和源码仓库不执行、不回写；fixture 中的链接会在写入前拒绝。
- 创建过程先写 `creating` manifest；复制或后续创建失败时保留 `creation_failed` manifest 和证据，不删除可能含副作用的部分 workspace。
- repository snapshot 使用只读 `git status --short --untracked-files=all`；运行前后的增量比较不会把已有 dirty/untracked 条目误报为新增污染。
- clean 只接受明确的 experiment/task/attempt 标识、专用 root、身份匹配的 manifest 和三个具体组件；删除前解析全部目标并检查物理边界、目录类型和递归链接。遇到链接或不明确目标直接停止，不升级删除手段。该实现不是通用删除工具。

## 修改文件

- `eval/models.py`
- `eval/workspace.py`
- `tests/eval/test_eval_reporting.py`
- `tests/eval/test_eval_workspace.py`
- `docs/work/B01-私有测试集v0/B01-私有测试集v0-checklist.md`：仅勾选现有 Task 1～2 复选框
- `docs/work/B01-私有测试集v0/feedback/W01-eval-contract-workspace-feedback.md`

Task 3～9 的实现文件、七题 fixture/verifier、metrics/reporting、runner 和正式入口均未新增。

## 精确验证结果

1. `conda run --no-capture-output -n re-uthcode python -m pytest tests/eval/test_eval_reporting.py tests/eval/test_eval_workspace.py -q`
   - 结果：`20 passed in 1.75s`。
2. `conda run --no-capture-output -n re-uthcode python -m compileall -q eval tests/eval`
   - 结果：退出码 `0`。
3. `git diff --check`
   - 结果：退出码 `0`；Git 仅提示仓库原有 `docs/Context-Index.md` 与 `docs/OutstandingDebtList.md` 的 LF/CRLF 转换警告，没有 whitespace error。

测试覆盖了合同 round-trip、未知字段/版本/路径、重复 ID、非法 interaction、宽泛 permission rule、分数边界、秘密不回显、`not_available` 与零值区分、嵌套不可变、AttemptRecord round-trip；以及 repo/子目录/link/home/root 拒绝、未标记目录拒绝、重复 attempt、dirty/untracked 保留、fixture 复制、部分创建失败、精确 clean、链接清理停止和同仓库 root 重开。

## Checklist 与差异

- Task 1：两项 Checklist 已完成，有上述定向测试证据。
- Task 2：三项 Checklist 已完成，有上述定向测试证据。
- 与 Task/Prompt 的实际范围无实质差异。按 Prompt 要求没有提前实施 Agent 执行、任务集、报告或 runner。
- 没有执行 Task 3～9 测试、全量 pytest、真实 Provider baseline 或任何网络/费用调用；这些属于后续 Worker 或明确授权范围。
- 没有执行 Git add、commit、push、merge、rebase 或归档。

## 遗留负担、风险与未验证项

- 未引入 Benchmark adapter、数据库、Registry/Manager、第二 Agent Loop、第二 Permission 系统或兼容层；Eval 合同模块不导入 `uthcode.core`、`uthcode.integrations` 或 Provider SDK。
- `Bash`、OS 权限和 Application 执行语义未被改变；本 Worker 没有声称外部 workspace 是 Sandbox。
- Windows junction 的实现路径使用 Python 可用的 junction 检测；当前离线测试在本机以可用的目录符号链接覆盖链接拒绝和 clean 停止，未额外创建 junction fixture。
- 未运行真实模型，未验证 W02 对合同/workspace API 的接入；W02 应在读取本 Feedback 后继续按其 Prompt 验收。

## UTF-8 guard

- files checked: `docs/work/B01-私有测试集v0/B01-私有测试集v0-checklist.md`、`docs/work/B01-私有测试集v0/feedback/W01-eval-contract-workspace-feedback.md`
- result: UTF-8 解码、replacement character、常见乱码和 Markdown fence 检查通过。
- repaired encoding issues: none

## 返工轮次 1：验收反馈后的安全边界修复

### 返工原因

首次验收不通过，发现三项边界问题：fixture 可传入 Eval root 并触发自复制风险；Permission resource 接受 `../outside.txt`、`src/../../outside.txt` 和 `./inside.txt`；外部 Eval root 错误地拒绝了用户 home 下的专用子目录。

### 实际修改

- `eval/workspace.py`：fixture 现在必须是源码仓库内的物理子目录，明确排除 Eval root，并在创建前检查与三个 attempt destination 不重叠；外部 root 仅拒绝用户 home 根本身，允许其下的专用目录。
- `eval/models.py`：Permission resource 复用规范化相对路径校验，拒绝绝对路径、`.`、`..`、路径穿越、通配符和非规范写法后才构造规则。
- `tests/eval/test_eval_workspace.py`：补充 home 子目录允许、home 根拒绝，以及源码仓库外、源码仓库根、Eval root fixture 拒绝且不产生 attempt 残留的测试。
- `tests/eval/test_eval_reporting.py`：补充三种 Permission resource 路径穿越回归测试。
- 冻结的 Spec、Tasks、Prompt、Checklist 未修改；本轮仅在本 Feedback 末尾追加记录。

### 重新验证结果

1. `conda run --no-capture-output -n re-uthcode python -m pytest tests/eval -q`
   - 结果：`25 passed in 2.18s`。
2. `conda run --no-capture-output -n re-uthcode python -m compileall -q eval tests/eval`
   - 结果：退出码 `0`。
3. `git diff --check`
   - 结果：退出码 `0`；仅有仓库原有文档的 LF/CRLF 转换警告，无 whitespace error。
4. UTF-8 guard：重新检查本 Feedback 与 W01 Checklist，2 个文件通过；无 replacement character、常见乱码或不平衡 Markdown fence。

本轮已覆盖并修复本次验收指出的安全问题，但 W01 是否重新验收通过仍以用户复核为准；在用户确认前不建议进入 W02。未执行 Git add、commit、push 或工作包归档。
