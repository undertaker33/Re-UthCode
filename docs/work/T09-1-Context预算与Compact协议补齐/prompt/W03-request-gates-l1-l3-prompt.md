# W03 Final Request / Dual Gates / L1-L3 Worker Prompt

## 任务范围与顺序

W01、W02完成后只执行Task 3“最终请求组装、Auto/Hard Gate 与确定性 L1-L3”。完成Feedback后停止，不接真实L4/L5 model call。

## 必须读取

全局规则、WorkPackageRules、本工作包四文件、A01/A03/A04 Context、T09 Core Design、W01/W02 Feedback、Task 3源码/测试和Tool Result externalization contract。使用`re-uthcode`。

必须逐一读取：`core/context.py`、`core/prompt.py`、`application/context.py`、`application/generation.py`、`tests/test_context_compiler.py`、`tests/test_context_budget_gate.py`、`tests/test_tool_result_persistence.py`、`tests/test_application_runs.py`。

冻结文档不得改写；只勾选Task 3现有项并创建/追加Feedback。

## 冻结决策

- D1：后续compact复用当前主模型。
- D2：后续B′无持久FSM。
- D3：Auto Gate与Hard Gate分离；L1-L3后仍高于Auto Gate即使低于E也返回L4-required；已清除pressure且Hard safe不做L4。
- count针对最终结构化request，含output reserve与uncertainty；Hard unsafe零Provider call。
- ContextCompiler是唯一model-view builder；AgentLoop已支持awaitable preparer，不重复改造。

## 修改范围与交付

仅Task 3列出文件。交付Transcript/Timeline logical view、final assembly/count、dual-gate、L1-L3 plan/apply/rebuild/recount、typed failure和安全diagnostics。

## 禁止

不实现L4/L5 Provider call、Memory/relevance、第二Compiler、Session bytes、Command/TUI、后台agent、`core/agent.py`改造或Git写入。

## 验证与Feedback

执行Task 3 Checklist，明确provider call count、259K→257K仍pressure、pressure cleared与impossible required context证据。创建`feedback/W03-request-gates-l1-l3-feedback.md`。
