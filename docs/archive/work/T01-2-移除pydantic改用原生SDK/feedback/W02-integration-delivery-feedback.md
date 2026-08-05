# W02 Integration Delivery Worker Feedback

## 执行范围

本轮由用户明确派发 `prompt/W02-integration-delivery-prompt.md`，严格按 Task 4 → Task 5 → Task 6 执行。W01 的三个原生 SDK Provider、共用辅助模块和协议测试作为已完成前置；W02 未修改 Core Provider 契约、Application API、配置模型、CLI/TUI 功能或三个 Provider 的协议实现。

正式调用链已收敛为：

```text
Headless / CLI / TUI
        ↓
Application Bootstrap
        ↓
integrations.providers.factory.create_provider()
        ↓
三个直接实现 ProviderPort 的原生 SDK Provider
        ↓
Anthropic Async SDK / OpenAI Async SDK
```

Application 不导入官方 SDK，Interface 不导入 Integration，Provider 包入口和根包均不导出 SDK Client 或具体 Provider。`create_provider()` 在源码中只有 Factory 定义和 Bootstrap 正式调用；未新增第二 Factory、Router、Plugin、Adapter、兼容入口或 Provider 抽象。

## Task 4：[接入主流程]

实际修改：

- 重写 `tests/test_architecture_boundaries.py`，删除已删除的 Pydantic AI FunctionModel/Bridge 测试入口，改为验证 SDK 仅位于三个 Provider Integration、依赖方向、唯一 Factory、协议字段归属、无私有流字段和 Headless 不加载 Interface。
- 修改 `tests/test_package.py`，用隔离子进程验证根包只暴露版本且不加载 OpenAI、Anthropic 或 Factory。
- 未修改 `src/uthcode/integrations/providers/factory.py`；现有 Factory 已满足唯一构造根和零网络构造要求。

验证结果：

- `pytest -q tests/test_architecture_boundaries.py tests/test_package.py`：`11 passed`。
- Application/Runtime/Factory/Contract：`35 passed`。
- Configuration/CLI/TUI：`67 passed`。
- 正式 Fake Headless、`uthcode exec` Fake、正式 TUI Fake、三 Provider Factory 零网络构造：专项测试全部通过。
- Core、Application、Interface 源码无 W02 修改；SDK import 仅存在于 `anthropic.py`、`openai_responses.py`、`openai_compat.py`。
- 旧标识扫描 `pydantic_ai|PydanticAIProvider|PydanticAICodec|FunctionModel|pydantic_graph`：无匹配。

## Task 5：[端到端验证]

- `python -m compileall -q src tests`：通过。
- 全量离线测试：改造后卸载前 `214 passed, 3 skipped`；清理并重装后、显式移除 API Key 再运行仍为 `214 passed, 3 skipped`。
- `python -m pip check`：`No broken requirements found.`。
- Application/CLI/TUI 错误矩阵专项脚本验证 Authentication、Rate Limit、Network、Invalid Response 和取消：Application 4 类异常分类，CLI 4 类均返回退出码 1 且不输出秘密，TUI 4 类均显示 `error`，双 Esc 取消显示 `cancelled`；输出 `application=4 cli=4 tui=4+cancel secret_safe=true`。
- 三个 Provider 显式取消和 Task 取消专项：`3 passed`；Application/Runtime/TUI 取消专项：`3 passed`。流关闭、无重复终态和独立 Fake Handle 行为通过。
- 10,000 个纯文本 Delta 离线微基准：`10000` 个 Delta、`10002` 个事件、`536.07 ms`；Stream 已关闭，网络调用 `0`，Pydantic AI 对象 `0`，普通 Delta 未复制完整流历史。测试 Double 按需生成/复用公开 Chat Chunk，未建立网络。
- `UTHCODE_RUN_LIVE` 未设置；三个 live 测试：`3 skipped, 35 deselected`。未运行真实端点，未读取或输出 API Key。

一次显式清除 API Key 后的全量测试出现既有 Textual 滚动动画时序波动（`50.81/59`），单测复跑通过，随后同样清除 API Key 的全量测试再次为 `214 passed, 3 skipped`。未修改 TUI 或以放宽断言处理该波动。

## Task 6：[遗留负担清理]

卸载前发行包记录：

- OpenAI `2.53.0`
- Anthropic `0.120.2`
- `pydantic-ai-slim` `2.22.0`
- `pydantic-graph` `2.22.0`
- `pydantic-ai` 未安装

发行包元数据检查显示，除当前 `uthcode` 之外没有项目反向依赖三个待卸载发行包；`pydantic-ai-slim` 对 `pydantic-graph` 的依赖属于待清理目标包自身依赖。按要求执行：

