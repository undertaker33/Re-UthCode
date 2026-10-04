# W06 外部评测与整包验收 Feedback

## 范围与结论

本轮按 `T17 → T18 → T19 → T20` 实施，Worker 使用 Luna（max）。没有执行 Git commit、push、merge、rebase、tag、release 或工作包归档。T17、T18、T20 的代码与文档边界已完成并有本地证据；T19 的真实服务、官方评分、POSIX 和人工安装验收仍缺条件。因此代码实施可交付，整包仍不能宣称完成，也不能自动归档。

## T17：SWE-bench 预测与安全 Trace

- 新增 `eval/swebench.py` 薄适配，调用 `eval/execution.py` 的正式 Headless Application 链路，不读取 gold patch，也不引入官方 SWE-bench harness 依赖。
- 输入为外部实例工作目录、题面和模型引用；每个实例使用独立 Eval 根目录，基线快照和结束快照计算实际 unified diff，包含新增文件。
- 预测 JSONL 每行严格包含 `instance_id`、`model_name_or_path`、`model_patch` 三字段；Trace 输出会移除秘密、图片字节、原生 payload、裸 bytes 和 bearer/API key 形态。
- 实际 Patch 快照排除评测运行时自动生成的 `.uthcode/permissions.toml`，但保留外部实例中的其他文件和新增文件。
- `eval/execution.py` 增加显式 `allow_external_workspace` 适配，使外部仓库只能作为当前尝试的 workspace，home 与 artifacts 仍在 Eval 根目录；搜索 API key 也进入统一脱敏值集合。
- 新增 `tests/eval/test_swebench_adapter.py` 覆盖三字段、实际新文件 diff、实例隔离及 Trace 脱敏。

## T18：正式入口与接缝

复核了 Core、Application、Headless Eval 和 Desktop 的现有入口，新增评测适配复用 Application/Headless 主链，没有新增演示 runtime 或 Renderer 直连工具。为适应当前真实目录约束，修正了一个 runtime 测试的临时 Git 工作目录创建；同步修正 file read 结构化 details 与 CLI 临时工作目录测试断言/前置条件。新增适配未改变 Tool、Provider、Permission、Session 或 Desktop 的既有职责边界。

## T19：已完成的本地/打包证据

以下命令均在 `re-uthcode` 环境或 Desktop 目录执行：

```text
conda run --no-capture-output -n re-uthcode python -m pytest tests/eval/test_swebench_adapter.py -q
3 passed

conda run --no-capture-output -n re-uthcode python -m pytest tests/eval/test_eval_execution.py -q
12 passed

conda run --no-capture-output -n re-uthcode python -m pytest tests/eval/test_swebench_adapter.py tests/eval/test_eval_execution.py -q
15 passed in 8.74s

conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py tests/test_application.py tests/test_application_runs.py tests/eval/test_eval_execution.py tests/eval/test_swebench_adapter.py -q
92 passed

conda run --no-capture-output -n re-uthcode python -m pytest tests/test_w06_integration_delivery.py -q
13 passed

conda run --no-capture-output -n re-uthcode python -m pytest tests/test_application_runtime.py tests/test_builtin_file_tools.py tests/test_builtin_process_tool.py tests/test_builtin_search_tools.py tests/test_cli.py -q
228 passed, 2 warnings in 21.03s

conda run --no-capture-output -n re-uthcode python -m pytest tests/eval/test_swebench_adapter.py tests/eval/test_eval_execution.py tests/test_application_runs.py tests/test_w06_integration_delivery.py -q
80 passed in 21.71s
```

两条 warning 来自既有 Windows asyncio subprocess transport 在回收时的 `PytestUnraisableExceptionWarning`；该命令退出码为 0。此前一次受有界等待约束的 `pytest -q` 在约 58% 后长时间无进展而被中断，之后 `pytest --maxfail=1 -vv` 定位到不存在临时 workdir 的测试并已修复；本轮没有再次启动全量 pytest。

Desktop 侧先设置了 `$env:UTHCODE_PYTHON='C:/Users/93445/miniconda3/envs/re-uthcode/python.exe'`。`npm run typecheck` 通过；`npx tsx --test --test-name-pattern 'runtime|process|close|background' tests/runtime-process.test.ts` 为 6 passed，`--test-name-pattern 'attachment|artifact|preview' tests/renderer-attachments.test.tsx` 为 4 passed，`--test-name-pattern 'settings|configured|effective|source' tests/renderer-settings.test.tsx` 为 2 passed。`npm run package` 与 `npm run make -- --platform=win32 --arch=x64` 均成功，runtime smoke 和 Electron x64 make 产物构建均通过。

## T20：文档与旧路径清理

同步了根 README、`eval/README.md`、getting started、`docs/Tools.md`、A04 Orchestration Context、core-design README 和 `docs/Context-Index.md`，补充当前 SWE-bench 适配和 Headless 入口事实，并明确评测适配器不属于产品 Tool Registry。OutstandingDebtList 经核对没有因本轮产生新的后置能力欠账。定向搜索未发现活动的 `max_iterations`、`AgentLoopConfig` 或旧 communicate-only 执行链；历史 Feedback 与冻结包内容未改。新增和修改文档通过 UTF-8 guard，Markdown fence 与 `git diff --check` 通过。

Checklist 只将有当前证据的 A25、A27、A29 以及 T17、T18、T20 核对项由 `[ ]` 改为 `[x]`。冻结检查：

