# W01 用户配置 Bootstrap Feedback

## 范围与结果

本 Worker 只实施 T01 用户配置 GUI 闭环，没有创建 Desktop Bridge、Electron、Renderer，也没有修改 TUI、Core 或 Provider 语义。Application 现在提供可在 `create_application` 之前调用的 `read_user_configuration` 与 `write_user_configuration`；两者只处理当前 user config 的 root、Provider、Model 字段和可持久化的默认权限。

## 实际调用流与安全边界

- 读取路径由 Application bootstrap 解析用户目录，调用 Integration 的 TOML 解析投影，再转换为 `UserConfigurationView`。缺失文件会生成现有空模板；TOML 可解析但语义无效时仍返回当前字段供编辑；语法错误只返回稳定的 path/field 错误，不改原文件。
- 读取投影只包含当前 Provider/Model 字段与 `api_key_configured`。literal、`env:` 表达式、解析后的 `SecretValue`、未知字段和 project config 不进入 Application DTO 或 `to_dict`。
- 写入请求是冻结的 Application DTO。root `None` 表示保留，Provider/Model 空 mapping 表示删除该 section；Provider 的 `api_key` 在跨过 Application 到 Integration writer 前才短暂 reveal，未提供或显式 `None` 保留原 literal/env 表达，空字符串清除，新值单次替换且返回 fresh safe view。
- Integration writer 先解析/校验 current schema、Provider/Model 引用、default model、default permission 和 Provider 支持的 reasoning effort，再使用同目录临时文件、flush/fsync、`os.replace` 原子替换。候选无效或替换失败时原文件不变；未知字段不会被静默透传。
- 写入成功后重新读取安全视图；有效首次写入已验证可被 `load_effective_config` 加载并交给 `create_application` 构造。`full_access` 仍不可写入 user default，project config 的凭据约束保持原路径。

## 修改文件

- `src/uthcode/application/configuration.py`：新增安全读 DTO、写请求冻结/脱敏投影。
- `src/uthcode/application/bootstrap.py`、`src/uthcode/application/__init__.py`：新增配置读写 Application 出口，并保留 Integration 组合边界。
- `src/uthcode/integrations/config/loader.py`、`writer.py`、`__init__.py`：新增安全 user 投影、无 project 的 current-schema 校验和 TOMLKit 原子写入；保留原有 `/model`、`/permission` 写回入口。
- `tests/test_configuration.py`：先新增安全读取、无效 TOML、key 保留/替换、引用/full_access、删除、原子失败、首次写入回载/构造和未知字段回归测试。

## 精确验证

| 命令 | 结果 |
| --- | --- |
| `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_configuration.py tests/test_config_contract.py tests/test_config_loader_integration.py -q` | 75 passed in 6.78s |
| `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q` | 23 passed in 4.89s |
| `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_application.py tests/test_application_runtime.py tests/test_application_runs.py tests/test_cli.py tests/test_command_dispatcher.py -q` | 94 passed in 24.32s |
| `git diff --check` | exit code 0；仅有 Git 关于工作区 LF/CRLF 的提示，无 whitespace error |
| `python C:\Users\93445\.codex\skills\uth-utf8-guard\scripts\check_utf8_docs.py docs/work/T10-DesktopGUI与TUI全量能力迁移/T10-DesktopGUI与TUI全量能力迁移-checklist.md`（写入前） | 1 file passed UTF-8 guard |

T01 Checklist 的 7 项均已在上述定向测试、架构测试和原子写回证据下勾选；T02 及之后 Checklist 未修改。密钥安全覆盖 DTO/`repr`/`to_dict`、稳定错误、`SecretValue` 序列化和工具摘要路径；本 T01 配置调用流本身不产生日志或运行 snapshot，也未把配置值写入这些出口。

## 偏差、风险与遗留负担

- 未发现任务书冲突或需要用户拍板的范围/安全决策。
- 未执行 Desktop、Windows Installer、Renderer 或 T02+ 端到端验证，这些属于后续 Worker 范围，不在本 Feedback 中宣称完成。
- 配置 writer 明确只接受当前 schema；未知字段和无效引用会失败，不提供 schema server、常驻 Configuration Manager、未知字段 passthrough 或旧 API 兼容层。
- 未新增可清理的构建产物、临时文件或依赖；未执行任何 `git add`、`commit`、`push`、`merge`、`rebase`、`tag`、`release` 或归档操作。

