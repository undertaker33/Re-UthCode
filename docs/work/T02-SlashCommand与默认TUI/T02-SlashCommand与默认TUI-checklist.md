# T02-SlashCommand与默认TUI Checklist

所有命令从仓库根目录执行，并使用 Conda 环境 `re-uthcode`。本工作包默认离线；不得自动运行需要真实模型凭据或产生费用的 live 测试。

## Task 1：更新阶段约束与入口依赖

- [x] 执行 `conda run -n re-uthcode python -m pip install -e . --group dev`，editable install 成功。
- [x] 执行 `conda run -n re-uthcode python -m pip check`，输出 `No broken requirements found.`。
- [x] 执行 `conda run -n re-uthcode python -c "import importlib.metadata as m; print(m.version('textual'), m.version('tomlkit'))"`，版本分别满足 `>=8.2,<9` 与 `>=0.15,<0.16`。
- [x] 执行 `conda run -n re-uthcode python -c "import importlib.metadata as m; print([e.value for e in m.entry_points(group='console_scripts') if e.name == 'uthcode'])"`，只输出一个项目 console script 目标。
- [x] 检查 `LICENSES/FirstCoder-MIT.txt`，包含 `Copyright (c) 2026 KomorGiaoGiao` 和完整 MIT 条款。
- [x] 查看 `git diff -- SRe-AGENTS.md`，只修改与 T02 配置、Slash Command、默认 TUI 和 Interface 边界直接冲突的条款。

## Task 2：建立 Application 有效配置模型

- [x] 执行 `conda run -n re-uthcode pytest -q tests/test_configuration.py -k "model or profile or immutable or single_model"`，配置模型用例全部通过。
- [x] 测试证明 Provider Profile ID、Model Ref 和远端 Model ID 可取不同值且不会互相覆盖。
- [x] 分别构造 unknown provider kind、unknown provider reference、unknown selected model 和非法输出 token 配置，均被拒绝。
- [x] 修改构造 Effective Config 时传入的原始 mapping 后，已构造对象保持不变；对象自身字段不可重新赋值。
- [x] 使用单模型 Headless 构造入口生成有效配置，模型、Provider 和配置来源均可由 Application 自有类型读取。
- [x] 执行 `rg -n "tomlkit|textual|pydantic_ai|openai|anthropic" src/uthcode/application/configuration.py`，返回 0 条第三方类型或 Provider 名称分支。
- [x] 检查 Application 公开导出，只存在新的 Effective Config 长期模型，不保留 T01 单 Provider 配置兼容入口。

## Task 3：实现配置发现、合并、安全与写回

- [x] 执行 `conda run -n re-uthcode pytest -q tests/test_configuration.py`，全部通过且网络拦截器记录 0 次请求。
- [x] 在用户配置不存在的临时 HOME 启动加载，创建注释待填模板、报告绝对路径并停止；未构造 Provider，模板不含可用 Key 或真实秘密。
- [x] 在含 `.git` 目录和 `.git` 文件的两类仓库中，从根到 cwd 多层放置配置，观察越近 cwd 的合法模型字段优先。
- [x] 在非 Git 目录中于父目录和 cwd 同时放置项目配置，只加载 cwd 文件。
- [x] 通过符号链接、相对路径和 Windows 大小写变体提供同一配置，加载记录中同一物理文件只出现一次。
- [x] 在项目配置分别加入 Provider 表、kind、base URL、秘密环境变量、直接 Key 和等价凭据字段，均硬失败并报告文件路径与禁止字段。
- [x] 项目配置定义 Model Profile 并引用用户 Provider，合法合并成功；引用不存在 Provider 或 Model Ref 时失败。
- [x] 写回用户顶层 model 后，重新读取文件确认注释、表顺序、Provider 表、Model 表和其他字段逐项保持；项目配置未变化。
- [x] 模拟临时文件写入或原子替换失败，用户配置原字节保持不变且临时文件被安全处理。
- [x] 执行 `rg -n "dotenv|\.env" src/uthcode/integrations/config src/uthcode/application`，返回 0 条 `.env` 加载实现。

## Task 4：扩展 Application Runtime

