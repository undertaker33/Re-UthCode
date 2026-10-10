# T12-Desktop功能补齐与工程收敛 — Checklist

所有复选框初始未完成。Task 编号、名称、顺序与 Spec/Tasks 一致；原 R/A 编号来自源需求 §3/§8。首次派发后文字、结构和顺序冻结，只允许勾选真实完成项，证据写入同级对应 Worker Feedback。

方法：每个 Task 执行 Tasks 所列真实测试入口并记录精确命令/通过数/退出码；新增行为覆盖正常及关键失败。一次结果可支撑多项但必须标明对应项，后续修改只重跑受影响证据。目录素材/Mock/旧包通过不能代替当前真实产品验证。每项多个条件全部满足后才勾选。

## 原行为与任务映射

| 源需求行为 | 对应实施 Task | 主要验收 |
| --- | --- | --- |
| R01 | T02、T04、T07 | A01 |
| R02 | T02、T04、T07 | A02 |
| R03 | T02、T04、T07 | A02 |
| R04 | T01、T04、T07 | A03、A06 |
| R05 | T04、T07 | A03 |
| R06 | T01、T04、T12 | A04–A05 |
| R07 | T01、T04、T07、T12 | A04、A06 |
| R08 | T03、T04、T07 | A07 |
| R09 | T03、T04、T07、T10、T15 | A07–A09 |
| R10 | T03、T04、T07、T10 | A09 |
| R11 | T03、T04、T07、T10、T11 | A08、A10 |
| R12 | T05、T08 | A11–A13 |
| R13 | T05、T08 | A11–A13 |
| R14 | T05、T08、T09 | A12–A13 |
| R15 | T06、T09、T15 | A14、A16 |
| R16 | T06、T09、T15 | A15–A16 |
| R17 | T11–T12 | A17 |
| R18 | T11–T12 | A18 |
| R19 | T11–T12 | A19 |
| R20 | T07、T10 | A20 |
| R21 | T13–T14、T16 | A21 |

## 原验收与任务映射

| 源需求验收 | 主要证据 Task |
| --- | --- |
| A01 | T02、T04、T07 |
| A02 | T02、T04、T07 |
| A03 | T01、T04 |
| A04 | T01、T04 |
| A05 | T07、T12 |
| A06 | T15 |
| A07 | T03、T04、T07 |
| A08 | T15 |
| A09 | T03、T04、T07、T10 |
| A10 | T03、T04、T11 |
| A11 | T05、T08 |
| A12 | T05、T08 |
| A13 | T05、T08、T09 |
| A14 | T06、T09 |
| A15 | T06、T09 |
| A16 | T15 |
| A17 | T11、T12 |
| A18 | T11、T12 |
| A19 | T11、T12 |
| A20 | T10 |
| A21 | T13、T16 |
| A22 | T15、T16 |
| A23 | T15、T16 |

## 按 Task 验收

### T01 Session 归档元数据与持久化

Worker：W01；行为：R04–R07；原验收：A03–A04。验证入口参见 Tasks 同编号步骤。

- [x] 对真实 Session 归档→关闭 store→重新打开→恢复，核对归属、标题、模型、消息时间、内容和置顶未改变；旧 metadata 缺字段仍可读，重复 archive/restore 返回同一最终状态（A04）。
- [x] 注入 metadata 写入失败、writer 冲突和中断，确认无第二份存储、无 Transcript 删除，重新读取能反映真实最终状态；记录定向命令与结果（A03–A04）。

### T02 安全正文按需搜索

Worker：W01；行为：R01–R03；原验收：A01–A02。验证入口参见 Tasks 同编号步骤。

- [ ] 两个已登记项目同名 Session，分别以标题、首消息、很久以前公开正文匹配；空查询/无匹配/有界结果正确，未知或未登记项目被拒绝，catalog/search 不创建 Runtime（A01）。
- [x] 归档仍命中并带标记；损坏/无权限/消失只产生局部反馈；查询取消及时停止，未公开 reasoning、ToolResult、日志与测试秘密标记不进入结果（A02）。

### T03 General 最小 Application 组合

Worker：W02；行为：R08–R11；原验收：A07–A10。验证入口参见 Tasks 同编号步骤。

- [x] 不选 Coding Project 即可创建/持久恢复 General Session；跨 mode 引用拒绝，旧无标签 Session 仍归 Coding；Prompt、Instruction 指纹和可信配置未继承项目内容（A07、A09）。
- [x] 检查首次创建、配置刷新、恢复后的实际请求及工具可见性：General 默认工具为空且无 Coding 指令，Coding 工具/权限及 Headless 正常与关键失败路径保持（A10）；记录架构测试结果。