```text
conda run --no-capture-output -n re-uthcode python C:/Users/93445/.codex/t11_check_frozen.py
PASS: 10 frozen files unchanged except permitted checklist completion marks
```

## 保留未完成项与风险

- A02：真实三协议 Provider 图片理解、端点/模型/SDK 证据未运行；等待用户配置后再测。
- A10/A15：Windows packaged 产物已构建并通过 smoke，但四格式/PDF 页图、PTY、中文 ANSI、stdin、停止/关闭仍未做安装后的人工验收。
- A12：POSIX PTY 条件不可用；WSL 仅有 Python 3.14 且没有 `re-uthcode`，未建平行环境。
- A18：真实 Tavily 查询→Fetch 未运行；没有请求、读取或打印密钥。
- A26：没有真实 SWE-bench Lite 实例和官方 harness 评分，不能记录 resolved 或伪造评分结果。
- A28：需要真实 Provider 的截图+文档→Patch→失败测试→日志修复→重跑→图片→产物联合链路未运行。
- A24 的人工产物点开仍按 W05 保持未完成。

因此 T19 只完成了可用的本地、定向和打包构建验证；缺少上述必需条件时，W06 不把整包标记为已验收，不归档。

## 返工 1：Terra 首轮 2P1 修正（2026-09-14）

Terra 首轮指出原实现用 bytes 快照与 `difflib` 拼接 Patch，无法可靠表达 Git binary、rename、mode、symlink 和 Windows autocrlf 语义；同时外部实例运行前没有拒绝用户已有 dirty checkout。本段只追加当前返工事实，前文历史结果与冻结需求文字保持不变。

- 删除 bytes 快照/difflib Patch 链，新增真实 Git 生成路径：保存 clean 检查时的 `HEAD`，用独立临时 `GIT_INDEX_FILE` 执行 `read-tree`、`git add -A` 和 `git diff --cached --binary --full-index --find-renames --find-copies`。实现不写用户 index，也不清理或回滚用户实例工作区；Git 正常尊重 `.gitignore`。
- 基线不存在时只排除评测运行时自产的 `.uthcode/permissions.toml`；基线已有的同名 tracked 业务文件不排除。标准 Patch 保留新增/删除、binary、rename、mode、换行和平台可用 symlink 信息。
- `run_swebench_instance` 在创建 Attempt、读取题面和调用 Provider 前执行 `git status --porcelain=v1 --untracked-files=all`；发现 tracked、staged 或未被 `.gitignore` 忽略的 untracked 改动时抛出明确 `EvalExecutionError`，dirty 测试确认 Provider builder 调用次数为 0。没有读取 gold patch。
- 旧两实例测试改用不同的外部 Eval root，因为现有 root marker 按源仓库绑定；没有放宽该隔离合同。

返工定向验证：

```text
conda run --no-capture-output -n re-uthcode python -m py_compile eval/swebench.py
通过

conda run --no-capture-output -n re-uthcode python -m pytest tests/eval/test_swebench_adapter.py -q
5 passed in 5.96s

conda run --no-capture-output -n re-uthcode python -m pytest tests/eval/test_swebench_adapter.py tests/eval/test_eval_execution.py tests/test_application_runs.py tests/test_w06_integration_delivery.py -q
82 passed in 22.02s

conda run --no-capture-output -n re-uthcode python -m pytest tests/test_architecture_boundaries.py tests/eval/test_swebench_adapter.py tests/eval/test_eval_execution.py tests/test_application_runs.py tests/test_w06_integration_delivery.py -q
105 passed in 29.75s
```

`test_model_patch_is_standard_git_patch_and_applies` 在临时仓库中覆盖 CRLF 文本、binary、新增、删除、rename、mode 与 symlink；对应用临时 clone 执行 `git apply --check --binary` 及应用后内容/mode 校验。Windows Git checkout 若不能物化 symlink 则按平台能力 skip；当前环境该路径可通过。`test_dirty_external_instance_is_rejected_before_provider` 同时准备 tracked 修改、staged 文件和 untracked 文件，并确认未调用 Provider。原有 Headless、三字段、Trace、isolation 证据仍有效。

本轮同步更新根 `README.md`、`docs/Tools.md`、`eval/README.md`、`docs/context/A04-Orchestration/Orchestration-Context.md`、`docs/user-manual/getting-started.md` 与 `docs/Context-Index.md`；Context Index 的 `snapshot_date` 和 `status_snapshot` 均为 `2026-09-14`。未执行全量 pytest、真实 Provider/Tavily、官方 harness、POSIX 或人工 packaged 验收；仍保持整包 `not_implemented`，不提交、不归档，交由 Terra 复审。

## 总控审核收口（2026-09-14）

Luna（max）完成 W06 与一轮返工，Terra（high）第二轮审核 PASS。标准 Git patch 可应用性与 clean baseline 两项 P1 均关闭。Reviewer 在临时 clone 验证 CRLF、二进制、新增删除、重命名、mode 和平台支持的 symlink，真实 index 保持不变；适配器复跑 5 passed in 7.17s，py_compile 通过。Worker 返工架构/Eval/W06 组合 105 passed，较窄 Eval/W06 82 passed；详细命令见返工记录。此前 package/make 成功仅代表标准构建和 smoke，不等同安装后人工验收。未再次宣称全量 pytest 通过。

W01—W06 均完成代码实施与独立审核。A02/A10/A12/A15/A18/A24/A26/A28 及依赖它们的整包验收边界仍需真实 Provider/Tavily、POSIX、官方 harness 和人工安装环境，保持 Checklist 未完成与整包 not_implemented，不归档。用户已明确先完成代码、配置后再测真实服务。

