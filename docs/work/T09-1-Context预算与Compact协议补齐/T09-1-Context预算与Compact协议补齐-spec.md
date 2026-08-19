# T09-1：Context 预算与 Compact 协议补齐 Spec

## 背景

T09 已建立持久会话、确定性 Context Compiler、Tool Result 外置和有界 Compactor，但生产运行时仍把固定 `258_000` 当作唯一预算权威，请求计数没有覆盖发送前的最终结构，原始事实与压缩视图仍共用 `CanonicalHistory/Projection`。现有 `AgentLoop` 已经能够 await sync/awaitable `request_preparer` 与 overflow handler，本包只复用该合同，不重复设计异步协议。

本包在模块化单体、单 Agent ReAct Loop、Session single-writer 和安全配置边界内，原位完成动态限制、多维 Hard Gate、Transcript/Timeline、L1-L5、手动 Compact、一次 overflow recovery、证据回读与正式入口收口。

## 目标

- 模型限制只来自用户显式配置和可选的可靠 Provider 运行时 metadata；不维护 bundled model metadata、本地型号表、模型目录或硬编码默认窗口。
- 项目配置只能保留或收紧用户配置的 `context_window`，不能补造用户缺失值，也不能放大用户可信上限。
- 分别表达配置运行输入上限、Provider 最大输入、Provider 最大输出、可选 combined-context 上限；按各维语义独立验证，不折叠成单一 `E`。
- 将 proactive Pressure Estimate、发送前 Preflight Safety Count/Estimate 与 Provider overflow 最终裁决分层；所有真实模型调用发送前都 fail closed Hard Gate。
- 以 Transcript 保存当前 Session 已闭合原始事实，以 append-only Timeline 保存派生语义视图，并用最后提交 checkpoint 确定有效状态。
- 建立确定性 L1-L3、复用当前主模型的 L4、Timeline Aging L5、bounded catch-up、manual compact 和一次 overflow reduction/retry。
- 硬切 Session v2；不迁移、不双读写、不保留旧 Projection 兼容层。

## 能力清单

### T01：动态模型限制与确定性请求安全链

- `ModelProfile.context_window` 是用户可显式配置的正整数输入运行上限；若用户未配置，只有可靠 Provider input metadata 能建立本次可运行上限，两者都缺失时初始化或发送前明确失败。
- 项目层 `context_window` 只有在用户层已有该值且不大于用户值时才允许；Provider metadata 也只能收紧最终 operating input limit。
- Provider limits DTO 分开保存 `max_input_tokens`、`max_output_tokens` 和可选 `max_combined_tokens`；未知维度保持未知。
- 不引入 bundled metadata；Anthropic 可通过 fake client 测试可靠运行时 limits，OpenAI/Compat 在无可靠来源时不伪造。
- Pressure Estimate 用于 Auto Gate；Preflight Safety Count/Estimate 用于 Hard Gate；两者共享集中 uncertainty/safety allowance，但不声称近似计数数学精确。
- 最终候选请求的 instruction、messages、tools、已知 framing、requested output reserve 按维度验证；input limit、output limit、combined limit 各自成立才可调用 Provider。
- 在同一任务内接通正式 `Application -> Context Compiler -> request_preparer -> AgentLoop -> ProviderPort` 链，完成 L1-L3、rebuild/re-gate，并删除固定 258K authority。

### T02：Transcript、Timeline 与 Session v2 一次性硬切

- Transcript 成为当前 Session durable closed semantic fact authority；Timeline 只允许 Fine entry、Epoch macro summary、Active checkpoint 三类产品记录。
- 成功派生 transaction 先写派生记录、最后写 checkpoint；loader 忽略 checkpoint 后未闭合尾部。
- fresh Session 使用 `transcript.jsonl`、`timeline.jsonl`、`runtime.jsonl`、metadata、lock 与 tool-results；old v1 明确 incompatible。
- 同一任务迁移 Context compiler、Application generation/history/session 与所有生产调用方，并删除 `CanonicalHistory`、`Projection` 和 `history.jsonl` 新写入路径。
- 保留 strict sequence、完整 Tool semantic group、single writer、fsync、reconciliation、quarantine 与 close/reopen recovery。

### T03：生产 L4 与 bounded catch-up

