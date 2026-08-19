# W04 Worker Prompt：L5 Timeline Aging 与 HistoryRead

你负责执行 T09-1 的 T04。T01～T03 必须完成并有 Feedback。只做 T04，不执行 T05～T08，不做 Git 写入或归档。

## 开始前必须完整读取

- `AGENTS.md`、文档路由、工作包规则、T09-1 四份主文档与 W01～W03 Feedback。
- 当前 compaction/context/session/tool registry、ToolResultRead、Transcript/Timeline store 及相关测试。

## 目标与冻结语义

实现 Fine Timeline 独立 L5 aging 与 current-Session HistoryRead。Fine budget 超限可在 ordinary request 低 pressure 时触发。L5 只选 old complete compact epoch，并按 opaque Transcript refs 读取 raw evidence；禁止 summary-of-summary。

成功 L5 先写 macro、最后 checkpoint；logical view supersede 旧 Fine coverage，但物理 Timeline 不删除。HistoryRead 只支持 active Session exact opaque ref + bounded page：不搜索、不跨 Session、不支持 semantic retrieval，输出不递归 externalize。

## 实施要求

- HistoryRead 与 ToolResultRead namespace、校验和授权边界分离。
- malformed/cross-session/invalid boundary/no-safe-epoch fail closed；不换模型、不递归 compact、不伪提交。
- Timeline record 仍只有三类；不做 GC、rotation、background job、Memory/retrieval index。
- 不接 manual lifecycle/commands/TUI。

## 验证与反馈

执行 Checklist T04 完整命令、T03 关键回归和架构测试。写入：

`docs/work/T09-1-Context预算与Compact协议补齐/feedback/W04-timeline-aging-history-read-feedback.md`

记录 raw-evidence 证据、no summary-of-summary、权限失败矩阵、精确测试统计、风险和未验证项；只勾选 T04。
