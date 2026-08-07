# T07 三层权限系统 Checklist

## Task 1 — 全局权限约束与 Core Domain

- [x] `SRe-AGENTS.md` 的 Permission 第 11 节明确 `full_access` 仍受 Guard Ask/Deny 约束，且未改动其他全局章节。
- [x] 执行 `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_permission.py -q`，Core 模式、Effect、Guard/Policy、来源优先级和 Session Grant 矩阵全部通过。
- [x] 检查 `src/uthcode/core/permission.py`，其 import 不包含 `tomlkit`、Provider SDK、Application、Integrations 或 Interfaces。
- [x] 对 Core 权限值执行 JSON 序列化测试，输出不含 Path、SDK 对象或可变容器泄漏。

## Task 2 — Tool Preflight 与 Trusted Action

- [x] 执行 Tool、file、search、process、application tool 单元测试，六工具的可信 Action 与 READ/WRITE/DESTRUCTIVE/EXTERNAL/UNKNOWN 分类全部通过。
- [x] 测试未知 Tool 和非法参数 ToolCall，均直接返回 error ToolResult，Permission evaluator 调用次数为 0。
- [x] 测试 ToolCall 参数携带伪 `effect` 字段，最终 Action 不受其覆盖。
- [x] 检查 ToolRegistry 只维护一套 JSON Schema validator，prepared 调用在授权后只执行一次。
- [x] 检查三个 Provider 的 ToolDefinition 序列化结果，不包含 Permission、Effect 或 Action 元数据。

## Task 3 — permissions.toml Discovery / Parse / Template

- [x] 执行 `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_permission_rules.py tests/test_config_loader_integration.py -q`，全部通过。
- [x] 在隔离 HOME/workdir fixture 中验证用户文件自动创建默认 Guard、当前项目文件自动创建空占位，且不改写 `config.toml`。
- [x] 验证 Git root→cwd、非 Git cwd、物理路径去重和 nearest project > parent > user 来源顺序。
- [x] 分别输入非法 TOML、未知 Effect、非法 regex、缺失目标和非法 Guard/Policy 结构，Run 初始化均明确失败且不静默跳过。
- [x] 若修改 `.gitignore`，执行 `git check-ignore -v <fixture>/.uthcode/permissions.toml` 证明只匹配权限文件，不忽略 `.uthcode/config.toml`。

## Task 4 — Workspace / Resource Scope 改造

- [x] 执行 file/search/application tool 与新增 workspace scope 测试，inside/outside、`..`、symlink escape、新路径、Windows case/drive 全部通过。
- [ ] 测试 outside 文件在未授权时不执行，在权限允许后通过真实 Tool 路径完成安全的读写操作。
- [x] 测试 workspace 内外的 read-before-write、changed-since-read、成功写后 tracker 更新行为，结果与 T04 不变量一致。
- [x] `rg -n "outside the workspace|_require_within" src/uthcode/integrations/tools` 的结果只保留解析/事实职责，不存在 outside 必然授权拒绝的生产分支。

## Task 5 — Rule + Strategy Evaluator 与 Guard

- [x] 执行 permission、rule、file、search、process 集成测试，default/auto/full_access 完整矩阵全部通过。
- [x] 验证最近项目 Allow 可覆盖父项目/User Deny；同一有效来源内 Deny > Ask > Allow；不存在全局 deny wins。
- [x] 验证 Guard Deny/Ask 在三模式生效；Guard Allow 在 default/auto 继续 Policy/Strategy，在 full_access 放行。
- [x] 验证 `.env`、`.env.*`、SSH、cloud/docker/Git/package credential、私钥文件命中 Guard，`.env.example` 与纯 metadata 枚举不误命中内容 Guard。
- [ ] 验证 ReadFile 与 Grep 均不能泄漏敏感内容，Pause/Event 只含脱敏摘要。
- [x] 以 mock/stub execute 验证需求列出的 Unix/Windows Bash Guard 正例；`rm -f`、普通 PID 的 `kill -9`、`rm -rf build/` 不命中 Guard，但可分类为 DESTRUCTIVE。

## Task 6 — Permission Pause / Resume 与 Session Grant

- [ ] 执行 `tests/test_agent_interaction.py`、`tests/test_agent_loop.py`、`tests/test_application_runs.py` 和 permission integration tests，全部通过。
- [ ] ordinary Ask 的 choices 精确为 once/session/reject，Guard Ask 精确为 once/reject，Guard 中不存在 session 选项。
- [ ] stale/wrong permission request ID 被拒绝；有效响应在同一 Turn 恢复且 prepared Tool 只执行一次。
- [ ] ordinary session grant 在同 Run 后续 Turn 生效，新 Run 不继承，且不能覆盖 Guard、Policy Deny 或不同 tool/action/effect/resource。
- [ ] reject/deny 生成一个 error ToolResult 与 ToolFinished，同 batch 下一 ToolCall 继续，FIFO 和每调用恰好一结果不变。
- [ ] 重现 cancel/approval race，取消优先且无残留 pending pause、waiter 或执行副作用。

