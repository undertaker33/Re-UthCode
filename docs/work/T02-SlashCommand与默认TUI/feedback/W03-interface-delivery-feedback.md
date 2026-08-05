# W03 Interface Delivery Worker Feedback

## 1. 完成结论

已严格按 Task 7 → Task 12 顺序完成本 Worker 授权范围。Checklist 中 Task 7—Task 12 的现有条目均已取得离线可复现证据并勾选；Task 1—Task 6 保持既有勾选状态。

本轮没有修改冻结的原始需求、Spec、Tasks 或 Prompt；没有执行 Git 提交、推送、PR、合并、分支写入或工作包归档。未引入旧 API 适配器、别名包装层、双轨配置、第二套 Registry 或未来能力占位模块。

## 2. 实际实现

### Task 7：默认 CLI 与 Headless exec

- 新增 `src/uthcode/__main__.py` 和 `src/uthcode/interfaces/cli.py`。无子命令进入默认 TUI，`exec` 使用标准库 `argparse`，支持位置 Prompt、stdin、`--cwd`、`--model`，不加载 Textual。
- Headless 请求始终构造单条 USER 消息；Text Delta 写 stdout，Reasoning/诊断写 stderr；成功、Provider/协议错误、配置/用法错误、取消分别映射为 0、1、2、130。
- `/help` 在 `exec` 中保持普通 Prompt；配置初始化由 Application 层错误类型转换为安全诊断；CLI 不直接依赖 Core、Integration 或 Provider SDK。

### Task 8：TUI 基础组件与流式渲染

- 新增 `interfaces/tui/state.py`、`rendering.py`、`widgets.py` 和 `ui.tcss`，实现六种当前 Transcript entry、Topbar、Transcript、活动行、Composer、批量流式 Markdown、reasoning entry、滚动跟随和选择状态。
- Composer 支持 Enter 提交、Shift+Enter 换行和空白忽略；流式刷新使用约 0.2 秒批次，终态、取消和异常强制 flush。
- TUI 只通过 `uthcode.application` 使用正式调用方模型；没有把 Textual 类型暴露到 Application API。

### Task 9：Completion、Model Picker 与双 Esc

- `interfaces/tui/completion.py` 与 `interfaces/tui/picker.py` 是独立模块、Widget 类和状态类。Completion 从同一个 Application Registry 读取候选，支持滚动、Up/Down、Tab、Enter、Esc；Picker 显示全部模型的 Ref、label、Provider 和当前项。
- 普通请求不携带上次 transcript；生成期间拒绝第二个普通请求和模型切换，但仍允许 Slash Command 分发。`/clear` 只清 transcript 和滚动状态，`/new` 保持未实现。
- 弹层打开时 Esc 只关闭弹层；无弹层生成中首次 Esc armed，1 秒内第二次调用当前 `GenerationHandle.cancel()`，超时则重新 armed。

### Task 10—12：主流程、端到端验证与清理

- 默认入口、`uthcode exec` 和 `python -m uthcode` 共用 `load_effective_config` 与 `create_application`；README 已更新首次配置、Fake 配置、TUI、exec 和嵌入式 Python 用法。
- 更新 `tests/test_cli.py`、`tests/test_tui.py`、架构边界测试和包测试，覆盖 headless 隔离、TUI Pilot、Fake 配置、首轮模板、安全项目配置失败、取消和命令/模型选择流程。
- `tests/conftest.py` 仅允许 Windows asyncio 所需的 loopback socket pair，仍拦截外部网络连接，避免离线测试因事件循环初始化误报。
- 保持源码目录只包含当前职责：`core`、`application`、`integrations`、`interfaces`；没有新增 Tool、Permission、Session、Memory、Dream、Skill、MCP、Hook、Worktree、Subagent、附件或 Diff 模块。

## 3. 文件改动

新增：

