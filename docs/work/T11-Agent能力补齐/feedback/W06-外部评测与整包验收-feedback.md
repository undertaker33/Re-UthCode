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
