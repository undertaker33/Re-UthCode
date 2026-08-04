# W01 Configuration Runtime Worker Feedback

## 1. 完成结论

已严格按 Task 1 → Task 4 顺序完成本 Worker 授权范围。Task 1—Task 4 的 Checklist 条目均已取得实际验证证据并勾选；Task 5—Task 12 未实施且保持未勾选。

本轮没有修改冻结的原始需求、Spec、Tasks 或 Prompt，没有修改 Core Provider 契约，没有读取真实 API Key，没有运行 live 测试，没有执行 Git 提交、推送、PR、合并或工作包归档。

## 2. 实际实现

### Task 1：阶段约束与入口依赖

- `pyproject.toml` 新增 Textual `>=8.2,<9`、TOMLKit `>=0.15,<0.16`，注册唯一 `uthcode` console script 目标 `uthcode.interfaces.cli:main`。
- `SRe-AGENTS.md` 仅调整 T02 直接冲突的 Slash Command、默认 Textual TUI、Interface 隔离、递归配置和项目安全边界条款；没有改动用户在 `AGENTS.md` 中新增的 UTH 禁用说明。
- 新增 `LICENSES/FirstCoder-MIT.txt`，保留完整 MIT 条款和 `Copyright (c) 2026 KomorGiaoGiao`。

### Task 2：Application 有效配置模型

- 新增 `application/configuration.py`，提供 `LaunchOptions`、`ConfigSource`、`ProviderProfile`、`ModelProfile`、`EffectiveConfig` 和 Application 自有 `ProviderKind`。
- Provider Profile ID、Model Ref 和远端 Model ID 是独立字段；模型引用、Provider 引用、Provider kind、输出 token 和温度均在模型构造时校验。
- Application 配置对象递归复制并冻结 mapping/list，配置来源使用不可变元组；对象字段不可重赋值，`repr` 不包含真实秘密。
- `EffectiveConfig.single_model(...)` 提供不依赖配置文件的 Headless 单模型构造入口。
- `application.__init__` 已移除 T01 `ProviderConfig` 公共导出，只公开新的配置模型、Application、Generation Handle 和配置加载/组合门面。

### Task 3：配置发现、合并、安全与写回

- 新增 `integrations/config/template.py`、`loader.py`、`writer.py` 和包出口。
- 用户配置不存在时，使用同目录临时文件和原子替换创建注释模板，抛出带绝对路径的初始化提示；加载层不构造 Provider、不读取秘密、不发起请求。
- Git 仓库支持 `.git` 目录和 worktree `.git` 文件，从根目录到 cwd 递归发现项目配置；非 Git 只读取 cwd 配置。路径在发现前解析物理路径并按平台规则去重。
- 项目层只允许模型选择和非秘密 Model Profile 字段，定义 Provider、kind、端点、秘密来源、Key 或等价凭据字段时硬失败，并报告路径和字段。
- 用户配置按用户 → 项目根 → 近 cwd → CLI model 覆盖合并；项目 Model Profile 可以引用用户 Provider。
- TOMLKit 只位于 Integration，通过同目录临时文件原子写回用户配置顶层 `model`，保留注释、表顺序和其他内容，不写项目配置；写入/替换失败会清理临时文件并保留原字节。

### Task 4：Application Runtime

- `GenerationHandle` 为每次请求创建独立取消状态，提供 `events()`、幂等 `cancel()` 和 `cancelled`；Application 不保存全局活动请求。
- `stream_generation()` 现在只作为正式 Handle 的便利流接口，继续在 Provider EOF 后才发布唯一完成终态，并拒绝无终态、重复终态和终态后事件。
- Application 提供 Model Catalog、当前 Model Ref、当前 Provider Profile、配置来源和安全的状态值。
- 模型切换严格执行“验证引用 → 构造候选 Provider → 写回用户顶层 model → 替换内存状态”；候选构造或写回失败时旧 Provider、当前 Model Ref 和用户文件均不变。
- `bootstrap.py` 以 `EffectiveConfig` 为唯一长期配置输入，Provider 仍只通过既有 Integration Factory 构造；测试可注入 Provider builder 和 model writer 验证回滚顺序。

## 3. 文件改动

新增：

- `LICENSES/FirstCoder-MIT.txt`
- `src/uthcode/application/configuration.py`
- `src/uthcode/integrations/config/__init__.py`
- `src/uthcode/integrations/config/template.py`
- `src/uthcode/integrations/config/loader.py`
- `src/uthcode/integrations/config/writer.py`
- `tests/test_configuration.py`
- `tests/test_application_runtime.py`
- 本 Feedback 文件

修改：