## 用户确认的验收缺陷修复与附件交互改造（2026-09-20，实施中）

用户在只读自检和真实 Desktop 模型测试后明确批准追加修复计划，并要求实施。此次范围包括工具图片引用契约、附件增删布局报错、就近且可操作的错误提示、图片默认缩略图和双击缩放弹窗、文件右键菜单、Office/PDF 系统打开、Markdown/代码右侧只读画布、ApplyPatch 格式提示及已确认的权限状态投影缺陷。冻结的需求、Spec、Tasks、Prompt 和 Checklist 文字保持不变；本段不把新增验收要求回写冻结文件，也不宣称整包验收完成。

自检确认：Qwen 可识别用户直接上传的图片，但正式工具工厂遗漏 `asset_ref` 使 ViewImage 图片/PDF 页图失败；附件高度变化可触发 ResizeObserver 警告及开发环境全屏遮罩，后端仍可继续；非视觉模型拒绝图片时草稿保留，但提示位于时间线上方，当前视口看不到。原会话的提示词重复注入尚未得到请求证据支持，本次新请求只观察到一条 system，不能据此排除历史问题。

总控先补充兼容协议回归：两个相同 reasoning chunk 均保留，formal 内容和原生 carrier 各形成一次；再次发送历史只包含一条 system、一条对应 assistant，reasoning 内容保持两段而不是被去重或再次翻倍。不修改 Provider 去重逻辑。

```text
conda run --no-capture-output -n re-uthcode python -m pytest tests/test_context_compiler.py tests/test_openai_compat_integration.py -q
新增测试前：34 passed, 1 skipped in 4.12s

conda run --no-capture-output -n re-uthcode python -m pytest tests/test_openai_compat_integration.py -q
新增并加强回归后：19 passed, 1 skipped in 2.24s
```

服务、Desktop 实施及独立审核仍在进行，实际提交、组合测试、当前构建和 Computer Use 复验结果在后续追加；此时不勾选未验证项目。

### 工具组独立审核（2026-09-21）

Luna 完成正式工厂图片引用、ApplyPatch 描述/错误中的严格标记、Bash 等待参数与公开下限对齐。Terra high 独立审核通过，确认本组不依赖尚在施工的预览/系统打开新 API，可以独立提交；原始附件和 PDF 页图由真实 AttachmentService 与正式工具工厂组合回归。总控补充的 compatible native/formal 回放回归同时通过。审核未发现需返工的工具组问题。

Reviewer 实际执行：

```text
conda run --no-capture-output -n re-uthcode python -m pytest tests/test_image_tools.py tests/test_builtin_process_tool.py tests/test_process_sessions.py tests/test_process_application_lifecycle.py tests/test_openai_compat_integration.py
186 passed, 1 skipped in 20.78s

conda run --no-capture-output -n re-uthcode python -m pytest tests/test_patch_tool.py
4 passed in 0.52s

conda run --no-capture-output -n re-uthcode python -m pytest tests/test_application_tools.py tests/test_builtin_file_tools.py
29 passed in 0.96s
```

本组不包含未完成的附件预览服务和 Desktop 界面改造。工具真实模型复验仍待后续总控 Computer Use，不将上述离线回归代替真实识图或整包验收。

### 修复中间态定向验收（2026-09-21，尚未收口）

工具组已通过 PR #115 合并，合并提交 `a422303`。附件服务与 Desktop 新交互仍处于未提交的实施中状态，本轮检查不代表独立审核通过或整包通过。

总控执行 `conda run --no-capture-output -n re-uthcode python -m pytest tests/test_attachments.py tests/test_desktop_artifacts.py tests/test_desktop_bridge.py tests/test_architecture_boundaries.py -q`，结果为 `121 passed in 15.50s`。后续相关修改需要重新验证受影响部分。

总控亲自通过 Computer Use 在开发 Electron 中导入用户指定的 2.7 MB 批次闭合图片，确认导入后输入区显示缩略图；双击打开独立图片弹窗，滚轮从 100% 放大至 112%，拖动平移和 Escape 关闭均有效。DeepSeek Pro 图片单独发送被拦截，提示在输入区可见且附件保留。本轮未调用视觉模型，不把 UI 检查当作真实模型识图通过。

仍待修复：缩略图实际约 42px，未达到批准的约 160px 展示；常驻省略号按钮和菜单展示仍需按右键交互收敛；中文界面显示英文 Session resumed；非视觉模型提示不应引导用户仅开启图片能力声明，而应选择实际支持图片的模型并说明草稿保留。以上已反馈给原 UI worker。历史恢复、多图换行、系统打开、只读画布、完整布局复验和当前构建验收仍未完成。

原 Luna / max 和 Terra / high 执行曾因额度中断；用户确认额度恢复后，已向原 worker 和 reviewer 发起继续任务，维持原审核流程，不以总控自检替代独立审核。
### Qwen 三条图片路径真实复验（2026-09-21）

总控亲自通过 Computer Use，在测试 Session `b030d600f7f24cff88347ebf1210e161` 从 DeepSeek Pro 切换到 `qwen3.6-flash`，保留原图草稿后成功发送。Turn `deb2674e0d15473bb643b44f7ea29ffb` 正确返回“错误也闭合”“Steering跳过也闭合”“每次只处理一个”“取消也要补齐结果”。

