# W04 进程输出与 Tool 活动实施提示词

请在 `D:\project\Re-UthCode` 严格串行实施 F01 的 T05 -> T06；不得修改 TUI 或其它任务。

## 开工前必须读取

1. `AGENTS.md`、基础路由、工作包规则、拍板边界和欠账清单
2. F01 原始需求、Spec、Tasks、Checklist 和本 Prompt
3. A01 current context、`docs/context/TUI/README.md` 的 Tool 展示合同
4. T04 Tool System、T05 Agent Loop 原始需求/Spec/Tasks，尤其 W02-R1～R4 与 W04 Feedback
5. 提交 `f32ad439aaf200adc98d177540ffdf6344668254` 中的 Tool redactor 设计
6. T05/T06 Tasks 定位的源码和测试

## 已确认决策

- 保留原设计：摘要不显示 API key、token、环境变量值、配置秘密或 ToolResult。
- 所有非空 ambient 环境值按 token 边界脱敏，仅 `0/1` 例外；不得因当前样例可读性而放宽。
- 修复 Tool 名重复和多 Tool FIFO，started 保持 transient、finished 保持 permanent。
- Windows 解码使用真实平台/shell 编码事实做有限 fallback，不引入猜测框架。

## 修改范围

- `integrations/tools/process_tools.py`、`application/tools.py`，必要的 UI-neutral Tool event/run 投影和定向 tests。
- 首次实施创建 `feedback/W04-process-tool-activity-feedback.md`；返工追加。
- 只勾选 T05/T06 已验证 Checklist。

禁止修改 Context/Provider/History/Session/TUI、Secret 配置边界、其它 Feedback、治理当前事实文档或 Git。

## 实施约束

1. 先补 CP936/OEM 中文与 Tool 名重复/FIFO 的失败测试。
2. 解码优先 UTF-8 strict，Windows fallback 必须来自当前执行 shell 可解释的系统编码；最终才 replacement。
3. 不调用全局 `chcp` 改变用户环境，不增加第三方 encoding detector。
4. Tool 名和 command summary 只能有一个展示 owner；不改变 ToolCall/ToolResult DTO。
5. 继续隐藏 Write/Edit/Grep/unknown/custom/raw ToolResult 内容。
6. 对全部 constructed secrets 和 `q7z/qz/q` 做 started/finished 事件级断言。

## 测试与验收

执行 Checklist T05/T06 的全部命令、架构测试与 `git diff --check`。在 Windows 使用真实中文文件名执行一次正式 process tool probe，清理探针目录并记录结果。

## Feedback 要求

说明编码选择顺序、Windows 证据、Tool 展示所有权、原脱敏设计如何保留、多 Tool FIFO、修改文件、测试结果、Checklist、偏差和风险。