- L4 使用 active Turn 冻结的主 Provider/model/limits，idle manual 使用当前选择；Compact request 独立、tool-free、bounded。
- 每个 Compact request 自身先通过 Hard Gate，不递归触发 Auto compact。
- 结构化结果按 covered Turn 形成 Fine entries，校验通过后 checkpoint 最后提交。
- 一次编排允许多个有界 epoch；每次 commit 后 rebuild 并重做 Gate。
- no-progress、repeated failure、no-safe-epoch、cancellation 都有限且可观测，不产生伪提交。

### T04：L5 Timeline Aging 与 HistoryRead

- Fine Timeline 超预算可独立触发 L5，不依赖普通请求先达到 Auto pressure。
- L5 只选择旧完整 epoch，并从 raw Transcript refs 重新取证，禁止 summary-of-summary。
- 成功 L5 追加 macro 与最后 checkpoint，在 logical view 中 supersede 旧 Fine entries，不删除物理记录。
- HistoryRead 只读 active Session 的精确 opaque Transcript ref，结果有界，不搜索、不跨 Session、不递归外置。

### T05：Application Compact 生命周期与 overflow recovery

- 下一普通调用前 durable append 已闭合事实，terminal tail 补齐余下闭合事实；不持久化 open continuation。
- active Turn 冻结 Provider、model、input/output/combined limits 与 tools；运行中 `/model` 只影响下一 Turn。
- manual compact 与自动治理复用同一 Application orchestrator；低 pressure 可执行，无候选为 success no-op。
- ordinary Provider overflow 最多执行一次 `reduce -> rebuild -> re-gate -> retry`；第二次 overflow 停止，不反向修改任何窗口事实。
- 直接 Application/Headless 路径已可运行、测试、回退，尚不依赖命令或 TUI 接入。

### T06：[接入主流程] 命令、TUI 与正式入口收口

- `/compact`、`/status`、CLI/TUI/bootstrap 正式接入 T05 Application 边界。
- 复用现有 AgentLoop sync/awaitable 合同，只对 Application command dispatcher/TUI 做所需 async adaptation，不新增第二套 preparer/overflow protocol。
- CLI、TUI、Headless 不拥有 Context 编排；旧同步-only compact 路径与旧入口在同一任务删除。

### T07：[端到端验证] Diagnostics、Eval、文档与回归

- status/diagnostics 分别展示 configured/provider/effective input、provider output/combined、count source、uncertainty、Auto/Hard、Timeline 与 outcome，不泄露正文或秘密。
- Eval 只消费公开安全 diagnostics，维持并列指标，不新增总分，不把 tuning 默认值变成产品阈值。
- 正式 Application/command/headless 入口覆盖普通、自动、手动、overflow、resume、HistoryRead 与失败路径。
- 用户手册、Core Design、Tools、A03/A04、索引与当前代码事实同步。

### T08：[遗留负担清理] 删除阶段性与兼容逻辑

- 删除固定 258K runtime authority、Projection/CanonicalHistory 生产语义、old Session 新写入、旧阶段文案和重复 Context 编排。
- 确认 bundled official model metadata 相关设计、实现、测试和欠账持续不存在；该路线已取消，不重新登记为未来能力。
- 重新盘点 `T02 Slash Command / TUI`、`B01 私有测试集 v0`、三条 T09 Context 欠账及其它被 T09-1 实际改变的条目；完全回补则删除、部分改变则更新、仍成立则保留、用户取消则删除且不转登记。
- 删除不可达分支、重复导出、兼容 alias/wrapper；确认没有第四种 Timeline record、持久 Compact FSM、独立 compaction model 或无调用方抽象。

## 非功能要求

- Core 不依赖 filesystem、network、Provider SDK、Application、Integration 或 Interface；SDK 类型截止在 Integration。
- Interface 只调用 Application；Headless 不依赖 TUI。
- reduction 与 persistence 按完整语义边界工作，ToolCall/ToolResult 不可拆。
- 未知 durability fail closed；无法确认副作用时不盲目重试。
- Context、diagnostics、Event、Journal、Snapshot、Eval artifact 不泄露秘密或 raw evidence 正文。
- 必过测试不依赖真实 Provider 网络；capability 使用 fake SDK/client fixture。
- 不新增第三方依赖。

