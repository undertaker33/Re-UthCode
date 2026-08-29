# W01 用户配置 Bootstrap 实施提示词

请在 `D:\project\Re-UthCode` 完整实施 T10 的 T01，只完成用户配置 GUI 闭环，不得实施 T02 之后内容。

## 开工前必须读取

1. `AGENTS.md`
2. `docs/README.md`、`docs/Context-Index.md`
3. `docs/rules/WorkPackageRules.md`、`docs/rules/UserDecisionBoundary.md`
4. `docs/OutstandingDebtList.md`
5. `docs/work/T10-DesktopGUI与TUI全量能力迁移/T10-DesktopGUI与TUI全量能力迁移.md`
6. 同目录 Spec、Tasks、Checklist
7. `docs/context/A04-Orchestration/Orchestration-Context.md`、`docs/user-manual/configuration.md`
8. Tasks T01 定位的配置源码与测试

## 已确认决策与代码事实

- GUI 只管理当前 user config 字段，不建通用 Settings/schema/TOML editor。
- 安全视图必须在 `create_application` 失败前可用，不得经由要求完整有效配置的 `EffectiveConfig` 读取 key。
- Provider API Key 只返回 configured bool；无新 key 时保留原 TOML literal/env 表达，有新 key 时一次性替换并不回显。
- `full_access` 不能作为 user default，project config 不能持有 Provider/凭据/等价重定向字段。
- user TOML 字段 `provider` 与 Application DTO 内部命名要显式翻译，Integration 表结构不穿透公共边界。

## 修改范围

- 只修改 Tasks T01 列出的 Application/config Integration 与 tests。
- 首次实施创建 `feedback/W01-user-config-bootstrap-feedback.md`；返工只在同文件末尾追加章节。
- 只勾选 T01 已由精确命令验证的 Checklist，不得改其文字/顺序。

禁止创建 Desktop Bridge/Electron/Renderer，禁止修改 TUI/Core/Provider 语义，禁止 Git 写操作或归档。

## 实施与验证

1. 使用 `re-uthcode` Conda 环境，先为安全读取、key 保留/替换、引用校验、原子性和 secret-safe 写失败测试。
2. 优先修改 `configuration.py`/`bootstrap.py`/`writer.py`；`loader.py` 只在复用 current-schema parse/validation 确有需要时最小修改。
3. 不建常驻 Configuration Manager、schema server、未知字段 passthrough 或兼容层。
4. 至少执行 Checklist T01 命令、`tests/test_architecture_boundaries.py`、`git diff --check`。

## Feedback 要求

Feedback 必须说明安全读/写调用流、未配置/无效 TOML 边界、API Key 保留与脱敏、原子写入、修改文件、精确测试结果、Checklist 证据、偏差/风险与遗留负担清理。不得将 Desktop Bridge 或 GUI 写成已完成。
