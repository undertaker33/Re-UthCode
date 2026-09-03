# W04 Settings 与 Markdown 实施提示词

请在 `D:\project\Re-UthCode` 严格实施 F03 的 T04。W03 完成后，串行完成 Settings 单 Modal、安全 Markdown、通用窄 clipboard 与聊天滚动入口。

## 开工前必须读取

1. AGENTS、docs 路由、WorkPackageRules、UserDecisionBoundary。
2. F03 冻结文件、本 Prompt、W03 Feedback。
3. GUI 当前上下文和 T04 列出的 Renderer/Electron/tests/CDP fixture。

## 已确认决策与范围

- Provider→Model 共享一个 modal root/focus/transaction；Back 返回 Provider，Cancel 回滚，Save 走既有 Configuration。
- API Key 明文只在显式 reveal 后存在于 editor-local lifecycle，不能进入 reducer/preferences/log/snapshot。
- 保持现有安全 Markdown 子集；Code Fence 只增加 language label 与原文 Copy，不折叠、不引入框架。
- `copyText` 由 main process clipboard 实现并保留 sender/frame/origin 校验；Renderer 不直接访问 Electron。
- 用户离底后 streaming 不抢回，必须有显式新消息/回到底部入口。
- 不创建 generic Modal、Secret store、Markdown framework 或第二 timeline state。

## 实施与验证

按 settings draft/modal → safe Markdown → copyText → scroll → locale/CSS/CDP fixture 顺序实施。运行 Checklist T04 的 typecheck、正式 npm test、Settings CDP acceptance、安全/秘密扫描和 diff 检查。首次创建 `feedback/W04-settings-markdown-feedback.md`，只勾选 T04。

## Feedback 要求

说明 modal/focus transaction、secret lifecycle、Markdown safety、clipboard boundary、scroll 状态、修改文件与精确测试/CDP 结果；记录偏差、未完成项、风险和清理，返工只追加。