- `SRe-AGENTS.md`
- `pyproject.toml`
- `src/uthcode/application/__init__.py`
- `src/uthcode/application/bootstrap.py`
- `src/uthcode/application/generation.py`
- `tests/test_application.py`
- 三个 T01 协议测试中的 live Headless 构造，迁移到新的 `EffectiveConfig.single_model(...)` 入口，以保持完整 T01 回归可运行且不恢复旧 Application 配置导出。
- `docs/work/T02-SlashCommand与默认TUI/T02-SlashCommand与默认TUI-checklist.md`，仅将 Task 1—Task 4 既有复选框改为完成。

删除：无。

## 4. 验证结果

- `conda run -n re-uthcode python --version`：Python 3.12.13。
- editable install：成功；Textual 8.2.8、TOMLKit 0.15.1，均满足声明范围。
- `conda run -n re-uthcode python -m pip check`：`No broken requirements found.`。
- console script 检查：仅有 `uthcode.interfaces.cli:main` 一个目标；目标实现属于后续 Task 7，本 Worker 未创建 Interface/CLI。
- `conda run -n re-uthcode pytest -q tests/test_configuration.py`：27 passed。
- `conda run -n re-uthcode pytest -q tests/test_application.py tests/test_application_runtime.py tests/test_provider_factory.py tests/test_provider_contract.py`：32 passed。
- `conda run -n re-uthcode pytest -q`：102 passed, 3 skipped；live 测试保持 skipped。
- `conda run -n re-uthcode python -m compileall -q src tests`：通过。
- `git diff --check`：通过；仅有 Git 的 LF/CRLF 转换提示。
- `rg -n "tomlkit|textual|pydantic_ai|openai|anthropic" src/uthcode/application/configuration.py`：0 条。
- `rg -n "dotenv|\.env" src/uthcode/integrations/config src/uthcode/application`：0 条。
- Application generation Provider 名称分支扫描和后续运行时类型扫描：均 0 条。

## 5. Checklist 与范围状态

- Task 1：6/6 已勾选。
- Task 2：7/7 已勾选。
- Task 3：10/10 已勾选。
- Task 4：10/10 已勾选。
- Task 5—Task 12：未实施，全部保持未勾选。

## 6. 偏差、风险与遗留清理

- T01 协议 live 测试原先直接从 Application 导入已被替代的 `ProviderConfig`；只迁移其测试构造到新的 Effective Config 入口，未恢复兼容导出或双轨配置。
- `uthcode` console script 已声明但 CLI 目标尚未实现，这是 Task 7 的明确范围，不是本 Worker 的未完成项；当前不应在本 Worker 结束后运行该入口期待 TUI。
- 没有创建 `commands`、`interfaces`、TUI、Session、Run、Agent Loop、Tool、Permission、Context、Skill 或 MCP 模块。
- 配置 Integration 只保存环境变量名称，未加载真实秘密；测试未产生网络请求、Key、缓存或构建产物。工作区保留用户原有的 `AGENTS.md` 修改，不覆盖或整理。

## 7. 第一轮返工（2026-08-04）

### 7.1 返工原因

审查发现 W01 原实现仍有两类边界问题：`bootstrap.py` 通过 `inspect.signature` 同时兼容单参数 `ProviderConfig` builder 和双参数 Application builder；Application 配置模型还保留了多组没有独立业务语义的同义属性、参数和回退读取。另有 Checklist 的路径去重测试只明确覆盖了符号链接，没有覆盖相对路径和 Windows 大小写变体的最终来源结果。

### 7.2 实际修改与规范 API

- 删除 `_invoke_override()`、`inspect.Parameter`、签名探测和单参数 builder 分支。`create_application()` 的唯一注入协议是 `ProviderBuilder = (ProviderProfile, ModelProfile) -> ProviderPort`；既有 Integration `ProviderConfig` 只在私有 bootstrap 转换函数中生成，并继续交给唯一 `integrations.providers.factory.create_provider()`。
- Application 配置身份统一为：`ProviderProfile.provider_profile_id`、`ModelProfile.model_ref`、`ModelProfile.provider_profile_id`、`ModelProfile.remote_model_id`。`EffectiveConfig.model` 是冻结 TOML 顶层选择的唯一 Model Ref 入口；`LaunchOptions.model` 与 `load_effective_config(..., model=...)` 是唯一进程覆盖入口。
- 删除 `LaunchOptions.model_override`、`ConfigSource.name/location`、`ProviderProfile.profile_id/id`、`ModelProfile.provider/ref/model`、`EffectiveConfig.selected_model/selected_model_ref/config_sources`、`UthCodeApplication.config/models` 和 `ApplicationStatus.current_model_ref/config_sources`。`EffectiveConfig.from_mapping()` 只接受 `model/providers/models` 顶层字段和 Application 自有嵌套字段，不再接受旧字段或静默忽略未知字段。
- TOML 文件格式中冻结的 `provider` 和嵌套 `model` 仍只存在于 Integration loader 的外部解析层；loader 将其一次转换为上述 Application 类型，不把它们作为 Application 公共 API。