- `src/uthcode/__main__.py`
- `src/uthcode/interfaces/__init__.py`
- `src/uthcode/interfaces/cli.py`
- `src/uthcode/interfaces/tui/__init__.py`
- `src/uthcode/interfaces/tui/app.py`
- `src/uthcode/interfaces/tui/completion.py`
- `src/uthcode/interfaces/tui/picker.py`
- `src/uthcode/interfaces/tui/rendering.py`
- `src/uthcode/interfaces/tui/state.py`
- `src/uthcode/interfaces/tui/ui.tcss`
- `src/uthcode/interfaces/tui/widgets.py`
- `tests/test_cli.py`
- `tests/test_tui.py`
- 本 Feedback 文件

修改：

- `README.md`：更新默认 TUI、Headless exec、首次配置和正式 Python API 文档。
- `src/uthcode/application/__init__.py`：公开 CLI/TUI 调用方需要的正式 Application 类型和安全配置错误类型。
- `src/uthcode/application/bootstrap.py`：将配置初始化/配置错误转换为 Application 层错误。
- `tests/conftest.py`：保留外部网络拦截并允许本地 asyncio 事件循环连接。
- `tests/test_architecture_boundaries.py`：加入 Interface 越界导入和 headless 不加载 Interface 的边界验证。
- `tests/test_package.py`：将入口断言更新为当前 `__main__`/`interfaces/cli.py` 结构。

删除：无。

## 4. 验证结果

