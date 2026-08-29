# W05 Windows Runtime 打包与 Installer 实施提示词

请在 `D:\project\Re-UthCode` 完整实施 T10 的 T08，构建 PyInstaller onedir Runtime 与 Squirrel.Windows Installer，不得实施 T09～T11 最终收口。

## 开工前必须读取

1. `AGENTS.md`、文档路由/工作包/用户决策/欠账规则
2. T10 原始需求、Spec、Tasks、Checklist 和本 Prompt
3. W01～W04 Feedback 和当前 Desktop/Bridge tests
4. `pyproject.toml`、`src/uthcode/prompt_assets/`、Tasks T08 定位文件
5. PyInstaller stable onedir/spec/runtime 文档，Forge extraResource/Squirrel.Windows/code signing 文档，Electron security/fuses 文档

## 已确认决策

- 只验收 Windows 11 x64；PyInstaller onedir；Forge `extraResource`；Squirrel.Windows `Setup.exe`。
- Bridge 依赖 stdio JSONL，因此 Runtime 必须保留 console subsystem，禁用 PyInstaller `--noconsole/--windowed`；窗口由 Electron `windowsHide` 隐藏。
- production 只从 `process.resourcesPath` 启动完整 onedir，不回退 system Python。
- 未签名安装包只作为 dev/RC 验收，不宣称公开发行就绪。

## 修改范围

- 只修改 Tasks T08 列出的 spec/build script/Forge/package/Runtime path/build dependency 与 tests。
- 首次实施创建 `feedback/W05-windows-packaging-feedback.md`；返工只追加；只勾选 T08 Checklist。
- 禁止自动更新、Service/Tray/Daemon、签名平台、构建输入复制/完整性链、Git 写/归档。

## 实施与验证

1. 将 PyInstaller 放入 `pyproject.toml` 真实 dev/build dependency，在 Windows 本机构建，明确收集 `prompt_assets/coding_agent.md`。
2. spawn dist Runtime 执行 ready/status/shutdown，验证 JSONL、stderr、asset、退出码和无 system Python fallback。
3. Forge 复制整个 Runtime onedir 到 ASAR 外 resources，package/make 后再运行 packaged smoke。
4. Main 早期收口 Squirrel 特殊参数，检查 Fuses、CSP/navigation/IPC 打包状态，验证无重复/orphan child。
5. 尽可能执行无 Python Windows 安装/启动/卸载；无可用干净环境时必须精确标记未验证，不写通过。

## Feedback 要求

Feedback 记录实际 Python/PyInstaller/Node/npm/Electron/Forge 版本，spec/asset/stdio 选择，package resources 结构，Squirrel lifecycle/Fuses，精确命令与结果，Installer 环境，未验证项，Checklist 和产物清理。