### 7.3 调用方与测试更新

- 更新 `tests/test_application.py`、`tests/test_application_runtime.py` 和三个协议 live 测试的 Headless 构造，全部改用 `EffectiveConfig.single_model(provider_profile_id=..., remote_model_id=...)`。
- 将原 `test_create_application_injection_can_observe_existing_provider_config` 改为双参数 Application Profile 注入测试，并新增单参数 builder 被拒绝的回归测试。
- `tests/test_configuration.py` 增加同义属性不存在、旧顶层/嵌套字段拒绝、唯一 `model` 覆盖参数和三类物理路径去重测试。
- README 中两个 Headless 示例同步到正式 `EffectiveConfig` API；未实现 CLI、TUI 或后续 Task 能力。

### 7.4 路径去重实际证据

- 符号链接：在 Git 根配置和 cwd 配置之间建立同一文件的符号链接，加载后的 `EffectiveConfig.sources` 只保留一次项目物理路径。
- 相对路径：在 Windows 当前环境以相对 `cwd` 和 `home` 参数让同一文件同时成为 user/project 候选，最终来源只有一个 user 路径。
- Windows 大小写变体：在当前 Windows 文件系统真实创建配置和 `.git`，使用交换大小写的真实路径参数加载，并以 `Path.samefile()` 验证最终 `sources` 只有一个物理文件；测试未 skip。

### 7.5 返工验证

- editable install：成功；Textual 8.2.8、TOMLKit 0.15.1。
- `pip check`：`No broken requirements found.`。
- 配置模型筛选：11 passed，21 deselected；配置全量：32 passed。
- Application/Runtime/Provider 回归：33 passed；架构边界：15 passed。
- 全量离线测试：108 passed，3 skipped；跳过项仍为显式 live 测试。
- `compileall`：通过；`git diff --check`：通过，仅有 LF/CRLF 转换提示。
- 静态检查确认：Application 配置别名扫描 0 条、bootstrap 签名探测 0 条、旧 Application `ProviderConfig` 调用 0 条、`.env` 加载 0 条、后续运行时类型 0 条；公开 Application 不导出 Integration `ProviderConfig`。Core Provider 文件无差异。
- UTF-8 Guard：README、Checklist 和本 Feedback 均通过 UTF-8 解码、乱码和 Markdown 围栏检查。

### 7.6 Checklist 与遗留风险

- Task 1：6/6；Task 2：7/7；Task 3：10/10；Task 4：10/10，合计 33/33 已勾选。
- Task 5—Task 12：0 项勾选，未创建 Command、CLI、TUI 或其他后续能力。
- `uthcode` console script 仍只是 Task 1 声明的后续入口，CLI 目标属于 Task 7，当前按范围未实现；README 仍保留 T01 的无 CLI/TUI 范围说明。
- live Provider 测试未运行，未读取真实 API Key，默认测试未联网。`AGENTS.md` 的既有用户修改保留；本轮未执行 Git commit、push、PR、合并或归档。

## 8. 第二轮返工（2026-08-04）

### 8.1 返工原因与用户决策

用户决定 T02 先收口，不实现 `temperature`；该能力延后到独立任务 T02-1。本批次只保留已经贯通到 Provider 请求链路的 `max_output_tokens`。原生 SDK 替换和更多模型请求参数的适配不属于本轮，也没有为了 `temperature` 修改 T01 的 ProviderConfig、Provider Factory、Pydantic AI 适配层或 Core Provider 契约。

### 8.2 删除的实现、配置入口与测试预期

- 删除 `ModelProfile.temperature` 字段及其数值校验逻辑。
- 删除 `EffectiveConfig.single_model()` 的 `temperature` 参数和构造传递。
- 从 Application Model Profile mapping 允许字段中删除 `temperature`；`EffectiveConfig.from_mapping()` 现在通过未知字段校验直接拒绝它。
- 从 Integration TOML Model Profile 允许字段中删除 `temperature`，并删除 loader 的读取、合并和转换；用户级与项目级 TOML 均不再静默忽略该字段。
- 检查并清除了模板、README 和有效配置字段中的 T02 `temperature` 声明。测试侧删除了“允许该字段进入 W01 配置链”的预期；本基线没有独立的合法 `temperature` 测试，新增了明确的拒绝回归测试。

