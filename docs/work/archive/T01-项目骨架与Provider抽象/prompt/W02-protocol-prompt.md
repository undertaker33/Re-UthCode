# W02 Protocol Worker Prompt

你是 Re:UthCode 的 W02 Protocol Worker。只有当用户明确要求完整读取并执行本文件时，才视为获得 Task 5—Task 7 的实施授权。你必须在当前仓库内严格串行完成三个物理 Provider 协议适配，并在每条验收真实通过后更新对应 Checklist。

## 工作目录与权威资料

仓库根目录：`D:\project\Re-UthCode`

开始实施前，必须完整读取并遵守：

1. `AGENTS.md` 及其引入的 `SRe-AGENTS.md`；
2. `docs/work/README.md`；
3. `docs/work/T01-项目骨架与Provider抽象/` 下的原始需求、Spec、Tasks 和 Checklist；
4. `docs/work/T01-项目骨架与Provider抽象/feedback/W01-foundation-feedback.md`；
5. `pyproject.toml`、根 `README.md`；
6. `src/uthcode/core/provider.py`；
7. `src/uthcode/application/generation.py`；
8. `src/uthcode/integrations/providers/` 当前全部源码；
9. `tests/test_provider_contract.py`、`tests/test_application.py`、`tests/test_architecture_boundaries.py`。

需求、Spec、Tasks、Checklist 和仓库规则共同构成实施边界。旧 `D:\project\UthCode` 与 `D:\project\MewCode` 只能读取相关参考文件，不得修改或复制旧公共 API。官方 SDK/Pydantic AI 资料用于确认当前 2.22 行为，不得用记忆猜测协议。

## 前置门槛与授权范围

- 开始前确认 W01 的 Task 1—Task 4 Checklist 已全部完成，基础测试仍通过，并阅读 W01 Feedback 中的偏差与风险。
- 若 W01 遗留问题会改变协议实现边界、依赖版本或验收结果，停止并报告，不得在 W02 中越权修补冻结文档或扩大任务。
- 只按顺序完成：Task 5 Anthropic → Task 6 OpenAI Responses → Task 7 OpenAI-compatible Chat Completions。
- 前一个 Task 的全部 Checklist 未通过并勾选前，不得开始下一个 Task。
- 不得实施 Task 8—Task 11，不得创建配置、Factory、Application 组合入口、live 测试、CLI、Interface、Agent Loop 或其他后置能力。
- 修改范围严格限于 Tasks 对 Task 5—Task 7 列出的三个协议文件、三个协议测试文件，以及共用 `pydantic_ai.py` 中必要的 Codec 扩展点。不得修改 Core 契约或 Application 语义来迁就单一协议；发现确需修改时停止并交由用户决定。

## 环境与安全

- 所有 Python、安装和测试命令在 Conda 环境 `re-uthcode` 中运行，优先使用 `conda run -n re-uthcode ...`。
- 本 Worker 的测试必须完全离线，通过 Mock SDK Client 或 Mock Transport 实际经过对应 Pydantic AI Model 的协议转换。
- 不得调用真实模型端点，不得要求、读取、输出或写入 `DEEPSEEK_API_KEY` 及任何真实凭据。
- 不新增当前任务不需要的直接依赖。若确需调整依赖，先确认 Tasks 与 Spec 已授权；调整后执行 `pip check` 并清理无用或重复依赖。
- 尊重工作区已有改动，不覆盖、不回退、不顺手整理范围外文件；不得执行提交、推送、PR、合并或归档。

## 已确认的设计决策

- Provider 实现必须按物理文件隔离：`anthropic.py`、`openai_responses.py`、`openai_compat.py`。
- Core 只持有 UthCode 自有 JSON-safe 模型；SDK、Pydantic AI Model 与协议对象只能存在于 Integration。
- `pydantic_ai.py` 是唯一共用 Direct 桥接层，只提供协议无关流程与 Codec 扩展点，不得出现 Provider 名称 switch/if 或三个协议的专有字段。
- Native Item 必须保留协议身份和原始顺序，只能由同一 Provider/协议恢复；切换 Provider 时不得发送其他协议的不透明数据。
- Runtime、Application 和 Core 不得按 Provider 名称分支。
- 不增加旧类、旧 API、别名、Facade、包装层、双实现或为了兼容少数端点而存在的全局补丁表。

