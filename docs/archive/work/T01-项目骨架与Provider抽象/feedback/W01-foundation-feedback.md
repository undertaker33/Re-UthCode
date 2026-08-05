# W01 Foundation Worker Feedback

## 1. 完成结论

W01 已按 Task 1 → Task 4 的顺序建立可安装工程、Provider Core 契约、Headless Application + Fake Provider，以及 Pydantic AI Direct 共用桥接层。Task 1—Task 4 的 25 条 Checklist 均已由执行 Worker 标记完成；本次文档整理重新验证后，四个测试文件共 19 项测试通过。

当前实现已形成 `application → core` 与 `integrations → core` 的基础依赖边界，没有引入 Interface、CLI、Agent Loop、真实厂商协议模块或其他后置能力。但依赖版本声明存在一项与 Spec 不一致的问题，详见“偏差与风险”；在修正前不应把 W01 视为完全满足全部文档约束。

## 2. 实际实现与关键机制

### Task 1：可安装项目骨架

- 使用 Python 3.12 的 src-layout 与 Hatchling 构建，根包只公开 `0.1.0` 版本信息，导入时不加载 Provider 或发起网络请求。
- 建立项目 README、`.gitignore` 和仅列秘密变量名的 `.env.example`；生产与开发依赖统一由 `pyproject.toml` 声明。
- Task 1 阶段没有提前创建未来职责目录；`core/`、`application/`、`integrations/` 是后续 Task 2—Task 4 加入真实实现时创建的。

### Task 2：Provider Core 契约

- `core/provider.py` 集中定义 UthCode 自有的请求、消息 Part、Native Item、工具、响应、流事件、用量、错误、取消和 `ProviderPort`。
- JSON 容器在进入契约时被递归校验并冻结；SDK 对象、Pydantic Model、集合及其他非 JSON 值会被拒绝。
- Native Item 携带 Provider 身份与顺序，只允许同身份 Provider 恢复；Core 不依赖 Pydantic AI 或厂商 SDK。
- `CancellationToken` 支持幂等取消和多个等待者，作为 UthCode 显式取消语义，不替代 Python Task 取消。

### Task 3：Headless Application 与 Fake Provider

- `UthCodeApplication` 只接收 `ProviderPort`，逐项转发流事件，并拒绝无完成终态、重复终态和终态后继续产出的非法流。
- `FakeProvider` 可脚本化事件、延迟和错误，记录请求且不建立网络连接，用于覆盖文本、Tool Call、用量、错误和取消路径。
- Application 不导入 Integration，也不根据 Provider 名称分支；当前没有 CLI、stdin 或界面依赖。

### Task 4：Pydantic AI Direct 共用桥接

- `PydanticAIProvider` 通过 Direct Model API 转换 UthCode 请求、工具 Schema、流事件、用量、完成原因与异常。
- Provider details 被转换为 JSON-safe Native Item；共用层按 Provider 身份筛选续轮数据，不向 Core 暴露第三方对象。
- 显式取消会结束流并退出异步上下文；原生 `asyncio.CancelledError` 保持原语义。
- 共用桥接层没有加入 Anthropic、OpenAI Responses 或 Chat Completions 的协议专有模块和构造分支。

## 3. 文件改动

新增工程文件：

- `.env.example`
- `.gitignore`
- `README.md`
- `pyproject.toml`
- `src/uthcode/__init__.py`
- `src/uthcode/core/__init__.py`
- `src/uthcode/core/provider.py`
- `src/uthcode/application/__init__.py`
- `src/uthcode/application/generation.py`
- `src/uthcode/integrations/__init__.py`
- `src/uthcode/integrations/providers/__init__.py`
- `src/uthcode/integrations/providers/fake.py`
- `src/uthcode/integrations/providers/pydantic_ai.py`
- `tests/test_package.py`
- `tests/test_provider_contract.py`
- `tests/test_application.py`
- `tests/test_architecture_boundaries.py`

工作包变更：

- `T01-项目骨架与Provider抽象-checklist.md`：仅将 Task 1—Task 4 的 25 条既有复选框改为完成状态。

## 4. 验证结果

本次文档整理在 `re-uthcode` 环境重新取得以下结果：

- `conda run -n re-uthcode python --version`：`Python 3.12.13`。
- `conda run -n re-uthcode python -m pip install -e . --group dev`：editable install 成功。
- `conda run -n re-uthcode python -m pip check`：`No broken requirements found.`。
- `conda run -n re-uthcode python -c "import uthcode; print(uthcode.__version__)"`：输出 `0.1.0`。
- 设置 UTF-8 输出后执行 `conda run --no-capture-output -n re-uthcode pytest -q tests/test_package.py tests/test_provider_contract.py tests/test_application.py tests/test_architecture_boundaries.py`：`19 passed, 1 warning`。
- `conda run -n re-uthcode python -m compileall -q src tests`：退出码 0。
- 搜索 Core 中的 `pydantic|openai|anthropic|langgraph|langchain`：0 条。
- 禁止依赖搜索只命中架构测试自身的禁止字符串断言，源码实现未命中。