## Task 7 — `/permission` Application Session Control 与 TUI

- [ ] 执行 command、completion、Application runs、TUI、CLI 测试，全部通过。
- [ ] 从 `/permission` 打开三模式 picker，切换 auto 后只影响当前 Run；新 Run 恢复 default。
- [ ] 选择 full_access 前显示明确高风险提示；模型、Tool 或项目规则均无法触发模式切换。
- [ ] 模式切换不写 `config.toml` 或 `permissions.toml`，也不改变已经 pending 的 Permission request。
- [ ] TUI ordinary approval 显示三选项，Guard approval 显示两选项，二者都只调用 Application 公共 API。
- [ ] CLI 遇到 Permission Pause 不自动 allow、不读取 stdin、不挂起，并按既有非交互策略安全结束。
- [ ] `/help` 与 completion 均从现有 Registry 展示 `/permission`，不存在第二套命令 dispatcher。

## Task 8 [接入主流程] — 全链路 Composition

- [ ] 从正式 Application bootstrap 创建 Run，观察普通 Tool 唯一经过 registered/validated → Action → Rules → Strategy → Allow/Deny/Ask → execute/ToolResult。
- [ ] 测试启动时非法 `permissions.toml` 硬失败，错误不泄露规则中的秘密值或 Provider 凭据。
- [ ] 检查 Agent 普通 Tool、Application 手动 Tool 等生产入口，不存在绕过权限 evaluator 的执行路径。
- [ ] AskUserQuestion 仍走 T06 控制路径且不进入普通权限分类；Provider adapters 不含权限分支。
- [ ] `rg -n "Permission|permission" src/uthcode/application src/uthcode/core src/uthcode/integrations/tools` 的人工审查确认无临时 wrapper、重复 loader、重复 validator 或双轨 executor。

## Task 9 [端到端验证] — Headless / CLI / TUI / Provider

- [ ] 从正式 Headless/Application 入口发起 workspace 内写文件，default 模式出现 Permission Pause；once 恢复后文件真实写入且 Tool 只执行一次。
- [ ] 从正式入口拒绝一次写入，目标文件不变化，模型获得 error ToolResult，同 batch 后续安全 Tool 继续执行。
- [ ] 从正式入口批准一个隔离临时目录中的 outside 操作，物理目标真实完成；未批准路径无变化。
- [ ] 从正式入口验证 `.env`/Grep 敏感保护、Guard once/reject、Session Grant 与 `/permission` 三模式切换。
- [ ] 参数化执行 Anthropic、OpenAI Responses、OpenAI-compatible 集成测试，对等 ToolCall 得到相同 Action 与 Decision。
- [ ] 执行 Headless、CLI、TUI 测试；Headless 完成 Permission round trip，CLI 不自动批准，TUI 无 Core/Integration 直连。
- [ ] 执行 architecture tests，证明不导入 Interfaces 时 Core/Application 权限链仍完整运行。

## Task 10 [遗留负担清理] — 旧语义与重复职责清理

- [ ] 执行 `rg -n "L1|L2|L3|L4|L5|accept_edits|bypassPermissions|dontAsk|PathSandbox|allow_always|deny_always|permissions\.ya?ml|permissions\.local|LangGraph|PermissionMode.*plan|Plugin.*Permission|MCP.*Permission|Skill.*Permission" src tests SRe-AGENTS.md`，除明确否定测试外返回 0 条生产遗留。
- [ ] 人工检查无 workspace outside 硬授权拒绝、第二 schema validator、第二 Pause waiter、第二 Slash dispatcher、Interface→Core/Integration 依赖和 Provider 特判。
- [ ] 执行 `conda run --no-capture-output -n re-uthcode python -m pytest -q`，全量测试通过。
- [ ] 执行 `conda run --no-capture-output -n re-uthcode python -m compileall -q src tests`，退出码为 0。
- [ ] 执行 `conda run --no-capture-output -n re-uthcode python -m pip check`，输出 `No broken requirements found.`。
- [ ] 执行 `git diff --check`，无空白错误；对本工作包、`SRe-AGENTS.md` 和修改的 Markdown 执行 UTF-8 guard，全部通过。
- [ ] W01～W04 Feedback 已记录实际修改、测试、偏差、风险与遗留清理结论；工作包未被擅自归档，Git 未提交或推送。