- `conda run --no-capture-output -n re-uthcode python -m pip install -e . --group dev`：成功安装 editable 包及开发依赖。
- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_cli.py`：`10 passed`。
- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_tui.py`：`8 passed`。
- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_tui.py -k "state or composer or stream or scroll or markdown"`：`6 passed, 2 deselected`。
- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_cli.py tests/test_tui.py tests/test_application.py tests/test_application_runtime.py`：`35 passed`。
- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_architecture_boundaries.py tests/test_package.py`：聚合验证通过（架构边界 17 项、包测试 2 项；与 CLI 合并执行时共 `29 passed`）。
- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_cli.py -k "formal"`：`4 passed`；覆盖 Fake 配置、首轮模板、项目配置安全失败和无 ANSI headless 输出。
- `conda run --no-capture-output -n re-uthcode pytest -q`：`186 passed, 3 skipped`；跳过项为既有显式 live 测试，未访问真实网络或 Provider。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests`：通过。
- `conda run --no-capture-output -n re-uthcode python -m pip check`：`No broken requirements found.`。
- `git diff --check`：通过；仅有 Git 关于工作区 LF/CRLF 转换的提示，无 whitespace error。
- `git status --short`：仅包含本 Feedback、Checklist 勾选、README、Application/测试修改和 W03 新增 Interface 文件；没有秘密、缓存或构建产物。

## 5. Checklist 状态

- Task 7：9/9 已勾选。
- Task 8：8/8 已勾选。
- Task 9：10/10 已勾选。
- Task 10：6/6 已勾选。
- Task 11：8/8 已勾选。
- Task 12：9/9 已勾选。

## 6. 参考基线、范围与风险

- 按 W03 指定的 FirstCoder 固定 commit 选择性复刻了适合当前范围的交互基线：topbar/transcript/composer、流式更新、选择状态、滚动跟随、completion/picker 与双 Esc 的交互形态；没有复制其未来能力、运行时导入或代码结构。
- 已确认仓库内 `LICENSES/FirstCoder-MIT.txt` 保留 MIT 许可说明。尝试从固定 commit 克隆参考仓库时网络连接被重置，未以该仓库作为运行时依赖；本实现只使用固定版本的可见视觉/交互信息和已保留的许可证说明。
- 没有进行真实 Provider/live 测试，也没有打开真实终端进行人工验收；Textual Pilot、Fake Provider、离线网络拦截和 headless 隔离测试均已通过。
- 未读取真实 API Key，未写入密钥，未发起外部网络请求；未执行 Git 写入或工作包归档。

## 7. 第一轮返工（2026-08-05）

### 7.1 返工原因

- 原 `UthCodeTUI.application_completion()` 只调用命令名阶段的 `CompletionEngine.complete()`，没有消费 Application Command System 的 `argument_candidates()`；因此 `/model ` 无参数候选，Usage、参数提示和静态参数候选也没有完整进入 TUI 菜单。
- 原 `_consume_generation()` 只有在下一个 Provider Event 到达时才调用 `StreamRenderer.push()`；首个 Delta 后 Provider 暂停时，缓冲内容会一直等到下一事件或终态才显示。
- 原 `tests/test_tui.py` 缺少上述两项真实 Pilot 行为的证据，不能仅以纯状态/renderer 测试覆盖冻结的 TUI 验收声明。

### 7.2 参数补全实现与数据流

- `src/uthcode/application/commands/models.py` 为 Application-owned `CompletionCandidate` 增加可选 `insert_text`、`argument_index` 和 `is_argument`，命令候选保持原有 `/canonical` 行为，参数候选可以携带完整插入文本。
- `UthCodeTUI.application_completion()` 现在先根据命令名后的空白明确区分命令名阶段与参数阶段。命令名阶段仍只调用唯一 Registry 驱动的 `CompletionEngine.complete()`；参数阶段先通过正式 Parser 取得 `CommandDefinition`，再调用 `CompletionEngine.argument_candidates()`，按当前参数前缀过滤，并从 Registry/CompletionEngine 读取 Usage 和参数提示。
- 参数插入文本使用 Registry 的 canonical command，并保留已经输入的参数前缀结构；因此 `/model ` 得到 Application Model Catalog 的全部 Ref，`/model two` 得到 `/model two/ref`，Tab 会写入完整命令，Enter 会通过正式 Parser/Dispatcher/`select_model()` 链路执行。
- 静态 `ArgumentSpec.choices` 与动态 `dynamic_candidates` 使用同一条 TUI 适配路径；TUI 没有维护模型或参数列表。Completion Menu 的 Static body 关闭 Rich markup，确保 Registry 生成的 `/model [model-ref]` Usage 不会被方括号吞掉。Model Picker 的 Widget、状态和模块均未复用。

### 7.3 定时批量刷新与生命周期

- 每次生成在 `UthCodeTUI._consume_generation()` 中创建一个 `StreamRenderer` 和一个 Textual `set_interval(0.2s)` Timer。Timer 独立调用 `renderer.flush()`，所以首个 Text/Reasoning Delta 后即使 Provider 没有下一事件，也会在约 0.2 秒后更新已有 Assistant/Reasoning Widget。
- Provider async iterator 没有被 timeout 包裹、取消或关闭来驱动刷新；Provider Event 仍由原有 `GenerationHandle.events()` 顺序消费。完成、`GenerationCancelled`、Provider 错误和普通应用异常路径均先强制 flush，再改变活动状态。
- `finally` 中停止 Timer、清空 renderer 引用、清空 generation task；`on_unmount()` 额外停止 Timer、取消当前 Handle 并等待 generation task，退出时不会遗留流刷新资源。关闭过程使用独立 `_closing` 标志，避免异步取消被误显示为 Provider 错误或在 Textual 节点销毁后继续更新 UI。
- 流式 Markdown 仍只更新一个可复用 Widget；终态、取消和异常后恢复选择状态。

### 7.4 新增测试与实际验证

- `tests/test_tui.py` 新增合成静态参数命令和 Fake Model Catalog 的 Pilot 测试：验证 `/model ` 展示完整 Catalog、`/model two` 前缀匹配 `two/ref`、Tab 得到完整 `/model two/ref`、Enter 经过正式模型切换链、静态候选、Registry Usage/参数提示以及 Completion/Picker 分离。
- 新增立即产生首个 Delta 后暂停的离线 Provider，Pilot 验证暂停期间 Text Delta 和 Reasoning Delta 均能由真实 0.2 秒 Timer 显示，Assistant Widget 数量保持 1；并验证完成、取消、异常立即 flush，Markdown 恢复可选择状态，退出清理 Timer、Handle 和 generation task。TUI 测试总数为 `14 passed`。
- 参数补全验收探针：`conda run --no-capture-output -n re-uthcode pytest -q tests/test_tui.py::test_tui_argument_completion_uses_catalog_and_formal_model_dispatch`，`1 passed`。
- 定时刷新验收探针：`conda run --no-capture-output -n re-uthcode pytest -q tests/test_tui.py::test_stream_timer_flushes_delta_before_provider_terminal_and_cleans_up`，`1 passed`。
- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_tui.py`：`14 passed`。
- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_cli.py tests/test_tui.py tests/test_application.py tests/test_application_runtime.py`：`41 passed`。
- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_architecture_boundaries.py tests/test_package.py`：`19 passed`。
- `conda run --no-capture-output -n re-uthcode pytest -q`：`192 passed, 3 skipped`；跳过项仍为既有显式 live Provider 测试。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests`：通过。
- `conda run --no-capture-output -n re-uthcode python -m pip install -e . --group dev`：成功；未增加依赖。
- `conda run --no-capture-output -n re-uthcode python -m pip check`：`No broken requirements found.`。
- `git diff --check`：通过，仅有工作区已有的 LF/CRLF 转换提示；`git status --short` 仅包含本工作包既有修改及本轮源码/测试变化，无秘密、缓存或构建产物。
- 静态边界复核确认：TUI 仅通过 Application 公共 API 使用参数候选和流事件；无 `uthcode.core`/`uthcode.integrations` 越界导入，无第二 Registry、硬编码模型列表、兼容层或未来能力耦合。

### 7.5 风险与未完成项

- 本轮范围内没有剩余未完成项。真实 Provider/live 测试和真实终端人工测试仍按 W03 原规则未运行；所有本轮证据均为离线 Fake Provider、Textual Pilot 和静态边界检查。
- 未修改原始需求、Spec、Tasks、Prompt 或 Checklist 文字/结构/顺序；未新增依赖，未执行 Git commit、push、PR、merge 或工作包归档。

## 8. 第二轮返工（2026-08-05）

### 8.1 返工原因

- 第一轮返工虽然补齐了参数候选交互，但把仅供 TUI 插入和展示使用的 `insert_text`、`argument_index`、`is_argument` 加入了 W02 的 Application-owned `CompletionCandidate`，越过 W03 只消费 W02 正式接口的边界。

### 8.2 实际修改

- 恢复 `application/commands/models.py` 中 W02 `CompletionCandidate` 的原始正式结构和 `/canonical` value 语义。
- 在 `interfaces/tui/completion.py` 新增 Interface-local `CompletionMenuItem`，只保存菜单展示、Usage、参数提示和 Composer 插入值。
- 命令名候选由 `CompletionMenuItem.from_command()` 适配 Application `CompletionCandidate`；参数候选仍只消费 `CompletionEngine.argument_candidates()`，由 TUI 本地菜单项保存完整插入文本。
- 参数候选、Model Catalog、Usage 和提示仍来自唯一 Registry/Application Command System；没有新增第二份命令或模型列表。
- 测试增加 Application Candidate 与 TUI Menu Item 为不同类型的边界断言。

### 8.3 验证结果

- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_command_completion.py tests/test_tui.py`：`19 passed`。
- 第二轮没有改变第一轮已通过的定时刷新机制；完整回归和静态边界结果见本轮最终验证。
- 未修改冻结任务文件或 Checklist 文字，未增加依赖，未执行 Git commit、push、PR、merge 或归档。