- [x] 执行 `conda run -n re-uthcode pytest -q tests/test_application.py tests/test_application_runtime.py tests/test_provider_factory.py tests/test_provider_contract.py`，全部通过。
- [x] 启动两个延迟 Fake Generation Handle，取消其中一个只产生该句柄的取消结果，另一个仍完成且各自记录一次请求。
- [x] 对同一 Generation Handle 重复调用取消，操作幂等且 `cancelled` 状态保持为真。
- [x] 通过便利流接口完成一次生成，测试证明其内部经过正式 Generation Handle 且仍拒绝无终态、重复终态和终态后事件。
- [x] Model Catalog 返回全部有效 Model Profile，状态输出包含当前模型、Provider Profile、配置来源和运行状态且不含注入秘密。
- [x] 模拟候选 Provider 构造失败，当前 Provider、当前 Model Ref 和用户配置字节均不变。
- [x] 模拟用户模型写回失败，候选 Provider 不替换当前 Provider，当前 Model Ref 和用户配置字节均不变。
- [x] 成功切换后，当前 Provider 和 Model Ref 同步更新，用户配置只修改顶层 model。
- [x] 执行 `rg -n "ProviderKind|anthropic|openai_responses|openai_compat|fake" src/uthcode/application/generation.py`，返回 0 条 Provider 选择分支。
- [x] 执行 `rg -n "Conversation|Session|RunState|Turn|AgentLoop" src/uthcode/application src/uthcode/integrations/config`，返回 0 条新增后续运行时类型。

## Task 5：实现 Command Registry 与 Parser

- [ ] 执行 `conda run -n re-uthcode pytest -q tests/test_command_registry.py tests/test_command_parser.py`，全部通过。
- [ ] 分别注册 canonical/canonical、alias/canonical、canonical/alias、alias/alias 和重复 alias 冲突，全部被拒绝且原 Registry 不变。
- [ ] 注册含大写、空白、斜杠或非法字符的命令名和 alias，全部被拒绝；解析调用名时大小写不敏感并得到小写 canonical。
- [ ] 通过 alias resolve 得到同一个 canonical Command Definition，`list_commands()` 保持稳定注册顺序和隐藏状态。
- [ ] 普通文本返回非命令；`/` 只标记 Slash 输入但不产生可执行调用；未知命令产生结构化未知结果。
- [ ] 解析 `/review 关注并发安全`，query 字节内容保持为 `关注并发安全`。
- [ ] 解析 `/do "target one" -- 请实现并测试`，args 为一个带空格参数，query 保持原始文本。
- [ ] 模拟引号不闭合、参数缺失和多余参数，得到可区分 Usage 错误而非执行异常。
- [ ] 执行 `rg -n "textual|mewcode|firstcoder|SkillLoader" src/uthcode/application/commands`，返回 0 条运行时依赖或未来 Loader。

## Task 6：实现 Completion、Dispatcher 与内置命令

- [ ] 执行 `conda run -n re-uthcode pytest -q tests/test_command_completion.py tests/test_command_dispatcher.py`，全部通过。
- [ ] 输入 `/` 得到全部非隐藏 canonical 命令，不受八项上限截断，`/help` 恰好出现一次且固定最后。
- [ ] 输入 `/c` 得到 clear、compact 及 alias 匹配项，按 canonical 去重，`/help` 仍恰好一次且固定最后。
- [ ] 未实现命令在候选中带未实现标记；命令解析完成后可得到 Registry 定义的 Usage 和参数提示。
- [ ] 静态参数命令返回静态候选；`/model` 动态候选与 Application Model Catalog 的 Model Ref 集合完全一致。
- [ ] 使用合成 LOCAL、LOCAL_UI、PROMPT 命令分别得到 output、结构化 ui_action、prompt，三者字段不混用。
- [ ] `/help` 总帮助和单命令帮助、alias、Usage、实现状态均随测试 Registry 变化，不依赖第二份列表。
- [ ] `/models` 与 `/m` resolve 到 canonical `/model`，Registry 中不存在 canonical `models`。
- [ ] 分别分发 config、compact、plan、new、resume、login、memory、dream、do、review，均返回 `功能未实现：/<canonical>` 和 NOT_IMPLEMENTED 状态。
- [ ] `/clear`、无参数 `/model`、`/quit` 分别返回 Clear Transcript、Open Model Picker、Quit Interface；Application 命令模块不导入 Textual。

