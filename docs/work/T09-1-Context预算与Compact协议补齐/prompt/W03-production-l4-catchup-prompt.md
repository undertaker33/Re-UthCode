# W03 Worker Prompt：生产 L4 与 bounded catch-up

你负责执行 T09-1 的 T03。T01、T02 必须已完成并有 Feedback。只做 T03，不执行 T04～T08，不做 Git 写入或归档。

## 开始前必须完整读取

- `AGENTS.md`、文档路由、工作包规则、T09-1 四份主文档与 W01/W02 Feedback。
- 当前 `core/compaction.py`、`core/context.py`、`application/context.py`、`application/generation.py`、`application/sessions.py`、Provider contracts、Timeline store 和相关测试。

## 目标与冻结语义

实现正式 tool-free L4 和 bounded catch-up：active Turn 复用冻结主 Provider/model/分维 limits；idle manual 用当前选择。Compact request 自身必须 Hard-gated，不递归 Auto compact，不引入独立 model 或跨 Provider fallback。

结果必须 one Fine entry per covered complete Turn，refs/coverage/summary 校验通过后才写入；派生 records 后 checkpoint-last。一个 orchestration 可做多个有界 epoch，每次提交后 rebuild 并重做 Pressure/Hard Gate。attempt、coverage、previous estimate、epoch、breaker、cancellation 都只在当前调用栈，不建立持久 FSM/Job/pointer。

## 实施要求

- retained target 应产生可测 headroom；只选择完整 safe epoch。
- no-progress、repeated failure、no-safe-epoch、parse/coverage failure 和 cancellation 都有限停止且不产生伪提交。
- Auto unresolved + Hard-safe 可继续 ordinary call 并记录原因；Hard-unsafe Provider call count 为 0。
- 删除旧 `summarizer_unavailable` 阶段路径；不实现 L5/HistoryRead/命令接入。

## 验证与反馈

执行 Checklist T03 命令、T01/T02 关键回归、架构测试和持久 FSM 扫描。写入：

`docs/work/T09-1-Context预算与Compact协议补齐/feedback/W03-production-l4-catchup-feedback.md`

只勾选 T03 已证明条目；记录 epoch 上限/no-progress 证据、调用计数、精确测试结果、风险与未验证项。
