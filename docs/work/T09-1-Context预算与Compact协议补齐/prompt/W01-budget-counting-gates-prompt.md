# W01 Budget / Counting / Dual Gates Worker Prompt

## 任务范围与顺序

只执行Task 1“模型窗口、计数能力与双 Gate 预算契约”。完成Feedback后停止，不实施Transcript/Timeline、L1-L5或命令接入。

## 必须读取

`AGENTS.md`、`docs/README.md`、`docs/Context-Index.md`、`docs/rules/WorkPackageRules.md`、本工作包Taskbook/Spec/Tasks/Checklist、A01/A03 Context、Task 1源码与测试，以及Taskbook第8节外部一手资料。使用Conda环境`re-uthcode`。

必须逐一读取：`application/configuration.py`、`integrations/config/loader.py`、`integrations/config/template.py`、`core/context.py`、`core/provider.py`、`integrations/providers/anthropic.py`、`application/bootstrap.py`、相关`__init__.py`，以及`test_configuration.py`、`test_config_contract.py`、现有Context/Provider contract tests。

首次派发后工作包冻结：不得改写需求、Spec、Tasks、Prompt或Checklist文字；只勾选已满足复选框并创建/追加Feedback。

## 冻结决策

- D1：L4/L5未来复用当前主Provider/model；本Worker不实现compaction。
- D2：未来B′无持久Compact FSM。
- D3：Auto Gate负责proactive pressure，Hard Gate独占发送许可；`E=min(C,reliable ceiling)`；`R` adaptive + absolute cap，初始内部default为`clamp(ceil(E*0.08),2048,32768)`，不是统一90%。
- final request projection必须包含input count、requested output reserve和count uncertainty；Provider count仍是estimate。

## 修改范围

仅Tasks Task 1列出的文件、必要exports和两个新增测试。不得修改OpenAI adapters伪造metadata；不得修改`core/agent.py`。

## 必须交付

正整数`context_window`配置；C/E；Provider/local count source；集中uncertainty policy；Auto/Hard结果；25K/128K/258K/1M；Anthropic SDK capability转换；删除固定258K唯一invariant。

## 禁止

不创建model catalog UI、Context Manager、Timeline、Compaction、Memory、Runtime recovery、后台任务、用户headroom配置系统或Git写入。

## 验证与Feedback

逐项执行Task 1 Checklist和architecture tests；真实网络不是CI条件。创建`feedback/W01-budget-counting-gates-feedback.md`，记录contract、默认policy、SDK边界、文件、精确测试、Checklist、差异、风险与cleanup。触及冻结产品/安全/架构边界时停止相关范围。