随后 Turn `722b534bfc944228a5165a493d2fd71e` 实际调用 `ViewImage(path=visual.png)`、`ReadDocument(path=sample.pdf,page=1)`、`ViewImage(path=sample.pdf,page=1)`。本地 transcript sequence 35/36/40 记录上述调用，37/38/41 对应结果均为 `is_error=false`；模型正确报告本地图和 PDF 页图中的 `AUDIT 7319`、左侧红色正方形、右侧蓝色圆形。没有使用 Bash、联网或修改文件。以上补齐当前 compatible 协议 Qwen 的三条识图路径，不替代 Anthropic/Responses 协议验证。

另观察到发送开始时权限选择器短暂显示“不可用”、结束后恢复“自动”，已通知 UI worker 定向复核同一 Run 的状态投影。ApplyPatch 未额外教授格式的真实调用、最终 UI 及构建验收仍待完成。
### ApplyPatch 真实工具说明复验（2026-09-21）

总控重启开发 Electron，恢复上述 Session 后，通过 Computer Use 要求 Qwen 先读取临时验收目录中的 `patch-target.txt`，仅使用 ApplyPatch 将 `status=verified` 改为 `status=verified-again`，再读取核实；请求未给出补丁格式、标记或示例，该 Session 此前没有人工教授补丁格式的消息。

Turn `733de68e57c0450ab066b60ef094ef9e` 的 transcript sequence 47/51/55 分别为 ReadFile、ApplyPatch、ReadFile，48/52/56 对应结果均 `is_error=false`。唯一一次 ApplyPatch 调用即包含正确的 `*** Begin Patch`、`*** Update File: patch-target.txt`、`@@`、增删行和 `*** End Patch`。总控直接读取测试文件，结果确为 `status=verified-again`。未使用 Bash 或其他写文件工具，无格式纠错重试。此项为当前 Qwen compatible 的真实调用证据，不代表所有模型均能首次正确调用。
### 服务组审核与 Git 收口（2026-09-21）

Luna 完成服务组，Terra 关闭文本截断硬上限和模型产物说明 finding 后正式审核 PASS。Reviewer 完整服务/Bridge/Command/Runtime/架构组合为 `150 passed in 17.32s`；最终产物说明修正后 `tests/test_application_runtime.py tests/test_desktop_bridge.py` 为 `92 passed in 6.33s`。确认默认图片预览 data_url 保留、新增 mode/DTO 不影响旧 Desktop，可独立合并。

总控只暂存审核允许的 13 个 Python/测试/W02 文件，diff --check 和 W02 UTF-8 检查通过，提交 `eed7ec5`，推送原 T11 分支并通过 PR #116 合并，合并提交 `775f4a0`。已将本地 T11 快进到该合并提交；Desktop 和其余文档改动仍未提交，待独立审核与实际验收。没有修改冻结工作包文字或归档。

### 历史附件归属补修与独立合并（2026-09-22）

总控在恢复测试 Session 后发现用户图片消失并出现空“引导”项；结合真实 Transcript 定位到正文与图片属于相同 message_id，却因 turn 级 user_seen 被分配了不同 replay kind。Luna 修复 Application 同消息 part 归属，Terra 审核通过，真实持久化、重启 resume 和 history.page 回归保留真正 steering 的语义。Desktop 仍需将同消息正文和附件组合显示，不把服务回归当作 UI 恢复通过。

本组同时补齐 ref-only attachment.copy_path Bridge 与模型可见产物链接编码说明。Worker 执行 history/bridge/runtime/architecture 组合 119 passed in 13.73s，attachments/session authority 32 passed in 7.55s；总控此前执行 bridge/runtime/architecture 115 passed in 16.83s。State 当前事实和 W02 Feedback 的 UTF-8 检查通过。仅暂存这组 8 个文件，提交 f86da60，经 PR #117 合并为 b9f3eb5，本地 T11 已快进。

Desktop 中间态 typecheck 通过，定向附件/聊天/状态/preload 检查仍有 3 项失败，已交原 Worker；错误边界仅写 DevTools 而未进入诊断记录的缺口也已退回修复。当前开发窗口附件导入观察与并行热更新重叠，须在稳定版本重验，不据此宣称导入或全屏报错已修复。冻结文字保持不变，整包仍未通过。

### 真实画布与系统打开复验、后续代理调整（2026-09-23）

上一轮总控 Computer Use 发现正式 App 附件 DTO 转换丢失 text，导致 Markdown 双击无操作；交 Worker 补回后，使用 preview-audit.md 实际验证右侧渲染、源码切换、拖拽调宽和关闭。画布打开后会覆盖聊天正文及发送按钮的问题仍未通过，已交回修改为共享右侧布局。sample.docx 双击已启动系统 Word，标题对应测试文件；Office 订阅登录提示阻挡进一步内容核对，未操作认证流程，不能写成 Office 内容验收完成。

用户明确后续实施代理改为 GPT-6 Luna / max，审核验收代理改为 GPT-6 Sol / medium，总控继续亲自 Computer Use。当前仅 PR #115/#116/#117 已完成相应独立合并，Desktop 改动仍待最终审核、标准构建和界面验收；不修改冻结文字，不改变尚未完成的整包结论。

### 正式历史附件 DTO 与重启复验（2026-09-23）

总控真实窗口确认 PR #117 的同消息 part 归属修复仍不足以恢复图片：Application 历史投影只含 Core ImagePart 引用，缺少 Renderer 要求的真实名称、大小与 opaque ref。GPT-6 Luna / max 在现有 AttachmentService 内补齐投影，generation 仅组合调用；缺失附件返回局部 available:false，不伪造名称或大小，不丢同消息正文，不内嵌图片 data_url。GPT-6 Sol / medium 对 Python 组独立复审 PASS。Worker 执行 history bridge、attachments、architecture boundaries 合计 38 passed in 14.00s，history bridge 单独 4 passed in 1.67s，W02 UTF-8 检查通过。