规范命名和第一轮返工结果保持不变：Provider Profile ID 使用 `provider_profile_id`，Model Ref 使用 `model_ref`，Remote Model ID 使用 `remote_model_id`；Provider builder 仍只有 `(ProviderProfile, ModelProfile)` 这一种注入签名。

### 8.3 拒绝与保留的实际验证

- Application `ModelProfile` 不再具有 `temperature` 属性。
- `EffectiveConfig.from_mapping()` 传入 Model Profile 的 `temperature` 时，以不支持字段错误拒绝。
- 用户级 TOML 的 `models.<ref>.temperature` 以带配置文件绝对路径和字段名的 `ConfigurationError` 失败。
- 项目级 TOML 的 `models.<ref>.temperature` 同样以带项目文件绝对路径和字段名的 `ConfigurationError` 失败，未发生静默忽略。
- `max_output_tokens` 仍可分别从用户配置和项目覆盖进入 `EffectiveConfig`；测试验证用户值 `128` 和项目覆盖值 `256`。
- bootstrap 测试实际拦截唯一 Integration Factory，验证 Application 的 `max_output_tokens=321` 被转换为 Integration `ProviderConfig.max_output_tokens=321`。既有 Factory/Pydantic settings 映射保持不变，因此最终请求设置链路没有被本轮删除。

### 8.4 第一轮返工回归

- 单一 Provider builder 签名回归通过，单参数 builder 仍明确失败；未恢复签名探测、`_invoke_override()` 或双形态调用。
- Provider Profile ID、Model Ref、Remote Model ID 的单一规范命名和 Application 公开边界回归通过；Application 未公开 Integration `ProviderConfig`。
- 符号链接、相对路径和 Windows 大小写变体均在当前 Windows 环境真实验证，同一物理配置文件在最终来源中只出现一次；Windows 大小写测试未 skip。
- GenerationHandle、模型切换、候选 Provider 失败回滚、写回原子性和第一轮运行时测试均继续通过。

### 8.5 测试、编译、依赖与静态检查

- `conda run -n re-uthcode python -m pip install -e . --group dev`：成功；Textual 8.2.8、TOMLKit 0.15.1 满足声明范围。
- `conda run -n re-uthcode python -m pip check`：`No broken requirements found.`。
- `conda run -n re-uthcode pytest -q tests/test_configuration.py`：36 passed。
- `conda run -n re-uthcode pytest -q tests/test_application.py tests/test_application_runtime.py tests/test_provider_factory.py tests/test_provider_contract.py`：34 passed。
- `conda run -n re-uthcode pytest -q tests/test_architecture_boundaries.py`：15 passed。
- `conda run -n re-uthcode pytest -q`：113 passed，3 skipped；跳过项仍为显式 live Provider 测试。
- `conda run -n re-uthcode python -m compileall -q src tests`：通过。
- `git diff --check`：通过，仅报告已有的 LF/CRLF 转换提示；`git status --short` 未发现秘密、构建产物或新增后续模块。
- `rg -n "temperature" src tests README.md`：W01 Application 配置、Integration config loader、README 和有效配置模板均无该字段；测试中的命中仅用于“不支持字段”的属性、输入和拒绝断言。剩余源码命中仅为本轮明确保留的 T01 Core `GenerationRequest` 字段及其既有 Pydantic AI 适配映射，Core、ProviderConfig、Factory 和适配文件均无本轮差异。
- 静态核对确认：bootstrap 无 builder 签名探测或双形态调用；Application 无 Integration `ProviderConfig` 公共导出；没有新增 Adapter、Facade、alias、wrapper、旧入口、CLI、TUI、Command 或其他后续 Task 模块；默认测试未联网、未读取或输出真实秘密。
- UTF-8 Guard：README、`SRe-AGENTS.md`、Checklist 和本 Feedback 均通过 UTF-8、乱码和 Markdown 围栏检查。

### 8.6 Checklist 最终状态与尚存风险

- Task 1：6/6 已勾选。
- Task 2：7/7 已勾选。
- Task 3：10/10 已勾选。
- Task 4：10/10 已勾选。
- Task 5—Task 12：0 项勾选，未实施。
- `temperature` 已明确延后到 T02-1；因此当前配置链路不能通过 W01 配置设置它，这是有意的产品边界而非遗漏。
- live Provider 测试仍未运行，真实 SDK 请求的在线行为留待后续任务验证；当前离线测试、编译、依赖和边界验证均通过。
- 本轮未执行 Git commit、push、PR、合并或归档；`AGENTS.md` 既有用户修改保持不变。
