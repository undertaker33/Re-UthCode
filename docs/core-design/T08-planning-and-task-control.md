# T08：在同一运行时中加入规划

简单任务可以直接执行，复杂任务则常常需要先形成计划。关键问题是：规划是否要另建一套工作流引擎？UthCode 的答案是否定的。Plan、Todo 和 Steering 都进入原有 Agent Loop，并使用同一份 Core 状态。

## Plan Mode 改变的是行动空间

用户执行 `/plan` 后，下一次 Turn 进入 Plan Mode。模型仍然读取上下文、进行推理并调用工具，但普通写工具会被 Runtime Hook 阻止，只读探索仍可继续。

模型可以直接给出一份普通规划回答，也可以调用 `ProposePlan` 提交结构化计划。后一种情况会创建 `PlanState` 并触发 typed Plan Review：

```text
PLAN
  → 只读探索
  → ProposePlan
  → 用户审阅
     ├─ 批准：切换到 DEFAULT，继续同一 Turn
     └─ 修订：保持 PLAN，把意见送回模型
```

## Todo 是执行状态，不是展示列表

`TodoWrite` 会替换当前任务列表并更新 `TaskState`。当仍有未完成事项时，模型试图结束 Turn 会被 completion hook 阻止，并收到一次反馈继续工作。

因此，Todo 不只是界面中的进度文本，而是会影响 Runtime 是否接受“任务已经完成”的控制事实。

## Steering 让用户修正正在进行的任务

运行期间的新普通输入会作为同一 Turn 的 Steering，形成真实的 User Message 并进入下一次模型决策。它不会创建另一个隐蔽会话，也不会直接篡改模型正在生成的响应。

如果当前正在等待权限审批、用户回答或计划审阅，输入必须先完成对应的 typed interaction，避免一句普通文本被误解为控制响应。

## 回到完整闭环

至此，UthCode 的 Agent Core 可以概括为：

```text
配置确定运行环境
  → Context 描述任务与能力
  → Model 选择回答或 Tool Call
  → Tool 在权限约束下作用于项目
  → Result、用户控制与任务状态回到 Core
  → Agent Loop 决定继续、暂停或完成
```

规划没有脱离这条闭环，权限与交互也没有成为旁路。这正是显式 Runtime 的价值：所有可观察行为最终都回到同一套状态与执行语义中。
