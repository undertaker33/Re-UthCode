# W03 Renderer Authority 实施提示词

请在 `D:\project\Re-UthCode` 严格实施 F03 的 T03。W02 status contract 稳定后，迁出 Renderer 纯 helper 和 App runtime lifecycle owner，保持唯一 reducer 与既有 Session/事件语义。

## 开工前必须读取

1. AGENTS、docs 路由、WorkPackageRules、UserDecisionBoundary。
2. F03 全部冻结文件、本 Prompt、W01/W02 Feedback。
3. `docs/context/GUI/GUI-Context.md`、A03、A04。
4. T03 源码、`desktop/package.json` 与相关 tests。

## 已确认决策与范围

- `state.ts` 是唯一 state/reducer authority；新 helper 只做纯 normalize/text/session 计算。
- `useRuntimeLifecycle` 接管而不是复制 App refs，且只有 App 一个生产调用方。
- per-Session cache 是 Interface projection，不持久化、不替代 Application/Session truth。
- 不建设 Redux/Zustand/EventBus/Manager/第二 store；不实施 Settings、Markdown 或布局功能。

## 实施与验证

1. 先迁出纯 helper并建立独立行为测试，再迁移 runtime lifecycle ownership。
2. 保持 AgentEvent→同一 reducer、Session A/B background、navigation、busy/stale/terminal convergence。
3. 把新 tests 加入正式 `npm test`，运行 typecheck、npm test、Checklist T03 扫描与 `git diff --check`。
4. 首次创建 `feedback/W03-renderer-authority-feedback.md`，只勾选 T03。

## Feedback 要求

说明 authority 前后位置、迁移而非复制的证据、测试拆分、精确命令结果、Checklist、偏差、风险与遗留负担；返工只追加。