### T04 Session 与 General Desktop 协议接入

Worker：W02；行为：R01–R11；原验收：A01–A07、A09–A10。验证入口参见 Tasks 同编号步骤。

- [x] 空闲目标可归档且无关 Turn 保持；目标 active、paused、pending interaction、compact 均受控拒绝，重复请求幂等且不取消任务（A03）。
- [x] 移除再登记同一 Project 后归档/内容仍在；跨 mode/未知 project 引用拒绝，搜索取消及迟到响应按请求/操作身份隔离，不篡改 Bridge 当前 owner；无任意路径读取。Renderer 选择隔离另验 T07（A02、A04）。
- [x] 从正式 RPC 创建/恢复 General 并切回 Coding，Coding 后台 Turn/event owner 不变；Main/preload 精确白名单、参数负例及已有 IPC 来源检查通过（A07、A09–A10）。

### T05 过程回放与安全明细来源

Worker：W02；行为：R12–R14；原验收：A11–A13。验证入口参见 Tasks 同编号步骤。

- [x] live/replay 保持 Message/Turn/ToolCall 归属和公开进度/最终正文区分；旧无时间记录为 unavailable，terminal 后计时不继续增加（A11–A12）。
- [x] 工具输出续读有界脱敏且绑定所属 Session/ref；超限、缺失、旧记录有局部不可用说明；ToolProgress 不进入 Transcript/RunState/Provider request（A13）。

### T06 变更摘要与当前只读 Diff 出口

Worker：W02；行为：R15–R16；原验收：A14–A16。验证入口参见 Tasks 同编号步骤。

- [x] 真实受控 Git 工作区内修改/新增/删除/重命名及非 Git 场景，当前 diff 路径、红绿行来源和有界状态准确；untracked 无虚构增删统计（A14）。
- [x] 历史摘要只来自可核实正式写入或观察；单一 git status、Bash 文字、模型声明、并发外部修改不被归到确定 Turn；没有历史快照时不产生历史完整 Diff（A14）。
- [ ] 工作区之外预览需原有单文件授权，工具 ref 与 Session 隔离；文件/图片/Markdown/日志丢失或拒绝均为局部反馈（A15）；packaged 操作留 T15 验收（A16）。

### T07 双模式导航与搜索归档界面

Worker：W03；行为：R01–R11；原验收：A01–A07、A09。验证入口参见 Tasks 同编号步骤。

- [ ] 两个 Coding 项目同名/收起/旧历史及 General 查询结果分别进入正确 Session；取消、移除项目、迟到回包不覆盖新选择，归档结果明确标记（A01–A02）。
- [ ] 归档当前会话安全离开、普通/Recent 不再显示且未提交输入仍归原主；重登记项目不丢归档状态，Session 菜单真实可用（A05–A06，联合 E2E 留 T15）。
- [ ] Coding/General 互切及 Settings 返回后，选择/历史/未发送输入独立；Coding 后台运行、审批仍能返回处理，General 无项目也可新建/恢复（A07、A09）。

### T08 连续过程分组与真实计时

Worker：W03；行为：R12–R14；原验收：A11–A13。验证入口参见 Tasks 同编号步骤。

- [ ] 连续七个工具含跨 batch 形成一个默认折叠组；插入公开说明、公开 reasoning、用户消息、审批/问答/计划审阅、关键失败分别切组，最终回答直显（A11）。
- [ ] live/replay/paging 合并与取消/切回/重载稳定，ToolCall 不重计；真实运行跨度可见，缺历史时间/输出明确不可用（A12–A13）。

### T09 统一右侧文件与日志审阅

Worker：W03；行为：R15–R16；原验收：A14–A16。验证入口参见 Tasks 同编号步骤。

- [ ] 从聊天入口查看真实 diff/文本/Markdown/图片/安全附件/日志，tab 切换和关闭有效，内容安全有界、截断可见，缺失/无权局部反馈（A15）。
- [ ] 切 Project/Session/mode 后旧预览不串台，历史摘要与当前 diff 时点分开，审批/错误不因打开右栏隐藏（A14–A16）；实际 packaged 对照在 T15 完成。

### T10 Composer 控制命令与草稿所有权

Worker：W03；行为：R20、R09–R11；原验收：A20、A09。验证入口参见 Tasks 同编号步骤。

- [ ] Coding 非空文字+一份未提交附件，开 picker/选模型/选权限的成功、业务失败、RPC 失败和取消均保留同一草稿且不发 turn.start；仅成功真实提交清对应草稿（A20）。
- [ ] General 文本与 Coding 文本/附件切换 Session/mode 后各归其主，迟到命令不清新 owner 或后续编辑；活动门禁、仅附件发送与发送失败回归保持（A09、A20）。

