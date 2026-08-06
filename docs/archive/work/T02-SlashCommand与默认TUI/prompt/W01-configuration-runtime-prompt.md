# W01 Configuration Runtime Worker Prompt

你是 Re:UthCode 的 Configuration Runtime Worker。只有当用户明确要求你执行本文件时，才表示授权你在当前仓库中严格串行完成 T02 的 Task 1—Task 4。不得实施后续 Task。

## 工作目录与权威资料

仓库根目录：`D:\project\Re-UthCode`

实施前必须完整读取：

1. `AGENTS.md` 及其引入的 `SRe-AGENTS.md`；
2. `docs/work/README.md`；
3. `docs/work/T02-SlashCommand与默认TUI/T02-SlashCommand与默认TUI.md`；
4. 同目录的 `-spec.md`、`-tasks.md`、`-checklist.md`；
5. T01 工作包与当前 `src/uthcode/application`、`src/uthcode/integrations/providers`、相关测试。

原始需求、Spec、Tasks、Checklist 与项目规则共同构成冻结边界。发现冲突、缺失、必须改 Core Provider 契约、无法保证项目配置安全或模型切换原子性时，停止相关范围，在 Feedback 记录并交由用户决定；不得自行修改冻结文件。

## 授权范围与顺序

只按以下顺序实施：

1. Task 1：更新阶段约束与入口依赖；
2. Task 2：建立 Application 有效配置模型；
3. Task 3：实现配置发现、合并、安全与写回；
4. Task 4：扩展 Application Runtime。

前一 Task 的全部验收通过并勾选后才能进入下一 Task。不得实施 Task 5—Task 12，不得提前创建 Command、CLI、TUI 或未来能力模块。允许修改和删除的文件以 Tasks 对应条目为准。尊重工作区用户改动，尤其不得覆盖 `AGENTS.md` 中用户新增的 UTH 禁用说明。

## 环境、依赖与参考

- 所有 Python、安装、测试命令使用 `conda run -n re-uthcode ...`；不得使用系统 Python。
- 依赖必须写入 `pyproject.toml`，只声明工作包确认的 Textual、TOMLKit 和实际测试依赖；执行 editable install 与 `pip check`。
- 默认测试全程离线，不读取真实 API Key，不运行 live 测试。
- FirstCoder 只核对冻结 Commit 的 MIT 许可证，本 Worker 不迁移 TUI 代码。
- 不修改 `D:\project\UthCode`、`D:\project\MewCode` 或外部仓库。

## 实施约束

- 配置文件模型与 Effective Config 分离：TOMLKit 类型只能在 `integrations/config`，Application 只接收 UthCode 自有不可变模型。
- 用户配置是唯一可信 Provider 来源。项目配置出现 Provider 表、端点、秘密来源、Key 或等价重定向字段必须硬失败，不得忽略或降级。
- 不加载 `.env`；API Key 真实值只由既有 Provider Factory 根据环境变量名称读取。
- 首次用户配置模板必须原子创建、无可用秘密、创建后停止启动且不构造 Provider。
- Git 项目配置从根到 cwd 递归；非 Git 只读 cwd；物理路径在加载前规范化、解析链接、Windows 大小写归一并去重。
- 用户 model 写回只修改顶层选择，必须保留注释、表顺序和其他内容，不写项目配置。
- Generation Handle 每次拥有独立 Cancellation Token；`stream_generation` 复用 Handle；Application 不建立全局活动请求。
- 模型切换严格按验证、候选 Provider 构造、用户配置原子写回、内存状态替换执行。失败时 Provider、current model 和文件都不变。
- Provider 构造仍只通过既有 Integration Factory；Application 用例不得出现 Provider 名称分支。
- 不兼容 T01 临时单 Provider 配置公共接口；直接替换并删除旧入口，不保留 Adapter、Facade、别名或双轨逻辑。
- 不修改 Core Provider 请求、事件、错误、取消或 Provider Port；不引入 Session、Run、Turn、Agent Loop、Tool、Permission、Context、Skill 或 MCP。
- 优先写能证明行为的测试；不得删除、放宽或绕过断言制造通过。
- 不执行 Git commit、push、PR、合并或工作包归档。

## 验收与 Checklist

对 Task 1—Task 4 逐项执行：阅读约束、检查工作区、最小实现、运行该 Task Checklist 每条命令和场景、记录证据。只有真实通过后才可把对应 `- [ ]` 改为 `- [x]`；Checklist 文字、顺序和编号不得修改。失败项保留未勾选并继续修复，停止条件除外。

本组结束时至少重新执行：

```powershell
conda run -n re-uthcode python -m pip check
conda run -n re-uthcode pytest -q tests/test_configuration.py tests/test_application.py tests/test_application_runtime.py tests/test_provider_factory.py tests/test_provider_contract.py
conda run -n re-uthcode python -m compileall -q src tests
git diff --check
git status --short
```

并确认原 T01 离线 Provider 回归未退化、没有网络请求、秘密或意外产物。

## Feedback 与交付

首次执行时创建：

`docs/work/T02-SlashCommand与默认TUI/feedback/W01-configuration-runtime-feedback.md`

按 `docs/work/README.md` 记录实际实现、关键机制、设计理由、文件改动、测试结果、Checklist 状态、偏差、风险和遗留清理。返工只在原文件末尾追加新章节，不覆盖旧事实。

最终回复应说明 Task 1—Task 4 各自结果、文件变更、验证命令与结果、已勾选/未勾选项、依赖与秘密审查，以及任何阻塞；明确未实施 Task 5—Task 12，未执行 Git 写入或归档。只有全部验收真实通过才能宣告本 Worker 完成。
