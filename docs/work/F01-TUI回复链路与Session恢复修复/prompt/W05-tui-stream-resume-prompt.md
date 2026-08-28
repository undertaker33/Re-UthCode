# W05 TUI 流式时序与 Resume Hydrate 实施提示词

请在 `D:\project\Re-UthCode` 严格串行实施 F01 的 T07 -> T08；独占 TUI 写集合，不得实施最终接入或文档验收。

## 开工前必须读取

1. `AGENTS.md`、基础路由、工作包规则、拍板边界、欠账清单
2. F01 原始需求、Spec、Tasks、Checklist 和本 Prompt
3. W01～W04 Feedback，确认 T02/T03/T04/T06 公共合同已完成
4. A03/A04 current context 和完整 `docs/context/TUI/README.md`
5. T02、T05、T09 的 TUI/Session 历史证据
6. T07/T08 Tasks 定位的全部 TUI 源码与 tests

## 已确认决策

- Reasoning 保持实时流式可见，使用独立语义 bar 色；正式回复使用现有绿色 bar。
- 永久 scrollback 最终必须 reasoning 在前、formal final 一次；assistant delta 仍需实时 preview。
- `/resume` 完整回放 user、steering、reasoning、formal assistant、safe Tool terminal。
- 长 replay 有界分批并让出事件循环；TUI 不读取 Session/History internals。
- 冷启动 lazy Session，先 resume 不产生 throwaway Session。

## 修改范围

- 仅 Tasks T07/T08 列出的 `interfaces/tui/` 和 TUI/session command integration tests。
- 首次实施创建 `feedback/W05-tui-stream-resume-feedback.md`；返工追加。
- 只勾选 T07/T08 已验证 Checklist。

禁止修改 Core/Provider/History/Application replay DTO/process tool/Tool redaction、其它 Feedback、当前事实文档或 Git。

## 实施约束

1. 先建立精确事件时间线测试，再替换 renderer 状态；不靠延时扩大掩盖竞态。
2. Reasoning safe blocks 可实时永久提交；assistant delta 实时临时预览，权威完成后永久提交一次。
3. 使用显式 kind/semantic color，不解析角色字符串猜颜色。
4. 多 reasoning segment、late reasoning、tool boundary、correction、Markdown fence 和 resize 均不能要求回写 scrollback。
5. replay 复用正式显示入口但不注入 live stream，不伪造 AgentEvent/Turn。
6. 每个 replay batch synchronized，batch 间异步 yield；不加分页、虚拟列表或 UI history store。
7. 无 active Session 时 shutdown、help/status/picker 和首条 input failure 保持安全。

## 测试与验收

执行 Checklist T07/T08 全部项、架构测试与 `git diff --check`。测试必须测量 terminal 前 preview 更新次数、per-kind 永久输出次数、bar 色值、event-loop yield、Provider/Turn/Transcript count 和 Session ID 集合。

## Feedback 要求

说明 chronological projection、preview/permanent 策略、颜色语义、append-only 保证、replay batching、lazy input 接线、修改文件、测试结果、Checklist、偏差和未验证的真实 Windows Terminal 项。
