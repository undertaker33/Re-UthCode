# AGENTS.md

本项目没有启用uth-governance，不要走uth场景路由，除非用户显式指定

## 以下引入作为AGENTS.md重构期间临时规则

@SRe-AGENTS.md

## 工作包

拿到需求文件后，必须读取并遵守：

@docs/work/README.md

## 开发环境

使用 conda activate re-uthcode环境

## 非兼容性原则

Re:UthCode 不兼容旧项目及自身此前实现中的旧类、旧 API、旧数据结构和旧行为，除非当前需求明确要求保留。

出现以下内容时，视为验收不通过：

- 为兼容旧实现而增加的适配器、别名、包装层、废弃入口或双轨逻辑；
- 已被新实现替代但仍然保留的旧代码、旧测试和不可达分支；
- 职责重复的模块、协议、数据结构或调用链；
- 项目现有能力或成熟依赖已经能够满足需求，却再次实现同等能力；
- 仅为了兼容 Re:UthCode 之前开发内容而污染当前设计。

发现遗留设计与当前需求冲突时，应直接替换并删除旧实现，不得默认增加兼容层。

## 目录结构

项目顶层结构固定为：

```text
src/uthcode/
├── core/           # 无界面的 Agent Core
├── application/    # 对外交互命令、用例和事件出口
├── integrations/   # Provider、存储、进程等外部系统适配
└── interfaces/     # TUI、CLI、Web、Desktop、IDE 等交互适配器
```

目录职责：

- `core/` 保存 Agent 的核心运行语义和领域能力，包括 Provider 抽象、Prompt、Tool、Agent Loop、Permission 及其权威内部模型；不得依赖具体 UI、第三方 SDK、文件存储或进程实现。
- `application/` 是 Agent Core 的统一调用入口，负责接收 Command、调用 Core、输出统一 Event；所有交互界面只能通过该层使用 Agent Core。
- `integrations/` 保存第三方 SDK 和外部系统的具体实现，例如 Provider SDK、文件存储和进程执行；第三方类型必须在此转换为 UthCode 自有模型。
- `interfaces/` 保存具体交互形态。TUI 只是第一个适配器，后续 CLI、Web、桌面客户端和 IDE 插件均在此独立接入。

依赖方向固定为：

```text
interfaces → application → core
                  ↓
             integrations
```

`core` 不得反向依赖 `application`、`integrations` 或 `interfaces`。

各顶层目录内部只根据当前 Day 的实际职责创建文件和子目录。不得提前创建后续 Day 的空目录、占位协议或伪实现，也不得按照 Day 编号组织源码。已完成任务确定的目录和公共边界，后续不得无理由重排。

## 参考来源

### 设计思路

- D:\project\UthCode（[undertaker33/UthCode](https://github.com/undertaker33/UthCode)）
- D:\project\MewCode
- https://github.com/openai/codex
- https://github.com/shareAI-lab/learn-claude-code
- https://github.com/anthropics/claude-code

### TUI

- https://github.com/KomorGiaoGiao/FirstCoder

