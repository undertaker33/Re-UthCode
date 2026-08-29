# W03 Electron Shell 与 Python Process 实施提示词

请在 `D:\project\Re-UthCode` 完整实施 T10 的 T03，只完成 Electron Main/Preload、Python child lifecycle 和 Desktop preferences，不得实施 T04 之后产品 UI。

## 开工前必须读取

1. `AGENTS.md`、文档路由/工作包/用户决策边界/欠账规则
2. T10 原始需求、Spec、Tasks、Checklist 和本 Prompt
3. W01、W02 Feedback 与已实现 Bridge tests
4. Electron 官方 Security、Process Model、Context Isolation、Sandbox、IPC、Forge Webpack Plugin 当前文档
5. Tasks T03 列出的 Desktop files/tests

## 已确认决策

- Electron 44.x stable、Forge 7.11.2 stable、Webpack Plugin、npm + lockfile、React/CSS；不用 Vite experimental 或 monorepo。
- BrowserWindow 使用 nodeIntegration false/contextIsolation true/sandbox true，限制 CSP/navigation/window/webview/IPC sender。
- Python child 使用 `spawn(shell:false, stdio: pipes, windowsHide:true)`，不用 shell wrapper，production 无 system Python fallback。
- Preload 逐方法暴露窄 API，不透传 raw ipcRenderer/event/Node object；Main 不拥有 Agent 语义。

## 修改范围

- 只修改 Tasks T03 的 Electron Main/Preload/process/preferences/tests 与最小 Renderer boot shell。
- 首次实施创建 `feedback/W03-electron-shell-process-feedback.md`；返工只追加；只勾选 T03 Checklist。
- 禁止预写 fake Project/Session/Chat/Interaction/Settings，禁止修改 Python Agent 语义、Git 写或归档。

## 实施与验证

1. 先以真实/fixture Bridge 写 child correlation、stderr、timeout/exit rejection、graceful shutdown/orphan 测试。
2. 对每个 IPC handler 校验 sender/frame/origin，folder/open path 只处理已登记项目。
3. preferences 只存 UI 元数据；注入假 key/session body 验证不持久。
4. 执行 `npm ci`、`npm ls`、typecheck、tests 和 `git diff --check`，精确结果入 Feedback。

## Feedback 要求

Feedback 说明 Electron 实际解析版本、security settings、preload API、spawn 参数、dev/production 路径、error/shutdown/reap、preference 范围、修改文件、测试结果、Checklist、未验证安全/打包项。