## 9. 第三轮返工（2026-08-05）

### 9.1 返工原因

- 任务包级独立审查发现 Application 仍允许两个 `GenerationHandle` 复用调用方传入的同一 `CancellationToken`，无法保证每个请求独立取消。
- CLI 在生成、`exec` 启动和默认 TUI 启动三条路径直接输出 `str(ProviderError)`，无法防御异常文本携带秘密。
- Transcript 只在鼠标滚轮事件中观察滚动位置，键盘和滚动条改变位置后可能仍自动跳到底部。
- 已勾选的完整 TUI 验收缺少 `/clear`、`/new`、生成中 Slash、模型切换拒绝、请求无历史和 Esc 超时等真实 Pilot 证据。

### 9.2 实际修改

- `UthCodeApplication.start_generation()` 和 `stream_generation()` 不再接受外部取消令牌；每个 Handle 始终在 Application 内部创建独立 `CancellationToken`。同时从 Application 公共导出中移除该 Core 控制类型，Provider 层自身的取消契约保持不变。
- CLI 三条 `ProviderError` 路径全部改为固定脱敏诊断，不再读取或拼接异常文本；测试分别注入流式和 Provider Factory 秘密字符串并确认 stderr、stdout 均不泄露。
- `TranscriptWidget` 通过 Textual `watch_scroll_y()` 观察所有真实滚动来源，并允许聚焦以接收键盘滚动；用户离开底部后新输出保持当前位置，键盘回到底部后恢复自动跟随。
- 新增临时 HOME Fake 配置的组合 Pilot 流程，覆盖 `/`、`/c`、`/help`、普通生成、`/clear`、`/new` 未实现、`/model` Picker 切换、用户配置写回、下一请求无历史、生成中 `/status`、直接模型切换拒绝和双 Esc 取消。
- 新增 Esc 超时后重新 armed 且不取消的 Pilot 测试，以及 Application 不再公开外部取消参数的签名断言。