### T11 配置单项持久化与安全边界应用

Worker：W04；行为：R17–R19；原验收：A17–A19。验证入口参见 Tasks 同编号步骤。

- [ ] 单字段/关联组写回及重读一致；连续快速编辑和另一字段写入不丢值；持久化失败保留待重试，写后应用失败分别可观察且不虚报成功（A17、A19）。
- [ ] 有前台/后台/跨项目 active/compact 和活进程时连续改配置，不取消/重绑/逐次 child 重启；边界到来应用 pending，进程保留旧快照，General 无工具（A18、A10）。
- [ ] SecretValue 的 repr/str 脱敏且不可序列化；安全 DTO/Prompt/Session/Event/日志中无测试 Key，未编辑 literal/env 表达保持；项目提权/Provider 重定向拒绝，用户默认模型只改顶层字段（A19）。

### T12 Settings 自动保存与归档管理

Worker：W04；行为：R06–R07、R17–R19；原验收：A05、A17–A19。验证入口参见 Tasks 同编号步骤。

- [ ] Settings 无全局提交按钮；现有支持字段逐项/关联组真实保存并重读，非法值保留本地错误，失败可重试，保存与应用状态区别可见（A17）。
- [ ] 连续改主题/语言/Provider/Model/搜索/工具上限/权限默认，迟到不覆盖、离开仍保有效编辑、不逐字段重启；editor-local 密钥与未编辑来源保持（A18–A19）。
- [ ] 归档页 Coding 原项目/General 分组、项目/文本过滤、恢复可操作；普通及 Recent 排除归档，侧栏无固定归档入口，恢复按原用户活动排序与置顶相容（A05）。

### T13 全仓调用证据与定点工程收敛

Worker：W05；行为：R21；原验收：A21。验证入口参见 Tasks 同编号步骤。

- [ ] 每个实际清理有六段证据与定向通过结果，删除符号精确引用检查无残留；无价值兼容/重复权威被替换，真实 CLI/TUI/Headless/安全调用者未误删（A21）。
- [ ] Python、Renderer、tests、依赖、打包各有实际盘点结果；证据不足明确不处理，未按 LOC 强拆、安全回归未削弱；维护负担判断可复审（A21）。

### T14 [接入主流程]

Worker：W05；行为：R01–R21；原验收：A01–A21。验证入口参见 Tasks 同编号步骤。

- [ ] 正式产品入口全部使用已实现 Application/RPC，未知调用拒绝，无模拟数据/假按钮/第二套 loop/history；Coding 后台任务和控制交互仍可继续（A01–A21）。
- [ ] 各 R/A 均有任务/Checklist/Feedback 证据去向；缺条件保留未勾选，旧结果若被后续改动失效则补验（A01–A21）。

### T15 [端到端验证]

Worker：W05；行为：R01–R21；原验收：A06、A08、A16、A22–A23。验证入口参见 Tasks 同编号步骤。

- [ ] 记录架构、受影响 Python 正常/关键失败、Desktop 全量 npm test 与 npm run typecheck 的精确通过数/退出码，必要构建及 Runtime smoke 指明产物来源（A22）。
- [ ] 实际 packaged 搜索→归档→重启→搜索→恢复覆盖多项目同名、General、owner 与内容保持（A06）；真实 Provider General 文本请求出现流式 delta 及最终正文，配置无效及取消受控（A08）。
- [ ] 真实受控 Git 修改后从聊天打开 packaged 当前 Diff、红绿行/路径正确；切项目/Session 无旧预览串台，历史摘要时点明确（A16）。
- [ ] Coding/General/Settings 真实 Desktop 与三 PNG/V4 对照截图；搜索、归档、字段保存和右栏可操作，窄窗/滚动/键盘焦点无明显破坏；原生输入/缩放和 CDP 证据分开，未执行条件保持未勾选（A23）。

### T16 [遗留负担清理]

Worker：W05；行为：R21及全部实际长期事实；原验收：A21–A23。验证入口参见 Tasks 同编号步骤。

- [ ] 删除/保留结果逐项可追溯，替代旧入口无残留，合理复杂性与关键安全/持久/Headless 覆盖保持（A21）。
- [ ] 相关用户手册/当前事实/Tools/核心设计/README/索引按维护映射检查且与源码一致；UTF-8 解码、replacement/乱码、fence 及内部链接检查通过，无真实秘密（A22–A23）。
- [ ] Checklist 勾选仅来自有效结果；Feedback 清楚区分完成/未验收/风险，未满足真实 A06/A08/A16/A23 等不写整包完成，能力欠账核对不把 Out of Scope 登记；不自行归档或 Git 写入（A21–A23）。