总控完整关闭并重启开发 Electron，恢复 Session b030d600f7f24cff88347ebf1210e161，原 2,823,713 B 图片已在用户消息正文之前显示约 160px 缩略图、真实文件名和大小，没有空引导项。但双击独立弹窗后图片仅约 38px；定位到旧 `.timeline-attachment img` 宽泛后代样式污染嵌套弹窗，Composer 同类样式也需收窄，已退回原 Worker 修复并交原 Reviewer 复审。图片弹窗尚未通过本轮验收。

Desktop 新一轮完整 npm test 为 250 passed、1 failed、1 cancelled：离线 Runtime 请求 20s 超时及后续 bundled Runtime smoke 120s 超时。使用相同 re-uthcode Python 单跑这两项分别通过（1 pass、1 pass），未放宽 timeout；完整重跑进行中，不能将此前 252 passed 作为当前修改全部通过的证据。旧长驻开发窗口导入 Markdown 后未显示附件，仍需在完整重启后的稳定版本复验，不据此宣称链路已恢复。
### 历史 DTO 服务组 Git 收口（2026-09-23）

仅暂存历史 DTO 服务、集成存储、真实历史测试与 W02 Feedback 共 5 个审核文件，diff --check 与冻结文件检查通过。提交 c2dac39，推送 T11-Agent能力补齐，通过 PR #118 合并为 caec630；本地 T11 已快进至合并提交。Desktop 与其余文档仍未提交。

Python 稳定后 Desktop Worker 原样重跑完整 npm test，结果 252 passed、0 failed、0 cancelled（约 91s），此前两项超时均已单跑通过，未放宽 timeout。该结果早于随后为 Computer Use 发现的弹窗 CSS 污染进行的修正，后者仍需定向回归与真实窗口复验。
### Desktop 实现组复审与关键窗口复验（2026-09-23）

GPT-6 Luna / max 删除被替代的附件祖先 img 固定尺寸规则及旧 fallback class，弹窗图片使用自身 auto 尺寸与窗口内 90% 上限。最终 typecheck、history App 集成、modal CSS 与 multipart reducer 定向回归通过，完整 npm test 为 253 passed、0 failed、0 cancelled、0 skipped（约 107.3s）。GPT-6 Sol / medium 独立审核本实现组 PASS，无待修 finding；该结论不替代当前构建和整包剩余验收。

总控亲自 Computer Use：重启后的 Markdown 导入正常，卡片位于输入区顶部；双击右侧渲染 Markdown-9251，切换源码显示行号，拖拽宽度约 460px 至 590px，聊天和发送按钮未被覆盖；打开画布时 Runtime 浮层消失，关闭画布后恢复。原图历史卡片双击后默认完整适应弹窗，图像约 950×600px；键盘加号从 100% 到 120%，拖动有平移，0 恢复居中适应，Escape 关闭后焦点回到原卡片。随后 Shift+F10 能打开菜单，提供预览、打开、定位、复制路径，已发送附件无移除操作。开发窗口中上述操作未出现整屏错误遮罩。

已关闭开发客户端并启动标准 npm run package；构建结果及产物窗口检查仍待后续记录。Office/PDF 其他类型、代码画布、超限文本及连续附件移除等尚未完成的真实窗口检查不因上述结果自动通过。
### 构建产物检查及用户交互增补（2026-09-24）

标准 `npm run package` 已成功完成（exit 0），re-uthcode Python 的 PyInstaller Runtime smoke 与 Electron Forge win32-x64 打包均通过。总控亲自启动 `desktop/out/UthCode-win32-x64/UthCode.exe`，历史 Session 恢复正常；Python 附件双击进入只读画布并显示行号，但实际检查发现 token 未着色、1266×793 窗口打开 460px 画布后输入工具栏逐字折行。原 Luna Worker 已补齐 Prism token 主题规则和按聊天列实际宽度触发的布局；Sol 代码复审通过，typecheck 与完整 npm test 255/255 通过，修复后的重新构建与视觉复验仍待完成。

构建产物中 Excel 附件显示绿色图标及 XLSX 标识，双击在系统 Excel 打开 sample.xlsx，实际可见 SHEET-5937 和 B2=42。PowerPoint 附件显示 PPTX 标识，双击触发 Windows 打开方式选择器；选择仅此次使用 PowerPoint 后未观察到文档窗口，不记为内容打开通过。PDF 附件双击已启动标题为 sample.pdf 的 Edge 窗口，随后 Computer Use 因无法可靠确定浏览器 URL 而强制终止，因此只记录系统应用启动，未验证 PDF 内容。上述结果不替代未完成的文件类型验收。

用户随后明确调整交互：输入区和消息图片缩略图进一步缩小，不显示图片名称、类型、大小；草稿附件必须可删除；移除粘贴附件按钮，选择附件改纯加号；文本输入区右键菜单只保留剪切、复制、粘贴、全选。已交原 Luna Worker 实施和原 Sol Reviewer 审核，图片/文件卡片的预览等操作仍沿用文件菜单。冻结需求、Spec、Tasks、Prompt 和 Checklist 文字不变，Desktop 未提交合并，整包仍未通过。

### 紧凑附件交互构建复验（2026-09-24）

