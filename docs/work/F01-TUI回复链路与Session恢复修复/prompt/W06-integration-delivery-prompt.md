# W06 F01 接入、验收与清理实施提示词

请在 `D:\project\Re-UthCode` 严格串行实施 F01 的 T09 -> T10 -> T11，完成唯一主链接入、端到端验收、当前事实文档同步和遗留负担清理；不得扩大范围。

## 开工前必须读取

1. `AGENTS.md`、`docs/README.md`、`docs/Context-Index.md`
2. 工作包规则、用户拍板边界、欠账清单、`uth-utf8-guard` SKILL
3. F01 原始需求、Spec、Tasks、Checklist 和全部 W01～W05 Prompt/Feedback
4. A01、A03、A04、TUI current context
5. `docs/README.md` 维护映射命中的用户手册、Core Design 和 Tool 文档
6. T09～T11 Tasks 定位的正式入口和 tests

## 已确认决策

- 四项 D-F01-01～04 全部冻结，按 Spec 实施。
- F01 不恢复 active Runtime checkpoint，不放宽原 Tool 脱敏，不新增 History/Session/UI 双轨。
- 只有本 Worker 完成全部证据后才可把 F01 标记 `implemented_unarchived`；不得归档或执行 Git 写。

## 修改范围

- T09～T11 所需正式组合入口、跨层 E2E tests、当前事实文档、F01 Checklist、`docs/Context-Index.md`。
- 首次实施创建 `feedback/W06-integration-delivery-feedback.md`；返工追加。
- 只能勾选有本轮或前序 Feedback 精确证据的 Checklist。

禁止修改 F01 冻结正文/Spec/Tasks/Prompts/Checklist 文字，禁止修改 T03/T05/T09 等冻结工作包，禁止新增范围外产品能力，禁止 commit/push/archive。

## 实施约束

1. 先复核 W01～W05 diff、Feedback 和 Checklist；发现任务书冲突立即记录并停止相关范围。
2. 从唯一正式入口验证普通/post-tool/post-resume/model-switch/new/CLI/Headless/TUI。
3. 真实 Windows Terminal 人工验收必须记录环境、操作和观察结果；无法运行时明确 `NOT VERIFIED`，不得伪造。
4. 当前事实文档只描述最终代码，不回写历史冻结工作包。
5. 使用 `uth-utf8-guard` 检查所有实际修改 Markdown；保留 UTF-8、无乱码、fence 平衡。
6. 清理只删除本包产物和确认无 caller 的被替代代码，不删除旧 Session 或用户文件。
7. 全量失败先判断是否本包回归；普通局部缺陷在范围内修复，范围扩张则停止。

## 测试与验收

完整执行 Checklist T09～T11，至少包含：

```powershell
conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q
conda run --no-capture-output -n re-uthcode python -m pytest -q
conda run --no-capture-output -n re-uthcode python -m compileall -q src tests eval
conda run --no-capture-output -n re-uthcode python -m pip check
git diff --check
```

对原始四轮会话、四现象、九类问题和 D-F01-01～04 建立逐项证据矩阵。

## Feedback 要求

Feedback 必须说明唯一正式调用链、十三项问题的关闭证据、reasoning 流式/颜色、message role、History storage、resume replay、lazy Session、Windows decode、Tool 原脱敏/FIFO、修改文件、每条命令精确结果、人工验收、Checklist、文档同步、否定扫描、未验证项、风险和清理结果。

完成条件满足后更新 `docs/Context-Index.md`：F01 从 `not_implemented` 改为 `implemented_unarchived`，工作包仍留在 `docs/work/`。