UTF-8 guard:
- files checked: `docs/work/T10-DesktopGUI与TUI全量能力迁移/T10-DesktopGUI与TUI全量能力迁移-checklist.md`（写入前、写入后）、`docs/work/T10-DesktopGUI与TUI全量能力迁移/feedback/W01-user-config-bootstrap-feedback.md`（写入后）
- result: passed
- repaired encoding issues: none

## 补充验证

在完成上述定向验证后执行仓库全量回归：

`conda run --no-capture-output -n re-uthcode python -m pytest -q` → **1318 passed, 3 skipped in 180.81s (0:03:00)**。

## 补充修订与复验

最终审查时将 Integration writer 的 `api_key = None` 也收敛为“未提供新 key，保留既有表达式”，与 Application 写请求一致；空字符串仍是显式清除。修订后重新执行：

- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_configuration.py tests/test_config_contract.py tests/test_config_loader_integration.py -q` → **75 passed in 5.75s**。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q` → **23 passed in 4.89s**。
- `git diff --check` → **exit code 0**；仅 LF/CRLF 提示，无 whitespace error。

该修订未改变 Checklist 验收文字或范围；无新增未验证项。

## 返工第 1 轮

### 原因

Reviewer 指出两项 P2：current-schema 候选写入不应因既有 `env:NAME` 在当前环境缺失而失败；同时 T01 对 env 保留、Provider/Model 增删改和删除边界的测试证据不足。

### 实际修改

- `validate_user_config_mapping` 新增 `resolve_secrets` 开关，默认值保持 `True`，因此正常 `load_config_data`/`load_effective_config` 仍解析 literal 与 `env:` 环境秘密。
- writer 校验候选时使用 `resolve_secrets=False`：校验 key 类型、`env:NAME` 的环境变量名形状和非 fake Provider 的 key 存在性，不读取环境变量，也不把候选 key 放入校验结果；原子写入仍保留原 TOML 文本。Application/API Key replace 边界未改变。
- 新增 env 变量存在与缺失两种保留测试；缺失时写入成功但后续正式 `load_effective_config` 仍按既有语义报告缺失，存在时正式加载解析为 `SecretValue`。
- 新增有效 Provider/Model 增加、修改及未引用 Provider/Model 删除测试；新增删除默认 Model 失败且原文件不变、无效 Provider kind/Model provider reference 失败且原文件不变测试。已有 literal 保留、replace、引用删除、`full_access` 拒绝测试继续保留。

### 精确重测

- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_configuration.py tests/test_config_contract.py tests/test_config_loader_integration.py -q` → **80 passed in 4.50s**。
- `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py -q` → **23 passed in 4.94s**。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests` → **exit code 0**。
- `conda run --no-capture-output -n re-uthcode python -m pytest -q` 首次复验出现 1 个既有 W06 TUI 异步 picker 用例失败；单独重跑该用例为 **1 passed in 1.96s**，未修改 TUI。随后第二次全量复验为 **1323 passed, 3 skipped in 231.86s (0:03:51)**。
- `git diff --check` → **exit code 0**；仅 LF/CRLF 提示，无 whitespace error。
- `python C:\Users\93445\.codex\skills\uth-utf8-guard\scripts\check_utf8_docs.py docs/work/T10-DesktopGUI与TUI全量能力迁移/feedback/W01-user-config-bootstrap-feedback.md docs/work/T10-DesktopGUI与TUI全量能力迁移/T10-DesktopGUI与TUI全量能力迁移-checklist.md` → **2 files passed UTF-8 guard**。

### Checklist 与范围复核

T01 原已勾选的 7 项保持不变；本轮补充证据覆盖其中的 env/literal 保留、增删改、默认 Model 删除失败和正式加载秘密解析。未修改 Checklist 文字、结构、编号或 T02+ 项；未实施任何 T02+ 范围，也未执行 Git 写操作或工作包归档。