总控对本轮 104px 图片、草稿直接移除、纯加号附件入口与原生四项编辑菜单改动执行标准 `npm run package`，exit 0，Runtime smoke 与 Forge 打包均通过。亲自启动构建产物后，通过加号导入用户指定的 2,823,713 B 原图，缩略图已缩小且不显示名称、MIME 或大小，右上角有移除按钮；单击成功移除，未触发预览或全屏错误遮罩。普通 Python 草稿附件也能通过直接移除按钮删除。

同一构建双击 preview-audit.py 后，画布实际可见关键字紫色、内建类型蓝色、字符串绿色及注释灰色；1266×793 窗口下约 460px 画布与约 520px 聊天列中，工具栏正常分行，发送按钮可见且无逐字竖排。前轮高亮与窄列布局 finding 在本次实际窗口中通过。

文本区右键实际只有 Cut、Copy、Paste、Select All 四项，但中文界面标签为英文，已交 Worker 增加按现有语言偏好读取的显式中英文标签。该小改后的最终构建与菜单实际行为尚待验证。附件定向测试为 17 passed，typecheck 通过；本轮完整 npm test 为 255 passed、1 failed（离线 Runtime 请求超时），同参数单跑该失败用例为 1 passed / 4.9s，未放宽 timeout；不将该次全量写为全部通过。真实剪贴板附件粘贴与最终中文菜单、剩余包级项目仍需继续验收。

### 本轮交互最终回归及串行构建（2026-09-24）

最终源码 typecheck 通过；附件定向 16 passed，Main 菜单定向 1 passed，合计 17 passed（澄清前一节“附件定向 17”的统计口径）。完整 npm test 为 256 passed、0 failed、0 cancelled、0 skipped，81.55 秒。Sol 独立复审未发现阻断 finding，复跑上述定向与 typecheck 通过。未放宽原超时参数。

总控曾把 npm test 与 npm run package 并行执行，但 windows-packaging.test.ts 会调用同一 build-python-runtime.mjs 写共享构建目录；该轮 package 返回成功后，实际客户端 Runtime 启动失败。退出后无持久 stderr 可确认具体丢失文件，因此不把共享目录冲突推断写成已证实的精确异常根因。测试结束后独立串行执行标准 npm run package（exit 0，Runtime smoke 与 Forge 通过），再由总控 Computer Use 启动产物，Runtime 就绪、原历史、模型与权限状态均正常恢复。

串行重建产物中，中文文本右键菜单仅有“剪切、复制、粘贴、全选”。总控输入未发送的菜单验收文字，经菜单全选、剪切快捷键和菜单粘贴，文字及草稿状态正常更新；随后清空测试文字。使用系统快捷键复制测试窗口图像到剪贴板，Ctrl+V 实际导入紧凑图片缩略图，未插入伴随文字；点击“×”移除成功，没有全屏错误遮罩，未发送模型请求。用户本轮增补的输入区操作已具备实际窗口证据，包级剩余验收仍保持未完成。

### 附件读取修复及会话切换重复投影定位（2026-10-03）

工具与读取服务修复经 Luna / max 实施、Sol / medium 独立审核无阻断 finding，定向 Python 41 passed、架构边界 23 passed。提交 `7ab6960` 经 PR #121 合并为 `5f1ebda`。外部文件仍通过原权限分类，只跳过不适用的项目目录指令激活；附件副本回归和 Excel A1 单格修复见 W03 本轮记录。随后三处工具说明、文档缩进与测试名称整理另待提交；此处不宣称新包或真实模型已验证这些后端修改。

总控在仍为上一版的 packaged Electron 中亲自 Computer Use 复现：已恢复的 `6de47b20261840e6a788bfa50d0e26a0` 新增一次 ReadDocument 后切换会话，记录保持正常；新建 `0175b8a994a5422fb07af6513dbf881b`，导入测试 sample.xlsx 并发送仅一次 ReadDocument 的请求，读取成功，返回 A1=SHEET-5937、B2=42，但发送后的用户行不显示附件。切到 `57f0b0bf3d1640b88dc8b3837184c752` 再返回，底部工具行不见。

完整无障碍文章列表进一步确认：记录并未删除，界面显示“有附件 user、reasoning、tool、reasoning、assistant”后，又显示“无附件 user、reasoning、空 assistant、reasoning、assistant”。工具行被合并到前半部，后半部保留重复实时投影。源码同时确认实时消息使用 UUID，而持久化消息身份由 turn_id 与起始 sequence 生成；以 message_id 匹配两者不能合并，tool_call_id 则一致。该证据已交原 Desktop Worker 修复和 Reviewer 审核，不以文本去重，不把此显示重复直接认定为模型请求重复注入。真实窗口已退出，修复后新包复验仍待完成。

### 附件测试失败格式化 OOM 修复（2026-10-04）

用户独立诊断确认，重试成功后旧测试仍要求整个页面没有 Attachments，实际命中正确的消息附件 DIV；Node 断言失败格式化会展开 React DOM 内部对象图并引发巨大分配。本轮由 GPT-6 Luna / max 只修改 renderer-attachments.test.tsx：失败后确认 Composer 中 att-1 数量为 1；成功后确认草稿数量为 0、用户消息中附件数量为 1。同文件直接 DOM/null 比较改为数量标量，保留 getAttribute 等标量检查。未修改 Runtime、产品行为、配置或冻结文字。GPT-6.1 Sol / medium 独立只读审核 PASS，无 finding。