pytest 警告来自仓库 `.pytest_cache` 路径无写权限，不影响本轮测试结果，但会妨碍 pytest 正常写入缓存，应在后续返工中确认该目录的权限或所有权。普通 `conda run` 捕获包含 `U+FFFD` 的测试输出时还会触发 Conda 的 GBK 编码异常；本次通过同一环境的 `--no-capture-output` 和 UTF-8 输出变量取得真实测试结果。

## 5. Checklist 状态

- Task 1：6/6 已勾选。
- Task 2：6/6 已勾选。
- Task 3：7/7 已勾选。
- Task 4：6/6 已勾选。
- 合计：25/25 已勾选。

Task 1 的“尚未出现职责目录”属于该 Task 完成时的阶段性验收；Task 2—Task 4 按计划加入真实职责文件后，最终目录状态不再满足该阶段描述。这不代表应删除后续实现，复审时应以 Task 1 当时的验证证据为准。

## 6. 与任务书不同的实际情况

`pyproject.toml` 当前声明 `pydantic-ai-slim[anthropic,openai]>=2.15,<3`，而 Spec 要求依赖限定在已验证的 2.22 次版本范围。环境中实际安装的是 `2.22.0`，所以本轮测试通过，但声明允许未来解析到未经验证的 2.23 及更高版本。这是实际依赖约束偏差，不能仅以当前安装版本正确代替修复。

## 7. 未完成项、风险与遗留负担

- 需要在后续返工中把 Pydantic AI 版本范围修正为仅允许 2.22 次版本，并重新执行安装、`pip check` 和四文件回归测试。
- 需要确认或修复 `.pytest_cache` 无写权限问题，避免持续产生测试警告。
- W01 未实现 Task 5—Task 11；真实厂商协议、配置与 Factory、正式组合入口和真实端点验证仍按后续 Worker 推进。
- 当前搜索未发现 LangGraph、LangChain、旧 API 兼容 Adapter、未来能力目录或 Core 第三方依赖；Provider 协议专有逻辑尚未提前进入共用桥接层。
- 本轮未执行提交、推送、PR、合并或工作包归档。

## 返工第 1 轮：依赖约束与 pytest 缓存权限

### 返工原因

首轮 Feedback 已记录两项未收口问题：`pydantic-ai-slim` 的声明范围仍允许解析到未经验证的 2.23 及更高版本；pytest 对仓库 `.pytest_cache` 的写入受到权限限制并产生警告。本轮严格限定为修正这两项问题，不进入 W02，也不实施 Task 5—Task 11。

### 实际修改

- 仅修改 `pyproject.toml` 中的 Pydantic AI 依赖范围：`pydantic-ai-slim[anthropic,openai]>=2.22,<2.23`。未升级其他依赖，未添加锁文件、兼容层或新依赖。
- 只读确认 `D:\project\Re-UthCode\.pytest_cache` 是仓库内精确的 pytest 生成目录：其中仅有 `.gitignore`、`CACHEDIR.TAG`、pytest `README.md` 和 `v/cache` 下的缓存文件；`.gitignore` 已通过 `.pytest_cache/` 忽略该目录，Git 状态没有该目录记录，也未发现用户文件。
- 该目录及已有缓存子项原先只有 `OWNER RIGHTS`、SYSTEM 和 Administrators ACL，没有当前执行身份的显式权限项。未删除目录；仅对该精确路径及其子项为当前身份授予 `Modify`（`(OI)(CI)M`）权限，使缓存文件可创建、修改和删除。
- 使用 Conda 环境中的临时文件完成创建、修改、读取和删除验证，结果为 `create/modify/delete: passed`，临时验证文件已清理。

### 依赖最终状态

- 最终声明范围：`pydantic-ai-slim[anthropic,openai]>=2.22,<2.23`，因此不会解析到 2.23 或更高版本。
- 安装后实际版本：`pydantic-ai-slim 2.22.0`，属于 2.22.x。
- 首次直接执行指定 editable install 命令时，pip 因默认 user-site `C:\Users\93445\AppData\Roaming\Python` 不可写而报告 `WinError 5`；未修改该用户目录。随后仅设置临时 `PYTHONUSERBASE`，用同一安装命令在 `re-uthcode` 环境中成功完成 editable install。

### 重新执行的命令及结果

- `conda run -n re-uthcode python -m pip install -e . --group dev`：在临时可写 user-site 下成功。
- `conda run -n re-uthcode python -m pip check`：`No broken requirements found.`。
- `conda run -n re-uthcode python -c "import pydantic_ai; import importlib.metadata as m; print(m.version('pydantic-ai-slim'))"`：`2.22.0`。
- 设置 `PYTHONUTF8=1`、`PYTHONIOENCODING=utf-8` 后执行四个 W01 测试文件：`19 passed in 1.04s`，不再出现 `.pytest_cache` 无写权限警告。
- `conda run -n re-uthcode python -m compileall -q src tests`：退出码 0。
- 再次执行 `conda run -n re-uthcode python -m pip check`：`No broken requirements found.`。
- `git diff --check`：退出码 0，无空白错误；Git 仅报告既有文档的 LF/CRLF 转换提示。
- `git status --short`：仅看到本工作包及 W01 首轮已产生的源码、测试、配置和 Prompt/Feedback 工作区变更；未发现真实秘密、缓存、构建产物或工作包外意外文件。