## 协议实施重点

### Task 5：Anthropic

- 保存和恢复 Thinking、Signature、Redacted Thinking、Tool Use、Tool Result 与缓存用量，保持块顺序和不透明值不变。
- 使用独立 Anthropic Codec；共用桥接层只调用扩展点，不识别 Anthropic 字段。
- 覆盖文本、Thinking Delta、签名续轮、Redacted Thinking、工具续轮、认证、限流、网络错误、取消和资源关闭。
- 不实现 Prompt Cache 策略、模型发现或 Context Window 查询。

### Task 6：OpenAI Responses

- 分别跟踪 Reasoning、Reasoning Summary、输出 Item、Function Call 与 Function Call Output 的 Item ID、Call ID、输出索引和顺序。
- 交错 Function Call 必须按各自身份聚合，禁止单一全局 Tool Call 缓冲区。
- 正确处理 Delta、Done、Terminal Snapshot 去重及冲突，覆盖 completed、incomplete、failed、异常 EOF、未完成调用和取消。
- Responses Item 格式不得进入 Chat 模块；不实现 WebSocket、服务端会话、previous-response 优化或 Context Compaction。

### Task 7：OpenAI-compatible Chat Completions

- 使用 Chat Completions function tool、assistant Tool Calls 与 `role=tool` Tool Result 结构。
- Tool Call 按 stream index 独立聚合，保持 ID、名称和参数正确；不得使用 Responses Function Call Item 格式。
- 覆盖文本、Thinking/Reasoning Carrier、缓存用量、完成原因、错误、取消和资源关闭。
- 兼容逻辑必须由测试或真实端点需求证明且保持有界，不得引入 Provider 名称补丁表。

## 执行、验收与 Checklist

对 Task 5、Task 6、Task 7 依次执行：

1. 阅读该 Task 在需求、Spec、Tasks 与 Checklist 中的全部内容及参考定位；
2. 先补齐能够证明协议行为的离线测试，再实现最小完整适配；
3. 执行该 Task 的每条 Checklist 命令与可观测场景，并保存简明证据；
4. 只有某条验收实际执行并满足原文，才将对应 `- [ ]` 改为 `- [x]`；
5. 该 Task 全部条目通过后，运行 W01 基础回归，再开始下一 Task。

禁止提前或批量勾选、凭阅读推定通过、放宽断言、用 Test/Function Model 代替厂商协议 Mock、修改 Checklist 文字，或勾选 Task 8—Task 11。失败项保留未勾选并继续修复；遇到停止条件则写入 Feedback 并请求用户决定。

完成 Task 7 后至少运行：

```powershell
conda run -n re-uthcode python -m pip check
conda run -n re-uthcode pytest -q tests/test_package.py tests/test_provider_contract.py tests/test_application.py tests/test_architecture_boundaries.py tests/test_anthropic_integration.py tests/test_openai_responses_integration.py tests/test_openai_compat_integration.py
conda run -n re-uthcode python -m compileall -q src tests
rg -n "pydantic_ai\.Agent|pydantic_graph|langgraph|langchain" src tests
git diff --check
git status --short
```

同时检查三个协议的专有字段只存在于各自物理模块，共用桥接层没有 Provider 名称分支，测试未产生真实网络请求、秘密、缓存或意外产物。

## Feedback 与最终交付

首次完成时创建：

`docs/work/T01-项目骨架与Provider抽象/feedback/W02-protocol-feedback.md`

Feedback 必须遵守 `docs/work/README.md`，精简记录实际实现、三协议关键映射、设计理由、文件改动、测试证据、Task 5—Task 7 Checklist 状态、任务书偏差、风险和遗留负担。返工只在同一文件末尾追加标明轮次的新章节，不覆盖旧事实，不新建 `v2`、`retry` 或 `fix` 文件。

最终回复必须明确说明：Task 5—Task 7 各自结果；实际命令与结果；已勾选和未勾选项；依赖审查；未访问真实端点；未实施 Task 8—Task 11；未执行 Git 提交、推送、PR 或归档。只有全部离线验收与回归通过后，才能宣告 W02 完成。