总控在 desktop/ 使用 Node v24.15.0、NODE_OPTIONS=--max-old-space-size=256、node --import tsx --test --test-isolation=none，外部监测设置 60 秒、768 MiB 私有内存、1 MiB 输出限制（仅测试进程，未修改项目配置）：

- --test-name-pattern="App keeps an imported attachment available for retry|App localizes the image capability refusal|App moves a sent attachment" tests/renderer-attachments.test.tsx：3 passed、0 failed、0 cancelled、0 skipped；Node duration_ms 1287.212，退出码 0，外部耗时 1.374 秒，私有内存采样峰值 229.3 MiB，无限制触发。能力拒绝用例内部同时覆盖 en/zh-CN。
- tests/renderer-attachments.test.tsx 完整文件：18 passed、0 failed、0 cancelled、0 skipped；Node duration_ms 1461.3266，退出码 0，外部耗时 1.547 秒，私有内存采样峰值 201.2 MiB，无限制触发。
- NODE_OPTIONS=--max-old-space-size=512; npm run typecheck：退出码 0。

以上为磁盘修复后的真实测试结果，不是内存中替换断言的对照实验；不支持据此断言 Agent Runtime 正常运行有持续内存泄漏。完整文件中的旧导航测试仍使用相同 live/durable message_id，因此不能把其通过作为会话重复投影根因修复证据。此次阶段未执行全量 Desktop、标准构建、真实 Provider 或窗口验收；会话身份合并修复继续交原 Worker，后续最终收口另行记录。

### 四项修复最终审核、回归和串行构建（2026-10-04）

附件发送后的安全 ref/元数据立即投影到用户行，成功清除 Composer，失败保留草稿；纯附件与正文+附件均接入 turn_started 权威消息身份，timeline 不携带大图 data_url。实时/历史身份根因修复与三项审核返工见本轮 W02 追加。GPT-6 Luna / max 实施、GPT-6.1 Sol / medium 最终独立审核 PASS，无剩余实质 finding。旧附件断言 OOM 修复仍保留产品附件展示，测试失败输出使用标量。ReadDocument/ViewImage 完整附件引用、项目外物理路径不激活项目指令、Excel 单格等后端修复已由 PR #121 合并，未提交的小范围说明与测试整理也已审核。

最终实际验证（Python 使用 C:/Users/93445/miniconda3/envs/re-uthcode/python.exe，Desktop 在 desktop/）：

- python -m pytest tests/test_builtin_file_tools.py tests/test_document_tools.py tests/test_image_tools.py tests/test_project_instructions.py -q：41 passed in 4.44s，exit 0。
- python -m pytest tests/test_architecture_boundaries.py -q：23 passed in 9.87s，exit 0。
- python -m pytest tests/test_application_runs.py tests/test_history_contract.py tests/test_history_bridge.py tests/test_t09_1_context_protocol_e2e.py -q：110 passed in 18.17s，exit 0。
- NODE_OPTIONS=--max-old-space-size=256，node --import tsx --test --test-isolation=none --test-concurrency=1：renderer-state.test.ts 55/55、renderer-attachments.test.tsx 18/18、首轮 App 导航定向 1/1。NODE_OPTIONS=--max-old-space-size=512，npm run typecheck：exit 0。256 MiB typecheck 曾因堆上限不足退出，未将其当作产品泄漏或通过证据。
- NODE_OPTIONS=--max-old-space-size=512，npm test：265 passed、0 failed、0 cancelled、0 skipped、0 todo；duration_ms 99313.8063，exit 0，外部耗时 100.052 秒，进程树私有内存采样峰值 2243.5 MiB。外部 600 秒/4 GiB/8 MiB 输出限制未触发。
- 上述全量结束后串行标准 npm run package：exit 0，102.715 秒，进程树采样峰值 1787.1 MiB；随后 npm run make：exit 0，217.776 秒，峰值 1753.2 MiB。两个构建的 PyInstaller Runtime smoke 均通过 ready/status/shutdown JSONL 及 importlib.resources prompt asset。构建使用既有 Conda Python，NODE_OPTIONS=--max-old-space-size=1024，外部 1200 秒/6 GiB/16 MiB 输出限制未触发。第一次 package 的宿主丢失退出结果，只作为中间记录；以上 package 是为取得可确认结果而串行复跑的最终一次，不虚报丢失结果。

最终 make 新包：D:/project/Re-UthCode/desktop/out/UthCode-win32-x64/UthCode.exe（244440576 B，2026-10-04 16:23:15）；安装产物 D:/project/Re-UthCode/desktop/out/make/squirrel.windows/x64/UthCode Setup.exe 已生成。本轮实际启动的是最终 make 目录中的客户端，不是 9 月旧包；没有执行安装或干净 Windows 安装环境验收。

### 总控原生真实窗口验收（2026-10-04）

总控本人使用当前 computer-use skill 的 @oai/sky 原生接口，无 CDP 或子代理代验收。最终客户端在测试目录 C:/Users/93445/AppData/Local/Temp/uthcode-t11-audit-9_etvcqh 创建 Session 815bed2249f1400ab38a13da21767594，导入用户指定原 PNG（2,823,713 B）与 sample.xlsx（A1=SHEET-5937、B2=42），发送仅一次 ReadDocument、限定 A1:B2 并解释图的请求。真实 qwen3.7-flash / openai_compat / https://dashscope.aliyuncs.com/compatible-mode/v1 / openai 2.53.0 成功识别图片 FIFO、error、skipped、cancelled 闭合语义；正式 Transcript 仅一项 ReadDocument，参数为 asset_ref=attachment:815bed2249f1400ab38a13da21767594:9c113feaca2d4d82a2c46e067a6914ba、range=A1:B2，结果 A1=SHEET-5937、B2=42。没有猜文件名路径或搜索用户原表。

