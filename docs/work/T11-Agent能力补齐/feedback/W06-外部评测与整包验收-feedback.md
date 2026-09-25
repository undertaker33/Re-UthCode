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