## 设计骨架

```text
user configured input limit? ─┐
reliable provider max input? ─┼─> effective operating input limit (至少一项存在，取更紧者)
provider max output? ─────────┤
provider combined limit? ─────┘   未知维度保持 unknown

final candidate request
  ├─ pressure estimate + allowance ──> Auto Gate
  └─ preflight safety count/estimate
       ├─ input <= effective input limit
       ├─ requested output <= known provider output limit
       └─ input + output reserve <= known combined limit
             ↓
        Hard-safe Provider call / fail closed
```

```text
Transcript raw closed facts ──► HistoryRead
            │
            └──► L4/L5 evidence
                         │
                         ▼
Timeline: Fine / Macro / Active checkpoint
                         │
                         ▼
                 logical model view
```

计数是带来源与 allowance 的安全估计，不是 tokenizer 精确性的虚假承诺；Provider overflow 仍是外部最终裁决。Compact attempt、coverage、previous estimate、epoch 与 cancellation 只在当前 Application 调用栈中保存。

## 能力欠账

无新增能力欠账。

本包实现完成后回补 T09 的动态模型限制、生产 tool-free Compaction、small/large-window adaptation 三项既有欠账。原先“维护 bundled official metadata”方案已取消并已从滚动清单移除，后续只确认其持续不存在。T08 还必须重新盘点因 `/compact` 和生产 Compaction 结果变化而部分受影响的 `T02 Slash Command / TUI`、`B01 私有测试集 v0` 等条目；只有实现完成、对应 Checklist 完成且 Feedback 有真实验收记录，才删除已完全回补部分，部分改变的记录必须改写而不是整条误删。

## Out of Scope

- bundled model metadata、本地 Model Catalog、硬编码模型默认窗口、自动模型发现 UI。
- Memory、Embedding、Vector/semantic retrieval、跨 Session retrieval。
- active/paused Run/Turn、Pending Tool、Permission、Provider coroutine 的跨进程恢复。
- 独立 Compaction Model、跨 Provider fallback、后台 Context Agent、Job Scheduler、持久 Compact FSM。
- Timeline physical GC、Artifact Store 生命周期与 GC。
- Subagent、Multi-Agent、Worktree。
- Provider-specific server-side context editing 进入 Core。
- old Session migration、dual read/write、compatibility alias。
- Permission、Plan/Todo、Runtime Hook、TUI rendering 与其它命令的非必要重构。

## 验收标准

1. 用户配置与可靠 Provider metadata 是唯一模型限制来源；无 bundled metadata 或固定 fallback。
2. 用户未配置且 Provider 无可靠 input limit 时 fail closed；项目不能补造或放大用户 `context_window`。
3. input、output、combined limits 分维表达和校验，unknown 不伪造、不折叠为单一 `E`。
4. Pressure Estimate 与 Preflight Safety Count/Estimate 分层；近似计数带集中 allowance，不宣称数学精确。
5. 每个 ordinary/L4/L5/manual/retry 调用均在发送前通过最终请求 Hard Gate；protected facts 自身超限时 Provider call count 为 0。
6. T01 独立接通正式请求链和 L1-L3，删除固定 258K authority；T02 独立完成所有 History/Session 生产调用方硬切。
7. L4/L5 tool-free、bounded、复用冻结主模型；catch-up 多 epoch、checkpoint-last、每批 rebuild/re-gate，无持久 FSM。
8. L5 从 raw Transcript 取证；HistoryRead 只允许 current Session exact bounded read。
9. fresh Session 使用 v2；old v1 incompatible，无迁移、双轨或 Projection 兼容层。
10. closed facts 在 request preparation 与 terminal 边界增量 durable；不持久化 open continuation。
11. manual compact 低 pressure 可执行、无候选 success no-op；ordinary overflow 只允许一次 bounded retry。
12. 已存在的 sync/awaitable preparer/overflow 合同仅被复用，无重复协议或无必要 `core/agent.py` 改造。
13. diagnostics/Eval 不泄露正文或秘密，不建立总分。
14. CLI、TUI、Headless、resume、Permission、Plan/Todo、Hook、架构测试和全量回归通过。
15. 生产路径中旧 authority、旧 Session writer、bundled metadata、第四种 Timeline record 与无调用方抽象为零。
