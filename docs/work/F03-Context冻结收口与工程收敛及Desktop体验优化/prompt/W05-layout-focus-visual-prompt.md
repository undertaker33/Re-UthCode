# W05 Layout、Focus 与 Visual 实施提示词

请在 `D:\project\Re-UthCode` 严格实施 F03 的 T05。W04 完成后实现面板拖拽、Focus Mode、Runtime 双 usage 与视觉层级，不并行修改共享 Desktop 文件。

## 开工前必须读取

1. AGENTS、docs 路由、WorkPackageRules、UserDecisionBoundary。
2. F03 冻结文件、本 Prompt、W02～W04 Feedback。
3. GUI 当前上下文、Desktop preferences/API、App/state/CSS/locale、visual/CDP runner/tests。

## 已确认决策与范围

- `sidebarWidth`/`runtimePanelWidth` 是 durable UI preference；Pointer move 不高频写 IPC。
- separator 支持 Pointer/keyboard/ARIA；viewport/zoom clamp 必须保持 Chat 可用，narrow 继续 overlay。
- `focusMode` 只在 Renderer transient state，不能持久化或改变 `panelMode`。
- RuntimePanel 只显示 Application DTO，不重算 Context/usage。
- 保持 show-more、catalog order、overlay focus/escape、IME、focus-visible、主题、语言和 reduced-motion。
- 不引入 UI/state/animation framework、第二 layout store 或 skeleton 占位。

## 实施与验证

按 preference schema/migration → reducer/layout wiring → separators/Focus → RuntimePanel → tokens/motion → CDP/fixture 顺序实施。运行 Checklist T05 的 typecheck、npm test、responsive/visual/CDP 与 diff 检查。首次创建 `feedback/W05-layout-focus-visual-feedback.md`，只勾选 T05。

## Feedback 要求

说明 width 生命周期、clamp 与稳定写边界、Focus 恢复、双 usage 展示、视觉 token、精确测试/截图/报告路径、Checklist、偏差和风险；返工只追加。