发送后的用户正文顶部保留 PNG 与 Excel 两个卡片，Composer 草稿清空。首次切到空白 Session 再返回，以及完整退出重启，均只显示 user、reasoning、tool、reasoning、assistant 一组，无重复用户行或空 assistant；工具位于两段合法 reasoning 之间。磁盘用户 UUID 为 1ef7491c185b453c948090509a04c39f，两个 assistant UUID 为 b4dd72a799fb4f3f9554e40b47649ba9、359c60b36d16437c9e12f2def4657110，同消息 part 共享身份。原 PNG 卡片双击，100% 原图完整适应预览弹窗；关闭正常。

另建 Session 3a5562d2004a4ba18a4b907613caaf35，正文为空，仅导入同 PNG：选 deepseek-v4-flash 后发送被 image capability 预检拒绝，对话区显示“所选模型不支持图片输入，请选择支持图片的模型。附件草稿已保留。”，输入区图片和移除按钮保留，未产生用户消息。切回原 Qwen 配置直接重试，模型成功解释图，输入区附件清空、消息区保留单一用户附件。用户默认模型最终重新核实为 __uthcode_model_3。两次发送的首个即刻截图尚为异步前一状态，下一观察已完成生成，因此真实窗口证明成功后卡片留存与无重复；“接受后、生成完成前即时投影”的精确时点由 App 定向测试支撑，不虚称已捕获该活动时点截图。新包直接项目外物理路径授权后的交互未另行实测，相关 OUTSIDE 分类、授权和指令激活修复由正式工厂 41 项回归支撑。

### 剩余验收去重及证据边界（2026-10-04）

交接时 19 个未勾选行实际为 13 组要求：A02/A10/A12/A15/A18/A26 各重复两次，共 12 行；另 T08/T14/T15/T16/T19 完成边界及 A24/A28 共 7 行。原 Sol 核对 W05 历史证据及当前不受影响逻辑后，T15 完成边界可完整复用并补勾；现剩 18 行、12 组要求，不是 18 个独立缺陷。

- A02：兼容协议的本轮真实用户图及既有本地/PDF 工具图证据可复用部分；仍缺三协议完整 SDK 请求与内容理解证据，当前没有 Responses 配置。已有 anthropic Qwen 配置不等于已完成该协议视觉验收。
- A10：本轮 packaged XLSX 真实读取和标准构建可作部分证据；PDF/DOCX/PPTX 正式读取、PDF 页图实际入模、干净 Windows/安装环境无开发隐式依赖仍缺，不能把旧系统应用启动当读取完成。Office 认证由用户自行处理。
- A12/T08/A15：既有 Windows PTY 自动化证据可复用不受本轮影响部分；POSIX isatty/输入/EOF/resize/取消与最终安装产物原生 PTY、中文/ANSI 日志、stdin/停止/关闭仍需验收。已有 WSL Ubuntu 与 docker-desktop，无需重装。
- A18：已有失败 fixture 可复用不受影响部分；真实 Tavily→静态页/PDF、URL/来源/用量尚缺，用户只需在用户配置或环境引用中配置搜索凭据，不在聊天发送密钥。
- T14：200 轮与失败/短周期/final/编辑重测/等待历史证据可复用；异常怀疑/纠偏之后人工输入的精确反例仍需核实，不能以普通 AskUser/steering 代替。
- A24/T16：已有 Main/preload/chat 自动化可复用；最终原生 Artifact 打开/定位、图片、缺失局部反馈、可执行仅定位与恶意 URI 不执行仍缺。附件预览不等同 Artifact 验收。
- A26：正式 Headless 预测与官方 SWE-bench Lite harness 实例评分尚未完成。环境预查 docker info 的 Linux engine 管道不存在；用户先启动 Docker Desktop 并等待 Linux engine 就绪，不要求重装，不把环境失败当评分通过。
- A28/T19：截图+文档→定位 Patch→失败测试→读日志修复→重跑→图片→交付物联合链仍需完整真实模型与正式工具结果，以上分段证据不能自动代替。

Checklist 只补勾 T15 的充分有效证据，冻结正文不改，T11 整包仍为 not_implemented，不归档。用户后续最小配合为配置可视觉的 Responses 模型和 Tavily 凭据、启动现有 Docker Linux engine、提供干净 Windows/安装验证条件，出现 Office 认证时自行完成；其余可在这些条件满足后复用有效证据开展定向验收。

### 活动生成中的附件投影补充观察（2026-10-04）

为补充前两次短请求完成过快的观察限制，总控在上述空白 Session eeda37b0f1014e8780ef3e55f5b81b82 导入同 PNG，发送约 2000 字图片解释请求，明确不调用工具或修改文件。首次接受后的下一原生观察仍在生成：输入区显示“向当前轮次发送引导”，截图有暂停/取消，assistant 仅输出至错误/跳过段落；无障碍用户 article 849 下已有图片 article 853，输入区正文与附件草稿均已清空，无移除附件按钮。因此当前最终新包已有“生成结束前用户附件卡片存在”的真实原生 UIA 证据；不声称截图量化了接受瞬间的毫秒延迟，精确即时 reducer 投影仍由 App 测试支撑。后续观察模型正常完成。该补充不改动此前阶段记录，不扩大为整包通过。
