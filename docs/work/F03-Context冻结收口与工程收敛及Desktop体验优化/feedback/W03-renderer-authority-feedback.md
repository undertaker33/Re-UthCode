# W03 Renderer Authority Feedback

## 状态

T03 已完成本轮 Renderer helper/lifecycle 迁移与行为测试拆分。未执行 Git commit、push、PR、merge、rebase、tag 或 release；未触碰既有 `.workbuddy/` 与 `临时目录/`。

## 实际改动

- 将纯文本与状态归一化迁移到 `desktop/src/renderer/text-normalization.ts`、`state-normalization.ts`，将 Session/runtime projection 迁移到 `state-session.ts`。这些 helper 只计算并返回值，不持有 store、reducer、持久状态或外部副作用。
- `desktop/src/renderer/state.ts` 保留唯一 `RendererState`/reducer 与 AgentEvent→state 写入路径；现有真实公共入口仍从 `state.ts` 暴露，helper 实现各只有一份，没有新增第二 reducer 或兼容双轨。
- 新增 `desktop/src/renderer/useRuntimeLifecycle.ts`，由 hook 统一拥有 mounted/generation、runtime owner、operation tail、stale guard、AbortController、terminal convergence 与 pending turn boundary。`App.tsx` 只调用 hook，不再保留同职责 refs/执行链。
- 将 `renderer.test.tsx` 中对应的 state/reducer、Session projection、lifecycle race 与 rebootstrap helper 合同迁移到 `renderer-state.test.ts`、`renderer-session.test.tsx`、`renderer-runtime-lifecycle.test.tsx`；保留原文件中的 Settings、Markdown、layout 及其 UI 合同。本轮未实施 Settings、Markdown 或布局功能。
- `desktop/package.json` 的正式 `test` 脚本已纳入三个新增测试文件。

## 关键机制与边界

事件仍统一进入 `state.ts` reducer；Session runtime snapshot 仅是 Interface projection，并按 project/session identity 隔离。生命周期操作先经 hook 的 generation/owner 检查，再串行进入 operation tail；终态事件与 status convergence 使用同一 turn identity，卸载或 owner 切换会使旧操作失效。App 没有复制这些 refs 或第二条生命周期实现。

## 精确验证

- `conda run --no-capture-output -n re-uthcode npm --prefix desktop run typecheck`：exit code `0`，`tsc --noEmit` 通过。
- `conda run --no-capture-output -n re-uthcode npm --prefix desktop test`：exit code `0`；`166` tests，`166` passed，`0` failed，`0` cancelled，`0` skipped；Webpack Main entry 编译通过；耗时约 `54.79s`。
- 否定扫描：`desktop/src/renderer` 未新增 `Redux`、`Zustand`、`EventBus`、`RuntimeManager`、`createStore` 或第二 reducer；runtime owner refs 仅存在于 `useRuntimeLifecycle.ts`，App 无重复 owner/generation/tail/latest-turn/pending/poll refs。
- `git diff --check`：exit code `0`，无 whitespace error（仅保留既有换行格式提示）。

## Checklist

仅勾选 T03 的六项，均已写回 `F03-Context冻结收口与工程收敛及Desktop体验优化-checklist.md`；T04～T09 未修改、未勾选。

## 偏差、未完成项与风险

- 本轮没有执行 `npm run package`、`npm run make`、CDP/visual acceptance、真实 Provider 或干净 Windows 环境验证；这些不属于 T03 本轮已验证项，不能描述为通过。
- 当前仓库仍有用户已有未跟踪 `.workbuddy/` 与 `临时目录/`；本轮没有清理、改写或纳入变更。
- 新增 helper 的稳定导出仅保留现有真实调用方所需的 `state.ts` 公共入口；没有为历史 API、旧实现或未来能力增加 facade、Manager 或第二套状态链。

## 收口复核

T03 的实现、迁移测试、正式 npm 脚本、typecheck、完整 npm test、否定扫描与 `git diff --check` 均已完成；冻结 Spec、Tasks、Prompt 文字未修改。

## 返工第 1 轮（Reviewer REQUEST CHANGES）

### Finding 与修复

- 修复 owner 路径的 terminal convergence：`App.tsx` 统一通过 `publishTerminalStatus` dispatch `status_loaded`，`closeActiveTurn` 调用 `startTerminalStatusConvergence(..., true, publishTerminalStatus)`。因此 terminal event 在导航 owner 存在时被阻止启动 event-side poll，随后 owner poll 进入 idle，替代 `project.open` 或 `runtime.shutdown` 失败也不会留下 `terminalStatusPending`/Composer 锁死。新增失败替代导航回归，覆盖 `turn.cancel → terminal event → owner status.get idle → project.open failure`。
- 删除 App 的整组 lifecycle re-export；lifecycle 测试直接从 `useRuntimeLifecycle` 引入 `rebootstrapProject`。删除 `state.ts` 对 normalize/text/session helper 与无消费者 reducer alias 的 facade 导出；测试改从真实 helper owner 引入，保留 `sessionLabel` 这一真实 Sidebar 公共入口。
- 新增 `renderer-state-ui.test.tsx`，恢复 fresh Run 后 `permissionMode: unknown` 在 Composer 中显示 unavailable 的 UI 断言，并纳入正式 `npm test`。

### 返工验证

- `conda run --no-capture-output -n re-uthcode npx tsx --test tests/renderer-runtime-lifecycle.test.tsx`：`10 passed`，`0 failed`，exit code `0`；包含新增失败导航回归。
- `conda run --no-capture-output -n re-uthcode npm --prefix desktop run typecheck`：exit code `0`。
- `conda run --no-capture-output -n re-uthcode npm --prefix desktop test`：`168 passed`，`0 failed`，`0 cancelled`，`0 skipped`，exit code `0`；Webpack Main entry 编译通过；耗时 `55.42s`。
- 返工后未执行 Git 写操作；冻结 Spec、Tasks、Prompt 未修改，Checklist 仍仅勾选 T03 六项。
