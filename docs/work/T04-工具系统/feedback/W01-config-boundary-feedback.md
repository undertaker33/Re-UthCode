# W01 config-boundary Feedback

## 1. 完成结论

已完成 T04 Task 1，未开始 Task 2—Task 9，未执行 Git 写操作，也未修改归档工作包。

配置数据流现在收敛为：

```text
Application LaunchOptions
    → Integration load_config_data()
    → LoadedConfigData（原始 canonical mapping）
    → Application EffectiveConfig.from_mapping()
```

Integration 不再导入 Application 或 Interface，也不再构造或公开 `EffectiveConfig`。

## 2. 实际实现

- 新增 `integrations/config/data.py`，定义 `LoadedConfigSource` 与 `LoadedConfigData`。返回值会深拷贝并冻结 providers、models 和嵌套值；模型字段已转换为 Application 既有的 `provider_profile_id`、`remote_model_id` 等 canonical 名称。
- `integrations/config/loader.py` 保留原有配置发现、TOML 解析、字段校验、项目安全限制、合并优先级、模型选择和模板初始化行为，入口改为 `load_config_data()`。
- `application/bootstrap.py` 将 `LaunchOptions` 的 primitive 参数传给 raw loader，再通过唯一 `EffectiveConfig.from_mapping()` 完成 Application 配置转换；Integration 的 path、field 和 template path 证据会转换到 Application 错误类型。
- `integrations/config/__init__.py` 移除 `load_effective_config`，改为收窄后的 raw loader/data 导出。
- 架构测试现在扫描整个 `src/uthcode/integrations`，永久禁止 `uthcode.application` 与 `uthcode.interfaces` 导入；未来目录检查不再错误禁止 T04 正式 `tools` 目录。
- 配置产品测试只从 `uthcode.application` 加载最终配置；Integration raw loader、发现去重和 writer 细节测试集中到新增的 `test_config_loader_integration.py`。

## 3. 文件变更

新增：

- `src/uthcode/integrations/config/data.py`
- `tests/test_config_loader_integration.py`
- `docs/work/T04-工具系统/feedback/W01-config-boundary-feedback.md`

修改：

- `src/uthcode/integrations/config/loader.py`
- `src/uthcode/integrations/config/__init__.py`
- `src/uthcode/application/bootstrap.py`
- `tests/test_configuration.py`
- `tests/test_architecture_boundaries.py`
- `tests/test_package.py`
- `docs/work/T04-工具系统/T04-工具系统-checklist.md`：仅勾选 Task 1 既有五项。

未修改：T04 后续 Tool、Provider、CLI、TUI、配置 TOML、配置模型、writer/template 实现及归档文档。

## 4. 验证结果

- 基线：配置 `38 passed`；架构 `9 passed`。
- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_config_loader_integration.py tests/test_configuration.py`：`42 passed`。
- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_architecture_boundaries.py tests/test_package.py`：`13 passed`。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests`：通过。
- `conda run --no-capture-output -n re-uthcode python -m pip check`：通过。
- `rg -n "uthcode\.application|uthcode\.interfaces" src/uthcode/integrations`：无匹配。
- `rg -n "load_effective_config" src/uthcode/integrations/config`：无匹配。
- `git diff --check`：通过。

UTF-8 guard:

- files checked: `docs/work/T04-工具系统/T04-工具系统-checklist.md`、`docs/work/T04-工具系统/feedback/W01-config-boundary-feedback.md`
- result: 通过 UTF-8 解码、常见乱码标记检查和 Markdown fence parity 检查
- repaired encoding issues: 无

## 5. Checklist、偏差与遗留清理

- Task 1：5/5 已勾选。
- Task 2—Task 9：保持未勾选、未实施。
- 没有改变配置格式、发现规则、优先级、秘密来源、模型选择、初始化模板或用户默认模型写回行为；未读取真实 API Key 或发起网络请求。
- 没有新增 Adapter、Facade、Shim、别名、旧入口、第二套有效配置模型或工具实现；Integration raw data 只作为 bootstrap 的一次性转换输入。
- 现有工作区中用户已经存在的归档移动变更未被整理或覆盖。

## 返工第 1 轮

### 1. 返工原因

审查发现 `tests/test_architecture_boundaries.py` 的 Integration 依赖门禁只读取 `ImportFrom.module`，无法识别 AST 中 `level=3、module="application"` 的 `from ...application import EffectiveConfig`，因此可能漏报 Integration 到 Application 或 Interfaces 的相对反向依赖。

### 2. 实际修改

- 仅修改 `tests/test_architecture_boundaries.py`，未修改产品源码。
- 新增基于扫描文件包路径的 Python 模块解析：结合 `ImportFrom.level`、`ImportFrom.module` 和源文件所在包路径，将合法相对导入解析为 `uthcode.*` 绝对模块；`__init__.py` 与普通模块文件分别按其 Python 包语义处理。
- `from . import name` 形式也解析出对应的包内子模块；解析超出 `uthcode` 包根的非法相对导入会显式报错，不以放宽门禁规避问题。
- Integration 反向依赖断言统一复用解析后的 AST 导入结果，继续拒绝 `uthcode.application`、`uthcode.interfaces` 及其子模块。
- 增加内存 AST 回归夹具，覆盖绝对 Application/Interfaces 导入、可解析到这两个模块的相对导入，以及合法的 Integration 内部相对导入；没有使用字符串 grep、扩大白名单或一律禁止相对导入。
- Checklist 未修改，Task 2—Task 9 未开始，未执行任何 Git 写操作。

### 3. 相对导入复现与回归测试

回归夹具以 `src/uthcode/integrations/config/_boundary_fixture.py` 作为包路径上下文，仅在内存中解析 AST，不创建辅助文件：

- `from ...application import EffectiveConfig` 解析为 `uthcode.application`，门禁断言失败。
- `from ...interfaces import UthCodeTUI` 解析为 `uthcode.interfaces`，门禁断言失败。
- `import uthcode.application`、`from uthcode.application import EffectiveConfig`、`import uthcode.interfaces`、`from uthcode.interfaces import UthCodeTUI` 均被门禁拒绝。
- `from .data import LoadedConfigData` 解析为 `uthcode.integrations.config.data`，通过门禁。
- `from ..providers import factory` 解析为 `uthcode.integrations.providers`，通过门禁。
- `from . import data` 解析为 `uthcode.integrations.config.data`，通过门禁。
- 当前整个 `src/uthcode/integrations` 的实际扫描继续通过同一门禁。

### 4. 返工验证结果

- `conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_architecture_boundaries.py tests/test_package.py`：`23 passed`。
- `conda run --no-capture-output -n re-uthcode python -m pytest -q tests/test_config_loader_integration.py tests/test_configuration.py`：`42 passed`。
- `conda run --no-capture-output -n re-uthcode python -m pytest -q`：`269 passed, 3 skipped`。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests`：通过。
- `conda run --no-capture-output -n re-uthcode python -m pip check`：通过，输出 `No broken requirements found.`。
- `conda run --no-capture-output -n re-uthcode git diff --check`：通过；仅有 Git 关于工作区 LF 在后续 Git 操作中可能转换为 CRLF 的提示，无 diff 错误。