## Task 7：实现默认 CLI 与 Headless exec

- [ ] 执行 `conda run -n re-uthcode pytest -q tests/test_cli.py`，全部通过且不打开真实终端或网络连接。
- [ ] 调用无子命令 CLI，注入的 TUI runner 恰好执行一次并收到同一正式 Application。
- [ ] `uthcode exec PROMPT` 与 stdin 两种路径均创建单消息请求，Text Delta 写 stdout，成功输出以换行结束且退出码为 0。
- [ ] `uthcode exec "/help"` 将文本原样作为普通 Prompt，不调用 Command Dispatcher。
- [ ] 空位置 Prompt 且 stdin 为空时，诊断写 stderr、stdout 为空、退出码为 2。
- [ ] `--cwd` 改变配置发现起点；`--model` 改变当前进程选择但用户配置字节不变。
- [ ] 配置初始化或配置错误返回 2；Provider/协议错误返回 1；显式取消或 Ctrl+C 返回 130。
- [ ] 执行 `conda run -n re-uthcode python -m uthcode exec "hello"` 的 Fake 配置 smoke，输出无 ANSI TUI 控制序列。
- [ ] 检查 `src/uthcode/interfaces/cli.py`，不导入 `uthcode.core`、`uthcode.integrations` 或 Textual Widget 模块。

## Task 8：实现 TUI 基础组件和流式渲染

- [ ] 执行 `conda run -n re-uthcode pytest -q tests/test_tui.py -k "state or composer or stream or scroll or markdown"`，全部通过。
- [ ] Textual Pilot 中 Topbar 显示 UthCode、当前 Model Ref 和 cwd/project；Transcript、活动行和 Composer 布局均存在。
- [ ] Composer 按 Enter 产生提交，Shift+Enter 插入换行，空白输入不产生提交。
- [ ] 连续多个 Text Delta 在刷新间隔内只批量更新现有 Assistant Markdown，而非每个 token 新建 Widget。
- [ ] Reasoning Delta 进入独立简洁 reasoning entry；完成、取消和异常前缓冲均被立即 flush。
- [ ] 流式 Markdown 更新期间文本选择被阻止，终态后恢复；Textual 异步更新取消不被记录为应用错误。
- [ ] 用户位于底部时新内容自动跟随；主动上滚后不跳到底；重新到底后恢复跟随；清空状态后复位。
- [ ] 执行 `rg -n "Tool|Permission|Session|TaskPlan|Attachment|ImagePaste|firstcoder|mewcode" src/uthcode/interfaces/tui`，除许可证说明或明确禁止断言外返回 0 条迁移耦合。

## Task 9：实现 Completion Menu、Model Picker 与双 Esc

- [ ] 执行 `conda run -n re-uthcode pytest -q tests/test_tui.py`，全部通过。
- [ ] 输入 `/` 打开可滚动 Command Completion Menu，Up/Down 改变选中项，Tab 补全 canonical，Enter 执行，Esc 只关闭菜单。
- [ ] 无参数 `/model` 打开独立 Model Picker，显示全部模型的 Ref、label、Provider 和当前项；Up/Down/Enter 可切换，Esc 只关闭 Picker。
- [ ] 静态检查和对象断言证明 Completion Menu 与 Model Picker 使用不同模块、Widget 类和状态类。
- [ ] 普通输入写入 USER entry，只构造单消息请求，流事件生成 ASSISTANT/REASONING entry；下一次请求不携带上次消息。
- [ ] 生成中第二个普通输入被拒绝；Slash Command 仍可分发；`/model` 直接调用和 Picker 选择均被拒绝且配置不变。
- [ ] `/clear` 只清 Transcript 并复位滚动状态，Application 当前模型与配置保持；`/new` 仍返回未实现。
- [ ] Completion 或 Picker 打开时 Esc 只关闭弹层；无弹层生成中第一次 Esc 显示再次按键提示，一秒内第二次调用当前 Handle.cancel()。
- [ ] 超过一秒的第二次 Esc 重新进入 armed 状态，不取消；取消完成后缓冲 flush 且活动状态显示 cancelled。
- [ ] `/quit` 退出 Interface；CLI `exec` 测试证明未实例化 Textual App。
- [ ] 执行 `rg -n "uthcode\.(core|integrations)" src/uthcode/interfaces`，返回 0 条越界导入。