### 9.3 验证结果

- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_application.py tests/test_application_runtime.py tests/test_cli.py tests/test_tui.py`：`47 passed`。
- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_architecture_boundaries.py tests/test_package.py`：`19 passed`。
- `conda run --no-capture-output -n re-uthcode pytest -q`：`198 passed, 3 skipped`；跳过项仍为显式 live Provider 测试。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests`：通过。
- `conda run --no-capture-output -n re-uthcode python -m pip check`：`No broken requirements found.`。
- `git diff --check` 与 Interface 依赖扫描通过；未增加依赖、秘密、缓存或工作包外产物。
- 未修改原始需求、Spec、Tasks、Prompt 或 Checklist 文字/结构/顺序，未执行 Git commit、push、PR、merge 或归档。

## 10. 第四轮返工（2026-08-05）

### 10.1 返工原因

- 首次运行生成的用户配置模板只有全部注释的 Fake/无效地址占位内容，没有列出真实 Provider `kind`、字段约束或环境变量设置方法，用户无法据此完成真实模型配置。
- 用户未编辑模板便再次启动时，空映射落入普通模型校验并报告 `configuration requires a selected model`，没有指出配置仍处于未初始化状态。

### 10.2 实际修改

- `integrations/config/template.py` 的模板改为可直接替换参数并取消注释的 `openai_compat` 完整示例，列出 `openai_compat`、`openai_responses`、`anthropic` 三种真实 Provider 类型，说明真实 Provider 的 `api_key_env` 要求、`openai_compat` 的 `base_url` 要求以及 `fake` 仅供显式离线测试。
- 模板加入当前 PowerShell 会话设置环境变量的示例，并明确 `api_key_env` 保存的是环境变量名，API Key 真实值不得写入 TOML。模板仍全部保持注释，首次运行不会自动启用 Fake Provider、无效地址或占位凭据。
- 配置加载器现在把空文件和纯注释用户配置识别为既有 `ConfigurationInitializationRequired`，提示用户编辑并取消注释一套完整 Provider/Model 配置；已有部分有效 TOML 但缺少 `model` 时，仍保留原有 `model` 字段级错误。
- Application 层保持相同异常类型和 `template_path` 接口，只同步安全初始化提示；没有改变配置字段、Provider 构造、项目配置安全边界或公开 Application API。
- README 首次配置章节同步真实 OpenAI-compatible 示例、环境变量命令、支持的 Provider 类型和字段约束。
- `/login` 仍按 T02 冻结范围返回未实现；本轮不允许无模型状态进入 TUI，也未引入凭据存储或配置交互 UI。

### 10.3 测试与验证

- 配置测试验证模板包含完整真实 Provider 示例、三种支持类型、环境变量说明和 Fake 限制，且不包含 `sk-` 形式的真实 Key。
- 新增纯注释模板第二次加载测试，确认继续返回初始化指引；新增部分配置缺少 `model` 测试，确认仍返回字段级配置错误。
- 正式 `python -m uthcode exec` 子进程测试覆盖首次创建模板和未编辑模板再次启动，两次均退出码 2、stdout 为空并输出不含秘密的初始化指引。
- `conda run --no-capture-output -n re-uthcode pytest -q tests/test_configuration.py tests/test_cli.py`：`50 passed`。
- `conda run --no-capture-output -n re-uthcode pytest -q`：`200 passed, 3 skipped`；跳过项仍为显式 live Provider 测试。
- `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests`、`python -m pip check` 和 `git diff --check` 均通过；未增加依赖。

### 10.4 范围与遗留检查

- 未修改原始需求、Spec、Tasks、Prompt 或 Checklist，未新建 T02-1，未实现 `/login`，未改变 TUI 启动架构。
- 未引入兼容别名、双轨配置、额外 Provider 类型或真实秘密；未执行 Git commit、push、PR、merge 或工作包归档。

## 11. 第五轮返工（2026-08-05）

### 11.1 返工原因

- 真实 DeepSeek OpenAI-compatible 流已经输出完整正文，但终态 usage 中 `prompt_tokens_details` 或 `completion_tokens_details` 为 JSON `null` 时，Codec 将其判为非法对象并抛出 `InvalidProviderResponseError`，导致 TUI 在成功正文后显示生成失败。
- 同一个异常在 TUI 中先由 `StreamRenderer` 写入英文 `generation failed`，随后又由 TUI 写入中文 `生成失败`，Activity 再显示 `error`，造成重复失败提示。

### 11.2 实际修改

- `OpenAICompatCodec.usage_from_model_response()` 现在仅将可选 usage detail 的 `None` 规范化为空字典；非空且非字典的值仍按原安全边界拒绝。缺省缓存与 reasoning token 数继续归一为 0。
- TUI Provider 异常和未知异常路径先调用普通 `renderer.flush()` 输出剩余正文，再只追加一条中文 `生成失败`；Activity 保留 `error` 状态。
- 删除不再有调用方的 `StreamRenderer.finish_error()`、`RenderBatch.error` 及对应分支，没有保留废弃入口或双轨错误渲染。

### 11.3 测试与真实验证

- 新增 OpenAI-compatible 集成回归测试，构造两个 usage detail 均为 `None` 的标准完成流，确认产生 `GenerationCompleted`、终态为 `stop`，缓存与 reasoning token 均归一为 0。
- TUI Pilot 错误终态测试现在断言 Transcript 只有一条 `生成失败`，同时确认剩余正文已 flush、Activity 为 `error`、Timer 和生成任务均已清理。
- 定向失败测试在修复前稳定复现两项缺陷；修复后定向测试 `4 passed`，Provider/TUI/Application 聚合测试 `34 passed, 1 skipped`。
- 使用当前用户 DeepSeek 配置发送一次最小真实请求，事件序列为 `TextDelta`、`NativeItemCompleted`、`GenerationCompleted`，终态 `finish_reason=stop`；没有记录正文、API Key 或其他秘密。
- `conda run --no-capture-output -n re-uthcode pytest -q`：`201 passed, 3 skipped`；跳过项仍为既有显式 live 测试。
- `compileall`、`pip check`、`git diff --check` 均通过；未增加依赖。

### 11.4 范围与遗留检查

- 本轮只修复已复现的 OpenAI-compatible 可空 usage 兼容性和 TUI 重复错误渲染，没有改变 Provider 公共模型、配置结构、命令系统或 `/login` 状态。
- 未修改原始需求、Spec、Tasks、Prompt 或 Checklist，未执行 Git commit、push、PR、merge 或归档。