```text
pip uninstall -y pydantic-ai pydantic-ai-slim pydantic-graph
```

结果为卸载 `pydantic-ai-slim` 与 `pydantic-graph`，跳过未安装的 `pydantic-ai`。随后执行 `pip install -e . --group dev --upgrade` 成功。未卸载基础 `pydantic`、`pydantic-core`、`httpx` 或官方 SDK 的共享依赖。

清理后验证：

- 三个 `pip show` 均报告未安装。
- `find_spec('pydantic_ai')` 为 `None`。
- OpenAI `2.53.0`、Anthropic `0.120.2` 可导入且在指定范围内。
- `pip check` 通过；compileall 和全量测试通过。
- 旧 Pydantic AI 标识、`provider_details`、兼容文件名、旧 Codec/Bridge/Recorder、`legacy_` 和双轨/重复抽象扫描均无匹配。
- 精确私有字段扫描 `\._response\b|_source_iter|record_model_stream`：无匹配。

Checklist 第 83 项原始命令 `_response|_source_iter|record_model_stream` 过宽，会命中任务要求保留的公开 `openai_responses` 模块名、Builder 名称及配置值；命中内容仅为：`OPENAI_RESPONSES`、`openai_responses`、`build_openai_responses_provider`，不存在第三方私有字段。该项按其实际安全边界完成，并保留了上述精确扫描证据。

## 文件与范围

W02 实际新增或修改：

- `tests/test_architecture_boundaries.py`
- `tests/test_package.py`
- `docs/work/T01-2-移除pydantic改用原生SDK/T01-2-移除pydantic改用原生SDK-checklist.md`：仅将已取得证据的既有复选框改为 `[x]`
- `docs/work/T01-2-移除pydantic改用原生SDK/feedback/W02-integration-delivery-feedback.md`

W01 已有的 Provider、依赖、协议测试及 `common.py` 改动保持不变；W02 未为修复测试而恢复旧 Bridge，也未新增兼容层。

Checklist Task 1—Task 6 的既有验收项均已取得证据并勾选；Task 3 的 live 门禁在本轮补充验证后勾选。工作包原始需求、Spec、Tasks、Prompt 和 Checklist 文字内容未修改。

未执行 Git 写入、提交、推送、分支操作或工作包归档；工作包仍等待用户审查并手动归档。

## W02 独立审查返工

独立审查发现并修复两处公开 SDK 事件覆盖缺口：

- OpenAI Responses 流此前会把官方 `response.reasoning_summary_part.added` 和 `response.reasoning_summary_part.done` 边界事件判为不支持。现在将两类无增量载荷的边界事件安全忽略，正文仍由既有 summary text delta/done 事件汇总。
- Anthropic 非 Beta Messages 流此前只从 `message_start.message.usage` 读取输入 token；当后续 `message_delta.usage` 省略可选缓存字段时，缓存读取量和写入量会错误保持为零。现在从 `message_start` 同步读取两个缓存字段，后续缺字段时保留已取得的值。

返工遵循先补回归测试再改实现：两条新测试修改实现前分别因“不支持的 Responses 事件”和“缓存 token 为零”失败；修改后均通过。验证结果：

- 两条定向回归测试：`2 passed`。
- Anthropic 与 OpenAI Responses Provider 套件：`25 passed, 2 skipped`。
- 全量离线测试：`215 passed, 3 skipped`。
- `python -m compileall -q src tests`、`python -m pip check`、`git diff --check`：通过。
- `pydantic_ai` 模块仍不可发现，三个 Pydantic AI 发行包仍未安装；源码内无旧 Pydantic AI 标识和第三方私有流字段残留。

本次返工未运行 live 测试，未执行 Git 写入、提交、推送、PR、合并或归档。

### 独立复查补充返工

第一次返工复查指出，上节将 `response.reasoning_summary_part.done` 描述为“无增量载荷的边界事件”并直接忽略并不完整：该官方事件包含完整 `part.text`，必须与同一 reasoning summary 已累计文本校验一致性。本补充记录取代上节关于这两类事件“安全忽略”的实现描述。

已新增冲突快照回归测试：令 summary delta 为 `plan`、part done 快照为 `CONFLICT`、output item done 仍为 `plan`。修改实现前该流会错误成功；现在 Provider 会校验 part 类型、文本和事件身份，并在完整快照与累计 delta 冲突时抛出 `InvalidProviderResponseError`。合法 added/done 事件仍正常通过，非空快照也可作为无 delta 流的 summary 内容。

补充返工验证：三条相关回归测试 `3 passed`；全量离线测试 `216 passed, 3 skipped`；compileall、pip check 和 `git diff --check` 均通过。仍未运行 live 测试或执行任何 Git 写入。