### 警告、未完成项与 W02 前置条件

- 本轮目标中的 pytest 缓存权限警告已消除；测试、编译和依赖检查均通过。
- 除 Git 的既有 LF/CRLF 转换提示外，没有遗留的测试警告或验证失败。没有未完成的 W01 返工项。
- W01 Task 1—Task 4 的 25 条 Checklist 仍保持已验证的完成状态；本轮未修改 Checklist、原始需求、Spec、Tasks 或 Prompt。
- W01 已满足进入 W02 的技术前置条件，但本轮没有实施 W02、Task 5—Task 11，也没有调用真实模型服务。进入 W02 仍须由用户通过对应 Prompt 显式派发。

## 返工第 2 轮：契约不可变性、流终态与边界验收收口

### 返工原因

复审发现首轮测试未能证明三项关键语义：JSON 容器仍可借助 `dict`/`list` 基类方法绕过保护；Provider Event 没有保留事件类型身份的统一 JSON 恢复入口；Application 在确认 Provider EOF 前已经向调用方发布成功终态。此外，网络阻断、共用桥接层错误矩阵和资源所有权规则缺少可观测证据。

### 实际修改

- 将 `JsonPayload` 与内部 JSON 数组改为不继承可变内建容器的只读 `Mapping`/`Sequence`，分别使用只读映射和私有元组保存递归冻结值。新增测试直接调用 `dict.__setitem__`、`list.__setitem__` 以及底层只读映射写入，均无法改变契约数据。
- 为当前七种 Provider Event 增加稳定类型标记，并提供统一的 `provider_event_from_dict`、`provider_event_from_json` 恢复入口；测试逐类完成类型身份与数据的 JSON round-trip，并拒绝未知事件类型。
- Application 暂存 `GenerationCompleted`，只有 Provider 迭代器确认 EOF 后才向调用方发布；无终态、重复终态和终态后事件都会失败，且测试确认调用方未观察到伪成功终态。退出时同时关闭 Provider 异步迭代器。
- 新增全局离线网络守卫，在测试执行阶段阻断 `socket` 与 `asyncio` 的外连入口；显式探针确认网络构造立即失败，Fake 与 Application 测试仍通过。
- 通过 `PydanticAIProvider.stream` 正式路径分别注入认证、限流、网络和非法响应失败，确认映射为对应 UthCode 错误。映射错误不复制测试秘密，也不保留第三方异常的 `cause` 或 `context`。
- 扩充取消验收：除证明流生成器执行关闭清理外，还以进入/退出计数证明桥接层不会接管或关闭调用方持有的外部 Model/Client 生命周期；桥接层只负责其创建的单次流上下文。

### 修改文件

- `src/uthcode/core/provider.py`
- `src/uthcode/core/__init__.py`
- `src/uthcode/application/generation.py`
- `src/uthcode/integrations/providers/pydantic_ai.py`
- `tests/conftest.py`
- `tests/test_provider_contract.py`
- `tests/test_application.py`
- `tests/test_architecture_boundaries.py`
- `docs/work/T01-项目骨架与Provider抽象/feedback/W01-foundation-feedback.md`

### 重新验证结果

- `conda run --no-capture-output -n re-uthcode python -m pip install --no-deps -e .`：editable install 成功；依赖已由前轮解析且本轮未新增或调整依赖。
- `conda run -n re-uthcode python -m pip check`：`No broken requirements found.`。
- 包版本为 `uthcode 0.1.0`，实际 `pydantic-ai-slim` 版本为 `2.22.0`。
- 四个 W01 测试文件：`25 passed in 1.63s`，无警告。
- `conda run -n re-uthcode python -m compileall -q src tests`：退出码 0。
- Core 第三方名称搜索与源码禁止依赖搜索均为 0 条；Task 5—Task 7 的三个协议源码及测试文件均不存在。
- 秘密扫描只命中错误泄漏回归测试中的合成哨兵值 `sk-secret-must-not-escape`，未发现真实秘密；未发现缓存、构建产物或工作包外意外文件。
- `git diff --check`：退出码 0；仅有既有文档的 Git LF/CRLF 转换提示。

### 收口结论

W01 Task 1—Task 4 的 25 条 Checklist 现均有与文字要求相符的自动化或静态证据，原有勾选保持有效。本轮没有修改冻结的原始需求、Spec、Tasks、Prompt 或 Checklist，没有实现 Task 5—Task 11，也没有执行 Git 提交、推送、PR、合并或归档。当前没有已知的 W01 遗留失败项，已满足由用户显式派发 W02 的技术前置条件。