## Task 10：[接入主流程] 接入正式启动链路

- [ ] 执行 `conda run -n re-uthcode pytest -q tests/test_cli.py tests/test_tui.py tests/test_application.py tests/test_application_runtime.py`，全部通过。
- [ ] 安装后的 `uthcode`、`uthcode exec` 与 `python -m uthcode` 均经过同一配置加载与 Application 组合入口。
- [ ] README 的首次配置、Fake TUI、`exec` 和 Headless Python 示例在临时 HOME/cwd 中可复现，且不访问网络。
- [ ] README 不再声明“没有 CLI/TUI”，不展示 T01 已失效单 Provider bootstrap，也不承诺 Out of Scope 功能。
- [ ] 检查 `application.__init__`，仅公开正式 Effective Config、加载、Application、Generation Handle、命令和调用方必需类型，不公开 TOMLKit、Textual 或 SDK 类型。
- [ ] 搜索旧 `create_application(ProviderConfig` 调用与 T01 临时配置公开导出，源码、README 和测试中返回 0 条兼容路径。

## Task 11：[端到端验证] 验证真实离线用户流程

- [ ] 在临时 HOME 中执行正式入口，用户配置不存在时创建模板并停止；网络拦截器记录 0 次请求。
- [ ] 填写两个 Fake Provider/Model 后启动 `uthcode` Pilot，验证 `/`、`/c`、`/help`、普通流、`/clear`、`/model` 切换和双 Esc 取消完整流程。
- [ ] 使用同一配置执行 `uthcode exec`，stdout 得到 Fake 文本、stderr 无 TUI 控制序列、退出码为 0。
- [ ] 在项目配置定义 Provider 或秘密字段，从 `uthcode` 和 `uthcode exec` 两个入口均安全失败并报告路径/字段。
- [ ] 执行 `conda run -n re-uthcode pytest -q`，全量离线测试通过，既有 live 测试明确 skipped。
- [ ] 执行 `conda run -n re-uthcode python -m compileall -q src tests`，退出码为 0。
- [ ] 执行 `conda run -n re-uthcode python -m pip check`，输出 `No broken requirements found.`。
- [ ] 在隔离 Textual/TUI 导入的测试进程中运行 Application、配置和 Headless 测试，全部通过。

## Task 12：[遗留负担清理] 清理重复职责和越界依赖

- [ ] 执行 `conda run -n re-uthcode pytest -q tests/test_architecture_boundaries.py`，全部通过。
- [ ] 搜索 built-in Command Definition、帮助列表和补全命令来源，确认只有一个正式 Registry，TUI 不含第二份命令常量。
- [ ] 搜索 Effective Config、配置 loader 和 Application bootstrap，确认各自只有一个正式实现，不存在 T01/新配置双轨。
- [ ] 执行 `rg -n "uthcode\.(core|integrations)" src/uthcode/interfaces`，返回 0 条；执行 `rg -n "textual|tomlkit" src/uthcode/core src/uthcode/application`，除架构测试禁止字符串外返回 0 条越界依赖。
- [ ] 执行 `rg -ni "dotenv|langgraph|langchain|mewcode|firstcoder" pyproject.toml src tests`，除许可证、参考说明或架构测试禁止字符串外返回 0 条运行时依赖/import。
- [ ] 执行 `rg --files src/uthcode`，不存在 Tool、Permission、Session、Context、Memory、Dream、Skill、MCP、Hook、Worktree、Subagent、附件或 Diff 占位模块。
- [ ] 搜索 `legacy_`、`compat_`、Adapter、Facade、旧入口和不可达分支，确认没有仅为兼容 Re:UthCode 早期实现而保留的逻辑。
- [ ] 执行 `conda run -n re-uthcode pytest -q`、`conda run -n re-uthcode python -m compileall -q src tests` 和 `conda run -n re-uthcode python -m pip check`，全部通过。
- [ ] 执行 `git diff --check`，无空白错误；执行 `git status --short`，没有秘密、缓存、构建产物或工作包外意外文件。
